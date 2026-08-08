"""Tests for db.crud.get_eligible_tournaments and
get_eligible_tournament_counts_by_category against a real Postgres (see
tests/conftest.py -- skipped cleanly when TEST_DATABASE_URL is unset).
CLAUDE.md, "Tournament selection": age category chosen first, date_from
within ELIGIBILITY_WINDOW_DAYS days, search window still open,
gender-matching Gra podwójna event required. Invented guids/names/cities
only.
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
    age_category: AgeCategory = AgeCategory.JUNIORZY,
    ranga: int | None = None,
) -> Tournament:
    return Tournament(
        guid=guid,
        name=f"Turniej testowy {guid}",
        type_prefix="OTK",
        age_category=age_category,
        ranga=ranga,
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

    result = await crud.get_eligible_tournaments(db_session, Gender.BOYS, AgeCategory.JUNIORZY, _TODAY, _NOW)

    assert [t.guid for t in result] == ["t1"]


async def test_gender_mismatch_is_excluded(db_session: AsyncSession):
    tournament = _make_tournament("t1", date(2026, 8, 10), _NOW + timedelta(hours=1))
    db_session.add(tournament)
    await db_session.flush()
    db_session.add(_make_event("t1", Gender.GIRLS))
    await db_session.flush()

    result = await crud.get_eligible_tournaments(db_session, Gender.BOYS, AgeCategory.JUNIORZY, _TODAY, _NOW)

    assert result == []


async def test_singles_only_tournament_is_excluded(db_session: AsyncSession):
    tournament = _make_tournament("t1", date(2026, 8, 10), _NOW + timedelta(hours=1))
    db_session.add(tournament)
    await db_session.flush()
    db_session.add(_make_event("t1", Gender.BOYS, is_doubles=False))
    await db_session.flush()

    result = await crud.get_eligible_tournaments(db_session, Gender.BOYS, AgeCategory.JUNIORZY, _TODAY, _NOW)

    assert result == []


async def test_age_category_mismatch_is_excluded(db_session: AsyncSession):
    # Step 5.1: choosing a category then a place must return only that
    # category's tournaments.
    juniorzy = _make_tournament("juniorzy", date(2026, 8, 10), _NOW + timedelta(hours=1), age_category=AgeCategory.JUNIORZY)
    skrzaty = _make_tournament("skrzaty", date(2026, 8, 10), _NOW + timedelta(hours=1), age_category=AgeCategory.SKRZATY)
    db_session.add_all([juniorzy, skrzaty])
    await db_session.flush()
    db_session.add(_make_event("juniorzy", Gender.BOYS))
    db_session.add(_make_event("skrzaty", Gender.BOYS))
    await db_session.flush()

    result = await crud.get_eligible_tournaments(db_session, Gender.BOYS, AgeCategory.JUNIORZY, _TODAY, _NOW)

    assert [t.guid for t in result] == ["juniorzy"]


async def test_date_at_window_boundary_is_included(db_session: AsyncSession):
    boundary = _TODAY + timedelta(days=crud.ELIGIBILITY_WINDOW_DAYS)
    tournament = _make_tournament("t1", boundary, _NOW + timedelta(hours=1))
    db_session.add(tournament)
    await db_session.flush()
    db_session.add(_make_event("t1", Gender.BOYS))
    await db_session.flush()

    result = await crud.get_eligible_tournaments(db_session, Gender.BOYS, AgeCategory.JUNIORZY, _TODAY, _NOW)

    assert [t.guid for t in result] == ["t1"]


async def test_date_one_day_past_window_boundary_is_excluded(db_session: AsyncSession):
    past_boundary = _TODAY + timedelta(days=crud.ELIGIBILITY_WINDOW_DAYS + 1)
    tournament = _make_tournament("t1", past_boundary, _NOW + timedelta(hours=1))
    db_session.add(tournament)
    await db_session.flush()
    db_session.add(_make_event("t1", Gender.BOYS))
    await db_session.flush()

    result = await crud.get_eligible_tournaments(db_session, Gender.BOYS, AgeCategory.JUNIORZY, _TODAY, _NOW)

    assert result == []


async def test_date_from_before_today_is_excluded(db_session: AsyncSession):
    tournament = _make_tournament("t1", date(2026, 8, 6), _NOW + timedelta(hours=1))
    db_session.add(tournament)
    await db_session.flush()
    db_session.add(_make_event("t1", Gender.BOYS))
    await db_session.flush()

    result = await crud.get_eligible_tournaments(db_session, Gender.BOYS, AgeCategory.JUNIORZY, _TODAY, _NOW)

    assert result == []


async def test_search_window_already_closed_is_excluded(db_session: AsyncSession):
    tournament = _make_tournament("t1", _TODAY, _NOW - timedelta(hours=1))
    db_session.add(tournament)
    await db_session.flush()
    db_session.add(_make_event("t1", Gender.BOYS))
    await db_session.flush()

    result = await crud.get_eligible_tournaments(db_session, Gender.BOYS, AgeCategory.JUNIORZY, _TODAY, _NOW)

    assert result == []


async def test_null_venue_city_still_eligible(db_session: AsyncSession):
    tournament = _make_tournament("t1", date(2026, 8, 10), _NOW + timedelta(hours=1), venue_city=None)
    db_session.add(tournament)
    await db_session.flush()
    db_session.add(_make_event("t1", Gender.GIRLS))
    await db_session.flush()

    result = await crud.get_eligible_tournaments(db_session, Gender.GIRLS, AgeCategory.JUNIORZY, _TODAY, _NOW)

    assert [t.guid for t in result] == ["t1"]
    assert result[0].venue_city is None


async def test_tournament_with_multiple_matching_events_returned_once(db_session: AsyncSession):
    tournament = _make_tournament("t1", date(2026, 8, 10), _NOW + timedelta(hours=1))
    db_session.add(tournament)
    await db_session.flush()
    db_session.add(_make_event("t1", Gender.BOYS))
    db_session.add(_make_event("t1", Gender.BOYS, is_doubles=False))
    await db_session.flush()

    result = await crud.get_eligible_tournaments(db_session, Gender.BOYS, AgeCategory.JUNIORZY, _TODAY, _NOW)

    assert [t.guid for t in result] == ["t1"]


async def test_results_sorted_by_date_from_ascending(db_session: AsyncSession):
    later = _make_tournament("later", date(2026, 8, 15), _NOW + timedelta(hours=1))
    earlier = _make_tournament("earlier", date(2026, 8, 9), _NOW + timedelta(hours=1))
    db_session.add_all([later, earlier])
    await db_session.flush()
    db_session.add(_make_event("later", Gender.BOYS))
    db_session.add(_make_event("earlier", Gender.BOYS))
    await db_session.flush()

    result = await crud.get_eligible_tournaments(db_session, Gender.BOYS, AgeCategory.JUNIORZY, _TODAY, _NOW)

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


async def test_category_counts_respect_gender(db_session: AsyncSession):
    # Step 5.1: category availability must respect gender -- a category
    # empty for one gender can still be available for the other.
    boys_only = _make_tournament(
        "boys-only", date(2026, 8, 10), _NOW + timedelta(hours=1), age_category=AgeCategory.JUNIORZY
    )
    girls_only = _make_tournament(
        "girls-only", date(2026, 8, 10), _NOW + timedelta(hours=1), age_category=AgeCategory.MLODZICY
    )
    db_session.add_all([boys_only, girls_only])
    await db_session.flush()
    db_session.add(_make_event("boys-only", Gender.BOYS))
    db_session.add(_make_event("girls-only", Gender.GIRLS))
    await db_session.flush()

    boys_counts = await crud.get_eligible_tournament_counts_by_category(db_session, Gender.BOYS, _TODAY, _NOW)
    girls_counts = await crud.get_eligible_tournament_counts_by_category(db_session, Gender.GIRLS, _TODAY, _NOW)

    assert boys_counts.get(AgeCategory.JUNIORZY) == 1
    assert boys_counts.get(AgeCategory.MLODZICY, 0) == 0
    assert girls_counts.get(AgeCategory.MLODZICY) == 1
    assert girls_counts.get(AgeCategory.JUNIORZY, 0) == 0


async def test_category_counts_group_multiple_tournaments(db_session: AsyncSession):
    a = _make_tournament("a", date(2026, 8, 10), _NOW + timedelta(hours=1), age_category=AgeCategory.KADECI)
    b = _make_tournament("b", date(2026, 8, 12), _NOW + timedelta(hours=1), age_category=AgeCategory.KADECI)
    db_session.add_all([a, b])
    await db_session.flush()
    db_session.add(_make_event("a", Gender.BOYS))
    db_session.add(_make_event("b", Gender.BOYS))
    await db_session.flush()

    counts = await crud.get_eligible_tournament_counts_by_category(db_session, Gender.BOYS, _TODAY, _NOW)

    assert counts.get(AgeCategory.KADECI) == 2


async def test_ranga_six_and_seven_are_excluded_from_eligible_list(db_session: AsyncSession):
    # CLAUDE.md step 5.4: ranga 6/7 are internal club events -- must not
    # appear at all, alongside an ordinary ranga 3 tournament that must
    # still show up.
    internal_six = _make_tournament("internal-six", date(2026, 8, 10), _NOW + timedelta(hours=1), ranga=6)
    internal_seven = _make_tournament("internal-seven", date(2026, 8, 11), _NOW + timedelta(hours=1), ranga=7)
    public = _make_tournament("public", date(2026, 8, 12), _NOW + timedelta(hours=1), ranga=3)
    db_session.add_all([internal_six, internal_seven, public])
    await db_session.flush()
    db_session.add(_make_event("internal-six", Gender.BOYS))
    db_session.add(_make_event("internal-seven", Gender.BOYS))
    db_session.add(_make_event("public", Gender.BOYS))
    await db_session.flush()

    result = await crud.get_eligible_tournaments(db_session, Gender.BOYS, AgeCategory.JUNIORZY, _TODAY, _NOW)

    assert [t.guid for t in result] == ["public"]


async def test_null_ranga_tournament_is_still_eligible(db_session: AsyncSession):
    # A NULL ranga is not one of HIDDEN_RANGAS -- it must still show, per
    # CLAUDE.md step 5.4 ("hiding it would risk losing a real tournament").
    tournament = _make_tournament("t1", date(2026, 8, 10), _NOW + timedelta(hours=1), ranga=None)
    db_session.add(tournament)
    await db_session.flush()
    db_session.add(_make_event("t1", Gender.BOYS))
    await db_session.flush()

    result = await crud.get_eligible_tournaments(db_session, Gender.BOYS, AgeCategory.JUNIORZY, _TODAY, _NOW)

    assert [t.guid for t in result] == ["t1"]


async def test_ranga_six_and_seven_are_excluded_from_category_counts(db_session: AsyncSession):
    # A category with only ranga 6/7 tournaments must count as unavailable
    # -- CLAUDE.md step 5.4: "a category can never be shown as available on
    # the strength of a tournament the player will then not see."
    internal = _make_tournament(
        "internal", date(2026, 8, 10), _NOW + timedelta(hours=1), age_category=AgeCategory.KADECI, ranga=6
    )
    db_session.add(internal)
    await db_session.flush()
    db_session.add(_make_event("internal", Gender.BOYS))
    await db_session.flush()

    counts = await crud.get_eligible_tournament_counts_by_category(db_session, Gender.BOYS, _TODAY, _NOW)

    assert counts.get(AgeCategory.KADECI, 0) == 0


async def test_null_ranga_tournament_counted_in_category_counts(db_session: AsyncSession):
    tournament = _make_tournament(
        "t1", date(2026, 8, 10), _NOW + timedelta(hours=1), age_category=AgeCategory.KADECI, ranga=None
    )
    db_session.add(tournament)
    await db_session.flush()
    db_session.add(_make_event("t1", Gender.BOYS))
    await db_session.flush()

    counts = await crud.get_eligible_tournament_counts_by_category(db_session, Gender.BOYS, _TODAY, _NOW)

    assert counts.get(AgeCategory.KADECI) == 1
