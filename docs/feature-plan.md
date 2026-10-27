# Feature plan: from diagnosis to action

> **Status (2026-10-27): built.** All eight features are in, with tests in
> `tests/test_features.py` and `tests/test_api.py`. Employment norms: 3 of 4
> fields usable (bond amount is one judgment short of `MIN_N`). Generated Q&A
> answers remain deferred - see "Decision needed later".

Eight features, built on the existing pipeline. The project's rules still hold:
**no flag without evidence**, **no language model decides risk**, and **no
document is stored or sent anywhere**. Each feature below says how it keeps them.

## Foundation (everything else builds on this)

The API currently returns findings only. Several features need more of what the
pipeline already computes:

- `clauses`: id, type, heading, text, and `spans` (page + rectangle) for every
  clause. Needed by the viewer (4), Q&A (5) and compare (3).
- `terms`: every extracted figure, by clause. Needed by costs (1), negotiation
  (2), dates (6) and contributions (9).

Both are derived per request and discarded with it, as now.

## 1. Money exposure calculator

**What:** "If you leave in month _m_, this costs you ₹X", with a slider over the
term, broken into lines: lock-in rent, notice in lieu, deposit held, late fees,
bond repayment.

**How:** `kwys/exposure.py` turns extracted terms into a structured `Exposure`
(rent, deposit, lock-in, notice, term length, escalation, late fee, bond). The
slider arithmetic runs in the browser, so it is instant. Every line names the
clause it comes from; a line whose inputs were not found is omitted, never
guessed.

**Honesty rule:** what the agreement *charges* for leaving early is often not
stated as a number. Lines that depend on a common reading (e.g. "remaining
lock-in rent") are labelled "up to" and say what they assume.

## 2. Negotiation pack

**What:** for each finding, suggested replacement wording; then one polite
message to the other party built from the asks the user ticks, editable,
copyable, downloadable.

**How:** `kwys/negotiate.py`, deterministic templates keyed by field or rule
(notice, deposit, lock-in, late fee, entry, refund, arbitrator, one-sided
duty, bond, non-compete). Target values come from the evidence the finding
already carries: the corpus median or the statutory anchor. No language
model. A finding with no template gets its existing question, never invented
wording.

## 3. Compare two versions

**What:** upload a revised draft from the report; see each term as improved,
worse, unchanged, added or removed, and which findings were resolved or newly
raised.

**How:** `POST /api/compare` takes both PDFs in one request and runs the
pipeline on each. `kwys/compare.py` aligns clauses by type plus text
similarity (difflib, stdlib) and judges each changed figure with the
direction map, the same file that already says which tail hurts whom.

## 4. Clause highlighting in the PDF

**What:** a Document tab showing the user's PDF with flagged clauses
highlighted by severity; clicking a finding jumps to its clause, and clicking
a highlight opens its finding.

**How:** rendered in the browser with `pdfjs-dist` from the file the user
already picked: the PDF is never sent back or kept on the server for this.
Highlights come from the clause `spans` the reader already records.

## 5. Ask the agreement a question

**What:** "Can I sublet?" → the clauses that answer it, highlighted and
cited; or "This agreement does not say", which is often the real finding.

**How:** `POST /api/ask` is stateless: the browser sends the question plus
the clause list it already has. `kwys/ask.py` maps the question to clause
types with the existing keyword classifier, then ranks clauses by BM25. When
nothing scores above a floor, it reports that the agreement is silent.
Fully local; deterministic; answers are always the document's own words.

**Not in this round:** generated prose answers from a language model. That
needs an API key (none is configured) and would send document text to a third
party, which the README promises never happens. See the decision below.

## 6. Key dates

**What:** start, end, lock-in end, last day to give notice, rent increase,
deposit refund due; for jobs, joining, probation end and bond end. Export
as a calendar file (.ics).

**How:** `kwys/extract/dates.py` finds dates in the text ("1st May 2026",
"05/04/2026", "April 5, 2026") with `python-dateutil` (already a dependency);
`kwys/timeline.py` derives the rest from the term, lock-in and notice figures.
Derived dates say what they are derived from. The .ics is generated in the
browser.

## 7. Employment offers, properly

**What:** real comparison data for service bonds, bond amounts, notice periods
and probation, the terms that hurt freshers most.

**How:** generalise the judgment harvester to a second domain: employment-bond
queries, patterns for `bond_amount_inr`, `bond_months`, `notice_months`,
`probation_months`, written to `data/corpus/judgments/employment/`. Build norms
as `judgments-employment-v1` with the same stated bias (only disputed bonds
reach court). Add an employment fixture PDF and tests. Same politeness rules:
robots.txt honoured, 3 s between requests, cached.

## 9. Opt-in shared data

**What:** after a report, an optional panel: "Help others: share these
anonymised figures". It shows exactly what would be sent, and nothing is sent
without a tick and a click.

**How:** `POST /api/contribute` accepts only whitelisted fields (no text, no
names, no clause wording), with values bounds-checked and coarsened (rent to
the nearest ₹1,000, dates dropped, city kept only if in the gazetteer).
Stored in SQLite (stdlib) under `data/contributions/`, which is never
committed. `kwys build-norms-from-contributions` builds a separate corpus
version, `contributed-v1`, labelled as self-reported and unverified, and never
merged with the judgment corpus. Below `MIN_N` it stays unusable, like any
other corpus.

## Requirements check

| Need | Status |
|---|---|
| Clause positions in PDF | ✅ `Clause.spans` already populated by the reader |
| Employment extractors, direction map, anchors | ✅ already in `patterns.py` and config |
| PDF rendering in browser | ✅ `pdfjs-dist` available on npm |
| Judgment source for employment | ✅ indiankanoon.org reachable, robots.txt allows `/doc/` and `/search/` |
| Date parsing | ✅ `python-dateutil` already a dependency |
| Storage for contributions | ✅ SQLite, stdlib; no new service |
| Language-model key for generated Q&A answers | ❌ not configured, and conflicts with the no-third-party promise: **deferred, retrieval-only Q&A built instead** |

## Decision needed later

Generated answers (5) and polished negotiation letters (2) would read better
with a language model. Doing so means sending clause text to an API. If that is
wanted, it should be opt-in per question with a visible notice, and the README's
privacy section changes. Until decided, both features are fully local.

## Build order

1. Foundation: clauses and terms in the API response.
2. Start the employment harvest in the background (it is slow on purpose).
3. Backend modules with tests: exposure, negotiate, dates/timeline, ask,
   compare, contribute.
4. Frontend: report tabs (Findings · Document · Costs · Dates · Ask ·
   Negotiate), compare flow, contribution panel.
5. Employment norms from the finished harvest; employment fixture.
6. Full test run, build, screenshots in light, dark and mobile; README update.
