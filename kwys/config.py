"""Loading and validating the three declarative config files.

These three files carry every judgement the system makes that is not learned
from data. They are loaded once, validated loudly, and cached.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from kwys.models import Domain, Role, StatutoryAnchorHit

log = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def _load(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Missing config file: {path}")
    with path.open() as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{name} did not parse to a mapping")
    return data


# ---------------------------------------------------------------- taxonomy


@lru_cache(maxsize=1)
def taxonomy() -> dict[str, Any]:
    return _load("taxonomy.yaml")


def clause_types(domain: Domain | None = None) -> list[str]:
    types = taxonomy()["clause_types"]
    if domain is None:
        return sorted(types)
    return sorted(t for t, spec in types.items() if domain.value in spec.get("domains", []))


def expected_clauses(domain: Domain) -> list[str]:
    """Clause types a document of this kind should normally contain.

    Used for missing-clause detection: the absence of a deposit-refund timeline
    is a risk the reader cannot possibly notice, because there is nothing on the
    page to notice.
    """
    return list(taxonomy()["domains"][domain.value].get("expected_clauses", []))


def weaker_party(domain: Domain) -> Role:
    return Role(taxonomy()["domains"][domain.value]["weaker_party"])


def display_name(clause_type: str) -> str:
    spec = taxonomy()["clause_types"].get(clause_type, {})
    return spec.get("display_name", clause_type.replace("_", " "))


# ---------------------------------------------------------------- direction


@lru_cache(maxsize=1)
def direction_map() -> dict[str, Any]:
    return _load("direction_map.yaml")["fields"]


def direction_for(field_key: str, role: Role) -> tuple[int, str] | None:
    """Return (+1|-1, rationale) for a field/role pair, or None if undeclared.

    `field_key` is "clause_type.field_name", e.g. "security_deposit.deposit_months".

    Returning None is meaningful and must not be treated as neutral: it means
    nobody has decided which way this field cuts, so the system has no business
    calling a deviation on it risky. The scorer skips these.
    """
    entry = direction_map().get(field_key)
    if not entry:
        return None
    per_role = entry.get(role.value)
    if not per_role:
        return None
    return int(per_role["direction"]), str(per_role["rationale"])


def undeclared_fields() -> list[str]:
    """Fields the taxonomy extracts but the direction map does not cover.

    Surfaced by `kwys doctor` so the gap is visible rather than silently
    swallowing findings.
    """
    declared = set(direction_map())
    extracted = {
        f"{ct}.{fname}"
        for ct, spec in taxonomy()["clause_types"].items()
        for fname in (spec.get("fields") or {})
    }
    # party/place/boolean fields are not scored by deviation, so exempt them
    scored_kinds = {"money", "duration", "percent", "ratio", "count", "distance"}
    numeric = {
        key
        for key in extracted
        if (spec := taxonomy()["clause_types"][key.split(".")[0]]["fields"].get(key.split(".")[1]))
        and spec.get("kind") in scored_kinds
    }
    return sorted(numeric - declared)


# ---------------------------------------------------------------- anchors


@lru_cache(maxsize=1)
def _anchors_raw() -> dict[str, Any]:
    return _load("statutory_anchors.yaml")


def statutory_anchor(
    field_key: str,
    value: float,
    variant: str = "residential",
    user_state: str | None = None,
) -> StatutoryAnchorHit | None:
    """Look up a verified statutory anchor for a field.

    Unverified anchors are SKIPPED with a warning, never used. A wrong citation
    in a tool aimed at people without legal training manufactures false
    confidence in exactly the person least able to catch the error, so the gate
    is deliberately annoying: someone must read the bare Act and set
    `verified: true` by hand.
    """
    per_field = _anchors_raw().get("anchors", {}).get(field_key)
    if not per_field:
        return None

    spec = per_field.get(variant) or per_field.get("all")
    if not spec:
        return None

    if not spec.get("verified", False):
        log.warning(
            "Statutory anchor %s/%s (%s) is unverified and was skipped. "
            "Read the bare Act, confirm the section and figure, then set verified: true.",
            field_key,
            variant,
            spec.get("source", "unknown source"),
        )
        return None

    comparison = spec["comparison"]
    anchor_value = float(spec["value"])
    exceeded = value > anchor_value if comparison == "max" else value < anchor_value

    applies_in = spec.get("applies_in") or []
    applies = "ALL_INDIA" in applies_in or (user_state is not None and user_state in applies_in)

    return StatutoryAnchorHit(
        value=anchor_value,
        comparison=comparison,
        unit=spec["unit"],
        source=spec["source"],
        note=spec.get("note"),
        exceeded=exceeded,
        applies=applies,
    )


def unverified_anchors() -> list[str]:
    """Every anchor still awaiting someone reading the bare Act."""
    out = []
    for field_key, variants in _anchors_raw().get("anchors", {}).items():
        for variant, spec in variants.items():
            if not spec.get("verified", False):
                out.append(f"{field_key}/{variant} — {spec.get('source', '?')}")
    return sorted(out)


# ---------------------------------------------------------------- validation


def validate_all() -> list[str]:
    """Cross-check the three files against each other. Returns problems found."""
    problems: list[str] = []

    tax = taxonomy()
    known_types = set(tax["clause_types"])

    for dom, spec in tax["domains"].items():
        for ct in spec.get("expected_clauses", []):
            if ct not in known_types:
                problems.append(f"domain {dom}: expected_clauses names unknown type {ct!r}")
        try:
            Role(spec["weaker_party"])
        except ValueError:
            problems.append(f"domain {dom}: weaker_party {spec['weaker_party']!r} is not a Role")

    for field_key in direction_map():
        ct = field_key.split(".")[0]
        if ct not in known_types:
            problems.append(f"direction_map: unknown clause type {ct!r} in {field_key!r}")

    for field_key in _anchors_raw().get("anchors", {}):
        ct = field_key.split(".")[0]
        if ct not in known_types:
            problems.append(f"statutory_anchors: unknown clause type {ct!r} in {field_key!r}")

    return problems
