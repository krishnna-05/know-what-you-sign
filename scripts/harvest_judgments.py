"""Build a reference corpus of real agreement terms from court judgments.

Executed rental agreements are private and unpublished; blank templates carry no
figures. Judgments recite the operative terms of real signed agreements and are
public record. See kwys/harvest/judgments.py for the method and its bias.

Usage
-----
  python scripts/harvest_judgments.py --pages 5
  python scripts/harvest_judgments.py --pages 10 --residential-only
  python scripts/harvest_judgments.py --report          # inspect what was found
  python scripts/harvest_judgments.py --domain employment_offer --pages 5

Output
------
  data/corpus/judgments/values.jsonl   one record per harvested figure, each
                                       carrying the judgment it came from
  data/corpus/judgments/employment/values.jsonl   the same, for employment
  data/corpus/judgments/cache/         raw pages, so re-runs cost no requests
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import Counter, defaultdict
from pathlib import Path

from kwys.harvest.judgments import (
    EMPLOYMENT_BOUNDS,
    EMPLOYMENT_PATTERNS,
    Fetcher,
    classify_property,
    derive_deposit_ratio,
    extract_values,
    fetch_judgment,
    search,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("harvest")

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "corpus" / "judgments"
CACHE_DIR = OUT_DIR / "cache"  # shared: a page fetched once is never fetched again
EMPLOYMENT_OUT_DIR = OUT_DIR / "employment"

# Several angles on the same population: a single query returns one slice of
# the index and would give a narrower corpus than the case law actually holds.
QUERIES = [
    '"security deposit" "months rent" lease tenant',
    '"security deposit" refund tenant landlord premises',
    '"lock in period" lease tenant premises',
    '"notice period" tenancy terminate landlord tenant',
    'rent agreement "monthly rent" "security deposit" eviction',
    'leave and licence agreement deposit licensee',
    '"rental agreement" tenant deposit refund suit',
]


# Disputes over a service bond or a dismissal recite the appointment letter:
# the bond amount and period, the notice each side must give, the probation.
EMPLOYMENT_QUERIES = [
    '"service bond" employee resigned "liquidated damages"',
    '"employment bond" employee training recovery',
    '"service bond" "serve the company" years',
    'bond "restraint of trade" "section 27" employee resign',
    '"appointment letter" "probation period" "notice period" employee',
    'employee bond amount recovery suit employer training',
    '"three months notice" "appointment letter" termination employee',
]


def harvest(pages: int, residential_only: bool, refresh: bool, domain: str) -> dict:
    employment = domain == "employment_offer"
    out_dir = EMPLOYMENT_OUT_DIR if employment else OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    fetcher = Fetcher(CACHE_DIR)

    doc_ids: list[str] = []
    seen: set[str] = set()
    for query in EMPLOYMENT_QUERIES if employment else QUERIES:
        for page in range(pages):
            found = search(fetcher, query, page)
            if not found:
                break
            for did in found:
                if did not in seen:
                    seen.add(did)
                    doc_ids.append(did)
        log.info("query %-52s -> %d unique judgments so far", query[:52], len(doc_ids))

    log.info("Fetching %d judgments (cached where already seen)...", len(doc_ids))

    records: list[dict] = []
    stats = Counter()
    for i, doc_id in enumerate(doc_ids, start=1):
        judgment = fetch_judgment(fetcher, doc_id)
        if judgment is None:
            stats["unfetchable"] += 1
            continue

        if employment:
            prop_type = "employment"
            values = extract_values(judgment, EMPLOYMENT_PATTERNS, EMPLOYMENT_BOUNDS)
        else:
            prop_type = classify_property(judgment.text)
            stats[f"property:{prop_type}"] += 1
            if residential_only and prop_type != "residential":
                stats["skipped_non_residential"] += 1
                continue

            values = extract_values(judgment)
            ratio = derive_deposit_ratio(values)
            if ratio:
                values.append(ratio)
        if not values:
            stats["no_values"] += 1
            continue

        stats["judgments_used"] += 1
        for v in values:
            stats[f"field:{v.field}"] += 1
            records.append(
                {
                    "field": v.field,
                    "value": v.value,
                    "unit": v.unit,
                    "property_type": prop_type,
                    "doc_id": v.doc_id,
                    "title": v.title[:160],
                    "source_url": f"https://indiankanoon.org/doc/{v.doc_id}/",
                    "sentence": v.sentence,
                }
            )

        if i % 25 == 0:
            log.info("  %d/%d judgments, %d values", i, len(doc_ids), len(records))

    out = out_dir / "values.jsonl"
    with out.open("w") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")

    log.info("Wrote %d values from %d judgments -> %s",
             len(records), stats["judgments_used"], out)
    return dict(stats)


def report(domain: str) -> None:
    path = (EMPLOYMENT_OUT_DIR if domain == "employment_offer" else OUT_DIR) / "values.jsonl"
    if not path.exists():
        raise SystemExit(f"Nothing harvested yet. Run without --report first. ({path})")

    by_field: dict[str, list[float]] = defaultdict(list)
    by_prop = Counter()
    docs = set()
    with path.open() as fh:
        for line in fh:
            r = json.loads(line)
            by_field[r["field"]].append(r["value"])
            by_prop[r["property_type"]] += 1
            docs.add(r["doc_id"])

    import statistics as st

    print(f"\n{len(docs)} judgments, {sum(len(v) for v in by_field.values())} values")
    print(f"property types: {dict(by_prop)}\n")
    print(f"{'field':22} {'n':>5} {'median':>10} {'p25':>10} {'p75':>10}  usable")
    print("-" * 72)
    for f, vals in sorted(by_field.items()):
        vals = sorted(vals)
        q = st.quantiles(vals, n=4) if len(vals) >= 4 else [float("nan")] * 3
        usable = "yes" if len(vals) >= 30 else f"no (need {30 - len(vals)} more)"
        print(
            f"{f:22} {len(vals):>5} {st.median(vals):>10.2f} "
            f"{q[0]:>10.2f} {q[2]:>10.2f}  {usable}"
        )
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pages", type=int, default=4, help="result pages per query")
    ap.add_argument("--residential-only", action="store_true",
                    help="drop judgments that read as commercial or industrial")
    ap.add_argument("--refresh", action="store_true", help="ignore the page cache")
    ap.add_argument("--report", action="store_true", help="summarise what was harvested")
    ap.add_argument("--domain", default="residential_lease",
                    choices=["residential_lease", "employment_offer"])
    args = ap.parse_args()

    if args.report:
        report(args.domain)
        return 0

    stats = harvest(args.pages, args.residential_only, args.refresh, args.domain)
    print("\n" + json.dumps(stats, indent=2, sort_keys=True))
    print(
        "\nRemember: only DISPUTED agreements reach court, so this corpus "
        "over-represents conflict-prone agreements. State that in any write-up."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
