"""The invitation engine (CLAUDE.md, "Invitation engine"; build order
step 7, extended by step 8.6's inviter-initiated cancel): the transactions
an invitation can go through, and nothing else. No Telegram, no strings —
bot.handlers.invitations does the talking, bot.invitation_text does the
wording.

    PENDING -> ACCEPTED | REJECTED | NOT_ATTENDING | CANCELLED | EXPIRED

Every function here re-verifies from scratch. The pre-invitation checks in
bot.partner_selection (step 6) ran seconds earlier and are a courtesy to
the player, not a guarantee: the named player may have accepted somebody
else since, and the inviter may have been matched by an invitation they
sent earlier. CLAUDE.md is explicit that the lock at accept time is what
protects the data, so nothing below trusts a decision made outside its own
transaction.

Two locks do that work, both in db.crud where their exact SQL is
documented:

- `lock_invitation_slot` — an advisory lock on (inviter, tournament),
  taken by `send_invitation`, so the "max 3 pending" count and the insert
  that follows it are atomic. Row locks cannot serialize inserts.
- `lock_tournament_invitations_for_players` — `SELECT ... FOR UPDATE` over
  every invitation at the tournament involving either player, taken by
  `accept_invitation`, so the "is either player already matched?"
  re-verification and the ACCEPTED write are atomic.

A failed re-verification needs no explicit rollback: the failure paths
below return before mutating anything, so the transaction has nothing in
it to undo and its locks release at the caller's commit. The one write
they do make on the way out is deliberate — a PENDING invitation found
past its expiry is marked EXPIRED (CLAUDE.md allows expiry to be
evaluated lazily on read, and this is that read).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto

from sqlalchemy.ext.asyncio import AsyncSession

from db import crud
from db.models import Account, Invitation, InvitationState, Player, Tournament
from entitlements import can_send_invitation

logger = logging.getLogger(__name__)


# --- Sending ------------------------------------------------------------------


class SendFailure(Enum):
    """Every way a confirmed send can still fail, re-checked inside the
    send transaction rather than trusted from step 6."""

    NOT_ENTITLED = auto()
    INVITEE_NOT_ON_COURTDUO = auto()
    SELF_INVITE = auto()
    GENDER_MISMATCH = auto()
    INVITER_ALREADY_MATCHED = auto()
    INVITEE_ALREADY_MATCHED = auto()
    # CLAUDE.md step 8.3, PROBLEM 5: this inviter already sent this invitee
    # an invitation for this tournament that was REJECTED or NOT_ATTENDING
    # -- caught here too, not just by bot.partner_selection's pre-check,
    # since the answer may have landed seconds before this transaction
    # started.
    ALREADY_ANSWERED = auto()
    PENDING_INVITATION_EXISTS = auto()
    # PROBLEM 3 (CLAUDE.md, "Pre-invitation checks"): the invitee already
    # has a PENDING invitation to this player for this tournament -- caught
    # here too, not just by bot.partner_selection's pre-check, since that
    # invitation may have been sent seconds before this transaction started.
    ALREADY_INVITED_BY_INVITEE = auto()
    MAX_PENDING_REACHED = auto()
    TOURNAMENT_UNAVAILABLE = auto()


@dataclass
class SendResult:
    failure: SendFailure | None = None
    invitation: Invitation | None = None
    invitee_account: Account | None = None
    # The inviter's existing partner, for the INVITER_ALREADY_MATCHED
    # message only. Never populated for INVITEE_ALREADY_MATCHED: CLAUDE.md
    # forbids revealing who the *invited* player is already playing with.
    inviter_partner_pzt_id: str | None = None


async def send_invitation(
    session: AsyncSession, account: Account, tournament: Tournament, invitee: Player, now: datetime
) -> SendResult:
    """Creates one PENDING invitation from `account` to `invitee`, or
    explains why it can't.

    The caller must have shown the confirmation screen first — CLAUDE.md
    requires the "po akceptacji nie można zmienić partnera" warning before
    the invitation exists, not after.
    """
    # CLAUDE.md, "Monetisation": every invitation routes through this seam
    # even though it returns True until paid tiers launch. Step 6 asked it
    # too; this is the call that actually gates the write.
    if not await can_send_invitation(account, tournament):
        return SendResult(failure=SendFailure.NOT_ENTITLED)

    if invitee.pzt_id == account.pzt_id:
        return SendResult(failure=SendFailure.SELF_INVITE)

    event_gender = crud.gender_for_account_code(account.gender)
    if invitee.gender != event_gender:
        return SendResult(failure=SendFailure.GENDER_MISMATCH)

    invitee_account = await crud.get_account_by_pzt_id(session, invitee.pzt_id)
    if invitee_account is None:
        # CLAUDE.md scenario 2 (invite a non-user) is build order step 9;
        # until it exists there is nowhere to deliver this.
        return SendResult(failure=SendFailure.INVITEE_NOT_ON_COURTDUO)

    if tournament.search_closes_at is None or tournament.search_closes_at <= now or tournament.date_from is None:
        # `search_closes_at` is the invitation's expiry (10:00
        # Europe/Warsaw on the start date, stored as UTC by the scraper).
        # With it gone or past there is no valid expiry to give the row.
        return SendResult(failure=SendFailure.TOURNAMENT_UNAVAILABLE)

    event = await crud.get_doubles_event(session, tournament.guid, event_gender)
    if event is None:
        return SendResult(failure=SendFailure.TOURNAMENT_UNAVAILABLE)

    # Everything from here is under the slot lock, so a second send by the
    # same player for the same tournament waits rather than racing the
    # count below. Reads issued after the lock is granted see whatever the
    # transaction ahead committed: under READ COMMITTED each statement
    # takes a fresh snapshot.
    await crud.lock_invitation_slot(session, account.pzt_id, tournament.guid)

    inviter_match = await crud.get_matched_invitation(session, account.pzt_id, tournament.guid)
    if inviter_match is not None:
        partner_pzt_id = (
            inviter_match.invitee_pzt_id
            if inviter_match.inviter_pzt_id == account.pzt_id
            else inviter_match.inviter_pzt_id
        )
        # Step 6 checks this before asking for a name, but a player who
        # was matched *while* typing that name would otherwise slip
        # through — nothing re-ran that check between then and now.
        return SendResult(failure=SendFailure.INVITER_ALREADY_MATCHED, inviter_partner_pzt_id=partner_pzt_id)

    if await crud.get_matched_invitation(session, invitee.pzt_id, tournament.guid) is not None:
        return SendResult(failure=SendFailure.INVITEE_ALREADY_MATCHED)

    # PROBLEM 5: re-checked here too -- the pre-check in
    # bot.partner_selection ran seconds earlier and the answer could have
    # landed since.
    if await crud.get_answered_invitation(session, account.pzt_id, invitee.pzt_id, tournament.guid) is not None:
        return SendResult(failure=SendFailure.ALREADY_ANSWERED)

    if await crud.get_pending_invitation(session, account.pzt_id, invitee.pzt_id, tournament.guid) is not None:
        return SendResult(failure=SendFailure.PENDING_INVITATION_EXISTS)

    # PROBLEM 3: the reverse direction -- `invitee` may have invited
    # `account` a moment ago, after bot.partner_selection's pre-check ran
    # but before this transaction started. Two invitations chasing the same
    # pair is confusing and pointless; either being accepted matches them.
    if await crud.get_pending_invitation(session, invitee.pzt_id, account.pzt_id, tournament.guid) is not None:
        return SendResult(failure=SendFailure.ALREADY_INVITED_BY_INVITEE)

    pending = await crud.count_pending_outgoing_invitations(session, account.pzt_id, tournament.guid)
    if pending >= crud.MAX_PENDING_INVITATIONS_PER_TOURNAMENT:
        return SendResult(failure=SendFailure.MAX_PENDING_REACHED)

    invitation = await crud.create_invitation(
        session,
        inviter_pzt_id=account.pzt_id,
        invitee_pzt_id=invitee.pzt_id,
        tournament_guid=tournament.guid,
        event_id=event.id,
        expires_at=tournament.search_closes_at,
    )
    logger.info(
        "Invitation %s created (tournament=%s, expires_at=%s)",
        invitation.id,
        tournament.guid,
        invitation.expires_at.isoformat(),
    )
    return SendResult(invitation=invitation, invitee_account=invitee_account)


# --- Answering ----------------------------------------------------------------


class RespondFailure(Enum):
    NOT_FOUND = auto()
    # The tapper is not this invitation's invitee. Callback payloads are
    # client-supplied, so this is an authorization check, not a sanity one.
    NOT_YOURS = auto()
    ALREADY_ANSWERED = auto()
    # Cancelled by somebody else's accept: "Ten zawodnik znalazł już partnera."
    CANCELLED_BY_MATCH = auto()
    EXPIRED = auto()
    # The re-verification inside the accept transaction found one of the
    # two players already matched at this tournament.
    PLAYER_ALREADY_MATCHED = auto()


@dataclass
class RespondResult:
    failure: RespondFailure | None = None
    invitation: Invitation | None = None
    # Other invitations this accept cancelled, for both players
    # (CLAUDE.md: "first accept wins"). Their counterparties are the
    # players owed "Ten zawodnik znalazł już partnera."
    cancelled: list[Invitation] = field(default_factory=list)
    # PLAYER_ALREADY_MATCHED only. CLAUDE.md's rule for who may be named:
    # the responder learns they themselves are matched, but never who the
    # *other* player was matched with.
    responder_already_matched: bool = False


def _expire_if_due(invitation: Invitation, now: datetime) -> bool:
    """Marks a PENDING invitation EXPIRED if its moment has passed.

    CLAUDE.md allows expiry to be evaluated lazily on read instead of by a
    scheduled job, on the condition that a PENDING invitation past its
    expiry is never acceptable. This is that evaluation, and it runs
    inside the locked transaction so an accept can't slip past it.
    """
    if invitation.expires_at > now:
        return False
    invitation.state = InvitationState.EXPIRED
    return True


def _terminal_failure(state: InvitationState) -> RespondFailure:
    if state is InvitationState.CANCELLED:
        return RespondFailure.CANCELLED_BY_MATCH
    if state is InvitationState.EXPIRED:
        return RespondFailure.EXPIRED
    return RespondFailure.ALREADY_ANSWERED


async def accept_invitation(
    session: AsyncSession, invitation_id: int, responder_pzt_id: str, now: datetime
) -> RespondResult:
    """Zatwierdź — the transaction CLAUDE.md warns is most likely to break.

    Locks every invitation at this tournament involving either player,
    re-verifies inside that lock that neither of them is already matched
    and that this invitation is still a live PENDING row, then accepts it
    and cancels every other pending invitation for both players at this
    tournament ("first accept wins"). See
    db.crud.lock_tournament_invitations_for_players for why the lock is
    shaped the way it is.
    """
    invitation = await crud.get_invitation_by_id(session, invitation_id)
    if invitation is None:
        return RespondResult(failure=RespondFailure.NOT_FOUND)
    if invitation.invitee_pzt_id != responder_pzt_id:
        return RespondResult(failure=RespondFailure.NOT_YOURS)

    players = (invitation.inviter_pzt_id, invitation.invitee_pzt_id)
    locked = await crud.lock_tournament_invitations_for_players(session, invitation.tournament_guid, players)
    # The invitation itself is in `locked` — it involves both players by
    # definition — and `populate_existing` has just refreshed it from the
    # committed row, so every check below reads post-lock truth rather
    # than the snapshot taken above.
    current = next((row for row in locked if row.id == invitation_id), None)
    if current is None:
        return RespondResult(failure=RespondFailure.NOT_FOUND)

    if current.state is not InvitationState.PENDING:
        return RespondResult(failure=_terminal_failure(current.state), invitation=current)

    if _expire_if_due(current, now):
        logger.info("Invitation %s expired on read at accept time", current.id)
        return RespondResult(failure=RespondFailure.EXPIRED, invitation=current)

    already_matched = next((row for row in locked if row.state is InvitationState.ACCEPTED), None)
    if already_matched is not None:
        # Reached when a match exists that this transaction's sweep never
        # cancelled — e.g. an invitation created in the instant before the
        # other player's accept committed. Nothing has been mutated, so
        # there is nothing to undo; the accept simply does not happen.
        responder_matched = responder_pzt_id in (already_matched.inviter_pzt_id, already_matched.invitee_pzt_id)
        logger.info("Accept of invitation %s refused: a player is already matched", current.id)
        return RespondResult(
            failure=RespondFailure.PLAYER_ALREADY_MATCHED,
            invitation=current,
            responder_already_matched=responder_matched,
        )

    current.state = InvitationState.ACCEPTED
    cancelled = []
    for row in locked:
        if row.id != current.id and row.state is InvitationState.PENDING:
            row.state = InvitationState.CANCELLED
            cancelled.append(row)
    await session.flush()

    logger.info("Invitation %s accepted; %d other pending invitation(s) cancelled", current.id, len(cancelled))
    return RespondResult(invitation=current, cancelled=cancelled)


async def _answer_without_matching(
    session: AsyncSession, invitation_id: int, responder_pzt_id: str, now: datetime, state: InvitationState
) -> RespondResult:
    """Shared body of Odrzuć and "Nie jadę na ten turniej".

    Both are instant and free (CLAUDE.md): they close exactly one
    invitation, leave every other pending invitation for both players
    standing, and let the inviter invite somebody else immediately. The
    single-row lock is only there so this can't collide with an accept
    elsewhere cancelling the same row.
    """
    invitation = await crud.get_invitation_by_id(session, invitation_id)
    if invitation is None:
        return RespondResult(failure=RespondFailure.NOT_FOUND)
    if invitation.invitee_pzt_id != responder_pzt_id:
        return RespondResult(failure=RespondFailure.NOT_YOURS)

    current = await crud.lock_invitation(session, invitation_id)
    if current is None:
        return RespondResult(failure=RespondFailure.NOT_FOUND)
    if current.state is not InvitationState.PENDING:
        return RespondResult(failure=_terminal_failure(current.state), invitation=current)
    if _expire_if_due(current, now):
        return RespondResult(failure=RespondFailure.EXPIRED, invitation=current)

    current.state = state
    await session.flush()
    logger.info("Invitation %s answered %s", current.id, state.value)
    return RespondResult(invitation=current)


async def reject_invitation(
    session: AsyncSession, invitation_id: int, responder_pzt_id: str, now: datetime
) -> RespondResult:
    """Odrzuć. Nothing else changes — the invitee's other pending
    invitations stand, and so do the inviter's."""
    return await _answer_without_matching(
        session, invitation_id, responder_pzt_id, now, InvitationState.REJECTED
    )


async def not_attending_invitation(
    session: AsyncSession, invitation_id: int, responder_pzt_id: str, now: datetime
) -> RespondResult:
    """"Nie jadę na ten turniej" — CLAUDE.md's third answer.

    Identical machinery to a rejection, and deliberately so: it closes this
    one invitation and nothing else. It is **not** a stored fact about the
    player and the tournament. Nothing anywhere reads NOT_ATTENDING back to
    block, hide or filter a future invitation to the same player for the
    same tournament, and nothing may start — players change their minds,
    enter late and withdraw. Only the wording the two sides see differs
    (bot.invitation_text) -- the colour is the same 🔴 as a refusal
    (CLAUDE.md step 8.3, PROBLEM 2: "not happening" either way).
    """
    return await _answer_without_matching(
        session, invitation_id, responder_pzt_id, now, InvitationState.NOT_ATTENDING
    )


# --- Cancelling (CLAUDE.md step 8.6) -------------------------------------------


class CancelFailure(Enum):
    """Every way a cancel can fail. Unlike RespondFailure, a terminal state
    other than PENDING is split out per actual answer rather than collapsed
    into one ALREADY_ANSWERED — CLAUDE.md step 8.6 asks the inviter to be
    told *what* the answer was, not just that there was one."""

    NOT_FOUND = auto()
    # The tapper is not this invitation's inviter -- callback payloads are
    # client-supplied, so this is an authorization check, same as
    # RespondFailure.NOT_YOURS on the answering side.
    NOT_YOURS = auto()
    ALREADY_ACCEPTED = auto()
    ALREADY_REJECTED = auto()
    ALREADY_NOT_ATTENDING = auto()
    ALREADY_CANCELLED = auto()
    EXPIRED = auto()


@dataclass
class CancelResult:
    failure: CancelFailure | None = None
    invitation: Invitation | None = None


def _cancel_terminal_failure(state: InvitationState) -> CancelFailure:
    if state is InvitationState.ACCEPTED:
        return CancelFailure.ALREADY_ACCEPTED
    if state is InvitationState.REJECTED:
        return CancelFailure.ALREADY_REJECTED
    if state is InvitationState.NOT_ATTENDING:
        return CancelFailure.ALREADY_NOT_ATTENDING
    if state is InvitationState.EXPIRED:
        return CancelFailure.EXPIRED
    return CancelFailure.ALREADY_CANCELLED


async def cancel_invitation(
    session: AsyncSession, invitation_id: int, inviter_pzt_id: str, now: datetime
) -> CancelResult:
    """Withdraws a still-PENDING invitation at its sender's request
    (CLAUDE.md step 8.6). Same shape as _answer_without_matching — a
    single-row lock re-verifies the invitation is still PENDING before
    writing, since the invitee may have answered it a moment before this
    transaction started. A confirmed match is never reachable here: once a
    row is ACCEPTED, this returns ALREADY_ACCEPTED and touches nothing.

    A cancelled invitation frees the slot it held (CLAUDE.md, "what a
    cancelled invitation frees up"): db.crud.count_pending_outgoing_invitations
    only counts PENDING rows, and db.crud.get_answered_invitation only
    matches REJECTED/NOT_ATTENDING, so nothing further is needed here for
    either the pending-count limit or the re-invite block to reflect a
    cancel immediately -- CANCELLED simply isn't in either query's set.
    """
    invitation = await crud.get_invitation_by_id(session, invitation_id)
    if invitation is None:
        return CancelResult(failure=CancelFailure.NOT_FOUND)
    if invitation.inviter_pzt_id != inviter_pzt_id:
        return CancelResult(failure=CancelFailure.NOT_YOURS)

    current = await crud.lock_invitation(session, invitation_id)
    if current is None:
        return CancelResult(failure=CancelFailure.NOT_FOUND)
    if current.state is not InvitationState.PENDING:
        return CancelResult(failure=_cancel_terminal_failure(current.state), invitation=current)
    if _expire_if_due(current, now):
        return CancelResult(failure=CancelFailure.EXPIRED, invitation=current)

    current.state = InvitationState.CANCELLED
    await session.flush()
    logger.info("Invitation %s cancelled by its inviter", current.id)
    return CancelResult(invitation=current)
