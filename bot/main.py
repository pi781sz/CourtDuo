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
from aiogram.types import BotCommand
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.handlers import (
    account_deletion_router,
    invitations_router,
    invite_friend_router,
    moje_deble_router,
    navigation_router,
    partner_selection_router,
    pending_external_invites_router,
    start_router,
    status_router,
    tournament_search_router,
    viewers_router,
)
from bot.i18n import t
from bot.lang import DEFAULT_LANG
from bot.middlewares.db import DbSessionMiddleware
from bot.middlewares.viewer_guard import ViewerActionGuardMiddleware
from bot.staleness import register as register_staleness_alarm

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# The Telegram "/" command menu. One module-level constant -- (command,
# locale key) pairs -- so adding another command later is a one-line
# change. /moje_deble, /usun_konto and /podglad stay reachable as commands
# but out of the menu.
BOT_COMMANDS: tuple[tuple[str, str], ...] = (("start", "commands.start"),)


async def set_bot_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        [BotCommand(command=command, description=t(key, DEFAULT_LANG)) for command, key in BOT_COMMANDS]
    )


def build_dispatcher(session_factory: async_sessionmaker | None = None) -> Dispatcher:
    """Assembles the Dispatcher: one DbSessionMiddleware, every feature
    router. Split out from main() so tests can feed real Updates through
    the exact same router wiring and ordering production uses (see
    tests/test_persistent_menu_routing.py) rather than duplicating it.
    """
    dispatcher = Dispatcher(storage=MemoryStorage())

    db_middleware = DbSessionMiddleware(session_factory)
    dispatcher.message.middleware(db_middleware)
    dispatcher.callback_query.middleware(db_middleware)
    # CLAUDE.md step 10: fail-closed guard against a viewer (an active
    # account_viewers grant, no Account of their own) reaching any action
    # callback -- registered after db_middleware, which it depends on for
    # `session`, and before every feature router so it sees every callback
    # query regardless of which router would otherwise have handled it.
    dispatcher.callback_query.middleware(ViewerActionGuardMiddleware())

    # CLAUDE.md "Operations": /status is registered before every other
    # router so nothing else gets a chance to intercept it first.
    dispatcher.include_router(status_router)

    # navigation/moje_deble/invite_friend/viewers registered first:
    # CLAUDE.md step 8.4's persistent reply keyboard adds exact-text
    # message handlers ("Znajdź partnera", "Moje deble", "Zaproś na
    # CourtDuo", and since step 10.2, "Podgląd konta") that must win
    # against a tap arriving while the player is mid another flow -- e.g.
    # typing a place or a partner name -- before those state-scoped
    # handlers ever see the update. viewers_router also carries the
    # /podglad command and its callback handlers, unaffected by ordering,
    # so moving it here for its label handler doesn't disturb them.
    dispatcher.include_router(navigation_router)
    dispatcher.include_router(moje_deble_router)
    dispatcher.include_router(invite_friend_router)
    dispatcher.include_router(viewers_router)
    dispatcher.include_router(start_router)
    dispatcher.include_router(tournament_search_router)
    dispatcher.include_router(partner_selection_router)
    dispatcher.include_router(invitations_router)
    dispatcher.include_router(pending_external_invites_router)
    dispatcher.include_router(account_deletion_router)

    # CLAUDE.md "Operations": the staleness alarm's background task,
    # spawned on dispatcher startup and cancelled on shutdown.
    register_staleness_alarm(dispatcher)
    return dispatcher


async def main() -> None:
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN is not set")

    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dispatcher = build_dispatcher()

    try:
        await set_bot_commands(bot)
        await bot.delete_webhook(drop_pending_updates=True)
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
