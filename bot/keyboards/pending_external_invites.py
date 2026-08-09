"""Inline keyboard for CLAUDE.md scenario 2's "they joined" notification
(build order step 9, PART 2): one button offering to send the real
invitation now that the named player has an account. The tournament and
the resolved player are carried on the callback itself, so tapping it
never asks the inviter to type the name again -- bot.handlers.pending_external_invites
hands both straight to bot.partner_selection.handle_partner_candidate,
step 6's own resolved-candidate entry point.
"""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.i18n import t


class SendPendingExternalInviteCallback(CallbackData, prefix="pesend"):
    tournament_guid: str
    invitee_pzt_id: str


def pending_external_invite_offer_keyboard(
    tournament_guid: str, invitee_pzt_id: str, lang: str
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=t("pending_external_invite.send_button", lang),
        callback_data=SendPendingExternalInviteCallback(
            tournament_guid=tournament_guid, invitee_pzt_id=invitee_pzt_id
        ),
    )
    builder.adjust(1)
    return builder.as_markup()
