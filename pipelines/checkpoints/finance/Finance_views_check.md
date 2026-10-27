# Final Checkpoint — Finance_views_check (Agents plan Phase 2, 2026-10-14)

**What it proves:** the 12 views of schema `finance` (migration 013, ADR-047) compute the metrics of
`docs/finance_metrics.md` correctly, and nobody outside Finance (role `employee`) can read them.

| Phase | Step | Result |
|---|---|---|
| 1 | Read the base tables (plain SELECTs) and the 12 views, read-only as `PG_RO_USER` | 1,000 invoices, 994 payments, 40 customers, 676 budget rows, 100 employees; `fact_ar_snapshot` 7,033 rows, `kpi_overdue_list` 1,532 |
| 2 | Recompute every metric in pandas from the base tables (no view SQL) | 52 weeks, 676 week × category, 2,080 week × customer, 1,532 overdue invoice-weeks |
| 3 | Compare views and reference on all 52 weeks (tolerance = one unit of the last rounded digit; NULL = NULL) | 4 KPI views equal; 12 views, every view and column has a COMMENT |
| 4 | Invariants | AR roll-forward, aging = AR, overdue = buckets, Σ categories = total: max diff 0.000; 4 invoices in 2026-W01; warm-up = weeks 1–13; 455 days, 52 weeks |
| 5 | Hand-check weeks 5, 16, 23, 49: arithmetic printed and frozen | owner reviewed 2026-10-14; equal to the first CSV draft |
| 6 | RBAC matrix with `retrieval.allowed()` (ADR-006) and catalog privileges | granted: ceo 1, manager 10, Finance employees 17; denied 72 (all role employee outside Finance); `finance_bi` 12 / 12 views, 0 / 15 tables outside `finance`, write 0 |

## Problems and fixes
- **Cold start:** no 2024 invoices → AR starts at 0 and the 91-day DSO window does not exist before week 14.
  Owner chose the available window with an `is_warmup` flag (P2-2); week 5 DSO uses 33 days.
- **ISO edge:** 4 invoices dated 2025-12-29 / 30 are ISO 2026-W01. Kept outside the report weeks (P2-3) and
  asserted, so the sum of the 52 weeks equals the ISO-2025 invoices.
- **PostGIS catalog objects** (`spatial_ref_sys`, `geometry_columns`, `geography_columns`) are readable by PUBLIC,
  which looked like `finance_bi` reading outside `finance`; they are excluded by name in the check and in
  `verify_readonly.sql` §18.
- **Rounding:** views round once at the end; the reference compares within one unit of the last digit (half-cent
  float ties), and invariants on rounded columns allow n × half a cent.
- First run stopped by design at Phase 5 (snapshot not reviewed); after the owner's review the second run passed
  7 / 7 with `files changed: 0`.
