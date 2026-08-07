"""/start and PZT-id registration (CLAUDE.md, "Identity" + user journeys
1-3; build order step 4). Every conversation enters here: a new Telegram
account is asked for its PZT id and bound to exactly one player; a
returning account skips straight to tournament search.
"""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.attempt_limiter import FailedAttemptLimiter
from bot.i18n import t
from bot.lang import DEFAULT_LANG, lang_for
from bot.registration import RegistrationOutcome, register_by_pzt_id
from bot.states import Registration
from bot.tournament_search import start_tournament_search
from db import crud

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
}


@router.message(CommandStart())
async def handle_start(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()

    account = await crud.get_account_by_telegram_id(session, message.from_user.id)
    if account is not None:
        # CLAUDE.md scenario 3: returning player skips registration
        # entirely, straight to tournament search.
        await start_tournament_search(message, state, lang_for(account))
        return

    await message.answer(t("start.greeting", DEFAULT_LANG))
    await message.answer(t("registration.ask_pzt_id", DEFAULT_LANG))
    await state.set_state(Registration.waiting_pzt_id)


@router.message(Registration.waiting_pzt_id)
async def handle_pzt_id(message: Message, state: FSMContext, session: AsyncSession) -> None:
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
    await message.answer(t("registration.welcome", lang, full_name=account.full_name))
    await start_tournament_search(message, state, lang_for(account))
