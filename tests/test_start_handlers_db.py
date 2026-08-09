"""Tests for bot.handlers.start attaching the persistent reply keyboard
(CLAUDE.md step 8.4, CHANGE 1, extended by step 8.7): on /start for a
brand new registration, on /start for a returning player, and -- step
8.7's fix -- on the "Witaj {imię}." greeting that completes a brand new
registration too, since that message (not the earlier "Cześć!") is the
one that actually precedes the age-category screen for a new player.
Needs a real Postgres -- see tests/conftest.py, skipped cleanly when
TEST_DATABASE_URL is unset. Invented telegram ids/names/pzt_ids only.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from bot.handlers.start import handle_pzt_id, handle_start
from bot.states import Registration
from db.models import Account, Player, Ranking, RankingList

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


async def test_completing_registration_also_attaches_the_persistent_keyboard(db_session: AsyncSession):
    # CLAUDE.md step 8.7: the earlier "Cześć!" greeting fires before the
    # player has typed anything -- this "Witaj {imię}." message, right
    # before the age-category screen, is the one CLAUDE.md's own rule for
    # returning players ("the greeting that precedes the age-category
    # screen") describes, so it needs its own attachment too.
    db_session.add(Player(pzt_id="NEW0001", full_name="Nowak Testowy", club=None, age_category=None, gender=None))
    await db_session.flush()
    db_session.add(Ranking(player_pzt_id="NEW0001", ranking_list=RankingList.M14, position=1, year=2026, month=8))
    await db_session.flush()

    message = _make_message()
    message.text = "NEW0001"
    state = _make_state()
    await state.set_state(Registration.waiting_pzt_id)

    await handle_pzt_id(message, state, db_session)

    markups = _reply_keyboard_calls(message)
    assert len(markups) == 1
    rows = [[button.text for button in row] for row in markups[0].keyboard]
    assert rows == [["Znajdź partnera"], ["Moje deble", "Zaproś na CourtDuo"]]
    assert markups[0].is_persistent is True
    assert markups[0].resize_keyboard is True
