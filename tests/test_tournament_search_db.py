"""Tests for db.crud.get_eligible_tournaments against a real Postgres
(see tests/conftest.py -- skipped cleanly when TEST_DATABASE_URL is
unset). CLAUDE.md, "Tournament selection": date_from within 14 days,
search window still open, gender-matching Gra podwójna event required.
Invented guids/names/cities only.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from db import crud
from db.models import AgeCategory, Event, Gender, PlayType, Tournament

_NOW = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)
_TODAY = date(2026, 8, 7)


def _make_tournament(
    guid: str,
    date_from: date,
    search_closes_at: datetime | None,
    venue_city: str | None = "Testowo",
    wojewodztwo: str | None = "testowe",
) -> Tournament:
    return Tournament(
        guid=guid,
        name=f"Turniej testowy {guid}",
        type_prefix="OTK",
        age_category=AgeCategory.JUNIORZY,
        ranga=None,
        date_from=date_from,
        date_to=date_from,
        wojewodztwo=wojewodztwo,
        venue_address=None,
        venue_city=venue_city,
        entry_deadline=None,
        withdrawal_deadline=None,
        search_closes_at=search_closes_at,
    )


def _make_event(tournament_guid: str, gender: Gender, is_doubles: bool = True) -> Event:
    return Event(
        tournament_guid=tournament_guid,
        category_label="Kategoria testowa",
        gender=gender,
        play_type=PlayType.DOUBLES if is_doubles else PlayType.SINGLES,
        draw_format=None,
        is_doubles=is_doubles,
    )


async def test_eligible_tournament_is_returned(db_session: AsyncSession):
    tournament = _make_tournament("t1", date(2026, 8, 10), _NOW + timedelta(hours=1))
    db_session.add(tournament)
    await db_session.flush()
    db_session.add(_make_event("t1", Gender.BOYS))
    await db_session.flush()

    result = await crud.get_eligible_tournaments(db_session, Gender.BOYS, _TODAY, _NOW)

    assert [t.guid for t in result] == ["t1"]


async def test_gender_mismatch_is_excluded(db_session: AsyncSession):
    tournament = _make_tournament("t1", date(2026, 8, 10), _NOW + timedelta(hours=1))
    db_session.add(tournament)
    await db_session.flush()
    db_session.add(_make_event("t1", Gender.GIRLS))
    await db_session.flush()

    result = await crud.get_eligible_tournaments(db_session, Gender.BOYS, _TODAY, _NOW)

    assert result == []


async def test_singles_only_tournament_is_excluded(db_session: AsyncSession):
    tournament = _make_tournament("t1", date(2026, 8, 10), _NOW + timedelta(hours=1))
    db_session.add(tournament)
    await db_session.flush()
    db_session.add(_make_event("t1", Gender.BOYS, is_doubles=False))
    await db_session.flush()

    result = await crud.get_eligible_tournaments(db_session, Gender.BOYS, _TODAY, _NOW)

    assert result == []


async def test_date_outside_14_day_window_is_excluded(db_session: AsyncSession):
    tournament = _make_tournament("t1", date(2026, 8, 22), _NOW + timedelta(hours=1))
    db_session.add(tournament)
    await db_session.flush()
    db_session.add(_make_event("t1", Gender.BOYS))
    await db_session.flush()

    result = await crud.get_eligible_tournaments(db_session, Gender.BOYS, _TODAY, _NOW)

    assert result == []


async def test_date_from_before_today_is_excluded(db_session: AsyncSession):
    tournament = _make_tournament("t1", date(2026, 8, 6), _NOW + timedelta(hours=1))
    db_session.add(tournament)
    await db_session.flush()
    db_session.add(_make_event("t1", Gender.BOYS))
    await db_session.flush()

    result = await crud.get_eligible_tournaments(db_session, Gender.BOYS, _TODAY, _NOW)

    assert result == []


async def test_search_window_already_closed_is_excluded(db_session: AsyncSession):
    tournament = _make_tournament("t1", _TODAY, _NOW - timedelta(hours=1))
    db_session.add(tournament)
    await db_session.flush()
    db_session.add(_make_event("t1", Gender.BOYS))
    await db_session.flush()

    result = await crud.get_eligible_tournaments(db_session, Gender.BOYS, _TODAY, _NOW)

    assert result == []


async def test_null_venue_city_still_eligible(db_session: AsyncSession):
    tournament = _make_tournament("t1", date(2026, 8, 10), _NOW + timedelta(hours=1), venue_city=None)
    db_session.add(tournament)
    await db_session.flush()
    db_session.add(_make_event("t1", Gender.GIRLS))
    await db_session.flush()

    result = await crud.get_eligible_tournaments(db_session, Gender.GIRLS, _TODAY, _NOW)

    assert [t.guid for t in result] == ["t1"]
    assert result[0].venue_city is None


async def test_tournament_with_multiple_matching_events_returned_once(db_session: AsyncSession):
    tournament = _make_tournament("t1", date(2026, 8, 10), _NOW + timedelta(hours=1))
    db_session.add(tournament)
    await db_session.flush()
    db_session.add(_make_event("t1", Gender.BOYS))
    db_session.add(_make_event("t1", Gender.BOYS, is_doubles=False))
    await db_session.flush()

    result = await crud.get_eligible_tournaments(db_session, Gender.BOYS, _TODAY, _NOW)

    assert [t.guid for t in result] == ["t1"]


async def test_results_sorted_by_date_from_ascending(db_session: AsyncSession):
    later = _make_tournament("later", date(2026, 8, 15), _NOW + timedelta(hours=1))
    earlier = _make_tournament("earlier", date(2026, 8, 9), _NOW + timedelta(hours=1))
    db_session.add_all([later, earlier])
    await db_session.flush()
    db_session.add(_make_event("later", Gender.BOYS))
    db_session.add(_make_event("earlier", Gender.BOYS))
    await db_session.flush()

    result = await crud.get_eligible_tournaments(db_session, Gender.BOYS, _TODAY, _NOW)

    assert [t.guid for t in result] == ["earlier", "later"]


async def test_get_tournament_by_guid_found_and_missing(db_session: AsyncSession):
    tournament = _make_tournament("t1", date(2026, 8, 10), _NOW + timedelta(hours=1))
    db_session.add(tournament)
    await db_session.flush()

    found = await crud.get_tournament_by_guid(db_session, "t1")
    missing = await crud.get_tournament_by_guid(db_session, "does-not-exist")

    assert found is not None
    assert found.guid == "t1"
    assert missing is None
