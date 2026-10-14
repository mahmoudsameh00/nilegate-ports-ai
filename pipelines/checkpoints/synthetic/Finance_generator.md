### Final Checkpoint — what was done, what went wrong, how it was fixed

| Phase | What | Problem found | Fix / consequence |
|---|---|---|---|
| 0 | Rules §4a R1–R10 written and approved before any code (D6) | The stored `invoices.status` is a random label: 689 of 1,000 not Paid, evenly over the quarters; payments "consistent with the status" would give DSO ≈ 250 days | Owner: payments follow terms and behaviour; the status is kept unchanged (ADR-013) and documented as a label by migration 012; label vs derived agree on 379 / 1,000 (reported). |
| 1 | Inputs (read-only PG): 500 vessels, 1,000 invoices, the bands; 13 categories → 6 segments | Faker draws differ between Windows and Linux (ROADMAP known issue) | Names from invented stems + `numpy.default_rng([42, phase])`: identical on every OS; one stream per phase. |
| 2 | 40 customers: segment, HQ country, terms, rating; behaviour in the manifest only | A behaviour column would hand the Insight agent the answer | Not stored (R3); rating correlates (prompt → 9 A, late / disputer → all C). |
| 3 | Vessel → customer by Zipf weights inside each segment | — | Top-10 customers 57.0 % of 2025 billing; 1–70 vessels per customer (median 9). |
| 4 | Payments: due = date + terms, delay by behaviour, horizon 2026-03-31 | Paid on or before due only 36 % (the "normal" range −3…+10) | Owner kept it. DSO 55 days; 150 invoices (40.2 M SDR) open at 2025-12-31; 6 unpaid at the horizon. |
| 5 | Weekly budget: fleet × 2.0 transits × median-tonnage laden toll, seasonal ±6 % | — | 302.1 M budget vs 267.9 M actual (−11.3 %): the plan assumes laden transits — a real, explainable variance. |
| 6 | Evaluation copy: 4 golden weeks, 5 planted errors + a budget miss, week 49 clean | A `test_case` column (R7 as written) would show the Auditor the answer | No label column (owner); labels in the answer key and the manifest. |
| 7 | 6 CSVs + manifest + answer key + migration 012 (one transaction, 26 comments, grants) | — | Reload equal; a second run with another hash seed: 0 files changed. Migration applied by the owner; `verify_readonly.sql` §17. |
