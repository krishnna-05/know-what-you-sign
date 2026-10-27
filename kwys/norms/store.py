"""Empirical norms: what a clause term actually looks like across real agreements.

This module is the intellectual core of the project and it contains no machine
learning at all. It is descriptive statistics over a corpus — an empirical CDF, a
median, a robust spread, and a bootstrap confidence interval on the percentile.

The single most important behaviour here is REFUSING TO ANSWER. A percentile
computed from eleven agreements is not the same claim as one computed from three
hundred, and a tool aimed at people who cannot check our working must not present
them identically. Below MIN_N the store returns a lookup marked `sufficient=False`
and the scorer declines to make a deviation claim from it.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

# Below this many observations we do not assert a percentile. 30 is the
# conventional floor for a stable empirical quantile and, at n=30, the bootstrap
# CI on a mid-range percentile is roughly +/-0.15 — wide, but honest.
MIN_N = 30

BOOTSTRAP_RESAMPLES = 1000
BOOTSTRAP_SEED = 20260908  # fixed: norms must be reproducible from a corpus


@dataclass
class FieldNorm:
    """The distribution of one field within one clause type."""

    field_key: str  # "security_deposit.deposit_months"
    unit: str
    values: list[float]
    corpus_version: str
    sources: dict[str, int] = field(default_factory=dict)  # provenance counts

    # ---------------------------------------------------------------- stats

    @property
    def n(self) -> int:
        return len(self.values)

    @property
    def sufficient(self) -> bool:
        return self.n >= MIN_N

    @property
    def sorted_values(self) -> np.ndarray:
        return np.sort(np.asarray(self.values, dtype=float))

    @property
    def median(self) -> float:
        return float(np.median(self.values)) if self.values else float("nan")

    @property
    def mad(self) -> float:
        """Median absolute deviation — a spread measure that a single absurd
        outlier cannot inflate, unlike the standard deviation."""
        if not self.values:
            return float("nan")
        arr = np.asarray(self.values, dtype=float)
        return float(np.median(np.abs(arr - np.median(arr))))

    def percentile_of(self, x: float) -> float:
        """Empirical CDF at x, with midpoint handling for ties.

        Ties matter here more than in most data: contract terms cluster hard on
        round numbers, so "2 months" may be a fifth of the corpus. Counting
        equal values as half-below is the standard mid-rank treatment and stops
        a modal value reading as either the 5th or the 25th percentile
        depending on which comparison operator we happened to write.
        """
        if not self.values:
            return float("nan")
        arr = self.sorted_values
        below = float(np.count_nonzero(arr < x))
        equal = float(np.count_nonzero(arr == x))
        return (below + 0.5 * equal) / len(arr)

    def bootstrap_ci(self, x: float, alpha: float = 0.05) -> tuple[float, float]:
        """Percentile bootstrap CI on the percentile of x.

        Resamples the corpus with replacement and recomputes where x falls. A
        wide interval is the honest output of a small corpus and the report
        shows it rather than hiding it behind a point estimate.
        """
        if not self.values:
            return (float("nan"), float("nan"))
        rng = np.random.default_rng(BOOTSTRAP_SEED)
        arr = np.asarray(self.values, dtype=float)
        n = len(arr)
        draws = rng.choice(arr, size=(BOOTSTRAP_RESAMPLES, n), replace=True)
        below = (draws < x).sum(axis=1)
        equal = (draws == x).sum(axis=1)
        pcts = (below + 0.5 * equal) / n
        lo, hi = np.quantile(pcts, [alpha / 2, 1 - alpha / 2])
        return (float(lo), float(hi))

    def robust_z(self, x: float) -> float:
        """(x - median) / (1.4826 * MAD): a z-score that outliers cannot skew.

        1.4826 rescales the MAD so that for normally distributed data it matches
        the standard deviation, keeping the number interpretable.
        """
        mad = self.mad
        if not np.isfinite(mad) or mad == 0:
            # A degenerate spread means every agreement says the same thing.
            # Any departure at all is then notable, but a z-score would be
            # infinite, so report the direction with a bounded magnitude.
            if not self.values:
                return float("nan")
            return 0.0 if x == self.median else (3.0 if x > self.median else -3.0)
        return float((x - self.median) / (1.4826 * mad))

    def quantile(self, q: float) -> float:
        return float(np.quantile(self.values, q)) if self.values else float("nan")

    def summary(self) -> dict[str, Any]:
        return {
            "field_key": self.field_key,
            "unit": self.unit,
            "n": self.n,
            "sufficient": self.sufficient,
            "median": None if not self.values else round(self.median, 4),
            "mad": None if not self.values else round(self.mad, 4),
            "p05": None if not self.values else round(self.quantile(0.05), 4),
            "p25": None if not self.values else round(self.quantile(0.25), 4),
            "p75": None if not self.values else round(self.quantile(0.75), 4),
            "p95": None if not self.values else round(self.quantile(0.95), 4),
            "corpus_version": self.corpus_version,
            "sources": self.sources,
        }

    def to_json(self) -> dict[str, Any]:
        return {**self.summary(), "values": [round(v, 6) for v in self.values]}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> FieldNorm:
        return cls(
            field_key=data["field_key"],
            unit=data["unit"],
            values=list(data.get("values", [])),
            corpus_version=data.get("corpus_version", "unknown"),
            sources=data.get("sources", {}),
        )


class NormStore:
    """All field distributions for one domain, at one corpus version."""

    def __init__(
        self,
        domain: str,
        version: str = "v1",
        corpus_bias: str | None = None,
        label: str | None = None,
    ) -> None:
        self.domain = domain
        self.version = version
        # What a reader is shown instead of the version string, which is a
        # maintainer's identifier ("judgments-v1") and means nothing to them.
        self.label = label
        # A one-line statement of what this corpus over- or under-represents,
        # carried into the manifest and surfaced in every report built on it.
        self.corpus_bias = corpus_bias
        self._norms: dict[str, FieldNorm] = {}

    # ---------------------------------------------------------------- build

    def add(self, field_key: str, value: float, unit: str, source: str = "unknown") -> None:
        norm = self._norms.get(field_key)
        if norm is None:
            norm = FieldNorm(
                field_key=field_key, unit=unit, values=[], corpus_version=self.version
            )
            self._norms[field_key] = norm
        norm.values.append(float(value))
        norm.sources[source] = norm.sources.get(source, 0) + 1

    def get(self, field_key: str) -> FieldNorm | None:
        return self._norms.get(field_key)

    def __contains__(self, field_key: str) -> bool:
        return field_key in self._norms

    def __len__(self) -> int:
        return len(self._norms)

    def coverage(self) -> dict[str, dict[str, Any]]:
        """What the store can and cannot currently speak to.

        Surfaced by `kwys doctor` so a thin corpus is visible as a number rather
        than discovered later as a suspiciously quiet report.
        """
        return {
            key: {"n": norm.n, "sufficient": norm.sufficient, "unit": norm.unit}
            for key, norm in sorted(self._norms.items())
        }

    # ---------------------------------------------------------------- io

    def save(self, root: Path | str) -> Path:
        out = Path(root) / self.version / self.domain
        out.mkdir(parents=True, exist_ok=True)
        for key, norm in self._norms.items():
            (out / f"{key}.json").write_text(json.dumps(norm.to_json(), indent=2))
        manifest = {
            "domain": self.domain,
            "version": self.version,
            "fields": self.coverage(),
            "min_n": MIN_N,
            "corpus_bias": self.corpus_bias,
            "label": self.label,
        }
        (out / "_manifest.json").write_text(json.dumps(manifest, indent=2))
        log.info("Wrote %d field norms to %s", len(self._norms), out)
        return out

    @classmethod
    def load(cls, root: Path | str, domain: str, version: str = "v1") -> NormStore:
        store = cls(domain=domain, version=version)
        path = Path(root) / version / domain
        manifest = path / "_manifest.json"
        if manifest.exists():
            try:
                meta = json.loads(manifest.read_text())
                store.corpus_bias = meta.get("corpus_bias")
                store.label = meta.get("label")
            except (OSError, ValueError):
                pass
        if not path.exists():
            log.warning(
                "No norm store at %s. The pipeline will run, but every deviation "
                "claim will be suppressed as unsupported. Build norms with "
                "`kwys build-norms` once you have a reference corpus.",
                path,
            )
            return store
        for f in path.glob("*.json"):
            if f.name.startswith("_"):
                continue
            norm = FieldNorm.from_json(json.loads(f.read_text()))
            store._norms[norm.field_key] = norm
        return store

    @property
    def is_empty(self) -> bool:
        return not self._norms


def is_synthetic(version: str) -> bool:
    return "SYNTHETIC" in version.upper()


def available_versions(root: Path | str, domain: str) -> list[str]:
    """Every corpus version built for this domain, real ones first.

    Synthetic corpora sort last so they can never become the default: a warning
    banner is not enough protection when the alternative is someone skimming
    fabricated percentiles.
    """
    root = Path(root)
    if not root.is_dir():
        return []
    versions = [p.name for p in root.iterdir() if (p / domain).is_dir()]
    # Self-reported figures sit between the two: real, but unverified, so a
    # corpus with checkable sources is preferred as the default.
    return sorted(
        versions, key=lambda v: (is_synthetic(v), v.startswith("contributed"), v.lower())
    )


def display_label(store: NormStore) -> str:
    """The reader-facing name of a corpus, whatever its manifest says."""
    if is_synthetic(store.version):
        return "Invented demo data (for testing only)"
    return store.label or store.version


def default_version(root: Path | str, domain: str) -> str | None:
    """The corpus to compare against when nobody asked for one: the first real one."""
    return next((v for v in available_versions(root, domain) if not is_synthetic(v)), None)
