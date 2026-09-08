# Know What You Sign

**Statistical deviation-based risk assessment of legal contract clauses for non-expert signatories.**

Most people sign rental agreements, offer letters and bond clauses they cannot read critically. They are
almost always the party with less bargaining power and no legal training. Professional review costs more
than anyone will pay for a routine six-page agreement, so the document goes unread until a term is enforced.

This tool does not tell you whether your contract is fair. It tells you **which clauses are statistically
unusual, and in whose favour** — and it shows its working for every single flag.

> **Deposit is 6 months' rent.** The median across 312 comparable agreements is 2 months; yours sits at the
> 96th percentile (CI 93–98%). The Model Tenancy Act 2021 s.11(1) suggests a cap of 2 months for homes.
> *Ask whether the deposit can be reduced to 2–3 months.*

## The idea

If a clause type has an observable distribution of terms across a large body of comparable contracts, then a
clause far outside that distribution is *objectively unusual* — and that can be computed, quantified and
explained without a lawyer in the loop.

Five stages: **structure the document → classify each clause → extract the operative numbers → compare
against empirical norms → attribute obligations to parties.**

Two things keep it honest:

- **The direction map** (`config/direction_map.yaml`). Statistics say what is *rare*; a 15-day notice period
  is as rare as a 6-month one. A hand-authored, ~40-line, git-versioned table says which tail is *harmful*
  and to whom. The system learns what is normal from data and declares what is bad in a file you can read
  and argue with.
- **No flag without evidence.** Every finding carries the clause text, the extracted value, the percentile,
  the sample size and the confidence interval. This is enforced in code, not by convention.

**The LLM never decides risk.** Stages 1–7 are deterministic and reproducible. An optional language model is
used only to phrase an already-computed finding in plain English, and it is handed the numbers rather than
the judgement.

## Status

The pipeline runs end to end. What works today:

| Stage | State |
|---|---|
| PDF ingestion, layout, header/footer stripping | working |
| Clause segmentation (numbering + typography) | working |
| Clause classification | rule-based baseline working; transformer training scripted, needs labels |
| Term extraction (₹, lakh/crore, `six (6) months`) | working |
| Norm store, percentiles, bootstrap CIs | working, **needs a corpus** |
| Party resolution and one-sided-duty detection | working |
| Paired asymmetry ("you: 6 months, them: 15 days") | working |
| Missing-clause detection | working |
| Scoring, terminal + HTML report, web UI | working |
| Statutory anchors | wired, **all pending verification** |
| Reference corpus from court judgments | working — 181 judgments harvested |

### Where the norms come from

Executed rental agreements are private and unpublished. Blank templates are published
everywhere and contain `Rs. ______` — no figures to measure. Court judgments sit between the
two: when a tenancy is disputed, the judgment recites the operative terms of the agreement
people actually signed, and judgments are public record.

`scripts/harvest_judgments.py` builds a corpus from them. Current state:

| field | n | median | p25–p75 | usable |
|---|---|---|---|---|
| `security_deposit.deposit_months` | 51 | 6 | 2 – 10.2 | yes |
| `notice_period.notice_months` | 53 | 3 | 3 – 6 | yes |
| `lock_in_period.lock_in_months` | 13 | 24 | — | no (needs 30) |

**The bias, stated in the artefact and in every report built on it:** only *disputed*
tenancies reach court, so this over-represents conflict-prone agreements and probably
harsher-than-average terms. The store carries a `corpus_bias` string that the pipeline
surfaces as a warning — it is not possible to read a report built on this corpus without
being told what it rests on.

Every harvested value records the judgment it came from, so any figure can be checked
against its source.

See [`data/raw/README.md`](data/raw/README.md) for collecting documents directly, and
[`PLAN.md`](PLAN.md) for the full plan, evaluation design and limitations.

## Quick start

```bash
uv venv --python 3.12
uv pip install -e ".[dev]"          # core: parsing, extraction, statistics, CLI
uv pip install -e ".[ml,ui,ocr]"    # add: transformers, Streamlit, OCR

# what can the system currently speak to?
kwys doctor

# try it on the bundled fixture (synthetic demo norms - see the banner)
python scripts/make_demo_norms.py
kwys analyse tests/fixtures/sample_lease.pdf --role tenant --corpus-version SYNTHETIC-DEMO

# inspect what the segmenter and classifier saw, when a report looks wrong
kwys segment tests/fixtures/sample_lease.pdf

# the web interface
streamlit run ui/app.py
```

### Building real norms

```bash
# from published court judgments - no corpus collection needed
python scripts/harvest_judgments.py --pages 5     # polite, cached, respects robots.txt
python scripts/harvest_judgments.py --report      # what was found, and is it enough?
kwys build-norms-from-judgments
kwys analyse agreement.pdf --role tenant --corpus-version judgments-v1

# or, from agreements you have collected yourself
python scripts/fetch_datasets.py                  # LEDGAR + CUAD + InLegalBERT (no API key)
kwys build-norms --corpus data/raw/residential_lease --domain residential_lease
```

### Note on Intel Macs

PyTorch stopped shipping Intel-Mac wheels after 2.2.2, which cascades into pinning
transformers to 4.x and NumPy to 1.x. `pyproject.toml` handles this with environment
markers, so Linux, Colab and Apple Silicon still get current versions. Training is
CPU-only on Intel Macs — fine for a few thousand clauses, too slow for the 80k-provision
LEDGAR stage, which belongs on Colab's free GPU.

## Two programs, not one

| | What it does | Who runs it | How often |
|---|---|---|---|
| `scripts/build_norms.py` | Reads several hundred collected agreements, extracts every deposit / notice period / lock-in, saves the "what is normal" tables | You, the maintainer | Once per corpus version |
| `kwys analyse` / the web app | Compares one person's contract against those saved tables | Anyone | Every use |

## Repository layout

```
kwys/
  ingest/     PDF → text with layout, OCR fallback for scans
  segment/    text → clause tree, by numbering and typography
  classify/   clause → provision type (the only trained model)
  extract/    clause → operative numbers, normalised to canonical units
  norms/      empirical distributions, percentiles, bootstrap CIs
  asymmetry/  who is bound by what; one-sided duties; missing clauses
  score/      deviation + direction + asymmetry → severity + evidence
  report/     plain-language output, clause-anchored
config/
  taxonomy.yaml            clause types and the fields we extract from each
  direction_map.yaml       which tail is harmful, and to whom
  statutory_anchors.yaml   statutory reference points, with citations
data/
  raw/        source documents — NEVER committed
  corpus/     parsed and labelled, DVC-tracked
  norms/      built distributions (regenerable artefact)
  gold/       hand-annotated evaluation sets — NEVER committed
```

## Privacy

Contracts contain names, addresses, salaries and identity numbers. The pipeline runs entirely on your own
machine — no document is sent to any third party, nothing is written to disk during analysis, and no
document content is logged. `data/raw/` and `data/gold/` are excluded from version control at the
repository level, not by habit.

## Scope and limitations

This is a **triage tool, not legal advice.** It measures deviation from observed practice, not legal
validity. An unusual clause may be perfectly lawful; a common clause may be unenforceable. It makes no
determination of enforceability, and that limitation is surfaced to the user rather than buried.

Norms are **descriptive, not normative** — if most agreements in the corpus favour landlords, the system
treats landlord-favourable as normal. Statutory anchors partially correct for this, where they exist.
Coverage is India-specific, metro-weighted, and currently limited to residential leases and employment
offers. Full limitations in [`PLAN.md`](PLAN.md) §8.

## Licence

MIT.
