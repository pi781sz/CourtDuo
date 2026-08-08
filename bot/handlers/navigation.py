"""The "Znajdź partnera" button's handler (CLAUDE.md, step 7.1, "a way
back"). Carries no state filter, like the three invitation-answer
handlers in bot.handlers.invitations: the tap can follow a pushed
notification, so the player may be in any state, or none at all, when
they tap it. Re-enters tournament search at the age-category screen —
exactly what a fresh `/start` does for an already-registered player.
"""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.handlers.tournament_search import start_tournament_search
from bot.keyboards.navigation import FindPartnerCallback
from bot.lang import lang_for
from db import crud

logger = logging.getLogger(__name__)

router = Router(name="navigation")


@router.callback_query(FindPartnerCallback.filter())
async def handle_find_partner(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    account = await crud.get_account_by_telegram_id(session, callback.from_user.id)
    lang = lang_for(account)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError as exc:
        logger.info("Could not clear Znajdź partnera button: %s", exc)
    await callback.answer()

    if account is None:
        # Every terminal message carrying this button was sent to a
        # registered account, so this can't happen in practice -- but a
        # missing account must not crash the tap.
        logger.warning("Znajdź partnera tapped with no account: telegram_id=%s", callback.from_user.id)
        return

    gender = crud.gender_for_account_code(account.gender)
    await start_tournament_search(callback.message, state, lang, session, gender)
