"""Reading scanned agreements.

Most people do not have a clean PDF of what they signed — they have a photo. A
tool that only reads native PDFs does not serve the person it was built for.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kwys.ingest.ocr import is_available

FIXTURE = Path(__file__).parent / "fixtures" / "sample_lease_scanned.pdf"

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        not is_available() or not FIXTURE.exists(),
        reason="needs the ocr extra and the scanned fixture",
    ),
]


def test_scanned_pages_are_detected_and_read():
    from kwys.ingest.pdf_reader import read_pdf

    parsed = read_pdf(str(FIXTURE))
    assert parsed.scanned_pages, "an image-only PDF must be recognised as scanned"
    assert parsed.was_ocred
    assert len(parsed.lines) > 20, "OCR should recover the body text"


def test_ocr_lines_carry_positions():
    """Without real bounding boxes the segmenter's typography branch stops
    working on scans and the report cannot highlight anything in the original."""
    from kwys.ingest.pdf_reader import read_pdf

    parsed = read_pdf(str(FIXTURE))
    for line in parsed.lines[:10]:
        x0, y0, x1, y1 = line.bbox
        assert x1 > x0 and y1 > y0, "degenerate bounding box"
        assert 0 <= x0 < 700 and 0 <= y0 < 900, "coordinates must be in PDF points"


def test_pipeline_runs_on_a_scan():
    from kwys.models import Domain, Role
    from kwys.pipeline import analyse

    result = analyse(str(FIXTURE), role=Role.TENANT, domain=Domain.RESIDENTIAL_LEASE)
    assert result.document.was_ocred
    assert result.clauses_checked > 5, "OCR output must still segment into clauses"
    assert any("optical character recognition" in w for w in result.warnings), (
        "the user must be told the text was recognised rather than read"
    )


def test_ocr_can_be_disabled():
    from kwys.ingest.pdf_reader import read_pdf

    parsed = read_pdf(str(FIXTURE), ocr=False)
    assert not parsed.lines, "with OCR off, an image-only PDF yields no text"
    assert any("not installed" in w or "not read" in w for w in parsed.warnings)
