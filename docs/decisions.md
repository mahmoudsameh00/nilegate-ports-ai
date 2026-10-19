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
- **Amendment 2 (2026-09-28, owner decision) — supersedes point (2):** every IFTMIN of a vessel that has invoices carries `RFF+IV` with the vessel's latest invoice (by date, then number): 376 of 434 messages. The project mimics the document flow (transport instruction → voyage → Suez transit dues invoice → toll band); the dates are not aligned and that is accepted. The EDI generator asserts that every referenced invoice belongs to the message's vessel, the loader audit re-checks it from MongoDB against PostgreSQL (`edi_invoice_mismatch = 0`), and `edi_messages` has an index on `keys.invoice_number`. The invoice number is a reference only (no amounts, D14): `edi_messages` stays level 1; the invoice itself stays level 2 / Finance in PostgreSQL.

## ADR-033 — The database enforces its own integrity and describes itself
- **Status:** Accepted (2026-09-27). Plan `PostgreSQL_Closure_plan` (findings F1–F6, F8); migrations 006, 008, 009. Supersedes the "Recommended (PROPOSED)" list of the ROADMAP.
- **Context:** A read-only examination found clean data but almost no constraints (CHECKs only on `documents` / `vessels.mmsi`), 10 unindexed foreign keys, no spatial index, planner statistics never collected, no comments, and `port_connections.country1/2` (ISO alpha-2 codes) apparently disagreeing with `ports.country` (names) on every row.
- **Decision:** Every closed value set, code format and numeric range is a CHECK (32, all verified against the data first): statuses, conditions, container types / sizes, role ceilings, email domain, IMO / container / invoice / LOCODE / MMSI formats, positive tonnages and amounts, band ranges, lat / lon ranges, `ports.geom` = lon / lat, no self-loops, no origin = destination, and `country1/2 = left(port1/2_locode, 2)`. `vessels.vessel_type` and `toll_rate_bands.vessel_category` carry the same 13-value list (a FK is impossible: the category repeats in the bands table). UNIQUE (category, condition, band order) on the bands. B-tree indexes on every FK column, GIST on both geometries. Every table and column has a COMMENT (read by the future tools). `ANALYZE` after migrations.
- **Consequences:** Negative test `db/check_constraints_reject.sql`: 14 / 14 invalid writes rejected. `verify_readonly.sql` §14–§15 all zero. Future synthetic data must respect the lists (a new status or category needs a migration).

## ADR-034 — Database access: loopback only, read-only role for tools
- **Status:** Accepted (2026-09-27). Plan `PostgreSQL_Closure_plan` (F7, F9); migration 007.
- **Context:** Only the `postgres` superuser existed, and `ports-postgres` published 5432 on every interface while `pg_hba` accepts password logins from any address. The tools / agents phase needs read access without superuser rights.
- **Decision:** `ports-postgres` is published on `127.0.0.1` only, like `ports-mongo`, and `PGHOST=127.0.0.1` in `.env` (with `localhost`, Windows tries IPv6 `::1` first and every connection waited 5 s; `[::1]` was published for a short time until the owner changed `PGHOST`). The group role `ports_readonly` (NOLOGIN) has CONNECT, USAGE on `public`, SELECT on every table, default privileges for future tables, and `default_transaction_read_only = on`; login users join it. The owner creates the login user from `.env` (`PG_RO_USER`, `PG_RO_PASSWORD`) with `db/create_readonly_user.ps1`. RBAC (ADR-006) stays a predicate applied by the tool layer; the role only guarantees read-only access.
- **Consequences:** Verified: port 5432 closed on the LAN addresses; a throwaway member of `ports_readonly` could SELECT and was refused every write both by the read-only session and, with that switched off, by privileges (8 / 8). Generators and notebooks keep using the superuser in read-only transactions until the login user exists.

## ADR-035 — RAG document registry: one row per raw file, stable slugs, versions by fingerprint
- **Status:** Accepted (2026-09-27). Answers ARCHITECTURE §10 Q2; migration 010, `Notebooks/rag/Documents_registry.ipynb`.
- **Context:** `documents` (ADR-009) existed but was empty. Filling it is the metadata step of the RAG ingestion order; it needs only the raw files and the chunk files, not the embedding decisions. The USCG corpus is one notebook but 23 files, and HbR mixes access levels (ADR-021).
- **Decision:** One row per raw file (29 = 6 sources + 23 USCG reports). `document_id` = a stable lowercase slug (reviewed for the 6 sources; `uscg_roi_<vessel>_<MISLE>` for the reports). A changed file (new `sha256`) is a new version: a new row `<slug>_v2` and re-ingestion of its chunks; no separate history table (all sources are fixed publications). `department` / `sensitivity_level` are document defaults (the majority of its chunks); chunk values stay authoritative. Titles as printed (PDF metadata for the reports, first page otherwise); `source_url` NULL because it was never recorded (not invented); `ingested_at` NULL until Qdrant. The rows are generated by the notebook with a CSV mirror (`Data/processed/rag/documents.csv`) and inserted by a generated migration, then compared with the mirror read-only.
- **Consequences:** 29 rows, 2,163 chunks, 765 pages, 29 distinct fingerprints (`verify_readonly.sql` §16). The Qdrant payload will carry `document_id`; the retrieval filter stays per chunk (ADR-021).

## ADR-036 — Pipelines are scripts (percent format); notebooks archived
- **Status:** Accepted (2026-10-01). Plan `docs/archive/2026-10-01_Scripts_and_ingestion_plan.md` (D1–D7). Supersedes the notebook parts of ADR-008 (one notebook per RAG source → one script per source) and the `notebook-dev-loop` skill.
- **Context:** The owner wants all work in scripts from now on. 15 notebooks (~23,900 code lines) hold every pipeline; their code had to keep the same flow and produce the same outputs.
- **Decision:** Each notebook becomes `pipelines/scripts/<area>/<stem>.py` in percent format (`# %% cell N` = notebook cell N), generated by `tools/nb_to_script.py`, never retyped. Code cells are byte-identical except three listed changes: `from IPython.display import display` in the header; a bare last expression wrapped in `_display_result(...)` (Jupyter showed it unless None); an IPython `%pip` line commented. Markdown cells stay in place as comments. The closing Final Checkpoint narrative moves unchanged to `pipelines/checkpoints/<area>/<stem>.md` (D1: a scripts folder and a checkpoints folder inside `pipelines/`). `tools/nb_to_script.py check` proves the equality statically; `tools/run.py --compare` runs a script, compares its ✅ lines with the notebook's saved outputs and reports every changed artifact by SHA-256. Paths written into outputs (e.g. the AIS / EDI manifests' `generator`, migration 010's header) keep the notebook path so the outputs stay byte-identical. Notebooks move to `docs/archive/notebooks/` after the owner's local run (D2); refactoring a script is allowed afterwards, one script at a time, each re-verified with the same check (D3).
- **Consequences:** `tools/run.py` replaces `tools/nb.py run`; skill `script-dev-loop` replaces `notebook-dev-loop`. `ExtractPortsConnection.py`: its INSERT into `port_connections` (cell 21) is disabled at the owner's request (kept as `#! ` comments, restorable by the converter), so the script is safe to re-run. A bare tuple `a, b` ending a cell is wrapped in `_display_tuple(...)` (shows the tuple, as Jupyter did). New pipelines (RAG retrieval, the PDF ingestion agent) are scripts.
- **Amendment (2026-10-01, refactor D3):** two levels. **Level A** (functions + `main()`, assertions instead of exploration prints, by hand): ExtractPortsAttributes, ExtractPortsConnection (its INSERT became `insert_port_connections()`, run only with `--insert` and refused on a non-empty table), SyntheticGenerator (the random-draw order is kept; vessels.csv and containers.csv regenerated identical in the cloud session), Documents_registry (migration 010 re-rendered byte-identical from the mirror), EDI_generator. **Level B** (`tools/nb_to_script.py clean`, generated from the archived notebook): the 7 RAG chunking scripts, AIS_EDI_profiling, AIS_generator, MongoDB_loader keep their linear phase structure (the flow, with a reviewed validation after each phase) as `# %% <Phase title>` sections with the narrative as comments; Jupyter's implicit display of a last expression and `display()` become `print()`; `check` proves the AST equals the archived notebook's code under exactly those rules. Verification: `tools/run.py all --compare` on the owner's machine (same ✅ lines in order, new ones allowed for level A; `files changed: 0`).

## ADR-037 — Embedding model: Gemini `gemini-embedding-2` (3,072 dimensions)
- **Status:** Accepted (2026-10-05) for the model; **D5 decided 2026-10-08: the composed unit** (complete run,
  `Data/processed/rag/eval/bakeoff_results.json`). RAG plan Phase 2; rule D1.
- **D5 (stage 2, Gemini):** composed `title + newline + text` D1 0.912 (EN 0.950 / AR 0.875), balanced 0.812, identifier
  hit@10 1.000 vs body only D1 0.867 (EN 0.900 / AR 0.833), balanced 0.772, identifier 0.778: the title helps in every
  column and both languages (as for Voyage); the dense vector embeds `compose(title, text)` (ADR-041).
- **Context:** Bake-off of three free API models on the frozen golden set (64 queries, 40 EN + 24 Egyptian Arabic
  twins) and the frozen golden facts, after the title / text normalization (ADR-041), each embedding the composed
  unit `title + newline + text` with its retrieval task parameters. `Embedding_bakeoff.py` stage 1, 2026-10-05.
- **Results (stage 1, composed unit):**

  | Model | D1 primary | hit@10 EN | hit@10 AR | Retrieval | Ranking | Context | Balanced | Identifier hit@10 |
  |---|---|---|---|---|---|---|---|---|
  | Gemini `gemini-embedding-2` (3,072) | **0.912** | 0.950 | 0.875 | 0.952 | 0.617 | 0.867 | **0.812** | 1.000 |
  | Voyage `voyage-4` (1,024) | 0.804 | 0.900 | 0.708 | 0.906 | 0.563 | 0.804 | 0.758 | 0.667 |
  | Jina `jina-embeddings-v5-text-small` (1,024) | 0.733 | 0.925 | 0.542 | 0.778 | 0.487 | 0.679 | 0.648 | 0.778 |

- **Decision:** Gemini `gemini-embedding-2`, default dimension 3,072, `taskType` RETRIEVAL_DOCUMENT / RETRIEVAL_QUERY.
  By rule D1 (mean hit@10 EN / AR; a gap under 5 points is a tie that goes to Jina): Gemini leads Voyage by 10.8
  points. It also leads every ADR-040 dimension (reported, not deciding) and closes most of the Arabic gap (AR hit@10
  0.875 vs 0.708), the plan's main quality risk.
- **Consequences / reported (not deciding):**
  - **Free-tier cap:** every text of a batch counts; ≈ 1,000-1,450 texts per day observed (exact cap UNCERTAIN). A full
    re-embedding of the corpus takes ≈ 2 days; at query time each question is one embedding call, so the free tier
    bounds the assistant to roughly a thousand questions a day. Moving to the paid tier is an owner decision.
  - **Data use:** Gemini's free tier may use inputs for training. Accepted for this corpus (public reports, no
    employee data; owner, D1). Never send non-public or personal data to the free tier.
  - The Qdrant `dense` vector has 3,072 dimensions (cosine); storage ≈ 26.6 MB for 2,163 float32 vectors.
  - Ranking stays the weakest dimension (nDCG@10 0.617) and context precision@8 ≈ 0.34 (EN): headroom for the Phase 7
    reranker and Phase 6 context shaping, judged by the ADR-040 rule.
  - Voyage limits confirmed by its 429 text: 3 RPM / 10K TPM without a payment method.
- **Amendment (2026-10-08, plan close, owner decision):** the bake-off vectors of every candidate (≈ 110 MB, the
  plan had called them "scratch") live in `Data/embeddings/bakeoff/` (git-ignored), not in `Notebooks/_scratch/`:
  `Embeddings.py` seeds from them, and `Retrieval.py`, `Lib_selftest.py` and `Search_index_benchmark.py` assert on them,
  so emptying `_scratch` would have made those scripts re-spend the free quota. Moved; the three scripts re-ran ✅ with
  `files changed: 0`.
- **Amendment (2026-10-09, data policy for every free API — embeddings, LLMs, reranker; owner decision, Agents plan
  §7 "Data policy"):** free tiers (Gemini / AI Studio, Groq, OpenRouter `:free`, Jina free) may receive **synthetic or
  public data only, minimized**: aggregates instead of rows where possible, made-up test records instead of rows of
  the company tables, no employee names or other personal data. Real company data goes to **paid tiers only**.
  Enforced in code: `pipelines/agents/llm.py` refuses a call whose `data_origin` is not "public" or "synthetic"
  (`FREE_TIER_DATA`), and the upload path already requires `GEMINI_TIER=paid` for non-public or personal documents
  (RAG plan Q5). OpenRouter privacy settings: free endpoints that may train stay allowed (synthetic data only),
  "publish prompts" stays off.
- **Amendment 2 (2026-10-14, owner decision) — supersedes the data-policy amendment above:** this is an educational
  project and every dataset in it is synthetic or public, so **no data guard**: the free APIs are used as if they
  were paid tiers. The `data_origin` refusal was removed from `pipelines/agents/llm.py` (the bake-off of ADR-045 ran
  with it; its cache keys never included it, so nothing re-runs). The upload approval gate (ADR-044, Q5) is opened by
  configuration, not code: `GEMINI_TIER=paid` in `.env` (its self-test still tests the refusal by removing the variable
  for that one check). Sending aggregates instead of rows stays a habit for token cost, not a rule. If real company data
  ever enters the project, this amendment must be revisited first.

## ADR-038 — Retrieval defaults: exact dense search + Jina reranker; no hybrid, no context shaping
- **Status:** Accepted (2026-10-08). RAG plan Phase 7, decided by the ADR-040 rule (fixed before the run);
  `pipelines/scripts/retrieval/Evaluation.py` → `Data/processed/rag/eval/results_2026-10-08.json`. Also records the
  search-index and cache decisions taken with the owner the same day.
- **Results** (64 golden queries through the real tool as the CEO; Gemini composed unit; balanced = mean of fact
  recall@10, nDCG@10, sufficiency@8, each EN / AR averaged):

  | Configuration | Balanced | Retrieval | Ranking | Context | Decision |
  |---|---|---|---|---|---|
  | dense (baseline) | 0.812 | 0.952 | 0.617 | 0.867 | — |
  | hybrid (dense + BM25, RRF) | 0.766 | 0.900 | 0.564 | 0.833 | rejected: −0.046; AR ranking −0.090 |
  | **dense + rerank** | **0.850** | 0.959 | **0.664** | **0.925** | **accepted: +0.037; worst drop AR ranking −0.019** |
  | hybrid + rerank | 0.839 | 0.958 | 0.662 | 0.896 | rejected: +0.027 < 0.03; AR context −0.042 |
  | dense + rerank + cap 2 per document | 0.602 | 0.720 | 0.449 | 0.637 | rejected: −0.247; AR context −0.375 |
  | dense + rerank + near-duplicate removal | 0.842 | 0.959 | 0.643 | 0.925 | rejected: −0.007; EN ranking −0.025 |

  RBAC leakage 0 in every configuration.
- **Decision:** `search_documents` defaults = exact dense search (`SearchParams(exact=True)`), 24 candidates reranked
  by Jina `jina-reranker-v3.5`, top k = 8; `hybrid=False`, `max_per_document=None`, `dedupe=False`. If the reranker
  hits its rate limit at query time, the dense order is returned (`request["reranked"] = False`), never an error.
  Search index: exact, not IVF / HNSW (owner rule "if IVF brings no gain, stay exact": `Search_index_benchmark.py`
  shows IVF either less accurate or slower; Qdrant exact 11.3 ms vs HNSW 19.1 ms, identical results). Query cache:
  in memory, persisted on disk (`QueryCache`; owner-suggested Redis benchmark: in-memory 0.2 µs, Redis 0.57 ms, the
  former per-call file read 1.7 ms growing to 589 ms after 1,000 questions); Redis is revisited only if the API phase
  runs several workers that must share a cache (ADR-018). gRPC and quantization: not used (owner).
- **Why hybrid loses here:** BM25 matches words, and an Egyptian Arabic question shares no words with the English
  corpus, so its BM25 list is noise that RRF mixes in (AR ranking −0.090). The `bm25` vectors stay in the collection
  (identifier lookups, a future English-only or bilingual corpus), off by default.
- **Why the per-document cap loses:** most answers come from one document (a USCG report, the Rotterdam report), and
  their facts are spread over several chunks of it; capping at 2 per document throws those chunks away (fact recall
  0.959 → 0.720). Near-duplicate removal is neutral on the facts (0.959 = 0.959, sufficiency equal) and slightly
  worse on ranking: the reranker already orders restated copies sensibly.
- **Consequences:** + ~0.6-1.5 s per question for the reranker (measured 590-1,480 ms; 30-60× the search) and a
  second external API (Jina) with its own unpublished per-minute limit (graceful fallback above). The reranker lowers
  identifier hit@10 1.000 → 0.889 (one of 9 identifier questions) and AR nDCG@10 0.597 → 0.578 (within the 0.02
  allowance) while raising EN nDCG@10 0.637 → 0.751 and sufficiency@8 EN 0.900 → 0.975, AR 0.833 → 0.875. The
  numbers are the baseline that the agents phase must not regress.
- **Amendment (2026-10-08, plan close, owner decision "keep as is"):** the `bm25` sparse vector **stays stored** in
  `nilegate_docs` although no default search uses it. It is cheap (sparse, server-built), keeps `hybrid=True`
  available without a reload, is exercised by `Retrieval.py` (RBAC matrix dense + hybrid, Phase 6 smoke test), and is
  the candidate for identifier questions in the agents phase (the reranker lowered identifier hit@10 to 0.889, above).
  Likewise the collection's HNSW index exists but every search sets `exact=True`.

## ADR-039 — Shared retrieval library `pipelines/lib/`; Qdrant point identity per document version
- **Status:** Accepted (2026-10-02, owner answers D11 of the RAG plan and the point-id question). Amends ADR-036 ("no
  shared `.py` modules yet") for the retrieval pipelines, and ADR-009 (payload gains `text_sha256`). Numbered 039
  because 037 / 038 are reserved by the RAG plan for the embedding model and the retrieval defaults.
- **Context:** Phases 2, 4, 5, 6 and 8 need the same embedding client, chunk-schema check and Qdrant writing code;
  copies would drift. Qdrant detects no change by itself (it stores what the loader sends), and ADR-035 makes a
  changed file a new version `<slug>_v2` without saying what happens to the old version's points: with point id =
  UUID5(`chunk_id`), a version with fewer or renamed chunks would leave stale points that retrieval could return.
- **Decision:**
  - `pipelines/lib/` (imported after putting the project root on `sys.path`): `common` (root, `.env`, redaction),
    `chunks` (the 16-column contract), `embeddings` (per-provider budgets, retries incl. Gemini's `retryDelay`, stop
    on a wait > 15 min, resumable cache keyed by id + text SHA-256), `qdrant_store` (collection spec, point identity,
    version-safe upsert, verification). Verified by `pipelines/scripts/retrieval/Lib_selftest.py` (no API call; a
    throwaway Qdrant collection).
  - Point id = UUID5(`document_id` + "/" + `chunk_id`) in a project namespace: a reload overwrites (never
    duplicates); each version has its own points.
  - `upsert_document` writes the new points first, then deletes every point of that document (and of the versions
    it supersedes) not in the new set: no stale chunk survives and no moment returns zero results for it.
    `verify_document` asserts exactly the expected ids per document.
  - Payload = the 16 chunk columns + `document_id` + `text_sha256` (lets the loader see a changed text in Qdrant).
  - BM25 is built by the server (`cloud_inference=True`; probe and self-test verified the stored sparse vector).
  - Change routing: new file / new fingerprint → new version (ADR-035) → re-chunk → embed only changed texts →
    upsert + stale cleanup; payload-only correction (e.g. a level) → payload update, no re-embedding; employee role /
    department change → nothing in Qdrant (read from PostgreSQL at query time).
- **Consequences:** `Embedding_bakeoff.py` now imports the client (refactor verified: Jina 0.754 and Voyage 0.825
  recomputed from the cache with 0 API calls, identical). The Phase 5 loader and the Phase 8 ingestion script use
  `qdrant_store` and never write Qdrant another way.
- **Amendment (2026-10-08, derived filter fields):** the payload also carries `unit_kind` (one vocabulary of 12
  kinds mapped from the 23 source-specific `unit_type` names in `qdrant_store.UNIT_KIND`, e.g. USCG "paragraphs" and
  the other sources' "paragraph" are both `paragraph`; an unmapped unit_type stops the load) and `year` (the first four
  digits of `version_date`, which mixes "2025" and "2024-04-06"; null when absent), both indexed. The chunk files are
  unchanged. Measured with oracle filters (dense, exact): `document_type` +0.004 balanced, `document_id` +0.024
  (AR hit@10 0.875 → 0.917): metadata filters mainly scope a question (kind, year, source) and pay off for accuracy
  when a question names one document (entity resolution → `document_id`, agents phase).

## ADR-040 — Retrieval evaluation at three levels: retrieval, ranking, context
- **Status:** Accepted (2026-10-02, owner: "balance retrieval quality, ranking quality and context quality; do it the
  right way for our data"). Fixes the deciding rule of RAG plan Phase 7 (→ ADR-038) **before** Phase 7 runs.
- **Context:** The golden set labels 1-3 equivalent chunks per question; hit@k only says whether ONE was found.
  Measured on the bake-off cache: q22 (three incidents) counted as found with two of them; only 13-15 % of the top-10
  chunks were labelled, so the rest could not be judged; near-duplicate restated recommendations took slots.
- **Decision:**
  - **Golden facts** (`pipelines/scripts/retrieval/Golden_facts.py` → `Data/processed/rag/eval/golden_facts.jsonl`,
    a separate file: the frozen golden set is untouched): 1-4 facts per English question (80), each a claim = groups
    of regex alternatives that must all match one chunk (a USCG fact is vessel AND claim, because every chunk of a
    report carries the vessel name). Validated: every fact stated by an expected chunk, the expected chunks together
    state all facts, every expected chunk states >= 1 fact, no fact stated by more than 40 chunks (broadest: 12).
    Arabic twins use their English question's facts (English corpus). Frozen by hash after the owner's review.
  - **Metrics** (`pipelines/lib/evaluation.py`): retrieval = fact recall@10 (diagnostics hit@10, complete@10);
    ranking = nDCG@10 with relevance = states >= 1 fact or is an expected id, ideal from the corpus-wide relevant set
    (diagnostics MRR, hit@1, hit@5); context = sufficiency@8, all facts in the 8 chunks `search_documents` returns
    (diagnostics precision@8, redundancy@8 = relevant chunks adding no new fact, facts per 1,000 chars). Each primary is
    the mean of its English and Arabic values; **balanced score** = mean of the three primaries.
  - **The embedding choice keeps D1** (fixed before any result): the dimensions are reported in ADR-037, never
    deciding. Changing the rule after seeing that Jina gets q22 complete and Voyage not would shape it on known results.
  - **Phase 7 rule (fixed now):** a configuration (hybrid, reranker, context shaping) replaces the baseline (dense
    only, top-8, chosen model) only if the balanced score rises by >= 0.03 AND no primary falls by more than 0.02 in
    either language AND RBAC leakage is 0. Latency (p50 / p95) is reported. A tie keeps the simpler configuration.
- **Consequences:** first reading (cache, dense only, `text`): Jina balanced 0.672 (retrieval 0.803, ranking 0.514,
  context 0.700), Voyage 0.756 (0.906 / 0.558 / 0.804). Ranking is the weakest dimension for both (relevant chunks are
  found but not near the top) and context precision@8 is ~0.33 in English with redundancy@8 ~0.40: the measured
  headroom for the Phase 7 reranker and for context shaping (near-duplicate removal). Arabic trails English in every
  dimension. Four queries per model were hit@10 successes whose 8-chunk context misses a fact.

## ADR-041 — One title / text rule for the whole corpus
- **Status:** Accepted (2026-10-02, owner: "the whole corpus on one scheme; `title` is a feature separate from
  `text`"). Supersedes the "header in every chunk's text" parts of ADR-024 (USCG) and ADR-023 (IMO document path
  repeated in each part); the header / path content is kept, in `title`.
- **Context:** Each source had made its own choice: every USCG chunk (1,544) started with a composed header line, 59
  IMO annex chunks with the document path, FBL clauses with "N. <title>", HbR tables / figures / milestones / boxes and
  LPI figures with their caption or heading, 10 LPI sections with a heading run into the first sentence; the rest
  (461) had the body only. A model, BM25 and an embedding therefore saw the location label for some chunks and not
  for others, and the bake-off's `title + text` variant duplicated it for USCG.
- **Decision:**
  - `title` = the chunk's full location label (document, section path, caption, clause number); `text` = the body
    only, never starting with its heading. The unit embedded, indexed (BM25), judged (golden facts) and handed to a
    model is `compose(title, text)` = title + newline + text, built only by `pipelines/lib/chunks.py`.
  - `split_heading` (one function): a leading composed header line (USCG, IMO annex) or a first line equal to the
    title plus at most a label / number ("Table:", "17.") moves to `title`; a "<title>. " run-in heading is removed;
    anything else is content and stays (prose such as "Road infrastructure plays …" under the title "Road").
    Lossless (old text = new title + newline or ". " + new text, up to whitespace) and idempotent, both asserted.
  - Applied in the **owning** chunking scripts as an appended last phase (`tools/nb_to_script.py` APPENDED, proven by
    `check`: notebook + patches + exactly this phase), after their own validations and coverage audits, which keep
    validating the chunking itself. Chunk boundaries, ids, order and the count (2,163) are unchanged: the frozen golden
    set, the golden facts and `documents.chunk_count` stay valid; no migration.
  - Contract (`pipelines/lib/chunks.check`): no chunk keeps a heading in `text`; `text` non-empty and <= 2,000
    characters; the composed unit >= 50 characters (5 USCG bodies are short once the header moved, e.g.
    "Administrative Recommendation: None.", kept with their title, owner decision).
- **Consequences:** 1,702 chunks normalized (1,603 header lines, 89 heading lines, 10 run-in headings), 461 unchanged.
  For 1,683 of them the composed unit equals the former text exactly, so their cached embeddings stay valid (the cache
  is keyed by text SHA-256). The bake-off embeds the composed unit (stage 1) and tests the body alone (stage 2, D5);
  `qdrant_store` builds BM25 from the composed unit (vessel names and MISLE numbers are in `title`).

## ADR-042 — Inference-time uploads: one company document shape, a validator, and layered injection screening
- **Status:** Accepted (2026-10-08, owner answers D12-D17 and Q1-Q8 of the RAG plan, Phase 8). Spec for people:
  `docs/templates/NileGate_document_v1.md`; code `pipelines/lib/uploads.py`, `upload_reader.py`, `screening.py`.
- **Context:** an employee may upload a document while talking to the assistant. A generic parser for any layout
  needed per-source rules and a human review gate for the 7 corpus sources; an inference-time path cannot hold a
  review gate. Uploaded text is untrusted (project rule 5) and may carry prompt injection, hidden text or active
  content.
- **Decision:**
  - **One fixed shape, "NileGate Document v1" (D15):** PDF or DOCX (Q6) with a text layer; a `key: value` metadata
    block between `NILEGATE-DOC v1` and `END-METADATA` (9 required fields, closed vocabularies, `document_code`
    `NG-<DEPT>-<TYPE>-<NNNN>` consistent with department and type); numbered bold / Heading-style sections, `1. Purpose`
    and `2. Scope` required, depth <= 3, no gaps; a footer `NileGate · <code> · page N of M · level L` equal to the
    block. Limits (Q7): 5 MB, 30 pages, 60,000 body characters, DOCX <= 25 MB uncompressed. One section = one logical
    unit, split at paragraph then sentence boundaries above 2,000 characters; corpus chunk contract and title / text
    rule (ADR-041), `unit_type` `section` (unit_kind `paragraph`). Because the shape is fixed, parsing is exact and the
    same document as PDF or DOCX gives the same chunks (measured).
  - **The uploader's access bounds the label (D13, ADR-006):** a document whose (level, department) the uploader
    could not see is refused (`E_LEVEL_ABOVE_UPLOADER`).
  - **Reading in a child process** (`python -m pipelines.lib.upload_reader`, 30 s timeout): a hanging or crashing
    parser takes only the child down. DOCX XML through `defusedxml`.
  - **Screening in four layers:** (1) file level — PDF `/JavaScript /JS /Launch /EmbeddedFiles /RichMedia /XFA /AcroForm
    /AA /SubmitForm /GoToR`, non-https links, form fields; DOCX macros, embedded / OLE objects, ActiveX, external
    relationships (remote templates), `altChunk`, DDE / INCLUDE fields; zip-bomb guard; encryption → the whole file is
    refused; (2) hidden text — PDF render mode 3 / opacity 0, < 4 pt, white, off-page; DOCX `vanish`, hidden styles,
    white, < 4 pt; comments and deleted tracked changes are never read; (3) visible text — NFKC, invisible / bidi /
    tag characters removed (more than 3 refuse the file), patterns in English, MSA and Egyptian Arabic for override,
    role change, role markers, prompt reveal, exfiltration URLs, tool calls, markdown beacons, base64 blobs, plus a
    whitespace-free form for the strongest phrases (a PDF turns zero-width characters into spaces); (4) handling —
    every upload result is labelled `trust="untrusted_upload"` and the agents phase must quote it as data, never
    follow it (the guarantee does not rest on detection).
  - **Q8:** a section with hidden text or a pattern hit is **removed and reported**, the rest is accepted; a hit in a
    required part (metadata block, footer, header) refuses; nothing left → refused.
- **Validation** (`Upload_validation.py`, 52 fixtures from `Upload_fixtures.py`): every case gets exactly its expected
  verdict (8 clean accepted with nothing removed; 13 visible-text attacks, 11 hidden-text, 9 file-level, 11 shape
  errors); **0 false positives on the 2,163 corpus chunks**; PDF / DOCX parity 3/3; reader timeout and crash refused;
  validation p95 ≈ 0.26 s.
- **Consequences:** + exact parsing, one clear message per problem, no review gate needed for a conversation upload.
  − documents not made from the template are refused (by design); the patterns catch known shapes only (layer 4 is
  the real guarantee); scanned documents are not accepted at inference time.

## ADR-043 — Conversation uploads: memory-only session store, a local ONNX embedding lane, two labelled lists
- **Status:** Accepted (2026-10-08). The local model is **`BAAI/bge-m3`**, chosen by the rule fixed before any run
  (measured after the project moved to `D:\Project`, which freed the disk space it needed); floor 0.45 and DirectML
  deferred by owner decision (below). `pipelines/lib/session_store.py`,
  `local_embeddings.py`, `retrieval.py` (`session=`); measured by `Upload_eval.py` →
  `Data/processed/rag/eval/uploads/upload_eval_2026-10-08.json`.
- **Decision:**
  - **Storage (D12, D14):** an accepted upload lives only in process memory (`SessionStore`): rows + vectors, owned by
    one employee, gone at session close or after 8 h; at most 5 documents / 300 chunks (Q7). Nothing is written to
    disk, Qdrant, PostgreSQL or the query cache (asserted: `Data/` tree and Qdrant count unchanged). The original bytes
    are kept in memory only for a manager (a promotion needs them). Redis with a TTL is the multi-worker form later
    (ADR-018).
  - **Embedding (D16, ADR-037, Q1):** every session upload is embedded **locally with ONNX Runtime** — no upload text
    leaves the machine, no Gemini quota is spent, one vector space and one floor. Models are exported once by
    `tools/export_onnx.py` (fp32 + weight-only int8 / int4, MatMulNBits; checked against PyTorch, min cosine fp32
    1.0). Measured (32 chunks of 4 documents, 30 English + 30 Egyptian Arabic questions; rule: hit@3 >= 0.85 EN and
    >= 0.75 AR):

    | Model | hit@3 EN | hit@3 AR | AR on the Arabic document | 32 chunks (CPU) |
    |---|---|---|---|---|
    | `mesolitica/llama2-embedding-600m-8k` (owner's pick; Malay-trained, Llama-2 tokenizer) | 0.767 | 0.167 | 0.833 | 10-17 s |
    | `intfloat/multilingual-e5-base` | 0.933 | 0.500 | 1.000 | 1.4-1.9 s |
    | **`BAAI/bge-m3`** (1,024 d, CLS pooling, MIT) | **1.000** | **1.000** (MRR 0.95) | 1.000 | 4.6-6.8 s |

    Only bge-m3 meets the rule (the owner's model misses both thresholds, e5-base the Arabic one): it is the
    session-lane model. The owner's model also loses dynamic int8 quantization (min cosine 0.809: Llama activation
    outliers), which weight-only int8 fixes (0.99998); bge-m3 weight-only int8 0.99975, int4 0.952 (same hit@3).
  - **Runtime settings (measured, i7-9750H):** fp32 (weight-only int8 / int4 are smaller but slower on this CPU),
    6 threads = the physical cores (12 logical threads were 5 % faster on a quiet machine but 30 % slower on a busy
    one), batch 8; upload of a 3-page PDF ≈ 3-4 s end to end, session lane ≈ 62-82 ms per question.
    DirectML on the GTX 1660 Ti (throwaway venv): bge-m3 embeds the 32 chunks in 1.1 s vs 6.8 s on the CPU,
    identical vectors, but a single question 107 ms vs 60 ms; adopting it means replacing `onnxruntime` with
    `onnxruntime-directml` project-wide (RapidOCR too): deferred (below).
  - **Merge (D17, Q4 "least problems"):** `search_documents(..., session=)` returns the corpus `results` exactly as
    before plus `session_results` (at most 3, above the model's floor, `trust="untrusted_upload"`, `lane="session"`).
    The corpus query is the employee's question only (Q2: never expanded with upload text). **Baseline preserved by
    construction and measured:** with a session holding all 4 documents, the 64 golden questions return identical
    corpus results; balanced dense 0.812 = baseline, dense + rerank 0.8495 = baseline (ADR-038), 0 Gemini calls.
  - **Floor (M2): 0.45 for bge-m3 — owner decision (2026-10-08) after the first full run.** The rule fixed before the
    run (keep upload chunks out of >= 95 % of golden corpus questions) gave 0.52: hit@3 EN 0.967 / AR 0.733, the
    Arabic one under its threshold. The owner moved the rule to >= 80 % keep-out → 0.45: hit@3 EN 1.000 / AR 0.900,
    9 of 64 golden questions (14.1 %) also get upload chunks. Why: the session list is separate and labelled, so an
    extra off-topic upload chunk costs little, while a hidden relevant one costs the employee their own document.
    Other points measured: 0.38 → 1.000 / 0.967 with 45.3 %; none → 1.000 / 1.000. The floor is computed from the
    ranked scores (an interpolated quantile let one question too many through: fixed), and `Upload_eval.py` asserts
    that the chosen model still meets the thresholds with its floor.
  - **DirectML: deferred (owner decision 2026-10-08)** to the API / deployment phase: it would replace `onnxruntime`
    for the whole project (RapidOCR included), and ≈ 3 s per small upload on the CPU is acceptable for now.
  - **Access (D13):** a session belongs to one employee (search, upload, get by anyone else → `PermissionError`);
    expiry / close empties it; every session result is re-checked with `allowed()` (ADR-006). Isolation 15/15.
- **Consequences:** + uploads never touch the shared corpus, the baseline cannot move, private text stays local.
  − bge-m3 is a 2.2 GB model (≈ 3 s per small upload on the CPU; DirectML would cut it 6×); two vector spaces mean no
  joint ranking of upload and corpus chunks (by design: two lists).
- **Amendment (2026-10-08, plan close, owner decisions):** (1) the two rejected candidates (`llama2-embedding-600m-8k`,
  `multilingual-e5-base`, 6.4 GB) are removed from `models/onnx/`; `Upload_eval.py` measures every model that is
  present and reuses the recorded rows of the reviewed `upload_eval_2026-10-08.json` (labelled `recorded`, printed with
  ⚠️) for a candidate that is not, so the choice table stays complete. (2) Precision rule: a smaller variant replaces
  fp32 only if its hit@3 stays within 0.02 **and** it is at least 20 % faster (`MIN_SPEEDUP`); the first re-run at the
  close picked int4 for being 33 ms (0.5 %) faster — timing noise (±20 % on this laptop) must not decide. fp32 stays.

## ADR-044 — Promotion of a manager's upload to the corpus
- **Status:** Accepted (2026-10-08, D12, D14, Q3, Q5, Q8). `session_store.request_promotion`,
  `pipelines/scripts/retrieval/Upload_promotion.py`.
- **Decision:** only a **manager**, for a document of **their own department**, on an explicit request, and only if
  screening removed nothing; then (and only then) the original file is persisted to `Data/incoming/promotion/<id>/`
  (git-ignored) with `request.json`. The owner reviews offline (`--review`: SHA-256, re-validation with the
  requester's *current* role, corpus contract, near-duplicates against the corpus, `review.md`), approves
  (`--approve`: staged chunk file, registry row, migration draft) or rejects. **Data policy (Q5, ADR-037):**
  approval requires `data_origin: public` and `personal_data: no`, unless `.env` declares `GEMINI_TIER=paid`.
  `--commit` registers the document like its siblings — same contract, model (Gemini), payload, collection and
  `documents` table (generated migration, applied by the owner) — after the owner has copied the raw file into
  `Data/raw/unstructured/company/` (checked by SHA-256); its files live in `Data/processed/rag/promoted/` so the
  corpus scripts' reviewed counts (2,163) stay valid; then upsert (`qdrant_store`, ADR-039), verification and a
  retrieval + RBAC check. Nothing is automatic.
- **Validation:** `Upload_promotion.py --selftest` 11/11 — employee, other department and screened document refused;
  internal document reviewed but approval refused by the data policy; a public document committed to a throwaway
  collection (8 points), found by its manager, invisible to a Finance employee (level 2), re-commit idempotent
  (0 chunk embeddings), `nilegate_docs` untouched (2,163).
- **Amendment (2026-10-08, plan close):** the generated migration also fills `documents.ingested_at` with the time
  `--commit` verified the points in Qdrant (the corpus got the same column through migration 011). It is written once,
  after the verification, and a re-commit leaves it unchanged (a migration is never edited; it may be applied
  already). Self-test 12/12 (new check: `migration_has_ingested_at`).

## ADR-045 — LLM per agent role on free APIs (bake-off)
- **Status:** **Accepted** (2026-10-12, owner) on a best-case bound: 6 of 9 candidates complete; the two incomplete
  ones miss only T4 items (`gemini-3.8-flash` 4, `laguna-s-2.1:free` 1). Scoring every missing item as perfect gives
  at most Writer 0.708 / Tools 0.938 (3.8 Flash; its T2 coverage 0.5 is final) and Writer 0.806 / Tools 0.875
  (laguna), below the tie threshold (> 0.897 Writer, > 1.000 Tools), so no remaining result can change the
  selection. The 5 items still run once (2026-10-13) for the record. Results file `llm_bakeoff_2026-10-12.json`.
  (Was PROPOSED 2026-10-11; gemma's LITE finished after 15 runs: it ties the writer leaders but loses the tie-break
  on packs per day.)
- **Context:** Agents plan D1 (free APIs only, main + fallback per role) and §7a; rules fixed before any call (owner,
  2026-10-10). `pipelines/scripts/agents/LLM_bakeoff.py`, frozen tasks `Data/processed/agents/eval/bakeoff_tasks.json`
  (sha256 `ed6723f5…`: T1 20 tool-calling questions, T2 10 weekly KPI tables, T3 10 invoice-exception tables, T4 the
  40 English golden questions with frozen top-8 passages; OpenRouter, `gemini-3.8-flash` and `gemma-4-31b-it` run
  the stratified LITE subset 8 / 4 / 4 / 8), results `llm_bakeoff_2026-10-12.json`. Deterministic scoring, no LLM
  judge.
- **Rule:** Writer / Insight = only models whose every T2 summary writes no number outside its table (strict: k / M
  and fewer decimals are the only rounding), score = mean(T2 driver coverage, T4 fact recall, T4 citation validity);
  Tools = mean(T1 accuracy, T3 validity × exactness with the model's best method); scores on LITE for every model; a
  gap < 5 points is a tie → packs per day (daily request limit ÷ requests per simulated pack) → TPM minutes →
  latency; main and fallback from different providers.
- **Results (LITE):**

  | Model | Writer / Insight | T2 gate | Tools | T4 recall / citation | Packs / day (writer) | Median latency (writer) |
  |---|---|---|---|---|---|---|
  | Groq `qwen/qwen3.8-27b` | 0.826 | pass | 0.938 | 0.479 / 1.000 | 111 | 0.7 s |
  | Gemini `gemini-3.5-flash-lite` | 0.833 | pass | **1.000** | 0.625 / 0.875 | ≥ 13 (limit not published) | 1.1 s |
  | Groq `openai/gpt-oss-20b` | 0.833 | pass | 0.938 | 0.500 / 1.000 | 111 | 1.5 s |
  | OpenRouter `nvidia/nemotron-3-super-120b-a12b:free` | 0.847 | pass | 0.938 | 0.667 / 1.000 | 5.6 | 11.8 s |
  | Groq `openai/gpt-oss-120b` | 0.653 | **fail** | 0.875 | 0.333 / 0.625 | — | 1.9 s |
  | Gemini `gemma-4-31b-it` (LITE) | 0.847 | pass | 0.938 | **0.792** / 1.000 | ≥ 8.9 | **76.7 s** |
  | Gemini `gemini-3.8-flash` (LITE, 20 / 24) | ≤ 0.708 | pass | 0.938 | 0.500 / 0.750 (4 of 8) | 2.2 | — |
  | OpenRouter `poolside/laguna-s-2.1:free` (LITE, 23 / 24) | ≤ 0.806 | pass | 0.875 | 0.762 / 0.571 (7 of 8) | 5.6 | — |
  | OpenRouter `thinkingmachines/inkling:free` | unavailable (403: "only available on agentic harnesses") | | | | | |

  Full sets (Gemini / Groq): `qwen3.8-27b` T1 0.95, T4 recall 0.594, citation 1.000; `gemini-3.5-flash-lite` T1
  1.00, T4 recall 0.457, citation 0.925; every model had 100 % T3 validity with at least one method.
- **Decision:** **Writer / Insight:** main Groq `qwen/qwen3.8-27b`, fallback Gemini
  `gemini-3.5-flash-lite` (the four gated models tie within 2.1 points; Groq's 1,000 requests / day per model gives
  the most packs per day, then the fewest tokens per pack). **Tools / routing:** main Gemini `gemini-3.5-flash-lite`
  (1.000, the only model with every T1 item right on LITE), fallback Groq `openai/gpt-oss-20b`. Structured output
  method per model = its best T3 method (`function_calling` for qwen and flash-lite; `json_schema` / `json_mode` for
  the gpt-oss models, whose `function_calling` validity was 0.75).
- **Consequences / reported (not deciding):**
  - The binding free limit is **requests per day**: `gemini-3.8-flash` allows 20 (it cannot serve one weekly pack),
    OpenRouter 50 across all free models (≈ 5 writer packs), Groq 1,000 per model. Groq's 8K TPM and its output-
    tokens-per-minute limit slow long reasoning outputs (a per-minute 429 waits a full minute before its one retry).
  - Strict T2 caught real errors in the largest model (`gpt-oss-120b`: `849.9 k` for −849,964, "13 categories"):
    model size is no guarantee of number fidelity; the Phase 6 Validator stays a hard gate.
  - gpt-oss writes `【n†…】` citations unless trained away; accepted as citations, logged as `t4_format_ok`.
  - Gemini's free tier showed 5xx bursts ("high demand"), stopping a model for the run only; free endpoints are not
    an availability guarantee, hence a fallback from another provider for every role. `gemma-4-31b-it` answered in
    5–74 s (median ≈ 35 s) with intermittent 500s → LITE only; a 5xx on the same request in two separate runs (each
    after its retry) is cached as a failure (`server_error_repeated`), so a flaky model is scored, not waited for.
  - Data policy: every bake-off call went through `FREE_TIER_DATA` (synthetic aggregates, made-up invoices, public
    passages; ADR-037 amendment); the guard was removed afterwards by ADR-037 amendment 2 (2026-10-14).
  - Upgrade path (paid tier): `gemma-4-31b-it` had the best T4 fact recall (0.792) and passed the T2 gate, but its free
    tier is too slow (writer median 76.7 s) and flaky; re-test it as a Writer candidate if the project moves to paid.
- **Amendment 1 (2026-10-19, owner; Agents plan Phase 5 S6, decision P5-8):** the weekly pack's real prompts (skills
  + evidence digests + tool results + output schema) measured 9.7K–17K tokens per Insight / Writer call; Groq's free
  8K tokens per minute refuse such a request outright ("Request too large"), so `qwen/qwen3.8-27b` could not serve
  the pack and every call fell back. The tie-break that chose qwen (packs per day) was measured on the bake-off's
  small prompts. **For the pack's Insight and Writer roles:** main `gemini-3.5-flash-lite` (tied with qwen on the
  Writer score, 0.833 vs 0.826; 250K TPM), fallback OpenRouter `nvidia/nemotron-3-super-120b-a12b:free` (Writer
  0.847, T2 gate passed, ~1M TPM, 50 requests / day; `function_calling`). Tools / routing unchanged. The token gate
  becomes "every call within its provider's per-minute token limit" (`llm.PROVIDERS`), reported per pack. A request
  over the limit is now a deterministic, cached failure in `llm.py` (`too_large`), so the role falls back at once.
  Measured after the change (weeks 5 / 10 / 23 / 49): 0 fallbacks, max 17.0K tokens per call, all within limits.

## ADR-046 — Synthetic finance data for the Weekly Finance Pack; `invoices.status` is a label
- **Status:** Accepted (2026-10-13 rules approved, 2026-10-14 migration 012 applied and verified). Agents plan §4a
  R1–R10 (D6, amended). `pipelines/scripts/synthetic/Finance_generator.py`, `db/migrations/012_finance_data.sql`.
- **Context:** the finance KPIs (AR aging, DSO, collections, customers, budget variance) need customers, terms,
  payments and a budget, which did not exist. The stored `invoices.status` turned out to be a random label (689 of
  1,000 not Paid, evenly over the four quarters): payments consistent with it would have shown DSO ≈ 250 days.
- **Decision:** (1) **Payments follow terms and behaviour**; `invoices.status` is kept unchanged (ADR-013, no
  regeneration) and documented by a COMMENT as the original label, not the payment state — every finance view derives
  the status from the dates (as-of logic). (2) 40 invented customers in 6 segments, `vessels.customer_id` NOT NULL by
  Zipf weights inside each segment; terms 30 / 45 / 60 and a credit rating are stored, the **behaviour class is not**
  (manifest only: evaluation ground truth). (3) One full payment per paid invoice, horizon 2026-03-31; the due date is
  derived, not stored. (4) Weekly budget = a planning model independent of the invoices (fleet × 2.0 transits ×
  median-tonnage laden toll, seasonal ±6 %). (5) Evaluation copy in schema `finance_test` (4 golden weeks, 5 planted
  invoice errors, 1 budget miss, week 49 clean) **without a label column**; the answer key is
  `Data/processed/agents/eval/finance_test_answer_key.json`. (6) Names and draws from `numpy.default_rng([42,
  phase])`, identical on every OS (not Faker). All new tables level 2 / Finance.
- **Results:** top-10 customers 57.0 % of 2025 billing; DSO 55 days; 150 invoices (40.2 M SDR) open at 2025-12-31,
  6 unpaid at the horizon; paid on or before due 36 % (owner kept); budget 302.1 M vs actual 267.9 M (−11.3 %,
  explained by the laden assumption); label vs derived agree on 379 / 1,000. `verify_readonly.sql` §17 =
  40 | 500 | 994 | 0 | 0 | 0 | 676 | 88 | 52, §14 / §15 clean (`db/audit/2026-10-14_after_012_report.txt`); a second
  generator run with another hash seed changed 0 files.

## ADR-047 — Schema `finance`: plain star / KPI views, one definition per metric
- **Status:** Accepted (2026-10-14). Agents plan Phase 2, owner decisions P2-1…P2-9; `db/migrations/013_finance_views.sql`,
  `docs/finance_metrics.md`, `pipelines/scripts/finance/Finance_views_check.py`. Takes up ADR-018's star-schema
  trigger (Power BI phase) in its preferred shape.
- **Context:** the Weekly Finance Pack needs the same numbers in Power BI (DirectQuery: complex DAX is limited) and in
  the agent tools (the Validator compares deck numbers exactly). Receivables "as of" a week must come from dates
  (ADR-046), and the data has no history before 2025-01-01.
- **Decision:** (1) Schema `finance` = 12 plain views (dims `dim_date`, `dim_week`, `dim_customer`, `dim_vessel`,
  `dim_toll_band`; facts `fact_invoice` with the derived due date, `fact_payment`, `fact_ar_snapshot` = open invoice ×
  week; KPI views `kpi_weekly`, `kpi_weekly_category`, `kpi_customer_13w`, `kpi_overdue_list`), no materialized views,
  no copies, **no SQL functions** — one row per `report_week`, the tools filter by week. (2) Metrics computed only in
  SQL; DAX stays sums / selections. (3) `report_week` = strict ISO weeks of 2025, as of Sunday 23:59; 2025-12-29…31
  are ISO 2026-W01, outside the 52 weeks. (4) DSO = AR ÷ billed in the last 91 days × 91; weeks 1–13 use the available
  window from 2025-01-01 with `is_warmup = true` (count-back deferred). (5) Customers ranked on the trailing 13 weeks.
  (6) Rounding once at the end: money 2 decimals, percent 2, days 1. (7) RBAC stays the tool predicate (ADR-006 /
  ADR-034): `finance.*` is level 2 / Finance, proved by a matrix over every employee with `retrieval.allowed()`; per
  ADR-006 non-Finance managers may read it. (8) Group role `finance_bi` (NOLOGIN, read-only, SELECT on `finance`
  only) for Power BI; views run with their owner's rights, so it needs nothing in `public`; its login is created in
  Phase 3 from `.env`. (9) No `finance_test` views now (Auditor tool, Phase 4 / 7).
- **Consequences:** every KPI view equals an independent pandas reference on all 52 weeks; weeks 5 / 16 / 23 / 49
  frozen as reviewed hand values (DSO 31.0 / 51.7 / 62.2 / 53.6 days); AR roll-forward, aging = AR and Σ categories =
  total hold; RBAC leakage 0 (72 role-`employee` users outside Finance denied); `finance_bi` reads 12 / 12 views and
  0 / 15 tables outside `finance`. A new metric = a new column or view in a new migration plus a definition in
  `docs/finance_metrics.md`.
- **Amendment (2026-10-14, Phase 3, owner P3-4):** a 13th view `kpi_weekly_trend` (migration 014) gives each report
  week its 13 trend rows, so Power BI's single week slicer drives the trend chart with no DAX (rejected: a
  disconnected slicer table with DAX measures; a 52-week chart that ignores the slicer).

## ADR-048 — Power BI semantic model and report: DirectQuery, thin DAX, one week slicer
- **Status:** Accepted (2026-10-15). Agents plan Phase 3, owner decisions P3-1…P3-14; `powerbi/NileGate_Finance.pbip`
  (TMDL model + PBIR report), `db/create_finance_bi_user.ps1`, `db/check_finance_bi_user.py`. Implements D5 and builds
  on ADR-047 (KPIs only in SQL), ADR-034 (read-only role), ADR-006.
- **Context:** the finance team needs a dashboard whose numbers equal the PowerPoint pack (the Validator compares
  numbers exactly), with no paid Power BI Service account, no gateway and no copy of the data; the model must be
  reviewable in git.
- **Decision:** (1) **Power BI Desktop + PBIP** (TMDL / PBIR in `powerbi/`; `.pbi/localSettings.json`, `cache.abf`
  and `*.pbix` git-ignored); the model is edited through the official **Power BI Modeling MCP**
  (`@microsoft/powerbi-modeling-mcp@1.0.0`, pinned in `.mcp.json`), report pages in Desktop. (2) **DirectQuery** on
  the 12 `finance` views used (all but `dim_date`) through the login `ports_bi` (member of `finance_bi` only,
  `default_transaction_read_only`, password in `.env`). (3) **One week dimension** `Week` (`dim_week`) filters every
  table: 18 many-to-one, single-direction relationships named `<from> -> <to>`; **Assume referential integrity off**
  (an INNER JOIN would drop the 4 invoices of 2026-W01 and the 152 payments paid in 2026); no `Vessel -> Customer`
  path (ambiguity). (4) **Thin DAX, three patterns only:** week-grain KPIs = `SELECTEDVALUE` of the `kpi_weekly`
  column (blank over several weeks; percent ÷ 100); semi-additive tables (AR Snapshot, Overdue List, Customer KPIs 13w,
  Weekly Trend) guarded by `HASONEVALUE(Week[report_week])`; additive facts (Invoices, Payments) plain `SUM` — 38
  measures in `Weekly KPIs`, folders per page; one calculated column (`customer_group`, a display label of
  `is_top10`). (5) Every column `summarizeBy = None`; keys / technical / measured columns hidden; friendly table
  names, the source view in each description. (6) Report: 5 pages (Overview, Revenue, Receivables, Customers,
  Exceptions = placeholder until the Auditor tool, P3-11) with one **single-select week slicer synced on all pages**
  (filter "is not (Blank)"); money `#,0.00` (the new Card visual abbreviates itself); where a visual sum of rounded
  SQL values would differ from the SQL KPI (customer shares), the visual shows the KPI and hides the total.
  (7) Visuals are built on screen with the owner (computer use, explained per visual), not generated.
- **Consequences:** every number of pages 1–4 equals `finance.kpi_weekly` read straight from PostgreSQL for weeks
  5 / 23 / 49 (and the revenue / AR / customer breakdowns each sum to the week's KPI); the dashboard is current when
  opened (no refresh) but **needs the database running** (an error otherwise — the containers restart with Docker,
  P3-12); MCP edits reach disk only after Desktop's Save (clear the "refresh manually" banner first). Upgrade path
  (D5): a work / school account → Power BI Service as an adapter; Import mode stays a fallback. Rejected: DAX KPI
  logic (would fork the definitions); a disconnected slicer table; a `.pbix` in git.

## ADR-049 — Stage 1 agent tools: one contract, the user and the dataset from the run context, SQL audit views
- **Status:** Accepted (2026-10-18, owner decisions P4-1…P4-8, Agents plan §5a); migration 015 applied by the owner
  (2026-10-19; `verify_readonly.sql` §19 as expected, `db/audit/2026-10-19_after_015_report.txt`), `Tools_check.py`
  8 / 8 ✅. `pipelines/agents/tools/`, `pipelines/agents/skill_loader.py`, `pipelines/agents/skills/`,
  `db/migrations/015_invoice_audit_views.sql`, `pipelines/scripts/agents/Tools_check.py`.
- **Context:** the Weekly Finance Pack's agents need governed tools whose numbers equal the dashboard (ADR-047 /
  048), that free models (small token budgets, varying JSON-schema support) can call reliably, and that cannot leak
  data or be talked into acting as another user.
- **Decision:** (1) **One contract:** each tool = a plain function `f(user, **args)` + a LangChain wrapper; the result
  is a `ToolResult` (`status` ok / not_permitted / context_unavailable / no_data, rows, `source` = view or API + the
  exact filter); only an ok result carries rows, and an ok result always names its source (enforced by the model).
  (2) **Who asks and which data come from the run context** (`RunContext(user, dataset)`, LangChain `ToolRuntime`),
  never from model arguments: no tool schema has a user field, and only the evaluation harness can select the
  `finance_test` copy. RBAC = `retrieval.allowed` (ADR-006) checked before any query, on the resources of
  `docs/rbac_mapping.md`. (3) **Six tools:** `finance_kpi(report_week, dataset ∈ weekly / category / customers /
  overdue / trend)` over the KPI views (P4-1); `invoice_audit(report_week | invoice_numbers)`; `compute_toll`;
  `search_documents` (the existing library); `suez_transits` (IMF PortWatch, public, no key); `web_search` (Tavily
  free tier over `httpx`, P4-4). Read-only `psycopg_pool` on `PG_RO_USER` (D10); parameterized SQL only.
  (4) **Audit in SQL** (P4-2, P4-6): views `finance.invoice_audit` and the twin `finance_test.invoice_audit` (P4-5;
  invisible to `finance_bi`) recompute every invoice from the toll bands and explain each finding with fixed checks
  (duplicate_charge on vessel + date + amount; tonnage_mismatch; amount_mismatch with probable cause
  billed_on_invoice_tonnage / flat_terminal_rate / condition_swapped / sfu_priced_ballast / unexplained; rate_mismatch);
  an independent Python `compute_toll` cross-checks them. (5) **External calls** (P4-7): timeout 10 s, no retry loop,
  any failure → context_unavailable with no data and never cached; cache per tool + arguments, no expiry once the
  window ended 14 days ago (a 2025 replay always sees the same context), 24 h otherwise. Retrieved and web text is
  marked untrusted and screened (`tools/trust.py` over the upload screening of ADR-042: invisible characters removed,
  known injection shapes flagged `suspected_injection`; amendment of the owner's skill review, 2026-10-19); NileGate
  figures come only from the structured fields of `finance_kpi`, `invoice_audit` and `compute_toll`, never from
  passage text (closes a path where a planted passage would satisfy "the number appears in a tool result"). (6) **Skills** (D13, P4-8): `SKILL.md` with a flat frontmatter (`name` = folder, `description`
  ≤ 250 chars, `stage`, `reviewed_by_owner`), body ≤ 1,200 tokens, only `references/*.md` beside it; our loader
  (`load` for workflow nodes, `descriptions` + `load_skill` for the supervisor). All six reviewed by the owner on
  2026-10-19 (13 fixes, e.g. a wrong budget-gap sentence in two skills, a rounding example that was the bake-off's own
  error, two deck slides asking for numbers no tool returns); `Tools_check.py` guards every name a skill writes
  against the tools, the rounding examples and the reviewed facts.
- **Consequences:** `Tools_check.py` 8 phases: compute_toll = 1,000 / 1,000 invoices; finance_kpi = its views on
  52 × 5 and the hand weeks; RBAC matrix 100 employees × 7 calls, leakage 0; external failure modes all
  context_unavailable; live PortWatch week 23 = 34.3 transits / day; 6 skills within budget. The audit dry run found
  the test copy's 5 planted errors with their causes (false alarms 0) and **3 real duplicate charges** in the
  original invoices (INV-0000626 / 0000925 / 0000630, both copies paid, 336,909.00 SDR) — a property of the random
  invoice draw (ADR-013, kept as data), the first content of the dashboard's Exceptions page. ADR-004's "0
  mismatches" still holds (each amount is right; the error is the repetition). Rejected: five small KPI tools (more
  schema tokens), a free `metric` argument, `employee_id` as a tool argument, a single audit view with a dataset
  column (would put the test copy inside `finance`), TTL-only caching (a replay would change), Brave (snippets only).

## ADR-050 — The `weekly_pack` workflow: hybrid nodes, PostgresSaver in `agent_state`, human approval
- **Status:** Accepted (2026-10-19, owner decisions P5-1…P5-8, Agents plan §5b; S4 / S6 decisions the same day).
  `pipelines/agents/graphs/` (`weekly_pack.py`, `models.py`), `pipelines/agents/roles.py`,
  `pipelines/agents/checkpointer.py`, `db/migrations/016_agent_state.sql`, `db/create_agent_user.ps1`,
  `db/check_agent_user.py`, `pipelines/scripts/agents/` (`Checkpointer_setup.py`, `Weekly_pack.py`,
  `Weekly_pack_check.py` 7 / 7 ✅).
- **Context:** Stage 1's pack has a fixed shape and must give reproducible numbers, survive a crash, wait for the
  Finance manager for hours or days, and spend little of the free LLM quotas (ADR-045).
- **Decision:** (1) **A LangGraph `StateGraph` with hybrid nodes** (P5-1): Data Readiness (gate R1–R4), KPI and
  Invoice Auditor are code calling the tool functions with the run's user; the Insight agent loops LLM ⇄
  `ToolNode(STAGE1_TOOLS)` (≤ 4 rounds, `search_documents` capped at 3 passages) then one structured call; the
  Writer is one structured call (`DeckDraft`, Phase 6 renders the PPTX). (2) **The Validator is code** (first
  version, P5-2): every number token of the draft must equal a numeric field of the cited structured evidence after
  an allowed rounding (number-validation), citations must exist, the draft label and deck shape are checked; a small
  template allowlist and dates are blanked; document / web rows never give numbers (ADR-049). Fail → back to the
  Writer with the problems, at most 2 rewrites, then `validation_failed`. (3) **Approval by `interrupt()`** (P5-4): a
  Finance manager or the CEO (checked in PostgreSQL at each decision) approves, edits (the edit goes back through the
  Validator) or rejects; refusals and edit diffs are logged in the state and saved with the pack (G5). The
  Publisher saves `reports/2025-W<ww>/` (save only, D9). (4) **Run context, not state:** the user and the dataset
  come from `RunContext` on every invoke and resume; a scheduled pack runs as a configured Finance manager (P5-5); the
  CLI keeps that identity in the checkpoint metadata, so an approver never becomes the run's user. (5) **Checkpoints
  in PostgreSQL** (P5-3, D3): schema `agent_state` owned by postgres; `PostgresSaver.setup()` run once as the owner
  (deployment step); the runtime login `ports_agent` ∈ `agent_writer` has DML on those tables only (no DDL, no
  TRUNCATE, nothing elsewhere); `durability="sync"`. (6) **Stops are statuses:** `not_ready`, `not_permitted`,
  `output_invalid` (a twice-invalid structured reply — a re-run would read the same cached replies),
  `validation_failed`, `rejected`, `published`; quota exhaustion stays an exception so the thread waits at its
  checkpoint and resumes later. (7) **Roles over llm.py** (`roles.py`): availability → the fallback of another
  provider, validity → one retry then stop; `FakeRoles` (same interface, the real parser) lets the whole graph run on
  52 weeks without quota (P5-7).
- **Consequences:** proven by `Weekly_pack_check.py`: 52 / 52 weeks reach the approval with fake models and are
  published; a process killed inside the Writer resumes from PostgreSQL in another process with only writer →
  validator → approval re-run (1 LLM call) and the same result; real models on weeks 5 / 10 / 23 / 49: two published,
  two `validation_failed` on real Writer errors (a sign dropped next to "down", a share cited from the wrong dataset)
  — the Validator caught them; it also found its own two gaps (web titles hid numbers; web dates failed) before the
  real run went green. The real prompts (9.7K–17K tokens) did not fit Groq's 8K TPM → ADR-045 amendment 1 (pack on
  Gemini + OpenRouter fallback). Open for Phase 6: a number is matched against any field of the cited evidence (bind
  it to its field, G1), the Writer's sign and citation errors, the full template allowlist, the PPTX. Rejected: an
  agent per node (quota, reproducibility), a Validator stub, the writer login owning the schema (DDL at runtime),
  MemorySaver (no crash resume), the CEO as the pack's identity (level 3 data), a new service employee (a change to
  a closed table).

---

## Dropped (history)
- Danish Maritime Authority AIS template (`ais_real_sample_template.csv`): dropped. AIS sources are `AISHub sample.json` (type/status diversity) and `NOAA AccessAIS.csv` (movement behaviour).
