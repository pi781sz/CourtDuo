"""Persistent per-scraper alarm state (CLAUDE.md "Operations"). Must be a
table, not an in-memory flag: the bot runs under `Restart=always`
(DEPLOY.md), and in-memory state would send one fresh alert per crash
loop instead of one alert followed by silence until recovery.

One row per scraper (`key` is the scraper name, e.g. "tournaments").
`firing` is whether the alarm is currently active for that scraper;
`last_sent_at` is when a message was last sent for it, used by
bot.staleness to decide whether a further reminder is due.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class AlarmState(Base):
    __tablename__ = "alarm_state"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    firing: Mapped[bool] = mapped_column(Boolean, nullable=False)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
