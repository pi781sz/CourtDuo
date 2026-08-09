""""Znajdź partnera": the inline button category_keyboard carries, and the
persistent-reply-keyboard label of the same name (CLAUDE.md step 8.4).
Both re-enter tournament search at the age-category screen -- exactly what
a fresh `/start` does for an already-registered player.

Neither carries a state filter: the tap can follow a pushed notification,
or arrive while the player is mid another flow entirely, so the player may
be in any state, or none at all, when it happens.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.handlers.tournament_search import start_tournament_search
from bot.i18n import all_translations
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

    await start_tournament_search(callback.message, state, lang, session, account)


@router.message(F.text.in_(all_translations("common.find_partner_button")))
async def handle_find_partner_button(message: Message, state: FSMContext, session: AsyncSession) -> None:
    account = await crud.get_account_by_telegram_id(session, message.from_user.id)
    lang = lang_for(account)

    if account is None:
        # A player can only see this label after /start has attached the
        # persistent keyboard, but registration may still be in progress
        # (no account yet) -- there's nothing to search with, so this must
        # not crash and must not be mistaken for a typed PZT id.
        logger.warning("Znajdź partnera tapped with no account: telegram_id=%s", message.from_user.id)
        return

    await start_tournament_search(message, state, lang, session, account)
