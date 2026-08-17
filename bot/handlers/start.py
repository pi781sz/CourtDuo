"""/start and PZT-id registration (CLAUDE.md, "Identity" + user journeys
1-3; build order step 4). Every conversation enters here: a new Telegram
account is asked for its PZT id and bound to exactly one player; a
returning account skips straight to tournament search.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import Bot, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.attempt_limiter import FailedAttemptLimiter
from bot.handlers.tournament_search import start_tournament_search
from bot.handlers.viewers import render_moje_deble_for_viewer
from bot.i18n import t
from bot.invitation_text import gendered
from bot.keyboards.navigation import persistent_menu_keyboard, viewer_menu_keyboard
from bot.lang import DEFAULT_LANG, lang_for
from bot.notifications import push
from bot.pending_external_invites import notify_pending_external_invites
from bot.registration import RegistrationOutcome, register_by_pzt_id
from bot.staleness import alarm_recipients
from bot.states import Registration
from bot.support_conversations import OPERATOR_SESSION_TTL
from bot.viewers import ViewerBindOutcome, bind_viewer
from core.text import display_name, first_name
from db import crud
from entitlements import can_use_viewers

logger = logging.getLogger(__name__)

router = Router(name="start")

# One process per bot instance, so a module-level, in-memory limiter is
# the "in-memory counter is fine" CLAUDE.md asks for — see
# bot.attempt_limiter's docstring.
_attempt_limiter = FailedAttemptLimiter()

_FAILURE_MESSAGE_KEYS = {
    RegistrationOutcome.NOT_FOUND: "registration.not_found",
    RegistrationOutcome.GENDER_CONFLICT: "registration.error_try_later",
    RegistrationOutcome.ALREADY_BOUND_TO_OTHER: "registration.already_bound",
    # CLAUDE.md step 12: deliberately the exact same wording as NOT_FOUND
    # -- "give no detail" means a blocked child must not be able to tell a
    # block apart from a mistyped id.
    RegistrationOutcome.BLOCKED: "registration.not_found",
}


@router.message(CommandStart())
async def handle_start(
    message: Message, state: FSMContext, session: AsyncSession, bot: Bot, command: CommandObject
) -> None:
    await state.clear()

    # CLAUDE.md step 10, GRANTING ACCESS: a deep-link payload
    # (t.me/<bot>?start=<token>) binds the tapper as a read-only viewer of
    # whichever player generated it. A used, expired or unknown token
    # falls straight through to plain /start below -- "never errors" -- so
    # this is deliberately not a branch that returns early on failure.
    payload = (command.args or "").strip()
    if payload:
        bind_result = await bind_viewer(
            session, message.from_user.id, payload, datetime.now(timezone.utc), message.from_user.full_name
        )
        if bind_result.outcome is ViewerBindOutcome.BOUND:
            watched = bind_result.watched_account
            # The viewer may or may not have a CourtDuo account of their
            # own (CLAUDE.md step 10: the two roles are independent) --
            # their own account's lang if they have one, DEFAULT_LANG
            # otherwise, same fallback bot.lang.lang_for uses everywhere.
            viewer_account = await crud.get_account_by_telegram_id(session, message.from_user.id)
            viewer_lang = lang_for(viewer_account)
            # CLAUDE.md step 10.1: a registered player acts as themselves
            # (their own keyboard is already full and stays that way) --
            # only a Telegram account with no player account of its own
            # needs the viewer-only keyboard, and this may be its first
            # message ever.
            await message.answer(
                gendered("viewer.bound", watched.gender, viewer_lang, name=display_name(watched.full_name)),
                reply_markup=None if viewer_account is not None else viewer_menu_keyboard(viewer_lang),
            )
            await push(
                bot,
                watched.telegram_id,
                t("viewer.player_notified_grant", lang_for(watched), telegram_name=message.from_user.full_name),
            )
            return

    account = await crud.get_account_by_telegram_id(session, message.from_user.id)
    if account is not None:
        # CLAUDE.md scenario 3: returning player skips registration
        # entirely, straight to tournament search. CLAUDE.md step 8.4: the
        # persistent reply keyboard is attached here, on /start, so it is
        # already present by the time the category screen shows up.
        lang = lang_for(account)
        await message.answer(
            t("start.greeting_returning", lang), reply_markup=persistent_menu_keyboard(lang, can_use_viewers(account))
        )
        await start_tournament_search(message, state, lang, session, account)
        return

    # CLAUDE.md step 10.1: a Telegram account with no player account of
    # its own may still be a read-only viewer of one or more players
    # (CLAUDE.md step 10) -- checked before falling into fresh
    # registration below, so their own /start opens the read-only view
    # with the viewer-only keyboard instead of asking for a PZT id that
    # doesn't apply to them.
    if await crud.get_active_viewer_grants_for_telegram_id(session, message.from_user.id):
        await message.answer(
            t("start.greeting_viewer", DEFAULT_LANG), reply_markup=viewer_menu_keyboard(DEFAULT_LANG)
        )
        await render_moje_deble_for_viewer(message, session, message.from_user.id, DEFAULT_LANG)
        return

    # CLAUDE.md step 14.3: an id in alarm_recipients() with no Account row
    # can never finish registration -- see bot.middlewares.support_conversation's
    # own "registration fall-through" fix, the same trade-off applies here
    # by construction. Offering the PZT-id prompt here is a guaranteed dead
    # end, and worse: SupportConversationMiddleware cannot tell "an
    # operator answering the bot's own prompt" apart from "an operator
    # replying to whichever player their own open session names" -- so
    # whatever this id typed next would be relayed to that child instead
    # of ever reaching registration. Refuse before any prompt is sent and
    # before Registration state is ever set -- this id keeps its ordinary
    # operator/support behaviour untouched otherwise.
    if message.from_user.id in alarm_recipients():
        note = (
            "CourtDuo support: this Telegram id is on ALARM_TELEGRAM_IDS, so it can't "
            "register as a player. To register it, remove it from ALARM_TELEGRAM_IDS, "
            "restart the service, and send /start again."
        )
        op_session = await crud.get_operator_session(session, message.from_user.id)
        if op_session is not None and datetime.now(timezone.utc) - op_session.last_activity_at <= OPERATOR_SESSION_TTL:
            watched_account = await crud.get_account_by_telegram_id(session, op_session.user_telegram_id)
            watched_name = (
                display_name(watched_account.full_name)
                if watched_account is not None
                else f"telegram id {op_session.user_telegram_id}"
            )
            note += (
                f" You still have a support conversation open with {watched_name} -- "
                "anything you type next goes to them, not to the bot."
            )
        await message.answer(note)
        return

    # CLAUDE.md step 8.4: the persistent reply keyboard is attached on this
    # very first message of a session, before there is even an account --
    # its "Zaproś na CourtDuo" label needs none, and the other two silently
    # no-op if tapped before registration finishes.
    await message.answer(t("start.greeting", DEFAULT_LANG), reply_markup=persistent_menu_keyboard(DEFAULT_LANG))
    await message.answer(t("registration.ask_pzt_id", DEFAULT_LANG))
    await state.set_state(Registration.waiting_pzt_id)


@router.message(Registration.waiting_pzt_id)
async def handle_pzt_id(message: Message, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    telegram_id = message.from_user.id
    lang = DEFAULT_LANG

    if _attempt_limiter.is_blocked(telegram_id):
        await message.answer(t("registration.too_many_attempts", lang))
        return

    result = await register_by_pzt_id(session, telegram_id, message.text or "")

    if result.outcome is not RegistrationOutcome.SUCCESS:
        _attempt_limiter.record_failure(telegram_id)
        await message.answer(t(_FAILURE_MESSAGE_KEYS[result.outcome], lang))
        # Stays in Registration.waiting_pzt_id so the player can retry.
        return

    account = result.account
    # CLAUDE.md step 8.7: for a brand new registration, this greeting --
    # not the very first "Cześć!" -- is the one that actually precedes the
    # age-category screen. The first greeting fires before the player has
    # typed anything and before their client may have finished applying
    # it; re-sending it here, right before the category screen needs the
    # slot for its own inline keyboard, closes that gap rather than
    # depending on the earlier attachment alone.
    await message.answer(
        t("registration.welcome", lang, first_name=first_name(account.full_name)),
        reply_markup=persistent_menu_keyboard(lang, can_use_viewers(account)),
    )

    # CLAUDE.md scenario 2, build order step 9 PART 2: tell every inviter
    # who is still owed a real invitation to this newly registered player.
    # Player.pzt_id is the account's own pzt_id (see bot.registration) --
    # the account and its player row always exist by this point.
    player = await crud.get_player_by_pzt_id(session, account.pzt_id)
    if player is not None:
        await notify_pending_external_invites(session, bot, player)

    await start_tournament_search(message, state, lang_for(account), session, account)
