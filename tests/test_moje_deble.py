"""Tests for bot.moje_deble's pure filtering, grouping and rendering logic
(CLAUDE.md, "Moje deble" status view; build order step 8): the day-boundary
rule, direction, ordering, and the exact wording. No database -- see
tests/test_moje_deble_db.py for the crud query and the full handler flow.
Invented names, pzt_ids and tournament guids only.

Invitation/Player/Tournament rows are constructed directly (no session) --
a plain ORM object with its relationships set by hand needs no database
connection, the same trick tests/test_invitation_handlers_db.py's
_add_tournament/_add_user helpers rely on for the DB-backed tests.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from bot.formatting import STATUS_EMOJI
from bot.moje_deble import (
    Direction,
    entry_from_invitation,
    entry_line,
    group_by_tournament,
    pending_received_entries,
    pending_sent_entries,
    render_groups,
    summary_groups,
    tournament_finished,
    visible_entries,
)
from db.models import Invitation, InvitationState, Player, Tournament

_LANG = "pl"


def _tournament(guid: str, date_from: date | None, date_to: date | None = None, venue_city: str = "Testowo") -> Tournament:
    return Tournament(
        guid=guid,
        name="Turniej testowy",
        type_prefix=None,
        age_category=None,
        ranga=5,
        date_from=date_from,
        date_to=date_to,
        wojewodztwo=None,
        venue_address=None,
        venue_city=venue_city,
        entry_deadline=None,
        withdrawal_deadline=None,
        search_closes_at=None,
    )


def _player(pzt_id: str, full_name: str) -> Player:
    return Player(pzt_id=pzt_id, full_name=full_name, club=None, age_category=None, gender=None)


def _invitation(
    invitation_id: int,
    inviter: Player,
    invitee: Player,
    tournament: Tournament,
    state: InvitationState,
    updated_at: datetime,
) -> Invitation:
    invitation = Invitation(
        id=invitation_id,
        inviter_pzt_id=inviter.pzt_id,
        invitee_pzt_id=invitee.pzt_id,
        tournament_guid=tournament.guid,
        event_id=1,
        state=state,
        expires_at=updated_at,
    )
    invitation.inviter = inviter
    invitation.invitee = invitee
    invitation.tournament = tournament
    invitation.updated_at = updated_at
    return invitation


_T0 = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


# --- tournament_finished ------------------------------------------------------


def test_tournament_finished_uses_date_to_when_present():
    assert tournament_finished(date(2026, 8, 1), date(2026, 8, 3), today=date(2026, 8, 4)) is True
    assert tournament_finished(date(2026, 8, 1), date(2026, 8, 3), today=date(2026, 8, 3)) is False


def test_tournament_finished_falls_back_to_date_from():
    assert tournament_finished(date(2026, 8, 1), None, today=date(2026, 8, 2)) is True
    assert tournament_finished(date(2026, 8, 1), None, today=date(2026, 8, 1)) is False


def test_tournament_finished_never_true_with_no_dates_at_all():
    assert tournament_finished(None, None, today=date(2026, 8, 1)) is False


def test_tournament_finished_day_boundary_is_the_whole_day_not_a_utc_instant():
    # A tournament ending 2026-08-01 is still not finished at any point
    # during 2026-08-01 Europe/Warsaw wall-clock time -- the caller is
    # responsible for passing a Warsaw date, not a UTC one; this just
    # checks the comparison itself doesn't sneak in an earlier cutoff.
    assert tournament_finished(date(2026, 8, 1), date(2026, 8, 1), today=date(2026, 8, 1)) is False
    assert tournament_finished(date(2026, 8, 1), date(2026, 8, 1), today=date(2026, 8, 2)) is True


# --- entry_from_invitation / direction ----------------------------------------


def test_entry_from_invitation_sent_direction():
    anna = _player("P001", "Testowa Anna")
    jagoda = _player("P002", "Testowa Jagoda")
    tournament = _tournament("g1", date(2026, 8, 22))
    invitation = _invitation(1, anna, jagoda, tournament, InvitationState.PENDING, _T0)

    entry = entry_from_invitation(invitation, viewer_pzt_id="P001")

    assert entry.direction is Direction.SENT
    assert entry.other_full_name == "Testowa Jagoda"


def test_entry_from_invitation_received_direction():
    anna = _player("P001", "Testowa Anna")
    jagoda = _player("P002", "Testowa Jagoda")
    tournament = _tournament("g1", date(2026, 8, 22))
    invitation = _invitation(1, anna, jagoda, tournament, InvitationState.PENDING, _T0)

    entry = entry_from_invitation(invitation, viewer_pzt_id="P002")

    assert entry.direction is Direction.RECEIVED
    assert entry.other_full_name == "Testowa Anna"


# --- visible_entries: state and finished-tournament filters -------------------


def test_visible_entries_excludes_cancelled_and_expired():
    anna = _player("P010", "Testowa Anna")
    jagoda = _player("P011", "Testowa Jagoda")
    tournament = _tournament("g10", date(2026, 8, 22))
    invitations = [
        _invitation(1, anna, jagoda, tournament, InvitationState.CANCELLED, _T0),
        _invitation(2, anna, jagoda, tournament, InvitationState.EXPIRED, _T0),
        _invitation(3, anna, jagoda, tournament, InvitationState.PENDING, _T0),
    ]

    entries = visible_entries(invitations, "P010", today=date(2026, 8, 1))

    assert [entry.invitation_id for entry in entries] == [3]


def test_visible_entries_excludes_finished_tournaments():
    anna = _player("P020", "Testowa Anna")
    jagoda = _player("P021", "Testowa Jagoda")
    finished = _tournament("g20", date(2026, 7, 1), date(2026, 7, 2))
    ongoing = _tournament("g21", date(2026, 8, 1), date(2026, 8, 3))
    invitations = [
        _invitation(1, anna, jagoda, finished, InvitationState.PENDING, _T0),
        _invitation(2, anna, jagoda, ongoing, InvitationState.PENDING, _T0),
    ]

    entries = visible_entries(invitations, "P020", today=date(2026, 8, 2))

    assert [entry.invitation_id for entry in entries] == [2]


# --- group_by_tournament: ordering ---------------------------------------------


def test_groups_are_ordered_by_own_most_recent_activity_oldest_first():
    # CLAUDE.md step 8.3, PROBLEM 7: activity order, oldest first, newest
    # last -- not tournament date. The tournament dates below are chosen
    # the opposite way round from the activity timestamps to prove it's the
    # latter driving the order.
    from datetime import timedelta

    anna = _player("P030", "Testowa Anna")
    jagoda = _player("P031", "Testowa Jagoda")
    later_date = _tournament("late-date", date(2026, 9, 1))
    earlier_date = _tournament("early-date", date(2026, 8, 1))
    invitations = [
        # Tournament date is later, but the activity on it is older.
        _invitation(1, anna, jagoda, later_date, InvitationState.PENDING, _T0),
        # Tournament date is earlier, but the activity on it is more recent.
        _invitation(2, anna, jagoda, earlier_date, InvitationState.PENDING, _T0 + timedelta(hours=1)),
    ]

    groups = group_by_tournament(invitations, "P030", today=date(2026, 7, 1), lang=_LANG)

    assert [group.tournament_guid for group in groups] == ["late-date", "early-date"]


def test_matched_hides_everything_else_in_that_tournament():
    # CLAUDE.md, step 8.1, PROBLEM 1(a): "When a tournament has a match,
    # show ONLY the match line. Nothing else for that tournament." -- not
    # "matched sorts first", the dead history underneath must be gone.
    anna = _player("P040", "Testowa Anna")
    jagoda = _player("P041", "Testowa Jagoda")
    ola = _player("P042", "Testowa Ola")
    tournament = _tournament("g40", date(2026, 8, 22))
    invitations = [
        _invitation(1, anna, jagoda, tournament, InvitationState.PENDING, _T0),
        _invitation(2, anna, ola, tournament, InvitationState.ACCEPTED, _T0),
    ]

    groups = group_by_tournament(invitations, "P040", today=date(2026, 8, 1), lang=_LANG)

    assert len(groups) == 1
    assert [entry.invitation_id for entry in groups[0].entries] == [2]


def test_within_a_tournament_non_matched_entries_sort_oldest_activity_first():
    # CLAUDE.md step 8.3, PROBLEM 7: oldest first, newest last, so the most
    # recent thing sits at the bottom nearest the input box.
    from datetime import timedelta

    anna = _player("P050", "Testowa Anna")
    jagoda = _player("P051", "Testowa Jagoda")
    ola = _player("P052", "Testowa Ola")
    tournament = _tournament("g50", date(2026, 8, 22))
    invitations = [
        _invitation(1, anna, jagoda, tournament, InvitationState.REJECTED, _T0),
        _invitation(2, anna, ola, tournament, InvitationState.PENDING, _T0 + timedelta(hours=1)),
    ]

    groups = group_by_tournament(invitations, "P050", today=date(2026, 8, 1), lang=_LANG)

    assert [entry.invitation_id for entry in groups[0].entries] == [1, 2]


# --- collapsing repeats between the same pair -----------------------------------


def test_repeated_invitations_between_the_same_pair_collapse_to_the_latest():
    # CLAUDE.md, step 8.1, PROBLEM 1(b): three attempts between the same
    # two players at the same tournament collapse to one line showing only
    # the most recent state -- direction included, since the back-and-forth
    # can switch who invited whom.
    from datetime import timedelta

    anna = _player("P130", "Testowa Anna")
    alisha = _player("P131", "Testowa Alisha")
    tournament = _tournament("g130", date(2026, 8, 13))
    invitations = [
        # Anna invited Alisha, Alisha rejected.
        _invitation(1, anna, alisha, tournament, InvitationState.REJECTED, _T0),
        # Alisha invited Anna, Anna rejected.
        _invitation(2, alisha, anna, tournament, InvitationState.REJECTED, _T0 + timedelta(hours=1)),
        # Anna invited Alisha again -- still pending, and the most recent.
        _invitation(3, anna, alisha, tournament, InvitationState.PENDING, _T0 + timedelta(hours=2)),
    ]

    groups = group_by_tournament(invitations, "P130", today=date(2026, 8, 1), lang=_LANG)

    assert len(groups) == 1
    assert [entry.invitation_id for entry in groups[0].entries] == [3]
    assert entry_line(groups[0].entries[0], _LANG) == "🟠 Alisha Testowa — wysłane"


def test_collapsing_is_scoped_per_tournament_not_globally():
    # The same pair, two different tournaments -- each tournament keeps
    # its own most-recent line; collapsing must not reach across them.
    anna = _player("P140", "Testowa Anna")
    alisha = _player("P141", "Testowa Alisha")
    t1 = _tournament("g140a", date(2026, 8, 13))
    t2 = _tournament("g140b", date(2026, 8, 22))
    invitations = [
        _invitation(1, anna, alisha, t1, InvitationState.PENDING, _T0),
        _invitation(2, anna, alisha, t2, InvitationState.REJECTED, _T0),
    ]

    groups = group_by_tournament(invitations, "P140", today=date(2026, 8, 1), lang=_LANG)

    assert len(groups) == 2
    assert {entry.invitation_id for group in groups for entry in group.entries} == {1, 2}


# --- entry_line / render_groups: wording ---------------------------------------


def test_sent_pending_wording_matches_claude_md_example():
    # PZT stores "Nazwisko Imię" (surname first); display goes through
    # display_name(), so "Testowa Maja" (as stored) reads as "Maja
    # Testowa" in the rendered line -- CLAUDE.md, step 7.1, "Name order".
    anna = _player("P060", "Testowa Anna")
    maja = _player("P061", "Testowa Maja")
    tournament = _tournament("g60", date(2026, 8, 29))
    invitation = _invitation(1, anna, maja, tournament, InvitationState.PENDING, _T0)
    entry = entry_from_invitation(invitation, viewer_pzt_id="P060")

    # CLAUDE.md step 8.4, CHANGE 4: the name leads, status follows.
    assert entry_line(entry, _LANG) == "🟠 Maja Testowa — wysłane"


def test_sent_rejected_and_not_attending_wording_matches_claude_md_example():
    # CLAUDE.md, step 8.1, PROBLEM 2: rejected and not-attending now share
    # 🔴 -- "the colour only needs to say 'not happening'" -- the wording
    # still carries the distinction ("odmowa" vs "nie jedzie").
    anna = _player("P070", "Testowa Anna")
    bartosz = _player("P071", "Testowy Bartosz")
    wiktoria = _player("P072", "Testowa Wiktoria")
    tournament = _tournament("g70", date(2026, 8, 29))

    rejected = entry_from_invitation(
        _invitation(1, anna, bartosz, tournament, InvitationState.REJECTED, _T0), "P070"
    )
    not_attending = entry_from_invitation(
        _invitation(2, anna, wiktoria, tournament, InvitationState.NOT_ATTENDING, _T0), "P070"
    )

    assert entry_line(rejected, _LANG) == "🔴 Bartosz Testowy — odmowa"
    assert entry_line(not_attending, _LANG) == "🔴 Wiktoria Testowa — nie jedzie"


def test_received_pending_reads_differently_from_sent_pending():
    # CLAUDE.md step 8.4, CHANGE 4: direction is still carried by the
    # status word after the name -- "wysłane" vs "zaprasza" -- so a
    # received pending line must not read the same as a sent one.
    anna = _player("P080", "Testowa Anna")
    maja = _player("P081", "Testowa Maja")
    tournament = _tournament("g80", date(2026, 8, 29))
    invitation = _invitation(1, maja, anna, tournament, InvitationState.PENDING, _T0)

    entry = entry_from_invitation(invitation, viewer_pzt_id="P080")
    line = entry_line(entry, _LANG)

    assert entry.direction is Direction.RECEIVED
    assert line == "🟠 Maja Testowa — zaprasza"
    assert line != "🟠 Maja Testowa — wysłane"


def test_matched_wording_is_symmetric_regardless_of_direction():
    anna = _player("P090", "Testowa Anna")
    jagoda = _player("P091", "Testowa Jagoda")
    tournament = _tournament("g90", date(2026, 8, 22))
    invitation = _invitation(1, anna, jagoda, tournament, InvitationState.ACCEPTED, _T0)

    as_inviter = entry_line(entry_from_invitation(invitation, "P090"), _LANG)
    as_invitee = entry_line(entry_from_invitation(invitation, "P091"), _LANG)

    assert as_inviter == "🟢 Jagoda Testowa — gracie razem"
    assert as_invitee == "🟢 Anna Testowa — gracie razem"


# --- CLAUDE.md step 8.3, PROBLEM 2: every line's colour comes from the lookup ---


def test_every_visible_state_renders_its_status_emoji_lookup_value():
    anna = _player("P095", "Testowa Anna")
    jagoda = _player("P096", "Testowa Jagoda")
    tournament = _tournament("g95", date(2026, 8, 22))

    for state in (
        InvitationState.PENDING,
        InvitationState.ACCEPTED,
        InvitationState.REJECTED,
        InvitationState.NOT_ATTENDING,
    ):
        invitation = _invitation(1, anna, jagoda, tournament, state, _T0)
        sent_line = entry_line(entry_from_invitation(invitation, "P095"), _LANG)
        received_line = entry_line(entry_from_invitation(invitation, "P096"), _LANG)
        assert sent_line.startswith(STATUS_EMOJI[state])
        assert received_line.startswith(STATUS_EMOJI[state])


def test_render_groups_matches_claude_md_layout():
    anna = _player("P100", "Testowa Anna")
    maja = _player("P101", "Testowa Maja")
    bartosz = _player("P102", "Testowy Bartosz")
    wiktoria = _player("P103", "Testowa Wiktoria")
    tournament = _tournament("g100", date(2026, 8, 29), venue_city="Zielona Góra")
    tournament.ranga = 3  # OTK
    invitations = [
        _invitation(1, anna, maja, tournament, InvitationState.PENDING, _T0),
        _invitation(2, anna, bartosz, tournament, InvitationState.REJECTED, _T0),
        _invitation(3, anna, wiktoria, tournament, InvitationState.NOT_ATTENDING, _T0),
    ]

    groups = group_by_tournament(invitations, "P100", today=date(2026, 8, 1), lang=_LANG)
    text = render_groups(groups, _LANG)

    assert text == (
        "OTK Zielona Góra - 29.08.2026\n"
        "🟠 Maja Testowa — wysłane\n"
        "🔴 Bartosz Testowy — odmowa\n"
        "🔴 Wiktoria Testowa — nie jedzie"
    )


def test_render_groups_separates_tournaments_with_a_blank_line():
    anna = _player("P110", "Testowa Anna")
    jagoda = _player("P111", "Testowa Jagoda")
    t1 = _tournament("g110a", date(2026, 8, 1), venue_city="A")
    t2 = _tournament("g110b", date(2026, 9, 1), venue_city="B")
    invitations = [
        _invitation(1, anna, jagoda, t1, InvitationState.PENDING, _T0),
        _invitation(2, anna, jagoda, t2, InvitationState.PENDING, _T0),
    ]

    groups = group_by_tournament(invitations, "P110", today=date(2026, 7, 1), lang=_LANG)
    text = render_groups(groups, _LANG)

    assert "\n\n" in text
    blocks = text.split("\n\n")
    assert len(blocks) == 2


# --- pending_received_entries: what gets action buttons ------------------------


def test_pending_received_entries_only_open_received_invitations():
    anna = _player("P120", "Testowa Anna")
    jagoda = _player("P121", "Testowa Jagoda")
    ola = _player("P122", "Testowa Ola")
    karol = _player("P123", "Testowy Karol")
    tournament = _tournament("g120", date(2026, 8, 22))
    matched_tournament = _tournament("g121", date(2026, 8, 29))
    invitations = [
        # Anna sent to Jagoda (sent, pending) -- not actionable here.
        _invitation(1, anna, jagoda, tournament, InvitationState.PENDING, _T0),
        # Ola sent to Anna (received, pending) -- actionable.
        _invitation(2, ola, anna, tournament, InvitationState.PENDING, _T0),
        # Already matched, at a different tournament -- not pending, not
        # actionable, and (per the matched-only rule) it hides nothing
        # here since it belongs to a different tournament group entirely.
        _invitation(3, anna, karol, matched_tournament, InvitationState.ACCEPTED, _T0),
    ]

    groups = group_by_tournament(invitations, "P120", today=date(2026, 8, 1), lang=_LANG)
    pending = pending_received_entries(groups)

    assert [entry.invitation_id for entry in pending] == [2]


# --- pending_sent_entries: what gets the cancel button (CLAUDE.md step 8.6) -----


def test_pending_sent_entries_only_open_sent_invitations():
    anna = _player("P150", "Testowa Anna")
    jagoda = _player("P151", "Testowa Jagoda")
    ola = _player("P152", "Testowa Ola")
    karol = _player("P153", "Testowy Karol")
    tournament = _tournament("g150", date(2026, 8, 22))
    matched_tournament = _tournament("g151", date(2026, 8, 29))
    invitations = [
        # Anna sent to Jagoda (sent, pending) -- actionable (cancel).
        _invitation(1, anna, jagoda, tournament, InvitationState.PENDING, _T0),
        # Ola sent to Anna (received, pending) -- not actionable here.
        _invitation(2, ola, anna, tournament, InvitationState.PENDING, _T0),
        # Already matched, at a different tournament.
        _invitation(3, anna, karol, matched_tournament, InvitationState.ACCEPTED, _T0),
    ]

    groups = group_by_tournament(invitations, "P150", today=date(2026, 8, 1), lang=_LANG)
    pending = pending_sent_entries(groups)

    assert [entry.invitation_id for entry in pending] == [1]


def test_pending_sent_and_received_entries_never_overlap():
    # CLAUDE.md step 8.6: only the sender ever gets the cancel button, only
    # the invitee ever gets the three answer buttons -- never both on the
    # same entry.
    anna = _player("P160", "Testowa Anna")
    jagoda = _player("P161", "Testowa Jagoda")
    ola = _player("P162", "Testowa Ola")
    tournament = _tournament("g160", date(2026, 8, 22))
    invitations = [
        _invitation(1, anna, jagoda, tournament, InvitationState.PENDING, _T0),
        _invitation(2, ola, anna, tournament, InvitationState.PENDING, _T0),
    ]

    groups = group_by_tournament(invitations, "P160", today=date(2026, 8, 1), lang=_LANG)
    sent_ids = {entry.invitation_id for entry in pending_sent_entries(groups)}
    received_ids = {entry.invitation_id for entry in pending_received_entries(groups)}

    assert sent_ids == {1}
    assert received_ids == {2}
    assert sent_ids.isdisjoint(received_ids)


# --- summary_groups: no-duplicate-lines fix, still-open received omitted -------


def test_summary_groups_omits_still_open_received_entries_but_keeps_the_rest():
    # A group with one sent-pending and one received-pending entry: the
    # received one is left out of the summary body (it gets its own
    # follow-up message instead), but the group survives since the
    # sent-pending entry is still there.
    anna = _player("P170", "Testowa Anna")
    karol = _player("P171", "Testowy Karol")
    ola = _player("P172", "Testowa Ola")
    tournament = _tournament("g170", date(2026, 8, 22))
    invitations = [
        _invitation(1, anna, karol, tournament, InvitationState.PENDING, _T0),
        _invitation(2, ola, anna, tournament, InvitationState.PENDING, _T0),
    ]

    groups = group_by_tournament(invitations, "P170", today=date(2026, 8, 1), lang=_LANG)
    summary = summary_groups(groups)

    assert len(summary) == 1
    assert [entry.invitation_id for entry in summary[0].entries] == [1]


def test_summary_groups_drops_a_group_whose_only_entry_is_received_pending():
    # CLAUDE.md, "EMPTY GROUPS": omitting the received-pending entry here
    # leaves nothing under the heading, so the whole group -- heading
    # included -- must not appear in the summary at all.
    anna = _player("P180", "Testowa Anna")
    karol = _player("P181", "Testowy Karol")
    tournament = _tournament("g180", date(2026, 8, 22))
    invitations = [_invitation(1, karol, anna, tournament, InvitationState.PENDING, _T0)]

    groups = group_by_tournament(invitations, "P180", today=date(2026, 8, 1), lang=_LANG)
    summary = summary_groups(groups)

    assert summary == []


def test_summary_groups_keeps_other_groups_when_only_one_is_dropped():
    # A mix across two tournaments: one has only a received-pending entry
    # (dropped entirely), the other has a sent-pending entry (kept) -- the
    # drop must be scoped to the empty group, not the whole summary.
    anna = _player("P190", "Testowa Anna")
    karol = _player("P191", "Testowy Karol")
    ola = _player("P192", "Testowa Ola")
    received_only = _tournament("g190a", date(2026, 8, 13))
    sent_only = _tournament("g190b", date(2026, 8, 22))
    invitations = [
        _invitation(1, karol, anna, received_only, InvitationState.PENDING, _T0),
        _invitation(2, anna, ola, sent_only, InvitationState.PENDING, _T0),
    ]

    groups = group_by_tournament(invitations, "P190", today=date(2026, 8, 1), lang=_LANG)
    summary = summary_groups(groups)

    assert [group.tournament_guid for group in summary] == ["g190b"]


def test_summary_groups_empty_when_every_group_is_only_received_pending():
    # CLAUDE.md: "If omitting them leaves the summary with no groups at
    # all" -- both tournaments here have nothing but a still-open received
    # invitation, so the summary ends up with no groups whatsoever.
    anna = _player("P200", "Testowa Anna")
    karol = _player("P201", "Testowy Karol")
    ola = _player("P202", "Testowa Ola")
    t1 = _tournament("g200a", date(2026, 8, 13))
    t2 = _tournament("g200b", date(2026, 8, 22))
    invitations = [
        _invitation(1, karol, anna, t1, InvitationState.PENDING, _T0),
        _invitation(2, ola, anna, t2, InvitationState.PENDING, _T0),
    ]

    groups = group_by_tournament(invitations, "P200", today=date(2026, 8, 1), lang=_LANG)
    summary = summary_groups(groups)

    assert summary == []


def test_summary_groups_never_drops_a_matched_or_stranded_entry():
    # Matched (ACCEPTED) entries are untouched by this filter regardless
    # of direction -- only PENDING+RECEIVED is ever omitted.
    anna = _player("P210", "Testowa Anna")
    jagoda = _player("P211", "Testowa Jagoda")
    tournament = _tournament("g210", date(2026, 8, 22))
    invitations = [_invitation(1, jagoda, anna, tournament, InvitationState.ACCEPTED, _T0)]

    groups = group_by_tournament(invitations, "P210", today=date(2026, 8, 1), lang=_LANG)
    summary = summary_groups(groups)

    assert len(summary) == 1
    assert [entry.invitation_id for entry in summary[0].entries] == [1]
