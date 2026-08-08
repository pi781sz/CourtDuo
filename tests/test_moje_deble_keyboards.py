"""Tests for the action buttons attached to /moje_deble (CLAUDE.md, "Moje
deble" status view; build order step 8). Pure -- no database, no Telegram.
Invented names/invitation ids only.
"""

from __future__ import annotations

from bot.keyboards.invitations import AcceptInvitationCallback, NotAttendingCallback, RejectInvitationCallback
from bot.keyboards.moje_deble import pending_received_keyboard
from bot.moje_deble import Direction, DebelEntry
from db.models import InvitationState


def _entry(invitation_id: int, name: str) -> DebelEntry:
    return DebelEntry(
        invitation_id=invitation_id,
        tournament_guid="g1",
        state=InvitationState.PENDING,
        direction=Direction.RECEIVED,
        other_full_name=name,
        updated_at=None,
    )


def test_no_entries_means_no_keyboard():
    assert pending_received_keyboard([], "pl") is None


def test_one_entry_gets_three_labelled_buttons_reusing_step_7_callbacks():
    entry = _entry(42, "Testowy Bartosz")

    markup = pending_received_keyboard([entry], "pl")

    buttons = [button for row in markup.inline_keyboard for button in row]
    assert [button.text for button in buttons] == [
        "Zatwierdź — Bartosz Testowy",
        "Odrzuć — Bartosz Testowy",
        "Nie jadę na ten turniej — Bartosz Testowy",
    ]
    assert buttons[0].callback_data == AcceptInvitationCallback(invitation_id=42).pack()
    assert buttons[1].callback_data == RejectInvitationCallback(invitation_id=42).pack()
    assert buttons[2].callback_data == NotAttendingCallback(invitation_id=42).pack()


def test_two_entries_each_get_their_own_labelled_row_of_three():
    entries = [_entry(1, "Testowa Maja"), _entry(2, "Testowy Bartosz")]

    markup = pending_received_keyboard(entries, "pl")

    buttons = [button for row in markup.inline_keyboard for button in row]
    assert len(buttons) == 6
    assert all("Maja Testowa" in button.text for button in buttons[:3])
    assert all("Bartosz Testowy" in button.text for button in buttons[3:])
    assert AcceptInvitationCallback.unpack(buttons[0].callback_data).invitation_id == 1
    assert AcceptInvitationCallback.unpack(buttons[3].callback_data).invitation_id == 2
