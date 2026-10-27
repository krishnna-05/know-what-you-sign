"""Calendar dates and the length of the agreement, from clause text.

Indian agreements write dates three ways - "1st May 2026", "this 5th day of
April 2026", "05/04/2026" - and the numeric form is day-first. A date's meaning
(signed, starts, joining) comes from the words around it, not its position:
the preamble usually carries the signing date and clause 1 the start, but not
always.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from kwys.extract.patterns import _months_of

# Keyed by the first three letters, which every spelling above shares.
_MONTHS = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"],
        start=1,
    )
}
_MONTH_RE = (
    r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
    r"sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
)
_ORD = r"(?:st|nd|rd|th)?"

# (pattern, which groups are day / month / year)
_PATTERNS: list[tuple[re.Pattern[str], tuple[int, int, int]]] = [
    # "1st May 2026", "5th day of April, 2026"
    (re.compile(rf"\b(\d{{1,2}}){_ORD}\s+(?:day\s+of\s+)?{_MONTH_RE},?\s+(\d{{4}})\b", re.I),
     (1, 2, 3)),
    # "May 1, 2026"
    (re.compile(rf"\b{_MONTH_RE}\s+(\d{{1,2}}){_ORD},?\s+(\d{{4}})\b", re.I), (2, 1, 3)),
    # "05/04/2026", "05-04-2026", "05.04.2026": day first, as written in India
    (re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b"), (1, 2, 3)),
]

# What a date is, from the words just before it. Order matters: the first kind
# whose cue appears nearest the date wins.
_CUES: list[tuple[str, re.Pattern[str]]] = [
    ("start", re.compile(
        r"commenc\w*|start\w*|effective|with\s+effect\s+from|w\.?\s?e\.?\s?f\.?|"
        r"from\s*$|begin\w*", re.I)),
    ("joining", re.compile(r"join\w*|report\s+for\s+duty|date\s+of\s+appointment", re.I)),
    ("end", re.compile(r"expir\w*|end\w*\s+on|till|until|up\s*to", re.I)),
    ("signed", re.compile(
        r"made|executed|signed|entered\s+into|dated|issued|this\s*$", re.I)),
]

# "for a period of eleven (11) months", "a term of 2 years"
_TERM = re.compile(
    r"(?:for\s+a\s+(?:fixed\s+)?|initial\s+|the\s+)?(?:period|term|tenure|duration)\s+of\s+"
    r"(.{1,40}?(?:months?|years?))",
    re.I,
)


@dataclass
class FoundDate:
    value: date
    raw: str
    kind: str | None  # start / joining / end / signed, or None when unclear


def find_dates(text: str) -> list[FoundDate]:
    """Every parseable calendar date in the text, with what it seems to mark."""
    out: list[FoundDate] = []
    taken: list[tuple[int, int]] = []
    for pattern, (di, mi, yi) in _PATTERNS:
        for m in pattern.finditer(text):
            if any(a <= m.start() < b for a, b in taken):
                continue
            month_raw = m.group(mi)
            month = int(month_raw) if month_raw.isdigit() else _MONTHS.get(month_raw.lower()[:3])
            try:
                value = date(int(m.group(yi)), int(month or 0), int(m.group(di)))
            except (TypeError, ValueError):
                continue  # "31/02/2026" or a stray number pattern
            taken.append((m.start(), m.end()))
            out.append(FoundDate(value, m.group(0), _kind_before(text, m.start())))
    out.sort(key=lambda d: text.find(d.raw))
    return out


def _kind_before(text: str, pos: int, window: int = 70) -> str | None:
    before = text[max(0, pos - window) : pos]
    best: tuple[int, str] | None = None
    for kind, cue in _CUES:
        for m in cue.finditer(before):
            # The cue nearest the date describes it.
            if best is None or m.end() > best[0]:
                best = (m.end(), kind)
    return best[1] if best else None


def find_term_months(text: str) -> tuple[float, str] | None:
    """The length of the agreement, in months, with the words it came from."""
    for m in _TERM.finditer(text):
        found = _months_of(m.group(1))
        if found and 1 <= found[0] <= 240:
            return found[0], m.group(0).strip()
    return None
