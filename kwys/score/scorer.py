"""Turning measurements into ranked, justified findings.

The formula is in PLAN.md section 5. Three properties matter more than the
arithmetic:

  1. DEVIATION IS NOT HARM. A percentile says a term is rare. The direction map
     says which tail is bad, and for whom. A 15-day notice period and a 6-month
     one are equally unusual; only one is a trap. Where no direction is declared
     for a field, the deviation is NOT scored — undeclared means "nobody
     decided", not "harmless".

  2. THIN CORPORA GET SHRUNK, NOT HIDDEN. A percentile from 40 agreements is
     pulled toward neutral by n/(n+k); below MIN_N it is refused outright.

  3. EVERY FINDING CARRIES ITS EVIDENCE. Enforced by the Evidence type, which
     will not construct without grounds.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from kwys import config as C
from kwys.models import (
    Clause,
    Domain,
    Evidence,
    Finding,
    NormLookup,
    Role,
    Severity,
    Term,
)
from kwys.norms.store import NormStore

log = logging.getLogger(__name__)

_WEIGHTS_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "weights.yaml"


def _load_weights() -> dict[str, Any]:
    with _WEIGHTS_PATH.open() as fh:
        return yaml.safe_load(fh)


@dataclass
class ScoredTerm:
    """Intermediate result for one extracted value."""

    term: Term
    norm: NormLookup | None
    harm_percentile: float | None  # 0..1 on the harmful side, AFTER shrinkage
    direction: int | None
    rationale: str | None
    raw_harm: float | None = None  # before shrinkage; what the gate tests


class Scorer:
    def __init__(
        self,
        domain: Domain,
        role: Role,
        norms: NormStore,
        user_state: str | None = None,
    ) -> None:
        self.domain = domain
        self.role = role
        self.norms = norms
        self.user_state = user_state
        cfg = _load_weights()
        self.w = cfg["weights"]
        self.thresholds = cfg["thresholds"]
        self.k = float(cfg["shrinkage_k"])
        self.min_harm = float(cfg["min_harm_percentile"])

    # ---------------------------------------------------------------- deviation

    def score_term(self, clause_type: str, term: Term) -> ScoredTerm:
        """Locate a value in its reference distribution and orient it by harm."""
        field_key = f"{clause_type}.{term.field}"

        direction_entry = C.direction_for(field_key, self.role)
        if direction_entry is None:
            # Nobody has declared which way this field cuts. Refusing to score is
            # the honest response; treating it as neutral would quietly convert
            # an undeclared field into "no risk".
            return ScoredTerm(term, None, None, None, None, None)
        direction, rationale = direction_entry

        if not isinstance(term.value, (int, float)) or isinstance(term.value, bool):
            return ScoredTerm(term, None, None, direction, rationale, None)

        norm = self.norms.get(field_key)
        if norm is None or norm.n == 0:
            return ScoredTerm(term, None, None, direction, rationale, None)

        value = float(term.value)
        pct = norm.percentile_of(value)
        ci_low, ci_high = norm.bootstrap_ci(value)

        lookup = NormLookup(
            field=field_key,
            value=value,
            percentile=pct,
            ci_low=ci_low,
            ci_high=ci_high,
            n=norm.n,
            median=norm.median,
            mad=norm.mad,
            robust_z=norm.robust_z(value),
            corpus_version=norm.corpus_version,
            sufficient=norm.sufficient,
        )

        if not norm.sufficient:
            # Below MIN_N we record the lookup for the audit trail but make no
            # deviation claim from it.
            return ScoredTerm(term, lookup, None, direction, rationale, None)

        # Orient: q is the share of the corpus on the FAVOURABLE side of this
        # value, so q near 1 means "worse than almost everyone else's".
        q = pct if direction > 0 else (1.0 - pct)

        # Shrink toward neutral in proportion to how little evidence we have.
        w = norm.n / (norm.n + self.k)
        q_hat = 0.5 + w * (q - 0.5)

        return ScoredTerm(term, lookup, q_hat, direction, rationale, raw_harm=q)

    # ---------------------------------------------------------------- findings

    def finding_from_term(
        self, clause: Clause, scored: ScoredTerm
    ) -> Finding | None:
        """Build a finding from a deviation, if it clears the bar."""
        if scored.harm_percentile is None or scored.norm is None:
            return None
        # Gate on the RAW percentile: "is this in the harmful tail at all?".
        # Shrinkage then reduces the severity of what passes, rather than
        # suppressing whole fields whose corpus happens to be small.
        if (scored.raw_harm or 0.0) < self.min_harm:
            return None

        clause_type = clause.clause_type or "other"
        anchor = C.statutory_anchor(
            scored.norm.field,
            scored.norm.value,
            variant="residential" if self.domain is Domain.RESIDENTIAL_LEASE else "all",
            user_state=self.user_state,
        )

        score = self.w["deviation"] * scored.harm_percentile
        if anchor is not None and anchor.exceeded and anchor.applies:
            # An independent second signal pointing the same way. Additive, not
            # multiplicative: the two are different KINDS of evidence and the
            # report shows them separately rather than blending them.
            score = min(1.0, score + 0.15)

        evidence = Evidence(
            clause_id=clause.id,
            clause_type=clause_type,
            clause_text=clause.text,
            field=scored.norm.field,
            term=scored.term,
            norm=scored.norm,
            anchor=anchor,
            direction=scored.direction,
            direction_rationale=scored.rationale,
        )

        return Finding(
            clause_id=clause.id,
            severity=self._severity(score),
            score=round(score, 3),
            headline=self._headline(clause_type, scored),
            plain_language=self._explain(clause_type, scored, anchor),
            question_to_ask=self._question(clause_type, scored),
            evidence=evidence,
        )

    def finding_from_asymmetry(self, clause: Clause, detail: str) -> Finding:
        evidence = Evidence(
            clause_id=clause.id,
            clause_type=clause.clause_type or "other",
            clause_text=clause.text,
            asymmetry=True,
            asymmetry_detail=detail,
        )
        score = self.w["asymmetry"] + 0.45  # one-sided duties are rarely trivial
        return Finding(
            clause_id=clause.id,
            severity=self._severity(score),
            score=round(min(score, 1.0), 3),
            headline="This obligation runs only one way",
            plain_language=detail,
            question_to_ask="Ask whether this can be made to apply equally to both sides.",
            evidence=evidence,
        )

    def finding_from_paired(self, clause: Clause, detail: str, extra: dict) -> Finding:
        """A lopsided pair: the same obligation, sized differently for each side.

        Scored above a bare missing-mirror finding because it rests on two
        extracted figures rather than on an absence, and because the ratio makes
        it immediately checkable by the user against their own document.
        """
        evidence = Evidence(
            clause_id=clause.id,
            clause_type=clause.clause_type or "other",
            clause_text=clause.text,
            asymmetry=True,
            asymmetry_detail=detail,
        )
        ratio = float(extra.get("ratio", 1.0))
        # Grows with how lopsided the pair is, saturating so a 50x ratio does not
        # crowd out every other finding in the report.
        score = min(1.0, 0.55 + 0.12 * min(ratio, 5.0))
        return Finding(
            clause_id=clause.id,
            severity=self._severity(score),
            score=round(score, 3),
            headline="One side gets far longer than the other",
            plain_language=detail,
            question_to_ask="Ask for both notice periods to be set to the same length.",
            evidence=evidence,
        )

    def finding_from_missing(self, clause_type: str, detail: str) -> Finding:
        evidence = Evidence(
            clause_id=f"missing:{clause_type}",
            clause_type=clause_type,
            clause_text="",
            missing_clause=True,
        )
        score = self.w["missing"] + 0.35
        return Finding(
            clause_id=f"missing:{clause_type}",
            severity=self._severity(score),
            score=round(min(score, 1.0), 3),
            headline=f"Nothing about {C.display_name(clause_type).lower()}",
            plain_language=detail,
            question_to_ask=(
                f"Ask for a clause covering {C.display_name(clause_type).lower()} "
                "to be added in writing."
            ),
            evidence=evidence,
        )

    # ---------------------------------------------------------------- language

    def _severity(self, score: float) -> Severity:
        if score >= self.thresholds["high"]:
            return Severity.HIGH
        if score >= self.thresholds["medium"]:
            return Severity.MEDIUM
        return Severity.LOW

    @staticmethod
    def _fmt(value: float, unit: str | None) -> str:
        unit_names = {
            "months_of_rent": "months' rent",
            "months": "months",
            "days": "days",
            "hours": "hours",
            "INR": "rupees",
            "pct_per_year": "% a year",
            "pct_per_month": "% a month",
        }
        name = unit_names.get(unit or "", unit or "")
        if value == int(value):
            return f"{int(value)} {name}".strip()
        return f"{value:g} {name}".strip()

    def _headline(self, clause_type: str, s: ScoredTerm) -> str:
        assert s.norm is not None
        return f"{C.display_name(clause_type)}: {self._fmt(s.norm.value, s.term.unit)}"

    def _explain(self, clause_type: str, s: ScoredTerm, anchor) -> str:
        """The sentence a non-expert actually reads.

        Deliberately gives the comparison in counts ("about 4 in 100") rather
        than percentiles. "96th percentile" is precise and meaningless to the
        person this tool exists for.
        """
        assert s.norm is not None
        n = s.norm
        yours = self._fmt(n.value, s.term.unit)
        typical = self._fmt(n.median, s.term.unit)

        share = (1.0 - n.percentile) if (s.direction or 1) > 0 else n.percentile
        in_hundred = max(1, round(share * 100))
        comparative = "as much as" if (s.direction or 1) > 0 else "as little as"

        parts = [
            f"Yours is {yours}. The usual figure across {n.n} comparable "
            f"agreements is {typical}, and only about {in_hundred} in 100 ask "
            f"{comparative} yours."
        ]
        if s.rationale:
            parts.append(s.rationale)
        if anchor is not None and anchor.exceeded and anchor.applies:
            parts.append(f"{anchor.note or ''} ({anchor.source})".strip())
        return " ".join(parts)

    def _question(self, clause_type: str, s: ScoredTerm) -> str:
        assert s.norm is not None
        target = self._fmt(s.norm.quantile_target, s.term.unit) if hasattr(
            s.norm, "quantile_target"
        ) else self._fmt(s.norm.median, s.term.unit)
        subject = C.display_name(clause_type).lower()
        direction_word = "reduced" if (s.direction or 1) > 0 else "increased"
        return f"Ask whether the {subject} can be {direction_word} to around {target}."
