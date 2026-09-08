"""Remove personal information before a document enters the corpus.

Agreements carry names, addresses, phone numbers, salaries and identity numbers.
Anything a real person shares for this project gets scrubbed on ingest, before
it is written to disk - not later, not on export.

This is regex-based and therefore imperfect. It is a floor, not a guarantee:
read the output before trusting it, and never publish a corpus on the strength
of this script alone.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

# Indian identifiers, most specific first.
PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("aadhaar", re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"), "[AADHAAR]"),
    ("pan", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), "[PAN]"),
    ("gstin", re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][A-Z\d]Z[A-Z\d]\b"), "[GSTIN]"),
    ("phone", re.compile(r"(?<!\d)(?:\+91[-\s]?)?[6-9]\d{9}(?!\d)"), "[PHONE]"),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b"), "[EMAIL]"),
    ("account", re.compile(r"\b(?:A/?c|account)\s*(?:no\.?|number)?\s*:?\s*\d{9,18}\b", re.I),
     "[ACCOUNT]"),
    ("ifsc", re.compile(r"\b[A-Z]{4}0[A-Z\d]{6}\b"), "[IFSC]"),
    # Names introduced by an honorific - the commonest way parties are named.
    ("name", re.compile(r"\b(?:Mr|Mrs|Ms|Shri|Smt|Dr|M/s)\.?\s+[A-Z][A-Za-z.]*"
                        r"(?:\s+[A-Z][A-Za-z.]*){0,3}"), "[NAME]"),
]


def scrub(text: str) -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}
    for name, pattern, replacement in PATTERNS:
        text, n = pattern.subn(replacement, text)
        if n:
            counts[name] = counts.get(name, 0) + n
    return text, counts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("paths", nargs="+", type=Path, help="text files to scrub in place")
    ap.add_argument("--report", type=Path, help="write a JSON summary of what was removed")
    args = ap.parse_args()

    summary = {}
    for path in args.paths:
        text = path.read_text(errors="replace")
        cleaned, counts = scrub(text)
        path.write_text(cleaned)
        summary[str(path)] = counts
        total = sum(counts.values())
        print(f"{path.name}: removed {total} item(s) {counts or ''}")

    if args.report:
        args.report.write_text(json.dumps(summary, indent=2))
    print("\nRegex scrubbing is a floor, not a guarantee. Read the output before "
          "trusting it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
