"""Tests for the [Menu] / "Znajdź partnera" / "Moje deble" navigation
keyboards (CLAUDE.md, step 7.1, "a way back", reworked by build order step
8.2 into a single entry point). Pure -- no database, no Telegram.
"""

from __future__ import annotations

from bot.keyboards.navigation import (
    FindPartnerCallback,
    MenuCallback,
    MojeDebleCallback,
    find_partner_keyboard,
    menu_keyboard,
    terminal_keyboard,
)


def test_find_partner_keyboard_has_one_button():
    markup = find_partner_keyboard("pl")

    buttons = [button for row in markup.inline_keyboard for button in row]
    assert len(buttons) == 1
    assert buttons[0].text == "Znajdź partnera"
    assert buttons[0].callback_data == FindPartnerCallback().pack()


def test_terminal_keyboard_has_one_menu_button():
    # CLAUDE.md build order step 8.2: "terminal messages get ONE button:
    # [Menu]."
    markup = terminal_keyboard("pl")

    buttons = [button for row in markup.inline_keyboard for button in row]
    assert [button.text for button in buttons] == ["🔵 Menu"]
    assert buttons[0].callback_data == MenuCallback().pack()


def test_menu_keyboard_offers_both_options():
    markup = menu_keyboard("pl")

    buttons = [button for row in markup.inline_keyboard for button in row]
    assert [button.text for button in buttons] == ["Znajdź partnera", "Moje deble"]
    assert buttons[0].callback_data == FindPartnerCallback().pack()
    assert buttons[1].callback_data == MojeDebleCallback().pack()
