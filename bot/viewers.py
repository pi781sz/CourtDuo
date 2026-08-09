"""Read-only viewers: token lifecycle, binding, and notification forwarding
(CLAUDE.md, "Identity", step 10). The Telegram plumbing lives in
bot.handlers.viewers and the deep-link interception in
bot.handlers.start; this module is the engine, the same split
bot.registration and bot.invitation_engine follow.

A viewer never gets a database row of its own account -- it is purely a
(account_id, viewer_telegram_id) grant. Binding one is deliberately not an
error path: CLAUDE.md step 10 says a used, expired or unknown token
"behaves like a plain /start and never errors", so bind_viewer reports
BOUND or INVALID and never raises.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum, auto

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from bot.notifications import push
from db import crud
from db.models import Account, ViewerInviteToken

logger = logging.getLogger(__name__)

# CLAUDE.md step 10, GRANTING ACCESS: "a single-use random token, valid 24
# hours".
TOKEN_TTL = timedelta(hours=24)


def generate_token() -> str:
    # url-safe, no padding characters that would need escaping in a t.me
    # deep link -- well under Telegram's 64-character start-payload limit.
    return secrets.token_urlsafe(24)


def invite_link(bot_username: str, token: str) -> str:
    """A t.me deep link that reopens the bot with the token as /start's
    payload (CLAUDE.md step 10: "a t.me deep link"). Mirrors
    bot.invite_friend.share_link's get_me()-at-runtime convention -- the
    bot username is never hardcoded, so the same code is correct for the
    test and production bots."""
    return f"https://t.me/{bot_username}?start={token}"


async def create_invite_token(session: AsyncSession, account: Account) -> ViewerInviteToken | None:
    """Issues a fresh invite token for `account`, or None if they're
    already at the 3-active-viewer cap (CLAUDE.md step 10: "Maximum 3
    active viewers per account") -- refused here rather than letting a
    token sit unusable, since it could never be bound anyway.
    """
    if await crud.count_active_viewers(session, account.id) >= crud.MAX_ACTIVE_VIEWERS:
        return None
    expires_at = datetime.now(timezone.utc) + TOKEN_TTL
    return await crud.create_viewer_invite_token(session, account.id, generate_token(), expires_at)


class ViewerBindOutcome(Enum):
    BOUND = auto()
    INVALID = auto()


@dataclass
class ViewerBindResult:
    outcome: ViewerBindOutcome
    watched_account: Account | None = None


async def bind_viewer(session: AsyncSession, viewer_telegram_id: int, raw_token: str, now: datetime) -> ViewerBindResult:
    """Consumes `raw_token` (CLAUDE.md step 10, GRANTING ACCESS) and binds
    `viewer_telegram_id` as a read-only viewer of the token's account.

    A used, expired or unknown token returns INVALID and changes nothing
    -- the caller (bot.handlers.start) then falls through to plain /start
    behaviour, never an error message (CLAUDE.md: "never errors").
    Already-active access (the player re-shares a fresh link to someone
    who already has it) is treated as a harmless no-op bind, not a second
    grant. Re-checks the 3-viewer cap here too, not just at token
    creation: two outstanding tokens for the same account could otherwise
    both be consumed and push the count past 3.
    """
    token_row = await crud.get_viewer_invite_token(session, raw_token)
    if token_row is None or token_row.consumed_at is not None or token_row.expires_at <= now:
        return ViewerBindResult(ViewerBindOutcome.INVALID)

    # Burned either way, successful or not -- a token gets exactly one
    # attempt (CLAUDE.md: "The token is consumed").
    await crud.mark_viewer_invite_token_consumed(session, token_row, now)

    existing = await crud.get_active_viewer(session, token_row.account_id, viewer_telegram_id)
    if existing is None:
        if await crud.count_active_viewers(session, token_row.account_id) >= crud.MAX_ACTIVE_VIEWERS:
            return ViewerBindResult(ViewerBindOutcome.INVALID)
        await crud.add_viewer(session, token_row.account_id, viewer_telegram_id)

    watched_account = await crud.get_account_by_id(session, token_row.account_id)
    if watched_account is None:
        logger.error("viewer_invite_token %s has no matching account", token_row.id)
        return ViewerBindResult(ViewerBindOutcome.INVALID)
    return ViewerBindResult(ViewerBindOutcome.BOUND, watched_account=watched_account)


async def forward_to_viewers(bot: Bot, session: AsyncSession, account_id: int, text: str) -> None:
    """Sends a text-only copy of `text` to every active viewer of
    `account_id` -- CLAUDE.md step 10, WHAT A VIEWER CAN DO: "Receive a
    copy of every notification the player receives or triggers." No
    `reply_markup` is ever accepted or passed here, so "forwarded
    notifications carry NO action buttons at all" holds by construction,
    not by per-call-site care.

    Deliberately does not re-check entitlements.can_use_viewers: a grant
    already made must keep forwarding even if the watched player's pzt_id
    later drops off the allowlist (only creating new grants is gated —
    revocation is exclusively the player's own action, see CLAUDE.md's "no
    admin path" rule).
    """
    viewers = await crud.get_active_viewers_for_account(session, account_id)
    for viewer in viewers:
        await push(bot, viewer.viewer_telegram_id, text)
