"""The persistent reply keyboard (CLAUDE.md, step 8.4) and the one inline
button that survives alongside it.

Step 8.2's inline [Menu] button — attached to every terminal message so a
player always had a way back — is gone: persistent_menu_keyboard() is
attached once at the start of a session and stays visible under the input
box the whole time, so no individual message needs a navigation button of
its own any more.

find_partner_keyboard is the one exception, kept for bot.handlers.moje_deble:
its own summary/empty state still needs a single "Znajdź partnera" button
rather than "Moje deble" too, since tapping "Moje deble" there would just
point back at the screen already on screen.
"""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from bot.i18n import t


class FindPartnerCallback(CallbackData, prefix="fpart"):
    pass


class MojeDebleCallback(CallbackData, prefix="mdeble"):
    pass


def find_partner_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("common.find_partner_button", lang), callback_data=FindPartnerCallback())
    builder.adjust(1)
    return builder.as_markup()


def persistent_menu_keyboard(lang: str) -> ReplyKeyboardMarkup:
    """CLAUDE.md step 8.4: [Znajdź partnera] alone on its own row, [Moje
    deble] and [Zaproś na CourtDuo] sharing the next -- resize_keyboard so
    it doesn't take up the whole screen, is_persistent so it doesn't hide
    itself after one tap."""
    builder = ReplyKeyboardBuilder()
    builder.button(text=t("common.find_partner_button", lang))
    builder.button(text=t("common.moje_deble_button", lang))
    builder.button(text=t("common.invite_button", lang))
    builder.adjust(1, 2)
    return builder.as_markup(resize_keyboard=True, is_persistent=True)
