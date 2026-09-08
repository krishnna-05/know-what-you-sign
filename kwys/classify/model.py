"""Transformer inference, with the rule baseline as fallback.

`classify()` picks whichever classifier is actually available: the fine-tuned
model if one has been trained, the rules otherwise. Nothing else in the codebase
needs to know which ran — but `kwys doctor` reports it, because a report built on
the baseline and one built on a trained model are different claims and the
difference must not be invisible.

Loading is lazy and cached: importing this module must not pull torch into the
process for users who only ever run the rule path.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from kwys.classify.rules import Prediction
from kwys.classify.rules import classify_text as classify_by_rules
from kwys.models import Clause, Domain

log = logging.getLogger(__name__)

MODEL_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "models" / "clause-classifier"

# Below this the model abstains to `other`, exactly as the rules do. A confident
# wrong type routes the clause to the wrong reference distribution and produces a
# well-formatted, wrong percentile - worse than no type at all.
MIN_CONFIDENCE = 0.55


@lru_cache(maxsize=1)
def _load(model_dir: str):
    """Load the fine-tuned classifier, or return None if there isn't one."""
    path = Path(model_dir)
    if not path.exists():
        return None
    try:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(str(path))
        model = AutoModelForSequenceClassification.from_pretrained(str(path))
        model.eval()
        torch.set_num_threads(max(1, (torch.get_num_threads() or 4)))
        log.info("Loaded trained clause classifier from %s", path)
        return tokenizer, model
    except Exception as exc:  # noqa: BLE001 - fall back rather than break the run
        log.warning(
            "Could not load the trained classifier at %s (%s). "
            "Falling back to the rule baseline.",
            path, exc,
        )
        return None


def is_trained_available(model_dir: Path | str = MODEL_DIR) -> bool:
    return Path(model_dir).exists()


def classify_with_model(text: str, model_dir: Path | str = MODEL_DIR) -> Prediction | None:
    """Predict with the fine-tuned model, or None if it isn't available."""
    loaded = _load(str(model_dir))
    if loaded is None:
        return None

    import torch

    tokenizer, model = loaded
    enc = tokenizer(text, truncation=True, max_length=256, return_tensors="pt")
    with torch.no_grad():
        logits = model(**enc).logits[0]
    probs = torch.softmax(logits, dim=-1)
    idx = int(torch.argmax(probs))
    confidence = float(probs[idx])
    label = model.config.id2label[idx]

    if confidence < MIN_CONFIDENCE:
        return Prediction("other", round(confidence, 3), {}, [])

    scores = {
        model.config.id2label[i]: round(float(p), 4)
        for i, p in enumerate(probs)
        if float(p) > 0.01
    }
    return Prediction(label, round(confidence, 3), scores, [])


def classify(text: str, domain: Domain | None = None) -> Prediction:
    """Best available classifier for this text."""
    pred = classify_with_model(text)
    return pred if pred is not None else classify_by_rules(text, domain)


def classify_clauses(clauses: list[Clause], domain: Domain | None = None) -> list[Clause]:
    """Annotate clauses in place, using the trained model when there is one."""
    for clause in clauses:
        pred = classify(clause.context_text, domain)
        clause.clause_type = pred.clause_type
        clause.type_confidence = pred.confidence
    return clauses


def active_classifier() -> str:
    return "trained" if is_trained_available() else "rules"
