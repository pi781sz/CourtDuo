"""Tests for the persistent reply keyboard and the "Znajdź partnera" inline
button (CLAUDE.md step 8.4: the inline [Menu] button build order step 8.2
introduced is gone, replaced by a reply keyboard attached once at the
start of a session). Pure -- no database, no Telegram.
"""

from __future__ import annotations

from bot.keyboards.invitations import ReleaseMatchCallback
from bot.keyboards.navigation import (
    FindPartnerCallback,
    MojeDebleCallback,
    find_partner_keyboard,
    invitation_sent_keyboard,
    moje_deble_summary_keyboard,
    persistent_menu_keyboard,
    viewer_menu_keyboard,
)


def test_find_partner_keyboard_has_one_button():
    markup = find_partner_keyboard("pl")

    buttons = [button for row in markup.inline_keyboard for button in row]
    assert len(buttons) == 1
    assert buttons[0].text == "Znajdź partnera"
    assert buttons[0].callback_data == FindPartnerCallback().pack()


def test_persistent_menu_keyboard_layout_and_labels():
    # CLAUDE.md step 8.4: [Znajdź partnera] alone on its own row, [Moje
    # deble] and [Zaproś na CourtDuo] sharing the next.
    markup = persistent_menu_keyboard("pl")

    rows = [[button.text for button in row] for row in markup.keyboard]
    assert rows == [["Znajdź partnera"], ["Moje deble", "Zaproś na CourtDuo"]]


def test_persistent_menu_keyboard_is_resizable_and_persistent():
    markup = persistent_menu_keyboard("pl")

    assert markup.resize_keyboard is True
    assert markup.is_persistent is True


def test_persistent_menu_keyboard_gains_a_fourth_row_when_podglad_is_shown():
    # CLAUDE.md step 10.2, PROBLEM 4: a fourth row, [Podgląd konta], only
    # for accounts entitlements.can_use_viewers allows -- the caller
    # decides, this keyboard just lays it out when told to.
    markup = persistent_menu_keyboard("pl", show_podglad=True)

    rows = [[button.text for button in row] for row in markup.keyboard]
    assert rows == [["Znajdź partnera"], ["Moje deble", "Zaproś na CourtDuo"], ["Podgląd konta"]]
    assert markup.resize_keyboard is True
    assert markup.is_persistent is True


def test_persistent_menu_keyboard_defaults_to_no_podglad_row():
    markup = persistent_menu_keyboard("pl", show_podglad=False)

    rows = [[button.text for button in row] for row in markup.keyboard]
    assert rows == [["Znajdź partnera"], ["Moje deble", "Zaproś na CourtDuo"]]


def test_invitation_sent_keyboard_has_one_moje_deble_button():
    # CLAUDE.md step 8.7: belt-and-braces for "Zaproszenie zostało
    # wysłane" -- an inline button, so it can't be collapsed the way the
    # persistent reply keyboard can be.
    markup = invitation_sent_keyboard("pl")

    buttons = [button for row in markup.inline_keyboard for button in row]
    assert len(buttons) == 1
    assert buttons[0].text == "Moje deble"
    assert buttons[0].callback_data == MojeDebleCallback().pack()


def test_viewer_menu_keyboard_has_only_moje_deble_no_find_partner_no_invite():
    # CLAUDE.md step 10.1: a viewer-only Telegram account must never see
    # Znajdź partnera or Zaproś na CourtDuo -- neither flow it can complete.
    markup = viewer_menu_keyboard("pl")

    rows = [[button.text for button in row] for row in markup.keyboard]
    assert rows == [["Moje deble"]]
    assert markup.resize_keyboard is True
    assert markup.is_persistent is True


def test_moje_deble_summary_keyboard_with_no_stranded_matches_is_just_find_partner():
    # CLAUDE.md step 12.1, PROBLEM 4: no extra buttons when nothing is
    # stranded -- same single button as before.
    markup = moje_deble_summary_keyboard("pl")

    buttons = [button for row in markup.inline_keyboard for button in row]
    assert [button.text for button in buttons] == ["Znajdź partnera"]
    assert buttons[0].callback_data == FindPartnerCallback().pack()


def test_moje_deble_summary_keyboard_adds_one_usun_button_per_stranded_match():
    # CLAUDE.md step 12.1, PROBLEM 4: the stranded match's own "Usuń"
    # button rides on the summary's own keyboard instead of a repeated
    # follow-up message -- one per stranded match, each carrying its own
    # invitation id.
    markup = moje_deble_summary_keyboard("pl", [101, 202])

    buttons = [button for row in markup.inline_keyboard for button in row]
    assert [button.text for button in buttons] == ["Znajdź partnera", "Usuń", "Usuń"]
    assert buttons[1].callback_data == ReleaseMatchCallback(invitation_id=101).pack()
    assert buttons[2].callback_data == ReleaseMatchCallback(invitation_id=202).pack()


def test_find_partner_keyboard_and_moje_deble_callback_prefixes_unchanged():
    # Still used elsewhere (find_partner_keyboard/moje_deble_summary_keyboard
    # above, invitation_sent_keyboard, and bot.handlers.moje_deble's own
    # inline callback route).
    assert FindPartnerCallback.__prefix__ == "fpart"
    assert MojeDebleCallback.__prefix__ == "mdeble"
