"""Inline keyboard for "Zaproś na CourtDuo": two URL buttons, WhatsApp and
Telegram (CLAUDE.md step 8.4, CHANGE 2; the SMS option step 8.4 worked
around was dropped entirely by step 8.5, since Telegram's inline URL
buttons only accept http(s) (and tg://) schemes and reject an sms: one
outright).

Also reused by bot.invitation_send when a named player exists in PZT's
rankings but has no CourtDuo account yet (CLAUDE.md step 8.5, PROBLEM 4):
same two buttons, same generic share text -- the named player's own name
never goes into it, since that message may end up sent to anyone.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.i18n import t
from bot.invite_friend import telegram_share_url, whatsapp_url


def share_keyboard(link: str, text: str, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("invite_friend.whatsapp_button", lang), url=whatsapp_url(text))
    builder.button(text=t("invite_friend.telegram_button", lang), url=telegram_share_url(link, text))
    builder.adjust(1)
    return builder.as_markup()
