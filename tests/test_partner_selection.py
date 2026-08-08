"""Tests for bot.partner_selection's pure name-matching logic (CLAUDE.md,
"Name matching"; build order step 6): both PZT name orders, diacritic
folding, the single-token refusal, the whole-name-not-substring rule, and
the 3-candidate cap. No database -- see tests/test_partner_selection_db.py
for the six pre-invitation checks and the disambiguation queries. Invented
names only.
"""

from __future__ import annotations

from bot.partner_selection import (
    MAX_CANDIDATES,
    MatchOutcome,
    classify_matches,
    matches_full_name,
    name_query_variants,
    split_name_tokens,
)


def test_split_name_tokens_single_token():
    assert split_name_tokens("Jagoda") == ["Jagoda"]


def test_split_name_tokens_two_tokens():
    assert split_name_tokens("Jagoda Szewczyk") == ["Jagoda", "Szewczyk"]


def test_split_name_tokens_collapses_whitespace():
    assert split_name_tokens("  Jagoda   Szewczyk  ") == ["Jagoda", "Szewczyk"]


def test_name_query_variants_two_tokens_offers_both_orders():
    variants = name_query_variants(["Jagoda", "Szewczyk"])
    assert "Jagoda Szewczyk" in variants
    assert "Szewczyk Jagoda" in variants
    assert len(variants) == 2


def test_name_query_variants_three_tokens_offers_only_as_typed():
    # No unambiguous reordering for anything but exactly two tokens.
    variants = name_query_variants(["Anna", "Nowak", "Kowalska"])
    assert variants == ["Anna Nowak Kowalska"]


def test_matches_full_name_accepts_pzt_order_surname_first():
    # PZT stores "Nazwisko Imię" -- a query typed in that order must match.
    assert matches_full_name("Szewczyk Jagoda", ["Szewczyk", "Jagoda"]) is True


def test_matches_full_name_accepts_reversed_first_name_first():
    # A player usually types "Imię Nazwisko" instead.
    assert matches_full_name("Szewczyk Jagoda", ["Jagoda", "Szewczyk"]) is True


def test_matches_full_name_is_case_insensitive():
    assert matches_full_name("Szewczyk Jagoda", ["jagoda", "szewczyk"]) is True
    assert matches_full_name("Szewczyk Jagoda", ["SZEWCZYK", "JAGODA"]) is True


def test_matches_full_name_is_diacritic_insensitive():
    assert matches_full_name("Świątek Iga", ["Iga", "Swiatek"]) is True
    assert matches_full_name("Świątek Iga", ["iga", "swiatek"]) is True


def test_matches_full_name_collapses_extra_whitespace():
    assert matches_full_name("Szewczyk  Jagoda", ["Jagoda", "Szewczyk"]) is True


def test_matches_full_name_requires_whole_name_not_substring():
    # CLAUDE.md, "Name matching": "'Kow' must return nothing."
    assert matches_full_name("Kowalski Jan", ["Kow", "Jan"]) is False
    assert matches_full_name("Kowalski Jan", ["Kowalski"]) is False


def test_matches_full_name_rejects_wrong_name():
    assert matches_full_name("Kowalski Jan", ["Nowak", "Jan"]) is False


def test_classify_matches_empty_is_not_found():
    assert classify_matches([]) is MatchOutcome.NOT_FOUND


def test_classify_matches_single_is_single():
    assert classify_matches(["a"]) is MatchOutcome.SINGLE


def test_classify_matches_two_or_three_is_disambiguate():
    assert classify_matches(["a", "b"]) is MatchOutcome.DISAMBIGUATE
    assert classify_matches(["a", "b", "c"]) is MatchOutcome.DISAMBIGUATE
    assert MAX_CANDIDATES == 3


def test_classify_matches_over_cap_is_too_many():
    assert classify_matches(["a", "b", "c", "d"]) is MatchOutcome.TOO_MANY
