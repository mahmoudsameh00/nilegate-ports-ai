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

| Archived file | Date | What it was | Why archived |
|---|---|---|---|
| `2026-09-10_pgvector_schema_and_stack.md` | 2026-09-10 | First schema: PostgreSQL + pgvector, MinIO, UUID keys, `TEXT[]` sensitivity levels | Abandoned in favour of Qdrant and numeric levels (ADR-001, ADR-006, ADR-014); MinIO deferred (ADR-018) |
| `2026-09-11_data_inventory.md` | 2026-09-11 | First inventory of real vs synthetic data | Facts out of date (ADR-002, ADR-007) |
| `2026-09-12_data_purpose_and_processing_plan.md` | 2026-09-12 | What each source is for, first processing plan | Merged into `ARCHITECTURE.md` → Data sources |
| `2026-09-13_initial_architecture_proposal.md` | 2026-09-13 | Generic "Data Analyst Agent" architecture proposal | Proposal only; the chosen parts are in ADR-001 and ADR-012; the deferred parts are in ADR-018 |
| `2026-09-14_master_checkpoint.md` | 2026-09-14 | ChatGPT hand-off checkpoint (reviewed version) | Split into `ARCHITECTURE.md`, `docs/decisions.md` and `docs/ROADMAP.md` |
