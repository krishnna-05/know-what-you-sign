"""Rule baseline for unfair-clause detection in consumer terms of service.

Exists for the same two reasons as the clause-type rules: it works before any
model is trained, and it is the honest baseline the trained model has to beat.
A transformer that cannot outperform weighted keyword matching on eight
well-defined categories has not earned its place in the system, and the
evaluation is required to report that comparison either way.

Categories follow the LexGLUE unfair_tos label set, which applies the CLAUDETTE
annotation scheme to consumer terms of service. Multi-label by construction: a
venue clause is routinely both a jurisdiction and a choice-of-law clause.
"""

from __future__ import annotations

import re

# (pattern, weight) per unfairness category. Negative weights separate
# categories that share vocabulary.
UNFAIR_RULES: dict[str, list[tuple[str, float]]] = {
    "Limitation of liability": [
        (r"\b(?:no|not)\s+(?:be\s+)?(?:accept|assume)\w*\s+(?:any\s+)?liability", 3.0),
        (r"\bin\s+no\s+event\s+(?:shall|will)\b", 3.0),
        (r"\b(?:disclaim|exclude)\w*\s+(?:all\s+)?(?:liability|warrant)", 3.0),
        (r"\bmaximum\s+(?:aggregate\s+)?liability\b", 3.0),
        (r"\bto\s+the\s+(?:maximum|fullest)\s+extent\s+permitted\b", 2.0),
        (r"\bas\s+is\b|\bwithout\s+warrant", 2.0),
        (r"\bnot\s+(?:be\s+)?responsible\s+for\b", 2.0),
    ],
    "Unilateral termination": [
        # The modal and the verb are routinely separated - "may, in its absolute
        # discretion, immediately terminate" - so a short gap is allowed. Kept
        # tight (up to ~6 words) to avoid spanning a sentence boundary.
        (r"\b(?:may|can|reserves?\s+the\s+right\s+to)\b(?:\s+\w+){0,6}?\s+"
         r"(?:terminate|suspend|cancel|close|disable|deactivate)\b", 3.0),
        (r"\b(?:at\s+|in\s+)?(?:its|our|their)\s+(?:sole|absolute)\s+discretion\b", 2.5),
        (r"\bwithout\s+(?:prior\s+)?notice\b", 2.0),
        (r"\bwith\s+or\s+without\s+cause\b", 3.0),
        (r"\bfor\s+any\s+reason\s+(?:or\s+no\s+reason\s+)?whatsoever\b", 2.5),
        # A right held by the CONSUMER is not unfairness - it is the opposite.
        # "you may cancel at any time" must not read as a unilateral termination
        # clause just because it shares every keyword with one.
        (r"\byou\s+(?:may|can)\b(?:\s+\w+){0,4}?\s+"
         r"(?:terminate|cancel|close|delete|stop)\b", -4.0),
    ],
    "Unilateral change": [
        (r"\b(?:may|reserves?\s+the\s+right\s+to)\s+(?:modify|change|amend|update|revise)\b", 3.0),
        (r"\bchanges?\s+(?:to\s+)?these\s+terms\b", 2.0),
        (r"\bcontinued\s+use\s+(?:of|after)\b", 2.0),
        (r"\bat\s+any\s+time\s+without\s+notice\b", 2.0),
    ],
    "Content removal": [
        (r"\b(?:remove|delete|take\s+down|disable\s+access\s+to)\s+(?:any\s+)?"
         r"(?:content|material|post)", 3.0),
        (r"\bwithout\s+notice\b", 1.0),
        (r"\brefuse\s+(?:or\s+remove\s+)?(?:any\s+)?content\b", 3.0),
    ],
    "Contract by using": [
        (r"\bby\s+(?:using|accessing|visiting|continuing\s+to\s+use)\b", 3.0),
        (r"\byou\s+(?:agree|accept|consent)\s+to\s+(?:be\s+bound|these\s+terms)", 2.5),
        (r"\bconstitutes?\s+(?:your\s+)?acceptance\b", 3.0),
    ],
    "Choice of law": [
        (r"\bgoverned\s+by\s+(?:and\s+construed\s+)?(?:in\s+accordance\s+with\s+)?the\s+laws?\b",
         3.5),
        (r"\blaws?\s+of\s+(?:the\s+)?(?:state|country|england|scotland)\b", 2.5),
        (r"\bwithout\s+regard\s+to\s+(?:its\s+)?conflicts?\s+of\s+laws?\b", 2.5),
    ],
    "Jurisdiction": [
        (r"\bexclusive\s+jurisdiction\b", 3.5),
        (r"\b(?:submit|consent)\s+to\s+the\s+(?:exclusive\s+)?jurisdiction\b", 3.5),
        (r"\bcourts?\s+(?:of|in|located\s+in)\b", 2.0),
        (r"\bvenue\s+(?:shall|will)\s+(?:be|lie)\b", 2.5),
    ],
    "Arbitration": [
        (r"\barbitrat(?:ion|or|e)\b", 3.5),
        (r"\bbinding\s+arbitration\b", 4.0),
        (r"\bwaive\s+(?:any\s+)?right\s+to\s+(?:a\s+)?(?:jury\s+trial|class\s+action)\b", 3.0),
        (r"\bclass\s+action\s+waiver\b", 3.5),
        (r"\bAmerican\s+Arbitration\s+Association\b|\bJAMS\b", 3.0),
    ],
}

# Multi-label, so each category is judged on its own evidence rather than
# competing with the others. A clause clearing this is flagged for that type.
FLAG_THRESHOLD = 3.0

_COMPILED = {
    label: [(re.compile(p, re.I), w) for p, w in rules]
    for label, rules in UNFAIR_RULES.items()
}


def score_clause(text: str) -> dict[str, float]:
    """Weighted evidence per unfairness category."""
    scores: dict[str, float] = {}
    for label, rules in _COMPILED.items():
        total = sum(w for pattern, w in rules if pattern.search(text))
        if total > 0:
            scores[label] = round(total, 2)
    return scores


def predict(text: str, threshold: float = FLAG_THRESHOLD) -> list[str]:
    """Which kinds of unfairness this clause shows, if any."""
    return sorted(
        label for label, score in score_clause(text).items() if score >= threshold
    )


def labels() -> list[str]:
    return sorted(UNFAIR_RULES)
