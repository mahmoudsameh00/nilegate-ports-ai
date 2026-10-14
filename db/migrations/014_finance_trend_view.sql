-- =====================================================================
-- 014 — finance.kpi_weekly_trend: the 13-week trend of each report week (Agents plan Phase 3, owner decision P3-4)
-- Why: Power BI's single week slicer filters dim_week to one week, so a trend chart would show one point. This view
-- gives every report_week its own 13 trend rows (weeks w−12 … w, fewer at the start of the year): the slicer filters
-- report_week, the chart's axis is trend_week. No DAX; the values are kpi_weekly's own (M11, docs/finance_metrics.md).
-- Decisions: ADR-047 (plain views, KPIs in SQL). Written by hand; never edited after applying. Grants come from the
-- default privileges of migration 013 (ports_readonly, finance_bi).
-- =====================================================================
BEGIN;

CREATE VIEW finance.kpi_weekly_trend AS
SELECT s.report_week,
       t.report_week AS trend_week,
       t.report_week - s.report_week AS week_offset,
       t.report_week = s.report_week AS is_report_week,
       t.iso_week_label AS trend_week_label,
       t.week_end AS trend_week_end,
       t.is_warmup,
       t.invoices_billed, t.billed_sdr, t.collected_sdr, t.ar_sdr, t.overdue_sdr, t.dso_days,
       t.budget_sdr, t.budget_variance_sdr, t.budget_variance_pct, t.top10_share_13w_pct
FROM finance.dim_week s
JOIN finance.kpi_weekly t ON t.report_week BETWEEN s.report_week - 12 AND s.report_week;

COMMENT ON VIEW finance.kpi_weekly_trend IS 'The 13-week trend of each report week (M11): one row per (report_week, trend_week) for the weeks w−12 … w (fewer in weeks 1–12), values from kpi_weekly. Filter report_week, chart over trend_week. Level 2, Finance.';
COMMENT ON COLUMN finance.kpi_weekly_trend.report_week IS 'The report week the trend belongs to (filter on this)';
COMMENT ON COLUMN finance.kpi_weekly_trend.trend_week IS 'A week inside the trend window (chart axis)';
COMMENT ON COLUMN finance.kpi_weekly_trend.week_offset IS 'trend_week − report_week: −12 … 0';
COMMENT ON COLUMN finance.kpi_weekly_trend.is_report_week IS 'True on the report week itself (offset 0)';
COMMENT ON COLUMN finance.kpi_weekly_trend.trend_week_label IS 'ISO label of the trend week, e.g. 2025-W23';
COMMENT ON COLUMN finance.kpi_weekly_trend.trend_week_end IS 'Sunday of the trend week';
COMMENT ON COLUMN finance.kpi_weekly_trend.is_warmup IS 'The trend week is a warm-up week (1–13)';
COMMENT ON COLUMN finance.kpi_weekly_trend.invoices_billed IS 'kpi_weekly.invoices_billed of the trend week';
COMMENT ON COLUMN finance.kpi_weekly_trend.billed_sdr IS 'kpi_weekly.billed_sdr of the trend week (SDR)';
COMMENT ON COLUMN finance.kpi_weekly_trend.collected_sdr IS 'kpi_weekly.collected_sdr of the trend week (SDR)';
COMMENT ON COLUMN finance.kpi_weekly_trend.ar_sdr IS 'kpi_weekly.ar_sdr of the trend week (SDR)';
COMMENT ON COLUMN finance.kpi_weekly_trend.overdue_sdr IS 'kpi_weekly.overdue_sdr of the trend week (SDR)';
COMMENT ON COLUMN finance.kpi_weekly_trend.dso_days IS 'kpi_weekly.dso_days of the trend week';
COMMENT ON COLUMN finance.kpi_weekly_trend.budget_sdr IS 'kpi_weekly.budget_sdr of the trend week (SDR)';
COMMENT ON COLUMN finance.kpi_weekly_trend.budget_variance_sdr IS 'kpi_weekly.budget_variance_sdr of the trend week (SDR)';
COMMENT ON COLUMN finance.kpi_weekly_trend.budget_variance_pct IS 'kpi_weekly.budget_variance_pct of the trend week (percent)';
COMMENT ON COLUMN finance.kpi_weekly_trend.top10_share_13w_pct IS 'kpi_weekly.top10_share_13w_pct of the trend week (percent)';

COMMIT;
