"""Tests for bot.keyboards.invitations.invitation_answer_keyboard (CLAUDE.md
step 8.3, PROBLEM 4, and step 8.4, CHANGE 3/CHANGE 1): three buttons --
Zatwierdź, Odrzuć, Nie jadę na ten turniej -- with no leading emoji and no
fourth [Menu] button (the persistent reply keyboard replaces it). Pure --
no database, no Telegram.
"""

from __future__ import annotations

from bot.keyboards.invitations import (
    AcceptInvitationCallback,
    CancelInvitationCallback,
    NotAttendingCallback,
    RejectInvitationCallback,
    cancel_invitation_keyboard,
    invitation_answer_keyboard,
)


def _buttons(markup):
    return [button for row in markup.inline_keyboard for button in row]


def test_invitation_answer_keyboard_has_three_buttons_no_emoji():
    markup = invitation_answer_keyboard(42, "pl")
    buttons = _buttons(markup)

    assert [button.text for button in buttons] == [
        "Zatwierdź",
        "Odrzuć",
        "Nie jadę na ten turniej",
    ]


def test_all_three_buttons_carry_the_invitation_id():
    markup = invitation_answer_keyboard(42, "pl")
    buttons = _buttons(markup)

    assert buttons[0].callback_data == AcceptInvitationCallback(invitation_id=42).pack()
    assert buttons[1].callback_data == RejectInvitationCallback(invitation_id=42).pack()
    assert buttons[2].callback_data == NotAttendingCallback(invitation_id=42).pack()


# --- cancel_invitation_keyboard (CLAUDE.md step 8.6) ----------------------------


def test_cancel_invitation_keyboard_has_one_plain_text_button():
    markup = cancel_invitation_keyboard(42, "pl")
    buttons = _buttons(markup)

    assert [button.text for button in buttons] == ["Anuluj zaproszenie"]


def test_cancel_invitation_keyboard_button_carries_the_invitation_id():
    markup = cancel_invitation_keyboard(42, "pl")
    buttons = _buttons(markup)

    assert buttons[0].callback_data == CancelInvitationCallback(invitation_id=42).pack()
