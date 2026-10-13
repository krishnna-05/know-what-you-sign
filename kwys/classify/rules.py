"""Rule-based clause classifier — the baseline, and the cold-start path.

Two reasons this exists rather than going straight to a transformer:

  1. It makes the whole pipeline runnable on day one, before a single clause has
     been labelled. Everything downstream — extraction, norms, scoring, the
     report — can be built and tested against real output instead of stubs.
  2. It is the honest baseline for the evaluation. A transformer that cannot beat
     weighted keyword matching on 15 clause types has not earned its place in the
     system, and PLAN.md section 6 requires reporting exactly that comparison.

Scoring is weighted evidence, not first-match-wins: `notice` appears in both
notice-period and entry clauses, and the discriminating signal is which OTHER
terms occur alongside it. Ties and low totals fall through to `other`, which is
an honest abstention — a wrong type sends the wrong norm distribution
downstream, which is worse than no type at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from kwys.models import Clause, Domain

# (pattern, weight). Negative weights push AWAY from a type — they are how
# near-miss confusions get separated.
Rule = tuple[str, float]

RULES: dict[str, list[Rule]] = {
    "security_deposit": [
        (r"security\s+deposit", 3.0), (r"\bdeposit\b", 1.5),
        (r"interest[- ]free", 1.0), (r"advance\s+amount", 1.0),
        (r"refund", -0.5),  # a refund clause is its own type
    ],
    "deposit_refund": [
        (r"refund(?:ed|able)?\s+(?:to|within|at)", 3.0),
        (r"return(?:ed)?\s+the\s+(?:security\s+)?deposit", 3.0),
        (r"deduct", 1.2), (r"vacant\s+possession", 1.0),
    ],
    "lock_in_period": [
        (r"lock[- ]?in", 4.0), (r"minimum\s+period\s+of\s+(?:stay|tenancy)", 2.5),
        (r"shall\s+not\s+vacate", 2.0),
    ],
    "notice_period": [
        (r"(?:prior\s+)?(?:written\s+)?notice\s+of\s+(?:his|her|its|their)?\s*intention", 3.0),
        (r"notice\s+(?:period|to\s+quit)", 2.5),
        # A duration attached to "notice" is the defining feature, so it must
        # outweigh a TERMINATION heading inherited from the parent clause.
        (r"(?:months?|weeks?)\s+(?:prior\s+)?(?:written\s+)?notice", 3.5),
        (r"days?\s+(?:prior\s+)?(?:written\s+)?notice", 3.0),
        (r"notice\s+to\s+(?:vacate|terminate|quit|the\s+other)", 2.5),
        (r"vacate\s+(?:the\s+premises\s+)?by\s+giving", 2.5),
        # "may terminate ... by giving fifteen (15) days notice" fixes a notice
        # period; without this it ties with termination and abstains.
        (r"by\s+giving\s+.{0,40}?notice", 1.5),
        (r"intention\s+to\s+vacate", 2.0),
        (r"enter\s+and\s+inspect", -3.0),  # entry clauses also mention notice
    ],
    "termination": [
        (r"terminat(?:e|ion|ed)", 3.0), (r"determine\s+this\s+agreement", 2.0),
        (r"cure\s+period", 1.5), (r"breach", 1.0),
        (r"hand\s+over\s+vacant", 1.5),
    ],
    "rent_and_escalation": [
        (r"monthly\s+(?:rent|licen[cs]e\s+fee)", 3.0), (r"\brent\s+(?:of|shall\s+be)", 2.0),
        # Leave-and-licence agreements (standard in Maharashtra) call it this.
        (r"licen[cs]e\s+fee", 3.0),
        (r"enhanc|escalat|increas(?:e|ed)\s+by", 2.5),
        (r"payable\s+(?:on|before)", 1.0),
        (r"deposit", -1.0),
    ],
    "penalty_and_late_fee": [
        (r"interest\s+at\s+the\s+rate", 3.0), (r"late\s+(?:fee|payment|charge)", 3.0),
        (r"penalt(?:y|ies)", 2.5), (r"delay\s+in\s+payment", 2.5),
        (r"grace\s+period", 1.5),
    ],
    "maintenance_and_repairs": [
        (r"repair", 2.5), (r"maintenance|maintain", 2.0),
        (r"tenantable\s+condition", 3.0), (r"wear\s+and\s+tear", 2.0),
        (r"whitewash|painting", 1.5),
    ],
    "use_restrictions": [
        (r"shall\s+(?:only\s+)?use\s+the\s+(?:premises|property)", 2.5),
        (r"residential\s+purpose", 2.5), (r"unlawful|illegal\s+(?:purpose|activity)", 2.0),
        (r"nuisance", 2.0), (r"pets?\b", 1.5),
    ],
    "entry_and_inspection": [
        (r"enter\s+and\s+inspect", 4.0), (r"right\s+of\s+(?:entry|access)", 3.0),
        (r"inspect(?:ion)?\s+the\s+premises", 3.0),
        (r"(?:may|shall\s+be\s+entitled\s+to)\s+enter\s+the\s+premises", 3.0),
        (r"reasonable\s+times?", 1.0),
    ],
    "subletting": [
        (r"sub-?let", 4.0), (r"assign\s+or\s+part\s+with", 3.0),
        (r"part\s+with\s+possession", 3.0), (r"third\s+part(?:y|ies)", 1.0),
    ],
    "dispute_resolution": [
        (r"arbitrat(?:ion|or)", 4.0), (r"seat\s+of\s+arbitration", 3.0),
        (r"conciliation|mediat(?:ion|or)", 2.5),
        (r"Arbitration\s+and\s+Conciliation\s+Act", 3.0),
    ],
    "governing_law": [
        (r"governing\s+law", 3.5), (r"exclusive\s+jurisdiction", 3.5),
        (r"courts?\s+at\s+\w+\s+(?:alone\s+)?shall", 3.0),
        (r"subject\s+to\s+the\s+jurisdiction", 3.0),
        (r"arbitrat", -1.5),
    ],
    "indemnity": [
        (r"indemnif(?:y|ied|ication)", 4.0), (r"hold\s+harmless", 3.0),
        (r"keep\s+indemnified", 3.5), (r"claims?,?\s+damages", 1.5),
    ],
    "confidentiality": [
        (r"confidential(?:ity)?", 3.5), (r"non-?disclosure", 3.0),
        (r"proprietary\s+information", 2.5), (r"trade\s+secret", 2.5),
    ],
    # ---- employment ----
    "bond_and_recovery": [
        (r"\bbond\b", 3.5), (r"service\s+agreement\s+period", 2.5),
        (r"training\s+cost", 3.0), (r"recover(?:y|ed)?\s+(?:of\s+)?(?:the\s+)?(?:sum|amount)", 2.0),
        (r"liquidated\s+damages", 2.0),
    ],
    "probation": [
        (r"probation(?:ary)?", 4.0),
        (r"confirm(?:ation|ed)\s+(?:of\s+)?(?:your\s+)?(?:employment|service)", 2.5),
    ],
    "non_compete": [
        (r"non-?compet(?:e|ition)", 4.0), (r"shall\s+not\s+(?:join|engage)", 2.5),
        (r"competing\s+business", 3.0), (r"restraint\s+of\s+trade", 2.0),
        (r"solicit", 1.5),
    ],
    "ip_assignment": [
        (r"intellectual\s+property", 3.5), (r"copyright|patent", 2.5),
        (r"work\s+product", 2.5), (r"assign(?:ed|ment)?\s+to\s+the\s+company", 2.5),
    ],
}

# Below this the evidence is too thin to name a type, and we abstain.
MIN_SCORE = 2.5
# The winner must beat the runner-up by this much, or the clause is ambiguous.
MIN_MARGIN = 1.0

_COMPILED: dict[str, list[tuple[re.Pattern[str], float]]] = {
    ctype: [(re.compile(pat, re.IGNORECASE), w) for pat, w in rules]
    for ctype, rules in RULES.items()
}


@dataclass
class Prediction:
    clause_type: str
    confidence: float
    scores: dict[str, float]
    matched: list[str]


# Evidence from an inherited heading counts for less than the clause's own
# words. At full weight, "1. TERM AND LOCK-IN" made every sub-clause beneath it
# a lock-in, including the one that only states the length of the tenancy.
HEADING_WEIGHT = 0.5


def classify_text(text: str, domain: Domain | None = None) -> Prediction:
    """Score a clause against every rule set and return the best-supported type.

    `text` may be `Clause.context_text` - "HEADING [SEP] body" - in which case
    heading matches are discounted by HEADING_WEIGHT.
    """
    heading, sep, body = text.partition(" [SEP] ")
    if not sep:
        heading, body = "", text
    from kwys import config as C

    allowed = set(C.clause_types(domain)) if domain else set(_COMPILED)

    scores: dict[str, float] = {}
    matched: dict[str, list[str]] = {}

    for ctype, rules in _COMPILED.items():
        if ctype not in allowed:
            continue
        total = 0.0
        hits: list[str] = []
        for pattern, weight in rules:
            if pattern.search(body):
                total += weight
            elif heading and pattern.search(heading):
                total += weight * HEADING_WEIGHT
            else:
                continue
            if weight > 0:
                hits.append(pattern.pattern)
        if total > 0:
            scores[ctype] = round(total, 2)
            matched[ctype] = hits

    if not scores:
        return Prediction("other", 0.0, {}, [])

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best, best_score = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0.0

    if best_score < MIN_SCORE or (best_score - runner_up) < MIN_MARGIN:
        # Abstention is deliberate. A wrong type routes the clause to the wrong
        # reference distribution and produces a confident, wrong percentile.
        return Prediction("other", round(best_score / 10.0, 3), scores, matched.get(best, []))

    # Map raw score onto a rough 0..1 confidence. Not calibrated — the trained
    # classifier replaces this, and `kwys doctor` reports which is in use.
    confidence = min(0.95, 0.4 + 0.1 * (best_score - runner_up))
    return Prediction(best, round(confidence, 3), scores, matched[best])


def classify_clauses(clauses: list[Clause], domain: Domain | None = None) -> list[Clause]:
    """Annotate clauses in place with their predicted type.

    The parent heading is included in the text seen by the classifier: sub-clause
    4.3 alone is often meaningless, and "4. TERMINATION" above it is decisive.
    """
    for clause in clauses:
        pred = classify_text(clause.context_text, domain)
        clause.clause_type = pred.clause_type
        clause.type_confidence = pred.confidence
    return clauses
