"""Inline keyboards for the invitation flow (CLAUDE.md, "Invitation
engine"; build order step 7).

Two keyboards, five buttons, no text input anywhere: the inviter confirms
or cancels, and the invitee answers with exactly one of Zatwierdź, Odrzuć
and "Nie jadę na ten turniej" (CLAUDE.md, non-negotiable rule 1 — every
interaction is a button and a pre-defined message).

One callback class per button, matching bot.keyboards.tournament_search.
The three answer buttons carry the invitation id, which is all
bot.handlers.invitations needs to find the row; the confirmation buttons
carry nothing, since the tournament and the chosen partner are already in
FSM state. Callback payloads come from the client and cannot be trusted:
the handlers re-check that the tapper really is the invitation's invitee.
"""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.i18n import t
from bot.keyboards.navigation import MenuCallback


class ConfirmSendCallback(CallbackData, prefix="isend"):
    pass


class CancelSendCallback(CallbackData, prefix="icncl"):
    pass


class AcceptInvitationCallback(CallbackData, prefix="iacc"):
    invitation_id: int


class RejectInvitationCallback(CallbackData, prefix="irej"):
    invitation_id: int


class NotAttendingCallback(CallbackData, prefix="inat"):
    invitation_id: int


def confirm_send_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("invitation.confirm_send_button", lang), callback_data=ConfirmSendCallback())
    builder.button(text=t("invitation.confirm_cancel_button", lang), callback_data=CancelSendCallback())
    builder.adjust(1)
    return builder.as_markup()


def invitation_answer_keyboard(invitation_id: int, lang: str) -> InlineKeyboardMarkup:
    """CLAUDE.md step 8.3, PROBLEM 3: a fourth button, Menu, alongside the
    three answers -- a player who wants to do something else first has a
    way out. Tapping it does not answer the invitation: it stays PENDING,
    answerable later from Moje deble (bot.handlers.navigation.handle_menu
    handles the tap; it carries no invitation_id and touches no invitation
    row)."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=t("invitation.accept_button", lang),
        callback_data=AcceptInvitationCallback(invitation_id=invitation_id),
    )
    builder.button(
        text=t("invitation.reject_button", lang),
        callback_data=RejectInvitationCallback(invitation_id=invitation_id),
    )
    builder.button(
        text=t("invitation.not_attending_button", lang),
        callback_data=NotAttendingCallback(invitation_id=invitation_id),
    )
    builder.button(text=t("common.menu_button", lang), callback_data=MenuCallback())
    builder.adjust(1)
    return builder.as_markup()
