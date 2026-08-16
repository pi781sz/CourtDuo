"""Maps one delivered support-relay message (CLAUDE.md, "Operations" >
"Support") back to the user it came from, so an operator's native
Telegram reply can be routed to the right recipient.

One row per (operator, delivered message): a `/pomoc` message relayed to
three operators writes three rows, each keyed on that operator's own copy
of the message, so whichever one replies routes correctly regardless of
which operator answers.

Deliberately does not store the message body -- this table only answers
"which user does this operator message belong to"; Telegram already holds
the conversation, and CourtDuo does not need a second, stored copy of a
child's message. Must be a table, not memory: the bot runs under
`Restart=always` and the Dispatcher uses `MemoryStorage`, so an in-memory
mapping would break every reply across a restart -- the same reasoning
CLAUDE.md already gives for `alarm_state`.
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedAtMixin


class SupportThread(CreatedAtMixin, Base):
    __tablename__ = "support_threads"
    __table_args__ = (UniqueConstraint("operator_chat_id", "operator_message_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    operator_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    operator_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
