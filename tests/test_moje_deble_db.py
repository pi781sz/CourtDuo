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

from bot.account_deletion import delete_account
from bot.handlers.moje_deble import (
    handle_moje_deble_button,
    handle_moje_deble_button_press,
    handle_moje_deble_command,
)
from bot.keyboards.invitations import CancelInvitationCallback, ReleaseMatchCallback
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


_STATUS_EMOJI_PREFIXES = ("🟠", "🔴", "🟢", "⚠️")


def _all_entry_lines(mock: MagicMock) -> list[str]:
    """Every entry_line()-shaped line across every message a render sent:
    each line of the summary body that starts with one of the status
    emoji, plus every follow-up message in full (a follow-up message
    *is* a single entry_line() call). Tournament headings and the summary
    heading are never mistaken for an entry line -- they never start with
    one of these emoji."""
    lines = []
    for text in _texts(mock):
        for line in text.split("\n"):
            if line.startswith(_STATUS_EMOJI_PREFIXES):
                lines.append(line)
    return lines


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
    # answer-keyboard follow-ups. The one still-open sent invitation (to
    # Maja) no longer gets a follow-up message of its own either -- its
    # line stays in the summary body and its cancel button rides on the
    # summary message's own keyboard instead (no-duplicate-lines fix).
    assert len(texts) == 1
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

    # CLAUDE.md step 12.2: no "Znajdź partnera" button on the summary --
    # duplicated the persistent reply keyboard's own label. Nothing
    # stranded here, but the still-open sent invitation to Maja gets its
    # own named cancel button.
    markup = _markups(message)[0]
    assert _button_texts(markup) == ["Anuluj: Maja Testowa"]


async def test_received_pending_reads_differently_and_is_actionable(db_session: AsyncSession):
    await _add_user(db_session, "MDB010", "Testowa Anna", telegram_id=910010)
    await _add_user(db_session, "MDB011", "Testowy Karol")
    await _add_tournament(db_session, "mdb-t10", _FAR_FUTURE)
    await _add_invitation(db_session, "MDB011", "MDB010", "mdb-t10", InvitationState.PENDING)

    message = _make_message(910010)
    await handle_moje_deble_command(message, db_session)

    texts = _texts(message)
    # This player has nothing but one still-open *received* invitation --
    # its line is left out of the summary body (no-duplicate-lines fix),
    # which leaves the one tournament group with nothing left in it, which
    # in turn leaves the whole summary with nothing to show. So no summary
    # message at all: just the one follow-up message with the three
    # answer buttons (CLAUDE.md step 8.1, PROBLEM 3).
    assert len(texts) == 1

    follow_up_text = texts[0]
    assert follow_up_text == "🟠 Karol Testowy — zaprasza"

    markup = _markups(message)[0]
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
    # Both invitations here are still-open received ones, so both
    # tournament groups end up empty in the summary and the summary is
    # skipped entirely (CLAUDE.md, "EMPTY GROUPS") -- one follow-up
    # message per pending received invitation, nothing else.
    assert len(texts) == 2
    assert any("Karol Testowy" in text for text in texts)
    assert any("Ola Testowa" in text for text in texts)
    for markup in _markups(message):
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

    # Anna's own sent invitation (to Karol) stays in the summary body and
    # gets its named cancel button on the summary keyboard -- no follow-up
    # message of its own any more. Ola's invitation to Anna is still-open
    # *received*, so it gets its own follow-up message with the three
    # answer buttons, and its line is left out of the summary body/dropped
    # its (otherwise-empty) tournament group from the summary entirely.
    texts = _texts(message)
    assert len(texts) == 2

    summary_text, summary_markup = texts[0], _markups(message)[0]
    assert "Karol Testowy — wysłane" in summary_text
    assert "Ola" not in summary_text
    assert _button_texts(summary_markup) == ["Anuluj: Karol Testowy"]

    follow_up_text, follow_up_markup = texts[1], _markups(message)[1]
    assert follow_up_text == "🟠 Ola Testowa — zaprasza"
    assert _button_texts(follow_up_markup) == ["Zatwierdź", "Odrzuć", "Nie jadę na ten turniej"]


# --- A stranded match (CLAUDE.md step 12.1, PROBLEM 4): shown once -------------


async def test_stranded_match_appears_once_with_its_usun_button_on_the_summary(db_session: AsyncSession):
    await _add_user(db_session, "MDB090", "Testowa Anna", telegram_id=910090)
    await _add_user(db_session, "MDB091", "Testowa Jagoda", telegram_id=910091)
    tournament = await _add_tournament(db_session, "mdb-t90", _FAR_FUTURE, venue_city="Warszawa")
    matched = await _add_invitation(db_session, "MDB090", "MDB091", "mdb-t90", InvitationState.ACCEPTED)

    jagoda = await crud.get_account_by_pzt_id(db_session, "MDB091")
    await delete_account(db_session, jagoda, today=date(2026, 8, 7))
    await db_session.flush()

    message = _make_message(910090)
    await handle_moje_deble_command(message, db_session)

    texts = _texts(message)
    # One message only -- the stranded-match line must not be repeated in
    # a second, follow-up message.
    assert len(texts) == 1
    assert texts[0].count("potwierdź osobiście") == 1
    assert "⚠️ Jagoda Testowa — potwierdź osobiście" in texts[0]

    markup = _markups(message)[0]
    # CLAUDE.md step 12.2: no "Znajdź partnera" button alongside "Usuń" --
    # it duplicated the persistent reply keyboard's own label.
    assert _button_texts(markup) == ["Usuń"]
    release_button = markup.inline_keyboard[-1][0]
    assert release_button.callback_data == ReleaseMatchCallback(invitation_id=matched.id).pack()


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


async def test_empty_state_has_no_inline_keyboard(db_session: AsyncSession):
    # CLAUDE.md step 12.2: the inline "Znajdź partnera" button this used
    # to carry duplicated the persistent reply keyboard's own label,
    # already visible below the input box -- removed.
    await _add_user(db_session, "MDB040", "Testowa Anna", telegram_id=910040)

    message = _make_message(910040)
    await handle_moje_deble_command(message, db_session)

    assert _texts(message) == ["Nie masz jeszcze żadnych zaproszeń."]
    assert _markups(message)[0] is None


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


# --- No-duplicate-lines fix: an entry line is never rendered twice -------------
#
# A bug report found a still-open sent invitation's line rendered in the
# summary AND repeated, verbatim, in a follow-up message that existed only
# to hang the cancel button on. The fix follows the precedent already set
# for a stranded match's "Usuń" button: fold the button onto the summary
# message's own keyboard instead of a second message. These tests cover
# every kind of entry this view can show at once, and the two "still-open"
# cases and the "everything omitted" edge case individually.


async def test_no_entry_line_appears_more_than_once_across_all_messages(db_session: AsyncSession):
    await _add_user(db_session, "MDB200", "Testowa Anna", telegram_id=910200)
    await _add_user(db_session, "MDB201", "Testowa Jagoda", telegram_id=910201)  # stranded match
    await _add_user(db_session, "MDB202", "Testowy Karol")  # still-open sent
    await _add_user(db_session, "MDB203", "Testowa Ola")  # still-open received
    await _add_user(db_session, "MDB204", "Testowy Bartosz")  # rejected
    await _add_user(db_session, "MDB205", "Testowa Wiktoria")  # not attending
    await _add_tournament(db_session, "mdb-t200", _FAR_FUTURE, venue_city="A")
    await _add_tournament(db_session, "mdb-t201", _FAR_FUTURE + timedelta(days=1), venue_city="B")
    await _add_tournament(db_session, "mdb-t202", _FAR_FUTURE + timedelta(days=2), venue_city="C")
    await _add_tournament(db_session, "mdb-t203", _FAR_FUTURE + timedelta(days=3), venue_city="D")
    await _add_tournament(db_session, "mdb-t204", _FAR_FUTURE + timedelta(days=4), venue_city="E")

    await _add_invitation(db_session, "MDB200", "MDB201", "mdb-t200", InvitationState.ACCEPTED)
    await _add_invitation(db_session, "MDB200", "MDB202", "mdb-t201", InvitationState.PENDING)
    await _add_invitation(db_session, "MDB203", "MDB200", "mdb-t202", InvitationState.PENDING)
    await _add_invitation(db_session, "MDB200", "MDB204", "mdb-t203", InvitationState.REJECTED)
    await _add_invitation(db_session, "MDB200", "MDB205", "mdb-t204", InvitationState.NOT_ATTENDING)

    jagoda = await crud.get_account_by_pzt_id(db_session, "MDB201")
    await delete_account(db_session, jagoda, today=date(2026, 8, 7))
    await db_session.flush()

    message = _make_message(910200)
    await handle_moje_deble_command(message, db_session)

    entry_lines = _all_entry_lines(message)
    assert len(entry_lines) == len(set(entry_lines)), f"a line repeated: {entry_lines}"

    # Sanity: every one of the five entries actually showed up somewhere,
    # so this isn't passing by having silently dropped one.
    joined = "\n".join(_texts(message))
    for name in ("Jagoda Testowa", "Karol Testowy", "Ola Testowa", "Bartosz Testowy", "Wiktoria Testowa"):
        assert name in joined


async def test_still_open_sent_invitation_produces_exactly_one_message(db_session: AsyncSession):
    await _add_user(db_session, "MDB210", "Testowa Anna", telegram_id=910210)
    await _add_user(db_session, "MDB211", "Testowy Karol")
    await _add_tournament(db_session, "mdb-t210", _FAR_FUTURE)
    invitation = await _add_invitation(db_session, "MDB210", "MDB211", "mdb-t210", InvitationState.PENDING)

    message = _make_message(910210)
    await handle_moje_deble_command(message, db_session)

    assert len(_texts(message)) == 1
    markup = _markups(message)[0]
    assert _button_texts(markup) == ["Anuluj: Karol Testowy"]
    assert markup.inline_keyboard[0][0].callback_data == CancelInvitationCallback(
        invitation_id=invitation.id
    ).pack()


async def test_still_open_received_invitation_appears_only_in_its_own_message(db_session: AsyncSession):
    await _add_user(db_session, "MDB220", "Testowa Anna", telegram_id=910220)
    await _add_user(db_session, "MDB221", "Testowy Karol")
    await _add_user(db_session, "MDB222", "Testowa Ola")
    await _add_tournament(db_session, "mdb-t220", _FAR_FUTURE, venue_city="Radom")
    # A second, matched entry at a different tournament, so the summary
    # message still gets sent (otherwise this would collapse into the
    # all-omitted case exercised separately below).
    await _add_tournament(db_session, "mdb-t221", _FAR_FUTURE + timedelta(days=1), venue_city="Łódź")
    await _add_invitation(db_session, "MDB221", "MDB220", "mdb-t220", InvitationState.PENDING)
    await _add_invitation(db_session, "MDB220", "MDB222", "mdb-t221", InvitationState.ACCEPTED)

    message = _make_message(910220)
    await handle_moje_deble_command(message, db_session)

    texts = _texts(message)
    summary_text = texts[0]
    assert "Karol Testowy" not in summary_text

    received_messages = [text for text in texts if text == "🟠 Karol Testowy — zaprasza"]
    assert len(received_messages) == 1


async def test_empty_group_dropped_but_other_groups_keep_their_heading(db_session: AsyncSession):
    # CLAUDE.md, "EMPTY GROUPS": one tournament has nothing but a
    # still-open received invitation and disappears from the summary
    # entirely; another has a sent-pending invitation and keeps its
    # heading and line as usual.
    await _add_user(db_session, "MDB230", "Testowa Anna", telegram_id=910230)
    await _add_user(db_session, "MDB231", "Testowy Karol")
    await _add_user(db_session, "MDB232", "Testowa Ola")
    await _add_tournament(db_session, "mdb-t230", _FAR_FUTURE, venue_city="Radom")
    await _add_tournament(db_session, "mdb-t231", _FAR_FUTURE + timedelta(days=1), venue_city="Łódź")
    await _add_invitation(db_session, "MDB231", "MDB230", "mdb-t230", InvitationState.PENDING)
    await _add_invitation(db_session, "MDB230", "MDB232", "mdb-t231", InvitationState.PENDING)

    message = _make_message(910230)
    await handle_moje_deble_command(message, db_session)

    texts = _texts(message)
    summary_text = texts[0]
    assert "Radom" not in summary_text
    assert "Karol Testowy" not in summary_text
    assert "Łódź" in summary_text
    assert "Ola Testowa — wysłane" in summary_text


async def test_summary_message_skipped_when_everything_is_still_open_received(db_session: AsyncSession):
    # CLAUDE.md: "If omitting them leaves the summary with no groups at
    # all, the summary message must not be sent" -- this player has
    # nothing but two still-open received invitations, so no summary
    # message goes out, only the two follow-ups.
    await _add_user(db_session, "MDB240", "Testowa Anna", telegram_id=910240)
    await _add_user(db_session, "MDB241", "Testowy Karol")
    await _add_user(db_session, "MDB242", "Testowa Ola")
    await _add_tournament(db_session, "mdb-t240", _FAR_FUTURE, venue_city="Radom")
    await _add_tournament(db_session, "mdb-t241", _FAR_FUTURE + timedelta(days=1), venue_city="Łódź")
    await _add_invitation(db_session, "MDB241", "MDB240", "mdb-t240", InvitationState.PENDING)
    await _add_invitation(db_session, "MDB242", "MDB240", "mdb-t241", InvitationState.PENDING)

    message = _make_message(910240)
    await handle_moje_deble_command(message, db_session)

    texts = _texts(message)
    assert "Moje deble" not in texts
    assert len(texts) == 2
    assert {texts[0], texts[1]} == {"🟠 Karol Testowy — zaprasza", "🟠 Ola Testowa — zaprasza"}
    for markup in _markups(message):
        assert len(_button_texts(markup)) == 3
