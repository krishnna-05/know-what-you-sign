"""The HTTP layer behind the web interface.

Run against a throwaway norms directory, so the result does not depend on
which corpora happen to be built on the machine running the tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

import kwys.api.main as api  # noqa: E402
import kwys.pipeline as pipeline  # noqa: E402
from kwys.norms.store import MIN_N, NormStore, available_versions, default_version  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "sample_lease.pdf"
LEASE = "residential_lease"


@pytest.fixture
def data_root(tmp_path, monkeypatch) -> Path:
    """A data root holding one real corpus and one synthetic one."""
    norms = tmp_path / "norms"
    for version in ("real-v1", "SYNTHETIC-DEMO"):
        store = NormStore(LEASE, version, label="Real agreements, from court cases")
        for i in range(MIN_N + 10):
            store.add("notice_period.notice_months", 1 + i % 3, "months")
        store.save(norms)
    monkeypatch.setattr(api, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(pipeline, "DATA_ROOT", tmp_path)
    monkeypatch.delenv("KWYS_DEMO_DATA", raising=False)
    return tmp_path


@pytest.fixture
def client(data_root) -> TestClient:
    return TestClient(api.app)


def _post(client: TestClient, **form):
    with FIXTURE.open("rb") as f:
        return client.post(
            "/api/analyse",
            files={"file": ("lease.pdf", f, "application/pdf")},
            data={"role": "tenant", "domain": LEASE, **form},
        )


def test_synthetic_corpus_is_never_the_default(data_root):
    root = data_root / "norms"
    assert available_versions(root, LEASE) == ["real-v1", "SYNTHETIC-DEMO"]
    assert default_version(root, LEASE) == "real-v1"
    assert default_version(root, "employment_offer") is None


def _lease_corpora(client: TestClient) -> list[dict]:
    cfg = client.get("/api/config").json()
    return next(d for d in cfg["domains"] if d["value"] == LEASE)["corpora"]


def test_demo_data_is_hidden_by_default(client):
    """Invented percentiles are not offered to someone checking a real contract."""
    assert [c["version"] for c in _lease_corpora(client)] == ["real-v1"]
    assert _post(client, corpus_version="SYNTHETIC-DEMO").status_code == 400


def test_demo_data_can_be_switched_on(client, monkeypatch):
    monkeypatch.setenv("KWYS_DEMO_DATA", "1")
    corpora = _lease_corpora(client)
    assert [c["version"] for c in corpora] == ["real-v1", "SYNTHETIC-DEMO"]
    # A synthetic store is labelled as such whatever its manifest claims.
    assert corpora[1]["label"] == "Invented demo data (for testing only)"
    assert _post(client, corpus_version="SYNTHETIC-DEMO").status_code == 200


def test_corpora_carry_reader_facing_labels(client):
    corpus = _lease_corpora(client)[0]
    assert corpus["label"] == "Real agreements, from court cases"
    assert corpus["coverage"][0]["label"]


def test_analyse_without_a_corpus_uses_the_real_default(client):
    """Omitting the corpus must not silently mean "compare against nothing"."""
    r = _post(client)
    assert r.status_code == 200, r.text
    assert r.json()["corpusLabel"] == "Real agreements, from court cases"


@pytest.mark.parametrize("version", ["v1", "../../etc", "judgments-v1"])
def test_unknown_corpus_is_refused(client, version):
    """It is a path component; anything not actually built is rejected."""
    r = _post(client, corpus_version=version)
    assert r.status_code == 400


def test_role_must_belong_to_the_domain(client):
    r = _post(client, role="employee")
    assert r.status_code == 400


def test_non_pdf_is_refused(client):
    r = client.post(
        "/api/analyse",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        data={"role": "tenant", "domain": LEASE},
    )
    assert r.status_code == 400


def test_oversized_upload_is_refused(client, monkeypatch):
    monkeypatch.setattr(api, "MAX_UPLOAD_BYTES", 10)
    r = _post(client)
    assert r.status_code == 413


def test_every_charted_finding_has_its_distribution(client):
    body = _post(client, corpus_version="real-v1").json()
    for f in body["findings"]:
        if f["evidence"]["norm"]:
            assert f["evidence"]["field"] in body["distributions"]
