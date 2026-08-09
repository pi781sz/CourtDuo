"""Tests for bot.handlers.start.handle_start attaching the persistent
reply keyboard (CLAUDE.md step 8.4, CHANGE 1): once for a brand new
registration, once for a returning player, both on /start. Needs a real
Postgres for the Account row the returning-player branch looks up -- see
tests/conftest.py, skipped cleanly when TEST_DATABASE_URL is unset.
Invented telegram ids/names/pzt_ids only.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from bot.handlers.start import handle_start
from db.models import Account, Player

_TELEGRAM_ID = 600001


def _make_message() -> MagicMock:
    message = MagicMock()
    message.from_user.id = _TELEGRAM_ID
    message.answer = AsyncMock()
    return message


def _make_state() -> FSMContext:
    key = StorageKey(bot_id=1, chat_id=_TELEGRAM_ID, user_id=_TELEGRAM_ID)
    return FSMContext(storage=MemoryStorage(), key=key)


def _reply_keyboard_calls(message: MagicMock) -> list[ReplyKeyboardMarkup]:
    return [
        call.kwargs["reply_markup"]
        for call in message.answer.call_args_list
        if isinstance(call.kwargs.get("reply_markup"), ReplyKeyboardMarkup)
    ]


async def test_new_registration_attaches_the_persistent_keyboard_on_the_greeting(db_session: AsyncSession):
    message = _make_message()
    state = _make_state()

    await handle_start(message, state, db_session)

    markups = _reply_keyboard_calls(message)
    assert len(markups) == 1
    rows = [[button.text for button in row] for row in markups[0].keyboard]
    assert rows == [["Znajdź partnera"], ["Moje deble", "Zaproś na CourtDuo"]]
    assert markups[0].is_persistent is True
    assert markups[0].resize_keyboard is True


async def test_returning_player_also_gets_the_persistent_keyboard_on_start(db_session: AsyncSession):
    db_session.add(Player(pzt_id="STR0001", full_name="Testowy Gracz", club=None, age_category=None, gender=None))
    await db_session.flush()
    db_session.add(
        Account(telegram_id=_TELEGRAM_ID, pzt_id="STR0001", full_name="Testowy Gracz", gender="M", lang="pl")
    )
    await db_session.flush()

    message = _make_message()
    state = _make_state()

    await handle_start(message, state, db_session)

    markups = _reply_keyboard_calls(message)
    assert len(markups) == 1
    rows = [[button.text for button in row] for row in markups[0].keyboard]
    assert rows == [["Znajdź partnera"], ["Moje deble", "Zaproś na CourtDuo"]]
