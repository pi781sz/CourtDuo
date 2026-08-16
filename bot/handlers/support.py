"""/pomoc: a two-way support relay between a player and the operators in
`bot.staleness.alarm_recipients()` (CLAUDE.md, "Operations" > "Support").

This is player <-> operator only, never player <-> player -- CLAUDE.md
rule 1 forbids free-text messaging between players, and nothing here
relays a player's words to anyone but an operator, or an operator's words
to anyone but the one player who asked. See CLAUDE.md's "Support"
subsection for the full carve-out.

Router registered in bot.main alongside navigation/moje_deble/invite_friend/
viewers -- before the state-scoped routers -- so a persistent-reply-keyboard
tap still wins over a stale Support.waiting_message state, exactly as
CLAUDE.md's "Navigation" section already requires elsewhere.
"""

from __future__ import annotations

import html
import logging

from aiogram import Bot, F, Router
from aiogram.enums import ContentType
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.attempt_limiter import FailedAttemptLimiter
from bot.i18n import t
from bot.lang import lang_for
from bot.notifications import push
from bot.staleness import alarm_recipients
from bot.states import Support
from core.text import display_name
from db import crud

logger = logging.getLogger(__name__)

router = Router(name="support")

# A separate instance from bot.handlers.start's registration limiter --
# CLAUDE.md, "Support": "its own separate instance -- do not share the
# registration limiter." Same shape (5 per hour), same "one process per
# bot instance, in-memory counter is fine" reasoning.
_support_limiter = FailedAttemptLimiter()


def _escape(text: str) -> str:
    """The bot's default parse mode is HTML (bot.main); a player's or
    operator's own free-typed text must never be interpreted as markup --
    an unescaped "<" would either break delivery outright or render
    oddly. quote=False keeps quote characters as-is in the message body,
    where they're not inside any HTML attribute."""
    return html.escape(text, quote=False)


@router.message(Command("pomoc"))
async def handle_pomoc(message: Message, state: FSMContext, session: AsyncSession) -> None:
    """Works whether or not the Telegram account has an Account row --
    CLAUDE.md: "the single most likely support message is 'I could not
    register', from someone who by definition has no account."""
    account = await crud.get_account_by_telegram_id(session, message.from_user.id)
    lang = lang_for(account)
    await message.answer(t("support.prompt", lang))
    await state.set_state(Support.waiting_message)


@router.message(Support.waiting_message, F.content_type != ContentType.TEXT)
async def handle_pomoc_non_text(message: Message, session: AsyncSession) -> None:
    """Never relays media in either direction. The state stays set so the
    player can simply try again with text -- CLAUDE.md, "Support"."""
    account = await crud.get_account_by_telegram_id(session, message.from_user.id)
    lang = lang_for(account)
    await message.answer(t("support.non_text_refusal", lang))


@router.message(Support.waiting_message)
async def handle_pomoc_message(message: Message, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    telegram_id = message.from_user.id
    account = await crud.get_account_by_telegram_id(session, telegram_id)
    lang = lang_for(account)

    if _support_limiter.is_blocked(telegram_id):
        await state.clear()
        await message.answer(t("support.rate_limited", lang))
        return

    _support_limiter.record_failure(telegram_id)
    await state.clear()

    if account is not None:
        sender_line = f"{_escape(display_name(account.full_name))} ({_escape(account.pzt_id)})"
    else:
        sender_line = "not registered"

    operator_text = (
        "CourtDuo support message\n"
        f"From: {sender_line}\n"
        f"Telegram id: {telegram_id}\n\n"
        f"{_escape(message.text or '')}"
    )

    for operator_id in alarm_recipients():
        sent_message_id = await push(bot, operator_id, operator_text)
        if sent_message_id is None:
            continue
        # A private DM's chat id is the operator's own telegram id -- the
        # same id `push` sent to -- since bot.notifications.push always
        # opens/uses that account's own chat with the bot.
        await crud.create_support_thread(session, operator_id, sent_message_id, telegram_id)

    await message.answer(t("support.confirmation", lang))


async def _is_operator_reply(message: Message) -> bool:
    return (
        message.reply_to_message is not None
        and message.text is not None
        and message.from_user is not None
        and message.from_user.id in alarm_recipients()
    )


@router.message(_is_operator_reply)
async def handle_operator_reply(message: Message, session: AsyncSession, bot: Bot) -> None:
    """CLAUDE.md, "Support", OPERATOR REPLY PATH. The filter above already
    guarantees the sender is in alarm_recipients() -- anyone else's
    reply-to never reaches this handler at all, matching the "invisible,
    not merely locked" discipline bot.handlers.status and /podglad already
    use: no outbound message, no reply of any kind.
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
    reply_text = f"{t('support.reply_header', lang)}\n\n{_escape(message.text or '')}"
    await push(bot, thread.user_telegram_id, reply_text)
