--
-- PostgreSQL database dump
--

-- Dumped from database version 16.9 (Debian 16.9-1.pgdg110+1)
-- Dumped by pg_dump version 16.9 (Debian 16.9-1.pgdg110+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: agent_state; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA agent_state;


--
-- Name: SCHEMA agent_state; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA agent_state IS 'LangGraph checkpoints of the agents platform (PostgresSaver; Agents plan Phase 5, D3). Tables created by PostgresSaver.setup() as the owner (deployment step); written only through the role agent_writer. Holds level-2 Finance numbers (tool results of a run).';


--
-- Name: finance; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA finance;


--
-- Name: SCHEMA finance; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA finance IS 'Star views and weekly KPI views of the Weekly Finance Pack over the public tables (Agents plan Phase 2, D4); plain views, no stored data. Level 2, Finance.';


--
-- Name: finance_test; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA finance_test;


--
-- Name: SCHEMA finance_test; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA finance_test IS 'Evaluation copy only (Agents plan §4a R7): 4 golden weeks with planted invoice errors and a budget miss; never joined with the real tables; the answer key is outside the database.';


--
-- Name: fuzzystrmatch; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS fuzzystrmatch WITH SCHEMA public;


--
-- Name: EXTENSION fuzzystrmatch; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION fuzzystrmatch IS 'determine similarities and distance between strings';


--
-- Name: postgis; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS postgis WITH SCHEMA public;


--
-- Name: EXTENSION postgis; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION postgis IS 'PostGIS geometry and geography spatial types and functions';


--
-- Name: postgis_tiger_geocoder; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS postgis_tiger_geocoder WITH SCHEMA tiger;


--
-- Name: EXTENSION postgis_tiger_geocoder; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION postgis_tiger_geocoder IS 'PostGIS tiger geocoder and reverse geocoder';


--
-- Name: postgis_topology; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS postgis_topology WITH SCHEMA topology;


--
-- Name: EXTENSION postgis_topology; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION postgis_topology IS 'PostGIS topology spatial types and functions';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: checkpoint_blobs; Type: TABLE; Schema: agent_state; Owner: -
--

CREATE TABLE agent_state.checkpoint_blobs (
    thread_id text NOT NULL,
    checkpoint_ns text DEFAULT ''::text NOT NULL,
    channel text NOT NULL,
    version text NOT NULL,
    type text NOT NULL,
    blob bytea
);


--
-- Name: checkpoint_migrations; Type: TABLE; Schema: agent_state; Owner: -
--

CREATE TABLE agent_state.checkpoint_migrations (
    v integer NOT NULL
);


--
-- Name: checkpoint_writes; Type: TABLE; Schema: agent_state; Owner: -
--

CREATE TABLE agent_state.checkpoint_writes (
    thread_id text NOT NULL,
    checkpoint_ns text DEFAULT ''::text NOT NULL,
    checkpoint_id text NOT NULL,
    task_id text NOT NULL,
    idx integer NOT NULL,
    channel text NOT NULL,
    type text,
    blob bytea NOT NULL,
    task_path text DEFAULT ''::text NOT NULL
);


--
-- Name: checkpoints; Type: TABLE; Schema: agent_state; Owner: -
--

CREATE TABLE agent_state.checkpoints (
    thread_id text NOT NULL,
    checkpoint_ns text DEFAULT ''::text NOT NULL,
    checkpoint_id text NOT NULL,
    parent_checkpoint_id text,
    type text,
    checkpoint jsonb NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL
);


--
-- Name: customers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.customers (
    customer_id integer NOT NULL,
    customer_name text NOT NULL,
    country text NOT NULL,
    segment text NOT NULL,
    payment_terms_days integer NOT NULL,
    credit_rating text NOT NULL,
    CONSTRAINT customers_rating_chk CHECK ((credit_rating = ANY (ARRAY['A'::text, 'B'::text, 'C'::text]))),
    CONSTRAINT customers_segment_chk CHECK ((segment = ANY (ARRAY['container'::text, 'tanker'::text, 'bulk'::text, 'roro'::text, 'cruise'::text, 'agent'::text]))),
    CONSTRAINT customers_terms_chk CHECK ((payment_terms_days = ANY (ARRAY[30, 45, 60])))
);


--
-- Name: TABLE customers; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.customers IS 'Synthetic customers (shipping lines / agents) billed for Suez transit dues; 40 invented companies (Agents plan §4a R1). Level 2, Finance.';


--
-- Name: COLUMN customers.customer_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.customers.customer_id IS 'Surrogate key';


--
-- Name: COLUMN customers.customer_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.customers.customer_name IS 'Invented company name (not a real company)';


--
-- Name: COLUMN customers.country; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.customers.country IS 'Headquarters country (not the flag of its vessels)';


--
-- Name: COLUMN customers.segment; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.customers.segment IS 'Customer segment by the vessel types it operates';


--
-- Name: COLUMN customers.payment_terms_days; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.customers.payment_terms_days IS 'Payment terms: due date = invoice date + these days';


--
-- Name: COLUMN customers.credit_rating; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.customers.credit_rating IS 'Credit rating A / B / C (correlates with payment behaviour, does not reveal it)';


--
-- Name: dim_customer; Type: VIEW; Schema: finance; Owner: -
--

CREATE VIEW finance.dim_customer AS
 SELECT customer_id,
    customer_name,
    country,
    segment,
    payment_terms_days,
    credit_rating
   FROM public.customers;


--
-- Name: VIEW dim_customer; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON VIEW finance.dim_customer IS 'Billed customers (shipping lines and agents, synthetic). Level 2, Finance.';


--
-- Name: COLUMN dim_customer.customer_id; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_customer.customer_id IS 'Customer id';


--
-- Name: COLUMN dim_customer.customer_name; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_customer.customer_name IS 'Invented company name (no real company)';


--
-- Name: COLUMN dim_customer.country; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_customer.country IS 'Head-office country';


--
-- Name: COLUMN dim_customer.segment; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_customer.segment IS 'container, tanker, bulk, roro, cruise or agent';


--
-- Name: COLUMN dim_customer.payment_terms_days; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_customer.payment_terms_days IS 'Payment terms in days (30, 45 or 60): due date = invoice date + terms';


--
-- Name: COLUMN dim_customer.credit_rating; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_customer.credit_rating IS 'Credit rating A, B or C';


--
-- Name: dim_date; Type: VIEW; Schema: finance; Owner: -
--

CREATE VIEW finance.dim_date AS
 SELECT (d)::date AS date_day,
    (EXTRACT(isoyear FROM d))::integer AS iso_year,
    (EXTRACT(week FROM d))::integer AS iso_week,
    to_char(d, 'IYYY"-W"IW'::text) AS iso_week_label,
    (date_trunc('week'::text, d))::date AS week_start,
    ((date_trunc('week'::text, d))::date + 6) AS week_end,
        CASE
            WHEN (EXTRACT(isoyear FROM d) = (2025)::numeric) THEN (EXTRACT(week FROM d))::integer
            ELSE NULL::integer
        END AS report_week,
    (EXTRACT(isodow FROM d))::integer AS iso_dow,
    (EXTRACT(year FROM d))::integer AS calendar_year,
    (EXTRACT(quarter FROM d))::integer AS calendar_quarter,
    (EXTRACT(month FROM d))::integer AS calendar_month
   FROM generate_series(('2025-01-01'::date)::timestamp with time zone, ('2026-03-31'::date)::timestamp with time zone, '1 day'::interval) d(d);


--
-- Name: VIEW dim_date; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON VIEW finance.dim_date IS 'Calendar 2025-01-01 → 2026-03-31 (the payments horizon), one row per day, with its ISO week. Level 2, Finance (schema level).';


--
-- Name: COLUMN dim_date.date_day; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_date.date_day IS 'The day';


--
-- Name: COLUMN dim_date.iso_year; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_date.iso_year IS 'ISO-8601 week-numbering year (2025-12-29..31 belong to 2026)';


--
-- Name: COLUMN dim_date.iso_week; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_date.iso_week IS 'ISO-8601 week number 1–53 (Monday to Sunday)';


--
-- Name: COLUMN dim_date.iso_week_label; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_date.iso_week_label IS 'ISO week as text, e.g. 2025-W05';


--
-- Name: COLUMN dim_date.week_start; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_date.week_start IS 'Monday of the ISO week';


--
-- Name: COLUMN dim_date.week_end; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_date.week_end IS 'Sunday of the ISO week (the "as of" day of a report)';


--
-- Name: COLUMN dim_date.report_week; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_date.report_week IS 'Report week 1–52 (ISO weeks of 2025, D12); NULL for days of ISO 2026';


--
-- Name: COLUMN dim_date.iso_dow; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_date.iso_dow IS 'ISO day of week, 1 = Monday … 7 = Sunday';


--
-- Name: COLUMN dim_date.calendar_year; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_date.calendar_year IS 'Calendar year';


--
-- Name: COLUMN dim_date.calendar_quarter; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_date.calendar_quarter IS 'Calendar quarter 1–4';


--
-- Name: COLUMN dim_date.calendar_month; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_date.calendar_month IS 'Calendar month 1–12';


--
-- Name: toll_rate_bands; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.toll_rate_bands (
    id integer NOT NULL,
    vessel_category text NOT NULL,
    laden_ballast text NOT NULL,
    band_order integer NOT NULL,
    band_label text NOT NULL,
    band_min_tons numeric NOT NULL,
    band_max_tons numeric,
    rate_sdr_per_ton numeric NOT NULL,
    CONSTRAINT toll_rate_bands_band_order_chk CHECK ((band_order >= 1)),
    CONSTRAINT toll_rate_bands_band_range_chk CHECK (((band_min_tons >= (0)::numeric) AND ((band_max_tons IS NULL) OR (band_max_tons > band_min_tons)))),
    CONSTRAINT toll_rate_bands_laden_ballast_chk CHECK ((laden_ballast = ANY (ARRAY['Laden'::text, 'Ballast'::text]))),
    CONSTRAINT toll_rate_bands_rate_chk CHECK ((rate_sdr_per_ton > (0)::numeric)),
    CONSTRAINT toll_rate_bands_vessel_category_chk CHECK ((vessel_category = ANY (ARRAY['Chemical Tankers & Other Liquid Bulk Tankers'::text, 'Containerships'::text, 'Crude Oil Tankers'::text, 'Cruise Ships'::text, 'Dry Bulk Vessels'::text, 'General Cargo / Multi-Purpose / Heavy Lift Vessels'::text, 'Liquefied Natural Gas (LNG) Carriers'::text, 'Liquefied Petroleum Gas (LPG) Carriers'::text, 'Other Vessels'::text, 'Petroleum Product Tankers'::text, 'Roll-On/Roll-Off (Ro/Ro) Vessels'::text, 'Special Floating Units'::text, 'Vehicles Carriers'::text])))
);


--
-- Name: TABLE toll_rate_bands; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.toll_rate_bands IS 'Suez Canal transit dues from 2023-01-01, progressive bands per vessel category and condition (ADR-004, ADR-005). Level 1, Finance.';


--
-- Name: COLUMN toll_rate_bands.id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.toll_rate_bands.id IS 'Surrogate key';


--
-- Name: COLUMN toll_rate_bands.vessel_category; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.toll_rate_bands.vessel_category IS 'Suez vessel category (same 13 values as vessels.vessel_type)';


--
-- Name: COLUMN toll_rate_bands.laden_ballast; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.toll_rate_bands.laden_ballast IS 'Laden or Ballast';


--
-- Name: COLUMN toll_rate_bands.band_order; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.toll_rate_bands.band_order IS 'Position of the band within (category, condition), from 1';


--
-- Name: COLUMN toll_rate_bands.band_label; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.toll_rate_bands.band_label IS 'Band label as printed in the tariff';


--
-- Name: COLUMN toll_rate_bands.band_min_tons; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.toll_rate_bands.band_min_tons IS 'Lower bound of the band, SCNT';


--
-- Name: COLUMN toll_rate_bands.band_max_tons; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.toll_rate_bands.band_max_tons IS 'Upper bound of the band, SCNT; NULL = open last band';


--
-- Name: COLUMN toll_rate_bands.rate_sdr_per_ton; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.toll_rate_bands.rate_sdr_per_ton IS 'Rate in SDR per SCNT ton within the band (money is stored in SDR only, ADR-003)';


--
-- Name: dim_toll_band; Type: VIEW; Schema: finance; Owner: -
--

CREATE VIEW finance.dim_toll_band AS
 SELECT id AS toll_rate_band_id,
    vessel_category,
    laden_ballast,
    band_order,
    band_label,
    band_min_tons,
    band_max_tons,
    rate_sdr_per_ton
   FROM public.toll_rate_bands;


--
-- Name: VIEW dim_toll_band; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON VIEW finance.dim_toll_band IS 'Suez transit dues bands (progressive, SDR per SCNT; ADR-004). Level 2, Finance (schema level; the tariff table is level 1).';


--
-- Name: COLUMN dim_toll_band.toll_rate_band_id; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_toll_band.toll_rate_band_id IS 'Band id (toll_rate_bands.id)';


--
-- Name: COLUMN dim_toll_band.vessel_category; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_toll_band.vessel_category IS 'Tariff vessel category';


--
-- Name: COLUMN dim_toll_band.laden_ballast; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_toll_band.laden_ballast IS 'Laden or Ballast';


--
-- Name: COLUMN dim_toll_band.band_order; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_toll_band.band_order IS 'Band position 1–8 within the category and condition';


--
-- Name: COLUMN dim_toll_band.band_label; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_toll_band.band_label IS 'Band label as printed in the tariff';


--
-- Name: COLUMN dim_toll_band.band_min_tons; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_toll_band.band_min_tons IS 'Lower bound of the band (SCNT)';


--
-- Name: COLUMN dim_toll_band.band_max_tons; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_toll_band.band_max_tons IS 'Upper bound of the band (SCNT); NULL = open-ended';


--
-- Name: COLUMN dim_toll_band.rate_sdr_per_ton; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_toll_band.rate_sdr_per_ton IS 'Rate in SDR per SCNT inside the band';


--
-- Name: ports; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ports (
    locode character varying(5) NOT NULL,
    name text NOT NULL,
    country text NOT NULL,
    function character(8) NOT NULL,
    status character(2) NOT NULL,
    outflows double precision NOT NULL,
    lon double precision NOT NULL,
    lat double precision NOT NULL,
    geom public.geometry(Point,4326) NOT NULL,
    CONSTRAINT ports_function_format_chk CHECK ((function ~ '^[0-9-]{7}[0-9B-]$'::text)),
    CONSTRAINT ports_geom_matches_lon_lat_chk CHECK (((abs((public.st_x(geom) - lon)) < (0.000000001)::double precision) AND (abs((public.st_y(geom) - lat)) < (0.000000001)::double precision))),
    CONSTRAINT ports_lat_lon_chk CHECK ((((lat >= ('-90'::integer)::double precision) AND (lat <= (90)::double precision)) AND ((lon >= ('-180'::integer)::double precision) AND (lon <= (180)::double precision)))),
    CONSTRAINT ports_locode_format_chk CHECK (((locode)::text ~ '^[A-Z]{2}[A-Z2-9]{3}$'::text)),
    CONSTRAINT ports_outflows_chk CHECK ((outflows >= (0)::double precision)),
    CONSTRAINT ports_status_format_chk CHECK ((status ~ '^[A-Z]{2}$'::text))
);


--
-- Name: TABLE ports; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.ports IS 'Real port reference (UN/LOCODE, from attributed_ports.geojson; ADR-002). Level 1, Operations.';


--
-- Name: COLUMN ports.locode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.ports.locode IS '5-character UN/LOCODE, the cross-entity key for ports (ADR-002)';


--
-- Name: COLUMN ports.name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.ports.name IS 'Port name';


--
-- Name: COLUMN ports.country; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.ports.country IS 'Country name (port_connections uses ISO alpha-2 codes instead)';


--
-- Name: COLUMN ports.function; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.ports.function IS 'UN/LOCODE function classifier, 8 positions (1 = port, 2 = rail, 3 = road, 4 = airport, 5 = postal, 6 = multimodal, 7 = fixed transport, B = border crossing; - = no)';


--
-- Name: COLUMN ports.status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.ports.status IS 'UN/LOCODE status code (e.g. AI = approved by national agency, RL = recognised location)';


--
-- Name: COLUMN ports.outflows; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.ports.outflows IS 'Aggregated outgoing flow of the port in the port-flows network';


--
-- Name: COLUMN ports.lon; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.ports.lon IS 'Longitude, WGS 84 (= ST_X(geom))';


--
-- Name: COLUMN ports.lat; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.ports.lat IS 'Latitude, WGS 84 (= ST_Y(geom))';


--
-- Name: COLUMN ports.geom; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.ports.geom IS 'Point, SRID 4326';


--
-- Name: vessels; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vessels (
    vessel_id integer NOT NULL,
    imo_number character varying(7) NOT NULL,
    vessel_name text NOT NULL,
    vessel_type text NOT NULL,
    flag_country text NOT NULL,
    scnt_tons numeric NOT NULL,
    origin_locode character varying(5) NOT NULL,
    destination_locode character varying(5) NOT NULL,
    condition text NOT NULL,
    status text NOT NULL,
    mmsi character varying(9) NOT NULL,
    customer_id integer NOT NULL,
    CONSTRAINT vessels_condition_chk CHECK ((condition = ANY (ARRAY['Laden'::text, 'Ballast'::text]))),
    CONSTRAINT vessels_imo_number_format_chk CHECK (((imo_number)::text ~ '^[0-9]{7}$'::text)),
    CONSTRAINT vessels_mmsi_format_chk CHECK (((mmsi)::text ~ '^[2-7][0-9]{8}$'::text)),
    CONSTRAINT vessels_route_chk CHECK (((origin_locode)::text <> (destination_locode)::text)),
    CONSTRAINT vessels_scnt_tons_chk CHECK ((scnt_tons > (0)::numeric)),
    CONSTRAINT vessels_status_chk CHECK ((status = ANY (ARRAY['In Transit'::text, 'At Port'::text, 'Anchored'::text, 'Completed'::text]))),
    CONSTRAINT vessels_vessel_type_chk CHECK ((vessel_type = ANY (ARRAY['Chemical Tankers & Other Liquid Bulk Tankers'::text, 'Containerships'::text, 'Crude Oil Tankers'::text, 'Cruise Ships'::text, 'Dry Bulk Vessels'::text, 'General Cargo / Multi-Purpose / Heavy Lift Vessels'::text, 'Liquefied Natural Gas (LNG) Carriers'::text, 'Liquefied Petroleum Gas (LPG) Carriers'::text, 'Other Vessels'::text, 'Petroleum Product Tankers'::text, 'Roll-On/Roll-Off (Ro/Ro) Vessels'::text, 'Special Floating Units'::text, 'Vehicles Carriers'::text])))
);


--
-- Name: TABLE vessels; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.vessels IS 'Synthetic NileGate fleet (500 vessels, seed 42): system of record for vessel identity (ADR-028). Level 1, Operations.';


--
-- Name: COLUMN vessels.vessel_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.vessels.vessel_id IS 'Surrogate key (= imo_number - 9000000)';


--
-- Name: COLUMN vessels.imo_number; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.vessels.imo_number IS '7-digit IMO number (synthetic, sequential; the IMO check digit is not enforced)';


--
-- Name: COLUMN vessels.vessel_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.vessels.vessel_name IS 'Vessel name (synthetic)';


--
-- Name: COLUMN vessels.vessel_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.vessels.vessel_type IS 'Suez vessel category (same values as toll_rate_bands.vessel_category)';


--
-- Name: COLUMN vessels.flag_country; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.vessels.flag_country IS 'Flag state name; its ITU MID is the first 3 digits of mmsi';


--
-- Name: COLUMN vessels.scnt_tons; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.vessels.scnt_tons IS 'Suez Canal Net Tonnage (SCNT), basis of the transit dues';


--
-- Name: COLUMN vessels.origin_locode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.vessels.origin_locode IS 'Origin port of the current voyage (UN/LOCODE)';


--
-- Name: COLUMN vessels.destination_locode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.vessels.destination_locode IS 'Destination port of the current voyage (UN/LOCODE)';


--
-- Name: COLUMN vessels.condition; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.vessels.condition IS 'Laden or Ballast (selects the toll band set)';


--
-- Name: COLUMN vessels.status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.vessels.status IS 'In Transit, At Port, Anchored or Completed; the synthetic AIS tracks follow it (ADR-032)';


--
-- Name: COLUMN vessels.mmsi; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.vessels.mmsi IS 'Ship station MMSI: MID of flag_country (db/reference/flag_country_mid.csv) + 6 digits. Synthetic (migration 005).';


--
-- Name: COLUMN vessels.customer_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.vessels.customer_id IS 'The customer billed for this vessel (FK customers; migration 012)';


--
-- Name: dim_vessel; Type: VIEW; Schema: finance; Owner: -
--

CREATE VIEW finance.dim_vessel AS
 SELECT v.vessel_id,
    v.imo_number,
    v.vessel_name,
    v.vessel_type AS vessel_category,
    v.flag_country,
    v.scnt_tons,
    v.condition,
    v.origin_locode,
    po.name AS origin_port,
    v.destination_locode,
    pd.name AS destination_port,
    (((v.origin_locode)::text || '-'::text) || (v.destination_locode)::text) AS route,
    v.customer_id
   FROM ((public.vessels v
     LEFT JOIN public.ports po ON (((po.locode)::text = (v.origin_locode)::text)))
     LEFT JOIN public.ports pd ON (((pd.locode)::text = (v.destination_locode)::text)));


--
-- Name: VIEW dim_vessel; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON VIEW finance.dim_vessel IS 'Vessels with their category, route (port names) and billed customer. Level 2, Finance (schema level; the vessels table is level 1).';


--
-- Name: COLUMN dim_vessel.vessel_id; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_vessel.vessel_id IS 'Vessel id';


--
-- Name: COLUMN dim_vessel.imo_number; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_vessel.imo_number IS 'IMO number (7 digits, synthetic)';


--
-- Name: COLUMN dim_vessel.vessel_name; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_vessel.vessel_name IS 'Vessel name';


--
-- Name: COLUMN dim_vessel.vessel_category; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_vessel.vessel_category IS 'Suez tariff vessel category (13 values) = vessels.vessel_type; the budget is set per category';


--
-- Name: COLUMN dim_vessel.flag_country; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_vessel.flag_country IS 'Flag state';


--
-- Name: COLUMN dim_vessel.scnt_tons; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_vessel.scnt_tons IS 'Suez Canal Net Tonnage';


--
-- Name: COLUMN dim_vessel.condition; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_vessel.condition IS 'Laden or Ballast (vessel record)';


--
-- Name: COLUMN dim_vessel.origin_locode; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_vessel.origin_locode IS 'Origin port UN/LOCODE';


--
-- Name: COLUMN dim_vessel.origin_port; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_vessel.origin_port IS 'Origin port name';


--
-- Name: COLUMN dim_vessel.destination_locode; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_vessel.destination_locode IS 'Destination port UN/LOCODE';


--
-- Name: COLUMN dim_vessel.destination_port; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_vessel.destination_port IS 'Destination port name';


--
-- Name: COLUMN dim_vessel.route; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_vessel.route IS 'origin-destination LOCODE pair';


--
-- Name: COLUMN dim_vessel.customer_id; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_vessel.customer_id IS 'The customer billed for this vessel';


--
-- Name: dim_week; Type: VIEW; Schema: finance; Owner: -
--

CREATE VIEW finance.dim_week AS
 SELECT w AS report_week,
    format('2025-W%s'::text, lpad((w)::text, 2, '0'::text)) AS iso_week_label,
    ('2024-12-30'::date + (7 * (w - 1))) AS week_start,
    (('2024-12-30'::date + (7 * (w - 1))) + 6) AS week_end,
    GREATEST(((('2024-12-30'::date + (7 * (w - 1))) + 6) - 90), '2025-01-01'::date) AS dso_window_start,
    (((('2024-12-30'::date + (7 * (w - 1))) + 6) - GREATEST(((('2024-12-30'::date + (7 * (w - 1))) + 6) - 90), '2025-01-01'::date)) + 1) AS dso_window_days,
    ((((('2024-12-30'::date + (7 * (w - 1))) + 6) - '2025-01-01'::date) + 1) < 91) AS is_warmup
   FROM generate_series(1, 52) w(w);


--
-- Name: VIEW dim_week; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON VIEW finance.dim_week IS 'The 52 report weeks (ISO weeks of 2025, D12) with the DSO window. Level 2, Finance (schema level).';


--
-- Name: COLUMN dim_week.report_week; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_week.report_week IS 'Report week 1–52 = ISO week of 2025';


--
-- Name: COLUMN dim_week.iso_week_label; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_week.iso_week_label IS 'ISO week as text, e.g. 2025-W05';


--
-- Name: COLUMN dim_week.week_start; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_week.week_start IS 'Monday of the week';


--
-- Name: COLUMN dim_week.week_end; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_week.week_end IS 'Sunday of the week: every "as of" metric is measured at its end (23:59)';


--
-- Name: COLUMN dim_week.dso_window_start; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_week.dso_window_start IS 'First day of the DSO window: week_end − 90 days, not before 2025-01-01 (start of the billing history)';


--
-- Name: COLUMN dim_week.dso_window_days; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_week.dso_window_days IS 'Length of the DSO window in days: 91, or fewer in the warm-up weeks';


--
-- Name: COLUMN dim_week.is_warmup; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.dim_week.is_warmup IS 'True for weeks 1–13: less than 91 days of billing history, receivables still building up from zero (no 2024 invoices); DSO uses the shorter window (owner decision P2-2)';


--
-- Name: invoices; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.invoices (
    invoice_id integer NOT NULL,
    invoice_number text NOT NULL,
    vessel_id integer NOT NULL,
    toll_rate_band_id integer,
    invoice_date date NOT NULL,
    scnt_tons numeric NOT NULL,
    rate_sdr_per_ton numeric,
    amount numeric NOT NULL,
    description text,
    status text NOT NULL,
    CONSTRAINT invoices_amount_chk CHECK ((amount > (0)::numeric)),
    CONSTRAINT invoices_number_format_chk CHECK ((invoice_number ~ '^INV-[0-9]{7}$'::text)),
    CONSTRAINT invoices_rate_chk CHECK (((rate_sdr_per_ton IS NULL) OR (rate_sdr_per_ton > (0)::numeric))),
    CONSTRAINT invoices_scnt_tons_chk CHECK ((scnt_tons > (0)::numeric)),
    CONSTRAINT invoices_status_chk CHECK ((status = ANY (ARRAY['Issued'::text, 'Paid'::text, 'Pending'::text])))
);


--
-- Name: TABLE invoices; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.invoices IS 'Suez transit dues invoices (1,000, dated 2025), built in PostgreSQL (ADR-013). Level 2, Finance.';


--
-- Name: COLUMN invoices.invoice_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.invoices.invoice_id IS 'Surrogate key';


--
-- Name: COLUMN invoices.invoice_number; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.invoices.invoice_number IS 'Unique number INV-nnnnnnn';


--
-- Name: COLUMN invoices.vessel_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.invoices.vessel_id IS 'Invoiced vessel';


--
-- Name: COLUMN invoices.toll_rate_band_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.invoices.toll_rate_band_id IS 'Terminal toll band reached by the vessel SCNT (ADR-004)';


--
-- Name: COLUMN invoices.invoice_date; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.invoices.invoice_date IS 'Invoice date (2025)';


--
-- Name: COLUMN invoices.scnt_tons; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.invoices.scnt_tons IS 'SCNT of the vessel at invoicing';


--
-- Name: COLUMN invoices.rate_sdr_per_ton; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.invoices.rate_sdr_per_ton IS 'Rate of the terminal band, SDR per ton';


--
-- Name: COLUMN invoices.amount; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.invoices.amount IS 'Progressive sum over the bands, in SDR (ADR-003, ADR-004)';


--
-- Name: COLUMN invoices.description; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.invoices.description IS 'Free text, e.g. Suez Canal transit dues - <category>';


--
-- Name: COLUMN invoices.status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.invoices.status IS 'Original generator label (Issued / Pending / Paid), drawn at random over 2025 (ADR-013); NOT the payment state — the payment state is derived from payments by the finance views (Agents plan §4a, D6 amended 2026-10-13).';


--
-- Name: payments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.payments (
    invoice_number text NOT NULL,
    paid_date date NOT NULL,
    amount_sdr numeric NOT NULL,
    CONSTRAINT payments_amount_chk CHECK ((amount_sdr > (0)::numeric))
);


--
-- Name: TABLE payments; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.payments IS 'One full payment per paid invoice (no partial payments), up to 2026-03-31; an invoice without a row is unpaid. Level 2, Finance.';


--
-- Name: COLUMN payments.invoice_number; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.payments.invoice_number IS 'The paid invoice (FK invoices)';


--
-- Name: COLUMN payments.paid_date; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.payments.paid_date IS 'Date the payment was received';


--
-- Name: COLUMN payments.amount_sdr; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.payments.amount_sdr IS 'Amount paid in SDR (= the invoice amount)';


--
-- Name: fact_invoice; Type: VIEW; Schema: finance; Owner: -
--

CREATE VIEW finance.fact_invoice AS
 SELECT i.invoice_id,
    i.invoice_number,
    i.invoice_date,
        CASE
            WHEN (EXTRACT(isoyear FROM i.invoice_date) = (2025)::numeric) THEN (EXTRACT(week FROM i.invoice_date))::integer
            ELSE NULL::integer
        END AS invoice_report_week,
    v.customer_id,
    i.vessel_id,
    v.vessel_type AS vessel_category,
    b.laden_ballast AS priced_condition,
    i.toll_rate_band_id,
    i.scnt_tons,
    i.rate_sdr_per_ton,
    i.amount AS amount_sdr,
    c.payment_terms_days,
    (i.invoice_date + c.payment_terms_days) AS due_date,
    p.paid_date,
    (p.paid_date - i.invoice_date) AS days_to_pay,
    (p.paid_date - (i.invoice_date + c.payment_terms_days)) AS days_paid_after_due
   FROM ((((public.invoices i
     JOIN public.vessels v ON ((v.vessel_id = i.vessel_id)))
     JOIN public.customers c ON ((c.customer_id = v.customer_id)))
     LEFT JOIN public.toll_rate_bands b ON ((b.id = i.toll_rate_band_id)))
     LEFT JOIN public.payments p ON ((p.invoice_number = i.invoice_number)));


--
-- Name: VIEW fact_invoice; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON VIEW finance.fact_invoice IS 'One row per invoice with the derived due date and its payment (ADR-046: invoices.status is a label and is not used). Level 2, Finance.';


--
-- Name: COLUMN fact_invoice.invoice_id; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.fact_invoice.invoice_id IS 'Invoice id';


--
-- Name: COLUMN fact_invoice.invoice_number; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.fact_invoice.invoice_number IS 'Invoice number INV-nnnnnnn';


--
-- Name: COLUMN fact_invoice.invoice_date; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.fact_invoice.invoice_date IS 'Invoice (billing) date: revenue is counted in its week';


--
-- Name: COLUMN fact_invoice.invoice_report_week; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.fact_invoice.invoice_report_week IS 'Report week of the invoice date; NULL for 2025-12-29..31 (ISO 2026-W01)';


--
-- Name: COLUMN fact_invoice.customer_id; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.fact_invoice.customer_id IS 'Billed customer (through the vessel)';


--
-- Name: COLUMN fact_invoice.vessel_id; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.fact_invoice.vessel_id IS 'Vessel id';


--
-- Name: COLUMN fact_invoice.vessel_category; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.fact_invoice.vessel_category IS 'Vessel category (13 tariff categories)';


--
-- Name: COLUMN fact_invoice.priced_condition; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.fact_invoice.priced_condition IS 'Laden or Ballast as priced (from the terminal band; Special Floating Units always Laden)';


--
-- Name: COLUMN fact_invoice.toll_rate_band_id; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.fact_invoice.toll_rate_band_id IS 'Terminal band containing the vessel SCNT';


--
-- Name: COLUMN fact_invoice.scnt_tons; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.fact_invoice.scnt_tons IS 'Billed Suez Canal Net Tonnage';


--
-- Name: COLUMN fact_invoice.rate_sdr_per_ton; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.fact_invoice.rate_sdr_per_ton IS 'Rate of the terminal band (SDR per SCNT)';


--
-- Name: COLUMN fact_invoice.amount_sdr; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.fact_invoice.amount_sdr IS 'Invoice amount in SDR (progressive toll, ADR-003 / ADR-004)';


--
-- Name: COLUMN fact_invoice.payment_terms_days; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.fact_invoice.payment_terms_days IS 'Customer payment terms in days';


--
-- Name: COLUMN fact_invoice.due_date; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.fact_invoice.due_date IS 'Derived due date = invoice_date + payment_terms_days (not stored, ADR-046)';


--
-- Name: COLUMN fact_invoice.paid_date; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.fact_invoice.paid_date IS 'Date of the single full payment; NULL = unpaid at the 2026-03-31 horizon';


--
-- Name: COLUMN fact_invoice.days_to_pay; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.fact_invoice.days_to_pay IS 'paid_date − invoice_date in days; NULL if unpaid';


--
-- Name: COLUMN fact_invoice.days_paid_after_due; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.fact_invoice.days_paid_after_due IS 'paid_date − due_date in days (negative = paid early); NULL if unpaid';


--
-- Name: fact_ar_snapshot; Type: VIEW; Schema: finance; Owner: -
--

CREATE VIEW finance.fact_ar_snapshot AS
 SELECT w.report_week,
    w.week_end AS as_of_date,
    f.invoice_number,
    f.invoice_date,
    f.due_date,
    f.customer_id,
    f.vessel_id,
    f.vessel_category,
    f.amount_sdr,
    (w.week_end - f.due_date) AS days_past_due,
    ((w.week_end - f.due_date) > 0) AS is_overdue,
        CASE
            WHEN ((w.week_end - f.due_date) <= 0) THEN 'current'::text
            WHEN ((w.week_end - f.due_date) <= 30) THEN '1-30'::text
            WHEN ((w.week_end - f.due_date) <= 60) THEN '31-60'::text
            WHEN ((w.week_end - f.due_date) <= 90) THEN '61-90'::text
            ELSE '90+'::text
        END AS aging_bucket,
        CASE
            WHEN ((w.week_end - f.due_date) <= 0) THEN 1
            WHEN ((w.week_end - f.due_date) <= 30) THEN 2
            WHEN ((w.week_end - f.due_date) <= 60) THEN 3
            WHEN ((w.week_end - f.due_date) <= 90) THEN 4
            ELSE 5
        END AS aging_bucket_order
   FROM (finance.dim_week w
     JOIN finance.fact_invoice f ON (((f.invoice_date <= w.week_end) AND ((f.paid_date IS NULL) OR (f.paid_date > w.week_end)))));


--
-- Name: VIEW fact_ar_snapshot; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON VIEW finance.fact_ar_snapshot IS 'Receivables as of each report week: one row per invoice issued on or before the week''s Sunday and not paid by then, with its age past due. Level 2, Finance.';


--
-- Name: COLUMN fact_ar_snapshot.report_week; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.fact_ar_snapshot.report_week IS 'Report week';


--
-- Name: COLUMN fact_ar_snapshot.as_of_date; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.fact_ar_snapshot.as_of_date IS 'Sunday of the report week (as of 23:59)';


--
-- Name: COLUMN fact_ar_snapshot.invoice_number; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.fact_ar_snapshot.invoice_number IS 'Open invoice';


--
-- Name: COLUMN fact_ar_snapshot.invoice_date; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.fact_ar_snapshot.invoice_date IS 'Invoice date';


--
-- Name: COLUMN fact_ar_snapshot.due_date; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.fact_ar_snapshot.due_date IS 'Derived due date';


--
-- Name: COLUMN fact_ar_snapshot.customer_id; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.fact_ar_snapshot.customer_id IS 'Billed customer';


--
-- Name: COLUMN fact_ar_snapshot.vessel_id; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.fact_ar_snapshot.vessel_id IS 'Vessel id';


--
-- Name: COLUMN fact_ar_snapshot.vessel_category; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.fact_ar_snapshot.vessel_category IS 'Vessel category';


--
-- Name: COLUMN fact_ar_snapshot.amount_sdr; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.fact_ar_snapshot.amount_sdr IS 'Open amount in SDR (no partial payments: the full invoice amount)';


--
-- Name: COLUMN fact_ar_snapshot.days_past_due; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.fact_ar_snapshot.days_past_due IS 'as_of_date − due_date in days (≤ 0 = not yet due)';


--
-- Name: COLUMN fact_ar_snapshot.is_overdue; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.fact_ar_snapshot.is_overdue IS 'True when days_past_due ≥ 1';


--
-- Name: COLUMN fact_ar_snapshot.aging_bucket; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.fact_ar_snapshot.aging_bucket IS 'current (≤ 0), 1-30, 31-60, 61-90 or 90+ days past due';


--
-- Name: COLUMN fact_ar_snapshot.aging_bucket_order; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.fact_ar_snapshot.aging_bucket_order IS 'Sort order of aging_bucket, 1 = current … 5 = 90+';


--
-- Name: fact_payment; Type: VIEW; Schema: finance; Owner: -
--

CREATE VIEW finance.fact_payment AS
 SELECT p.invoice_number,
    p.paid_date,
        CASE
            WHEN (EXTRACT(isoyear FROM p.paid_date) = (2025)::numeric) THEN (EXTRACT(week FROM p.paid_date))::integer
            ELSE NULL::integer
        END AS paid_report_week,
    p.amount_sdr,
    f.invoice_date,
    f.due_date,
    f.customer_id,
    f.vessel_id,
    f.vessel_category,
    f.days_to_pay,
    f.days_paid_after_due
   FROM (public.payments p
     JOIN finance.fact_invoice f ON ((f.invoice_number = p.invoice_number)));


--
-- Name: VIEW fact_payment; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON VIEW finance.fact_payment IS 'One row per payment (one full payment per paid invoice): collections are counted in the week of paid_date. Level 2, Finance.';


--
-- Name: COLUMN fact_payment.invoice_number; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.fact_payment.invoice_number IS 'Paid invoice';


--
-- Name: COLUMN fact_payment.paid_date; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.fact_payment.paid_date IS 'Payment date';


--
-- Name: COLUMN fact_payment.paid_report_week; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.fact_payment.paid_report_week IS 'Report week of the payment; NULL for payments in ISO 2026';


--
-- Name: COLUMN fact_payment.amount_sdr; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.fact_payment.amount_sdr IS 'Amount received in SDR (= the invoice amount)';


--
-- Name: COLUMN fact_payment.invoice_date; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.fact_payment.invoice_date IS 'Invoice date of the paid invoice';


--
-- Name: COLUMN fact_payment.due_date; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.fact_payment.due_date IS 'Derived due date of the paid invoice';


--
-- Name: COLUMN fact_payment.customer_id; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.fact_payment.customer_id IS 'Paying customer';


--
-- Name: COLUMN fact_payment.vessel_id; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.fact_payment.vessel_id IS 'Vessel of the paid invoice';


--
-- Name: COLUMN fact_payment.vessel_category; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.fact_payment.vessel_category IS 'Vessel category of the paid invoice';


--
-- Name: COLUMN fact_payment.days_to_pay; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.fact_payment.days_to_pay IS 'paid_date − invoice_date in days';


--
-- Name: COLUMN fact_payment.days_paid_after_due; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.fact_payment.days_paid_after_due IS 'paid_date − due_date in days (negative = paid early)';


--
-- Name: invoice_audit; Type: VIEW; Schema: finance; Owner: -
--

CREATE VIEW finance.invoice_audit AS
 WITH billed AS (
         SELECT i.invoice_number,
            i.vessel_id,
            i.invoice_date,
            i.scnt_tons,
            i.amount AS billed_sdr,
            i.rate_sdr_per_ton AS billed_rate
           FROM public.invoices i
        ), inv AS (
         SELECT b.invoice_number,
            b.vessel_id,
            b.invoice_date,
            b.scnt_tons,
            b.billed_sdr,
            b.billed_rate,
            v.vessel_name,
            v.vessel_type AS vessel_category,
            v.condition,
            v.scnt_tons AS vessel_scnt,
                CASE
                    WHEN (v.vessel_type = 'Special Floating Units'::text) THEN 'Laden'::text
                    ELSE v.condition
                END AS priced_condition,
            d.report_week
           FROM ((billed b
             JOIN public.vessels v ON ((v.vessel_id = b.vessel_id)))
             JOIN finance.dim_date d ON ((d.date_day = b.invoice_date)))
        ), scenario AS (
         SELECT inv.invoice_number,
            'expected'::text AS scenario,
            inv.vessel_category AS category,
            inv.priced_condition AS cond,
            inv.vessel_scnt AS tons
           FROM inv
        UNION ALL
         SELECT inv.invoice_number,
            'invoice_tonnage'::text,
            inv.vessel_category,
            inv.priced_condition,
            inv.scnt_tons
           FROM inv
          WHERE (inv.scnt_tons <> inv.vessel_scnt)
        UNION ALL
         SELECT inv.invoice_number,
            'condition_swapped'::text,
            inv.vessel_category,
                CASE inv.condition
                    WHEN 'Laden'::text THEN 'Ballast'::text
                    ELSE 'Laden'::text
                END AS "case",
            inv.vessel_scnt
           FROM inv
          WHERE (inv.vessel_category <> 'Special Floating Units'::text)
        UNION ALL
         SELECT inv.invoice_number,
            'sfu_priced_ballast'::text,
            'Other Vessels'::text,
            'Ballast'::text,
            inv.vessel_scnt
           FROM inv
          WHERE (inv.vessel_category = 'Special Floating Units'::text)
        UNION ALL
         SELECT inv.invoice_number,
            'notes_crude_ballast'::text,
            'Crude Oil Tankers'::text,
            'Ballast'::text,
            inv.vessel_scnt
           FROM inv
          WHERE ((inv.priced_condition = 'Ballast'::text) AND (inv.vessel_category = 'Chemical Tankers & Other Liquid Bulk Tankers'::text))
        ), priced AS (
         SELECT s.invoice_number,
            s.scenario,
            sum((t.rate_sdr_per_ton * (LEAST(s.tons, COALESCE(t.band_max_tons, s.tons)) - t.band_min_tons))) AS toll_exact,
            (array_agg(t.rate_sdr_per_ton ORDER BY t.band_order DESC))[1] AS terminal_rate,
            (array_agg(t.band_label ORDER BY t.band_order DESC))[1] AS terminal_band
           FROM (scenario s
             JOIN public.toll_rate_bands t ON (((t.vessel_category = s.category) AND (t.laden_ballast = s.cond) AND (s.tons > t.band_min_tons))))
          GROUP BY s.invoice_number, s.scenario
        ), hyp AS (
         SELECT i.invoice_number,
            i.vessel_id,
            i.invoice_date,
            i.scnt_tons,
            i.billed_sdr,
            i.billed_rate,
            i.vessel_name,
            i.vessel_category,
            i.condition,
            i.vessel_scnt,
            i.priced_condition,
            i.report_week,
            e.toll_exact AS expected_exact,
            round(e.toll_exact, 2) AS expected_sdr,
            e.terminal_rate,
            e.terminal_band,
            round(it.toll_exact, 2) AS invoice_tonnage_sdr,
            round((e.terminal_rate * i.vessel_scnt), 2) AS flat_terminal_sdr,
            round(cs.toll_exact, 2) AS condition_swapped_sdr,
            round(sb.toll_exact, 2) AS sfu_ballast_sdr,
            round(nc.toll_exact, 2) AS notes_crude_sdr,
            row_number() OVER w AS dup_rank,
            first_value(i.invoice_number) OVER w AS dup_first
           FROM (((((inv i
             JOIN priced e ON (((e.invoice_number = i.invoice_number) AND (e.scenario = 'expected'::text))))
             LEFT JOIN priced it ON (((it.invoice_number = i.invoice_number) AND (it.scenario = 'invoice_tonnage'::text))))
             LEFT JOIN priced cs ON (((cs.invoice_number = i.invoice_number) AND (cs.scenario = 'condition_swapped'::text))))
             LEFT JOIN priced sb ON (((sb.invoice_number = i.invoice_number) AND (sb.scenario = 'sfu_priced_ballast'::text))))
             LEFT JOIN priced nc ON (((nc.invoice_number = i.invoice_number) AND (nc.scenario = 'notes_crude_ballast'::text))))
          WINDOW w AS (PARTITION BY i.vessel_id, i.invoice_date, i.billed_sdr ORDER BY i.invoice_number)
        ), findings AS (
         SELECT h.invoice_number,
            h.vessel_id,
            h.invoice_date,
            h.scnt_tons,
            h.billed_sdr,
            h.billed_rate,
            h.vessel_name,
            h.vessel_category,
            h.condition,
            h.vessel_scnt,
            h.priced_condition,
            h.report_week,
            h.expected_exact,
            h.expected_sdr,
            h.terminal_rate,
            h.terminal_band,
            h.invoice_tonnage_sdr,
            h.flat_terminal_sdr,
            h.condition_swapped_sdr,
            h.sfu_ballast_sdr,
            h.notes_crude_sdr,
            h.dup_rank,
            h.dup_first,
            'duplicate_charge'::text AS check_code,
            NULL::text AS probable_cause,
            (0)::numeric AS expected_charge,
            h.dup_first AS duplicate_of,
            format('same vessel, date and amount as %s: the whole charge is billed twice'::text, h.dup_first) AS evidence
           FROM hyp h
          WHERE (h.dup_rank > 1)
        UNION ALL
         SELECT h.invoice_number,
            h.vessel_id,
            h.invoice_date,
            h.scnt_tons,
            h.billed_sdr,
            h.billed_rate,
            h.vessel_name,
            h.vessel_category,
            h.condition,
            h.vessel_scnt,
            h.priced_condition,
            h.report_week,
            h.expected_exact,
            h.expected_sdr,
            h.terminal_rate,
            h.terminal_band,
            h.invoice_tonnage_sdr,
            h.flat_terminal_sdr,
            h.condition_swapped_sdr,
            h.sfu_ballast_sdr,
            h.notes_crude_sdr,
            h.dup_rank,
            h.dup_first,
            'tonnage_mismatch'::text,
            NULL::text,
            h.expected_sdr,
            NULL::text,
            format('invoice SCNT %s <> vessel SCNT %s'::text, h.scnt_tons, h.vessel_scnt) AS format
           FROM hyp h
          WHERE ((h.dup_rank = 1) AND (h.scnt_tons <> h.vessel_scnt))
        UNION ALL
         SELECT h.invoice_number,
            h.vessel_id,
            h.invoice_date,
            h.scnt_tons,
            h.billed_sdr,
            h.billed_rate,
            h.vessel_name,
            h.vessel_category,
            h.condition,
            h.vessel_scnt,
            h.priced_condition,
            h.report_week,
            h.expected_exact,
            h.expected_sdr,
            h.terminal_rate,
            h.terminal_band,
            h.invoice_tonnage_sdr,
            h.flat_terminal_sdr,
            h.condition_swapped_sdr,
            h.sfu_ballast_sdr,
            h.notes_crude_sdr,
            h.dup_rank,
            h.dup_first,
            'amount_mismatch'::text,
                CASE
                    WHEN (abs((h.billed_sdr - h.invoice_tonnage_sdr)) <= 0.01) THEN 'billed_on_invoice_tonnage'::text
                    WHEN (abs((h.billed_sdr - h.flat_terminal_sdr)) <= 0.01) THEN 'flat_terminal_rate'::text
                    WHEN (abs((h.billed_sdr - h.condition_swapped_sdr)) <= 0.01) THEN 'condition_swapped'::text
                    WHEN (abs((h.billed_sdr - h.sfu_ballast_sdr)) <= 0.01) THEN 'sfu_priced_ballast'::text
                    WHEN (abs((h.billed_sdr - h.notes_crude_sdr)) <= 0.01) THEN 'notes_crude_ballast_rate'::text
                    ELSE 'unexplained'::text
                END AS "case",
            h.expected_sdr,
            NULL::text,
            format('billed %s SDR; tariff %s / %s at %s SCNT = %s SDR (progressive, terminal band %s at %s SDR/t)'::text, h.billed_sdr, h.vessel_category, h.priced_condition, h.vessel_scnt, h.expected_sdr, h.terminal_band, h.terminal_rate) AS format
           FROM hyp h
          WHERE ((h.dup_rank = 1) AND (abs((h.billed_sdr - h.expected_exact)) > 0.01))
        UNION ALL
         SELECT h.invoice_number,
            h.vessel_id,
            h.invoice_date,
            h.scnt_tons,
            h.billed_sdr,
            h.billed_rate,
            h.vessel_name,
            h.vessel_category,
            h.condition,
            h.vessel_scnt,
            h.priced_condition,
            h.report_week,
            h.expected_exact,
            h.expected_sdr,
            h.terminal_rate,
            h.terminal_band,
            h.invoice_tonnage_sdr,
            h.flat_terminal_sdr,
            h.condition_swapped_sdr,
            h.sfu_ballast_sdr,
            h.notes_crude_sdr,
            h.dup_rank,
            h.dup_first,
            'rate_mismatch'::text,
            NULL::text,
            h.expected_sdr,
            NULL::text,
            format('stored rate %s SDR/t <> terminal band %s rate %s SDR/t'::text, h.billed_rate, h.terminal_band, h.terminal_rate) AS format
           FROM hyp h
          WHERE ((h.dup_rank = 1) AND (h.billed_rate IS NOT NULL) AND (h.billed_rate <> h.terminal_rate))
        )
 SELECT report_week,
    invoice_number,
    invoice_date,
    vessel_id,
    vessel_name,
    vessel_category,
    condition AS vessel_condition,
    check_code,
    probable_cause,
    billed_sdr,
    expected_charge AS expected_sdr,
    round((billed_sdr - expected_charge), 2) AS difference_sdr,
    duplicate_of,
    evidence,
        CASE
            WHEN (probable_cause = 'notes_crude_ballast_rate'::text) THEN 'manual_review'::text
            ELSE 'error'::text
        END AS review
   FROM findings;


--
-- Name: VIEW invoice_audit; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON VIEW finance.invoice_audit IS 'Invoice audit findings (Agents plan §5a, migration 015): every invoice recomputed from the progressive toll bands (ADR-004); one row per finding (duplicate_charge, tonnage_mismatch, amount_mismatch with a probable cause, rate_mismatch). No row = the invoice passed. Read by the invoice_audit tool and the Exceptions page. Level 2, Finance.';


--
-- Name: COLUMN invoice_audit.report_week; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.invoice_audit.report_week IS 'Report week of the invoice date (ISO 2025 week; NULL for 2026-W01)';


--
-- Name: COLUMN invoice_audit.invoice_number; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.invoice_audit.invoice_number IS 'The invoice with the finding';


--
-- Name: COLUMN invoice_audit.invoice_date; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.invoice_audit.invoice_date IS 'Invoice date';


--
-- Name: COLUMN invoice_audit.vessel_id; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.invoice_audit.vessel_id IS 'The billed vessel';


--
-- Name: COLUMN invoice_audit.vessel_name; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.invoice_audit.vessel_name IS 'Vessel name';


--
-- Name: COLUMN invoice_audit.vessel_category; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.invoice_audit.vessel_category IS 'Tariff category of the vessel (vessels.vessel_type)';


--
-- Name: COLUMN invoice_audit.vessel_condition; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.invoice_audit.vessel_condition IS 'Condition of the vessel (vessels.condition); Special Floating Units are priced Laden';


--
-- Name: COLUMN invoice_audit.check_code; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.invoice_audit.check_code IS 'duplicate_charge | tonnage_mismatch | amount_mismatch | rate_mismatch';


--
-- Name: COLUMN invoice_audit.probable_cause; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.invoice_audit.probable_cause IS 'amount_mismatch only: billed_on_invoice_tonnage | flat_terminal_rate | condition_swapped | sfu_priced_ballast | notes_crude_ballast_rate | unexplained (the first hypothesis that reproduces the billed amount within 0.01 SDR)';


--
-- Name: COLUMN invoice_audit.billed_sdr; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.invoice_audit.billed_sdr IS 'Amount billed (SDR)';


--
-- Name: COLUMN invoice_audit.expected_sdr; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.invoice_audit.expected_sdr IS 'Correct charge (SDR): the progressive toll of the vessel; 0 for a duplicate';


--
-- Name: COLUMN invoice_audit.difference_sdr; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.invoice_audit.difference_sdr IS 'billed - expected (SDR): positive = overbilled, negative = underbilled';


--
-- Name: COLUMN invoice_audit.duplicate_of; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.invoice_audit.duplicate_of IS 'duplicate_charge only: the original invoice number';


--
-- Name: COLUMN invoice_audit.evidence; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.invoice_audit.evidence IS 'The numbers behind the finding (tons, category, condition, band, rate)';


--
-- Name: COLUMN invoice_audit.review; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.invoice_audit.review IS 'error | manual_review: manual_review = priced by a tariff Notes rule (a ballast chemical tanker at the Crude Oil Tankers ballast rates — right if it is an oil/chemical tanker, migration 019) — confirm the rule, it may be correct; not counted as money at stake';


--
-- Name: kpi_customer_13w; Type: VIEW; Schema: finance; Owner: -
--

CREATE VIEW finance.kpi_customer_13w AS
 WITH grid AS (
         SELECT w.report_week,
            w.week_start,
            w.week_end,
            c_1.customer_id
           FROM (finance.dim_week w
             CROSS JOIN public.customers c_1)
        ), billing AS (
         SELECT g.report_week,
            g.customer_id,
            COALESCE(sum(f.amount_sdr) FILTER (WHERE (f.invoice_date >= g.week_start)), (0)::numeric) AS billed_week_sdr,
            COALESCE(sum(f.amount_sdr), (0)::numeric) AS billed_13w_sdr
           FROM (grid g
             LEFT JOIN finance.fact_invoice f ON (((f.customer_id = g.customer_id) AND ((f.invoice_date >= (g.week_end - 90)) AND (f.invoice_date <= g.week_end)))))
          GROUP BY g.report_week, g.customer_id
        ), open_ar AS (
         SELECT fact_ar_snapshot.report_week,
            fact_ar_snapshot.customer_id,
            sum(fact_ar_snapshot.amount_sdr) AS ar_sdr,
            sum(fact_ar_snapshot.amount_sdr) FILTER (WHERE fact_ar_snapshot.is_overdue) AS overdue_sdr
           FROM finance.fact_ar_snapshot
          GROUP BY fact_ar_snapshot.report_week, fact_ar_snapshot.customer_id
        ), ranked AS (
         SELECT b.report_week,
            b.customer_id,
            b.billed_week_sdr,
            b.billed_13w_sdr,
            sum(b.billed_13w_sdr) OVER (PARTITION BY b.report_week) AS total_13w_sdr,
            row_number() OVER (PARTITION BY b.report_week ORDER BY b.billed_13w_sdr DESC, b.customer_id) AS rank_13w
           FROM billing b
        )
 SELECT r.report_week,
    r.customer_id,
    c.customer_name,
    c.segment,
    c.country,
    c.credit_rating,
    c.payment_terms_days,
    round(r.billed_week_sdr, 2) AS billed_week_sdr,
    round(r.billed_13w_sdr, 2) AS billed_13w_sdr,
    round((((100)::numeric * r.billed_13w_sdr) / NULLIF(r.total_13w_sdr, (0)::numeric)), 2) AS share_13w_pct,
    r.rank_13w,
    lag(r.rank_13w) OVER (PARTITION BY r.customer_id ORDER BY r.report_week) AS rank_13w_prev,
    ((r.rank_13w <= 10) AND (r.billed_13w_sdr > (0)::numeric)) AS is_top10,
    round(COALESCE(o.ar_sdr, (0)::numeric), 2) AS ar_sdr,
    round(COALESCE(o.overdue_sdr, (0)::numeric), 2) AS overdue_sdr
   FROM ((ranked r
     JOIN public.customers c ON ((c.customer_id = r.customer_id)))
     LEFT JOIN open_ar o ON (((o.report_week = r.report_week) AND (o.customer_id = r.customer_id))));


--
-- Name: VIEW kpi_customer_13w; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON VIEW finance.kpi_customer_13w IS 'Every customer in every report week: billing of the week and of the trailing 13 weeks (91 days ending Sunday), share, rank, receivables. Level 2, Finance.';


--
-- Name: COLUMN kpi_customer_13w.report_week; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_customer_13w.report_week IS 'Report week';


--
-- Name: COLUMN kpi_customer_13w.customer_id; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_customer_13w.customer_id IS 'Customer id';


--
-- Name: COLUMN kpi_customer_13w.customer_name; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_customer_13w.customer_name IS 'Customer name';


--
-- Name: COLUMN kpi_customer_13w.segment; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_customer_13w.segment IS 'Customer segment';


--
-- Name: COLUMN kpi_customer_13w.country; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_customer_13w.country IS 'Head-office country';


--
-- Name: COLUMN kpi_customer_13w.credit_rating; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_customer_13w.credit_rating IS 'Credit rating A, B or C';


--
-- Name: COLUMN kpi_customer_13w.payment_terms_days; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_customer_13w.payment_terms_days IS 'Payment terms in days';


--
-- Name: COLUMN kpi_customer_13w.billed_week_sdr; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_customer_13w.billed_week_sdr IS 'Billed in the report week (SDR, 2 decimals)';


--
-- Name: COLUMN kpi_customer_13w.billed_13w_sdr; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_customer_13w.billed_13w_sdr IS 'Billed in the trailing 13 weeks = 91 days ending the week''s Sunday (SDR, 2 decimals)';


--
-- Name: COLUMN kpi_customer_13w.share_13w_pct; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_customer_13w.share_13w_pct IS 'Share of all billing in the trailing 13 weeks, percent (2 decimals)';


--
-- Name: COLUMN kpi_customer_13w.rank_13w; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_customer_13w.rank_13w IS 'Rank by billed_13w_sdr (1 = largest; ties by customer_id)';


--
-- Name: COLUMN kpi_customer_13w.rank_13w_prev; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_customer_13w.rank_13w_prev IS 'rank_13w in the previous report week; NULL in week 1';


--
-- Name: COLUMN kpi_customer_13w.is_top10; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_customer_13w.is_top10 IS 'True for ranks 1–10 with billing > 0 in the trailing 13 weeks';


--
-- Name: COLUMN kpi_customer_13w.ar_sdr; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_customer_13w.ar_sdr IS 'Open receivables of the customer as of the week''s Sunday (SDR)';


--
-- Name: COLUMN kpi_customer_13w.overdue_sdr; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_customer_13w.overdue_sdr IS 'Overdue part of ar_sdr (SDR)';


--
-- Name: kpi_overdue_list; Type: VIEW; Schema: finance; Owner: -
--

CREATE VIEW finance.kpi_overdue_list AS
 SELECT a.report_week,
    a.as_of_date,
    a.invoice_number,
    a.customer_id,
    c.customer_name,
    a.vessel_id,
    v.vessel_name,
    a.vessel_category,
    a.invoice_date,
    a.due_date,
    a.amount_sdr,
    a.days_past_due,
    a.aging_bucket,
    row_number() OVER (PARTITION BY a.report_week ORDER BY a.amount_sdr DESC, a.invoice_number) AS rank_by_amount
   FROM ((finance.fact_ar_snapshot a
     JOIN public.customers c ON ((c.customer_id = a.customer_id)))
     JOIN public.vessels v ON ((v.vessel_id = a.vessel_id)))
  WHERE a.is_overdue;


--
-- Name: VIEW kpi_overdue_list; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON VIEW finance.kpi_overdue_list IS 'Overdue invoices (≥ 1 day past due) as of each report week, ranked by amount. Level 2, Finance.';


--
-- Name: COLUMN kpi_overdue_list.report_week; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_overdue_list.report_week IS 'Report week';


--
-- Name: COLUMN kpi_overdue_list.as_of_date; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_overdue_list.as_of_date IS 'Sunday of the report week';


--
-- Name: COLUMN kpi_overdue_list.invoice_number; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_overdue_list.invoice_number IS 'Overdue invoice';


--
-- Name: COLUMN kpi_overdue_list.customer_id; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_overdue_list.customer_id IS 'Customer id';


--
-- Name: COLUMN kpi_overdue_list.customer_name; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_overdue_list.customer_name IS 'Customer name';


--
-- Name: COLUMN kpi_overdue_list.vessel_id; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_overdue_list.vessel_id IS 'Vessel id';


--
-- Name: COLUMN kpi_overdue_list.vessel_name; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_overdue_list.vessel_name IS 'Vessel name';


--
-- Name: COLUMN kpi_overdue_list.vessel_category; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_overdue_list.vessel_category IS 'Vessel category';


--
-- Name: COLUMN kpi_overdue_list.invoice_date; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_overdue_list.invoice_date IS 'Invoice date';


--
-- Name: COLUMN kpi_overdue_list.due_date; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_overdue_list.due_date IS 'Derived due date';


--
-- Name: COLUMN kpi_overdue_list.amount_sdr; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_overdue_list.amount_sdr IS 'Open amount (SDR)';


--
-- Name: COLUMN kpi_overdue_list.days_past_due; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_overdue_list.days_past_due IS 'Days past due as of the Sunday';


--
-- Name: COLUMN kpi_overdue_list.aging_bucket; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_overdue_list.aging_bucket IS '1-30, 31-60, 61-90 or 90+';


--
-- Name: COLUMN kpi_overdue_list.rank_by_amount; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_overdue_list.rank_by_amount IS 'Rank within the week by amount (1 = largest)';


--
-- Name: budget_weekly; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.budget_weekly (
    budget_year integer NOT NULL,
    iso_week integer NOT NULL,
    vessel_category text NOT NULL,
    budget_sdr numeric NOT NULL,
    CONSTRAINT budget_weekly_amount_chk CHECK ((budget_sdr >= (0)::numeric)),
    CONSTRAINT budget_weekly_category_chk CHECK ((vessel_category = ANY (ARRAY['Chemical Tankers & Other Liquid Bulk Tankers'::text, 'Containerships'::text, 'Crude Oil Tankers'::text, 'Cruise Ships'::text, 'Dry Bulk Vessels'::text, 'General Cargo / Multi-Purpose / Heavy Lift Vessels'::text, 'Liquefied Natural Gas (LNG) Carriers'::text, 'Liquefied Petroleum Gas (LPG) Carriers'::text, 'Other Vessels'::text, 'Petroleum Product Tankers'::text, 'Roll-On/Roll-Off (Ro/Ro) Vessels'::text, 'Special Floating Units'::text, 'Vehicles Carriers'::text]))),
    CONSTRAINT budget_weekly_week_chk CHECK (((iso_week >= 1) AND (iso_week <= 52))),
    CONSTRAINT budget_weekly_year_chk CHECK ((budget_year = 2025))
);


--
-- Name: TABLE budget_weekly; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.budget_weekly IS 'Weekly budget 2025 per vessel category: a planning model (fleet x 2.0 transits x median-tonnage laden toll, seasonal +/-6 %), not fitted to the invoices (Agents plan §4a R6). Level 2, Finance.';


--
-- Name: COLUMN budget_weekly.budget_year; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.budget_weekly.budget_year IS 'Budget year (2025 only)';


--
-- Name: COLUMN budget_weekly.iso_week; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.budget_weekly.iso_week IS 'ISO week of the budget year';


--
-- Name: COLUMN budget_weekly.vessel_category; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.budget_weekly.vessel_category IS 'Suez tariff vessel category (same 13 values as vessels.vessel_type)';


--
-- Name: COLUMN budget_weekly.budget_sdr; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.budget_weekly.budget_sdr IS 'Budgeted transit dues in SDR';


--
-- Name: kpi_weekly; Type: VIEW; Schema: finance; Owner: -
--

CREATE VIEW finance.kpi_weekly AS
 WITH billed AS (
         SELECT w.report_week,
            count(f.invoice_id) AS invoices_billed,
            COALESCE(sum(f.amount_sdr), (0)::numeric) AS billed_sdr
           FROM (finance.dim_week w
             LEFT JOIN finance.fact_invoice f ON (((f.invoice_date >= w.week_start) AND (f.invoice_date <= w.week_end))))
          GROUP BY w.report_week
        ), collected AS (
         SELECT w.report_week,
            count(p.invoice_number) AS payments_received,
            COALESCE(sum(p.amount_sdr), (0)::numeric) AS collected_sdr
           FROM (finance.dim_week w
             LEFT JOIN finance.fact_payment p ON (((p.paid_date >= w.week_start) AND (p.paid_date <= w.week_end))))
          GROUP BY w.report_week
        ), ar AS (
         SELECT w.report_week,
            count(a.invoice_number) AS ar_invoices,
            COALESCE(sum(a.amount_sdr), (0)::numeric) AS ar_sdr,
            count(a.invoice_number) FILTER (WHERE a.is_overdue) AS overdue_invoices,
            COALESCE(sum(a.amount_sdr) FILTER (WHERE a.is_overdue), (0)::numeric) AS overdue_sdr,
            COALESCE(sum(a.amount_sdr) FILTER (WHERE (a.aging_bucket = 'current'::text)), (0)::numeric) AS aging_current_sdr,
            COALESCE(sum(a.amount_sdr) FILTER (WHERE (a.aging_bucket = '1-30'::text)), (0)::numeric) AS aging_1_30_sdr,
            COALESCE(sum(a.amount_sdr) FILTER (WHERE (a.aging_bucket = '31-60'::text)), (0)::numeric) AS aging_31_60_sdr,
            COALESCE(sum(a.amount_sdr) FILTER (WHERE (a.aging_bucket = '61-90'::text)), (0)::numeric) AS aging_61_90_sdr,
            COALESCE(sum(a.amount_sdr) FILTER (WHERE (a.aging_bucket = '90+'::text)), (0)::numeric) AS aging_90_plus_sdr
           FROM (finance.dim_week w
             LEFT JOIN finance.fact_ar_snapshot a ON ((a.report_week = w.report_week)))
          GROUP BY w.report_week
        ), dso_base AS (
         SELECT w.report_week,
            COALESCE(sum(f.amount_sdr), (0)::numeric) AS dso_window_billed_sdr
           FROM (finance.dim_week w
             LEFT JOIN finance.fact_invoice f ON (((f.invoice_date >= w.dso_window_start) AND (f.invoice_date <= w.week_end))))
          GROUP BY w.report_week
        ), budget AS (
         SELECT budget_weekly.iso_week AS report_week,
            sum(budget_weekly.budget_sdr) AS budget_sdr
           FROM public.budget_weekly
          WHERE (budget_weekly.budget_year = 2025)
          GROUP BY budget_weekly.iso_week
        ), concentration AS (
         SELECT kpi_customer_13w.report_week,
            (sum(kpi_customer_13w.billed_13w_sdr) FILTER (WHERE kpi_customer_13w.is_top10) / NULLIF(sum(kpi_customer_13w.billed_13w_sdr), (0)::numeric)) AS top10_share
           FROM finance.kpi_customer_13w
          GROUP BY kpi_customer_13w.report_week
        ), base AS (
         SELECT w.report_week,
            w.iso_week_label,
            w.week_start,
            w.week_end,
            w.is_warmup,
            w.dso_window_days,
            b.invoices_billed,
            b.billed_sdr,
            c.payments_received,
            c.collected_sdr,
            a.ar_invoices,
            a.ar_sdr,
            a.overdue_invoices,
            a.overdue_sdr,
            a.aging_current_sdr,
            a.aging_1_30_sdr,
            a.aging_31_60_sdr,
            a.aging_61_90_sdr,
            a.aging_90_plus_sdr,
            d.dso_window_billed_sdr,
            ((a.ar_sdr / NULLIF(d.dso_window_billed_sdr, (0)::numeric)) * (w.dso_window_days)::numeric) AS dso_days,
            bu.budget_sdr,
            k.top10_share
           FROM ((((((finance.dim_week w
             JOIN billed b ON ((b.report_week = w.report_week)))
             JOIN collected c ON ((c.report_week = w.report_week)))
             JOIN ar a ON ((a.report_week = w.report_week)))
             JOIN dso_base d ON ((d.report_week = w.report_week)))
             LEFT JOIN budget bu ON ((bu.report_week = w.report_week)))
             LEFT JOIN concentration k ON ((k.report_week = w.report_week)))
        )
 SELECT report_week,
    iso_week_label,
    week_start,
    week_end,
    is_warmup,
    invoices_billed,
    round(billed_sdr, 2) AS billed_sdr,
    payments_received,
    round(collected_sdr, 2) AS collected_sdr,
    ar_invoices,
    round(ar_sdr, 2) AS ar_sdr,
    overdue_invoices,
    round(overdue_sdr, 2) AS overdue_sdr,
    round(aging_current_sdr, 2) AS aging_current_sdr,
    round(aging_1_30_sdr, 2) AS aging_1_30_sdr,
    round(aging_31_60_sdr, 2) AS aging_31_60_sdr,
    round(aging_61_90_sdr, 2) AS aging_61_90_sdr,
    round(aging_90_plus_sdr, 2) AS aging_90_plus_sdr,
    dso_window_days,
    round(dso_window_billed_sdr, 2) AS dso_window_billed_sdr,
    round(dso_days, 1) AS dso_days,
    round(budget_sdr, 2) AS budget_sdr,
    round((billed_sdr - budget_sdr), 2) AS budget_variance_sdr,
    round((((100)::numeric * (billed_sdr - budget_sdr)) / NULLIF(budget_sdr, (0)::numeric)), 2) AS budget_variance_pct,
    round(((100)::numeric * top10_share), 2) AS top10_share_13w_pct,
    round((((100)::numeric * (billed_sdr - lag(billed_sdr) OVER wk)) / NULLIF(lag(billed_sdr) OVER wk, (0)::numeric)), 2) AS billed_wow_pct,
    round((((100)::numeric * (collected_sdr - lag(collected_sdr) OVER wk)) / NULLIF(lag(collected_sdr) OVER wk, (0)::numeric)), 2) AS collected_wow_pct,
    round((((100)::numeric * (ar_sdr - lag(ar_sdr) OVER wk)) / NULLIF(lag(ar_sdr) OVER wk, (0)::numeric)), 2) AS ar_wow_pct,
    round((((100)::numeric * (overdue_sdr - lag(overdue_sdr) OVER wk)) / NULLIF(lag(overdue_sdr) OVER wk, (0)::numeric)), 2) AS overdue_wow_pct,
    round((dso_days - lag(dso_days) OVER wk), 1) AS dso_wow_days
   FROM base
  WINDOW wk AS (ORDER BY report_week);


--
-- Name: VIEW kpi_weekly; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON VIEW finance.kpi_weekly IS 'Company KPIs, one row per report week (definitions: docs/finance_metrics.md). Money SDR 2 decimals, *_pct percent 2 decimals, days 1 decimal; WoW NULL in week 1. Level 2, Finance.';


--
-- Name: COLUMN kpi_weekly.report_week; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly.report_week IS 'Report week 1–52';


--
-- Name: COLUMN kpi_weekly.iso_week_label; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly.iso_week_label IS 'ISO week as text';


--
-- Name: COLUMN kpi_weekly.week_start; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly.week_start IS 'Monday of the week';


--
-- Name: COLUMN kpi_weekly.week_end; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly.week_end IS 'Sunday of the week (as of 23:59)';


--
-- Name: COLUMN kpi_weekly.is_warmup; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly.is_warmup IS 'Weeks 1–13: under 91 days of history, receivables still building up; DSO on a shorter window';


--
-- Name: COLUMN kpi_weekly.invoices_billed; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly.invoices_billed IS 'Number of invoices dated in the week';


--
-- Name: COLUMN kpi_weekly.billed_sdr; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly.billed_sdr IS 'Billed revenue: sum of invoice amounts dated in the week (SDR)';


--
-- Name: COLUMN kpi_weekly.payments_received; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly.payments_received IS 'Number of payments dated in the week';


--
-- Name: COLUMN kpi_weekly.collected_sdr; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly.collected_sdr IS 'Collections: sum of payments dated in the week (SDR)';


--
-- Name: COLUMN kpi_weekly.ar_invoices; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly.ar_invoices IS 'Number of open invoices at the week end';


--
-- Name: COLUMN kpi_weekly.ar_sdr; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly.ar_sdr IS 'Accounts receivable at the week end: invoices issued by Sunday and unpaid by Sunday (SDR)';


--
-- Name: COLUMN kpi_weekly.overdue_invoices; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly.overdue_invoices IS 'Number of open invoices at least 1 day past due';


--
-- Name: COLUMN kpi_weekly.overdue_sdr; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly.overdue_sdr IS 'Overdue receivables (≥ 1 day past due) at the week end (SDR)';


--
-- Name: COLUMN kpi_weekly.aging_current_sdr; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly.aging_current_sdr IS 'Receivables not yet due (SDR)';


--
-- Name: COLUMN kpi_weekly.aging_1_30_sdr; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly.aging_1_30_sdr IS 'Receivables 1–30 days past due (SDR)';


--
-- Name: COLUMN kpi_weekly.aging_31_60_sdr; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly.aging_31_60_sdr IS 'Receivables 31–60 days past due (SDR)';


--
-- Name: COLUMN kpi_weekly.aging_61_90_sdr; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly.aging_61_90_sdr IS 'Receivables 61–90 days past due (SDR)';


--
-- Name: COLUMN kpi_weekly.aging_90_plus_sdr; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly.aging_90_plus_sdr IS 'Receivables more than 90 days past due (SDR)';


--
-- Name: COLUMN kpi_weekly.dso_window_days; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly.dso_window_days IS 'Days in the DSO window (91, fewer in warm-up weeks)';


--
-- Name: COLUMN kpi_weekly.dso_window_billed_sdr; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly.dso_window_billed_sdr IS 'Billed revenue inside the DSO window (SDR)';


--
-- Name: COLUMN kpi_weekly.dso_days; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly.dso_days IS 'DSO = ar_sdr ÷ dso_window_billed_sdr × dso_window_days (owner decision P2-1), 1 decimal';


--
-- Name: COLUMN kpi_weekly.budget_sdr; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly.budget_sdr IS 'Weekly budget, all categories (SDR)';


--
-- Name: COLUMN kpi_weekly.budget_variance_sdr; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly.budget_variance_sdr IS 'billed_sdr − budget_sdr (SDR)';


--
-- Name: COLUMN kpi_weekly.budget_variance_pct; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly.budget_variance_pct IS '(billed − budget) ÷ budget, percent';


--
-- Name: COLUMN kpi_weekly.top10_share_13w_pct; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly.top10_share_13w_pct IS 'Share of the 10 largest customers in the trailing 13 weeks'' billing, percent';


--
-- Name: COLUMN kpi_weekly.billed_wow_pct; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly.billed_wow_pct IS 'Billed revenue change vs the previous week, percent';


--
-- Name: COLUMN kpi_weekly.collected_wow_pct; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly.collected_wow_pct IS 'Collections change vs the previous week, percent';


--
-- Name: COLUMN kpi_weekly.ar_wow_pct; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly.ar_wow_pct IS 'Receivables change vs the previous week, percent';


--
-- Name: COLUMN kpi_weekly.overdue_wow_pct; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly.overdue_wow_pct IS 'Overdue receivables change vs the previous week, percent';


--
-- Name: COLUMN kpi_weekly.dso_wow_days; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly.dso_wow_days IS 'DSO change vs the previous week, in days';


--
-- Name: kpi_weekly_category; Type: VIEW; Schema: finance; Owner: -
--

CREATE VIEW finance.kpi_weekly_category AS
 WITH grid AS (
         SELECT w.report_week,
            w.week_start,
            w.week_end,
            b.vessel_category,
            b.budget_sdr
           FROM (finance.dim_week w
             JOIN public.budget_weekly b ON (((b.budget_year = 2025) AND (b.iso_week = w.report_week))))
        ), base AS (
         SELECT g.report_week,
            g.vessel_category,
            g.budget_sdr,
            count(f.invoice_id) AS invoices_billed,
            COALESCE(sum(f.amount_sdr), (0)::numeric) AS billed_sdr
           FROM (grid g
             LEFT JOIN finance.fact_invoice f ON (((f.vessel_category = g.vessel_category) AND ((f.invoice_date >= g.week_start) AND (f.invoice_date <= g.week_end)))))
          GROUP BY g.report_week, g.vessel_category, g.budget_sdr
        )
 SELECT report_week,
    vessel_category,
    invoices_billed,
    round(billed_sdr, 2) AS billed_sdr,
    round(budget_sdr, 2) AS budget_sdr,
    round((billed_sdr - budget_sdr), 2) AS budget_variance_sdr,
    round((((100)::numeric * (billed_sdr - budget_sdr)) / NULLIF(budget_sdr, (0)::numeric)), 2) AS budget_variance_pct,
    round(lag(billed_sdr) OVER cw, 2) AS billed_prev_sdr,
    round((billed_sdr - lag(billed_sdr) OVER cw), 2) AS billed_wow_change_sdr,
    round((((100)::numeric * (billed_sdr - lag(billed_sdr) OVER cw)) / NULLIF(lag(billed_sdr) OVER cw, (0)::numeric)), 2) AS billed_wow_pct
   FROM base
  WINDOW cw AS (PARTITION BY vessel_category ORDER BY report_week);


--
-- Name: VIEW kpi_weekly_category; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON VIEW finance.kpi_weekly_category IS 'Billing vs budget per report week and vessel category (52 × 13 rows); the week''s drivers = largest |billed_wow_change_sdr|. Level 2, Finance.';


--
-- Name: COLUMN kpi_weekly_category.report_week; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly_category.report_week IS 'Report week';


--
-- Name: COLUMN kpi_weekly_category.vessel_category; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly_category.vessel_category IS 'Vessel category (13 tariff categories)';


--
-- Name: COLUMN kpi_weekly_category.invoices_billed; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly_category.invoices_billed IS 'Invoices of the category dated in the week';


--
-- Name: COLUMN kpi_weekly_category.billed_sdr; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly_category.billed_sdr IS 'Billed revenue of the category in the week (SDR)';


--
-- Name: COLUMN kpi_weekly_category.budget_sdr; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly_category.budget_sdr IS 'Budget of the category for the week (SDR)';


--
-- Name: COLUMN kpi_weekly_category.budget_variance_sdr; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly_category.budget_variance_sdr IS 'billed_sdr − budget_sdr (SDR)';


--
-- Name: COLUMN kpi_weekly_category.budget_variance_pct; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly_category.budget_variance_pct IS '(billed − budget) ÷ budget, percent';


--
-- Name: COLUMN kpi_weekly_category.billed_prev_sdr; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly_category.billed_prev_sdr IS 'Billed revenue of the category in the previous week (SDR); NULL in week 1';


--
-- Name: COLUMN kpi_weekly_category.billed_wow_change_sdr; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly_category.billed_wow_change_sdr IS 'billed_sdr − billed_prev_sdr (SDR)';


--
-- Name: COLUMN kpi_weekly_category.billed_wow_pct; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly_category.billed_wow_pct IS 'Change vs the previous week, percent; NULL when the previous week was 0';


--
-- Name: kpi_weekly_trend; Type: VIEW; Schema: finance; Owner: -
--

CREATE VIEW finance.kpi_weekly_trend AS
 SELECT s.report_week,
    t.report_week AS trend_week,
    (t.report_week - s.report_week) AS week_offset,
    (t.report_week = s.report_week) AS is_report_week,
    t.iso_week_label AS trend_week_label,
    t.week_end AS trend_week_end,
    t.is_warmup,
    t.invoices_billed,
    t.billed_sdr,
    t.collected_sdr,
    t.ar_sdr,
    t.overdue_sdr,
    t.dso_days,
    t.budget_sdr,
    t.budget_variance_sdr,
    t.budget_variance_pct,
    t.top10_share_13w_pct
   FROM (finance.dim_week s
     JOIN finance.kpi_weekly t ON (((t.report_week >= (s.report_week - 12)) AND (t.report_week <= s.report_week))));


--
-- Name: VIEW kpi_weekly_trend; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON VIEW finance.kpi_weekly_trend IS 'The 13-week trend of each report week (M11): one row per (report_week, trend_week) for the weeks w−12 … w (fewer in weeks 1–12), values from kpi_weekly. Filter report_week, chart over trend_week. Level 2, Finance.';


--
-- Name: COLUMN kpi_weekly_trend.report_week; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly_trend.report_week IS 'The report week the trend belongs to (filter on this)';


--
-- Name: COLUMN kpi_weekly_trend.trend_week; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly_trend.trend_week IS 'A week inside the trend window (chart axis)';


--
-- Name: COLUMN kpi_weekly_trend.week_offset; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly_trend.week_offset IS 'trend_week − report_week: −12 … 0';


--
-- Name: COLUMN kpi_weekly_trend.is_report_week; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly_trend.is_report_week IS 'True on the report week itself (offset 0)';


--
-- Name: COLUMN kpi_weekly_trend.trend_week_label; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly_trend.trend_week_label IS 'ISO label of the trend week, e.g. 2025-W23';


--
-- Name: COLUMN kpi_weekly_trend.trend_week_end; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly_trend.trend_week_end IS 'Sunday of the trend week';


--
-- Name: COLUMN kpi_weekly_trend.is_warmup; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly_trend.is_warmup IS 'The trend week is a warm-up week (1–13)';


--
-- Name: COLUMN kpi_weekly_trend.invoices_billed; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly_trend.invoices_billed IS 'kpi_weekly.invoices_billed of the trend week';


--
-- Name: COLUMN kpi_weekly_trend.billed_sdr; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly_trend.billed_sdr IS 'kpi_weekly.billed_sdr of the trend week (SDR)';


--
-- Name: COLUMN kpi_weekly_trend.collected_sdr; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly_trend.collected_sdr IS 'kpi_weekly.collected_sdr of the trend week (SDR)';


--
-- Name: COLUMN kpi_weekly_trend.ar_sdr; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly_trend.ar_sdr IS 'kpi_weekly.ar_sdr of the trend week (SDR)';


--
-- Name: COLUMN kpi_weekly_trend.overdue_sdr; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly_trend.overdue_sdr IS 'kpi_weekly.overdue_sdr of the trend week (SDR)';


--
-- Name: COLUMN kpi_weekly_trend.dso_days; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly_trend.dso_days IS 'kpi_weekly.dso_days of the trend week';


--
-- Name: COLUMN kpi_weekly_trend.budget_sdr; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly_trend.budget_sdr IS 'kpi_weekly.budget_sdr of the trend week (SDR)';


--
-- Name: COLUMN kpi_weekly_trend.budget_variance_sdr; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly_trend.budget_variance_sdr IS 'kpi_weekly.budget_variance_sdr of the trend week (SDR)';


--
-- Name: COLUMN kpi_weekly_trend.budget_variance_pct; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly_trend.budget_variance_pct IS 'kpi_weekly.budget_variance_pct of the trend week (percent)';


--
-- Name: COLUMN kpi_weekly_trend.top10_share_13w_pct; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.kpi_weekly_trend.top10_share_13w_pct IS 'kpi_weekly.top10_share_13w_pct of the trend week (percent)';


--
-- Name: budget_weekly; Type: TABLE; Schema: finance_test; Owner: -
--

CREATE TABLE finance_test.budget_weekly (
    budget_year integer NOT NULL,
    iso_week integer NOT NULL,
    vessel_category text NOT NULL,
    budget_sdr numeric NOT NULL,
    CONSTRAINT budget_weekly_amount_chk CHECK ((budget_sdr >= (0)::numeric)),
    CONSTRAINT budget_weekly_category_chk CHECK ((vessel_category = ANY (ARRAY['Chemical Tankers & Other Liquid Bulk Tankers'::text, 'Containerships'::text, 'Crude Oil Tankers'::text, 'Cruise Ships'::text, 'Dry Bulk Vessels'::text, 'General Cargo / Multi-Purpose / Heavy Lift Vessels'::text, 'Liquefied Natural Gas (LNG) Carriers'::text, 'Liquefied Petroleum Gas (LPG) Carriers'::text, 'Other Vessels'::text, 'Petroleum Product Tankers'::text, 'Roll-On/Roll-Off (Ro/Ro) Vessels'::text, 'Special Floating Units'::text, 'Vehicles Carriers'::text]))),
    CONSTRAINT budget_weekly_week_chk CHECK (((iso_week >= 1) AND (iso_week <= 52))),
    CONSTRAINT budget_weekly_year_chk CHECK ((budget_year = 2025))
);


--
-- Name: TABLE budget_weekly; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON TABLE finance_test.budget_weekly IS 'Budget rows of the 4 golden weeks, one of them changed (a planted budget miss). Level 2, Finance.';


--
-- Name: invoices; Type: TABLE; Schema: finance_test; Owner: -
--

CREATE TABLE finance_test.invoices (
    invoice_number text NOT NULL,
    vessel_id integer NOT NULL,
    invoice_date date NOT NULL,
    scnt_tons numeric NOT NULL,
    billed_sdr numeric NOT NULL,
    CONSTRAINT test_invoices_amount_chk CHECK ((billed_sdr > (0)::numeric)),
    CONSTRAINT test_invoices_number_chk CHECK ((invoice_number ~ '^INV-[0-9]{7}$'::text)),
    CONSTRAINT test_invoices_scnt_chk CHECK ((scnt_tons > (0)::numeric))
);


--
-- Name: TABLE invoices; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON TABLE finance_test.invoices IS 'Invoices of 4 golden weeks as billed, some with planted errors (no label column). Level 2, Finance.';


--
-- Name: COLUMN invoices.invoice_number; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.invoices.invoice_number IS 'Invoice number (a planted duplicate has a new number)';


--
-- Name: COLUMN invoices.vessel_id; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.invoices.vessel_id IS 'The vessel (FK public.vessels)';


--
-- Name: COLUMN invoices.invoice_date; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.invoices.invoice_date IS 'Invoice date';


--
-- Name: COLUMN invoices.scnt_tons; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.invoices.scnt_tons IS 'Suez Canal Net Tonnage as billed';


--
-- Name: COLUMN invoices.billed_sdr; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.invoices.billed_sdr IS 'Amount billed in SDR';


--
-- Name: invoice_audit; Type: VIEW; Schema: finance_test; Owner: -
--

CREATE VIEW finance_test.invoice_audit AS
 WITH billed AS (
         SELECT i.invoice_number,
            i.vessel_id,
            i.invoice_date,
            i.scnt_tons,
            i.billed_sdr,
            NULL::numeric AS billed_rate
           FROM finance_test.invoices i
        ), inv AS (
         SELECT b.invoice_number,
            b.vessel_id,
            b.invoice_date,
            b.scnt_tons,
            b.billed_sdr,
            b.billed_rate,
            v.vessel_name,
            v.vessel_type AS vessel_category,
            v.condition,
            v.scnt_tons AS vessel_scnt,
                CASE
                    WHEN (v.vessel_type = 'Special Floating Units'::text) THEN 'Laden'::text
                    ELSE v.condition
                END AS priced_condition,
            d.report_week
           FROM ((billed b
             JOIN public.vessels v ON ((v.vessel_id = b.vessel_id)))
             JOIN finance.dim_date d ON ((d.date_day = b.invoice_date)))
        ), scenario AS (
         SELECT inv.invoice_number,
            'expected'::text AS scenario,
            inv.vessel_category AS category,
            inv.priced_condition AS cond,
            inv.vessel_scnt AS tons
           FROM inv
        UNION ALL
         SELECT inv.invoice_number,
            'invoice_tonnage'::text,
            inv.vessel_category,
            inv.priced_condition,
            inv.scnt_tons
           FROM inv
          WHERE (inv.scnt_tons <> inv.vessel_scnt)
        UNION ALL
         SELECT inv.invoice_number,
            'condition_swapped'::text,
            inv.vessel_category,
                CASE inv.condition
                    WHEN 'Laden'::text THEN 'Ballast'::text
                    ELSE 'Laden'::text
                END AS "case",
            inv.vessel_scnt
           FROM inv
          WHERE (inv.vessel_category <> 'Special Floating Units'::text)
        UNION ALL
         SELECT inv.invoice_number,
            'sfu_priced_ballast'::text,
            'Other Vessels'::text,
            'Ballast'::text,
            inv.vessel_scnt
           FROM inv
          WHERE (inv.vessel_category = 'Special Floating Units'::text)
        UNION ALL
         SELECT inv.invoice_number,
            'notes_crude_ballast'::text,
            'Crude Oil Tankers'::text,
            'Ballast'::text,
            inv.vessel_scnt
           FROM inv
          WHERE ((inv.priced_condition = 'Ballast'::text) AND (inv.vessel_category = 'Chemical Tankers & Other Liquid Bulk Tankers'::text))
        ), priced AS (
         SELECT s.invoice_number,
            s.scenario,
            sum((t.rate_sdr_per_ton * (LEAST(s.tons, COALESCE(t.band_max_tons, s.tons)) - t.band_min_tons))) AS toll_exact,
            (array_agg(t.rate_sdr_per_ton ORDER BY t.band_order DESC))[1] AS terminal_rate,
            (array_agg(t.band_label ORDER BY t.band_order DESC))[1] AS terminal_band
           FROM (scenario s
             JOIN public.toll_rate_bands t ON (((t.vessel_category = s.category) AND (t.laden_ballast = s.cond) AND (s.tons > t.band_min_tons))))
          GROUP BY s.invoice_number, s.scenario
        ), hyp AS (
         SELECT i.invoice_number,
            i.vessel_id,
            i.invoice_date,
            i.scnt_tons,
            i.billed_sdr,
            i.billed_rate,
            i.vessel_name,
            i.vessel_category,
            i.condition,
            i.vessel_scnt,
            i.priced_condition,
            i.report_week,
            e.toll_exact AS expected_exact,
            round(e.toll_exact, 2) AS expected_sdr,
            e.terminal_rate,
            e.terminal_band,
            round(it.toll_exact, 2) AS invoice_tonnage_sdr,
            round((e.terminal_rate * i.vessel_scnt), 2) AS flat_terminal_sdr,
            round(cs.toll_exact, 2) AS condition_swapped_sdr,
            round(sb.toll_exact, 2) AS sfu_ballast_sdr,
            round(nc.toll_exact, 2) AS notes_crude_sdr,
            row_number() OVER w AS dup_rank,
            first_value(i.invoice_number) OVER w AS dup_first
           FROM (((((inv i
             JOIN priced e ON (((e.invoice_number = i.invoice_number) AND (e.scenario = 'expected'::text))))
             LEFT JOIN priced it ON (((it.invoice_number = i.invoice_number) AND (it.scenario = 'invoice_tonnage'::text))))
             LEFT JOIN priced cs ON (((cs.invoice_number = i.invoice_number) AND (cs.scenario = 'condition_swapped'::text))))
             LEFT JOIN priced sb ON (((sb.invoice_number = i.invoice_number) AND (sb.scenario = 'sfu_priced_ballast'::text))))
             LEFT JOIN priced nc ON (((nc.invoice_number = i.invoice_number) AND (nc.scenario = 'notes_crude_ballast'::text))))
          WINDOW w AS (PARTITION BY i.vessel_id, i.invoice_date, i.billed_sdr ORDER BY i.invoice_number)
        ), findings AS (
         SELECT h.invoice_number,
            h.vessel_id,
            h.invoice_date,
            h.scnt_tons,
            h.billed_sdr,
            h.billed_rate,
            h.vessel_name,
            h.vessel_category,
            h.condition,
            h.vessel_scnt,
            h.priced_condition,
            h.report_week,
            h.expected_exact,
            h.expected_sdr,
            h.terminal_rate,
            h.terminal_band,
            h.invoice_tonnage_sdr,
            h.flat_terminal_sdr,
            h.condition_swapped_sdr,
            h.sfu_ballast_sdr,
            h.notes_crude_sdr,
            h.dup_rank,
            h.dup_first,
            'duplicate_charge'::text AS check_code,
            NULL::text AS probable_cause,
            (0)::numeric AS expected_charge,
            h.dup_first AS duplicate_of,
            format('same vessel, date and amount as %s: the whole charge is billed twice'::text, h.dup_first) AS evidence
           FROM hyp h
          WHERE (h.dup_rank > 1)
        UNION ALL
         SELECT h.invoice_number,
            h.vessel_id,
            h.invoice_date,
            h.scnt_tons,
            h.billed_sdr,
            h.billed_rate,
            h.vessel_name,
            h.vessel_category,
            h.condition,
            h.vessel_scnt,
            h.priced_condition,
            h.report_week,
            h.expected_exact,
            h.expected_sdr,
            h.terminal_rate,
            h.terminal_band,
            h.invoice_tonnage_sdr,
            h.flat_terminal_sdr,
            h.condition_swapped_sdr,
            h.sfu_ballast_sdr,
            h.notes_crude_sdr,
            h.dup_rank,
            h.dup_first,
            'tonnage_mismatch'::text,
            NULL::text,
            h.expected_sdr,
            NULL::text,
            format('invoice SCNT %s <> vessel SCNT %s'::text, h.scnt_tons, h.vessel_scnt) AS format
           FROM hyp h
          WHERE ((h.dup_rank = 1) AND (h.scnt_tons <> h.vessel_scnt))
        UNION ALL
         SELECT h.invoice_number,
            h.vessel_id,
            h.invoice_date,
            h.scnt_tons,
            h.billed_sdr,
            h.billed_rate,
            h.vessel_name,
            h.vessel_category,
            h.condition,
            h.vessel_scnt,
            h.priced_condition,
            h.report_week,
            h.expected_exact,
            h.expected_sdr,
            h.terminal_rate,
            h.terminal_band,
            h.invoice_tonnage_sdr,
            h.flat_terminal_sdr,
            h.condition_swapped_sdr,
            h.sfu_ballast_sdr,
            h.notes_crude_sdr,
            h.dup_rank,
            h.dup_first,
            'amount_mismatch'::text,
                CASE
                    WHEN (abs((h.billed_sdr - h.invoice_tonnage_sdr)) <= 0.01) THEN 'billed_on_invoice_tonnage'::text
                    WHEN (abs((h.billed_sdr - h.flat_terminal_sdr)) <= 0.01) THEN 'flat_terminal_rate'::text
                    WHEN (abs((h.billed_sdr - h.condition_swapped_sdr)) <= 0.01) THEN 'condition_swapped'::text
                    WHEN (abs((h.billed_sdr - h.sfu_ballast_sdr)) <= 0.01) THEN 'sfu_priced_ballast'::text
                    WHEN (abs((h.billed_sdr - h.notes_crude_sdr)) <= 0.01) THEN 'notes_crude_ballast_rate'::text
                    ELSE 'unexplained'::text
                END AS "case",
            h.expected_sdr,
            NULL::text,
            format('billed %s SDR; tariff %s / %s at %s SCNT = %s SDR (progressive, terminal band %s at %s SDR/t)'::text, h.billed_sdr, h.vessel_category, h.priced_condition, h.vessel_scnt, h.expected_sdr, h.terminal_band, h.terminal_rate) AS format
           FROM hyp h
          WHERE ((h.dup_rank = 1) AND (abs((h.billed_sdr - h.expected_exact)) > 0.01))
        UNION ALL
         SELECT h.invoice_number,
            h.vessel_id,
            h.invoice_date,
            h.scnt_tons,
            h.billed_sdr,
            h.billed_rate,
            h.vessel_name,
            h.vessel_category,
            h.condition,
            h.vessel_scnt,
            h.priced_condition,
            h.report_week,
            h.expected_exact,
            h.expected_sdr,
            h.terminal_rate,
            h.terminal_band,
            h.invoice_tonnage_sdr,
            h.flat_terminal_sdr,
            h.condition_swapped_sdr,
            h.sfu_ballast_sdr,
            h.notes_crude_sdr,
            h.dup_rank,
            h.dup_first,
            'rate_mismatch'::text,
            NULL::text,
            h.expected_sdr,
            NULL::text,
            format('stored rate %s SDR/t <> terminal band %s rate %s SDR/t'::text, h.billed_rate, h.terminal_band, h.terminal_rate) AS format
           FROM hyp h
          WHERE ((h.dup_rank = 1) AND (h.billed_rate IS NOT NULL) AND (h.billed_rate <> h.terminal_rate))
        )
 SELECT report_week,
    invoice_number,
    invoice_date,
    vessel_id,
    vessel_name,
    vessel_category,
    condition AS vessel_condition,
    check_code,
    probable_cause,
    billed_sdr,
    expected_charge AS expected_sdr,
    round((billed_sdr - expected_charge), 2) AS difference_sdr,
    duplicate_of,
    evidence,
        CASE
            WHEN (probable_cause = 'notes_crude_ballast_rate'::text) THEN 'manual_review'::text
            ELSE 'error'::text
        END AS review
   FROM findings;


--
-- Name: VIEW invoice_audit; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON VIEW finance_test.invoice_audit IS 'The same audit over the evaluation copy finance_test.invoices (Agents plan §4a R7; same SQL as finance.invoice_audit except the source CTE). Evaluation only; invisible to Power BI. Level 2, Finance.';


--
-- Name: COLUMN invoice_audit.report_week; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.invoice_audit.report_week IS 'Report week of the invoice date (ISO 2025 week)';


--
-- Name: COLUMN invoice_audit.invoice_number; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.invoice_audit.invoice_number IS 'The invoice with the finding';


--
-- Name: COLUMN invoice_audit.invoice_date; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.invoice_audit.invoice_date IS 'Invoice date';


--
-- Name: COLUMN invoice_audit.vessel_id; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.invoice_audit.vessel_id IS 'The billed vessel';


--
-- Name: COLUMN invoice_audit.vessel_name; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.invoice_audit.vessel_name IS 'Vessel name';


--
-- Name: COLUMN invoice_audit.vessel_category; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.invoice_audit.vessel_category IS 'Tariff category of the vessel (vessels.vessel_type)';


--
-- Name: COLUMN invoice_audit.vessel_condition; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.invoice_audit.vessel_condition IS 'Condition of the vessel (vessels.condition); Special Floating Units are priced Laden';


--
-- Name: COLUMN invoice_audit.check_code; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.invoice_audit.check_code IS 'duplicate_charge | tonnage_mismatch | amount_mismatch | rate_mismatch (never: the copy stores no rate)';


--
-- Name: COLUMN invoice_audit.probable_cause; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.invoice_audit.probable_cause IS 'amount_mismatch only: billed_on_invoice_tonnage | flat_terminal_rate | condition_swapped | sfu_priced_ballast | notes_crude_ballast_rate | unexplained';


--
-- Name: COLUMN invoice_audit.billed_sdr; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.invoice_audit.billed_sdr IS 'Amount billed (SDR)';


--
-- Name: COLUMN invoice_audit.expected_sdr; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.invoice_audit.expected_sdr IS 'Correct charge (SDR): the progressive toll of the vessel; 0 for a duplicate';


--
-- Name: COLUMN invoice_audit.difference_sdr; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.invoice_audit.difference_sdr IS 'billed - expected (SDR)';


--
-- Name: COLUMN invoice_audit.duplicate_of; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.invoice_audit.duplicate_of IS 'duplicate_charge only: the original invoice number';


--
-- Name: COLUMN invoice_audit.evidence; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.invoice_audit.evidence IS 'The numbers behind the finding';


--
-- Name: COLUMN invoice_audit.review; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.invoice_audit.review IS 'error | manual_review (a tariff Notes rule, migration 019)';


--
-- Name: kpi_weekly; Type: VIEW; Schema: finance_test; Owner: -
--

CREATE VIEW finance_test.kpi_weekly AS
 WITH weeks AS (
         SELECT w.report_week,
            w.week_start,
            w.week_end
           FROM finance.dim_week w
          WHERE (w.report_week IN ( SELECT DISTINCT budget_weekly.iso_week
                   FROM finance_test.budget_weekly
                  WHERE (budget_weekly.budget_year = 2025)))
        ), billed AS (
         SELECT w.report_week,
            count(i.invoice_number) AS invoices_billed,
            COALESCE(sum(i.billed_sdr), (0)::numeric) AS billed_sdr
           FROM (weeks w
             LEFT JOIN finance_test.invoices i ON (((i.invoice_date >= w.week_start) AND (i.invoice_date <= w.week_end))))
          GROUP BY w.report_week
        ), budget AS (
         SELECT budget_weekly.iso_week AS report_week,
            sum(budget_weekly.budget_sdr) AS budget_sdr
           FROM finance_test.budget_weekly
          WHERE (budget_weekly.budget_year = 2025)
          GROUP BY budget_weekly.iso_week
        ), prev AS (
         SELECT w.report_week,
                CASE
                    WHEN (w.report_week > 1) THEN COALESCE(sum(f.amount_sdr), (0)::numeric)
                    ELSE NULL::numeric
                END AS billed_prev_sdr
           FROM (weeks w
             LEFT JOIN finance.fact_invoice f ON (((f.invoice_date >= (w.week_start - 7)) AND (f.invoice_date <= (w.week_end - 7)))))
          GROUP BY w.report_week
        )
 SELECT k.report_week,
    k.iso_week_label,
    k.week_start,
    k.week_end,
    k.is_warmup,
    b.invoices_billed,
    round(b.billed_sdr, 2) AS billed_sdr,
    k.payments_received,
    k.collected_sdr,
    k.ar_invoices,
    k.ar_sdr,
    k.overdue_invoices,
    k.overdue_sdr,
    k.aging_current_sdr,
    k.aging_1_30_sdr,
    k.aging_31_60_sdr,
    k.aging_61_90_sdr,
    k.aging_90_plus_sdr,
    k.dso_window_days,
    k.dso_window_billed_sdr,
    k.dso_days,
    round(bu.budget_sdr, 2) AS budget_sdr,
    round((b.billed_sdr - bu.budget_sdr), 2) AS budget_variance_sdr,
    round((((100)::numeric * (b.billed_sdr - bu.budget_sdr)) / NULLIF(bu.budget_sdr, (0)::numeric)), 2) AS budget_variance_pct,
    k.top10_share_13w_pct,
    round((((100)::numeric * (b.billed_sdr - p.billed_prev_sdr)) / NULLIF(p.billed_prev_sdr, (0)::numeric)), 2) AS billed_wow_pct,
    k.collected_wow_pct,
    k.ar_wow_pct,
    k.overdue_wow_pct,
    k.dso_wow_days
   FROM (((finance.kpi_weekly k
     JOIN billed b ON ((b.report_week = k.report_week)))
     JOIN budget bu ON ((bu.report_week = k.report_week)))
     JOIN prev p ON ((p.report_week = k.report_week)));


--
-- Name: VIEW kpi_weekly; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON VIEW finance_test.kpi_weekly IS 'Twin of finance.kpi_weekly over the evaluation copy (Agents plan §5d, migration 017): billed and budget from the copy (planted errors and the budget miss); receivables, collections, DSO, the top-10 share and their WoW from the live view (the copy has no payments); billed WoW against the live previous week. Weeks 10, 23, 36, 49 only. Evaluation only; invisible to Power BI. Level 2, Finance.';


--
-- Name: COLUMN kpi_weekly.report_week; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.kpi_weekly.report_week IS 'ISO week of 2025 (a week of the evaluation copy)';


--
-- Name: COLUMN kpi_weekly.iso_week_label; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.kpi_weekly.iso_week_label IS 'As finance.kpi_weekly';


--
-- Name: COLUMN kpi_weekly.week_start; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.kpi_weekly.week_start IS 'As finance.kpi_weekly';


--
-- Name: COLUMN kpi_weekly.week_end; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.kpi_weekly.week_end IS 'As finance.kpi_weekly';


--
-- Name: COLUMN kpi_weekly.is_warmup; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.kpi_weekly.is_warmup IS 'As finance.kpi_weekly';


--
-- Name: COLUMN kpi_weekly.invoices_billed; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.kpi_weekly.invoices_billed IS 'Invoices of the copy dated in the week (a planted duplicate counts)';


--
-- Name: COLUMN kpi_weekly.billed_sdr; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.kpi_weekly.billed_sdr IS 'Billed in the week (SDR) as in finance_test.invoices, planted errors included';


--
-- Name: COLUMN kpi_weekly.payments_received; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.kpi_weekly.payments_received IS 'LIVE value (finance.kpi_weekly): the copy has no payments';


--
-- Name: COLUMN kpi_weekly.collected_sdr; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.kpi_weekly.collected_sdr IS 'LIVE value (finance.kpi_weekly): the copy has no payments';


--
-- Name: COLUMN kpi_weekly.ar_invoices; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.kpi_weekly.ar_invoices IS 'LIVE value (finance.kpi_weekly)';


--
-- Name: COLUMN kpi_weekly.ar_sdr; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.kpi_weekly.ar_sdr IS 'LIVE value (finance.kpi_weekly)';


--
-- Name: COLUMN kpi_weekly.overdue_invoices; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.kpi_weekly.overdue_invoices IS 'LIVE value (finance.kpi_weekly)';


--
-- Name: COLUMN kpi_weekly.overdue_sdr; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.kpi_weekly.overdue_sdr IS 'LIVE value (finance.kpi_weekly)';


--
-- Name: COLUMN kpi_weekly.aging_current_sdr; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.kpi_weekly.aging_current_sdr IS 'LIVE value (finance.kpi_weekly)';


--
-- Name: COLUMN kpi_weekly.aging_1_30_sdr; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.kpi_weekly.aging_1_30_sdr IS 'LIVE value (finance.kpi_weekly)';


--
-- Name: COLUMN kpi_weekly.aging_31_60_sdr; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.kpi_weekly.aging_31_60_sdr IS 'LIVE value (finance.kpi_weekly)';


--
-- Name: COLUMN kpi_weekly.aging_61_90_sdr; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.kpi_weekly.aging_61_90_sdr IS 'LIVE value (finance.kpi_weekly)';


--
-- Name: COLUMN kpi_weekly.aging_90_plus_sdr; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.kpi_weekly.aging_90_plus_sdr IS 'LIVE value (finance.kpi_weekly)';


--
-- Name: COLUMN kpi_weekly.dso_window_days; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.kpi_weekly.dso_window_days IS 'LIVE value (finance.kpi_weekly)';


--
-- Name: COLUMN kpi_weekly.dso_window_billed_sdr; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.kpi_weekly.dso_window_billed_sdr IS 'LIVE value (finance.kpi_weekly): the DSO base stays on the live invoices';


--
-- Name: COLUMN kpi_weekly.dso_days; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.kpi_weekly.dso_days IS 'LIVE value (finance.kpi_weekly)';


--
-- Name: COLUMN kpi_weekly.budget_sdr; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.kpi_weekly.budget_sdr IS 'Budget of the week (SDR) from finance_test.budget_weekly (week 36 carries the planted miss)';


--
-- Name: COLUMN kpi_weekly.budget_variance_sdr; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.kpi_weekly.budget_variance_sdr IS 'billed − budget (SDR), both from the copy';


--
-- Name: COLUMN kpi_weekly.budget_variance_pct; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.kpi_weekly.budget_variance_pct IS '(billed − budget) / budget, percent, both from the copy';


--
-- Name: COLUMN kpi_weekly.top10_share_13w_pct; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.kpi_weekly.top10_share_13w_pct IS 'LIVE value (finance.kpi_weekly)';


--
-- Name: COLUMN kpi_weekly.billed_wow_pct; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.kpi_weekly.billed_wow_pct IS 'Billed of the copy vs billed of the LIVE previous week, percent';


--
-- Name: COLUMN kpi_weekly.collected_wow_pct; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.kpi_weekly.collected_wow_pct IS 'LIVE value (finance.kpi_weekly)';


--
-- Name: COLUMN kpi_weekly.ar_wow_pct; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.kpi_weekly.ar_wow_pct IS 'LIVE value (finance.kpi_weekly)';


--
-- Name: COLUMN kpi_weekly.overdue_wow_pct; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.kpi_weekly.overdue_wow_pct IS 'LIVE value (finance.kpi_weekly)';


--
-- Name: COLUMN kpi_weekly.dso_wow_days; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.kpi_weekly.dso_wow_days IS 'LIVE value (finance.kpi_weekly)';


--
-- Name: kpi_weekly_category; Type: VIEW; Schema: finance_test; Owner: -
--

CREATE VIEW finance_test.kpi_weekly_category AS
 WITH weeks AS (
         SELECT w.report_week,
            w.week_start,
            w.week_end
           FROM finance.dim_week w
          WHERE (w.report_week IN ( SELECT DISTINCT budget_weekly.iso_week
                   FROM finance_test.budget_weekly
                  WHERE (budget_weekly.budget_year = 2025)))
        ), grid AS (
         SELECT w.report_week,
            w.week_start,
            w.week_end,
            b_1.vessel_category,
            b_1.budget_sdr
           FROM (weeks w
             JOIN finance_test.budget_weekly b_1 ON (((b_1.budget_year = 2025) AND (b_1.iso_week = w.report_week))))
        ), base AS (
         SELECT g.report_week,
            g.vessel_category,
            g.budget_sdr,
            count(i.invoice_number) AS invoices_billed,
            COALESCE(sum(i.billed_sdr), (0)::numeric) AS billed_sdr
           FROM (grid g
             LEFT JOIN (finance_test.invoices i
             JOIN public.vessels v ON ((v.vessel_id = i.vessel_id))) ON (((v.vessel_type = g.vessel_category) AND ((i.invoice_date >= g.week_start) AND (i.invoice_date <= g.week_end)))))
          GROUP BY g.report_week, g.vessel_category, g.budget_sdr
        ), prev AS (
         SELECT g.report_week,
            g.vessel_category,
                CASE
                    WHEN (g.report_week > 1) THEN COALESCE(sum(f.amount_sdr), (0)::numeric)
                    ELSE NULL::numeric
                END AS billed_prev_sdr
           FROM (grid g
             LEFT JOIN finance.fact_invoice f ON (((f.vessel_category = g.vessel_category) AND ((f.invoice_date >= (g.week_start - 7)) AND (f.invoice_date <= (g.week_end - 7))))))
          GROUP BY g.report_week, g.vessel_category
        )
 SELECT b.report_week,
    b.vessel_category,
    b.invoices_billed,
    round(b.billed_sdr, 2) AS billed_sdr,
    round(b.budget_sdr, 2) AS budget_sdr,
    round((b.billed_sdr - b.budget_sdr), 2) AS budget_variance_sdr,
    round((((100)::numeric * (b.billed_sdr - b.budget_sdr)) / NULLIF(b.budget_sdr, (0)::numeric)), 2) AS budget_variance_pct,
    round(p.billed_prev_sdr, 2) AS billed_prev_sdr,
    round((b.billed_sdr - p.billed_prev_sdr), 2) AS billed_wow_change_sdr,
    round((((100)::numeric * (b.billed_sdr - p.billed_prev_sdr)) / NULLIF(p.billed_prev_sdr, (0)::numeric)), 2) AS billed_wow_pct
   FROM (base b
     JOIN prev p ON (((p.report_week = b.report_week) AND (p.vessel_category = b.vessel_category))));


--
-- Name: VIEW kpi_weekly_category; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON VIEW finance_test.kpi_weekly_category IS 'Twin of finance.kpi_weekly_category over the evaluation copy (Agents plan §5d, migration 017): billed from finance_test.invoices, budget from finance_test.budget_weekly (the planted budget miss), the previous week from the live invoices. Weeks 10, 23, 36, 49 only. Evaluation only; invisible to Power BI. Level 2, Finance.';


--
-- Name: COLUMN kpi_weekly_category.report_week; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.kpi_weekly_category.report_week IS 'ISO week of 2025 (a week of the evaluation copy)';


--
-- Name: COLUMN kpi_weekly_category.vessel_category; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.kpi_weekly_category.vessel_category IS 'Tariff category (vessels.vessel_type)';


--
-- Name: COLUMN kpi_weekly_category.invoices_billed; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.kpi_weekly_category.invoices_billed IS 'Invoices of the copy dated in the week for the category (a planted duplicate counts)';


--
-- Name: COLUMN kpi_weekly_category.billed_sdr; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.kpi_weekly_category.billed_sdr IS 'Billed in the week (SDR) as in finance_test.invoices, planted errors included';


--
-- Name: COLUMN kpi_weekly_category.budget_sdr; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.kpi_weekly_category.budget_sdr IS 'Budget of the week (SDR) from finance_test.budget_weekly (one row planted: week 36)';


--
-- Name: COLUMN kpi_weekly_category.budget_variance_sdr; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.kpi_weekly_category.budget_variance_sdr IS 'billed − budget (SDR)';


--
-- Name: COLUMN kpi_weekly_category.budget_variance_pct; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.kpi_weekly_category.budget_variance_pct IS '(billed − budget) / budget, percent';


--
-- Name: COLUMN kpi_weekly_category.billed_prev_sdr; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.kpi_weekly_category.billed_prev_sdr IS 'Billed in the previous week (SDR) from the LIVE invoices (the copy holds no previous week)';


--
-- Name: COLUMN kpi_weekly_category.billed_wow_change_sdr; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.kpi_weekly_category.billed_wow_change_sdr IS 'billed − billed_prev (SDR); the week''s drivers = the largest absolute changes';


--
-- Name: COLUMN kpi_weekly_category.billed_wow_pct; Type: COMMENT; Schema: finance_test; Owner: -
--

COMMENT ON COLUMN finance_test.kpi_weekly_category.billed_wow_pct IS 'Week-over-week change of billed, percent (NULL when the previous week billed 0)';


--
-- Name: containers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.containers (
    container_id integer NOT NULL,
    container_number character varying(11) NOT NULL,
    container_type text NOT NULL,
    size_ft integer NOT NULL,
    status text NOT NULL,
    vessel_id integer NOT NULL,
    origin_locode character varying(5) NOT NULL,
    destination_locode character varying(5) NOT NULL,
    CONSTRAINT containers_number_format_chk CHECK (((container_number)::text ~ '^[A-Z]{3}[UJZ][0-9]{7}$'::text)),
    CONSTRAINT containers_route_chk CHECK (((origin_locode)::text <> (destination_locode)::text)),
    CONSTRAINT containers_size_ft_chk CHECK ((size_ft = ANY (ARRAY[20, 40]))),
    CONSTRAINT containers_status_chk CHECK ((status = ANY (ARRAY['Loaded'::text, 'In Transit'::text, 'At Port'::text, 'Delivered'::text, 'Empty'::text]))),
    CONSTRAINT containers_type_chk CHECK ((container_type = ANY (ARRAY['Dry'::text, 'Reefer'::text, 'Open Top'::text, 'Flat Rack'::text])))
);


--
-- Name: TABLE containers; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.containers IS 'Synthetic containers (1,000) carried by the vessels; same origin / destination as their vessel. Level 1, Operations.';


--
-- Name: COLUMN containers.container_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.containers.container_id IS 'Surrogate key';


--
-- Name: COLUMN containers.container_number; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.containers.container_number IS 'Container number in ISO 6346 form (synthetic, sequential; the check digit is not enforced)';


--
-- Name: COLUMN containers.container_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.containers.container_type IS 'Dry, Reefer, Open Top or Flat Rack';


--
-- Name: COLUMN containers.size_ft; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.containers.size_ft IS 'Length in feet: 20 or 40';


--
-- Name: COLUMN containers.status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.containers.status IS 'Loaded, In Transit, At Port, Delivered or Empty';


--
-- Name: COLUMN containers.vessel_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.containers.vessel_id IS 'Carrying vessel';


--
-- Name: COLUMN containers.origin_locode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.containers.origin_locode IS 'Port of loading (UN/LOCODE)';


--
-- Name: COLUMN containers.destination_locode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.containers.destination_locode IS 'Port of discharge (UN/LOCODE)';


--
-- Name: containers_container_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.containers_container_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: containers_container_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.containers_container_id_seq OWNED BY public.containers.container_id;


--
-- Name: departments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.departments (
    department_id integer NOT NULL,
    department_name text NOT NULL,
    description text
);


--
-- Name: TABLE departments; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.departments IS 'NileGate departments (Operations, Customs, Finance, HR, IT). Level 1, HR.';


--
-- Name: COLUMN departments.department_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.departments.department_id IS 'Surrogate key; owner department of every protected resource (ADR-006)';


--
-- Name: COLUMN departments.department_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.departments.department_name IS 'Unique department name';


--
-- Name: COLUMN departments.description; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.departments.description IS 'Optional description';


--
-- Name: departments_department_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.departments_department_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: departments_department_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.departments_department_id_seq OWNED BY public.departments.department_id;


--
-- Name: documents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.documents (
    document_id text NOT NULL,
    filename text NOT NULL,
    title text NOT NULL,
    source text NOT NULL,
    real_or_synthetic text NOT NULL,
    document_type text NOT NULL,
    department_id integer NOT NULL,
    sensitivity_level smallint NOT NULL,
    version_date text,
    ingestion_scope text,
    source_url text,
    sha256 character(64) NOT NULL,
    file_size_bytes bigint NOT NULL,
    page_count integer,
    chunk_count integer,
    ingested_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT documents_chunk_count_check CHECK ((chunk_count >= 0)),
    CONSTRAINT documents_file_size_bytes_check CHECK ((file_size_bytes > 0)),
    CONSTRAINT documents_page_count_check CHECK ((page_count > 0)),
    CONSTRAINT documents_real_or_synthetic_check CHECK ((real_or_synthetic = ANY (ARRAY['real'::text, 'synthetic'::text]))),
    CONSTRAINT documents_sensitivity_level_check CHECK (((sensitivity_level >= 1) AND (sensitivity_level <= 3)))
);


--
-- Name: TABLE documents; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.documents IS 'RAG document registry and lineage, one row per ingested source file (ADR-009); filled in the RAG phase. Level 1, IT.';


--
-- Name: COLUMN documents.document_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.documents.document_id IS 'Stable slug of the source, e.g. lpi_methodology; carried in every Qdrant payload';


--
-- Name: COLUMN documents.filename; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.documents.filename IS 'File name under Data/raw/...';


--
-- Name: COLUMN documents.title; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.documents.title IS 'Document title';


--
-- Name: COLUMN documents.source; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.documents.source IS 'Publisher, e.g. The World Bank';


--
-- Name: COLUMN documents.real_or_synthetic; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.documents.real_or_synthetic IS 'real or synthetic';


--
-- Name: COLUMN documents.document_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.documents.document_type IS 'Same values as the chunk column document_type';


--
-- Name: COLUMN documents.department_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.documents.department_id IS 'Owner department (default; a chunk may differ, ADR-021)';


--
-- Name: COLUMN documents.sensitivity_level; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.documents.sensitivity_level IS 'Default level 1-3; a chunk may be higher (ADR-021)';


--
-- Name: COLUMN documents.version_date; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.documents.version_date IS 'As published; precision varies by source';


--
-- Name: COLUMN documents.ingestion_scope; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.documents.ingestion_scope IS 'Part of the document ingested; NULL = whole document';


--
-- Name: COLUMN documents.source_url; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.documents.source_url IS 'Where the document was obtained';


--
-- Name: COLUMN documents.sha256; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.documents.sha256 IS 'Fingerprint of the raw file (change detection); a new version = a new row';


--
-- Name: COLUMN documents.file_size_bytes; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.documents.file_size_bytes IS 'Raw file size';


--
-- Name: COLUMN documents.page_count; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.documents.page_count IS 'Pages of the raw file';


--
-- Name: COLUMN documents.chunk_count; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.documents.chunk_count IS 'Chunks produced; NULL until chunked';


--
-- Name: COLUMN documents.ingested_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.documents.ingested_at IS 'When loaded into Qdrant; NULL until then';


--
-- Name: COLUMN documents.created_at; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.documents.created_at IS 'Row creation time';


--
-- Name: employees; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.employees (
    employee_id integer NOT NULL,
    first_name text NOT NULL,
    last_name text NOT NULL,
    email text NOT NULL,
    role_id integer NOT NULL,
    department_id integer NOT NULL,
    hire_date date NOT NULL,
    CONSTRAINT employees_email_format_chk CHECK ((email ~ '^[a-z0-9._-]+@nilegate\.com$'::text))
);


--
-- Name: TABLE employees; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.employees IS 'Synthetic employees (Faker, seed 42). Contains personal data. Level 2, HR (ADR-006); no status column (ADR-017).';


--
-- Name: COLUMN employees.employee_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.employees.employee_id IS 'Surrogate key';


--
-- Name: COLUMN employees.first_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.employees.first_name IS 'First name (synthetic)';


--
-- Name: COLUMN employees.last_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.employees.last_name IS 'Last name (synthetic)';


--
-- Name: COLUMN employees.email; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.employees.email IS 'Unique @nilegate.com address';


--
-- Name: COLUMN employees.role_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.employees.role_id IS 'Role (roles.role_id): sensitivity ceiling';


--
-- Name: COLUMN employees.department_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.employees.department_id IS 'Department (departments.department_id): department grant';


--
-- Name: COLUMN employees.hire_date; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.employees.hire_date IS 'Hire date (anchored to 2026-09-13)';


--
-- Name: employees_employee_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.employees_employee_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: employees_employee_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.employees_employee_id_seq OWNED BY public.employees.employee_id;


--
-- Name: invoices_invoice_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.invoices_invoice_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: invoices_invoice_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.invoices_invoice_id_seq OWNED BY public.invoices.invoice_id;


--
-- Name: port_connections; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.port_connections (
    port1_locode character varying(5) NOT NULL,
    port2_locode character varying(5) NOT NULL,
    flows double precision NOT NULL,
    country1 text NOT NULL,
    country2 text NOT NULL,
    geom public.geometry(LineString,4326) NOT NULL,
    CONSTRAINT port_connections_country_codes_chk CHECK (((country1 = "left"((port1_locode)::text, 2)) AND (country2 = "left"((port2_locode)::text, 2)))),
    CONSTRAINT port_connections_flows_chk CHECK ((flows > (0)::double precision)),
    CONSTRAINT port_connections_no_self_loop_chk CHECK (((port1_locode)::text <> (port2_locode)::text))
);


--
-- Name: TABLE port_connections; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.port_connections IS 'Real port-to-port network with flows (port_flows shapefile). Both directions present. Level 1, Operations.';


--
-- Name: COLUMN port_connections.port1_locode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.port_connections.port1_locode IS 'From port (UN/LOCODE)';


--
-- Name: COLUMN port_connections.port2_locode; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.port_connections.port2_locode IS 'To port (UN/LOCODE)';


--
-- Name: COLUMN port_connections.flows; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.port_connections.flows IS 'Flow volume between the two ports (> 0)';


--
-- Name: COLUMN port_connections.country1; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.port_connections.country1 IS 'ISO 3166-1 alpha-2 country code of port1 (= left(port1_locode, 2))';


--
-- Name: COLUMN port_connections.country2; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.port_connections.country2 IS 'ISO 3166-1 alpha-2 country code of port2 (= left(port2_locode, 2))';


--
-- Name: COLUMN port_connections.geom; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.port_connections.geom IS 'Straight 2-point LineString from port1 to port2, SRID 4326 (not a sea lane)';


--
-- Name: roles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.roles (
    role_id integer NOT NULL,
    role_name text NOT NULL,
    allowed_sensitivity_level integer NOT NULL,
    CONSTRAINT roles_allowed_sensitivity_level_chk CHECK (((allowed_sensitivity_level >= 1) AND (allowed_sensitivity_level <= 3)))
);


--
-- Name: TABLE roles; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.roles IS 'Roles and their sensitivity ceiling: employee 1, manager 2, ceo 3 (ADR-006). Level 2, IT.';


--
-- Name: COLUMN roles.role_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.roles.role_id IS 'Surrogate key';


--
-- Name: COLUMN roles.role_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.roles.role_name IS 'employee, manager or ceo';


--
-- Name: COLUMN roles.allowed_sensitivity_level; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.roles.allowed_sensitivity_level IS 'Highest sensitivity level the role may read (1-3)';


--
-- Name: roles_role_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.roles_role_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: roles_role_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.roles_role_id_seq OWNED BY public.roles.role_id;


--
-- Name: toll_rate_bands_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.toll_rate_bands_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: toll_rate_bands_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.toll_rate_bands_id_seq OWNED BY public.toll_rate_bands.id;


--
-- Name: vessels_vessel_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.vessels_vessel_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: vessels_vessel_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.vessels_vessel_id_seq OWNED BY public.vessels.vessel_id;


--
-- Name: containers container_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.containers ALTER COLUMN container_id SET DEFAULT nextval('public.containers_container_id_seq'::regclass);


--
-- Name: departments department_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.departments ALTER COLUMN department_id SET DEFAULT nextval('public.departments_department_id_seq'::regclass);


--
-- Name: employees employee_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.employees ALTER COLUMN employee_id SET DEFAULT nextval('public.employees_employee_id_seq'::regclass);


--
-- Name: invoices invoice_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invoices ALTER COLUMN invoice_id SET DEFAULT nextval('public.invoices_invoice_id_seq'::regclass);


--
-- Name: roles role_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles ALTER COLUMN role_id SET DEFAULT nextval('public.roles_role_id_seq'::regclass);


--
-- Name: toll_rate_bands id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.toll_rate_bands ALTER COLUMN id SET DEFAULT nextval('public.toll_rate_bands_id_seq'::regclass);


--
-- Name: vessels vessel_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vessels ALTER COLUMN vessel_id SET DEFAULT nextval('public.vessels_vessel_id_seq'::regclass);


--
-- Name: checkpoint_blobs checkpoint_blobs_pkey; Type: CONSTRAINT; Schema: agent_state; Owner: -
--

ALTER TABLE ONLY agent_state.checkpoint_blobs
    ADD CONSTRAINT checkpoint_blobs_pkey PRIMARY KEY (thread_id, checkpoint_ns, channel, version);


--
-- Name: checkpoint_migrations checkpoint_migrations_pkey; Type: CONSTRAINT; Schema: agent_state; Owner: -
--

ALTER TABLE ONLY agent_state.checkpoint_migrations
    ADD CONSTRAINT checkpoint_migrations_pkey PRIMARY KEY (v);


--
-- Name: checkpoint_writes checkpoint_writes_pkey; Type: CONSTRAINT; Schema: agent_state; Owner: -
--

ALTER TABLE ONLY agent_state.checkpoint_writes
    ADD CONSTRAINT checkpoint_writes_pkey PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx);


--
-- Name: checkpoints checkpoints_pkey; Type: CONSTRAINT; Schema: agent_state; Owner: -
--

ALTER TABLE ONLY agent_state.checkpoints
    ADD CONSTRAINT checkpoints_pkey PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id);


--
-- Name: budget_weekly budget_weekly_pkey; Type: CONSTRAINT; Schema: finance_test; Owner: -
--

ALTER TABLE ONLY finance_test.budget_weekly
    ADD CONSTRAINT budget_weekly_pkey PRIMARY KEY (budget_year, iso_week, vessel_category);


--
-- Name: invoices invoices_pkey; Type: CONSTRAINT; Schema: finance_test; Owner: -
--

ALTER TABLE ONLY finance_test.invoices
    ADD CONSTRAINT invoices_pkey PRIMARY KEY (invoice_number);


--
-- Name: budget_weekly budget_weekly_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.budget_weekly
    ADD CONSTRAINT budget_weekly_pkey PRIMARY KEY (budget_year, iso_week, vessel_category);


--
-- Name: containers containers_container_number_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.containers
    ADD CONSTRAINT containers_container_number_key UNIQUE (container_number);


--
-- Name: containers containers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.containers
    ADD CONSTRAINT containers_pkey PRIMARY KEY (container_id);


--
-- Name: customers customers_customer_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customers
    ADD CONSTRAINT customers_customer_name_key UNIQUE (customer_name);


--
-- Name: customers customers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.customers
    ADD CONSTRAINT customers_pkey PRIMARY KEY (customer_id);


--
-- Name: departments departments_department_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.departments
    ADD CONSTRAINT departments_department_name_key UNIQUE (department_name);


--
-- Name: departments departments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.departments
    ADD CONSTRAINT departments_pkey PRIMARY KEY (department_id);


--
-- Name: documents documents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_pkey PRIMARY KEY (document_id);


--
-- Name: documents documents_sha256_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_sha256_key UNIQUE (sha256);


--
-- Name: employees employees_email_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.employees
    ADD CONSTRAINT employees_email_key UNIQUE (email);


--
-- Name: employees employees_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.employees
    ADD CONSTRAINT employees_pkey PRIMARY KEY (employee_id);


--
-- Name: invoices invoices_invoice_number_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invoices
    ADD CONSTRAINT invoices_invoice_number_key UNIQUE (invoice_number);


--
-- Name: invoices invoices_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invoices
    ADD CONSTRAINT invoices_pkey PRIMARY KEY (invoice_id);


--
-- Name: payments payments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payments
    ADD CONSTRAINT payments_pkey PRIMARY KEY (invoice_number);


--
-- Name: port_connections port_connections_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.port_connections
    ADD CONSTRAINT port_connections_pkey PRIMARY KEY (port1_locode, port2_locode);


--
-- Name: ports ports_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ports
    ADD CONSTRAINT ports_pkey PRIMARY KEY (locode);


--
-- Name: roles roles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_pkey PRIMARY KEY (role_id);


--
-- Name: roles roles_role_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_role_name_key UNIQUE (role_name);


--
-- Name: toll_rate_bands toll_rate_bands_band_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.toll_rate_bands
    ADD CONSTRAINT toll_rate_bands_band_key UNIQUE (vessel_category, laden_ballast, band_order);


--
-- Name: toll_rate_bands toll_rate_bands_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.toll_rate_bands
    ADD CONSTRAINT toll_rate_bands_pkey PRIMARY KEY (id);


--
-- Name: vessels vessels_imo_number_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vessels
    ADD CONSTRAINT vessels_imo_number_key UNIQUE (imo_number);


--
-- Name: vessels vessels_mmsi_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vessels
    ADD CONSTRAINT vessels_mmsi_key UNIQUE (mmsi);


--
-- Name: vessels vessels_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vessels
    ADD CONSTRAINT vessels_pkey PRIMARY KEY (vessel_id);


--
-- Name: checkpoint_blobs_thread_id_idx; Type: INDEX; Schema: agent_state; Owner: -
--

CREATE INDEX checkpoint_blobs_thread_id_idx ON agent_state.checkpoint_blobs USING btree (thread_id);


--
-- Name: checkpoint_writes_thread_id_idx; Type: INDEX; Schema: agent_state; Owner: -
--

CREATE INDEX checkpoint_writes_thread_id_idx ON agent_state.checkpoint_writes USING btree (thread_id);


--
-- Name: checkpoints_thread_id_idx; Type: INDEX; Schema: agent_state; Owner: -
--

CREATE INDEX checkpoints_thread_id_idx ON agent_state.checkpoints USING btree (thread_id);


--
-- Name: test_invoices_vessel_id_idx; Type: INDEX; Schema: finance_test; Owner: -
--

CREATE INDEX test_invoices_vessel_id_idx ON finance_test.invoices USING btree (vessel_id);


--
-- Name: containers_destination_locode_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX containers_destination_locode_idx ON public.containers USING btree (destination_locode);


--
-- Name: containers_origin_locode_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX containers_origin_locode_idx ON public.containers USING btree (origin_locode);


--
-- Name: containers_vessel_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX containers_vessel_id_idx ON public.containers USING btree (vessel_id);


--
-- Name: documents_department_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX documents_department_id_idx ON public.documents USING btree (department_id);


--
-- Name: employees_department_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX employees_department_id_idx ON public.employees USING btree (department_id);


--
-- Name: employees_role_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX employees_role_id_idx ON public.employees USING btree (role_id);


--
-- Name: invoices_toll_rate_band_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX invoices_toll_rate_band_id_idx ON public.invoices USING btree (toll_rate_band_id);


--
-- Name: invoices_vessel_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX invoices_vessel_id_idx ON public.invoices USING btree (vessel_id);


--
-- Name: port_connections_geom_gist; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX port_connections_geom_gist ON public.port_connections USING gist (geom);


--
-- Name: port_connections_port2_locode_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX port_connections_port2_locode_idx ON public.port_connections USING btree (port2_locode);


--
-- Name: ports_geom_gist; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ports_geom_gist ON public.ports USING gist (geom);


--
-- Name: vessels_customer_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX vessels_customer_id_idx ON public.vessels USING btree (customer_id);


--
-- Name: vessels_destination_locode_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX vessels_destination_locode_idx ON public.vessels USING btree (destination_locode);


--
-- Name: vessels_origin_locode_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX vessels_origin_locode_idx ON public.vessels USING btree (origin_locode);


--
-- Name: invoices invoices_vessel_id_fkey; Type: FK CONSTRAINT; Schema: finance_test; Owner: -
--

ALTER TABLE ONLY finance_test.invoices
    ADD CONSTRAINT invoices_vessel_id_fkey FOREIGN KEY (vessel_id) REFERENCES public.vessels(vessel_id);


--
-- Name: containers containers_destination_locode_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.containers
    ADD CONSTRAINT containers_destination_locode_fkey FOREIGN KEY (destination_locode) REFERENCES public.ports(locode);


--
-- Name: containers containers_origin_locode_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.containers
    ADD CONSTRAINT containers_origin_locode_fkey FOREIGN KEY (origin_locode) REFERENCES public.ports(locode);


--
-- Name: containers containers_vessel_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.containers
    ADD CONSTRAINT containers_vessel_id_fkey FOREIGN KEY (vessel_id) REFERENCES public.vessels(vessel_id);


--
-- Name: documents documents_department_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_department_id_fkey FOREIGN KEY (department_id) REFERENCES public.departments(department_id);


--
-- Name: employees employees_department_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.employees
    ADD CONSTRAINT employees_department_id_fkey FOREIGN KEY (department_id) REFERENCES public.departments(department_id);


--
-- Name: employees employees_role_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.employees
    ADD CONSTRAINT employees_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(role_id);


--
-- Name: invoices invoices_toll_rate_band_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invoices
    ADD CONSTRAINT invoices_toll_rate_band_id_fkey FOREIGN KEY (toll_rate_band_id) REFERENCES public.toll_rate_bands(id);


--
-- Name: invoices invoices_vessel_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.invoices
    ADD CONSTRAINT invoices_vessel_id_fkey FOREIGN KEY (vessel_id) REFERENCES public.vessels(vessel_id);


--
-- Name: payments payments_invoice_number_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payments
    ADD CONSTRAINT payments_invoice_number_fkey FOREIGN KEY (invoice_number) REFERENCES public.invoices(invoice_number);


--
-- Name: port_connections port_connections_port1_locode_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.port_connections
    ADD CONSTRAINT port_connections_port1_locode_fkey FOREIGN KEY (port1_locode) REFERENCES public.ports(locode);


--
-- Name: port_connections port_connections_port2_locode_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.port_connections
    ADD CONSTRAINT port_connections_port2_locode_fkey FOREIGN KEY (port2_locode) REFERENCES public.ports(locode);


--
-- Name: vessels vessels_customer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vessels
    ADD CONSTRAINT vessels_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.customers(customer_id);


--
-- Name: vessels vessels_destination_locode_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vessels
    ADD CONSTRAINT vessels_destination_locode_fkey FOREIGN KEY (destination_locode) REFERENCES public.ports(locode);


--
-- Name: vessels vessels_origin_locode_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vessels
    ADD CONSTRAINT vessels_origin_locode_fkey FOREIGN KEY (origin_locode) REFERENCES public.ports(locode);


--
-- PostgreSQL database dump complete
--

