"""Suggested replacement wording for each finding.

Deterministic templates, keyed by what the finding rests on. Target values come
from the finding's own evidence - the corpus median, the statutory figure, the
line a declared rule draws - never from a model's guess. A finding with no
template gets no wording: its question still stands, and inventing contract
language for a case nobody has written a template for is how a tool like this
ends up recommending something harmful.

The wording is a starting point for a conversation, not drafting advice, and
the interface says so.
"""

from __future__ import annotations

import math

from kwys import config as C
from kwys.facts import Facts
from kwys.models import Domain, Finding, Role

# What each side is called in suggested wording. Generic on purpose: the
# reader replaces these with the defined terms their own agreement uses.
PARTY_NOUNS: dict[Role, str] = {
    Role.TENANT: "Tenant",
    Role.LANDLORD: "Landlord",
    Role.EMPLOYEE: "Employee",
    Role.EMPLOYER: "Company",
    Role.CONSUMER: "User",
    Role.PROVIDER: "Company",
}

_OTHER = {
    Role.TENANT: Role.LANDLORD, Role.LANDLORD: Role.TENANT,
    Role.EMPLOYEE: Role.EMPLOYER, Role.EMPLOYER: Role.EMPLOYEE,
    Role.CONSUMER: Role.PROVIDER, Role.PROVIDER: Role.CONSUMER,
}


def _num(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:.1f}".rstrip("0").rstrip(".")


def _months(x: float) -> str:
    """Possessive, as in "2 months' notice" / "1 month's notice"."""
    if x < 1:
        return f"{round(x * 30)} days'"
    return "1 month's" if x == 1 else f"{_num(x)} months'"


def _round_months(x: float) -> float:
    """A negotiable figure: whole months, half a month at the bottom."""
    return max(0.5, round(x * 2) / 2) if x < 2 else float(math.floor(x + 0.5))


def _inr(x: float) -> str:
    """Indian digit grouping: 1,92,000."""
    s = str(int(round(x)))
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups + [tail])


def suggest(
    finding: Finding,
    facts: Facts,
    domain: Domain,
    role: Role,
    user_city: str | None = None,
) -> str | None:
    """Suggested replacement wording for one finding, or None."""
    me = PARTY_NOUNS[role]
    them = PARTY_NOUNS[_OTHER[role]]
    ev = finding.evidence
    lease = domain is Domain.RESIDENTIAL_LEASE

    if domain is Domain.CONSUMER_TOS:
        return None  # standard terms are not negotiated clause by clause

    # ---- a figure, judged against the corpus, the law or a declared rule
    target: float | None = None
    if ev.norm is not None and ev.norm.sufficient:
        target = ev.norm.median
    elif ev.anchor is not None:
        target = ev.anchor.value
    field = ev.field or ""

    if field.endswith("deposit_months"):
        t = _round_months(target if target is not None else 2)
        amount = (
            f" (Rs. {_inr(t * float(facts.monthly_rent.value))})" if facts.monthly_rent else ""
        )
        return (
            f"The {me} shall pay a refundable, interest-free security deposit of "
            f"{_months(t)} rent{amount}, to be returned in full on "
            f"handover, less only documented costs of damage beyond normal wear and tear."
        )

    if field.endswith("notice_months") or finding.headline.startswith("One side gets far"):
        t = _round_months(target if target is not None else 1)
        if lease:
            return (
                f"Either party may terminate this agreement by giving the other "
                f"{_months(t)} written notice."
            )
        return (
            f"Either party may end the employment by giving the other {_months(t)} "
            f"written notice, or salary in lieu of the notice period."
        )

    if field.endswith("lock_in_months"):
        t = _round_months(target if target is not None else 6)
        return (
            f"The lock-in period shall be {_num(t)} months and shall bind both parties "
            f"equally: neither may terminate before it ends, except for a material "
            f"breach by the other."
        )

    if field.endswith("refund_days"):
        return (
            f"The {them} shall refund the security deposit within 30 days of the {me} "
            f"handing over vacant possession, after deducting only documented costs of "
            f"damage beyond normal wear and tear, with an itemised statement of any "
            f"deduction."
        )

    if field.endswith("late_fee_pct"):
        return (
            f"If rent is paid more than 7 days after its due date, the {me} shall pay "
            f"simple interest at 1% per month on the overdue amount, for the period of "
            f"delay only."
        )

    if field.endswith("notice_hours"):
        return (
            f"The {them} may enter the premises only at reasonable times and with at "
            f"least 24 hours' prior written notice to the {me}, except in an emergency."
        )

    if field.endswith("escalation_pct"):
        t = target if target is not None else 5
        return f"The rent may be increased by not more than {_num(t)}% on each renewal."

    if field.endswith("bond_months") or field.endswith("bond_amount_inr"):
        months = (
            _round_months(target) if field.endswith("bond_months") and target else None
        )
        span = f"{_num(months)} months" if months else "the bond period"
        return (
            f"If the {me} leaves within {span}, the amount recoverable shall not exceed "
            f"the actual, documented cost of training provided, and shall reduce pro "
            f"rata for each completed month of service."
        )

    if field.endswith("probation_months"):
        t = _round_months(target if target is not None else 6)
        return (
            f"The probation period shall be {_num(t)} months, and may be extended only "
            f"once, in writing, with reasons."
        )

    if field.endswith("noncompete_months"):
        return (
            f"After the employment ends, the {me} shall be free to take up any "
            f"employment or business. This does not affect the {me}'s duty to keep the "
            f"{them}'s confidential information confidential."
        )

    # ---- structural: who decides disputes, and where
    if ev.clause_type == "dispute_resolution" and ev.rule_basis:
        seat = f" The seat of arbitration shall be {user_city}." if user_city else ""
        return (
            "Any dispute shall be referred to a sole arbitrator appointed jointly by "
            "both parties or, failing agreement within 30 days, appointed under "
            f"Section 11 of the Arbitration and Conciliation Act, 1996.{seat}"
        )

    if ev.venue_distance_km is not None:
        place = user_city or (
            "the city where the property is located" if lease else "the city where the "
            f"{me} works"
        )
        return (
            f"The courts at {place} shall have jurisdiction, and any arbitration shall "
            f"be seated there."
        )

    # ---- structural: a duty that binds one side only
    if ev.asymmetry and ev.clause_type == "lock_in_period":
        n = _num(float(facts.lock_in_months.value)) if facts.lock_in_months else "the"
        span = f"{n}-month" if facts.lock_in_months else "the"
        return (
            f"The {span} lock-in shall bind both parties equally: neither may terminate "
            f"before it ends, except for a material breach by the other."
        )
    if ev.asymmetry:
        return (
            f"The obligations in this clause shall apply equally to the {me} and the "
            f"{them}."
        )

    # ---- something that should be there and is not
    if ev.missing_clause:
        return _MISSING.get(ev.clause_type, lambda me, them: None)(me, them)

    return None


_MISSING = {
    "deposit_refund": lambda me, them: (
        f"The {them} shall refund the security deposit within 30 days of the {me} "
        f"handing over vacant possession, less only documented costs of damage beyond "
        f"normal wear and tear."
    ),
    "notice_period": lambda me, them: (
        "Either party may terminate this agreement by giving the other one month's "
        "written notice."
    ),
    "termination": lambda me, them: (
        "Either party may terminate this agreement for a material breach by the "
        "other that is not remedied within 15 days of written notice of it."
    ),
    "maintenance_and_repairs": lambda me, them: (
        f"The {them} shall carry out structural and major repairs at their own cost. "
        f"The {me} shall carry out minor day-to-day repairs."
    ),
    "dispute_resolution": lambda me, them: (
        "Any dispute shall first be discussed in good faith and, failing settlement "
        "within 30 days, referred to a sole arbitrator appointed jointly by both "
        "parties."
    ),
    "probation": lambda me, them: (
        "The probation period shall be 6 months, and may be extended only once, in "
        "writing, with reasons."
    ),
    "confidentiality": lambda me, them: (
        "Each party shall keep the other's confidential information confidential, "
        "during the employment and for 2 years after it ends."
    ),
}


def label_for(finding: Finding) -> str:
    """A short name for the ask, for the message builder's checklist."""
    ev = finding.evidence
    if ev.missing_clause:
        return f"Add: {C.display_name(ev.clause_type).lower()}"
    return finding.headline
