"""HTTP API behind the React interface.

Two endpoints: one describes what the system can currently do, one analyses a
document. Everything else the interface needs is derived from those.

PRIVACY. An uploaded agreement carries names, addresses, salaries and identity
numbers. It is written to a temporary file only because the PDF reader needs a
path, it is deleted the moment the request ends, and nothing about its contents
is logged. Do not add request logging here without revisiting that.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from kwys import config as C
from kwys.asymmetry.parties import DOMAIN_ROLES
from kwys.models import Domain, Role
from kwys.norms.store import MIN_N, NormStore
from kwys.pipeline import DATA_ROOT, analyse

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


def _corpora(domain: Domain) -> list[dict[str, Any]]:
    """Norm stores built for this domain, real ones first.

    Synthetic corpora sort last and can never be the default: a warning banner
    is not enough protection when the alternative is someone skimming
    fabricated percentiles.
    """
    root = DATA_ROOT / "norms"
    if not root.exists():
        return []

    out = []
    for path in root.iterdir():
        if not (path / domain.value).is_dir():
            continue
        store = NormStore.load(root, domain.value, path.name)
        coverage = store.coverage()
        out.append(
            {
                "version": path.name,
                "synthetic": "SYNTHETIC" in path.name.upper(),
                "fields": len(store),
                "usable": sum(1 for v in coverage.values() if v["sufficient"]),
                "bias": store.corpus_bias,
                "coverage": [
                    {"field": k, "n": v["n"], "usable": v["sufficient"]}
                    for k, v in coverage.items()
                ],
            }
        )
    return sorted(out, key=lambda c: (c["synthetic"], c["version"].lower()))


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
                "weakerParty": spec["weaker_party"],
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
        "minSampleSize": MIN_N,
        "capabilities": {
            "ocr": ocr_available(),
            "clauseClassifier": active_classifier(),
            "unfairDetector": active_detector(),
        },
        "unverifiedAnchors": C.unverified_anchors(),
    }


@app.post("/api/analyse")
async def post_analyse(
    file: UploadFile = File(...),
    role: str = Form(...),
    domain: str = Form(...),
    corpus_version: str = Form("v1"),
    city: str | None = Form(None),
    state: str | None = Form(None),
    semantic: bool = Form(False),
) -> JSONResponse:
    """Analyse one uploaded agreement."""
    try:
        role_enum, domain_enum = Role(role), Domain(domain)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if role_enum not in DOMAIN_ROLES[domain_enum]:
        raise HTTPException(
            status_code=400,
            detail=f"{role} is not a party to a {domain}",
        )

    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"That file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
        )
    if not payload.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="That does not look like a PDF.")

    # delete=True: the document must not outlive the request, and must never
    # land anywhere backed up or synced.
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
        tmp.write(payload)
        tmp.flush()
        try:
            result = analyse(
                tmp.name,
                role=role_enum,
                domain=domain_enum,
                user_city=city or None,
                user_state=state or None,
                corpus_version=corpus_version,
                semantic=semantic,
            )
        except Exception as exc:  # noqa: BLE001 - surface a message, not a stack
            log.exception("analysis failed")
            raise HTTPException(
                status_code=500, detail=f"Could not analyse that document: {exc}"
            ) from exc

    return JSONResponse(
        {
            "summary": result.summary_line(),
            "clausesChecked": result.clauses_checked,
            "corpusVersion": result.corpus_version,
            "wasOcred": result.document.was_ocred,
            "pageCount": result.document.page_count,
            "lowStructure": result.document.low_structure,
            "role": result.document.user_role.value,
            "warnings": result.warnings,
            "findings": [_finding_json(f) for f in result.findings],
            "distributions": _distributions(result, domain_enum, corpus_version),
        }
    )


def _finding_json(f) -> dict[str, Any]:
    ev = f.evidence
    return {
        "clauseId": f.clause_id,
        "severity": f.severity.value,
        "score": round(f.score, 3),
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
                    "robustZ": ev.norm.robust_z,
                    "sufficient": ev.norm.sufficient,
                }
                if ev.norm
                else None
            ),
            "anchor": (
                {
                    "value": ev.anchor.value,
                    "source": ev.anchor.source,
                    "note": ev.anchor.note,
                    "exceeded": ev.anchor.exceeded,
                    "applies": ev.anchor.applies,
                }
                if ev.anchor
                else None
            ),
            "directionRationale": ev.direction_rationale,
            "asymmetry": ev.asymmetry,
            "missingClause": ev.missing_clause,
            "venueDistanceKm": ev.venue_distance_km,
            "semanticOutlier": ev.semantic_outlier,
            "unfairTypes": ev.unfair_types,
        },
    }


def _distributions(
    result, domain: Domain, corpus_version: str
) -> dict[str, dict[str, Any]]:
    """The reference values behind each norm-backed finding, for the charts.

    Sent as counts per distinct value rather than raw observations: the chart
    draws one bar per value, and shipping 382 numbers to render 6 bars is waste.
    """
    fields = {
        f.evidence.norm.field
        for f in result.findings
        if f.evidence.norm and f.evidence.norm.sufficient
    }
    if not fields:
        return {}

    store = NormStore.load(DATA_ROOT / "norms", domain.value, corpus_version)
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
