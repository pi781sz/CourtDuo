"""Declarative base and shared column mixins for all CourtDuo tables."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class CreatedAtMixin:
    """`created_at` only, for rows that are written once and never change
    (e.g. matches — a confirmed pairing is final, see CLAUDE.md "First
    accept wins")."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TimestampMixin(CreatedAtMixin):
    """`created_at` + `updated_at`, for rows whose fields change after insert."""

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
