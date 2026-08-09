"""The Telegram plumbing for CLAUDE.md scenario 2's "offer to send the
real invitation" button (build order step 9, PART 2). The tournament and
the now-registered player are both already resolved -- carried on the
callback itself by bot.keyboards.pending_external_invites -- so this hands
off straight to bot.partner_selection.handle_partner_candidate, the same
resolved-candidate entry point step 6's disambiguation tap uses
(bot.handlers.partner_selection.handle_partner_select), rather than
re-implementing any of its checks.

No state filter: like the three invitation-answer buttons, this arrives
from a push notification, so the inviter may be anywhere -- mid another
flow, or in no state at all.
"""

from __future__ import annotations

from aiogram import Bot, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.i18n import t
from bot.keyboards.navigation import persistent_menu_keyboard
from bot.keyboards.pending_external_invites import SendPendingExternalInviteCallback
from bot.lang import lang_for
from bot.partner_selection import handle_partner_candidate
from db import crud

router = Router(name="pending_external_invites")


@router.callback_query(SendPendingExternalInviteCallback.filter())
async def handle_send_pending_external_invite(
    callback: CallbackQuery,
    callback_data: SendPendingExternalInviteCallback,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
) -> None:
    account = await crud.get_account_by_telegram_id(session, callback.from_user.id)
    lang = lang_for(account)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer()

    if account is None:
        await callback.message.answer(
            t("invitation.no_longer_valid", lang), reply_markup=persistent_menu_keyboard(lang)
        )
        return

    tournament = await crud.get_tournament_by_guid(session, callback_data.tournament_guid)
    candidate = await crud.get_player_by_pzt_id(session, callback_data.invitee_pzt_id)
    if tournament is None or candidate is None:
        # A re-scrape or a data problem between the notification and this
        # tap -- CLAUDE.md, "Never dead-end": say so rather than crash.
        await callback.message.answer(
            t("tournament_search.tournament_gone", lang), reply_markup=persistent_menu_keyboard(lang)
        )
        return

    # start_invitation_send (reached via handle_partner_candidate) reads
    # tournament_guid back out of state, exactly as the typed-name flow
    # left it there when the tournament was first chosen -- this button
    # skips straight past that step, so it must set it here instead.
    await state.update_data(tournament_guid=tournament.guid)
    await handle_partner_candidate(callback.message, state, session, lang, account, tournament, candidate, bot)
