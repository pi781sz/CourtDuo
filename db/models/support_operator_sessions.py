"""One row per operator currently in an open reply conversation with a
player (CLAUDE.md, "Operations" > "Support"). Its presence is what "this
operator has a conversation open" means -- deleted on close, or on lazy
60-minute expiry (bot.middlewares.support_conversation, evaluated on the
next message that arrives from that operator, no scheduler).

A table, not memory, for the same `Restart=always` / `MemoryStorage`
reasoning as `support_conversations` and `alarm_state`.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class SupportOperatorSession(Base):
    __tablename__ = "support_operator_sessions"

    operator_telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
