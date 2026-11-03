-- =====================================================================
-- 022 — The finance_test twins (migration 017) get the columns migration 021 appended to the live views
--       (weekly-pack improvement, Phase B; plan docs/analysis/financial_intelligence/implementation_roadmap.md)
-- Why: from Phase B the finance_kpi tool returns the 021 columns; an evaluation run (dataset "test") reads the twins,
-- so the twins must offer the same column names. Rule of 017 kept: billed and budget come from the copy, everything
-- the copy does not hold comes from the live views.
--   from the copy       billed_13w_sdr / budget_13w_sdr / budget_variance_13w_pct: the live 13-week sums with the
--                       report week's live billed / budget replaced by the copy's (a planted error or the planted
--                       budget miss moves the 13-week position as it would in a real company's books)
--   from the live views roll_window_weeks, the DSO split, the four typical swings (history of the live weeks), the
--                       overdue roll-forward, the due-this-week rate, the on-time rate; invoices_prev of a category
-- Safety: CREATE OR REPLACE VIEW keeps the 017 columns, their order and their comments, and only APPENDS (PostgreSQL
-- refuses anything else); the live finance views, Power BI and the scheduled packs are not touched.
-- Same rounding as 013 / 021 (money 2, percent 2). Grants: kept by CREATE OR REPLACE (default privileges of 012).
-- Written by hand; never edited after applying.
-- =====================================================================
BEGIN;

CREATE OR REPLACE VIEW finance_test.kpi_weekly_category AS
WITH weeks AS (
    SELECT w.report_week, w.week_start, w.week_end
    FROM finance.dim_week w
    WHERE w.report_week IN (SELECT DISTINCT iso_week FROM finance_test.budget_weekly WHERE budget_year = 2025)),
grid AS (
    SELECT w.report_week, w.week_start, w.week_end, b.vessel_category, b.budget_sdr
    FROM weeks w
    JOIN finance_test.budget_weekly b ON b.budget_year = 2025 AND b.iso_week = w.report_week),
base AS (
    SELECT g.report_week, g.vessel_category, g.budget_sdr,
           count(i.invoice_number) AS invoices_billed, coalesce(sum(i.billed_sdr), 0) AS billed_sdr
    FROM grid g
    LEFT JOIN (finance_test.invoices i JOIN public.vessels v ON v.vessel_id = i.vessel_id)
      ON v.vessel_type = g.vessel_category AND i.invoice_date BETWEEN g.week_start AND g.week_end
    GROUP BY g.report_week, g.vessel_category, g.budget_sdr),
prev AS (
    SELECT g.report_week, g.vessel_category,
           CASE WHEN g.report_week > 1 THEN coalesce(sum(f.amount_sdr), 0) END AS billed_prev_sdr
    FROM grid g
    LEFT JOIN finance.fact_invoice f
      ON f.vessel_category = g.vessel_category AND f.invoice_date BETWEEN g.week_start - 7 AND g.week_end - 7
    GROUP BY g.report_week, g.vessel_category)
SELECT b.report_week, b.vessel_category, b.invoices_billed,
       round(b.billed_sdr, 2) AS billed_sdr,
       round(b.budget_sdr, 2) AS budget_sdr,
       round(b.billed_sdr - b.budget_sdr, 2) AS budget_variance_sdr,
       round(100 * (b.billed_sdr - b.budget_sdr) / NULLIF(b.budget_sdr, 0), 2) AS budget_variance_pct,
       round(p.billed_prev_sdr, 2) AS billed_prev_sdr,
       round(b.billed_sdr - p.billed_prev_sdr, 2) AS billed_wow_change_sdr,
       round(100 * (b.billed_sdr - p.billed_prev_sdr) / NULLIF(p.billed_prev_sdr, 0), 2) AS billed_wow_pct,
       lc.invoices_prev
FROM base b
JOIN prev p ON p.report_week = b.report_week AND p.vessel_category = b.vessel_category
LEFT JOIN finance.kpi_weekly_category lc ON lc.report_week = b.report_week AND lc.vessel_category = b.vessel_category;

CREATE OR REPLACE VIEW finance_test.kpi_weekly AS
WITH weeks AS (
    SELECT w.report_week, w.week_start, w.week_end
    FROM finance.dim_week w
    WHERE w.report_week IN (SELECT DISTINCT iso_week FROM finance_test.budget_weekly WHERE budget_year = 2025)),
billed AS (
    SELECT w.report_week, count(i.invoice_number) AS invoices_billed, coalesce(sum(i.billed_sdr), 0) AS billed_sdr
    FROM weeks w
    LEFT JOIN finance_test.invoices i ON i.invoice_date BETWEEN w.week_start AND w.week_end
    GROUP BY w.report_week),
budget AS (
    SELECT iso_week AS report_week, sum(budget_sdr) AS budget_sdr
    FROM finance_test.budget_weekly WHERE budget_year = 2025 GROUP BY iso_week),
prev AS (
    SELECT w.report_week, CASE WHEN w.report_week > 1 THEN coalesce(sum(f.amount_sdr), 0) END AS billed_prev_sdr
    FROM weeks w
    LEFT JOIN finance.fact_invoice f ON f.invoice_date BETWEEN w.week_start - 7 AND w.week_end - 7
    GROUP BY w.report_week),
-- the live 13-week sums with the report week swapped for the copy's (amounts are whole cents: no rounding drift)
rolling AS (
    SELECT k.report_week,
           k.billed_13w_sdr - k.billed_sdr + b.billed_sdr AS billed_13w_sdr,
           k.budget_13w_sdr - k.budget_sdr + bu.budget_sdr AS budget_13w_sdr
    FROM finance.kpi_weekly k
    JOIN billed b ON b.report_week = k.report_week
    JOIN budget bu ON bu.report_week = k.report_week)
SELECT k.report_week, k.iso_week_label, k.week_start, k.week_end, k.is_warmup,
       b.invoices_billed, round(b.billed_sdr, 2) AS billed_sdr,
       k.payments_received, k.collected_sdr,
       k.ar_invoices, k.ar_sdr,
       k.overdue_invoices, k.overdue_sdr,
       k.aging_current_sdr, k.aging_1_30_sdr, k.aging_31_60_sdr, k.aging_61_90_sdr, k.aging_90_plus_sdr,
       k.dso_window_days, k.dso_window_billed_sdr, k.dso_days,
       round(bu.budget_sdr, 2) AS budget_sdr,
       round(b.billed_sdr - bu.budget_sdr, 2) AS budget_variance_sdr,
       round(100 * (b.billed_sdr - bu.budget_sdr) / NULLIF(bu.budget_sdr, 0), 2) AS budget_variance_pct,
       k.top10_share_13w_pct,
       round(100 * (b.billed_sdr - p.billed_prev_sdr) / NULLIF(p.billed_prev_sdr, 0), 2) AS billed_wow_pct,
       k.collected_wow_pct, k.ar_wow_pct, k.overdue_wow_pct, k.dso_wow_days,
       k.roll_window_weeks,
       round(r.billed_13w_sdr, 2) AS billed_13w_sdr,
       round(r.budget_13w_sdr, 2) AS budget_13w_sdr,
       round(100 * (r.billed_13w_sdr - r.budget_13w_sdr) / NULLIF(r.budget_13w_sdr, 0), 2) AS budget_variance_13w_pct,
       k.dso_best_days, k.dso_delinquency_days,
       k.billed_wow_typical_pct, k.collected_wow_typical_pct, k.ar_wow_typical_pct, k.overdue_wow_typical_pct,
       k.overdue_new_sdr, k.overdue_paid_sdr, k.due_week_sdr, k.due_week_collected_sdr, k.due_week_collected_pct,
       k.ontime_13w_pct
FROM finance.kpi_weekly k
JOIN billed b ON b.report_week = k.report_week
JOIN budget bu ON bu.report_week = k.report_week
JOIN prev p ON p.report_week = k.report_week
JOIN rolling r ON r.report_week = k.report_week;

-- ---------------------------------------------------------------- comments of the appended columns (ADR-033)
COMMENT ON COLUMN finance_test.kpi_weekly_category.invoices_prev IS 'LIVE value (finance.kpi_weekly_category): invoices of the category in the previous week (the copy holds no previous week)';

COMMENT ON COLUMN finance_test.kpi_weekly.roll_window_weeks IS 'LIVE value (finance.kpi_weekly, M9b)';
COMMENT ON COLUMN finance_test.kpi_weekly.billed_13w_sdr IS 'Live 13-week billed with the report week replaced by the copy''s billed (planted errors included), M9b';
COMMENT ON COLUMN finance_test.kpi_weekly.budget_13w_sdr IS 'Live 13-week budget with the report week replaced by the copy''s budget (week 36 carries the planted miss), M9b';
COMMENT ON COLUMN finance_test.kpi_weekly.budget_variance_13w_pct IS '(billed_13w − budget_13w) / budget_13w, percent, both as in this view';
COMMENT ON COLUMN finance_test.kpi_weekly.dso_best_days IS 'LIVE value (finance.kpi_weekly, M12)';
COMMENT ON COLUMN finance_test.kpi_weekly.dso_delinquency_days IS 'LIVE value (finance.kpi_weekly, M12)';
COMMENT ON COLUMN finance_test.kpi_weekly.billed_wow_typical_pct IS 'LIVE value (finance.kpi_weekly, M13): the typical swing is the history of the live weeks';
COMMENT ON COLUMN finance_test.kpi_weekly.collected_wow_typical_pct IS 'LIVE value (finance.kpi_weekly, M13)';
COMMENT ON COLUMN finance_test.kpi_weekly.ar_wow_typical_pct IS 'LIVE value (finance.kpi_weekly, M13)';
COMMENT ON COLUMN finance_test.kpi_weekly.overdue_wow_typical_pct IS 'LIVE value (finance.kpi_weekly, M13)';
COMMENT ON COLUMN finance_test.kpi_weekly.overdue_new_sdr IS 'LIVE value (finance.kpi_weekly, M14)';
COMMENT ON COLUMN finance_test.kpi_weekly.overdue_paid_sdr IS 'LIVE value (finance.kpi_weekly, M14)';
COMMENT ON COLUMN finance_test.kpi_weekly.due_week_sdr IS 'LIVE value (finance.kpi_weekly, M14)';
COMMENT ON COLUMN finance_test.kpi_weekly.due_week_collected_sdr IS 'LIVE value (finance.kpi_weekly, M14)';
COMMENT ON COLUMN finance_test.kpi_weekly.due_week_collected_pct IS 'LIVE value (finance.kpi_weekly, M14)';
COMMENT ON COLUMN finance_test.kpi_weekly.ontime_13w_pct IS 'LIVE value (finance.kpi_weekly, M16)';

COMMIT;
