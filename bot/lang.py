"""Where the interface language for a chat comes from.

There is no account yet at /start's first message, so DEFAULT_LANG (read
from the DEFAULT_LANG env var, "pl" per .env.example) is the only option
there. Once an Account row exists, its `lang` column is authoritative —
this is the seam locales/en.json plugs into later without touching
handlers (CLAUDE.md, "locales/en.json will be added later; the structure
must support it from day one").
"""

from __future__ import annotations

import os

from db.models import Account

DEFAULT_LANG = os.environ.get("DEFAULT_LANG", "pl")


def lang_for(account: Account | None) -> str:
    return account.lang if account is not None else DEFAULT_LANG
