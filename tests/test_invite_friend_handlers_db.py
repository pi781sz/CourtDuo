"""Tests for bot.handlers.invite_friend.handle_invite_friend (CLAUDE.md
step 8.4, CHANGE 2): the "Zaproś na CourtDuo" persistent-keyboard label.
Needs a real Postgres for the Account row the handler looks up -- see
tests/conftest.py, skipped cleanly when TEST_DATABASE_URL is unset.
Invented telegram ids/names/pzt_ids only.
"""

from __future__ import annotations

import re
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from bot.handlers.invite_friend import handle_invite_friend
from db.models import Account, Player

_TELEGRAM_ID = 800001


def _make_message() -> MagicMock:
    message = MagicMock()
    message.from_user.id = _TELEGRAM_ID
    message.answer = AsyncMock()
    return message


def _make_bot(username: str) -> MagicMock:
    bot = MagicMock()
    bot.get_me = AsyncMock(return_value=MagicMock(username=username))
    return bot


async def _make_account(session: AsyncSession) -> None:
    session.add(Player(pzt_id="IVF0001", full_name="Testowy Gracz", club=None, age_category=None, gender=None))
    await session.flush()
    session.add(Account(telegram_id=_TELEGRAM_ID, pzt_id="IVF0001", full_name="Testowy Gracz", gender="M", lang="pl"))
    await session.flush()


async def test_link_comes_from_get_me_not_a_literal(db_session: AsyncSession):
    await _make_account(db_session)
    message = _make_message()
    bot = _make_bot("courtduo_prod_bot")

    await handle_invite_friend(message, db_session, bot)

    bot.get_me.assert_awaited_once()
    body = message.answer.call_args.args[0]
    assert "https://t.me/courtduo_prod_bot" in body

    # A different bot (e.g. the test bot) produces a different link from
    # the exact same code path -- proves it isn't hardcoded anywhere.
    message2 = _make_message()
    bot2 = _make_bot("courtduo_test_bot")
    await handle_invite_friend(message2, db_session, bot2)
    body2 = message2.answer.call_args.args[0]
    assert "https://t.me/courtduo_test_bot" in body2
    assert "courtduo_prod_bot" not in body2


async def test_message_includes_copyable_sms_text_since_no_sms_button_exists(db_session: AsyncSession):
    await _make_account(db_session)
    message = _make_message()
    bot = _make_bot("courtduo_prod_bot")

    await handle_invite_friend(message, db_session, bot)

    body = message.answer.call_args.args[0]
    assert "<code>" in body
    markup = message.answer.call_args.kwargs["reply_markup"]
    button_texts = [button.text for row in markup.inline_keyboard for button in row]
    assert "SMS" not in button_texts
    assert button_texts == ["WhatsApp", "Telegram"]


async def test_keyboard_buttons_are_both_https_urls(db_session: AsyncSession):
    await _make_account(db_session)
    message = _make_message()
    bot = _make_bot("courtduo_prod_bot")

    await handle_invite_friend(message, db_session, bot)

    markup = message.answer.call_args.kwargs["reply_markup"]
    buttons = [button for row in markup.inline_keyboard for button in row]
    for button in buttons:
        assert button.url.startswith("https://")


async def test_no_phone_number_appears_anywhere_in_the_share_flow(db_session: AsyncSession):
    # CLAUDE.md, non-negotiable rule 2: the bot never sees, stores or
    # sends a phone number. Nothing here ever touches one -- the recipient
    # is chosen in the player's own phone/app.
    await _make_account(db_session)
    message = _make_message()
    bot = _make_bot("courtduo_prod_bot")

    await handle_invite_friend(message, db_session, bot)

    body = message.answer.call_args.args[0]
    markup = message.answer.call_args.kwargs["reply_markup"]
    urls = [button.url for row in markup.inline_keyboard for button in row]
    # No phone-number-shaped token (a run of 7+ digits, optionally with a
    # leading +) anywhere in what was sent.
    assert not re.search(r"\+?\d{7,}", body)
    assert not any(re.search(r"\+?\d{7,}", url) for url in urls)
    assert not hasattr(Account, "phone")
