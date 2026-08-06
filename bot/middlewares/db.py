"""Opens one AsyncSession per update and injects it into handlers as the
`session` kwarg, committing after the handler returns. On an unhandled
exception the session is closed without a commit, which rolls back
whatever the handler had pending — no handler needs its own try/rollback.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import async_sessionmaker

from db.session import get_session_factory


class DbSessionMiddleware(BaseMiddleware):
    def __init__(self, session_factory: async_sessionmaker | None = None) -> None:
        self._session_factory = session_factory or get_session_factory()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with self._session_factory() as session:
            data["session"] = session
            result = await handler(event, data)
            await session.commit()
            return result
