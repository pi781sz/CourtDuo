"""End-to-end tests for bot.registration.register_by_pzt_id against a
real Postgres (see tests/conftest.py — skipped cleanly when
TEST_DATABASE_URL is unset). All names and PZT ids below are invented
for testing; CLAUDE.md forbids real scraped player data from ever
entering git.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from bot.registration import RegistrationOutcome, register_by_pzt_id
from db.models import AgeCategory, Gender, Player, Ranking, RankingList


async def _add_player_with_rankings(
    session: AsyncSession,
    pzt_id: str,
    full_name: str,
    ranking_lists: list[RankingList],
    gender: Gender = Gender.BOYS,
    year: int = 2026,
    month: int = 8,
) -> None:
    session.add(
        Player(
            pzt_id=pzt_id,
            full_name=full_name,
            club="TKS Testowo",
            age_category=AgeCategory.JUNIORZY,
            gender=gender,
        )
    )
    await session.flush()
    for ranking_list in ranking_lists:
        session.add(Ranking(player_pzt_id=pzt_id, ranking_list=ranking_list, year=year, month=month, position=1))
    await session.flush()


async def test_successful_registration(db_session: AsyncSession):
    await _add_player_with_rankings(db_session, "INV001", "Janina Testowa", [RankingList.W18], gender=Gender.GIRLS)

    result = await register_by_pzt_id(db_session, telegram_id=1001, raw_pzt_id=" inv001 ")

    assert result.outcome is RegistrationOutcome.SUCCESS
    assert result.account.telegram_id == 1001
    assert result.account.pzt_id == "INV001"
    assert result.account.full_name == "Janina Testowa"
    assert result.account.gender == "W"


async def test_pzt_id_not_found(db_session: AsyncSession):
    await _add_player_with_rankings(db_session, "INV001", "Janina Testowa", [RankingList.W18], gender=Gender.GIRLS)

    result = await register_by_pzt_id(db_session, telegram_id=1001, raw_pzt_id="DOESNOTEXIST")

    assert result.outcome is RegistrationOutcome.NOT_FOUND
    assert result.account is None


async def test_no_ranking_data_at_all_is_not_found(db_session: AsyncSession):
    result = await register_by_pzt_id(db_session, telegram_id=1001, raw_pzt_id="INV001")

    assert result.outcome is RegistrationOutcome.NOT_FOUND
    assert result.account is None


async def test_player_who_plays_up_registers_with_agreeing_gender(db_session: AsyncSession):
    await _add_player_with_rankings(
        db_session, "INV002", "Adam Testowy", [RankingList.M16, RankingList.M18], gender=Gender.BOYS
    )

    result = await register_by_pzt_id(db_session, telegram_id=1002, raw_pzt_id="INV002")

    assert result.outcome is RegistrationOutcome.SUCCESS
    assert result.account.gender == "M"


async def test_gender_conflict_refuses_registration(db_session: AsyncSession):
    await _add_player_with_rankings(
        db_session, "INV003", "Zly Rekord", [RankingList.M14, RankingList.W14], gender=Gender.BOYS
    )

    result = await register_by_pzt_id(db_session, telegram_id=1003, raw_pzt_id="INV003")

    assert result.outcome is RegistrationOutcome.GENDER_CONFLICT
    assert result.account is None


async def test_pzt_id_already_bound_to_another_account(db_session: AsyncSession):
    await _add_player_with_rankings(db_session, "INV001", "Janina Testowa", [RankingList.W18], gender=Gender.GIRLS)

    first = await register_by_pzt_id(db_session, telegram_id=1001, raw_pzt_id="INV001")
    assert first.outcome is RegistrationOutcome.SUCCESS

    second = await register_by_pzt_id(db_session, telegram_id=1002, raw_pzt_id="inv001")
    assert second.outcome is RegistrationOutcome.ALREADY_BOUND_TO_OTHER


async def test_lookup_is_case_insensitive_and_keeps_canonical_pzt_id(db_session: AsyncSession):
    await _add_player_with_rankings(db_session, "inv004", "Ola Przykladowa", [RankingList.W16], gender=Gender.GIRLS)

    result = await register_by_pzt_id(db_session, telegram_id=1004, raw_pzt_id=" Inv004 ")

    assert result.outcome is RegistrationOutcome.SUCCESS
    assert result.account.pzt_id == "inv004"


async def test_only_newest_period_is_searched(db_session: AsyncSession):
    await _add_player_with_rankings(
        db_session, "INV005", "Stary Zapis", [RankingList.W18], gender=Gender.GIRLS, year=2026, month=7
    )
    await _add_player_with_rankings(
        db_session, "INV006", "Nowy Zapis", [RankingList.W18], gender=Gender.GIRLS, year=2026, month=8
    )

    result = await register_by_pzt_id(db_session, telegram_id=1005, raw_pzt_id="INV005")

    assert result.outcome is RegistrationOutcome.NOT_FOUND
