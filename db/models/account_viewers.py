"""Read-only viewers (CLAUDE.md, "Identity": step 10 — a separate,
revocable, read-only relationship a player grants on top of their own
one-account-one-player identity; allowlisted test feature).

`ViewerInviteToken` is the single-use, 24-hour-lived deep-link token a
player generates from their own account (bot.viewers.create_invite_token)
and hands to whoever they want watching. `AccountViewer` is the resulting
grant, created once the token is consumed (bot.viewers.bind_viewer).

A viewer_telegram_id is deliberately not unique across accounts: the same
Telegram account can hold active grants from several different players,
each granted independently (the unique index below is scoped to one
(account_id, viewer_telegram_id) pair, not to viewer_telegram_id alone).
bot.handlers.viewers's read-only Moje deble has to account for that.

`revoked_at` is nullable rather than the row being deleted on revocation:
revocation must be instant and the grant/revoke history worth keeping, the
same reasoning CLAUDE.md's invitation engine applies to CANCELLED rows.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, CreatedAtMixin

if TYPE_CHECKING:
    from .accounts import Account


class AccountViewer(Base):
    __tablename__ = "account_viewers"
    __table_args__ = (
        # "Unique on (account_id, viewer_telegram_id) where revoked_at is
        # null" (task spec, DATA) -- a revoked grant must not block the
        # same viewer being re-granted later, so uniqueness only applies
        # among currently-active rows.
        Index(
            "uq_account_viewers_active",
            "account_id",
            "viewer_telegram_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    viewer_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    account: Mapped["Account"] = relationship()


class ViewerInviteToken(CreatedAtMixin, Base):
    __tablename__ = "viewer_invite_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    token: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    account: Mapped["Account"] = relationship()
