"""Flagging clauses that are unusual in wording rather than in numbers.

Most of this system rests on quantities: a deposit is six months' rent, a notice
period is ninety days. But plenty of harmful clauses contain no number at all -
a sweeping indemnity, an unusual use restriction, a waiver buried in a
maintenance provision. Those need a different measure.

The measure here is distance from the semantic centre of clauses of the same
type. If two hundred termination clauses cluster tightly and yours sits far
outside that cluster, yours says something the others do not.

THIS IS THE WEAKEST LEG OF THE METHOD, BY DESIGN AND BY ADMISSION.

Semantic unusualness is not harm. A clause that is unusually GENEROUS to the
tenant is equally far from the centroid. Distance alone therefore cannot support
a finding, and this module never produces one on its own: the pipeline gates it
behind an independent signal - an asymmetry on the same clause, or an obligation
falling on the user with no counterpart. PLAN.md section 5.2 says so, and the
evaluation reports this leg's contribution separately so a reader can see how
much of the performance comes from the solid parts.

Centroids are built from LEDGAR, which is legitimate here in a way it is NOT
legitimate for numeric norms. LEDGAR gives linguistic transfer - what a
termination provision sounds like - and that carries across jurisdictions. What
it cannot give is Indian rental figures, which is why the numeric norms come
from court judgments instead.

MEASURED FAILURE MODE - report this, do not hide it
---------------------------------------------------
Testing on hand-written clauses showed the transfer is only partial, and it
fails in a way that matters. Distance from the LEDGAR centroid:

    38%   "This agreement may be terminated by either party upon thirty
           days written notice."                                    (ordinary)
   100%   "The Lessee irrevocably waives all rights to notice, hearing,
           or judicial process, and consents to the Lessor entering by
           force..."                                               (egregious)
    92%   "The Lessee shall indemnify the Lessor against all claims
           arising from the Lessee's use of the premises."          (ordinary)
    72%   "The Lessee shall indemnify the Lessor personally and without
           limit against any claim whatsoever including the Lessor's own
           negligence, criminal acts, and unrelated business ventures."
                                                                   (egregious)

The termination pair behaves correctly. The indemnity pair is INVERTED: the
ordinary clause scores higher than the abusive one. The likely cause is domain
mismatch - LEDGAR indemnities are long, verbose US commercial provisions, so a
short plain Indian rental indemnity reads as unusual while a verbose abusive one
reads as familiar.

The conclusion is not that the leg is worthless, but that distance from a
foreign-corpus centroid is not a reliable harm signal on its own. That is
exactly why it is gated behind an independent signal and weighted lowest, and
why the evaluation reports its contribution separately. Fixing it properly needs
centroids built from Indian consumer contracts - which is the same corpus
problem the numeric norms faced, and is listed as future work.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

# Small and fast: 80MB, and this runs on a CPU that is also doing OCR.
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# Below this many examples a centroid is not a centre, it is a coincidence.
MIN_EXAMPLES = 40

# Our clause types mapped onto LEDGAR provision labels. Only types with a
# genuine linguistic counterpart appear: forcing a mapping for "security
# deposit" onto a corpus of SEC filings would produce a confident, meaningless
# centroid.
LEDGAR_MAP: dict[str, list[str]] = {
    "termination": ["Terminations"],
    "notice_period": ["Notices"],
    "indemnity": ["Indemnifications"],
    "governing_law": ["Governing Laws", "Jurisdictions", "Venues"],
    "dispute_resolution": ["Arbitration"],
    "confidentiality": ["Confidentiality"],
    "use_restrictions": ["Use Of Proceeds"],
    "penalty_and_late_fee": ["Fees", "Expenses"],
    "maintenance_and_repairs": ["Maintenance"],
    "subletting": ["Assignments"],
    "ip_assignment": ["Intellectual Property"],
    "non_compete": ["Non-Compete"],
}


@lru_cache(maxsize=1)
def _model() -> Any:
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(EMBEDDING_MODEL)


def embed(texts: list[str]) -> np.ndarray:
    """Unit-normalised embeddings, so cosine distance is a dot product."""
    vecs = _model().encode(texts, show_progress_bar=False, convert_to_numpy=True)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    return vecs / np.maximum(norms, 1e-12)


class SemanticNorms:
    """Per-clause-type centroids and the distance distribution around them."""

    def __init__(self) -> None:
        self.centroids: dict[str, np.ndarray] = {}
        self.distances: dict[str, np.ndarray] = {}  # sorted, for percentiles
        self.counts: dict[str, int] = {}

    def add_type(self, clause_type: str, vectors: np.ndarray) -> None:
        if len(vectors) < MIN_EXAMPLES:
            log.info(
                "skipping %s: only %d examples, below the %d needed for a centroid",
                clause_type, len(vectors), MIN_EXAMPLES,
            )
            return
        centroid = vectors.mean(axis=0)
        centroid /= max(float(np.linalg.norm(centroid)), 1e-12)
        dists = 1.0 - vectors @ centroid
        self.centroids[clause_type] = centroid
        self.distances[clause_type] = np.sort(dists)
        self.counts[clause_type] = len(vectors)

    def outlier_percentile(self, clause_type: str, text: str) -> float | None:
        """How far outside the norm this clause reads, as a percentile.

        Returns None when there is no centroid for the type - which the caller
        must treat as "no information", never as "normal".
        """
        centroid = self.centroids.get(clause_type)
        if centroid is None:
            return None
        vec = embed([text])[0]
        distance = 1.0 - float(vec @ centroid)
        reference = self.distances[clause_type]
        return float(np.searchsorted(reference, distance) / len(reference))

    def save(self, path: Path | str) -> Path:
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            path / "semantic.npz",
            **{f"c__{k}": v for k, v in self.centroids.items()},
            **{f"d__{k}": v for k, v in self.distances.items()},
        )
        (path / "semantic_meta.json").write_text(
            json.dumps(
                {"model": EMBEDDING_MODEL, "min_examples": MIN_EXAMPLES,
                 "counts": self.counts},
                indent=2,
            )
        )
        return path

    @classmethod
    def load(cls, path: Path | str) -> SemanticNorms:
        store = cls()
        npz = Path(path) / "semantic.npz"
        if not npz.exists():
            return store
        data = np.load(npz)
        for key in data.files:
            kind, _, name = key.partition("__")
            if kind == "c":
                store.centroids[name] = data[key]
            elif kind == "d":
                store.distances[name] = data[key]
        meta = Path(path) / "semantic_meta.json"
        if meta.exists():
            store.counts = json.loads(meta.read_text()).get("counts", {})
        return store

    @property
    def is_empty(self) -> bool:
        return not self.centroids
