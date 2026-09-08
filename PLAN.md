# Contract Clause Risk Grader — Implementation Plan

**Statistical Deviation-Based Risk Assessment of Legal Contract Clauses for Non-Expert Signatories**

---

## 0. Scope decisions to make before writing code

Three decisions determine whether this project succeeds. Make them now.

### 0.1 Pick two contract domains, not "contracts"

The norm distribution is only meaningful *within* a comparable population. "Notice period" in an SEC-filed
merger agreement and in a Bengaluru rental agreement are unrelated variables. Recommended scope:

| Domain | Why |
|---|---|
| **Residential rental / lease agreement** (primary) | Highest volume, most standardised, richest quantitative terms (deposit, lock-in, notice, escalation), templates freely available, statutory anchor exists (Model Tenancy Act 2021) |
| **Employment offer letter / appointment letter with bond** (secondary) | Second-highest personal impact, strong quantitative terms (bond amount, bond duration, notice period, non-compete duration) |

Freelance/service and loan agreements are stated as *future work*. Two domains done properly beats six done badly,
and the percentile claim collapses if the corpus is a mixed bag.

### 0.2 The reference corpus is the project — plan for it first

This is the single largest risk. **CUAD and LEDGAR will not give you the norms you need.** They are US
commercial/SEC contracts between institutions. They are still useful (see §3.3) but only for *transfer learning*,
never as the empirical distribution. If you skip this and compute percentiles over LEDGAR, the central claim of
the project is invalid.

Budget **3–4 weeks** for corpus construction. Target **300–500 agreements per domain**; the system is usable at 150.

### 0.3 Deviation ≠ harm. You need a direction map.

A 15-day notice period is as much a statistical outlier as a 6-month one, but it is *favourable* to the tenant.
Percentile alone cannot express risk. You need a small, hand-authored, auditable table:

`(clause_type, signatory_role) → which tail is harmful`

~40 entries. This is expert knowledge and it is unavoidable — but it is *declarative, inspectable, and versioned*,
which is categorically different from the "hand-written expert rules" the proposal rightly criticises. State this
explicitly in the report: the system learns *what is normal* from data and encodes *which direction is bad* as a
reviewable ~40-line table. That is a defensible and honest position.

---

## 1. Architecture

```
PDF/DOCX
   │
   ├─▶ [1] Ingestion & layout ────────▶ text + span coords + font metadata
   │
   ├─▶ [2] Clause segmentation ───────▶ List[Clause{id, number, heading, text, page, bbox}]
   │
   ├─▶ [3] Clause type classification ▶ Clause.type + confidence
   │
   ├─▶ [4] Term extraction ───────────▶ Clause.terms = [{field, raw, value, unit}]
   │        + party/role resolution
   │
   ├─▶ [5] Norm lookup ───────────────▶ percentile, n, CI, statutory anchor
   │        (offline-built norm store)
   │
   ├─▶ [6] Asymmetry + missing-clause ▶ obligation graph, mirror check
   │
   ├─▶ [7] Risk scoring ──────────────▶ severity + evidence object
   │
   └─▶ [8] Report rendering ──────────▶ plain-language HTML/PDF, clause-anchored
```

**Design invariant: the LLM never decides risk.** Stages 1–7 are deterministic and reproducible. An optional LLM
is used only in stage 8 to phrase an already-computed finding in plain English, and it is given the numbers rather
than the judgement. This keeps every flag traceable and is the difference between a research contribution and a
wrapper.

### Repo layout

```
know-what-you-sign/
├── kwys/
│   ├── ingest/          # pdf_reader.py, ocr.py, normalize.py
│   ├── segment/         # numbering.py, headings.py, segmenter.py
│   ├── classify/        # taxonomy.py, train.py, infer.py
│   ├── extract/         # patterns.py, ner.py, normalize_units.py, parties.py
│   ├── norms/           # build_norms.py, store.py, percentile.py, direction_map.yaml
│   ├── asymmetry/       # obligations.py, mirror_table.yaml
│   ├── score/           # scorer.py, weights.yaml
│   ├── report/          # render.py, templates/, explain_llm.py (optional)
│   └── api/             # main.py (FastAPI), tasks.py
├── data/
│   ├── raw/             # source PDFs (gitignored)
│   ├── corpus/          # parsed + labelled parquet (DVC-tracked)
│   ├── norms/           # built distributions (versioned artefact)
│   └── gold/            # hand-annotated eval sets
├── notebooks/
├── tests/
├── ui/                  # streamlit_app.py  (or next/ later)
└── PLAN.md
```

---

## 2. Tech stack

### Recommended stack (and why over the alternative)

| Stage | Recommended | Alternatives considered | Rationale |
|---|---|---|---|
| Language | **Python 3.11** | — | Entire legal-NLP ecosystem |
| Env | **uv** + `pyproject.toml` | conda, poetry | Fast, reproducible; conda if you need system OCR libs pinned |
| PDF text + layout | **PyMuPDF (fitz)** | pdfplumber, pdfminer.six | Fastest, gives per-span font size/weight/bbox — essential for heading detection. Keep `pdfplumber` for table extraction only |
| Scanned PDF | **PaddleOCR** or **Surya**, fallback Tesseract | Tesseract alone, AWS Textract | Modern detectors handle skewed phone photos of agreements far better; Tesseract as offline fallback. Preprocess with OpenCV (deskew, denoise, adaptive threshold) |
| Layout-aware fallback | **Docling** (IBM) | unstructured.io, LayoutParser | Good recovery when numbering is visual rather than textual; use only when rule-based segmentation confidence is low |
| Segmentation | **Rule-based (regex + font features)**, optional line-level BIO tagger later | LLM chunking | Legal numbering is highly regular; rules are auditable and free. Add a small `sklearn`/`sklearn-crfsuite` line classifier only if rules stall below ~0.9 F1 |
| Clause classification | **InLegalBERT** (`law-ai/InLegalBERT`) primary; **Legal-BERT** (`nlpaueb/legal-bert-base-uncased`) and **DeBERTa-v3-base** as baselines | GPT-style zero-shot | InLegalBERT is pretrained on Indian legal text — directly relevant. Report all three in the paper; this *is* an ablation |
| Training | **HF `transformers` + `datasets` + `accelerate`**, PEFT/LoRA if GPU-poor | PyTorch Lightning | Standard, well documented; Colab/Kaggle T4 is enough for base-size encoders |
| Long clauses | Sliding-window 512 + max-pool, or **Longformer** for the tail | truncation | Indemnity/termination clauses routinely exceed 512 tokens; naive truncation silently drops the operative sentence |
| Term extraction | **spaCy 3.x** (`en_core_web_trf`) + `EntityRuler`/`Matcher` + custom regex, plus a fine-tuned token classifier for hard fields | pure regex, pure LLM | Hybrid wins: regex nails `₹`/`Rs.`/lakh/crore/`six (6) months`; the tagger catches the rest |
| Number/date normalisation | `dateparser`, `word2number`, custom Indian-numeral parser (lakh/crore) | — | You must normalise to canonical units (months, INR) before any percentile is meaningful |
| Embeddings (non-quantitative clauses) | **sentence-transformers** — `all-mpnet-base-v2` baseline, fine-tuned InLegalBERT-ST preferred | OpenAI/Voyage embeddings | Local, free, no data leaves the machine (contracts are sensitive) |
| Statistics | `numpy`, `scipy`, `pandas`, `statsmodels` | — | Empirical CDF, bootstrap CIs, robust stats (median/MAD), KDE |
| Outlier detection | `scikit-learn` (LOF, IsolationForest) for embedding-space outliers | — | Only as a secondary signal, always gated (§5.3) |
| Corpus storage | **Parquet** + **DuckDB** for analytics; **SQLite** for app state | Postgres | Zero-ops, fast, portable; move to Postgres only if you deploy multi-user |
| Data versioning | **DVC** (or plain `git-lfs` + a manifest) | — | Norms must be reproducible from a corpus snapshot; this is a stated research claim |
| Experiment tracking | **Weights & Biases** free tier, or MLflow local | — | You will run many classifier variants; log them |
| Backend | **FastAPI** + **Celery/RQ + Redis** for async OCR jobs | Flask | OCR of a 20-page scan takes 30–90s; you need a job queue, not a blocking request |
| UI (MVP / demo) | **Streamlit** | — | Fastest path to a working demo and screenshots for the report |
| UI (if productionising) | **Next.js + React + Tailwind**, `react-pdf` for clause highlight overlay | — | Only if you have time after the core works |
| Report export | **WeasyPrint** or `pdfkit` | — | HTML → PDF, keeps clause anchors |
| Optional plain-language layer | **Anthropic Python SDK** (`anthropic`), model `claude-opus-5` (or `claude-haiku-4-5` at $1/$5 per MTok if cost-sensitive) | local Llama/Mistral | Only rewrites a computed finding into plain English; must be off by default and clearly disclosed, since it sends clause text off-device |
| Testing | `pytest`, `hypothesis` for the unit-normalisation code | — | Unit parsing is where silent bugs live |
| Packaging | **Docker** (OCR + fonts baked in) | — | OCR deps are the classic "works on my machine" trap |

### What to deliberately *not* use
- **No LLM as the risk judge.** It destroys explainability and the novelty claim.
- **No cloud OCR for the default path.** Contracts contain names, addresses, salaries, PAN/Aadhaar numbers.
- **No synthetic data in the norm distributions.** Generating fake rental agreements to pad the corpus and then
  computing percentiles over them is circular. Synthetic data is acceptable *only* for augmenting classifier
  training, and must be disclosed.

---

## 3. Data plan (do this first — weeks 1–4)

### 3.1 Corpus sources (rental, India)

| Source | Expected yield | Notes |
|---|---|---|
| Public template/e-stamp sites (LegalDesk, Vakilsearch, NoBroker, Housing, 99acres, state e-stamp portals) | 150–250 | Templates, so the *modal* terms; scrape respectfully, record provenance and licence |
| State property-registration portals publishing registered lease deeds | 50–150 | Real executed agreements — the most valuable subset. Availability varies by state; check Karnataka/Maharashtra/Delhi portals |
| Donated real agreements (peers, hostel/PG contracts, family) | 50–100 | **Highest research value.** Get written consent, redact PII on ingest with a PII scrubber (spaCy NER + regex for PAN/Aadhaar/phone/email) |
| Legal-aid and consumer-forum published specimens | 20–50 | Often the pathological examples — good for the eval set |

Employment: offer-letter templates from HR sites, company career pages, public appointment-letter formats,
plus donated (redacted) offer letters.

### 3.2 Statutory anchors — a second, independent axis

Encode a small YAML of statutory/regulatory reference points. This makes a flag far stronger than percentile alone.

```yaml
residential_lease:
  security_deposit_months:
    anchor: 2          # Model Tenancy Act 2021 §11(1) — residential
    source: "Model Tenancy Act, 2021, s.11(1)"
  deposit_refund_days:
    anchor: 30
    source: "Model Tenancy Act, 2021, s.11(3)"
```

Output becomes: *"Deposit is 6× monthly rent. 88% of sampled agreements are ≤3×, and the Model Tenancy Act 2021
suggests a cap of 2× for residential tenancies."* Two independent forms of evidence, both citable.

Note in the report that the Model Tenancy Act is a model law adopted by some states only — do not overstate it.

### 3.3 Where CUAD / LEDGAR actually fit

- **LEDGAR** (~850k provisions, 100-label subset): pretraining / intermediate fine-tuning for the clause
  classifier. Train on LEDGAR, then fine-tune on your ~2,000 hand-labelled domain clauses. This is a real,
  reportable transfer-learning result.
- **CUAD** (510 contracts, 41 clause types with character spans): supervision signal for span-level extraction
  and for the termination/indemnity/governing-law heads.
- **ContractNLI**: useful if you add the "does this contract permit X?" question layer later.

Say plainly in the paper: *these corpora supply linguistic transfer, not norms.*

### 3.4 Annotation plan

| Set | Size | Labels | Who |
|---|---|---|---|
| Segmentation gold | 30 docs | clause boundaries | You |
| Classification train | ~2,000 clauses | 14-type taxonomy | You + 1 peer, measure κ on a 200-clause overlap |
| Extraction gold | 500 clauses | field spans + normalised values | You |
| **End-to-end risk gold** | 40 contracts | per-clause: would a lawyer flag this? severity 0–2 | **2 law students / a lawyer** — this is your ground truth, protect it, never train on it |

Tooling: **Label Studio** (self-hosted, supports PDF/text spans and classification in one project) or **doccano**
if you want something lighter.

### 3.5 Clause taxonomy (start here, ~14 types)

`rent_and_escalation`, `security_deposit`, `deposit_refund`, `lock_in_period`, `notice_period`,
`termination`, `maintenance_and_repairs`, `use_restrictions`, `entry_and_inspection`, `subletting`,
`penalty_and_late_fee`, `dispute_resolution_arbitration`, `governing_law_jurisdiction`, `indemnity`,
plus `other`. Employment adds `bond_and_recovery`, `non_compete`, `confidentiality`, `probation`, `ip_assignment`.

Map each to LEDGAR labels where one exists so transfer learning has a bridge.

---

## 4. Stage implementation notes

### Stage 1 — Ingestion
- `fitz` → per-page list of spans `{text, bbox, font, size, flags}`. Keep coordinates: the report highlights the
  clause in the original PDF, which is what makes the output trustworthy to a user.
- Scanned detection: page has <50 extracted characters but non-trivial image area → OCR route.
- Ligature/hyphenation repair, header/footer stripping (repeated y-position lines across pages), de-column.
- PII scrub happens here for anything entering the corpus (never for the user's own live upload — that stays in memory).

### Stage 2 — Segmentation
Cascade, most reliable first:
1. Hierarchical numbering regex: `^\s*(\d+(\.\d+)*)[.)]\s`, `^\s*\(?([a-z]|[ivx]+)\)`, `^\s*(ARTICLE|CLAUSE|SECTION)\s+[IVX\d]+`
2. Typographic headings: font size > body median, or bold, or ALL CAPS short line
3. Fallback: blank-line paragraph blocks
Build a tree (clause → sub-clause), and carry the parent heading into the child's classification context —
sub-clause `4.3` alone is often meaningless without "4. TERMINATION".
- **Confidence signal:** if <60% of blocks matched a numbering pattern, mark the doc `low_structure` and warn the
  user rather than silently producing garbage.

### Stage 3 — Classification
- Input: `parent_heading [SEP] clause_text`. This one trick is worth several F1 points.
- Two-stage training: LEDGAR (100 labels) → domain head (15 labels).
- Calibrate with temperature scaling; abstain to `other` below threshold. An abstention is honest; a wrong type
  produces a wrong norm lookup, which is worse than no flag.
- Report macro-F1 and the confusion matrix; termination↔notice and deposit↔refund will be your hard pairs.

### Stage 4 — Term extraction + parties
- **Fields per clause type** (declared in YAML): e.g. `security_deposit → {amount_inr, months_of_rent}`,
  `notice_period → {duration_months, bound_party}`, `dispute_resolution → {seat_city, institution}`.
- Regex first (`₹`, `Rs.`, `INR`, `lakh`, `crore`, `\d+\s*(days|months|years)`, `six \(6\) months`), token
  classifier for the residue.
- **Normalise everything**: months, INR, % — and derive ratios (`deposit ÷ monthly rent`) which are far more
  comparable across cities than raw amounts. Ratios are what you should build norms over.
- **Party resolution:** parse the preamble/definitions ("hereinafter referred to as the 'Lessee'"), build an
  alias map {Lessee, Tenant, Party of the Second Part} → role, then resolve pronouns/definite descriptions within
  clauses. Ask the user once at upload: *"which side are you?"* — the entire risk direction depends on it.
- **Geographic term:** for arbitration seat / exclusive jurisdiction, geocode the named city against the
  property/employment city (offline gazetteer + `geopy` distance). Distance in km is a genuinely quantitative,
  objective measure of enforcement burden — a strong, novel feature.

### Stage 5 — Norm store
Built offline, versioned as an artefact:
```
norms/v1/{domain}/{clause_type}/{field}.json
  { "n": 312, "values": [...], "median": 2.0, "mad": 0.5,
    "ecdf_x": [...], "ecdf_y": [...], "p05": 1, "p95": 6,
    "corpus_hash": "...", "built_at": "...", "sources": {...} }
```
- Percentile via empirical CDF with midpoint interpolation for ties.
- **Bootstrap CI on the percentile** (1,000 resamples). Report it.
- **Suppress the percentile claim when `n < 30`** and fall back to "insufficient reference data — flagged for
  attention only". Overclaiming on thin data is the easiest way to lose credibility in the viva.
- Stratify where you have the volume (city tier, residential vs commercial); fall back to the pooled distribution
  and say so.

### Stage 6 — Asymmetry + missing clauses
- **Obligation graph:** dependency parse each sentence; find deontic modals (`shall`, `must`, `shall not`,
  `is required to`, `may`); attach to the resolved subject role; classify as obligation / right / prohibition.
  Emit tuples `(role, modality, predicate, clause_id)`.
- **Mirror table** (YAML): clause types that *should* be reciprocal — termination right, notice period, indemnity,
  cure period, entry rights. If a duty exists for role A with no counterpart for role B → asymmetry flag.
- **Missing-clause detection** (worth calling out as a contribution — absence is invisible to a lay reader):
  expected clause set per domain minus observed set. "This agreement specifies no timeline for deposit refund;
  94% of comparable agreements do." Absence of a protective term is a risk the user cannot possibly notice.

### Stage 7 — Scoring
See §5.

### Stage 8 — Report
- Sorted findings, each rendering: clause text (with the operative span highlighted), extracted term, the
  distribution plot with the user's value marked, the statutory anchor if any, the plain-language sentence,
  and **a concrete question to ask the counterparty** ("Ask whether the deposit can be reduced to 2 months and the
  refund window fixed at 30 days"). Converting a flag into a *negotiable ask* is the actual user value.
- Persistent, prominent disclaimer: triage, not legal advice; no view on enforceability.

---

## 5. The risk model (write this section into your paper carefully)

For clause `c`, type `t`, field `f`, user role `r`, value `x`, reference sample size `n`:

**5.1 Quantitative deviation**
```
p  = ECDF_t,f(x)                       # empirical percentile
d  = direction_map[t][f][r] ∈ {+1,-1}  # +1 ⇒ larger is worse for r
q  = p if d = +1 else (1 - p)          # harm-side percentile
w  = n / (n + k),  k = 30              # shrinkage on thin data
q̂  = 0.5 + w·(q - 0.5)                 # shrunk toward "neutral"
z  = d·(x - median_t,f) / (1.4826·MAD_t,f)   # robust effect size, reported alongside
```
Also compute `a = x / statutory_anchor` where an anchor exists; report both signals independently rather than
blending them — they are different kinds of evidence.

**5.2 Non-quantitative deviation**
```
u = percentile of cosine distance from centroid of type-t clause embeddings
```
**Gate it.** Semantic unusualness alone is not risk (an unusually *tenant-friendly* clause is also far from the
centroid). Only surface it when at least one of: an asymmetry flag on the same clause, an obligation on the user's
role with no reciprocal, or a weakly-supervised "onerous term" classifier fires. Be explicit in the write-up that
this is the weakest leg of the method — that honesty is worth more than a fragile claim.

**5.3 Composite**
```
severity = clip( w_q·q̂ + w_a·A + w_m·M + w_u·(u·gate) , 0, 1 )
buckets:  ≥0.75 High │ 0.45–0.75 Medium │ <0.45 Low (not shown by default)
```
Weights live in `weights.yaml`, are fixed and documented, and are tuned **once** on a dev split of the gold set —
never on the test split. Report sensitivity of final precision/recall to the weights; a system whose output swings
wildly with weights is not making an objective claim.

**5.4 Evidence object** — every finding carries, and the UI shows:
```json
{"clause_id":"4.2","type":"security_deposit","field":"months_of_rent",
 "value":6.0,"percentile":0.96,"ci":[0.93,0.98],"n":312,
 "median":2.0,"direction":"higher_is_worse_for_tenant",
 "statutory_anchor":{"value":2,"source":"Model Tenancy Act 2021 s.11(1)"},
 "severity":0.82,"bucket":"High"}
```
No flag without a populated evidence object. Enforce this in code — it is the project's core discipline.

---

## 6. Evaluation

| Component | Metric | Target | Data |
|---|---|---|---|
| Text extraction | CER on scanned set | <5% | 20 scans with manual transcript |
| Segmentation | boundary F1 (±1 line tolerance) | ≥0.90 | 30 gold docs |
| Classification | macro-F1 (15 classes) | ≥0.85 | held-out 20% |
| " (ablation) | InLegalBERT vs Legal-BERT vs DeBERTa vs TF-IDF+SVM | — | same split |
| " (ablation) | with vs without LEDGAR pretraining | — | same split |
| Extraction | normalised-value accuracy per field | ≥0.90 | 500 gold clauses |
| Party attribution | role-assignment accuracy | ≥0.85 | 300 obligations |
| **End-to-end** | **precision / recall / F1 vs lawyer-flagged clauses** | **P≥0.70, R≥0.75** | **40-contract gold set** |
| " | precision@5 (do the top 5 flags matter?) | ≥0.80 | same |
| Annotator agreement | Cohen's κ between the two annotators | ≥0.6 | 40-contract overlap |
| Robustness | flag stability under paraphrase / OCR noise injection | — | perturbed subset |
| **User study** | comprehension pre/post, time-to-locate-risk, SUS | — | 15–20 non-experts, 2 contracts each |

Recall is more important than precision here — a missed onerous clause is the failure mode that hurts the user.
Tune the operating point accordingly and justify it.

Baselines to beat (needed for any paper): (a) keyword/rule-based flagging, (b) zero-shot LLM prompt "list the risky
clauses", (c) TF-IDF + SVM classifier with fixed thresholds. Beating (b) on *explainability and consistency* even
where F1 is comparable is a legitimate and defensible result — measure run-to-run variance of the LLM baseline;
it will be poor, and that instability is your argument.

---

## 7. Timeline (14 weeks)

| Wk | Work | Deliverable / go-no-go |
|---|---|---|
| 1 | Scope lock, taxonomy v1, repo + CI + Docker skeleton | Taxonomy YAML, running skeleton |
| 2–4 | **Corpus construction** (scraping, consent, PII scrub, provenance log) + Label Studio setup | ≥200 rental docs parsed. **Gate: if <150, cut to one domain** |
| 3–4 | Stage 1 + 2 (ingestion, OCR, segmentation) in parallel with corpus work | Segmentation F1 ≥0.90 on gold |
| 5 | Annotate 2,000 clauses (you + peer), κ check | Labelled train set |
| 6–7 | Stage 3 classifier: LEDGAR pretrain → domain fine-tune, 3-model ablation | macro-F1 ≥0.85, W&B runs logged |
| 8 | Stage 4 extraction + unit normalisation + party resolution | Field accuracy ≥0.90 |
| 9 | Stage 5 norm store, direction map, statutory anchors, bootstrap CIs | `norms/v1` artefact, distribution plots |
| 10 | Stage 6 asymmetry + missing-clause detection | Obligation tuples on 30 docs |
| 11 | Stage 7 scoring + weight tuning on dev split | Evidence objects end-to-end |
| 12 | Stage 8 report UI (Streamlit), PDF export, disclaimers | Working demo |
| 13 | **Evaluation**: gold-set eval, baselines, ablations, user study | Results tables |
| 14 | Paper/report, error analysis, limitations, demo video | Submission |

Parallelisable: corpus work (weeks 2–5) is independent of pipeline work (weeks 3–4, 6–8) — if working in a team,
split along that line. If solo, the corpus is the critical path; start it week 1, not week 3.

---

## 8. Known limitations to state up front (do not let a reviewer find these first)

1. **Norms are descriptive, not normative.** If 90% of agreements in the corpus are landlord-favourable, the
   system will treat landlord-favourable as normal. Mitigate by pairing every percentile with the statutory anchor
   where one exists, and say this explicitly.
2. **Template bias.** A corpus dominated by online templates measures what template vendors publish, not what
   people actually sign. Report the template/executed/donated split of your corpus and, where possible, compare
   the two distributions — that comparison is itself an interesting result.
3. **Direction map is expert knowledge.** ~40 entries, hand-authored. Declared, versioned, inspectable — but not
   learned. Own it rather than hiding it.
4. **No enforceability judgement.** An unusual clause may be perfectly lawful; a common clause may be void. The
   system measures deviation, not validity.
5. **Jurisdiction.** Norms are India-specific and largely metro-weighted. Do not claim generality.
6. **Semantic-outlier leg is weak** relative to the quantitative leg. Report its contribution separately in the
   ablation so a reader can see how much of the performance is carried by the solid part.

---

## 9. First week, concretely

1. `uv init`, add `pymupdf pdfplumber spacy transformers datasets torch sentence-transformers scikit-learn pandas numpy scipy duckdb pyyaml pytest streamlit fastapi`; `python -m spacy download en_core_web_trf`.
2. Write `kwys/ingest/pdf_reader.py` and run it over 10 agreements you can find today. Look at the raw output.
3. Write `taxonomy.yaml`, `direction_map.yaml`, `statutory_anchors.yaml` — all three by hand, ~150 lines total.
   Doing this early forces the scope decisions and exposes vagueness before any model is trained.
4. Start the corpus scrape. Log provenance (URL, date, licence) per document from the very first file — retrofitting
   provenance across 400 documents is miserable, and you will need it for the ethics/data statement.
