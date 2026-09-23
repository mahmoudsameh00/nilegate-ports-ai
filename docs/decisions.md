# Architecture Decision Log

Format: context, then the decision, then its consequences. Status is one of `Accepted`, `Superseded`, `Rejected` or `Deferred`.
Never delete an entry; supersede it with a new one. Sources for older entries are in `docs/archive/`.

---

## ADR-001 — Polyglot storage: PostgreSQL/PostGIS + MongoDB + Qdrant
- **Status:** Accepted (2026-09-14). Supersedes the single-store design (2026-09-10) and the "pgvector first" proposal (2026-09-13).
- **Context:** The first design put relational data, JSONB AIS/EDI and vectors (pgvector, 384-dim) in one PostgreSQL instance, with MinIO for raw files. The project is educational and job-oriented and should be ready for a larger corpus.
- **Decision:** PostgreSQL/PostGIS is the relational system of record and holds document metadata/lineage. MongoDB holds semi-structured data (AIS, EDI). Qdrant owns vector retrieval.
- **Consequences:** Three stores to run (Docker Compose later). pgvector, the `ais_tracking`/`edi_messages` JSONB tables and MinIO are not used. Raw files stay under `Data/raw/`. Whether object storage ever returns is UNCERTAIN.

## ADR-002 — Port reference data and LOCODE as the join key
- **Status:** Accepted.
- **Decision:** `ports` comes from `attributed_ports.geojson`: 856 features, deduplicated on LOCODE keeping the first occurrence, gives 837 rows (the duplicates are alternate spellings such as Turku/Åbo). `port_connections` comes from `port_flows.shp`: 20,554 rows, exact duplicates removed, gives 19,990. Every operational entity references ports by 5-character UN/LOCODE.
- **Rejected:** deriving ports from `port_flows` (836 ports), which the early inventory proposed.

## ADR-003 — Money is stored in SDR only
- **Status:** Accepted.
- **Decision:** Tariff rates are SDR per Suez Canal Net Ton (SCNT). All stored and calculated amounts stay in SDR. `invoices.currency` was removed. The `accepted_currencies` table (10 currencies from the tariff PDF) was dropped by `db/migrations/001` on 2026-09-23. It had been left in the DB after the decision.
- **Consequences:** Multi-currency invoicing would be a new decision, not a restoration of the table.

## ADR-004 — Progressive toll bands; invoices as a general table
- **Status:** Accepted.
- **Decision:** `toll_rate_bands` stores progressive bands per (vessel_category, laden_ballast): 13 categories, 177 rows, 7 bands (8 for Containerships), the last band open-ended. `invoices` is a general invoices table, not a Suez-only table. For generated Suez invoices:
  - `amount` = Σ rate × tons inside each band (full progressive amount)
  - `toll_rate_band_id` and `rate_sdr_per_ton` = the terminal band that contains the vessel's SCNT
  - Special Floating Units are always priced as Laden (the source has Laden rates only)
- **Verified 2026-09-23:** all 1,000 invoices satisfy these rules exactly (`db/audit/2026-09-23_verify_report.txt`, §12).
- **Deferred business rules** (retrieval-only, via ADR-005): Ballast Petroleum Product / Oil-Chemical tankers → ballast Crude Oil rates; OBO/combined carriers → highest applicable cargo rate; refusal of transit inspection → gross tonnage plus extra charges; actual condition at transit controls.

## ADR-005 — The Suez tariff PDF has two roles
- **Status:** Accepted.
- **Decision:** The numeric tables live in `toll_rate_bands` and have no RAG role. The **Notes section** is a RAG source, so that the deferred rules in ADR-004 and the Special Floating Units definition can be retrieved and explained.

## ADR-006 — RBAC: numeric sensitivity ceiling plus owner department
- **Status:** Accepted. The numeric ceiling was decided 2026-09-14; the department rule was added 2026-09-23.
- **Rejected:** named levels (`public/internal/confidential/executive`) stored as a `TEXT[]` per role.
- **Decision:** `roles.allowed_sensitivity_level` is an integer ceiling (employee 1, manager 2, ceo 3). A resource is visible if its level is at or below the role ceiling, **or** if it belongs to the user's department and its level is ≤ 2. Level 3 is never unlocked by department. Every `department` value must be a row in `departments`. Employees have no status (ADR-017). Full mapping: `docs/rbac_mapping.md`.

## ADR-007 — USCG reports: real corpus, separate from synthetic incidents
- **Status:** Accepted.
- **Decision:** The real USCG Reports of Investigation are ingested as-is with `source_type = real_regulatory_report`. **23 files.** One report (the DALI / Francis Scott Key Bridge BOIR) was removed on purpose by the owner. Planned synthetic incidents that reference our own vessels, ports and containers use `synthetic_internal_incident` and use the real reports as few-shot style grounding.

## ADR-008 — One ingestion notebook per source document
- **Status:** Accepted.
- **Decision:** Each RAG source has its own notebook (`<Source>_chunking.ipynb`) that writes to `Data/processed/rag/{extracted,cleaned,chunks}`. The earlier combined `Notebooks/rag_pipeline.ipynb` was deleted on purpose.
- **Consequence:** Cross-source consistency comes from the shared chunk schema (ADR-009) and a cross-source validation step in each notebook.

## ADR-009 — Unified 16-column chunk schema; document metadata in PostgreSQL
- **Status:** Accepted (2026-09-23 for the `documents` table part).
- **Decision:** Every chunk file uses exactly: `page, unit_type, logical_unit, chunk_id, parent_chunk, sub_chunk, title, text, char_count, filename, source, real_or_synthetic, document_type, department, sensitivity_level, version_date`. There is one authoritative text field (`text`); no `content`/`rag_text` duplication. Document-level metadata (document_id, checksum, file size, page count, ingestion time) lives in the PostgreSQL `documents` table (`db/migrations/002`). Audit and dedup metadata live in separate artifacts, never in the chunk schema.
- **Consequence:** The Qdrant payload = chunk columns + `document_id`. This resolves the gap between the checkpoint's metadata list and the implemented schema.

## ADR-010 — Deduplicate logical units before chunking
- **Status:** Accepted (first applied in the LPI Connecting to Compete plan).
- **Decision:** Detect duplicates at the logical-unit level: normalized hash for exact duplicates, then lexical similarity (TF-IDF / cosine) for near duplicates. Choose the canonical copy by source role. Keep contextual duplicates. When unsure, send to manual review and do not delete. Embeddings are not a dependency of ingestion.

## ADR-011 — Current news comes from a live tool, not the corpus
- **Status:** Accepted.
- **Decision:** News questions ("what happened in the Suez Canal this week") are answered by a live `web_search` tool routed by the agent layer, not by ingestion.

## ADR-012 — Agents MVP = Supervisor + Analytics Agent
- **Status:** Accepted (design only; not implemented).
- **Decision:** Start with one Supervisor (task state, routing, evidence) and one Analytics Agent. Add specialists (Knowledge/RAG, Power BI, Validator, Visualization) only when they improve accuracy, security isolation or maintainability.

## ADR-013 — Invoices were finalized inside PostgreSQL
- **Status:** Accepted (2026-09-23).
- **Context:** `SyntheticGenerator.ipynb` does not reproduce the stored invoices (its last cell fails and it never computes `rate_sdr_per_ton`).
- **Decision:** The database is the source of truth for `invoices`. `Data/processed/synthetic/invoices.csv` is an export of it. Since 2026-09-23 the notebook re-runs cleanly: it reproduces employees, vessels and containers (hire dates anchored to 2026-09-13, `save_or_verify` refuses to overwrite a CSV with different data), and it rebuilds invoices only to validate the pricing method. It never saves or loads invoices.

## ADR-014 — Tables from the first design: kept, deferred or dropped
- **Status:** Accepted (2026-09-23).
- `documents` → **kept, redesigned** (migration 002).
- `audit_log` → **deferred** to the API/agents phase. Redesign then: `employee_id INTEGER` (not UUID), `resource_type`, `resource_id`, `decision` (allowed/denied), `trace_id`, `TIMESTAMPTZ`.
- `document_chunks` → **dropped** (replaced by the Qdrant payload and the parquet chunk files).
- `reports` → **dropped** (no consumer; revisit if scheduled reports are built).
- `ais_tracking`, `edi_messages` → **moved** to MongoDB (ADR-001).

## ADR-015 — Database credentials come from `.env`
- **Status:** Accepted (2026-09-23).
- **Decision:** Notebooks read `PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD` from the git-ignored `.env` at the project root (template: `.env.example`). No credentials in notebooks.
- **Consequence:** The old literal password is still in git history (local development container only).

## ADR-016 — Schema changes only through numbered migrations
- **Status:** Accepted (2026-09-23).
- **Decision:** `db/schema_snapshot.sql` (pg_dump) is the schema source of truth. Every change is a new `db/migrations/NNN_*.sql`, applied by the owner, followed by a new snapshot. The live database is only accessed read-only otherwise.

## ADR-017 — Employees have no active/inactive status
- **Status:** Accepted (2026-09-23).
- **Context:** The generator gave each regular employee a random `Active`/`Inactive` status (95/5). This produced 6 Inactive rows that no rule used.
- **Decision:** The concept does not exist in the model. `employees.status` is dropped (`db/migrations/003`), removed from `employees.csv` and from `SyntheticGenerator.ipynb`. The generator keeps one `random.random()` draw where the status was drawn, so every `department_id` stays identical to the stored rows (verified).

---

## Rejected / not adopted (history)
- DuckDB for local analytics, Redis job queue, star schema warehouse layer: PROPOSED in the 2026-09-13 proposal, not adopted.
- Danish Maritime Authority AIS template (`ais_real_sample_template.csv`): dropped. AIS sources are `AISHub sample.json` (type/status diversity) and `NOAA AccessAIS.csv` (movement behaviour).
