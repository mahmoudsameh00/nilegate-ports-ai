-- =====================================================================
-- 006 — Integrity constraints and indexes (close the PostgreSQL database)
-- Decisions: ADR-033. Plan: docs/plans/PostgreSQL_Closure_plan.md (findings F1–F5).
-- Every constraint was checked against the live data first (0 violations on 2026-09-27); a violation would make
-- this transaction fail and change nothing.
-- =====================================================================
BEGIN;

-- ---- closed value sets ------------------------------------------------------------------------------------------
ALTER TABLE public.roles
    ADD CONSTRAINT roles_allowed_sensitivity_level_chk CHECK (allowed_sensitivity_level BETWEEN 1 AND 3);

ALTER TABLE public.toll_rate_bands
    ADD CONSTRAINT toll_rate_bands_laden_ballast_chk CHECK (laden_ballast IN ('Laden', 'Ballast')),
    ADD CONSTRAINT toll_rate_bands_vessel_category_chk CHECK (vessel_category IN (
        'Chemical Tankers & Other Liquid Bulk Tankers', 'Containerships', 'Crude Oil Tankers', 'Cruise Ships',
        'Dry Bulk Vessels', 'General Cargo / Multi-Purpose / Heavy Lift Vessels', 'Liquefied Natural Gas (LNG) Carriers',
        'Liquefied Petroleum Gas (LPG) Carriers', 'Other Vessels', 'Petroleum Product Tankers',
        'Roll-On/Roll-Off (Ro/Ro) Vessels', 'Special Floating Units', 'Vehicles Carriers')),
    ADD CONSTRAINT toll_rate_bands_band_order_chk CHECK (band_order >= 1),
    ADD CONSTRAINT toll_rate_bands_band_range_chk CHECK (band_min_tons >= 0 AND (band_max_tons IS NULL OR band_max_tons > band_min_tons)),
    ADD CONSTRAINT toll_rate_bands_rate_chk CHECK (rate_sdr_per_ton > 0),
    ADD CONSTRAINT toll_rate_bands_band_key UNIQUE (vessel_category, laden_ballast, band_order);

-- vessel_type <-> toll_rate_bands.vessel_category: a FK is impossible (the category repeats in the bands table), so
-- both columns carry the same 13-value list (the logical link of ARCHITECTURE §4.1 becomes enforced)
ALTER TABLE public.vessels
    ADD CONSTRAINT vessels_vessel_type_chk CHECK (vessel_type IN (
        'Chemical Tankers & Other Liquid Bulk Tankers', 'Containerships', 'Crude Oil Tankers', 'Cruise Ships',
        'Dry Bulk Vessels', 'General Cargo / Multi-Purpose / Heavy Lift Vessels', 'Liquefied Natural Gas (LNG) Carriers',
        'Liquefied Petroleum Gas (LPG) Carriers', 'Other Vessels', 'Petroleum Product Tankers',
        'Roll-On/Roll-Off (Ro/Ro) Vessels', 'Special Floating Units', 'Vehicles Carriers')),
    ADD CONSTRAINT vessels_condition_chk CHECK (condition IN ('Laden', 'Ballast')),
    ADD CONSTRAINT vessels_status_chk CHECK (status IN ('In Transit', 'At Port', 'Anchored', 'Completed')),
    ADD CONSTRAINT vessels_imo_number_format_chk CHECK (imo_number ~ '^[0-9]{7}$'),
    ADD CONSTRAINT vessels_scnt_tons_chk CHECK (scnt_tons > 0),
    ADD CONSTRAINT vessels_route_chk CHECK (origin_locode <> destination_locode);

ALTER TABLE public.containers
    ADD CONSTRAINT containers_size_ft_chk CHECK (size_ft IN (20, 40)),
    ADD CONSTRAINT containers_type_chk CHECK (container_type IN ('Dry', 'Reefer', 'Open Top', 'Flat Rack')),
    ADD CONSTRAINT containers_status_chk CHECK (status IN ('Loaded', 'In Transit', 'At Port', 'Delivered', 'Empty')),
    ADD CONSTRAINT containers_number_format_chk CHECK (container_number ~ '^[A-Z]{3}[UJZ][0-9]{7}$'),
    ADD CONSTRAINT containers_route_chk CHECK (origin_locode <> destination_locode);

ALTER TABLE public.invoices
    ADD CONSTRAINT invoices_status_chk CHECK (status IN ('Issued', 'Paid', 'Pending')),
    ADD CONSTRAINT invoices_number_format_chk CHECK (invoice_number ~ '^INV-[0-9]{7}$'),
    ADD CONSTRAINT invoices_amount_chk CHECK (amount > 0),
    ADD CONSTRAINT invoices_scnt_tons_chk CHECK (scnt_tons > 0),
    ADD CONSTRAINT invoices_rate_chk CHECK (rate_sdr_per_ton IS NULL OR rate_sdr_per_ton > 0);

ALTER TABLE public.employees
    ADD CONSTRAINT employees_email_format_chk CHECK (email ~ '^[a-z0-9._-]+@nilegate\.com$');

ALTER TABLE public.ports
    ADD CONSTRAINT ports_locode_format_chk CHECK (locode ~ '^[A-Z]{2}[A-Z2-9]{3}$'),
    ADD CONSTRAINT ports_function_format_chk CHECK (function ~ '^[0-9-]{7}[0-9B-]$'),
    ADD CONSTRAINT ports_status_format_chk CHECK (status ~ '^[A-Z]{2}$'),
    ADD CONSTRAINT ports_lat_lon_chk CHECK (lat BETWEEN -90 AND 90 AND lon BETWEEN -180 AND 180),
    ADD CONSTRAINT ports_outflows_chk CHECK (outflows >= 0),
    ADD CONSTRAINT ports_geom_matches_lon_lat_chk CHECK (abs(ST_X(geom) - lon) < 1e-9 AND abs(ST_Y(geom) - lat) < 1e-9);

-- country1 / country2 are ISO 3166-1 alpha-2 codes (ports.country holds names): they must be the LOCODE prefix
ALTER TABLE public.port_connections
    ADD CONSTRAINT port_connections_no_self_loop_chk CHECK (port1_locode <> port2_locode),
    ADD CONSTRAINT port_connections_flows_chk CHECK (flows > 0),
    ADD CONSTRAINT port_connections_country_codes_chk CHECK (country1 = left(port1_locode, 2) AND country2 = left(port2_locode, 2));

-- ---- indexes on foreign-key columns (joins and ON DELETE checks) -------------------------------------------------
CREATE INDEX port_connections_port2_locode_idx ON public.port_connections (port2_locode);
CREATE INDEX employees_department_id_idx       ON public.employees (department_id);
CREATE INDEX employees_role_id_idx             ON public.employees (role_id);
CREATE INDEX vessels_origin_locode_idx         ON public.vessels (origin_locode);
CREATE INDEX vessels_destination_locode_idx    ON public.vessels (destination_locode);
CREATE INDEX containers_vessel_id_idx          ON public.containers (vessel_id);
CREATE INDEX containers_origin_locode_idx      ON public.containers (origin_locode);
CREATE INDEX containers_destination_locode_idx ON public.containers (destination_locode);
CREATE INDEX invoices_vessel_id_idx            ON public.invoices (vessel_id);
CREATE INDEX invoices_toll_rate_band_id_idx    ON public.invoices (toll_rate_band_id);

-- ---- spatial indexes --------------------------------------------------------------------------------------------
CREATE INDEX ports_geom_gist            ON public.ports USING gist (geom);
CREATE INDEX port_connections_geom_gist ON public.port_connections USING gist (geom);

COMMIT;
