"""Tests for the FSM-state side effects of the "Zmień miejscowość" /
"Zmień kategorię wiekową" navigation buttons (CLAUDE.md, "Tournament
selection"; step 5.1): the former must keep the chosen category, the
latter must clear it and return to the category screen. Needs a real
Postgres for the Account/Player rows the handlers look up -- see
tests/conftest.py, skipped cleanly when TEST_DATABASE_URL is unset.
Invented telegram ids/names only.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy.ext.asyncio import AsyncSession

from bot.handlers.tournament_search import handle_change_category, handle_change_place
from bot.states import TournamentSearch
from db.models import Account, AgeCategory, Player

_TELEGRAM_ID = 999001


def _make_callback() -> MagicMock:
    callback = MagicMock()
    callback.from_user.id = _TELEGRAM_ID
    callback.message.edit_reply_markup = AsyncMock()
    callback.message.answer = AsyncMock()
    callback.answer = AsyncMock()
    return callback


async def _make_state() -> FSMContext:
    key = StorageKey(bot_id=1, chat_id=_TELEGRAM_ID, user_id=_TELEGRAM_ID)
    state = FSMContext(storage=MemoryStorage(), key=key)
    await state.update_data(category=AgeCategory.MLODZICY.name, place="Uniejów")
    await state.set_state(TournamentSearch.waiting_place)
    return state


async def _make_account(db_session: AsyncSession) -> None:
    db_session.add(Player(pzt_id="TST00001", full_name="Test Player", club=None, age_category=None, gender=None))
    await db_session.flush()
    db_session.add(
        Account(telegram_id=_TELEGRAM_ID, pzt_id="TST00001", full_name="Test Player", gender="M", lang="pl")
    )
    await db_session.flush()


async def test_change_place_preserves_category(db_session: AsyncSession):
    await _make_account(db_session)
    state = await _make_state()
    callback = _make_callback()

    await handle_change_place(callback, state, db_session)

    data = await state.get_data()
    assert data["category"] == AgeCategory.MLODZICY.name
    assert data.get("place") is None
    assert await state.get_state() == TournamentSearch.waiting_place.state


async def test_change_category_clears_category(db_session: AsyncSession):
    await _make_account(db_session)
    state = await _make_state()
    callback = _make_callback()

    await handle_change_category(callback, state, db_session)

    data = await state.get_data()
    assert data.get("category") is None
    assert data.get("place") is None
    assert await state.get_state() == TournamentSearch.waiting_category.state
