"""The semantic-outlier leg: opt-in, batched, and never loaded needlessly.

This is the weakest part of the method and the most expensive. Both facts are
measured, and both are why it does not run by default:

  - On the fixture's ordinary boilerplate it scores 87%, 88%, 93%, 95%, 95%
    against the LEDGAR centroids. Every one is near or past the 90% threshold,
    because Indian rental clauses sit far from US commercial ones across the
    board. The percentile scale is shifted, so the threshold flags almost
    everything.
  - Loading the embedding model costs ~15 seconds. Charging every reader that
    for the least reliable signal is a bad trade.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from kwys.models import Domain, Role

FIXTURE = Path(__file__).parent / "fixtures" / "sample_lease.pdf"
pytestmark = pytest.mark.skipif(not FIXTURE.exists(), reason="needs the fixture")


def _embedding_model_loaded() -> bool:
    """Has sentence-transformers actually been imported into this process?"""
    return "sentence_transformers" in sys.modules


def test_default_run_never_loads_the_embedding_model():
    """Regression: a 15-second model load ran on every analysis, to score one
    clause that then did not flag. The candidate list must be built before the
    module is touched."""
    from kwys.pipeline import analyse

    assert not _embedding_model_loaded(), "test must start with the model unloaded"
    analyse(str(FIXTURE), role=Role.TENANT, domain=Domain.RESIDENTIAL_LEASE)
    assert not _embedding_model_loaded(), (
        "the default path loaded the embedding model; it is opt-in"
    )


def test_semantic_flag_does_not_change_the_other_findings():
    """Turning the weak leg on must only ever ADD findings, never disturb the
    ones resting on solid evidence."""
    from kwys.pipeline import analyse

    off = analyse(str(FIXTURE), role=Role.TENANT, domain=Domain.RESIDENTIAL_LEASE)
    on = analyse(
        str(FIXTURE), role=Role.TENANT, domain=Domain.RESIDENTIAL_LEASE, semantic=True
    )
    assert {f.clause_id for f in off.findings} <= {f.clause_id for f in on.findings}


@pytest.mark.slow
def test_batched_scoring_matches_one_at_a_time():
    """The batched path is an optimisation, not a different answer."""
    from kwys.norms.semantic import SemanticNorms

    store = SemanticNorms.load(Path(__file__).parent.parent / "data" / "norms" / "semantic")
    if store.is_empty:
        pytest.skip("semantic centroids not built")

    items = [
        ("termination", "This agreement may be terminated by either party on notice."),
        ("indemnity", "The Lessee shall indemnify the Lessor against all claims."),
        ("no_such_type", "A clause of a type with no centroid at all."),
    ]
    batched = store.outlier_percentiles(items)
    one_by_one = [store.outlier_percentile(ct, text) for ct, text in items]
    assert batched == one_by_one
    assert batched[2] is None, "a type with no centroid must answer None, not 0.0"
