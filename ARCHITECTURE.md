# Architecture — Ports & Logistics AI (NileGate)

Describes the system **as it exists today** and marks everything else explicitly.
Labels: `IMPLEMENTED`, `PLANNED` (decided, not built), `PROPOSED` (not decided), `DEFERRED` (postponed until a trigger), `ABANDONED`, `UNCERTAIN`.
Decisions are referenced as ADR-NNN (`docs/decisions.md`). Status lives in `docs/ROADMAP.md`.

---

## 1. System overview

A learning/job-readiness project that models a fictional port & logistics company (**NileGate**, `@nilegate.com`) with a mix of real public data and synthetic company data. The target is an AI system that answers operational and knowledge questions over three kinds of data, with role- and department-based access control.

```text
                    Structured              Semi-structured         Unstructured
                    PostgreSQL/PostGIS      MongoDB                 Qdrant (+ docs metadata in PostgreSQL)
                    IMPLEMENTED             IMPLEMENTED             IMPLEMENTED (2,163 points, search_documents)
                          \                     |                     /
                           +------ governed tool layer (PLANNED; the document tool is IMPLEMENTED) ----+
                                              |
                                  Supervisor → Analytics Agent (PLANNED, ADR-012)
```

Today the system is **data preparation plus the document retrieval tool**: pipeline scripts (`pipelines/scripts/`, converted from the notebooks on 2026-10-01, ADR-036), files under `Data/`, a PostgreSQL database, a MongoDB database (AIS + EDI, since 2026-09-27), a Qdrant collection `nilegate_docs` and the shared library `pipelines/lib/` whose `search_documents` is the RBAC-filtered document tool (RAG plan closed 2026-10-08, ADR-037 – ADR-044). There is no API, Supervisor or LLM answer step yet. AIS and EDI serve tools / agents and analytics, **not RAG** (ADR-030).

## 2. Components

| Component | State | Details |
|---|---|---|
| PostgreSQL 16.9 + PostGIS 3.5.2 (Docker container `ports-postgres`, image `postgis/postgis:16-3.5`, db `ports_logistics`, port 5432, volume `ports-postgres-data`) | IMPLEMENTED (closed 2026-09-27) | Schema verified 2026-09-27 after migrations 001–009 (`db/schema_snapshot.sql`, audit `db/audit/2026-09-27_after_006_009_report.txt`). Roles: `postgres` superuser + `ports_readonly` group role (SELECT only, ADR-034; the login user is created by the owner). Published on `127.0.0.1` only (ADR-034). Extensions: postgis, postgis_topology, postgis_tiger_geocoder, fuzzystrmatch (the last three ship with the image and are unused). |
| Structured ETL scripts (`pipelines/scripts/structured/`: `ExtractPortsAttributes`, `ExtractPortsConnection`) | IMPLEMENTED (partly reproducible) | The toll CSV's origin is undocumented (the never-run `ExtractTollRates` probe was deleted 2026-09-27). The code that loaded `ports` into the DB is not in the repo. |
| Synthetic data script (`pipelines/scripts/synthetic/SyntheticGenerator.py`) | IMPLEMENTED | Faker/random seed 42, hire dates anchored to 2026-09-13. It reproduces employees, vessels and containers exactly (re-confirmed 2026-09-27: 28/28 cells, all three CSVs identical) and verifies them against the CSVs (never overwrites); database-owned columns (`vessels.mmsi`) are declared in `DB_OWNED_COLUMNS` and not compared. 2026-09-27: the leftover `employees.status` (ADR-017 drift) was removed, keeping its random draw. Invoices are rebuilt only to validate the pricing; the DB is canonical (ADR-013). |
| RAG ingestion scripts, one per source (ADR-008, ADR-036; `pipelines/scripts/rag/`) | IMPLEMENTED for FBL, LPI Methodology, Suez Notes, LPI Connecting to Compete, HbR annual report 2025, IMO casualty-reporting circular | PyMuPDF extraction → cleaned logical units → (dedup) → semantic chunks in the 16-column schema |
| `documents` registry table | IMPLEMENTED (29 rows, 2026-09-27; `ingested_at` filled 2026-10-08) | migration 002 (table), 010 (rows), 011 (`ingested_at` = the last full Qdrant load); `pipelines/scripts/rag/Documents_registry.py`; ADR-009, ADR-035 |
| Qdrant 1.19.1 (Docker container `ports-qdrant`, image `qdrant/qdrant:v1.19.1` pinned by digest, ports `127.0.0.1:6333` REST / `:6334` gRPC only, volume `ports-qdrant-data`) | IMPLEMENTED (container 2026-10-02; collection `nilegate_docs` 2026-10-08) | API key on every request (`QDRANT_API_KEY`), telemetry off; probe 2026-10-02 all pass: server-side BM25 available (D4, no `fastembed`), ADR-006 filter inside both prefetches of a hybrid RRF query. Commands and audit in `db/qdrant/`; web dashboard at `http://127.0.0.1:6333/dashboard` (asks for the API key). `nilegate_docs`: 2,163 points / 29 documents, named vectors `dense` (3,072, cosine; used by every search) + `bm25` (server-built; stored for `hybrid=True` and identifier questions, unused by default — ADR-038 amendment), payload = the 16 chunk columns + `document_id` + `text_sha256`, payload indexes on the RBAC and metadata keys; point id = UUID5(document_id + chunk_id) (ADR-039); written only by `Qdrant_loader.py` (and `Upload_promotion.py --commit` for a promoted document). |
| Embedding model | IMPLEMENTED (2026-10-08) | Gemini `gemini-embedding-2`, 3,072 dims, on the composed unit `title + newline + text` (ADR-037, ADR-041); bake-off on a frozen golden set (40 EN + 24 Egyptian Arabic, `Embedding_bakeoff.py`); vectors files first in `Data/embeddings/gemini-embedding-2/` (only `manifest.json` committed); bake-off vectors of every candidate in `Data/embeddings/bakeoff/` (git-ignored, read by later scripts) |
| Document retrieval tool `search_documents` (`pipelines/lib/retrieval.py`, shared library `pipelines/lib/`, ADR-039) | IMPLEMENTED (2026-10-08) | User → role ceiling + department from PostgreSQL (read-only user) → RBAC ∧ metadata filter inside Qdrant → Gemini query vector (in-memory + disk query cache) → exact dense, 24 candidates → Jina `jina-reranker-v3.5` → top 8 (ADR-038; hybrid / shaping switchable, off). Evaluated at three levels (ADR-040): balanced 0.850, RBAC leakage 0 (88-search matrix). Scripts in `pipelines/scripts/retrieval/`. |
| MongoDB 8.0.32 (Docker container `ports-mongo`, image `mongo:8.0.32` pinned by digest, db `ports_logistics`, port `127.0.0.1:27017` only, volume `ports-mongo-data`) | IMPLEMENTED (2026-09-27) | Root user for administration + application user `readWrite` on `ports_logistics` only (ADR-027); commands, scripts and audit outputs in `db/mongo/`. Collections `ais_positions` (time-series), `ais_vessels`, `edi_messages` — see §5A. |
| Semi-structured scripts (`pipelines/scripts/semi_structured/`) | IMPLEMENTED | `AIS_EDI_profiling` (samples → reviewed profiles), `AIS_generator` (500 synthetic tracks, files), `EDI_generator` (434 synthetic IFTMIN, files), `MongoDB_loader` (the only writer to MongoDB, ADR-031: real + synthetic, reload, consistency audit). |
| Pipeline scripts + tooling (`pipelines/scripts/<area>/`, `pipelines/checkpoints/<area>/`, `tools/run.py`, `tools/nb_to_script.py`) | IMPLEMENTED (2026-10-01), verified locally (15/15, again after the refactor) | Percent-format scripts generated from the 15 notebooks: code cells identical except three listed changes, statically proven (`tools/nb_to_script.py check`); Final Checkpoint narratives in `pipelines/checkpoints/`. Owner's local run 2026-10-01: all 15 exit 0, identical ✅ lines, 0 artifacts changed; the notebooks are archived in `docs/archive/notebooks/` (ADR-036). |
| Inference-time uploads (RAG plan Phase 8; `pipelines/lib/upload_reader.py`, `screening.py`, `uploads.py`, `local_embeddings.py`, `session_store.py`; `search_documents(..., session=)`) | IMPLEMENTED as a library (2026-10-08); local model `BAAI/bge-m3` (ADR-043) | One company document shape "NileGate Document v1" (PDF / DOCX) validated at upload, layered injection screening, conversation-only storage in memory, local ONNX embeddings (no upload text leaves the machine), corpus results + separate `session_results` labelled `untrusted_upload`, manager promotion through an offline review (ADR-042 – ADR-044). Validated: 52 fixtures, 0 corpus false positives, baseline unchanged with a session, isolation 15/15, promotion self-test 11/11. |
| Agents, tool layer, API (FastAPI mentioned), auth, audit_log | PLANNED | ADR-012, ADR-014 |
| Retrieval evaluation harness (golden set, golden facts, `pipelines/lib/evaluation.py`, `Evaluation.py`) | IMPLEMENTED (2026-10-08) | ADR-040; baseline `Data/processed/rag/eval/results_2026-10-08.json` for the agents phase |
| Power BI dashboard (`powerbi/NileGate_Finance.pbip`: TMDL model + PBIR report, Power BI Desktop 2.158) | IMPLEMENTED (2026-10-15, Agents plan Phase 3) | ADR-048. DirectQuery on 12 `finance` views (all but `dim_date`) through the login `ports_bi` (member of `finance_bi` only, read-only; `db/create_finance_bi_user.ps1`, `db/check_finance_bi_user.py` 11 / 11). Model edited through the Power BI Modeling MCP (`.mcp.json`): `Week` filters every table (18 many-to-one, single-direction relationships, referential integrity off), 38 thin measures in `Weekly KPIs` (SELECTEDVALUE / HASONEVALUE-guarded SUM / SUM), 1 label column. Report: Overview, Revenue, Receivables, Customers, Exceptions (placeholder until the Auditor tool), one single-select week slicer synced on all pages. Numbers = `finance.kpi_weekly` for weeks 5 / 23 / 49. Needs PostgreSQL running when opened. |
| End-to-end answer evaluation, observability, Docker Compose | PLANNED / PROPOSED | see ROADMAP |
| pgvector single store | ABANDONED | ADR-001 |
| Star schema | IMPLEMENTED as plain views (schema `finance`, 2026-10-14) | ADR-047 (ADR-018's trigger) |
| DuckDB, Redis job queue, MinIO object storage | DEFERRED (revisit in agents / API phases) | ADR-018 |

## 3. Data sources (what each source is for)

| Source file (`Data/raw/...`) | Kind | Target | Role |
|---|---|---|---|
| `structured/attributed_ports.geojson` | real | `ports` | primary geographic reference (ADR-002) |
| `structured/Port_flows/port_flows.*` (shapefile) | real | `port_connections` | port-to-port network and flows |
| `unstructured/Transit_Dues_Rates.pdf` (Suez Canal Authority, from 2023-01-01) | real | tables → `toll_rate_bands`; Notes → RAG | pricing reference, deferred rules (ADR-005) |
| `semi-structured/AISHub sample.json` | real | MongoDB `ais_vessels` + `ais_positions` (loaded) | 30-min snapshot, one fix per vessel (10,000): vessel type / NAVSTAT diversity, static and voyage fields |
| `semi-structured/NOAA AccessAIS.csv` | real | MongoDB `ais_positions` + `ais_vessels` (loaded) | 78 min of harbour tracks (54 vessels): reporting intervals, harbour speed, teleport threshold |
| `semi-structured/IFTMIN_D12A_sample.edi` | synthetic template (self-described; profiled 2026-09-27) | MongoDB `edi_messages` (loaded, flagged) | EDIFACT structure for the EDI generator (its UNT count is wrong; no IMO, no voyage) |
| ITU Table of Maritime Identification Digits (`db/reference/itu_mid_table.csv`, captured 2026-09-27) | real | migration 005 | MID of each `flag_country` → `vessels.mmsi` (ADR-028) |
| `unstructured/LPI.pdf` (Connecting to Compete 2025, 30 p.) | real | RAG | 2023–24 findings, benchmarking, policy framework |
| `unstructured/LPI_Methodology.pdf` (32 p.) | real | RAG | indicator definitions and methodology; includes an Egypt example (Figures 7–8, deliberately not extracted) |
| `unstructured/HbR_Annual_report_2025_highlights.pdf` (Port of Rotterdam Authority, 85 p.) | real | RAG | port-authority annual report treated as NileGate's internal report: strategy, ESG, governance (level 1); own financial results (level 3, ADR-021) |
| `unstructured/MSC-MEPC_3-Circ_4-Rev_1.pdf` (IMO, 31 p., 18 Nov 2014) | real | RAG + field catalogue | what must be reported about a marine casualty and which values each field takes; its machine-readable **field catalogue** (extracted file, ADR-023) is the schema for synthetic incidents and the coding vocabulary for the USCG reports |
| `unstructured/us_coast_guard_reports/*.pdf` (23, 580 p.) | real | RAG + IMO-coded incident profiles | real incident narratives (ADR-007); one shared ROI template, one notebook for the corpus (ADR-024); 115 image-only pages OCR'd with RapidOCR (ADR-025); one incident profile per report in the extracted file + one profile chunk per report |
| `unstructured/FBL_template.pdf` (FIATA) | real template | RAG | bill-of-lading concepts; template for synthetic FBLs |
| Faker + seeds | synthetic | departments, roles, employees, vessels, containers, invoices | company data anchored to real ports and tariffs |
| Live web search | live | agent tool (planned) | news, not corpus (ADR-011) |

## 4. Database schema (PostgreSQL) — VERIFIED 2026-10-14 (after migrations 001–012; 013 = schema `finance`, views)

Source of truth: `db/schema_snapshot.sql`. Audit outputs: `db/audit/2026-09-27_after_006_009_report.txt`, `db/audit/2026-10-14_after_012_report.txt` (§17 finance data). Every table and column carries a COMMENT (migrations 008–009, 012) that describes it for tools and agents. All tables are in `public` except the evaluation copy in schema `finance_test` (migration 012). `spatial_ref_sys` is a PostGIS system table: never drop it.

| Table | Rows | Primary key | Columns (type, all NOT NULL unless marked `null`) |
|---|---:|---|---|
| `ports` | 837 | `locode` | locode varchar(5), name text, country text, function char(8), status char(2), outflows float8, lon float8, lat float8, geom geometry(Point,4326) |
| `port_connections` | 19,990 | (`port1_locode`, `port2_locode`) | port1_locode varchar(5), port2_locode varchar(5), flows float8, country1 text, country2 text, geom geometry(LineString,4326) |
| `toll_rate_bands` | 177 | `id` serial | vessel_category text, laden_ballast text, band_order int, band_label text, band_min_tons numeric, band_max_tons numeric `null` (open last band), rate_sdr_per_ton numeric |
| `departments` | 5 | `department_id` serial | department_name text UNIQUE, description text `null` |
| `roles` | 3 | `role_id` serial | role_name text UNIQUE, allowed_sensitivity_level int |
| `employees` | 100 | `employee_id` serial | first_name, last_name, email UNIQUE, role_id, department_id, hire_date date. No status column (ADR-017) |
| `vessels` | 500 | `vessel_id` serial | imo_number varchar(7) UNIQUE, vessel_name, vessel_type, flag_country, scnt_tons numeric, origin_locode, destination_locode, condition, status, **mmsi varchar(9) UNIQUE** (CHECK `^[2-7][0-9]{8}$`; migrations 004–005, ADR-028), **customer_id** → customers (migration 012, ADR-046) |
| `customers` | 40 | `customer_id` int | customer_name UNIQUE (invented), country (HQ), segment ∈ {container, tanker, bulk, roro, cruise, agent}, payment_terms_days ∈ {30, 45, 60}, credit_rating ∈ {A, B, C}. Level 2 / Finance (migration 012, ADR-046) |
| `payments` | 994 | `invoice_number` → invoices | paid_date date, amount_sdr numeric > 0 (= the invoice amount). One full payment per paid invoice, up to 2026-03-31; no row = unpaid. Level 2 / Finance |
| `budget_weekly` | 676 | (`budget_year`, `iso_week`, `vessel_category`) | budget_sdr numeric ≥ 0; year 2025 only, weeks 1–52, the 13 categories. A planning model, not fitted to the invoices. Level 2 / Finance |
| `finance_test.invoices` / `finance_test.budget_weekly` | 88 / 52 | `invoice_number` / as `budget_weekly` | evaluation copy of 4 golden weeks with planted errors and a budget miss; **no label column** (answer key outside the database). Level 2 / Finance |
| `containers` | 1,000 | `container_id` serial | container_number varchar(11) UNIQUE, container_type, size_ft int, status, vessel_id, origin_locode, destination_locode |
| `invoices` | 1,000 | `invoice_id` serial | invoice_number text UNIQUE, vessel_id, toll_rate_band_id `null`, invoice_date date, scnt_tons numeric, rate_sdr_per_ton numeric `null`, amount numeric, description `null`, status |
| `documents` | 29 | `document_id` text | filename, title, source, real_or_synthetic, document_type, department_id → departments, sensitivity_level 1–3, version_date, ingestion_scope, source_url, sha256 UNIQUE, file_size_bytes, page_count, chunk_count, ingested_at, created_at. CHECKs: real_or_synthetic ∈ {real, synthetic}, sensitivity_level 1–3, file_size_bytes > 0, page_count > 0, chunk_count ≥ 0. Index on department_id. One row per raw file of the RAG corpus (6 sources + 23 USCG reports), filled by migration 010 (ADR-035); `ingested_at` = 2026-10-08 16:58:18+03 for all 29 (migration 011, the last full load of `nilegate_docs`) |

`accepted_currencies` was dropped (migration 001, ADR-003).

**Schema `finance` (migrations 013–014, 2026-10-14, ADR-047)** — 13 plain views over the tables above (no stored data, no
materialized views; D4 / ADR-018), the only source of the Weekly Finance Pack KPIs (Power BI DirectQuery and the
agent tools read them; definitions `docs/finance_metrics.md`). `report_week` 1–52 = ISO weeks of 2025, "as of" =
Sunday 23:59; due date = invoice date + terms; payment state from `payments` only (never `invoices.status`).

| View | Grain / rows | Content |
|---|---|---|
| `dim_date` | day, 455 (2025-01-01 → 2026-03-31) | ISO year / week / label, week start / end, `report_week` (NULL in ISO 2026), calendar parts |
| `dim_week` | report week, 52 | week start / end, DSO window (start, days), `is_warmup` (weeks 1–13) |
| `dim_customer` / `dim_vessel` / `dim_toll_band` | 40 / 500 / 177 | customers; vessels with category, route and port names, customer; tariff bands |
| `fact_invoice` | invoice, 1,000 | amount, category, priced condition, band, terms, **derived due date**, paid date, days to pay / after due, `invoice_report_week` (4 invoices in 2026-W01 → NULL) |
| `fact_payment` | payment, 994 | paid date / week, amount, invoice and customer keys, days to pay |
| `fact_ar_snapshot` | open invoice × report week, 7,033 | the as-of status: days past due, `is_overdue`, aging bucket (current / 1-30 / 31-60 / 61-90 / 90+) |
| `kpi_weekly` | report week, 52 | billed, collected, AR, overdue, aging buckets, DSO (+ window), budget and variance, top-10 share (13 weeks), WoW |
| `kpi_weekly_category` | week × category, 676 | billed vs budget per category, WoW change (the week's drivers) |
| `kpi_customer_13w` | week × customer, 2,080 | billing of the week / trailing 13 weeks, share, rank (+ previous), top-10 flag, AR, overdue |
| `kpi_overdue_list` | overdue invoice × week, 1,532 | the overdue list ranked by amount, with customer and vessel names |
| `kpi_weekly_trend` | report week × trend week, 598 | the 13-week trend of each report week (weeks w−12 … w), values = `kpi_weekly` (migration 014: lets one week slicer drive a trend chart) |

Rounding once at the end of the KPI views (money 2 decimals, `*_pct` percent 2 decimals, days 1). Access: the views
are level 2 / Finance (RBAC stays the tool predicate, ADR-006 / ADR-034); `ports_readonly` reads them; the group role
`finance_bi` (NOLOGIN, read-only) has SELECT on schema `finance` only — the Power BI login `ports_bi` is its only
member (Phase 3, ADR-048). Views
run with their owner's rights, so `finance_bi` needs nothing in `public`. Verified by
`pipelines/scripts/finance/Finance_views_check.py` (7 / 7 ✅) and `verify_readonly.sql` §18.

Reference data: roles = employee(1)/manager(2)/ceo(3). Departments = Operations, Customs, Finance, HR, IT.

Constraints (migration 006, ADR-033): 32 CHECK constraints enforce every closed value set (statuses, conditions, container types / sizes, role ceilings, the 13 vessel categories on both `vessels.vessel_type` and `toll_rate_bands.vessel_category`), every code format (IMO, MMSI, container, invoice, LOCODE, UN/LOCODE function / status, `@nilegate.com` emails), every range (positive tonnages and amounts, band bounds, lat / lon) and the consistency rules `ports.geom = (lon, lat)`, `port_connections.country1/2 = left(port1/2_locode, 2)`, no self-loop, origin ≠ destination. UNIQUE (vessel_category, laden_ballast, band_order) on the toll bands. Indexes: every FK column has a B-tree index; `ports.geom` and `port_connections.geom` have GIST indexes. Negative test: `db/check_constraints_reject.sql` (14 / 14 rejected).

### 4.1 Relations (all are enforced foreign keys unless noted)

```text
ports.locode ◄── port_connections.port1_locode, port2_locode
ports.locode ◄── vessels.origin_locode, destination_locode
ports.locode ◄── containers.origin_locode, destination_locode
vessels.vessel_id ◄── containers.vessel_id
vessels.vessel_id ◄── invoices.vessel_id
customers.customer_id ◄── vessels.customer_id                     (migration 012)
invoices.invoice_number ◄── payments.invoice_number                (one payment per paid invoice)
vessels.vessel_id ◄── finance_test.invoices.vessel_id
toll_rate_bands.id ◄── invoices.toll_rate_band_id
roles.role_id ◄── employees.role_id
departments.department_id ◄── employees.department_id
departments.department_id ◄── documents.department_id
vessels.vessel_type  ~  toll_rate_bands.vessel_category           (no FK possible; both columns share the same 13-value CHECK, ADR-033)
port_connections.country1/2 = left(port1/2_locode, 2)             (ISO alpha-2 codes; ports.country holds names; CHECK)
```

### 4.2 Verified data invariants (2026-09-23)
- Geometry: every `ports.geom` is a POINT and every `port_connections.geom` a LINESTRING, SRID 4326. `ports.lon/lat` equal `ST_X/ST_Y(geom)`.
- No orphan LOCODEs. Every container has the same origin/destination as its vessel.
- `vessels.vessel_id = imo_number − 9000000` (load order matches the CSV).
- Every `vessel_type` exists as a `vessel_category`. Toll bands are contiguous (each band's max equals the next band's min), and each (category, condition) has exactly one open-ended band. Special Floating Units have Laden bands only.
- Invoices (ADR-004): `scnt_tons` = vessel SCNT; the band's category and condition match the vessel (SFU → Laden); `rate_sdr_per_ton` = rate of the terminal band; `amount` = full progressive sum (0 mismatches, max diff 0.01 from rounding). Dates are in 2025. Statuses: Issued 361 / Paid 311 / Pending 328 — **a random label, not the payment state** (ADR-046: the payment state comes from `payments`; label and payments agree on 379 / 1,000).
- Finance data (2026-10-14, `verify_readonly.sql` §17): every vessel has a customer of its segment; every payment equals its invoice amount, is dated on or after the invoice and on or before 2026-03-31; DSO at 2025-12-31 = 55 days; budget 302.1 M vs actual 267.9 M SDR.
- Employees: 1 CEO (Operations), 2 managers per department, 89 employees. Emails are unique.
- `vessels.mmsi` (2026-09-27, `verify_readonly.sql` §13): 500 non-null, unique, 9 digits; `mmsi = MID(flag_country) || lpad((vessel_id·7919 + 42) mod 10⁶, 6)`, the MID from `db/reference/flag_country_mid.csv` (one MID per flag). No MMSI equals a real one of the AIS samples.
- Our identifiers are sequential, not checksummed: 50 / 500 `imo_number` pass the IMO check digit and 101 / 1,000 `container_number` pass ISO 6346. Kept as is (owner decision Q-A, 2026-09-27); check digits are enforced on real data only.

## 5A. Semi-structured store (MongoDB) — IMPLEMENTED 2026-09-27

Database `ports_logistics` in `ports-mongo` (MongoDB 8.0.32). Written only by `pipelines/scripts/semi_structured/MongoDB_loader.py` (drop + recreate of these three collections, ADR-031); last verified load: `Data/processed/semi-structured/load_audit/` (content hashes identical on consecutive runs).

| Collection | Kind | Documents | Keys and indexes | Validation |
|---|---|---:|---|---|
| `ais_positions` | time-series (`timeField: ts`, `metaField: meta`, granularity `minutes`) | 1,321,568 = 9,982 AISHub + 967 NOAA (real) + 1,310,619 synthetic | `meta{mmsi, imo, source, real_or_synthetic, load_run, source_sha256}`, `loc` GeoJSON Point, `sog`, `cog`, `heading`, `navstat`, `src_row`; indexes `mmsi_ts` (meta.mmsi + ts), `loc_2dsphere`, and `meta_1_ts_1` (created by MongoDB) | none possible on the server (8.0.32 refuses `$jsonSchema` and unique indexes on time-series) → checked in the loader + post-load `$jsonSchema` audit (0 violations); no duplicate (mmsi, ts) |
| `ais_vessels` | regular | 10,534 = 9,982 AISHub + 52 NOAA (real) + 500 synthetic | unique (`source`, `mmsi`); `imo`; `vessel_id` (synthetic only; real = null) | server `$jsonSchema` validator (`error`, `strict`) |
| `edi_messages` | regular | 435 = 1 sample template (flag `unt_count_mismatch`) + 434 synthetic IFTMIN | unique (`source`, `interchange_ref`, `message_ref`); `keys.vessel_imo`; `keys.container_numbers`; `keys.invoice_number` | server `$jsonSchema` validator |

Every document carries provenance (source file / manifest, its sha256, load run, generator + seed for synthetic data) and `sensitivity_level = 1`, `department = Operations` (`docs/rbac_mapping.md` §3). Real vessels are reference data, never linked to PostgreSQL (ADR-028). The consistency audit of the loader (identities, UN/LOCODEs, containers, start / end ports, no teleporting, at sea, EDI ↔ AIS voyages, no shared identifiers) is a hard gate: all checks pass.

**Synthetic data rules (ADR-032):** tracks for the 500 vessels cover each vessel's current voyage up to the as-of instant `2026-09-13T00:00Z` (earliest departure 2026-06-24), consistent with `vessels.status`; the port sequence is the shortest path over `port_connections` and every leg follows a **sea path** (`searoute`, MARNET; 2 vessels without a network path sail one direct sea leg); 0.96 % of the open-sea fixes fall on land in a 1 km mask, all in canals / narrow waterways; fixes every 10 min under way / 60 min stationary; harbour speed and the teleport threshold come from the NOAA profile, open-sea speeds are documented defaults. IFTMIN: one message per vessel's consignment (its containers), dates and voyage number from the AIS voyage, `RFF+IV` = the vessel's latest invoice (376 of 434 messages; the flow is mimicked, dates are not aligned — ADR-032 amendment 2), no amounts.

## 5. RAG chunk layer (IMPLEMENTED as files)

Chunk files are `Data/processed/rag/chunks/*.parquet` with the unified 16-column schema (ADR-009):
`page, unit_type, logical_unit, chunk_id, parent_chunk, sub_chunk, title, text, char_count, filename, source, real_or_synthetic, document_type, department, sensitivity_level (Int64, 1–3), version_date (string)`.

**Title / text rule (ADR-041, 2026-10-02), one for the whole corpus:** `title` = the chunk's full location label
(document, section path, caption, clause number; for USCG the header `USCG ROI <vessel> (MISLE <n>, <date>) — <section
path>`, for IMO annex parts the document path); `text` = the body only, never starting with its heading;
`char_count = len(text)`. The unit embedded, indexed and handed to a model is `compose(title, text)` = title + newline +
text (`pipelines/lib/chunks.py`, which also enforces the rule). Applied as the last phase of the owning chunking
scripts; where the rules below say a header or path is "on every chunk", it now sits in `title`.

| Source | Chunks | document_type | department | level | version_date |
|---|---:|---|---|---:|---|
| FBL_template.pdf (FIATA) | 31 | bill_of_lading_template | Operations | 1 | null |
| LPI_Methodology.pdf (The World Bank) | 94 | methodology_report | Operations | 1 | 2026 (publication year; data covers 2023–2024) |
| Transit_Dues_Rates.pdf, Notes only (Suez Canal Authority) | 4 | suez_transit_dues_schedule | Finance | 1 | 2023-01-01 |
| LPI.pdf, Connecting to Compete 2025 (The World Bank) | 69 | lpi_connecting_to_compete_2025 | Operations | 1 | 2025 (data covers 2023–2024) |
| HbR_Annual_report_2025_highlights.pdf (Port of Rotterdam Authority) | 352 | port_authority_annual_report | Operations (347) / Finance (5) | 1 / 3, **per chunk** (ADR-021) | 2025 |
| MSC-MEPC_3-Circ_4-Rev_1.pdf (International Maritime Organization (IMO)) | 69 | imo_casualty_reporting_circular | Operations | 1 | 2014-11-18 |
| 23 × `*_ROI_Redacted.pdf` (United States Coast Guard; one file per report, `filename` per chunk) | 1,544 | uscg_report_of_investigation | Operations | 1 | per report: date of the Commandant's action (YYYY-MM-DD) |

Unified corpus today: 2,163 chunks (cross-source check passes; `chunk_id` prefixes `fbl_`/`definitions_`, `lpi_`, `suez_notes_`, `lpi2025_`, `hbr2025_`, `imo_mci_`, `uscg_`). Levels: 2,158 level 1, 5 level 3. The IMO circular's chunks and the USCG incident profiles are complementary: the circular is the reporting procedure and the dictionary of fields / codes, a profile is one incident coded with it.

Chunking rules: semantic boundaries first; `MIN_CHUNK_CHARS = 300` (short units are merged with neighbours in the same section); `MAX_CHUNK_CHARS = 2000` is a safety cap, not a target; tables become one chunk per row in the LPI notebooks, while HbR groups the consecutive short KPI rows of one table into one chunk (header written once, balanced split when a table does not fit); figures, IRO/text boxes and milestone cards become one self-contained chunk; a section made only of short pieces under minor headings becomes one labelled "section block" chunk (HbR credits); no chunk under 50 characters; footnotes are either informative (appended as "Note: …") or citation-only (kept as metadata); dedup happens before chunking (ADR-010), at item level and with a canonical-source policy across documents (ADR-019). Vector charts go through a retrieval-value gate; curated figure descriptions may only contain numbers printed in the figure (ADR-020). Content the document itself contradicts is excluded with evidence (ADR-022). `sensitivity_level` / `department` may be decided per unit, and a chunk never mixes them (ADR-021). Template corpora (USCG) are one source with one chunk file (ADR-024); every USCG chunk starts with the header `USCG ROI <vessel> (MISLE <n>, <incident date>) — <section path>`, and chunks follow the content (a vessel or persons table, a numbered finding with its sub-items, the Determination of Cause, a recommendation with its action, the incident profile; raster figure captions are metadata in the extracted file, not chunks); OCR text carries its provenance to the coverage audit (ADR-025); curated text uses roles, never names (ADR-026). Reporting forms (IMO) are chunked along their structure — one chunk per field group, conditional section or option table, the document path (and column names / condition) repeated in every part, carried-down categories written on every option line; the form itself is kept as a machine-readable field catalogue in the extracted file (ADR-023).

## 6. Main flows

**Structured ETL (IMPLEMENTED):**
```text
Data/raw/structured/*  ──script (pandas/geopandas, validate, dedup)──►  Data/processed/structured/*.csv
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
LPI Connecting to Compete adds: dedup against the Methodology units, and a whole-PDF line coverage audit;
its cleaned file is ONE JSON object {source, units, duplicate_audit, coverage_audit}
HbR adds: per-unit access decisions (ADR-021), source errata (ADR-022), within-source summary dedup (ADR-019),
band-aware reading order for full-width graphics; same single cleaned file and coverage audit
IMO adds: rows rebuilt by baseline, table columns from the drawn cell borders (merged lines split by words),
the field catalogue (fields, option tables, cross-references) in the extracted file (ADR-023), clause-level errata
```

**Semi-structured (IMPLEMENTED, 2026-09-27):**
```text
Data/raw/semi-structured/* ──AIS_EDI_profiling──► profiles/*.json (reviewed; no database)
PostgreSQL (read-only) + profiles ──AIS_generator──► synthetic/ais_*.parquet, voyages_synthetic.parquet + manifest
PostgreSQL (read-only) + voyages + IFTMIN template ──EDI_generator──► synthetic/edi_messages_synthetic.jsonl + manifest
raw samples + synthetic artifacts ──MongoDB_loader (app user; drop + recreate; reload; audit vs PostgreSQL)──► MongoDB
                                                                        └─► load_audit/<run>.json + <run>_rejected.csv
```

**Embedding and loading (IMPLEMENTED, 2026-10-08; ADR-037, ADR-039, ADR-041):**
```text
chunks/*.parquet ─► compose(title, text) ─► Gemini gemini-embedding-2 (files first, cached by chunk id + text sha256)
   ─► Data/embeddings/gemini-embedding-2/dense_composed.parquet + manifest.json (hashes)
   ─► Qdrant_loader (the only writer; UUID5 point ids; re-validated from Qdrant; second load = no change) ─► nilegate_docs
```

**Retrieval (IMPLEMENTED 2026-10-08 up to the cited chunks; the LLM answer is PLANNED):**
```text
search_documents(question, employee_id, filters, session=None)
  ─► employee ─► role ceiling + department (PostgreSQL, read-only user; docs/rbac_mapping.md)
  ─► filter = RBAC ∧ metadata, inside the Qdrant query ─► Gemini query vector (query cache)
  ─► exact dense, 24 candidates ─► Jina rerank (fallback: dense order) ─► top 8 chunks with document_id, page, level
  ─► [PLANNED] Supervisor / LLM answer with citations
```

**Documents uploaded in a conversation (IMPLEMENTED as a library, 2026-10-08; ADR-042 – ADR-044):**
```text
PDF / DOCX bytes ─► G0 type (magic bytes) + size ─► child process: upload_reader (file-level + hidden-text findings)
   ─► metadata block + uploader access (ADR-006) + footer + numbered sections ─► screening (sections with hidden
      text / injection removed and reported; required parts refuse) ─► chunks (corpus contract, ADR-041)
   ─► local ONNX embeddings ─► SessionStore (memory only, owner = employee, TTL 8 h)
search_documents(question, employee, session) ─► corpus lane (unchanged: Gemini query, RBAC, rerank) = results
                                             └► session lane (local query vector, floor, ≤ 3)   = session_results
                                                (trust = "untrusted_upload": data, never instructions)
manager + own department + explicit request ─► Data/incoming/promotion/<id>/ ─► owner: review → approve → commit
   (raw file copied by the owner; Data/processed/rag/promoted/; documents row via migration; Gemini; nilegate_docs)
```

## 7. Interfaces

- **No API exists.** FastAPI is mentioned for later (PLANNED).
- Database access: psycopg 3 with the `PG*` variables from `.env` (ADR-015). Schema changes only through `db/migrations/` (ADR-016). Tools and agents connect as a member of `ports_readonly` (`PG_RO_*`, ADR-034) and apply the RBAC predicate of `docs/rbac_mapping.md` themselves.
- MongoDB access: pymongo with the `MONGO_*` variables from `.env` (template `.env.example`), as the application user; administration with `mongosh` inside the container through `db/mongo/run.ps1` (ADR-027).
- File contracts: the CSV headers in `Data/processed/structured|synthetic/` match the table columns (minus serial ids); `vessels.csv` ends with the database-owned `mmsi` (refreshed from PostgreSQL by `db/export_vessels_mirror.py`). Chunk parquet = the 16-column schema. The Qdrant payload = the 16 chunk columns + `document_id` + `text_sha256` (`pipelines/lib/qdrant_store.py`).
- Document tool (Python, no API yet): `pipelines.lib.retrieval.search_documents(query, employee_id, k=8, filters=None, session=None)` → `SearchResult` (`results`: corpus chunks; `session_results`: the conversation's uploads, labelled `untrusted_upload`). Qdrant is reached with `qdrant-client` and `QDRANT_API_KEY`; Gemini and Jina with `httpx` and `GEMINI_API_KEY` / `JINA_API_KEY` from `.env`.

## 8. Dependencies (`pyproject.toml`, Python 3.13, uv)

pandas 3.0.5, numpy 2.2.4, geopandas 1.1.4, psycopg[binary] 3.3.5, pymupdf 1.28.2, pypdf 6.18.1, pyarrow, pillow, scikit-learn 1.9.1 (TF-IDF), faker 40.38.0, ipykernel.
Added for the USCG notebook (2026-09-26, `uv add`): rapidocr 3.9.2 + onnxruntime 1.30.0 (OCR, ADR-025), scipy 1.18.1 (figure regions on scans), nbconvert 7.17.1 (notebook execution into logs).
Added for the semi-structured phase (2026-09-27, `uv add`): pymongo 4.18.2 (+ dnspython 2.8.0), searoute 1.6.0 (+ geojson 3.3.0; sea paths), global-land-mask 1.0.0 (land check). scipy is also used for the AIS routing (`scipy.sparse.csgraph`).
Added for retrieval (2026-10-01 – 2026-10-08, `uv add`): qdrant-client 1.19.1, httpx 0.28.1 (every embedding / rerank API; no vendor SDK). scikit-learn also serves the IVF benchmark (KMeans).
Added for inference-time uploads (2026-10-08, `uv add`): defusedxml 0.7.1 (untrusted DOCX XML), tokenizers 0.22.1 (local ONNX models; brings huggingface-hub, hf-xet, fsspec). The export of the local models (`tools/export_onnx.py`) needs torch / transformers / onnx only once, in a throwaway environment, not in the project.
Added for the agents platform (2026-10-10, Agents plan Phase 0, `uv add`, all `==`): langchain-core 1.6.9, langchain 1.4.4, langgraph 1.2.14, langchain-google-genai 4.4.0 (+ google-genai), langchain-groq 1.1.3 (+ groq), langchain-openai 1.7.0 (OpenRouter's OpenAI-compatible endpoint; + openai, tiktoken), langgraph-checkpoint-postgres 3.1.2, psycopg-pool 3.3.3, pydantic 2.14.0 (was transitive 2.13.5), python-pptx 1.0.2, matplotlib 3.11.2, langsmith 0.14.7 — 49 packages installed, no existing pin changed. LLM access goes through `pipelines/agents/llm.py` (provider registry, model factory with temperature 0 and no library retries, per-minute budget, persisted daily quota state, response cache; no data guard — all project data is synthetic or public, ADR-037 amendment 2); the model per role is ADR-045 (Accepted 2026-10-12). Development skills for the coding assistant: 5 reviewed `langchain-ai/langchain-skills` in the local skills folder (`README_third_party.md`). Line endings of data files are pinned to LF by `.gitattributes` (their SHA-256 are verified).

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
| 008 | One ingestion notebook per source (a script per source since ADR-036) |
| 009 | 16-column chunk schema; document metadata in `documents` |
| 010 | Dedup logical units before chunking |
| 011 | News via live web search |
| 012 | Supervisor + Analytics Agent MVP |
| 013 | Invoices finalized in PostgreSQL; DB is source of truth |
| 014 | Keep `documents`, defer `audit_log`, drop `document_chunks`/`reports` |
| 015 | Credentials from `.env` |
| 016 | Schema changes only via numbered migrations |
| 017 | Employees have no active/inactive status |
| 018 | DuckDB, Redis, star schema, MinIO deferred to agents / API / Power BI phases |
| 019 | Cross-document dedup at item level with a canonical-source policy (refines 010) |
| 020 | Vector charts: retrieval-value gate; curated descriptions may use only printed numbers |
| 021 | Access level per logical unit; a chunk never mixes levels or departments |
| 022 | Source errata: content contradicted by the document itself is excluded with evidence |
| 023 | Reporting forms: machine-readable field catalogue + structure-following chunks (extended 2026-09-27: USCG profiles code printed facts only) |
| 024 | A source may be a corpus of same-template documents (refines 008) |
| 025 | OCR with RapidOCR: cache, provenance, readability gate |
| 026 | Personal data: report text as published, roles in curated text |
| 027 | MongoDB 8.0 in its own container, localhost only, root + least-privilege app user |
| 028 | Vessel identity in PostgreSQL (MMSI added); real AIS vessels are reference data, never linked |
| 029 | Collections `ais_positions` (time-series), `ais_vessels`, `edi_messages`; validation per collection kind |
| 030 | AIS / EDI are not RAG sources |
| 031 | Files first, one writer: generators write files, one idempotent loader writes MongoDB |
| 032 | Synthetic AIS / EDI rules: seeds, profile-derived parameters, routes over the port network, consistency audit gate |
| 033 | The database enforces its integrity (CHECK / UNIQUE, FK and GIST indexes) and describes itself (comments) |
| 034 | Database access: loopback-only ports; read-only group role for tools and agents |
| 035 | RAG document registry: one row per raw file, stable slugs, versions by fingerprint |
| 036 | Pipelines are scripts (percent format); notebooks archived |
| 037 | Embedding model: Gemini `gemini-embedding-2` (3,072 d), composed unit; never non-public data on the free tier |
| 038 | Retrieval defaults: exact dense + Jina rerank; no hybrid, no context shaping |
| 039 | Shared library `pipelines/lib/`; Qdrant point id per document version |
| 040 | Retrieval evaluation at three levels (retrieval, ranking, context) |
| 041 | One title / text rule for the whole corpus |
| 042 | Inference-time uploads: one company document shape, validator, layered injection screening |
| 043 | Conversation uploads: memory-only session store, local ONNX lane, two labelled result lists |
| 044 | Promotion of a manager's upload to the corpus: request → offline review → registration like the siblings |
| 045 | LLM per agent role on free APIs, chosen by a frozen bake-off |
| 046 | Synthetic finance data for the Weekly Finance Pack; `invoices.status` is a label |
| 047 | Schema `finance`: plain star / KPI views, one definition per metric (SQL only) |
| 048 | Power BI: Desktop + PBIP, DirectQuery via a read-only login, thin DAX (3 patterns), one synced week slicer |

## 10. Open architectural questions

1. ~~Embedding model (local sentence-transformers vs API).~~ Answered 2026-10-08 (ADR-037): Gemini `gemini-embedding-2` (3,072 dims) won a bake-off on a frozen golden set; conversation uploads use a local ONNX model, `BAAI/bge-m3` (ADR-043). Plan archived as `docs/archive/2026-10-08_RAG_Embeddings_Qdrant_plan.md`.
2. ~~`document_id` slugs and versions.~~ Answered 2026-09-27 (ADR-035): stable slugs, one row per raw file, a new file version = a new row.
3. ~~Whether the proposed CHECK constraints and indexes should be applied before the agent phase.~~ Answered 2026-09-27: applied (migration 006, ADR-033).
4. Where the shared "event timeline" for causal consistency lives (PostgreSQL table vs generator-only config). Answered for this phase (ADR-032 amendment): the 2026 operational timeline is `voyages_synthetic.parquet` (AIS + EDI); invoices are 2025 history; EDI references them (`RFF+IV`) to mimic the document flow (ADR-032 amendment 2). A shared timeline with incidents is decided with the causal-consistency phase.
5. ~~Synthetic AIS routes crossing land.~~ Answered 2026-09-27: sea paths per leg (`searoute`); open-sea fixes on land 49 % → 0.96 % (ADR-032 amendment).
6. ~~Loopback binding of `ports-postgres` and a read-only role.~~ Answered 2026-09-27: both done (ADR-034).
