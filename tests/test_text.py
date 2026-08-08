"""Tests for core.text.fold_diacritics and core.text.first_name.

Step 5 (CLAUDE.md, "Tournament selection") uses fold_diacritics to match a
typed place against venue_city/wojewodztwo regardless of spelling -- PZT
itself is inconsistent about diacritics (one live tournament writes
"Zielona Gora" in one row and "Zielona Góra" in another).

Step 5.5 adds first_name: PZT stores names "Nazwisko Imię" (surname
first), so the player's own welcome greeting needs the last token.
"""

from __future__ import annotations

from core.text import first_name, fold_diacritics


def test_uniejow_variants_fold_equal():
    assert fold_diacritics("Uniejów") == fold_diacritics("UNIEJOW") == fold_diacritics("uniejow")


def test_zielona_gora_variants_fold_equal():
    assert fold_diacritics("Zielona Góra") == fold_diacritics("Zielona Gora") == "zielona gora"


def test_first_name_two_tokens_returns_last():
    assert first_name("Szewczyk Jagoda") == "Jagoda"


def test_first_name_hyphenated_surname_is_two_tokens():
    assert first_name("Nowak-Kowalska Anna") == "Anna"


def test_first_name_more_than_two_tokens_returns_last():
    assert first_name("Kowalski Jan Piotr") == "Piotr"


def test_first_name_single_token_returned_unchanged():
    assert first_name("Madonna") == "Madonna"


def test_first_name_empty_string_returned_unchanged():
    assert first_name("") == ""


def test_first_name_strips_surrounding_and_collapses_internal_whitespace():
    assert first_name("  Szewczyk   Jagoda  ") == "Jagoda"
