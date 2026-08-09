"""Tests for bot.invite_friend (pure link/text building) and
bot.keyboards.invite_friend (the inline keyboard) -- CLAUDE.md step 8.4,
CHANGE 2. No database, no Telegram, no network.
"""

from __future__ import annotations

from bot.invite_friend import share_link, share_text, telegram_share_url, whatsapp_url
from bot.keyboards.invite_friend import share_keyboard


def test_share_link_is_built_from_the_given_username_not_hardcoded():
    assert share_link("courtduo_prod_bot") == "https://t.me/courtduo_prod_bot"
    assert share_link("courtduo_test_bot") == "https://t.me/courtduo_test_bot"


def test_share_text_contains_the_link_and_is_short():
    text = share_text("https://t.me/courtduo_prod_bot", "pl")

    assert "https://t.me/courtduo_prod_bot" in text
    # CLAUDE.md step 8.4: "keep it short enough that a 13-year-old will
    # actually send it."
    assert len(text) < 200


def test_whatsapp_url_is_https_and_carries_the_encoded_text():
    text = "Cześć! Dołącz do CourtDuo: https://t.me/courtduo_prod_bot"
    url = whatsapp_url(text)

    assert url.startswith("https://wa.me/?text=")
    assert " " not in url  # percent-encoded, not a raw space
    assert "ś" not in url  # diacritics are percent-encoded, not literal


def test_telegram_share_url_is_https_and_carries_link_and_text():
    link = "https://t.me/courtduo_prod_bot"
    text = "Cześć! Dołącz do CourtDuo: " + link
    url = telegram_share_url(link, text)

    assert url.startswith("https://t.me/share/url?")
    assert "url=" in url
    assert "text=" in url


def test_neither_share_url_ever_uses_a_non_http_scheme():
    # Telegram's inline URL buttons only accept http(s) (and tg://) --
    # never sms:, tel:, whatsapp: etc. (CLAUDE.md step 8.4, CHANGE 2).
    link = "https://t.me/courtduo_prod_bot"
    text = "share text"

    assert whatsapp_url(text).startswith("https://")
    assert telegram_share_url(link, text).startswith("https://")


def test_share_keyboard_has_two_https_url_buttons_no_sms():
    markup = share_keyboard("https://t.me/courtduo_prod_bot", "share text", "pl")
    buttons = [button for row in markup.inline_keyboard for button in row]

    assert [button.text for button in buttons] == ["WhatsApp", "Telegram"]
    for button in buttons:
        assert button.url is not None
        assert button.url.startswith("https://")
        assert not button.url.startswith("sms:")
