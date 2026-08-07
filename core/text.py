"""Text helpers shared by scrapers and bot code.

fold_diacritics exists because PZT itself is inconsistent about
diacritics in place names — one live tournament writes "Zielona Gora" in
its "Miejsce turnieju" row and "Zielona Góra" in its "Miejsce rozgrywek"
row for the same event. Step 5 (CLAUDE.md, "Tournament selection") uses
this to match a typed place against venue_city/wojewodztwo regardless of
how the player or PZT spelled it.
"""

from __future__ import annotations

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
