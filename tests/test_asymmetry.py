from __future__ import annotations

from kwys.asymmetry.obligations import (
    extract_obligations,
    find_asymmetries,
    find_missing_clauses,
    find_paired_asymmetries,
)
from kwys.asymmetry.parties import build_party_map
from kwys.models import Clause, Domain, Modality, Role, Term

PREAMBLE = (
    'between Mr. A. Kumar (hereinafter referred to as the "LESSOR") of the ONE PART '
    'and Ms. S. Nair (hereinafter referred to as the "LESSEE") of the OTHER PART.'
)


def _pmap():
    return build_party_map(PREAMBLE, Domain.RESIDENTIAL_LEASE)


def test_party_labels_resolve_to_roles():
    pmap = _pmap()
    assert pmap.label_to_role["lessee"] is Role.TENANT
    assert pmap.label_to_role["lessor"] is Role.LANDLORD


def test_negation_is_read_before_obligation():
    """"shall not" must not be read as an obligation to do the thing forbidden."""
    c = Clause(id="3.2", text="The Lessee shall not sublet the premises.", clause_type="subletting")
    obs = extract_obligations(c, _pmap())
    assert obs[0].modality is Modality.PROHIBITION


def test_bound_party_is_the_subject_not_the_object():
    """"The Lessee shall pay the Lessor" binds the LESSEE. Getting this backwards
    inverts the risk direction of every finding in the document."""
    c = Clause(id="2.1", text="The Lessee shall pay the Lessor the monthly rent.")
    obs = extract_obligations(c, _pmap())
    assert obs[0].role is Role.TENANT


def test_one_sided_duty_is_flagged():
    pmap = _pmap()
    clauses = [
        Clause(
            id="4.1",
            text="The Lessee shall give six months notice to the Lessor.",
            clause_type="notice_period",
        )
    ]
    obs = [o for c in clauses for o in extract_obligations(c, pmap)]
    assert find_asymmetries(clauses, obs, pmap)


def test_paired_asymmetry_reports_both_figures():
    """The strongest finding this tool produces: two ordinary-looking numbers,
    pages apart, that are wildly different. A lay reader cannot hold both in
    mind at once, which is exactly why it needs computing."""
    pmap = _pmap()
    tenant_clause = Clause(
        id="4.1",
        text="The Lessee shall give six (6) months prior written notice to the Lessor.",
        clause_type="notice_period",
    )
    landlord_clause = Clause(
        id="4.2",
        text="The Lessor may terminate this agreement by giving fifteen (15) days notice.",
        clause_type="termination",
    )
    pairs = [
        (
            tenant_clause,
            [Term(field="notice_months", raw="six (6) months", value=6.0, unit="months")],
        ),
        (
            landlord_clause,
            [Term(field="notice_months", raw="fifteen (15) days", value=0.5, unit="months")],
        ),
    ]
    found = find_paired_asymmetries(pairs, pmap)
    assert found, "a 12x notice imbalance must be reported"
    _, detail, extra = found[0]
    assert extra["ratio"] == 12.0
    assert "15 days" in detail and "6 months" in detail


def test_similar_periods_are_not_flagged():
    """One month versus two is not worth raising; noise buries real findings."""
    pmap = _pmap()
    pairs = [
        (Clause(id="4.1", text="The Lessee shall give two months notice."),
         [Term(field="notice_months", raw="two months", value=2.0, unit="months")]),
        (Clause(id="4.2", text="The Lessor shall give one month notice."),
         [Term(field="notice_months", raw="one month", value=1.0, unit="months")]),
    ]
    assert not find_paired_asymmetries(pairs, pmap)


def test_missing_clause_detection():
    """Absence is the risk a reader cannot notice: there is nothing on the page
    to notice."""
    clauses = [Clause(id="1", text="x", clause_type="rent_and_escalation")]
    missing = dict(find_missing_clauses(clauses, Domain.RESIDENTIAL_LEASE))
    assert "deposit_refund" in missing
    assert "rent_and_escalation" not in missing
