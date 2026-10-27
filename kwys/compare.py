"""What changed between two drafts of the same agreement, and for whom.

Negotiation happens in rounds, and the second draft is the one nobody reads
closely. Three views of the change:

- the key figures, each judged better or worse FOR THE READER;
- the findings, resolved or newly raised;
- the clauses, matched across drafts by wording, as added, removed or reworded.

Clause numbering is not trusted for matching: inserting one clause renumbers
everything after it. Clauses are paired by text similarity instead.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

from kwys.facts import Facts
from kwys.models import AnalysisResult, Finding, Role

# Key figures worth comparing: (label, unit, +1 if larger is worse for the
# weaker party). The stronger party reads every direction reversed.
FIGURES: dict[str, tuple[str, str, int]] = {
    "monthly_rent": ("Monthly rent", "INR", +1),
    "deposit_inr": ("Security deposit", "INR", +1),
    "deposit_months": ("Deposit, in months of rent", "months", +1),
    "lock_in_months": ("Lock-in", "months", +1),
    "notice_months": ("Notice you must give", "months", +1),
    "their_notice_months": ("Notice they must give", "months", -1),
    "term_months": ("Length of the agreement", "months", 0),
    "escalation_pct": ("Annual rent increase", "%", +1),
    "late_fee_pct": ("Late-payment charge", "% a month", +1),
    "refund_days": ("Days to refund the deposit", "days", +1),
    "bond_months": ("Bond period", "months", +1),
    "bond_amount": ("Bond amount", "INR", +1),
    "probation_months": ("Probation", "months", +1),
    "noncompete_months": ("Non-compete after leaving", "months", +1),
}

WEAKER = {Role.TENANT, Role.EMPLOYEE, Role.CONSUMER}

SAME = 0.97  # at or above: the same clause, unchanged in substance
MATCH = 0.55  # at or above: the same clause, reworded


def _finding_key(f: Finding) -> tuple:
    """What a finding is ABOUT, independent of clause numbers and figures."""
    ev = f.evidence
    return (
        ev.clause_type,
        ev.field,
        ev.missing_clause,
        ev.asymmetry,
        bool(ev.rule_basis),
        ev.venue_distance_km is not None,
        tuple(ev.unfair_types),
    )


def _figures(old: Facts, new: Facts, role: Role) -> list[dict[str, Any]]:
    flip = 1 if role in WEAKER else -1
    out = []
    for name, (label, unit, worse_if_larger) in FIGURES.items():
        a, b = getattr(old, name), getattr(new, name)
        if a is None and b is None:
            continue
        va = float(a.value) if a else None
        vb = float(b.value) if b else None
        if va is not None and vb is not None and abs(va - vb) < 1e-9:
            continue
        if va is None:
            change = "added"
        elif vb is None:
            change = "removed"
        elif worse_if_larger == 0:
            change = "changed"
        else:
            worse = (vb > va) == (worse_if_larger * flip > 0)
            change = "worse" if worse else "better"
        out.append({
            "key": name,
            "label": label,
            "unit": unit,
            "old": va,
            "new": vb,
            "oldClause": a.clause_id if a else None,
            "newClause": b.clause_id if b else None,
            "change": change,
        })
    return out


def _clauses(old: AnalysisResult, new: AnalysisResult) -> dict[str, Any]:
    olds = [c for c in old.document.clauses if c.text.strip()]
    news = [c for c in new.document.clauses if c.text.strip()]

    # Every pair's similarity, then greedy best-first: the closest pairs are the
    # surest, and claiming them first keeps a reworded clause from being stolen
    # by a merely similar neighbour.
    pairs = []
    for i, a in enumerate(olds):
        for j, b in enumerate(news):
            sm = SequenceMatcher(None, a.text, b.text, autojunk=False)
            if sm.real_quick_ratio() < MATCH or sm.quick_ratio() < MATCH:
                continue
            r = sm.ratio()
            if r >= MATCH:
                pairs.append((r, i, j))
    pairs.sort(reverse=True)

    used_old: set[int] = set()
    used_new: set[int] = set()
    modified, unchanged = [], 0
    for r, i, j in pairs:
        if i in used_old or j in used_new:
            continue
        used_old.add(i)
        used_new.add(j)
        if r >= SAME:
            unchanged += 1
        else:
            modified.append({
                "oldId": olds[i].id,
                "newId": news[j].id,
                "similarity": round(r, 2),
                "oldText": olds[i].text,
                "newText": news[j].text,
            })

    modified.sort(key=lambda m: next(k for k, c in enumerate(news) if c.id == m["newId"]))
    return {
        "modified": modified,
        "added": [{"id": c.id, "text": c.text} for k, c in enumerate(news) if k not in used_new],
        "removed": [{"id": c.id, "text": c.text} for k, c in enumerate(olds) if k not in used_old],
        "unchanged": unchanged,
    }


def compare(
    old: AnalysisResult, new: AnalysisResult, old_facts: Facts, new_facts: Facts, role: Role
) -> dict[str, Any]:
    old_keys = {_finding_key(f): f for f in old.findings}
    new_keys = {_finding_key(f): f for f in new.findings}

    def brief(f: Finding) -> dict[str, str]:
        return {"headline": f.headline, "severity": f.severity.value, "clauseId": f.clause_id}

    return {
        "figures": _figures(old_facts, new_facts, role),
        "findings": {
            "resolved": [brief(f) for k, f in old_keys.items() if k not in new_keys],
            "raised": [brief(f) for k, f in new_keys.items() if k not in old_keys],
            "remaining": [brief(f) for k, f in new_keys.items() if k in old_keys],
        },
        "clauses": _clauses(old, new),
    }
