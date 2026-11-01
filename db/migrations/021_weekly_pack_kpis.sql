-- =====================================================================
-- 021 — Weekly pack KPIs: new columns at the end of three finance views (weekly-pack improvement, Phase A)
-- Plan: docs/analysis/financial_intelligence/implementation_roadmap.md (APPROVED 2026-10-31; decisions W-R1…W-R8).
-- Definitions: docs/finance_metrics.md M9b, M12, M13, M14, M15, M16. Written by hand; never edited after applying.
-- Safety: CREATE OR REPLACE VIEW keeps every existing column, its name, type and order, and only APPENDS columns
-- (PostgreSQL refuses anything else), so the agent tools (explicit column lists, pipelines/agents/tools/finance.py),
-- the Power BI tables (explicit columns) and finance.kpi_weekly_trend see no change. Privileges and existing
-- comments are kept by CREATE OR REPLACE. The finance_test twins (migration 017) are not touched here: the tools read
-- the new columns only from Phase B, which adds them to the twins first.
-- Conventions (as 013): as of the report week's Sunday 23:59; money 2 decimals, *_pct percent 2 decimals, days 1
-- decimal, rounded once at the end; NULL where a value is undefined (no division by zero).
-- =====================================================================
BEGIN;

-- ---------------------------------------------------------------- kpi_weekly (013 body unchanged inside `prev`)
CREATE OR REPLACE VIEW finance.kpi_weekly AS
WITH billed AS (
    SELECT w.report_week, count(f.invoice_id) AS invoices_billed, coalesce(sum(f.amount_sdr), 0) AS billed_sdr
    FROM finance.dim_week w
    LEFT JOIN finance.fact_invoice f ON f.invoice_date BETWEEN w.week_start AND w.week_end
    GROUP BY w.report_week),
collected AS (
    SELECT w.report_week, count(p.invoice_number) AS payments_received, coalesce(sum(p.amount_sdr), 0) AS collected_sdr
    FROM finance.dim_week w
    LEFT JOIN finance.fact_payment p ON p.paid_date BETWEEN w.week_start AND w.week_end
    GROUP BY w.report_week),
ar AS (
    SELECT w.report_week,
           count(a.invoice_number) AS ar_invoices,
           coalesce(sum(a.amount_sdr), 0) AS ar_sdr,
           count(a.invoice_number) FILTER (WHERE a.is_overdue) AS overdue_invoices,
           coalesce(sum(a.amount_sdr) FILTER (WHERE a.is_overdue), 0) AS overdue_sdr,
           coalesce(sum(a.amount_sdr) FILTER (WHERE a.aging_bucket = 'current'), 0) AS aging_current_sdr,
           coalesce(sum(a.amount_sdr) FILTER (WHERE a.aging_bucket = '1-30'), 0) AS aging_1_30_sdr,
           coalesce(sum(a.amount_sdr) FILTER (WHERE a.aging_bucket = '31-60'), 0) AS aging_31_60_sdr,
           coalesce(sum(a.amount_sdr) FILTER (WHERE a.aging_bucket = '61-90'), 0) AS aging_61_90_sdr,
           coalesce(sum(a.amount_sdr) FILTER (WHERE a.aging_bucket = '90+'), 0) AS aging_90_plus_sdr
    FROM finance.dim_week w
    LEFT JOIN finance.fact_ar_snapshot a ON a.report_week = w.report_week
    GROUP BY w.report_week),
dso_base AS (
    SELECT w.report_week, coalesce(sum(f.amount_sdr), 0) AS dso_window_billed_sdr
    FROM finance.dim_week w
    LEFT JOIN finance.fact_invoice f ON f.invoice_date BETWEEN w.dso_window_start AND w.week_end
    GROUP BY w.report_week),
budget AS (
    SELECT iso_week AS report_week, sum(budget_sdr) AS budget_sdr
    FROM public.budget_weekly WHERE budget_year = 2025 GROUP BY iso_week),
concentration AS (
    SELECT report_week, sum(billed_13w_sdr) FILTER (WHERE is_top10) / NULLIF(sum(billed_13w_sdr), 0) AS top10_share
    FROM finance.kpi_customer_13w GROUP BY report_week),
base AS (
    SELECT w.report_week, w.iso_week_label, w.week_start, w.week_end, w.is_warmup, w.dso_window_days,
           b.invoices_billed, b.billed_sdr, c.payments_received, c.collected_sdr,
           a.ar_invoices, a.ar_sdr, a.overdue_invoices, a.overdue_sdr, a.aging_current_sdr, a.aging_1_30_sdr,
           a.aging_31_60_sdr, a.aging_61_90_sdr, a.aging_90_plus_sdr,
           d.dso_window_billed_sdr,
           a.ar_sdr / NULLIF(d.dso_window_billed_sdr, 0) * w.dso_window_days AS dso_days,
           bu.budget_sdr, k.top10_share
    FROM finance.dim_week w
    JOIN billed b ON b.report_week = w.report_week
    JOIN collected c ON c.report_week = w.report_week
    JOIN ar a ON a.report_week = w.report_week
    JOIN dso_base d ON d.report_week = w.report_week
    LEFT JOIN budget bu ON bu.report_week = w.report_week
    LEFT JOIN concentration k ON k.report_week = w.report_week),
prev AS (
    SELECT report_week, iso_week_label, week_start, week_end, is_warmup,
           invoices_billed, round(billed_sdr, 2) AS billed_sdr,
           payments_received, round(collected_sdr, 2) AS collected_sdr,
           ar_invoices, round(ar_sdr, 2) AS ar_sdr,
           overdue_invoices, round(overdue_sdr, 2) AS overdue_sdr,
           round(aging_current_sdr, 2) AS aging_current_sdr, round(aging_1_30_sdr, 2) AS aging_1_30_sdr,
           round(aging_31_60_sdr, 2) AS aging_31_60_sdr, round(aging_61_90_sdr, 2) AS aging_61_90_sdr,
           round(aging_90_plus_sdr, 2) AS aging_90_plus_sdr,
           dso_window_days, round(dso_window_billed_sdr, 2) AS dso_window_billed_sdr, round(dso_days, 1) AS dso_days,
           round(budget_sdr, 2) AS budget_sdr,
           round(billed_sdr - budget_sdr, 2) AS budget_variance_sdr,
           round(100 * (billed_sdr - budget_sdr) / NULLIF(budget_sdr, 0), 2) AS budget_variance_pct,
           round(100 * top10_share, 2) AS top10_share_13w_pct,
           round(100 * (billed_sdr - lag(billed_sdr) OVER wk) / NULLIF(lag(billed_sdr) OVER wk, 0), 2) AS billed_wow_pct,
           round(100 * (collected_sdr - lag(collected_sdr) OVER wk) / NULLIF(lag(collected_sdr) OVER wk, 0), 2) AS collected_wow_pct,
           round(100 * (ar_sdr - lag(ar_sdr) OVER wk) / NULLIF(lag(ar_sdr) OVER wk, 0), 2) AS ar_wow_pct,
           round(100 * (overdue_sdr - lag(overdue_sdr) OVER wk) / NULLIF(lag(overdue_sdr) OVER wk, 0), 2) AS overdue_wow_pct,
           round(dso_days - lag(dso_days) OVER wk, 1) AS dso_wow_days
    FROM base
    WINDOW wk AS (ORDER BY report_week)),
-- M9b: billing and budget of the rolling window (13 weeks, or weeks 1 … w before week 13), from the unrounded base
rolling AS (
    SELECT report_week,
           count(*) OVER r13 AS roll_window_weeks,
           sum(billed_sdr) OVER r13 AS billed_13w_sdr,
           sum(budget_sdr) OVER r13 AS budget_13w_sdr,
           round(aging_current_sdr / NULLIF(dso_window_billed_sdr, 0) * dso_window_days, 1) AS dso_best_days
    FROM base
    WINDOW r13 AS (ORDER BY report_week ROWS BETWEEN 12 PRECEDING AND CURRENT ROW)),
-- M13: the typical weekly swing = median |WoW| (the view's rounded WoW) over the rolling window, ≥ 8 values
swing AS (
    SELECT p.report_week,
           (SELECT CASE WHEN count(*) >= 8 THEN percentile_cont(0.5) WITHIN GROUP (ORDER BY abs(x.billed_wow_pct)::float8) END
            FROM prev x WHERE x.report_week BETWEEN p.report_week - 12 AND p.report_week AND x.billed_wow_pct IS NOT NULL) AS billed_typ,
           (SELECT CASE WHEN count(*) >= 8 THEN percentile_cont(0.5) WITHIN GROUP (ORDER BY abs(x.collected_wow_pct)::float8) END
            FROM prev x WHERE x.report_week BETWEEN p.report_week - 12 AND p.report_week AND x.collected_wow_pct IS NOT NULL) AS collected_typ,
           (SELECT CASE WHEN count(*) >= 8 THEN percentile_cont(0.5) WITHIN GROUP (ORDER BY abs(x.ar_wow_pct)::float8) END
            FROM prev x WHERE x.report_week BETWEEN p.report_week - 12 AND p.report_week AND x.ar_wow_pct IS NOT NULL) AS ar_typ,
           (SELECT CASE WHEN count(*) >= 8 THEN percentile_cont(0.5) WITHIN GROUP (ORDER BY abs(x.overdue_wow_pct)::float8) END
            FROM prev x WHERE x.report_week BETWEEN p.report_week - 12 AND p.report_week AND x.overdue_wow_pct IS NOT NULL) AS overdue_typ
    FROM prev p),
-- M14: overdue roll-forward and the cash falling due in the week. Overdue at Sunday S = due ≤ S − 1 and unpaid at S,
-- so overdue(S) − overdue(S − 7) = newly overdue (due S − 7 … S − 1, unpaid at S) − overdue paid (due ≤ S − 8, paid
-- S − 6 … S): an exact identity, asserted by Finance_views_check.py.
flows AS (
    SELECT w.report_week,
           coalesce(sum(f.amount_sdr) FILTER (WHERE f.due_date BETWEEN w.week_end - 7 AND w.week_end - 1
                                                AND (f.paid_date IS NULL OR f.paid_date > w.week_end)), 0) AS overdue_new_sdr,
           coalesce(sum(f.amount_sdr) FILTER (WHERE f.due_date <= w.week_end - 8
                                                AND f.paid_date BETWEEN w.week_start AND w.week_end), 0) AS overdue_paid_sdr,
           coalesce(sum(f.amount_sdr) FILTER (WHERE f.due_date BETWEEN w.week_start AND w.week_end), 0) AS due_week_sdr,
           coalesce(sum(f.amount_sdr) FILTER (WHERE f.due_date BETWEEN w.week_start AND w.week_end
                                                AND f.paid_date <= w.week_end), 0) AS due_week_collected_sdr
    FROM finance.dim_week w
    CROSS JOIN finance.fact_invoice f
    GROUP BY w.report_week),
-- M16: share of the payments made in the 91 days ending Sunday (from 2025-01-01 in the warm-up) paid on or before due
punctuality AS (
    SELECT w.report_week,
           100.0 * count(p.invoice_number) FILTER (WHERE p.days_paid_after_due <= 0) / NULLIF(count(p.invoice_number), 0) AS ontime_13w
    FROM finance.dim_week w
    LEFT JOIN finance.fact_payment p ON p.paid_date BETWEEN w.week_end - 90 AND w.week_end
    GROUP BY w.report_week)
SELECT p.*,
       r.roll_window_weeks,
       round(r.billed_13w_sdr, 2) AS billed_13w_sdr,
       round(r.budget_13w_sdr, 2) AS budget_13w_sdr,
       round(100 * (r.billed_13w_sdr - r.budget_13w_sdr) / NULLIF(r.budget_13w_sdr, 0), 2) AS budget_variance_13w_pct,
       r.dso_best_days,
       p.dso_days - r.dso_best_days AS dso_delinquency_days,
       round(s.billed_typ::numeric, 2) AS billed_wow_typical_pct,
       round(s.collected_typ::numeric, 2) AS collected_wow_typical_pct,
       round(s.ar_typ::numeric, 2) AS ar_wow_typical_pct,
       round(s.overdue_typ::numeric, 2) AS overdue_wow_typical_pct,
       round(fl.overdue_new_sdr, 2) AS overdue_new_sdr,
       round(fl.overdue_paid_sdr, 2) AS overdue_paid_sdr,
       round(fl.due_week_sdr, 2) AS due_week_sdr,
       round(fl.due_week_collected_sdr, 2) AS due_week_collected_sdr,
       round(100 * fl.due_week_collected_sdr / NULLIF(fl.due_week_sdr, 0), 2) AS due_week_collected_pct,
       round(pu.ontime_13w, 2) AS ontime_13w_pct
FROM prev p
JOIN rolling r ON r.report_week = p.report_week
JOIN swing s ON s.report_week = p.report_week
JOIN flows fl ON fl.report_week = p.report_week
JOIN punctuality pu ON pu.report_week = p.report_week;

-- ---------------------------------------------------------------- kpi_customer_13w (013 body unchanged inside `prev`)
CREATE OR REPLACE VIEW finance.kpi_customer_13w AS
WITH grid AS (
    SELECT w.report_week, w.week_start, w.week_end, c.customer_id
    FROM finance.dim_week w CROSS JOIN public.customers c),
billing AS (
    SELECT g.report_week, g.customer_id,
           coalesce(sum(f.amount_sdr) FILTER (WHERE f.invoice_date >= g.week_start), 0) AS billed_week_sdr,
           coalesce(sum(f.amount_sdr), 0) AS billed_13w_sdr
    FROM grid g
    LEFT JOIN finance.fact_invoice f ON f.customer_id = g.customer_id AND f.invoice_date BETWEEN g.week_end - 90 AND g.week_end
    GROUP BY g.report_week, g.customer_id),
open_ar AS (
    SELECT report_week, customer_id, sum(amount_sdr) AS ar_sdr, sum(amount_sdr) FILTER (WHERE is_overdue) AS overdue_sdr
    FROM finance.fact_ar_snapshot GROUP BY report_week, customer_id),
ranked AS (
    SELECT b.*, sum(b.billed_13w_sdr) OVER (PARTITION BY b.report_week) AS total_13w_sdr,
           row_number() OVER (PARTITION BY b.report_week ORDER BY b.billed_13w_sdr DESC, b.customer_id) AS rank_13w
    FROM billing b),
prev AS (
    SELECT r.report_week, r.customer_id, c.customer_name, c.segment, c.country, c.credit_rating, c.payment_terms_days,
           round(r.billed_week_sdr, 2) AS billed_week_sdr,
           round(r.billed_13w_sdr, 2) AS billed_13w_sdr,
           round(100 * r.billed_13w_sdr / NULLIF(r.total_13w_sdr, 0), 2) AS share_13w_pct,
           r.rank_13w,
           lag(r.rank_13w) OVER (PARTITION BY r.customer_id ORDER BY r.report_week) AS rank_13w_prev,
           (r.rank_13w <= 10 AND r.billed_13w_sdr > 0) AS is_top10,
           round(coalesce(o.ar_sdr, 0), 2) AS ar_sdr,
           round(coalesce(o.overdue_sdr, 0), 2) AS overdue_sdr
    FROM ranked r
    JOIN public.customers c ON c.customer_id = r.customer_id
    LEFT JOIN open_ar o ON o.report_week = r.report_week AND o.customer_id = r.customer_id),
punctuality AS (
    SELECT g.report_week, g.customer_id,
           100.0 * count(p.invoice_number) FILTER (WHERE p.days_paid_after_due <= 0) / NULLIF(count(p.invoice_number), 0) AS ontime_13w
    FROM grid g
    LEFT JOIN finance.fact_payment p ON p.customer_id = g.customer_id AND p.paid_date BETWEEN g.week_end - 90 AND g.week_end
    GROUP BY g.report_week, g.customer_id)
SELECT p.*,
       -- M15: receivables against the customer's own 13-week billing, and the watchlist flag (W-R1 / W-R7)
       round(100 * p.ar_sdr / NULLIF(p.billed_13w_sdr, 0), 2) AS ar_to_billed_13w_pct,
       CASE WHEN p.report_week <= 13 THEN NULL
            ELSE p.ar_sdr >= 1000000 AND (p.billed_13w_sdr = 0 OR p.ar_sdr >= 0.8 * p.billed_13w_sdr) END AS is_watchlist,
       round(pu.ontime_13w, 2) AS ontime_13w_pct
FROM prev p
JOIN punctuality pu ON pu.report_week = p.report_week AND pu.customer_id = p.customer_id;

-- ---------------------------------------------------------------- kpi_weekly_category (013 select + one column)
CREATE OR REPLACE VIEW finance.kpi_weekly_category AS
WITH grid AS (
    SELECT w.report_week, w.week_start, w.week_end, b.vessel_category, b.budget_sdr
    FROM finance.dim_week w
    JOIN public.budget_weekly b ON b.budget_year = 2025 AND b.iso_week = w.report_week),
base AS (
    SELECT g.report_week, g.vessel_category, g.budget_sdr,
           count(f.invoice_id) AS invoices_billed, coalesce(sum(f.amount_sdr), 0) AS billed_sdr
    FROM grid g
    LEFT JOIN finance.fact_invoice f ON f.vessel_category = g.vessel_category AND f.invoice_date BETWEEN g.week_start AND g.week_end
    GROUP BY g.report_week, g.vessel_category, g.budget_sdr)
SELECT report_week, vessel_category, invoices_billed,
       round(billed_sdr, 2) AS billed_sdr,
       round(budget_sdr, 2) AS budget_sdr,
       round(billed_sdr - budget_sdr, 2) AS budget_variance_sdr,
       round(100 * (billed_sdr - budget_sdr) / NULLIF(budget_sdr, 0), 2) AS budget_variance_pct,
       round(lag(billed_sdr) OVER cw, 2) AS billed_prev_sdr,
       round(billed_sdr - lag(billed_sdr) OVER cw, 2) AS billed_wow_change_sdr,
       round(100 * (billed_sdr - lag(billed_sdr) OVER cw) / NULLIF(lag(billed_sdr) OVER cw, 0), 2) AS billed_wow_pct,
       lag(invoices_billed) OVER cw AS invoices_prev
FROM base
WINDOW cw AS (PARTITION BY vessel_category ORDER BY report_week);

-- ---------------------------------------------------------------- comments on the new columns
COMMENT ON COLUMN finance.kpi_weekly.roll_window_weeks IS 'Weeks in the rolling window of the *_13w columns: 13, or the report week number before week 13 (M9b).';
COMMENT ON COLUMN finance.kpi_weekly.billed_13w_sdr IS 'Billed revenue of the rolling window (weeks w-12 … w, from week 1 before week 13), SDR (M9b).';
COMMENT ON COLUMN finance.kpi_weekly.budget_13w_sdr IS 'Budget of the same rolling window, SDR (M9b).';
COMMENT ON COLUMN finance.kpi_weekly.budget_variance_13w_pct IS '(billed_13w − budget_13w) ÷ budget_13w × 100: the period''s position against plan (M9b).';
COMMENT ON COLUMN finance.kpi_weekly.dso_best_days IS 'Best-possible DSO: current (not overdue) AR ÷ DSO-window billing × window days, 1 decimal (M12).';
COMMENT ON COLUMN finance.kpi_weekly.dso_delinquency_days IS 'dso_days − dso_best_days: the days of billing outstanding because customers pay late (M12).';
COMMENT ON COLUMN finance.kpi_weekly.billed_wow_typical_pct IS 'Typical weekly swing of billed: median |billed_wow_pct| over the rolling window, at least 8 values, else NULL (M13).';
COMMENT ON COLUMN finance.kpi_weekly.collected_wow_typical_pct IS 'Typical weekly swing of collected: median |collected_wow_pct| over the rolling window, at least 8 values (M13).';
COMMENT ON COLUMN finance.kpi_weekly.ar_wow_typical_pct IS 'Typical weekly swing of AR: median |ar_wow_pct| over the rolling window, at least 8 values (M13).';
COMMENT ON COLUMN finance.kpi_weekly.overdue_wow_typical_pct IS 'Typical weekly swing of overdue: median |overdue_wow_pct| over the rolling window, at least 8 values (M13).';
COMMENT ON COLUMN finance.kpi_weekly.overdue_new_sdr IS 'Invoices that became overdue in the week (due from the previous Sunday to this Saturday) and are unpaid at Sunday, SDR (M14).';
COMMENT ON COLUMN finance.kpi_weekly.overdue_paid_sdr IS 'Payments in the week on invoices already overdue at the previous Sunday, SDR; overdue change = new − paid (M14).';
COMMENT ON COLUMN finance.kpi_weekly.due_week_sdr IS 'Invoices falling due in the week (Monday–Sunday), SDR (M14).';
COMMENT ON COLUMN finance.kpi_weekly.due_week_collected_sdr IS 'Part of due_week_sdr paid by the week''s Sunday, SDR (M14).';
COMMENT ON COLUMN finance.kpi_weekly.due_week_collected_pct IS 'due_week_collected_sdr ÷ due_week_sdr × 100 (M14).';
COMMENT ON COLUMN finance.kpi_weekly.ontime_13w_pct IS 'Share of the payments made in the 91 days ending Sunday that were paid on or before due, percent (M16).';
COMMENT ON COLUMN finance.kpi_customer_13w.ar_to_billed_13w_pct IS 'Customer AR ÷ its own 13-week billing × 100; NULL when it billed nothing in 13 weeks (M15).';
COMMENT ON COLUMN finance.kpi_customer_13w.is_watchlist IS 'AR ≥ 1,000,000 SDR and (no 13-week billing or AR ≥ 80 % of it); NULL in warm-up weeks 1–13 (M15, W-R1 / W-R7).';
COMMENT ON COLUMN finance.kpi_customer_13w.ontime_13w_pct IS 'Share of the customer''s payments in the 91 days ending Sunday paid on or before due, percent; NULL without payments (M16).';
COMMENT ON COLUMN finance.kpi_weekly_category.invoices_prev IS 'Invoices billed in the category in the previous report week; NULL in week 1 (shows how many invoices sit behind a WoW driver).';

COMMIT;
