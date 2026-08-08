"""The Telegram side of step 7 against a real Postgres: who gets told
what, and what happens when a message can't be delivered (CLAUDE.md,
"Invitation engine"; build order step 7). Skipped cleanly when
TEST_DATABASE_URL is unset -- see tests/conftest.py.

The engine's own transactions are covered in
tests/test_invitation_engine_db.py; these tests are about the push
messages that follow them, which is where a player can silently end up
knowing nothing. Invented names, telegram ids and pzt_ids only.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from aiogram.exceptions import TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy.ext.asyncio import AsyncSession

from bot.handlers.invitations import (
    handle_accept,
    handle_confirm_send,
    handle_not_attending,
    handle_reject,
)
from bot.invitation_engine import send_invitation
from bot.keyboards.invitations import (
    AcceptInvitationCallback,
    NotAttendingCallback,
    RejectInvitationCallback,
)
from bot.states import InvitationSend, PartnerSelection
from db import crud
from db.models import Account, AgeCategory, Event, Gender, InvitationState, Player, PlayType, Tournament

_NOW = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)
_GUID = "hnd-t1"
_LABEL = "WTK Testowo - 22.08.2026"


async def _add_tournament(session: AsyncSession) -> Tournament:
    tournament = Tournament(
        guid=_GUID,
        name="Turniej testowy",
        type_prefix="WTK",
        age_category=AgeCategory.MLODZICY,
        ranga=5,
        date_from=date(2026, 8, 22),
        date_to=date(2026, 8, 23),
        wojewodztwo="testowe",
        venue_address=None,
        venue_city="Testowo",
        entry_deadline=None,
        withdrawal_deadline=None,
        search_closes_at=_NOW + timedelta(days=15),
    )
    session.add(tournament)
    await session.flush()
    session.add(
        Event(
            tournament_guid=_GUID,
            category_label="Kategoria testowa",
            gender=Gender.GIRLS,
            play_type=PlayType.DOUBLES,
            draw_format=None,
            is_doubles=True,
        )
    )
    await session.flush()
    return tournament


async def _add_user(
    session: AsyncSession, pzt_id: str, full_name: str, telegram_id: int, gender: Gender = Gender.GIRLS
) -> Player:
    player = Player(
        pzt_id=pzt_id, full_name=full_name, club=None, age_category=AgeCategory.MLODZICY, gender=gender
    )
    session.add(player)
    await session.flush()
    session.add(
        Account(
            telegram_id=telegram_id,
            pzt_id=pzt_id,
            full_name=full_name,
            gender="W" if gender is Gender.GIRLS else "M",
        )
    )
    await session.flush()
    return player


def _make_callback(telegram_id: int) -> MagicMock:
    callback = MagicMock()
    callback.from_user.id = telegram_id
    callback.message.edit_reply_markup = AsyncMock()
    callback.message.answer = AsyncMock()
    callback.answer = AsyncMock()
    return callback


def _make_bot(fail_for: set[int] | None = None) -> MagicMock:
    """A bot whose send_message records every push, and refuses the chats
    in `fail_for` exactly as Telegram does for a player who blocked the
    bot."""
    blocked = fail_for or set()
    bot = MagicMock()

    async def send_message(chat_id, text, reply_markup=None):
        if chat_id in blocked:
            raise TelegramForbiddenError(method=MagicMock(), message="bot was blocked by the user")
        return MagicMock()

    bot.send_message = AsyncMock(side_effect=send_message)
    return bot


def _pushes(bot: MagicMock) -> dict[int, list[str]]:
    pushed: dict[int, list[str]] = {}
    for call in bot.send_message.call_args_list:
        chat_id = call.args[0] if call.args else call.kwargs["chat_id"]
        text = call.args[1] if len(call.args) > 1 else call.kwargs["text"]
        pushed.setdefault(chat_id, []).append(text)
    return pushed


def _answers(callback: MagicMock) -> list[str]:
    return [call.args[0] for call in callback.message.answer.call_args_list]


async def _state_for(telegram_id: int, tournament_guid: str, partner_pzt_id: str) -> FSMContext:
    state = FSMContext(storage=MemoryStorage(), key=StorageKey(bot_id=1, chat_id=telegram_id, user_id=telegram_id))
    await state.update_data(
        category=AgeCategory.MLODZICY.name, tournament_guid=tournament_guid, partner_pzt_id=partner_pzt_id
    )
    await state.set_state(InvitationSend.waiting_confirmation)
    return state


# --- sending --------------------------------------------------------------------


async def test_confirming_sends_the_invitation_to_the_invitee(db_session: AsyncSession):
    await _add_tournament(db_session)
    await _add_user(db_session, "HND001", "Testowa Anna", 8001)
    await _add_user(db_session, "HND002", "Testowa Jagoda", 8002)
    callback = _make_callback(8001)
    bot = _make_bot()
    state = await _state_for(8001, _GUID, "HND002")

    await handle_confirm_send(callback, state, db_session, bot)

    pushed = _pushes(bot)
    assert list(pushed) == [8002]
    # The invitee is told who is asking, in full, and warned before they
    # can tap anything (CLAUDE.md).
    assert pushed[8002][0] == (
        f"Testowa Anna zaprasza Cię do gry podwójnej.\n{_LABEL}\n"
        "Uwaga: po akceptacji nie można zmienić partnera."
    )
    # Three buttons and no text entry: Zatwierdź, Odrzuć, Nie jadę.
    markup = bot.send_message.call_args.kwargs["reply_markup"]
    assert [button.text for row in markup.inline_keyboard for button in row] == [
        "Zatwierdź",
        "Odrzuć",
        "Nie jadę na ten turniej",
    ]
    assert _answers(callback) == [f"Zaproszenie zostało wysłane. Czekaj na odpowiedź.\n🟠 Testowa Jagoda — {_LABEL}"]
    assert await crud.count_pending_outgoing_invitations(db_session, "HND001", _GUID) == 1
    # Free to name somebody else straight away, up to three pending.
    assert await state.get_state() == PartnerSelection.waiting_name.state


async def test_an_undeliverable_invitation_is_cancelled_rather_than_left_pending(db_session: AsyncSession):
    # CLAUDE.md: do not leave the inviter waiting on a 🟠 that can never
    # resolve. The invitee here has blocked the bot.
    await _add_tournament(db_session)
    await _add_user(db_session, "HND010", "Testowa Anna", 8010)
    await _add_user(db_session, "HND011", "Testowa Jagoda", 8011)
    callback = _make_callback(8010)
    bot = _make_bot(fail_for={8011})
    state = await _state_for(8010, _GUID, "HND011")

    await handle_confirm_send(callback, state, db_session, bot)

    assert _answers(callback) == [
        "Nie udało się dostarczyć zaproszenia do Testowa Jagoda. Wpisz imię i nazwisko innej osoby."
    ]
    assert await crud.count_pending_outgoing_invitations(db_session, "HND010", _GUID) == 0
    assert await state.get_state() == PartnerSelection.waiting_name.state


async def test_confirming_a_player_who_gained_a_partner_meanwhile_is_refused(db_session: AsyncSession):
    await _add_tournament(db_session)
    await _add_user(db_session, "HND020", "Testowa Anna", 8020)
    await _add_user(db_session, "HND021", "Testowa Jagoda", 8021)
    await _add_user(db_session, "HND022", "Testowa Ola", 8022)
    # Jagoda accepts Ola while Anna is still looking at the confirmation.
    ola = await crud.get_account_by_pzt_id(db_session, "HND022")
    jagoda = await crud.get_player_by_pzt_id(db_session, "HND021")
    tournament = await crud.get_tournament_by_guid(db_session, _GUID)
    other = (await send_invitation(db_session, ola, tournament, jagoda, _NOW)).invitation
    other.state = InvitationState.ACCEPTED
    await db_session.flush()

    callback = _make_callback(8020)
    bot = _make_bot()
    await handle_confirm_send(callback, await _state_for(8020, _GUID, "HND021"), db_session, bot)

    # Never reveals who that partner is (CLAUDE.md) -- and nothing was pushed.
    assert _answers(callback) == ["Testowa Jagoda ma już partnera na ten turniej.\nWpisz imię i nazwisko innej osoby."]
    assert bot.send_message.await_count == 0


# --- answering ------------------------------------------------------------------


async def test_accept_tells_both_sides_and_every_cancelled_player(db_session: AsyncSession):
    await _add_tournament(db_session)
    await _add_user(db_session, "HND030", "Testowa Anna", 8030)
    await _add_user(db_session, "HND031", "Testowa Jagoda", 8031)
    await _add_user(db_session, "HND032", "Testowa Ola", 8032)
    await _add_user(db_session, "HND033", "Testowa Ewa", 8033)
    tournament = await crud.get_tournament_by_guid(db_session, _GUID)
    anna = await crud.get_account_by_pzt_id(db_session, "HND030")
    ewa = await crud.get_account_by_pzt_id(db_session, "HND033")
    chosen = (
        await send_invitation(db_session, anna, tournament, await crud.get_player_by_pzt_id(db_session, "HND031"), _NOW)
    ).invitation
    # Anna's other outgoing invitation, and one Jagoda was holding.
    await send_invitation(db_session, anna, tournament, await crud.get_player_by_pzt_id(db_session, "HND032"), _NOW)
    await send_invitation(db_session, ewa, tournament, await crud.get_player_by_pzt_id(db_session, "HND031"), _NOW)

    callback = _make_callback(8031)
    bot = _make_bot()
    await handle_accept(callback, AcceptInvitationCallback(invitation_id=chosen.id), db_session, bot)

    assert _answers(callback) == [f"🟢 Partner: Testowa Anna — {_LABEL}"]
    pushed = _pushes(bot)
    # The inviter: the alert, then her own 🟢 status. Feminine verb.
    assert pushed[8030] == [f"Testowa Jagoda przyjęła zaproszenie.\n🟢 Partner: Testowa Jagoda — {_LABEL}"]
    # Both cancelled counterparties, and nobody else.
    assert pushed[8032] == ["Ten zawodnik znalazł już partnera."]
    assert pushed[8033] == ["Ten zawodnik znalazł już partnera."]
    assert set(pushed) == {8030, 8032, 8033}


async def test_accept_still_matches_when_the_inviter_has_blocked_the_bot(db_session: AsyncSession):
    # A failed push must not take down the transaction that already
    # decided the match.
    await _add_tournament(db_session)
    await _add_user(db_session, "HND040", "Testowa Anna", 8040)
    await _add_user(db_session, "HND041", "Testowa Jagoda", 8041)
    tournament = await crud.get_tournament_by_guid(db_session, _GUID)
    anna = await crud.get_account_by_pzt_id(db_session, "HND040")
    invitation = (
        await send_invitation(db_session, anna, tournament, await crud.get_player_by_pzt_id(db_session, "HND041"), _NOW)
    ).invitation

    callback = _make_callback(8041)
    await handle_accept(
        callback, AcceptInvitationCallback(invitation_id=invitation.id), db_session, _make_bot(fail_for={8040})
    )

    assert _answers(callback) == [f"🟢 Partner: Testowa Anna — {_LABEL}"]
    assert (await crud.get_invitation_by_id(db_session, invitation.id)).state is InvitationState.ACCEPTED


async def test_reject_tells_the_inviter_with_the_right_verb_for_a_boy(db_session: AsyncSession):
    await _add_tournament(db_session)
    db_session.add(
        Event(
            tournament_guid=_GUID,
            category_label="Kategoria testowa chłopcy",
            gender=Gender.BOYS,
            play_type=PlayType.DOUBLES,
            draw_format=None,
            is_doubles=True,
        )
    )
    await db_session.flush()
    await _add_user(db_session, "HND050", "Testowy Adam", 8050, gender=Gender.BOYS)
    await _add_user(db_session, "HND051", "Testowy Marek", 8051, gender=Gender.BOYS)
    tournament = await crud.get_tournament_by_guid(db_session, _GUID)
    adam = await crud.get_account_by_pzt_id(db_session, "HND050")
    invitation = (
        await send_invitation(db_session, adam, tournament, await crud.get_player_by_pzt_id(db_session, "HND051"), _NOW)
    ).invitation

    callback = _make_callback(8051)
    bot = _make_bot()
    await handle_reject(callback, RejectInvitationCallback(invitation_id=invitation.id), db_session, bot)

    assert _answers(callback) == [f"🔴 Odrzuciłeś zaproszenie od Testowy Adam — {_LABEL}."]
    assert _pushes(bot)[8050] == [f"🔴 Testowy Marek odrzucił zaproszenie — {_LABEL}."]
    assert (await crud.get_invitation_by_id(db_session, invitation.id)).state is InvitationState.REJECTED


async def test_not_attending_tells_the_inviter_something_neutral(db_session: AsyncSession):
    await _add_tournament(db_session)
    await _add_user(db_session, "HND060", "Testowa Anna", 8060)
    await _add_user(db_session, "HND061", "Testowa Jagoda", 8061)
    tournament = await crud.get_tournament_by_guid(db_session, _GUID)
    anna = await crud.get_account_by_pzt_id(db_session, "HND060")
    invitation = (
        await send_invitation(db_session, anna, tournament, await crud.get_player_by_pzt_id(db_session, "HND061"), _NOW)
    ).invitation

    callback = _make_callback(8061)
    bot = _make_bot()
    await handle_not_attending(callback, NotAttendingCallback(invitation_id=invitation.id), db_session, bot)

    assert _answers(callback) == ["Odpowiedziałaś, że nie jedziesz na ten turniej."]
    # ⚪, not 🔴: distinct from a refusal (CLAUDE.md).
    assert _pushes(bot)[8060] == ["⚪ Testowa Jagoda nie jedzie na ten turniej."]
    assert (await crud.get_invitation_by_id(db_session, invitation.id)).state is InvitationState.NOT_ATTENDING


async def test_answering_an_already_cancelled_invitation_says_so_without_changing_it(db_session: AsyncSession):
    await _add_tournament(db_session)
    await _add_user(db_session, "HND070", "Testowa Anna", 8070)
    await _add_user(db_session, "HND071", "Testowa Jagoda", 8071)
    await _add_user(db_session, "HND072", "Testowa Ola", 8072)
    tournament = await crud.get_tournament_by_guid(db_session, _GUID)
    anna = await crud.get_account_by_pzt_id(db_session, "HND070")
    to_jagoda = (
        await send_invitation(db_session, anna, tournament, await crud.get_player_by_pzt_id(db_session, "HND071"), _NOW)
    ).invitation
    to_ola = (
        await send_invitation(db_session, anna, tournament, await crud.get_player_by_pzt_id(db_session, "HND072"), _NOW)
    ).invitation
    await handle_accept(
        _make_callback(8071), AcceptInvitationCallback(invitation_id=to_jagoda.id), db_session, _make_bot()
    )

    callback = _make_callback(8072)
    await handle_accept(callback, AcceptInvitationCallback(invitation_id=to_ola.id), db_session, _make_bot())

    assert _answers(callback) == ["Ten zawodnik znalazł już partnera."]
    assert (await crud.get_invitation_by_id(db_session, to_ola.id)).state is InvitationState.CANCELLED
