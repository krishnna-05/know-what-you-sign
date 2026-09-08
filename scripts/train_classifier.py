"""Train the clause-type classifier.

Two stages, per PLAN.md section 3:

  1. INTERMEDIATE fine-tuning on LEDGAR (80k US contract provisions, 100 labels).
     This teaches the encoder what contract language looks like. It is linguistic
     transfer only - LEDGAR contains no Indian rental agreements and supplies no
     norms.
  2. DOMAIN fine-tuning on your own labelled clauses (~2,000 across 15 types).
     This adapts the model to the vocabulary people actually get handed.

Stage 1 on 80k provisions is too slow on an Intel Mac CPU (many hours). Run it on
Colab's free GPU and download the checkpoint; stage 2 on 2k clauses is perfectly
comfortable locally. `--stage 2 --from-base` skips stage 1 entirely, which is the
right first experiment: if the LEDGAR stage does not measurably help, it has not
earned its complexity, and that is a reportable ablation either way.

Usage
-----
  python scripts/train_classifier.py --stage 1 --epochs 2          # Colab
  python scripts/train_classifier.py --stage 2 --labels data/corpus/labelled.jsonl
  python scripts/train_classifier.py --stage 2 --from-base ...     # ablation arm
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("train")

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# Indian legal register, Indian statutory vocabulary. Legal-BERT and DeBERTa are
# the ablation baselines the evaluation requires - all three, same split.
BASE_MODELS = {
    "inlegalbert": "law-ai/InLegalBERT",
    "legalbert": "nlpaueb/legal-bert-base-uncased",
    "deberta": "microsoft/deberta-v3-base",
}


def _ensure_loadable(base: str) -> str:
    """Convert a legacy .bin checkpoint to safetensors if torch is too old.

    transformers >= 4.56 blocks torch.load below torch 2.6 (CVE-2025-32434), and
    Intel-Mac torch caps at 2.2.2. All three encoders this project evaluates ship
    only .bin. Converting once, up front, beats failing mid-run with a traceback
    that says nothing about what to do next.
    """
    import torch
    from packaging.version import Version

    if Version(torch.__version__.split("+")[0]) >= Version("2.6"):
        return base
    if Path(base).exists():
        return base  # a local checkpoint we saved ourselves is already safetensors

    from scripts.convert_to_safetensors import TRUSTED_REPOS, convert

    if base not in TRUSTED_REPOS:
        log.warning(
            "torch %s cannot load legacy .bin checkpoints and %s is not in the "
            "trusted conversion list. Run scripts/convert_to_safetensors.py "
            "--force if you are sure of the source.",
            torch.__version__, base,
        )
        return base

    log.info("torch %s predates 2.6; converting %s to safetensors first",
             torch.__version__, base)
    return str(convert(base))


def _load_jsonl(path: Path) -> list[dict]:
    with path.open() as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _tokenize(tokenizer, texts: list[str], max_length: int):
    return tokenizer(
        texts, truncation=True, padding="max_length", max_length=max_length
    )


def train(
    *,
    stage: int,
    base: str,
    out: Path,
    labels_path: Path | None,
    epochs: float,
    batch_size: int,
    max_length: int,
    lr: float,
    limit: int | None,
) -> Path:
    import numpy as np
    import torch
    from sklearn.metrics import classification_report, f1_score
    from torch.utils.data import Dataset
    from transformers import (
        AutoModelForSequenceClassification,
        AutoTokenizer,
        Trainer,
        TrainingArguments,
    )

    if stage == 1:
        ledgar = DATA / "external" / "ledgar"
        if not ledgar.exists():
            raise SystemExit(
                f"LEDGAR not found at {ledgar}. Run: python scripts/fetch_datasets.py ledgar"
            )
        train_rows = _load_jsonl(ledgar / "train.jsonl")
        eval_rows = _load_jsonl(ledgar / "validation.jsonl")
    else:
        if labels_path is None or not labels_path.exists():
            raise SystemExit(
                "Stage 2 needs your labelled clauses: --labels data/corpus/labelled.jsonl\n"
                'Each line: {"text": "...", "label": "security_deposit"}\n'
                "See PLAN.md section 3.4 for the annotation plan."
            )
        rows = _load_jsonl(labels_path)
        if len(rows) < 200:
            log.warning(
                "Only %d labelled clauses. Expect an unstable model; the plan "
                "budgets ~2,000 across 15 types.",
                len(rows),
            )
        split = int(len(rows) * 0.8)
        train_rows, eval_rows = rows[:split], rows[split:]

    if limit:
        train_rows = train_rows[:limit]
        eval_rows = eval_rows[: max(1, limit // 5)]

    label_names = sorted({r["label"] for r in train_rows} | {r["label"] for r in eval_rows})
    label_to_id = {name: i for i, name in enumerate(label_names)}
    log.info(
        "Stage %d: %d train / %d eval, %d labels, base=%s",
        stage, len(train_rows), len(eval_rows), len(label_names), base,
    )

    base = _ensure_loadable(base)

    tokenizer = AutoTokenizer.from_pretrained(base)
    model = AutoModelForSequenceClassification.from_pretrained(
        base,
        num_labels=len(label_names),
        id2label={i: n for n, i in label_to_id.items()},
        label2id=label_to_id,
        ignore_mismatched_sizes=True,  # the stage-1 head has 100 labels, stage 2 has ~15
    )

    class ClauseDataset(Dataset):
        def __init__(self, rows: list[dict]) -> None:
            self.enc = _tokenize(tokenizer, [r["text"] for r in rows], max_length)
            self.labels = [label_to_id[r["label"]] for r in rows]

        def __len__(self) -> int:
            return len(self.labels)

        def __getitem__(self, i: int) -> dict:
            item = {k: torch.tensor(v[i]) for k, v in self.enc.items()}
            item["labels"] = torch.tensor(self.labels[i])
            return item

    def metrics(pred):
        preds = np.argmax(pred.predictions, axis=1)
        return {
            "macro_f1": f1_score(pred.label_ids, preds, average="macro", zero_division=0),
            "micro_f1": f1_score(pred.label_ids, preds, average="micro", zero_division=0),
        }

    out.mkdir(parents=True, exist_ok=True)
    args = TrainingArguments(
        output_dir=str(out / "checkpoints"),
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        per_device_eval_batch_size=batch_size * 2,
        learning_rate=lr,
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="macro_f1",
        logging_steps=50,
        report_to=[],
        use_cpu=not torch.cuda.is_available(),
        seed=20260908,
    )

    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=ClauseDataset(train_rows),
        eval_dataset=ClauseDataset(eval_rows),
        compute_metrics=metrics,
    )
    trainer.train()

    result = trainer.evaluate()
    log.info("macro-F1 %.4f | micro-F1 %.4f", result["eval_macro_f1"], result["eval_micro_f1"])

    preds = np.argmax(trainer.predict(ClauseDataset(eval_rows)).predictions, axis=1)
    # `labels` must be given explicitly: an eval split need not contain every
    # class, and without it sklearn matches target_names against only the classes
    # actually present and raises. Real runs hit this too — rare clause types are
    # exactly the ones a random split drops.
    report = classification_report(
        [label_to_id[r["label"]] for r in eval_rows],
        preds,
        labels=list(range(len(label_names))),
        target_names=label_names,
        zero_division=0,
        output_dict=True,
    )

    trainer.save_model(str(out))
    tokenizer.save_pretrained(str(out))
    (out / "eval_report.json").write_text(
        json.dumps(
            {
                "stage": stage,
                "base_model": base,
                "labels": label_names,
                "macro_f1": result["eval_macro_f1"],
                "micro_f1": result["eval_micro_f1"],
                "per_class": report,
                "n_train": len(train_rows),
                "n_eval": len(eval_rows),
            },
            indent=2,
        )
    )
    log.info("Saved to %s", out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stage", type=int, choices=(1, 2), required=True)
    ap.add_argument(
        "--base", default="inlegalbert",
        help=f"one of {list(BASE_MODELS)}, or any Hugging Face model id",
    )
    ap.add_argument("--from-base", action="store_true",
                    help="stage 2 without the LEDGAR stage - the ablation arm")
    ap.add_argument("--labels", type=Path, default=DATA / "corpus" / "labelled.jsonl")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--epochs", type=float, default=3.0)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--max-length", type=int, default=256)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--limit", type=int, help="cap rows, for a quick smoke test")
    args = ap.parse_args()

    base = BASE_MODELS.get(args.base, args.base)
    stage1_out = DATA / "models" / "ledgar-stage1"

    if args.stage == 2 and not args.from_base:
        if stage1_out.exists():
            base = str(stage1_out)
            log.info("Starting from the LEDGAR-tuned checkpoint at %s", stage1_out)
        else:
            log.warning(
                "No stage-1 checkpoint at %s; starting from the base encoder. "
                "This is the --from-base ablation arm, so record it as such.",
                stage1_out,
            )

    out = args.out or (
        stage1_out if args.stage == 1 else DATA / "models" / "clause-classifier"
    )
    train(
        stage=args.stage, base=base, out=out, labels_path=args.labels,
        epochs=args.epochs, batch_size=args.batch_size, max_length=args.max_length,
        lr=args.lr, limit=args.limit,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
