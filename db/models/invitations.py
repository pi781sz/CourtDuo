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

A `PendingExternalInvite` records an invitation sent to a typed name that
isn't on CourtDuo yet (CLAUDE.md scenario 2), keyed on the typed name
rather than a player row, since there is no player row to key on until
that person registers.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
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

    inviter: Mapped["Player"] = relationship(foreign_keys=[inviter_pzt_id], back_populates="sent_invitations")
    invitee: Mapped["Player"] = relationship(foreign_keys=[invitee_pzt_id], back_populates="received_invitations")
    tournament: Mapped["Tournament"] = relationship()
    event: Mapped["Event"] = relationship()


class PendingExternalInvite(CreatedAtMixin, Base):
    __tablename__ = "pending_external_invites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inviter_pzt_id: Mapped[str] = mapped_column(
        String, ForeignKey("players.pzt_id", ondelete="CASCADE"), nullable=False
    )
    typed_name: Mapped[str] = mapped_column(String, nullable=False)
    tournament_guid: Mapped[str] = mapped_column(
        String, ForeignKey("tournaments.guid", ondelete="CASCADE"), nullable=False
    )

    inviter: Mapped["Player"] = relationship(back_populates="pending_external_invites")
    tournament: Mapped["Tournament"] = relationship()
