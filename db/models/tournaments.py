"""Tournaments and events are modelled separately (CLAUDE.md, "Data
sources"): a tournament is the overall competition; an event is one
`Kategoria: ... Typ: ...` line inside its `Rozgrywki` block. Most
tournaments have no `Gra podwójna` event at all — `Event.is_doubles` is
the flag everything downstream (search creation) filters on.

`guid` is PZT's own tournament identifier (extracted from the results
link, see scrapers.tournaments.parser) and is used as the natural primary
key, since it's what re-running the scraper upserts against.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin
from .enums import AgeCategory, Gender, PlayType

if TYPE_CHECKING:
    from .matching import Search


class Tournament(TimestampMixin, Base):
    __tablename__ = "tournaments"

    guid: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    type_prefix: Mapped[str | None] = mapped_column(String, nullable=True)
    age_category: Mapped[AgeCategory] = mapped_column(SAEnum(AgeCategory, name="age_category"), nullable=False)
    ranga: Mapped[int | None] = mapped_column(Integer, nullable=True)
    date_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    wojewodztwo: Mapped[str | None] = mapped_column(String, nullable=True)

    # Naive, Europe/Warsaw local wall-clock time exactly as PZT renders it
    # (scrapers.tournaments.parser never attaches a tzinfo to these two).
    entry_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    withdrawal_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)

    # UTC instant. See Tournament.search_closes_at in
    # scrapers/tournaments/models.py for the 10:00 Europe/Warsaw ->  UTC
    # conversion — searches stay open until this instant regardless of
    # entry_deadline (CLAUDE.md, "Matching engine").
    search_closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    events: Mapped[list["Event"]] = relationship(back_populates="tournament", cascade="all, delete-orphan")


class Event(TimestampMixin, Base):
    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("tournament_guid", "category_label", "gender", "play_type", name="uq_event_identity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tournament_guid: Mapped[str] = mapped_column(
        String, ForeignKey("tournaments.guid", ondelete="CASCADE"), nullable=False
    )
    category_label: Mapped[str] = mapped_column(String, nullable=False)
    gender: Mapped[Gender] = mapped_column(SAEnum(Gender, name="gender"), nullable=False)
    play_type: Mapped[PlayType] = mapped_column(SAEnum(PlayType, name="play_type"), nullable=False)
    draw_format: Mapped[str | None] = mapped_column(String, nullable=True)
    is_doubles: Mapped[bool] = mapped_column(Boolean, nullable=False)

    tournament: Mapped["Tournament"] = relationship(back_populates="events")
    searches: Mapped[list["Search"]] = relationship(back_populates="event", cascade="all, delete-orphan")
