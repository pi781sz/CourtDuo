"""Tests for what's left in bot.handlers.support after the open-conversation
rework (CLAUDE.md, "Operations" > "Support"): opening a conversation on
/pomoc, the reply-to fallback (unchanged), and the two operator buttons
("Reply: {name}" / "Close conversation"). The actual message relaying and
lazy expiry now live in bot.middlewares.support_conversation -- see
tests/test_support_conversation_middleware_db.py for those.

Needs a real Postgres -- see tests/conftest.py, skipped cleanly when
TEST_DATABASE_URL is unset. Invented telegram ids/names/pzt_ids only --
never a real PZT id (CLAUDE.md rule 4).
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from bot.handlers.support import (
    handle_operator_reply,
    handle_pomoc,
    handle_support_close_tap,
    handle_support_reply_tap,
)
from bot.i18n import t
from bot.keyboards.support import SupportReplyCallback
from db import crud
from db.models import Account, Player

_LANG = "pl"


def _make_message(telegram_id: int, text: str | None = None) -> MagicMock:
    message = MagicMock()
    message.from_user = MagicMock(id=telegram_id, full_name="Testowy Gracz")
    message.text = text
    message.answer = AsyncMock()
    return message


def _make_reply_message(chat_id: int, reply_to_message_id: int, text: str | None) -> MagicMock:
    message = MagicMock()
    message.chat = MagicMock(id=chat_id)
    message.from_user = MagicMock(id=chat_id)
    message.text = text
    message.reply_to_message = MagicMock(message_id=reply_to_message_id)
    message.answer = AsyncMock()
    return message


def _make_callback(telegram_id: int) -> MagicMock:
    callback = MagicMock()
    callback.from_user = MagicMock(id=telegram_id)
    callback.answer = AsyncMock()
    callback.message = MagicMock()
    callback.message.answer = AsyncMock()
    return callback


_message_id_counter = iter(range(1, 1_000_000))


def _make_bot() -> MagicMock:
    bot = MagicMock()

    async def _send(chat_id, text, reply_markup=None):
        return MagicMock(message_id=next(_message_id_counter))

    bot.send_message = AsyncMock(side_effect=_send)
    return bot


async def _add_account(session: AsyncSession, pzt_id: str, telegram_id: int, full_name: str) -> Account:
    session.add(Player(pzt_id=pzt_id, full_name=full_name, club=None, age_category=None, gender=None))
    await session.flush()
    account = Account(telegram_id=telegram_id, pzt_id=pzt_id, full_name=full_name, gender="M")
    session.add(account)
    await session.flush()
    return account


async def test_pomoc_opens_a_conversation_without_an_account(db_session: AsyncSession):
    # CLAUDE.md, "Support": "the single most likely support message is 'I
    # could not register', from someone who by definition has no account."
    message = _make_message(960001)

    await handle_pomoc(message, db_session)

    message.answer.assert_awaited_once_with(t("support.conversation_opened", _LANG))
    conversation = await crud.get_support_conversation(db_session, 960001)
    assert conversation is not None
    assert conversation.is_open is True


async def test_pomoc_reopens_an_already_closed_conversation(db_session: AsyncSession):
    telegram_id = 960002
    await crud.open_support_conversation(db_session, telegram_id, datetime.now(timezone.utc))
    await crud.close_support_conversation(db_session, telegram_id)

    await handle_pomoc(_make_message(telegram_id), db_session)

    conversation = await crud.get_support_conversation(db_session, telegram_id)
    assert conversation.is_open is True


async def test_operator_reply_is_delivered_only_to_its_own_mapped_user(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    operator_id = 966666
    monkeypatch.setenv("ALARM_TELEGRAM_IDS", str(operator_id))
    user_a, user_b = 960010, 960011
    await crud.create_support_thread(db_session, operator_id, 1001, user_a)
    await crud.create_support_thread(db_session, operator_id, 1002, user_b)
    await db_session.commit()

    bot = _make_bot()
    reply = _make_reply_message(operator_id, reply_to_message_id=1001, text="Sprobuj ponownie za godzine")

    await handle_operator_reply(reply, db_session, bot)

    bot.send_message.assert_awaited_once()
    delivered_to = bot.send_message.await_args_list[0].args[0]
    assert delivered_to == user_a
    assert delivered_to != user_b
    delivered_text = bot.send_message.await_args_list[0].args[1]
    assert delivered_text.startswith(t("support.reply_header", _LANG))


async def test_operator_reply_with_no_mapping_tells_the_operator_and_relays_nothing(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    operator_id = 977777
    monkeypatch.setenv("ALARM_TELEGRAM_IDS", str(operator_id))
    bot = _make_bot()
    reply = _make_reply_message(operator_id, reply_to_message_id=99999, text="?")

    await handle_operator_reply(reply, db_session, bot)

    bot.send_message.assert_not_awaited()
    reply.answer.assert_awaited_once()


async def test_reply_button_tap_opens_an_operator_session_named_for_the_player(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    operator_id = 968001
    monkeypatch.setenv("ALARM_TELEGRAM_IDS", str(operator_id))
    player_id = 960020
    await _add_account(db_session, "SUP8001", player_id, "Szewczyk Jagoda")
    await db_session.commit()

    callback = _make_callback(operator_id)
    callback_data = SupportReplyCallback(user_telegram_id=player_id)

    await handle_support_reply_tap(callback, callback_data, db_session)

    session_row = await crud.get_operator_session(db_session, operator_id)
    assert session_row is not None
    assert session_row.user_telegram_id == player_id
    callback.message.answer.assert_awaited_once()
    confirmation_text = callback.message.answer.await_args_list[0].args[0]
    assert "Jagoda Szewczyk" in confirmation_text
    assert "SUP8001" in confirmation_text


async def test_reply_button_tap_from_a_non_operator_opens_nothing(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ALARM_TELEGRAM_IDS", "968002")
    not_an_operator = 968003
    callback = _make_callback(not_an_operator)
    callback_data = SupportReplyCallback(user_telegram_id=960021)

    await handle_support_reply_tap(callback, callback_data, db_session)

    assert await crud.get_operator_session(db_session, not_an_operator) is None
    callback.message.answer.assert_not_awaited()
    callback.answer.assert_awaited_once()


async def test_close_conversation_ends_the_operator_session_and_tells_both_sides(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    operator_id = 968010
    monkeypatch.setenv("ALARM_TELEGRAM_IDS", str(operator_id))
    player_id = 960030
    now = datetime.now(timezone.utc)
    await crud.open_operator_session(db_session, operator_id, player_id, now)
    await crud.open_support_conversation(db_session, player_id, now)
    await db_session.commit()

    callback = _make_callback(operator_id)
    bot = _make_bot()

    await handle_support_close_tap(callback, db_session, bot)

    assert await crud.get_operator_session(db_session, operator_id) is None
    player_conversation = await crud.get_support_conversation(db_session, player_id)
    assert player_conversation.is_open is False

    callback.message.answer.assert_awaited_once_with("Conversation closed.")
    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args_list[0].args[0] == player_id
    assert bot.send_message.await_args_list[0].args[1] == t("support.conversation_closed_by_operator", _LANG)


async def test_close_conversation_from_a_non_operator_does_nothing(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ALARM_TELEGRAM_IDS", "968020")
    not_an_operator = 968021
    callback = _make_callback(not_an_operator)
    bot = _make_bot()

    await handle_support_close_tap(callback, db_session, bot)

    bot.send_message.assert_not_awaited()
    callback.message.answer.assert_not_awaited()
    callback.answer.assert_awaited_once()


async def test_close_conversation_with_nothing_open_tells_the_operator_plainly(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    operator_id = 968030
    monkeypatch.setenv("ALARM_TELEGRAM_IDS", str(operator_id))
    callback = _make_callback(operator_id)
    bot = _make_bot()

    await handle_support_close_tap(callback, db_session, bot)

    bot.send_message.assert_not_awaited()
    callback.message.answer.assert_awaited_once_with("CourtDuo support: no conversation was open.")
