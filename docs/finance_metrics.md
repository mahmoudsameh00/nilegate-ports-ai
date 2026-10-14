# Finance metrics — definitions of the Weekly Finance Pack

One definition per metric, computed **only** in the SQL views of schema `finance` (migration 013, Agents plan Phase 2,
owner decisions P2-1…P2-9 of 2026-10-14). Power BI (DirectQuery) and the agent tools read these views; DAX measures
stay simple sums / selections of the view columns, and no tool recomputes a KPI. Money in SDR (ADR-003). Access:
level 2 / Finance (`docs/rbac_mapping.md`, ADR-006).

## Conventions

| Item | Rule |
|---|---|
| Report week | `report_week` 1–52 = the ISO-8601 weeks of 2025 (D12), Monday → Sunday. Week 1 = 2024-12-30 → 2025-01-05; week 52 = 2025-12-22 → 2025-12-28. |
| "As of" a week | As of its **Sunday 23:59**: an invoice issued on that Sunday is open; a payment dated that Sunday is received. |
| ISO edge | 2025-12-29 … 31 belong to ISO **2026-W01**: the 4 invoices dated 2025-12-29 / 30 are in `fact_invoice` (`invoice_report_week` NULL) but in no report week. |
| Due date | `invoice_date + customers.payment_terms_days` (derived, not stored; ADR-046). |
| Payment state | From `payments` only (one full payment per paid invoice). `invoices.status` is a random label and is **never used** (ADR-046). |
| History start | 2025-01-01: there are no 2024 invoices, so receivables start at 0. **Warm-up weeks 1–13** (`is_warmup = true`) have fewer than 91 days of history (P2-2). |
| Rounding | Once, at the end of each KPI view: money 2 decimals, `*_pct` in percent with 2 decimals, days 1 decimal (P2-9). Sums are taken over unrounded values. |
| NULL | WoW is NULL in week 1 and when the previous value is 0 (no division by zero, no invented 100 %). |

## Definitions

| # | Metric | Definition | View . column |
|---|---|---|---|
| M1 | Billed revenue | Σ `amount` of the invoices whose `invoice_date` is in the week (Mon–Sun) | `kpi_weekly.billed_sdr`, `invoices_billed`; per category `kpi_weekly_category.billed_sdr` |
| M2 | Collections | Σ `payments.amount_sdr` whose `paid_date` is in the week | `kpi_weekly.collected_sdr`, `payments_received` |
| M3 | Accounts receivable (AR) at week end | Σ amount of the invoices with `invoice_date ≤ Sunday` and (no payment or `paid_date > Sunday`). Identity: AR(w) = AR(w−1) + billed(w) − collected(w) | `kpi_weekly.ar_sdr`, `ar_invoices`; rows `fact_ar_snapshot` |
| M4 | AR aging | Days past due = Sunday − due date. Buckets: **current** (≤ 0), **1–30**, **31–60**, **61–90**, **90+**; Σ buckets = AR | `kpi_weekly.aging_*_sdr`; `fact_ar_snapshot.aging_bucket` |
| M5 | Overdue | Open invoices with days past due ≥ 1 (= the four overdue buckets); the list ranked by amount | `kpi_weekly.overdue_sdr`, `overdue_invoices`; `kpi_overdue_list` |
| M6 | DSO | **AR at week end ÷ billed revenue in the DSO window × window days.** Window = the 91 days ending Sunday (13 weeks); in warm-up weeks it starts 2025-01-01 and is shorter (week 5: 33 days) (P2-1, P2-2) | `kpi_weekly.dso_days`, `dso_window_days`, `dso_window_billed_sdr`; `dim_week.dso_window_start` |
| M7 | Top customers | Billed revenue per customer in the trailing 13 weeks (91 days ending Sunday), ranked (ties by `customer_id`); rank of the previous week for "changes" | `kpi_customer_13w.billed_13w_sdr`, `rank_13w`, `rank_13w_prev`, `share_13w_pct` |
| M8 | Concentration | Share of the top-10 customers in the trailing 13 weeks' billing (only customers with billing > 0 count) | `kpi_weekly.top10_share_13w_pct`; `kpi_customer_13w.is_top10` |
| M9 | Budget variance | Absolute = billed − budget; % = (billed − budget) ÷ budget × 100; company total and per vessel category | `kpi_weekly.budget_variance_sdr` / `_pct`; `kpi_weekly_category.budget_variance_*` |
| M10 | Week-over-week | (this week − previous week) ÷ previous week × 100, for billed, collected, AR, overdue; DSO as a difference in days; per category also the absolute change (the week's drivers = largest \|change\|) | `kpi_weekly.*_wow_pct`, `dso_wow_days`; `kpi_weekly_category.billed_wow_change_sdr`, `billed_wow_pct` |
| M11 | 13-week trend | The rows of `kpi_weekly` for weeks w−12 … w (fewer at the start of the year); no separate view | `kpi_weekly` filtered |

Why a 13-week window for customers: a week has about 19 invoices, so a single week's "top 10" is almost every
customer billed that week and its share means nothing.

### Deferred / rejected alternatives

- **DSO count-back** (walk back through daily revenue until AR is used up): more exact with lumpy revenue, but harder
  to explain and to check by hand; on weeks 14–52 it differs from M6 by −7.9 … +8.8 days. Deferred (P2-1).
- Warm-up weeks as NULL DSO or a report window of weeks 14–52: rejected by the owner (P2-2) — every week is reported,
  with `is_warmup` to say the receivables are still building up.
- KPI functions `kpi_*(report_week)`: rejected (P2-4) — one view per KPI serves Power BI and the tools with the same
  number; the tool filters `WHERE report_week = %s`.

## Hand-checked weeks (P2-7)

Computed three times — a pandas draft from the CSV mirrors, an independent pandas reference from the base tables
(`pipelines/scripts/finance/Finance_views_check.py`), and the SQL views — and equal on all 52 weeks; the four weeks
below are frozen as a reviewed snapshot (owner, 2026-10-14). SDR.

| | Week 5 (warm-up) | Week 16 (quietest) | Week 23 (peak) | Week 49 (clean test week) |
|---|---:|---:|---:|---:|
| Period | 01-27 → 02-02 | 04-14 → 04-20 | 06-02 → 06-08 | 12-01 → 12-07 |
| M1 billed | 6,902,530.53 (21) | 2,934,677.21 (11) | 8,394,785.98 (29) | 4,056,397.94 (19) |
| M2 collected | 1,411,387.40 (5) | 4,005,943.10 (13) | 5,263,662.35 (15) | 4,029,984.17 (14) |
| M3 AR = prev + M1 − M2 | 16,611,981.14 + … = 22,103,124.27 | 39,670,822.56 + … = 38,599,556.67 | 44,499,856.06 + … = 47,630,979.69 | 38,141,948.50 + … = 38,168,362.27 |
| M4 current / 1–30 / 31–60 / 61–90 / 90+ | 21,988,511.40 / 114,612.87 / 0 / 0 / 0 | 28,348,699.74 / 7,149,749.75 / 3,101,107.18 / 0 / 0 | 35,079,356.53 / 9,617,968.47 / 1,604,150.66 / 442,302.33 / 887,201.70 | 30,097,966.10 / 4,299,647.40 / 2,333,087.97 / 151,558.65 / 1,286,102.15 |
| M5 overdue | 114,612.87 (1) | 10,250,856.93 (32) | 12,551,623.16 (42) | 8,070,396.17 (27) |
| M6 DSO | 22,103,124.27 ÷ 23,514,511.67 × 33 = 31.0 | ÷ 67,895,115.94 × 91 = 51.7 | ÷ 69,692,545.51 × 91 = 62.2 | ÷ 64,782,666.48 × 91 = 53.6 |
| M8 top-10 share | 62.58 % | 56.89 % | 59.46 % | 60.36 % |
| M9 vs budget | +1,387,866.70 (+25.17 %) | −2,705,116.76 (−47.96 %) | +2,629,861.85 (+45.62 %) | −1,887,283.50 (−31.75 %) |
| M10 billed WoW | +24.03 % | −22.10 % | +25.83 % | −43.08 % |

Known facts of the data (not errors): the weekly budget variance swings widely (≈ 19 invoices a week) and the
budget is above actual billing by ≈ 11 % over the year (ADR-046, the laden-tonnage planning assumption).
