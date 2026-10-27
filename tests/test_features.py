"""The features built on top of the analysis: costs, dates, drafts, questions,
draft comparison and shared figures.

Each test pins a number or a behaviour a reader would act on, so a regression
shows up as a wrong rupee figure or a wrong date, not a vague failure.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

from kwys.models import Domain, Role
from kwys.pipeline import analyse

FIXTURES = Path(__file__).parent / "fixtures"
LEASE = FIXTURES / "sample_lease.pdf"

sys.path.insert(0, str(FIXTURES))
from contracts import EMPLOYMENT  # noqa: E402
from make_fixture import LEASE_REVISED, build  # noqa: E402


@pytest.fixture(scope="module")
def lease():
    return analyse(str(LEASE), role=Role.TENANT, domain=Domain.RESIDENTIAL_LEASE)


@pytest.fixture(scope="module")
def lease_facts(lease):
    from kwys.facts import gather

    return gather(lease, Role.TENANT)


@pytest.fixture(scope="module")
def offer(tmp_path_factory):
    path = build(EMPLOYMENT, tmp_path_factory.mktemp("offer") / "offer.pdf")
    return analyse(str(path), role=Role.EMPLOYEE, domain=Domain.EMPLOYMENT_OFFER)


# ------------------------------------------------------------------- facts


def test_facts_pick_the_readers_own_notice(lease_facts):
    """Six months binds the tenant; fifteen days binds the landlord."""
    assert lease_facts.notice_months.value == 6
    assert lease_facts.notice_months.clause_id == "4.1"
    assert lease_facts.their_notice_months.value == 0.5


def test_facts_find_term_and_dates(lease_facts):
    assert lease_facts.term_months.value == 11
    assert lease_facts.start_date.value == date(2026, 5, 1)
    assert lease_facts.signed_date.value == date(2026, 4, 5)
    assert lease_facts.rent_due_day.value == 5


def test_a_job_has_no_fixed_term(offer):
    """'Probation for a period of twelve months' is not the length of the job."""
    from kwys.facts import gather

    facts = gather(offer, Role.EMPLOYEE)
    assert facts.term_months is None
    assert facts.probation_months.value == 12
    assert facts.bond_amount.value == 300_000


@pytest.mark.parametrize(
    "text, expected, kind",
    [
        ("shall commence on 1st May 2026", date(2026, 5, 1), "start"),
        ("made at Pune on this 2nd day of June 2026", date(2026, 6, 2), "signed"),
        ("Your date of joining is 15/07/2026.", date(2026, 7, 15), "joining"),
        ("with effect from September 3, 2026", date(2026, 9, 3), "start"),
    ],
)
def test_dates_are_read_day_first_with_their_meaning(text, expected, kind):
    from kwys.extract.dates import find_dates

    found = find_dates(text)
    assert found and found[0].value == expected and found[0].kind == kind


def test_impossible_dates_are_ignored():
    from kwys.extract.dates import find_dates

    assert find_dates("dated 31/02/2026") == []


# ---------------------------------------------------------------- exposure


def test_leaving_cost_uses_the_worse_charge_not_both(lease_facts):
    """Remaining lock-in and notice in lieu cover the same months: never summed."""
    from kwys.exposure import build_exposure

    exp = build_exposure(lease_facts, Domain.RESIDENTIAL_LEASE, Role.TENANT)
    month1 = exp["schedule"][0]
    by_key = {line["key"]: line["amount"] for line in month1["lines"]}
    assert by_key["lock_in"] == 8 * 32_000  # 9-month lock-in, leaving after month 1
    assert by_key["notice"] == 6 * 32_000
    assert month1["atRisk"] == max(by_key.values())


def test_lock_in_line_disappears_once_it_has_run(lease_facts):
    from kwys.exposure import build_exposure

    exp = build_exposure(lease_facts, Domain.RESIDENTIAL_LEASE, Role.TENANT)
    month10 = exp["schedule"][9]
    assert {line["key"] for line in month10["lines"]} == {"notice"}


def test_deposit_and_late_fee_are_priced(lease_facts):
    from kwys.exposure import build_exposure

    exp = build_exposure(lease_facts, Domain.RESIDENTIAL_LEASE, Role.TENANT)
    assert exp["depositHeld"] == {"amount": 192_000, "clauseId": "2.2", "days": 180}
    assert exp["lateFee"]["amount"] == 960  # 3% of 32,000


def test_no_cost_schedule_for_the_landlord(lease_facts):
    from kwys.exposure import build_exposure

    assert build_exposure(lease_facts, Domain.RESIDENTIAL_LEASE, Role.LANDLORD) is None


def test_bond_shows_full_and_pro_rata(offer):
    from kwys.exposure import build_exposure
    from kwys.facts import gather

    exp = build_exposure(gather(offer, Role.EMPLOYEE), Domain.EMPLOYMENT_OFFER, Role.EMPLOYEE)
    bond = next(line for line in exp["schedule"][11]["lines"] if line["key"] == "bond")
    assert bond["amount"] == 300_000
    assert bond["proRata"] == 200_000  # 12 of 36 months served
    # Salary is the reader's to enter; it is never computed or sent.
    notice = next(line for line in exp["schedule"][0]["lines"] if line["key"] == "notice")
    assert notice["amount"] is None and notice["salaryMonths"] == 3


# ---------------------------------------------------------------- timeline


def test_timeline_dates(lease_facts):
    from kwys.timeline import build_timeline

    tl = build_timeline(lease_facts, Domain.RESIDENTIAL_LEASE)
    by_label = {e["label"]: e for e in tl["events"]}
    assert by_label["Agreement starts"]["date"] == "2026-05-01"
    assert by_label["Agreement ends"]["date"] == "2027-03-31"
    assert by_label["Lock-in ends"]["date"] == "2027-02-01"
    # Six months before the end, a day early to be safe.
    assert by_label["Last day to give notice"]["date"] == "2026-09-30"
    assert by_label["Deposit due back"]["date"] == "2027-09-27"
    assert not by_label["Last day to give notice"]["stated"]
    assert tl["recurring"]["dayOfMonth"] == 5


def test_rise_after_an_eleven_month_term_is_on_renewal(lease_facts):
    from kwys.timeline import build_timeline

    tl = build_timeline(lease_facts, Domain.RESIDENTIAL_LEASE)
    rise = next(e for e in tl["events"] if e["label"].startswith("Rent rises"))
    assert "renewed" in rise["basis"]


# ------------------------------------------------------------- negotiation


def test_every_lease_finding_gets_wording(lease, lease_facts):
    from kwys.negotiate import suggest

    for f in lease.findings:
        wording = suggest(f, lease_facts, Domain.RESIDENTIAL_LEASE, Role.TENANT, "Bengaluru")
        assert wording, f.headline


def test_wording_is_written_for_the_readers_side(lease, lease_facts):
    from kwys.negotiate import suggest

    entry = next(f for f in lease.findings if "enter" in f.headline)
    wording = suggest(entry, lease_facts, Domain.RESIDENTIAL_LEASE, Role.TENANT)
    assert "Landlord may enter" in wording and "24 hours" in wording


def test_terms_of_service_get_no_invented_wording(lease, lease_facts):
    from kwys.negotiate import suggest

    assert suggest(lease.findings[0], lease_facts, Domain.CONSUMER_TOS, Role.CONSUMER) is None


# ---------------------------------------------------------------------- ask


@pytest.fixture(scope="module")
def lease_clauses(lease):
    from kwys.ask import AskClause

    return [AskClause(c.id, c.text, c.clause_type) for c in lease.document.clauses]


@pytest.mark.parametrize(
    "question, clause_id",
    [
        ("Can I sublet?", "3.2"),
        ("When do I get my deposit back?", "2.2"),
        ("What happens if I pay rent late?", "2.5"),
        ("Can the landlord come in without telling me?", "3.3"),
        ("Who fixes things if they break?", "3.1"),
    ],
)
def test_questions_find_their_clause(lease_clauses, question, clause_id):
    from kwys.ask import answer

    out = answer(question, lease_clauses, Domain.RESIDENTIAL_LEASE)
    assert not out["silent"]
    assert clause_id in [a["clauseId"] for a in out["answers"]]


@pytest.mark.parametrize("question", ["Can I keep a dog?", "Is there parking?"])
def test_silence_is_reported_not_papered_over(lease_clauses, question):
    """The agreement says nothing about pets; a near-miss is not an answer."""
    from kwys.ask import answer

    assert answer(question, lease_clauses, Domain.RESIDENTIAL_LEASE)["silent"]


# ----------------------------------------------------------------- compare


@pytest.fixture(scope="module")
def diff(lease, tmp_path_factory):
    from kwys.compare import compare
    from kwys.facts import gather

    path = build(LEASE_REVISED, tmp_path_factory.mktemp("rev") / "revised.pdf")
    new = analyse(str(path), role=Role.TENANT, domain=Domain.RESIDENTIAL_LEASE)
    return compare(lease, new, gather(lease, Role.TENANT), gather(new, Role.TENANT), Role.TENANT)


def test_compare_judges_each_change_for_the_reader(diff):
    changes = {f["key"]: f["change"] for f in diff["figures"]}
    assert changes["deposit_months"] == "better"  # 6 -> 3
    assert changes["refund_days"] == "better"  # 180 -> 30
    assert changes["lock_in_months"] == "worse"  # 9 -> 11


def test_compare_reports_resolved_findings(diff):
    resolved = [f["headline"] for f in diff["findings"]["resolved"]]
    assert "The owner can enter with little or no notice" in resolved


def test_compare_matches_clauses_by_wording_not_number(diff):
    """The new 3.3 (pets) is not a rewording of the old 3.3 (entry)."""
    assert [c["id"] for c in diff["clauses"]["added"]] == ["3.3"]
    assert [c["id"] for c in diff["clauses"]["removed"]] == ["3.3"]
    assert "pets" in diff["clauses"]["added"][0]["text"]
    assert {m["newId"] for m in diff["clauses"]["modified"]} == {"1.2", "2.2", "2.3"}


# ------------------------------------------------------------ contributions


def test_contribution_is_coarsened_and_city_checked():
    from kwys.contribute import clean

    out = clean(
        "residential_lease",
        [
            {"key": "rent_and_escalation.monthly_rent_inr", "value": 32_400},
            {"key": "security_deposit.deposit_months", "value": 5.8},
        ],
        "12 MG Road, Flat 4B",
    )
    assert out["figures"]["rent_and_escalation.monthly_rent_inr"] == 32_000
    assert out["figures"]["security_deposit.deposit_months"] == 6.0
    assert out["city"] is None, "free text is where an address ends up; it is dropped"


@pytest.mark.parametrize(
    "figures",
    [
        [],
        [{"key": "security_deposit.deposit_months", "value": 400}],
        [{"key": "clause_text", "value": 1}],
        [{"key": "security_deposit.deposit_months", "value": "six"}],
    ],
)
def test_bad_contributions_are_refused(figures):
    from kwys.contribute import Rejected, clean

    with pytest.raises(Rejected):
        clean("residential_lease", figures, None)


def test_contributions_dedupe_and_build_their_own_corpus(tmp_path):
    from kwys.contribute import CONTRIBUTED_VERSION, ContributionStore, build_store, clean

    store = ContributionStore(tmp_path / "c.sqlite")
    fig = [{"key": "security_deposit.deposit_months", "value": 3}]
    assert store.add(clean("residential_lease", fig, "Pune"))
    assert not store.add(clean("residential_lease", fig, "Pune")), "same report twice"
    norms = build_store(store, Domain.RESIDENTIAL_LEASE)
    assert norms.version == CONTRIBUTED_VERSION
    assert norms.corpus_bias and "Self-reported" in norms.corpus_bias


def test_contributed_corpus_never_becomes_the_default(tmp_path):
    from kwys.norms.store import NormStore, default_version

    for version in ("contributed-v1", "judgments-v1"):
        s = NormStore("residential_lease", version)
        s.add("notice_period.notice_months", 1, "months")
        s.save(tmp_path)
    assert default_version(tmp_path, "residential_lease") == "judgments-v1"


# ------------------------------------------------------------- employment


def test_employment_judgment_patterns():
    from kwys.harvest.judgments import (
        EMPLOYMENT_BOUNDS,
        EMPLOYMENT_PATTERNS,
        Judgment,
        extract_values,
    )

    text = (
        "The appointment letter stated a probation period of six months. The "
        "petitioner executed a service bond of Rs. 2,00,000/- agreeing to serve the "
        "company for a minimum period of three years, and either side could "
        "terminate by giving three months notice."
    )
    got = {
        v.field: v.value
        for v in extract_values(Judgment("1", "t", text), EMPLOYMENT_PATTERNS, EMPLOYMENT_BOUNDS)
    }
    assert got == {
        "bond_amount_inr": 200_000,
        "bond_months": 36,  # three years, in months
        "notice_months": 3,
        "probation_months": 6,
    }
