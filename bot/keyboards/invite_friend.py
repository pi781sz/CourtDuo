"""Inline keyboard for "Zaproś na CourtDuo" (CLAUDE.md step 8.4, CHANGE 2):
two URL buttons, WhatsApp and Telegram. Telegram's Bot API only accepts
http(s) (and tg://) schemes for an inline URL button and rejects an sms:
one outright -- so there is deliberately no SMS button here; the SMS case
is handled by putting the share text in the message body instead (see
bot.handlers.invite_friend).
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
