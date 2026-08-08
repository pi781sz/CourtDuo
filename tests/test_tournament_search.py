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
    RANGA_PREFIX,
    TournamentOption,
    cap_results,
    category_is_available,
    category_selected_text,
    category_short_label,
    match_by_place,
    meets_min_place_length,
    ranga_prefix,
    selection_confirmation_text,
    tournament_label,
)
from db.models import AgeCategory

UNIEJOW = TournamentOption(
    guid="t-uniejow", date_from=date(2026, 8, 29), venue_city="Uniejów", wojewodztwo="łódzkie", ranga=5
)
ZIELONA_GORA = TournamentOption(
    guid="t-zielona-gora", date_from=date(2026, 8, 15), venue_city="Zielona Gora", wojewodztwo="lubuskie"
)
NO_CITY = TournamentOption(
    guid="t-no-city", date_from=date(2026, 8, 20), venue_city=None, wojewodztwo="mazowieckie", ranga=3
)


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
    # ranga 5 -> WTK (CLAUDE.md step 5.4).
    assert tournament_label(UNIEJOW) == "WTK Uniejów - 29.08.2026"


def test_tournament_label_falls_back_to_wojewodztwo_when_venue_city_is_null():
    # ranga 3 -> OTK.
    assert tournament_label(NO_CITY) == "OTK mazowieckie - 20.08.2026"


def test_tournament_label_has_no_prefix_when_ranga_is_null():
    option = TournamentOption(guid="t-null-ranga", date_from=date(2026, 8, 20), venue_city="Radom", wojewodztwo=None)
    assert tournament_label(option) == "Radom - 20.08.2026"


def test_tournament_label_uses_plain_hyphen_not_em_dash():
    assert "—" not in tournament_label(UNIEJOW)
    assert " - " in tournament_label(UNIEJOW)


def test_ranga_prefix_lookup_for_one_through_seven_and_null():
    # CLAUDE.md step 5.4: ranga 6/7 (internal club events) are excluded
    # from the eligible list entirely (see tests/test_tournament_search_db.py)
    # rather than mapped here, so they have no entry in RANGA_PREFIX.
    assert ranga_prefix(1) == "MP"
    assert ranga_prefix(2) == "SS"
    assert ranga_prefix(3) == "OTK"
    assert ranga_prefix(4) == "MW"
    assert ranga_prefix(5) == "WTK"
    assert ranga_prefix(6) is None
    assert ranga_prefix(7) is None
    assert ranga_prefix(None) is None
    assert 6 not in RANGA_PREFIX
    assert 7 not in RANGA_PREFIX


def test_type_prefix_agrees_with_ranga_for_known_real_combinations():
    # Sanity check requested in step 5.4: tournaments.type_prefix (scraped
    # from the tournament name -- see scrapers/tournaments/parser.py's
    # TYPE_PREFIXES) and the ranga-derived prefix should describe the same
    # tournament type for every combination PZT actually produces. "OTK SS"
    # corresponds to ranga 2 (whose derived prefix is the bare "SS" --
    # scraped names read e.g. "OTK SS ... turniej"), plain "OTK" to ranga 3,
    # "WTK" to ranga 5, "MW" to ranga 4 (tests/test_tournament_parser.py's
    # SAMPLE_PAGE fixture exercises the OTK/ranga=3 pair against real PZT
    # markup). There is no observed ranga=1/"MP" pair: TYPE_PREFIXES never
    # includes "MP", so a real ranga=1 tournament's name wouldn't match the
    # scraper's prefix regex at all -- see the PR description.
    known_type_prefix_by_ranga = {
        2: "OTK SS",
        3: "OTK",
        4: "MW",
        5: "WTK",
    }
    for ranga, type_prefix in known_type_prefix_by_ranga.items():
        derived = ranga_prefix(ranga)
        assert derived is not None
        assert derived in type_prefix.split()


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
    assert "08.08.2026" in text


def test_category_selected_text_contains_short_form():
    # CLAUDE.md step 5.3, problem 1: the confirmation shown right after
    # tapping a category button must name the category in its short form.
    assert category_selected_text(AgeCategory.MLODZICY, "pl") == "Wybrana kategoria wiekowa: U14"
    assert "U12" in category_selected_text(AgeCategory.SKRZATY, "pl")
    assert "U16" in category_selected_text(AgeCategory.KADECI, "pl")
    assert "U18" in category_selected_text(AgeCategory.JUNIORZY, "pl")


def test_selection_confirmation_falls_back_to_wojewodztwo_when_venue_city_is_null():
    text = selection_confirmation_text(
        venue_city=None,
        wojewodztwo="mazowieckie",
        category=AgeCategory.JUNIORZY,
        date_from=date(2026, 8, 8),
        lang="pl",
    )
    assert "mazowieckie" in text
