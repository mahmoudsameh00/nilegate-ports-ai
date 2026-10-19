-- =====================================================================
-- 015 — Invoice audit views: finance.invoice_audit + its twin finance_test.invoice_audit (Agents plan §5a S4,
--       owner decisions P4-2, P4-5, P4-6 of 2026-10-18)
-- Why: the Invoice Auditor recomputes every invoice from the progressive toll bands (ADR-004) and explains each
-- exception with fixed, deterministic checks, so the agents never guess a cause. A view (not Python only) gives one
-- definition to the agent tool `invoice_audit` and to the dashboard's Exceptions page (DirectQuery, ADR-048); an
-- independent Python compute_toll checks the expected amounts (pipelines/scripts/agents/Tools_check.py).
-- The twin view reads the evaluation copy (Agents plan §4a R7) and lives in schema finance_test, so Power BI
-- (finance_bi: schema finance only) never sees it and the copy is never mixed with the real tables. Both views are
-- the same SQL except the first CTE `billed`, which maps each source to the same columns (the check compares them).
-- Checks (one row per finding):
--   duplicate_charge  same vessel, date and amount under another number; the lowest number is the original
--   tonnage_mismatch  invoice SCNT <> the vessel's SCNT
--   amount_mismatch   |billed - expected| > 0.01 SDR (the rounding of ADR-004); probable_cause = the first
--                     hypothesis that reproduces the billed amount within 0.01: billed_on_invoice_tonnage,
--                     flat_terminal_rate, condition_swapped, sfu_priced_ballast; else unexplained
--   rate_mismatch     stored rate <> the terminal band's rate (live invoices only: the copy stores no rate)
-- Expected = the toll of the vessel's category, condition (Special Floating Units -> Laden) and SCNT. A duplicate's
-- expected charge is 0 and it gets no other check (the original carries them).
-- Decisions: ADR-004, ADR-046 (finance_test), ADR-047 (plain views, no functions). Grants come from the default
-- privileges of migrations 012 / 013 (ports_readonly both views; finance_bi finance.invoice_audit only).
-- Written by hand; never edited after applying.
-- =====================================================================
BEGIN;

CREATE VIEW finance.invoice_audit AS
WITH billed AS (
    SELECT i.invoice_number, i.vessel_id, i.invoice_date, i.scnt_tons, i.amount AS billed_sdr,
           i.rate_sdr_per_ton AS billed_rate
    FROM public.invoices i
), inv AS (
    SELECT b.invoice_number, b.vessel_id, b.invoice_date, b.scnt_tons, b.billed_sdr, b.billed_rate,
           v.vessel_name, v.vessel_type AS vessel_category, v.condition, v.scnt_tons AS vessel_scnt,
           CASE WHEN v.vessel_type = 'Special Floating Units' THEN 'Laden' ELSE v.condition END AS priced_condition,
           d.report_week
    FROM billed b
    JOIN public.vessels v ON v.vessel_id = b.vessel_id
    JOIN finance.dim_date d ON d.date_day = b.invoice_date
), scenario AS (
    SELECT invoice_number, 'expected' AS scenario, vessel_category AS category, priced_condition AS cond,
           vessel_scnt AS tons FROM inv
    UNION ALL
    SELECT invoice_number, 'invoice_tonnage', vessel_category, priced_condition, scnt_tons FROM inv
    WHERE scnt_tons <> vessel_scnt
    UNION ALL
    SELECT invoice_number, 'condition_swapped', vessel_category,
           CASE condition WHEN 'Laden' THEN 'Ballast' ELSE 'Laden' END, vessel_scnt FROM inv
    WHERE vessel_category <> 'Special Floating Units'
    UNION ALL
    SELECT invoice_number, 'sfu_priced_ballast', 'Other Vessels', 'Ballast', vessel_scnt FROM inv
    WHERE vessel_category = 'Special Floating Units'
), priced AS (
    SELECT s.invoice_number, s.scenario,
           sum(t.rate_sdr_per_ton * (LEAST(s.tons, COALESCE(t.band_max_tons, s.tons)) - t.band_min_tons)) AS toll_exact,
           (array_agg(t.rate_sdr_per_ton ORDER BY t.band_order DESC))[1] AS terminal_rate,
           (array_agg(t.band_label ORDER BY t.band_order DESC))[1] AS terminal_band
    FROM scenario s
    JOIN public.toll_rate_bands t
      ON t.vessel_category = s.category AND t.laden_ballast = s.cond AND s.tons > t.band_min_tons
    GROUP BY s.invoice_number, s.scenario
), hyp AS (
    SELECT i.*, e.toll_exact AS expected_exact, round(e.toll_exact, 2) AS expected_sdr, e.terminal_rate,
           e.terminal_band,
           round(it.toll_exact, 2) AS invoice_tonnage_sdr,
           round(e.terminal_rate * i.vessel_scnt, 2) AS flat_terminal_sdr,
           round(cs.toll_exact, 2) AS condition_swapped_sdr,
           round(sb.toll_exact, 2) AS sfu_ballast_sdr,
           row_number() OVER w AS dup_rank,
           first_value(i.invoice_number) OVER w AS dup_first
    FROM inv i
    JOIN priced e ON e.invoice_number = i.invoice_number AND e.scenario = 'expected'
    LEFT JOIN priced it ON it.invoice_number = i.invoice_number AND it.scenario = 'invoice_tonnage'
    LEFT JOIN priced cs ON cs.invoice_number = i.invoice_number AND cs.scenario = 'condition_swapped'
    LEFT JOIN priced sb ON sb.invoice_number = i.invoice_number AND sb.scenario = 'sfu_priced_ballast'
    WINDOW w AS (PARTITION BY i.vessel_id, i.invoice_date, i.billed_sdr ORDER BY i.invoice_number)
), findings AS (
    SELECT h.*, 'duplicate_charge' AS check_code, NULL::text AS probable_cause, 0::numeric AS expected_charge,
           h.dup_first AS duplicate_of,
           format('same vessel, date and amount as %s: the whole charge is billed twice', h.dup_first) AS evidence
    FROM hyp h WHERE h.dup_rank > 1
    UNION ALL
    SELECT h.*, 'tonnage_mismatch', NULL, h.expected_sdr, NULL,
           format('invoice SCNT %s <> vessel SCNT %s', h.scnt_tons, h.vessel_scnt)
    FROM hyp h WHERE h.dup_rank = 1 AND h.scnt_tons <> h.vessel_scnt
    UNION ALL
    SELECT h.*, 'amount_mismatch',
           CASE WHEN abs(h.billed_sdr - h.invoice_tonnage_sdr) <= 0.01 THEN 'billed_on_invoice_tonnage'
                WHEN abs(h.billed_sdr - h.flat_terminal_sdr) <= 0.01 THEN 'flat_terminal_rate'
                WHEN abs(h.billed_sdr - h.condition_swapped_sdr) <= 0.01 THEN 'condition_swapped'
                WHEN abs(h.billed_sdr - h.sfu_ballast_sdr) <= 0.01 THEN 'sfu_priced_ballast'
                ELSE 'unexplained' END,
           h.expected_sdr, NULL,
           format('billed %s SDR; tariff %s / %s at %s SCNT = %s SDR (progressive, terminal band %s at %s SDR/t)',
                  h.billed_sdr, h.vessel_category, h.priced_condition, h.vessel_scnt, h.expected_sdr,
                  h.terminal_band, h.terminal_rate)
    FROM hyp h WHERE h.dup_rank = 1 AND abs(h.billed_sdr - h.expected_exact) > 0.01
    UNION ALL
    SELECT h.*, 'rate_mismatch', NULL, h.expected_sdr, NULL,
           format('stored rate %s SDR/t <> terminal band %s rate %s SDR/t', h.billed_rate, h.terminal_band,
                  h.terminal_rate)
    FROM hyp h WHERE h.dup_rank = 1 AND h.billed_rate IS NOT NULL AND h.billed_rate <> h.terminal_rate
)
SELECT report_week, invoice_number, invoice_date, vessel_id, vessel_name, vessel_category,
       condition AS vessel_condition, check_code, probable_cause, billed_sdr, expected_charge AS expected_sdr,
       round(billed_sdr - expected_charge, 2) AS difference_sdr, duplicate_of, evidence
FROM findings;

CREATE VIEW finance_test.invoice_audit AS
WITH billed AS (
    SELECT i.invoice_number, i.vessel_id, i.invoice_date, i.scnt_tons, i.billed_sdr,
           NULL::numeric AS billed_rate
    FROM finance_test.invoices i
), inv AS (
    SELECT b.invoice_number, b.vessel_id, b.invoice_date, b.scnt_tons, b.billed_sdr, b.billed_rate,
           v.vessel_name, v.vessel_type AS vessel_category, v.condition, v.scnt_tons AS vessel_scnt,
           CASE WHEN v.vessel_type = 'Special Floating Units' THEN 'Laden' ELSE v.condition END AS priced_condition,
           d.report_week
    FROM billed b
    JOIN public.vessels v ON v.vessel_id = b.vessel_id
    JOIN finance.dim_date d ON d.date_day = b.invoice_date
), scenario AS (
    SELECT invoice_number, 'expected' AS scenario, vessel_category AS category, priced_condition AS cond,
           vessel_scnt AS tons FROM inv
    UNION ALL
    SELECT invoice_number, 'invoice_tonnage', vessel_category, priced_condition, scnt_tons FROM inv
    WHERE scnt_tons <> vessel_scnt
    UNION ALL
    SELECT invoice_number, 'condition_swapped', vessel_category,
           CASE condition WHEN 'Laden' THEN 'Ballast' ELSE 'Laden' END, vessel_scnt FROM inv
    WHERE vessel_category <> 'Special Floating Units'
    UNION ALL
    SELECT invoice_number, 'sfu_priced_ballast', 'Other Vessels', 'Ballast', vessel_scnt FROM inv
    WHERE vessel_category = 'Special Floating Units'
), priced AS (
    SELECT s.invoice_number, s.scenario,
           sum(t.rate_sdr_per_ton * (LEAST(s.tons, COALESCE(t.band_max_tons, s.tons)) - t.band_min_tons)) AS toll_exact,
           (array_agg(t.rate_sdr_per_ton ORDER BY t.band_order DESC))[1] AS terminal_rate,
           (array_agg(t.band_label ORDER BY t.band_order DESC))[1] AS terminal_band
    FROM scenario s
    JOIN public.toll_rate_bands t
      ON t.vessel_category = s.category AND t.laden_ballast = s.cond AND s.tons > t.band_min_tons
    GROUP BY s.invoice_number, s.scenario
), hyp AS (
    SELECT i.*, e.toll_exact AS expected_exact, round(e.toll_exact, 2) AS expected_sdr, e.terminal_rate,
           e.terminal_band,
           round(it.toll_exact, 2) AS invoice_tonnage_sdr,
           round(e.terminal_rate * i.vessel_scnt, 2) AS flat_terminal_sdr,
           round(cs.toll_exact, 2) AS condition_swapped_sdr,
           round(sb.toll_exact, 2) AS sfu_ballast_sdr,
           row_number() OVER w AS dup_rank,
           first_value(i.invoice_number) OVER w AS dup_first
    FROM inv i
    JOIN priced e ON e.invoice_number = i.invoice_number AND e.scenario = 'expected'
    LEFT JOIN priced it ON it.invoice_number = i.invoice_number AND it.scenario = 'invoice_tonnage'
    LEFT JOIN priced cs ON cs.invoice_number = i.invoice_number AND cs.scenario = 'condition_swapped'
    LEFT JOIN priced sb ON sb.invoice_number = i.invoice_number AND sb.scenario = 'sfu_priced_ballast'
    WINDOW w AS (PARTITION BY i.vessel_id, i.invoice_date, i.billed_sdr ORDER BY i.invoice_number)
), findings AS (
    SELECT h.*, 'duplicate_charge' AS check_code, NULL::text AS probable_cause, 0::numeric AS expected_charge,
           h.dup_first AS duplicate_of,
           format('same vessel, date and amount as %s: the whole charge is billed twice', h.dup_first) AS evidence
    FROM hyp h WHERE h.dup_rank > 1
    UNION ALL
    SELECT h.*, 'tonnage_mismatch', NULL, h.expected_sdr, NULL,
           format('invoice SCNT %s <> vessel SCNT %s', h.scnt_tons, h.vessel_scnt)
    FROM hyp h WHERE h.dup_rank = 1 AND h.scnt_tons <> h.vessel_scnt
    UNION ALL
    SELECT h.*, 'amount_mismatch',
           CASE WHEN abs(h.billed_sdr - h.invoice_tonnage_sdr) <= 0.01 THEN 'billed_on_invoice_tonnage'
                WHEN abs(h.billed_sdr - h.flat_terminal_sdr) <= 0.01 THEN 'flat_terminal_rate'
                WHEN abs(h.billed_sdr - h.condition_swapped_sdr) <= 0.01 THEN 'condition_swapped'
                WHEN abs(h.billed_sdr - h.sfu_ballast_sdr) <= 0.01 THEN 'sfu_priced_ballast'
                ELSE 'unexplained' END,
           h.expected_sdr, NULL,
           format('billed %s SDR; tariff %s / %s at %s SCNT = %s SDR (progressive, terminal band %s at %s SDR/t)',
                  h.billed_sdr, h.vessel_category, h.priced_condition, h.vessel_scnt, h.expected_sdr,
                  h.terminal_band, h.terminal_rate)
    FROM hyp h WHERE h.dup_rank = 1 AND abs(h.billed_sdr - h.expected_exact) > 0.01
    UNION ALL
    SELECT h.*, 'rate_mismatch', NULL, h.expected_sdr, NULL,
           format('stored rate %s SDR/t <> terminal band %s rate %s SDR/t', h.billed_rate, h.terminal_band,
                  h.terminal_rate)
    FROM hyp h WHERE h.dup_rank = 1 AND h.billed_rate IS NOT NULL AND h.billed_rate <> h.terminal_rate
)
SELECT report_week, invoice_number, invoice_date, vessel_id, vessel_name, vessel_category,
       condition AS vessel_condition, check_code, probable_cause, billed_sdr, expected_charge AS expected_sdr,
       round(billed_sdr - expected_charge, 2) AS difference_sdr, duplicate_of, evidence
FROM findings;

COMMENT ON VIEW finance.invoice_audit IS 'Invoice audit findings (Agents plan §5a, migration 015): every invoice recomputed from the progressive toll bands (ADR-004); one row per finding (duplicate_charge, tonnage_mismatch, amount_mismatch with a probable cause, rate_mismatch). No row = the invoice passed. Read by the invoice_audit tool and the Exceptions page. Level 2, Finance.';
COMMENT ON VIEW finance_test.invoice_audit IS 'The same audit over the evaluation copy finance_test.invoices (Agents plan §4a R7; same SQL as finance.invoice_audit except the source CTE). Evaluation only; invisible to Power BI. Level 2, Finance.';

COMMENT ON COLUMN finance.invoice_audit.report_week IS 'Report week of the invoice date (ISO 2025 week; NULL for 2026-W01)';
COMMENT ON COLUMN finance.invoice_audit.invoice_number IS 'The invoice with the finding';
COMMENT ON COLUMN finance.invoice_audit.invoice_date IS 'Invoice date';
COMMENT ON COLUMN finance.invoice_audit.vessel_id IS 'The billed vessel';
COMMENT ON COLUMN finance.invoice_audit.vessel_name IS 'Vessel name';
COMMENT ON COLUMN finance.invoice_audit.vessel_category IS 'Tariff category of the vessel (vessels.vessel_type)';
COMMENT ON COLUMN finance.invoice_audit.vessel_condition IS 'Condition of the vessel (vessels.condition); Special Floating Units are priced Laden';
COMMENT ON COLUMN finance.invoice_audit.check_code IS 'duplicate_charge | tonnage_mismatch | amount_mismatch | rate_mismatch';
COMMENT ON COLUMN finance.invoice_audit.probable_cause IS 'amount_mismatch only: billed_on_invoice_tonnage | flat_terminal_rate | condition_swapped | sfu_priced_ballast | unexplained (the first hypothesis that reproduces the billed amount within 0.01 SDR)';
COMMENT ON COLUMN finance.invoice_audit.billed_sdr IS 'Amount billed (SDR)';
COMMENT ON COLUMN finance.invoice_audit.expected_sdr IS 'Correct charge (SDR): the progressive toll of the vessel; 0 for a duplicate';
COMMENT ON COLUMN finance.invoice_audit.difference_sdr IS 'billed - expected (SDR): positive = overbilled, negative = underbilled';
COMMENT ON COLUMN finance.invoice_audit.duplicate_of IS 'duplicate_charge only: the original invoice number';
COMMENT ON COLUMN finance.invoice_audit.evidence IS 'The numbers behind the finding (tons, category, condition, band, rate)';

COMMENT ON COLUMN finance_test.invoice_audit.report_week IS 'Report week of the invoice date (ISO 2025 week)';
COMMENT ON COLUMN finance_test.invoice_audit.invoice_number IS 'The invoice with the finding';
COMMENT ON COLUMN finance_test.invoice_audit.invoice_date IS 'Invoice date';
COMMENT ON COLUMN finance_test.invoice_audit.vessel_id IS 'The billed vessel';
COMMENT ON COLUMN finance_test.invoice_audit.vessel_name IS 'Vessel name';
COMMENT ON COLUMN finance_test.invoice_audit.vessel_category IS 'Tariff category of the vessel (vessels.vessel_type)';
COMMENT ON COLUMN finance_test.invoice_audit.vessel_condition IS 'Condition of the vessel (vessels.condition); Special Floating Units are priced Laden';
COMMENT ON COLUMN finance_test.invoice_audit.check_code IS 'duplicate_charge | tonnage_mismatch | amount_mismatch | rate_mismatch (never: the copy stores no rate)';
COMMENT ON COLUMN finance_test.invoice_audit.probable_cause IS 'amount_mismatch only: billed_on_invoice_tonnage | flat_terminal_rate | condition_swapped | sfu_priced_ballast | unexplained';
COMMENT ON COLUMN finance_test.invoice_audit.billed_sdr IS 'Amount billed (SDR)';
COMMENT ON COLUMN finance_test.invoice_audit.expected_sdr IS 'Correct charge (SDR): the progressive toll of the vessel; 0 for a duplicate';
COMMENT ON COLUMN finance_test.invoice_audit.difference_sdr IS 'billed - expected (SDR)';
COMMENT ON COLUMN finance_test.invoice_audit.duplicate_of IS 'duplicate_charge only: the original invoice number';
COMMENT ON COLUMN finance_test.invoice_audit.evidence IS 'The numbers behind the finding';

COMMIT;
