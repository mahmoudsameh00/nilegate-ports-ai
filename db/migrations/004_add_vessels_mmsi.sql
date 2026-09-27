-- =====================================================================
-- 004 — Add vessels.mmsi (Maritime Mobile Service Identity)
-- Decisions: ADR-028 (vessel identity stays in PostgreSQL; MMSI added here), plan D4 (varchar(9) + CHECK).
-- A ship MMSI is 9 digits: MID (201-775, the flag's Maritime Identification Digits) + 6 digits.
-- Nullable at this step; migration 005 fills every row and sets NOT NULL.
-- =====================================================================
BEGIN;

ALTER TABLE public.vessels
    ADD COLUMN mmsi character varying(9),
    ADD CONSTRAINT vessels_mmsi_format_chk CHECK (mmsi ~ '^[2-7][0-9]{8}$'),
    ADD CONSTRAINT vessels_mmsi_key UNIQUE (mmsi);

COMMENT ON COLUMN public.vessels.mmsi IS
    'Ship station MMSI: MID of flag_country (db/reference/flag_country_mid.csv) + 6 digits. Synthetic (migration 005).';

COMMIT;
