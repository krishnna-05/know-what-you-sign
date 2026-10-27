"""HTTP API behind the React interface.

One endpoint describes what the system can currently do; one analyses a
document, another compares two drafts of one. Questions and shared figures
have their own endpoints, and neither keeps the document: a question arrives
with the clauses it is asked of, and a shared figure is a number, not text.

PRIVACY. An uploaded agreement carries names, addresses, salaries and identity
numbers. It is written to a temporary file only because the PDF reader needs a
path, it is deleted the moment the request ends, and nothing about its contents
is logged. Do not add request logging here without revisiting that.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from kwys import config as C
from kwys.ask import AskClause, answer
from kwys.asymmetry.parties import DOMAIN_ROLES
from kwys.compare import compare
from kwys.contribute import ContributionStore, Rejected, clean, offer
from kwys.exposure import build_exposure
from kwys.facts import gather
from kwys.models import AnalysisResult, Domain, Role
from kwys.negotiate import label_for, suggest
from kwys.norms.store import NormStore, available_versions, display_label, is_synthetic
from kwys.pipeline import DATA_ROOT, analyse
from kwys.timeline import build_timeline

log = logging.getLogger(__name__)

# 25 MB. A scanned forty-page agreement is a few megabytes; anything far larger
# is a mistake or an attack, and OCR on it would tie up the process for minutes.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

app = FastAPI(title="Know What You Sign", version="0.1.0")

# The React dev server runs on a different port. In production the built assets
# are served by this same app, so no origin crosses.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Human-readable role labels. The enum values ("tenant") are for the code; these
# are what a person picks from.
ROLE_LABELS: dict[Role, tuple[str, str]] = {
    Role.TENANT: ("I'm renting the place", "tenant / lessee"),
    Role.LANDLORD: ("I own the place", "landlord / lessor"),
    Role.EMPLOYEE: ("I'm taking the job", "employee"),
    Role.EMPLOYER: ("I'm offering the job", "employer"),
    Role.CONSUMER: ("I'm the user", "customer / user"),
    Role.PROVIDER: ("I run the service", "the company"),
}


def demo_data_enabled() -> bool:
    """Whether synthetic corpora may be offered at all.

    Off unless asked for (`serve.py --dev` or `--demo-data`). Invented
    percentiles have no business in front of someone checking a real contract,
    however loud the warning next to them.
    """
    return os.environ.get("KWYS_DEMO_DATA") == "1"


def _versions(domain: Domain) -> list[str]:
    """Corpora a reader may choose for this domain, real ones first."""
    versions = available_versions(DATA_ROOT / "norms", domain.value)
    if demo_data_enabled():
        return versions
    return [v for v in versions if not is_synthetic(v)]


def _corpora(domain: Domain) -> list[dict[str, Any]]:
    """Norm stores a reader may choose, real ones first (the first is the default)."""
    root = DATA_ROOT / "norms"
    out = []
    for version in _versions(domain):
        store = NormStore.load(root, domain.value, version)
        out.append(
            {
                "version": version,
                "label": display_label(store),
                "synthetic": is_synthetic(version),
                "bias": store.corpus_bias,
                "coverage": [
                    {
                        "field": k,
                        "label": C.display_name(k.split(".")[0]),
                        "n": v["n"],
                        "usable": v["sufficient"],
                    }
                    for k, v in store.coverage().items()
                ],
            }
        )
    return out


@app.get("/api/config")
def get_config() -> dict[str, Any]:
    """Everything the interface needs to render its first screen."""
    from kwys.classify.model import active_classifier
    from kwys.classify.unfair import active_detector
    from kwys.ingest.ocr import is_available as ocr_available

    domains = []
    for domain in Domain:
        spec = C.taxonomy()["domains"][domain.value]
        roles = DOMAIN_ROLES[domain]
        domains.append(
            {
                "value": domain.value,
                "label": spec["display_name"],
                "weakerParty": C.weaker_party(domain).value,
                "roles": [
                    {
                        "value": r.value,
                        "label": ROLE_LABELS[r][0],
                        "hint": ROLE_LABELS[r][1],
                    }
                    for r in roles
                ],
                "corpora": _corpora(domain),
            }
        )

    return {
        "domains": domains,
        "capabilities": {
            "ocr": ocr_available(),
            "clauseClassifier": active_classifier(),
            "unfairDetector": active_detector(),
            "contributions": contributions_enabled(),
        },
    }


def _check_inputs(
    role: str, domain: str, corpus_version: str | None
) -> tuple[Role, Domain]:
    try:
        role_enum, domain_enum = Role(role), Domain(domain)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if role_enum not in DOMAIN_ROLES[domain_enum]:
        raise HTTPException(
            status_code=400,
            detail=f"{role} is not a party to a {domain}",
        )

    # Only a corpus that is actually built can be named. Anything else would
    # silently produce a report with no comparisons in it - and the value is a
    # path component, so it must never reach the filesystem unchecked.
    if corpus_version and corpus_version not in _versions(domain_enum):
        raise HTTPException(
            status_code=400,
            detail=f"No reference corpus called {corpus_version!r} is built for {domain}.",
        )
    return role_enum, domain_enum


async def _read_pdf(file: UploadFile) -> bytes:
    # Read one byte past the cap rather than the whole body, so an oversized
    # upload is refused without first being held in memory in full.
    payload = await file.read(MAX_UPLOAD_BYTES + 1)
    if not payload:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"That file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
        )
    if not payload.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="That does not look like a PDF.")
    return payload


def _analyse_bytes(
    payload: bytes,
    role: Role,
    domain: Domain,
    city: str | None,
    state: str | None,
    corpus_version: str | None,
) -> AnalysisResult:
    # delete=True: the document must not outlive the request, and must never
    # land anywhere backed up or synced.
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
        tmp.write(payload)
        tmp.flush()
        try:
            return analyse(
                tmp.name,
                role=role,
                domain=domain,
                user_city=city or None,
                user_state=state or None,
                corpus_version=corpus_version or None,
            )
        except Exception as exc:  # noqa: BLE001 - surface a message, not a stack
            # The exception goes to the server log only: its text is internal
            # and can quote the document, and neither belongs in front of the
            # reader.
            log.exception("analysis failed")
            raise HTTPException(
                status_code=500,
                detail="This document could not be analysed. Check that it is a "
                "readable PDF and try again.",
            ) from exc


def _report_json(
    result: AnalysisResult, role: Role, domain: Domain, city: str | None
) -> dict[str, Any]:
    """The whole report: findings, plus everything the other tabs are built from."""
    corpus_label = None
    if result.corpus_version:
        corpus_label = display_label(
            NormStore.load(DATA_ROOT / "norms", domain.value, result.corpus_version)
        )

    facts = gather(result, role)
    return {
        "clausesChecked": result.clauses_checked,
        "corpusLabel": corpus_label,
        "corpusBias": result.corpus_bias,
        "wasOcred": result.document.was_ocred,
        "pageCount": result.document.page_count,
        # Reader-facing caveats only. `result.diagnostics` - unbuilt norms,
        # untrained models and the commands that fix them - is for whoever
        # runs the server, and stays in the CLI.
        "warnings": result.warnings,
        "findings": [
            {
                **_finding_json(f),
                "label": label_for(f),
                "suggestedWording": suggest(f, facts, domain, role, city or None),
            }
            for f in result.findings
        ],
        "notChecked": [
            {"clauseId": u.clause_id, "label": u.label, "value": u.value}
            for u in result.unassessed
        ],
        "distributions": _distributions(result, domain),
        "clauses": [
            {
                "id": c.id,
                "type": c.clause_type,
                "typeLabel": C.display_name(c.clause_type) if c.clause_type else None,
                "heading": c.heading or c.parent_heading,
                "text": c.text,
                "spans": [s.model_dump() for s in c.spans],
            }
            for c in result.document.clauses
        ],
        "facts": facts.to_json(),
        "exposure": build_exposure(facts, domain, role),
        "timeline": build_timeline(facts, domain),
        # Figures the reader may choose to share. Offered, never sent: the
        # browser posts them only after the reader has seen them and agreed.
        "shareable": offer(domain, result.extracted, city) if contributions_enabled() else [],
    }


@app.post("/api/analyse")
async def post_analyse(
    file: UploadFile = File(...),
    role: str = Form(...),
    domain: str = Form(...),
    corpus_version: str | None = Form(None),
    city: str | None = Form(None),
    state: str | None = Form(None),
) -> JSONResponse:
    """Analyse one uploaded agreement."""
    role_enum, domain_enum = _check_inputs(role, domain, corpus_version)
    payload = await _read_pdf(file)
    result = _analyse_bytes(payload, role_enum, domain_enum, city, state, corpus_version)
    return JSONResponse(_report_json(result, role_enum, domain_enum, city))


@app.post("/api/compare")
async def post_compare(
    old_file: UploadFile = File(...),
    new_file: UploadFile = File(...),
    role: str = Form(...),
    domain: str = Form(...),
    corpus_version: str | None = Form(None),
    city: str | None = Form(None),
    state: str | None = Form(None),
) -> JSONResponse:
    """Two drafts of one agreement: the new one's report, and what changed."""
    role_enum, domain_enum = _check_inputs(role, domain, corpus_version)
    old_bytes = await _read_pdf(old_file)
    new_bytes = await _read_pdf(new_file)
    old = _analyse_bytes(old_bytes, role_enum, domain_enum, city, state, corpus_version)
    new = _analyse_bytes(new_bytes, role_enum, domain_enum, city, state, corpus_version)
    diff = compare(old, new, gather(old, role_enum), gather(new, role_enum), role_enum)
    return JSONResponse(
        {"report": _report_json(new, role_enum, domain_enum, city), "diff": diff}
    )


class AskClauseIn(BaseModel):
    id: str = Field(max_length=40)
    text: str = Field(max_length=20_000)
    type: str | None = Field(default=None, max_length=60)


class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=300)
    domain: Domain
    # The clauses travel with the question because nothing is kept between
    # requests: the server has no copy of the document to search.
    clauses: list[AskClauseIn] = Field(max_length=1_000)


@app.post("/api/ask")
def post_ask(body: AskIn) -> dict[str, Any]:
    """Answer a question with the agreement's own clauses, or report silence."""
    return answer(
        body.question,
        [AskClause(c.id, c.text, c.type) for c in body.clauses],
        body.domain,
    )


def contributions_enabled() -> bool:
    """On unless switched off (KWYS_CONTRIBUTIONS=0) - sharing is still opt-in per report."""
    return os.environ.get("KWYS_CONTRIBUTIONS", "1") != "0"


def _contribution_store() -> ContributionStore:
    return ContributionStore(DATA_ROOT / "contributions" / "contributions.sqlite")


class FigureIn(BaseModel):
    key: str = Field(max_length=80)
    value: float


class ContributeIn(BaseModel):
    domain: str = Field(max_length=40)
    city: str | None = Field(default=None, max_length=60)
    figures: list[FigureIn] = Field(max_length=20)


@app.post("/api/contribute")
def post_contribute(body: ContributeIn) -> dict[str, Any]:
    """Store figures a reader chose to share. Numbers only; see kwys.contribute."""
    if not contributions_enabled():
        raise HTTPException(status_code=404, detail="Sharing is not enabled on this server.")
    try:
        cleaned = clean(body.domain, [f.model_dump() for f in body.figures], body.city)
    except Rejected as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    stored = _contribution_store().add(cleaned)
    return {"stored": stored, "duplicate": not stored}


def _finding_json(f) -> dict[str, Any]:
    ev = f.evidence
    return {
        "clauseId": f.clause_id,
        "severity": f.severity.value,
        "headline": f.headline,
        "plainLanguage": f.plain_language,
        "question": f.question_to_ask,
        "evidence": {
            "clauseType": ev.clause_type,
            "clauseText": ev.clause_text,
            "field": ev.field,
            "term": (
                {"value": ev.term.value, "unit": ev.term.unit, "raw": ev.term.raw}
                if ev.term
                else None
            ),
            "norm": (
                {
                    "value": ev.norm.value,
                    "median": ev.norm.median,
                    "percentile": ev.norm.percentile,
                    "ciLow": ev.norm.ci_low,
                    "ciHigh": ev.norm.ci_high,
                    "n": ev.norm.n,
                }
                if ev.norm
                else None
            ),
            "anchor": (
                {
                    "value": ev.anchor.value,
                    "comparison": ev.anchor.comparison,
                    "unit": ev.anchor.unit,
                    "source": ev.anchor.source,
                    "note": ev.anchor.note,
                    "exceeded": ev.anchor.exceeded,
                    "applies": ev.anchor.applies,
                }
                if ev.anchor
                else None
            ),
            "directionRationale": ev.direction_rationale,
            "missingClause": ev.missing_clause,
            "venueDistanceKm": ev.venue_distance_km,
            "unfairTypes": ev.unfair_types,
            "ruleBasis": ev.rule_basis,
        },
    }


def _distributions(result, domain: Domain) -> dict[str, dict[str, Any]]:
    """The reference values behind each norm-backed finding, for the charts.

    Sent as counts per distinct value rather than raw observations: the chart
    draws one bar per value, and shipping 382 numbers to render 6 bars is waste.
    """
    fields = {
        f.evidence.norm.field
        for f in result.findings
        if f.evidence.norm and f.evidence.norm.sufficient
    }
    if not fields or not result.corpus_version:
        return {}

    # The version the pipeline actually used, which may be the default it chose.
    store = NormStore.load(DATA_ROOT / "norms", domain.value, result.corpus_version)
    out: dict[str, dict[str, Any]] = {}
    for field in fields:
        norm = store.get(field)
        if norm is None or not norm.values:
            continue
        counts: dict[float, int] = {}
        for v in norm.values:
            counts[v] = counts.get(v, 0) + 1
        out[field] = {
            "n": norm.n,
            "median": norm.median,
            "counts": [
                {"value": v, "count": c} for v, c in sorted(counts.items())
            ],
        }
    return out


def mount_static(directory: Path | str) -> None:
    """Serve the built React app from this same process.

    Used in production so there is one process, one port and no CORS. In
    development the Vite dev server handles the frontend instead.
    """
    from fastapi.staticfiles import StaticFiles

    path = Path(directory)
    if path.is_dir():
        app.mount("/", StaticFiles(directory=str(path), html=True), name="web")
        log.info("Serving the built interface from %s", path)
