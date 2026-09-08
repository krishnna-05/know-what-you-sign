"""Detecting unfair clauses in consumer terms of service.

Picks the trained detector when one exists and the rule baseline otherwise, the
same way clause-type classification does. `kwys doctor` reports which is live,
because a report produced by the baseline and one produced by a trained model
are different claims.

Categories follow LexGLUE unfair_tos, which applies the CLAUDETTE annotation
scheme to consumer terms of service. Using a published label set rather than one
of our own means the detector can be measured against work other people have
done, instead of only against itself.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

from kwys.classify.unfair_rules import predict as rule_predict

log = logging.getLogger(__name__)

MODEL_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "models" / "unfair-tos"

# Plain-language descriptions. The label names come from an academic annotation
# scheme and mean nothing to the person this tool exists for: "Unilateral
# change" is not a phrase anyone outside contract law would use.
DESCRIPTIONS: dict[str, tuple[str, str]] = {
    "Limitation of liability": (
        "They limit what they owe you if something goes wrong",
        "Ask what you would actually be entitled to if their service caused you a loss.",
    ),
    "Unilateral termination": (
        "They can cut off your account, you cannot do the same to them",
        "Ask what notice you would get, and what happens to anything you have paid for.",
    ),
    "Unilateral change": (
        "They can change these terms whenever they like",
        "Ask whether you will be told before the terms change, and whether "
        "you can leave if you disagree.",
    ),
    "Content removal": (
        "They can delete what you post without telling you",
        "Ask whether you can get a copy of your content before it is removed.",
    ),
    "Contract by using": (
        "Simply using the service counts as agreeing to all of this",
        "Worth knowing: you may be bound by terms you were never shown.",
    ),
    "Choice of law": (
        "Disputes are decided under another country's law",
        "Ask which country's law applies, and whether your local consumer protections still hold.",
    ),
    "Jurisdiction": (
        "Any dispute has to be taken to a court somewhere else",
        "Ask where a dispute would have to be heard, and what that would cost you to do.",
    ),
    "Arbitration": (
        "You give up the right to go to court, and often to join a group claim",
        "Ask whether you can opt out of arbitration, and by when.",
    ),
}


@lru_cache(maxsize=1)
def _load(model_dir: str):
    path = Path(model_dir)
    if not (path / "config.json").exists():
        return None
    try:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(str(path))
        model = AutoModelForSequenceClassification.from_pretrained(str(path))
        model.eval()

        threshold = 0.5
        report = path / "eval_report.json"
        if report.exists():
            threshold = json.loads(report.read_text()).get("threshold", 0.5)

        log.info("Loaded unfair-clause detector from %s (threshold %.2f)", path, threshold)
        return tokenizer, model, threshold, torch
    except Exception as exc:  # noqa: BLE001 - fall back rather than break the run
        log.warning("Could not load the unfair-clause model (%s); using rules.", exc)
        return None


def predict(text: str, model_dir: Path | str = MODEL_DIR) -> list[str]:
    """Which kinds of unfairness this clause shows."""
    loaded = _load(str(model_dir))
    if loaded is None:
        return rule_predict(text)

    tokenizer, model, threshold, torch = loaded
    enc = tokenizer(text, truncation=True, max_length=256, return_tensors="pt")
    with torch.no_grad():
        probs = torch.sigmoid(model(**enc).logits)[0]
    return [
        model.config.id2label[i]
        for i, p in enumerate(probs)
        if float(p) >= threshold
    ]


def active_detector(model_dir: Path | str = MODEL_DIR) -> str:
    return "trained" if _load(str(model_dir)) is not None else "rules"


def describe(label: str) -> tuple[str, str]:
    """Plain-language headline and question for an unfairness category."""
    return DESCRIPTIONS.get(
        label, (label, "Ask what this clause means for you in practice.")
    )
