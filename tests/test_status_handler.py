"""bot.handlers.status's /status command (CLAUDE.md "Operations"): must be
silent to anybody whose Telegram id is not in ALARM_TELEGRAM_IDS -- no
reply, no error, indistinguishable from any other unknown command a
player might type. Against a real Postgres (see tests/conftest.py,
skipped cleanly when TEST_DATABASE_URL is unset) since handle_status
needs a real session to query scraper_runs through, even though this test
never has to populate any rows to prove the silence.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from bot.handlers.status import handle_status


def _make_message(telegram_id: int) -> MagicMock:
    message = MagicMock()
    message.from_user.id = telegram_id
    message.answer = AsyncMock()
    return message


async def test_status_is_silent_for_a_non_allowlisted_id(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ALARM_TELEGRAM_IDS", "999999")
    message = _make_message(123456)  # not in ALARM_TELEGRAM_IDS

    await handle_status(message, db_session)

    message.answer.assert_not_called()


async def test_status_is_silent_when_no_recipients_are_configured_at_all(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("ALARM_TELEGRAM_IDS", raising=False)
    message = _make_message(123456)

    await handle_status(message, db_session)

    message.answer.assert_not_called()


async def test_status_replies_for_an_allowlisted_id(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ALARM_TELEGRAM_IDS", "999999")
    message = _make_message(999999)

    await handle_status(message, db_session)

    message.answer.assert_called_once()
    report = message.answer.call_args.args[0]
    assert "tournaments" in report
    assert "rankings" in report
