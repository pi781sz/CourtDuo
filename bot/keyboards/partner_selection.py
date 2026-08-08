"""Inline keyboard for the partner-name disambiguation screen (CLAUDE.md,
"Disambiguation"; build order step 6). One button per name-matched
candidate; tapping one resolves the ambiguity and runs the remaining
pre-invitation checks exactly as a single match would (see
bot.handlers.partner_selection.handle_partner_select).
"""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.partner_selection import CandidateOption


class PartnerSelectCallback(CallbackData, prefix="psel"):
    pzt_id: str


def disambiguation_keyboard(options: list[CandidateOption]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for option in options:
        builder.button(text=option.label, callback_data=PartnerSelectCallback(pzt_id=option.pzt_id))
    builder.adjust(1)
    return builder.as_markup()
