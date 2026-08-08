"""Text helpers shared by scrapers and bot code.

fold_diacritics exists because PZT itself is inconsistent about
diacritics in place names — one live tournament writes "Zielona Gora" in
its "Miejsce turnieju" row and "Zielona Góra" in its "Miejsce rozgrywek"
row for the same event. Step 5 (CLAUDE.md, "Tournament selection") uses
this to match a typed place against venue_city/wojewodztwo regardless of
how the player or PZT spelled it.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_DIACRITIC_MAP = str.maketrans(
    {
        "ą": "a",
        "ć": "c",
        "ę": "e",
        "ł": "l",
        "ń": "n",
        "ó": "o",
        "ś": "s",
        "ź": "z",
        "ż": "z",
    }
)


def fold_diacritics(s: str) -> str:
    """Lowercases and strips Polish diacritics: ą->a ć->c ę->e ł->l ń->n
    ó->o ś->s ź->z ż->z. "Uniejów", "UNIEJOW" and "uniejow" all fold to
    "uniejow"."""
    return s.lower().translate(_DIACRITIC_MAP)


def first_name(full_name: str) -> str:
    """Returns the player's first name for display, given PZT's "Nazwisko
    Imię" (surname first) ordering. "Szewczyk Jagoda" -> "Jagoda".

    Display only -- accounts.full_name keeps the full stored name, and
    invitation-facing code must keep using full_name so the invitee knows
    exactly who is asking (CLAUDE.md, "Step 5.5 -- Friendlier greeting")."""
    tokens = full_name.split()
    if len(tokens) <= 1:
        return full_name
    if len(tokens) > 2:
        logger.debug("first_name: unexpected token count %d for %r", len(tokens), full_name)
    return tokens[-1]
