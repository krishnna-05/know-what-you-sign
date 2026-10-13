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

# Within this radius the venue is the user's own metropolitan area and imposes
# no real burden - courts in Gurugram are not a hardship for someone in Delhi.
VENUE_NEARBY_KM = 60.0

# Only the far tail is worth raising. Below this, "unusual wording" is noise.
SEMANTIC_OUTLIER_PERCENTILE = 0.90


def _indian_grouping(value: float) -> str:
    """3,00,000 rather than 300,000: how the reader's own agreement writes it."""
    digits = str(int(round(value)))
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return ",".join([head, *groups, tail]) if head else ",".join([*groups, tail])


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
            # Only a binding instrument moves the score - a model law that the
            # user's state has not adopted is shown as guidance and scored as
            # nothing, because it is not law where they live.
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

    def finding_from_venue(
        self, clause: Clause, venue: str, distance_km: float, kind: str
    ) -> Finding | None:
        """A dispute venue far from where the user actually lives.

        Not a deviation finding: it needs no corpus, because the harm is
        arithmetic. If pursuing a Rs.60,000 deposit means travelling 2,000 km
        and retaining a lawyer there, the right exists on paper and nowhere
        else. Scored on distance because that IS the severity.
        """
        if distance_km < VENUE_NEARBY_KM:
            return None

        evidence = Evidence(
            clause_id=clause.id,
            clause_type=clause.clause_type or "other",
            clause_text=clause.text,
            field=f"{clause.clause_type}.{'seat' if kind == 'arbitration' else 'jurisdiction'}"
            "_distance_km",
            term=Term(
                field="venue_distance_km", raw=venue, value=distance_km,
                unit="km", extractor="geo",
            ),
            direction=+1,
            direction_rationale=(
                "If a dispute has to be heard in a distant city, the travel and "
                "lawyer's fees can cost more than the amount in dispute — which "
                "in practice means the right cannot be used at all."
            ),
            venue_distance_km=distance_km,
        )
        # Saturating: beyond roughly a day's travel the practical effect stops
        # getting meaningfully worse, and a 2,500 km venue should not crowd out
        # every other finding in the report.
        score = min(0.92, 0.42 + 0.5 * min(distance_km / 1500.0, 1.0))
        word = "arbitration" if kind == "arbitration" else "any court case"
        return Finding(
            clause_id=clause.id,
            severity=self._severity(score),
            score=round(score, 3),
            headline=f"Disputes must be heard in {venue}",
            plain_language=(
                f"This agreement requires {word} to take place in {venue}, "
                f"about {distance_km:,.0f} km from you. Travelling there and "
                f"hiring a lawyer there may cost more than whatever you would "
                f"be arguing about."
            ),
            question_to_ask=(
                "Ask for disputes to be heard in your own city instead."
            ),
            evidence=evidence,
        )

    def finding_from_semantic(
        self, clause: Clause, percentile: float, gate_reason: str
    ) -> Finding | None:
        """A clause that READS unlike others of its type.

        Never fires alone. Semantic distance measures unusual, not harmful - an
        unusually generous clause sits just as far from the centroid as an
        unusually harsh one - so the caller must supply `gate_reason`: an
        independent signal on the same clause that gives the distance a
        direction. Weighted lowest of all the legs, and reported separately in
        the evaluation so a reader can see how little of the performance rests
        on it.
        """
        if percentile < SEMANTIC_OUTLIER_PERCENTILE:
            return None

        evidence = Evidence(
            clause_id=clause.id,
            clause_type=clause.clause_type or "other",
            clause_text=clause.text,
            semantic_outlier=round(percentile, 3),
            asymmetry=True,
            asymmetry_detail=gate_reason,
        )
        score = self.w["semantic"] * percentile + 0.35
        return Finding(
            clause_id=clause.id,
            severity=self._severity(min(score, 1.0)),
            score=round(min(score, 1.0), 3),
            headline="This clause is worded unusually",
            plain_language=(
                f"This {C.display_name(clause.clause_type or 'clause').lower()} "
                f"clause is worded differently from about "
                f"{percentile:.0%} of comparable clauses. {gate_reason} "
                "Unusual wording is not necessarily unfair, but it is worth "
                "reading closely."
            ),
            question_to_ask="Ask what this clause means in plain language, and why it is needed.",
            evidence=evidence,
        )

    def finding_from_unfair(self, clause: Clause, unfair_types: list[str]) -> Finding:
        """A terms-of-service clause matching an expert-defined unfairness type.

        Scored higher than most legs because the label set was defined by
        lawyers (the CLAUDETTE scheme, as published in LexGLUE) rather than by
        us, and because a clause carrying several types at once is compounding
        rather than merely unusual.
        """
        from kwys.classify.unfair import describe

        headline, question = describe(unfair_types[0])
        score = min(0.94, 0.52 + 0.14 * (len(unfair_types) - 1))

        detail = headline
        if len(unfair_types) > 1:
            others = ", ".join(describe(t)[0].lower() for t in unfair_types[1:])
            detail = f"{headline}. It also means: {others}."

        return Finding(
            clause_id=clause.id,
            severity=self._severity(score),
            score=round(score, 3),
            headline=headline,
            plain_language=detail,
            question_to_ask=question,
            evidence=Evidence(
                clause_id=clause.id,
                clause_type=clause.clause_type or "other",
                clause_text=clause.text,
                unfair_types=unfair_types,
            ),
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

    # ---------------------------------------------------------------- no corpus
    #
    # Findings that need no reference data. Without these, a term with no
    # corpus behind it was silently dropped, and a harsh agreement could come
    # back looking nearly clean - the more dangerous failure for this tool.

    def _anchor_variant(self) -> str:
        return "residential" if self.domain is Domain.RESIDENTIAL_LEASE else "all"

    def _harms(self, field_key: str, comparison: str) -> tuple[bool, str | None]:
        """Whether breaching a ceiling (or floor) hurts this reader, and why."""
        entry = C.direction_for(field_key, self.role)
        if entry is None:
            return False, None
        direction, rationale = entry
        return (direction > 0) == (comparison == "max"), rationale

    def has_reference(self, clause_type: str, term: Term) -> bool:
        """Whether anything at all can judge this term: data, law or a rule."""
        field_key = f"{clause_type}.{term.field}"
        norm = self.norms.get(field_key)
        if norm is not None and norm.sufficient:
            return True
        if C.statutory_anchor(field_key, 0.0, self._anchor_variant()) is not None:
            return True
        return C.threshold_rule(field_key, term.unit, self.role) is not None

    def finding_from_anchor(self, clause: Clause, term: Term) -> Finding | None:
        """A term past a statutory line that BINDS here, with or without a corpus.

        Only a binding instrument stands alone. A model law the reader's state
        has not adopted still appears as context on a deviation finding, but on
        its own it would flag every refund window in every non-adopting state -
        "30 days" included - which is noise. A declared rule of thumb in
        structural_rules.yaml covers the clearly excessive cases instead.
        """
        if not isinstance(term.value, (int, float)) or isinstance(term.value, bool):
            return None
        clause_type = clause.clause_type or "other"
        field_key = f"{clause_type}.{term.field}"
        anchor = C.statutory_anchor(
            field_key, float(term.value), self._anchor_variant(), self.user_state
        )
        if anchor is None or not anchor.exceeded or not anchor.applies:
            return None
        harms, rationale = self._harms(field_key, anchor.comparison)
        if not harms:
            return None

        score = 0.8
        yours = self._fmt(float(term.value), term.unit)
        return Finding(
            clause_id=clause.id,
            severity=self._severity(score),
            score=score,
            headline=f"{C.display_name(clause_type)}: {yours}",
            plain_language=f"Yours is {yours}. {self._anchor_sentence(anchor)}",
            question_to_ask=(
                f"Ask for the {C.display_name(clause_type).lower()} to be brought "
                f"in line with {anchor.source.split(',')[0]}."
            ),
            evidence=Evidence(
                clause_id=clause.id,
                clause_type=clause_type,
                clause_text=clause.text,
                field=field_key,
                term=term,
                anchor=anchor,
                direction_rationale=rationale,
            ),
        )

    def finding_from_threshold(self, clause: Clause, term: Term) -> Finding | None:
        """A term past a declared rule-of-thumb line in structural_rules.yaml."""
        if not isinstance(term.value, (int, float)) or isinstance(term.value, bool):
            return None
        clause_type = clause.clause_type or "other"
        field_key = f"{clause_type}.{term.field}"
        rule = C.threshold_rule(field_key, term.unit, self.role)
        if rule is None:
            return None
        value = float(term.value)
        line = float(rule["value"])
        if not (value < line if rule["flag_if"] == "below" else value > line):
            return None

        if term.unit == "hours":
            shown = "no" if value == 0 else f"only {self._fmt(value, term.unit)}'"
        else:
            shown = self._fmt(value, term.unit)
        annual = f"{value * 12:g}%" if term.unit == "pct_per_month" else ""
        score = 0.8 if rule["severity"] == "high" else 0.55
        return Finding(
            clause_id=clause.id,
            severity=self._severity(score),
            score=score,
            headline=rule["headline"],
            plain_language=" ".join(
                rule["explain"].format(value=shown, annual=annual).split()
            ),
            question_to_ask=rule["question"],
            evidence=Evidence(
                clause_id=clause.id,
                clause_type=clause_type,
                clause_text=clause.text,
                field=field_key,
                term=term,
                rule_basis=rule["basis"],
            ),
        )

    def finding_from_one_sided(self, clause: Clause, rule: dict) -> Finding:
        """A clause that binds only the reader, where it normally binds both."""
        score = 0.6
        return Finding(
            clause_id=clause.id,
            severity=self._severity(score),
            score=score,
            headline=rule["headline"],
            plain_language=" ".join(rule["explain"].split()),
            question_to_ask=rule["question"],
            evidence=Evidence(
                clause_id=clause.id,
                clause_type=clause.clause_type or "other",
                clause_text=clause.text,
                asymmetry=True,
                asymmetry_detail=f"The {clause.clause_type} binds only you.",
            ),
        )

    def finding_from_arbitrator(self, clause: Clause, appointer: str) -> Finding:
        """A sole arbitrator chosen by the other side alone."""
        rule = C.structural_rules()["unilateral_arbitrator"]
        score = 0.8 if rule["severity"] == "high" else 0.55
        return Finding(
            clause_id=clause.id,
            severity=self._severity(score),
            score=score,
            headline=rule["headline"],
            plain_language=" ".join(rule["explain"].format(appointer=appointer).split()),
            question_to_ask=rule["question"],
            evidence=Evidence(
                clause_id=clause.id,
                clause_type=clause.clause_type or "other",
                clause_text=clause.text,
                rule_basis=rule["basis"],
            ),
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
        if unit == "INR":
            return f"Rs. {_indian_grouping(value)}"
        name = unit_names.get(unit or "", unit or "")
        if name.startswith("%"):
            return f"{value:g}{name}"  # "5% a month", not "5 % a month"
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
        if anchor is not None and anchor.exceeded:
            parts.append(self._anchor_sentence(anchor))
        return " ".join(parts)

    def _anchor_sentence(self, anchor) -> str:
        """Phrase a statutory reference according to whether it actually binds.

        The Model Tenancy Act is a MODEL law: it binds nobody until a state
        adopts it, and only four have. Telling a reader in a non-adopting state
        that "the law caps this at two months" would be false, and false in the
        direction that gets someone into an argument they cannot win. The figure
        is still a useful reference point, so it is shown either way - with
        different words.
        """
        note = " ".join((anchor.note or "").split())
        if anchor.applies:
            return f"{note} ({anchor.source})".strip()
        if self.user_state is None:
            # Not "your state has not adopted it": we were not told the state.
            return (
                f"{note} This is a model law that binds only in states that have "
                f"adopted it, so it is a reference point unless yours has. "
                f"({anchor.source})"
            ).strip()
        return (
            f"{note} This is a model law that your state has not adopted, so it "
            f"is a reference point rather than a rule that binds here. "
            f"({anchor.source})"
        ).strip()

    def _question(self, clause_type: str, s: ScoredTerm) -> str:
        assert s.norm is not None
        target = self._fmt(s.norm.quantile_target, s.term.unit) if hasattr(
            s.norm, "quantile_target"
        ) else self._fmt(s.norm.median, s.term.unit)
        subject = C.display_name(clause_type).lower()
        direction_word = "reduced" if (s.direction or 1) > 0 else "increased"
        return f"Ask whether the {subject} can be {direction_word} to around {target}."
