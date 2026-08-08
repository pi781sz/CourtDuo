"""The "Znajdź partnera" button (CLAUDE.md, step 7.1, "a way back"): every
terminal message — one that ends a flow with nothing else to tap — carries
this button so `/start` is never the only way forward. Its handler lives
in bot.handlers.navigation; this module only builds the keyboard, since
every module that composes a terminal message (bot.handlers.invitations
today) needs it alongside whatever other reply_markup it was already
passing (usually none).
"""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.i18n import t


class FindPartnerCallback(CallbackData, prefix="fpart"):
    pass


def find_partner_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("common.find_partner_button", lang), callback_data=FindPartnerCallback())
    builder.adjust(1)
    return builder.as_markup()
