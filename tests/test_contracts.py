"""Regression tests over whole example agreements.

Each test pins a failure that was seen on a realistic document: a clause type
the rules missed, a figure that was not extracted, a "missing" finding about a
section sitting in plain sight, a role that changed nothing. The PDFs are built
from tests/fixtures/contracts.py on the fly, and compared against a small norm
store made here, so nothing depends on which corpora a machine has built.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from kwys.classify.rules import classify_text
from kwys.extract.patterns import derive_deposit_months, extract_terms
from kwys.models import Domain, Role
from kwys.norms.store import MIN_N, NormStore
from kwys.pipeline import analyse

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
import contracts  # noqa: E402
from make_fixture import build  # noqa: E402

LEASE = Domain.RESIDENTIAL_LEASE


# ---------------------------------------------------------------- clause types


@pytest.mark.parametrize(
    "text",
    [
        "NOTICE AND TERMINATION [SEP] The Tenant shall give one (1) month written "
        "notice to vacate.",
        "NOTICE [SEP] The Lessee may vacate by giving fifteen (15) days written notice.",
        "NOTICE [SEP] The Licensor may terminate this licence by giving seven (7) days "
        "written notice to the Licensee.",
    ],
)
def test_notice_clauses_are_recognised(text):
    """Once scored too low, or tied with termination, and abstained to `other`."""
    assert classify_text(text, LEASE).clause_type == "notice_period"


def test_a_heading_does_not_outvote_the_clause_itself():
    """Under "TERM AND LOCK-IN", a clause stating only the length of the tenancy
    was labelled a lock-in, and the lock-in was then reported twice."""
    text = "TERM AND LOCK-IN [SEP] This licence shall be for a period of eleven (11) months."
    assert classify_text(text, LEASE).clause_type != "lock_in_period"


def test_licence_fee_is_rent():
    """Leave-and-licence agreements say "licence fee"; it is the rent."""
    text = "LICENCE FEE [SEP] The Licensee shall pay a monthly licence fee of Rs. 45,000/-."
    assert classify_text(text, LEASE).clause_type == "rent_and_escalation"


def test_entry_without_inspect_wording_is_recognised():
    text = "ACCESS [SEP] The Licensor may enter the premises at any time without notice."
    assert classify_text(text, LEASE).clause_type == "entry_and_inspection"


# ---------------------------------------------------------------- deposit figures


@pytest.mark.parametrize(
    ("text", "months"),
    [
        ("a security deposit of Rs. 11,000/-, being half (0.5) a month's rent", 0.5),
        ("being ten (10) months' licence fee", 10.0),
        ("being one and a half months' rent", 1.5),
        ("being six (6) months' rent", 6.0),
    ],
)
def test_deposit_in_months_is_read(text, months):
    terms = {t.field: t.value for t in extract_terms("security_deposit", text)}
    assert terms.get("deposit_months") == months


def test_deposit_months_is_derived_from_rupees():
    term = derive_deposit_months(56_000, 28_000)
    assert term is not None
    assert term.value == 2.0
    assert term.extractor == "derived", "a worked-out figure must say so"


# ---------------------------------------------------------------- whole documents


@pytest.fixture(scope="module")
def norms_root(tmp_path_factory) -> Path:
    """Deposits around 2-4 months and lock-ins around 6-12: unremarkable middles."""
    root = tmp_path_factory.mktemp("norms")
    store = NormStore(LEASE.value, "test")
    for i in range(MIN_N * 2):
        store.add("security_deposit.deposit_months", 2 + i % 3, "months_of_rent")
        store.add("lock_in_period.lock_in_months", 6 + i % 7, "months")
        store.add("notice_period.notice_months", 1 + i % 3, "months")
    store.save(root)
    return root


@pytest.fixture(scope="module")
def pdfs(tmp_path_factory) -> dict[str, Path]:
    out = tmp_path_factory.mktemp("contracts")
    return {name: build(blocks, out / f"{name}.pdf") for name, blocks in contracts.ALL.items()}


def _run(pdfs, norms_root, name: str, role: Role, domain: Domain = LEASE):
    return analyse(
        str(pdfs[name]), role=role, domain=domain, norms_root=norms_root,
        corpus_version="test",
    )


def _ids(result) -> set[str]:
    return {f.clause_id for f in result.findings}


def test_fair_lease_is_quiet_for_the_tenant(pdfs, norms_root):
    """Every section is present and every term ordinary: nothing to report."""
    result = _run(pdfs, norms_root, "02_lease_fair", Role.TENANT)
    assert [f.headline for f in result.findings] == []


def test_the_role_changes_what_is_flagged(pdfs, norms_root):
    """The generous lease once gave identical output for tenant and landlord,
    because the clauses that differ by role were never recognised."""
    tenant = _run(pdfs, norms_root, "03_lease_generous_to_tenant", Role.TENANT)
    landlord = _run(pdfs, norms_root, "03_lease_generous_to_tenant", Role.LANDLORD)

    assert _ids(tenant) != _ids(landlord)
    # 15 days' notice for the tenant against 6 months for the landlord.
    assert any(f.evidence.asymmetry and f.clause_id.startswith("3.") for f in landlord.findings)
    # A half-month deposit is low, which is the landlord's problem, not the tenant's.
    assert "2.2" in _ids(landlord)
    assert "2.2" not in _ids(tenant)


def test_harsh_lease_flags_the_notice_imbalance_for_the_tenant_only(pdfs, norms_root):
    tenant = _run(pdfs, norms_root, "01_lease_harsh_on_tenant", Role.TENANT)
    landlord = _run(pdfs, norms_root, "01_lease_harsh_on_tenant", Role.LANDLORD)

    notice = next((f for f in tenant.findings if f.clause_id == "4.1"), None)
    assert notice is not None and notice.evidence.asymmetry
    assert "4.1" not in _ids(landlord)


def test_licence_fee_counts_as_rent(pdfs, norms_root):
    result = _run(pdfs, norms_root, "01_lease_harsh_on_tenant", Role.TENANT)
    assert "missing:rent_and_escalation" not in _ids(result)


def test_nothing_is_claimed_missing_from_an_unreadable_structure(pdfs, norms_root):
    """Unnumbered prose once produced eight "missing" findings about sections
    that are all there, just not numbered."""
    result = _run(pdfs, norms_root, "06_lease_unnumbered_prose", Role.TENANT)
    assert result.document.low_structure
    assert not any(f.evidence.missing_clause for f in result.findings)


def test_a_jurisdiction_clause_covers_dispute_resolution(pdfs, norms_root):
    """"Nothing about how disputes are settled" is false when the agreement names
    the courts that will hear them."""
    result = _run(pdfs, norms_root, "02_lease_fair", Role.TENANT)
    assert "missing:dispute_resolution" not in _ids(result)
    assert "missing:termination" not in _ids(result)


def test_job_offer_flags_the_notice_imbalance(pdfs, norms_root):
    result = _run(
        pdfs, norms_root, "07_job_offer_with_bond", Role.EMPLOYEE, Domain.EMPLOYMENT_OFFER
    )
    assert any(f.evidence.asymmetry for f in result.findings)


# ---------------------------------------------------------------- no-corpus rules
#
# A harsh lease once came back with two findings, because every term without
# comparison data was dropped in silence. These pin the four corpus-free legs:
# binding law, a unilateral arbitrator, declared thresholds, and the list of
# what could not be judged at all.


def _by_clause(result) -> dict[str, list]:
    out: dict[str, list] = {}
    for f in result.findings:
        out.setdefault(f.clause_id, []).append(f)
    return out


def test_harsh_lease_flags_its_rule_breaches_for_the_tenant(pdfs, norms_root):
    found = _by_clause(_run(pdfs, norms_root, "01_lease_harsh_on_tenant", Role.TENANT))

    assert "Perkins Eastern" in found["5.1"][0].evidence.rule_basis  # arbitrator
    assert found["3.2"][0].headline.startswith("The owner can enter")  # entry, no notice
    assert found["2.5"][0].evidence.rule_basis  # 5% a month late fee
    assert found["2.3"][0].evidence.rule_basis  # 120-day refund
    assert found["1.2"][0].headline == "Only you are locked in"
    # One finding per clause: the late fee is not also "runs only one way".
    assert all(len(v) == 1 for v in found.values()), found


def test_rules_protect_only_the_side_they_name(pdfs, norms_root):
    """The landlord chose the arbitrator and gains from entry without notice."""
    result = _run(pdfs, norms_root, "01_lease_harsh_on_tenant", Role.LANDLORD)
    assert not any(f.evidence.rule_basis for f in result.findings)
    assert "1.2" not in _ids(result)


def test_unjudgeable_terms_are_listed_not_dropped(pdfs, norms_root):
    result = _run(pdfs, norms_root, "01_lease_harsh_on_tenant", Role.TENANT)
    listed = {(u.clause_id, u.value) for u in result.unassessed}
    assert ("2.4", "15% a year") in listed  # rent rise: no data, law or rule
    flagged = _ids(result)
    assert not any(u.clause_id in flagged for u in result.unassessed)


def test_binding_law_stands_alone_where_it_applies(pdfs, norms_root):
    """In Assam the Model Tenancy Act binds, so the refund rule gives way to it."""
    result = analyse(
        str(pdfs["01_lease_harsh_on_tenant"]), role=Role.TENANT, domain=LEASE,
        norms_root=norms_root, corpus_version="test", user_state="Assam",
    )
    refund = _by_clause(result)["2.3"][0]
    assert refund.evidence.anchor is not None and refund.evidence.anchor.applies


def test_a_model_law_alone_does_not_flag_an_ordinary_refund(pdfs, norms_root):
    """Outside adopting states, "refund at handover" would flag every refund
    window - 30 days included. The fair lease must stay quiet."""
    result = analyse(
        str(pdfs["02_lease_fair"]), role=Role.TENANT, domain=LEASE,
        norms_root=norms_root, corpus_version="test", user_state="Karnataka",
    )
    assert result.findings == []


def test_job_offer_flags_the_non_compete_under_section_27(pdfs, norms_root):
    result = _run(
        pdfs, norms_root, "07_job_offer_with_bond", Role.EMPLOYEE, Domain.EMPLOYMENT_OFFER
    )
    noncompete = _by_clause(result)["4.1"][0]
    assert "s.27" in noncompete.evidence.anchor.source
    assert "commonly unenforceable" in noncompete.plain_language
    # The bond has no reference yet, and says so rather than vanishing.
    assert any(u.label.startswith("Service bond") for u in result.unassessed)


def test_figures_read_as_the_agreement_writes_them():
    from kwys.score.scorer import Scorer

    assert Scorer._fmt(300_000, "INR") == "Rs. 3,00,000"
    assert Scorer._fmt(1_92_00_000, "INR") == "Rs. 1,92,00,000"
    assert Scorer._fmt(5, "pct_per_month") == "5% a month"
