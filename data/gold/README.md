# Gold evaluation set

**Never committed. Never trained on. Touched once, at the end.**

40 contracts, each annotated by someone with legal training — a law student or a
lawyer — marking which clauses they would flag and how seriously. This is the
ground truth the whole evaluation rests on (PLAN.md section 6).

## Why it must stay separate

Every other dataset in this project feeds the system. This one judges it. If you
tune weights, thresholds or rules while looking at these documents, the reported
precision and recall become meaningless — you will have fitted the evaluation.

Split it: use a dev portion for tuning `config/weights.yaml`, keep a test
portion sealed until the final run.

## Annotation format

One JSON file per contract:

```json
{
  "document": "gold_007.pdf",
  "domain": "residential_lease",
  "signatory_role": "tenant",
  "annotator": "annotator_a",
  "annotated_on": "2026-11-14",
  "clauses": [
    {"clause_id": "2.2", "would_flag": true,  "severity": 2,
     "note": "six months deposit, well above market"},
    {"clause_id": "2.4", "would_flag": false, "severity": 0, "note": ""}
  ]
}
```

`severity`: 0 = fine, 1 = worth raising, 2 = would advise against signing as drafted.

## Two annotators, not one

Have both annotate the same 40 contracts and report Cohen's κ. A κ below about
0.6 means the annotators do not agree on what "risky" means, and no score
measured against that set can be trusted. That is a finding in itself and
belongs in the write-up.

## Ask early

You need these people in roughly week 13. People say yes slowly. Start asking
your college's law department, friends doing LLB, and family contacts in week 1.
