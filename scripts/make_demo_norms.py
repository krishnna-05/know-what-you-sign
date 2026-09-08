"""Generate a SYNTHETIC norm store, for development and demos only.

READ THIS BEFORE USING THE OUTPUT.

These distributions are invented. They are shaped to be plausible so the
pipeline can be exercised end to end before a real corpus exists, but they are
not evidence of anything. A percentile computed against them tells you the code
works; it tells you nothing about rental agreements.

The store is stamped with corpus_version "SYNTHETIC-DEMO", and both the terminal
and HTML reports refuse to present findings built on it as real - they carry a
banner instead. That marker is load-bearing: do not remove it, and do not ship a
demo screenshot without it visible.

Replace this with `kwys build-norms` over real collected agreements as soon as
you have them. See PLAN.md section 3.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from kwys.norms.store import NormStore

VERSION = "SYNTHETIC-DEMO"
SEED = 20260908

# (field_key, unit, generator) - shapes chosen to be plausible: contract terms
# cluster hard on round numbers with a long tail on the landlord-favourable side.
SPECS = [
    ("security_deposit.deposit_months", "months_of_rent",
     lambda r, n: r.choice([1, 2, 3, 4, 5, 6, 10], n, p=[.05, .46, .28, .11, .05, .04, .01])),
    ("deposit_refund.refund_days", "days",
     lambda r, n: r.choice([0, 7, 15, 30, 45, 60, 90, 180], n,
                           p=[.14, .10, .22, .34, .08, .07, .04, .01])),
    ("lock_in_period.lock_in_months", "months",
     lambda r, n: r.choice([0, 3, 6, 9, 11, 12], n, p=[.20, .18, .34, .12, .10, .06])),
    ("notice_period.notice_months", "months",
     lambda r, n: r.choice([0.5, 1, 2, 3, 6], n, p=[.06, .48, .30, .13, .03])),
    ("rent_and_escalation.escalation_pct", "pct_per_year",
     lambda r, n: r.choice([0, 5, 6, 8, 10, 12, 15], n, p=[.08, .28, .16, .18, .20, .07, .03])),
    ("penalty_and_late_fee.late_fee_pct", "pct_per_month",
     lambda r, n: r.choice([0.5, 1, 1.5, 2, 3], n, p=[.14, .44, .20, .16, .06])),
    ("entry_and_inspection.notice_hours", "hours",
     lambda r, n: r.choice([0, 12, 24, 48, 72], n, p=[.16, .10, .46, .22, .06])),
    ("maintenance_and_repairs.threshold_inr", "INR",
     lambda r, n: r.choice([500, 1000, 2000, 3000, 5000], n, p=[.14, .30, .28, .18, .10])),
]


def build(n: int = 300) -> NormStore:
    rng = np.random.default_rng(SEED)
    store = NormStore(domain="residential_lease", version=VERSION)
    for field_key, unit, gen in SPECS:
        for value in gen(rng, n):
            store.add(field_key, float(value), unit, source="SYNTHETIC")
    return store


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=300, help="observations per field")
    ap.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "data" / "norms",
    )
    args = ap.parse_args()

    store = build(args.n)
    out = store.save(args.out)
    print(f"Wrote {len(store)} SYNTHETIC field norms (n={args.n} each) to {out}")
    print()
    print("These numbers are invented. Reports built on them carry a banner and")
    print("must not be presented as evidence about real agreements.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
