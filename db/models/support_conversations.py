"""Whether a player's plain text right now should be relayed to support
(CLAUDE.md, "Operations" > "Support", "open conversation"). One row per
Telegram id that has ever run /pomoc.

`is_open` plus a lazy 30-minute idle check against `last_activity_at` (see
bot.middlewares.support_conversation -- evaluated on the next message that
arrives, no scheduler) is the whole state machine. A table, not FSM state,
because the bot runs under `Restart=always` and the Dispatcher uses
`MemoryStorage` -- an in-memory flag would silently reroute a child's next
message to the wrong place after every restart, the same reasoning
CLAUDE.md already gives for `alarm_state` and `support_threads`.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class SupportConversation(Base):
    __tablename__ = "support_conversations"

    user_telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    is_open: Mapped[bool] = mapped_column(Boolean, nullable=False)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
