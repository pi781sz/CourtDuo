"""Tests for the "Znajdź partnera" keyboard (CLAUDE.md, step 7.1, "a way
back"). Pure -- no database, no Telegram.
"""

from __future__ import annotations

from bot.keyboards.navigation import FindPartnerCallback, find_partner_keyboard


def test_find_partner_keyboard_has_one_button():
    markup = find_partner_keyboard("pl")

    buttons = [button for row in markup.inline_keyboard for button in row]
    assert len(buttons) == 1
    assert buttons[0].text == "Znajdź partnera"
    assert buttons[0].callback_data == FindPartnerCallback().pack()
