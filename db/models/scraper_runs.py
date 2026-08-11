"""One row per invocation of a scraper (CLAUDE.md "Operations": the
staleness alarm). Written by scrapers.tournaments.__main__ and
scrapers.rankings.__main__ on every real run -- including a failed one --
so bot.staleness can tell a scraper that is actively failing from one
that has simply stopped running at all. `--dry-run`, `--dump-html` and
`--dump-index-html` are debugging paths and write nothing here.

`ok=False` covers three cases (see the two __main__ modules): the scrape
raised, the rankings scraper could not discover the published period, or
items_seen/items_written came back zero -- a parser failure, not a quiet
month (CLAUDE.md "Tournament selection"/"Rankings"). A run of failures
does not reset bot.staleness's clock: it only ever looks at the newest
row with ok=True.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ScraperRun(Base):
    __tablename__ = "scraper_runs"
    __table_args__ = (Index("ix_scraper_runs_scraper_finished_at", "scraper", "finished_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scraper: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    items_seen: Mapped[int | None] = mapped_column(Integer, nullable=True)
    items_written: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Short failure summary (exception class + message, truncated to ~500
    # chars) when ok is False. Never a full stack trace, and never
    # anything containing a player name -- CLAUDE.md rule 4 applies to
    # this column exactly as it does to a fixture file.
    detail: Mapped[str | None] = mapped_column(String, nullable=True)
