"""/pomoc: an open, two-way support conversation between a player and the
operators in `bot.staleness.alarm_recipients()` (CLAUDE.md, "Operations" >
"Support").

This is player <-> operator only, never player <-> player -- non-negotiable
rule 1 forbids free-text messaging between players, and nothing here
relays a player's words to anyone but an operator, or an operator's words
to anyone but the one player their own open session (or an explicit
reply-to) names. See CLAUDE.md's "Support" subsection for the full
carve-out.

The actual relaying -- and the lazy 30-/60-minute expiry that closes a
conversation without a scheduler -- lives in
bot.middlewares.support_conversation, an OUTER message middleware that
runs ahead of every router (bot.main.build_dispatcher) so it can catch a
player's or operator's plain text regardless of which router would
otherwise have claimed it. This module only owns what's left: opening a
conversation on /pomoc, the reply-to fallback (unchanged from before this
step), and the two buttons an operator taps -- "Reply: {name}" and "Close
conversation".

Router registered in bot.main alongside navigation/moje_deble/invite_friend/
viewers -- before the state-scoped routers -- so a persistent-reply-keyboard
tap still wins against a stale support state, exactly as CLAUDE.md's
"Navigation" section already requires elsewhere. (In practice the outer
middleware above already intercepts a label tap before it would ever reach
here -- this router's own ordering only still matters for /pomoc itself and
the reply-to fallback.)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.i18n import t
from bot.keyboards.support import SupportCloseCallback, SupportReplyCallback, support_close_keyboard
from bot.lang import lang_for
from bot.notifications import push
from bot.staleness import alarm_recipients
from bot.support_conversations import escape
from core.text import display_name
from db import crud

logger = logging.getLogger(__name__)

router = Router(name="support")


@router.message(Command("pomoc"))
async def handle_pomoc(message: Message, session: AsyncSession) -> None:
    """Works whether or not the Telegram account has an Account row --
    CLAUDE.md: "the single most likely support message is 'I could not
    register', from someone who by definition has no account." Opens (or
    silently re-opens) this Telegram id's own conversation -- no FSM state
    involved, so a restart between /pomoc and the player's next message
    never loses it (see bot.middlewares.support_conversation)."""
    account = await crud.get_account_by_telegram_id(session, message.from_user.id)
    lang = lang_for(account)
    await crud.open_support_conversation(session, message.from_user.id, datetime.now(timezone.utc))
    await message.answer(t("support.conversation_opened", lang))


async def _is_operator_reply(message: Message) -> bool:
    return (
        message.reply_to_message is not None
        and message.text is not None
        and message.from_user is not None
        and message.from_user.id in alarm_recipients()
    )


@router.message(_is_operator_reply)
async def handle_operator_reply(message: Message, session: AsyncSession, bot: Bot) -> None:
    """CLAUDE.md, "Support": a reply-to always wins over the open
    conversation -- explicit beats implicit. Unchanged from before this
    step. The filter above already guarantees the sender is in
    alarm_recipients() -- anyone else's reply-to never reaches this
    handler at all, matching the "invisible, not merely locked" discipline
    bot.handlers.status and /podglad already use: no outbound message, no
    reply of any kind.
    """
    operator_chat_id = message.chat.id
    operator_message_id = message.reply_to_message.message_id

    thread = await crud.get_support_thread(session, operator_chat_id, operator_message_id)
    if thread is None:
        # "Never fail silently and never guess a recipient" -- tell the
        # operator plainly rather than dropping the reply.
        await message.answer("CourtDuo support: this message isn't a support thread I can route a reply for.")
        return

    account = await crud.get_account_by_telegram_id(session, thread.user_telegram_id)
    lang = lang_for(account)
    reply_text = f"{t('support.reply_header', lang)}\n\n{escape(message.text or '')}"
    await push(bot, thread.user_telegram_id, reply_text)


def _describe_player(account) -> str:
    if account is not None:
        return f"{display_name(account.full_name)} (PZT {account.pzt_id})"
    return "an unregistered Telegram id"


@router.callback_query(SupportReplyCallback.filter())
async def handle_support_reply_tap(
    callback: CallbackQuery, callback_data: SupportReplyCallback, session: AsyncSession
) -> None:
    """CLAUDE.md, "Operations" > "Support", OPERATOR SIDE: tapping "Reply:
    {name}" (on an incoming support message) or "Reopen: {name}" (on this
    operator's own expiry notice) both open the same operator session --
    the two buttons share this one callback because they do exactly the
    same thing. Only an id in alarm_recipients() may act on it at all --
    the same "invisible, not merely locked" discipline used everywhere
    else in "Operations": anyone else's tap gets no outbound message.
    """
    if callback.from_user.id not in alarm_recipients():
        await callback.answer()
        return

    account = await crud.get_account_by_telegram_id(session, callback_data.user_telegram_id)
    await crud.open_operator_session(
        session, callback.from_user.id, callback_data.user_telegram_id, datetime.now(timezone.utc)
    )
    await callback.answer()
    await callback.message.answer(
        f"Conversation opened with {_describe_player(account)}. Everything you type from now on "
        "goes to them.",
        reply_markup=support_close_keyboard(),
    )


@router.callback_query(SupportCloseCallback.filter())
async def handle_support_close_tap(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    """CLAUDE.md, "Operations" > "Support": "Close conversation ends it.
    Both the operator and the player are told." Also closes the player's
    own support_conversations row (CLAUDE.md, PLAYER SIDE: "the operator
    closes it" is one of the ways a player's own conversation ends) so a
    closed exchange doesn't keep broadcasting the player's next messages
    to every operator regardless."""
    if callback.from_user.id not in alarm_recipients():
        await callback.answer()
        return

    op_session = await crud.get_operator_session(session, callback.from_user.id)
    await crud.close_operator_session(session, callback.from_user.id)
    await callback.answer()

    if op_session is None:
        await callback.message.answer("CourtDuo support: no conversation was open.")
        return

    await crud.close_support_conversation(session, op_session.user_telegram_id)
    await callback.message.answer("Conversation closed.")

    user_account = await crud.get_account_by_telegram_id(session, op_session.user_telegram_id)
    lang = lang_for(user_account)
    await push(bot, op_session.user_telegram_id, t("support.conversation_closed_by_operator", lang))
