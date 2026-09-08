"""Generate synthetic contract PDFs for testing the pipeline.

IMPORTANT — these are for testing PARSING ONLY. Synthetic agreements must never
enter the reference corpus. Computing percentiles over documents we generated
ourselves and then reporting them as empirical norms would be circular: the
system would be measuring our own assumptions and calling it evidence.
See PLAN.md section 2, "What to deliberately not use".

Usage:  python tests/fixtures/make_fixture.py
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

HERE = Path(__file__).parent

# A deliberately lopsided agreement. The terms marked ⚑ are outliers we expect
# the pipeline to flag once norms exist; the rest are ordinary and should stay
# quiet. A fixture where everything is alarming tests nothing.
LEASE = [
    ("H1", "RESIDENTIAL RENTAL AGREEMENT"),
    ("P", "This Rental Agreement is made at Bengaluru on this 5th day of April 2026 "
          "between Mr. A. Kumar, residing at Indiranagar, Bengaluru (hereinafter referred "
          "to as the \"LESSOR\") of the ONE PART and Ms. S. Nair (hereinafter referred to "
          "as the \"LESSEE\") of the OTHER PART."),
    ("H2", "1. TERM"),
    ("P", "1.1 The tenancy shall commence on 1st May 2026 and shall be for a period of "
          "eleven (11) months, renewable by mutual consent."),
    ("P", "1.2 The Lessee shall not vacate the premises before the expiry of a lock-in "
          "period of nine (9) months from the date of commencement. ⚑"),
    ("H2", "2. RENT AND DEPOSIT"),
    ("P", "2.1 The Lessee shall pay a monthly rent of Rs. 32,000/- (Rupees Thirty Two "
          "Thousand only) on or before the 5th day of each English calendar month."),
    ("P", "2.2 The Lessee has paid a refundable interest-free security deposit of "
          "Rs. 1,92,000/- (Rupees One Lakh Ninety Two Thousand only), being six (6) "
          "months' rent, the receipt of which the Lessor hereby acknowledges. ⚑"),
    ("P", "2.3 The said security deposit shall be refunded to the Lessee within one "
          "hundred and eighty (180) days from the date of handing over vacant "
          "possession, after deducting any amounts due. ⚑"),
    ("P", "2.4 The rent shall be enhanced by ten percent (10%) upon each renewal."),
    ("P", "2.5 In the event of any delay in payment of rent beyond the due date, the "
          "Lessee shall pay interest at the rate of 3% per month on the outstanding amount."),
    ("H2", "3. MAINTENANCE AND USE"),
    ("P", "3.1 The Lessee shall keep the premises in good and tenantable condition and "
          "shall bear all minor repairs up to Rs. 3,000/- per occasion."),
    ("P", "3.2 The Lessee shall not sublet, assign or part with possession of the "
          "premises or any part thereof without the prior written consent of the Lessor."),
    ("P", "3.3 The Lessor or his authorised agent may enter and inspect the premises at "
          "any time without prior notice to the Lessee. ⚑"),
    ("H2", "4. NOTICE AND TERMINATION"),
    ("P", "4.1 The Lessee shall give six (6) months prior written notice to the Lessor "
          "of his intention to vacate the premises. ⚑"),
    ("P", "4.2 The Lessor may terminate this agreement by giving fifteen (15) days "
          "written notice to the Lessee. ⚑"),
    ("P", "4.3 Upon termination the Lessee shall hand over vacant and peaceful "
          "possession of the premises to the Lessor."),
    ("H2", "5. DISPUTE RESOLUTION"),
    ("P", "5.1 All disputes arising out of or in connection with this agreement shall be "
          "referred to arbitration by a sole arbitrator appointed by the Lessor, and the "
          "seat of arbitration shall be at New Delhi. ⚑"),
    ("P", "5.2 The courts at New Delhi alone shall have exclusive jurisdiction. ⚑"),
    ("H2", "6. INDEMNITY"),
    ("P", "6.1 The Lessee shall indemnify and keep indemnified the Lessor against all "
          "claims, damages, costs and expenses arising from the Lessee's use of the premises."),
    ("P", "IN WITNESS WHEREOF the parties have set their hands on the day and year first "
          "above written."),
]


def _wrap(text: str, fontname: str, size: float, width: float) -> list[str]:
    """Greedy word wrap, measured with the real font metrics."""
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if pymupdf.get_text_length(trial, fontname=fontname, fontsize=size) <= width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def build(blocks: list[tuple[str, str]], out: Path, *, page_size=(595, 842)) -> Path:
    """Render blocks to a PDF with real heading typography.

    Lays out line by line at explicit coordinates rather than relying on
    insert_textbox's return value, which made overflow silently overlap text and
    drop whole sections. Headings are bold and larger than body so the
    segmenter's typographic branch is genuinely exercised.
    """
    page_w, page_h = page_size
    margin, width = 60.0, page_size[0] - 120.0
    top, bottom = 70.0, page_h - 70.0

    doc = pymupdf.open()

    def new_page():
        return doc.new_page(width=page_w, height=page_h)

    page, y = new_page(), top

    for kind, text in blocks:
        text = text.replace(" \u2691", "")  # marker is for the reader of this file only
        size, font = {"H1": (15, "hebo"), "H2": (12, "hebo"), "P": (10, "helv")}[kind]
        leading = size * 1.45
        gap = {"H1": 20, "H2": 14, "P": 8}[kind]

        wrapped = _wrap(text, font, size, width)

        # Keep a heading with at least one line of what follows it.
        needed = leading * (len(wrapped) + (1 if kind != "P" else 0))
        if y + needed > bottom and y > top:
            page, y = new_page(), top

        for line in wrapped:
            if y + leading > bottom:
                page, y = new_page(), top
            page.insert_text((margin, y), line, fontsize=size, fontname=font)
            y += leading
        y += gap

    # Footer once per page, after layout, so it never collides with body text.
    total = doc.page_count
    for i in range(total):
        doc[i].insert_text(
            (margin, page_h - 40), f"Page {i + 1} of {total}", fontsize=8, fontname="helv"
        )

    doc.save(out)
    doc.close()
    return out


if __name__ == "__main__":
    p = build(LEASE, HERE / "sample_lease.pdf")
    print(f"wrote {p} ({p.stat().st_size:,} bytes)")
