"""Bot entrypoint. Reads BOT_TOKEN/DATABASE_URL from the environment
(CLAUDE.md, "Never commit secrets") and starts long polling.
"""

from __future__ import annotations

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from dotenv import load_dotenv

from bot.handlers import my_players, start
from bot.i18n import t
from bot.lang import DEFAULT_LANG
from bot.middlewares.db import DbSessionMiddleware

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def _set_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description=t("commands.start", DEFAULT_LANG)),
            BotCommand(command="moi_zawodnicy", description=t("commands.moi_zawodnicy", DEFAULT_LANG)),
        ]
    )


async def main() -> None:
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN is not set")

    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dispatcher = Dispatcher(storage=MemoryStorage())

    db_middleware = DbSessionMiddleware()
    dispatcher.message.middleware(db_middleware)
    dispatcher.callback_query.middleware(db_middleware)

    dispatcher.include_router(start.router)
    dispatcher.include_router(my_players.router)

    await _set_commands(bot)
    await bot.delete_webhook(drop_pending_updates=True)
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
