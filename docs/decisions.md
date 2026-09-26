# Architecture Decision Log

Format: context, then the decision, then its consequences. Status is one of `Accepted`, `Superseded`, `Rejected` or `Deferred`.
Never delete an entry; supersede it with a new one. Sources for older entries are in `docs/archive/`.

---

## ADR-001 — Polyglot storage: PostgreSQL/PostGIS + MongoDB + Qdrant
- **Status:** Accepted (2026-09-14). Supersedes the single-store design (2026-09-10) and the "pgvector first" proposal (2026-09-13).
- **Context:** The first design put relational data, JSONB AIS/EDI and vectors (pgvector, 384-dim) in one PostgreSQL instance, with MinIO for raw files. The project is educational and job-oriented and should be ready for a larger corpus.
- **Decision:** PostgreSQL/PostGIS is the relational system of record and holds document metadata/lineage. MongoDB holds semi-structured data (AIS, EDI). Qdrant owns vector retrieval.
- **Consequences:** Three stores to run (Docker Compose later). pgvector and the `ais_tracking`/`edi_messages` JSONB tables are abandoned. MinIO was dropped silently when the design changed, without a recorded reason; it is now deferred (ADR-018). Raw files stay under `Data/raw/`.

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
- **Refined by:** ADR-019 (item-level matching, canonical-source policy, trimming).

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

## ADR-018 — DuckDB, Redis, a star schema and MinIO are deferred, not rejected
- **Status:** Deferred (2026-09-23).
- **Context:** The 2026-09-13 proposal recommended DuckDB for sandboxed analysis, a Redis-backed job queue and a star-schema analytics layer. The 2026-09-10 design used MinIO (S3-compatible object storage) for raw files, and it disappeared from later designs without a recorded reason. None of the four was discussed or rejected on merit; they were simply not needed yet. At current scale (largest table 19,990 rows), with no API, no background jobs, one user and about 30 raw PDFs read directly from `Data/raw/`, each would add a service to run and learn without solving a present problem.
- **Decision:** Do not add them now. Revisit each at its trigger:
  - **DuckDB** → agents phase, if the Analytics Agent needs an isolated, read-only analysis sandbox (e.g. querying Parquet/CSV snapshots instead of the live PostgreSQL).
  - **Redis job queue** (or another queue) → API phase, when ingestion or analysis must run in the background instead of in notebooks.
  - **Star schema** → Power BI phase. Preferred shape: fact/dimension **views** on top of the existing normalized tables, not a rebuild.
  - **MinIO / object storage** → API / Docker Compose phase, if several services need shared access to raw files, users upload documents, or document versions must be kept. Until then `Data/raw/` is the raw-file store.
- **Consequences:** No change to the current stack. When a trigger is reached, the choice becomes a new ADR (adopt or reject, with reasons).

## ADR-019 — Cross-document dedup: item-level matching and a canonical-source policy
- **Status:** Accepted (2026-09-25). Refines ADR-010; first applied in `LPI_Connecting_to_Compete_chunking.ipynb`.
- **Context:** Connecting to Compete 2025 repeats large parts of the LPI Methodology report (both indicator tables, most abbreviations, much of its Chapter 1), while also adding findings on the same concepts. Unit-level similarity alone cannot separate "same text" from "same topic, new facts".
- **Decision:** Compare **items**, not whole units: sentences for prose, indicator definitions for table rows, one line per abbreviation. An item is a duplicate when repeated (difflib ratio ≥ 0.90) or paraphrased (≥ 0.75) without any new content word; candidates are pre-filtered by TF-IDF character n-grams (≥ 0.50), small structured families are compared exhaustively. Only the ingesting source is ever modified. Canonical source by role: the **Methodology** for indicator definitions, methodology and data construction (tables, abbreviations, Chapter 1 of Connecting to Compete); **Connecting to Compete** for findings, figures and the policy framework. Units fully covered are suppressed; units in a Methodology-canonical section that also carry new sentences keep only those sentences; close paraphrases go to manual review. Thresholds, decisions, removed items and all candidate pairs are stored in the cleaned file (`duplicate_audit`).
- **Consequences:** 18 units suppressed and 7 trimmed for Connecting to Compete; the Methodology corpus is unchanged. A whole-PDF coverage audit proves every removed line has a canonical copy.
- **Extension (2026-09-26, HbR annual report):** the same matching applies **within one document**. Summary parts (the Foreword, "2025 at a glance", the key-figure tables of 6.1) are non-canonical; the thematic chapters and the financial statements are canonical. A summary unit fully covered by canonical text is suppressed, one that repeats some canonical sentences is trimmed; a repeat between two canonical units is kept (`keep_contextual`) because each belongs to its own subsection. Table rows match only when all their value numbers are contained (years and zeros excluded, ≥ 3 distinct values) and the labels share a word. Result: 9 rows suppressed, 1 card trimmed, 8 kept contextual.

## ADR-020 — Vector charts: retrieval-value gate and number-checked curated descriptions
- **Status:** Accepted (2026-09-25).
- **Context:** The charts of Connecting to Compete are vector drawings: bar heights and points are not text, and the extracted numbers are mostly axis ticks. Several figures only restate the prose.
- **Decision:** Every figure passes a value gate reviewed against its render and the surrounding prose: `full` (caption + panels + curated description + note/source), `caption_only`, or `skip` (logged with a reason). Curated descriptions are qualitative and may contain **only numbers printed in the figure's own extracted text** (asserted). The region of every figure, including skipped ones, is recorded so its text never leaks into the body. Nothing stays flagged: when a figure contradicts the prose, the figure's own plotted data are read from the vector drawings and decide; a misleading figure is skipped (the correct statement stays in the prose).
- **Consequences:** 6 full, 1 caption-only, 3 skipped figures (2.4 and 2.9 covered by prose; 2.10 skipped because its title contradicts its own data — about two economies above the 45-degree line for every one below, i.e. B2C slower, as the p.23 prose says; measured in step 4.5a). Descriptions carry `provenance = curated_from_render`.

## ADR-021 — Access level per logical unit; a chunk never mixes levels or departments
- **Status:** Accepted (2026-09-26). Applies ADR-006 and `docs/rbac_mapping.md` §4; first applied in `HbR_Annual_report_2025_chunking.ipynb`.
- **Context:** The HbR annual report is treated as NileGate's internal report: most of it is public narrative (level 1), but the Port Authority's own financial results are level 3 / Finance. A document-level constant cannot express that, and a chunk that mixes levels would leak level-3 text to level-1 users or hide level-1 text from them.
- **Decision:** `sensitivity_level` and `department` are decided **per logical unit** (Phase 9). A keyword pre-filter (money and finance terms) lists every candidate unit; **every candidate gets a reviewed decision with a reason code** (asserted: candidates = reviewed set), so no unit is classified by a keyword alone. Rule for HbR: level 3 / Finance = the organisation's own financial results and position (financial statements, revenue, operating expenses, EBITDA / net result, gross investments); programme budgets, discounts, governance thresholds, economic-impact figures and ESG ratios stay level 1. The chunking grouping key includes level and department, and validation asserts that no chunk mixes them and that the level-3 units equal the level-3 chunks. The 16-column schema is unchanged (ADR-009): the two columns are simply filled per chunk.
- **Consequences:** HbR: 140 candidates → 37 level-3 units → 5 level-3 chunks (of 352). The corpus now holds chunks of two levels; the retrieval filter (ADR-006) must be applied per chunk, never per document. Future sources with mixed sensitivity (synthetic company documents) follow the same pattern.

## ADR-022 — Source errata: content contradicted by the document itself is excluded with evidence
- **Status:** Accepted (2026-09-26). First applied in `HbR_Annual_report_2025_chunking.ipynb`.
- **Context:** Published PDFs contain errors: a table cell that contradicts its own row, a truncated number, a sentence that contradicts the same page. Indexing them would let the assistant cite a wrong fact; silently correcting them would invent content.
- **Decision:** When the PDF contradicts itself, the document's own evidence decides. The wrong cell or sentence is **excluded, never corrected**; the rest of the row / paragraph is kept. Each erratum is declared in a reviewed list with its evidence (pages, the contradicting values), applied exactly once (asserted), saved in the extracted file, and shown as `erratum_excluded` in the whole-PDF coverage audit (located physically, not by text). No item may stay flagged: it is either resolved by evidence or excluded with a reason. (A figure that contradicts its own plotted data is handled the same way under ADR-020.)
- **Consequences:** HbR: p.83 "Deepsea containers −1.5%" and "Containers 2024 = 133,4" (table cells) and the p.70 sentence on an eight-person Executive Board (prose) are excluded.

---

## Dropped (history)
- Danish Maritime Authority AIS template (`ais_real_sample_template.csv`): dropped. AIS sources are `AISHub sample.json` (type/status diversity) and `NOAA AccessAIS.csv` (movement behaviour).
