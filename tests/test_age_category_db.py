"""Tests for db.crud.get_player_own_age_category against a real Postgres
(see tests/conftest.py -- skipped cleanly when TEST_DATABASE_URL is unset):
CLAUDE.md step 8.3, "Deriving a player's own age category" -- the lowest
ranking list a player appears in for the newest period overall, never a
guess when there are no ranking rows at all. Invented pzt_ids/names only.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from db import crud
from db.models import AgeCategory, Gender, Player, Ranking, RankingList


async def _add_player(session: AsyncSession, pzt_id: str, full_name: str, gender: Gender = Gender.GIRLS) -> None:
    session.add(Player(pzt_id=pzt_id, full_name=full_name, club=None, age_category=None, gender=gender))
    await session.flush()


async def test_player_in_a_single_list_uses_that_category(db_session: AsyncSession):
    await _add_player(db_session, "AGE001", "Testowa Anna")
    db_session.add(Ranking(player_pzt_id="AGE001", ranking_list=RankingList.W14, year=2026, month=8, position=10))
    await db_session.flush()

    category = await crud.get_player_own_age_category(db_session, "AGE001")

    assert category is AgeCategory.MLODZICY


async def test_player_playing_up_is_treated_as_the_lower_category(db_session: AsyncSession):
    # CLAUDE.md step 8.3: "A player in M14 and M16 is a U14 player playing
    # up, so their category is 14."
    await _add_player(db_session, "AGE002", "Testowy Piotr", gender=Gender.BOYS)
    db_session.add(Ranking(player_pzt_id="AGE002", ranking_list=RankingList.M14, year=2026, month=8, position=30))
    db_session.add(Ranking(player_pzt_id="AGE002", ranking_list=RankingList.M16, year=2026, month=8, position=5))
    await db_session.flush()

    category = await crud.get_player_own_age_category(db_session, "AGE002")

    assert category is AgeCategory.MLODZICY


async def test_player_with_no_ranking_rows_returns_none(db_session: AsyncSession):
    await _add_player(db_session, "AGE003", "Testowa Ola")

    category = await crud.get_player_own_age_category(db_session, "AGE003")

    assert category is None


async def test_only_the_newest_period_is_considered(db_session: AsyncSession):
    # An older period's row for a lower category must not win over the
    # newest period's own rows.
    await _add_player(db_session, "AGE004", "Testowa Ewa")
    db_session.add(Ranking(player_pzt_id="AGE004", ranking_list=RankingList.W12, year=2026, month=6, position=1))
    db_session.add(Ranking(player_pzt_id="AGE004", ranking_list=RankingList.W16, year=2026, month=8, position=1))
    await db_session.flush()

    category = await crud.get_player_own_age_category(db_session, "AGE004")

    assert category is AgeCategory.KADECI
