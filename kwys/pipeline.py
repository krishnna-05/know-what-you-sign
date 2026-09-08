"""End-to-end analysis: PDF in, ranked justified findings out.

Stages run in order and each one degrades honestly rather than failing:
a scanned page without OCR is reported as unreadable, an unclassifiable clause
abstains to `other`, and a field with no reference distribution produces no
deviation claim. The alternative — filling gaps with guesses — produces a report
that looks complete and is wrong, which is the worst outcome for a user who
cannot check our working.
"""

from __future__ import annotations

import logging
from pathlib import Path

from kwys import config as C
from kwys.asymmetry.obligations import (
    extract_obligations,
    find_asymmetries,
    find_missing_clauses,
    find_paired_asymmetries,
)
from kwys.asymmetry.parties import build_party_map
from kwys.classify.model import classify_clauses
from kwys.extract.patterns import contradiction_warning, extract_terms
from kwys.models import AnalysisResult, Document, Domain, Role, Severity
from kwys.norms.store import NormStore
from kwys.score.scorer import Scorer
from kwys.segment.segmenter import segment

log = logging.getLogger(__name__)

DATA_ROOT = Path(__file__).resolve().parent.parent / "data"


def analyse(
    path: str | Path,
    *,
    role: Role,
    domain: Domain,
    user_city: str | None = None,
    user_state: str | None = None,
    norms_root: Path | str | None = None,
    corpus_version: str = "v1",
    show_low: bool = False,
) -> AnalysisResult:
    """Analyse one agreement."""
    from kwys.ingest.pdf_reader import read_pdf

    parsed = read_pdf(path)
    warnings = list(parsed.warnings)

    clauses, low_structure = segment(parsed)
    if low_structure:
        warnings.append(
            "This document does not use consistent clause numbering, so it could "
            "not be split reliably. Findings below may be incomplete — treat them "
            "as a starting point, not a full review."
        )

    classify_clauses(clauses, domain)

    document = Document(
        path=str(path),
        domain=domain,
        user_role=role,
        user_city=user_city,
        page_count=parsed.page_count,
        was_ocred=parsed.was_ocred,
        low_structure=low_structure,
        clauses=clauses,
    )

    norms = NormStore.load(
        norms_root or (DATA_ROOT / "norms"), domain.value, corpus_version
    )
    if norms.corpus_bias:
        # A corpus's bias must reach the reader, not just sit in the manifest.
        # Percentiles from litigated tenancies and percentiles from a random
        # sample support different claims, and the user cannot tell them apart.
        warnings.append(f"About the comparison data: {norms.corpus_bias}")

    if not norms.is_empty and "SYNTHETIC" in corpus_version.upper():
        warnings.append(
            "THESE COMPARISONS ARE NOT REAL. This report was built against a "
            "synthetic demo corpus generated for testing. The percentages below "
            "describe invented data, not actual agreements. Build real norms "
            "with `kwys build-norms` before showing this to anyone."
        )

    if norms.is_empty:
        warnings.append(
            "No reference corpus is loaded, so no clause can be compared against "
            "what is normal. Only one-sided obligations and missing clauses are "
            "reported below. Build norms with `kwys build-norms` to enable "
            "deviation findings."
        )

    scorer = Scorer(domain=domain, role=role, norms=norms, user_state=user_state)
    pmap = build_party_map(parsed.text, domain)
    findings = []

    # --- deviation findings -------------------------------------------------
    clause_terms: list[tuple] = []
    for clause in clauses:
        if not clause.clause_type or clause.clause_type == "other":
            continue

        note = contradiction_warning(clause.text)
        if note:
            warnings.append(f"Clause {clause.id}: {note}")

        terms = extract_terms(clause.clause_type, clause.text)
        clause_terms.append((clause, terms))

        for term in terms:
            scored = scorer.score_term(clause.clause_type, term)
            finding = scorer.finding_from_term(clause, scored)
            if finding:
                findings.append(finding)

    # --- structural findings ------------------------------------------------
    obligations = [o for c in clauses for o in extract_obligations(c, pmap)]
    by_id = {c.id: c for c in clauses}

    # Paired comparison first: "you give 6 months, they give 15 days" is a
    # stronger and more actionable finding than "no mirror clause found", and
    # both would otherwise fire on the same provision.
    paired_clause_ids = set()
    for clause_id, detail, extra in find_paired_asymmetries(clause_terms, pmap):
        clause = by_id.get(clause_id)
        if clause:
            paired_clause_ids.update(extra["clauses"])
            findings.append(scorer.finding_from_paired(clause, detail, extra))

    for clause_id, detail in find_asymmetries(clauses, obligations, pmap):
        if clause_id in paired_clause_ids:
            continue  # already reported, with numbers attached
        clause = by_id.get(clause_id)
        if clause:
            findings.append(scorer.finding_from_asymmetry(clause, detail))

    for clause_type, detail in find_missing_clauses(clauses, domain):
        findings.append(scorer.finding_from_missing(clause_type, detail))

    findings.sort(key=lambda f: f.score, reverse=True)
    if not show_low:
        findings = [f for f in findings if f.severity is not Severity.LOW]

    if pmap.unresolved:
        warnings.append(
            "Some defined parties could not be matched to a side: "
            + ", ".join(pmap.unresolved[:4])
        )

    return AnalysisResult(
        document=document,
        findings=findings,
        clauses_checked=len([c for c in clauses if c.id != "preamble"]),
        corpus_version=corpus_version if not norms.is_empty else None,
        warnings=warnings,
    )


def unverified_anchor_warning() -> str | None:
    pending = C.unverified_anchors()
    if not pending:
        return None
    return (
        f"{len(pending)} statutory anchor(s) are not yet verified and are being "
        "skipped. Findings will rely on the corpus alone until someone checks "
        "them against the bare Act."
    )
