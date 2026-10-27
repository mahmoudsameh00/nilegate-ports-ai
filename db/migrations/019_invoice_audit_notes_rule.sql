-- =====================================================================
-- 019 — Invoice audit: the tariff Notes rule for ballast oil / chemical tankers (Agents plan §5f K5 / F5, owner
--       2026-10-22; the open point of the suez-toll-audit skill review, 2026-10-19)
-- The Suez Notes (corpus chunk suez_notes_ballast_combined_carrier_rates), checked against toll_rate_bands:
--   "Ballast Petroleum Product Tankers ... rates of ballast Crude Oil Tankers" — already in the tables (the two
--     categories' ballast bands are identical): nothing to add;
--   "Ballast Oil/Chemical Tankers ... rates of ballast Crude Oil Tankers" — NOT in the tables: our category
--     "Chemical Tankers & Other Liquid Bulk Tankers" is wider than "Oil/Chemical Tankers" and the data cannot tell the
--     subtype, so a ballast chemical tanker billed at the Crude Oil ballast toll may be right → a person decides;
--   OBO / combined carriers — none of our 13 categories: not applicable; "the vessel's actual condition upon transit"
--     — the audit prices the vessel's condition already.
-- So the audit (015) gains one hypothesis, `notes_crude_ballast_rate` (a ballast vessel of the chemical category
-- whose billed amount = the Crude Oil Tankers ballast toll of its SCNT within 0.01 SDR), and one column at the end,
-- `review`: 'manual_review' for that cause, 'error' for every other finding. Everything else is 015 unchanged (the
-- same SQL, built from it by exact replacements). Today's data has no such invoice (every invoice = its own bands,
-- ADR-004): the views return the same rows plus review = 'error'. CREATE OR REPLACE keeps the grants of 012/013/015.
-- Written from 015 by a script (exact replacements, each found once per view); never edited after applying.
-- =====================================================================
BEGIN;

CREATE OR REPLACE VIEW finance.invoice_audit AS
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
    UNION ALL
    SELECT invoice_number, 'notes_crude_ballast', 'Crude Oil Tankers', 'Ballast', vessel_scnt FROM inv
    WHERE priced_condition = 'Ballast' AND vessel_category = 'Chemical Tankers & Other Liquid Bulk Tankers'
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
           round(nc.toll_exact, 2) AS notes_crude_sdr,
           row_number() OVER w AS dup_rank,
           first_value(i.invoice_number) OVER w AS dup_first
    FROM inv i
    JOIN priced e ON e.invoice_number = i.invoice_number AND e.scenario = 'expected'
    LEFT JOIN priced it ON it.invoice_number = i.invoice_number AND it.scenario = 'invoice_tonnage'
    LEFT JOIN priced cs ON cs.invoice_number = i.invoice_number AND cs.scenario = 'condition_swapped'
    LEFT JOIN priced sb ON sb.invoice_number = i.invoice_number AND sb.scenario = 'sfu_priced_ballast'
    LEFT JOIN priced nc ON nc.invoice_number = i.invoice_number AND nc.scenario = 'notes_crude_ballast'
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
                WHEN abs(h.billed_sdr - h.notes_crude_sdr) <= 0.01 THEN 'notes_crude_ballast_rate'
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
       round(billed_sdr - expected_charge, 2) AS difference_sdr, duplicate_of, evidence,
       CASE WHEN probable_cause = 'notes_crude_ballast_rate' THEN 'manual_review' ELSE 'error' END AS review
FROM findings;

CREATE OR REPLACE VIEW finance_test.invoice_audit AS
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
    UNION ALL
    SELECT invoice_number, 'notes_crude_ballast', 'Crude Oil Tankers', 'Ballast', vessel_scnt FROM inv
    WHERE priced_condition = 'Ballast' AND vessel_category = 'Chemical Tankers & Other Liquid Bulk Tankers'
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
           round(nc.toll_exact, 2) AS notes_crude_sdr,
           row_number() OVER w AS dup_rank,
           first_value(i.invoice_number) OVER w AS dup_first
    FROM inv i
    JOIN priced e ON e.invoice_number = i.invoice_number AND e.scenario = 'expected'
    LEFT JOIN priced it ON it.invoice_number = i.invoice_number AND it.scenario = 'invoice_tonnage'
    LEFT JOIN priced cs ON cs.invoice_number = i.invoice_number AND cs.scenario = 'condition_swapped'
    LEFT JOIN priced sb ON sb.invoice_number = i.invoice_number AND sb.scenario = 'sfu_priced_ballast'
    LEFT JOIN priced nc ON nc.invoice_number = i.invoice_number AND nc.scenario = 'notes_crude_ballast'
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
                WHEN abs(h.billed_sdr - h.notes_crude_sdr) <= 0.01 THEN 'notes_crude_ballast_rate'
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
       round(billed_sdr - expected_charge, 2) AS difference_sdr, duplicate_of, evidence,
       CASE WHEN probable_cause = 'notes_crude_ballast_rate' THEN 'manual_review' ELSE 'error' END AS review
FROM findings;

COMMENT ON COLUMN finance.invoice_audit.probable_cause IS 'amount_mismatch only: billed_on_invoice_tonnage | flat_terminal_rate | condition_swapped | sfu_priced_ballast | notes_crude_ballast_rate | unexplained (the first hypothesis that reproduces the billed amount within 0.01 SDR)';
COMMENT ON COLUMN finance.invoice_audit.review IS 'error | manual_review: manual_review = priced by a tariff Notes rule (a ballast chemical tanker at the Crude Oil Tankers ballast rates — right if it is an oil/chemical tanker, migration 019) — confirm the rule, it may be correct; not counted as money at stake';
COMMENT ON COLUMN finance_test.invoice_audit.probable_cause IS 'amount_mismatch only: billed_on_invoice_tonnage | flat_terminal_rate | condition_swapped | sfu_priced_ballast | notes_crude_ballast_rate | unexplained';
COMMENT ON COLUMN finance_test.invoice_audit.review IS 'error | manual_review (a tariff Notes rule, migration 019)';

COMMIT;
