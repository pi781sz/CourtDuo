"""The Telegram side of account deletion and match release against a real
Postgres (CLAUDE.md step 12). Skipped cleanly when TEST_DATABASE_URL is
unset -- see tests/conftest.py.

The engine's own transactions are covered in tests/test_account_deletion_db.py;
these tests are about who gets told what and with which buttons, mirroring
tests/test_invitation_handlers_db.py's conventions. Invented names, telegram
ids and pzt_ids only (CLAUDE.md rule 4).
"""

from __future__ import annotations

import itertools
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from bot.handlers.account_deletion import (
    handle_delete_account_confirm,
    handle_delete_account_start,
    handle_release_match_abort,
    handle_release_match_confirm,
    handle_release_match_start,
    handle_usun_konto,
)
from bot.invitation_engine import accept_invitation, send_invitation
from bot.keyboards.invitations import ReleaseMatchConfirmCallback
from db import crud
from db.models import Account, AccountViewer, AgeCategory, Event, Gender, InvitationState, Player, PlayType, Tournament

_NOW = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)
_GUID = "delh-t1"


async def _add_tournament(session: AsyncSession, guid: str = _GUID) -> Tournament:
    tournament = Tournament(
        guid=guid,
        name=f"Turniej testowy {guid}",
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
            tournament_guid=guid,
            category_label="Kategoria testowa",
            gender=Gender.GIRLS,
            play_type=PlayType.DOUBLES,
            draw_format=None,
            is_doubles=True,
        )
    )
    await session.flush()
    return tournament


async def _add_user(session: AsyncSession, pzt_id: str, full_name: str, telegram_id: int) -> Player:
    player = Player(pzt_id=pzt_id, full_name=full_name, club=None, age_category=AgeCategory.MLODZICY, gender=Gender.GIRLS)
    session.add(player)
    await session.flush()
    session.add(Account(telegram_id=telegram_id, pzt_id=pzt_id, full_name=full_name, gender="W"))
    await session.flush()
    return player


def _make_callback(telegram_id: int) -> MagicMock:
    callback = MagicMock()
    callback.from_user.id = telegram_id
    callback.message.edit_reply_markup = AsyncMock()
    callback.message.answer = AsyncMock()
    callback.answer = AsyncMock()
    return callback


def _make_bot() -> MagicMock:
    bot = MagicMock()
    message_ids = itertools.count(1)

    async def send_message(chat_id, text, reply_markup=None):
        return MagicMock(message_id=next(message_ids))

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


async def test_usun_konto_shows_the_explain_screen(db_session: AsyncSession):
    await _add_user(db_session, "DELH001", "Testowa Anna", 8101)
    message = MagicMock()
    message.from_user.id = 8101
    message.answer = AsyncMock()

    await handle_usun_konto(message, db_session)

    text = message.answer.call_args.args[0]
    assert "Usunięcie konta CourtDuo" in text
    assert "Tej operacji nie można cofnąć." in text
    # CLAUDE.md step 12.1, PROBLEM 1: gendered on the confirmed partner
    # (here identical to Anna's own "W" gender per the same-gender
    # eligibility rule), exact wording.
    assert "Partnerka dowie się o usunięciu Twojego konta na CourtDuo i będzie mogła skasować waszą parę ze swoich debli na CourtDuo." in text
    # CLAUDE.md step 12.1, PROBLEM 2: no viewer bullet for an account with
    # no active viewers -- almost every account.
    assert "podglądu" not in text


async def test_usun_konto_shows_the_viewer_bullet_only_when_a_viewer_exists(db_session: AsyncSession):
    await _add_user(db_session, "DELH002", "Testowa Basia", 8102)
    account = await crud.get_account_by_pzt_id(db_session, "DELH002")
    db_session.add(AccountViewer(account_id=account.id, viewer_telegram_id=9999, viewer_display_name="Testowy Rodzic"))
    await db_session.flush()
    message = MagicMock()
    message.from_user.id = 8102
    message.answer = AsyncMock()

    await handle_usun_konto(message, db_session)

    text = message.answer.call_args.args[0]
    assert "Dostęp do podglądu Twojego konta zostanie usunięty." in text


async def test_delete_account_confirm_notifies_partner_and_pending_counterparties(db_session: AsyncSession):
    # Two separate tournaments: "first accept wins" cancels every other
    # PENDING invitation Anna holds at the *same* tournament the moment
    # she's matched there, so a still-open invitation has to live at a
    # different one to survive alongside the confirmed match.
    matched_tournament = await _add_tournament(db_session, guid="delh-t1")
    pending_tournament = await _add_tournament(db_session, guid="delh-t2")
    await _add_user(db_session, "DELH010", "Testowa Anna", 8110)
    await _add_user(db_session, "DELH011", "Testowa Jagoda", 8111)
    await _add_user(db_session, "DELH012", "Testowa Ola", 8112)
    anna = await crud.get_account_by_pzt_id(db_session, "DELH010")

    matched = (
        await send_invitation(
            db_session, anna, matched_tournament, await crud.get_player_by_pzt_id(db_session, "DELH011"), _NOW
        )
    ).invitation
    await accept_invitation(db_session, matched.id, "DELH011", _NOW)
    still_pending = (
        await send_invitation(
            db_session, anna, pending_tournament, await crud.get_player_by_pzt_id(db_session, "DELH012"), _NOW
        )
    ).invitation
    await db_session.flush()
    assert still_pending.state is InvitationState.PENDING

    callback = _make_callback(8110)
    bot = _make_bot()

    await handle_delete_account_confirm(callback, db_session, bot)

    assert _answers(callback) == ["Twoje konto zostało usunięte."]
    pushed = _pushes(bot)
    # Jagoda (confirmed partner) is told to confirm in person.
    assert pushed[8111] == [
        "Anna Testowa usunęła swoje konto CourtDuo.\nPotwierdź z nią osobiście, czy nadal gracie razem na tym turnieju."
    ]
    # Ola (still-pending invitee) is told her invitation was cancelled.
    assert pushed[8112] == ["Anna Testowa usunęła swoje konto CourtDuo. Zaproszenie na WTK Testowo - 22.08.2026 zostało anulowane."]
    assert await crud.get_account_by_telegram_id(db_session, 8110) is None


async def test_release_match_flow_frees_the_tournament(db_session: AsyncSession):
    tournament = await _add_tournament(db_session)
    await _add_user(db_session, "DELH020", "Testowa Anna", 8120)
    await _add_user(db_session, "DELH021", "Testowa Jagoda", 8121)
    anna = await crud.get_account_by_pzt_id(db_session, "DELH020")
    matched = (
        await send_invitation(db_session, anna, tournament, await crud.get_player_by_pzt_id(db_session, "DELH021"), _NOW)
    ).invitation
    await accept_invitation(db_session, matched.id, "DELH021", _NOW)
    await db_session.flush()

    delete_callback = _make_callback(8120)
    await handle_delete_account_confirm(delete_callback, db_session, _make_bot())

    start_callback = _make_callback(8121)
    await handle_release_match_start(start_callback, MagicMock(invitation_id=matched.id), db_session)
    # CLAUDE.md step 12.1, PROBLEM 5: exact wording, no gendered verb.
    assert _answers(start_callback)[0] == "Czy na pewno chcesz usunąć tego debla?"

    abort_callback = _make_callback(8121)
    await handle_release_match_abort(abort_callback, db_session)
    assert _answers(abort_callback)[0] == "Anulowane"
    assert (await crud.get_invitation_by_id(db_session, matched.id)).state is InvitationState.ACCEPTED

    confirm_callback = _make_callback(8121)
    bot = _make_bot()
    await handle_release_match_confirm(
        confirm_callback, ReleaseMatchConfirmCallback(invitation_id=matched.id), db_session, bot
    )

    assert _answers(confirm_callback) == [
        "Zwolniłaś parę na turnieju WTK Testowo - 22.08.2026. Możesz teraz zaprosić inną osobę."
    ]
    assert await crud.get_matched_invitation(db_session, "DELH021", tournament.guid) is None
