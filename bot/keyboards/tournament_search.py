"""Inline keyboards for tournament search (CLAUDE.md, "Tournament
selection"; build order step 5, revised by step 5.1 to add the age
category screen, and by step 5.3 so "Zmień kategorię wiekową" appears on
every keyboard shown after a category has been chosen). Callback data
classes live here alongside the keyboards they build, since
bot/handlers/tournament_search.py needs both — the classes for
`.filter()`/unpacking, the builders for rendering.
"""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.i18n import t
from bot.tournament_search import (
    TournamentOption,
    categories_for_own_category,
    category_is_available,
    category_short_label,
    tournament_label,
)
from db.models import AgeCategory


class CategorySelectCallback(CallbackData, prefix="tcat"):
    category: str


class TournamentSelectCallback(CallbackData, prefix="tsel"):
    guid: str


class ShowAllTournamentsCallback(CallbackData, prefix="tall"):
    pass


class ChangePlaceCallback(CallbackData, prefix="tchg"):
    pass


class ChangeCategoryCallback(CallbackData, prefix="tchgcat"):
    pass


def category_keyboard(
    counts: dict[AgeCategory, int], lang: str, own_category: AgeCategory | None = None
) -> InlineKeyboardMarkup:
    """CLAUDE.md step 8.3, PROBLEM 1a: only offers categories the player is
    eligible for (>= their own -- see bot.tournament_search.
    categories_for_own_category); `own_category=None` offers all four,
    used when it cannot be derived."""
    builder = InlineKeyboardBuilder()
    for category in categories_for_own_category(own_category):
        short = category_short_label(category, lang)
        if category_is_available(counts, category):
            text = short
        else:
            text = t("tournament_search.category_unavailable", lang, category=short)
        builder.button(text=text, callback_data=CategorySelectCallback(category=category.name))
    # CLAUDE.md step 12.1, PROBLEM 6: no "Moje deble" / "Znajdź partnera"
    # buttons here -- both already live on the persistent reply keyboard
    # below the input box, and mixing them into this grid of real choices
    # (the category buttons) risked a mis-tap losing the player's place.
    # An inline keyboard carries only the choices relevant to its own
    # message; navigation lives on the persistent keyboard alone.
    builder.adjust(2)
    return builder.as_markup()


def results_keyboard(options: list[TournamentOption], lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for option in options:
        builder.button(text=tournament_label(option), callback_data=TournamentSelectCallback(guid=option.guid))
    builder.button(text=t("tournament_search.change_place", lang), callback_data=ChangePlaceCallback())
    builder.button(text=t("tournament_search.change_category", lang), callback_data=ChangeCategoryCallback())
    builder.adjust(1)
    return builder.as_markup()


def no_matches_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("tournament_search.show_all", lang), callback_data=ShowAllTournamentsCallback())
    builder.button(text=t("tournament_search.change_place", lang), callback_data=ChangePlaceCallback())
    builder.button(text=t("tournament_search.change_category", lang), callback_data=ChangeCategoryCallback())
    builder.adjust(1)
    return builder.as_markup()


def none_eligible_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Shown with "none_eligible" (CLAUDE.md step 5.3): zero tournaments
    match this category at all, so "Zmień miejscowość" would only lead to
    the same dead end again — only a category change can help. CLAUDE.md
    step 8.4: no [Menu] button needed alongside it any more -- the
    persistent reply keyboard is always visible below the input box."""
    builder = InlineKeyboardBuilder()
    builder.button(text=t("tournament_search.change_category", lang), callback_data=ChangeCategoryCallback())
    builder.adjust(1)
    return builder.as_markup()
