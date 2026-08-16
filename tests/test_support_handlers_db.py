"""Tests for /pomoc, the two-way support relay between a player and the
operators in bot.staleness.alarm_recipients() (CLAUDE.md, "Operations" >
"Support"). Player <-> operator only, never player <-> player -- these
tests are written as the invariants the task asked for, not as a list of
cases, so a future change that breaks the promise fails loudly regardless
of how it was broken:

  1. A support message is never delivered to any Telegram id outside
     alarm_recipients().
  2. An operator reply is delivered only to the user_telegram_id recorded
     for that exact (operator_chat_id, operator_message_id).
  3. No non-text content is relayed in either direction.
  4. No message body is ever written to the database.
  5. A reply-to-message from a Telegram id not in alarm_recipients()
     produces no outbound message at all -- covered end-to-end in
     tests/test_persistent_menu_routing.py, which exercises the real
     router/filter wiring rather than calling handlers directly.

Needs a real Postgres -- see tests/conftest.py, skipped cleanly when
TEST_DATABASE_URL is unset. Invented telegram ids/names/pzt_ids only --
never a real PZT id (CLAUDE.md rule 4).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.enums import ContentType
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.handlers.support import (
    handle_operator_reply,
    handle_pomoc,
    handle_pomoc_message,
    handle_pomoc_non_text,
)
from bot.i18n import t
from bot.states import Support
from db import crud
from db.models import Account, Player, SupportThread

_LANG = "pl"


def _make_state(telegram_id: int) -> FSMContext:
    key = StorageKey(bot_id=1, chat_id=telegram_id, user_id=telegram_id)
    return FSMContext(storage=MemoryStorage(), key=key)


def _make_message(telegram_id: int, text: str | None, content_type=ContentType.TEXT) -> MagicMock:
    message = MagicMock()
    message.from_user = MagicMock(id=telegram_id, full_name="Testowy Gracz")
    message.text = text
    message.content_type = content_type
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


async def test_pomoc_prompts_and_sets_state_without_an_account(db_session: AsyncSession):
    # CLAUDE.md, "Support": "the single most likely support message is 'I
    # could not register', from someone who by definition has no account."
    message = _make_message(950001, text=None)
    state = _make_state(950001)

    await handle_pomoc(message, state, db_session)

    message.answer.assert_awaited_once_with(t("support.prompt", _LANG))
    assert await state.get_state() == Support.waiting_message.state


async def test_relay_reaches_every_alarm_recipient_and_no_one_else(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("ALARM_TELEGRAM_IDS", "111111,222222")
    telegram_id = 950002
    await _add_account(db_session, "SUP0002", telegram_id, "Kowalski Jan")

    message = _make_message(telegram_id, text="Nie moge sie zarejestrowac")
    state = _make_state(telegram_id)
    await state.set_state(Support.waiting_message)
    bot = _make_bot()

    await handle_pomoc_message(message, state, db_session, bot)

    recipients = {call.args[0] for call in bot.send_message.await_args_list}
    assert recipients == {111111, 222222}
    message.answer.assert_awaited_once_with(t("support.confirmation", _LANG))
    assert await state.get_state() is None


async def test_relay_is_silent_when_no_operators_are_configured(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("ALARM_TELEGRAM_IDS", raising=False)
    telegram_id = 950003
    message = _make_message(telegram_id, text="Halo?")
    state = _make_state(telegram_id)
    await state.set_state(Support.waiting_message)
    bot = _make_bot()

    await handle_pomoc_message(message, state, db_session, bot)

    bot.send_message.assert_not_awaited()


async def test_relay_names_a_registered_sender_and_marks_an_unregistered_one(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("ALARM_TELEGRAM_IDS", "333333")

    registered_id = 950004
    await _add_account(db_session, "SUP0004", registered_id, "Szewczyk Jagoda")
    message = _make_message(registered_id, text="Pytanie")
    state = _make_state(registered_id)
    await state.set_state(Support.waiting_message)
    bot = _make_bot()
    await handle_pomoc_message(message, state, db_session, bot)
    operator_text = bot.send_message.await_args_list[0].args[1]
    assert "Jagoda Szewczyk" in operator_text
    assert "SUP0004" in operator_text
    assert str(registered_id) in operator_text

    unregistered_id = 950005
    message2 = _make_message(unregistered_id, text="Pytanie 2")
    state2 = _make_state(unregistered_id)
    await state2.set_state(Support.waiting_message)
    bot2 = _make_bot()
    await handle_pomoc_message(message2, state2, db_session, bot2)
    operator_text2 = bot2.send_message.await_args_list[0].args[1]
    assert "not registered" in operator_text2


async def test_no_message_body_is_ever_written_to_the_database(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("ALARM_TELEGRAM_IDS", "444444")
    telegram_id = 950006
    secret = "a very specific support message body xyz123"
    message = _make_message(telegram_id, text=secret)
    state = _make_state(telegram_id)
    await state.set_state(Support.waiting_message)
    bot = _make_bot()

    await handle_pomoc_message(message, state, db_session, bot)

    # Structural guarantee: the table has no column that could hold a body.
    columns = {c.name for c in inspect(SupportThread).columns}
    assert columns == {"id", "operator_chat_id", "operator_message_id", "user_telegram_id", "created_at"}

    # Defensive: whatever is actually stored never contains the message text.
    rows = (await db_session.execute(select(SupportThread))).scalars().all()
    assert rows
    for row in rows:
        values = [row.operator_chat_id, row.operator_message_id, row.user_telegram_id, str(row.created_at)]
        assert all(secret not in str(v) for v in values)


async def test_non_text_content_is_refused_and_state_stays_set(db_session: AsyncSession):
    telegram_id = 950007
    message = _make_message(telegram_id, text=None, content_type=ContentType.PHOTO)
    state = _make_state(telegram_id)
    await state.set_state(Support.waiting_message)

    # handle_pomoc_non_text takes no Bot at all -- structurally incapable
    # of relaying anything, which is what invariant 3 requires for this
    # direction.
    await handle_pomoc_non_text(message, db_session)

    message.answer.assert_awaited_once_with(t("support.non_text_refusal", _LANG))
    assert await state.get_state() == Support.waiting_message.state


async def test_rate_cap_blocks_the_sixth_message_in_an_hour(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("ALARM_TELEGRAM_IDS", "555555")
    telegram_id = 950008
    bot = _make_bot()

    for _ in range(5):
        state = _make_state(telegram_id)
        await state.set_state(Support.waiting_message)
        message = _make_message(telegram_id, text="wiadomosc")
        await handle_pomoc_message(message, state, db_session, bot)

    assert bot.send_message.await_count == 5

    state = _make_state(telegram_id)
    await state.set_state(Support.waiting_message)
    blocked_message = _make_message(telegram_id, text="szosta wiadomosc")
    await handle_pomoc_message(blocked_message, state, db_session, bot)

    # Nothing new was sent to any operator for the over-cap attempt.
    assert bot.send_message.await_count == 5
    blocked_message.answer.assert_awaited_once_with(t("support.rate_limited", _LANG))


async def test_operator_reply_is_delivered_only_to_its_own_mapped_user(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    operator_id = 666666
    monkeypatch.setenv("ALARM_TELEGRAM_IDS", str(operator_id))
    user_a, user_b = 950010, 950011
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
    operator_id = 777777
    monkeypatch.setenv("ALARM_TELEGRAM_IDS", str(operator_id))
    bot = _make_bot()
    reply = _make_reply_message(operator_id, reply_to_message_id=99999, text="?")

    await handle_operator_reply(reply, db_session, bot)

    bot.send_message.assert_not_awaited()
    reply.answer.assert_awaited_once()
