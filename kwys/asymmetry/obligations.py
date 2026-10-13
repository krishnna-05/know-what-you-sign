"""Extracting who is bound to do what, and spotting one-sided duties.

Asymmetry is the commonest structural form of unfairness in consumer contracts
and it is invisible to a lay reader, because seeing it requires holding two
clauses forty pages apart in your head at once. "The Lessor may terminate on 15
days' notice; the Lessee shall give 6 months" reads as two ordinary sentences.

Two findings come out of this module:
  - a duty imposed on one side with no counterpart on the other
  - a MISSING clause: a protection that comparable agreements normally contain
    and this one simply does not. Absence is the risk a reader cannot notice,
    because there is nothing on the page to notice.
"""

from __future__ import annotations

import re

from kwys.asymmetry.parties import PartyMap
from kwys.models import Clause, Domain, Modality, Obligation, Role

# Deontic markers. Order matters: negatives must be tested before positives, or
# "shall not" is read as an obligation to do the thing it forbids.
_MARKERS: list[tuple[re.Pattern[str], Modality]] = [
    (re.compile(r"\bshall\s+not\b|\bmust\s+not\b|\bmay\s+not\b|\bshall\s+never\b", re.I),
     Modality.PROHIBITION),
    (re.compile(r"\bis\s+prohibited\b|\bis\s+forbidden\b|\bshall\s+refrain\b", re.I),
     Modality.PROHIBITION),
    (re.compile(r"\bshall\b|\bmust\b|\bis\s+required\s+to\b|\bis\s+liable\s+to\b"
                r"|\bundertakes\s+to\b|\bagrees\s+to\b", re.I),
     Modality.OBLIGATION),
    (re.compile(r"\bmay\b|\bis\s+entitled\s+to\b|\bshall\s+be\s+at\s+liberty\b"
                r"|\breserves\s+the\s+right\b|\bhas\s+the\s+right\b", re.I),
     Modality.RIGHT),
]

_SENTENCE = re.compile(r"(?<=[.;])\s+(?=[A-Z])")

# Clause types where a duty on one side normally has a mirror on the other.
# A duty here with no counterpart is structurally lopsided, not merely unusual.
MIRRORED_TYPES = {
    "notice_period": "notice before ending the agreement",
    # Deliberately neutral. This type covers both the RIGHT to terminate and the
    # duties that follow one, and labelling the whole type "the right to end the
    # agreement" produced nonsense on handover clauses: "only the tenant is
    # bound here on the right to end the agreement".
    "termination": "ending the agreement and what follows",
    "indemnity": "who compensates whom",
    "penalty_and_late_fee": "penalties for breach",
}


def extract_obligations(clause: Clause, pmap: PartyMap) -> list[Obligation]:
    """Find the deontic statements in a clause and attribute each to a party."""
    out: list[Obligation] = []
    for sentence in _SENTENCE.split(clause.text):
        sentence = sentence.strip()
        if len(sentence) < 15:
            continue

        modality = next((m for pat, m in _MARKERS if pat.search(sentence)), None)
        if modality is None:
            continue

        role = _bound_party(sentence, pmap)
        out.append(
            Obligation(
                clause_id=clause.id,
                role=role,
                modality=modality,
                predicate=_predicate(sentence),
                raw_sentence=sentence,
            )
        )
    return out


def _bound_party(sentence: str, pmap: PartyMap) -> Role | None:
    """Who is bound by this sentence?

    The subject is what matters, and in legal drafting the subject reliably
    precedes the modal. Where both parties appear before it — "the Lessee shall
    pay the Lessor" — the nearest preceding mention wins, which is the subject.
    Where neither appears, we return None rather than guessing: a wrong
    attribution inverts the risk direction and is worse than no attribution.
    """
    modal = re.search(r"\b(shall|must|may|is required to|agrees to|undertakes to)\b",
                      sentence, re.I)
    prefix = sentence[: modal.start()] if modal else sentence

    best: tuple[int, Role] | None = None
    for label, role in pmap.label_to_role.items():
        for m in re.finditer(rf"\b{re.escape(label)}\b", prefix.lower()):
            if best is None or m.start() > best[0]:
                best = (m.start(), role)
    return best[1] if best else None


def _predicate(sentence: str) -> str:
    """A short human-readable summary of what is required."""
    m = re.search(
        r"\b(?:shall|must|may|is required to|agrees to|undertakes to)\s+(?:not\s+)?(.{5,70})",
        sentence,
        re.I,
    )
    text = m.group(1) if m else sentence[:70]
    return re.sub(r"\s+", " ", text).strip(" .,;")


def find_asymmetries(
    clauses: list[Clause],
    obligations: list[Obligation],
    pmap: PartyMap,
    user_role: Role | None = None,
) -> list[tuple[str, str]]:
    """Duties on one side with no counterpart on the other.

    Returns (clause_id, human-readable explanation) pairs. Only clause types in
    MIRRORED_TYPES are checked: plenty of provisions are one-sided by their
    nature (a tenant does not indemnify themselves) and flagging those would
    bury the real findings in noise.

    `user_role` decides WHOSE one-sided duty is worth raising. An unmatched duty
    on the counterparty is not a risk to the reader - it is a protection. Without
    this the tool told a landlord "you must give six months' notice" about a
    clause binding the tenant, which is the opposite of true.
    """
    by_type: dict[str, dict[Role, list[Obligation]]] = {}
    clause_types = {c.id: c.clause_type for c in clauses}

    for ob in obligations:
        ctype = clause_types.get(ob.clause_id)
        if ctype not in MIRRORED_TYPES or ob.role is None:
            continue
        if ob.modality is Modality.RIGHT:
            continue  # a right on one side is not a duty needing a mirror
        by_type.setdefault(ctype, {}).setdefault(ob.role, []).append(ob)

    findings: list[tuple[str, str]] = []
    counterparty = pmap.counterparty_of

    for ctype, per_role in by_type.items():
        for role, obs in per_role.items():
            other = counterparty.get(role)
            if other is None or per_role.get(other):
                continue  # the mirror exists; nothing lopsided here
            if user_role is not None and role is not user_role:
                continue  # binds the other side: their problem, not the reader's
            subject = MIRRORED_TYPES[ctype]
            who = "You are" if role is user_role else f"Only the {role.value} is"
            findings.append(
                (
                    obs[0].clause_id,
                    f"{who} bound here on {subject}. "
                    f"No matching obligation on the {other.value} was found "
                    f"anywhere in the document.",
                )
            )
    return findings


# A protection can be provided by a clause of a neighbouring type. "Nothing
# about how disputes are settled" is false when a clause names the courts that
# will hear them, and "nothing about ending the agreement" is false when the
# notice clauses say how either side ends it.
COVERED_BY: dict[str, set[str]] = {
    "dispute_resolution": {"governing_law"},
    "termination": {"notice_period"},
}


def find_missing_clauses(clauses: list[Clause], domain: Domain) -> list[tuple[str, str]]:
    """Protections that comparable agreements normally contain and this one lacks."""
    from kwys import config as C

    present = {c.clause_type for c in clauses if c.clause_type}
    missing = [
        ct
        for ct in C.expected_clauses(domain)
        if ct not in present and not (COVERED_BY.get(ct, set()) & present)
    ]
    return [
        (
            ct,
            f"This agreement says nothing about {C.display_name(ct).lower()}. "
            f"Comparable agreements normally cover it.",
        )
        for ct in missing
    ]


# Fields where both sides normally carry a comparable figure. A lopsided PAIR is
# a far stronger finding than a missing one, and it is the single thing a lay
# reader is least able to spot: the two numbers sit pages apart and each looks
# unremarkable alone.
PAIRED_FIELDS = {
    "notice_months": "notice before ending the agreement",
    "cure_period_days": "time allowed to fix a problem",
}

# Ratios at or below this are not raised. 2:1 (tenant two months, landlord one)
# is the ordinary Indian pattern; flagging it would bury the genuinely lopsided
# cases in noise. The threshold is exclusive, so a 2x split stays quiet and a 3x
# one does not.
PAIR_RATIO_THRESHOLD = 2.0


def attribute_clause_to_party(clause: Clause, pmap: PartyMap) -> Role | None:
    """Whose figure is this clause stating?

    Uses the clause's own deontic sentences. A clause phrased as a right — "the
    Lessor MAY terminate by giving fifteen days notice" — still fixes the notice
    the Lessor must give, so rights count here even though they are excluded
    from the missing-mirror check.
    """
    obs = extract_obligations(clause, pmap)
    roles = [o.role for o in obs if o.role is not None]
    if not roles:
        return pmap.resolve(clause.text)
    # The first attributed sentence carries the clause's subject.
    return roles[0]


def find_paired_asymmetries(
    clause_terms: list[tuple[Clause, list]],
    pmap: PartyMap,
    user_role: Role | None = None,
) -> list[tuple[str, str, dict]]:
    """Compare the same field across both parties.

    `clause_terms` is [(clause, [Term, ...]), ...]. Returns
    (clause_id, explanation, detail) for each field where the two sides differ
    by more than PAIR_RATIO_THRESHOLD.

    `user_role` decides both the wording and whether the imbalance is raised at
    all. The heavier side of a lopsided pair is a burden for whoever carries it
    and an advantage for the other party; reporting "you must give six months"
    to the party who gives fifteen days is simply false.
    """
    # field -> role -> (value, clause_id, unit)
    collected: dict[str, dict[Role, tuple[float, str, str]]] = {}

    for clause, terms in clause_terms:
        role = attribute_clause_to_party(clause, pmap)
        if role is None:
            continue
        for term in terms:
            if term.field not in PAIRED_FIELDS:
                continue
            if not isinstance(term.value, (int, float)) or isinstance(term.value, bool):
                continue
            per_field = collected.setdefault(term.field, {})
            # Keep the largest figure per side: documents often restate a period,
            # and the longer one is what binds.
            existing = per_field.get(role)
            if existing is None or float(term.value) > existing[0]:
                per_field[role] = (float(term.value), clause.id, term.unit or "")

    out: list[tuple[str, str, dict]] = []
    for field_name, per_role in collected.items():
        if len(per_role) < 2:
            continue
        (role_a, (val_a, cid_a, unit)), (role_b, (val_b, cid_b, _)) = sorted(
            per_role.items(), key=lambda kv: kv[1][0], reverse=True
        )
        if val_b <= 0 or (val_a / val_b) <= PAIR_RATIO_THRESHOLD:
            continue

        subject = PAIRED_FIELDS[field_name]
        ratio = val_a / val_b

        # role_a carries the heavier obligation. Only raise it for the party who
        # actually bears it; for the other side this clause is an advantage.
        if user_role is not None and role_a is not user_role:
            continue

        heavier = "You" if role_a is user_role else f"The {role_a.value}"
        lighter = f"the {role_b.value}"
        out.append(
            (
                cid_a,
                (
                    f"{heavier} must give {_fmt_period(val_a, unit)} of {subject}, "
                    f"but {lighter} need only give {_fmt_period(val_b, unit)} "
                    f"(clause {cid_b}) — {ratio:.0f} times less."
                ),
                {
                    "field": field_name,
                    "ratio": round(ratio, 2),
                    role_a.value: val_a,
                    role_b.value: val_b,
                    "clauses": [cid_a, cid_b],
                },
            )
        )
    return out


def _fmt_period(value: float, unit: str) -> str:
    """Render a period the way a person would say it.

    Sub-month periods are expressed in days: "0.5 months" is how the pipeline
    stores it and not how anyone would ever say it.
    """
    if unit == "months" and 0 < value < 1:
        days = round(value * 30)
        return f"{days} day{'s' if days != 1 else ''}"
    singular = unit.rstrip("s")
    if value == int(value):
        n = int(value)
        return f"{n} {singular}{'s' if n != 1 else ''}"
    return f"{value:g} {unit}"
