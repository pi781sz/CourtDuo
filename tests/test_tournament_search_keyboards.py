"""Tests for the step 5.2 "no pagination" behaviour: results_keyboard shows
one button per tournament with no "show more" button, and the results
message gets a narrowing note only when the 40-button safety cap is hit
(CLAUDE.md, "Tournament selection"). Pure functions only, no database.
Invented tournament guids/cities only.
"""

from __future__ import annotations

from datetime import date

from bot.handlers.tournament_search import _results_text
from bot.keyboards.navigation import FindPartnerCallback, MojeDebleCallback
from bot.keyboards.tournament_search import (
    ChangeCategoryCallback,
    ChangePlaceCallback,
    category_keyboard,
    no_matches_keyboard,
    none_eligible_keyboard,
    results_keyboard,
)
from bot.tournament_search import (
    CATEGORY_ORDER,
    MAX_RESULTS,
    TournamentOption,
    cap_results,
    categories_for_own_category,
)

_NAV_BUTTON_COUNT = 2  # "Zmień miejscowość" + "Zmień kategorię wiekową"


def _options(n: int) -> list[TournamentOption]:
    return [
        TournamentOption(guid=f"t{i}", date_from=date(2026, 8, 1), venue_city="Miasto", wojewodztwo=None)
        for i in range(n)
    ]


def _all_button_texts(markup) -> list[str]:
    return [button.text for row in markup.inline_keyboard for button in row]


def test_results_keyboard_shows_all_12_with_no_more_button():
    options = _options(12)
    shown, capped = cap_results(options)
    assert capped is False

    markup = results_keyboard(shown, "pl")
    texts = _all_button_texts(markup)

    assert len(texts) == 12 + _NAV_BUTTON_COUNT
    assert not any("więcej" in text.lower() for text in texts)


def test_results_keyboard_45_tournaments_capped_at_40_buttons():
    options = _options(45)
    shown, capped = cap_results(options)
    assert capped is True
    assert len(shown) == MAX_RESULTS == 40

    markup = results_keyboard(shown, "pl")
    texts = _all_button_texts(markup)

    assert len(texts) == 40 + _NAV_BUTTON_COUNT


def test_results_text_adds_narrowing_note_only_when_capped():
    capped_text = _results_text(capped=True, lang="pl")
    uncapped_text = _results_text(capped=False, lang="pl")

    assert "zawęź" in capped_text.lower()
    assert "zawęź" not in uncapped_text.lower()


def _callback_prefixes(markup) -> list[str]:
    return [button.callback_data.split(":")[0] for row in markup.inline_keyboard for button in row if button.callback_data]


def test_every_post_category_keyboard_offers_change_category():
    # CLAUDE.md step 5.3, problem 2: once a category is chosen, every
    # keyboard the player can reach must offer a way back to the category
    # screen -- never just a subset of them.
    change_category_prefix = ChangeCategoryCallback.__prefix__

    keyboards = {
        "results_keyboard": results_keyboard(_options(3), "pl"),
        "results_keyboard_empty": results_keyboard([], "pl"),
        "no_matches_keyboard": no_matches_keyboard("pl"),
        "none_eligible_keyboard": none_eligible_keyboard("pl"),
    }
    for name, markup in keyboards.items():
        assert change_category_prefix in _callback_prefixes(markup), f"{name} is missing change-category"


def test_none_eligible_keyboard_offers_only_change_category():
    # CLAUDE.md step 8.4: no [Menu] button any more -- the persistent
    # reply keyboard is always visible below the input box, so the only
    # button left here is the one real choice, "Zmień kategorię wiekową".
    markup = none_eligible_keyboard("pl")

    texts = _all_button_texts(markup)
    assert texts == ["Zmień kategorię wiekową"]


def test_no_matches_keyboard_still_offers_show_all_and_change_place():
    markup = no_matches_keyboard("pl")
    texts = _all_button_texts(markup)
    assert any("wszystkie" in text.lower() for text in texts)
    assert any("miejscowość" in text.lower() for text in texts)
    assert any("kategori" in text.lower() for text in texts)


def test_category_keyboard_offers_moje_deble_and_find_partner_too():
    # CLAUDE.md build order step 8: "Add 'Moje deble' alongside 'Znajdź
    # partnera' on the age-category screen too."
    counts = {category: 1 for category in CATEGORY_ORDER}
    markup = category_keyboard(counts, "pl")

    texts = _all_button_texts(markup)
    assert "Moje deble" in texts
    assert "Znajdź partnera" in texts
    prefixes = _callback_prefixes(markup)
    assert MojeDebleCallback.__prefix__ in prefixes
    assert FindPartnerCallback.__prefix__ in prefixes


def test_no_pagination_callback_classes_remain():
    # ChangePlaceCallback/ChangeCategoryCallback still exist; the page/show-
    # more callback was removed entirely (step 5.2).
    import bot.keyboards.tournament_search as keyboards_module

    assert not hasattr(keyboards_module, "TournamentPageCallback")
    assert ChangePlaceCallback is not None
    assert ChangeCategoryCallback is not None


def test_category_keyboard_filters_by_own_category():
    # CLAUDE.md step 8.3, PROBLEM 1a: a U16 player only sees U16/U18 --
    # U12/U14 are hidden entirely, not shown disabled.
    from db.models import AgeCategory

    counts = {category: 1 for category in CATEGORY_ORDER}
    markup = category_keyboard(counts, "pl", AgeCategory.KADECI)

    texts = _all_button_texts(markup)
    assert "U12" not in texts
    assert "U14" not in texts
    assert "U16" in texts
    assert "U18" in texts


def test_category_keyboard_with_no_own_category_shows_all_four():
    from db.models import AgeCategory

    counts = {category: 1 for category in CATEGORY_ORDER}
    markup = category_keyboard(counts, "pl", None)

    texts = _all_button_texts(markup)
    assert texts[:4] == ["U12", "U14", "U16", "U18"]
    assert categories_for_own_category(AgeCategory.SKRZATY) == CATEGORY_ORDER
