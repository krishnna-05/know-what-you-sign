"""Build reference distributions from a corpus of collected agreements.

This is the maintainer step the whole system rests on. It reads every PDF in a
directory, runs stages 1-4 of the pipeline over each, and collects the extracted
values into per-field distributions.

The corpus must be REAL agreements of the kind being analysed. Synthetic
documents must never enter it: computing percentiles over documents we generated
ourselves and reporting them as empirical norms would be circular, measuring our
own assumptions and calling it evidence.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from kwys.classify.model import classify_clauses
from kwys.extract.patterns import extract_terms
from kwys.models import Domain
from kwys.norms.store import NormStore
from kwys.segment.segmenter import segment_file

log = logging.getLogger(__name__)

PROVENANCE = "provenance.json"


def _provenance(corpus: Path) -> dict[str, dict[str, Any]]:
    """Per-document source records, if the collector kept them.

    Provenance is not bookkeeping. Template agreements from vendor websites and
    executed agreements from registration portals have different distributions,
    and being able to report the split - and compare the two - is a result in
    itself. Retrofitting it across 400 files later is miserable.
    """
    path = corpus / PROVENANCE
    if not path.exists():
        log.warning(
            "No %s in %s. Source of each document will be recorded as 'unknown', "
            "and the template-vs-executed split cannot be reported.",
            PROVENANCE,
            corpus,
        )
        return {}
    return json.loads(path.read_text())


def build(
    corpus: Path | str, domain: Domain, version: str = "v1"
) -> tuple[NormStore, dict[str, Any]]:
    corpus = Path(corpus)
    store = NormStore(domain=domain.value, version=version)
    prov = _provenance(corpus)

    stats: dict[str, Any] = {
        "documents": 0,
        "failed": [],
        "low_structure": [],
        "clauses": 0,
        "terms": 0,
    }

    pdfs = sorted(corpus.rglob("*.pdf"))
    if not pdfs:
        log.warning("No PDFs found under %s", corpus)
        return store, stats

    for pdf in pdfs:
        try:
            clauses, low, _ = segment_file(str(pdf))
        except Exception as exc:  # noqa: BLE001 - one bad file must not stop the build
            log.warning("Skipped %s: %s", pdf.name, exc)
            stats["failed"].append(pdf.name)
            continue

        if low:
            # Still used: a badly numbered document usually yields SOME clean
            # clauses, and discarding it entirely would bias the corpus toward
            # well-typeset agreements, which are not the ones people get handed.
            stats["low_structure"].append(pdf.name)

        classify_clauses(clauses, domain)
        source = prov.get(pdf.name, {}).get("source", "unknown")

        stats["documents"] += 1
        stats["clauses"] += len(clauses)

        for clause in clauses:
            if not clause.clause_type or clause.clause_type == "other":
                continue
            for term in extract_terms(clause.clause_type, clause.text):
                if not isinstance(term.value, (int, float)) or isinstance(term.value, bool):
                    continue
                store.add(
                    f"{clause.clause_type}.{term.field}",
                    float(term.value),
                    term.unit or "",
                    source=source,
                )
                stats["terms"] += 1

    log.info(
        "Built %d field norms from %d documents (%d terms)",
        len(store),
        stats["documents"],
        stats["terms"],
    )
    return store, stats


# ---------------------------------------------------------------- judgments

JUDGMENT_BIAS = (
    "Built from terms recited in published court judgments. Only DISPUTED "
    "tenancies reach court, so this corpus over-represents conflict-prone "
    "agreements and probably harsher-than-average terms. Treat percentiles as "
    "indicative of litigated tenancies, not of the rental market as a whole."
)

# The harvester names fields as they appear in a judgment; the norm store keys
# them by clause type, as the analyser looks them up.
FIELD_TO_KEY = {
    "deposit_months": "security_deposit.deposit_months",
    "notice_months": "notice_period.notice_months",
    "lock_in_months": "lock_in_period.lock_in_months",
    # deposit_inr and monthly_rent_inr are inputs to the ratio, not comparable
    # quantities themselves: Rs.2,00,000 means different things in different
    # cities, whereas "four months' rent" travels.
}


def build_from_judgments(
    values_path: Path | str,
    domain: Domain = Domain.RESIDENTIAL_LEASE,
    version: str = "judgments-v1",
    *,
    residential_only: bool = False,
) -> tuple[NormStore, dict[str, Any]]:
    """Build a norm store from harvested judgment values.

    One value per judgment per field: a judgment that recites the same term
    three times must not weigh three times as much as one that states it once.
    """
    values_path = Path(values_path)
    store = NormStore(domain=domain.value, version=version, corpus_bias=JUDGMENT_BIAS)
    stats: dict[str, Any] = {"records": 0, "used": 0, "judgments": set(), "skipped": {}}

    best: dict[tuple[str, str], dict] = {}  # (doc_id, field) -> record

    with values_path.open() as fh:
        for line in fh:
            if not line.strip():
                continue
            rec = json.loads(line)
            stats["records"] += 1

            key = FIELD_TO_KEY.get(rec["field"])
            if key is None:
                stats["skipped"]["not_a_norm_field"] = (
                    stats["skipped"].get("not_a_norm_field", 0) + 1
                )
                continue
            if residential_only and rec.get("property_type") != "residential":
                stats["skipped"]["non_residential"] = (
                    stats["skipped"].get("non_residential", 0) + 1
                )
                continue

            best.setdefault((rec["doc_id"], rec["field"]), rec)

    for (doc_id, field_name), rec in best.items():
        key = FIELD_TO_KEY[field_name]
        store.add(key, float(rec["value"]), rec["unit"], source=f"judgment:{doc_id}")
        stats["used"] += 1
        stats["judgments"].add(doc_id)

    stats["judgments"] = len(stats["judgments"])
    log.info(
        "Built %d field norms from %d judgments (%d values kept of %d records)",
        len(store), stats["judgments"], stats["used"], stats["records"],
    )
    return store, stats
