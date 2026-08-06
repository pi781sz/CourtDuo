"""Forgiving player-name search for registration (see CLAUDE.md,
"Registration flow" step 3): case-insensitive, ignores Polish diacritics,
and doesn't care which word comes first ("Kowalski Jan" finds "Jan
Kowalski").
"""

from __future__ import annotations

import unicodedata

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Player

# unicodedata's NFKD decomposition doesn't touch these — Polish stroke/tail
# letters have no canonical decomposition into base + combining mark, so
# they need an explicit fold before NFKD strips the rest (ó, ą, ę, ć, ń, ź, ż).
_POLISH_FOLD = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")


def normalize_name(text: str) -> str:
    folded = text.translate(_POLISH_FOLD)
    decomposed = unicodedata.normalize("NFKD", folded)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return without_marks.casefold().strip()


def matches_query(normalized_full_name: str, query_tokens: list[str]) -> bool:
    name_tokens = normalized_full_name.split()
    return all(any(token in name_token for name_token in name_tokens) for token in query_tokens)


async def search_players_by_name(session: AsyncSession, query: str, limit: int = 10) -> list[Player]:
    """Filters the whole `players` table in Python rather than in SQL,
    since Postgres ILIKE can't fold Polish diacritics without the
    `unaccent` extension. Fine at PZT junior-roster scale; revisit with a
    normalized, indexed column if this table grows much larger.
    """
    query_tokens = [token for token in normalize_name(query).split() if token]
    if not query_tokens:
        return []

    result = await session.execute(select(Player))
    candidates = result.scalars().all()
    matches = [p for p in candidates if matches_query(normalize_name(p.full_name), query_tokens)]
    matches.sort(key=lambda p: p.full_name)
    return matches[:limit]
