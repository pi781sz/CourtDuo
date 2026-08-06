"""`t(key, lang)` — the only way user-facing text may reach a handler
(CLAUDE.md, "Never hardcode user-facing strings"). Looks up a dotted key
path in locales/<lang>.json, falling back to Polish if the language file
or the key is missing, so locales/en.json can be dropped in later with no
code change (CLAUDE.md, "Language").
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_LOCALES_DIR = Path(__file__).resolve().parent.parent / "locales"
DEFAULT_LANG = "pl"


@lru_cache(maxsize=None)
def _load(lang: str) -> dict:
    path = _LOCALES_DIR / f"{lang}.json"
    if not path.exists():
        path = _LOCALES_DIR / f"{DEFAULT_LANG}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def t(key: str, lang: str = DEFAULT_LANG, **kwargs: object) -> str:
    node: object = _load(lang)
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            if lang != DEFAULT_LANG:
                return t(key, DEFAULT_LANG, **kwargs)
            return key
        node = node[part]
    if not isinstance(node, str):
        return key
    return node.format(**kwargs) if kwargs else node
