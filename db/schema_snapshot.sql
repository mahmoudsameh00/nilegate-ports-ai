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
    destination_locode character varying(5) NOT NULL
);


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
-- Name: employees; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.employees (
    employee_id integer NOT NULL,
    first_name text NOT NULL,
    last_name text NOT NULL,
    email text NOT NULL,
    role_id integer NOT NULL,
    department_id integer NOT NULL,
    hire_date date NOT NULL
);


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
    status text NOT NULL
);


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
    geom public.geometry(LineString,4326) NOT NULL
);


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
    geom public.geometry(Point,4326) NOT NULL
);


--
-- Name: roles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.roles (
    role_id integer NOT NULL,
    role_name text NOT NULL,
    allowed_sensitivity_level integer NOT NULL
);


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
    rate_sdr_per_ton numeric NOT NULL
);


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
    status text NOT NULL
);


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
-- Name: vessels vessels_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vessels
    ADD CONSTRAINT vessels_pkey PRIMARY KEY (vessel_id);


--
-- Name: documents_department_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX documents_department_id_idx ON public.documents USING btree (department_id);


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

