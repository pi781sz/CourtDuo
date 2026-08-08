"""Tests for core.text.fold_diacritics, core.text.first_name and
core.text.display_name.

Step 5 (CLAUDE.md, "Tournament selection") uses fold_diacritics to match a
typed place against venue_city/wojewodztwo regardless of spelling -- PZT
itself is inconsistent about diacritics (one live tournament writes
"Zielona Gora" in one row and "Zielona Góra" in another).

Step 5.5 adds first_name: PZT stores names "Nazwisko Imię" (surname
first), so the player's own welcome greeting needs the first given name.

Step 7.1 adds display_name: every other user-facing display of a name
must show "Imię Nazwisko" instead of PZT's stored "Nazwisko Imię", and
corrects first_name, which used to return the LAST token instead of the
first given name (the second token).
"""

from __future__ import annotations

from core.text import display_name, first_name, fold_diacritics


def test_uniejow_variants_fold_equal():
    assert fold_diacritics("Uniejów") == fold_diacritics("UNIEJOW") == fold_diacritics("uniejow")


def test_zielona_gora_variants_fold_equal():
    assert fold_diacritics("Zielona Góra") == fold_diacritics("Zielona Gora") == "zielona gora"


def test_first_name_two_tokens_returns_second():
    assert first_name("Szewczyk Jagoda") == "Jagoda"


def test_first_name_hyphenated_surname_is_two_tokens():
    assert first_name("Nowak-Kowalska Anna") == "Anna"


def test_first_name_more_than_two_tokens_returns_the_second_not_the_last():
    # The first token is the surname, so the first given name is the
    # SECOND token, not the last.
    assert first_name("Kowalski Jan Piotr") == "Jan"


def test_first_name_single_token_returned_unchanged():
    assert first_name("Madonna") == "Madonna"


def test_first_name_empty_string_returned_unchanged():
    assert first_name("") == ""


def test_first_name_strips_surrounding_and_collapses_internal_whitespace():
    assert first_name("  Szewczyk   Jagoda  ") == "Jagoda"


# --- display_name ---------------------------------------------------------------


def test_display_name_swaps_surname_and_given_name():
    assert display_name("Szewczyk Jagoda") == "Jagoda Szewczyk"


def test_display_name_keeps_hyphenated_surname_intact():
    assert display_name("Nowak-Kowalska Anna") == "Anna Nowak-Kowalska"


def test_display_name_moves_surname_to_the_end_with_multiple_given_names():
    assert display_name("Kowalski Jan Piotr") == "Jan Piotr Kowalski"


def test_display_name_single_token_returned_unchanged():
    assert display_name("Madonna") == "Madonna"


def test_display_name_empty_string_returned_unchanged():
    assert display_name("") == ""


def test_display_name_strips_surrounding_and_collapses_internal_whitespace():
    assert display_name("  Szewczyk   Jagoda  ") == "Jagoda Szewczyk"


def test_display_name_never_raises_on_odd_input():
    for value in ("   ", "\t\n", "Ó", "a b c d e"):
        display_name(value)
