"""Typed objects passed between pipeline stages.

The important one is `Evidence`. A `Finding` cannot be constructed without it,
which is how the project's central discipline — no flag without traceable
evidence — is enforced by the type system rather than by good intentions.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

# ---------------------------------------------------------------- primitives


class Role(StrEnum):
    """Which side of the agreement the user is on.

    Everything about risk direction depends on this. A three-month notice
    period is a burden for whoever must give it.
    """

    TENANT = "tenant"
    LANDLORD = "landlord"
    EMPLOYEE = "employee"
    EMPLOYER = "employer"
    CONSUMER = "consumer"
    PROVIDER = "provider"


class Domain(StrEnum):
    RESIDENTIAL_LEASE = "residential_lease"
    EMPLOYMENT_OFFER = "employment_offer"
    CONSUMER_TOS = "consumer_tos"


class Severity(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Modality(StrEnum):
    """Deontic force of an obligation, for the asymmetry analysis."""

    OBLIGATION = "obligation"  # shall, must, is required to
    RIGHT = "right"  # may, is entitled to
    PROHIBITION = "prohibition"  # shall not, must not


# ---------------------------------------------------------------- document


class Span(BaseModel):
    """A rectangle on a page, so the report can point at the original PDF.

    Without this the user has to take our word for it. With it, they can see
    the clause highlighted in their own document, which is most of what makes
    the output trustworthy to someone who cannot assess the reasoning.
    """

    page: int
    x0: float
    y0: float
    x1: float
    y1: float


class Clause(BaseModel):
    """One clause or sub-clause, as segmented from the document."""

    id: str  # stable within a document, e.g. "4.2"
    number: str | None = None  # "4.2" as printed, if numbered
    heading: str | None = None  # own heading, if any
    parent_heading: str | None = None  # inherited from the parent clause
    text: str
    spans: list[Span] = Field(default_factory=list)
    depth: int = 0
    order: int = 0  # position in the document, for stable sorting

    # filled by later stages
    clause_type: str | None = None
    type_confidence: float | None = None

    @property
    def context_text(self) -> str:
        """Text as the classifier should see it.

        Sub-clause 4.3 alone is often meaningless; "4. TERMINATION" as context
        is worth several F1 points and costs nothing.
        """
        if self.parent_heading:
            return f"{self.parent_heading} [SEP] {self.text}"
        return self.text


class Document(BaseModel):
    path: str
    domain: Domain
    user_role: Role
    user_city: str | None = None  # for arbitration-venue distance
    page_count: int = 0
    was_ocred: bool = False
    low_structure: bool = False  # segmentation was not confident
    clauses: list[Clause] = Field(default_factory=list)


# ---------------------------------------------------------------- extraction


class Term(BaseModel):
    """One operative value pulled out of a clause, normalised to a canonical unit.

    `raw` is kept so the report can quote the document rather than paraphrase it,
    and so a wrong extraction is visible rather than silent.
    """

    field: str  # "deposit_months", as named in taxonomy.yaml
    raw: str  # exactly as it appeared: "six (6) months"
    value: float | str | bool | None
    unit: str | None = None  # "months", "INR", "pct_per_year"
    span: Span | None = None
    extractor: Literal["regex", "ner", "derived", "geo"] = "regex"
    confidence: float = 1.0


class Obligation(BaseModel):
    """Who is bound to do what, for the asymmetry analysis."""

    clause_id: str
    role: Role | None  # None when the bound party could not be resolved
    modality: Modality
    predicate: str  # short verb phrase
    raw_sentence: str


# ---------------------------------------------------------------- norms


class NormLookup(BaseModel):
    """Where a value sits in the reference distribution.

    `n` and `ci` are not optional decoration. A percentile computed from 12
    agreements is not the same claim as one computed from 312, and the report
    must be able to say so.
    """

    field: str
    value: float
    percentile: float  # 0..1, raw position in the distribution
    ci_low: float
    ci_high: float
    n: int
    median: float
    mad: float
    robust_z: float
    corpus_version: str
    sufficient: bool  # False when n < MIN_N; percentile must not be asserted


class StatutoryAnchorHit(BaseModel):
    """A statutory reference point, only ever populated from a verified anchor."""

    value: float
    comparison: Literal["max", "min"]
    unit: str
    source: str  # "Model Tenancy Act, 2021, s.11(1)"
    note: str | None = None
    exceeded: bool
    applies: bool  # False where the user's state has not adopted the instrument


# ---------------------------------------------------------------- findings


class Evidence(BaseModel):
    """Everything needed to justify a single flag, and to audit it later.

    A Finding cannot exist without one of these. If you are tempted to add a
    finding with no evidence, the answer is to not add the finding.
    """

    clause_id: str
    clause_type: str
    clause_text: str
    field: str | None = None
    term: Term | None = None
    norm: NormLookup | None = None
    anchor: StatutoryAnchorHit | None = None
    direction: int | None = None  # +1 larger is worse, -1 smaller is worse
    direction_rationale: str | None = None
    asymmetry: bool = False
    asymmetry_detail: str | None = None
    missing_clause: bool = False
    unfair_types: list[str] = Field(default_factory=list)  # LexGLUE unfair_tos labels
    semantic_outlier: float | None = None  # percentile of distance from centroid
    venue_distance_km: float | None = None  # measured, not compared to a corpus
    # A declared rule from config/structural_rules.yaml, by what it rests on.
    rule_basis: str | None = None

    @model_validator(mode="after")
    def _must_carry_something(self) -> Evidence:
        grounds = (
            self.norm is not None,
            self.anchor is not None,
            self.asymmetry,
            self.missing_clause,
            self.semantic_outlier is not None,
            # A dispute venue's distance is measured, not compared against a
            # corpus: the harm is arithmetic. It is still evidence, and the
            # figure is in the record.
            self.venue_distance_km is not None,
            # An unfairness category from an expert-annotated scheme is
            # evidence in its own right, and a stronger kind than most here:
            # the label set was defined by lawyers, not by us.
            bool(self.unfair_types),
            # A rule written down in config, with its threshold and its reason,
            # for harms plain on the face of a clause.
            self.rule_basis is not None,
        )
        if not any(grounds):
            raise ValueError(
                f"Evidence for clause {self.clause_id!r} carries no grounds. "
                "Every finding must rest on a norm comparison, a statutory anchor, "
                "an asymmetry, a missing clause, a measured venue distance, or a "
                "gated semantic outlier."
            )
        return self


class Finding(BaseModel):
    """One thing worth the user's attention."""

    clause_id: str
    severity: Severity
    score: float = Field(ge=0.0, le=1.0)
    headline: str  # "Deposit is 6 months' rent"
    plain_language: str  # the sentence a non-expert reads
    question_to_ask: str | None = None  # what to actually say to the other side
    evidence: Evidence  # required, by design


class UnassessedTerm(BaseModel):
    """A term that was found but could not be judged either way.

    Listed so that silence is not mistaken for "fine": with no reference data,
    no statutory anchor and no rule, the report has nothing to say about it.
    """

    clause_id: str
    label: str  # "Rent and annual increase"
    value: str  # "15 % a year", as the reader should see it


class AnalysisResult(BaseModel):
    document: Document
    findings: list[Finding] = Field(default_factory=list)
    clauses_checked: int = 0
    corpus_version: str | None = None
    generated_at: datetime = Field(default_factory=datetime.now)
    warnings: list[str] = Field(default_factory=list)
    unassessed: list[UnassessedTerm] = Field(default_factory=list)

    def by_severity(self, s: Severity) -> list[Finding]:
        return [f for f in self.findings if f.severity is s]

    def summary_line(self) -> str:
        high = len(self.by_severity(Severity.HIGH))
        med = len(self.by_severity(Severity.MEDIUM))
        return (
            f"{self.clauses_checked} clauses checked. "
            f"{high} need your attention, {med} worth a look."
        )

    def to_evidence_json(self) -> list[dict[str, Any]]:
        """Flat dump for evaluation scripts and for the audit trail."""
        return [
            {"severity": f.severity.value, "score": round(f.score, 3), **f.evidence.model_dump()}
            for f in self.findings
        ]
