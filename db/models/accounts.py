"""One Telegram account is one PZT player (CLAUDE.md, "Identity"). There is
no adult/child distinction and no multi-player account — registration links
a `telegram_id` to exactly one `players.pzt_id`, which the player already
knows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin
from .enums import Plan, value_enum

if TYPE_CHECKING:
    from .players import Player


class Account(TimestampMixin, Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    pzt_id: Mapped[str] = mapped_column(
        String, ForeignKey("players.pzt_id", ondelete="CASCADE"), unique=True, nullable=False
    )

    # CLAUDE.md, "Monetisation — build now, enable later": every invitation
    # creation must route through db.crud.can_send_invitation rather than
    # reading these columns directly.
    plan: Mapped[Plan] = mapped_column(
        value_enum(Plan, "plan"), nullable=False, default=Plan.FREE, server_default=Plan.FREE.value
    )
    invitations_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    lang: Mapped[str] = mapped_column(String(2), nullable=False, default="pl", server_default="pl")

    player: Mapped["Player"] = relationship(back_populates="account")
