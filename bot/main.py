"""Bot entrypoint. Reads BOT_TOKEN/DATABASE_URL from the environment
(CLAUDE.md, "Never commit secrets") and starts long polling.

No routers are registered yet — the invitation-flow handlers are future
work (CLAUDE.md, "Build order" items 4+), not part of this schema change.
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

    await bot.delete_webhook(drop_pending_updates=True)
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
