"""Figures readers choose to share, to grow a corpus that is not from court.

The judgment corpus only sees agreements that ended in a dispute. Readers who
check an ordinary agreement can, if they choose, add its figures to a second
corpus - and every report built on that one says it is self-reported.

WHAT IS STORED, AND WHAT IS NOT. Only whitelisted numbers: a deposit in months
of rent, a notice period, a bond length. Never text, names, addresses, clause
wording or exact dates. Rupee amounts are rounded, and the city is kept only
if it is one the gazetteer knows - a free-text field is where an address
would end up. The browser shows the reader exactly this payload before
anything is sent, and nothing is sent without their click.

ABUSE. Anyone can submit anything. Three defences: bounds (a 400-month
deposit is refused), coarsening (so a value cannot carry a message), and
isolation (contributed figures form their own corpus version, never merged
into the judgment corpus, and like any corpus they are unusable below MIN_N).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from kwys.models import Domain

# norm key -> (unit, lower bound, upper bound, rounding step)
ALLOWED: dict[str, dict[str, tuple[str, float, float, float]]] = {
    Domain.RESIDENTIAL_LEASE.value: {
        "security_deposit.deposit_months": ("months_of_rent", 0.5, 36, 0.5),
        "notice_period.notice_months": ("months", 0.25, 24, 0.25),
        "lock_in_period.lock_in_months": ("months", 0.5, 60, 0.5),
        "deposit_refund.refund_days": ("days", 1, 365, 1),
        "rent_and_escalation.escalation_pct": ("pct_per_year", 0, 50, 0.5),
        "penalty_and_late_fee.late_fee_pct": ("pct_per_month", 0, 20, 0.5),
        "rent_and_escalation.monthly_rent_inr": ("INR", 1_000, 10_00_000, 1_000),
    },
    Domain.EMPLOYMENT_OFFER.value: {
        "bond_and_recovery.bond_months": ("months", 1, 120, 1),
        "bond_and_recovery.bond_amount_inr": ("INR", 1_000, 50_00_000, 5_000),
        "notice_period.notice_months": ("months", 0.25, 12, 0.25),
        "probation.probation_months": ("months", 1, 36, 1),
        "non_compete.noncompete_months": ("months", 1, 120, 1),
    },
}

# What the reader is shown for each figure before they agree to share it.
LABELS = {
    "security_deposit.deposit_months": "Security deposit",
    "notice_period.notice_months": "Notice period",
    "lock_in_period.lock_in_months": "Lock-in",
    "deposit_refund.refund_days": "Days to refund the deposit",
    "rent_and_escalation.escalation_pct": "Annual rent increase",
    "penalty_and_late_fee.late_fee_pct": "Late-payment charge",
    "rent_and_escalation.monthly_rent_inr": "Monthly rent (rounded)",
    "bond_and_recovery.bond_months": "Bond period",
    "bond_and_recovery.bond_amount_inr": "Bond amount (rounded)",
    "probation.probation_months": "Probation",
    "non_compete.noncompete_months": "Non-compete",
}

CONTRIBUTED_VERSION = "contributed-v1"
CONTRIBUTED_LABEL = "Shared by people who used this tool"
CONTRIBUTED_BIAS = (
    "Self-reported by people who checked their agreement with this tool and "
    "chose to share its figures. Unverified, and skewed towards people careful "
    "enough to check before signing."
)


class Rejected(ValueError):
    """A contribution that cannot be accepted, with the reason."""


def _round(value: float, step: float) -> float:
    return round(round(value / step) * step, 2)


def clean(domain: str, figures: list[dict[str, Any]], city: str | None) -> dict[str, Any]:
    """Validate and coarsen a contribution, or raise Rejected."""
    allowed = ALLOWED.get(domain)
    if allowed is None:
        raise Rejected("Figures are not collected for this kind of agreement.")
    if not figures:
        raise Rejected("There are no figures to share.")
    if len(figures) > len(allowed):
        raise Rejected("Too many figures.")

    out: dict[str, float] = {}
    for fig in figures:
        key = fig.get("key")
        if key not in allowed:
            raise Rejected(f"{key!r} is not a figure that is collected.")
        if key in out:
            raise Rejected(f"{key!r} appears twice.")
        try:
            value = float(fig.get("value"))
        except (TypeError, ValueError) as exc:
            raise Rejected(f"{key!r} is not a number.") from exc
        unit, lo, hi, step = allowed[key]
        if not (lo <= value <= hi):
            raise Rejected(f"{key!r} is outside the plausible range.")
        out[key] = _round(value, step)

    place = None
    if city:
        from kwys.extract.geo import lookup, normalise

        # Only a city the gazetteer knows. Anything else is free text, and free
        # text is where someone's address would end up.
        if lookup(city) is not None:
            place = normalise(city)

    return {"domain": domain, "figures": out, "city": place}


class ContributionStore:
    """An append-only SQLite table of cleaned contributions."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS contributions (
                       id INTEGER PRIMARY KEY,
                       domain TEXT NOT NULL,
                       city TEXT,
                       figures TEXT NOT NULL,
                       digest TEXT NOT NULL UNIQUE,
                       month TEXT NOT NULL
                   )"""
            )

    def _db(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def add(self, cleaned: dict[str, Any]) -> bool:
        """Store a cleaned contribution. False if an identical one is already in.

        The digest stops the same report being submitted over and over. It
        also means two genuinely identical agreements count once - a small
        loss, and the safer one.
        """
        body = json.dumps(
            {"d": cleaned["domain"], "c": cleaned["city"], "f": cleaned["figures"]},
            sort_keys=True,
        )
        digest = hashlib.sha256(body.encode()).hexdigest()
        # Month, not timestamp: enough to see drift, too coarse to identify.
        month = datetime.now(UTC).strftime("%Y-%m")
        with self._db() as db:
            try:
                db.execute(
                    "INSERT INTO contributions (domain, city, figures, digest, month) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (cleaned["domain"], cleaned["city"], json.dumps(cleaned["figures"]),
                     digest, month),
                )
            except sqlite3.IntegrityError:
                return False
        return True

    def rows(self, domain: str) -> list[dict[str, Any]]:
        with self._db() as db:
            cur = db.execute(
                "SELECT id, city, figures FROM contributions WHERE domain = ?", (domain,)
            )
            return [
                {"id": r[0], "city": r[1], "figures": json.loads(r[2])} for r in cur.fetchall()
            ]

    def count(self, domain: str | None = None) -> int:
        with self._db() as db:
            if domain:
                return db.execute(
                    "SELECT COUNT(*) FROM contributions WHERE domain = ?", (domain,)
                ).fetchone()[0]
            return db.execute("SELECT COUNT(*) FROM contributions").fetchone()[0]


def build_store(store: ContributionStore, domain: Domain):
    """A norm store from contributions: its own corpus version, never merged."""
    from kwys.norms.store import NormStore

    norms = NormStore(
        domain=domain.value,
        version=CONTRIBUTED_VERSION,
        corpus_bias=CONTRIBUTED_BIAS,
        label=CONTRIBUTED_LABEL,
    )
    allowed = ALLOWED[domain.value]
    for row in store.rows(domain.value):
        for key, value in row["figures"].items():
            if key in allowed:
                norms.add(key, float(value), allowed[key][0], source=f"contribution:{row['id']}")
    return norms


def offer(domain: Domain, extracted, city: str | None) -> list[dict[str, Any]]:
    """What the reader would be offered to share from this report.

    Built server-side from the same extraction, so the browser can only send
    back figures the analysis actually found - and the server re-validates them
    anyway.
    """
    allowed = ALLOWED.get(domain.value, {})
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ct in extracted:
        for term in ct.terms:
            key = f"{ct.clause_type}.{term.field}"
            if key not in allowed or key in seen:
                continue
            if not isinstance(term.value, int | float) or isinstance(term.value, bool):
                continue
            unit, lo, hi, step = allowed[key]
            if not (lo <= float(term.value) <= hi):
                continue
            seen.add(key)
            out.append({
                "key": key,
                "label": LABELS[key],
                "value": _round(float(term.value), step),
                "unit": unit,
            })
    return out
