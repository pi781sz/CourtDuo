"""SQLAlchemy models for the CourtDuo schema (see CLAUDE.md and the
top-level task description for the table list). Import from here — e.g.
`from db.models import Base, Player` — rather than the submodules
directly, and import this module (not just `Base`) wherever Alembic
autogenerate needs the full set of mapped classes registered on
`Base.metadata`.
"""

from __future__ import annotations

from .accounts import Account, AccountPlayer
from .base import Base
from .enums import (
    AccountRole,
    AgeCategory,
    Gender,
    Plan,
    PlayType,
    RankingList,
    RequestState,
    SearchState,
)
from .matching import Match, Request, Search
from .players import Player
from .rankings import Ranking
from .tournaments import Event, Tournament

__all__ = [
    "Base",
    "Account",
    "AccountPlayer",
    "Player",
    "Ranking",
    "Tournament",
    "Event",
    "Search",
    "Request",
    "Match",
    "AccountRole",
    "AgeCategory",
    "Gender",
    "Plan",
    "PlayType",
    "RankingList",
    "RequestState",
    "SearchState",
]
