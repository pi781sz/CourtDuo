"""The confirmation screen (CLAUDE.md, "Invitation engine"; build order
step 7). start_invitation_send() is the single entry point step 6
(bot.partner_selection) calls once a partner has been resolved and every
pre-invitation check has passed.

Nothing is written here. CLAUDE.md requires the "po akceptacji nie można
zmienić partnera" warning to be shown *before* the player confirms — a
confirmed match cannot be cancelled by either side — so this module only
shows what is about to happen and hands the tap to
bot.handlers.invitations, which runs the send transaction in
bot.invitation_engine.

The transaction re-checks everything this screen assumed. The gap between
seeing this screen and tapping Wyślij zaproszenie is unbounded: the player
can leave the chat open for an hour, and the named partner can be matched
by somebody else in the meantime.
"""

from __future__ import annotations

from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.i18n import t
from bot.invitation_text import confirmation_text
from bot.keyboards.invitations import confirm_send_keyboard
from bot.keyboards.navigation import terminal_keyboard
from bot.states import InvitationSend
from bot.tournament_search import label_for_tournament
from core.text import display_name
from db import crud
from db.models import Account, Player, Tournament


async def start_invitation_send(
    message: Message,
    state: FSMContext,
    lang: str,
    session: AsyncSession,
    account: Account,
    tournament: Tournament,
    invitee: Player,
) -> None:
    invitee_account = await crud.get_account_by_pzt_id(session, invitee.pzt_id)
    if invitee_account is None:
        # The named player is on PZT's roster but doesn't use CourtDuo, so
        # there is nowhere to deliver an invitation. CLAUDE.md scenario 2
        # (share text via the player's own phone contacts) is build order
        # step 9; until then, say so and let them type another name rather
        # than show a confirmation screen that cannot lead anywhere. The
        # player stays in PartnerSelection.waiting_name.
        await message.answer(
            t("invitation.invitee_not_on_courtduo", lang, name=display_name(invitee.full_name)),
            reply_markup=terminal_keyboard(lang),
        )
        return

    await state.update_data(partner_pzt_id=invitee.pzt_id)
    await message.answer(
        confirmation_text(invitee.full_name, label_for_tournament(tournament), lang),
        reply_markup=confirm_send_keyboard(lang),
    )
    await state.set_state(InvitationSend.waiting_confirmation)
