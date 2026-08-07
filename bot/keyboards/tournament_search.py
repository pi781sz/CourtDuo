"""Inline keyboards for tournament-place search (CLAUDE.md, "Tournament
selection"; build order step 5). Callback data classes live here
alongside the keyboards they build, since bot/handlers/tournament_search.py
needs both — the classes for `.filter()`/unpacking, the builders for
rendering.
"""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.i18n import t
from bot.tournament_search import TournamentOption, tournament_label


class TournamentSelectCallback(CallbackData, prefix="tsel"):
    guid: str


class TournamentPageCallback(CallbackData, prefix="tpage"):
    offset: int


class ShowAllTournamentsCallback(CallbackData, prefix="tall"):
    pass


class ChangePlaceCallback(CallbackData, prefix="tchg"):
    pass


def results_keyboard(
    page: list[TournamentOption], has_more: bool, next_offset: int, lang: str
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for option in page:
        builder.button(text=tournament_label(option), callback_data=TournamentSelectCallback(guid=option.guid))
    if has_more:
        builder.button(
            text=t("tournament_search.show_more", lang),
            callback_data=TournamentPageCallback(offset=next_offset),
        )
    builder.button(text=t("tournament_search.change_place", lang), callback_data=ChangePlaceCallback())
    builder.adjust(1)
    return builder.as_markup()


def no_matches_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("tournament_search.show_all", lang), callback_data=ShowAllTournamentsCallback())
    builder.button(text=t("tournament_search.change_place", lang), callback_data=ChangePlaceCallback())
    builder.adjust(1)
    return builder.as_markup()
