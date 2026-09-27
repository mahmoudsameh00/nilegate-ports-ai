# Documentation archive

These files are kept for history: decisions, abandoned approaches and how the project evolved.
**Do not treat them as current.** Current sources of truth:

| Topic | File |
|---|---|
| Rules and conventions for working on the project | the project rules |
| Current architecture and verified schema | `ARCHITECTURE.md` |
| Status, missing work, known issues | `docs/ROADMAP.md` |
| Decisions (ADR log) | `docs/decisions.md` |
| Access control mapping | `docs/rbac_mapping.md` |
| The active implementation plan (one at a time) | `docs/plans/` |

| Archived file | Date | What it was | Why archived |
|---|---|---|---|
| `2026-09-10_pgvector_schema_and_stack.md` | 2026-09-10 | First schema: PostgreSQL + pgvector, MinIO, UUID keys, `TEXT[]` sensitivity levels | Abandoned in favour of Qdrant and numeric levels (ADR-001, ADR-006, ADR-014); MinIO deferred (ADR-018) |
| `2026-09-11_data_inventory.md` | 2026-09-11 | First inventory of real vs synthetic data | Facts out of date (ADR-002, ADR-007) |
| `2026-09-12_data_purpose_and_processing_plan.md` | 2026-09-12 | What each source is for, first processing plan | Merged into `ARCHITECTURE.md` → Data sources |
| `2026-09-13_initial_architecture_proposal.md` | 2026-09-13 | Generic "Data Analyst Agent" architecture proposal | Proposal only; the chosen parts are in ADR-001 and ADR-012; the deferred parts are in ADR-018 |
| `2026-09-14_master_checkpoint.md` | 2026-09-14 | ChatGPT hand-off checkpoint (reviewed version) | Split into `ARCHITECTURE.md`, `docs/decisions.md` and `docs/ROADMAP.md` |
| `2026-09-25_LPI_Connecting_to_Compete_2025_chunking_plan.md` | 2026-09-25 | Approved plan for `LPI_Connecting_to_Compete_chunking.ipynb`, with its implementation record (deviations) at the top | Implemented and closed; the notebook's Final Checkpoint markdown is the authoritative description; lasting decisions are ADR-019 and ADR-020 |
| `2026-09-26_HbR_Annual_report_2025_chunking_plan.md` | 2026-09-26 | Approved plan for `HbR_Annual_report_2025_chunking.ipynb`, with its implementation record at the top and a dated implementation log (§5) | Implemented and closed; the notebook's Final Checkpoint markdown is the authoritative description; lasting decisions are ADR-021, ADR-022 and the within-source extension of ADR-019 |
| `2026-09-26_MSC-MEPC_3-Circ_4-Rev_1_chunking_plan.md` | 2026-09-26 | Approved plan for `IMO_MSC-MEPC_3_Circ_4_Rev_1_chunking.ipynb` (IMO casualty-reporting circular), with its implementation record at the top, the §3 decisions (§5) and a dated implementation log (§6) | Implemented and closed; the notebook's Final Checkpoint markdown is the authoritative description; lasting decisions are ADR-023 and the extensions of ADR-019 (forms) and ADR-022 (clause level) |
| `2026-09-27_USCG_ROI_chunking_plan.md` | 2026-09-27 | Approved plan for `USCG_ROI_chunking.ipynb` (23 USCG Reports of Investigation, OCR, IMO incident profiles), with its implementation record at the top, the §4 decisions and a dated implementation log (§6) | Implemented and closed; the notebook's Final Checkpoint markdown is the authoritative description; lasting decisions are ADR-024, ADR-025 and ADR-026 |
| `2026-09-27_SemiStructured_MongoDB_plan.md` | 2026-09-27 | Approved plan for the semi-structured phase (AIS + EDI → MongoDB: profiling, MongoDB container and users, `vessels.mmsi` migrations 004–005, AIS / EDI generators, loader with consistency audit), with its implementation record at the top, the §4 decisions and a dated implementation log | Implemented and closed; the Final Checkpoint markdowns of the four `Notebooks/semi_structured/` notebooks are the authoritative description; lasting decisions are ADR-027 – ADR-032 |
| `2026-09-27_PostgreSQL_Closure_plan.md` | 2026-09-27 | Plan that closed the PostgreSQL database after a read-only examination (findings F1–F10): integrity constraints, FK / GIST indexes, comments, statistics, read-only role, loopback binding; implementation record at the top | Implemented and closed; lasting decisions are ADR-033 and ADR-034; `db/README.md` holds the commands |
