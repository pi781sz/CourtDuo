"""Inline keyboards for self-service account deletion (CLAUDE.md step 12,
"Self-service deletion"). Two screens, three buttons total -- the first
screen's "Usuń konto" leads to the second, which is the only one that
actually deletes anything. Mirrors the release-match confirmation pair
(bot.keyboards.invitations.release_match_confirm_keyboard, the button
itself carried by bot.keyboards.navigation.moje_deble_summary_keyboard
since step 12.1) in shape.
"""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.i18n import t


class DeleteAccountStartCallback(CallbackData, prefix="delacc"):
    pass


class DeleteAccountConfirmCallback(CallbackData, prefix="delaccy"):
    pass


class DeleteAccountAbortCallback(CallbackData, prefix="delaccn"):
    pass


def delete_account_explain_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("deletion.start_button", lang), callback_data=DeleteAccountStartCallback())
    builder.button(text=t("deletion.abort_button", lang), callback_data=DeleteAccountAbortCallback())
    builder.adjust(1)
    return builder.as_markup()


def delete_account_confirm_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("deletion.confirm_button", lang), callback_data=DeleteAccountConfirmCallback())
    builder.button(text=t("deletion.abort_button", lang), callback_data=DeleteAccountAbortCallback())
    builder.adjust(1)
    return builder.as_markup()
