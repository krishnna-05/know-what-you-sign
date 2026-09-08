"""Reading scanned agreements.

Most people do not have a clean PDF of the thing they signed. They have a photo
taken on a phone, or a scan a landlord emailed them. A tool that only reads
native PDFs does not serve the person it was built for.

Uses RapidOCR (ONNX runtime, CPU) rather than Tesseract because it needs no
system binary: `uv pip install rapidocr-onnxruntime` and it works. That matters
for a project meant to be deployable on a free tier by someone without admin
rights on their machine.

The important design point is that OCR output is converted back into the SAME
`Line` objects the native reader produces, carrying real bounding boxes and an
estimated font size. Everything downstream - heading detection, clause
numbering, the report's clause highlighting - then works unchanged on a scan.
"""

from __future__ import annotations

import logging
import statistics
from functools import lru_cache
from typing import TYPE_CHECKING, Any

import pymupdf

if TYPE_CHECKING:
    from kwys.ingest.pdf_reader import Line

log = logging.getLogger(__name__)

# 200 dpi is the usual sweet spot: enough detail for 8-10pt legal body text,
# without the memory cost of 300+ on a 20-page scan.
RENDER_DPI = 200

# Below this the recogniser is guessing. Kept rather than dropped, but the
# caller is told, because a silently mangled clause is worse than a flagged one.
MIN_TEXT_CONFIDENCE = 0.5


@lru_cache(maxsize=1)
def _engine() -> Any:
    """Load the OCR engine once. Model load dominates the cost of a short run."""
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError(
            "OCR needs the 'ocr' extra: uv pip install -e '.[ocr]'"
        ) from exc
    return RapidOCR()


def _preprocess(img):
    """Deskew and clean a page before recognition.

    Phone photos of contracts are rarely square to the page, and a few degrees
    of rotation measurably costs accuracy on dense small text. Skipped silently
    when OpenCV is absent - the OCR still runs, just less well.
    """
    try:
        import cv2
    except ImportError:
        return img

    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY) if img.ndim == 3 else img

    # Estimate skew from the dominant text angle via the minimum-area rectangle
    # around the dark pixels.
    thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    coords = cv2.findNonZero(thresh)
    if coords is None:
        return img

    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle += 90
    elif angle > 45:
        angle -= 90

    # Only correct a genuine tilt. Rotating by a fraction of a degree adds
    # interpolation blur for no gain.
    if abs(angle) < 0.75 or abs(angle) > 15:
        return img

    h, w = gray.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(
        img, matrix, (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def ocr_page(page: pymupdf.Page, page_number: int, start_order: int) -> list[Line]:
    """Recognise one page, returning Lines positioned in PDF coordinates."""
    import numpy as np

    from kwys.ingest.pdf_reader import Line

    pix = page.get_pixmap(dpi=RENDER_DPI)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    img = np.ascontiguousarray(img[:, :, :3])
    img = _preprocess(img)

    result, _ = _engine()(img)
    if not result:
        return []

    # Map image pixels back to PDF points so spans line up with the original
    # page - without this the report cannot highlight a clause on a scan.
    scale = 72.0 / RENDER_DPI

    raw: list[tuple[list, str, float]] = [
        (box, text, float(conf)) for box, text, conf in result if text.strip()
    ]
    if not raw:
        return []

    heights = [
        abs(max(p[1] for p in box) - min(p[1] for p in box)) for box, _, _ in raw
    ]
    body_height = statistics.median(heights) if heights else 1.0

    lines: list[Line] = []
    for i, (box, text, _conf) in enumerate(raw):
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        height = abs(max(ys) - min(ys))

        # RapidOCR gives no font metrics. Height relative to the page's median
        # line is a serviceable proxy: it is exactly what the heading detector
        # compares, and headings really are taller.
        size = round(10.0 * (height / body_height), 1) if body_height else 10.0

        lines.append(
            Line(
                text=text.strip(),
                page=page_number,
                bbox=(
                    min(xs) * scale, min(ys) * scale,
                    max(xs) * scale, max(ys) * scale,
                ),
                size=size,
                # Weight is not recoverable from OCR. Reporting False rather than
                # guessing keeps the heading detector on the size signal alone,
                # which is the one we can actually measure.
                bold=False,
                order=start_order + i,
            )
        )

    low = sum(1 for _, _, c in raw if c < MIN_TEXT_CONFIDENCE)
    if low:
        log.info("page %d: %d of %d lines recognised with low confidence",
                 page_number + 1, low, len(raw))

    return lines


def ocr_document(path: str, pages: list[int]) -> tuple[list[Line], list[str]]:
    """OCR the given page numbers of a document.

    Returns (lines, warnings). Only the pages the native reader could not read
    are processed: OCR is roughly a hundred times slower than text extraction,
    and running it over a document that is already readable wastes a minute for
    a worse result.
    """
    warnings: list[str] = []
    lines: list[Line] = []

    with pymupdf.open(path) as doc:
        for pno in pages:
            if pno >= doc.page_count:
                continue
            try:
                page_lines = ocr_page(doc[pno], pno, len(lines))
            except Exception as exc:  # noqa: BLE001 - one bad page must not stop the rest
                log.warning("OCR failed on page %d: %s", pno + 1, exc)
                warnings.append(f"Page {pno + 1} could not be read even with OCR.")
                continue
            if not page_lines:
                warnings.append(f"Page {pno + 1} appears to contain no readable text.")
            lines.extend(page_lines)

    if lines:
        warnings.append(
            f"{len(pages)} page(s) were read by optical character recognition "
            "because they contain no selectable text. Recognition is imperfect: "
            "check any figure that matters against the original document."
        )
    return lines, warnings


def is_available() -> bool:
    try:
        import rapidocr_onnxruntime  # noqa: F401
    except ImportError:
        return False
    return True
