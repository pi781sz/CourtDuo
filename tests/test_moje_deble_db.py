"""End-to-end tests for /moje_deble and the "Moje deble" button (CLAUDE.md,
"Moje deble" status view; build order step 8) against a real Postgres --
see tests/conftest.py, skipped cleanly when TEST_DATABASE_URL is unset.

bot.moje_deble's own filtering/grouping/wording rules are unit-tested
without a database in tests/test_moje_deble.py; these tests are about the
things only a real query can prove: db.crud.get_invitations_for_player
returns the right rows with names/tournaments already loaded, the handlers
wire the buttons up, and -- the case most worth a real round trip -- a
third party's own match never leaks into somebody else's view even though
both rows sit in the same `invitations` table.

Invented pzt_ids, telegram ids and names only (CLAUDE.md, "Never commit
scraped player data").
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.handlers.moje_deble import (
    handle_moje_deble_button,
    handle_moje_deble_button_press,
    handle_moje_deble_command,
)
from bot.moje_deble import group_by_tournament, render_groups
from db import crud
from db.models import Account, AgeCategory, Event, Gender, Invitation, InvitationState, Player, PlayType, Tournament

_NOW = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)
_FAR_FUTURE = date(2026, 8, 7) + timedelta(days=400)  # safely "not finished" no matter when this test runs


async def _add_tournament(
    session: AsyncSession, guid: str, date_from: date, date_to: date | None = None, venue_city: str = "Testowo"
) -> Tournament:
    tournament = Tournament(
        guid=guid,
        name=f"Turniej {guid}",
        type_prefix="WTK",
        age_category=AgeCategory.MLODZICY,
        ranga=5,
        date_from=date_from,
        date_to=date_to,
        wojewodztwo="testowe",
        venue_address=None,
        venue_city=venue_city,
        entry_deadline=None,
        withdrawal_deadline=None,
        search_closes_at=_NOW + timedelta(days=200),
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


async def _add_user(session: AsyncSession, pzt_id: str, full_name: str, telegram_id: int | None = None) -> Player:
    player = Player(pzt_id=pzt_id, full_name=full_name, club=None, age_category=AgeCategory.MLODZICY, gender=Gender.GIRLS)
    session.add(player)
    await session.flush()
    if telegram_id is not None:
        session.add(Account(telegram_id=telegram_id, pzt_id=pzt_id, full_name=full_name, gender="W"))
        await session.flush()
    return player


async def _event_id(session: AsyncSession, tournament_guid: str) -> int:
    result = await session.execute(select(Event).where(Event.tournament_guid == tournament_guid))
    return result.scalars().one().id


async def _add_invitation(
    session: AsyncSession,
    inviter_pzt_id: str,
    invitee_pzt_id: str,
    tournament_guid: str,
    state: InvitationState,
    updated_at: datetime = _NOW,
) -> Invitation:
    invitation = Invitation(
        inviter_pzt_id=inviter_pzt_id,
        invitee_pzt_id=invitee_pzt_id,
        tournament_guid=tournament_guid,
        event_id=await _event_id(session, tournament_guid),
        state=state,
        expires_at=_NOW + timedelta(days=200),
    )
    session.add(invitation)
    await session.flush()
    invitation.updated_at = updated_at
    await session.flush()
    return invitation


def _make_message(telegram_id: int) -> MagicMock:
    message = MagicMock()
    message.from_user.id = telegram_id
    message.answer = AsyncMock()
    return message


def _make_callback(telegram_id: int) -> MagicMock:
    callback = MagicMock()
    callback.from_user.id = telegram_id
    callback.message.edit_reply_markup = AsyncMock()
    callback.message.answer = AsyncMock()
    callback.answer = AsyncMock()
    return callback


def _texts(mock: MagicMock) -> list[str]:
    return [call.args[0] for call in mock.answer.call_args_list]


def _markups(mock: MagicMock) -> list:
    return [call.kwargs.get("reply_markup") for call in mock.answer.call_args_list]


def _button_texts(markup) -> list[str]:
    return [button.text for row in markup.inline_keyboard for button in row]


# --- db.crud.get_invitations_for_player ----------------------------------------


async def test_get_invitations_for_player_returns_both_directions_with_names_loaded(db_session: AsyncSession):
    await _add_tournament(db_session, "crud-t1", _FAR_FUTURE)
    await _add_user(db_session, "CRUD001", "Testowa Anna")
    await _add_user(db_session, "CRUD002", "Testowa Jagoda")
    await _add_user(db_session, "CRUD003", "Testowa Ola")
    await _add_invitation(db_session, "CRUD001", "CRUD002", "crud-t1", InvitationState.PENDING)
    await _add_invitation(db_session, "CRUD003", "CRUD001", "crud-t1", InvitationState.REJECTED)
    # Involves neither CRUD001 -- must not come back.
    await _add_invitation(db_session, "CRUD002", "CRUD003", "crud-t1", InvitationState.PENDING)

    invitations = await crud.get_invitations_for_player(db_session, "CRUD001")

    assert len(invitations) == 2
    assert {inv.inviter.full_name for inv in invitations} | {inv.invitee.full_name for inv in invitations} >= {
        "Testowa Anna",
        "Testowa Jagoda",
        "Testowa Ola",
    }
    assert all(inv.tournament.guid == "crud-t1" for inv in invitations)


# --- Full view: wording, ordering, and the CLAUDE.md example shape -------------


async def test_moje_deble_matches_claude_md_layout_and_directions(db_session: AsyncSession):
    await _add_user(db_session, "MDB001", "Testowa Anna", telegram_id=910001)
    await _add_user(db_session, "MDB002", "Testowa Jagoda")
    await _add_user(db_session, "MDB003", "Testowa Maja")
    await _add_user(db_session, "MDB004", "Testowy Bartosz")
    await _add_user(db_session, "MDB005", "Testowa Wiktoria")

    earlier = _FAR_FUTURE
    later = _FAR_FUTURE + timedelta(days=7)
    await _add_tournament(db_session, "mdb-t1", earlier, venue_city="Uniejów")
    await _add_tournament(db_session, "mdb-t2", later, venue_city="Zielona Góra")

    # Tournament 1: matched.
    await _add_invitation(db_session, "MDB001", "MDB002", "mdb-t1", InvitationState.ACCEPTED)

    # Tournament 2: one of each, CLAUDE.md's own example plus a received one.
    await _add_invitation(
        db_session, "MDB001", "MDB003", "mdb-t2", InvitationState.PENDING, updated_at=_NOW + timedelta(hours=1)
    )
    await _add_invitation(
        db_session, "MDB001", "MDB004", "mdb-t2", InvitationState.REJECTED, updated_at=_NOW + timedelta(hours=2)
    )
    await _add_invitation(
        db_session, "MDB001", "MDB005", "mdb-t2", InvitationState.NOT_ATTENDING, updated_at=_NOW + timedelta(hours=3)
    )

    message = _make_message(910001)
    await handle_moje_deble_command(message, db_session)

    texts = _texts(message)
    # No pending *received* invitations anywhere in this scenario
    # (tournament 1 is matched-only, tournament 2 is all sent), so no
    # answer-keyboard follow-ups -- but the one still-open sent invitation
    # (to Maja) gets its own cancel-button follow-up (CLAUDE.md step 8.6).
    assert len(texts) == 2
    lines = texts[0].split("\n")
    # CLAUDE.md step 8.3, PROBLEM 6: a heading as the first line.
    assert lines[0] == "Moje deble"
    assert lines[1] == ""
    assert lines[2] == "WTK Uniejów - " + f"{earlier:%d.%m.%Y}"
    assert lines[3] == "🟢 Jagoda Testowa — gracie razem"
    assert "" in lines[4:]  # blank line separates the two tournament blocks
    assert f"WTK Zielona Góra - {later:%d.%m.%Y}" in lines
    assert "🟠 Maja Testowa — wysłane" in lines
    assert "🔴 Bartosz Testowy — odmowa" in lines
    assert "🔴 Wiktoria Testowa — nie jedzie" in lines

    markup = _markups(message)[0]
    assert _button_texts(markup) == ["Znajdź partnera"]

    # The sent-pending follow-up: the cancel button, not the answer keyboard.
    assert texts[1] == "🟠 Maja Testowa — wysłane"
    assert _button_texts(_markups(message)[1]) == ["Anuluj zaproszenie"]


async def test_received_pending_reads_differently_and_is_actionable(db_session: AsyncSession):
    await _add_user(db_session, "MDB010", "Testowa Anna", telegram_id=910010)
    await _add_user(db_session, "MDB011", "Testowy Karol")
    await _add_tournament(db_session, "mdb-t10", _FAR_FUTURE)
    await _add_invitation(db_session, "MDB011", "MDB010", "mdb-t10", InvitationState.PENDING)

    message = _make_message(910010)
    await handle_moje_deble_command(message, db_session)

    texts = _texts(message)
    # CLAUDE.md step 8.1, PROBLEM 3: the summary is one message; a still
    # pending received invitation gets its own follow-up message with the
    # three answer buttons, not a slot in the summary's own keyboard.
    assert len(texts) == 2
    summary_text = texts[0]
    assert "Karol Testowy" in summary_text
    # Not the sent-pending wording -- this one was received.
    assert "Karol Testowy — wysłane" not in summary_text
    assert _button_texts(_markups(message)[0]) == ["Znajdź partnera"]

    follow_up_text = texts[1]
    assert follow_up_text == "🟠 Karol Testowy — zaprasza"

    markup = _markups(message)[1]
    button_texts = _button_texts(markup)
    # CLAUDE.md step 8.4: exactly the three answers, no Menu button.
    assert button_texts == ["Zatwierdź", "Odrzuć", "Nie jadę na ten turniej"]


async def test_one_follow_up_message_per_pending_received_invitation(db_session: AsyncSession):
    await _add_user(db_session, "MDB015", "Testowa Anna", telegram_id=910015)
    await _add_user(db_session, "MDB016", "Testowy Karol")
    await _add_user(db_session, "MDB017", "Testowa Ola")
    await _add_tournament(db_session, "mdb-t15", _FAR_FUTURE, venue_city="Radom")
    await _add_tournament(db_session, "mdb-t16", _FAR_FUTURE + timedelta(days=1), venue_city="Łódź")
    await _add_invitation(db_session, "MDB016", "MDB015", "mdb-t15", InvitationState.PENDING)
    await _add_invitation(db_session, "MDB017", "MDB015", "mdb-t16", InvitationState.PENDING)

    message = _make_message(910015)
    await handle_moje_deble_command(message, db_session)

    texts = _texts(message)
    # One summary message, plus one follow-up per pending received
    # invitation -- CLAUDE.md step 8.1, PROBLEM 3.
    assert len(texts) == 3
    follow_ups = texts[1:]
    assert any("Karol Testowy" in text for text in follow_ups)
    assert any("Ola Testowa" in text for text in follow_ups)
    for markup in _markups(message)[1:]:
        assert len(_button_texts(markup)) == 3


# --- Cancelling (CLAUDE.md step 8.6): only the sender gets the button ----------


async def test_sent_pending_gets_cancel_button_received_pending_gets_answer_buttons(db_session: AsyncSession):
    await _add_user(db_session, "MDB080", "Testowa Anna", telegram_id=910080)
    await _add_user(db_session, "MDB081", "Testowy Karol")
    await _add_user(db_session, "MDB082", "Testowa Ola")
    await _add_tournament(db_session, "mdb-t80", _FAR_FUTURE, venue_city="Radom")
    await _add_tournament(db_session, "mdb-t81", _FAR_FUTURE + timedelta(days=1), venue_city="Łódź")
    # Anna sent this one -- she may cancel it, Karol only answers it.
    await _add_invitation(db_session, "MDB080", "MDB081", "mdb-t80", InvitationState.PENDING)
    # Ola sent this one to Anna -- Anna answers it, she has no cancel button.
    await _add_invitation(db_session, "MDB082", "MDB080", "mdb-t81", InvitationState.PENDING)

    message = _make_message(910080)
    await handle_moje_deble_command(message, db_session)

    follow_ups = list(zip(_texts(message)[1:], _markups(message)[1:]))
    sent_follow_up = next(text_markup for text_markup in follow_ups if "Karol" in text_markup[0])
    received_follow_up = next(text_markup for text_markup in follow_ups if "Ola" in text_markup[0])

    assert _button_texts(sent_follow_up[1]) == ["Anuluj zaproszenie"]
    assert _button_texts(received_follow_up[1]) == ["Zatwierdź", "Odrzuć", "Nie jadę na ten turniej"]


# --- WHAT IT HIDES: finished tournaments, day boundary --------------------------


async def test_finished_tournament_excluded_ongoing_included_warsaw_boundary(db_session: AsyncSession):
    await _add_user(db_session, "MDB020", "Testowa Anna")
    await _add_user(db_session, "MDB021", "Testowa Jagoda")
    await _add_user(db_session, "MDB022", "Testowa Ola")
    # Ends 2026-08-05: finished as of 2026-08-06, still live on 2026-08-05
    # itself -- "over at the end of that day", not before it.
    await _add_tournament(db_session, "mdb-t20", date(2026, 8, 4), date_to=date(2026, 8, 5))
    # Still running on 2026-08-06.
    await _add_tournament(db_session, "mdb-t21", date(2026, 8, 6), date_to=date(2026, 8, 8))
    await _add_invitation(db_session, "MDB020", "MDB021", "mdb-t20", InvitationState.PENDING)
    await _add_invitation(db_session, "MDB020", "MDB022", "mdb-t21", InvitationState.PENDING)

    invitations = await crud.get_invitations_for_player(db_session, "MDB020")

    still_live = date(2026, 8, 5)
    groups_still_live = group_by_tournament(invitations, "MDB020", today=still_live, lang="pl")
    assert {g.tournament_guid for g in groups_still_live} == {"mdb-t20", "mdb-t21"}

    finished_boundary = date(2026, 8, 6)
    groups_after = group_by_tournament(invitations, "MDB020", today=finished_boundary, lang="pl")
    assert {g.tournament_guid for g in groups_after} == {"mdb-t21"}
    assert "Testowa Jagoda" not in render_groups(groups_after, "pl")


# --- CANCELLED INVITATIONS: noise, not history ----------------------------------


async def test_cancelled_invitations_are_absent(db_session: AsyncSession):
    await _add_user(db_session, "MDB030", "Testowa Anna", telegram_id=910030)
    await _add_user(db_session, "MDB031", "Testowa Jagoda")
    await _add_tournament(db_session, "mdb-t30", _FAR_FUTURE)
    await _add_invitation(db_session, "MDB030", "MDB031", "mdb-t30", InvitationState.CANCELLED)

    message = _make_message(910030)
    await handle_moje_deble_command(message, db_session)

    texts = _texts(message)
    assert texts == ["Nie masz jeszcze żadnych zaproszeń."]


# --- EMPTY STATE ------------------------------------------------------------------


async def test_empty_state_offers_find_partner_only(db_session: AsyncSession):
    await _add_user(db_session, "MDB040", "Testowa Anna", telegram_id=910040)

    message = _make_message(910040)
    await handle_moje_deble_command(message, db_session)

    assert _texts(message) == ["Nie masz jeszcze żadnych zaproszeń."]
    markup = _markups(message)[0]
    assert _button_texts(markup) == ["Znajdź partnera"]


async def test_command_before_registration_does_not_crash(db_session: AsyncSession):
    message = _make_message(910041)

    await handle_moje_deble_command(message, db_session)

    assert _texts(message) == ["Zacznij od komendy /start, aby się zarejestrować."]
    # CLAUDE.md step 8.5: /moje_deble is typeable before /start ever ran,
    # so this can be a session's very first message -- it must not be the
    # one place the persistent reply keyboard never shows up.
    markup = _markups(message)[0]
    assert markup.is_persistent is True
    assert markup.resize_keyboard is True
    rows = [[button.text for button in row] for row in markup.keyboard]
    assert rows == [["Znajdź partnera"], ["Moje deble", "Zaproś na CourtDuo"]]


# --- NEVER: a third party's partner name never appears --------------------------


async def test_a_third_partys_partner_is_never_revealed(db_session: AsyncSession):
    await _add_user(db_session, "MDB050", "Testowa Anna", telegram_id=910050)
    await _add_user(db_session, "MDB051", "Testowy Bartosz")
    await _add_user(db_session, "MDB052", "Testowa Sekret")
    await _add_tournament(db_session, "mdb-t50", _FAR_FUTURE)

    # Anna's own (still-open) invitation to Bartosz.
    await _add_invitation(db_session, "MDB050", "MDB051", "mdb-t50", InvitationState.PENDING)
    # Bartosz is separately matched with somebody else at the same
    # tournament -- none of Anna's business, and no row of hers points at it.
    await _add_invitation(db_session, "MDB051", "MDB052", "mdb-t50", InvitationState.ACCEPTED)

    message = _make_message(910050)
    await handle_moje_deble_command(message, db_session)

    text = _texts(message)[0]
    assert "Sekret" not in text
    assert "Bartosz Testowy" in text


# --- Reachable via the button too, same rendering --------------------------------


async def test_moje_deble_button_clears_itself_and_renders_the_same_view(db_session: AsyncSession):
    await _add_user(db_session, "MDB060", "Testowa Anna", telegram_id=910060)

    callback = _make_callback(910060)
    await handle_moje_deble_button(callback, db_session)

    callback.message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)
    callback.answer.assert_awaited_once()
    assert callback.message.answer.await_count == 1
    assert callback.message.answer.call_args.args[0] == "Nie masz jeszcze żadnych zaproszeń."


# --- Reachable via the persistent-keyboard label too (CLAUDE.md step 8.4) -------


async def test_moje_deble_button_press_renders_the_same_view(db_session: AsyncSession):
    await _add_user(db_session, "MDB061", "Testowa Anna", telegram_id=910061)

    message = _make_message(910061)
    await handle_moje_deble_button_press(message, db_session)

    assert _texts(message) == ["Nie masz jeszcze żadnych zaproszeń."]


async def test_moje_deble_button_press_before_registration_does_not_crash(db_session: AsyncSession):
    message = _make_message(910062)

    await handle_moje_deble_button_press(message, db_session)

    assert _texts(message) == ["Zacznij od komendy /start, aby się zarejestrować."]
    markup = _markups(message)[0]
    assert markup.is_persistent is True
    assert markup.resize_keyboard is True
