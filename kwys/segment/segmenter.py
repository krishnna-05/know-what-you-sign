"""Turning a parsed document into a tree of clauses.

Cascade, most reliable signal first:
  1. hierarchical numbering        (1, 1.1, (a), ARTICLE IV)
  2. typographic headings          (larger, bold, or ALL CAPS short lines)
  3. blank-line paragraph blocks   (last resort)

If too little of the document matched a structural signal, the result is marked
`low_structure` and the caller warns the user rather than silently presenting
garbage as analysis.
"""

from __future__ import annotations

import logging

from kwys.ingest.pdf_reader import Line, ParsedDocument
from kwys.models import Clause
from kwys.segment.numbering import looks_like_heading, match_number

log = logging.getLogger(__name__)

# Below this share of numbered blocks we do not trust the structure.
LOW_STRUCTURE_THRESHOLD = 0.35

# A "clause" shorter than this is a stray fragment, not a provision.
MIN_CLAUSE_CHARS = 25


def _new_clause(
    *, cid: str, number: str | None, heading: str | None, depth: int, order: int, line: Line
) -> Clause:
    return Clause(
        id=cid,
        number=number,
        heading=heading,
        text="",
        spans=[line.span],
        depth=depth,
        order=order,
    )


def segment(parsed: ParsedDocument) -> tuple[list[Clause], bool]:
    """Split a parsed document into clauses.

    Returns (clauses, low_structure).
    """
    if not parsed.lines:
        return [], True

    clauses: list[Clause] = []
    current: Clause | None = None
    order = 0
    numbered_starts = 0
    # depth -> heading, so a sub-clause can inherit "4. TERMINATION"
    heading_stack: dict[int, str] = {}

    for line in parsed.lines:
        num = match_number(line.text)
        is_heading = looks_like_heading(
            line.text, line.size, parsed.body_size, line.bold
        )

        starts_clause = num is not None or (is_heading and current is not None)

        if starts_clause:
            if current is not None:
                _finalise(current, clauses)

            if num is not None:
                numbered_starts += 1
                depth = num.depth
                label = num.label
                # A numbered line whose remainder is a heading (e.g. "4. TERMINATION")
                # gives this clause its own heading and seeds it for children.
                own_heading = (
                    num.rest
                    if num.rest and looks_like_heading(
                        num.rest, line.size, parsed.body_size, line.bold
                    )
                    else None
                )
                cid = label
            else:
                depth = 0
                label = None
                own_heading = line.text.strip()
                cid = f"h{order}"

            current = _new_clause(
                cid=cid, number=label, heading=own_heading, depth=depth, order=order, line=line
            )

            # Inherit the nearest shallower heading as context.
            parent = next(
                (heading_stack[d] for d in sorted(heading_stack, reverse=True) if d < depth),
                None,
            )
            current.parent_heading = parent

            if own_heading:
                heading_stack[depth] = own_heading
                # A new heading at this depth invalidates deeper ones.
                for d in [d for d in heading_stack if d > depth]:
                    heading_stack.pop(d)

            if num is not None and num.rest and own_heading is None:
                current.text = num.rest

            order += 1
            continue

        if current is None:
            # Preamble before the first numbered clause: parties, recitals.
            current = _new_clause(
                cid="preamble", number=None, heading="Preamble", depth=0, order=order, line=line
            )
            order += 1

        current.text = f"{current.text} {line.text}".strip()
        current.spans.append(line.span)

    if current is not None:
        _finalise(current, clauses)

    total_starts = max(1, len([c for c in clauses if c.id != "preamble"]))
    numbered_ratio = numbered_starts / total_starts
    low_structure = numbered_ratio < LOW_STRUCTURE_THRESHOLD

    if low_structure:
        log.warning(
            "Only %.0f%% of clause starts were numbered; document structure is unreliable.",
            numbered_ratio * 100,
        )

    clauses = _dedupe_ids(clauses)
    return clauses, low_structure


def _finalise(clause: Clause, out: list[Clause]) -> None:
    """Keep a clause only if it carries enough text to say anything about.

    A heading with no body is not a provision — but if it opened a section we
    still needed it on the stack, which is why this filter runs at the end
    rather than at creation.
    """
    clause.text = clause.text.strip()
    if len(clause.text) >= MIN_CLAUSE_CHARS:
        out.append(clause)


def _dedupe_ids(clauses: list[Clause]) -> list[Clause]:
    """Documents restart numbering across schedules and annexures.

    Duplicate ids would silently overwrite each other in every downstream dict,
    so the second "4.2" becomes "4.2#2" rather than colliding.
    """
    seen: dict[str, int] = {}
    for c in clauses:
        if c.id in seen:
            seen[c.id] += 1
            c.id = f"{c.id}#{seen[c.id]}"
        else:
            seen[c.id] = 1
    return clauses


def segment_file(path: str) -> tuple[list[Clause], bool, ParsedDocument]:
    """Convenience wrapper: read a PDF and segment it in one call."""
    from kwys.ingest.pdf_reader import read_pdf

    parsed = read_pdf(path)
    clauses, low = segment(parsed)
    return clauses, low, parsed
