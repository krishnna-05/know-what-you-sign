"""PDF -> text with layout, the first stage of the pipeline.

Uses PyMuPDF because it exposes per-span font size, weight and bounding box.
That metadata is not a nicety: it is what lets the segmenter recognise a
heading in a document whose numbering is inconsistent, and what lets the report
highlight a clause in the user's own PDF rather than asking them to trust us.
"""

from __future__ import annotations

import logging
import re
import statistics
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from kwys.models import Span

log = logging.getLogger(__name__)

# A page with almost no extractable text but plenty of page area is a scan.
# 50 characters is generous: even a near-empty page of a real PDF beats it.
SCANNED_CHAR_THRESHOLD = 50

# A line repeating at the same vertical position on this fraction of pages is
# running furniture (header/footer), not contract text.
FURNITURE_PAGE_FRACTION = 0.6
FURNITURE_Y_TOLERANCE = 8.0  # points

_DIGITS = re.compile(r"\d+")


@dataclass
class Line:
    """One visual line of text, with the typography needed to spot headings."""

    text: str
    page: int
    bbox: tuple[float, float, float, float]
    size: float  # dominant font size on the line
    bold: bool
    order: int

    @property
    def span(self) -> Span:
        x0, y0, x1, y1 = self.bbox
        return Span(page=self.page, x0=x0, y0=y0, x1=x1, y1=y1)

    @property
    def y(self) -> float:
        return self.bbox[1]


@dataclass
class ParsedDocument:
    path: str
    lines: list[Line] = field(default_factory=list)
    page_count: int = 0
    scanned_pages: list[int] = field(default_factory=list)
    body_size: float = 10.0  # modal font size, i.e. ordinary paragraph text
    warnings: list[str] = field(default_factory=list)
    # Setup problems for the maintainer, not the reader (see AnalysisResult).
    diagnostics: list[str] = field(default_factory=list)

    @property
    def was_ocred(self) -> bool:
        return bool(self.scanned_pages)

    @property
    def text(self) -> str:
        return "\n".join(ln.text for ln in self.lines)


def _is_bold(flags: int, fontname: str) -> bool:
    """PyMuPDF exposes bold both as a span flag bit and in the font name."""
    return bool(flags & 2**4) or "bold" in fontname.lower()


def _clean(text: str) -> str:
    """Repair the usual PDF extraction damage.

    Ligatures survive as single codepoints and break keyword matching later;
    non-breaking spaces defeat naive whitespace splitting.
    """
    for bad, good in (
        ("ﬀ", "ff"), ("ﬁ", "fi"), ("ﬂ", "fl"),
        ("ﬃ", "ffi"), ("ﬄ", "ffl"),
        (" ", " "), ("’", "'"), ("‘", "'"),
        ("“", '"'), ("”", '"'),
        ("–", "-"), ("—", "-"),
    ):
        text = text.replace(bad, good)
    return " ".join(text.split())


def _extract_lines(doc: pymupdf.Document) -> tuple[list[Line], list[int]]:
    lines: list[Line] = []
    scanned: list[int] = []
    order = 0

    for pno, page in enumerate(doc):
        page_dict = page.get_text("dict")
        page_chars = 0

        for block in page_dict.get("blocks", []):
            if block.get("type") != 0:  # 0 = text, 1 = image
                continue
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                if not spans:
                    continue
                text = _clean("".join(s.get("text", "") for s in spans))
                if not text:
                    continue
                page_chars += len(text)

                # Size and weight come from the span holding the most characters,
                # so a stray superscript does not redefine the line.
                dominant = max(spans, key=lambda s: len(s.get("text", "")))
                lines.append(
                    Line(
                        text=text,
                        page=pno,
                        bbox=tuple(line["bbox"]),
                        size=round(float(dominant.get("size", 10.0)), 1),
                        bold=_is_bold(
                            int(dominant.get("flags", 0)), str(dominant.get("font", ""))
                        ),
                        order=order,
                    )
                )
                order += 1

        if page_chars < SCANNED_CHAR_THRESHOLD:
            scanned.append(pno)

    return lines, scanned


def _furniture_key(line: Line) -> tuple[str, int]:
    """Identity of a line for repeated-furniture detection.

    Digits are normalised away because the commonest footer of all — "Page 1 of
    2", "Page 2 of 2" — differs on every page and would otherwise never be
    recognised as repeating. Position is included so a phrase that legitimately
    recurs in the body is not mistaken for a header.
    """
    return (_DIGITS.sub("#", line.text.lower()), round(line.y / FURNITURE_Y_TOLERANCE))


def _strip_furniture(lines: list[Line], page_count: int) -> tuple[list[Line], int]:
    """Remove headers, footers and page numbers.

    Matched on (digit-normalised text, rounded y-position) rather than text
    alone, so a clause that legitimately repeats a phrase in the body is not
    eaten. Requires the line to appear on most pages at the same height.
    """
    if page_count < 2:
        return lines, 0  # a single page cannot show repetition

    keyed = Counter(_furniture_key(ln) for ln in lines if len(ln.text) < 120)
    threshold = max(2, int(page_count * FURNITURE_PAGE_FRACTION))
    furniture = {k for k, count in keyed.items() if count >= threshold}

    if not furniture:
        return lines, 0

    kept = [ln for ln in lines if _furniture_key(ln) not in furniture]
    return kept, len(lines) - len(kept)


def read_pdf(
    path: str | Path, *, strip_furniture: bool = True, ocr: bool = True
) -> ParsedDocument:
    """Read a PDF into typed lines carrying their typography and position.

    Raises FileNotFoundError if the path is wrong; returns a document with
    `scanned_pages` populated (and no text for those pages) when the file is a
    scan — the caller decides whether to route it to OCR.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"No such document: {path}")

    with pymupdf.open(path) as doc:
        page_count = doc.page_count
        lines, scanned = _extract_lines(doc)

    parsed = ParsedDocument(
        path=str(path), lines=lines, page_count=page_count, scanned_pages=scanned
    )

    if scanned:
        from kwys.ingest.ocr import is_available, ocr_document

        if ocr and is_available():
            log.info("OCR-ing %d scanned page(s)", len(scanned))
            ocr_lines, ocr_warnings = ocr_document(str(path), scanned)
            # Interleave by page so clause order follows the document, not the
            # order in which the two readers happened to run.
            parsed.lines = sorted(
                parsed.lines + ocr_lines, key=lambda ln: (ln.page, ln.bbox[1])
            )
            for i, ln in enumerate(parsed.lines):
                ln.order = i
            parsed.warnings.extend(ocr_warnings)
        else:
            parsed.warnings.append(
                f"{len(scanned)} of {page_count} pages look scanned and could not "
                f"be read, so nothing on them was checked."
            )
            parsed.diagnostics.append(
                "OCR is not installed. Install it with: uv pip install -e '.[ocr]'"
            )

    if strip_furniture:
        parsed.lines, removed = _strip_furniture(parsed.lines, page_count)
        if removed:
            log.debug("Removed %d header/footer lines", removed)

    if parsed.lines:
        # Modal size, not mean: a document is mostly body text, and the mode is
        # unmoved by a big title or a block of fine print.
        parsed.body_size = statistics.mode(ln.size for ln in parsed.lines)
    else:
        parsed.warnings.append("No extractable text found at all.")

    return parsed
