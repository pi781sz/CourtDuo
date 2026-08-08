"""Tests for the "Znajdź partnera" / "Moje deble" navigation keyboards
(CLAUDE.md, step 7.1, "a way back", extended by build order step 8's
terminal-message audit). Pure -- no database, no Telegram.
"""

from __future__ import annotations

from bot.keyboards.navigation import FindPartnerCallback, MojeDebleCallback, find_partner_keyboard, terminal_keyboard


def test_find_partner_keyboard_has_one_button():
    markup = find_partner_keyboard("pl")

    buttons = [button for row in markup.inline_keyboard for button in row]
    assert len(buttons) == 1
    assert buttons[0].text == "Znajdź partnera"
    assert buttons[0].callback_data == FindPartnerCallback().pack()


def test_terminal_keyboard_has_both_buttons():
    # CLAUDE.md build order step 8: "Every one of them gets both buttons:
    # [Moje deble] [Znajdź partnera]."
    markup = terminal_keyboard("pl")

    buttons = [button for row in markup.inline_keyboard for button in row]
    assert [button.text for button in buttons] == ["Moje deble", "Znajdź partnera"]
    assert buttons[0].callback_data == MojeDebleCallback().pack()
    assert buttons[1].callback_data == FindPartnerCallback().pack()
