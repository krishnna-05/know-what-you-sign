"""The consumer terms-of-service domain.

A different problem shape from rental agreements: no numeric norms to deviate
from, but an expert-defined set of unfairness categories to match against. That
expert ground truth is why this domain exists in the project at all — it is the
only part that can be measured against work other people have published.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kwys import config as C
from kwys.classify.unfair import DESCRIPTIONS, describe
from kwys.classify.unfair_rules import labels
from kwys.models import Domain, Role

DATA = Path(__file__).resolve().parent.parent / "data" / "external" / "unfair_tos"


def test_domain_is_registered():
    assert Domain.CONSUMER_TOS.value in C.taxonomy()["domains"]
    assert C.weaker_party(Domain.CONSUMER_TOS) is Role.CONSUMER


def test_tos_expects_no_clauses():
    """Terms of service vary far too much in structure for an absence to mean
    anything. A missing-clause finding here would be pure noise."""
    assert C.expected_clauses(Domain.CONSUMER_TOS) == []


def test_every_category_has_plain_language():
    """The label set comes from an academic annotation scheme. "Unilateral
    change" is not a phrase anyone outside contract law would use, and a
    finding the reader cannot parse is not a finding."""
    for label in labels():
        headline, question = describe(label)
        assert headline != label, f"{label} was never translated"
        assert question.endswith((".", "?")), f"{label} has no actionable question"
        assert len(headline) < 90


def test_descriptions_cover_the_benchmark_labels():
    assert set(DESCRIPTIONS) == set(labels())


def test_unknown_label_degrades_gracefully():
    """If the benchmark adds a category, the tool must still say something
    rather than raising in front of a user."""
    headline, question = describe("Some New Category")
    assert headline and question


@pytest.mark.skipif(not (DATA / "test.jsonl").exists(), reason="needs unfair_tos")
def test_rules_find_real_annotated_clauses():
    """Sanity check against clauses that human annotators marked unfair. The
    baseline is not expected to catch them all — it catches roughly a third —
    but catching none would mean the rules are broken."""
    from kwys.classify.unfair_rules import predict

    rows = [json.loads(line) for line in (DATA / "test.jsonl").open()]
    unfair = [r for r in rows if r["labels"]][:200]
    hits = sum(1 for r in unfair if predict(r["text"]))
    assert hits / len(unfair) > 0.25, (
        f"rules fired on only {hits}/{len(unfair)} clauses experts marked unfair"
    )


@pytest.mark.skipif(not (DATA / "test.jsonl").exists(), reason="needs unfair_tos")
def test_rules_stay_quiet_on_fair_clauses():
    """Precision matters too: a report that flags every clause has told the
    reader nothing."""
    from kwys.classify.unfair_rules import predict

    rows = [json.loads(line) for line in (DATA / "test.jsonl").open()]
    fair = [r for r in rows if not r["labels"]][:300]
    false_alarms = sum(1 for r in fair if predict(r["text"]))
    assert false_alarms / len(fair) < 0.35, (
        f"rules fired on {false_alarms}/{len(fair)} clauses experts marked fair"
    )


def test_ui_role_map_covers_every_domain():
    """Regression: adding CONSUMER_TOS to the Domain enum left the Streamlit
    role map with two entries and three domains, which would have raised a
    KeyError in front of a user. Adding a domain must not silently break the
    interface."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from ui.app import ROLE_BY_DOMAIN

    missing = [d.value for d in Domain if d not in ROLE_BY_DOMAIN]
    assert not missing, f"the UI has no role options for: {missing}"
    for domain, options in ROLE_BY_DOMAIN.items():
        assert len(options) == 2, f"{domain} must offer both sides"


def test_synthetic_corpus_is_never_the_default():
    """Regression: the corpus selector sorted alphabetically, so SYNTHETIC-DEMO
    came above judgments-v1 and the app opened on invented numbers. A warning
    banner is not enough — a default that has to be read to be safe is the wrong
    default, and someone skimming would take fabricated percentiles at face
    value."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from ui.app import _available_versions

    for domain in Domain:
        versions = _available_versions(domain)
        if len(versions) > 1:
            assert "SYNTHETIC" not in versions[0].upper(), (
                f"{domain.value} would open on synthetic data: {versions}"
            )
