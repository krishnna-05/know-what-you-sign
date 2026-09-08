# Reference corpus — collected agreements

**Nothing in this directory is committed.** `.gitignore` excludes it at the
repository level, not by habit, because these files contain real people's names,
addresses, salaries and identity numbers.

## What goes here

Real agreements of the kind the tool analyses. For `residential_lease` that
means actual Indian residential rental agreements — not templates you wrote, not
synthetic documents, not US contracts.

This is the only part of the project that cannot be downloaded, generated or
substituted. `kwys build-norms` reads this directory; without it, every
deviation claim is suppressed and the tool can only report one-sided
obligations and missing clauses.

## Target

| Domain | Minimum useful | Target | Why |
|---|---|---|---|
| `residential_lease/` | 150 | 300–500 | Below ~30 per FIELD the store refuses to assert a percentile, and not every document states every field |
| `employment_offer/` | 150 | 300–500 | Same |

A document that mentions only rent and deposit contributes to two fields, not
fifteen. Plan for roughly 2–3× more documents than you think you need.

## Where to get them

Ordered by effort, and inversely by value.

**Easy — template sites.** NoBroker, Housing.com, LegalDesk, Vakilsearch,
99acres, state e-stamp portals. Expect 150–250. Scrape politely: respect
`robots.txt`, rate-limit, and record the URL and date for every file.

**Medium — registration portals.** Some state property-registration portals
publish registered lease deeds. Far more valuable than templates because they
are what people actually signed. Availability varies by state; Karnataka,
Maharashtra and Delhi are worth checking first.

**Hardest, most valuable — donated documents.** Friends in rented flats, hostel
and PG agreements, relatives, your college's own accommodation contracts. Ask
early: replies trickle in over weeks. These are the only documents that reflect
what ordinary people are actually handed.

## Before a donated document goes in this folder

1. **Get permission in writing.** A WhatsApp message saying "yes, you can use
   this for your project" is enough. Keep it.
2. **Scrub it.** `python scripts/scrub_pii.py <file>` removes names, phone
   numbers, emails, PAN, Aadhaar, GSTIN, account and IFSC numbers. It is
   regex-based and therefore a floor, not a guarantee — **read the output.**
3. **Record where it came from** in `provenance.json` (below).

## provenance.json

Keep this from the very first file. Retrofitting provenance across 400
documents is miserable, and you need it for three separate reasons: the data
statement in your report, the template-vs-executed split (which is itself a
reportable result — the two populations have different distributions), and
being able to drop a source later if its licence turns out to be wrong.

```json
{
  "lease_0001.pdf": {
    "source": "template",
    "origin": "https://example.com/rental-agreement-format",
    "collected_on": "2026-09-08",
    "licence": "public template, no stated restriction",
    "city": "Bengaluru",
    "state": "Karnataka",
    "consent": null,
    "scrubbed": true
  },
  "lease_0002.pdf": {
    "source": "donated",
    "origin": "personal contact",
    "collected_on": "2026-09-12",
    "licence": "consent given for research use",
    "city": "Chennai",
    "state": "Tamil Nadu",
    "consent": "whatsapp 2026-09-12",
    "scrubbed": true
  }
}
```

`source` should be one of `template`, `registered`, `donated`, `specimen`.
`kwys build-norms` reads it and records per-field source counts in the norm
store, so a distribution built entirely from vendor templates is visible as
such rather than silently passing as representative.

## Layout

```
data/raw/
  provenance.json
  residential_lease/
    lease_0001.pdf
    ...
  employment_offer/
    offer_0001.pdf
    ...
```
