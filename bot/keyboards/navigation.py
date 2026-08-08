"""The "Znajdź partnera" and "Moje deble" buttons (CLAUDE.md, step 7.1,
"a way back", extended by step 8's terminal-message audit): every terminal
message — one that ends a flow with nothing else to tap — carries both, so
`/start` is never the only way forward and a player is never stuck without
a link to their own status view. Handlers live in bot.handlers.navigation
(Znajdź partnera) and bot.handlers.moje_deble (Moje deble); this module
only builds the keyboards, since every module that composes a terminal
message needs one of them alongside whatever other reply_markup it was
already passing (usually none).

find_partner_keyboard stays single-button for the one place a "Moje deble"
button would point back at itself: the empty state of /moje_deble.
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


def find_partner_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("common.find_partner_button", lang), callback_data=FindPartnerCallback())
    builder.adjust(1)
    return builder.as_markup()


def terminal_keyboard(lang: str) -> InlineKeyboardMarkup:
    """CLAUDE.md build order step 8: "Every one of them gets both buttons:
    [Moje deble] [Znajdź partnera]." The pair every terminal message in
    bot.handlers.invitations carries, plus every place elsewhere in this
    audit that turned out to end a flow with nothing else to tap.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text=t("common.moje_deble_button", lang), callback_data=MojeDebleCallback())
    builder.button(text=t("common.find_partner_button", lang), callback_data=FindPartnerCallback())
    builder.adjust(1)
    return builder.as_markup()
