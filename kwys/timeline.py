"""The dates that matter, stated or worked out from the figures.

A stated date is quoted from the document. A derived one - "last day to give
notice" - is computed, and says what from, because an off-by-one in a notice
deadline is exactly the kind of error a reader cannot see.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from dateutil.relativedelta import relativedelta

from kwys.facts import Facts
from kwys.models import Domain


def _add_months(d: date, months: float) -> date:
    whole = int(months)
    rest_days = round((months - whole) * 30)
    return d + relativedelta(months=whole) + timedelta(days=rest_days)


def _fmt_months(x: float) -> str:
    if x < 1:
        return f"{round(x * 30)} days"
    v = int(x) if float(x).is_integer() else round(x, 1)
    return f"{v} month{'s' if v != 1 else ''}"


def build_timeline(facts: Facts, domain: Domain) -> dict[str, Any]:
    events: list[dict[str, Any]] = []

    def add(label: str, when: date, clause_id: str, basis: str, stated: bool, kind: str) -> None:
        events.append({
            "label": label,
            "date": when.isoformat(),
            "clauseId": clause_id,
            "basis": basis,
            "stated": stated,
            "kind": kind,  # milestone / deadline / money
        })

    if facts.signed_date:
        add("Signed", facts.signed_date.value, facts.signed_date.clause_id,
            f"“{facts.signed_date.raw}”", True, "milestone")

    start = facts.start_date
    employment = domain is Domain.EMPLOYMENT_OFFER

    if start:
        s: date = start.value  # type: ignore[assignment]
        add("You join" if employment else "Agreement starts", s, start.clause_id,
            f"“{start.raw}”", True, "milestone")

        if employment:
            if facts.probation_months:
                n = float(facts.probation_months.value)
                add("Probation ends", _add_months(s, n), facts.probation_months.clause_id,
                    f"{_fmt_months(n)} after joining", False, "milestone")
            if facts.bond_months:
                n = float(facts.bond_months.value)
                add("Bond ends", _add_months(s, n), facts.bond_months.clause_id,
                    f"{_fmt_months(n)} after joining; leaving before this may "
                    "trigger the bond", False, "deadline")
        else:
            if facts.lock_in_months:
                n = float(facts.lock_in_months.value)
                add("Lock-in ends", _add_months(s, n), facts.lock_in_months.clause_id,
                    f"{_fmt_months(n)} after the start; the earliest you can leave "
                    "without breaching it", False, "deadline")
            if facts.escalation_pct:
                pct = float(facts.escalation_pct.value)
                # An 11-month agreement never reaches its own first increase;
                # it only bites if the agreement is renewed.
                renewal = facts.term_months is not None and float(facts.term_months.value) <= 12
                add(f"Rent rises {pct:g}%", _add_months(s, 12), facts.escalation_pct.clause_id,
                    "One year after the start, if the agreement is renewed"
                    if renewal else "One year after the start", False, "money")

            if facts.term_months:
                n = float(facts.term_months.value)
                end = _add_months(s, n) - timedelta(days=1)
                add("Agreement ends", end, facts.term_months.clause_id,
                    f"{_fmt_months(n)} from the start", False, "milestone")
                if facts.notice_months:
                    k = float(facts.notice_months.value)
                    deadline = _add_months(end + timedelta(days=1), -k) - timedelta(days=1)
                    if deadline >= s:
                        add("Last day to give notice", deadline,
                            facts.notice_months.clause_id,
                            f"{_fmt_months(k)} before the agreement ends, if you "
                            "will leave then", False, "deadline")
                if facts.refund_days:
                    d = int(facts.refund_days.value)
                    add("Deposit due back", end + timedelta(days=d),
                        facts.refund_days.clause_id,
                        f"Within {d} days of the end, if you hand over then",
                        False, "money")

    events.sort(key=lambda e: e["date"])

    recurring = None
    if facts.rent_due_day and not employment:
        recurring = {
            "label": "Rent due",
            "dayOfMonth": int(facts.rent_due_day.value),
            "clauseId": facts.rent_due_day.clause_id,
            "from": start.value.isoformat() if start else None,  # type: ignore[union-attr]
            "months": int(float(facts.term_months.value)) if facts.term_months else 12,
        }

    return {"events": events, "recurring": recurring, "hasStart": start is not None}
