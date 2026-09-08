"""Download the public legal-NLP corpora this project transfers from.

WHAT THESE ARE FOR — and what they are NOT for.

LEDGAR and CUAD are US commercial contracts filed with the SEC, negotiated
between institutions with lawyers on both sides. They supply LINGUISTIC
TRANSFER: they teach a model what a termination provision sounds like, which
carries across jurisdictions.

They do NOT supply norms. "Notice period" in a merger agreement and in a
Bengaluru rental agreement are different variables with different distributions,
and computing percentiles over LEDGAR would invalidate the central claim of this
project. The reference corpus for norms must be real Indian agreements of the
same kind as the document being analysed, and it has to be collected by hand.
See PLAN.md sections 0.2 and 3.

No API key is required for any of these.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data" / "external"


def fetch_ledgar(limit: int | None = None) -> Path:
    """LEDGAR: ~80k contract provisions labelled with 100 provision types.

    Distributed as the `ledgar` config of LexGLUE. Used for intermediate
    fine-tuning before the small domain-specific head — see PLAN.md stage 3.
    """
    from datasets import load_dataset

    out = DATA / "ledgar"
    out.mkdir(parents=True, exist_ok=True)

    print("Downloading LEDGAR (coastalcph/lex_glue, config 'ledgar')...")
    ds = load_dataset("coastalcph/lex_glue", "ledgar")

    label_names = ds["train"].features["label"].names
    (out / "labels.json").write_text(json.dumps(label_names, indent=2))

    for split in ("train", "validation", "test"):
        rows = ds[split]
        if limit:
            rows = rows.select(range(min(limit, len(rows))))
        path = out / f"{split}.jsonl"
        with path.open("w") as fh:
            for r in rows:
                fh.write(
                    json.dumps({"text": r["text"], "label": label_names[r["label"]]}) + "\n"
                )
        print(f"  {split}: {len(rows):,} provisions -> {path.name}")

    print(f"  {len(label_names)} provision labels -> labels.json")
    return out


def fetch_cuad() -> Path:
    """CUAD: 510 commercial contracts, 41 clause types, with character spans.

    The spans are the useful part: supervision for span-level extraction and for
    the termination / indemnity / governing-law heads.
    """
    from datasets import load_dataset

    out = DATA / "cuad"
    out.mkdir(parents=True, exist_ok=True)

    print("Downloading CUAD (theatticusproject/cuad-qa)...")
    ds = load_dataset("theatticusproject/cuad-qa", trust_remote_code=False)

    for split in ds:
        path = out / f"{split}.jsonl"
        with path.open("w") as fh:
            for r in ds[split]:
                fh.write(
                    json.dumps(
                        {
                            "id": r.get("id"),
                            "question": r.get("question"),
                            "context": r.get("context", "")[:20000],
                            "answers": r.get("answers"),
                        }
                    )
                    + "\n"
                )
        print(f"  {split}: {len(ds[split]):,} rows -> {path.name}")
    return out


def fetch_inlegalbert() -> Path:
    """InLegalBERT: BERT pretrained on Indian legal text.

    The most relevant encoder available for this project — Indian legal register,
    Indian statutory vocabulary. Legal-BERT and DeBERTa are the ablation
    baselines (PLAN.md section 6).
    """
    from huggingface_hub import snapshot_download

    print("Downloading law-ai/InLegalBERT...")
    path = snapshot_download(
        repo_id="law-ai/InLegalBERT",
        cache_dir=str(DATA / "models"),
        allow_patterns=["*.json", "*.txt", "*.bin", "*.safetensors", "*.model"],
    )
    print(f"  -> {path}")
    return Path(path)


def fetch_unfair_tos() -> Path:
    """LexGLUE unfair_tos: 50 terms-of-service documents, expert-annotated.

    This is the CLAUDETTE annotation applied to consumer terms of service, and
    it is this project's thesis in another domain: an unreadable document, a
    signatory with no bargaining power, and clauses that are unfair in
    identifiable, recurring ways.

    Two things make it valuable here. The documents are public by design, unlike
    rental agreements. And it ships with EXPERT LABELS, which means the unfair
    clause detector can be evaluated against a published benchmark instead of
    needing a lawyer to annotate a gold set by hand.
    """
    import json as _json

    from datasets import load_dataset

    out = DATA / "unfair_tos"
    out.mkdir(parents=True, exist_ok=True)

    print("Downloading unfair_tos (coastalcph/lex_glue, config 'unfair_tos')...")
    ds = load_dataset("coastalcph/lex_glue", "unfair_tos")
    names = ds["train"].features["labels"].feature.names
    (out / "labels.json").write_text(_json.dumps(names, indent=2))

    for split in ds:
        with (out / f"{split}.jsonl").open("w") as fh:
            for r in ds[split]:
                fh.write(
                    _json.dumps(
                        {"text": r["text"], "labels": [names[i] for i in r["labels"]]}
                    ) + "\n"
                )
        print(f"  {split}: {len(ds[split]):,} clauses -> {split}.jsonl")
    print(f"  {len(names)} unfairness types -> labels.json")
    return out


TARGETS = {
    "ledgar": fetch_ledgar,
    "unfair_tos": fetch_unfair_tos,
    "cuad": fetch_cuad,
    "inlegalbert": fetch_inlegalbert,
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("targets", nargs="*", default=list(TARGETS), choices=[*TARGETS, []])
    ap.add_argument("--limit", type=int, help="cap rows per split (for a quick smoke test)")
    args = ap.parse_args()

    targets = args.targets or list(TARGETS)
    DATA.mkdir(parents=True, exist_ok=True)

    failed = []
    for name in targets:
        try:
            if name == "ledgar":
                TARGETS[name](limit=args.limit)
            else:
                TARGETS[name]()
        except Exception as exc:  # noqa: BLE001 - report and continue to the next
            print(f"FAILED {name}: {type(exc).__name__}: {exc}", file=sys.stderr)
            failed.append(name)

    if failed:
        print(f"\n{len(failed)} target(s) failed: {', '.join(failed)}", file=sys.stderr)
        return 1
    print("\nDone. Remember: these give linguistic transfer, not norms.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
