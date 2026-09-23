-- =====================================================================
-- 001 — Drop accepted_currencies
-- Decision: ADR-003 (every monetary value is stored in SDR; currencies are not modelled).
-- Verified 2026-09-23: the table still exists (10 rows) and no foreign key references it.
-- invoices.currency was already dropped earlier (invoices has a gap at attnum 6).
-- =====================================================================
BEGIN;

DROP TABLE public.accepted_currencies;   -- RESTRICT (default): fails if anything depends on it

COMMIT;
