"""End-to-end tests for bot.partner_selection against a real Postgres (see
tests/conftest.py -- skipped cleanly when TEST_DATABASE_URL is unset):
whole-name search over the `players` table, the disambiguation label
queries (including the same-name-same-ranking-list case CLAUDE.md calls
out explicitly), and each of the six pre-invitation checks. All
pzt_ids/names below are invented; CLAUDE.md forbids real scraped player
data from ever entering git.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy.ext.asyncio import AsyncSession

from bot.partner_selection import (
    CheckFailure,
    build_candidate_options,
    find_matching_players,
    handle_partner_candidate,
    run_pre_invitation_checks,
    start_partner_selection,
)
from bot.states import TournamentSearch
from db import crud
from db.models import Account, AgeCategory, Event, Gender, Invitation, InvitationState, Player, PlayType, Ranking, RankingList, Tournament

_NOW = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)


def _tournament(guid: str = "t1", age_category: AgeCategory = AgeCategory.MLODZICY) -> Tournament:
    return Tournament(
        guid=guid,
        name=f"Turniej testowy {guid}",
        type_prefix="OTK",
        age_category=age_category,
        ranga=3,
        date_from=date(2026, 8, 20),
        date_to=date(2026, 8, 20),
        wojewodztwo="testowe",
        venue_address=None,
        venue_city="Testowo",
        entry_deadline=None,
        withdrawal_deadline=None,
        search_closes_at=_NOW + timedelta(days=1),
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
    session: AsyncSession,
    pzt_id: str,
    full_name: str,
    gender: Gender = Gender.GIRLS,
    age_category: AgeCategory = AgeCategory.MLODZICY,
) -> None:
    session.add(Player(pzt_id=pzt_id, full_name=full_name, club=None, age_category=age_category, gender=gender))
    await session.flush()


async def _add_account(session: AsyncSession, telegram_id: int, pzt_id: str, full_name: str, gender_code: str) -> None:
    session.add(Account(telegram_id=telegram_id, pzt_id=pzt_id, full_name=full_name, gender=gender_code))
    await session.flush()


def _add_invitation(
    session: AsyncSession,
    inviter_pzt_id: str,
    invitee_pzt_id: str,
    tournament_guid: str,
    event_id: int,
    state: InvitationState,
) -> None:
    session.add(
        Invitation(
            inviter_pzt_id=inviter_pzt_id,
            invitee_pzt_id=invitee_pzt_id,
            tournament_guid=tournament_guid,
            event_id=event_id,
            state=state,
            expires_at=_NOW + timedelta(days=1),
        )
    )


def _make_message() -> MagicMock:
    message = MagicMock()
    message.answer = AsyncMock()
    return message


def _make_state(telegram_id: int) -> FSMContext:
    key = StorageKey(bot_id=1, chat_id=telegram_id, user_id=telegram_id)
    return FSMContext(storage=MemoryStorage(), key=key)


# --- find_matching_players ---------------------------------------------------


async def test_find_matching_players_whole_name_both_orders(db_session: AsyncSession):
    await _add_player(db_session, "INV040", "Szewczyk Jagoda", gender=Gender.GIRLS)
    await _add_player(db_session, "INV041", "Kowalski Jan", gender=Gender.BOYS)

    matches = await find_matching_players(db_session, ["Jagoda", "Szewczyk"])

    assert [p.pzt_id for p in matches] == ["INV040"]


async def test_find_matching_players_no_substring_match(db_session: AsyncSession):
    await _add_player(db_session, "INV041", "Kowalski Jan", gender=Gender.BOYS)

    matches = await find_matching_players(db_session, ["Kow", "Jan"])

    assert matches == []


# --- disambiguation candidate labelling --------------------------------------


async def test_disambiguation_same_name_same_ranking_list_uses_position(db_session: AsyncSession):
    # CLAUDE.md, "Disambiguation": two distinct players share both name and
    # ranking list, so age category alone can't separate them -- position
    # must.
    await _add_player(db_session, "INV010", "Nowak Maja", gender=Gender.GIRLS)
    await _add_player(db_session, "INV011", "Nowak Maja", gender=Gender.GIRLS)
    db_session.add(Ranking(player_pzt_id="INV010", ranking_list=RankingList.W14, year=2026, month=8, position=34))
    db_session.add(Ranking(player_pzt_id="INV011", ranking_list=RankingList.W14, year=2026, month=8, position=112))
    await db_session.flush()

    candidates = [
        await crud.get_player_by_pzt_id(db_session, "INV010"),
        await crud.get_player_by_pzt_id(db_session, "INV011"),
    ]
    options = await build_candidate_options(db_session, candidates, AgeCategory.MLODZICY, "pl")
    labels = {option.pzt_id: option.label for option in options}

    assert labels["INV010"] == "Nowak Maja — W14, poz. 34"
    assert labels["INV011"] == "Nowak Maja — W14, poz. 112"


async def test_disambiguation_falls_back_to_players_own_list(db_session: AsyncSession):
    # INV020 has a row in the tournament's own category (W14); INV021 only
    # has a row for a category they play up into (W16) -- CLAUDE.md: "if
    # the player has no row in that list, use any row they do have and
    # label it with its own list code."
    await _add_player(db_session, "INV020", "Kowalska Zofia", gender=Gender.GIRLS)
    await _add_player(db_session, "INV021", "Kowalska Zofia", gender=Gender.GIRLS)
    db_session.add(Ranking(player_pzt_id="INV020", ranking_list=RankingList.W14, year=2026, month=8, position=5))
    db_session.add(Ranking(player_pzt_id="INV021", ranking_list=RankingList.W16, year=2026, month=8, position=9))
    await db_session.flush()

    candidates = [
        await crud.get_player_by_pzt_id(db_session, "INV020"),
        await crud.get_player_by_pzt_id(db_session, "INV021"),
    ]
    options = await build_candidate_options(db_session, candidates, AgeCategory.MLODZICY, "pl")
    labels = {option.pzt_id: option.label for option in options}

    assert labels["INV020"] == "Kowalska Zofia — W14, poz. 5"
    assert labels["INV021"] == "Kowalska Zofia — W16, poz. 9"


async def test_disambiguation_candidate_with_no_ranking_row_shown_without_dropping(db_session: AsyncSession):
    # CLAUDE.md: "If a candidate has no ranking row at all, show them with
    # no position rather than dropping them."
    await _add_player(db_session, "INV030", "Wisniewski Adam", gender=Gender.BOYS)
    await _add_player(db_session, "INV031", "Wisniewski Adam", gender=Gender.BOYS)
    db_session.add(Ranking(player_pzt_id="INV030", ranking_list=RankingList.M14, year=2026, month=8, position=20))
    await db_session.flush()

    candidates = [
        await crud.get_player_by_pzt_id(db_session, "INV030"),
        await crud.get_player_by_pzt_id(db_session, "INV031"),
    ]
    options = await build_candidate_options(db_session, candidates, AgeCategory.MLODZICY, "pl")
    labels = {option.pzt_id: option.label for option in options}

    assert labels["INV030"] == "Wisniewski Adam — M14, poz. 20"
    assert labels["INV031"] == "Wisniewski Adam — brak rankingu w bazie"


# --- the six pre-invitation checks -------------------------------------------


async def test_check_1_self_invite_is_refused(db_session: AsyncSession):
    tournament = _tournament()
    db_session.add(tournament)
    await db_session.flush()
    await _add_event(db_session, tournament.guid, Gender.GIRLS)
    await _add_player(db_session, "INV001", "Testowa Anna", gender=Gender.GIRLS)
    await _add_account(db_session, 2001, "INV001", "Testowa Anna", "W")

    account = await crud.get_account_by_pzt_id(db_session, "INV001")
    candidate = await crud.get_player_by_pzt_id(db_session, "INV001")

    failure = await run_pre_invitation_checks(db_session, account, tournament, candidate)

    assert failure is CheckFailure.SELF_INVITE


async def test_check_2_gender_mismatch_is_refused(db_session: AsyncSession):
    tournament = _tournament()
    db_session.add(tournament)
    await db_session.flush()
    await _add_event(db_session, tournament.guid, Gender.GIRLS)
    await _add_player(db_session, "INV001", "Testowa Anna", gender=Gender.GIRLS)
    await _add_account(db_session, 2001, "INV001", "Testowa Anna", "W")
    await _add_player(db_session, "INV002", "Testowy Piotr", gender=Gender.BOYS)

    account = await crud.get_account_by_pzt_id(db_session, "INV001")
    candidate = await crud.get_player_by_pzt_id(db_session, "INV002")

    failure = await run_pre_invitation_checks(db_session, account, tournament, candidate)

    assert failure is CheckFailure.GENDER_MISMATCH


async def test_check_3_inviter_already_matched_skips_the_name_prompt(db_session: AsyncSession):
    tournament = _tournament()
    db_session.add(tournament)
    await db_session.flush()
    event_id = await _add_event(db_session, tournament.guid, Gender.GIRLS)
    await _add_player(db_session, "INV001", "Testowa Anna", gender=Gender.GIRLS)
    await _add_account(db_session, 2001, "INV001", "Testowa Anna", "W")
    await _add_player(db_session, "INV002", "Testowa Ola", gender=Gender.GIRLS)
    _add_invitation(db_session, "INV001", "INV002", tournament.guid, event_id, InvitationState.ACCEPTED)
    await db_session.flush()

    account = await crud.get_account_by_pzt_id(db_session, "INV001")
    message = _make_message()
    state = _make_state(2001)

    await start_partner_selection(message, state, "pl", db_session, account, tournament)

    assert await state.get_state() == TournamentSearch.waiting_category.state
    texts = [call.args[0] for call in message.answer.call_args_list]
    assert any("Testowa Ola" in text for text in texts)
    # Never dead-ends: a category keyboard is attached to one of the replies.
    assert any(call.kwargs.get("reply_markup") is not None for call in message.answer.call_args_list)


async def test_check_3_finds_partner_regardless_of_which_side_inviter_was(db_session: AsyncSession):
    # The matched invitation may have the account as the *invitee* rather
    # than the inviter -- get_matched_invitation must find it either way.
    tournament = _tournament()
    db_session.add(tournament)
    await db_session.flush()
    event_id = await _add_event(db_session, tournament.guid, Gender.GIRLS)
    await _add_player(db_session, "INV001", "Testowa Anna", gender=Gender.GIRLS)
    await _add_account(db_session, 2001, "INV001", "Testowa Anna", "W")
    await _add_player(db_session, "INV002", "Testowa Ola", gender=Gender.GIRLS)
    _add_invitation(db_session, "INV002", "INV001", tournament.guid, event_id, InvitationState.ACCEPTED)
    await db_session.flush()

    account = await crud.get_account_by_pzt_id(db_session, "INV001")
    message = _make_message()
    state = _make_state(2001)

    await start_partner_selection(message, state, "pl", db_session, account, tournament)

    texts = [call.args[0] for call in message.answer.call_args_list]
    assert any("Testowa Ola" in text for text in texts)


async def test_check_4_invitee_already_matched_does_not_reveal_partner(db_session: AsyncSession):
    tournament = _tournament()
    db_session.add(tournament)
    await db_session.flush()
    event_id = await _add_event(db_session, tournament.guid, Gender.GIRLS)
    await _add_player(db_session, "INV001", "Testowa Anna", gender=Gender.GIRLS)
    await _add_account(db_session, 2001, "INV001", "Testowa Anna", "W")
    await _add_player(db_session, "INV002", "Testowa Ola", gender=Gender.GIRLS)
    await _add_player(db_session, "INV003", "Testowa Ewa", gender=Gender.GIRLS)
    _add_invitation(db_session, "INV002", "INV003", tournament.guid, event_id, InvitationState.ACCEPTED)
    await db_session.flush()

    account = await crud.get_account_by_pzt_id(db_session, "INV001")
    candidate = await crud.get_player_by_pzt_id(db_session, "INV002")

    failure = await run_pre_invitation_checks(db_session, account, tournament, candidate)

    assert failure is CheckFailure.INVITEE_ALREADY_MATCHED


async def test_check_5_pending_invitation_already_sent_is_refused(db_session: AsyncSession):
    tournament = _tournament()
    db_session.add(tournament)
    await db_session.flush()
    event_id = await _add_event(db_session, tournament.guid, Gender.GIRLS)
    await _add_player(db_session, "INV001", "Testowa Anna", gender=Gender.GIRLS)
    await _add_account(db_session, 2001, "INV001", "Testowa Anna", "W")
    await _add_player(db_session, "INV002", "Testowa Ola", gender=Gender.GIRLS)
    _add_invitation(db_session, "INV001", "INV002", tournament.guid, event_id, InvitationState.PENDING)
    await db_session.flush()

    account = await crud.get_account_by_pzt_id(db_session, "INV001")
    candidate = await crud.get_player_by_pzt_id(db_session, "INV002")

    failure = await run_pre_invitation_checks(db_session, account, tournament, candidate)

    assert failure is CheckFailure.PENDING_INVITATION_EXISTS


async def test_check_6_max_pending_invitations_reached_is_refused(db_session: AsyncSession):
    tournament = _tournament()
    db_session.add(tournament)
    await db_session.flush()
    event_id = await _add_event(db_session, tournament.guid, Gender.GIRLS)
    await _add_player(db_session, "INV001", "Testowa Anna", gender=Gender.GIRLS)
    await _add_account(db_session, 2001, "INV001", "Testowa Anna", "W")
    for i in range(3):
        await _add_player(db_session, f"INV10{i}", f"Testowa Osoba{i}", gender=Gender.GIRLS)
        _add_invitation(db_session, "INV001", f"INV10{i}", tournament.guid, event_id, InvitationState.PENDING)
    await _add_player(db_session, "INV999", "Testowa Nowa", gender=Gender.GIRLS)
    await db_session.flush()

    account = await crud.get_account_by_pzt_id(db_session, "INV001")
    candidate = await crud.get_player_by_pzt_id(db_session, "INV999")

    failure = await run_pre_invitation_checks(db_session, account, tournament, candidate)

    assert failure is CheckFailure.MAX_PENDING_REACHED


async def test_all_checks_pass_hands_off_to_step_7_stub(db_session: AsyncSession):
    tournament = _tournament()
    db_session.add(tournament)
    await db_session.flush()
    await _add_event(db_session, tournament.guid, Gender.GIRLS)
    await _add_player(db_session, "INV001", "Testowa Anna", gender=Gender.GIRLS)
    await _add_account(db_session, 2001, "INV001", "Testowa Anna", "W")
    await _add_player(db_session, "INV002", "Testowa Ola", gender=Gender.GIRLS)
    await db_session.flush()

    account = await crud.get_account_by_pzt_id(db_session, "INV001")
    candidate = await crud.get_player_by_pzt_id(db_session, "INV002")
    message = _make_message()
    state = _make_state(2001)

    await handle_partner_candidate(message, state, db_session, "pl", account, tournament, candidate)

    data = await state.get_data()
    assert data["partner_pzt_id"] == "INV002"
    texts = [call.args[0] for call in message.answer.call_args_list]
    assert any("budowie" in text for text in texts)
