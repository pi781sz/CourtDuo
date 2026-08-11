"""Operator-only /status command (CLAUDE.md "Operations"): a plain-text
snapshot of each scraper's last successful run, last run outcome, and
whether it is currently inside its staleness threshold.

Gated on the same ALARM_TELEGRAM_IDS the staleness alarm itself sends to
-- this is an operator surface, not a player-facing one, so it is never
wired through entitlements or locales/pl.json. To anybody whose Telegram
id isn't on that list, /status does nothing at all -- no reply, not even
a refusal -- so a child typing it sees exactly what they would see typing
any other unknown command (the same "invisible, not merely locked"
discipline bot.handlers.viewers already applies to /podglad).

Registered first in bot.main, ahead of every other router, so nothing
else gets a chance to swallow the command first.
"""

from __future__ import annotations

from datetime import datetime, timezone

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.staleness import SCRAPERS, alarm_recipients, format_status_report, get_scraper_status

router = Router(name="status")


@router.message(Command("status"))
async def handle_status(message: Message, session: AsyncSession) -> None:
    if message.from_user is None or message.from_user.id not in alarm_recipients():
        return
    now = datetime.now(timezone.utc)
    statuses = [await get_scraper_status(session, scraper, now) for scraper in SCRAPERS]
    await message.answer(format_status_report(statuses, now))
