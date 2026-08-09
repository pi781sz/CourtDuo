"""Tests for the "Znajdź partnera" handlers -- the inline button
(CLAUDE.md, step 7.1, "a way back") and, since build order step 8.4, the
persistent reply keyboard's label of the same name. Needs a real Postgres
for the Account row the handlers look up -- see tests/conftest.py, skipped
cleanly when TEST_DATABASE_URL is unset. Invented telegram ids/names only.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy.ext.asyncio import AsyncSession

from bot.handlers.navigation import handle_find_partner, handle_find_partner_button
from bot.states import InvitationSend, TournamentSearch
from db.models import Account, Player

_TELEGRAM_ID = 999101


def _make_callback() -> MagicMock:
    callback = MagicMock()
    callback.from_user.id = _TELEGRAM_ID
    callback.message.edit_reply_markup = AsyncMock()
    callback.message.answer = AsyncMock()
    callback.answer = AsyncMock()
    return callback


def _make_message() -> MagicMock:
    message = MagicMock()
    message.from_user.id = _TELEGRAM_ID
    message.answer = AsyncMock()
    return message


def _make_state() -> FSMContext:
    key = StorageKey(bot_id=1, chat_id=_TELEGRAM_ID, user_id=_TELEGRAM_ID)
    return FSMContext(storage=MemoryStorage(), key=key)


async def _make_account(db_session: AsyncSession) -> None:
    db_session.add(Player(pzt_id="NAV00001", full_name="Testowy Gracz", club=None, age_category=None, gender=None))
    await db_session.flush()
    db_session.add(
        Account(telegram_id=_TELEGRAM_ID, pzt_id="NAV00001", full_name="Testowy Gracz", gender="M", lang="pl")
    )
    await db_session.flush()


async def test_find_partner_reenters_category_selection_from_any_state(db_session: AsyncSession):
    # The button can follow a pushed notification, so the player may be
    # mid another flow entirely (CLAUDE.md, step 7.1).
    await _make_account(db_session)
    state = _make_state()
    await state.update_data(tournament_guid="whatever", partner_pzt_id="OTHER001")
    await state.set_state(InvitationSend.waiting_confirmation)
    callback = _make_callback()

    await handle_find_partner(callback, state, db_session)

    callback.message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)
    callback.answer.assert_awaited_once()
    assert await state.get_state() == TournamentSearch.waiting_category.state
    assert callback.message.answer.await_count == 1
    assert callback.message.answer.call_args.kwargs["reply_markup"] is not None


async def test_find_partner_with_no_state_at_all(db_session: AsyncSession):
    await _make_account(db_session)
    state = _make_state()
    callback = _make_callback()

    await handle_find_partner(callback, state, db_session)

    assert await state.get_state() == TournamentSearch.waiting_category.state


async def test_find_partner_with_no_account_does_not_crash(db_session: AsyncSession):
    # Can't happen in practice -- the button is only ever sent to a
    # registered account -- but a missing account must not raise.
    state = _make_state()
    callback = _make_callback()

    await handle_find_partner(callback, state, db_session)

    callback.message.answer.assert_not_awaited()


# --- persistent-keyboard "Znajdź partnera" label (CLAUDE.md step 8.4) ---------


async def test_find_partner_button_reenters_category_selection_from_any_state(db_session: AsyncSession):
    await _make_account(db_session)
    state = _make_state()
    await state.update_data(tournament_guid="whatever", partner_pzt_id="OTHER001")
    await state.set_state(InvitationSend.waiting_confirmation)
    message = _make_message()

    await handle_find_partner_button(message, state, db_session)

    assert await state.get_state() == TournamentSearch.waiting_category.state
    message.answer.assert_awaited_once()


async def test_find_partner_button_with_no_account_does_not_crash(db_session: AsyncSession):
    # Can arrive mid-registration, before an account exists -- must not
    # raise and must not be mistaken for a typed PZT id.
    state = _make_state()
    message = _make_message()

    await handle_find_partner_button(message, state, db_session)

    message.answer.assert_not_awaited()
