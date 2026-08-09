"""Tests for bot.keyboards.invitations.invitation_answer_keyboard (CLAUDE.md
step 8.3, PROBLEM 3 and PROBLEM 4): four buttons -- Zatwierdź, Odrzuć, Nie
jadę na ten turniej, Menu -- the first three carrying the invitation id, the
fourth a plain [Menu] tap that must not answer the invitation. Pure -- no
database, no Telegram.
"""

from __future__ import annotations

from bot.keyboards.invitations import (
    AcceptInvitationCallback,
    NotAttendingCallback,
    RejectInvitationCallback,
    invitation_answer_keyboard,
)
from bot.keyboards.navigation import MenuCallback


def _buttons(markup):
    return [button for row in markup.inline_keyboard for button in row]


def test_invitation_answer_keyboard_has_four_buttons_with_icons():
    markup = invitation_answer_keyboard(42, "pl")
    buttons = _buttons(markup)

    assert [button.text for button in buttons] == [
        "✅ Zatwierdź",
        "❌ Odrzuć",
        "⛔ Nie jadę na ten turniej",
        "🔵 Menu",
    ]


def test_first_three_buttons_carry_the_invitation_id():
    markup = invitation_answer_keyboard(42, "pl")
    buttons = _buttons(markup)

    assert buttons[0].callback_data == AcceptInvitationCallback(invitation_id=42).pack()
    assert buttons[1].callback_data == RejectInvitationCallback(invitation_id=42).pack()
    assert buttons[2].callback_data == NotAttendingCallback(invitation_id=42).pack()


def test_menu_button_carries_no_invitation_id():
    # CLAUDE.md step 8.3, PROBLEM 3: Menu must not answer the invitation --
    # its callback carries nothing tying it to this invitation at all, so
    # it can only route to bot.handlers.navigation.handle_menu, which never
    # touches an Invitation row.
    markup = invitation_answer_keyboard(42, "pl")
    buttons = _buttons(markup)

    assert buttons[3].callback_data == MenuCallback().pack()
