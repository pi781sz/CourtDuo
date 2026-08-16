"""Shared, framework-light helpers for the open support conversation
(CLAUDE.md, "Operations" > "Support"): the two lazy-expiry windows, and
telling a command or a persistent-reply-keyboard-label tap apart from a
genuine free-typed message. Used by bot.middlewares.support_conversation
(the only thing that actually relays a message) and by
bot.handlers.support (the callback buttons around it), so both agree on
exactly the same rules without duplicating them.
"""

from __future__ import annotations

import html
from datetime import timedelta

from bot.i18n import all_translations

# CLAUDE.md, "Operations" > "Support", EXPIRY: evaluated lazily, whenever
# a message arrives -- deliberately no scheduler.
PLAYER_CONVERSATION_TTL = timedelta(minutes=30)
OPERATOR_SESSION_TTL = timedelta(minutes=60)

# The persistent reply keyboard's own labels (bot.keyboards.navigation).
# Tapping any of these closes a player's open conversation silently, same
# as sending a command -- CLAUDE.md, "Operations" > "Support", PLAYER SIDE.
_NAV_LABEL_KEYS = (
    "common.find_partner_button",
    "common.moje_deble_button",
    "common.invite_button",
    "common.podglad_button",
)


def is_command(text: str) -> bool:
    return text.startswith("/")


def is_nav_label(text: str) -> bool:
    return any(text in all_translations(key) for key in _NAV_LABEL_KEYS)


def escape(text: str) -> str:
    """The bot's default parse mode is HTML (bot.main); a player's or
    operator's own free-typed text must never be interpreted as markup.
    quote=False keeps quote characters as-is, since this text never lands
    inside an HTML attribute."""
    return html.escape(text, quote=False)
