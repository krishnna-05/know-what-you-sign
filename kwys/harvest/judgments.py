"""Harvesting real agreement terms from published court judgments.

WHY THIS EXISTS

Executed rental agreements are private documents and are not published anywhere.
Blank templates are published everywhere but contain no figures. Court judgments
sit in between: when a tenancy is disputed, the judgment recites the operative
terms of the actual signed agreement, and judgments ARE public record.

    "the defendant paid a security deposit of Rs.12,21,000 ... the monthly
     rent of Rs.1,85,000 ..."

That is a real, executed, 6.6-month deposit ratio.

THE BIAS, STATED UP FRONT

Only DISPUTED agreements reach court. This corpus therefore over-represents
conflict-prone tenancies and probably harsher-than-average terms. That belongs in
the limitations section of any write-up, not in a footnote. Two mitigations are
built in: every harvested value carries the judgment it came from, so any figure
can be checked; and `corpus_bias` is recorded in the norm store so a report built
on it can say what it rests on.

BEING A GOOD CITIZEN

robots.txt is parsed and honoured (it disallows a specific list of documents),
requests are rate-limited and cached to disk, and a descriptive User-Agent is
sent. Do not remove any of that to go faster.
"""

from __future__ import annotations

import hashlib
import html as html_mod
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from urllib.robotparser import RobotFileParser

log = logging.getLogger(__name__)

BASE = "https://indiankanoon.org"
USER_AGENT = (
    "kwys-research/0.1 (academic project on contract clause readability; "
    "contact via github.com/krishnna-05/know-what-you-sign)"
)
REQUEST_DELAY = 3.0  # seconds between requests - deliberately unhurried
MAX_RETRIES = 4
BACKOFF_BASE = 8.0  # seconds; doubles per retry after a 429


@dataclass
class HarvestedValue:
    """One figure lifted from a judgment, with the sentence it came from.

    `sentence` is not optional decoration: extraction from narrative prose is
    error-prone in a way clause parsing is not, and a value nobody can check
    against its source has no business entering a reference distribution.
    """

    field: str
    value: float
    unit: str
    sentence: str
    doc_id: str
    title: str = ""
    tier: int = 1
    position: int = 0  # character offset, for proximity-based pairing


@dataclass
class Judgment:
    doc_id: str
    title: str
    text: str
    values: list[HarvestedValue] = field(default_factory=list)


# --------------------------------------------------------------- extraction

_RS = r"(?:Rs\.?|INR|₹)\s*([\d,]+(?:\.\d+)?)"
_WORDNUM = r"[a-zA-Z]+(?:[\s-]+[a-zA-Z]+){0,3}"

# Deliberately narrow. A judgment mentions many sums - court fees, damages,
# arrears, costs - and a loose pattern quietly poisons the distribution with
# numbers that have nothing to do with the deposit.
# (pattern, tier). Tier 1 is an unambiguous recitation of the operative term;
# tier 2 is plausible but could catch an unrelated sum. Within a judgment, only
# the BEST tier that matched is used - mixing them lets a decree amount sit in
# the same pool as the deposit, and nothing downstream can tell them apart.
PATTERNS: dict[str, list[tuple[re.Pattern[str], int]]] = {
    "deposit_inr": [
        (re.compile(rf"security\s+deposit\s+(?:amount\s+)?of{_RS}", re.I), 1),
        (re.compile(rf"security\s+deposit[^.]{{0,40}}?{_RS}", re.I), 1),
        (re.compile(rf"(?:paid|deposited)[^.]{{0,30}}?deposit[^.]{{0,30}}?{_RS}", re.I), 2),
        (re.compile(rf"deposit\s+(?:amount\s+)?of{_RS}", re.I), 2),
    ],
    "monthly_rent_inr": [
        (re.compile(rf"monthly\s+rent(?:al)?\s+of{_RS}", re.I), 1),
        (re.compile(rf"monthly\s+rent(?:al)?[^.]{{0,30}}?{_RS}", re.I), 1),
        (re.compile(rf"rent\s+of{_RS}\s*(?:per\s+month|p\.?m\.?)", re.I), 1),
        (re.compile(rf"rent\s+(?:at|@)[^.]{{0,20}}?{_RS}\s*(?:per\s+month|p\.?m\.?)", re.I), 2),
    ],
    "deposit_months": [
        (re.compile(
            rf"(?:security\s+)?deposit[^.]{{0,50}}?({_WORDNUM}|\d+)\s*months?[''’]?s?\s+rent",
            re.I), 1),
        (re.compile(
            rf"({_WORDNUM}|\d+)\s*months?[''’]?s?\s+rent\s+as\s+(?:security\s+)?deposit",
            re.I), 1),
    ],
    "notice_months": [
        (re.compile(rf"notice\s+(?:period\s+)?of\s+({_WORDNUM}|\d+)\s*months?", re.I), 1),
        (re.compile(
            rf"({_WORDNUM}|\d+)\s*months?[''’]?s?\s+(?:prior\s+|advance\s+)?notice", re.I), 2),
    ],
    "lock_in_months": [
        (re.compile(rf"lock[- ]?in\s+(?:period\s+)?(?:of\s+)?({_WORDNUM}|\d+)\s*months?",
                    re.I), 1),
    ],
}

# Plausibility bounds. A value outside these is an extraction error, not a
# remarkable agreement, and dropping it is safer than letting it skew a median.
BOUNDS = {
    "deposit_inr": (1_000.0, 5_00_00_000.0),
    "monthly_rent_inr": (300.0, 50_00_000.0),
    "deposit_months": (0.5, 36.0),
    "notice_months": (0.25, 24.0),
    "lock_in_months": (0.5, 60.0),
}

# A deposit and a rent further apart than this in the text are not treated as
# describing the same tenancy.
MAX_PAIR_DISTANCE = 3000

# Judgments about factories, shops and offices are not comparable to homes.
COMMERCIAL_HINTS = re.compile(
    r"\b(?:factory|godown|warehouse|showroom|shop\s+premises|office\s+premises|"
    r"industrial|commercial\s+(?:premises|purpose)|hotel|petrol\s+pump|cinema)\b",
    re.I,
)
RESIDENTIAL_HINTS = re.compile(
    r"\b(?:residential|dwelling|house|flat|apartment|tenement|bungalow|"
    r"residence|family)\b",
    re.I,
)


def _sentence_around(text: str, start: int, end: int, width: int = 180) -> str:
    lo = max(0, start - width // 2)
    hi = min(len(text), end + width // 2)
    return re.sub(r"\s+", " ", text[lo:hi]).strip()


def extract_values(judgment: Judgment) -> list[HarvestedValue]:
    """Pull agreement figures out of a judgment's narrative text."""
    from kwys.extract.numbers import parse_indian_digits, words_to_number

    out: list[HarvestedValue] = []
    text = judgment.text

    for field_name, patterns in PATTERNS.items():
        unit = "INR" if field_name.endswith("_inr") else "months"
        candidates: list[HarvestedValue] = []
        seen: set[tuple[int, float]] = set()

        for pattern, tier in patterns:
            for m in pattern.finditer(text):
                raw = m.group(1)
                value = parse_indian_digits(raw) or words_to_number(raw)
                if value is None:
                    continue
                lo, hi = BOUNDS[field_name]
                if not (lo <= value <= hi):
                    continue
                if (tier, value) in seen:
                    continue
                seen.add((tier, value))
                candidates.append(
                    HarvestedValue(
                        field=field_name,
                        value=float(value),
                        unit=unit,
                        sentence=_sentence_around(text, m.start(), m.end()),
                        doc_id=judgment.doc_id,
                        title=judgment.title,
                        tier=tier,
                        position=m.start(),
                    )
                )

        if not candidates:
            continue

        # Keep only the most specific tier that matched anywhere in this judgment.
        best_tier = min(c.tier for c in candidates)
        kept = [c for c in candidates if c.tier == best_tier]

        # Judgments recite the agreement in the statement of facts, near the
        # start; later mentions are about the dispute, the decree and the costs.
        # The earliest occurrence is the operative term.
        kept.sort(key=lambda c: c.position)
        out.append(kept[0])

    return out


def derive_deposit_ratio(values: list[HarvestedValue]) -> HarvestedValue | None:
    """Turn a deposit and a rent from the same judgment into months of rent.

    The ratio is the comparable quantity: a Rs.2,00,000 deposit means something
    entirely different in Mumbai and in Kochi, whereas "four months' rent"
    travels. Only the SMALLEST plausible rent and the LARGEST deposit are used,
    because judgments often recite an escalated rent alongside the original.
    """
    deposits = [v for v in values if v.field == "deposit_inr"]
    rents = [v for v in values if v.field == "monthly_rent_inr"]
    if not deposits or not rents:
        return None
    if any(v.field == "deposit_months" for v in values):
        return None  # the judgment states the ratio outright; prefer that

    deposit, rent = deposits[0], rents[0]
    if rent.value <= 0:
        return None

    # Both figures must come from the same passage. A deposit recited on page 1
    # and a rent quoted on page 30 are probably different tenancies, or the rent
    # after escalation - either way the ratio between them means nothing.
    if abs(deposit.position - rent.position) > MAX_PAIR_DISTANCE:
        return None

    ratio = deposit.value / rent.value
    lo, hi = BOUNDS["deposit_months"]
    if not (lo <= ratio <= hi):
        return None

    return HarvestedValue(
        field="deposit_months",
        value=round(ratio, 2),
        unit="months_of_rent",
        sentence=f"[derived] {deposit.sentence} || {rent.sentence}",
        doc_id=deposit.doc_id,
        title=deposit.title,
    )


def classify_property(text: str) -> str:
    """residential / commercial / unknown, from how the judgment describes it."""
    commercial = len(COMMERCIAL_HINTS.findall(text))
    residential = len(RESIDENTIAL_HINTS.findall(text))
    # A clear margin is required in both directions. Word-counting over a long
    # judgment picks up incidental vocabulary, and a near-tie carries no signal
    # - "unknown" is the honest answer, and --residential-only then excludes it.
    if commercial >= 2 and commercial > residential * 1.5:
        return "commercial"
    if residential >= 3 and residential > commercial * 2:
        return "residential"
    return "unknown"


# --------------------------------------------------------------- fetching


class Fetcher:
    """Polite, cached HTTP client for one host."""

    def __init__(self, cache_dir: Path, delay: float = REQUEST_DELAY) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.delay = delay
        self._last = 0.0
        self._robots = self._read_robots()

    def _read_robots(self) -> RobotFileParser | None:
        """Fetch robots.txt with OUR user agent, then hand it to the parser.

        RobotFileParser.read() uses urllib's default "Python-urllib/3.x" agent,
        which this host blocks with a 403. The parser treats 403 as
        disallow_all, so it silently forbade every URL - including ones robots
        plainly permits. Failing closed is the right default; fetching properly
        in the first place is better.
        """
        parser = RobotFileParser()
        try:
            req = urllib.request.Request(
                f"{BASE}/robots.txt", headers={"User-Agent": USER_AGENT}
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                body = resp.read().decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not read robots.txt (%s); refusing to crawl.", exc)
            return None
        parser.parse(body.splitlines())
        return parser

    def allowed(self, url: str) -> bool:
        """robots.txt disallows a specific list of documents. Honour it."""
        if self._robots is None:
            return False
        return self._robots.can_fetch(USER_AGENT, url)

    def get(self, url: str, *, use_cache: bool = True) -> str | None:
        if not self.allowed(url):
            log.info("robots.txt disallows %s - skipping", url)
            return None

        key = hashlib.sha256(url.encode()).hexdigest()[:20]
        cached = self.cache_dir / f"{key}.html"
        if use_cache and cached.exists():
            return cached.read_text(errors="replace")

        wait = self.delay - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

        body = self._get_with_backoff(url)
        if body is None:
            return None

        cached.write_text(body)
        return body

    def _get_with_backoff(self, url: str) -> str | None:
        """Fetch, backing off when the server asks us to slow down.

        A fixed delay is not enough for a sustained crawl: a first pass lost 61
        judgments to HTTP 429 and simply logged them. Being rate-limited is the
        server telling us our pace is wrong, so we wait longer each time rather
        than dropping the document and moving on. Honour Retry-After when it is
        sent, and permanently slow the whole crawler down after a 429 - the next
        request is likely to be refused too.
        """
        for attempt in range(MAX_RETRIES):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return resp.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as exc:
                if exc.code != 429:
                    log.warning("fetch failed %s: HTTP %s", url, exc.code)
                    return None
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                wait = (
                    float(retry_after)
                    if retry_after and retry_after.isdigit()
                    else BACKOFF_BASE * (2**attempt)
                )
                # Raise the floor for every later request, not just this one.
                self.delay = min(self.delay * 1.5, 15.0)
                log.info(
                    "rate limited; waiting %.0fs and slowing to %.1fs between "
                    "requests (attempt %d/%d)",
                    wait, self.delay, attempt + 1, MAX_RETRIES,
                )
                time.sleep(wait)
            except (urllib.error.URLError, TimeoutError) as exc:
                log.warning("fetch failed %s: %s", url, exc)
                return None

        log.warning("giving up on %s after %d rate-limited attempts", url, MAX_RETRIES)
        return None


def strip_html(raw: str) -> str:
    raw = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.S | re.I)
    return html_mod.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw))).strip()


def search(fetcher: Fetcher, query: str, page: int = 0) -> list[str]:
    """Return judgment ids for one page of results."""
    url = f"{BASE}/search/?formInput={urllib.parse.quote(query)}&pagenum={page}"
    body = fetcher.get(url)
    if not body:
        return []
    ids, seen = [], set()
    for did in re.findall(r"/doc/(\d+)/", body):
        if did not in seen:
            seen.add(did)
            ids.append(did)
    return ids


def fetch_judgment(fetcher: Fetcher, doc_id: str) -> Judgment | None:
    body = fetcher.get(f"{BASE}/doc/{doc_id}/")
    if not body:
        return None
    title_m = re.search(r"<title>(.*?)</title>", body, re.S | re.I)
    title = html_mod.unescape(title_m.group(1)).strip() if title_m else ""
    return Judgment(doc_id=doc_id, title=title, text=strip_html(body))
