"""Answer a question from the agreement's own words.

"Can I sublet?" is answered with the clauses that speak to it, ranked and
quoted - or with "this agreement does not say", which is often the real
finding. Nothing is generated: every answer is text from the document, so it
cannot misstate what the document says.

Stateless by design. The caller sends the clauses with the question; nothing
about the document is kept between requests.

Ranking is BM25 over clause text, boosted for clauses whose TYPE the question
is about. The type comes from the same keyword rules that classify clauses,
plus a short table of how people ask - "move out" is about notice and
lock-in, though neither word appears in it.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from kwys.classify.rules import classify_text
from kwys.models import Domain

_WORD = re.compile(r"[a-z0-9]+")
_STOP = set(
    "a an the of to in on at for by with and or is are be can i my me we our you your "
    "do does did will would should could may if what when how who which this that it "
    "as from any there their they them have has had not no".split()
)

# How people ask, mapped to the clause types that answer it.
INTENTS: list[tuple[re.Pattern[str], list[str]]] = [
    (re.compile(r"\bsub-?let|\bguest|\bflatmate|\broommate|\bpaying guest", re.I),
     ["subletting", "use_restrictions"]),
    (re.compile(r"\bpet|\bdog|\bcat\b|\bbusiness from|\bcommercial use", re.I),
     ["use_restrictions"]),
    (re.compile(r"\bleave\b|\bmove out|\bvacate|\bbreak (?:the|my|this) (?:lease|agreement|"
                r"contract)|\bexit|\bget out|\bend (?:the|my)", re.I),
     ["notice_period", "lock_in_period", "termination"]),
    (re.compile(r"\bresign|\bquit\b|\bnotice", re.I),
     ["notice_period", "termination", "bond_and_recovery"]),
    (re.compile(r"\bdeposit|\brefund|\bmoney back", re.I),
     ["security_deposit", "deposit_refund"]),
    (re.compile(r"\brepair|\bfix|\bbroken|\bmaintenance|\bleak|\bpaint", re.I),
     ["maintenance_and_repairs"]),
    (re.compile(r"\brent\b.*\b(?:increase|rise|hike|go up)|\bincrease\b|\bhike\b", re.I),
     ["rent_and_escalation"]),
    # Last of the rent patterns: "rent" alone is in nearly every clause, so
    # shared words cannot find the one that sets it.
    (re.compile(r"\b(?:how much|what) (?:is )?(?:the |my )?rent|\brent (?:amount|due)|"
                r"\bwhen (?:is|do i pay) (?:the |my )?rent", re.I), ["rent_and_escalation"]),
    (re.compile(r"\blate\b|\bpenalt|\bfine\b|\bmiss(?:ed)? (?:a )?payment", re.I),
     ["penalty_and_late_fee"]),
    (re.compile(r"\benter|\bvisit|\binspect|\bkey\b|\bcome in", re.I),
     ["entry_and_inspection"]),
    (re.compile(r"\bdispute|\bcourt|\bsue\b|\barbitrat|\bcase\b|\blegal action", re.I),
     ["dispute_resolution", "governing_law"]),
    (re.compile(r"\bevict|\bthrow (?:me )?out|\bterminat|\bfire[ds]?\b|\bdismiss", re.I),
     ["termination", "notice_period"]),
    (re.compile(r"\bbond\b|\btraining cost|\bpay back", re.I), ["bond_and_recovery"]),
    (re.compile(r"\bcompetitor|\bnon-?compete|\bjoin another|\bnew job", re.I),
     ["non_compete"]),
    (re.compile(r"\bprobation|\bconfirm(?:ed|ation)\b", re.I), ["probation"]),
    (re.compile(r"\bside project|\binvention|\bown(?:s|ership)? (?:of )?(?:my )?(?:work|code)",
                re.I), ["ip_assignment"]),
    (re.compile(r"\bdamage|\bliab|\bcompensat|\bindemn", re.I), ["indemnity"]),
]

TYPE_BOOST = 2.5  # added to a clause's score when its type answers the question
MIN_SCORE = 1.2  # below this, the clause is not an answer; silence is reported
# A clause of a type the question is NOT about must earn its place on shared
# words alone, and shared words are cheap: "keep a dog" and "keep the premises
# in good repair" share one. Only a strong overlap counts.
MIN_OFF_TOPIC = 3.5
MAX_ANSWERS = 3


@dataclass
class AskClause:
    id: str
    text: str
    clause_type: str | None = None


def _tokens(text: str) -> list[str]:
    return [t for t in _WORD.findall(text.lower()) if t not in _STOP and len(t) > 1]


def _stem(t: str) -> str:
    # Crude, but enough to meet "sublet" with "subletting" and "enter" with "entry".
    for suffix in ("ting", "ing", "ies", "ed", "es", "s", "y"):
        if t.endswith(suffix) and len(t) - len(suffix) >= 4:
            return t[: -len(suffix)]
    return t


def question_types(question: str, domain: Domain | None) -> list[str]:
    """The clause types a question is about, most likely first."""
    types: list[str] = []
    for pattern, ctypes in INTENTS:
        if pattern.search(question):
            types.extend(t for t in ctypes if t not in types)
    pred = classify_text(question, domain)
    for t, _ in sorted(pred.scores.items(), key=lambda kv: -kv[1]):
        if t not in types:
            types.append(t)
    return types


def answer(question: str, clauses: list[AskClause], domain: Domain | None = None) -> dict:
    """The clauses that answer `question`, best first; or silence."""
    q_terms = [_stem(t) for t in _tokens(question)]
    wanted = question_types(question, domain)
    docs = [[_stem(t) for t in _tokens(c.text)] for c in clauses]

    if not clauses or (not q_terms and not wanted):
        return {"answers": [], "silent": True, "topics": wanted}

    # BM25 (k1=1.2, b=0.75): the standard, and robust on documents this short.
    n = len(docs)
    avg = sum(len(d) for d in docs) / n or 1.0
    df = Counter(t for d in docs for t in set(d))

    scored = []
    for clause, doc in zip(clauses, docs, strict=True):
        tf = Counter(doc)
        s = 0.0
        for t in set(q_terms):
            if t not in tf:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            s += idf * tf[t] * 2.2 / (tf[t] + 1.2 * (0.25 + 0.75 * len(doc) / avg))
        if clause.clause_type in wanted:
            # Earlier in the list is a closer match to how the question was asked.
            s += TYPE_BOOST * (1 - 0.15 * wanted.index(clause.clause_type))
        elif s < MIN_OFF_TOPIC:
            continue
        if s > 0:
            scored.append((s, clause))

    scored.sort(key=lambda x: -x[0])
    top = [(s, c) for s, c in scored if s >= MIN_SCORE][:MAX_ANSWERS]
    return {
        "answers": [
            {"clauseId": c.id, "clauseType": c.clause_type, "text": c.text,
             "score": round(s, 2)}
            for s, c in top
        ],
        "silent": not top,
        "topics": wanted[:3],
    }
