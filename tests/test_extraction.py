from __future__ import annotations

import pytest

from kwys.extract.patterns import contradiction_warning, extract_terms


def _fields(clause_type: str, text: str) -> dict[str, object]:
    return {t.field: t.value for t in extract_terms(clause_type, text)}


def test_deposit_ratio_preferred_over_division():
    """"being six (6) months' rent" states the ratio outright. Deriving it by
    dividing by a rent that lives in another clause is strictly worse."""
    got = _fields(
        "security_deposit",
        "a security deposit of Rs. 1,92,000/- (Rupees One Lakh Ninety Two "
        "Thousand only), being six (6) months' rent",
    )
    assert got["deposit_inr"] == 192_000
    assert got["deposit_months"] == 6


@pytest.mark.parametrize(
    "text,expected_months",
    [
        ("shall give six (6) months prior written notice", 6),
        ("by giving fifteen (15) days written notice", 0.5),
        ("shall give 90 days prior written notice", 3),
        ("two (2) years notice", 24),
    ],
)
def test_durations_normalise_to_months(text, expected_months):
    """Regression: plain digit durations ("90 days") silently extracted nothing,
    because the whole match was handed to the number parser."""
    assert _fields("notice_period", text)["notice_months"] == expected_months


@pytest.mark.parametrize(
    "clause_type,text,field,expected",
    [
        (
            "rent_and_escalation",
            "rent shall be enhanced by ten percent (10%)",
            "escalation_pct",
            10,
        ),
        (
            "penalty_and_late_fee",
            "interest at the rate of 3% per month",
            "late_fee_pct",
            3,
        ),
    ],
)
def test_percentages(clause_type, text, field, expected):
    """Regression: every percent extraction returned None."""
    assert _fields(clause_type, text)[field] == expected


def test_period_inside_rupees_does_not_break_sentence_scoping():
    got = _fields(
        "rent_and_escalation",
        "The rent is Rs. 32,000/-. The rent shall be enhanced by ten percent (10%) yearly.",
    )
    assert got["monthly_rent_inr"] == 32_000
    assert got["escalation_pct"] == 10


def test_absent_notice_encodes_as_zero_not_missing():
    """"without prior notice" IS the finding. Recording it as absent would hide
    the very thing the user needs to see."""
    assert _fields("entry_and_inspection", "may enter at any time without prior notice")[
        "notice_hours"
    ] == 0.0


def test_arbitration_seat_and_appointer():
    got = _fields(
        "dispute_resolution",
        "referred to arbitration by a sole arbitrator appointed by the Lessor, "
        "and the seat of arbitration shall be at New Delhi",
    )
    assert got["seat_city"] == "New Delhi"
    assert got["appointed_by"] == "Lessor"


def test_contradiction_is_surfaced():
    assert contradiction_warning("a term of six (7) months") is not None
    assert contradiction_warning("a term of six (6) months") is None
