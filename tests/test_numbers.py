"""Number parsing is where silent, confident, wrong answers come from.

A deposit misread as 192 instead of 192000 does not raise; it produces a
well-formatted percentile that is completely wrong. These tests are therefore
heavier than the module's size suggests.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from kwys.extract.numbers import (
    CRORE,
    LAKH,
    duplication_disagrees,
    parse_duplicated,
    parse_indian_digits,
    words_to_number,
)


@pytest.mark.parametrize(
    "phrase,expected",
    [
        ("one", 1), ("eleven", 11), ("nineteen", 19),
        ("twenty", 20), ("thirty two thousand", 32_000),
        ("one lakh", LAKH), ("one lakh ninety two thousand", 192_000),
        ("two crore fifty lakh", 2 * CRORE + 50 * LAKH),
        ("Rupees One Lakh Ninety Two Thousand only", 192_000),
        ("one hundred and eighty", 180),
        ("five lacs", 5 * LAKH),
    ],
)
def test_words_to_number(phrase, expected):
    assert words_to_number(phrase) == expected


def test_words_to_number_rejects_non_numbers():
    assert words_to_number("the lessee shall pay") is None
    assert words_to_number("") is None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("32,000", 32_000),
        ("1,92,000", 192_000),        # Indian grouping
        ("1,92,00,000", 1_92_00_000),
        ("1,92,000/-", 192_000),      # trailing rupee dash
        ("10.5", 10.5),
        ("500", 500),
    ],
)
def test_parse_indian_digits(text, expected):
    assert parse_indian_digits(text) == expected


def test_parse_indian_digits_rejects_junk():
    assert parse_indian_digits("3%") is None
    assert parse_indian_digits("six months") is None


def test_duplicated_prefers_digits():
    assert parse_duplicated("six (6) months")[0] == 6
    assert parse_duplicated("one hundred and eighty (180) days")[0] == 180


def test_contradiction_detected():
    """A document that writes six in words and 7 in figures is ambiguous on its
    face, and the user must be told rather than handed our first guess."""
    assert duplication_disagrees("six (7) months") == (6.0, 7.0)
    assert duplication_disagrees("six (6) months") is None


@given(st.integers(min_value=1, max_value=99_99_99_999))
def test_indian_grouping_roundtrip(n: int):
    """Any integer, formatted the Indian way, must parse back to itself."""
    s = str(n)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        formatted = ",".join([*groups, tail])
    else:
        formatted = s
    assert parse_indian_digits(formatted) == n


@given(st.integers(min_value=0, max_value=500))
def test_duplicated_never_disagrees_with_itself(n: int):
    word_free = f"a period of ({n}) months"
    parsed = parse_duplicated(word_free)
    if parsed is not None:
        assert parsed[0] == n
