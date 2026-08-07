"""Tests for core.text.fold_diacritics.

Step 5 (CLAUDE.md, "Tournament selection") uses this to match a typed
place against venue_city/wojewodztwo regardless of spelling -- PZT itself
is inconsistent about diacritics (one live tournament writes "Zielona
Gora" in one row and "Zielona Góra" in another).
"""

from __future__ import annotations

from core.text import fold_diacritics


def test_uniejow_variants_fold_equal():
    assert fold_diacritics("Uniejów") == fold_diacritics("UNIEJOW") == fold_diacritics("uniejow")


def test_zielona_gora_variants_fold_equal():
    assert fold_diacritics("Zielona Góra") == fold_diacritics("Zielona Gora") == "zielona gora"
