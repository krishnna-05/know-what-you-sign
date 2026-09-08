"""Build semantic centroids for clause types, from LEDGAR.

Legitimate here in a way it is NOT for numeric norms: LEDGAR supplies linguistic
transfer - what a termination provision sounds like - and that carries across
jurisdictions. It cannot supply Indian rental figures, which is why the numeric
norms come from court judgments instead. See kwys/norms/semantic.py.

  python scripts/build_semantic_norms.py --per-type 400
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import defaultdict
from pathlib import Path

from kwys.norms.semantic import LEDGAR_MAP, SemanticNorms, embed

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("semantic")

ROOT = Path(__file__).resolve().parent.parent
LEDGAR = ROOT / "data" / "external" / "ledgar"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--per-type", type=int, default=400,
                    help="cap examples per clause type (embedding is the slow part)")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "norms" / "semantic")
    args = ap.parse_args()

    if not (LEDGAR / "train.jsonl").exists():
        raise SystemExit(
            f"LEDGAR not found at {LEDGAR}. Run: python scripts/fetch_datasets.py ledgar"
        )

    wanted = {lab: ct for ct, labs in LEDGAR_MAP.items() for lab in labs}
    buckets: dict[str, list[str]] = defaultdict(list)

    with (LEDGAR / "train.jsonl").open() as fh:
        for line in fh:
            row = json.loads(line)
            clause_type = wanted.get(row["label"])
            if clause_type and len(buckets[clause_type]) < args.per_type:
                buckets[clause_type].append(row["text"])

    store = SemanticNorms()
    for clause_type, texts in sorted(buckets.items()):
        log.info("embedding %-26s %d examples", clause_type, len(texts))
        store.add_type(clause_type, embed(texts))

    if store.is_empty:
        raise SystemExit("No clause type had enough examples to form a centroid.")

    out = store.save(args.out)
    print(f"\nBuilt {len(store.centroids)} centroids -> {out}")
    for ct, n in sorted(store.counts.items()):
        print(f"  {ct:26} {n}")
    print(
        "\nThis is the weakest leg of the method: semantic distance measures "
        "UNUSUAL, not HARMFUL, so the pipeline only surfaces it when an "
        "independent signal fires on the same clause."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
