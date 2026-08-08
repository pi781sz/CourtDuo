"""The action buttons attached to /moje_deble (CLAUDE.md, "Moje deble"
status view; build order step 8): a still-pending received invitation must
be answerable straight from this view, "reusing step 7's handlers" --
these buttons carry the exact same callback classes
(bot.keyboards.invitations.AcceptInvitationCallback and friends) that the
originally pushed invitation used, so bot.handlers.invitations' existing
handle_accept/handle_reject/handle_not_attending answer them unchanged.
Nothing new is registered for them.

Unlike the single pushed invitation (bot.keyboards.invitations.
invitation_answer_keyboard), this view can show more than one pending
received invitation at once, so every button is labelled with who it
answers.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.i18n import t
from bot.keyboards.invitations import AcceptInvitationCallback, NotAttendingCallback, RejectInvitationCallback
from bot.moje_deble import DebelEntry
from core.text import display_name


def pending_received_keyboard(entries: list[DebelEntry], lang: str) -> InlineKeyboardMarkup | None:
    """None when there is nothing pending to answer -- a message with no
    action to take gets no keyboard from this function (the empty state
    and the matched-only case use bot.keyboards.navigation instead).
    """
    if not entries:
        return None
    builder = InlineKeyboardBuilder()
    for entry in entries:
        name = display_name(entry.other_full_name)
        builder.button(
            text=f'{t("invitation.accept_button", lang)} — {name}',
            callback_data=AcceptInvitationCallback(invitation_id=entry.invitation_id),
        )
        builder.button(
            text=f'{t("invitation.reject_button", lang)} — {name}',
            callback_data=RejectInvitationCallback(invitation_id=entry.invitation_id),
        )
        builder.button(
            text=f'{t("invitation.not_attending_button", lang)} — {name}',
            callback_data=NotAttendingCallback(invitation_id=entry.invitation_id),
        )
    builder.adjust(1)
    return builder.as_markup()
