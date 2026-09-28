# Roadmap & status

Single place for project status. Last updated: 2026-09-27 (semi-structured phase closed; PostgreSQL closed: constraints, indexes, comments, read-only role, loopback binding).
Labels: `DONE`, `IN PROGRESS`, `PARTIAL`, `NEXT`, `PLANNED`, `PROPOSED`, `DEFERRED`, `BLOCKED`.

## Current phase

**RAG, steps 3–5 (extraction, cleaning, chunking), done per source.** Done for 7 sources: FBL, LPI Methodology, Suez Notes, LPI Connecting to Compete, HbR annual report 2025, the IMO casualty-reporting circular and **the 23 USCG Reports of Investigation (finished 2026-09-27: 1,544 chunks, corpus 2,163)**. **Semi-structured phase DONE (2026-09-27, plan archived as `docs/archive/2026-09-27_SemiStructured_MongoDB_plan.md`): MongoDB 8.0.32 holds 1,321,568 AIS positions, 10,534 vessel records and 435 IFTMIN messages (real samples + synthetic data for our 500 vessels), loaded by one idempotent notebook with a consistency audit against PostgreSQL. Next step: not planned yet — the owner decides (no plan is active; `docs/plans/` is empty).** Closed plans in `docs/archive/`; reference notebooks: `Notebooks/rag/USCG_ROI_chunking.ipynb` (template corpora, OCR, incident profiles), `Notebooks/rag/IMO_MSC-MEPC_3_Circ_4_Rev_1_chunking.ipynb`, `Notebooks/rag/HbR_Annual_report_2025_chunking.ipynb`. The unstructured part (chunks) and the semi-structured part (MongoDB) are closed; still open: embeddings / Qdrant / retrieval.

## Status

| Area | Status | Notes |
|---|---|---|
| Docker + PostgreSQL 16.9 / PostGIS 3.5.2 | DONE (closed) | verified 2026-09-23; closed 2026-09-27: container re-created on 127.0.0.1 only, read-only group role (ADR-034) |
| Docker + MongoDB 8.0.32 (`ports-mongo`, 127.0.0.1 only, app user) | DONE | 2026-09-27; privilege check 6/6, feature probe in `db/mongo/audit/` (ADR-027) |
| ports (837), port_connections (19,990) | DONE | verified |
| toll_rate_bands (177) | DONE | verified; how the CSV was extracted from the PDF is undocumented |
| departments (5), roles (3), employees (100) | DONE | verified |
| vessels (500), containers (1,000), invoices (1,000) | DONE | verified; invoices built in PostgreSQL (ADR-013) |
| Migration 001: drop `accepted_currencies` | DONE | applied 2026-09-23 |
| Migration 002: create `documents` | DONE | applied 2026-09-23; table empty |
| Migration 003: drop `employees.status` | DONE | applied 2026-09-23 |
| Migrations 004–005: `vessels.mmsi` (add, fill from the ITU MID table) | DONE | applied 2026-09-27; verify §13 all zero (ADR-028) |
| Migrations 006–009: integrity constraints, FK / GIST indexes, read-only role, comments | DONE | applied 2026-09-27 (ADR-033, ADR-034); negative test 14/14 rejected; `ANALYZE` done |
| Schema snapshot + audit after migrations | DONE | 2026-09-27 (after 009): §13–§15 all zero, 0 errors |
| RAG corpus inventory + `documents` registry | DONE | 2026-09-27: 29 rows (migration 010, ADR-035), equal to `Data/processed/rag/documents.csv` |
| FBL chunking | DONE | 31 chunks |
| LPI Methodology chunking | DONE | 94 chunks; cross-source concat check = 129 rows |
| Suez Notes chunking | DONE | 4 chunks |
| LPI Connecting to Compete chunking | DONE | 69 chunks; 131 units → 113 after dedup against LPI Methodology (18 suppressed, 7 trimmed); cross-source concat = 198 rows; whole-PDF coverage: 2,189 lines, 0 unaccounted; nothing flagged or pending |
| HbR annual report chunking | DONE | 2026-09-26: 352 chunks (347 level 1 / Operations, 5 level 3 / Finance — ADR-021); 602 units → 593 after within-source dedup (9 suppressed, 1 trimmed); 3 source errata excluded (ADR-022); cross-source concat = 550 rows; whole-PDF coverage: 4,151 lines, 0 unaccounted; nothing flagged or pending |
| IMO circular chunking (`MSC-MEPC_3-Circ_4-Rev_1.pdf`) | DONE | 2026-09-26: 69 chunks (all level 1 / Operations); field catalogue (117 fields, 30 option tables / 553 options) in the extracted file (ADR-023); 689 units, 55 by-design repeats kept, nothing suppressed; 2 source errata excluded (ADR-022, one clause-level) + 1 empty option; cross-source concat = 619 rows; whole-PDF coverage: 2,329 lines, 0 unaccounted; nothing flagged or pending |
| USCG ×23 chunking + IMO incident profiles | DONE | 2026-09-27: 23 reports / 580 pages (115 image-only pages OCR'd with RapidOCR, ADR-025); one notebook for the corpus (ADR-024); 3,223 units (23 incident profiles, 407 values traced) → Executive Summary 49 sentences trimmed, 2 units dropped; 1 source erratum excluded (ADR-022); 1,544 chunks, all level 1 / Operations (figure captions kept as metadata, 2026-09-27); roles in curated text (ADR-026); cross-source concat = 2,163 rows; coverage: 18,999 lines, 0 unaccounted; open points closed as ADR extensions |
| Embedding model choice | NEXT | plan PROPOSED (bake-off of free API models: Jina v5-text-small, Voyage voyage-4, Gemini embedding 2, on a golden set) |
| Qdrant setup, collection, controlled ingestion, retrieval | NEXT | same plan (container `ports-qdrant`, collection `nilegate_docs`) |
| RBAC-filtered retrieval | PLANNED | rule decided (ADR-006) |
| MongoDB + AIS/EDI profiling, generators, loader | DONE | 2026-09-27: `Notebooks/semi_structured/` (profiling 28 cells, AIS generator 22, EDI generator 16, loader 32; all 0 errors); 1,321,568 / 10,534 / 435 documents; 0 schema violations, 0 unaccounted records, consistency audit all pass (incl. tracks at sea); idempotent (ADR-029 – ADR-032) |
| Synthetic incidents / synthetic FBLs | PLANNED (optional) | |
| Causal consistency checks (PostgreSQL ↔ AIS ↔ incidents ↔ RAG) | PLANNED | needs a shared event timeline per vessel/shipment |
| Agents (Supervisor + Analytics) | PLANNED | ADR-012 |
| API, auth, audit_log, guardrails | PLANNED | audit_log redesign in ADR-014 |
| Evaluation (golden tasks), observability (trace IDs) | PLANNED | |
| Power BI integration | PROPOSED | |
| Docker Compose for all services | PLANNED | not before the core works |

RAG ingestion order (do not skip ahead): inventory → metadata → extraction → cleaning → chunking → embedding model → Qdrant (local Docker) → collection → small controlled subset → retrieval test → metadata filtering → RBAC → scale → hybrid/reranking only if evaluation shows it is needed.

## Missing work

**Required**
- RAG retrieval (embeddings, Qdrant, RBAC-filtered search, evaluation): plan PROPOSED 2026-09-28 — `docs/plans/RAG_Embeddings_Qdrant_plan.md` (decisions D1–D8 at the start of the next session; free API embeddings / reranker, Qdrant hybrid; design in `docs/RETRIEVAL_FLOW.md`).
- Embedding model, Qdrant, retrieval with the RBAC filter.

**Owner actions** — done 2026-09-28: the read-only login user exists (`db/check_readonly_user.py` 8/8 PASS); the orphan Docker volume was deleted.

**Embedding readiness (checked 2026-09-28, read-only):** 2,163 chunks, 16 columns, unique `chunk_id`; 0 empty texts, 0 `char_count` mismatches, 0 over 2,000 chars, 0 under 50, 0 duplicate texts; levels 1 (2,158) / 3 (5); every department in `departments`; every chunk file name in `documents` and every `chunk_count` equal. Nothing blocks the embedding phase.

**Recommended (PROPOSED)** — the former list (CHECK constraints, toll band UNIQUE, FK and GIST indexes, read-only role, vessel type ↔ category link) was applied on 2026-09-27 (migrations 006–007, ADR-033 / ADR-034). Nothing is pending on the PostgreSQL schema.

**Deferred (ADR-018): check at the start of each phase**
- Agents phase → decide on DuckDB as the analysis sandbox.
- API / Docker Compose phase → decide on a job queue (Redis or other) and on object storage for raw files (MinIO).
- Power BI phase → decide on star-schema views.

**Blocked**
- Agents → blocked on retrieval.

## Known issues

- Git: the USCG WIP up to Phase 4 is committed (e89ef95); the finished notebook, its three artifacts (extracted, cleaned, chunks) and the 2026-09-27 docs (archive, ADR-024–026, ARCHITECTURE, ROADMAP) are to be committed by the owner. Seen from the Linux VM, several data files show as modified only because of CRLF line endings (no content change).
- Cleaned-file format differs by source: LPI Connecting to Compete and HbR store `{source, units, duplicate_audit, coverage_audit}`, older sources store a plain list of units. Not blocking: the embedding phase reads the chunk parquet files (one schema), not the cleaned files.
- The old DB password was committed in notebooks before ADR-015 (local development container only).
- `Notebooks/synthetic/SyntheticGenerator.ipynb` was fixed on 2026-09-23 (paths, `%pip`, currencies, indentation, `rate_sdr_per_ton`, date anchoring, validation cell) and on 2026-09-27 (ADR-017 drift, database-owned `mmsi`). Re-running it reproduces employees, vessels and containers exactly (28/28, re-checked after the PostgreSQL container was re-created).
- The notebooks have no automated tests. Validation lives in assertion cells.
- `sensitivity_level` / `department` now vary within one source (HbR, ADR-021): the future `documents` rows and the Qdrant payload must carry them per chunk; a document-level value is not enough.
- `toll_rate_bands.csv` extraction method is undocumented (the never-run `ExtractTollRates.ipynb` probe was deleted on 2026-09-27).
- ~~`pymupdf4llm` unused dependency~~ removed 2026-09-27 (`uv remove`; also drops pymupdf-layout and tabulate, used nowhere).
- Semi-structured phase (2026-09-27), open points:
  - ~~Synthetic AIS routes crossing land~~ closed 2026-09-27: sea paths per leg (`searoute`), open-sea fixes on land 49 % → 0.96 % (canals and narrow waterways only); MongoDB reloaded (1,321,568 positions), audit all pass (ADR-032 amendment).
  - EDI ↔ invoices: linked 2026-09-28 by owner decision (`RFF+IV` = the vessel's latest invoice, 376 messages; the flow is mimicked, dates are not aligned; audited, `edi_invoice_mismatch = 0`; ADR-032 amendment 2).
  - Our `imo_number` / `container_number` are sequential and mostly fail their check digits (kept by owner decision Q-A).
  - ~~`ports-postgres` on all interfaces~~ closed 2026-09-27 (loopback only, ADR-034). ~~Orphan Docker volume~~ deleted by the owner 2026-09-28.
  - `SyntheticGenerator.ipynb` could not have passed before 2026-09-27: it still built `employees.status` (ADR-017 drift). Fixed (draw kept), full run 28/28 with all CSVs identical.
  - Test runs of the loader left extra reports in `Data/processed/semi-structured/load_audit/`; only the latest run describes the current MongoDB content (the owner may delete the older ones).
- Unstructured data closed (2026-09-27): all 7 raw PDF sources are chunked (corpus 2,163); the three USCG open points were closed as recorded decisions (ADR-019, ADR-020 and ADR-023 extensions: letters' restated recommendations kept; raster figures caption_only by rule; profiles code printed facts only). Notebooks reorganised into `Notebooks/rag/`, `structured/`, `synthetic/`; `Notebooks/_scratch/` emptied.
