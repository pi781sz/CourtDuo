"""Tests for bot.tournament_search's pure logic: category ordering/
labelling, place matching, button labels, the selection confirmation
message, and the results cap (CLAUDE.md, "Tournament selection"; build
order step 5, revised by step 5.1 and step 5.2 which removed pagination
in favour of a single-keyboard result list with a 40-button safety cap).
No database — see tests/test_tournament_search_db.py for the eligibility
queries themselves. Invented tournament guids/cities only.
"""

from __future__ import annotations

from datetime import date

from bot.tournament_search import (
    CATEGORY_ORDER,
    MAX_RESULTS,
    TournamentOption,
    cap_results,
    category_is_available,
    category_short_label,
    match_by_place,
    meets_min_place_length,
    selection_confirmation_text,
    tournament_label,
)
from db.models import AgeCategory

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


def _options(n: int) -> list[TournamentOption]:
    return [
        TournamentOption(guid=f"t{i}", date_from=date(2026, 8, 1), venue_city="Miasto", wojewodztwo=None)
        for i in range(n)
    ]


def test_cap_results_under_cap_shows_everything_uncapped():
    options = _options(12)
    shown, capped = cap_results(options)
    assert shown == options
    assert capped is False


def test_cap_results_at_cap_is_not_capped():
    options = _options(MAX_RESULTS)
    shown, capped = cap_results(options)
    assert shown == options
    assert capped is False


def test_cap_results_over_cap_truncates_to_first_40_and_flags_capped():
    options = _options(45)
    shown, capped = cap_results(options)
    assert shown == options[:MAX_RESULTS]
    assert len(shown) == MAX_RESULTS == 40
    assert capped is True


def test_category_order_is_all_four_youngest_first():
    # CLAUDE.md step 5.1: "all four are always offered" -- never filtered
    # or reordered by the player's own age.
    assert CATEGORY_ORDER == (
        AgeCategory.SKRZATY,
        AgeCategory.MLODZICY,
        AgeCategory.KADECI,
        AgeCategory.JUNIORZY,
    )


def test_category_short_label_is_u_form_not_enum_name():
    assert category_short_label(AgeCategory.SKRZATY, "pl") == "U12"
    assert category_short_label(AgeCategory.MLODZICY, "pl") == "U14"
    assert category_short_label(AgeCategory.KADECI, "pl") == "U16"
    assert category_short_label(AgeCategory.JUNIORZY, "pl") == "U18"


def test_category_is_available_true_when_count_positive():
    counts = {AgeCategory.MLODZICY: 3}
    assert category_is_available(counts, AgeCategory.MLODZICY) is True


def test_category_is_available_false_when_absent_or_zero():
    counts = {AgeCategory.MLODZICY: 0}
    assert category_is_available(counts, AgeCategory.MLODZICY) is False
    assert category_is_available(counts, AgeCategory.SKRZATY) is False


def test_selection_confirmation_contains_town_category_and_date():
    text = selection_confirmation_text(
        venue_city="Grodzisk Mazowiecki",
        wojewodztwo="mazowieckie",
        category=AgeCategory.MLODZICY,
        date_from=date(2026, 8, 8),
        lang="pl",
    )
    assert "Grodzisk Mazowiecki" in text
    assert "U14" in text
    assert "2026.08.08" in text


def test_selection_confirmation_falls_back_to_wojewodztwo_when_venue_city_is_null():
    text = selection_confirmation_text(
        venue_city=None,
        wojewodztwo="mazowieckie",
        category=AgeCategory.JUNIORZY,
        date_from=date(2026, 8, 8),
        lang="pl",
    )
    assert "mazowieckie" in text
