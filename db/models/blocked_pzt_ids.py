"""Blocking (CLAUDE.md, "Not yet built" -> "Account deletion and
blocking"; step 12). Blocking has to survive deletion -- a blocked
player's own `accounts` row is gone the moment they're blocked-and-
deleted, so it cannot be a column on `accounts`. This is its own table,
keyed on `pzt_id` alone, with no foreign key to `players` either: PZT's
roster is scraper-maintained and a blocked pzt_id must stay blocked even
if it briefly drops off a ranking list and the scraper's `players` row
goes stale.

Written and read only via psql by a human operator (CLAUDE.md step 12:
"No admin path in the bot. No Telegram command, for anyone, ever.") --
see docs/RUNBOOK.md. The bot only ever reads this table
(db.crud.is_pzt_id_blocked), at registration and at invitation send/accept
time.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class BlockedPztId(Base):
    __tablename__ = "blocked_pzt_ids"

    pzt_id: Mapped[str] = mapped_column(String, primary_key=True)
    blocked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
