"""SQLAlchemy models for the CourtDuo schema (see CLAUDE.md and the
top-level task description for the table list). Import from here — e.g.
`from db.models import Base, Player` — rather than the submodules
directly, and import this module (not just `Base`) wherever Alembic
autogenerate needs the full set of mapped classes registered on
`Base.metadata`.
"""

from __future__ import annotations

from .account_viewers import AccountViewer, ViewerInviteToken
from .accounts import Account
from .alarm_state import AlarmState
from .base import Base
from .blocked_pzt_ids import BlockedPztId
from .enums import (
    AgeCategory,
    Gender,
    InvitationState,
    Plan,
    PlayType,
    RankingList,
)
from .invitations import Invitation, PendingExternalInvite
from .players import Player
from .rankings import Ranking
from .scraper_runs import ScraperRun
from .support_threads import SupportThread
from .tournaments import Event, Tournament

__all__ = [
    "Base",
    "Account",
    "Player",
    "Ranking",
    "Tournament",
    "Event",
    "Invitation",
    "PendingExternalInvite",
    "AccountViewer",
    "ViewerInviteToken",
    "ScraperRun",
    "AlarmState",
    "BlockedPztId",
    "SupportThread",
    "AgeCategory",
    "Gender",
    "InvitationState",
    "Plan",
    "PlayType",
    "RankingList",
]
