"""Accounts belong to adults, not players (CLAUDE.md, "Accounts belong to
adults"). One account may manage several players via `account_players`
(siblings, or a coach's squad).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, CreatedAtMixin, TimestampMixin
from .enums import AccountRole, Plan, value_enum

if TYPE_CHECKING:
    from .players import Player


class Account(TimestampMixin, Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    role: Mapped[AccountRole] = mapped_column(value_enum(AccountRole, "account_role"), nullable=False)

    # CLAUDE.md, "Monetisation — build now, enable later": every search
    # creation must route through db.crud.can_start_search rather than
    # reading these columns directly.
    plan: Mapped[Plan] = mapped_column(
        value_enum(Plan, "plan"), nullable=False, default=Plan.FREE, server_default=Plan.FREE.value
    )
    searches_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    lang: Mapped[str] = mapped_column(String(2), nullable=False, default="pl", server_default="pl")

    player_links: Mapped[list["AccountPlayer"]] = relationship(back_populates="account", cascade="all, delete-orphan")


class AccountPlayer(CreatedAtMixin, Base):
    """Join table: which account(s) manage which player(s)."""

    __tablename__ = "account_players"

    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    player_pzt_id: Mapped[str] = mapped_column(
        String, ForeignKey("players.pzt_id", ondelete="CASCADE"), primary_key=True
    )

    account: Mapped["Account"] = relationship(back_populates="player_links")
    player: Mapped["Player"] = relationship(back_populates="account_links")
