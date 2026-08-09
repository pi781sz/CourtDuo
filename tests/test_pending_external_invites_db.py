"""CLAUDE.md scenario 2, build order step 9: storing an invitation attempt
against a named player who has no CourtDuo account yet (PART 1), and
notifying every inviter still owed one once that player registers (PART
2). Needs a real Postgres -- see tests/conftest.py, skipped cleanly when
TEST_DATABASE_URL is unset. Invented telegram ids/names/pzt_ids only.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.handlers.pending_external_invites import handle_send_pending_external_invite
from bot.handlers.start import handle_pzt_id
from bot.keyboards.pending_external_invites import SendPendingExternalInviteCallback
from bot.partner_selection import handle_partner_candidate
from bot.pending_external_invites import notify_pending_external_invites
from bot.states import InvitationSend, Registration
from db import crud
from db.models import (
    Account,
    AgeCategory,
    Event,
    Gender,
    Invitation,
    InvitationState,
    Player,
    PendingExternalInvite,
    PlayType,
    Ranking,
    RankingList,
    Tournament,
)

_NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)


def _tournament(guid: str = "pei-t1", search_closes_at: datetime | None = None, date_from: date | None = None) -> Tournament:
    return Tournament(
        guid=guid,
        name=f"Turniej testowy {guid}",
        type_prefix="OTK",
        age_category=AgeCategory.MLODZICY,
        ranga=3,
        date_from=date_from or date(2026, 8, 20),
        date_to=date_from or date(2026, 8, 20),
        wojewodztwo="testowe",
        venue_address=None,
        venue_city="Testowo",
        entry_deadline=None,
        withdrawal_deadline=None,
        search_closes_at=search_closes_at if search_closes_at is not None else _NOW + timedelta(days=1),
    )


async def _add_event(session: AsyncSession, tournament_guid: str, gender: Gender) -> int:
    event = Event(
        tournament_guid=tournament_guid,
        category_label="Kategoria testowa",
        gender=gender,
        play_type=PlayType.DOUBLES,
        draw_format=None,
        is_doubles=True,
    )
    session.add(event)
    await session.flush()
    return event.id


async def _add_player(
    session: AsyncSession, pzt_id: str, full_name: str, gender: Gender = Gender.GIRLS
) -> Player:
    player = Player(pzt_id=pzt_id, full_name=full_name, club=None, age_category=AgeCategory.MLODZICY, gender=gender)
    session.add(player)
    await session.flush()
    return player


async def _add_account(session: AsyncSession, telegram_id: int, pzt_id: str, full_name: str, gender_code: str) -> Account:
    account = Account(telegram_id=telegram_id, pzt_id=pzt_id, full_name=full_name, gender=gender_code)
    session.add(account)
    await session.flush()
    return account


def _make_message() -> MagicMock:
    message = MagicMock()
    message.answer = AsyncMock()
    return message


def _make_state(telegram_id: int) -> FSMContext:
    key = StorageKey(bot_id=1, chat_id=telegram_id, user_id=telegram_id)
    return FSMContext(storage=MemoryStorage(), key=key)


def _make_bot() -> MagicMock:
    bot = MagicMock()
    bot.get_me = AsyncMock(return_value=MagicMock(username="courtduo_test_bot"))
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    return bot


async def _all_pending(session: AsyncSession) -> list[PendingExternalInvite]:
    result = await session.execute(select(PendingExternalInvite))
    return list(result.scalars().all())


# --- PART 1: storing the attempt ---------------------------------------------


async def test_naming_a_player_with_no_account_stores_a_pending_external_invite(db_session: AsyncSession):
    tournament = _tournament()
    db_session.add(tournament)
    await db_session.flush()
    await _add_event(db_session, tournament.guid, Gender.GIRLS)
    await _add_player(db_session, "PEI001", "Testowa Anna", gender=Gender.GIRLS)
    await _add_account(db_session, 3001, "PEI001", "Testowa Anna", "W")
    await _add_player(db_session, "PEI002", "Testowa Ola", gender=Gender.GIRLS)

    account = await crud.get_account_by_pzt_id(db_session, "PEI001")
    candidate = await crud.get_player_by_pzt_id(db_session, "PEI002")
    message = _make_message()
    state = _make_state(3001)

    await handle_partner_candidate(message, state, db_session, "pl", account, tournament, candidate, _make_bot())

    rows = await _all_pending(db_session)
    assert len(rows) == 1
    assert rows[0].inviter_pzt_id == "PEI001"
    assert rows[0].invitee_pzt_id == "PEI002"
    assert rows[0].tournament_guid == tournament.guid


async def test_showing_the_message_twice_does_not_duplicate_the_row(db_session: AsyncSession):
    tournament = _tournament()
    db_session.add(tournament)
    await db_session.flush()
    await _add_event(db_session, tournament.guid, Gender.GIRLS)
    await _add_player(db_session, "PEI003", "Testowa Anna", gender=Gender.GIRLS)
    await _add_account(db_session, 3002, "PEI003", "Testowa Anna", "W")
    await _add_player(db_session, "PEI004", "Testowa Ola", gender=Gender.GIRLS)

    account = await crud.get_account_by_pzt_id(db_session, "PEI003")
    candidate = await crud.get_player_by_pzt_id(db_session, "PEI004")
    state = _make_state(3002)

    await handle_partner_candidate(
        _make_message(), state, db_session, "pl", account, tournament, candidate, _make_bot()
    )
    await handle_partner_candidate(
        _make_message(), state, db_session, "pl", account, tournament, candidate, _make_bot()
    )

    rows = await _all_pending(db_session)
    assert len(rows) == 1


async def test_a_failed_pre_invitation_check_stores_nothing(db_session: AsyncSession):
    # CLAUDE.md step 9, PART 1: "Only store the attempt if the invitation
    # would actually have been valid." A gender mismatch must never reach
    # send_not_on_courtduo_response at all.
    tournament = _tournament()
    db_session.add(tournament)
    await db_session.flush()
    await _add_event(db_session, tournament.guid, Gender.GIRLS)
    await _add_player(db_session, "PEI005", "Testowa Anna", gender=Gender.GIRLS)
    await _add_account(db_session, 3003, "PEI005", "Testowa Anna", "W")
    await _add_player(db_session, "PEI006", "Testowy Piotr", gender=Gender.BOYS)

    account = await crud.get_account_by_pzt_id(db_session, "PEI005")
    candidate = await crud.get_player_by_pzt_id(db_session, "PEI006")
    message = _make_message()
    state = _make_state(3003)

    await handle_partner_candidate(message, state, db_session, "pl", account, tournament, candidate, _make_bot())

    assert await _all_pending(db_session) == []


# --- crud helpers -------------------------------------------------------------


def test_tournament_search_still_open_true_within_window_and_open():
    tournament = _tournament(search_closes_at=_NOW + timedelta(days=1), date_from=date(2026, 8, 20))
    today = date(2026, 8, 9)
    assert crud.tournament_search_still_open(tournament, today, _NOW) is True


def test_tournament_search_still_open_false_past_the_window():
    tournament = _tournament(search_closes_at=_NOW + timedelta(days=1), date_from=date(2026, 8, 20))
    today = date(2026, 9, 20)
    assert crud.tournament_search_still_open(tournament, today, _NOW) is False


def test_tournament_search_still_open_false_when_search_closed():
    tournament = _tournament(search_closes_at=_NOW - timedelta(hours=1), date_from=date(2026, 8, 20))
    today = date(2026, 8, 9)
    assert crud.tournament_search_still_open(tournament, today, _NOW) is False


# --- PART 2: notifying the inviter --------------------------------------------


async def test_notify_pushes_the_inviter_when_still_eligible(db_session: AsyncSession):
    tournament = _tournament(guid="pei-t2")
    db_session.add(tournament)
    await db_session.flush()
    await _add_event(db_session, tournament.guid, Gender.GIRLS)
    await _add_player(db_session, "PEI010", "Testowa Anna", gender=Gender.GIRLS)
    await _add_account(db_session, 3010, "PEI010", "Testowa Anna", "W")
    new_player = await _add_player(db_session, "PEI011", "Testowa Ola", gender=Gender.GIRLS)
    await crud.create_pending_external_invite_if_missing(db_session, "PEI010", "PEI011", tournament.guid)
    await db_session.flush()

    bot = _make_bot()
    await notify_pending_external_invites(db_session, bot, new_player)

    bot.send_message.assert_awaited_once()
    call = bot.send_message.call_args
    chat_id = call.args[0] if call.args else call.kwargs["chat_id"]
    text = call.args[1] if len(call.args) > 1 else call.kwargs["text"]
    assert chat_id == 3010
    assert "Ola Testowa" in text
    assert "dołączyła do CourtDuo" in text
    markup = call.kwargs["reply_markup"]
    buttons = [button for row in markup.inline_keyboard for button in row]
    assert [button.text for button in buttons] == ["Wyślij zaproszenie"]

    # Consumed: nothing left to process again.
    assert await _all_pending(db_session) == []


async def test_notify_gendered_on_the_new_players_own_gender_boy(db_session: AsyncSession):
    tournament = _tournament(guid="pei-t3")
    db_session.add(tournament)
    await db_session.flush()
    await _add_event(db_session, tournament.guid, Gender.BOYS)
    await _add_player(db_session, "PEI012", "Testowy Adam", gender=Gender.BOYS)
    await _add_account(db_session, 3011, "PEI012", "Testowy Adam", "M")
    new_player = await _add_player(db_session, "PEI013", "Testowy Marek", gender=Gender.BOYS)
    await crud.create_pending_external_invite_if_missing(db_session, "PEI012", "PEI013", tournament.guid)
    await db_session.flush()

    bot = _make_bot()
    await notify_pending_external_invites(db_session, bot, new_player)

    text = bot.send_message.call_args.args[1]
    assert "dołączył do CourtDuo" in text
    assert "Marek Testowy" in text


async def test_notify_skips_when_window_has_passed(db_session: AsyncSession):
    # Well past ELIGIBILITY_WINDOW_DAYS (28) from "today" -- notify_pending_external_invites
    # reads the real wall clock, so this must be robust to whenever the
    # suite actually runs, not just relative to _NOW.
    far_future = (datetime.now(timezone.utc) + timedelta(days=crud.ELIGIBILITY_WINDOW_DAYS + 30)).date()
    tournament = _tournament(guid="pei-t4", date_from=far_future, search_closes_at=_NOW + timedelta(days=365))
    db_session.add(tournament)
    await db_session.flush()
    await _add_event(db_session, tournament.guid, Gender.GIRLS)
    await _add_player(db_session, "PEI014", "Testowa Anna", gender=Gender.GIRLS)
    await _add_account(db_session, 3012, "PEI014", "Testowa Anna", "W")
    new_player = await _add_player(db_session, "PEI015", "Testowa Ola", gender=Gender.GIRLS)
    await crud.create_pending_external_invite_if_missing(db_session, "PEI014", "PEI015", tournament.guid)
    await db_session.flush()

    bot = _make_bot()
    await notify_pending_external_invites(db_session, bot, new_player)

    bot.send_message.assert_not_awaited()
    # Still consumed -- it can never become eligible again.
    assert await _all_pending(db_session) == []


async def test_notify_skips_when_search_closed(db_session: AsyncSession):
    tournament = _tournament(guid="pei-t5", search_closes_at=_NOW - timedelta(hours=1))
    db_session.add(tournament)
    await db_session.flush()
    await _add_event(db_session, tournament.guid, Gender.GIRLS)
    await _add_player(db_session, "PEI016", "Testowa Anna", gender=Gender.GIRLS)
    await _add_account(db_session, 3013, "PEI016", "Testowa Anna", "W")
    new_player = await _add_player(db_session, "PEI017", "Testowa Ola", gender=Gender.GIRLS)
    await crud.create_pending_external_invite_if_missing(db_session, "PEI016", "PEI017", tournament.guid)
    await db_session.flush()

    bot = _make_bot()
    await notify_pending_external_invites(db_session, bot, new_player)

    bot.send_message.assert_not_awaited()
    assert await _all_pending(db_session) == []


async def test_notify_skips_when_inviter_already_matched_elsewhere(db_session: AsyncSession):
    tournament = _tournament(guid="pei-t6")
    db_session.add(tournament)
    await db_session.flush()
    event_id = await _add_event(db_session, tournament.guid, Gender.GIRLS)
    await _add_player(db_session, "PEI018", "Testowa Anna", gender=Gender.GIRLS)
    await _add_account(db_session, 3014, "PEI018", "Testowa Anna", "W")
    await _add_player(db_session, "PEI019", "Testowa Ewa", gender=Gender.GIRLS)
    await _add_account(db_session, 3015, "PEI019", "Testowa Ewa", "W")
    new_player = await _add_player(db_session, "PEI020", "Testowa Ola", gender=Gender.GIRLS)
    await crud.create_pending_external_invite_if_missing(db_session, "PEI018", "PEI020", tournament.guid)
    db_session.add(
        Invitation(
            inviter_pzt_id="PEI018",
            invitee_pzt_id="PEI019",
            tournament_guid=tournament.guid,
            event_id=event_id,
            state=InvitationState.ACCEPTED,
            expires_at=_NOW + timedelta(days=1),
        )
    )
    await db_session.flush()

    bot = _make_bot()
    await notify_pending_external_invites(db_session, bot, new_player)

    bot.send_message.assert_not_awaited()
    assert await _all_pending(db_session) == []


async def test_notify_processes_several_rows_independently(db_session: AsyncSession):
    eligible_tournament = _tournament(guid="pei-t7a")
    ineligible_tournament = _tournament(guid="pei-t7b", search_closes_at=_NOW - timedelta(hours=1))
    db_session.add_all([eligible_tournament, ineligible_tournament])
    await db_session.flush()
    await _add_event(db_session, eligible_tournament.guid, Gender.GIRLS)
    await _add_event(db_session, ineligible_tournament.guid, Gender.GIRLS)
    await _add_player(db_session, "PEI021", "Testowa Anna", gender=Gender.GIRLS)
    await _add_account(db_session, 3016, "PEI021", "Testowa Anna", "W")
    await _add_player(db_session, "PEI022", "Testowa Ewa", gender=Gender.GIRLS)
    await _add_account(db_session, 3017, "PEI022", "Testowa Ewa", "W")
    new_player = await _add_player(db_session, "PEI023", "Testowa Ola", gender=Gender.GIRLS)
    await crud.create_pending_external_invite_if_missing(db_session, "PEI021", "PEI023", eligible_tournament.guid)
    await crud.create_pending_external_invite_if_missing(db_session, "PEI022", "PEI023", ineligible_tournament.guid)
    await db_session.flush()

    bot = _make_bot()
    await notify_pending_external_invites(db_session, bot, new_player)

    assert bot.send_message.await_count == 1
    chat_id = bot.send_message.call_args.args[0]
    assert chat_id == 3016
    assert await _all_pending(db_session) == []


# --- The offer button's handler -----------------------------------------------


async def test_tapping_the_offer_button_leads_to_the_confirmation_screen(db_session: AsyncSession):
    tournament = _tournament(guid="pei-t8")
    db_session.add(tournament)
    await db_session.flush()
    await _add_event(db_session, tournament.guid, Gender.GIRLS)
    await _add_player(db_session, "PEI030", "Testowa Anna", gender=Gender.GIRLS)
    await _add_account(db_session, 3018, "PEI030", "Testowa Anna", "W")
    await _add_player(db_session, "PEI031", "Testowa Ola", gender=Gender.GIRLS)
    await _add_account(db_session, 3019, "PEI031", "Testowa Ola", "W")
    await db_session.flush()

    callback = MagicMock()
    callback.from_user.id = 3018
    callback.message = _make_message()
    callback.message.edit_reply_markup = AsyncMock()
    callback.answer = AsyncMock()
    callback_data = SendPendingExternalInviteCallback(tournament_guid=tournament.guid, invitee_pzt_id="PEI031")
    state = _make_state(3018)

    await handle_send_pending_external_invite(callback, callback_data, state, db_session, _make_bot())

    data = await state.get_data()
    assert data["tournament_guid"] == tournament.guid
    assert data["partner_pzt_id"] == "PEI031"
    assert await state.get_state() == InvitationSend.waiting_confirmation.state
    text = callback.message.answer.call_args.args[0]
    assert text.startswith("Zaproszenie do: Ola Testowa")


async def test_registration_end_to_end_notifies_the_waiting_inviter(db_session: AsyncSession):
    # Full loop: Adam names Ola while she has no account (PART 1 stores the
    # row), then Ola registers via /start's own handler (PART 2 fires from
    # there without any extra wiring).
    tournament = _tournament(guid="pei-t9")
    db_session.add(tournament)
    await db_session.flush()
    await _add_event(db_session, tournament.guid, Gender.GIRLS)
    await _add_player(db_session, "PEI040", "Testowa Anna", gender=Gender.GIRLS)
    await _add_account(db_session, 3021, "PEI040", "Testowa Anna", "W")
    await _add_player(db_session, "PEI041", "Testowa Ola", gender=Gender.GIRLS)

    account = await crud.get_account_by_pzt_id(db_session, "PEI040")
    candidate = await crud.get_player_by_pzt_id(db_session, "PEI041")
    await handle_partner_candidate(
        _make_message(), _make_state(3021), db_session, "pl", account, tournament, candidate, _make_bot()
    )
    assert len(await _all_pending(db_session)) == 1

    # Ola now registers for real.
    db_session.add(Ranking(player_pzt_id="PEI041", ranking_list=RankingList.W14, year=2026, month=8, position=1))
    await db_session.flush()

    message = _make_message()
    message.from_user.id = 4001
    message.text = "PEI041"
    state = _make_state(4001)
    await state.set_state(Registration.waiting_pzt_id)
    bot = _make_bot()

    await handle_pzt_id(message, state, db_session, bot)

    bot.send_message.assert_awaited_once()
    call = bot.send_message.call_args
    assert call.args[0] == 3021
    assert "Ola Testowa" in call.args[1]
    assert await _all_pending(db_session) == []


async def test_tapping_the_offer_button_when_tournament_is_gone(db_session: AsyncSession):
    await _add_player(db_session, "PEI032", "Testowa Anna", gender=Gender.GIRLS)
    await _add_account(db_session, 3020, "PEI032", "Testowa Anna", "W")
    await db_session.flush()

    callback = MagicMock()
    callback.from_user.id = 3020
    callback.message = _make_message()
    callback.message.edit_reply_markup = AsyncMock()
    callback.answer = AsyncMock()
    callback_data = SendPendingExternalInviteCallback(tournament_guid="gone-guid", invitee_pzt_id="PEI032")
    state = _make_state(3020)

    await handle_send_pending_external_invite(callback, callback_data, state, db_session, _make_bot())

    text = callback.message.answer.call_args.args[0]
    assert text == "Ten turniej jest już niedostępny."
