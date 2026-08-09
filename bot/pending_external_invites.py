"""The "they joined" half of CLAUDE.md scenario 2 (build order step 9,
PART 2). bot.invitation_send.send_not_on_courtduo_response (PART 1) is the
only writer of pending_external_invites, storing one row per (inviter,
named player, tournament) whenever every one of step 6's checks passed but
the named player had no account to deliver a real invitation to. This
module is the only reader: once that named player actually registers,
every stored row naming them is checked and, for the ones still worth
acting on, pushes the inviter a notification with a button that resumes
the invitation without retyping the name.

Every row is consumed here -- deleted after being checked, whether or not
it ends up notifying anyone. None of the three conditions CLAUDE.md lists
("within the window, search still open, and the inviter has not since
matched with someone else") can become true again once false, and
registration only happens once per pzt_id, so nothing is ever lost by not
keeping a row around past this one check.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from bot.invitation_text import gendered
from bot.keyboards.pending_external_invites import pending_external_invite_offer_keyboard
from bot.lang import DEFAULT_LANG
from bot.notifications import push
from core.text import display_name
from db import crud
from db.models import PendingExternalInvite, Player

logger = logging.getLogger(__name__)

_WARSAW_TZ = ZoneInfo("Europe/Warsaw")


def _warsaw_today_and_utc_now() -> tuple[date, datetime]:
    """Mirrors the private helper of the same name in
    bot.handlers.tournament_search and bot.partner_selection -- see the
    latter's docstring for why this is duplicated rather than shared.
    """
    now = datetime.now(timezone.utc)
    return now.astimezone(_WARSAW_TZ).date(), now


async def notify_pending_external_invites(session: AsyncSession, bot: Bot, new_player: Player) -> None:
    """Called once, right after a successful registration (see
    bot.handlers.start), with the Player row that registration just bound
    an account to. Never raises on a single failed push -- bot.notifications.push
    already swallows Telegram's own failures, and one inviter with a
    stale/blocked chat must not stop the rest of this player's pending
    rows from being processed.
    """
    pending_rows = await crud.get_pending_external_invites_for_invitee(session, new_player.pzt_id)
    if not pending_rows:
        return

    today, now = _warsaw_today_and_utc_now()
    for pending in pending_rows:
        await _process_one(session, bot, pending, new_player, today, now)


async def _process_one(
    session: AsyncSession,
    bot: Bot,
    pending: PendingExternalInvite,
    new_player: Player,
    today: date,
    now: datetime,
) -> None:
    tournament = pending.tournament
    still_open = tournament is not None and crud.tournament_search_still_open(tournament, today, now)
    inviter_already_matched = (
        await crud.get_matched_invitation(session, pending.inviter_pzt_id, pending.tournament_guid) is not None
    )

    if still_open and not inviter_already_matched:
        inviter_account = await crud.get_account_by_pzt_id(session, pending.inviter_pzt_id)
        if inviter_account is not None:
            lang = inviter_account.lang or DEFAULT_LANG
            await push(
                bot,
                inviter_account.telegram_id,
                gendered(
                    "pending_external_invite.joined",
                    crud.account_code_for_gender(new_player.gender),
                    lang,
                    name=display_name(new_player.full_name),
                ),
                reply_markup=pending_external_invite_offer_keyboard(tournament.guid, new_player.pzt_id, lang),
            )
        else:
            logger.error(
                "pending_external_invite %s has no account for inviter_pzt_id; skipping notification", pending.id
            )

    await crud.delete_pending_external_invite(session, pending.id)
