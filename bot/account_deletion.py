"""Account deletion (CLAUDE.md, "Not yet built" -> step 12, "Account
deletion and blocking"). Mirrors bot.invitation_engine's split: the
transaction lives here, no Telegram; bot.handlers.account_deletion does
the talking and pushes the notifications this module's result implies.

Deleting alone would let a player re-register in seconds with the same
PZT id -- see bot.registration and db.crud.is_pzt_id_blocked for the
separate, deliberately harder-to-reach mechanism (blocked_pzt_ids,
written only by a human at psql) that survives this deletion.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from bot.moje_deble import tournament_finished
from db import crud
from db.models import Account, Invitation, InvitationState

logger = logging.getLogger(__name__)


@dataclass
class DeletionResult:
    deleted_pzt_id: str
    deleted_full_name: str
    deleted_gender: str
    deleted_telegram_id: int
    # PENDING invitations this account SENT, now CANCELLED -- each invitee
    # is owed a "cancelled" notification (CLAUDE.md step 12: "pending
    # invitations they SENT are cancelled; each invitee is notified
    # normally").
    cancelled_sent: list[Invitation] = field(default_factory=list)
    # PENDING invitations this account RECEIVED, now CANCELLED -- each
    # inviter is owed the same, symmetric notification.
    cancelled_received: list[Invitation] = field(default_factory=list)
    # ACCEPTED invitations left untouched -- each partner is owed the
    # "confirm in person" notification (CLAUDE.md step 12, "What happens
    # to a confirmed partner").
    confirmed_matches: list[Invitation] = field(default_factory=list)


async def delete_account(session: AsyncSession, account: Account, today: date) -> DeletionResult:
    """The whole of CLAUDE.md step 12's "Self-service deletion" +
    "What is actually erased, and what is kept", in one transaction.

    Every PENDING invitation involving this pzt_id is re-locked
    (db.crud.lock_invitation) before being touched, the same discipline
    bot.invitation_engine.cancel_invitation applies -- an accept elsewhere
    can land in the gap between reading this player's invitations and
    acting on them, and a row that turned ACCEPTED in that gap must be
    treated as a confirmed match, not silently cancelled out from under
    the player who just accepted it.

    The caller commits; this only flushes (same convention as
    bot.invitation_engine and db.crud.create_account).
    """
    pzt_id = account.pzt_id
    full_name = account.full_name
    gender = account.gender
    telegram_id = account.telegram_id

    invitations = await crud.get_invitations_for_player(session, pzt_id)
    result = DeletionResult(
        deleted_pzt_id=pzt_id, deleted_full_name=full_name, deleted_gender=gender, deleted_telegram_id=telegram_id
    )

    # CLAUDE.md step 12, "What is actually erased, and what is kept":
    # "invitation rows for tournaments that have not finished, carrying a
    # NAME SNAPSHOT of the deleted player." Written before the account row
    # itself is gone, on every row this pzt_id appears in on either side,
    # regardless of state -- REJECTED/NOT_ATTENDING/CANCELLED/EXPIRED rows
    # get one too even though they're already hidden from Moje deble,
    # since "nothing is deleted from the database" already keeps them
    # around for the results-based verification planned later.
    for invitation in invitations:
        tournament = invitation.tournament
        if tournament_finished(tournament.date_from, tournament.date_to, today):
            continue
        if invitation.inviter_pzt_id == pzt_id:
            invitation.inviter_name_snapshot = full_name
        if invitation.invitee_pzt_id == pzt_id:
            invitation.invitee_name_snapshot = full_name

    for invitation in invitations:
        if invitation.state is InvitationState.ACCEPTED:
            result.confirmed_matches.append(invitation)
            continue
        if invitation.state is not InvitationState.PENDING:
            continue

        current = await crud.lock_invitation(session, invitation.id)
        if current is None:
            continue
        if current.state is InvitationState.ACCEPTED:
            # Accepted by the other side in the gap between the read above
            # and this lock -- it is now a confirmed match, not a PENDING
            # row to cancel.
            result.confirmed_matches.append(current)
            continue
        if current.state is not InvitationState.PENDING:
            continue

        current.state = InvitationState.CANCELLED
        if current.inviter_pzt_id == pzt_id:
            result.cancelled_sent.append(current)
        else:
            result.cancelled_received.append(current)

    # CLAUDE.md step 12, "What is actually erased": "referrer records,
    # pending external invites" -- both phrases name the one mechanism
    # this codebase has for a "share this invite" attempt against a
    # non-user (db.models.PendingExternalInvite), keyed on inviter_pzt_id.
    await crud.delete_pending_external_invites_by_inviter(session, pzt_id)

    # account_viewers and viewer_invite_tokens both carry ondelete="CASCADE"
    # foreign keys to accounts.id, so this one DELETE also removes every
    # viewer grant and invite token for this account -- CLAUDE.md step 12:
    # "the account row and its viewers go."
    await crud.delete_account(session, account)

    logger.info("Account deleted: telegram_id=%s", telegram_id)
    return result


async def purge_finished_tournament_snapshots(session: AsyncSession, today: date) -> int:
    """CLAUDE.md step 12: "Purge those snapshots once the tournament has
    finished. Add this to the same periodic task that already runs the
    staleness check." Called from bot.staleness's own 6-hour loop
    (bot.staleness._loop) rather than a scheduler of its own. Returns the
    number of invitation rows touched, purely for the caller to log.
    """
    purged = await crud.purge_finished_tournament_name_snapshots(session, today)
    if purged:
        logger.info("Purged name snapshots on %d invitation row(s) for finished tournaments", purged)
    return purged
