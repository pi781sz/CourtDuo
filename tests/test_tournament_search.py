"""Tests for bot.tournament_search's pure logic: place matching, button
labels, and pagination (CLAUDE.md, "Tournament selection"; build order
step 5). No database — see tests/test_tournament_search_db.py for the
eligibility query itself. Invented tournament guids/cities only.
"""

from __future__ import annotations

from datetime import date

from bot.tournament_search import (
    PAGE_SIZE,
    TournamentOption,
    match_by_place,
    meets_min_place_length,
    paginate,
    tournament_label,
)

UNIEJOW = TournamentOption(guid="t-uniejow", date_from=date(2026, 8, 29), venue_city="Uniejów", wojewodztwo="łódzkie")
ZIELONA_GORA = TournamentOption(
    guid="t-zielona-gora", date_from=date(2026, 8, 15), venue_city="Zielona Gora", wojewodztwo="lubuskie"
)
NO_CITY = TournamentOption(guid="t-no-city", date_from=date(2026, 8, 20), venue_city=None, wojewodztwo="mazowieckie")


def test_place_matching_is_diacritic_and_case_insensitive():
    options = [UNIEJOW]
    assert match_by_place(options, "uniejow") == options
    assert match_by_place(options, "Uniejów") == options
    assert match_by_place(options, "UNIEJOW") == options


def test_place_matches_pzt_spelling_without_diacritics():
    # PZT itself stores "Zielona Gora" in one row and "Zielona Góra" in
    # another for the same tournament (core/text.py's fold_diacritics
    # docstring) -- the query must match either spelling.
    options = [ZIELONA_GORA]
    assert match_by_place(options, "Zielona Góra") == options
    assert match_by_place(options, "Zielona Gora") == options


def test_place_matches_substring_of_city():
    assert match_by_place([UNIEJOW], "niejo") == [UNIEJOW]


def test_place_matches_wojewodztwo_when_venue_city_present():
    assert match_by_place([UNIEJOW], "lodzkie") == [UNIEJOW]


def test_null_venue_city_is_still_reachable_via_wojewodztwo():
    assert match_by_place([NO_CITY], "mazowieckie") == [NO_CITY]


def test_null_venue_city_never_matches_on_city():
    # Nothing in venue_city to match against -- must not spuriously match
    # every query just because it's None.
    assert match_by_place([NO_CITY], "xyz") == []


def test_no_match_returns_empty_list():
    assert match_by_place([UNIEJOW], "gdansk") == []


def test_meets_min_place_length():
    assert meets_min_place_length("uni") is True
    assert meets_min_place_length("un") is False
    assert meets_min_place_length("  un  ") is False
    assert meets_min_place_length("") is False


def test_tournament_label_uses_venue_city():
    assert tournament_label(UNIEJOW) == "Uniejów — 2026.08.29"


def test_tournament_label_falls_back_to_wojewodztwo_when_venue_city_is_null():
    assert tournament_label(NO_CITY) == "mazowieckie — 2026.08.20"


def test_paginate_first_page_and_has_more():
    options = [
        TournamentOption(guid=f"t{i}", date_from=date(2026, 8, i + 1), venue_city="Miasto", wojewodztwo=None)
        for i in range(1, 11)
    ]
    page, has_more = paginate(options, offset=0)
    assert len(page) == PAGE_SIZE
    assert page == options[:PAGE_SIZE]
    assert has_more is True


def test_paginate_last_page_has_no_more():
    options = [
        TournamentOption(guid=f"t{i}", date_from=date(2026, 8, i + 1), venue_city="Miasto", wojewodztwo=None)
        for i in range(1, 11)
    ]
    page, has_more = paginate(options, offset=PAGE_SIZE)
    assert page == options[PAGE_SIZE:]
    assert has_more is False


def test_paginate_exact_page_size_has_no_more():
    options = [
        TournamentOption(guid=f"t{i}", date_from=date(2026, 8, i + 1), venue_city="Miasto", wojewodztwo=None)
        for i in range(1, PAGE_SIZE + 1)
    ]
    page, has_more = paginate(options, offset=0)
    assert len(page) == PAGE_SIZE
    assert has_more is False
