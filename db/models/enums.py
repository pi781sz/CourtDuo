"""Enum types shared by the database models.

AgeCategory, Gender, PlayType and RankingList are the exact enums the
scrapers already parse PZT pages into (see scrapers.tournaments.models
and scrapers.rankings.models). They're re-exported here rather than
redefined, so there is exactly one place that knows PZT's vocabulary
("Chłopcy"/"Dziewczęta", "Gra podwójna", the M12/W12/... ranking codes)
and db.crud can hand a scraped dataclass's enum straight to a model
column with no translation step.

AccountRole/Plan/SearchState/RequestState are domain concepts with no
scraper equivalent, so they're defined here directly.
"""

from __future__ import annotations

import enum

from sqlalchemy import Enum as SAEnum

from scrapers.rankings.models import RankingList
from scrapers.tournaments.models import AgeCategory, Gender, PlayType

__all__ = [
    "AgeCategory",
    "Gender",
    "PlayType",
    "RankingList",
    "AccountRole",
    "Plan",
    "SearchState",
    "RequestState",
]


class AccountRole(enum.Enum):
    """CLAUDE.md, "Accounts belong to adults": the role an account holder identifies as."""

    RODZIC = "rodzic"
    OPIEKUN = "opiekun"
    TRENER = "trener"


class Plan(enum.Enum):
    """CLAUDE.md, "Monetisation — build now, enable later"."""

    FREE = "free"
    PAID = "paid"


class SearchState(enum.Enum):
    OPEN = "OPEN"
    REQUESTED = "REQUESTED"
    MATCHED = "MATCHED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class RequestState(enum.Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


def value_enum(enum_cls: type[enum.Enum], name: str) -> SAEnum:
    """A Postgres enum column that stores members by `.value` (e.g. "free",
    "rodzic") instead of SQLAlchemy's default `.name` ("FREE", "RODZIC").

    Used for AccountRole/Plan, whose values are CLAUDE.md's literal wire
    strings ("rodzic / opiekun / trener", "'free' | 'paid'") and are worth
    keeping human-legible in the database. Not used for AgeCategory, whose
    values are ints and can't be Postgres enum labels at all — it stores by
    name (SKRZATY/MLODZICY/...) instead, same as SQLAlchemy's default.
    """
    return SAEnum(enum_cls, name=name, values_callable=lambda obj: [e.value for e in obj])
