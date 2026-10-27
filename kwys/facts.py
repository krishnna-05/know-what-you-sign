"""The agreement's key figures, picked once for every feature that needs them.

The cost calculator, the timeline and the negotiation drafts all ask the same
questions - what is the rent, whose notice is six months, when does it start -
and must get the same answers the findings were built on. Each figure keeps the
clause it came from and the words it was read from, so every number shown
downstream can be traced back to the document.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date

from kwys.extract.dates import find_dates, find_term_months
from kwys.models import AnalysisResult, Domain, Role


@dataclass
class Fact:
    value: float | str | date
    clause_id: str
    raw: str


@dataclass
class Facts:
    # residential lease
    monthly_rent: Fact | None = None
    deposit_inr: Fact | None = None
    deposit_months: Fact | None = None
    lock_in_months: Fact | None = None
    escalation_pct: Fact | None = None
    late_fee_pct: Fact | None = None
    refund_days: Fact | None = None
    rent_due_day: Fact | None = None
    # either domain
    notice_months: Fact | None = None  # the notice the READER must give
    their_notice_months: Fact | None = None  # the notice the other side must give
    term_months: Fact | None = None
    signed_date: Fact | None = None
    start_date: Fact | None = None
    # employment
    bond_months: Fact | None = None
    bond_amount: Fact | None = None
    probation_months: Fact | None = None
    noncompete_months: Fact | None = None
    unresolved: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        out = {}
        for k, v in asdict(self).items():
            if k == "unresolved" or v is None:
                continue
            value = v["value"]
            out[k] = {
                "value": value.isoformat() if isinstance(value, date) else value,
                "clauseId": v["clause_id"],
                "raw": v["raw"],
            }
        return out


_SIMPLE = {
    "monthly_rent_inr": "monthly_rent",
    "deposit_inr": "deposit_inr",
    "deposit_months": "deposit_months",
    "lock_in_months": "lock_in_months",
    "escalation_pct": "escalation_pct",
    "late_fee_pct": "late_fee_pct",
    "refund_days": "refund_days",
    "bond_months": "bond_months",
    "bond_amount_inr": "bond_amount",
    "probation_months": "probation_months",
    "noncompete_months": "noncompete_months",
}

# "on or before the 5th day of each month"
_DUE_DAY = re.compile(
    r"(?:on\s+or\s+)?before\s+the\s+(\d{1,2})(?:st|nd|rd|th)?\s+(?:day\s+)?of\s+(?:each|every)",
    re.I,
)


def gather(result: AnalysisResult, role: Role) -> Facts:
    """Pick each key figure from the analysis, preferring the reader's own."""
    facts = Facts()
    notice_is_readers = False  # True once a notice clause binding the reader is seen

    for ct in result.extracted:
        for term in ct.terms:
            if not isinstance(term.value, int | float) or isinstance(term.value, bool):
                continue
            if term.field == "notice_months":
                fact = Fact(float(term.value), ct.clause_id, term.raw)
                # A notice period belongs to whoever must give it. One that
                # binds nobody in particular stands in for the reader's only
                # until a clause that names them is found.
                if ct.bound is role and not notice_is_readers:
                    facts.notice_months, notice_is_readers = fact, True
                elif ct.bound is None and facts.notice_months is None:
                    facts.notice_months = fact
                elif ct.bound not in (None, role) and facts.their_notice_months is None:
                    facts.their_notice_months = fact
                continue
            # Rent is the first one stated: later mentions are usually the
            # escalated figure.
            name = _SIMPLE.get(term.field)
            if name and getattr(facts, name) is None:
                setattr(facts, name, Fact(float(term.value), ct.clause_id, term.raw))

    # Only a lease has a fixed length. In a job offer "a period of twelve months"
    # is the probation or the bond, never the length of the employment.
    fixed_term = result.document.domain is Domain.RESIDENTIAL_LEASE
    for clause in result.document.clauses:
        if fixed_term and facts.term_months is None and clause.clause_type in (None, "other"):
            found = find_term_months(clause.text)
            if found:
                facts.term_months = Fact(found[0], clause.id, found[1])
        for d in find_dates(clause.text):
            if d.kind in ("start", "joining") and facts.start_date is None:
                facts.start_date = Fact(d.value, clause.id, d.raw)
            elif d.kind == "signed" and facts.signed_date is None:
                facts.signed_date = Fact(d.value, clause.id, d.raw)
        if facts.rent_due_day is None and clause.clause_type == "rent_and_escalation":
            m = _DUE_DAY.search(clause.text)
            if m and 1 <= int(m.group(1)) <= 28:
                facts.rent_due_day = Fact(float(m.group(1)), clause.id, m.group(0))

    return facts
