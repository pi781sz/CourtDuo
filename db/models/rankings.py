"""One row per (player, ranking_list, year, month) PZT publication.

History is kept deliberately — a new month's scrape inserts new rows
rather than overwriting the previous month's, since past position is
useful context. The bot always reads the newest (year, month) for a given
ranking_list (see db.crud.get_latest_ranking_period), never assumes it,
matching CLAUDE.md's "Do not hardcode or increment Year/Month."
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin
from .enums import RankingList

if TYPE_CHECKING:
    from .players import Player


class Ranking(TimestampMixin, Base):
    __tablename__ = "rankings"
    __table_args__ = (
        UniqueConstraint("player_pzt_id", "ranking_list", "year", "month", name="uq_ranking_period"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_pzt_id: Mapped[str] = mapped_column(
        String, ForeignKey("players.pzt_id", ondelete="CASCADE"), nullable=False
    )
    ranking_list: Mapped[RankingList] = mapped_column(SAEnum(RankingList, name="ranking_list"), nullable=False)
    position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)

    player: Mapped["Player"] = relationship(back_populates="rankings")
