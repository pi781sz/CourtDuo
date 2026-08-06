"""Small display helpers shared by more than one handler/keyboard, kept
out of bot/i18n.py since they decide *which* string to use, not how to
look one up.
"""

from __future__ import annotations

from bot.i18n import t


def format_position(position: int | None, lang: str) -> str:
    if position is None:
        return t("registration.position_unknown", lang)
    return t("registration.position_known", lang, position=position)
