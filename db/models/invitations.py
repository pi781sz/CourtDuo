"""The invitation engine's tables (CLAUDE.md, "Invitation engine").

An `Invitation` is a structured, one-shot ask from `inviter_pzt_id` to
`invitee_pzt_id` for one event of one tournament. It moves through
PENDING -> ACCEPTED/REJECTED/NOT_ATTENDING/CANCELLED/EXPIRED in place.
`expires_at` is set by the caller per CLAUDE.md's
10:00-Europe/Warsaw-on-start-date rule; nothing here computes it, since
that depends on the tournament's start date which only the caller has in
hand at invitation-creation time.

A pair can appear in more than one row over time: an invitation answered
REJECTED or NOT_ATTENDING may be followed by a fresh PENDING one for the
same two players and the same tournament. That is deliberate and load
bearing — CLAUDE.md forbids "nie jadę na ten turniej" from becoming a
stored fact that blocks, hides or filters any future invitation, so
nothing here or in db.crud may ever key uniqueness on (inviter, invitee,
tournament).

Two constraints CLAUDE.md asks to be enforced "in the database, not only
in application code" can't be expressed as plain SQLAlchemy/Postgres
column constraints, since both are counts/lookups across sibling rows
rather than a fixed key:

- max 3 PENDING outgoing invitations per (inviter, tournament)
- at most one ACCEPTED invitation per tournament per player, whether
  they appear as inviter or invitee in it

Both are enforced by Postgres trigger functions created in the Alembic
migration (`enforce_max_pending_invitations`,
`enforce_single_accepted_invitation`), not by anything in this module —
SQLAlchemy's declarative layer has no construct for either shape of rule.
The application-level pre-invitation checks in CLAUDE.md's "Pre-invitation
checks" section exist to give a player a friendly error *before* hitting
these triggers, not to replace them.

A `PendingExternalInvite` records an invitation attempt against a named
player who is on PZT's roster but has no CourtDuo account yet (CLAUDE.md
scenario 2; build order step 9). Keyed on `invitee_pzt_id`, not the typed
string -- step 6's name matching (including disambiguation) already
resolved the typed name to a specific `players` row before this is
written, so there is a real player to key on even though there is no
`accounts` row yet. When that pzt_id later registers, db.crud looks up
every row here matching it and notifies each `inviter_pzt_id` still
eligible to be told.

`inviter_name_snapshot`/`invitee_name_snapshot` (CLAUDE.md step 12,
"What is actually erased, and what is kept"): a copy of that side's
`accounts.full_name`, written only when that side's account is deleted
(bot.account_deletion.delete_account). `players.full_name` itself is never
erased -- it is PZT's own public roster data, kept regardless of any
CourtDuo account -- but Moje deble's *display* of a deleted player's name
on a still-open invitation is deliberately not tied to that permanent
roster copy: it reads the snapshot instead (bot.moje_deble), so the
snapshot -- and only the snapshot -- can be purged once the tournament
finishes (bot.account_deletion.purge_finished_tournament_snapshots, run
off the same periodic loop as the staleness check). A snapshot is cleared
if the same pzt_id ever registers again before that purge runs
(db.crud.clear_name_snapshots_for_pzt_id, called from
bot.registration.register_by_pzt_id) so a returning player's own match
goes back to showing 🟢 normally instead of a stale "confirm in person".
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, CreatedAtMixin, TimestampMixin
from .enums import InvitationState, value_enum

if TYPE_CHECKING:
    from .players import Player
    from .tournaments import Event, Tournament


class Invitation(TimestampMixin, Base):
    __tablename__ = "invitations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inviter_pzt_id: Mapped[str] = mapped_column(
        String, ForeignKey("players.pzt_id", ondelete="CASCADE"), nullable=False
    )
    invitee_pzt_id: Mapped[str] = mapped_column(
        String, ForeignKey("players.pzt_id", ondelete="CASCADE"), nullable=False
    )
    tournament_guid: Mapped[str] = mapped_column(
        String, ForeignKey("tournaments.guid", ondelete="CASCADE"), nullable=False
    )
    event_id: Mapped[int] = mapped_column(Integer, ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    state: Mapped[InvitationState] = mapped_column(
        value_enum(InvitationState, "invitation_state"),
        nullable=False,
        default=InvitationState.PENDING,
        server_default=InvitationState.PENDING.value,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # The Telegram message id of the notification pushed to the invitee
    # when this invitation was sent (bot.handlers.invitations.handle_confirm_send).
    # CLAUDE.md step 8.6: lets a later cancel best-effort strip that
    # message's three answer buttons via edit_message_reply_markup, so a
    # withdrawn invitation cannot still be tapped from the screen it first
    # arrived on. Never set for an invitation whose push failed (there is
    # no message to point at); a cancel with no id here simply skips the
    # edit -- the transaction re-check is what actually prevents an answer,
    # this is cosmetic only.
    invitee_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # CLAUDE.md step 12: set only when the corresponding side's account has
    # been deleted -- see the module docstring. Null for the overwhelming
    # majority of rows, whose accounts are alive and whose display always
    # reads the live `players.full_name` join instead.
    inviter_name_snapshot: Mapped[str | None] = mapped_column(String, nullable=True)
    invitee_name_snapshot: Mapped[str | None] = mapped_column(String, nullable=True)

    inviter: Mapped["Player"] = relationship(foreign_keys=[inviter_pzt_id], back_populates="sent_invitations")
    invitee: Mapped["Player"] = relationship(foreign_keys=[invitee_pzt_id], back_populates="received_invitations")
    tournament: Mapped["Tournament"] = relationship()
    event: Mapped["Event"] = relationship()


class PendingExternalInvite(CreatedAtMixin, Base):
    __tablename__ = "pending_external_invites"
    __table_args__ = (
        UniqueConstraint(
            "inviter_pzt_id",
            "invitee_pzt_id",
            "tournament_guid",
            name="uq_pending_external_invite_inviter_invitee_tournament",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inviter_pzt_id: Mapped[str] = mapped_column(
        String, ForeignKey("players.pzt_id", ondelete="CASCADE"), nullable=False
    )
    invitee_pzt_id: Mapped[str] = mapped_column(
        String, ForeignKey("players.pzt_id", ondelete="CASCADE"), nullable=False
    )
    tournament_guid: Mapped[str] = mapped_column(
        String, ForeignKey("tournaments.guid", ondelete="CASCADE"), nullable=False
    )

    inviter: Mapped["Player"] = relationship(
        foreign_keys=[inviter_pzt_id], back_populates="pending_external_invites"
    )
    invitee: Mapped["Player"] = relationship(foreign_keys=[invitee_pzt_id])
    tournament: Mapped["Tournament"] = relationship()
