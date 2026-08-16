"""Tests for bot.middlewares.support_conversation.SupportConversationMiddleware
-- the open conversation on both sides of /pomoc (CLAUDE.md, "Operations" >
"Support"). Written as the invariants the task asked for, not a list of
cases, so a future change that breaks the promise fails loudly regardless
of how it was broken:

  1. A player's message is never delivered to a Telegram id outside
     alarm_recipients().
  2. An operator's message is delivered only to the player named by their
     own open session -- never any other player.
  3. An incoming message from a second player never changes which
     conversation an operator has open.
  4. An expired conversation or session never delivers a message, on
     either side.
  5. No non-text content is relayed in either direction.
  6. No message body is ever written to the database.
  7. A command or a persistent-reply-keyboard label always falls through
     untouched (closing a player's own open conversation silently on the
     way), regardless of what is open -- this is what keeps /status and
     every other router's own priority unchanged.

Needs a real Postgres -- see tests/conftest.py, skipped cleanly when
TEST_DATABASE_URL is unset. Invented telegram ids/names/pzt_ids only --
never a real PZT id (CLAUDE.md rule 4).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.enums import ContentType
from aiogram.types import Message
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.middlewares.support_conversation import (
    OPERATOR_SESSION_TTL,
    PLAYER_CONVERSATION_TTL,
    SupportConversationMiddleware,
)
from bot.i18n import t
from db import crud
from db.models import Account, Player, SupportConversation, SupportOperatorSession, SupportThread

_LANG = "pl"
_NOW = datetime.now(timezone.utc)


def _make_message(telegram_id: int, text: str | None, content_type=ContentType.TEXT, reply_to=None) -> MagicMock:
    message = MagicMock(spec=Message)
    message.from_user = MagicMock(id=telegram_id, full_name="Testowy Gracz")
    message.text = text
    message.content_type = content_type
    message.reply_to_message = reply_to
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


async def _run(middleware: SupportConversationMiddleware, message, bot) -> AsyncMock:
    """Runs one message through the middleware; returns the `next handler`
    mock so a test can assert whether it was called (message fell
    through) or not (the middleware fully handled it itself)."""
    handler = AsyncMock(return_value=None)
    await middleware(handler, message, {"bot": bot})
    return handler


@pytest.fixture
def middleware(db_sessionmaker: async_sessionmaker[AsyncSession]) -> SupportConversationMiddleware:
    return SupportConversationMiddleware(session_factory=db_sessionmaker)


# ---- invariant 1: never delivered outside alarm_recipients() ----


async def test_player_relay_reaches_only_configured_operators(
    db_sessionmaker: async_sessionmaker[AsyncSession], middleware, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("ALARM_TELEGRAM_IDS", "811111,822222")
    telegram_id = 900001
    async with db_sessionmaker() as session:
        await crud.open_support_conversation(session, telegram_id, _NOW)
        await session.commit()

    bot = _make_bot()
    message = _make_message(telegram_id, "Nie moge sie zarejestrowac")
    handler = await _run(middleware, message, bot)

    handler.assert_not_awaited()
    recipients = {call.args[0] for call in bot.send_message.await_args_list}
    assert recipients == {811111, 822222}
    message.answer.assert_awaited_once_with(t("support.confirmation", _LANG))


async def test_player_relay_is_silent_when_no_operators_are_configured(
    db_sessionmaker: async_sessionmaker[AsyncSession], middleware, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("ALARM_TELEGRAM_IDS", raising=False)
    telegram_id = 900002
    async with db_sessionmaker() as session:
        await crud.open_support_conversation(session, telegram_id, _NOW)
        await session.commit()

    bot = _make_bot()
    message = _make_message(telegram_id, "Halo?")
    await _run(middleware, message, bot)

    bot.send_message.assert_not_awaited()


# ---- invariant 2: operator's message reaches only their own named player ----


async def test_operator_relay_reaches_only_the_player_named_by_their_own_session(
    db_sessionmaker: async_sessionmaker[AsyncSession], middleware, monkeypatch: pytest.MonkeyPatch
):
    operator_id = 833333
    monkeypatch.setenv("ALARM_TELEGRAM_IDS", str(operator_id))
    user_a, user_b = 900010, 900011
    async with db_sessionmaker() as session:
        await crud.open_operator_session(session, operator_id, user_a, _NOW)
        await session.commit()

    bot = _make_bot()
    message = _make_message(operator_id, "Sprobuj ponownie za godzine")
    handler = await _run(middleware, message, bot)

    handler.assert_not_awaited()
    bot.send_message.assert_awaited_once()
    delivered_to = bot.send_message.await_args_list[0].args[0]
    assert delivered_to == user_a
    assert delivered_to != user_b
    delivered_text = bot.send_message.await_args_list[0].args[1]
    assert delivered_text.startswith(t("support.reply_header", _LANG))


# ---- invariant 3: a second player's message never redirects an open operator session ----


async def test_a_second_players_message_does_not_change_the_operators_open_session(
    db_sessionmaker: async_sessionmaker[AsyncSession], middleware, monkeypatch: pytest.MonkeyPatch
):
    operator_id = 844444
    monkeypatch.setenv("ALARM_TELEGRAM_IDS", str(operator_id))
    user_a, user_b = 900020, 900021
    async with db_sessionmaker() as session:
        await crud.open_operator_session(session, operator_id, user_a, _NOW)
        await crud.open_support_conversation(session, user_b, _NOW)
        await session.commit()

    bot = _make_bot()
    message = _make_message(user_b, "Czy ktos moze mi pomoc?")
    await _run(middleware, message, bot)

    async with db_sessionmaker() as session:
        session_row = await crud.get_operator_session(session, operator_id)
        assert session_row is not None
        assert session_row.user_telegram_id == user_a


# ---- invariant 4: expiry never delivers ----


async def test_expired_player_conversation_does_not_relay_and_closes(
    db_sessionmaker: async_sessionmaker[AsyncSession], middleware, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("ALARM_TELEGRAM_IDS", "855555")
    telegram_id = 900030
    stale = _NOW - PLAYER_CONVERSATION_TTL - timedelta(minutes=1)
    async with db_sessionmaker() as session:
        await crud.open_support_conversation(session, telegram_id, stale)
        await session.commit()

    bot = _make_bot()
    message = _make_message(telegram_id, "Jestem tu jeszcze?")
    handler = await _run(middleware, message, bot)

    handler.assert_not_awaited()
    bot.send_message.assert_not_awaited()
    message.answer.assert_awaited_once_with(t("support.conversation_expired", _LANG))

    async with db_sessionmaker() as session:
        conversation = await crud.get_support_conversation(session, telegram_id)
        assert conversation.is_open is False


async def test_expired_operator_session_does_not_deliver_and_closes(
    db_sessionmaker: async_sessionmaker[AsyncSession], middleware, monkeypatch: pytest.MonkeyPatch
):
    operator_id = 866666
    monkeypatch.setenv("ALARM_TELEGRAM_IDS", str(operator_id))
    player_id = 900040
    stale = _NOW - OPERATOR_SESSION_TTL - timedelta(minutes=1)
    async with db_sessionmaker() as session:
        await crud.open_operator_session(session, operator_id, player_id, stale)
        await session.commit()

    bot = _make_bot()
    message = _make_message(operator_id, "Jeszcze tu jestem")
    handler = await _run(middleware, message, bot)

    handler.assert_not_awaited()
    bot.send_message.assert_not_awaited()
    message.answer.assert_awaited_once()
    assert "expired" in message.answer.await_args_list[0].args[0]

    async with db_sessionmaker() as session:
        assert await crud.get_operator_session(session, operator_id) is None


# ---- invariant 5: no non-text content relayed either direction ----


async def test_non_text_from_a_player_with_an_open_conversation_is_refused_not_relayed(
    db_sessionmaker: async_sessionmaker[AsyncSession], middleware, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("ALARM_TELEGRAM_IDS", "877777")
    telegram_id = 900050
    async with db_sessionmaker() as session:
        await crud.open_support_conversation(session, telegram_id, _NOW)
        await session.commit()

    bot = _make_bot()
    message = _make_message(telegram_id, None, content_type=ContentType.PHOTO)
    handler = await _run(middleware, message, bot)

    handler.assert_not_awaited()
    bot.send_message.assert_not_awaited()
    message.answer.assert_awaited_once_with(t("support.non_text_refusal", _LANG))


async def test_non_text_from_an_operator_with_an_open_session_is_refused_not_relayed(
    db_sessionmaker: async_sessionmaker[AsyncSession], middleware, monkeypatch: pytest.MonkeyPatch
):
    operator_id = 888888
    monkeypatch.setenv("ALARM_TELEGRAM_IDS", str(operator_id))
    player_id = 900060
    async with db_sessionmaker() as session:
        await crud.open_operator_session(session, operator_id, player_id, _NOW)
        await session.commit()

    bot = _make_bot()
    message = _make_message(operator_id, None, content_type=ContentType.STICKER)
    handler = await _run(middleware, message, bot)

    handler.assert_not_awaited()
    bot.send_message.assert_not_awaited()
    message.answer.assert_awaited_once()


async def test_non_text_with_nothing_open_is_left_untouched(
    db_sessionmaker: async_sessionmaker[AsyncSession], middleware, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("ALARM_TELEGRAM_IDS", raising=False)
    bot = _make_bot()
    message = _make_message(900070, None, content_type=ContentType.PHOTO)
    handler = await _run(middleware, message, bot)

    handler.assert_awaited_once()
    message.answer.assert_not_awaited()


# ---- invariant 6: no message body ever written to the database ----


async def test_no_message_body_is_ever_written_to_the_database(
    db_sessionmaker: async_sessionmaker[AsyncSession], middleware, monkeypatch: pytest.MonkeyPatch
):
    operator_id = 899999
    monkeypatch.setenv("ALARM_TELEGRAM_IDS", str(operator_id))
    telegram_id = 900080
    secret = "a very specific support message body xyz123"

    async with db_sessionmaker() as session:
        await crud.open_support_conversation(session, telegram_id, _NOW)
        await session.commit()

    bot = _make_bot()
    message = _make_message(telegram_id, secret)
    await _run(middleware, message, bot)

    async with db_sessionmaker() as session:
        assert {c.name for c in inspect(SupportConversation).columns} == {
            "user_telegram_id",
            "is_open",
            "last_activity_at",
        }
        assert {c.name for c in inspect(SupportOperatorSession).columns} == {
            "operator_telegram_id",
            "user_telegram_id",
            "last_activity_at",
        }
        threads = (await session.execute(select(SupportThread))).scalars().all()
        assert threads
        for row in threads:
            values = [row.operator_chat_id, row.operator_message_id, row.user_telegram_id, str(row.created_at)]
            assert all(secret not in str(v) for v in values)


# ---- invariant 7: a command or nav label always falls through, closing silently ----


async def test_a_command_closes_the_open_conversation_silently_and_falls_through(
    db_sessionmaker: async_sessionmaker[AsyncSession], middleware, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("ALARM_TELEGRAM_IDS", "900100")  # different id -- this sender is a player
    telegram_id = 900090
    async with db_sessionmaker() as session:
        await crud.open_support_conversation(session, telegram_id, _NOW)
        await session.commit()

    bot = _make_bot()
    message = _make_message(telegram_id, "/moje_deble")
    handler = await _run(middleware, message, bot)

    handler.assert_awaited_once()
    bot.send_message.assert_not_awaited()
    message.answer.assert_not_awaited()

    async with db_sessionmaker() as session:
        conversation = await crud.get_support_conversation(session, telegram_id)
        assert conversation.is_open is False


async def test_a_persistent_keyboard_label_closes_the_open_conversation_silently_and_falls_through(
    db_sessionmaker: async_sessionmaker[AsyncSession], middleware, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("ALARM_TELEGRAM_IDS", raising=False)
    telegram_id = 900091
    async with db_sessionmaker() as session:
        await crud.open_support_conversation(session, telegram_id, _NOW)
        await session.commit()

    bot = _make_bot()
    message = _make_message(telegram_id, t("common.moje_deble_button", _LANG))
    handler = await _run(middleware, message, bot)

    handler.assert_awaited_once()
    bot.send_message.assert_not_awaited()

    async with db_sessionmaker() as session:
        conversation = await crud.get_support_conversation(session, telegram_id)
        assert conversation.is_open is False


async def test_status_command_from_an_operator_with_an_open_session_still_falls_through(
    db_sessionmaker: async_sessionmaker[AsyncSession], middleware, monkeypatch: pytest.MonkeyPatch
):
    """CLAUDE.md: "/status is registered before every other router so
    nothing else gets a chance to intercept it first" must still hold even
    when the operator has an open reply session -- a command is never
    swallowed by the relay."""
    operator_id = 900101
    monkeypatch.setenv("ALARM_TELEGRAM_IDS", str(operator_id))
    player_id = 900102
    async with db_sessionmaker() as session:
        await crud.open_operator_session(session, operator_id, player_id, _NOW)
        await session.commit()

    bot = _make_bot()
    message = _make_message(operator_id, "/status")
    handler = await _run(middleware, message, bot)

    handler.assert_awaited_once()
    bot.send_message.assert_not_awaited()


# ---- reply-to always wins, untouched ----


async def test_reply_to_bypasses_the_middleware_entirely(
    db_sessionmaker: async_sessionmaker[AsyncSession], middleware, monkeypatch: pytest.MonkeyPatch
):
    operator_id = 900110
    monkeypatch.setenv("ALARM_TELEGRAM_IDS", str(operator_id))
    other_player = 900111
    async with db_sessionmaker() as session:
        await crud.open_operator_session(session, operator_id, other_player, _NOW)
        await session.commit()

    bot = _make_bot()
    original = MagicMock(spec=Message, message_id=42)
    message = _make_message(operator_id, "a reply, not a fresh message", reply_to=original)
    handler = await _run(middleware, message, bot)

    # Falls straight through to bot.handlers.support's own reply-to path --
    # the middleware itself relays nothing and answers nothing.
    handler.assert_awaited_once()
    bot.send_message.assert_not_awaited()
    message.answer.assert_not_awaited()


# ---- the registration fall-through fix ----


async def test_operator_with_no_account_and_nothing_open_gets_a_note_instead_of_reaching_registration(
    db_sessionmaker: async_sessionmaker[AsyncSession], middleware, monkeypatch: pytest.MonkeyPatch
):
    operator_id = 900120
    monkeypatch.setenv("ALARM_TELEGRAM_IDS", str(operator_id))
    bot = _make_bot()
    message = _make_message(operator_id, "SWD12345")  # looks like a PZT id
    handler = await _run(middleware, message, bot)

    handler.assert_not_awaited()
    message.answer.assert_awaited_once()
    assert "no open conversation" in message.answer.await_args_list[0].args[0]


async def test_operator_with_an_account_and_nothing_open_uses_the_bot_normally(
    db_sessionmaker: async_sessionmaker[AsyncSession], middleware, monkeypatch: pytest.MonkeyPatch
):
    operator_id = 900121
    monkeypatch.setenv("ALARM_TELEGRAM_IDS", str(operator_id))
    async with db_sessionmaker() as session:
        await _add_account(session, "SUP9121", operator_id, "Kowalski Jan")
        await session.commit()

    bot = _make_bot()
    message = _make_message(operator_id, "Uniejow")
    handler = await _run(middleware, message, bot)

    handler.assert_awaited_once()
    message.answer.assert_not_awaited()


async def test_an_ordinary_player_with_nothing_open_is_left_untouched(
    db_sessionmaker: async_sessionmaker[AsyncSession], middleware, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("ALARM_TELEGRAM_IDS", raising=False)
    bot = _make_bot()
    message = _make_message(900130, "Uniejow")
    handler = await _run(middleware, message, bot)

    handler.assert_awaited_once()
    message.answer.assert_not_awaited()
    bot.send_message.assert_not_awaited()


# ---- the rate cap on the player -> operator relay ----


async def test_player_relay_rate_cap_blocks_the_sixth_message_in_an_hour(
    db_sessionmaker: async_sessionmaker[AsyncSession], middleware, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("ALARM_TELEGRAM_IDS", "900140")
    telegram_id = 900141
    async with db_sessionmaker() as session:
        await crud.open_support_conversation(session, telegram_id, _NOW)
        await session.commit()

    bot = _make_bot()
    for _ in range(5):
        message = _make_message(telegram_id, "wiadomosc")
        await _run(middleware, message, bot)

    assert bot.send_message.await_count == 5

    blocked_message = _make_message(telegram_id, "szosta wiadomosc")
    await _run(middleware, blocked_message, bot)

    assert bot.send_message.await_count == 5
    blocked_message.answer.assert_awaited_once_with(t("support.rate_limited", _LANG))
