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
    PAIRED_FIELDS,
    attribute_clause_to_party,
    extract_obligations,
    find_asymmetries,
    find_missing_clauses,
    find_paired_asymmetries,
)
from kwys.asymmetry.parties import build_party_map
from kwys.classify.model import classify_clauses
from kwys.extract.patterns import (
    contradiction_warning,
    derive_deposit_months,
    extract_terms,
)
from kwys.models import (
    AnalysisResult,
    Document,
    Domain,
    Modality,
    Role,
    Severity,
    UnassessedTerm,
)
from kwys.norms.store import NormStore, default_version, is_synthetic
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
    corpus_version: str | None = None,
    show_low: bool = False,
    semantic: bool = False,
) -> AnalysisResult:
    """Analyse one agreement.

    With no `corpus_version`, compares against the first real corpus built for
    the domain - never a synthetic one.
    """
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

    norms_root = Path(norms_root or (DATA_ROOT / "norms"))
    corpus_version = corpus_version or default_version(norms_root, domain.value)
    norms = (
        NormStore.load(norms_root, domain.value, corpus_version)
        if corpus_version
        else NormStore(domain.value)
    )
    is_tos = domain is Domain.CONSUMER_TOS
    if norms.corpus_bias:
        # A corpus's bias must reach the reader, not just sit in the manifest.
        # Percentiles from litigated tenancies and percentiles from a random
        # sample support different claims, and the user cannot tell them apart.
        warnings.append(f"About the comparison data: {norms.corpus_bias}")

    if not norms.is_empty and is_synthetic(corpus_version):
        warnings.append(
            "THESE COMPARISONS ARE NOT REAL. This report was built against a "
            "synthetic demo corpus generated for testing. The percentages below "
            "describe invented data, not actual agreements. Build real norms "
            "with `kwys build-norms` before showing this to anyone."
        )

    if norms.is_empty and not is_tos:
        warnings.append(
            "No reference corpus is loaded, so no clause can be compared against "
            "what is normal. Only one-sided obligations and missing clauses are "
            "reported below. Build norms with `kwys build-norms` to enable "
            "deviation findings."
        )

    pending_anchors = unverified_anchor_warning()
    if pending_anchors and not is_tos:
        warnings.append(pending_anchors)

    scorer = Scorer(domain=domain, role=role, norms=norms, user_state=user_state)
    pmap = build_party_map(parsed.text, domain)
    findings = []

    # --- consumer terms of service ------------------------------------------
    # A different problem shape: no numeric norms to deviate from, but an
    # expert-annotated set of unfairness categories to match against.
    if domain is Domain.CONSUMER_TOS:
        from kwys.classify.unfair import active_detector
        from kwys.classify.unfair import predict as predict_unfair

        for clause in clauses:
            unfair = predict_unfair(clause.text)
            if unfair:
                findings.append(scorer.finding_from_unfair(clause, unfair))

        findings.sort(key=lambda f: f.score, reverse=True)
        if active_detector() == "rules":
            warnings.append(
                "No trained unfair-clause detector was found, so this used the "
                "rule baseline, which finds roughly a third of what an expert "
                "would flag. Train one with: python scripts/train_classifier.py "
                "--task unfair-tos"
            )
        return AnalysisResult(
            document=document,
            findings=findings,
            clauses_checked=len(clauses),
            warnings=warnings,
        )

    # --- deviation findings -------------------------------------------------
    # Extract everything first: some figures can only be worked out from terms
    # that sit in another clause (a deposit in rupees needs the monthly rent).
    clause_terms: list[tuple] = []
    for clause in clauses:
        if not clause.clause_type or clause.clause_type == "other":
            continue

        note = contradiction_warning(clause.text)
        if note:
            warnings.append(f"Clause {clause.id}: {note}")

        clause_terms.append((clause, extract_terms(clause.clause_type, clause.text)))

    _derive_deposit_months(clause_terms)
    unassessed: list[tuple] = []

    for clause, terms in clause_terms:
        # Some fields belong to a PARTY, not to the agreement. A notice period
        # is one side's obligation, and the same six months is a burden for
        # whoever must give it and a benefit for the other. Scoring it without
        # asking whose it is told a landlord "yours is 6 months" about a clause
        # binding the tenant. Fields like the deposit or the lock-in belong to
        # the agreement as a whole and are scored for either reader via the
        # direction map.
        bound = attribute_clause_to_party(clause, pmap)

        for term in terms:
            if term.field in PAIRED_FIELDS and bound is not None and bound is not role:
                continue
            scored = scorer.score_term(clause.clause_type, term)
            # The corpus first; then the law, which needs no corpus; then a
            # declared rule of thumb. The first that has something to say wins,
            # so one term never produces two findings.
            finding = (
                scorer.finding_from_term(clause, scored)
                or scorer.finding_from_anchor(clause, term)
                or scorer.finding_from_threshold(clause, term)
            )
            if finding:
                findings.append(finding)
            elif _is_judgeable(clause.clause_type, term, role) and not scorer.has_reference(
                clause.clause_type, term
            ):
                unassessed.append((clause, term))

    # --- venue distance -----------------------------------------------------
    # Needs no corpus: the harm is arithmetic, not statistical.
    if user_city:
        from kwys.extract.geo import distance_between, lookup

        if lookup(user_city) is None:
            warnings.append(
                f"'{user_city}' was not recognised, so the distance to any "
                "arbitration or court venue could not be checked."
            )
        else:
            # An agreement usually names the same city as the arbitration seat
            # AND as the exclusive court jurisdiction. Reporting both produces
            # two near-identical findings for one problem, so they are collapsed
            # to the first clause that names each distinct venue.
            venues_seen: set[str] = set()
            for clause, terms in clause_terms:
                for term in terms:
                    if term.field not in ("seat_city", "jurisdiction_city"):
                        continue
                    venue = str(term.value)
                    key = venue.strip().lower()
                    if key in venues_seen:
                        continue
                    km = distance_between(user_city, venue)
                    if km is None:
                        warnings.append(
                            f"Clause {clause.id} names '{venue}' as the venue, "
                            "which was not recognised, so its distance from you "
                            "could not be checked."
                        )
                        venues_seen.add(key)
                        continue
                    kind = "arbitration" if term.field == "seat_city" else "court"
                    finding = scorer.finding_from_venue(clause, venue, km, kind)
                    if finding:
                        findings.append(finding)
                    venues_seen.add(key)

    # --- structural findings ------------------------------------------------
    obligations = [o for c in clauses for o in extract_obligations(c, pmap)]
    by_id = {c.id: c for c in clauses}

    # Paired comparison first: "you give 6 months, they give 15 days" is a
    # stronger and more actionable finding than "no mirror clause found", and
    # both would otherwise fire on the same provision.
    # Clauses that bind only the reader where they normally bind both, and a
    # sole arbitrator chosen by the other side. Declared in
    # config/structural_rules.yaml; neither needs a corpus.
    rule_clause_ids: set[str] = set()
    for clause, rule in _one_sided_clauses(clause_terms, pmap, role, domain):
        rule_clause_ids.add(clause.id)
        findings.append(scorer.finding_from_one_sided(clause, rule))
    for clause, appointer in _unilateral_arbitrators(clause_terms, pmap, role):
        rule_clause_ids.add(clause.id)
        findings.append(scorer.finding_from_arbitrator(clause, appointer))

    # A clause already flagged by a law or a declared rule has a specific
    # finding; "this obligation runs only one way" about it adds only noise.
    rule_clause_ids.update(
        f.clause_id
        for f in findings
        if f.evidence.rule_basis or (f.evidence.anchor and f.evidence.norm is None)
    )

    paired_clause_ids = set()
    for clause_id, detail, extra in find_paired_asymmetries(clause_terms, pmap, role):
        clause = by_id.get(clause_id)
        if clause:
            paired_clause_ids.update(extra["clauses"])
            findings.append(scorer.finding_from_paired(clause, detail, extra))

    for clause_id, detail in find_asymmetries(clauses, obligations, pmap, role):
        if clause_id in paired_clause_ids or clause_id in rule_clause_ids:
            continue  # already reported, more specifically
        clause = by_id.get(clause_id)
        if clause:
            findings.append(scorer.finding_from_asymmetry(clause, detail))

    # Absence can only be claimed about a document we could read the structure
    # of. When segmentation failed, every expected section would be reported
    # missing - including the ones sitting in plain sight in the prose.
    if not low_structure:
        for clause_type, detail in find_missing_clauses(clauses, domain):
            findings.append(scorer.finding_from_missing(clause_type, detail))

    # --- semantic outliers, GATED ------------------------------------------
    # Distance from the centroid says a clause is unusual, not that it is
    # harmful: an unusually generous clause is equally far out. It therefore
    # only surfaces on a clause that ALREADY carries an independent signal -
    # here, an obligation on the user with no counterpart on the other side.
    #
    # OFF BY DEFAULT, and measurement is why. Scoring the fixture's ordinary
    # boilerplate against the LEDGAR centroids gives 87%, 88%, 93%, 95%, 95% -
    # every one of them near or past the 90% threshold. Indian rental clauses
    # sit far from US commercial ones across the board, so the percentile scale
    # is shifted and the threshold flags almost everything. Combined with the
    # inverted indemnity result in kwys/norms/semantic.py, this leg cannot be
    # trusted on this domain, and it costs ~15s to load the embedding model.
    # Charging every reader 15 seconds for the least reliable signal is a bad
    # trade, so it is opt-in (`--semantic`) until centroids exist that are built
    # from Indian consumer contracts.
    #
    # The candidate list is still built BEFORE the module is touched, and
    # everything is scored in one batched call rather than one per clause.
    gated: dict[str, str] = {}
    already = {f.clause_id for f in findings}
    for ob in obligations:
        if ob.role is not role or ob.modality is Modality.RIGHT:
            continue
        if ob.clause_id in already:
            continue
        gated.setdefault(
            ob.clause_id, f"It places an obligation on you ({ob.predicate[:60]})."
        )

    candidates = (
        [c for c in clauses if c.id in gated and c.clause_type and c.clause_type != "other"]
        if semantic
        else []
    )

    if candidates:
        from kwys.norms.semantic import SemanticNorms

        semantic = SemanticNorms.load(DATA_ROOT / "norms" / "semantic")
        # Only types with a centroid can be scored; if none of the candidates
        # has one, outlier_percentiles answers without loading the model.
        scored_pcts = (
            semantic.outlier_percentiles(
                [(c.clause_type, c.text) for c in candidates]
            )
            if not semantic.is_empty
            else [None] * len(candidates)
        )
        for clause, pct in zip(candidates, scored_pcts, strict=True):
            if pct is None:
                continue
            finding = scorer.finding_from_semantic(clause, pct, gated[clause.id])
            if finding:
                findings.append(finding)

    findings = _merge_same_clause_findings(findings)
    findings.sort(key=lambda f: f.score, reverse=True)
    if not show_low:
        findings = [f for f in findings if f.severity is not Severity.LOW]

    if pmap.unresolved:
        warnings.append(
            "Some defined parties could not be matched to a side: "
            + ", ".join(pmap.unresolved[:4])
        )

    # Terms nothing could judge, on clauses that drew no finding at all.
    # Listed so that a quiet report is not read as a clean one.
    flagged = {f.clause_id for f in findings}
    not_checked = [
        UnassessedTerm(
            clause_id=clause.id,
            label=C.display_name(clause.clause_type),
            value=Scorer._fmt(float(term.value), term.unit),
        )
        for clause, term in unassessed
        if clause.id not in flagged
    ]

    return AnalysisResult(
        document=document,
        findings=findings,
        clauses_checked=len([c for c in clauses if c.id != "preamble"]),
        corpus_version=corpus_version if not norms.is_empty else None,
        warnings=warnings,
        unassessed=not_checked,
    )


def _is_judgeable(clause_type: str, term, role: Role) -> bool:
    """A numeric term someone has declared a harmful direction for.

    Monthly rent has no direction - it is a price, not a term - so its absence
    from the report is not a gap worth mentioning.
    """
    if not isinstance(term.value, (int, float)) or isinstance(term.value, bool):
        return False
    return C.direction_for(f"{clause_type}.{term.field}", role) is not None


def _one_sided_clauses(clause_terms, pmap, role: Role, domain: Domain):
    """Clauses of a type that should bind both sides, binding only the reader."""
    for rule in C.structural_rules().get("one_sided", []):
        if domain.value not in rule.get("domains", [domain.value]):
            continue
        of_type = [c for c, _ in clause_terms if c.clause_type == rule["clause_type"]]
        bound = {c.id: attribute_clause_to_party(c, pmap) for c in of_type}
        if any(b is not None and b is not role for b in bound.values()):
            continue  # the other side is bound somewhere too
        for clause in of_type:
            if bound[clause.id] is role:
                yield clause, rule
                break


def _unilateral_arbitrators(clause_terms, pmap, role: Role):
    """A sole arbitrator appointed by the other side alone."""
    for clause, terms in clause_terms:
        for term in terms:
            if term.field != "appointed_by":
                continue
            appointer = pmap.resolve(str(term.value))
            if appointer is not None and appointer is not role:
                yield clause, str(term.value)
                break


def _derive_deposit_months(clause_terms: list[tuple]) -> None:
    """Add a deposit-in-months figure where only rupee amounts are stated.

    The comparison data is in months of rent, so "a deposit of Rs. 11,000" on a
    Rs. 22,000 rent could not be compared at all. Done only when the agreement
    states exactly one monthly rent: with several, which one is ambiguous.
    """
    rents = {
        t.value for _, terms in clause_terms for t in terms if t.field == "monthly_rent_inr"
    }
    if len(rents) != 1:
        return
    (rent,) = rents
    for _, terms in clause_terms:
        fields = {t.field for t in terms}
        if "deposit_months" in fields:
            continue
        deposit = next((t for t in terms if t.field == "deposit_inr"), None)
        if deposit is not None:
            derived = derive_deposit_months(float(deposit.value), float(rent))
            if derived is not None:
                terms.append(derived)


def _merge_same_clause_findings(findings: list) -> list:
    """Fold a deviation finding into the asymmetry finding for the same clause.

    Clause 4.1 was being reported twice: once as "you give 6 months, they give
    15 days" and again as "yours is 6 months, the usual is 3". Both are true and
    both are about the same number, so a reader sees the same clause twice and
    has to work out they are one problem. Merged, they are a stronger single
    finding than either alone - the imbalance AND the fact that your side of it
    is also unusual.

    The asymmetry finding survives because it is the more actionable of the two;
    the norm comparison is appended to its evidence so nothing is lost from the
    audit trail.
    """
    by_clause: dict[str, list] = {}
    for f in findings:
        by_clause.setdefault(f.clause_id, []).append(f)

    merged = []
    for group in by_clause.values():
        if len(group) == 1:
            merged.extend(group)
            continue

        asym = next((f for f in group if f.evidence.asymmetry), None)
        deviation = next((f for f in group if f.evidence.norm is not None), None)

        if asym is None or deviation is None:
            merged.extend(group)
            continue

        norm = deviation.evidence.norm
        asym.plain_language = (
            f"{asym.plain_language} On top of that, your own figure is unusual: "
            f"the usual across {norm.n} comparable agreements is "
            f"{norm.median:g}, not {norm.value:g}."
        )
        # Carry the measurement into the surviving finding's evidence so the
        # "show the working" panel still has the numbers.
        asym.evidence.norm = norm
        asym.evidence.term = deviation.evidence.term
        asym.evidence.field = deviation.evidence.field
        asym.score = round(min(1.0, max(asym.score, deviation.score) + 0.05), 3)
        merged.append(asym)
        merged.extend(f for f in group if f not in (asym, deviation))

    return merged


def unverified_anchor_warning() -> str | None:
    pending = C.unverified_anchors()
    if not pending:
        return None
    return (
        f"{len(pending)} statutory anchor(s) are not yet verified and are being "
        "skipped. Findings will rely on the corpus alone until someone checks "
        "them against the bare Act."
    )
