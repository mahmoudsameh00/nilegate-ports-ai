# Roadmap & status

Single place for project status. Last updated: 2026-09-26 (IMO circular closed).
Labels: `DONE`, `IN PROGRESS`, `PARTIAL`, `NEXT`, `PLANNED`, `PROPOSED`, `DEFERRED`, `BLOCKED`.

## Current phase

**RAG, steps 3–5 (extraction, cleaning, chunking), done per source.** Done for 6 sources: FBL, LPI Methodology, Suez Notes, LPI Connecting to Compete, HbR annual report 2025 and **the IMO casualty-reporting circular MSC-MEPC.3/Circ.4/Rev.1 (finished 2026-09-26)**. **Next: the 23 USCG Reports of Investigation** (`Data/raw/unstructured/us_coast_guard_reports/`), parsed from a template learned on seeded samples and coded with the IMO field catalogue. Active plan: `docs/plans/USCG_ROI_chunking_plan.md` (**Status: APPROVED 2026-09-26** — one notebook for the 23 reports, OCR for image-only pages, chunking chosen per content, roles instead of names). Reference notebooks: `Notebooks/IMO_MSC-MEPC_3_Circ_4_Rev_1_chunking.ipynb` (rows by baseline, grids from cell borders, field catalogue, balanced splits), `Notebooks/HbR_Annual_report_2025_chunking.ipynb` (per-unit access control, source errata, within-source dedup, coverage audit) and `Notebooks/LPI_Connecting_to_Compete_chunking.ipynb` (notes policy, figure gate); closed plans in `docs/archive/`.

## Status

| Area | Status | Notes |
|---|---|---|
| Docker + PostgreSQL 16.9 / PostGIS 3.5.2 | DONE | verified 2026-09-23 |
| ports (837), port_connections (19,990) | DONE | verified |
| toll_rate_bands (177) | DONE | verified; how the CSV was extracted from the PDF is undocumented |
| departments (5), roles (3), employees (100) | DONE | verified |
| vessels (500), containers (1,000), invoices (1,000) | DONE | verified; invoices built in PostgreSQL (ADR-013) |
| Migration 001: drop `accepted_currencies` | DONE | applied 2026-09-23 |
| Migration 002: create `documents` | DONE | applied 2026-09-23; table empty |
| Migration 003: drop `employees.status` | DONE | applied 2026-09-23 |
| Schema snapshot + audit after migrations | DONE | 2026-09-23, all checks pass |
| RAG corpus inventory | PARTIAL | per-document classification exists in each notebook; the `documents` table exists but is empty |
| FBL chunking | DONE | 31 chunks |
| LPI Methodology chunking | DONE | 94 chunks; cross-source concat check = 129 rows |
| Suez Notes chunking | DONE | 4 chunks |
| LPI Connecting to Compete chunking | DONE | 69 chunks; 131 units → 113 after dedup against LPI Methodology (18 suppressed, 7 trimmed); cross-source concat = 198 rows; whole-PDF coverage: 2,189 lines, 0 unaccounted; nothing flagged or pending |
| HbR annual report chunking | DONE | 2026-09-26: 352 chunks (347 level 1 / Operations, 5 level 3 / Finance — ADR-021); 602 units → 593 after within-source dedup (9 suppressed, 1 trimmed); 3 source errata excluded (ADR-022); cross-source concat = 550 rows; whole-PDF coverage: 4,151 lines, 0 unaccounted; nothing flagged or pending |
| IMO circular chunking (`MSC-MEPC_3-Circ_4-Rev_1.pdf`) | DONE | 2026-09-26: 69 chunks (all level 1 / Operations); field catalogue (117 fields, 30 option tables / 553 options) in the extracted file (ADR-023); 689 units, 55 by-design repeats kept, nothing suppressed; 2 source errata excluded (ADR-022, one clause-level) + 1 empty option; cross-source concat = 619 rows; whole-PDF coverage: 2,329 lines, 0 unaccounted; nothing flagged or pending |
| USCG ×23 chunking + IMO incident profiles | NEXT | plan APPROVED 2026-09-26: `docs/plans/USCG_ROI_chunking_plan.md` (one notebook; OCR with RapidOCR installed by uv — new dependency; curated incident profiles; roles instead of names) |
| Embedding model choice | PLANNED | `Data/embeddings/` is empty |
| Qdrant setup, collection, controlled ingestion, retrieval | PLANNED | |
| RBAC-filtered retrieval | PLANNED | rule decided (ADR-006) |
| MongoDB + AIS/EDI profiling and generators | PLANNED | the samples must be profiled before any collection design |
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
- USCG chunking (next; plan APPROVED). Add the OCR engine before its Phase 1b: `uv add rapidocr onnxruntime`.
- Fill `documents` rows for every chunked source.
- Embedding model, Qdrant, retrieval with the RBAC filter.

**Recommended (PROPOSED, needs approval as a migration)**
- CHECK constraints: `roles.allowed_sensitivity_level BETWEEN 1 AND 3`; `toll_rate_bands.laden_ballast IN ('Laden','Ballast')`; `vessels.condition` idem; `containers.size_ft IN (20,40)`; positive tonnage and amounts; status value lists.
- `UNIQUE (vessel_category, laden_ballast, band_order)` on `toll_rate_bands`.
- Indexes on FK columns: `containers.vessel_id`, `invoices.vessel_id`, `invoices.toll_rate_band_id`, `employees.role_id`, `employees.department_id`, `vessels.origin_locode/destination_locode`, `port_connections.port2_locode`.
- GIST indexes on `ports.geom` and `port_connections.geom`.
- A read-only database role for agents and tools (today only the `postgres` superuser exists).
- `vessels.vessel_type` ↔ `toll_rate_bands.vessel_category` is a logical link with no constraint (0 mismatches today).

**Deferred (ADR-018): check at the start of each phase**
- Agents phase → decide on DuckDB as the analysis sandbox.
- API / Docker Compose phase → decide on a job queue (Redis or other) and on object storage for raw files (MinIO).
- Power BI phase → decide on star-schema views.

**Blocked**
- MongoDB collection design → blocked on profiling the AIS/EDI samples.
- Agents → blocked on retrieval.

## Known issues

- Git: all work up to the HbR notebook is committed (a470732); the IMO notebook, its artifacts and the 2026-09-26 IMO docs are to be committed by the owner. `Notebooks/LPI_Connecting_to_Compete_chunking.ipynb` was saved again after the last commit (2026-09-25 22:30) and shows as modified: check before committing it. Seen from the Linux VM, several data files show as modified only because of CRLF line endings (no content change).
- Cleaned-file format differs by source: LPI Connecting to Compete and HbR store `{source, units, duplicate_audit, coverage_audit}`, older sources store a plain list of units. The future ingestion loader must accept both (or the older files are migrated then).
- `Notebooks/_scratch/` (git-ignored) holds temporary review files (figure renders, a state export, a notebook backup); it can be deleted.
- The old DB password was committed in notebooks before ADR-015 (local development container only).
- `SyntheticGenerator.ipynb` was fixed on 2026-09-23 (paths, `%pip`, currencies, indentation, `rate_sdr_per_ton`, date anchoring, validation cell). Re-running it reproduces employees, vessels and containers exactly (employees confirmed on Windows, 2026-09-23).
- The notebooks have no automated tests. Validation lives in assertion cells.
- `sensitivity_level` / `department` now vary within one source (HbR, ADR-021): the future `documents` rows and the Qdrant payload must carry them per chunk; a document-level value is not enough.
- `toll_rate_bands.csv` extraction method is undocumented. `ExtractTollRates.ipynb` was never executed and `pdfplumber` is not a project dependency.
- `pymupdf4llm` is a dependency but is not used by any notebook (EXPERIMENTAL).
- USCG reports (inventory 2026-09-26): 4 reports have image-only bodies (H20_BELOW, PROWLER_ATTESSA_IV, QUEEN_OF_THE_WEST, UNA_MAS) and 2 rely on an OCR layer (VICAR_602, MERRICK); OCR is not in the stack yet: approved for the USCG notebook (RapidOCR via uv, plan §4.2).
