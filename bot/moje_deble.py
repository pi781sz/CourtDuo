"""Moje deble: the "everything I've sent or received" status view
(CLAUDE.md, "Moje deble" status view; build order step 8).

Pure filtering, grouping and rendering logic lives here so it can be
unit-tested without a database or Telegram, the same split as
bot.tournament_search / bot.handlers.tournament_search and
bot.invitation_text / bot.handlers.invitations. bot.handlers.moje_deble
fetches the rows (db.crud.get_invitations_for_player) and sends whatever
this module renders.

Nothing here mutates or deletes an invitation -- CLAUDE.md: "Nothing is
deleted from the database — this is a display filter only. Past
invitations stay for the results-based verification planned later."
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum, auto

from bot.formatting import STATUS_EMOJI
from bot.i18n import t
from bot.tournament_search import label_for_tournament
from core.text import display_name
from db.models import Invitation, InvitationState, Tournament

# CLAUDE.md, "WHAT IT SHOWS": only these four states are ever displayed --
# matching the four colours ("Colours, matching step 7.1"). CANCELLED is
# noise ("the player was already told at the time" -- CLAUDE.md, "CANCELLED
# INVITATIONS") and EXPIRED has no bullet of its own in CLAUDE.md's status
# display at all. Both are filtered out here for *display* only; neither
# state is touched or deleted.
_VISIBLE_STATES = frozenset(
    {InvitationState.PENDING, InvitationState.ACCEPTED, InvitationState.REJECTED, InvitationState.NOT_ATTENDING}
)


class Direction(Enum):
    """Which side of the invitation the viewer is on -- CLAUDE.md: "Show
    both directions ... and make clear which is which"."""

    SENT = auto()
    RECEIVED = auto()


@dataclass(frozen=True)
class DebelEntry:
    """One invitation, from one player's point of view. `other_full_name`
    is always the *other* participant's PZT-order name (never the
    viewer's own) -- display_name() is applied at render time, once, the
    same convention bot.invitation_text follows. `other_pzt_id` is the
    same participant's id -- the key _collapse_repeats groups by, since
    two players can in principle share a display name but never a pzt_id.
    """

    invitation_id: int
    tournament_guid: str
    state: InvitationState
    direction: Direction
    other_pzt_id: str
    other_full_name: str
    updated_at: datetime


def tournament_finished(date_from: date | None, date_to: date | None, today: date) -> bool:
    """CLAUDE.md, "WHAT IT HIDES": "Use `date_to` where present, otherwise
    `date_from`; a tournament is over at the end of that day,
    Europe/Warsaw." `today` must already be that Europe/Warsaw wall-clock
    date -- see bot.handlers.moje_deble, which computes it the same way
    step 5's eligibility window does (never UTC's own date, which can
    disagree with Warsaw's near midnight).

    A tournament with neither date is never treated as finished, so a
    re-scrape that nulls both fields out can't silently make a live
    invitation vanish from this view.
    """
    end = date_to or date_from
    if end is None:
        return False
    return end < today


def entry_from_invitation(invitation: Invitation, viewer_pzt_id: str) -> DebelEntry:
    """One invitation, from `viewer_pzt_id`'s point of view.
    `viewer_pzt_id` must be one side of the invitation --
    db.crud.get_invitations_for_player only ever returns rows where that
    holds, so the other side is always the counterparty.
    """
    if invitation.inviter_pzt_id == viewer_pzt_id:
        direction = Direction.SENT
        other_pzt_id = invitation.invitee_pzt_id
        other_full_name = invitation.invitee.full_name
    else:
        direction = Direction.RECEIVED
        other_pzt_id = invitation.inviter_pzt_id
        other_full_name = invitation.inviter.full_name
    return DebelEntry(
        invitation_id=invitation.id,
        tournament_guid=invitation.tournament_guid,
        state=invitation.state,
        direction=direction,
        other_pzt_id=other_pzt_id,
        other_full_name=other_full_name,
        updated_at=invitation.updated_at,
    )


def visible_entries(invitations: list[Invitation], viewer_pzt_id: str, today: date) -> list[DebelEntry]:
    """Every invitation `viewer_pzt_id` should see: visible state, and its
    tournament hasn't finished (CLAUDE.md's two display filters). Order is
    decided by group_by_tournament, not here.
    """
    entries = []
    for invitation in invitations:
        if invitation.state not in _VISIBLE_STATES:
            continue
        tournament = invitation.tournament
        if tournament_finished(tournament.date_from, tournament.date_to, today):
            continue
        entries.append(entry_from_invitation(invitation, viewer_pzt_id))
    return entries


def _entry_sort_key(entry: DebelEntry) -> float:
    # CLAUDE.md step 8.3, PROBLEM 7: activity order, oldest first, newest
    # last -- "activity" is when the row last changed (updated_at), not
    # when it was created. A matched group only ever has the one surviving
    # entry (_matched_only), so there is nothing left to tiebreak against.
    return entry.updated_at.timestamp()


def _collapse_repeats(entries: list[DebelEntry]) -> list[DebelEntry]:
    """CLAUDE.md, "Moje deble" step 8.1: "Repeated invitations between the
    same two players for the same tournament are listed once per attempt.
    Collapse to one line per (tournament, other player), showing only the
    most recent state." One tournament's worth of entries in, keyed by
    `other_pzt_id` -- the two players can invite each other back and forth
    (a rejection or "nie jadę" is free and instant), so direction alone
    isn't enough to key on; only the latest row per pair is kept, and it
    carries whichever direction it happened to be.
    """
    latest_by_pair: dict[str, DebelEntry] = {}
    for entry in entries:
        current = latest_by_pair.get(entry.other_pzt_id)
        if current is None or entry.updated_at > current.updated_at:
            latest_by_pair[entry.other_pzt_id] = entry
    return list(latest_by_pair.values())


def _matched_only(entries: list[DebelEntry]) -> list[DebelEntry]:
    """CLAUDE.md, "Moje deble" step 8.1: "When a tournament has a match,
    show ONLY the match line. Nothing else for that tournament." A locked
    match makes every other row in the group dead history -- an older
    rejection, or an invitation to a third player that never went
    anywhere -- so once one ACCEPTED entry survives collapsing, it is the
    only thing shown.
    """
    matched = [entry for entry in entries if entry.state is InvitationState.ACCEPTED]
    return matched or entries


@dataclass(frozen=True)
class TournamentGroup:
    tournament_guid: str
    header: str
    entries: list[DebelEntry]


def group_by_tournament(
    invitations: list[Invitation], viewer_pzt_id: str, today: date, lang: str
) -> list[TournamentGroup]:
    """Every visible entry, grouped and ordered per CLAUDE.md's "WHAT IT
    SHOWS": activity order, oldest first, newest last, so the most recent
    thing sits at the bottom nearest the input box (step 8.3, PROBLEM 7) --
    tournament groups by their own most recent activity, and lines within a
    group the same way -- after collapsing repeats between the same pair
    and dropping everything but a match, if there is one.
    """
    entries = visible_entries(invitations, viewer_pzt_id, today)
    tournaments_by_guid: dict[str, Tournament] = {
        invitation.tournament_guid: invitation.tournament for invitation in invitations
    }

    grouped: dict[str, list[DebelEntry]] = {}
    for entry in entries:
        grouped.setdefault(entry.tournament_guid, []).append(entry)

    groups = []
    for guid, group_entries in grouped.items():
        group_entries = _matched_only(_collapse_repeats(group_entries))
        group_entries.sort(key=_entry_sort_key)
        tournament = tournaments_by_guid[guid]
        groups.append(
            TournamentGroup(
                tournament_guid=guid,
                header=label_for_tournament(tournament),
                entries=group_entries,
            )
        )
    # "Their own most recent activity" -- each group's own latest entry,
    # ascending, so the tournament with the most recently touched
    # invitation ends up last (CLAUDE.md step 8.3, PROBLEM 7). Every group
    # has at least one entry (it was only created because visible_entries
    # put something in it), so max() never sees an empty sequence.
    groups.sort(key=lambda group: max(entry.updated_at for entry in group.entries))
    return groups


_ENTRY_TEXT_KEYS: dict[tuple[Direction, InvitationState], str] = {
    (Direction.SENT, InvitationState.PENDING): "moje_deble.sent_pending",
    (Direction.SENT, InvitationState.REJECTED): "moje_deble.sent_rejected",
    (Direction.SENT, InvitationState.NOT_ATTENDING): "moje_deble.sent_not_attending",
    (Direction.RECEIVED, InvitationState.PENDING): "moje_deble.received_pending",
    (Direction.RECEIVED, InvitationState.REJECTED): "moje_deble.received_rejected",
    (Direction.RECEIVED, InvitationState.NOT_ATTENDING): "moje_deble.received_not_attending",
}


def entry_line(entry: DebelEntry, lang: str) -> str:
    """One status line. ACCEPTED is symmetric -- the same "Gracie razem: X"
    line regardless of who invited whom -- everything else is keyed by
    direction, carried by the leading phrase ("Wysłane do:" vs "Zaproszenie
    od:"), so a sent and a received line never read the same way.
    """
    name = display_name(entry.other_full_name)
    emoji = STATUS_EMOJI[entry.state]
    if entry.state is InvitationState.ACCEPTED:
        return t("moje_deble.matched", lang, emoji=emoji, name=name)
    return t(_ENTRY_TEXT_KEYS[(entry.direction, entry.state)], lang, emoji=emoji, name=name)


def render_groups(groups: list[TournamentGroup], lang: str) -> str:
    """The full view: one blank-line-separated block per tournament,
    header first, matching CLAUDE.md's "WHAT IT SHOWS" example."""
    blocks = []
    for group in groups:
        lines = [group.header] + [entry_line(entry, lang) for entry in group.entries]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def pending_received_entries(groups: list[TournamentGroup]) -> list[DebelEntry]:
    """Every still-open received invitation across all groups, in render
    order -- what the Zatwierdź/Odrzuć/"Nie jadę na ten turniej" buttons
    attach to (CLAUDE.md: "must be actionable from here")."""
    return [
        entry
        for group in groups
        for entry in group.entries
        if entry.state is InvitationState.PENDING and entry.direction is Direction.RECEIVED
    ]
