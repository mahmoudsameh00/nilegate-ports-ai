-- =====================================================================
-- 008 — Comments on every table and column (self-describing schema)
-- Decisions: ADR-033. Plan: docs/plans/PostgreSQL_Closure_plan.md (F8).
-- The future tool layer and agents read these comments (information_schema / pg_description) to understand the
-- data without the project docs. Sensitivity level / owner department per table: docs/rbac_mapping.md §2.
-- =====================================================================
BEGIN;

COMMENT ON TABLE public.ports IS 'Real port reference (UN/LOCODE, from attributed_ports.geojson; ADR-002). Level 1, Operations.';
COMMENT ON COLUMN public.ports.locode IS '5-character UN/LOCODE, the cross-entity key for ports (ADR-002)';
COMMENT ON COLUMN public.ports.name IS 'Port name';
COMMENT ON COLUMN public.ports.country IS 'Country name (port_connections uses ISO alpha-2 codes instead)';
COMMENT ON COLUMN public.ports.function IS 'UN/LOCODE function classifier, 8 positions (1 = port, 2 = rail, 3 = road, 4 = airport, 5 = postal, 6 = multimodal, 7 = fixed transport, B = border crossing; - = no)';
COMMENT ON COLUMN public.ports.status IS 'UN/LOCODE status code (e.g. AI = approved by national agency, RL = recognised location)';
COMMENT ON COLUMN public.ports.outflows IS 'Aggregated outgoing flow of the port in the port-flows network';
COMMENT ON COLUMN public.ports.lon IS 'Longitude, WGS 84 (= ST_X(geom))';
COMMENT ON COLUMN public.ports.lat IS 'Latitude, WGS 84 (= ST_Y(geom))';
COMMENT ON COLUMN public.ports.geom IS 'Point, SRID 4326';

COMMENT ON TABLE public.port_connections IS 'Real port-to-port network with flows (port_flows shapefile). Both directions present. Level 1, Operations.';
COMMENT ON COLUMN public.port_connections.port1_locode IS 'From port (UN/LOCODE)';
COMMENT ON COLUMN public.port_connections.port2_locode IS 'To port (UN/LOCODE)';
COMMENT ON COLUMN public.port_connections.flows IS 'Flow volume between the two ports (> 0)';
COMMENT ON COLUMN public.port_connections.country1 IS 'ISO 3166-1 alpha-2 country code of port1 (= left(port1_locode, 2))';
COMMENT ON COLUMN public.port_connections.country2 IS 'ISO 3166-1 alpha-2 country code of port2 (= left(port2_locode, 2))';
COMMENT ON COLUMN public.port_connections.geom IS 'Straight 2-point LineString from port1 to port2, SRID 4326 (not a sea lane)';

COMMENT ON TABLE public.toll_rate_bands IS 'Suez Canal transit dues from 2023-01-01, progressive bands per vessel category and condition (ADR-004, ADR-005). Level 1, Finance.';
COMMENT ON COLUMN public.toll_rate_bands.id IS 'Surrogate key';
COMMENT ON COLUMN public.toll_rate_bands.vessel_category IS 'Suez vessel category (same 13 values as vessels.vessel_type)';
COMMENT ON COLUMN public.toll_rate_bands.laden_ballast IS 'Laden or Ballast';
COMMENT ON COLUMN public.toll_rate_bands.band_order IS 'Position of the band within (category, condition), from 1';
COMMENT ON COLUMN public.toll_rate_bands.band_label IS 'Band label as printed in the tariff';
COMMENT ON COLUMN public.toll_rate_bands.band_min_tons IS 'Lower bound of the band, SCNT';
COMMENT ON COLUMN public.toll_rate_bands.band_max_tons IS 'Upper bound of the band, SCNT; NULL = open last band';
COMMENT ON COLUMN public.toll_rate_bands.rate_sdr_per_ton IS 'Rate in SDR per SCNT ton within the band (money is stored in SDR only, ADR-003)';

COMMENT ON TABLE public.departments IS 'NileGate departments (Operations, Customs, Finance, HR, IT). Level 1, HR.';
COMMENT ON COLUMN public.departments.department_id IS 'Surrogate key; owner department of every protected resource (ADR-006)';
COMMENT ON COLUMN public.departments.department_name IS 'Unique department name';
COMMENT ON COLUMN public.departments.description IS 'Optional description';

COMMENT ON TABLE public.roles IS 'Roles and their sensitivity ceiling: employee 1, manager 2, ceo 3 (ADR-006). Level 2, IT.';
COMMENT ON COLUMN public.roles.role_id IS 'Surrogate key';
COMMENT ON COLUMN public.roles.role_name IS 'employee, manager or ceo';
COMMENT ON COLUMN public.roles.allowed_sensitivity_level IS 'Highest sensitivity level the role may read (1-3)';

COMMENT ON TABLE public.employees IS 'Synthetic employees (Faker, seed 42). Contains personal data. Level 2, HR (ADR-006); no status column (ADR-017).';
COMMENT ON COLUMN public.employees.employee_id IS 'Surrogate key';
COMMENT ON COLUMN public.employees.first_name IS 'First name (synthetic)';
COMMENT ON COLUMN public.employees.last_name IS 'Last name (synthetic)';
COMMENT ON COLUMN public.employees.email IS 'Unique @nilegate.com address';
COMMENT ON COLUMN public.employees.role_id IS 'Role (roles.role_id): sensitivity ceiling';
COMMENT ON COLUMN public.employees.department_id IS 'Department (departments.department_id): department grant';
COMMENT ON COLUMN public.employees.hire_date IS 'Hire date (anchored to 2026-09-13)';

COMMENT ON TABLE public.vessels IS 'Synthetic NileGate fleet (500 vessels, seed 42): system of record for vessel identity (ADR-028). Level 1, Operations.';
COMMENT ON COLUMN public.vessels.vessel_id IS 'Surrogate key (= imo_number - 9000000)';
COMMENT ON COLUMN public.vessels.imo_number IS '7-digit IMO number (synthetic, sequential; the IMO check digit is not enforced)';
COMMENT ON COLUMN public.vessels.vessel_name IS 'Vessel name (synthetic)';
COMMENT ON COLUMN public.vessels.vessel_type IS 'Suez vessel category (same values as toll_rate_bands.vessel_category)';
COMMENT ON COLUMN public.vessels.flag_country IS 'Flag state name; its ITU MID is the first 3 digits of mmsi';
COMMENT ON COLUMN public.vessels.scnt_tons IS 'Suez Canal Net Tonnage (SCNT), basis of the transit dues';
COMMENT ON COLUMN public.vessels.origin_locode IS 'Origin port of the current voyage (UN/LOCODE)';
COMMENT ON COLUMN public.vessels.destination_locode IS 'Destination port of the current voyage (UN/LOCODE)';
COMMENT ON COLUMN public.vessels.condition IS 'Laden or Ballast (selects the toll band set)';
COMMENT ON COLUMN public.vessels.status IS 'In Transit, At Port, Anchored or Completed; the synthetic AIS tracks follow it (ADR-032)';

COMMENT ON TABLE public.containers IS 'Synthetic containers (1,000) carried by the vessels; same origin / destination as their vessel. Level 1, Operations.';
COMMENT ON COLUMN public.containers.container_id IS 'Surrogate key';
COMMENT ON COLUMN public.containers.container_number IS 'Container number in ISO 6346 form (synthetic, sequential; the check digit is not enforced)';
COMMENT ON COLUMN public.containers.container_type IS 'Dry, Reefer, Open Top or Flat Rack';
COMMENT ON COLUMN public.containers.size_ft IS 'Length in feet: 20 or 40';
COMMENT ON COLUMN public.containers.status IS 'Loaded, In Transit, At Port, Delivered or Empty';
COMMENT ON COLUMN public.containers.vessel_id IS 'Carrying vessel';
COMMENT ON COLUMN public.containers.origin_locode IS 'Port of loading (UN/LOCODE)';
COMMENT ON COLUMN public.containers.destination_locode IS 'Port of discharge (UN/LOCODE)';

COMMENT ON TABLE public.invoices IS 'Suez transit dues invoices (1,000, dated 2025), built in PostgreSQL (ADR-013). Level 2, Finance.';
COMMENT ON COLUMN public.invoices.invoice_id IS 'Surrogate key';
COMMENT ON COLUMN public.invoices.invoice_number IS 'Unique number INV-nnnnnnn';
COMMENT ON COLUMN public.invoices.vessel_id IS 'Invoiced vessel';
COMMENT ON COLUMN public.invoices.toll_rate_band_id IS 'Terminal toll band reached by the vessel SCNT (ADR-004)';
COMMENT ON COLUMN public.invoices.invoice_date IS 'Invoice date (2025)';
COMMENT ON COLUMN public.invoices.scnt_tons IS 'SCNT of the vessel at invoicing';
COMMENT ON COLUMN public.invoices.rate_sdr_per_ton IS 'Rate of the terminal band, SDR per ton';
COMMENT ON COLUMN public.invoices.amount IS 'Progressive sum over the bands, in SDR (ADR-003, ADR-004)';
COMMENT ON COLUMN public.invoices.description IS 'Free text, e.g. Suez Canal transit dues - <category>';
COMMENT ON COLUMN public.invoices.status IS 'Issued, Paid or Pending';

COMMENT ON TABLE public.documents IS 'RAG document registry and lineage, one row per ingested source file (ADR-009); filled in the RAG phase. Level 1, IT.';

COMMIT;
