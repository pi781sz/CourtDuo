"""Runs before every router, on every message (CLAUDE.md, "Operations" >
"Support"): the open conversation on both sides of /pomoc.

Registered as an OUTER message middleware (bot.main.build_dispatcher),
which is what lets it run ahead of filter checking anywhere in the router
tree and, when it decides a message has already been fully handled here
(relayed, refused, or explained), stop it from reaching any router at all
-- exactly what "silently reroute a child's message to support instead of
wherever it was headed" requires. Everything else -- a command, a
persistent-reply-keyboard label, an ordinary message from someone with no
open conversation -- falls straight through to `handler(event, data)`
unchanged, so navigation/moje_deble/invite_friend/viewers and every
state-scoped router downstream see it exactly as before this step.

Opens its own short-lived session per message via the same
async_sessionmaker bot.middlewares.db.DbSessionMiddleware uses --
deliberately independent of that middleware's own session, since this one
is OUTER (runs before any handler is chosen, let alone wrapped) while
DbSessionMiddleware is INNER (only wraps the handler that actually
matched). Commits its own writes itself; never touches `data["session"]`.

Order of checks, all lazy -- no scheduler anywhere:

  1. An explicit reply-to always wins (CLAUDE.md: "explicit beats
     implicit") -- untouched, falls through to bot.handlers.support's own
     `_is_operator_reply` path unchanged, suspended session or not.
  2. Non-text content: refused with a plain message if either side has an
     open conversation with this sender, otherwise ignored (falls through,
     same as before this step).
  3. A command or a persistent-reply-keyboard label: silently closes this
     Telegram id's own player conversation (a no-op if it had none), then
     falls through so the real command/label router handles it normally.
  4. An operator (`alarm_recipients()`) with an open, unexpired session:
     relayed to the player that session names, with a one-line English
     delivery receipt back to the operator naming who got it. Expired:
     the session is closed, the operator told, offered a button to
     reopen -- nothing is delivered. SUSPENDED (see step 5): nothing is
     delivered either -- the operator is shown one "Reply: {name}" button
     per player currently waiting and must pick one before anything they
     type reaches anybody.
  5. A player with an open, unexpired conversation: relayed to every
     operator, rate-capped exactly as the one-shot /pomoc relay always
     was, with no automatic reply to the player -- the operator's own
     answer is the next thing they see. Any *other* operator whose own
     open session currently names someone other than this sender is
     flipped to SUSPENDED at the same moment (CLAUDE.md: "A SUSPENDED
     SESSION, FAILING CLOSED") -- fail closed rather than let a stale
     target silently receive whatever that operator types next. Expired:
     the conversation is closed, the player told their message was not
     sent, pointed at /pomoc -- nothing is relayed.
  6. An operator with no Account row, plain text, no open conversation,
     no reply-to: told there is no open conversation instead of falling
     into the registration handler (the bug this step fixes -- CLAUDE.md,
     "Operations" > "Support", THE REGISTRATION FALL-THROUGH).
  7. Everything else: falls through untouched.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from aiogram import BaseMiddleware, Bot
from aiogram.enums import ContentType
from aiogram.types import Message, TelegramObject
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.attempt_limiter import FailedAttemptLimiter
from bot.i18n import t
from bot.keyboards.support import support_reply_keyboard, support_suspended_keyboard
from bot.lang import lang_for
from bot.notifications import push
from bot.staleness import alarm_recipients
from bot.support_conversations import (
    OPERATOR_SESSION_TTL,
    PLAYER_CONVERSATION_TTL,
    escape,
    is_command,
    is_nav_label,
)
from core.text import display_name
from db import crud
from db.session import get_session_factory

logger = logging.getLogger(__name__)

# A separate instance from every other FailedAttemptLimiter in this
# codebase (registration's, /pomoc's old one) -- CLAUDE.md, "Support":
# "its own separate instance." Caps how often one player's messages get
# relayed while their conversation is open, same shape (5/hour) the
# one-shot /pomoc relay always used.
_relay_limiter = FailedAttemptLimiter()


async def _relay_player_message(session, bot: Bot, account, telegram_id: int, text: str) -> None:
    """CLAUDE.md, "Operations" > "Support", OPERATOR SIDE: "Every incoming
    support message gets an inline button ... Reply: {name}." Broadcasts
    to every operator, exactly as the original one-shot relay did, one
    support_threads row per delivered copy so the reply-to fallback keeps
    working regardless."""
    if account is not None:
        who = display_name(account.full_name)
        sender_line = f"{escape(who)} ({escape(account.pzt_id)})"
        button_label = f"Reply: {who}"
    else:
        sender_line = "not registered"
        button_label = f"Reply: telegram id {telegram_id}"

    operator_text = (
        "CourtDuo support message\n"
        f"From: {sender_line}\n"
        f"Telegram id: {telegram_id}\n\n"
        f"{escape(text)}"
    )
    keyboard = support_reply_keyboard(telegram_id, button_label)
    for operator_id in alarm_recipients():
        sent_message_id = await push(bot, operator_id, operator_text, reply_markup=keyboard)
        if sent_message_id is None:
            continue
        await crud.create_support_thread(session, operator_id, sent_message_id, telegram_id)


async def _waiting_players(session, now: datetime, op_session) -> list[tuple[int, str]]:
    """Every player worth offering a SUSPENDED operator session a
    "Reply: {name}" button for (CLAUDE.md: "the bot replies ... naming
    both waiting players"): whoever the session still remembers being
    with -- it never forgets that on its own -- plus every player
    currently sitting on an unexpired open conversation. Sorted by
    Telegram id purely for a stable, deterministic button order."""
    telegram_ids = {op_session.user_telegram_id}
    for conversation in await crud.list_open_support_conversations(session):
        if now - conversation.last_activity_at <= PLAYER_CONVERSATION_TTL:
            telegram_ids.add(conversation.user_telegram_id)

    waiting: list[tuple[int, str]] = []
    for user_telegram_id in sorted(telegram_ids):
        account = await crud.get_account_by_telegram_id(session, user_telegram_id)
        name = display_name(account.full_name) if account is not None else f"telegram id {user_telegram_id}"
        waiting.append((user_telegram_id, name))
    return waiting


class SupportConversationMiddleware(BaseMiddleware):
    def __init__(self, session_factory: async_sessionmaker | None = None) -> None:
        self._session_factory = session_factory or get_session_factory()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or event.from_user is None:
            return await handler(event, data)

        # CLAUDE.md: "A reply-to-message still works and ALWAYS WINS over
        # the open conversation -- explicit beats implicit." Untouched --
        # bot.handlers.support's _is_operator_reply path takes it from here.
        if event.reply_to_message is not None:
            return await handler(event, data)

        telegram_id = event.from_user.id
        bot: Bot = data["bot"]
        now = datetime.now(timezone.utc)
        is_operator = telegram_id in alarm_recipients()

        async with self._session_factory() as session:
            account = await crud.get_account_by_telegram_id(session, telegram_id)
            lang = lang_for(account)

            if event.content_type != ContentType.TEXT:
                if is_operator:
                    op_session = await crud.get_operator_session(session, telegram_id)
                    if op_session is not None and now - op_session.last_activity_at <= OPERATOR_SESSION_TTL:
                        await event.answer("CourtDuo support: only text can be relayed. Please type your reply.")
                        return None
                conversation = await crud.get_support_conversation(session, telegram_id)
                if (
                    conversation is not None
                    and conversation.is_open
                    and now - conversation.last_activity_at <= PLAYER_CONVERSATION_TTL
                ):
                    await event.answer(t("support.non_text_refusal", lang))
                    return None
                return await handler(event, data)

            text = event.text or ""

            if is_command(text) or is_nav_label(text):
                # CLAUDE.md, "Operations" > "Support", PLAYER SIDE: "the
                # player taps any persistent-reply-keyboard label, or sends
                # any command -- handled normally, and the conversation
                # closes silently." A no-op if there was nothing open.
                await crud.close_support_conversation(session, telegram_id)
                await session.commit()
                return await handler(event, data)

            if is_operator:
                op_session = await crud.get_operator_session(session, telegram_id)
                if op_session is not None:
                    if now - op_session.last_activity_at > OPERATOR_SESSION_TTL:
                        watched_account = await crud.get_account_by_telegram_id(
                            session, op_session.user_telegram_id
                        )
                        watched_name = (
                            display_name(watched_account.full_name)
                            if watched_account is not None
                            else f"telegram id {op_session.user_telegram_id}"
                        )
                        await crud.close_operator_session(session, telegram_id)
                        await session.commit()
                        await event.answer(
                            f"CourtDuo support: your conversation with {watched_name} expired after "
                            "60 minutes of inactivity.",
                            reply_markup=support_reply_keyboard(
                                op_session.user_telegram_id, f"Reopen: {watched_name}"
                            ),
                        )
                        return None

                    if op_session.state == "suspended":
                        # CLAUDE.md: "A SUSPENDED SESSION, FAILING CLOSED"
                        # -- another player wrote in while this operator
                        # was away from this one. Nothing typed here is
                        # delivered to anyone until they explicitly pick
                        # who they mean again.
                        waiting = await _waiting_players(session, now, op_session)
                        await session.commit()
                        await event.answer(
                            "CourtDuo support: more than one player is waiting and this "
                            "conversation is suspended. Nothing you type is delivered until "
                            "you choose who to reply to:",
                            reply_markup=support_suspended_keyboard(waiting),
                        )
                        return None

                    watched_account = await crud.get_account_by_telegram_id(session, op_session.user_telegram_id)
                    watched_name = (
                        display_name(watched_account.full_name)
                        if watched_account is not None
                        else f"telegram id {op_session.user_telegram_id}"
                    )
                    reply_text = f"{t('support.reply_header', lang_for(watched_account))}\n\n{escape(text)}"
                    sent_message_id = await push(bot, op_session.user_telegram_id, reply_text)
                    await crud.touch_operator_session(session, telegram_id, now)
                    await session.commit()
                    if sent_message_id is not None:
                        # CLAUDE.md: "DELIVERY RECEIPTS TO THE OPERATOR" --
                        # what makes a misroute visible on the spot instead
                        # of several messages later.
                        await event.answer(f"Sent to {watched_name}.")
                    return None

            conversation = await crud.get_support_conversation(session, telegram_id)
            if conversation is not None and conversation.is_open:
                if now - conversation.last_activity_at > PLAYER_CONVERSATION_TTL:
                    await crud.close_support_conversation(session, telegram_id)
                    await session.commit()
                    await event.answer(t("support.conversation_expired", lang))
                    return None

                if _relay_limiter.is_blocked(telegram_id):
                    await session.commit()
                    await event.answer(t("support.rate_limited", lang))
                    return None
                _relay_limiter.record_failure(telegram_id)

                await _relay_player_message(session, bot, account, telegram_id, text)
                # CLAUDE.md: "A SUSPENDED SESSION, FAILING CLOSED" -- any
                # other operator's own open session that names someone
                # other than this sender must not go on delivering to a
                # stale target now that this player has written in too.
                await crud.suspend_other_operator_sessions(session, telegram_id)
                await crud.touch_support_conversation(session, telegram_id, now)
                await session.commit()
                # CLAUDE.md: "REMOVE THE PER-MESSAGE CONFIRMATION TO THE
                # PLAYER" -- the conversation-opened message already told
                # them their answer arrives here; the next thing they see
                # is the operator's own reply.
                return None

            if is_operator and account is None:
                # CLAUDE.md, "Operations" > "Support", THE REGISTRATION
                # FALL-THROUGH: an id on ALARM_TELEGRAM_IDS cannot register
                # as a player while it is on that list -- see also
                # bot.handlers.start, which never sees this message.
                await event.answer(
                    "CourtDuo support: no open conversation. Tap Reply on a support message to open one."
                )
                return None

            return await handler(event, data)
