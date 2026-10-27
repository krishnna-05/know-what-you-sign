"""What it costs to leave, month by month, in rupees.

"Six months' notice" is abstract; "₹1,92,000 if you leave without it" is not.
This turns the extracted figures into a schedule: for each month you might
leave in, the sums that could be charged, each traced to its clause.

HONESTY. An agreement often says that leaving early is a breach without saying
what the breach costs. Lines that rest on a common reading rather than a stated
figure are marked `kind="up_to"` and carry the assumption in `note`. Nothing is
computed from a figure that was not found: a missing input drops the line.
"""

from __future__ import annotations

import math
from typing import Any

from kwys.facts import Facts
from kwys.models import Domain, Role


def _inr(x: float) -> int:
    return int(round(x))


def _rent_at(facts: Facts, month: int) -> float | None:
    """Monthly rent in force during `month` (1-based), after any annual increase."""
    if facts.monthly_rent is None:
        return None
    rent = float(facts.monthly_rent.value)
    if facts.escalation_pct is not None:
        years = (month - 1) // 12
        rent *= (1 + float(facts.escalation_pct.value) / 100) ** years
    return rent


def build_exposure(facts: Facts, domain: Domain, role: Role) -> dict[str, Any] | None:
    """The leaving-cost schedule, or None when there is nothing to compute.

    Built for the weaker party - the tenant leaving, the employee resigning -
    since they are who pays these sums.
    """
    if domain is Domain.RESIDENTIAL_LEASE and role is Role.TENANT:
        return _lease(facts)
    if domain is Domain.EMPLOYMENT_OFFER and role is Role.EMPLOYEE:
        return _employment(facts)
    return None


def _lease(f: Facts) -> dict[str, Any] | None:
    if f.monthly_rent is None:
        return None  # every line here is priced in months of rent
    lock_in = float(f.lock_in_months.value) if f.lock_in_months else 0.0
    term = float(f.term_months.value) if f.term_months else 0.0
    horizon = max(1, math.ceil(max(term, lock_in, 12)))

    schedule = []
    for m in range(1, horizon + 1):
        rent = _rent_at(f, m) or 0.0
        lines = []
        if f.lock_in_months and m < lock_in:
            lines.append({
                "key": "lock_in",
                "label": "Rent for the rest of the lock-in",
                "amount": _inr((lock_in - m) * rent),
                "kind": "up_to",
                "clauseId": f.lock_in_months.clause_id,
                "note": f"If the agreement charges rent for the remaining "
                        f"{_months(lock_in - m, False)} of the lock-in.",
            })
        if f.notice_months:
            n = float(f.notice_months.value)
            lines.append({
                "key": "notice",
                "label": "Rent in lieu of notice",
                "amount": _inr(n * rent),
                "kind": "if_no_notice",
                "clauseId": f.notice_months.clause_id,
                "note": f"Only if you leave without giving {_months(n)} notice.",
            })
        # The remaining lock-in and the notice period cover the same months of
        # rent: charging both would bill one month twice. The larger is the
        # realistic worst case, not the sum.
        schedule.append({
            "month": m,
            "lines": lines,
            "atRisk": max((line["amount"] for line in lines), default=0),
        })

    held = None
    if f.deposit_inr:
        held = {
            "amount": _inr(float(f.deposit_inr.value)),
            "clauseId": f.deposit_inr.clause_id,
            "days": int(f.refund_days.value) if f.refund_days else None,
        }

    late = None
    if f.late_fee_pct:
        pct = float(f.late_fee_pct.value)
        late = {
            "pctPerMonth": pct,
            "amount": _inr(float(f.monthly_rent.value) * pct / 100),
            "clauseId": f.late_fee_pct.clause_id,
        }

    rent_by_year = []
    if f.escalation_pct:
        years = max(1, math.ceil(horizon / 12))
        rent_by_year = [
            {"year": y + 1, "rent": _inr(_rent_at(f, y * 12 + 1) or 0)} for y in range(years)
        ]

    return {
        "kind": "lease",
        "horizon": horizon,
        "lockInMonths": lock_in or None,
        "schedule": schedule,
        "depositHeld": held,
        "lateFee": late,
        "rentByYear": rent_by_year,
    }


def _employment(f: Facts) -> dict[str, Any] | None:
    if not (f.bond_months or f.bond_amount or f.notice_months):
        return None
    bond_m = float(f.bond_months.value) if f.bond_months else 0.0
    horizon = max(1, math.ceil(max(bond_m, 12)))

    schedule = []
    for m in range(1, horizon + 1):
        lines = []
        if f.bond_amount and (not bond_m or m < bond_m):
            full = float(f.bond_amount.value)
            pro_rata = full * (1 - m / bond_m) if bond_m else None
            lines.append({
                "key": "bond",
                "label": "Bond repayment",
                "amount": _inr(full),
                "proRata": _inr(pro_rata) if pro_rata is not None else None,
                "kind": "up_to",
                "clauseId": f.bond_amount.clause_id,
                "note": "The full amount, unless the bond reduces with time served."
                        if bond_m else "The bond does not state how long it runs.",
            })
        if f.notice_months:
            n = float(f.notice_months.value)
            # Priced in the browser: salary is the reader's to enter, and is
            # never sent anywhere.
            lines.append({
                "key": "notice",
                "label": "Salary in lieu of notice",
                "amount": None,
                "salaryMonths": n,
                "kind": "if_no_notice",
                "clauseId": f.notice_months.clause_id,
                "note": f"Only if you leave without serving {_months(n)} notice.",
            })
        schedule.append({
            "month": m,
            "lines": lines,
            "atRisk": sum(line["amount"] or 0 for line in lines),
        })

    return {
        "kind": "employment",
        "horizon": horizon,
        "bondMonths": bond_m or None,
        "schedule": schedule,
        "nonCompeteMonths": float(f.noncompete_months.value) if f.noncompete_months else None,
    }


def _months(x: float, possessive: bool = True) -> str:
    """ "6 months'" as in "6 months' notice"; "6 months" when not possessive."""
    mark = "'" if possessive else ""
    if x < 1:
        days = round(x * 30)
        return f"{days} day{'s' if days != 1 else ''}{mark}"
    v = int(x) if float(x).is_integer() else round(x, 1)
    return f"{v} month{'s' if v != 1 else ''}{mark}"
