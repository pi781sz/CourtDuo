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

import itertools
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from aiogram.exceptions import TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy.ext.asyncio import AsyncSession

from bot.handlers.invitations import (
    handle_accept,
    handle_cancel,
    handle_confirm_send,
    handle_not_attending,
    handle_reject,
)
from bot.invitation_engine import send_invitation
from bot.keyboards.invitations import (
    AcceptInvitationCallback,
    CancelInvitationCallback,
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
    bot. Each accepted push gets its own incrementing message_id, the same
    shape a real Telegram Message carries -- CLAUDE.md step 8.6 stores it
    on the invitation (invitations.invitee_message_id) so a later cancel
    can find the message again."""
    blocked = fail_for or set()
    bot = MagicMock()
    message_ids = itertools.count(1)

    async def send_message(chat_id, text, reply_markup=None):
        if chat_id in blocked:
            raise TelegramForbiddenError(method=MagicMock(), message="bot was blocked by the user")
        return MagicMock(message_id=next(message_ids))

    bot.send_message = AsyncMock(side_effect=send_message)
    bot.edit_message_reply_markup = AsyncMock()
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


def _button_texts(markup) -> list[str]:
    return [button.text for row in markup.inline_keyboard for button in row]


def _answer_markups(callback: MagicMock) -> list:
    return [call.kwargs.get("reply_markup") for call in callback.message.answer.call_args_list]


def _push_markups(bot: MagicMock) -> dict[int, list]:
    markups: dict[int, list] = {}
    for call in bot.send_message.call_args_list:
        chat_id = call.args[0] if call.args else call.kwargs["chat_id"]
        markups.setdefault(chat_id, []).append(call.kwargs.get("reply_markup"))
    return markups


def _is_persistent_menu(markup) -> bool:
    """CLAUDE.md step 8.5: every plain-text reply an invitee or inviter
    gets from the invitation flow -- an answer to their own tap, or an
    unprompted push -- carries the persistent reply keyboard, since a
    player answering an invitation may not have been in any conversation
    with the bot beforehand."""
    return (
        markup is not None
        and markup.is_persistent is True
        and markup.resize_keyboard is True
        and [[button.text for button in row] for row in markup.keyboard]
        == [["Znajdź partnera"], ["Moje deble", "Zaproś na CourtDuo"]]
    )


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
    # The invitee is told who is asking, in full and reordered to "Imię
    # Nazwisko" (CLAUDE.md, step 7.1), and warned before they can tap
    # anything (CLAUDE.md).
    assert pushed[8002][0] == (
        f"Anna Testowa zaprasza Cię do gry podwójnej.\n{_LABEL}\n"
        "Uwaga: po akceptacji nie można zmienić partnera."
    )
    # Three buttons and no text entry: Zatwierdź, Odrzuć, Nie jadę na ten
    # turniej -- no emoji, no Menu (CLAUDE.md step 8.4, CHANGE 1 and 3).
    markup = bot.send_message.call_args.kwargs["reply_markup"]
    assert _button_texts(markup) == ["Zatwierdź", "Odrzuć", "Nie jadę na ten turniej"]
    assert _answers(callback) == [f"Zaproszenie zostało wysłane. Czekaj na odpowiedź.\n🟠 Jagoda Testowa — {_LABEL}"]
    # CLAUDE.md step 8.7: belt-and-braces inline [Moje deble] button -- the
    # persistent reply keyboard can be collapsed by the player, so the one
    # screen they've just acted on gets its own way back that can't be.
    sent_markup = _answer_markups(callback)[0]
    assert _button_texts(sent_markup) == ["Moje deble"]
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
        "Nie udało się dostarczyć zaproszenia do Jagoda Testowa. Wpisz imię i nazwisko innej osoby."
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
    assert _answers(callback) == ["Jagoda Testowa ma już partnera na ten turniej.\nWpisz imię i nazwisko innej osoby."]
    assert bot.send_message.await_count == 0


async def test_confirming_send_when_the_invitee_already_invited_meanwhile_is_refused(db_session: AsyncSession):
    # PROBLEM 3 (CLAUDE.md, "Pre-invitation checks"): Jagoda invited Anna a
    # moment after Anna's own pre-invitation checks ran, so the send
    # transaction itself must catch it -- not just bot.partner_selection's
    # pre-check -- and no second invitation must be created.
    await _add_tournament(db_session)
    await _add_user(db_session, "HND080", "Testowa Anna", 8080)
    await _add_user(db_session, "HND081", "Testowa Jagoda", 8081)
    jagoda = await crud.get_account_by_pzt_id(db_session, "HND081")
    anna_player = await crud.get_player_by_pzt_id(db_session, "HND080")
    tournament = await crud.get_tournament_by_guid(db_session, _GUID)
    await send_invitation(db_session, jagoda, tournament, anna_player, _NOW)

    callback = _make_callback(8080)
    bot = _make_bot()
    await handle_confirm_send(callback, await _state_for(8080, _GUID, "HND081"), db_session, bot)

    assert _answers(callback) == [
        "Masz już zaproszenie od Jagoda Testowa na ten turniej. Sprawdź „Moje deble”, aby odpowiedzieć."
    ]
    assert _answer_markups(callback)[0] is None
    assert bot.send_message.await_count == 0
    assert await crud.count_pending_outgoing_invitations(db_session, "HND080", _GUID) == 0
    assert await crud.count_pending_outgoing_invitations(db_session, "HND081", _GUID) == 1


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

    assert _answers(callback) == [f"🟢 Partner: Anna Testowa — {_LABEL}"]
    # CLAUDE.md step 8.4: no inline navigation button any more -- step 8.5:
    # the persistent reply keyboard instead, since this may be the first
    # thing the invitee sees in a while.
    assert _is_persistent_menu(_answer_markups(callback)[0])
    pushed = _pushes(bot)
    # The inviter: the alert, then her own 🟢 status. Feminine verb.
    assert pushed[8030] == [f"Jagoda Testowa przyjęła zaproszenie.\n🟢 Partner: Jagoda Testowa — {_LABEL}"]
    # Both cancelled counterparties, and nobody else.
    assert pushed[8032] == ["Ten zawodnik znalazł już partnera."]
    assert pushed[8033] == ["Ten zawodnik znalazł już partnera."]
    assert set(pushed) == {8030, 8032, 8033}
    # Every one of these is an unprompted push (CLAUDE.md step 8.5): the
    # persistent reply keyboard rides along on all of them.
    push_markups = _push_markups(bot)
    assert all(_is_persistent_menu(markup) for markups in push_markups.values() for markup in markups)


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

    assert _answers(callback) == [f"🟢 Partner: Anna Testowa — {_LABEL}"]
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

    assert _answers(callback) == [f"🔴 Odrzuciłeś zaproszenie od Adam Testowy — {_LABEL}."]
    # CLAUDE.md step 8.4: no inline navigation button any more -- step 8.5:
    # the persistent reply keyboard instead.
    assert _is_persistent_menu(_answer_markups(callback)[0])
    assert _pushes(bot)[8050] == [f"🔴 Marek Testowy odrzucił zaproszenie — {_LABEL}."]
    assert _is_persistent_menu(_push_markups(bot)[8050][0])
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
    assert _is_persistent_menu(_answer_markups(callback)[0])
    # 🔴, same colour as a refusal now (CLAUDE.md step 8.3, PROBLEM 2).
    assert _pushes(bot)[8060] == ["🔴 Jagoda Testowa nie jedzie na ten turniej."]
    assert _is_persistent_menu(_push_markups(bot)[8060][0])
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
    assert _is_persistent_menu(_answer_markups(callback)[0])
    assert (await crud.get_invitation_by_id(db_session, to_ola.id)).state is InvitationState.CANCELLED


# --- cancelling (CLAUDE.md step 8.6) ---------------------------------------------


async def test_cancel_notifies_the_invitee_and_clears_their_original_buttons(db_session: AsyncSession):
    await _add_tournament(db_session)
    await _add_user(db_session, "CNH001", "Testowa Anna", 8100)
    await _add_user(db_session, "CNH002", "Testowa Jagoda", 8101)
    bot = _make_bot()
    await handle_confirm_send(_make_callback(8100), await _state_for(8100, _GUID, "CNH002"), db_session, bot)
    invitation = await crud.get_pending_invitation(db_session, "CNH001", "CNH002", _GUID)
    assert invitation.invitee_message_id is not None

    cancel_callback = _make_callback(8100)
    await handle_cancel(cancel_callback, CancelInvitationCallback(invitation_id=invitation.id), db_session, bot)

    # The inviter's own confirmation, naming the person and the tournament.
    assert _answers(cancel_callback) == [f"Anulowano zaproszenie do Jagoda Testowa — {_LABEL}."]
    assert _is_persistent_menu(_answer_markups(cancel_callback)[0])
    # The invitee is told, feminine verb for Anna (a girl).
    assert _pushes(bot)[8101][-1] == f"Anna Testowa wycofała zaproszenie — {_LABEL}."
    assert (await crud.get_invitation_by_id(db_session, invitation.id)).state is InvitationState.CANCELLED
    # The invitee's original invitation message loses its answer buttons.
    bot.edit_message_reply_markup.assert_awaited_once_with(
        chat_id=8101, message_id=invitation.invitee_message_id, reply_markup=None
    )


async def test_cancel_uses_masculine_verb_for_a_boy_inviter(db_session: AsyncSession):
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
    await _add_user(db_session, "CNH010", "Testowy Adam", 8110, gender=Gender.BOYS)
    await _add_user(db_session, "CNH011", "Testowy Marek", 8111, gender=Gender.BOYS)
    bot = _make_bot()
    await handle_confirm_send(_make_callback(8110), await _state_for(8110, _GUID, "CNH011"), db_session, bot)
    invitation = await crud.get_pending_invitation(db_session, "CNH010", "CNH011", _GUID)

    await handle_cancel(
        _make_callback(8110), CancelInvitationCallback(invitation_id=invitation.id), db_session, bot
    )

    assert _pushes(bot)[8111][-1] == f"Adam Testowy wycofał zaproszenie — {_LABEL}."


async def test_only_the_sender_may_cancel(db_session: AsyncSession):
    await _add_tournament(db_session)
    await _add_user(db_session, "CNH020", "Testowa Anna", 8120)
    await _add_user(db_session, "CNH021", "Testowa Jagoda", 8121)
    tournament = await crud.get_tournament_by_guid(db_session, _GUID)
    anna = await crud.get_account_by_pzt_id(db_session, "CNH020")
    invitation = (
        await send_invitation(db_session, anna, tournament, await crud.get_player_by_pzt_id(db_session, "CNH021"), _NOW)
    ).invitation

    # The invitee taps a spoofed cancel callback for an invitation that
    # isn't theirs to withdraw.
    callback = _make_callback(8121)
    await handle_cancel(callback, CancelInvitationCallback(invitation_id=invitation.id), db_session, _make_bot())

    assert _answers(callback) == ["To zaproszenie jest już nieaktualne."]
    assert (await crud.get_invitation_by_id(db_session, invitation.id)).state is InvitationState.PENDING


async def test_cancelling_an_already_accepted_invitation_fails_and_reports_the_real_outcome(
    db_session: AsyncSession,
):
    await _add_tournament(db_session)
    await _add_user(db_session, "CNH030", "Testowa Anna", 8130)
    await _add_user(db_session, "CNH031", "Testowa Jagoda", 8131)
    tournament = await crud.get_tournament_by_guid(db_session, _GUID)
    anna = await crud.get_account_by_pzt_id(db_session, "CNH030")
    invitation = (
        await send_invitation(db_session, anna, tournament, await crud.get_player_by_pzt_id(db_session, "CNH031"), _NOW)
    ).invitation
    # Jagoda accepts a moment before Anna's cancel tap lands.
    await handle_accept(_make_callback(8131), AcceptInvitationCallback(invitation_id=invitation.id), db_session, _make_bot())

    cancel_callback = _make_callback(8130)
    await handle_cancel(
        cancel_callback, CancelInvitationCallback(invitation_id=invitation.id), db_session, _make_bot()
    )

    assert _answers(cancel_callback) == [
        "Nie można anulować — Jagoda Testowa już zaakceptowała to zaproszenie."
    ]
    # A confirmed match is locked (CLAUDE.md) -- cancel must not touch it.
    assert (await crud.get_invitation_by_id(db_session, invitation.id)).state is InvitationState.ACCEPTED


async def test_after_cancelling_the_inviter_may_re_invite_the_same_person(db_session: AsyncSession):
    await _add_tournament(db_session)
    await _add_user(db_session, "CNH040", "Testowa Anna", 8140)
    await _add_user(db_session, "CNH041", "Testowa Jagoda", 8141)
    tournament = await crud.get_tournament_by_guid(db_session, _GUID)
    anna = await crud.get_account_by_pzt_id(db_session, "CNH040")
    jagoda_player = await crud.get_player_by_pzt_id(db_session, "CNH041")
    invitation = (await send_invitation(db_session, anna, tournament, jagoda_player, _NOW)).invitation

    await handle_cancel(
        _make_callback(8140), CancelInvitationCallback(invitation_id=invitation.id), db_session, _make_bot()
    )

    # Below the 3-pending limit again, and free to re-invite the same person.
    assert await crud.count_pending_outgoing_invitations(db_session, "CNH040", _GUID) == 0
    again = await send_invitation(db_session, anna, tournament, jagoda_player, _NOW)
    assert again.failure is None
