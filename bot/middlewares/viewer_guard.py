"""Fail-closed guard against a viewer acting on the player's behalf
(CLAUDE.md, "Identity", step 10, WHAT A VIEWER CANNOT DO: "enforce all of
this in code, not by hiding buttons... A viewer callback for any action
must be rejected server-side even if a button were somehow present.").

Every existing action handler already resolves who is acting exclusively
via `crud.get_account_by_telegram_id(session, callback.from_user.id)`,
never from the callback payload -- so a pure viewer (no Account row of
their own) already gets each handler's own `account is None` no-op branch
today, incidentally. This middleware makes that safety property explicit,
uniform, and independent of any single handler being written correctly:
it runs before every callback_query handler in the dispatcher and blocks
anyone with no Account of their own who nonetheless holds an active
viewer grant, unless the specific callback is on the read-only allowlist
below.

Allowlist, not denylist, on purpose: a new action callback added anywhere
in bot/ in the future is blocked for account-less viewers by default,
unless someone deliberately marks its prefix safe here -- the safer
default for a fail-closed check.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, TelegramObject

from db import crud

logger = logging.getLogger(__name__)

# ViewerChooseAccountCallback (bot.keyboards.viewers): the one callback a
# pure viewer is meant to tap -- picking which watched player's read-only
# Moje deble to open. Nothing else lets a viewer with no Account of their
# own act on anything.
_SAFE_PREFIXES = frozenset({"vwchs"})


class ViewerActionGuardMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, CallbackQuery) and event.data:
            prefix = event.data.split(":", 1)[0]
            if prefix not in _SAFE_PREFIXES:
                session = data["session"]
                account = await crud.get_account_by_telegram_id(session, event.from_user.id)
                if account is None:
                    grants = await crud.get_active_viewer_grants_for_telegram_id(session, event.from_user.id)
                    if grants:
                        logger.info(
                            "Blocked action callback from viewer-only telegram_id=%s prefix=%s",
                            event.from_user.id,
                            prefix,
                        )
                        await event.answer()
                        return None
        return await handler(event, data)
