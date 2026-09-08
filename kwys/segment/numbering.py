"""Recognising the numbering conventions of legal documents.

Contracts are one of the few document types that reliably announce their own
structure. Exploiting that is free, auditable and needs no training data — which
is why segmentation is rules and not a model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Ordered most-specific first: "1.2.3" must win before "1." can match it.
PATTERNS: list[tuple[str, re.Pattern[str], int]] = [
    # 1.2.3  /  1.2.3.  /  1.2.3)
    ("decimal", re.compile(r"^\s*(\d+(?:\.\d+){1,4})[.)]?\s+(?=\S)"), 0),
    # 1.  /  1)  /  (1)
    ("integer", re.compile(r"^\s*\(?(\d{1,3})\)|^\s*(\d{1,3})[.)]\s+(?=\S)"), 0),
    # (a) / a) / (iv) / iv)
    ("alpha_paren", re.compile(r"^\s*\(([a-z])\)\s*(?=\S)", re.I), 2),
    ("roman_paren", re.compile(r"^\s*\(([ivxlc]{1,6})\)\s*(?=\S)", re.I), 2),
    ("alpha_dot", re.compile(r"^\s*([a-z])[.)]\s+(?=\S)"), 2),
    # ARTICLE IV / CLAUSE 12 / SECTION 3
    (
        "keyword",
        re.compile(r"^\s*(ARTICLE|CLAUSE|SECTION|PARA(?:GRAPH)?)\s+([IVXLC]+|\d+)\b", re.I),
        0,
    ),
]

# The one genuinely ambiguous marker: a line opening "I. " followed by lowercase
# is the pronoun in prose, not a roman numeral list item.
#
# We deliberately do NOT guard "a. " here. In a contract a leading "a." is nearly
# always a list marker, and the two failure modes are not symmetric: treating a
# marker as prose merely merges a sub-clause into its parent (the text is still
# read and scored), whereas treating prose as a marker manufactures junk clauses
# that the classifier must then guess at. We take the recoverable error.
_FALSE_POSITIVE = re.compile(r"^\s*I[.)]\s+(?=[a-z])")


@dataclass(frozen=True)
class NumberMatch:
    label: str  # "4.2" exactly as printed
    scheme: str  # which pattern matched
    depth: int  # nesting depth implied by the scheme
    rest: str  # the line with the number stripped off


def match_number(line: str) -> NumberMatch | None:
    """Identify a clause number at the start of a line, if there is one."""
    if not line or len(line) > 400:
        return None

    for scheme, pattern, base_depth in PATTERNS:
        m = pattern.match(line)
        if not m:
            continue

        label = next((g for g in m.groups() if g), "")
        if scheme == "keyword":
            label = " ".join(g for g in m.groups() if g)

        rest = line[m.end() :].strip()

        # A number with nothing after it is a page number or a stray artefact.
        if not rest and scheme != "keyword":
            return None

        if scheme == "alpha_dot" and _FALSE_POSITIVE.match(line):
            return None

        depth = base_depth
        if scheme == "decimal":
            depth = label.count(".")  # "4.2.1" nests deeper than "4.2"

        return NumberMatch(label=label, scheme=scheme, depth=depth, rest=rest)

    return None


def looks_like_heading(text: str, size: float, body_size: float, bold: bool) -> bool:
    """Is this line a heading rather than body text?

    Three independent signals, any one sufficient: larger type, bold on a short
    line, or short-and-shouting. Headings are short by nature, so length gates
    every branch — a long bold paragraph is emphasis, not a heading.
    """
    stripped = text.strip()
    if not stripped or len(stripped) > 90:
        return False
    if stripped.endswith((".", ";", ",")):
        return False  # headings do not end in sentence punctuation

    if size > body_size + 0.6:
        return True
    if bold and len(stripped) < 70:
        return True
    letters = [c for c in stripped if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.8 and len(stripped) < 60:
        return True
    return False
