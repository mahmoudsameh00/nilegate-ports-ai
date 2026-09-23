# Architecture — Ports & Logistics AI (NileGate)

Describes the system **as it exists today** and marks everything else explicitly.
Labels: `IMPLEMENTED`, `PLANNED` (decided, not built), `PROPOSED` (not decided), `ABANDONED`, `UNCERTAIN`.
Decisions are referenced as ADR-NNN (`docs/decisions.md`). Status lives in `docs/ROADMAP.md`.

---

## 1. System overview

A learning/job-readiness project that models a fictional port & logistics company (**NileGate**, `@nilegate.com`) with a mix of real public data and synthetic company data. The target is an AI system that answers operational and knowledge questions over three kinds of data, with role- and department-based access control.

```text
                    Structured              Semi-structured         Unstructured
                    PostgreSQL/PostGIS      MongoDB                 Qdrant (+ docs metadata in PostgreSQL)
                    IMPLEMENTED             PLANNED                 PLANNED (chunks IMPLEMENTED as files)
                          \                     |                     /
                           +------ governed tool layer (PLANNED) ----+
                                              |
                                  Supervisor → Analytics Agent (PLANNED, ADR-012)
```

Today the system is **data preparation only**: Jupyter notebooks, files under `Data/`, and one PostgreSQL database. There is no application code, API or agent yet.

## 2. Components

| Component | State | Details |
|---|---|---|
| PostgreSQL 16.9 + PostGIS 3.5.2 (Docker container `ports-postgres`, image `postgis/postgis:16-3.5`, db `ports_logistics`, port 5432, volume `ports-postgres-data`) | IMPLEMENTED | Schema verified 2026-09-23 (`db/schema_snapshot.sql`). Only the `postgres` superuser exists. Extensions: postgis, postgis_topology, postgis_tiger_geocoder, fuzzystrmatch (the last three ship with the image and are unused). |
| Structured ETL notebooks (`ExtractPortsAttributes`, `ExtractPortsConnection`, `ExtractTollRates`) | IMPLEMENTED (partly reproducible) | `ExtractTollRates` never ran, and the toll CSV's origin is undocumented. The code that loaded `ports` into the DB is not in the repo. |
| Synthetic data notebook (`SyntheticGenerator`) | IMPLEMENTED | Faker/random seed 42, hire dates anchored to 2026-09-13. It reproduces employees, vessels and containers exactly (confirmed 2026-09-23) and verifies them against the CSVs (never overwrites). Invoices are rebuilt only to validate the pricing; the DB is canonical (ADR-013). |
| RAG ingestion notebooks, one per source (ADR-008) | IMPLEMENTED for FBL, LPI Methodology, Suez Notes; IN PROGRESS for LPI Connecting to Compete | PyMuPDF extraction → cleaned logical units → semantic chunks in the 16-column schema |
| `documents` registry table | IMPLEMENTED (empty) | migration 002, ADR-009 |
| Embedding model, Qdrant | PLANNED | model not chosen |
| MongoDB (`ais_events`, `edi_messages`) | PLANNED | design only after profiling the samples |
| Agents, tool layer, API (FastAPI mentioned), auth, audit_log | PLANNED | ADR-012, ADR-014 |
| Power BI, evaluation harness, observability, Docker Compose | PLANNED / PROPOSED | see ROADMAP |
| pgvector single store, MinIO, DuckDB, Redis, star schema | ABANDONED / not adopted | ADR-001 |

## 3. Data sources (what each source is for)

| Source file (`Data/raw/...`) | Kind | Target | Role |
|---|---|---|---|
| `structured/attributed_ports.geojson` | real | `ports` | primary geographic reference (ADR-002) |
| `structured/Port_flows/port_flows.*` (shapefile) | real | `port_connections` | port-to-port network and flows |
| `unstructured/Transit_Dues_Rates.pdf` (Suez Canal Authority, from 2023-01-01) | real | tables → `toll_rate_bands`; Notes → RAG | pricing reference, deferred rules (ADR-005) |
| `semi-structured/AISHub sample.json` | real | MongoDB (planned) | vessel type / NAVSTAT diversity for the AIS generator |
| `semi-structured/NOAA AccessAIS.csv` | real | MongoDB (planned) | movement behaviour (speed, heading, stops) |
| `semi-structured/IFTMIN_D12A_sample.edi` | real template | MongoDB (planned) | EDIFACT structure for the EDI generator |
| `unstructured/LPI.pdf` (Connecting to Compete 2025, 30 p.) | real | RAG | indicator results, benchmarking, including an Egypt example |
| `unstructured/LPI_Methodology.pdf` (32 p.) | real | RAG | indicator definitions and methodology |
| `unstructured/HbR_Annual_report_2025_highlights.pdf` | real | RAG | port-authority annual report; financial tables treated as level 3 |
| `unstructured/MSC-MEPC_3-Circ_4-Rev_1.pdf` (IMO) | real | RAG | casualty-reporting fields; schema for synthetic incidents |
| `unstructured/us_coast_guard_reports/*.pdf` (23) | real | RAG | real incident narratives (ADR-007) |
| `unstructured/FBL_template.pdf` (FIATA) | real template | RAG | bill-of-lading concepts; template for synthetic FBLs |
| Faker + seeds | synthetic | departments, roles, employees, vessels, containers, invoices | company data anchored to real ports and tariffs |
| Live web search | live | agent tool (planned) | news, not corpus (ADR-011) |

## 4. Database schema (PostgreSQL) — VERIFIED 2026-09-23 (after migrations 001–003)

Source of truth: `db/schema_snapshot.sql`. Audit output: `db/audit/2026-09-23_after_migrations_report.txt`. All tables are in `public`. `spatial_ref_sys` is a PostGIS system table: never drop it.

| Table | Rows | Primary key | Columns (type, all NOT NULL unless marked `null`) |
|---|---:|---|---|
| `ports` | 837 | `locode` | locode varchar(5), name text, country text, function char(8), status char(2), outflows float8, lon float8, lat float8, geom geometry(Point,4326) |
| `port_connections` | 19,990 | (`port1_locode`, `port2_locode`) | port1_locode varchar(5), port2_locode varchar(5), flows float8, country1 text, country2 text, geom geometry(LineString,4326) |
| `toll_rate_bands` | 177 | `id` serial | vessel_category text, laden_ballast text, band_order int, band_label text, band_min_tons numeric, band_max_tons numeric `null` (open last band), rate_sdr_per_ton numeric |
| `departments` | 5 | `department_id` serial | department_name text UNIQUE, description text `null` |
| `roles` | 3 | `role_id` serial | role_name text UNIQUE, allowed_sensitivity_level int |
| `employees` | 100 | `employee_id` serial | first_name, last_name, email UNIQUE, role_id, department_id, hire_date date. No status column (ADR-017) |
| `vessels` | 500 | `vessel_id` serial | imo_number varchar(7) UNIQUE, vessel_name, vessel_type, flag_country, scnt_tons numeric, origin_locode, destination_locode, condition, status |
| `containers` | 1,000 | `container_id` serial | container_number varchar(11) UNIQUE, container_type, size_ft int, status, vessel_id, origin_locode, destination_locode |
| `invoices` | 1,000 | `invoice_id` serial | invoice_number text UNIQUE, vessel_id, toll_rate_band_id `null`, invoice_date date, scnt_tons numeric, rate_sdr_per_ton numeric `null`, amount numeric, description `null`, status |
| `documents` | 0 | `document_id` text | filename, title, source, real_or_synthetic, document_type, department_id → departments, sensitivity_level 1–3, version_date, ingestion_scope, source_url, sha256 UNIQUE, file_size_bytes, page_count, chunk_count, ingested_at, created_at. CHECKs: real_or_synthetic ∈ {real, synthetic}, sensitivity_level 1–3, file_size_bytes > 0, page_count > 0, chunk_count ≥ 0. Index on department_id. Empty until the first document is registered (ADR-009) |

`accepted_currencies` was dropped (migration 001, ADR-003).

Reference data: roles = employee(1)/manager(2)/ceo(3). Departments = Operations, Customs, Finance, HR, IT.

Constraints: CHECK constraints exist only on `documents`. Apart from `documents_department_id_idx`, the only indexes are those behind PK/UNIQUE (no FK or spatial indexes). Proposed improvements are in ROADMAP → Recommended.

### 4.1 Relations (all are enforced foreign keys unless noted)

```text
ports.locode ◄── port_connections.port1_locode, port2_locode
ports.locode ◄── vessels.origin_locode, destination_locode
ports.locode ◄── containers.origin_locode, destination_locode
vessels.vessel_id ◄── containers.vessel_id
vessels.vessel_id ◄── invoices.vessel_id
toll_rate_bands.id ◄── invoices.toll_rate_band_id
roles.role_id ◄── employees.role_id
departments.department_id ◄── employees.department_id
departments.department_id ◄── documents.department_id
vessels.vessel_type  ~  toll_rate_bands.vessel_category           (logical only, no constraint)
```

### 4.2 Verified data invariants (2026-09-23)
- Geometry: every `ports.geom` is a POINT and every `port_connections.geom` a LINESTRING, SRID 4326. `ports.lon/lat` equal `ST_X/ST_Y(geom)`.
- No orphan LOCODEs. Every container has the same origin/destination as its vessel.
- `vessels.vessel_id = imo_number − 9000000` (load order matches the CSV).
- Every `vessel_type` exists as a `vessel_category`. Toll bands are contiguous (each band's max equals the next band's min), and each (category, condition) has exactly one open-ended band. Special Floating Units have Laden bands only.
- Invoices (ADR-004): `scnt_tons` = vessel SCNT; the band's category and condition match the vessel (SFU → Laden); `rate_sdr_per_ton` = rate of the terminal band; `amount` = full progressive sum (0 mismatches, max diff 0.01 from rounding). Dates are in 2025. Statuses: Issued 361 / Paid 311 / Pending 328.
- Employees: 1 CEO (Operations), 2 managers per department, 89 employees. Emails are unique.

## 5. RAG chunk layer (IMPLEMENTED as files)

Chunk files are `Data/processed/rag/chunks/*.parquet` with the unified 16-column schema (ADR-009):
`page, unit_type, logical_unit, chunk_id, parent_chunk, sub_chunk, title, text, char_count, filename, source, real_or_synthetic, document_type, department, sensitivity_level (Int64, 1–3), version_date (string)`.

| Source | Chunks | document_type | department | level | version_date |
|---|---:|---|---|---:|---|
| FBL_template.pdf (FIATA) | 31 | bill_of_lading_template | Operations | 1 | null |
| LPI_Methodology.pdf (The World Bank) | 94 | methodology_report | Operations | 1 | 2026 (publication year; data covers 2023–2024) |
| Transit_Dues_Rates.pdf, Notes only (Suez Canal Authority) | 4 | suez_transit_dues_schedule | Finance | 1 | 2023-01-01 |
| LPI.pdf (in progress) | — | lpi_connecting_to_compete_2025 | Operations | 1 | 2025 |

Chunking rules: semantic boundaries first; `MIN_CHUNK_CHARS = 300` (short units are merged with neighbours in the same section); `MAX_CHUNK_CHARS = 2000` is a safety cap, not a target; tables become one chunk per row (bullets may be split); figures become one self-contained description; footnotes are either informative (appended as "Note: …") or citation-only (kept as metadata); dedup happens before chunking (ADR-010).

## 6. Main flows

**Structured ETL (IMPLEMENTED):**
```text
Data/raw/structured/*  ──notebook (pandas/geopandas, validate, dedup)──►  Data/processed/structured/*.csv
                                                                         └─► PostgreSQL (psycopg INSERT, or manual load — UNCERTAIN for ports/toll bands)
Faker (seed 42) + ports.csv + toll_rate_bands.csv ──SyntheticGenerator──► Data/processed/synthetic/*.csv (save_or_verify) ──► PostgreSQL
invoices: finalized inside PostgreSQL; CSV is an export (ADR-013)
```

**RAG ingestion (IMPLEMENTED up to chunks):**
```text
PDF ─► page inventory ─► page classification ─► structure map (headings, tables, figures)
    ─► structured extraction ─► notes/footnotes ─► body text + paragraph reconstruction
    ─► section assignment ─► logical units ─► dedup (ADR-010) ─► chunks ─► 16-col schema
    ─► parquet save ─► reload + validate ─► cross-source schema check
artifacts: extracted/<stem>_extracted.json · cleaned/<stem>_logical_units.json · chunks/<stem>_chunks.parquet
```

**Retrieval (PLANNED):**
```text
user ─► employee ─► role ceiling + department ─► Qdrant payload filter (docs/rbac_mapping.md)
     ─► authorized chunks only ─► ranking ─► cited passages ─► LLM
```

## 7. Interfaces

- **No API exists.** FastAPI is mentioned for later (PLANNED).
- Database access: psycopg 3 with the `PG*` variables from `.env` (ADR-015). Schema changes only through `db/migrations/` (ADR-016).
- File contracts: the CSV headers in `Data/processed/structured|synthetic/` match the table columns (minus serial ids). Chunk parquet = the 16-column schema. The Qdrant payload (PLANNED) = chunk columns + `document_id`.

## 8. Dependencies (`pyproject.toml`, Python 3.13, uv)

pandas 3.0.5, numpy 2.2.4, geopandas 1.1.4, psycopg[binary] 3.3.5, pymupdf 1.28.2, pymupdf4llm (unused), pypdf 6.18.1, pyarrow, pillow, scikit-learn 1.9.1 (TF-IDF), faker 40.38.0, ipykernel.
Not declared but referenced: `pdfplumber` (only in the never-run `ExtractTollRates.ipynb`).

## 9. Major architectural decisions

| ADR | Decision |
|---|---|
| 001 | PostgreSQL/PostGIS + MongoDB + Qdrant (pgvector single store abandoned) |
| 002 | Ports from geojson; LOCODE is the cross-entity key |
| 003 | Money in SDR only; `accepted_currencies` dropped |
| 004 | Progressive toll bands; invoices = general table; terminal-band rate |
| 005 | Suez PDF: tables → SQL, Notes → RAG |
| 006 | RBAC = numeric ceiling OR owner department (≤ 2) |
| 007 | 23 real USCG reports; synthetic incidents kept separate |
| 008 | One ingestion notebook per source |
| 009 | 16-column chunk schema; document metadata in `documents` |
| 010 | Dedup logical units before chunking |
| 011 | News via live web search |
| 012 | Supervisor + Analytics Agent MVP |
| 013 | Invoices finalized in PostgreSQL; DB is source of truth |
| 014 | Keep `documents`, defer `audit_log`, drop `document_chunks`/`reports` |
| 015 | Credentials from `.env` |
| 016 | Schema changes only via numbered migrations |

## 10. Open architectural questions

1. Embedding model (local sentence-transformers vs API). It fixes the Qdrant vector size and cost.
2. `document_id` slugs, and whether one row per file version is enough (a new version = new sha256 = new row), or explicit version history is needed.
3. Whether the proposed CHECK constraints and indexes (ROADMAP → Recommended) should be applied before the agent phase.
4. Where the shared "event timeline" for causal consistency lives (PostgreSQL table vs generator-only config).
5. Whether object storage (MinIO/S3) returns for raw files when the corpus grows (UNCERTAIN).
