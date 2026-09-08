"""Measure the system, and report the numbers honestly.

Three evaluations, each answering a different question:

  segmentation   Did we split the document into the right clauses?
  clause-type    Did we identify what each clause is about?
  unfair-tos     Can we detect unfair clauses, and does the trained model
                 actually beat the rule baseline?

The last one carries the most weight, because it is the only part of this
project with EXPERT GROUND TRUTH that we did not author ourselves. LexGLUE's
unfair_tos applies the CLAUDETTE annotation scheme to consumer terms of service,
and reporting against it means the result can be compared with published work
rather than only with itself.

Two reporting rules, both deliberate:

  RECALL OVER PRECISION. A missed unfair clause is the failure that hurts the
  user; a false flag costs them a moment's reading. Both are reported, and the
  operating point is chosen accordingly.

  MACRO OVER MICRO. 89% of unfair_tos clauses carry no label, so accuracy and
  micro-F1 both flatter badly - predicting "fair" for everything scores 89%
  accuracy. Macro-F1 across the eight unfair types is the headline, and
  per-class recall is printed because an average can hide a category the system
  never finds at all.

Usage
-----
  python scripts/evaluate.py unfair-tos            # rules vs trained model
  python scripts/evaluate.py segmentation
  python scripts/evaluate.py all --json results.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def _load_jsonl(path: Path) -> list[dict]:
    with path.open() as fh:
        return [json.loads(line) for line in fh if line.strip()]


# ------------------------------------------------------------------ unfair_tos


def evaluate_unfair_tos(split: str = "test", limit: int | None = None) -> dict[str, Any]:
    """Rule baseline vs trained model on expert-annotated terms of service."""
    import numpy as np

    from kwys.classify.unfair_rules import predict as rule_predict

    data_dir = DATA / "external" / "unfair_tos"
    if not data_dir.exists():
        raise SystemExit(
            f"unfair_tos not found at {data_dir}. "
            "Run: python scripts/fetch_datasets.py unfair_tos"
        )

    label_names = json.loads((data_dir / "labels.json").read_text())
    rows = _load_jsonl(data_dir / f"{split}.jsonl")
    if limit:
        rows = rows[:limit]

    idx = {n: i for i, n in enumerate(label_names)}

    def vectorise(labels: list[str]) -> list[int]:
        vec = [0] * len(label_names)
        for lab in labels:
            if lab in idx:
                vec[idx[lab]] = 1
        return vec

    y_true = np.array([vectorise(r["labels"]) for r in rows])

    results: dict[str, Any] = {
        "split": split,
        "n": len(rows),
        "positive_rate": round(float((y_true.sum(axis=1) > 0).mean()), 4),
        "systems": {},
    }

    # --- rule baseline ---
    y_rules = np.array([vectorise(rule_predict(r["text"])) for r in rows])
    results["systems"]["rules"] = _score(y_true, y_rules, label_names)

    # --- trained model, if one exists ---
    model_dir = DATA / "models" / "unfair-tos"
    # A directory alone is not a model: training creates it, and checkpoints
    # land inside it, long before the final weights are saved. Check for the
    # config that a finished save actually writes.
    if (model_dir / "config.json").exists():
        y_model = _predict_with_model(model_dir, [r["text"] for r in rows], label_names)
        results["systems"]["trained"] = _score(y_true, y_model, label_names)
    else:
        results["systems"]["trained"] = None

    return results


def _predict_with_model(model_dir: Path, texts: list[str], label_names: list[str]):
    import numpy as np
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    report_path = model_dir / "eval_report.json"
    threshold = 0.5
    if report_path.exists():
        threshold = json.loads(report_path.read_text()).get("threshold", 0.5)

    tokenizer = AutoTokenizer.from_pretrained(str(model_dir))
    model = AutoModelForSequenceClassification.from_pretrained(str(model_dir))
    model.eval()

    out = []
    batch = 32
    with torch.no_grad():
        for i in range(0, len(texts), batch):
            enc = tokenizer(
                texts[i : i + batch], truncation=True, padding=True,
                max_length=128, return_tensors="pt",
            )
            probs = torch.sigmoid(model(**enc).logits).numpy()
            out.append((probs >= threshold).astype(int))
    return np.vstack(out)


def _score(y_true, y_pred, label_names: list[str]) -> dict[str, Any]:
    from sklearn.metrics import (
        f1_score,
        precision_recall_fscore_support,
        precision_score,
        recall_score,
    )

    per_class = precision_recall_fscore_support(
        y_true, y_pred, average=None, zero_division=0, labels=range(len(label_names))
    )
    return {
        "macro_f1": round(float(f1_score(y_true, y_pred, average="macro", zero_division=0)), 4),
        "micro_f1": round(float(f1_score(y_true, y_pred, average="micro", zero_division=0)), 4),
        "macro_precision": round(
            float(precision_score(y_true, y_pred, average="macro", zero_division=0)), 4
        ),
        "macro_recall": round(
            float(recall_score(y_true, y_pred, average="macro", zero_division=0)), 4
        ),
        "per_class": {
            label_names[i]: {
                "precision": round(float(p), 3),
                "recall": round(float(r), 3),
                "f1": round(float(f), 3),
                "support": int(sup),
            }
            for i, (p, r, f, sup) in enumerate(zip(*per_class, strict=False))
        },
    }


# ---------------------------------------------------------------- segmentation


def evaluate_segmentation() -> dict[str, Any]:
    """Clause-boundary quality on the documents we have gold structure for.

    The bundled fixture has known structure by construction, which makes this a
    smoke test rather than a real measurement. A genuine number needs the 30
    hand-annotated documents described in PLAN.md section 3.4 - and until those
    exist, this reports what it is rather than pretending otherwise.
    """
    from kwys.segment.segmenter import segment_file

    fixture = ROOT / "tests" / "fixtures" / "sample_lease.pdf"
    if not fixture.exists():
        return {"status": "no fixture"}

    clauses, low, parsed = segment_file(str(fixture))
    expected = {
        "1.1", "1.2", "2.1", "2.2", "2.3", "2.4", "2.5",
        "3.1", "3.2", "3.3", "4.1", "4.2", "4.3", "5.1", "5.2", "6.1",
    }
    found = {c.id for c in clauses}
    tp = len(expected & found)
    precision = tp / max(1, len(found - {"preamble"}))
    recall = tp / max(1, len(expected))
    return {
        "status": "smoke test only - needs the 30-document gold set for a real number",
        "documents": 1,
        "expected_clauses": len(expected),
        "found_clauses": len(found),
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(2 * precision * recall / max(1e-9, precision + recall), 3),
        "low_structure": low,
        "missing": sorted(expected - found),
    }


# ---------------------------------------------------------------- clause type


def evaluate_clause_type() -> dict[str, Any]:
    """Clause-type accuracy on the fixture, whose labels we know.

    Also a smoke test. The real evaluation needs the ~2,000 hand-labelled
    clauses from PLAN.md section 3.4; this exists so a regression in the rules
    is caught rather than discovered later in a report.
    """
    from kwys.classify.model import classify_clauses
    from kwys.models import Domain
    from kwys.segment.segmenter import segment_file

    gold = {
        "1.2": "lock_in_period", "2.1": "rent_and_escalation",
        "2.2": "security_deposit", "2.3": "deposit_refund",
        "2.4": "rent_and_escalation", "2.5": "penalty_and_late_fee",
        "3.1": "maintenance_and_repairs", "3.2": "subletting",
        "3.3": "entry_and_inspection", "4.1": "notice_period",
        "4.2": "termination", "4.3": "termination",
        "5.1": "dispute_resolution", "5.2": "governing_law",
        "6.1": "indemnity",
    }
    fixture = ROOT / "tests" / "fixtures" / "sample_lease.pdf"
    clauses, _, _ = segment_file(str(fixture))
    classify_clauses(clauses, Domain.RESIDENTIAL_LEASE)
    by_id = {c.id: c.clause_type for c in clauses}

    correct = [cid for cid, want in gold.items() if by_id.get(cid) == want]
    wrong = {
        cid: {"expected": want, "got": by_id.get(cid)}
        for cid, want in gold.items()
        if by_id.get(cid) != want
    }
    return {
        "status": "smoke test only - needs ~2,000 labelled clauses for a real number",
        "n": len(gold),
        "correct": len(correct),
        "accuracy": round(len(correct) / len(gold), 3),
        "errors": wrong,
    }


# ---------------------------------------------------------------- reporting


def print_unfair(results: dict[str, Any]) -> None:
    print(f"\nunfair_tos [{results['split']}]  n={results['n']:,}  "
          f"{results['positive_rate']:.1%} of clauses carry at least one label\n")
    print(f"{'system':10} {'macro-F1':>9} {'micro-F1':>9} {'precision':>10} {'recall':>8}")
    print("-" * 50)
    for name, scores in results["systems"].items():
        if scores is None:
            print(f"{name:10} {'not trained yet':>38}")
            continue
        print(f"{name:10} {scores['macro_f1']:>9.3f} {scores['micro_f1']:>9.3f} "
              f"{scores['macro_precision']:>10.3f} {scores['macro_recall']:>8.3f}")

    best = results["systems"].get("trained") or results["systems"]["rules"]
    print(f"\nper class ({'trained' if results['systems'].get('trained') else 'rules'}):")
    print(f"{'':32} {'prec':>6} {'recall':>7} {'F1':>6} {'n':>6}")
    for label, m in sorted(best["per_class"].items(), key=lambda kv: -kv[1]["support"]):
        print(f"  {label:30} {m['precision']:>6.2f} {m['recall']:>7.2f} "
              f"{m['f1']:>6.2f} {m['support']:>6}")

    rules = results["systems"]["rules"]
    trained = results["systems"].get("trained")
    if trained:
        delta = trained["macro_f1"] - rules["macro_f1"]
        verdict = (
            f"The trained model beats the rule baseline by {delta:+.3f} macro-F1."
            if delta > 0.02
            else "The trained model does NOT clearly beat the rule baseline. "
                 "Report that: it is a real result, and it means the added "
                 "complexity has not yet earned its place."
        )
        print(f"\n{verdict}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("what", nargs="?", default="all",
                    choices=["all", "unfair-tos", "segmentation", "clause-type"])
    ap.add_argument("--split", default="test", choices=["train", "validation", "test"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--json", type=Path, help="also write results as JSON")
    args = ap.parse_args()

    out: dict[str, Any] = {}

    if args.what in ("all", "segmentation"):
        out["segmentation"] = evaluate_segmentation()
        r = out["segmentation"]
        print(f"\nsegmentation: F1 {r.get('f1')}  ({r['status']})")
        if r.get("missing"):
            print(f"  missed: {r['missing']}")

    if args.what in ("all", "clause-type"):
        out["clause_type"] = evaluate_clause_type()
        r = out["clause_type"]
        print(f"\nclause type: {r['correct']}/{r['n']} correct  ({r['status']})")
        for cid, e in r["errors"].items():
            print(f"  {cid}: expected {e['expected']}, got {e['got']}")

    if args.what in ("all", "unfair-tos"):
        out["unfair_tos"] = evaluate_unfair_tos(args.split, args.limit)
        print_unfair(out["unfair_tos"])

    if args.json:
        args.json.write_text(json.dumps(out, indent=2))
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
