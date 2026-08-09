"""A player is a junior registered with PZT. `pzt_id` is PZT's own id for
them (read off the alphabetical ranking roster, see scrapers.rankings) and
is used as the natural primary key rather than a surrogate id, since it's
exactly what invitation-target search and ranking upserts key off.

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
    from .accounts import Account
    from .invitations import Invitation, PendingExternalInvite
    from .rankings import Ranking


class Player(TimestampMixin, Base):
    __tablename__ = "players"

    pzt_id: Mapped[str] = mapped_column(String, primary_key=True)
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    club: Mapped[str | None] = mapped_column(String, nullable=True)
    age_category: Mapped[AgeCategory | None] = mapped_column(SAEnum(AgeCategory, name="age_category"), nullable=True)
    gender: Mapped[Gender | None] = mapped_column(SAEnum(Gender, name="gender"), nullable=True)

    rankings: Mapped[list["Ranking"]] = relationship(back_populates="player", cascade="all, delete-orphan")
    account: Mapped["Account | None"] = relationship(back_populates="player", uselist=False, cascade="all, delete-orphan")
    sent_invitations: Mapped[list["Invitation"]] = relationship(
        foreign_keys="Invitation.inviter_pzt_id", back_populates="inviter", cascade="all, delete-orphan"
    )
    received_invitations: Mapped[list["Invitation"]] = relationship(
        foreign_keys="Invitation.invitee_pzt_id", back_populates="invitee", cascade="all, delete-orphan"
    )
    pending_external_invites: Mapped[list["PendingExternalInvite"]] = relationship(
        foreign_keys="PendingExternalInvite.inviter_pzt_id",
        back_populates="inviter",
        cascade="all, delete-orphan",
    )
