---
name: finance-kpi-definitions
description: What each weekly finance KPI of NileGate means, which finance_kpi dataset and field holds it, and the reporting conventions (report week, as-of Sunday, warm-up weeks, rounding). Load before reading or explaining any finance number.
stage: 1
reviewed_by_owner: 2026-10-19
---
# Finance KPI definitions (source of truth: docs/finance_metrics.md)

Every KPI is computed once, in the SQL views of schema `finance`. You **never recompute** a KPI: call `finance_kpi`
and use the field it returns. The Power BI dashboard shows the same numbers.

## Conventions
- **Report week** 1–52 = ISO weeks of 2025 (Monday–Sunday). Week 1 = 2024-12-30 → 2025-01-05; week 52 ends
  2025-12-28. 2025-12-29…31 belong to 2026-W01 and are in no report week.
- **As of** Sunday 23:59 of the week: an invoice issued that Sunday is open; a payment dated that Sunday is received.
- **Money** in SDR only. Rounding is done once in the view: money 2 decimals, `*_pct` in percent with 2 decimals,
  days 1 decimal.
- **Warm-up weeks 1–13** (`is_warmup = true`): receivables start at 0 on 2025-01-01, so AR and DSO are still building
  up; DSO uses a shorter window (`dso_window_days`). Always say so when you report a warm-up week.
- **WoW** is NULL in week 1 and when the previous value is 0: write "not available", never 100 %.
- Payment state comes from payments only; the invoice status label is never used.

## Metrics → `finance_kpi(report_week, dataset)` fields
| Metric | Meaning | dataset . field |
|---|---|---|
| Billed revenue | Σ invoices dated in the week | weekly . `billed_sdr`, `invoices_billed` |
| Collections | Σ payments dated in the week | weekly . `collected_sdr`, `payments_received` |
| AR | open invoices at week end; AR(w) = AR(w−1) + billed − collected | weekly . `ar_sdr`, `ar_invoices` |
| AR aging | days past due = Sunday − due date; buckets current / 1–30 / 31–60 / 61–90 / 90+ (Σ = AR) | weekly . `aging_*_sdr` |
| Overdue | open and ≥ 1 day past due | weekly . `overdue_sdr`, `overdue_invoices`; list: overdue |
| DSO | AR ÷ billed in the DSO window × window days (91, shorter in warm-up) | weekly . `dso_days` (+ `dso_window_*`) |
| Due date | invoice date + the customer's terms (30 / 45 / 60 days) | overdue . `due_date` |
| Top customers | billed in the trailing 13 weeks, ranked; previous rank for changes | customers . `billed_13w_sdr`, `rank_13w`, `rank_13w_prev`, `share_13w_pct` |
| Concentration | share of the top 10 customers in the trailing 13 weeks | weekly . `top10_share_13w_pct` |
| Budget variance | billed − budget, and ÷ budget × 100 | weekly / category . `budget_variance_sdr`, `budget_variance_pct` |
| WoW | (this − previous) ÷ previous × 100; DSO as a difference in days | weekly . `*_wow_pct`, `dso_wow_days`; category . `billed_wow_change_sdr` |
| 13-week trend | weeks w−12 … w | trend |

## Which dataset to ask for
- One headline number or the KPI tiles → `weekly`.
- "Why did revenue change", per vessel category, vs budget → `category` (largest |WoW change| first).
- Customers, concentration, who moved → `customers`.
- Who owes us, the oldest / largest overdue invoices → `overdue` (the note says how many of the total you got).
- A chart or a "since…" question → `trend`.

## Known facts of the data (not errors)
Background only: never write these figures (no tool returns them).
- About 19 invoices a week, so weekly variances swing widely.
- Over the year, actual billing is about 11 % below budget (planning assumption: laden tonnage).
- A top-10 share uses 13 weeks because one week's top 10 is almost every customer billed that week.
- Weeks 10, 15 and 50 each hold one duplicate charge (both copies paid) that inflates billed and collected: say
  so when reporting them (`invoice_audit` gives the amounts).
