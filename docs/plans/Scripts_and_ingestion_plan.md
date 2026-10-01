# Plan — Notebooks → scripts, and one ingestion script for new unstructured documents

- **Status:** APPROVED (2026-10-01), decisions D1–D7 answered by the owner (§4, "Answers"). Branch
  `feat/scripts-and-rag-ingestion`.
- **Goal:** (A) turn every notebook into a Python script **without changing what the code does or where anything
  sits**, keeping the closing "Final Checkpoint" markdown as a readable document; from then on all work is in scripts.
  (B) one ready script that takes a **new** unstructured raw document from `Data/raw/` through parsing, cleaning,
  chunking, registration, embedding and the Qdrant upsert.
- **Relation to the active plan:** `docs/plans/RAG_Embeddings_Qdrant_plan.md` (APPROVED 2026-09-28) stays as it is and
  is paused at Phase 0. 2026-10-01: rewritten for a fresh local start; **part B moved into it as its Phase 8**
  (§3 below is kept as the original proposal only).
- **Touches:** the project rules conventions (notebooks → scripts), `tools/nb.py`, the local skills foldernotebook-dev-loop`,
  the local assistant folderhooks/guard.py` (`.ipynb` read block), ARCHITECTURE §2, ROADMAP; a new ADR (next number: ADR-036, so the RAG
  plan's ADR-036 / 037 become 037 / 038).

---

## 1. Starting point (verified 2026-10-01, read-only)

15 notebooks, ~23,900 code lines, no IPython magics except one `%pip` (ExtractPortsConnection, forbidden by
the project rules rule 6), no `input()`, no plotting.

| Notebook | Cells (code / md) | Code lines | Final Checkpoint markdown | Script-only issues |
|---|---|---:|---|---|
| rag/LPI_methodology_chunking | 92 / 49 | 4,748 | cell 139 (an empty md cell follows) | 50 `display`, 10 bare trailing expressions |
| rag/LPI_Connecting_to_Compete_chunking | 83 / 21 | 3,780 | last cell (129 lines) | 63 `display` |
| rag/HbR_Annual_report_2025_chunking | 82 / 21 | 3,697 | last cell (120 lines) | 44 `display` |
| rag/USCG_ROI_chunking | 67 / 19 | 3,484 | last cell (144 lines) | 24 `display` |
| rag/IMO_MSC-MEPC_3_Circ_4_Rev_1_chunking | 70 / 21 | 2,680 | last cell (100 lines) | 38 `display` |
| rag/FBL_chunking | 24 / 16 | 1,810 | last cell (85 lines) | 3 `display`, 2 bare |
| rag/Suez_Notes_chunking | 18 / 22 | 577 | cell 38 | 1 bare |
| rag/Documents_registry | 9 / 6 | 162 | cell 13 | — |
| semi_structured/MongoDB_loader | 19 / 13 | 804 | cells 28 + 31 | writes MongoDB (idempotent, ADR-031) |
| semi_structured/AIS_EDI_profiling | 18 / 10 | 618 | cells 25 + 27 | — |
| semi_structured/AIS_generator | 13 / 9 | 433 | cells 19 + 21 | 1 bare |
| semi_structured/EDI_generator | 9 / 7 | 255 | cells 13 + 15 | 1 bare |
| synthetic/SyntheticGenerator | 28 / 1 | 651 | none | 6 bare |
| structured/ExtractPortsAttributes | 14 / 0 | 130 | none | 1 bare |
| structured/ExtractPortsConnection | 25 / 0 | 120 | none | 18 bare, `%pip`, **inserts into `port_connections`** |

`Data/raw/` is not in git, and the databases run on the owner's machine, so **the scripts can be executed only
locally**; the cloud session can verify the conversion statically (below).

## 2. Part A — conversion

### A1. Shape (recommended)
- `scripts/` mirrors `Notebooks/`: `scripts/rag/LPI_methodology_chunking.py`, `scripts/semi_structured/…`, same stems.
- **Percent format** (`# %%` code cell, `# %% [markdown]` markdown cell as `# ` comment lines) — the format
  `tools/nb.py` cell files already use. A plain `uv run python scripts/rag/X.py` runs it top to bottom; VS Code still
  shows it as runnable cells.
- Every code cell is copied **byte for byte, in the same order**; every markdown cell stays at its place as a comment
  block (the section headings and explanations keep their context).
- The **Final Checkpoint** markdown goes to a companion file `scripts/<folder>/<stem>.md` (rendered tables and
  headings, readable on GitHub), unchanged text. The script keeps a one-line pointer at its place. Notebooks without a
  Final Checkpoint get no companion file (nothing is invented).
- The conversion is done by a deterministic converter (`tools/nb_to_script.py`), never by retyping.

### A2. The only changes a script needs (each listed, nothing else)
| # | Change | Why | Where |
|---|---|---|---|
| 1 | one header line `from IPython.display import display` | `display()` exists only inside Jupyter; IPython is already installed and prints the same text repr | the 7 RAG notebooks that call it |
| 2 | bare last-line expressions wrapped in `display(...)` | a script silently drops them; the notebook showed them | 40 cells (table above) |
| 3 | `%pip install "psycopg[binary]"` removed | not valid Python; the project rules rule 6 (uv only; psycopg is in `pyproject.toml`) | ExtractPortsConnection |
| 4 | a header docstring: source notebook, inputs, outputs, side effects, "safe to re-run?" | a script has no visible outputs to read from | all |

### A3. Guarding side effects (no behaviour change)
ExtractPortsConnection inserts into `port_connections` (completed table, the project rules rule 2: never rebuild). Its header
says **DO NOT RE-RUN**, and it is excluded from the local verification run. MongoDB_loader is idempotent (ADR-031) and
Documents_registry only generates the migration file; both are verified locally like the rest.

### A4. Verification
- **Cloud (static, before any commit of scripts):** for each script, the converter's reverse step rebuilds the cell
  list and asserts: code cells equal the notebook's code cells except the listed changes (diff report saved), markdown
  count and text equal, Final Checkpoint text in the `.md` equals the notebook cell, `python -m py_compile` passes.
- **Local (owner, one script at a time, smallest first):** `uv run python scripts/…`, then
  `git status --porcelain Data/` must be empty (tracked artifacts byte-identical) and the script's `✅` lines must equal
  the notebook's saved ones (`tools/nb.py check` summary vs the script log).

### A5. After verification
- Notebooks: deleted in one separate commit (git history keeps them with their outputs) — see D2.
- `tools/nb.py` → `tools/run.py` (run a script with its log in `scripts/_scratch/run_<stem>.log`, print errors + `✅` lines;
  `_scratch` git-ignored like today); skill `notebook-dev-loop` → `script-dev-loop`; guard hook `.ipynb` rule kept (archived notebooks are still large, deviation);
  the project rules "Stack / Where things are / Conventions / Token discipline", ARCHITECTURE §2, ROADMAP, ADR-036.

## 3. Part B — `scripts/rag/ingest_new_documents.py` (MOVED 2026-10-01 to the RAG plan, Phase 8; kept for history)

### B1. What it does
```text
Data/raw/unstructured/<new file>  +  its metadata entry (required, see B2)
  → detect new: sha256 not in Data/processed/rag/documents.csv
  → extract   : PyMuPDF text + layout; OCR (RapidOCR, ADR-025) only for image-only pages
  → clean     : repeated headers / footers, hyphenation, page numbers → logical units (headings by font size)
  → dedup     : within the source and against the existing corpus (unit level, before chunking)
  → chunk     : semantic boundaries, MIN 300 / MAX 2000 chars, the 16-column schema (ARCHITECTURE §5)
  → validate  : schema, dtypes, unique chunk_id, cross-source concat, reload from disk
  → REVIEW GATE: writes a review report (flagged units, coverage) and stops; `--approve <document_id>` continues
  → register  : row in documents.csv + generated migration db/migrations/NNN_*.sql (applied by the owner)
  → embed     : chosen model (RAG plan Phase 2), files first into Data/embeddings/<model>/ (resumable)
  → upsert    : Qdrant `nilegate_docs` through the loader's code (one writer, idempotent: UUID5(chunk_id))
```
Artifacts use the existing layout (`extracted/`, `cleaned/`, `chunks/`). Re-running on the same file changes nothing.

### B2. Metadata is never guessed
`sensitivity_level`, `department`, `document_type`, `source`, `real_or_synthetic`, `title`, `version_date`,
`source_url` come from a metadata file the owner fills (`Data/raw/unstructured/_incoming.csv`, one row per new file).
A file without a row is listed and skipped; there is no default sensitivity level.

### B3. Honest limit
The 7 existing sources each needed source-specific rules and manual review. A generic pipeline gives a correct but
plainer result; this is why the review gate exists and why "when unsure, preserve and mark for review" applies. The
existing per-source scripts stay the reference for those sources; the generic script never rewrites their artifacts.

## 4. Decisions (recommended option first)
- **D1 — Final Checkpoint location:** companion `.md` next to the script + pointer in the script / *or* kept inline as
  a comment block only / *or* both.
- **D2 — Notebooks after local verification:** delete (history keeps them) / *or* move to `docs/archive/notebooks/` /
  *or* keep alongside the scripts.
- **D3 — Large notebooks (up to 4,748 code lines):** convert as one script each, no refactor (refactoring into modules
  would change code and is a later, separate task) / *or* split now.
- **D4 — Bare expressions:** wrap in `display(...)` / *or* drop them.
- **D5 — Input formats for part B:** PDF only (all 29 current raw files are PDF) / *or* PDF + DOCX + TXT/MD.
- **D6 — Order of part B vs the RAG plan:** build B's stages up to the review gate + registration now, and its embed /
  upsert stages right after RAG Phases 2–5 (reusing their code) / *or* pause B until the RAG plan finishes.
- **D7 — Old branch:** `feat/rag-retrieval` (identical to `master`) deleted on GitHub by the owner / *or* kept.

### Answers (owner, 2026-10-01)
- **D1:** companion `.md`, kept apart from the script. Revised by the owner (2026-10-01): one main folder with a scripts
  folder and a checkpoints folder inside → `pipelines/scripts/<area>/<stem>.py` + `pipelines/checkpoints/<area>/<stem>.md`.
- **D2:** notebooks move to `docs/archive/notebooks/<folder>/` after the local verification (row in
  `docs/archive/README.md`).
- **D3:** refactoring is allowed; what must not change is the **flow and the outputs**. Applied in two steps so the
  outputs stay provable: (1) faithful conversion (A1–A4) verified locally against the committed artifacts; (2) then a
  refactor per script, each re-verified locally with the same check (`git status --porcelain Data/` empty, same `✅`
  lines). A refactor is never committed without its local verification.
- **D4:** left to the assistant → wrap in `display(...)` (keeps what the notebook showed).
- **D5:** PDF only (the ingestion script is a dedicated PDF agent).
- **D6:** part B waits until the RAG plan is finished, then is built in one go (it reuses the RAG plan's embedding and
  loader code). Steps 6–7 below move after the RAG plan.
- **D7:** delete `feat/rag-retrieval` (identical to `master`). The cloud session's git proxy refuses branch deletion
  (HTTP 403), so the owner deletes it on GitHub (Branches page) or locally: `git push origin --delete feat/rag-retrieval`.

## 5. Order of work (one step at a time, owner confirms each)
1. Approve this plan (answers D1–D7). 2. Converter + static check, cloud. 3. Convert the 15 notebooks (smallest
first), static report. 4. Owner runs each script locally and sends the summary. 5. Tooling / docs / ADR-036.
6. Part B to the review gate. 7. Part B embed / upsert (after RAG Phases 2–5). 8. Close (archive, ROADMAP).

## Progress / deviations
- 2026-10-01: plan written and APPROVED; deleting `feat/rag-retrieval` was refused by the cloud git proxy (owner deletes it).
- 2026-10-01, steps 2–3 DONE: `tools/nb_to_script.py` (convert + check) and `tools/run.py` (run, ✅ lines, SHA-256 report
  of `Data/processed` + `db/migrations`, `--compare` with the notebook's saved ✅ lines). 15 scripts, 12 checkpoint
  `.md` (the 3 structured / synthetic notebooks have no Final Checkpoint; nothing invented). `check`: ALL OK under
  Python 3.13 (every cell equal; 40 cells with a wrapped last expression, 1 `%pip` commented, 4 empty cells skipped).
  Deviations from §2: (a) layout per revised D1; (b) only the closing narrative cell moves to the `.md`, a
  "## Final Checkpoint" heading cell before the last code cell (semi-structured notebooks) stays in the script; (c) the
  converter's first version treated `%s` SQL placeholders as magics, caught by `check`, fixed (magics only in cells that
  are not valid Python); (d) wrapping keeps Jupyter's rule "None is not shown", so `conn.commit()` etc. print nothing;
  (e) strings that name the notebook inside outputs (AIS / EDI manifests, migration 010 header) are unchanged, so the
  outputs stay byte-identical — they can be updated in the refactor step.
- Step 5 DONE early (docs): ADR-036, skill `script-dev-loop` (replaces `notebook-dev-loop`), the project rules, ARCHITECTURE §2,
  ROADMAP; RAG plan paused with ADR numbers shifted. `tools/nb.py` kept until the notebooks are archived.
- Trial run in the cloud (only `SyntheticGenerator` has all inputs in git): fails at cell 3 (`employees.csv` regenerated
  differently, nothing overwritten). The original notebook, executed here on a scratch copy, fails at the same cell →
  environment (Linux), not the conversion; recorded in ROADMAP known issues. All other scripts need `Data/raw/` or the
  databases → local only.
- Guard hook: its relative path blocked every command after the shell changed directory; now
  the local guard hook (owner approved). To confirm on Windows.
- **Next (owner, local, step 4):** `uv sync`, then per script, smallest first:
  `uv run python tools/run.py pipelines/scripts/<area>/<stem>.py --compare` → expect `compare: ✅ identical`,
  `exit 0`, `files changed: 0` (MongoDB_loader adds one new load report by design; skip ExtractPortsConnection: DO NOT
  RE-RUN). Then step 4b: archive the notebooks; then D3 refactors one script at a time with the same check.
- 2026-10-01, local run (owner) started: ExtractPortsAttributes ✅ (exit 0, files changed 0). Documents_registry
  stopped at its PostgreSQL connection (`ConnectionTimeout`: the database was not reachable; Phase 1 ✅ before it,
  nothing written) → re-run with `ports-postgres` up.
- Converter fix found while reading ExtractPortsConnection: a cell ending in a bare tuple (`len(a), len(b)`) was
  wrapped as `_display_result(len(a), len(b))` (two arguments → TypeError at run time; the static check could not see
  it). Bare tuples now use `_display_tuple(...)`; 2 cells, both in ExtractPortsConnection; no other script affected.
- Owner decision: ExtractPortsConnection joins the run; its INSERT cell (21) is disabled by the converter (commented
  with `#! `, a reason line, restorable; `check` proves it), so the script only reads PostgreSQL and rewrites the CSV.
- 2026-10-01, step 4 DONE (owner, Windows): `tools/run.py all --compare` order, all 15 scripts exit 0, ✅ lines
  identical to the notebooks' saved outputs, `files changed: 0` for every script (MongoDB_loader created its new load
  report + rejected CSV by design). SyntheticGenerator passes on Windows (the Linux difference is a platform issue,
  ROADMAP known issues). Documents_registry first failed only because PostgreSQL was down.
- Step 4b DONE: notebooks moved to `docs/archive/notebooks/<area>/` (git mv; row in `docs/archive/README.md`);
  `tools/nb_to_script.py` reads them there (`check` ALL OK), `tools/run.py --compare` finds them there.
  `db/mongo/README.md` points to the script. Historical mentions (ADRs, migration 010 header, closed-phase docs) keep
  the notebook paths on purpose.
- **Part A is complete.** Open: (1) D3 refactors, optional, one script at a time with the same local check;
  (2) part B (PDF ingestion) after the RAG plan. **Next: owner decides refactor now vs. resume RAG retrieval.**
- 2026-10-01, D3 refactor DONE in the cloud, **local verification pending**. Owner: "take your time; the flow and the
  outputs are what matter". Two levels (ADR-036 amendment, `pipelines/README.md`):
  - Level A, by hand (functions + `main()`, assertions instead of exploration prints): ExtractPortsAttributes,
    ExtractPortsConnection (INSERT → `insert_port_connections()`, only with `--insert`, refuses a non-empty table),
    SyntheticGenerator (unused `get_toll_band_id` removed; random-draw order kept — vessels.csv and containers.csv
    regenerated identical here), Documents_registry (migration 010 re-rendered byte-identical from the mirror here),
    EDI_generator. New assertions were checked against the committed CSVs where possible. pyflakes clean.
  - Level B, generated (`nb_to_script.py clean`): the 7 RAG scripts, AIS_EDI_profiling, AIS_generator, MongoDB_loader;
    `check` proves AST equality with the archived notebooks (negative test: a changed argument and a removed line are
    caught, a comment edit is not).
  - `tools/run.py --compare` now accepts the notebook's ✅ lines kept in order plus new ones (level A adds a few).
  - Deviation from D3's wording ("never committed without its local verification"): the refactor has to be committed
    to reach the owner's machine; it is marked pending here until the local run passes.
  - Load reports: the run of 2026-10-01 created `load_audit/20261001T092224Z.json` + `_rejected.csv` on the owner's
    machine. Not useless: every MongoDB document now carries `load_run = 20261001T092224Z`, so this is the report of the
    current database content; the committed 20260928 pair is the stale one. Owner to decide (recommended: commit the
    new pair, `git rm` the old pair).
- **Next (owner, local):** `git pull`, then `uv run python tools/run.py all --compare`; expected: 15/15 exit 0,
  `compare: ✅`, `files changed: 0` (MongoDB_loader creates a new load report by design). Then close this plan
  (archive it; RAG retrieval plan becomes the only active plan).
