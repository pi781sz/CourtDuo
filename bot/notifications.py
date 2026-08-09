"""Pushing a message to a player who is not in a conversation.

Everything in steps 4-6 replies to an update the player just sent. Step 7
is the first code that has to reach somebody unprompted: the invitee when
an invitation arrives, the inviter when it is answered, and the players
whose own invitations were cancelled by somebody else's match.

A push can simply fail — the player may have blocked the bot, deleted the
chat, or never started one. That is a normal outcome here, not an error to
propagate: an unhandled TelegramForbiddenError inside an accept handler
would abort the handler after the transaction had already decided the
match, leaving the two players matched in the database and told nothing.
So `push` swallows the API's failures, logs them and reports whether the
message landed, and callers decide what a failed delivery means. For a new
invitation it means the invitation must not stay 🟠 pending against a
player who will never see it (see bot.handlers.invitations); for a status
update it means nothing beyond the log line.

Only telegram ids and invitation ids are logged, never names — the same
rule bot.registration follows, for the same reason: these are children.
"""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup

logger = logging.getLogger(__name__)


async def push(
    bot: Bot,
    telegram_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup | ReplyKeyboardMarkup | None = None,
) -> bool:
    """Sends `text` to `telegram_id`. Returns True if Telegram accepted it."""
    try:
        await bot.send_message(telegram_id, text, reply_markup=reply_markup)
        return True
    except TelegramForbiddenError:
        # Blocked the bot, or deleted the chat.
        logger.warning("Push rejected by Telegram (blocked or chat deleted): telegram_id=%s", telegram_id)
        return False
    except TelegramBadRequest as exc:
        # "chat not found" and friends — the account exists in CourtDuo but
        # the chat behind it no longer does.
        logger.warning("Push failed: telegram_id=%s (%s)", telegram_id, exc)
        return False
    except TelegramAPIError:
        # Network trouble, rate limits, an outage. Unexpected, so it keeps
        # its traceback, but it still must not take the handler down.
        logger.exception("Push failed unexpectedly: telegram_id=%s", telegram_id)
        return False
