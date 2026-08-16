"""Inline keyboards for the operator side of the open support conversation
(CLAUDE.md, "Operations" > "Support"). Operator-facing only -- every label
here is hardcoded English, the same narrow, documented exception to
"never hardcode user-facing strings" the rest of "Operations" already
uses, since these buttons are only ever shown to an id in
`alarm_recipients()`, never a player.
"""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


class SupportReplyCallback(CallbackData, prefix="sprep"):
    """Opens -- or re-opens, after the operator session expired -- the
    tapping operator's own conversation with this player. Carries the
    player's own Telegram id, which is what support_operator_sessions is
    keyed on, rather than an invitation id or a support_threads row."""

    user_telegram_id: int


class SupportCloseCallback(CallbackData, prefix="sclse"):
    pass


def support_reply_keyboard(user_telegram_id: int, label: str) -> InlineKeyboardMarkup:
    """One button, carrying the player's Telegram id. Reused both for the
    "Reply: {name}" button on an incoming support message and for the
    "Reopen: {name}" button on an operator session's own expiry notice --
    both do exactly the same thing, so they share the one callback."""
    builder = InlineKeyboardBuilder()
    builder.button(text=label, callback_data=SupportReplyCallback(user_telegram_id=user_telegram_id))
    builder.adjust(1)
    return builder.as_markup()


def support_close_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Close conversation", callback_data=SupportCloseCallback())
    builder.adjust(1)
    return builder.as_markup()


def support_suspended_keyboard(waiting_players: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    """CLAUDE.md, "A SUSPENDED SESSION, FAILING CLOSED": one "Reply: {name}"
    button per player currently waiting, reusing the exact same
    SupportReplyCallback a fresh incoming message's own button uses --
    tapping either does the same thing, open (or reopen) this operator's
    session named for that one player."""
    builder = InlineKeyboardBuilder()
    for user_telegram_id, name in waiting_players:
        builder.button(
            text=f"Reply: {name}", callback_data=SupportReplyCallback(user_telegram_id=user_telegram_id)
        )
    builder.adjust(1)
    return builder.as_markup()
