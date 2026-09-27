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

COMMENT ON COLUMN public.invoices.status IS 'Issued, Paid or Pending';


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
-- Name: vessels_destination_locode_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX vessels_destination_locode_idx ON public.vessels USING btree (destination_locode);


--
-- Name: vessels_origin_locode_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX vessels_origin_locode_idx ON public.vessels USING btree (origin_locode);


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

