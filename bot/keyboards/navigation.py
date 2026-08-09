"""The [Menu] navigation button and the menu it opens (CLAUDE.md, step 7.1,
"a way back", reworked by step 8.2 into a single entry point): a terminal
message — one that ends a flow with nothing else to tap — carries one
[Menu] button rather than "Znajdź partnera" and "Moje deble" side by side.
Tapping it shows a small menu message with both options. Handlers live in
bot.handlers.navigation (Menu, Znajdź partnera) and bot.handlers.moje_deble
(Moje deble); this module only builds the keyboards, since every module
that composes a terminal message needs one alongside whatever other
reply_markup it was already passing (usually none).

find_partner_keyboard stays single-button for the one place a "Moje deble"
button would point back at itself: the "Moje deble" summary and its empty
state (CLAUDE.md, "Moje deble" status view).
"""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.i18n import t


class FindPartnerCallback(CallbackData, prefix="fpart"):
    pass


class MojeDebleCallback(CallbackData, prefix="mdeble"):
    pass


class MenuCallback(CallbackData, prefix="menu"):
    pass


def find_partner_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("common.find_partner_button", lang), callback_data=FindPartnerCallback())
    builder.adjust(1)
    return builder.as_markup()


def terminal_keyboard(lang: str) -> InlineKeyboardMarkup:
    """CLAUDE.md build order step 8.2: a terminal message — the journey has
    ended and the player has no next step in the current flow — carries
    exactly one button, [Menu], rather than the two direct buttons step 8
    used. Tapping it opens menu_keyboard()'s chooser.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text=t("common.menu_button", lang), callback_data=MenuCallback())
    builder.adjust(1)
    return builder.as_markup()


def menu_keyboard(lang: str) -> InlineKeyboardMarkup:
    """The chooser [Menu] opens: "Znajdź partnera" and "Moje deble", in
    that order (CLAUDE.md step 8.2)."""
    builder = InlineKeyboardBuilder()
    builder.button(text=t("common.find_partner_button", lang), callback_data=FindPartnerCallback())
    builder.button(text=t("common.moje_deble_button", lang), callback_data=MojeDebleCallback())
    builder.adjust(1)
    return builder.as_markup()
