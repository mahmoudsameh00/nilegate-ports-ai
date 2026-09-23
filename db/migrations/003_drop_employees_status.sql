-- =====================================================================
-- 003 — Drop employees.status
-- Decision: ADR-017 (the project has no active/inactive employee concept).
-- Verified 2026-09-23: no constraint, index, view or trigger uses the column.
-- 94 rows 'Active', 6 rows 'Inactive' are discarded.
-- =====================================================================
BEGIN;

ALTER TABLE public.employees DROP COLUMN status;

COMMIT;
