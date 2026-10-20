-- =====================================================================
-- 017 — Twin KPI views of the evaluation copy: finance_test.kpi_weekly + finance_test.kpi_weekly_category
--       (Agents plan §5d step S2, owner decision P7-2 of 2026-10-19)
-- Why: the planted budget miss (week 36, LNG Carriers, budget × 1.5) lives in finance_test.budget_weekly, which no
-- view read, so the Insight agent and the Writer could never see it. These two views give the evaluation copy the
-- same columns as finance.kpi_weekly / finance.kpi_weekly_category; the finance_kpi tool reads them only when the
-- run context says dataset = "test" (set by the evaluation harness alone, ADR-049), so the pack sees the copy's
-- books — planted errors included — as it would see a real company's.
-- What comes from the copy and what from the live views (the copy has 4 weeks and no payments):
--   from finance_test   invoices_billed, billed_sdr (planted errors and the planted duplicate included), budget_sdr
--                       and the variances against it
--   from the live views billed of the previous week (the WoW base: the copy holds no week w−1), every receivables
--                       column (AR, aging, overdue, collected, DSO and its window), the top-10 share and the other WoW
--                       columns of finance.kpi_weekly — stated in the column comments
-- Weeks: the report weeks present in finance_test.budget_weekly (10, 23, 36, 49).
-- Same rounding as migration 013 (once at the end: money 2, percent 2). Decisions: ADR-046 (finance_test), ADR-047
-- (plain views, one definition per metric), ADR-049 (dataset from the run context). Grants: the default privileges of
-- migration 012 (ports_readonly reads schema finance_test; finance_bi never does — Power BI cannot see the copy).
-- Written by hand; never edited after applying.
-- =====================================================================
BEGIN;

CREATE VIEW finance_test.kpi_weekly_category AS
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
       round(100 * (b.billed_sdr - p.billed_prev_sdr) / NULLIF(p.billed_prev_sdr, 0), 2) AS billed_wow_pct
FROM base b
JOIN prev p ON p.report_week = b.report_week AND p.vessel_category = b.vessel_category;

CREATE VIEW finance_test.kpi_weekly AS
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
    GROUP BY w.report_week)
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
       k.collected_wow_pct, k.ar_wow_pct, k.overdue_wow_pct, k.dso_wow_days
FROM finance.kpi_weekly k
JOIN billed b ON b.report_week = k.report_week
JOIN budget bu ON bu.report_week = k.report_week
JOIN prev p ON p.report_week = k.report_week;

-- ---------------------------------------------------------------- comments (read by the tools, ADR-033)
COMMENT ON VIEW finance_test.kpi_weekly_category IS 'Twin of finance.kpi_weekly_category over the evaluation copy (Agents plan §5d, migration 017): billed from finance_test.invoices, budget from finance_test.budget_weekly (the planted budget miss), the previous week from the live invoices. Weeks 10, 23, 36, 49 only. Evaluation only; invisible to Power BI. Level 2, Finance.';
COMMENT ON COLUMN finance_test.kpi_weekly_category.report_week IS 'ISO week of 2025 (a week of the evaluation copy)';
COMMENT ON COLUMN finance_test.kpi_weekly_category.vessel_category IS 'Tariff category (vessels.vessel_type)';
COMMENT ON COLUMN finance_test.kpi_weekly_category.invoices_billed IS 'Invoices of the copy dated in the week for the category (a planted duplicate counts)';
COMMENT ON COLUMN finance_test.kpi_weekly_category.billed_sdr IS 'Billed in the week (SDR) as in finance_test.invoices, planted errors included';
COMMENT ON COLUMN finance_test.kpi_weekly_category.budget_sdr IS 'Budget of the week (SDR) from finance_test.budget_weekly (one row planted: week 36)';
COMMENT ON COLUMN finance_test.kpi_weekly_category.budget_variance_sdr IS 'billed − budget (SDR)';
COMMENT ON COLUMN finance_test.kpi_weekly_category.budget_variance_pct IS '(billed − budget) / budget, percent';
COMMENT ON COLUMN finance_test.kpi_weekly_category.billed_prev_sdr IS 'Billed in the previous week (SDR) from the LIVE invoices (the copy holds no previous week)';
COMMENT ON COLUMN finance_test.kpi_weekly_category.billed_wow_change_sdr IS 'billed − billed_prev (SDR); the week''s drivers = the largest absolute changes';
COMMENT ON COLUMN finance_test.kpi_weekly_category.billed_wow_pct IS 'Week-over-week change of billed, percent (NULL when the previous week billed 0)';

COMMENT ON VIEW finance_test.kpi_weekly IS 'Twin of finance.kpi_weekly over the evaluation copy (Agents plan §5d, migration 017): billed and budget from the copy (planted errors and the budget miss); receivables, collections, DSO, the top-10 share and their WoW from the live view (the copy has no payments); billed WoW against the live previous week. Weeks 10, 23, 36, 49 only. Evaluation only; invisible to Power BI. Level 2, Finance.';
COMMENT ON COLUMN finance_test.kpi_weekly.report_week IS 'ISO week of 2025 (a week of the evaluation copy)';
COMMENT ON COLUMN finance_test.kpi_weekly.iso_week_label IS 'As finance.kpi_weekly';
COMMENT ON COLUMN finance_test.kpi_weekly.week_start IS 'As finance.kpi_weekly';
COMMENT ON COLUMN finance_test.kpi_weekly.week_end IS 'As finance.kpi_weekly';
COMMENT ON COLUMN finance_test.kpi_weekly.is_warmup IS 'As finance.kpi_weekly';
COMMENT ON COLUMN finance_test.kpi_weekly.invoices_billed IS 'Invoices of the copy dated in the week (a planted duplicate counts)';
COMMENT ON COLUMN finance_test.kpi_weekly.billed_sdr IS 'Billed in the week (SDR) as in finance_test.invoices, planted errors included';
COMMENT ON COLUMN finance_test.kpi_weekly.payments_received IS 'LIVE value (finance.kpi_weekly): the copy has no payments';
COMMENT ON COLUMN finance_test.kpi_weekly.collected_sdr IS 'LIVE value (finance.kpi_weekly): the copy has no payments';
COMMENT ON COLUMN finance_test.kpi_weekly.ar_invoices IS 'LIVE value (finance.kpi_weekly)';
COMMENT ON COLUMN finance_test.kpi_weekly.ar_sdr IS 'LIVE value (finance.kpi_weekly)';
COMMENT ON COLUMN finance_test.kpi_weekly.overdue_invoices IS 'LIVE value (finance.kpi_weekly)';
COMMENT ON COLUMN finance_test.kpi_weekly.overdue_sdr IS 'LIVE value (finance.kpi_weekly)';
COMMENT ON COLUMN finance_test.kpi_weekly.aging_current_sdr IS 'LIVE value (finance.kpi_weekly)';
COMMENT ON COLUMN finance_test.kpi_weekly.aging_1_30_sdr IS 'LIVE value (finance.kpi_weekly)';
COMMENT ON COLUMN finance_test.kpi_weekly.aging_31_60_sdr IS 'LIVE value (finance.kpi_weekly)';
COMMENT ON COLUMN finance_test.kpi_weekly.aging_61_90_sdr IS 'LIVE value (finance.kpi_weekly)';
COMMENT ON COLUMN finance_test.kpi_weekly.aging_90_plus_sdr IS 'LIVE value (finance.kpi_weekly)';
COMMENT ON COLUMN finance_test.kpi_weekly.dso_window_days IS 'LIVE value (finance.kpi_weekly)';
COMMENT ON COLUMN finance_test.kpi_weekly.dso_window_billed_sdr IS 'LIVE value (finance.kpi_weekly): the DSO base stays on the live invoices';
COMMENT ON COLUMN finance_test.kpi_weekly.dso_days IS 'LIVE value (finance.kpi_weekly)';
COMMENT ON COLUMN finance_test.kpi_weekly.budget_sdr IS 'Budget of the week (SDR) from finance_test.budget_weekly (week 36 carries the planted miss)';
COMMENT ON COLUMN finance_test.kpi_weekly.budget_variance_sdr IS 'billed − budget (SDR), both from the copy';
COMMENT ON COLUMN finance_test.kpi_weekly.budget_variance_pct IS '(billed − budget) / budget, percent, both from the copy';
COMMENT ON COLUMN finance_test.kpi_weekly.top10_share_13w_pct IS 'LIVE value (finance.kpi_weekly)';
COMMENT ON COLUMN finance_test.kpi_weekly.billed_wow_pct IS 'Billed of the copy vs billed of the LIVE previous week, percent';
COMMENT ON COLUMN finance_test.kpi_weekly.collected_wow_pct IS 'LIVE value (finance.kpi_weekly)';
COMMENT ON COLUMN finance_test.kpi_weekly.ar_wow_pct IS 'LIVE value (finance.kpi_weekly)';
COMMENT ON COLUMN finance_test.kpi_weekly.overdue_wow_pct IS 'LIVE value (finance.kpi_weekly)';
COMMENT ON COLUMN finance_test.kpi_weekly.dso_wow_days IS 'LIVE value (finance.kpi_weekly)';

COMMIT;
