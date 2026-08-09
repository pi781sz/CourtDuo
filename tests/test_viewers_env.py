"""CLAUDE.md rule 4 ("Never commit scraped player data") applied to step
10: VIEWER_ALLOWLIST_PZT_IDS must ship empty in .env.example -- a real PZT
id would identify a real child in a public repository. Static checks
only, no database.
"""

from __future__ import annotations

import pathlib
import re

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_env_example_documents_the_viewer_allowlist_var_with_an_empty_value():
    text = (_REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    match = re.search(r"^VIEWER_ALLOWLIST_PZT_IDS=(.*)$", text, re.MULTILINE)
    assert match is not None, "VIEWER_ALLOWLIST_PZT_IDS is not documented in .env.example"
    assert match.group(1).strip() == "", "VIEWER_ALLOWLIST_PZT_IDS must ship with an empty value"


def test_entitlements_never_hardcodes_an_allowlist_value():
    # can_use_viewers must read the allowlist from the environment only --
    # no literal PZT id fallback or default baked into the source.
    text = (_REPO_ROOT / "entitlements.py").read_text(encoding="utf-8")
    assert 'os.environ.get("VIEWER_ALLOWLIST_PZT_IDS"' in text
