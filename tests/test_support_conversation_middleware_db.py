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
     conversation an operator has open -- it SUSPENDS it instead (see
     invariants 8-10 below).
  4. An expired conversation or session never delivers a message, on
     either side.
  5. No non-text content is relayed in either direction.
  6. No message body is ever written to the database.
  7. A command or a persistent-reply-keyboard label always falls through
     untouched (closing a player's own open conversation silently on the
     way), regardless of what is open -- this is what keeps /status and
     every other router's own priority unchanged.
  8. A message from a second player always suspends the operator's
     session (on top of invariant 3: the target name doesn't change, but
     delivery stops until the operator picks again).
  9. A suspended session delivers NOTHING to any player, whatever the
     operator types, until a "Reply: {name}" button is tapped.
  10. A message typed while suspended is never delivered later, to anyone
      -- tapping "Reply:" resumes the session but does not flush anything
      held.
  11. A player never receives an automatic confirmation of their own
      message -- the operator's reply is the next thing they see.
  12. Every delivered operator message produces exactly one receipt to
      that operator naming the recipient.

Needs a real Postgres -- see tests/conftest.py, skipped cleanly when
TEST_DATABASE_URL is unset. Invented telegram ids/names/pzt_ids only --
never a real PZT id (CLAUDE.md rule 4).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.enums import ContentType
from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import Message
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.handlers.support import handle_support_reply_tap
from bot.keyboards.support import SupportReplyCallback
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
    # FIX 1: no automatic confirmation to the player any more -- the
    # conversation-opened message already told them their answer arrives
    # here.
    message.answer.assert_not_awaited()


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


# ---- invariant 3 & 8: a second player's message never redirects an open operator session, but does suspend it ----


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
        # FIX 2: the target never silently changes -- but the session is
        # no longer safe to deliver through until the operator re-picks.
        assert session_row.state == "suspended"


async def test_a_message_from_the_operators_own_current_player_does_not_suspend(
    db_sessionmaker: async_sessionmaker[AsyncSession], middleware, monkeypatch: pytest.MonkeyPatch
):
    """The no-auto-switch rule cuts both ways: a session must not be
    suspended by more messages from the exact player it's already open
    with."""
    operator_id = 844445
    monkeypatch.setenv("ALARM_TELEGRAM_IDS", str(operator_id))
    user_a = 900022
    async with db_sessionmaker() as session:
        await crud.open_operator_session(session, operator_id, user_a, _NOW)
        await crud.open_support_conversation(session, user_a, _NOW)
        await session.commit()

    bot = _make_bot()
    message = _make_message(user_a, "kolejna wiadomosc od tej samej osoby")
    await _run(middleware, message, bot)

    async with db_sessionmaker() as session:
        session_row = await crud.get_operator_session(session, operator_id)
        assert session_row.state == "open"


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
            "state",
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


# ---- helpers shared by the suspension / receipt tests below ----


def _make_callback(telegram_id: int) -> MagicMock:
    callback = MagicMock()
    callback.from_user = MagicMock(id=telegram_id)
    callback.answer = AsyncMock()
    callback.message = MagicMock()
    callback.message.answer = AsyncMock()
    return callback


# ---- reproduction of the reported bug ----
#
# Live testing: with an open conversation to player A, player B sent
# /pomoc and a message. The operator then typed a reply intended for B,
# and it was delivered to A.
#
# Reproducing it against the UNFIXED code (git stash the middleware/crud
# changes and re-run just this test) shows outcome (a): B's message
# correctly carried its own "Reply:" button, the operator's session
# correctly stayed pointed at A, and the operator's plain-typed message
# still went to A -- nothing stopped them from typing while the session
# still named A. A design failure, not a routing bug: (b) and (c) are
# both false. This test passes on the fixed code because the session is
# now SUSPENDED the moment B's message arrives, so the operator's typed
# reply is withheld rather than misdelivered.


async def test_reported_bug_operator_reply_after_a_second_players_message_is_withheld_not_misdelivered(
    db_sessionmaker: async_sessionmaker[AsyncSession], middleware, monkeypatch: pytest.MonkeyPatch
):
    operator_id = 910001
    monkeypatch.setenv("ALARM_TELEGRAM_IDS", str(operator_id))
    player_a, player_b = 910010, 910011

    async with db_sessionmaker() as session:
        # Operator already tapped "Reply: A" -- an open session on A.
        await crud.open_support_conversation(session, player_a, _NOW)
        await crud.open_operator_session(session, operator_id, player_a, _NOW)
        # B has an open conversation too (sent /pomoc already).
        await crud.open_support_conversation(session, player_b, _NOW)
        await session.commit()

    bot = _make_bot()

    # B sends a message.
    b_message = _make_message(player_b, "Wiadomosc od B")
    await _run(middleware, b_message, bot)

    # B's own message carried its own "Reply:" button, unconditionally.
    b_deliveries = [c for c in bot.send_message.await_args_list if c.args[0] == operator_id]
    assert len(b_deliveries) == 1
    assert b_deliveries[0].kwargs.get("reply_markup") is not None
    bot.send_message.reset_mock()

    # The operator's session still names A -- no silent redirect.
    async with db_sessionmaker() as session:
        op_session = await crud.get_operator_session(session, operator_id)
        assert op_session.user_telegram_id == player_a
        assert op_session.state == "suspended"

    # The operator, unaware, types a reply meant for B.
    op_message = _make_message(operator_id, "Odpowiedz dla B")
    await _run(middleware, op_message, bot)

    # It must NOT be delivered to A (the old bug) -- and must not be
    # delivered to B either, since the operator never said so explicitly.
    bot.send_message.assert_not_awaited()


# ---- invariant 9: a suspended session delivers nothing, whatever is typed ----


async def test_suspended_session_delivers_nothing_regardless_of_what_the_operator_types(
    db_sessionmaker: async_sessionmaker[AsyncSession], middleware, monkeypatch: pytest.MonkeyPatch
):
    operator_id = 920001
    monkeypatch.setenv("ALARM_TELEGRAM_IDS", str(operator_id))
    player_a, player_b = 920010, 920011
    async with db_sessionmaker() as session:
        await crud.open_operator_session(session, operator_id, player_a, _NOW)
        await crud.open_support_conversation(session, player_b, _NOW)
        await session.commit()

    bot = _make_bot()
    # B's message suspends the operator's session.
    await _run(middleware, _make_message(player_b, "halo"), bot)
    bot.send_message.reset_mock()

    for text in ("pierwsza proba", "druga proba", "trzecia proba"):
        await _run(middleware, _make_message(operator_id, text), bot)

    bot.send_message.assert_not_awaited()

    async with db_sessionmaker() as session:
        op_session = await crud.get_operator_session(session, operator_id)
        assert op_session.state == "suspended"
        assert op_session.user_telegram_id == player_a


async def test_suspended_session_offers_a_reply_button_per_waiting_player(
    db_sessionmaker: async_sessionmaker[AsyncSession], middleware, monkeypatch: pytest.MonkeyPatch
):
    operator_id = 920020
    monkeypatch.setenv("ALARM_TELEGRAM_IDS", str(operator_id))
    player_a, player_b = 920030, 920031
    async with db_sessionmaker() as session:
        await _add_account(session, "SUP2003", player_a, "Nowak Amelia")
        await _add_account(session, "SUP2004", player_b, "Kowalski Piotr")
        await crud.open_operator_session(session, operator_id, player_a, _NOW)
        await crud.open_support_conversation(session, player_a, _NOW)
        await crud.open_support_conversation(session, player_b, _NOW)
        await session.commit()

    bot = _make_bot()
    await _run(middleware, _make_message(player_b, "halo"), bot)

    suspended_message = _make_message(operator_id, "kto to jest?")
    await _run(middleware, suspended_message, bot)

    suspended_message.answer.assert_awaited_once()
    _, kwargs = suspended_message.answer.await_args
    keyboard = kwargs["reply_markup"]
    labels = {button.text for row in keyboard.inline_keyboard for button in row}
    assert labels == {"Reply: Amelia Nowak", "Reply: Piotr Kowalski"}


# ---- invariant 10: nothing typed while suspended is ever delivered later ----


async def test_message_typed_while_suspended_is_never_delivered_after_resuming(
    db_sessionmaker: async_sessionmaker[AsyncSession], middleware, monkeypatch: pytest.MonkeyPatch
):
    operator_id = 930001
    monkeypatch.setenv("ALARM_TELEGRAM_IDS", str(operator_id))
    player_a, player_b = 930010, 930011
    async with db_sessionmaker() as session:
        await crud.open_operator_session(session, operator_id, player_a, _NOW)
        await crud.open_support_conversation(session, player_b, _NOW)
        await session.commit()

    bot = _make_bot()
    await _run(middleware, _make_message(player_b, "halo"), bot)
    bot.send_message.reset_mock()

    # Typed while suspended -- held, not delivered.
    await _run(middleware, _make_message(operator_id, "wiadomosc napisana w zawieszeniu"), bot)
    bot.send_message.assert_not_awaited()

    # The operator taps "Reply: B" to resume.
    async with db_sessionmaker() as session:
        callback = _make_callback(operator_id)
        callback_data = SupportReplyCallback(user_telegram_id=player_b)
        await handle_support_reply_tap(callback, callback_data, session)
        await session.commit()

    async with db_sessionmaker() as session:
        op_session = await crud.get_operator_session(session, operator_id)
        assert op_session.state == "open"
        assert op_session.user_telegram_id == player_b

    # Resuming never retroactively delivers the held message.
    bot.send_message.assert_not_awaited()

    # The operator has to retype -- only the fresh message is delivered.
    await _run(middleware, _make_message(operator_id, "nowa wiadomosc dla B"), bot)
    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args_list[0].args[0] == player_b
    delivered_text = bot.send_message.await_args_list[0].args[1]
    assert "nowa wiadomosc dla B" in delivered_text
    assert "wiadomosc napisana w zawieszeniu" not in delivered_text


# ---- invariant 11: no automatic confirmation to the player ----


async def test_player_never_gets_an_automatic_confirmation_of_their_own_message(
    db_sessionmaker: async_sessionmaker[AsyncSession], middleware, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("ALARM_TELEGRAM_IDS", "940001")
    telegram_id = 940002
    async with db_sessionmaker() as session:
        await crud.open_support_conversation(session, telegram_id, _NOW)
        await session.commit()

    bot = _make_bot()
    message = _make_message(telegram_id, "czy to dziala?")
    await _run(middleware, message, bot)

    message.answer.assert_not_awaited()


# ---- invariant 12: exactly one delivery receipt per delivered operator message ----


async def test_operator_gets_exactly_one_receipt_naming_the_recipient(
    db_sessionmaker: async_sessionmaker[AsyncSession], middleware, monkeypatch: pytest.MonkeyPatch
):
    operator_id = 950001
    monkeypatch.setenv("ALARM_TELEGRAM_IDS", str(operator_id))
    player_id = 950010
    async with db_sessionmaker() as session:
        await _add_account(session, "SUP5001", player_id, "Szewczyk Jagoda")
        await crud.open_operator_session(session, operator_id, player_id, _NOW)
        await session.commit()

    bot = _make_bot()
    message = _make_message(operator_id, "Sprobuj ponownie za godzine")
    await _run(middleware, message, bot)

    bot.send_message.assert_awaited_once()
    message.answer.assert_awaited_once_with("Sent to Jagoda Szewczyk.")


async def test_no_receipt_when_nothing_was_actually_delivered(
    db_sessionmaker: async_sessionmaker[AsyncSession], middleware, monkeypatch: pytest.MonkeyPatch
):
    """A suspended session (invariant 9) is the main case, covered above --
    this checks the delivery-failure path too: push() returning None must
    not produce a false "Sent to" receipt."""
    operator_id = 950020
    monkeypatch.setenv("ALARM_TELEGRAM_IDS", str(operator_id))
    player_id = 950021
    async with db_sessionmaker() as session:
        await crud.open_operator_session(session, operator_id, player_id, _NOW)
        await session.commit()

    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=TelegramForbiddenError(MagicMock(), "blocked"))

    message = _make_message(operator_id, "wiadomosc")
    await _run(middleware, message, bot)

    message.answer.assert_not_awaited()
