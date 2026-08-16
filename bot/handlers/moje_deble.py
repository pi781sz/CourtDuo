"""/moje_deble and the "Moje deble" button (CLAUDE.md, "Moje deble" status
view; build order step 8, reworked by step 8.1, and by step 8.4). Reachable
three ways -- the command, the age-category screen's inline button, and the
"Moje deble" label on the persistent reply keyboard (CLAUDE.md step 8.4) --
all routed through the same rendering here.

Carries no state filter, like bot.handlers.navigation.handle_find_partner:
the button can follow a pushed notification or arrive mid any flow, so the
player may be in any FSM state, or none, when they tap it. Unlike "Znajdź
partnera", looking at this view doesn't change anything about where the
player was, so the state is left untouched rather than reset.

Step 8.1: a pending received invitation can't hang its buttons off the one
summary message any more (there can be several, and they'd need to be
distinguishable) -- so the summary is one message, and every pending
received invitation gets its own follow-up message carrying step 7's own
three-button keyboard (bot.keyboards.invitations.invitation_answer_keyboard)
unchanged, wired to the exact same handlers
(bot.handlers.invitations.handle_accept/handle_reject/handle_not_attending).

Step 8.6 gave a pending *sent* invitation the same follow-up-message
treatment, with a single "Anuluj zaproszenie" button instead of the three
answers -- only the sender may withdraw it. This PR (no-duplicate-lines)
removed that follow-up message: it only ever existed to have somewhere to
hang the cancel button, and its entry_line() duplicated the line already
sitting in the summary body -- the same bug step 12.1/12.2 had already
fixed once for a stranded match's "Usuń" button. A still-open sent
invitation's line now stays exactly where it already was, in the summary
body, and its cancel button (bot.keyboards.invitations.CancelInvitationCallback,
labelled with the partner's name) rides on the summary message's own
keyboard instead (bot.keyboards.navigation.moje_deble_summary_keyboard).
A still-open *received* invitation keeps its own follow-up message --
three buttons don't fit unambiguously on a shared keyboard -- but is now
left out of the summary body, so its line still only ever appears once.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.handlers.viewers import render_moje_deble_for_viewer
from bot.i18n import all_translations, t
from bot.keyboards.invitations import invitation_answer_keyboard
from bot.keyboards.navigation import (
    MojeDebleCallback,
    moje_deble_summary_keyboard,
    persistent_menu_keyboard,
)
from bot.lang import lang_for
from bot.moje_deble import (
    entry_line,
    group_by_tournament,
    partner_deleted_entries,
    pending_received_entries,
    pending_sent_entries,
    render_groups,
    summary_groups,
)
from core.text import display_name
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
        # CLAUDE.md, "EMPTY STATE": "say so plainly." Step 12.2 removed
        # the inline "Znajdź partnera" button this used to carry -- it
        # duplicated the persistent reply keyboard's own label, already
        # visible below the input box. No reply_markup at all.
        await message.answer(t("moje_deble.empty", lang))
        return

    # Step 8.3, PROBLEM 6: a heading as the first line, so a player
    # scrolling back through the chat knows what this message is.
    # Step 12.1, PROBLEM 4: a stranded match's own "Usuń" button rides
    # along on this same keyboard -- its status line is already in `body`,
    # so it must not be repeated in a follow-up message just to have
    # somewhere to hang the button. This PR (no-duplicate-lines) applies
    # the same fix to a still-open sent invitation's "Anuluj" button
    # instead of its own follow-up message -- see moje_deble_summary_keyboard.
    # Step 12.2: no "Znajdź partnera" button here any more either, for the
    # same reason as the empty state above.
    #
    # summary_groups() also leaves out every still-open *received*
    # invitation -- it gets its own follow-up message below instead, so
    # its line must not also sit in this body (the bug this PR fixes).
    # When that leaves nothing to summarise at all, no summary message is
    # sent -- one below would otherwise carry a heading with nothing
    # under it, or the misleading "you have nothing" wording while the
    # follow-up messages right after it ask the player to act on
    # something.
    summary = summary_groups(groups)
    release_ids = [entry.invitation_id for entry in partner_deleted_entries(groups)]
    cancel_entries = [
        (entry.invitation_id, display_name(entry.other_full_name)) for entry in pending_sent_entries(groups)
    ]
    if summary:
        heading = t("moje_deble.heading", lang)
        body = render_groups(summary, lang)
        await message.answer(
            f"{heading}\n\n{body}",
            reply_markup=moje_deble_summary_keyboard(lang, release_ids, cancel_entries),
        )

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
        # CLAUDE.md step 10: a Telegram account with no CourtDuo account
        # of its own may still be a read-only viewer of one or more
        # players -- checked before falling back to not_registered, so a
        # viewer's /moje_deble opens the read-only screen instead of
        # being told to /start.
        if await render_moje_deble_for_viewer(message, session, message.from_user.id, lang):
            return
        # Unlike the button, the command is typeable by anyone at any
        # time, including before /start has ever run -- so this can be a
        # session's very first message, one /start never reached (CLAUDE.md
        # step 8.5: "Attach it on every message that starts an
        # interaction, not only /start"). There is no account yet for
        # either of the keyboard's other two labels to act on, but showing
        # it here still points the player at /start instead of leaving
        # them with no way forward at all.
        await message.answer(t("moje_deble.not_registered", lang), reply_markup=persistent_menu_keyboard(lang))
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


@router.message(F.text.in_(all_translations("common.moje_deble_button")))
async def handle_moje_deble_button_press(message: Message, session: AsyncSession) -> None:
    """CLAUDE.md step 8.4: the persistent reply keyboard's "Moje deble"
    label. Unlike the command, this can arrive before /start's account
    exists (registration in progress) -- same not_registered fallback as
    the command gets."""
    account = await crud.get_account_by_telegram_id(session, message.from_user.id)
    lang = lang_for(account)
    if account is None:
        # CLAUDE.md step 10: same viewer fallback as the command handler.
        if await render_moje_deble_for_viewer(message, session, message.from_user.id, lang):
            return
        await message.answer(t("moje_deble.not_registered", lang), reply_markup=persistent_menu_keyboard(lang))
        return
    await _render_and_send(message, session, account, lang)
