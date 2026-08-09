"""Tests for bot.handlers.start attaching the persistent reply keyboard
(CLAUDE.md step 8.4, CHANGE 1, extended by step 8.7): on /start for a
brand new registration, on /start for a returning player, and -- step
8.7's fix -- on the "Witaj {imię}." greeting that completes a brand new
registration too, since that message (not the earlier "Cześć!") is the
one that actually precedes the age-category screen for a new player.

Also covers CLAUDE.md step 10's deep-link viewer binding: /start's
payload is intercepted before any of the above runs, and a used, expired
or unknown token must fall through to plain /start byte-for-byte -- "never
errors".

Needs a real Postgres -- see tests/conftest.py, skipped cleanly when
TEST_DATABASE_URL is unset. Invented telegram ids/names/pzt_ids only.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from aiogram.filters import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from bot.handlers.start import handle_pzt_id, handle_start
from bot.states import Registration
from bot.viewers import bind_viewer, create_invite_token
from db import crud
from db.models import Account, Player, Ranking, RankingList

_TELEGRAM_ID = 600001
_NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)


def _make_message() -> MagicMock:
    message = MagicMock()
    message.from_user.id = _TELEGRAM_ID
    message.answer = AsyncMock()
    return message


def _make_state() -> FSMContext:
    key = StorageKey(bot_id=1, chat_id=_TELEGRAM_ID, user_id=_TELEGRAM_ID)
    return FSMContext(storage=MemoryStorage(), key=key)


def _make_bot() -> MagicMock:
    bot = MagicMock()
    bot.get_me = AsyncMock(return_value=MagicMock(username="courtduo_test_bot"))
    return bot


def _reply_keyboard_calls(message: MagicMock) -> list[ReplyKeyboardMarkup]:
    return [
        call.kwargs["reply_markup"]
        for call in message.answer.call_args_list
        if isinstance(call.kwargs.get("reply_markup"), ReplyKeyboardMarkup)
    ]


async def test_new_registration_attaches_the_persistent_keyboard_on_the_greeting(db_session: AsyncSession):
    message = _make_message()
    state = _make_state()

    await handle_start(message, state, db_session, _make_bot(), CommandObject())

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

    await handle_start(message, state, db_session, _make_bot(), CommandObject())

    markups = _reply_keyboard_calls(message)
    assert len(markups) == 1
    rows = [[button.text for button in row] for row in markups[0].keyboard]
    assert rows == [["Znajdź partnera"], ["Moje deble", "Zaproś na CourtDuo"]]


async def _add_watched_account(session: AsyncSession, pzt_id: str, telegram_id: int, full_name: str = "Nowak Adam") -> Account:
    session.add(Player(pzt_id=pzt_id, full_name=full_name, club=None, age_category=None, gender=None))
    await session.flush()
    account = Account(telegram_id=telegram_id, pzt_id=pzt_id, full_name=full_name, gender="M")
    session.add(account)
    await session.flush()
    return account


def _make_bot_with_send() -> MagicMock:
    bot = _make_bot()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    return bot


# --- CLAUDE.md step 10: deep-link viewer binding --------------------------------


async def test_start_with_a_valid_token_binds_the_viewer_and_notifies_the_player(db_session: AsyncSession):
    watched = await _add_watched_account(db_session, "STR0010", 600010)
    token = await create_invite_token(db_session, watched)

    message = _make_message()
    message.from_user.full_name = "Rodzic Testowy"
    bot = _make_bot_with_send()

    await handle_start(message, _make_state(), db_session, bot, CommandObject(args=token.token))

    message.answer.assert_awaited_once()
    assert "Adam Nowak" in message.answer.call_args.args[0]
    # CLAUDE.md step 10.1, PROBLEM 1: the binder has no CourtDuo account of
    # their own, so this may be their first message ever -- they must get
    # the viewer-only keyboard, never the full player one.
    bind_markup = message.answer.call_args.kwargs["reply_markup"]
    assert isinstance(bind_markup, ReplyKeyboardMarkup)
    assert [[button.text for button in row] for row in bind_markup.keyboard] == [["Moje deble"]]
    # CLAUDE.md step 10.1, PROBLEM 4: the grant notification's new wording.
    bot.send_message.assert_awaited_once()
    push_call = bot.send_message.await_args
    assert push_call.args[0] == 600010
    assert push_call.args[1] == "Rodzic Testowy ma teraz dostęp do podglądu Twojego konta CourtDuo."
    assert await crud.count_active_viewers(db_session, watched.id) == 1
    # Never the ordinary registration greeting for a bind -- it's a
    # separate flow, not a player /start.
    assert "PZT" not in message.answer.call_args.args[0]


async def test_a_registered_player_binding_as_a_viewer_keeps_their_own_full_keyboard(db_session: AsyncSession):
    # CLAUDE.md step 10.1, "acts as themselves... full keyboard,
    # unchanged": a Telegram account that is already a registered player
    # must not have its keyboard swapped just because it also taps
    # someone else's viewer invite link.
    db_session.add(Player(pzt_id="STR0013", full_name="Testowy Gracz", club=None, age_category=None, gender=None))
    await db_session.flush()
    db_session.add(Account(telegram_id=_TELEGRAM_ID, pzt_id="STR0013", full_name="Testowy Gracz", gender="M"))
    await db_session.flush()
    watched = await _add_watched_account(db_session, "STR0014", 600014)
    token = await create_invite_token(db_session, watched)

    message = _make_message()
    bot = _make_bot_with_send()

    await handle_start(message, _make_state(), db_session, bot, CommandObject(args=token.token))

    message.answer.assert_awaited_once()
    assert message.answer.call_args.kwargs.get("reply_markup") is None


async def test_start_with_an_already_used_token_behaves_like_plain_start(db_session: AsyncSession):
    watched = await _add_watched_account(db_session, "STR0011", 600011)
    token = await create_invite_token(db_session, watched)
    await bind_viewer(db_session, 600099, token.token, _NOW)

    used_message = _make_message()
    used_bot = _make_bot_with_send()
    await handle_start(used_message, _make_state(), db_session, used_bot, CommandObject(args=token.token))

    plain_message = _make_message()
    plain_bot = _make_bot_with_send()
    await handle_start(plain_message, _make_state(), db_session, plain_bot, CommandObject())

    assert [c.args[0] for c in used_message.answer.call_args_list] == [
        c.args[0] for c in plain_message.answer.call_args_list
    ]
    used_bot.send_message.assert_not_awaited()
    # No second viewer grant was created for this already-consumed token.
    assert await crud.count_active_viewers(db_session, watched.id) == 1


async def test_start_with_an_expired_token_behaves_like_plain_start(db_session: AsyncSession):
    watched = await _add_watched_account(db_session, "STR0012", 600012)
    # handle_start always calls bind_viewer with the real current time, so
    # the expiry here is relative to it rather than the fixed _NOW used
    # elsewhere in this file, to stay valid no matter when this test runs.
    row = await crud.create_viewer_invite_token(
        db_session, watched.id, "expired-token-xyz", datetime.now(timezone.utc) - timedelta(hours=1)
    )

    expired_message = _make_message()
    expired_bot = _make_bot_with_send()
    await handle_start(expired_message, _make_state(), db_session, expired_bot, CommandObject(args=row.token))

    plain_message = _make_message()
    plain_bot = _make_bot_with_send()
    await handle_start(plain_message, _make_state(), db_session, plain_bot, CommandObject())

    assert [c.args[0] for c in expired_message.answer.call_args_list] == [
        c.args[0] for c in plain_message.answer.call_args_list
    ]
    expired_bot.send_message.assert_not_awaited()
    assert await crud.count_active_viewers(db_session, watched.id) == 0


async def test_start_with_an_unknown_token_behaves_like_plain_start(db_session: AsyncSession):
    unknown_message = _make_message()
    unknown_bot = _make_bot_with_send()
    await handle_start(unknown_message, _make_state(), db_session, unknown_bot, CommandObject(args="totally-unknown-token"))

    plain_message = _make_message()
    plain_bot = _make_bot_with_send()
    await handle_start(plain_message, _make_state(), db_session, plain_bot, CommandObject())

    assert [c.args[0] for c in unknown_message.answer.call_args_list] == [
        c.args[0] for c in plain_message.answer.call_args_list
    ]
    unknown_bot.send_message.assert_not_awaited()


# --- CLAUDE.md step 10.1, PROBLEM 1: a pure viewer's own /start ----------------


async def test_a_pure_viewer_plain_start_gets_the_viewer_keyboard_not_registration(db_session: AsyncSession):
    watched = await _add_watched_account(db_session, "STR0015", 600015, full_name="Kowalski Jan")
    await crud.add_viewer(db_session, watched.id, _TELEGRAM_ID)

    message = _make_message()
    await handle_start(message, _make_state(), db_session, _make_bot_with_send(), CommandObject())

    texts = [c.args[0] for c in message.answer.call_args_list]
    # Never dropped into PZT-id registration -- this Telegram account has
    # no player of its own, only a viewer grant.
    assert not any("PZT" in text for text in texts)
    assert any("Jan Kowalski" in text for text in texts)

    # Both the greeting and the read-only view itself carry the
    # viewer-only keyboard -- never persistent_menu_keyboard.
    markups = _reply_keyboard_calls(message)
    assert markups
    for markup in markups:
        assert [[button.text for button in row] for row in markup.keyboard] == [["Moje deble"]]


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

    await handle_pzt_id(message, state, db_session, _make_bot())

    markups = _reply_keyboard_calls(message)
    assert len(markups) == 1
    rows = [[button.text for button in row] for row in markups[0].keyboard]
    assert rows == [["Znajdź partnera"], ["Moje deble", "Zaproś na CourtDuo"]]
    assert markups[0].is_persistent is True
    assert markups[0].resize_keyboard is True
