"""Tests for bot.keyboards.viewers (CLAUDE.md, "Identity", step 10). Pure
-- no database, no Telegram. AccountViewer/Account rows here are plain
in-memory objects, never flushed to a session -- these keyboards only
ever read `.id`/`.account_id`/`.full_name` off them.
"""

from __future__ import annotations

from bot.keyboards.viewers import (
    ViewerChooseAccountCallback,
    ViewerCreateInviteCallback,
    ViewerRevokeCallback,
    podglad_menu_keyboard,
    viewer_chooser_keyboard,
    viewer_invite_share_keyboard,
)
from db.models import Account, AccountViewer


def _buttons(markup):
    return [button for row in markup.inline_keyboard for button in row]


def _viewer(viewer_id: int) -> AccountViewer:
    return AccountViewer(id=viewer_id, account_id=1, viewer_telegram_id=1000 + viewer_id)


def test_podglad_menu_lists_one_revoke_button_per_viewer_plus_a_create_button():
    markup = podglad_menu_keyboard([_viewer(1), _viewer(2)], "pl")
    buttons = _buttons(markup)

    assert [button.text for button in buttons] == [
        "Odwołaj dostęp #1",
        "Odwołaj dostęp #2",
        "Utwórz zaproszenie do podglądu",
    ]
    assert buttons[-1].callback_data == ViewerCreateInviteCallback().pack()


def test_podglad_menu_hides_the_create_button_at_the_three_viewer_cap():
    markup = podglad_menu_keyboard([_viewer(1), _viewer(2), _viewer(3)], "pl")
    buttons = _buttons(markup)

    assert [button.text for button in buttons] == ["Odwołaj dostęp #1", "Odwołaj dostęp #2", "Odwołaj dostęp #3"]


def test_revoke_buttons_carry_the_viewer_rows_own_id_not_the_display_index():
    markup = podglad_menu_keyboard([_viewer(42)], "pl")
    button = _buttons(markup)[0]

    assert button.callback_data == ViewerRevokeCallback(viewer_id=42).pack()


def test_podglad_menu_with_no_viewers_is_just_the_create_button():
    markup = podglad_menu_keyboard([], "pl")
    buttons = _buttons(markup)

    assert [button.text for button in buttons] == ["Utwórz zaproszenie do podglądu"]


def test_viewer_invite_share_keyboard_has_one_telegram_button_no_whatsapp():
    # CLAUDE.md step 10: the token is for one specific person the player
    # picks themselves via Telegram's own contact picker -- no WhatsApp
    # button here, unlike bot.keyboards.invite_friend.share_keyboard.
    markup = viewer_invite_share_keyboard("https://t.me/courtduo_bot?start=tok123", "pl")
    buttons = _buttons(markup)

    assert [button.text for button in buttons] == ["Telegram"]
    assert buttons[0].url is not None
    assert buttons[0].url.startswith("https://t.me/share/url?")


def test_viewer_chooser_keyboard_shows_reordered_display_names():
    accounts = [
        Account(id=1, telegram_id=11, pzt_id="A1", full_name="Szewczyk Jagoda", gender="W"),
        Account(id=2, telegram_id=12, pzt_id="A2", full_name="Nowak Adam", gender="M"),
    ]
    markup = viewer_chooser_keyboard(accounts, "pl")
    buttons = _buttons(markup)

    assert [button.text for button in buttons] == ["Jagoda Szewczyk", "Adam Nowak"]
    assert buttons[0].callback_data == ViewerChooseAccountCallback(account_id=1).pack()
    assert buttons[1].callback_data == ViewerChooseAccountCallback(account_id=2).pack()


def test_callback_prefixes():
    assert ViewerCreateInviteCallback.__prefix__ == "vwmk"
    assert ViewerRevokeCallback.__prefix__ == "vwrv"
    assert ViewerChooseAccountCallback.__prefix__ == "vwchs"
