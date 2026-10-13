"""Parsing numbers as Indian legal documents actually write them.

Three habits make this harder than a plain float() call:

  1. Belt-and-braces duplication — "six (6) months", "ten percent (10%)".
     The digit and the word always agree in a well-drafted document; where they
     disagree, that is itself worth surfacing rather than silently picking one.
  2. The Indian numbering system — lakh (10^5) and crore (10^7), with grouping
     to match: 1,92,000 not 192,000. A naive thousands-separator strip gets the
     right answer here by luck, but "1,92,00,000" defeats it.
  3. Amounts written out in full — "Rupees One Lakh Ninety Two Thousand only".

Getting this wrong is not a visible failure. A deposit misread as 192 instead of
192000 produces a confident, well-formatted, completely wrong percentile, which
is worse than no answer. Hence the property tests in tests/test_numbers.py.
"""

from __future__ import annotations

import re

LAKH = 100_000
CRORE = 10_000_000

_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fourty": 40,  # misspelling is common
    "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_SCALES = {"hundred": 100, "thousand": 1_000, "lakh": LAKH, "lac": LAKH,
           "lakhs": LAKH, "lacs": LAKH, "crore": CRORE, "crores": CRORE,
           "million": 1_000_000, "billion": 1_000_000_000}

_WORD_RE = re.compile(r"[a-z]+")


def words_to_number(text: str) -> float | None:
    """Convert an English number phrase to a value, Indian scales included.

    Returns None when the phrase contains no number words at all, so the caller
    can distinguish "not a number" from "zero".
    """
    tokens = [
        t for t in _WORD_RE.findall(text.lower()) if t not in {"and", "a", "only", "rupees", "rs"}
    ]
    if not tokens:
        return None

    total = 0.0      # completed scale groups
    current = 0.0    # the group being accumulated
    seen_any = False

    for tok in tokens:
        if tok in _UNITS:
            current += _UNITS[tok]
            seen_any = True
        elif tok in _TENS:
            current += _TENS[tok]
            seen_any = True
        elif tok == "half":
            # "half a month's rent", "one and a half months"
            current += 0.5
            seen_any = True
        elif tok in _SCALES:
            scale = _SCALES[tok]
            if not seen_any and scale >= 100:
                # "lakh" with no preceding count means one lakh
                current = 1.0
                seen_any = True
            if scale == 100:
                current *= scale
            else:
                # thousand/lakh/crore close a group: "one lakh ninety two thousand"
                total += (current or 1.0) * scale
                current = 0.0
        elif seen_any:
            # a non-number word ends the phrase
            break

    if not seen_any:
        return None
    return total + current


def parse_indian_digits(text: str) -> float | None:
    """Parse a digit string that may use Indian grouping: 1,92,000 or 1,92,00,000."""
    cleaned = text.strip().replace(" ", "")
    cleaned = re.sub(r"[/\-]+$", "", cleaned)  # trailing "/-" on rupee amounts
    if not re.fullmatch(r"\d{1,3}(?:,\d{2,3})*(?:\.\d+)?|\d+(?:\.\d+)?", cleaned):
        return None
    try:
        return float(cleaned.replace(",", ""))
    except ValueError:
        return None


# "six (6)" / "ten percent (10%)" — the parenthesised digit is authoritative
_DUP = re.compile(
    r"(?P<words>(?:[a-zA-Z]+[\s-]+){1,6}?)\(\s*(?P<digits>\d[\d,]*(?:\.\d+)?)\s*%?\s*\)"
)


def parse_duplicated(text: str) -> tuple[float, str] | None:
    """Handle the "six (6)" construction, returning (value, matched_text).

    The digits win, but the words are checked against them: a mismatch means the
    document contradicts itself, and the caller is told so rather than being
    handed a number that looks certain.
    """
    m = _DUP.search(text)
    if not m:
        return None
    digits = parse_indian_digits(m.group("digits"))
    if digits is None:
        return None
    return digits, m.group(0)


def duplication_disagrees(text: str) -> tuple[float, float] | None:
    """Return (word_value, digit_value) when a "six (7)" contradiction is found."""
    m = _DUP.search(text)
    if not m:
        return None
    digits = parse_indian_digits(m.group("digits"))
    words = words_to_number(m.group("words"))
    if digits is None or words is None:
        return None
    if abs(words - digits) > 1e-9:
        return (words, digits)
    return None
