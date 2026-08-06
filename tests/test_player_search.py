"""Tests for bot.player_search's name normalization and matching — the
part CLAUDE.md calls out explicitly: case-insensitive, diacritic-blind,
word-order independent. No real player names; these are invented.
"""

from __future__ import annotations

from bot.player_search import matches_query, normalize_name


def test_normalize_name_strips_polish_diacritics_and_casefolds():
    assert normalize_name("Błuś") == "blus"
    assert normalize_name("Michał Świątek") == "michal swiatek"


def test_matches_query_is_case_and_diacritic_insensitive():
    name = normalize_name("Michał Błuś")
    assert matches_query(name, normalize_name("blus").split())
    assert matches_query(name, normalize_name("BLUS").split())


def test_matches_query_ignores_word_order():
    name = normalize_name("Jan Kowalski")
    assert matches_query(name, normalize_name("Kowalski Jan").split())
    assert matches_query(name, normalize_name("Jan Kowalski").split())


def test_matches_query_requires_every_token():
    name = normalize_name("Jan Kowalski")
    assert not matches_query(name, normalize_name("Jan Nowak").split())
