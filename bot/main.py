"""Bot entrypoint. Reads BOT_TOKEN/DATABASE_URL from the environment
(CLAUDE.md, "Never commit secrets") and starts long polling.

Registers one router per feature (CLAUDE.md build order step 4:
registration; step 5: tournament selection by place; step 6: partner name
entry; step 7: invitation send/accept/reject; step 8: the Moje deble status
view). Later steps add routers here rather than growing these.
"""

from __future__ import annotations

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

from bot.handlers import (
    invitations_router,
    moje_deble_router,
    navigation_router,
    partner_selection_router,
    start_router,
    tournament_search_router,
)
from bot.middlewares.db import DbSessionMiddleware

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN is not set")

    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dispatcher = Dispatcher(storage=MemoryStorage())

    db_middleware = DbSessionMiddleware()
    dispatcher.message.middleware(db_middleware)
    dispatcher.callback_query.middleware(db_middleware)

    dispatcher.include_router(start_router)
    dispatcher.include_router(tournament_search_router)
    dispatcher.include_router(partner_selection_router)
    dispatcher.include_router(invitations_router)
    dispatcher.include_router(navigation_router)
    dispatcher.include_router(moje_deble_router)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
