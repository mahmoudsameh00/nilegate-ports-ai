# Roadmap & status

Single place for project status. Last updated: 2026-09-25.
Labels: `DONE`, `IN PROGRESS`, `PARTIAL`, `NEXT`, `PLANNED`, `PROPOSED`, `DEFERRED`, `BLOCKED`.

## Current phase

**RAG, steps 3–5 (extraction, cleaning, chunking), done per source.** Done for 4 sources: FBL, LPI Methodology, Suez Notes and **LPI Connecting to Compete (finished 2026-09-25)**. **Next: `HbR_Annual_report_2025_highlights.pdf`** (new notebook, ADR-008), then the IMO circular, then the 23 USCG reports. Active plan: `docs/plans/HbR_Annual_report_2025_chunking_plan.md` (**Status: PROPOSED — review and approve before any notebook work**). Reference notebook: `Notebooks/LPI_Connecting_to_Compete_chunking.ipynb` (value gate for figures, item-level dedup, whole-PDF coverage audit, Final Checkpoint markdown); its closed plan is in `docs/archive/2026-09-25_LPI_Connecting_to_Compete_2025_chunking_plan.md`.

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
| LPI Connecting to Compete chunking | DONE | 70 chunks; 132 units → 114 after dedup against LPI Methodology (18 suppressed, 7 trimmed); cross-source concat = 199 rows; whole-PDF coverage: 2,189 lines, 0 unaccounted |
| HbR annual report chunking | NEXT | plan PROPOSED: `docs/plans/HbR_Annual_report_2025_chunking_plan.md` (needs approval) |
| IMO circular, USCG ×23 chunking | PLANNED | |
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
- HbR, IMO and USCG chunking (next: HbR).
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

- Git: all work up to 2026-09-25 (chunking notebooks, RAG artifacts, docs) is committed together with the finished LPI Connecting to Compete notebook.
- LPI Connecting to Compete contradicts itself on B2B vs B2C postal delivery times (Figure 2.10 title vs p.23). Both statements are kept verbatim; the figure unit is flagged `source_inconsistency` (ADR-020).
- Cleaned-file format differs by source: LPI Connecting to Compete stores `{source, units, duplicate_audit, coverage_audit}`, older sources store a plain list of units. The future ingestion loader must accept both (or the older files are migrated then).
- `Notebooks/_scratch/` (git-ignored) holds temporary review files (figure renders, a state export, a notebook backup); it can be deleted.
- The old DB password was committed in notebooks before ADR-015 (local development container only).
- `SyntheticGenerator.ipynb` was fixed on 2026-09-23 (paths, `%pip`, currencies, indentation, `rate_sdr_per_ton`, date anchoring, validation cell). Re-running it reproduces employees, vessels and containers exactly (employees confirmed on Windows, 2026-09-23).
- The notebooks have no automated tests. Validation lives in assertion cells.
- `toll_rate_bands.csv` extraction method is undocumented. `ExtractTollRates.ipynb` was never executed and `pdfplumber` is not a project dependency.
- `pymupdf4llm` is a dependency but is not used by any notebook (EXPERIMENTAL).
