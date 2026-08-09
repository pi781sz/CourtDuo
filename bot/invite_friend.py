"""Generic "invite a friend to CourtDuo" share text and link (CLAUDE.md
step 8.4, CHANGE 2). Unattached to any tournament or named player -- that
is build order step 9's pending_external_invites flow, not this one.

Pure text/link building only, no Telegram or DB -- bot.handlers.invite_friend
is the glue that fetches the bot's own username via get_me() and sends the
message. The bot never sees, stores or handles a phone number anywhere in
this flow (CLAUDE.md, non-negotiable rule 2): the recipient is chosen in
the player's own phone/app when they tap Share.
"""

from __future__ import annotations

from urllib.parse import quote

from bot.i18n import t


def share_link(bot_username: str) -> str:
    return f"https://t.me/{bot_username}"


def share_text(link: str, lang: str) -> str:
    return t("invite_friend.share_text", lang, link=link)


def whatsapp_url(text: str) -> str:
    """https://wa.me/?text=... opens WhatsApp's own contact picker with
    the message pre-filled -- the bot never learns who it goes to."""
    return f"https://wa.me/?text={quote(text, safe='')}"


def telegram_share_url(link: str, text: str) -> str:
    """https://t.me/share/url -- Telegram's own forward-to-contact sheet,
    pre-filled the same way WhatsApp's is."""
    return f"https://t.me/share/url?url={quote(link, safe='')}&text={quote(text, safe='')}"
