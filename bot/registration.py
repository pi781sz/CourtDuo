"""Registration by PZT ID (CLAUDE.md, "Identity"; build order step 4).

Binds a Telegram account to exactly one PZT player: the player types
their PZT id, it's looked up in the newest published ranking period, and
the account is created. RegistrationOutcome enumerates every way that
lookup can end — bot/handlers/start.py maps each one onto a reply and
decides whether it counts against the per-account failed-attempt cap.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum, auto

from sqlalchemy.ext.asyncio import AsyncSession

from db import crud
from db.models import Account

logger = logging.getLogger(__name__)


def normalize_pzt_id(raw: str) -> str:
    """Strip whitespace, remove internal spaces, uppercase — the only
    validation a PZT id gets. There is no format regex: the database
    lookup below is the validator (CLAUDE.md, LOOKUP RULES).
    """
    return "".join(raw.split()).upper()


class GenderConflictError(Exception):
    """A pzt_id appears under both an M and a W ranking code in the same
    period — corrupt upstream data, not something to guess through
    (CLAUDE.md, LOOKUP RULES)."""


def derive_gender(ranking_list_codes: set[str]) -> str:
    """`ranking_list_codes` is e.g. {"M14", "M16"} for a player who plays
    up — every code must agree on the M/W prefix. Raises
    GenderConflictError if not. Callers must not pass an empty set.
    """
    genders = {code[0] for code in ranking_list_codes}
    if len(genders) > 1:
        raise GenderConflictError(f"pzt_id has ranking codes across genders: {sorted(ranking_list_codes)}")
    return genders.pop()


class RegistrationOutcome(Enum):
    SUCCESS = auto()
    NOT_FOUND = auto()
    GENDER_CONFLICT = auto()
    ALREADY_BOUND_TO_OTHER = auto()


@dataclass
class RegistrationResult:
    outcome: RegistrationOutcome
    account: Account | None = None


async def register_by_pzt_id(session: AsyncSession, telegram_id: int, raw_pzt_id: str) -> RegistrationResult:
    """Never logs the typed id or a player's name (CLAUDE.md, LOOKUP
    RULES) — only the Telegram id and the outcome.
    """
    typed_pzt_id = normalize_pzt_id(raw_pzt_id)

    period = await crud.get_latest_ranking_period_overall(session)
    if period is None:
        logger.info("Registration failed: no ranking data available (telegram_id=%s)", telegram_id)
        return RegistrationResult(RegistrationOutcome.NOT_FOUND)
    year, month = period

    rankings = await crud.get_rankings_for_player_in_period(session, typed_pzt_id, year, month)
    if not rankings:
        logger.info("Registration failed: pzt_id not found (telegram_id=%s)", telegram_id)
        return RegistrationResult(RegistrationOutcome.NOT_FOUND)

    # The exact, canonical value as scraped — not necessarily equal to
    # typed_pzt_id's uppercased-no-spaces form — since it's what
    # players.pzt_id (and therefore accounts.pzt_id's FK) must match.
    canonical_pzt_id = rankings[0].player_pzt_id

    try:
        gender = derive_gender({r.ranking_list.code for r in rankings})
    except GenderConflictError:
        logger.error("Registration failed: gender conflict across ranking lists (telegram_id=%s)", telegram_id)
        return RegistrationResult(RegistrationOutcome.GENDER_CONFLICT)

    existing = await crud.get_account_by_pzt_id(session, canonical_pzt_id)
    if existing is not None and existing.telegram_id != telegram_id:
        logger.info("Registration failed: pzt_id already bound to another account (telegram_id=%s)", telegram_id)
        return RegistrationResult(RegistrationOutcome.ALREADY_BOUND_TO_OTHER)

    player = await crud.get_player_by_pzt_id(session, canonical_pzt_id)
    if player is None:
        # Can't happen: a Ranking row's FK guarantees the Player row
        # exists. Treated as not-found rather than raising, so a handler
        # bug elsewhere can't 500 a player's registration attempt.
        logger.error("Registration failed: ranking row with no matching player (telegram_id=%s)", telegram_id)
        return RegistrationResult(RegistrationOutcome.NOT_FOUND)

    account = await crud.create_account(
        session, telegram_id=telegram_id, pzt_id=canonical_pzt_id, full_name=player.full_name, gender=gender
    )
    logger.info("Registration succeeded (telegram_id=%s)", telegram_id)
    return RegistrationResult(RegistrationOutcome.SUCCESS, account=account)
