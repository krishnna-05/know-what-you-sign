"""The scoring rules that keep the tool honest.

These are not arithmetic tests. Each one pins a decision that, if it silently
regressed, would make the system confidently wrong for a user who cannot check
its working.
"""

from __future__ import annotations

import pytest

from kwys.models import Domain, Role, Term
from kwys.norms.store import MIN_N, NormStore
from kwys.score.scorer import Scorer


def _norms(values: list[float], field: str = "security_deposit.deposit_months") -> NormStore:
    s = NormStore("residential_lease", "test")
    for v in values:
        s.add(field, v, "months_of_rent")
    return s


def _term(value: float, field: str = "deposit_months") -> Term:
    return Term(field=field, raw=str(value), value=value, unit="months_of_rent")


def _scorer(store: NormStore, role: Role = Role.TENANT) -> Scorer:
    return Scorer(Domain.RESIDENTIAL_LEASE, role, store)


TYPICAL = [2.0] * 140 + [3.0] * 90 + [1.0] * 30 + [4.0] * 30 + [6.0] * 10


def test_direction_flips_with_role():
    """The same 6-month deposit is a burden for the tenant and a protection for
    the landlord. If this ever collapses, the tool tells tenants that a SMALL
    deposit is the risky one."""
    store = _norms(TYPICAL)
    tenant = _scorer(store, Role.TENANT).score_term("security_deposit", _term(6.0))
    landlord = _scorer(store, Role.LANDLORD).score_term("security_deposit", _term(6.0))
    assert tenant.raw_harm > 0.9
    assert landlord.raw_harm < 0.1


def test_undeclared_field_is_not_scored():
    """Undeclared means "nobody decided which way this cuts", not "harmless"."""
    store = _norms([1.0] * 100, field="rent_and_escalation.monthly_rent_inr")
    scored = _scorer(store).score_term(
        "rent_and_escalation", Term(field="monthly_rent_inr", raw="x", value=99999.0, unit="INR")
    )
    assert scored.harm_percentile is None
    assert scored.direction is None


def test_below_min_n_makes_no_deviation_claim():
    store = _norms([2.0] * (MIN_N - 1))
    scored = _scorer(store).score_term("security_deposit", _term(9.0))
    assert scored.norm is not None, "the lookup is still recorded for the audit trail"
    assert not scored.norm.sufficient
    assert scored.harm_percentile is None


def test_thin_corpus_still_reports_but_less_severely():
    """Regression: the harm gate was applied to the SHRUNK percentile, so at
    n=30 the maximum achievable value (0.75) sat below the 0.80 gate and no
    field with a small corpus could ever produce a finding. Shrinkage must
    temper severity, not act as a hidden second sample-size threshold."""
    thin = _norms([2.0] * 20 + [3.0] * 9 + [9.0])
    fat = _norms(TYPICAL * 2)

    thin_scored = _scorer(thin).score_term("security_deposit", _term(9.0))
    fat_scored = _scorer(fat).score_term("security_deposit", _term(9.0))

    assert thin_scored.raw_harm >= 0.8, "must still clear the gate"
    assert thin_scored.harm_percentile < fat_scored.harm_percentile, (
        "a thin corpus must yield a LOWER severity than a thick one at the "
        "same percentile"
    )


def test_extreme_deviation_can_reach_high_alone():
    """Regression: with deviation weighted 0.55, no pure deviation finding could
    ever cross the 0.75 "high" threshold, however extreme. The project's
    headline signal must be able to carry a finding on its own."""
    from kwys.models import Clause, Severity

    store = _norms(TYPICAL * 3)
    scorer = _scorer(store)
    clause = Clause(id="2.2", text="deposit of six months rent", clause_type="security_deposit")
    scored = scorer.score_term("security_deposit", _term(6.0))
    finding = scorer.finding_from_term(clause, scored)
    assert finding is not None
    assert finding.severity is Severity.HIGH


def test_typical_value_produces_no_finding():
    """A clause at the median must be silent. A report that flags twenty clauses
    has told the user nothing."""
    from kwys.models import Clause

    store = _norms(TYPICAL)
    scorer = _scorer(store)
    clause = Clause(id="2.2", text="deposit of two months rent", clause_type="security_deposit")
    scored = scorer.score_term("security_deposit", _term(2.0))
    assert scorer.finding_from_term(clause, scored) is None


def test_every_finding_carries_evidence():
    from kwys.models import Clause

    store = _norms(TYPICAL * 3)
    scorer = _scorer(store)
    clause = Clause(id="2.2", text="deposit of six months rent", clause_type="security_deposit")
    finding = scorer.finding_from_term(
        clause, scorer.score_term("security_deposit", _term(6.0))
    )
    assert finding.evidence.norm is not None
    assert finding.evidence.clause_text
    assert finding.question_to_ask, "a flag the user cannot act on is trivia"


@pytest.mark.parametrize("value,expect_finding", [(2.0, False), (3.0, False), (6.0, True)])
def test_severity_gradation(value, expect_finding):
    from kwys.models import Clause

    store = _norms(TYPICAL * 3)
    scorer = _scorer(store)
    clause = Clause(id="2.2", text="t", clause_type="security_deposit")
    scored = scorer.score_term("security_deposit", _term(value))
    assert (scorer.finding_from_term(clause, scored) is not None) is expect_finding
