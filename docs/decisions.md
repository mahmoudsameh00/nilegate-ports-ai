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
- **Refined by:** ADR-024 (2026-09-27) — a source may be a corpus of same-template documents (USCG, 23 reports, one notebook).

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
- **Extension (2026-09-26, IMO MSC-MEPC.3/Circ.4/Rev.1 — reporting forms):** a form repeats values **by design** (the same option label closing many tables, the same field in several event groups). Field and option lines are compared **without their code**; within the document only exact repeats count, and they are kept (`keep_contextual`) because each belongs to its own table / group; two different lines with similar wording are recorded as `similar_wording_distinct_value`, never as duplicates. Result: 55 exact repeats kept, nothing suppressed.
- **Extension (2026-09-27, USCG reports — decision letters):** in a corpus of reports whose letters act on the report's recommendations (Commandant's action, district / OCMI endorsements), the **letters' restatements of a recommendation are kept**: each letter is a separate decision document and the recommendation beside its action / endorsement is the answerable unit. Only the Executive Summary is non-canonical within a report. Restatements are measured and listed in the duplicate audit (USCG: 390 sentences), never trimmed.

## ADR-020 — Vector charts: retrieval-value gate and number-checked curated descriptions
- **Status:** Accepted (2026-09-25).
- **Context:** The charts of Connecting to Compete are vector drawings: bar heights and points are not text, and the extracted numbers are mostly axis ticks. Several figures only restate the prose.
- **Decision:** Every figure passes a value gate reviewed against its render and the surrounding prose: `full` (caption + panels + curated description + note/source), `caption_only`, or `skip` (logged with a reason). Curated descriptions are qualitative and may contain **only numbers printed in the figure's own extracted text** (asserted). The region of every figure, including skipped ones, is recorded so its text never leaks into the body. Nothing stays flagged: when a figure contradicts the prose, the figure's own plotted data are read from the vector drawings and decide; a misleading figure is skipped (the correct statement stays in the prose).
- **Consequences:** 6 full, 1 caption-only, 3 skipped figures (2.4 and 2.9 covered by prose; 2.10 skipped because its title contradicts its own data — about two economies above the 45-degree line for every one below, i.e. B2C slower, as the p.23 prose says; measured in step 4.5a). Descriptions carry `provenance = curated_from_render`.
- **Extension (2026-09-27, USCG reports — raster figures):** the gate needs values that can be **checked against printed text**. A **raster** figure (photo, scanned or embedded image of a chart, map or diagram) has no text-readable values, so a curated description could not be number-checked: it is `caption_only` **by rule**, without a render review; text read inside it by OCR stays `figure_internal`. Review against renders applies to **vector** figures. A `caption_only` raster caption is **metadata, not a chunk**: it names an image the system cannot show, and the few facts it adds are printed in the report text (USCG measured: median 11–18 % of a caption's content words are absent from its report, mostly image annotations). USCG: 204 captions (167 photos, 35 diagrams/charts, 2 tables) kept in the extracted file; 0 figure chunks.

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
- **Extension (2026-09-26, IMO circular):** the excluded part is the **smallest part that contradicts the document** — a cell, a sentence, or a **clause** when the rest of the sentence carries a correct, separate rule. IMO: the value-type cell `Y/N/U` of field 3.2.22 (contradicts its own drop-down description and footnote 2) and the clause "and as much of the consequence data in appendix 3, as possible" of circular para. 7 (para. 8 and the annex place the consequence data in Appendix 2); the minimum-field rule of the same sentence is kept.

## ADR-023 — Reporting forms: machine-readable field catalogue + structure-following chunks
- **Status:** Accepted (2026-09-26). First applied in `IMO_MSC-MEPC_3_Circ_4_Rev_1_chunking.ipynb`.
- **Context:** The IMO circular MSC-MEPC.3/Circ.4/Rev.1 is a reporting form: 117 fields in 13 groups, 7 conditional sections, 30 option tables with 553 coded options whose categories are often printed once and carried down. Split into fixed-size pieces, a field loses its group and value type and an option its table and category. The same field list is the planned schema for synthetic incidents (ADR-007) and a coding vocabulary for the real USCG reports.
- **Decision:** (1) The form is extracted into a **machine-readable field catalogue** kept in the source's extracted file (`extracted/<stem>_extracted.json`, key `field_catalogue`: groups, fields with minimum flag / value type / footnote refs / option-table refs, option tables with their options and levels, resolved cross-references). It is a file only — no database table. (2) Chunks follow the form: **one chunk per field group, per conditional section and per option table**, each starting with its document path (and printed column names / condition), repeated in every part; categories carried down are written on every option line; a unit that does not fit is split into the fewest **balanced** parts; field lines, option lines and "If so:" blocks are never cut. (3) Rows are rebuilt by baseline and table columns come from the drawn cell borders; a line merged across a column rule is split by its words.
- **Consequences:** IMO: 69 chunks, 13 of them below `MIN_CHUNK_CHARS` (whole short tables — a chunk never mixes tables). Later consumers (USCG incident profiles, synthetic incidents, the Analytics Agent) read the catalogue from the extracted file; if it becomes a database table, that is a new migration and ADR.
- **Extension (2026-09-27, USCG incident profiles):** a report is coded with the catalogue only where the report **prints** the value or an explicit statement supports one option: printed values (date, ship particulars), counts of printed rows (ships, dead or missing by group), and reviewed codes with one evidence sentence each (1.2.6 location, 1.2.7 overall casualty event, 1.2.8 severity). Fields that need an investigator's interpretation — ship operation, accident events, human-error and contributing-factor tables (tables 12, 16–29) — are **not coded** from the narrative; "seriously injured" is not coded when the report prints only "Injured"; an undeterminable location stays empty with its reason. Every value is traced to its line or evidence sentence (USCG: 407 values, Phase 20). The circular's own chunks stay in the corpus: they are the reporting procedure and the dictionary of the fields and option tables a profile is coded with; a profile is an instance, not a replacement.

## ADR-024 — A source may be a corpus of same-template documents (refines ADR-008)
- **Status:** Accepted (2026-09-27). First applied in `USCG_ROI_chunking.ipynb`.
- **Context:** The 23 USCG Reports of Investigation are separate PDFs written on one shared template. One notebook per PDF would repeat the same parser 23 times and learn nothing from their common structure.
- **Decision:** One ingestion notebook per **source**, where a source may be a corpus of documents written on the same template: one extracted, one cleaned and one chunks file for the corpus, `filename` on every chunk, per-document layers inside the extracted file. The format is learned from a **seeded sample**, written once as a reviewed template, every document is **fingerprinted** against it, and only the deviating documents are inspected individually (reviewed deviation list, asserted).
- **Consequences:** USCG: 1 notebook, 23 reports, 19 reviewed deviations in 11 reports; 1,544 chunks in one file. Future template corpora (e.g. synthetic incident reports) follow the same pattern.

## ADR-025 — OCR with RapidOCR: dependency, cache, provenance and readability gate
- **Status:** Accepted (2026-09-27). First applied in `USCG_ROI_chunking.ipynb` (owner decisions 2026-09-26: "do OCR", "must install with uv").
- **Context:** 115 USCG pages have no usable text layer (4 reports are scanned end to end); two reports rely on an old OCR layer. Tesseract needs a system install.
- **Decision:** `rapidocr` + `onnxruntime` (pinned, added with `uv add`, ONNX models bundled; no system install). Pages are rendered at 300 dpi; OCR lines are converted to PDF coordinates and go through the same row / template logic as native text, each with its recognizer confidence and `provenance` (`ocr`, `ocr_layer`, `native`) kept to the chunk's coverage audit. Every line is kept (`text_score = 0`) and a **readability gate** decides; weak lines are re-read from their own crop; text inside figure regions (found in the page image with text masked out) is `figure_internal`; short weak marks are `ocr_noise`. A per-page **cache** (engine and model versions, dpi, settings) is an artifact owned by the notebook (`Data/processed/rag/ocr_cache/<source>/`). A page that fails the gate is excluded with its reason, never silently. If the engine fails the gate on a new source, stop and ask before another engine.
- **Consequences:** USCG: 134 cached pages, 4,085 OCR lines + 690 OCR-layer lines; 3,127 OCR lines verified in their chunks (Phase 19). `scipy` was added for the figure-region labelling.

## ADR-026 — Personal data in public reports: text as published, roles in curated text
- **Status:** Accepted (2026-09-27). Plan decision §4.6 of the USCG notebook.
- **Context:** The USCG reports are public, redacted releases, yet they still print some names (signers, individual vessel owners, a few persons in the text or tables).
- **Decision:** Report text is kept as published (level 1 / Operations, `docs/rbac_mapping.md` §4). **Curated text** — chunk headers and paths, table units (vessels, persons), incident profiles and any generated description — uses **roles** ("the operator", "an individual owner (name not kept)"), never names. Signature blocks (name, rank, office) are excluded. Individual owners/operators are a reviewed list, guarded by an assert that every other printed party is a company or a redacted name; a Name column of a persons table is excluded (`pii_excluded` in the coverage audit).
- **Consequences:** USCG: 57 signature rows corrected to `signature`, 7 reports with individual parties written as roles, 0 names in curated chunks (asserted). Synthetic incidents and future report sources follow the same rule.

## ADR-027 — MongoDB runtime: own Docker container, localhost only, least privilege
- **Status:** Accepted (2026-09-27). Owner decision 1 of the semi-structured plan; implemented and verified the same day.
- **Context:** ADR-001 puts AIS / EDI in MongoDB. The project runs PostgreSQL as a local Docker container; Docker Compose is deferred (ADR-018). Credentials are in `.env` (ADR-015).
- **Decision:** MongoDB 8.0 runs in its own container `ports-mongo`, image pinned to `mongo:8.0.32` (digest `sha256:4968f22d0c6c10ef29952f3e807f62872ba22b3312f25803564fbfc08255efc2`), named volume `ports-mongo-data`, port published as `127.0.0.1:27017` only. A root user for administration and an application user with `readWrite` on `ports_logistics` only (created in `admin`). Credentials are `MONGO_*` variables in `.env` (names in `.env.example`); they are passed to Docker by name (`-e NAME`) and to `mongosh` through `db/mongo/run.ps1`, never on a command line. Administration uses `mongosh` inside the container. The driver is `pymongo==4.18.2`. All times are UTC.
- **Consequences:** Verified (`db/mongo/audit/`): the app user can create / write / drop collections in its database and is refused `collMod`, other databases, user listing and the full database list (6/6); an unauthenticated `listDatabases` is refused. Because the app user has no `collMod`, validators are always set when a collection is created. `docker inspect` still shows the root credentials of the container (local development only, same as `ports-postgres`). The MongoDB init variables are read only on the first start of an empty volume.

## ADR-028 — Vessel identity stays in PostgreSQL; MMSI added there; real AIS vessels are reference data
- **Status:** Accepted (2026-09-27). Owner decision 3; migrations 004–005 applied 2026-09-27.
- **Context:** AIS identifies ships by MMSI; `vessels` had only `imo_number`. The AIS samples contain 10,000+ real ships that are not NileGate's.
- **Decision:** `vessels.mmsi varchar(9)` UNIQUE with CHECK `^[2-7][0-9]{8}$` (004), filled deterministically (005): `MID(flag_country) || lpad(((vessel_id * 7919 + 42) % 1000000), 6, '0')` — 7919 is coprime with 10⁶, so the tail is unique per vessel; 42 is the seed offset. The MID comes from the ITU table (`db/reference/itu_mid_table.csv`, captured from https://www.itu.int/gladapp/Allocation/MIDs) through a reviewed mapping (`db/reference/flag_country_mid.csv`: 144 automatic, 15 name forms, Guam → 338 USA and Mayotte → 226 France as sovereign fallbacks). MongoDB documents reference `mmsi` / `imo`; PostgreSQL stays the system of record. Real AIS vessels are stored with `real_or_synthetic = real` and `vessel_id = null`, never linked.
- **Consequences:** 500 unique MMSIs, 0 collisions with the 10,051 real MMSIs of the samples (checked before 005 and audited after every load, together with IMO and call signs). `vessels.csv` ends with the database-owned `mmsi` (`db/export_vessels_mirror.py`); `SyntheticGenerator.ipynb` declares it in `DB_OWNED_COLUMNS`. Our IMO and container numbers stay sequential (not checksummed, owner decision Q-A): check digits are enforced on real data only.

## ADR-029 — Semi-structured collections and how each is validated
- **Status:** Accepted (2026-09-27). Owner decision 4, confirmed by the profile (plan §3.2a) and the feature probe.
- **Context:** The profile showed AISHub = one fix per vessel (a snapshot), NOAA = short tracks, IMO often absent or a placeholder, every AISHub value a string. The probe on 8.0.32 (`db/mongo/003_probe_features.js`) showed that a time-series collection refuses `$jsonSchema` validators and unique indexes (`InvalidOptions`), accepts `2dsphere` on a measurement field and a `meta.mmsi + ts` index, and that MongoDB creates `meta_1_ts_1` itself.
- **Decision:** `ais_positions` = time-series (`ts`, `meta{mmsi, imo, source, real_or_synthetic, load_run, source_sha256}`, granularity `minutes`), GeoJSON `loc` + `2dsphere`, index `mmsi_ts`; validated in the loader and by a post-load `{$nor: [$jsonSchema]}` audit, duplicates (mmsi, ts) removed by the loader. `ais_vessels` = one document per (`source`, `mmsi`), unique index, server validator. `edi_messages` = raw text + parsed segments + business keys + `flags`, unique (`source`, `interchange_ref`, `message_ref`), server validator. Every document carries provenance and `sensitivity_level` / `department`. Replaces the earlier name `ais_events`.
- **Consequences:** 1,321,568 / 10,534 / 435 documents (after the sea-path amendment), 0 schema violations, 0 duplicates. The same schema dictionaries serve as validators and as audit queries.

## ADR-030 — AIS and EDI are not RAG sources
- **Status:** Accepted (2026-09-27). Owner decision 7.
- **Decision:** AIS and EDI documents are never chunked or embedded. They serve tools / agents (positions, tracks, port calls, declared containers) and analytics (speeds, dwell times).
- **Consequences:** The Qdrant corpus stays the document knowledge base; a future tool layer queries MongoDB directly with the RBAC predicate of `docs/rbac_mapping.md` §1.

## ADR-031 — Files first, one writer to MongoDB
- **Status:** Accepted (2026-09-27). Plan decision D8.
- **Context:** Real and synthetic data share collections, and the loader must be idempotent (owner decision 5).
- **Decision:** Generators write versioned artifacts with manifests (`Data/processed/semi-structured/synthetic/`); `Notebooks/semi_structured/MongoDB_loader.ipynb` is the only writer: it verifies the manifests, gives every input record one disposition, drops and recreates only its own three collections, reloads everything from MongoDB, re-validates it and writes `load_audit/<run>.json` + `<run>_rejected.csv`.
- **Consequences:** Two consecutive loads give identical content hashes. Every input row is accounted for (loaded or a reviewed rejection; 0 unaccounted). Re-generating one source means re-running its generator and then the loader.

## ADR-032 — Synthetic AIS / EDI generation rules
- **Status:** Accepted (2026-09-27). Owner decision 6; decisions D9–D13.
- **Decision:** Fixed seeds (42; per-vessel streams `default_rng([42, vessel_id])`); the harbour speed and the teleport threshold come from the reviewed NOAA profile, open-sea speeds are documented defaults per vessel category (the samples hold harbour traffic only). Tracks cover each vessel's current voyage up to the as-of instant `2026-09-13T00:00Z`, consistent with `vessels.status` (refines D10: a fixed 30-day window would cut long voyages); fixes every 10 min under way / 60 min stationary; routes = shortest paths over `port_connections`, legs = great circles between ports. EDI = one IFTMIN per vessel consignment on the profiled template, IMO and voyage in `TDT`, dates from the AIS voyage, `RFF+IV` = the vessel's latest invoice, no amounts. A consistency audit against PostgreSQL (18 checks) is a hard gate of the loader.
- **Consequences:** 500 static records, 434 IFTMIN for 1,000 containers; all audit checks 0. Dimensions / draught stay null (not in PostgreSQL); weights and seals are seeded defaults.
- **Amendment (2026-09-27, same day):** (1) **Sea paths.** Great-circle legs put 49 % of the under-way fixes on land. Each leg between two consecutive ports of the (unchanged) `port_connections` sequence now follows a sea path from `searoute==1.6.0` (Eurostat MARNET network, Suez / Panama included), with the port points at its ends. Result: 1,310,619 fixes, routes ~40 % longer (median 7,178 nm), earliest departure 2026-06-24, max implied speed 19.8 kn; open-sea fixes (under way, > 20 nm from every port of the route) on land in the `global-land-mask==1.0.0` 1 km grid: 0.96 %, all in canals and narrow waterways (Suez first, then Panama, Dardanelles, Scheldt, St. Lawrence, Kiel / Elbe, Amazon) — checked by the generator and again by the loader audit from MongoDB. (2) **No invoice reference in IFTMIN (D13 amended).** PostgreSQL invoices are 2025 Suez transit dues; the IFTMIN belong to 2026 voyages, so `RFF+IV` claimed a link that does not exist. The vessel ↔ invoice relation stays in PostgreSQL. (3) **Event timeline (ARCHITECTURE §10 Q4):** the 2026 synthetic voyages (`voyages_synthetic.parquet`, AIS + EDI) are the operational timeline; invoices are 2025 history.

## ADR-033 — The database enforces its own integrity and describes itself
- **Status:** Accepted (2026-09-27). Plan `PostgreSQL_Closure_plan` (findings F1–F6, F8); migrations 006, 008, 009. Supersedes the "Recommended (PROPOSED)" list of the ROADMAP.
- **Context:** A read-only examination found clean data but almost no constraints (CHECKs only on `documents` / `vessels.mmsi`), 10 unindexed foreign keys, no spatial index, planner statistics never collected, no comments, and `port_connections.country1/2` (ISO alpha-2 codes) apparently disagreeing with `ports.country` (names) on every row.
- **Decision:** Every closed value set, code format and numeric range is a CHECK (32, all verified against the data first): statuses, conditions, container types / sizes, role ceilings, email domain, IMO / container / invoice / LOCODE / MMSI formats, positive tonnages and amounts, band ranges, lat / lon ranges, `ports.geom` = lon / lat, no self-loops, no origin = destination, and `country1/2 = left(port1/2_locode, 2)`. `vessels.vessel_type` and `toll_rate_bands.vessel_category` carry the same 13-value list (a FK is impossible: the category repeats in the bands table). UNIQUE (category, condition, band order) on the bands. B-tree indexes on every FK column, GIST on both geometries. Every table and column has a COMMENT (read by the future tools). `ANALYZE` after migrations.
- **Consequences:** Negative test `db/check_constraints_reject.sql`: 14 / 14 invalid writes rejected. `verify_readonly.sql` §14–§15 all zero. Future synthetic data must respect the lists (a new status or category needs a migration).

## ADR-034 — Database access: loopback only, read-only role for tools
- **Status:** Accepted (2026-09-27). Plan `PostgreSQL_Closure_plan` (F7, F9); migration 007.
- **Context:** Only the `postgres` superuser existed, and `ports-postgres` published 5432 on every interface while `pg_hba` accepts password logins from any address. The tools / agents phase needs read access without superuser rights.
- **Decision:** `ports-postgres` is published on the loopback addresses only (`127.0.0.1` and `[::1]`, the latter because `PGHOST=localhost` resolves to IPv6 first on Windows), like `ports-mongo`. The group role `ports_readonly` (NOLOGIN) has CONNECT, USAGE on `public`, SELECT on every table, default privileges for future tables, and `default_transaction_read_only = on`; login users join it. The owner creates the login user from `.env` (`PG_RO_USER`, `PG_RO_PASSWORD`) with `db/create_readonly_user.ps1`. RBAC (ADR-006) stays a predicate applied by the tool layer; the role only guarantees read-only access.
- **Consequences:** Verified: port 5432 closed on the LAN addresses; a throwaway member of `ports_readonly` could SELECT and was refused every write both by the read-only session and, with that switched off, by privileges (8 / 8). Generators and notebooks keep using the superuser in read-only transactions until the login user exists.

---

## Dropped (history)
- Danish Maritime Authority AIS template (`ais_real_sample_template.csv`): dropped. AIS sources are `AISHub sample.json` (type/status diversity) and `NOAA AccessAIS.csv` (movement behaviour).
