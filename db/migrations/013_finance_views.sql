-- =====================================================================
-- 013 — Schema finance: star views + weekly KPI views for the Weekly Finance Pack (Agents plan Phase 2)
-- Decisions: D4 (plain views, ADR-018's preferred shape; no materialized views, no copies), D12 (report_week =
-- ISO week 1–52 of 2025), owner decisions P2-1…P2-9 of 2026-10-14 (plan "Progress"), ADR-003 (SDR), ADR-006 /
-- ADR-034 (RBAC stays a tool predicate; the views are level 2 / Finance), ADR-046 (invoices.status is never used:
-- the payment state comes from payments, the due date = invoice_date + customers.payment_terms_days).
-- Metric definitions: docs/finance_metrics.md. Written by hand; never edited after applying.
-- Conventions: "as of report_week" = as of its Sunday 23:59 (an invoice paid on that Sunday is paid; an invoice
-- issued on it is open). KPI views round once at the end: money 2 decimals (SDR), *_pct in percent with 2
-- decimals, days 1 decimal. Views run with their owner's rights (security_invoker off), so finance_bi reads them
-- without any privilege on public.
-- =====================================================================
BEGIN;

CREATE SCHEMA finance;
COMMENT ON SCHEMA finance IS 'Star views and weekly KPI views of the Weekly Finance Pack over the public tables (Agents plan Phase 2, D4); plain views, no stored data. Level 2, Finance.';

-- ---------------------------------------------------------------- dimensions
CREATE VIEW finance.dim_date AS
SELECT d::date AS date_day,
       extract(isoyear FROM d)::int AS iso_year,
       extract(week FROM d)::int AS iso_week,
       to_char(d, 'IYYY"-W"IW') AS iso_week_label,
       date_trunc('week', d)::date AS week_start,
       (date_trunc('week', d)::date + 6) AS week_end,
       CASE WHEN extract(isoyear FROM d) = 2025 THEN extract(week FROM d)::int END AS report_week,
       extract(isodow FROM d)::int AS iso_dow,
       extract(year FROM d)::int AS calendar_year,
       extract(quarter FROM d)::int AS calendar_quarter,
       extract(month FROM d)::int AS calendar_month
FROM generate_series(DATE '2025-01-01', DATE '2026-03-31', INTERVAL '1 day') AS d;

CREATE VIEW finance.dim_week AS
SELECT w AS report_week,
       format('2025-W%s', lpad(w::text, 2, '0')) AS iso_week_label,
       DATE '2024-12-30' + 7 * (w - 1) AS week_start,
       DATE '2024-12-30' + 7 * (w - 1) + 6 AS week_end,
       greatest(DATE '2024-12-30' + 7 * (w - 1) + 6 - 90, DATE '2025-01-01') AS dso_window_start,
       (DATE '2024-12-30' + 7 * (w - 1) + 6) - greatest(DATE '2024-12-30' + 7 * (w - 1) + 6 - 90, DATE '2025-01-01') + 1 AS dso_window_days,
       (DATE '2024-12-30' + 7 * (w - 1) + 6) - DATE '2025-01-01' + 1 < 91 AS is_warmup
FROM generate_series(1, 52) AS w;

CREATE VIEW finance.dim_customer AS
SELECT customer_id, customer_name, country, segment, payment_terms_days, credit_rating
FROM public.customers;

CREATE VIEW finance.dim_vessel AS
SELECT v.vessel_id, v.imo_number, v.vessel_name, v.vessel_type AS vessel_category, v.flag_country, v.scnt_tons,
       v.condition, v.origin_locode, po.name AS origin_port, v.destination_locode, pd.name AS destination_port,
       v.origin_locode || '-' || v.destination_locode AS route, v.customer_id
FROM public.vessels v
LEFT JOIN public.ports po ON po.locode = v.origin_locode
LEFT JOIN public.ports pd ON pd.locode = v.destination_locode;

CREATE VIEW finance.dim_toll_band AS
SELECT id AS toll_rate_band_id, vessel_category, laden_ballast, band_order, band_label, band_min_tons, band_max_tons,
       rate_sdr_per_ton
FROM public.toll_rate_bands;

-- ---------------------------------------------------------------- facts
CREATE VIEW finance.fact_invoice AS
SELECT i.invoice_id, i.invoice_number, i.invoice_date,
       CASE WHEN extract(isoyear FROM i.invoice_date) = 2025 THEN extract(week FROM i.invoice_date)::int END AS invoice_report_week,
       v.customer_id, i.vessel_id, v.vessel_type AS vessel_category, b.laden_ballast AS priced_condition,
       i.toll_rate_band_id, i.scnt_tons, i.rate_sdr_per_ton, i.amount AS amount_sdr,
       c.payment_terms_days, i.invoice_date + c.payment_terms_days AS due_date,
       p.paid_date, p.paid_date - i.invoice_date AS days_to_pay,
       p.paid_date - (i.invoice_date + c.payment_terms_days) AS days_paid_after_due
FROM public.invoices i
JOIN public.vessels v ON v.vessel_id = i.vessel_id
JOIN public.customers c ON c.customer_id = v.customer_id
LEFT JOIN public.toll_rate_bands b ON b.id = i.toll_rate_band_id
LEFT JOIN public.payments p ON p.invoice_number = i.invoice_number;

CREATE VIEW finance.fact_payment AS
SELECT p.invoice_number, p.paid_date,
       CASE WHEN extract(isoyear FROM p.paid_date) = 2025 THEN extract(week FROM p.paid_date)::int END AS paid_report_week,
       p.amount_sdr, f.invoice_date, f.due_date, f.customer_id, f.vessel_id, f.vessel_category, f.days_to_pay,
       f.days_paid_after_due
FROM public.payments p
JOIN finance.fact_invoice f ON f.invoice_number = p.invoice_number;

-- One row per invoice that is open (issued, not yet paid) at the end of a report week: the as-of status.
CREATE VIEW finance.fact_ar_snapshot AS
SELECT w.report_week, w.week_end AS as_of_date, f.invoice_number, f.invoice_date, f.due_date, f.customer_id,
       f.vessel_id, f.vessel_category, f.amount_sdr,
       w.week_end - f.due_date AS days_past_due,
       w.week_end - f.due_date > 0 AS is_overdue,
       CASE WHEN w.week_end - f.due_date <= 0 THEN 'current'
            WHEN w.week_end - f.due_date <= 30 THEN '1-30'
            WHEN w.week_end - f.due_date <= 60 THEN '31-60'
            WHEN w.week_end - f.due_date <= 90 THEN '61-90'
            ELSE '90+' END AS aging_bucket,
       CASE WHEN w.week_end - f.due_date <= 0 THEN 1
            WHEN w.week_end - f.due_date <= 30 THEN 2
            WHEN w.week_end - f.due_date <= 60 THEN 3
            WHEN w.week_end - f.due_date <= 90 THEN 4
            ELSE 5 END AS aging_bucket_order
FROM finance.dim_week w
JOIN finance.fact_invoice f ON f.invoice_date <= w.week_end AND (f.paid_date IS NULL OR f.paid_date > w.week_end);

-- ---------------------------------------------------------------- KPI views (one row per report_week [× key])
CREATE VIEW finance.kpi_customer_13w AS
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
    FROM billing b)
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
LEFT JOIN open_ar o ON o.report_week = r.report_week AND o.customer_id = r.customer_id;

CREATE VIEW finance.kpi_weekly AS
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
    LEFT JOIN concentration k ON k.report_week = w.report_week)
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
WINDOW wk AS (ORDER BY report_week);

CREATE VIEW finance.kpi_weekly_category AS
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
       round(100 * (billed_sdr - lag(billed_sdr) OVER cw) / NULLIF(lag(billed_sdr) OVER cw, 0), 2) AS billed_wow_pct
FROM base
WINDOW cw AS (PARTITION BY vessel_category ORDER BY report_week);

CREATE VIEW finance.kpi_overdue_list AS
SELECT a.report_week, a.as_of_date, a.invoice_number, a.customer_id, c.customer_name, a.vessel_id, v.vessel_name,
       a.vessel_category, a.invoice_date, a.due_date, a.amount_sdr, a.days_past_due, a.aging_bucket,
       row_number() OVER (PARTITION BY a.report_week ORDER BY a.amount_sdr DESC, a.invoice_number) AS rank_by_amount
FROM finance.fact_ar_snapshot a
JOIN public.customers c ON c.customer_id = a.customer_id
JOIN public.vessels v ON v.vessel_id = a.vessel_id
WHERE a.is_overdue;

-- ---------------------------------------------------------------- comments (read by the future tools, ADR-033)
COMMENT ON VIEW finance.dim_date IS 'Calendar 2025-01-01 → 2026-03-31 (the payments horizon), one row per day, with its ISO week. Level 2, Finance (schema level).';
COMMENT ON COLUMN finance.dim_date.date_day IS 'The day';
COMMENT ON COLUMN finance.dim_date.iso_year IS 'ISO-8601 week-numbering year (2025-12-29..31 belong to 2026)';
COMMENT ON COLUMN finance.dim_date.iso_week IS 'ISO-8601 week number 1–53 (Monday to Sunday)';
COMMENT ON COLUMN finance.dim_date.iso_week_label IS 'ISO week as text, e.g. 2025-W05';
COMMENT ON COLUMN finance.dim_date.week_start IS 'Monday of the ISO week';
COMMENT ON COLUMN finance.dim_date.week_end IS 'Sunday of the ISO week (the "as of" day of a report)';
COMMENT ON COLUMN finance.dim_date.report_week IS 'Report week 1–52 (ISO weeks of 2025, D12); NULL for days of ISO 2026';
COMMENT ON COLUMN finance.dim_date.iso_dow IS 'ISO day of week, 1 = Monday … 7 = Sunday';
COMMENT ON COLUMN finance.dim_date.calendar_year IS 'Calendar year';
COMMENT ON COLUMN finance.dim_date.calendar_quarter IS 'Calendar quarter 1–4';
COMMENT ON COLUMN finance.dim_date.calendar_month IS 'Calendar month 1–12';

COMMENT ON VIEW finance.dim_week IS 'The 52 report weeks (ISO weeks of 2025, D12) with the DSO window. Level 2, Finance (schema level).';
COMMENT ON COLUMN finance.dim_week.report_week IS 'Report week 1–52 = ISO week of 2025';
COMMENT ON COLUMN finance.dim_week.iso_week_label IS 'ISO week as text, e.g. 2025-W05';
COMMENT ON COLUMN finance.dim_week.week_start IS 'Monday of the week';
COMMENT ON COLUMN finance.dim_week.week_end IS 'Sunday of the week: every "as of" metric is measured at its end (23:59)';
COMMENT ON COLUMN finance.dim_week.dso_window_start IS 'First day of the DSO window: week_end − 90 days, not before 2025-01-01 (start of the billing history)';
COMMENT ON COLUMN finance.dim_week.dso_window_days IS 'Length of the DSO window in days: 91, or fewer in the warm-up weeks';
COMMENT ON COLUMN finance.dim_week.is_warmup IS 'True for weeks 1–13: less than 91 days of billing history, receivables still building up from zero (no 2024 invoices); DSO uses the shorter window (owner decision P2-2)';

COMMENT ON VIEW finance.dim_customer IS 'Billed customers (shipping lines and agents, synthetic). Level 2, Finance.';
COMMENT ON COLUMN finance.dim_customer.customer_id IS 'Customer id';
COMMENT ON COLUMN finance.dim_customer.customer_name IS 'Invented company name (no real company)';
COMMENT ON COLUMN finance.dim_customer.country IS 'Head-office country';
COMMENT ON COLUMN finance.dim_customer.segment IS 'container, tanker, bulk, roro, cruise or agent';
COMMENT ON COLUMN finance.dim_customer.payment_terms_days IS 'Payment terms in days (30, 45 or 60): due date = invoice date + terms';
COMMENT ON COLUMN finance.dim_customer.credit_rating IS 'Credit rating A, B or C';

COMMENT ON VIEW finance.dim_vessel IS 'Vessels with their category, route (port names) and billed customer. Level 2, Finance (schema level; the vessels table is level 1).';
COMMENT ON COLUMN finance.dim_vessel.vessel_id IS 'Vessel id';
COMMENT ON COLUMN finance.dim_vessel.imo_number IS 'IMO number (7 digits, synthetic)';
COMMENT ON COLUMN finance.dim_vessel.vessel_name IS 'Vessel name';
COMMENT ON COLUMN finance.dim_vessel.vessel_category IS 'Suez tariff vessel category (13 values) = vessels.vessel_type; the budget is set per category';
COMMENT ON COLUMN finance.dim_vessel.flag_country IS 'Flag state';
COMMENT ON COLUMN finance.dim_vessel.scnt_tons IS 'Suez Canal Net Tonnage';
COMMENT ON COLUMN finance.dim_vessel.condition IS 'Laden or Ballast (vessel record)';
COMMENT ON COLUMN finance.dim_vessel.origin_locode IS 'Origin port UN/LOCODE';
COMMENT ON COLUMN finance.dim_vessel.origin_port IS 'Origin port name';
COMMENT ON COLUMN finance.dim_vessel.destination_locode IS 'Destination port UN/LOCODE';
COMMENT ON COLUMN finance.dim_vessel.destination_port IS 'Destination port name';
COMMENT ON COLUMN finance.dim_vessel.route IS 'origin-destination LOCODE pair';
COMMENT ON COLUMN finance.dim_vessel.customer_id IS 'The customer billed for this vessel';

COMMENT ON VIEW finance.dim_toll_band IS 'Suez transit dues bands (progressive, SDR per SCNT; ADR-004). Level 2, Finance (schema level; the tariff table is level 1).';
COMMENT ON COLUMN finance.dim_toll_band.toll_rate_band_id IS 'Band id (toll_rate_bands.id)';
COMMENT ON COLUMN finance.dim_toll_band.vessel_category IS 'Tariff vessel category';
COMMENT ON COLUMN finance.dim_toll_band.laden_ballast IS 'Laden or Ballast';
COMMENT ON COLUMN finance.dim_toll_band.band_order IS 'Band position 1–8 within the category and condition';
COMMENT ON COLUMN finance.dim_toll_band.band_label IS 'Band label as printed in the tariff';
COMMENT ON COLUMN finance.dim_toll_band.band_min_tons IS 'Lower bound of the band (SCNT)';
COMMENT ON COLUMN finance.dim_toll_band.band_max_tons IS 'Upper bound of the band (SCNT); NULL = open-ended';
COMMENT ON COLUMN finance.dim_toll_band.rate_sdr_per_ton IS 'Rate in SDR per SCNT inside the band';

COMMENT ON VIEW finance.fact_invoice IS 'One row per invoice with the derived due date and its payment (ADR-046: invoices.status is a label and is not used). Level 2, Finance.';
COMMENT ON COLUMN finance.fact_invoice.invoice_id IS 'Invoice id';
COMMENT ON COLUMN finance.fact_invoice.invoice_number IS 'Invoice number INV-nnnnnnn';
COMMENT ON COLUMN finance.fact_invoice.invoice_date IS 'Invoice (billing) date: revenue is counted in its week';
COMMENT ON COLUMN finance.fact_invoice.invoice_report_week IS 'Report week of the invoice date; NULL for 2025-12-29..31 (ISO 2026-W01)';
COMMENT ON COLUMN finance.fact_invoice.customer_id IS 'Billed customer (through the vessel)';
COMMENT ON COLUMN finance.fact_invoice.vessel_id IS 'Vessel id';
COMMENT ON COLUMN finance.fact_invoice.vessel_category IS 'Vessel category (13 tariff categories)';
COMMENT ON COLUMN finance.fact_invoice.priced_condition IS 'Laden or Ballast as priced (from the terminal band; Special Floating Units always Laden)';
COMMENT ON COLUMN finance.fact_invoice.toll_rate_band_id IS 'Terminal band containing the vessel SCNT';
COMMENT ON COLUMN finance.fact_invoice.scnt_tons IS 'Billed Suez Canal Net Tonnage';
COMMENT ON COLUMN finance.fact_invoice.rate_sdr_per_ton IS 'Rate of the terminal band (SDR per SCNT)';
COMMENT ON COLUMN finance.fact_invoice.amount_sdr IS 'Invoice amount in SDR (progressive toll, ADR-003 / ADR-004)';
COMMENT ON COLUMN finance.fact_invoice.payment_terms_days IS 'Customer payment terms in days';
COMMENT ON COLUMN finance.fact_invoice.due_date IS 'Derived due date = invoice_date + payment_terms_days (not stored, ADR-046)';
COMMENT ON COLUMN finance.fact_invoice.paid_date IS 'Date of the single full payment; NULL = unpaid at the 2026-03-31 horizon';
COMMENT ON COLUMN finance.fact_invoice.days_to_pay IS 'paid_date − invoice_date in days; NULL if unpaid';
COMMENT ON COLUMN finance.fact_invoice.days_paid_after_due IS 'paid_date − due_date in days (negative = paid early); NULL if unpaid';

COMMENT ON VIEW finance.fact_payment IS 'One row per payment (one full payment per paid invoice): collections are counted in the week of paid_date. Level 2, Finance.';
COMMENT ON COLUMN finance.fact_payment.invoice_number IS 'Paid invoice';
COMMENT ON COLUMN finance.fact_payment.paid_date IS 'Payment date';
COMMENT ON COLUMN finance.fact_payment.paid_report_week IS 'Report week of the payment; NULL for payments in ISO 2026';
COMMENT ON COLUMN finance.fact_payment.amount_sdr IS 'Amount received in SDR (= the invoice amount)';
COMMENT ON COLUMN finance.fact_payment.invoice_date IS 'Invoice date of the paid invoice';
COMMENT ON COLUMN finance.fact_payment.due_date IS 'Derived due date of the paid invoice';
COMMENT ON COLUMN finance.fact_payment.customer_id IS 'Paying customer';
COMMENT ON COLUMN finance.fact_payment.vessel_id IS 'Vessel of the paid invoice';
COMMENT ON COLUMN finance.fact_payment.vessel_category IS 'Vessel category of the paid invoice';
COMMENT ON COLUMN finance.fact_payment.days_to_pay IS 'paid_date − invoice_date in days';
COMMENT ON COLUMN finance.fact_payment.days_paid_after_due IS 'paid_date − due_date in days (negative = paid early)';

COMMENT ON VIEW finance.fact_ar_snapshot IS 'Receivables as of each report week: one row per invoice issued on or before the week''s Sunday and not paid by then, with its age past due. Level 2, Finance.';
COMMENT ON COLUMN finance.fact_ar_snapshot.report_week IS 'Report week';
COMMENT ON COLUMN finance.fact_ar_snapshot.as_of_date IS 'Sunday of the report week (as of 23:59)';
COMMENT ON COLUMN finance.fact_ar_snapshot.invoice_number IS 'Open invoice';
COMMENT ON COLUMN finance.fact_ar_snapshot.invoice_date IS 'Invoice date';
COMMENT ON COLUMN finance.fact_ar_snapshot.due_date IS 'Derived due date';
COMMENT ON COLUMN finance.fact_ar_snapshot.customer_id IS 'Billed customer';
COMMENT ON COLUMN finance.fact_ar_snapshot.vessel_id IS 'Vessel id';
COMMENT ON COLUMN finance.fact_ar_snapshot.vessel_category IS 'Vessel category';
COMMENT ON COLUMN finance.fact_ar_snapshot.amount_sdr IS 'Open amount in SDR (no partial payments: the full invoice amount)';
COMMENT ON COLUMN finance.fact_ar_snapshot.days_past_due IS 'as_of_date − due_date in days (≤ 0 = not yet due)';
COMMENT ON COLUMN finance.fact_ar_snapshot.is_overdue IS 'True when days_past_due ≥ 1';
COMMENT ON COLUMN finance.fact_ar_snapshot.aging_bucket IS 'current (≤ 0), 1-30, 31-60, 61-90 or 90+ days past due';
COMMENT ON COLUMN finance.fact_ar_snapshot.aging_bucket_order IS 'Sort order of aging_bucket, 1 = current … 5 = 90+';

COMMENT ON VIEW finance.kpi_customer_13w IS 'Every customer in every report week: billing of the week and of the trailing 13 weeks (91 days ending Sunday), share, rank, receivables. Level 2, Finance.';
COMMENT ON COLUMN finance.kpi_customer_13w.report_week IS 'Report week';
COMMENT ON COLUMN finance.kpi_customer_13w.customer_id IS 'Customer id';
COMMENT ON COLUMN finance.kpi_customer_13w.customer_name IS 'Customer name';
COMMENT ON COLUMN finance.kpi_customer_13w.segment IS 'Customer segment';
COMMENT ON COLUMN finance.kpi_customer_13w.country IS 'Head-office country';
COMMENT ON COLUMN finance.kpi_customer_13w.credit_rating IS 'Credit rating A, B or C';
COMMENT ON COLUMN finance.kpi_customer_13w.payment_terms_days IS 'Payment terms in days';
COMMENT ON COLUMN finance.kpi_customer_13w.billed_week_sdr IS 'Billed in the report week (SDR, 2 decimals)';
COMMENT ON COLUMN finance.kpi_customer_13w.billed_13w_sdr IS 'Billed in the trailing 13 weeks = 91 days ending the week''s Sunday (SDR, 2 decimals)';
COMMENT ON COLUMN finance.kpi_customer_13w.share_13w_pct IS 'Share of all billing in the trailing 13 weeks, percent (2 decimals)';
COMMENT ON COLUMN finance.kpi_customer_13w.rank_13w IS 'Rank by billed_13w_sdr (1 = largest; ties by customer_id)';
COMMENT ON COLUMN finance.kpi_customer_13w.rank_13w_prev IS 'rank_13w in the previous report week; NULL in week 1';
COMMENT ON COLUMN finance.kpi_customer_13w.is_top10 IS 'True for ranks 1–10 with billing > 0 in the trailing 13 weeks';
COMMENT ON COLUMN finance.kpi_customer_13w.ar_sdr IS 'Open receivables of the customer as of the week''s Sunday (SDR)';
COMMENT ON COLUMN finance.kpi_customer_13w.overdue_sdr IS 'Overdue part of ar_sdr (SDR)';

COMMENT ON VIEW finance.kpi_weekly IS 'Company KPIs, one row per report week (definitions: docs/finance_metrics.md). Money SDR 2 decimals, *_pct percent 2 decimals, days 1 decimal; WoW NULL in week 1. Level 2, Finance.';
COMMENT ON COLUMN finance.kpi_weekly.report_week IS 'Report week 1–52';
COMMENT ON COLUMN finance.kpi_weekly.iso_week_label IS 'ISO week as text';
COMMENT ON COLUMN finance.kpi_weekly.week_start IS 'Monday of the week';
COMMENT ON COLUMN finance.kpi_weekly.week_end IS 'Sunday of the week (as of 23:59)';
COMMENT ON COLUMN finance.kpi_weekly.is_warmup IS 'Weeks 1–13: under 91 days of history, receivables still building up; DSO on a shorter window';
COMMENT ON COLUMN finance.kpi_weekly.invoices_billed IS 'Number of invoices dated in the week';
COMMENT ON COLUMN finance.kpi_weekly.billed_sdr IS 'Billed revenue: sum of invoice amounts dated in the week (SDR)';
COMMENT ON COLUMN finance.kpi_weekly.payments_received IS 'Number of payments dated in the week';
COMMENT ON COLUMN finance.kpi_weekly.collected_sdr IS 'Collections: sum of payments dated in the week (SDR)';
COMMENT ON COLUMN finance.kpi_weekly.ar_invoices IS 'Number of open invoices at the week end';
COMMENT ON COLUMN finance.kpi_weekly.ar_sdr IS 'Accounts receivable at the week end: invoices issued by Sunday and unpaid by Sunday (SDR)';
COMMENT ON COLUMN finance.kpi_weekly.overdue_invoices IS 'Number of open invoices at least 1 day past due';
COMMENT ON COLUMN finance.kpi_weekly.overdue_sdr IS 'Overdue receivables (≥ 1 day past due) at the week end (SDR)';
COMMENT ON COLUMN finance.kpi_weekly.aging_current_sdr IS 'Receivables not yet due (SDR)';
COMMENT ON COLUMN finance.kpi_weekly.aging_1_30_sdr IS 'Receivables 1–30 days past due (SDR)';
COMMENT ON COLUMN finance.kpi_weekly.aging_31_60_sdr IS 'Receivables 31–60 days past due (SDR)';
COMMENT ON COLUMN finance.kpi_weekly.aging_61_90_sdr IS 'Receivables 61–90 days past due (SDR)';
COMMENT ON COLUMN finance.kpi_weekly.aging_90_plus_sdr IS 'Receivables more than 90 days past due (SDR)';
COMMENT ON COLUMN finance.kpi_weekly.dso_window_days IS 'Days in the DSO window (91, fewer in warm-up weeks)';
COMMENT ON COLUMN finance.kpi_weekly.dso_window_billed_sdr IS 'Billed revenue inside the DSO window (SDR)';
COMMENT ON COLUMN finance.kpi_weekly.dso_days IS 'DSO = ar_sdr ÷ dso_window_billed_sdr × dso_window_days (owner decision P2-1), 1 decimal';
COMMENT ON COLUMN finance.kpi_weekly.budget_sdr IS 'Weekly budget, all categories (SDR)';
COMMENT ON COLUMN finance.kpi_weekly.budget_variance_sdr IS 'billed_sdr − budget_sdr (SDR)';
COMMENT ON COLUMN finance.kpi_weekly.budget_variance_pct IS '(billed − budget) ÷ budget, percent';
COMMENT ON COLUMN finance.kpi_weekly.top10_share_13w_pct IS 'Share of the 10 largest customers in the trailing 13 weeks'' billing, percent';
COMMENT ON COLUMN finance.kpi_weekly.billed_wow_pct IS 'Billed revenue change vs the previous week, percent';
COMMENT ON COLUMN finance.kpi_weekly.collected_wow_pct IS 'Collections change vs the previous week, percent';
COMMENT ON COLUMN finance.kpi_weekly.ar_wow_pct IS 'Receivables change vs the previous week, percent';
COMMENT ON COLUMN finance.kpi_weekly.overdue_wow_pct IS 'Overdue receivables change vs the previous week, percent';
COMMENT ON COLUMN finance.kpi_weekly.dso_wow_days IS 'DSO change vs the previous week, in days';

COMMENT ON VIEW finance.kpi_weekly_category IS 'Billing vs budget per report week and vessel category (52 × 13 rows); the week''s drivers = largest |billed_wow_change_sdr|. Level 2, Finance.';
COMMENT ON COLUMN finance.kpi_weekly_category.report_week IS 'Report week';
COMMENT ON COLUMN finance.kpi_weekly_category.vessel_category IS 'Vessel category (13 tariff categories)';
COMMENT ON COLUMN finance.kpi_weekly_category.invoices_billed IS 'Invoices of the category dated in the week';
COMMENT ON COLUMN finance.kpi_weekly_category.billed_sdr IS 'Billed revenue of the category in the week (SDR)';
COMMENT ON COLUMN finance.kpi_weekly_category.budget_sdr IS 'Budget of the category for the week (SDR)';
COMMENT ON COLUMN finance.kpi_weekly_category.budget_variance_sdr IS 'billed_sdr − budget_sdr (SDR)';
COMMENT ON COLUMN finance.kpi_weekly_category.budget_variance_pct IS '(billed − budget) ÷ budget, percent';
COMMENT ON COLUMN finance.kpi_weekly_category.billed_prev_sdr IS 'Billed revenue of the category in the previous week (SDR); NULL in week 1';
COMMENT ON COLUMN finance.kpi_weekly_category.billed_wow_change_sdr IS 'billed_sdr − billed_prev_sdr (SDR)';
COMMENT ON COLUMN finance.kpi_weekly_category.billed_wow_pct IS 'Change vs the previous week, percent; NULL when the previous week was 0';

COMMENT ON VIEW finance.kpi_overdue_list IS 'Overdue invoices (≥ 1 day past due) as of each report week, ranked by amount. Level 2, Finance.';
COMMENT ON COLUMN finance.kpi_overdue_list.report_week IS 'Report week';
COMMENT ON COLUMN finance.kpi_overdue_list.as_of_date IS 'Sunday of the report week';
COMMENT ON COLUMN finance.kpi_overdue_list.invoice_number IS 'Overdue invoice';
COMMENT ON COLUMN finance.kpi_overdue_list.customer_id IS 'Customer id';
COMMENT ON COLUMN finance.kpi_overdue_list.customer_name IS 'Customer name';
COMMENT ON COLUMN finance.kpi_overdue_list.vessel_id IS 'Vessel id';
COMMENT ON COLUMN finance.kpi_overdue_list.vessel_name IS 'Vessel name';
COMMENT ON COLUMN finance.kpi_overdue_list.vessel_category IS 'Vessel category';
COMMENT ON COLUMN finance.kpi_overdue_list.invoice_date IS 'Invoice date';
COMMENT ON COLUMN finance.kpi_overdue_list.due_date IS 'Derived due date';
COMMENT ON COLUMN finance.kpi_overdue_list.amount_sdr IS 'Open amount (SDR)';
COMMENT ON COLUMN finance.kpi_overdue_list.days_past_due IS 'Days past due as of the Sunday';
COMMENT ON COLUMN finance.kpi_overdue_list.aging_bucket IS '1-30, 31-60, 61-90 or 90+';
COMMENT ON COLUMN finance.kpi_overdue_list.rank_by_amount IS 'Rank within the week by amount (1 = largest)';

-- ---------------------------------------------------------------- access (ADR-034; owner decision P2-6)
GRANT USAGE ON SCHEMA finance TO ports_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA finance TO ports_readonly;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA finance GRANT SELECT ON TABLES TO ports_readonly;

CREATE ROLE finance_bi NOLOGIN;
COMMENT ON ROLE finance_bi IS 'Least privilege for Power BI (Agents plan Phase 3): SELECT on schema finance only, nothing in public. A login user joins it (created in Phase 3 from .env); set default_transaction_read_only on that login too (role settings are not inherited).';
GRANT CONNECT ON DATABASE ports_logistics TO finance_bi;
GRANT USAGE ON SCHEMA finance TO finance_bi;
GRANT SELECT ON ALL TABLES IN SCHEMA finance TO finance_bi;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA finance GRANT SELECT ON TABLES TO finance_bi;
ALTER ROLE finance_bi SET default_transaction_read_only = on;

COMMIT;
