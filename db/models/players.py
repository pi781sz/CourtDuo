"""A player is a junior registered with PZT. `pzt_id` is PZT's own id for
them (read off the alphabetical ranking roster, see scrapers.rankings) and
is used as the natural primary key rather than a surrogate id, since it's
exactly what registration search and ranking upserts key off.

full_name/club/age_category/gender are a snapshot of the player's latest
scraped ranking row (see db.crud.upsert_ranking_entry) — CourtDuo doesn't
scrape player profile pages, so this is the only source for them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Enum as SAEnum
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin
from .enums import AgeCategory, Gender

if TYPE_CHECKING:
    from .accounts import AccountPlayer
    from .matching import Search
    from .rankings import Ranking


class Player(TimestampMixin, Base):
    __tablename__ = "players"

    pzt_id: Mapped[str] = mapped_column(String, primary_key=True)
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    club: Mapped[str | None] = mapped_column(String, nullable=True)
    age_category: Mapped[AgeCategory | None] = mapped_column(SAEnum(AgeCategory, name="age_category"), nullable=True)
    gender: Mapped[Gender | None] = mapped_column(SAEnum(Gender, name="gender"), nullable=True)

    rankings: Mapped[list["Ranking"]] = relationship(back_populates="player", cascade="all, delete-orphan")
    account_links: Mapped[list["AccountPlayer"]] = relationship(back_populates="player", cascade="all, delete-orphan")
    searches: Mapped[list["Search"]] = relationship(back_populates="player", cascade="all, delete-orphan")
