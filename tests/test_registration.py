"""Tests for bot.registration's pure logic: PZT-id normalization and
gender derivation from ranking-list codes. No database — see
tests/test_registration_db.py for the lookup itself. Invented ids/names
only.
"""

from __future__ import annotations

import pytest

from bot.registration import GenderConflictError, derive_gender, normalize_pzt_id


def test_normalize_pzt_id_strips_leading_and_trailing_whitespace():
    assert normalize_pzt_id("  swd12345  ") == "SWD12345"


def test_normalize_pzt_id_removes_internal_spaces():
    assert normalize_pzt_id("SWD 12345") == "SWD12345"


def test_normalize_pzt_id_uppercases():
    assert normalize_pzt_id("swd12345") == "SWD12345"


def test_normalize_pzt_id_handles_tabs_and_newlines():
    assert normalize_pzt_id("\tswd12345\n") == "SWD12345"


def test_derive_gender_single_code():
    assert derive_gender({"M14"}) == "M"
    assert derive_gender({"W18"}) == "W"


def test_derive_gender_agrees_across_lists_for_a_player_who_plays_up():
    assert derive_gender({"M14", "M16"}) == "M"


def test_derive_gender_raises_on_mixed_genders():
    with pytest.raises(GenderConflictError):
        derive_gender({"M14", "W14"})
