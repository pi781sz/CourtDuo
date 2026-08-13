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

CLAUDE.md step 8.4: the fourth [Menu] button step 8.3 added here is gone --
the persistent reply keyboard (bot.keyboards.navigation.persistent_menu_keyboard)
is always visible below the input box now, so a player who wants to step
away first already has a way out without one.
"""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.i18n import t


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


class CancelInvitationCallback(CallbackData, prefix="iwdrw"):
    invitation_id: int


# CLAUDE.md step 12, "What happens to a confirmed partner": the manual
# escape given to the player left behind when their match's partner
# deletes their CourtDuo account. Two-step, like account deletion itself
# -- ReleaseMatchCallback shows the warning, ReleaseMatchConfirmCallback is
# the only one of the three that actually touches the row.
class ReleaseMatchCallback(CallbackData, prefix="irlse"):
    invitation_id: int


class ReleaseMatchConfirmCallback(CallbackData, prefix="irlsy"):
    invitation_id: int


class ReleaseMatchAbortCallback(CallbackData, prefix="irlsn"):
    invitation_id: int


def confirm_send_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("invitation.confirm_send_button", lang), callback_data=ConfirmSendCallback())
    builder.button(text=t("invitation.confirm_cancel_button", lang), callback_data=CancelSendCallback())
    builder.adjust(1)
    return builder.as_markup()


def invitation_answer_keyboard(invitation_id: int, lang: str) -> InlineKeyboardMarkup:
    """Three buttons, Zatwierdź / Odrzuć / "Nie jadę na ten turniej". A
    player who wants to do something else first can just use the
    persistent reply keyboard (CLAUDE.md step 8.4) -- the invitation stays
    PENDING either way, answerable later from Moje deble, without needing
    a fourth button here to say so."""
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
    builder.adjust(1)
    return builder.as_markup()


def cancel_invitation_keyboard(invitation_id: int, lang: str) -> InlineKeyboardMarkup:
    """CLAUDE.md step 8.6: one button, on the inviter's own still-PENDING
    sent invitation in Moje deble -- the invitee gets invitation_answer_keyboard
    instead, never this one (they answer, they don't cancel)."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=t("invitation.cancel_button", lang),
        callback_data=CancelInvitationCallback(invitation_id=invitation_id),
    )
    builder.adjust(1)
    return builder.as_markup()


def release_match_keyboard(invitation_id: int, lang: str) -> InlineKeyboardMarkup:
    """CLAUDE.md step 12: one button, on the remaining player's own
    "confirm in person" match line in Moje deble -- step one of two."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=t("deletion.release_button", lang),
        callback_data=ReleaseMatchCallback(invitation_id=invitation_id),
    )
    builder.adjust(1)
    return builder.as_markup()


def release_match_confirm_keyboard(invitation_id: int, lang: str) -> InlineKeyboardMarkup:
    """CLAUDE.md step 12: "a confirmation that says clearly this cannot be
    undone" -- step two, the only tap that actually releases the pairing."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=t("deletion.release_confirm_button", lang),
        callback_data=ReleaseMatchConfirmCallback(invitation_id=invitation_id),
    )
    builder.button(
        text=t("deletion.abort_button", lang),
        callback_data=ReleaseMatchAbortCallback(invitation_id=invitation_id),
    )
    builder.adjust(1)
    return builder.as_markup()
