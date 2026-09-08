"""Pulling the operative values out of a clause.

Regex first, because the constructions that matter in Indian agreements are
highly stereotyped and a pattern is auditable in a way a model is not. A trained
token classifier handles the residue later (see PLAN.md stage 4); this module is
the floor, and on the fixture set it already reaches most fields.

Everything returned is normalised to a canonical unit — months, days, INR,
percent — because a percentile over mixed units is meaningless.
"""

from __future__ import annotations

import re

from kwys.extract.numbers import (
    duplication_disagrees,
    parse_duplicated,
    parse_indian_digits,
    words_to_number,
)
from kwys.models import Term

# ---------------------------------------------------------------- primitives

_NUM = r"(?:\d[\d,]*(?:\.\d+)?|[a-zA-Z]+(?:[\s-]+[a-zA-Z]+){0,5})"

_MONTH_WORDS = r"months?"
_DAY_WORDS = r"days?"
_YEAR_WORDS = r"years?"

_CURRENCY = r"(?:Rs\.?|INR|₹|Rupees)"


def _value_of(raw: str) -> float | None:
    """Resolve a number that may be digits, words, or the "six (6)" pair."""
    dup = parse_duplicated(raw)
    if dup:
        return dup[0]
    digits = parse_indian_digits(raw)
    if digits is not None:
        return digits
    return words_to_number(raw)


def _find(pattern: str, text: str) -> re.Match[str] | None:
    return re.search(pattern, text, re.IGNORECASE)


def _duration(text: str, unit_words: str) -> tuple[float, str] | None:
    """Find a duration expressed in the given unit, returning (value, raw).

    The number and the raw text are deliberately separate. Feeding the whole
    match ("180 days") to the number parser fails, because it is neither a bare
    numeral nor a number phrase — which made plain digit durations silently
    unextractable while "six (6) months" worked by accident.
    """
    m = _find(
        rf"({_NUM})\s*(?:\(\s*(\d[\d,]*)\s*\)\s*)?{unit_words}\b", text
    )
    if not m:
        return None
    # Parenthesised digits are authoritative where present: "six (6)".
    val = parse_indian_digits(m.group(2)) if m.group(2) else None
    if val is None:
        val = _value_of(m.group(1))
    return (val, m.group(0).strip()) if val is not None else None


def _money(text: str) -> tuple[float, str] | None:
    """Find a rupee amount, digits preferred over the written-out duplicate."""
    m = _find(rf"{_CURRENCY}\s*([\d,]+(?:\.\d+)?)\s*/?-?", text)
    if m:
        val = parse_indian_digits(m.group(1))
        if val is not None:
            return val, m.group(0).strip()
    # "Rupees One Lakh Ninety Two Thousand only"
    m = _find(r"Rupees\s+((?:[A-Za-z]+[\s-]+){1,10}?)only", text)
    if m:
        val = words_to_number(m.group(1))
        if val is not None:
            return val, m.group(0).strip()
    return None


def _percent(text: str, *, near: str | None = None) -> tuple[float, str] | None:
    scope = text
    if near:
        # Sentence-split on a period followed by whitespace + capital, so the
        # period in "Rs. 32,000" does not chop the sentence in half. Falling
        # back to the whole clause is safe: `near` only narrows, never gates.
        for sentence in re.split(r"(?<=[.;])\s+(?=[A-Z])", text):
            if re.search(near, sentence, re.IGNORECASE):
                scope = sentence
                break
    m = _find(
        rf"({_NUM})\s*(?:\(\s*([\d.]+)\s*%?\s*\))?\s*(?:%|per\s*cent|percent)", scope
    )
    if not m:
        return None
    val = parse_indian_digits(m.group(2)) if m.group(2) else None
    if val is None:
        val = _value_of(m.group(1))
    return (val, m.group(0).strip()) if val is not None else None


def _to_months(value: float, unit: str) -> float:
    return {"months": value, "days": value / 30.0, "years": value * 12.0}[unit]


# ---------------------------------------------------------------- per-field

def _term(field: str, value, unit: str | None, raw: str, conf: float = 0.9) -> Term:
    return Term(field=field, raw=raw, value=value, unit=unit, extractor="regex", confidence=conf)


def extract_deposit(text: str) -> list[Term]:
    out: list[Term] = []
    money = _money(text)
    if money:
        out.append(_term("deposit_inr", money[0], "INR", money[1]))
    # "being six (6) months' rent" states the ratio directly — far more reliable
    # than dividing by a monthly rent that may live in a different clause.
    m = _find(rf"({_NUM}\s*(?:\(\s*\d+\s*\))?)\s*{_MONTH_WORDS}[''`]?s?\s+rent", text)
    if m:
        val = _value_of(m.group(0))
        if val is not None:
            out.append(_term("deposit_months", val, "months_of_rent", m.group(0).strip(), 0.95))
    return out


def extract_refund(text: str) -> list[Term]:
    d = _duration(text, _DAY_WORDS)
    if d:
        return [_term("refund_days", d[0], "days", d[1])]
    m = _duration(text, _MONTH_WORDS)
    if m:
        return [_term("refund_days", _to_months(m[0], "months") * 30, "days", m[1], 0.85)]
    return []


def extract_lock_in(text: str) -> list[Term]:
    for unit, words in (("months", _MONTH_WORDS), ("years", _YEAR_WORDS), ("days", _DAY_WORDS)):
        d = _duration(text, words)
        if d:
            return [_term("lock_in_months", _to_months(d[0], unit), "months", d[1])]
    return []


def extract_notice(text: str) -> list[Term]:
    out: list[Term] = []
    for unit, words in (("months", _MONTH_WORDS), ("days", _DAY_WORDS), ("years", _YEAR_WORDS)):
        d = _duration(text, words)
        if d:
            out.append(_term("notice_months", _to_months(d[0], unit), "months", d[1]))
            break
    return out


def extract_rent(text: str) -> list[Term]:
    out: list[Term] = []
    money = _money(text)
    if money:
        out.append(_term("monthly_rent_inr", money[0], "INR", money[1]))
    pct = _percent(text, near="enhanc|increas|escalat|revis")
    if pct:
        out.append(_term("escalation_pct", pct[0], "pct_per_year", pct[1]))
    return out


def extract_penalty(text: str) -> list[Term]:
    out: list[Term] = []
    pct = _percent(text, near="interest|penalt|delay|late")
    if pct:
        unit = "pct_per_month" if re.search(r"per\s*month", text, re.I) else "pct"
        out.append(_term("late_fee_pct", pct[0], unit, pct[1]))
    return out


def extract_maintenance(text: str) -> list[Term]:
    money = _money(text)
    return [_term("threshold_inr", money[0], "INR", money[1])] if money else []


def extract_entry(text: str) -> list[Term]:
    d = _duration(text, r"hours?")
    if d:
        return [_term("notice_hours", d[0], "hours", d[1])]
    if re.search(r"without\s+(?:any\s+)?(?:prior\s+)?notice", text, re.I):
        # Absence of a required notice period is itself the finding, and zero is
        # the honest encoding of it.
        return [_term("notice_hours", 0.0, "hours", "without prior notice", 0.95)]
    return []


def extract_dispute(text: str) -> list[Term]:
    out: list[Term] = []
    m = _find(
        r"seat\s+of\s+arbitration\s+(?:shall\s+be\s+)?(?:at|in)\s+([A-Z][A-Za-z\s]{2,24})",
        text,
    )
    if not m:
        m = _find(
            r"arbitration\s+(?:shall\s+be\s+held\s+)?(?:at|in)\s+([A-Z][A-Za-z\s]{2,24})",
            text,
        )
    if m:
        out.append(_term("seat_city", m.group(1).strip(" .,"), None, m.group(0).strip(), 0.8))
    if _find(r"sole\s+arbitrator", text):
        out.append(_term("arbitrators_count", 1.0, "count", "sole arbitrator"))
    m = _find(r"arbitrator\s+appointed\s+by\s+the\s+(\w+)", text)
    if m:
        out.append(_term("appointed_by", m.group(1).strip(), None, m.group(0).strip(), 0.85))
    return out


def extract_jurisdiction(text: str) -> list[Term]:
    out: list[Term] = []
    m = _find(
        r"courts?\s+(?:at|in|of)\s+([A-Z][A-Za-z\s]{2,24}?)\s+(?:alone\s+)?(?:shall|will|have)",
        text,
    )
    if m:
        out.append(
            _term("jurisdiction_city", m.group(1).strip(" .,"), None, m.group(0).strip(), 0.85)
        )
    out.append(
        _term("exclusive", bool(_find(r"\bexclusive\b", text)), None,
              "exclusive" if _find(r"\bexclusive\b", text) else "not stated", 0.9)
    )
    return out


EXTRACTORS = {
    "security_deposit": extract_deposit,
    "deposit_refund": extract_refund,
    "lock_in_period": extract_lock_in,
    "notice_period": extract_notice,
    "termination": extract_notice,
    "rent_and_escalation": extract_rent,
    "penalty_and_late_fee": extract_penalty,
    "maintenance_and_repairs": extract_maintenance,
    "entry_and_inspection": extract_entry,
    "dispute_resolution": extract_dispute,
    "governing_law": extract_jurisdiction,
}


def extract_terms(clause_type: str, text: str) -> list[Term]:
    """Extract every field we know how to find for this clause type."""
    fn = EXTRACTORS.get(clause_type)
    return fn(text) if fn else []


def contradiction_warning(text: str) -> str | None:
    """Flag a clause whose words and digits disagree — "six (7) months".

    Rare, but when it happens the document is ambiguous on its face and the user
    should be told, not handed whichever number our regex reached first.
    """
    hit = duplication_disagrees(text)
    if hit:
        return (
            f"This clause writes the number two ways and they do not match: "
            f"'{hit[0]:g}' in words but '{hit[1]:g}' in figures."
        )
    return None
