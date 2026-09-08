from __future__ import annotations

from pathlib import Path

import pytest

from kwys.segment.numbering import looks_like_heading, match_number
from kwys.segment.segmenter import segment_file

FIXTURE = Path(__file__).parent / "fixtures" / "sample_lease.pdf"


@pytest.mark.parametrize(
    "line,scheme,label,depth",
    [
        ("4. TERMINATION", "integer", "4", 0),
        ("4.2 The Tenant shall pay", "decimal", "4.2", 1),
        ("4.2.1 Sub-provision", "decimal", "4.2.1", 2),
        ("(a) subletting is prohibited", "alpha_paren", "a", 2),
        ("(iv) arbitration seat", "roman_paren", "iv", 2),
        ("ARTICLE IV - TERMINATION", "keyword", "ARTICLE IV", 0),
    ],
)
def test_numbering_schemes(line, scheme, label, depth):
    m = match_number(line)
    assert m is not None, f"failed to match {line!r}"
    assert (m.scheme, m.label, m.depth) == (scheme, label, depth)


def test_depth_is_consistent_across_schemes():
    """A top-level "4." must not nest deeper than "4.2", or the parent-heading
    stack inherits from the wrong level and every sub-clause loses its context."""
    assert match_number("4. TERM").depth < match_number("4.2 x").depth
    assert match_number("4.2 x").depth < match_number("4.2.1 x").depth


@pytest.mark.parametrize("line", ["I. am writing to say", "The rent shall be paid.", "12"])
def test_prose_is_not_a_clause_number(line):
    assert match_number(line) is None


def test_parenthesised_subclause_survives_false_positive_guard():
    """Regression: the guard against prose "I." was eating "(a) ..." sub-clauses."""
    assert match_number("(a) subletting is prohibited") is not None


def test_heading_detection():
    assert looks_like_heading("TERMINATION", 12.0, 10.0, bold=True)
    assert not looks_like_heading(
        "The tenant shall pay the rent before the fifth day of each month.", 10.0, 10.0, bold=True
    )


@pytest.mark.skipif(not FIXTURE.exists(), reason="run tests/fixtures/make_fixture.py first")
class TestEndToEnd:
    def test_segments_all_clauses(self):
        clauses, low, parsed = segment_file(str(FIXTURE))
        assert not low, "fixture is well numbered and must not be flagged low-structure"
        assert len(clauses) >= 15
        assert parsed.page_count == 2

    def test_parent_headings_inherited(self):
        clauses, _, _ = segment_file(str(FIXTURE))
        by_id = {c.id: c for c in clauses}
        assert by_id["2.2"].parent_heading == "RENT AND DEPOSIT"
        assert by_id["4.1"].parent_heading == "NOTICE AND TERMINATION"

    def test_page_furniture_stripped(self):
        """Regression: "Page 1 of 2" / "Page 2 of 2" differ per page and were
        surviving text-identity matching, landing inside clause text."""
        clauses, _, _ = segment_file(str(FIXTURE))
        assert not [c.id for c in clauses if "page " in c.text.lower()]

    def test_clause_ids_are_unique(self):
        clauses, _, _ = segment_file(str(FIXTURE))
        ids = [c.id for c in clauses]
        assert len(ids) == len(set(ids))
