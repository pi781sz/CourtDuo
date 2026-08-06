"""The matching engine's tables (CLAUDE.md, "Matching engine").

A `Search` is one player's open slot for one event, `player_pzt_id` +
`event_id` unique together — "One active search per (player, event).
Enforce with a unique constraint." A search row is updated in place as it
moves through OPEN -> REQUESTED -> MATCHED/REJECTED/EXPIRED; it is never
re-inserted for the same pair.

A `Request` is one outgoing partner request between two searches
(`from_search_id`/`to_search_id`), unique per ordered pair for the same
reason. `expires_at` is set by the caller per CLAUDE.md's 24h-or-10:00
rule; nothing here computes it, since that depends on the tournament's
start date which only the caller has in hand at request-creation time.

A `Match` is the final, immutable outcome of one accepted request —
CLAUDE.md's "atomic locking" (`SELECT ... FOR UPDATE` both search rows,
re-verify unmatched, commit) is an application-level transaction, not
something the schema can enforce; the unique constraint on each of
search_a_id/search_b_id here only guarantees a search can't end up in two
matches.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, CreatedAtMixin, TimestampMixin
from .enums import RequestState, SearchState

if TYPE_CHECKING:
    from .players import Player
    from .tournaments import Event


class Search(TimestampMixin, Base):
    __tablename__ = "searches"
    __table_args__ = (UniqueConstraint("player_pzt_id", "event_id", name="uq_search_player_event"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_pzt_id: Mapped[str] = mapped_column(
        String, ForeignKey("players.pzt_id", ondelete="CASCADE"), nullable=False
    )
    event_id: Mapped[int] = mapped_column(Integer, ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    state: Mapped[SearchState] = mapped_column(
        SAEnum(SearchState, name="search_state"),
        nullable=False,
        default=SearchState.OPEN,
        server_default=SearchState.OPEN.value,
    )

    player: Mapped["Player"] = relationship(back_populates="searches")
    event: Mapped["Event"] = relationship(back_populates="searches")
    outgoing_requests: Mapped[list["Request"]] = relationship(
        foreign_keys="Request.from_search_id", back_populates="from_search", cascade="all, delete-orphan"
    )
    incoming_requests: Mapped[list["Request"]] = relationship(
        foreign_keys="Request.to_search_id", back_populates="to_search", cascade="all, delete-orphan"
    )


class Request(TimestampMixin, Base):
    __tablename__ = "requests"
    __table_args__ = (UniqueConstraint("from_search_id", "to_search_id", name="uq_request_pair"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    from_search_id: Mapped[int] = mapped_column(Integer, ForeignKey("searches.id", ondelete="CASCADE"), nullable=False)
    to_search_id: Mapped[int] = mapped_column(Integer, ForeignKey("searches.id", ondelete="CASCADE"), nullable=False)
    state: Mapped[RequestState] = mapped_column(
        SAEnum(RequestState, name="request_state"),
        nullable=False,
        default=RequestState.PENDING,
        server_default=RequestState.PENDING.value,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    from_search: Mapped["Search"] = relationship(foreign_keys=[from_search_id], back_populates="outgoing_requests")
    to_search: Mapped["Search"] = relationship(foreign_keys=[to_search_id], back_populates="incoming_requests")


class Match(CreatedAtMixin, Base):
    __tablename__ = "matches"
    __table_args__ = (
        UniqueConstraint("search_a_id", name="uq_match_search_a"),
        UniqueConstraint("search_b_id", name="uq_match_search_b"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    search_a_id: Mapped[int] = mapped_column(Integer, ForeignKey("searches.id", ondelete="CASCADE"), nullable=False)
    search_b_id: Mapped[int] = mapped_column(Integer, ForeignKey("searches.id", ondelete="CASCADE"), nullable=False)

    search_a: Mapped["Search"] = relationship(foreign_keys=[search_a_id])
    search_b: Mapped["Search"] = relationship(foreign_keys=[search_b_id])
