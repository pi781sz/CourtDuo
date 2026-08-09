"""/moje_deble and the "Moje deble" button (CLAUDE.md, "Moje deble" status
view; build order step 8, reworked by step 8.1): one place a player sees
every invitation they have sent or received. Reachable two ways -- the
command and the button every terminal message now carries
(bot.keyboards.navigation.terminal_keyboard) -- both routed through the
same rendering here.

Carries no state filter, like bot.handlers.navigation.handle_find_partner:
the button can follow a pushed notification or a terminal message from any
flow, so the player may be in any FSM state, or none, when they tap it.
Unlike "Znajdź partnera", looking at this view doesn't change anything
about where the player was, so the state is left untouched rather than
reset.

Step 8.1: a pending received invitation can't hang its buttons off the one
summary message any more (there can be several, and they'd need to be
distinguishable) -- so the summary is one message, and every pending
received invitation gets its own follow-up message carrying step 7's own
three-button keyboard (bot.keyboards.invitations.invitation_answer_keyboard)
unchanged, wired to the exact same handlers
(bot.handlers.invitations.handle_accept/handle_reject/handle_not_attending).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from aiogram import Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.i18n import t
from bot.keyboards.invitations import invitation_answer_keyboard
from bot.keyboards.navigation import MojeDebleCallback, find_partner_keyboard
from bot.lang import lang_for
from bot.moje_deble import entry_line, group_by_tournament, pending_received_entries, render_groups
from db import crud
from db.models import Account

logger = logging.getLogger(__name__)

router = Router(name="moje_deble")

_WARSAW_TZ = ZoneInfo("Europe/Warsaw")


def _warsaw_today():
    """Mirrors bot.handlers.tournament_search's helper of the same shape:
    the Europe/Warsaw wall-clock date CLAUDE.md's day-boundary rule counts
    from, never UTC's own date."""
    return datetime.now(timezone.utc).astimezone(_WARSAW_TZ).date()


async def _render_and_send(message: Message, session: AsyncSession, account: Account, lang: str) -> None:
    invitations = await crud.get_invitations_for_player(session, account.pzt_id)
    groups = group_by_tournament(invitations, account.pzt_id, _warsaw_today(), lang)

    if not groups:
        # CLAUDE.md, "EMPTY STATE": "say so plainly and offer 'Znajdź
        # partnera'." Not "Moje deble" too -- that button would point back
        # at this same empty screen.
        await message.answer(t("moje_deble.empty", lang), reply_markup=find_partner_keyboard(lang))
        return

    # CLAUDE.md step 8.1: "The summary list message itself gets [Znajdź
    # partnera]." Not [Moje deble] too, for the same reason as the empty
    # state -- it would only point back at the screen the player is
    # already looking at. Step 8.3, PROBLEM 6: a heading as the first line,
    # so a player scrolling back through the chat knows what this message is.
    heading = t("moje_deble.heading", lang)
    body = render_groups(groups, lang)
    await message.answer(f"{heading}\n\n{body}", reply_markup=find_partner_keyboard(lang))

    # One follow-up message per still-open received invitation, each with
    # its own answer keyboard, since a single summary message can't carry
    # more than one invitation's worth of Zatwierdź/Odrzuć/"Nie jadę"
    # buttons unambiguously.
    for entry in pending_received_entries(groups):
        await message.answer(
            entry_line(entry, lang), reply_markup=invitation_answer_keyboard(entry.invitation_id, lang)
        )


@router.message(Command("moje_deble"))
async def handle_moje_deble_command(message: Message, session: AsyncSession) -> None:
    account = await crud.get_account_by_telegram_id(session, message.from_user.id)
    lang = lang_for(account)
    if account is None:
        # Unlike the button, the command is typeable by anyone at any
        # time, including before /start has ever run. No [Menu] here
        # (CLAUDE.md step 8.2): there is no account yet for either of its
        # two options to act on -- the only real next step is /start.
        await message.answer(t("moje_deble.not_registered", lang))
        return
    await _render_and_send(message, session, account, lang)


@router.callback_query(MojeDebleCallback.filter())
async def handle_moje_deble_button(callback: CallbackQuery, session: AsyncSession) -> None:
    account = await crud.get_account_by_telegram_id(session, callback.from_user.id)
    lang = lang_for(account)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError as exc:
        logger.info("Could not clear Moje deble button: %s", exc)
    await callback.answer()

    if account is None:
        # Every terminal message carrying this button was sent to a
        # registered account, so this can't happen in practice -- but a
        # missing account must not crash the tap.
        logger.warning("Moje deble tapped with no account: telegram_id=%s", callback.from_user.id)
        return
    await _render_and_send(callback.message, session, account, lang)
