"""Extraction from judgment prose, where a silent error is most costly.

Clause parsing works on structured text. This works on narrative that recites
many unrelated sums - decree amounts, arrears, costs, court deposits - any of
which can match a loose money pattern. A wrong value here does not raise; it
enters the reference distribution and shifts a median that every later report
is measured against.
"""

from __future__ import annotations

from kwys.harvest.judgments import (
    Judgment,
    classify_property,
    derive_deposit_ratio,
    extract_values,
)


def _judgment(text: str, doc_id: str = "1") -> Judgment:
    return Judgment(doc_id=doc_id, title="Test v Test", text=text)


def _fields(text: str) -> dict[str, float]:
    return {v.field: v.value for v in extract_values(_judgment(text))}


# --------------------------------------------------------------- tiers

def test_specific_pattern_beats_generic_one():
    """Regression: a judgment reciting a Rs.12,21,000 security deposit AND a
    Rs.44,46,000 decree amount yielded both, and taking the max produced a
    24-month ratio instead of the true 6.6."""
    text = (
        "The tenant paid a security deposit of Rs.12,21,000 under the lease. "
        "The Trial Court decreed a deposit of Rs.44,46,000 towards damages."
    )
    assert _fields(text)["deposit_inr"] == 12_21_000


def test_earliest_mention_wins_within_a_tier():
    """Judgments recite the agreement in the statement of facts; later mentions
    concern the dispute."""
    text = (
        "The security deposit of Rs.2,00,000 was paid on execution. "
        "Later the security deposit of Rs.9,00,000 was claimed in appeal."
    )
    assert _fields(text)["deposit_inr"] == 2_00_000


# --------------------------------------------------------------- bounds

def test_implausible_values_are_dropped():
    """Out of bounds means extraction error, not a remarkable agreement."""
    assert "monthly_rent_inr" not in _fields("a monthly rent of Rs.12")
    assert "deposit_inr" not in _fields("a security deposit of Rs.500")


def test_word_numbers_are_read():
    assert _fields("a lock-in period of eleven months")["lock_in_months"] == 11
    assert _fields("notice period of three months")["notice_months"] == 3


# --------------------------------------------------------------- ratio

def test_ratio_derived_from_deposit_and_rent():
    text = (
        "The premises were let at a monthly rent of Rs.20,000 and the tenant "
        "paid a security deposit of Rs.1,20,000 at the time of execution."
    )
    values = extract_values(_judgment(text))
    ratio = derive_deposit_ratio(values)
    assert ratio is not None
    assert ratio.value == 6.0
    assert ratio.unit == "months_of_rent"


def test_distant_figures_are_not_paired():
    """A deposit on page 1 and a rent on page 30 are probably different
    tenancies, or the rent after escalation. The ratio between them is noise."""
    text = (
        "The tenant paid a security deposit of Rs.1,20,000. "
        + "Irrelevant discussion of precedent. " * 120
        + "The monthly rent of Rs.20,000 was payable in advance."
    )
    assert derive_deposit_ratio(extract_values(_judgment(text))) is None


def test_absurd_ratio_is_rejected():
    """A court deposit is not a security deposit. 200 months of rent is the
    signal that the two figures are unrelated."""
    text = (
        "The tenant was inducted at a monthly rent of Rs.500 and a "
        "security deposit of Rs.1,00,000 was ordered."
    )
    assert derive_deposit_ratio(extract_values(_judgment(text))) is None


def test_stated_ratio_beats_a_derived_one():
    text = (
        "The tenant paid a security deposit of six months rent, "
        "the monthly rent of Rs.20,000 being payable in advance."
    )
    values = extract_values(_judgment(text))
    assert any(v.field == "deposit_months" and v.value == 6 for v in values)
    assert derive_deposit_ratio(values) is None


# --------------------------------------------------------------- property type

def test_property_classification_requires_a_margin():
    """Regression: a National Highway Authority case was labelled residential
    because incidental vocabulary out-counted commercial terms. A near-tie
    carries no signal, and 'unknown' is the honest answer."""
    assert classify_property("the residential flat, a dwelling house for the family") == (
        "residential"
    )
    assert classify_property("the factory godown and industrial warehouse premises") == (
        "commercial"
    )
    assert classify_property("the premises were let to the appellant") == "unknown"


def test_one_value_per_field_per_judgment():
    """A judgment reciting a term three times must not weigh three times as
    much as one that states it once."""
    text = (
        "A security deposit of Rs.2,00,000 was paid. "
        "The security deposit of Rs.2,00,000 remains unrefunded. "
        "Interest on the security deposit of Rs.2,00,000 was claimed."
    )
    deposits = [v for v in extract_values(_judgment(text)) if v.field == "deposit_inr"]
    assert len(deposits) == 1
