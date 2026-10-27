# Pipelines

Every data pipeline of the project is a Python script here (ADR-036). Each script's header says what it reads, what
it writes and whether it is safe to re-run; the Final Checkpoint narrative (every step, its problems, their fixes) is
in `checkpoints/<area>/<stem>.md`. The notebooks they came from are archived in `docs/archive/notebooks/`.

Run one script, or all of them in verification order, from the project root:

```text
uv run python tools/run.py pipelines/scripts/<area>/<stem>.py [--compare]
uv run python tools/run.py all --compare [--from <stem>] [--with-mongo] [--hashseed N]
```

`tools/run.py` prints the ✅ validation lines, the errors and every file it changed or created under
`Data/processed/` and `db/migrations/` (SHA-256 before / after). `--compare` checks the ✅ lines against the archived
notebook's saved outputs.

| Script | Area | Refactor level | What it produces |
|---|---|---|---|
| `structured/ExtractPortsAttributes.py` | structured | A | `ports.csv` (837 ports) |
| `structured/ExtractPortsConnection.py` | structured | A | `port_connections.csv` (19,990 pairs); the table load only with `--insert` on an empty table |
| `synthetic/SyntheticGenerator.py` | synthetic | A | verifies employees / vessels / containers CSVs; checks invoice pricing (ADR-004, ADR-013) |
| `synthetic/Finance_generator.py` | synthetic | phases | `synthetic/finance/` (customers, vessel → customer, payments, weekly budget, the `finance_test` copy) + manifest, `agents/eval/finance_test_answer_key.json`, migration `012_finance_data.sql`; Agents plan §4a; re-run = identical (`--hashseed` checked) |
| `finance/Finance_views_check.py` | finance | phases | nothing (read-only): the `finance` views of migration 013 = an independent pandas reference on all 52 weeks, invariants, hand-check weeks 5 / 16 / 23 / 49 (reviewed snapshot), RBAC matrix + `finance_bi` privileges; Agents plan Phase 2, `docs/finance_metrics.md` |
| `rag/Documents_registry.py` | RAG | A | `documents.csv` + migration 010 (29 rows); database = mirror check |
| `rag/FBL_chunking.py` … `rag/USCG_ROI_chunking.py` (7) | RAG | B (USCG + one listed patch) | extracted / cleaned / chunks artifacts per source (2,163 chunks) |
| `semi_structured/AIS_EDI_profiling.py` | semi-structured | B | AIS / EDI profiles |
| `semi_structured/AIS_generator.py` | semi-structured | B | synthetic AIS tracks, static records, voyages + manifest |
| `semi_structured/EDI_generator.py` | semi-structured | A | synthetic IFTMIN messages + manifest |
| `semi_structured/MongoDB_loader.py` | semi-structured | B | MongoDB collections (only writer) + a load report per run |

| `retrieval/Provider_smoke_test.py` | retrieval | A | nothing (one tiny call per embedding provider + one rerank call) |
| `retrieval/Golden_set.py` | retrieval | A | `rag/eval/golden_set.jsonl` (frozen: 64 queries + 8 RBAC cases) |
| `retrieval/Golden_facts.py` | retrieval | A | `rag/eval/golden_facts.jsonl` (80 facts for the 40 questions; ADR-040) |
| `retrieval/Embedding_bakeoff.py` | retrieval | A | `rag/eval/bakeoff_results.json` (vectors cached in `Data/embeddings/bakeoff/`, git-ignored, read by later scripts) |
| `retrieval/Embeddings.py` | retrieval | A | `Data/embeddings/gemini-embedding-2/dense_<variant>.parquet` (git-ignored) + `manifest.json` (committed); ADR-037 |
| `retrieval/Qdrant_loader.py` | retrieval | A | Qdrant `nilegate_docs` (the only writer; nothing on disk); ADR-039 |
| `retrieval/Search_index_benchmark.py` | retrieval | A | nothing (exact vs IVF vs Qdrant exact / HNSW on our vectors) |
| `retrieval/Retrieval.py` | retrieval | A | nothing (validates `search_documents`: exactness, RBAC matrix, filters, cache, rate, latency) |
| `retrieval/Evaluation.py` | retrieval | A | `rag/eval/results_<date>.json` (configurations by the ADR-040 rule → ADR-038) |
| `retrieval/Lib_selftest.py` | retrieval | A | nothing (checks `pipelines/lib/`; throwaway Qdrant collection) |
| `retrieval/Upload_fixtures.py` | retrieval | B-style phases | `rag/eval/uploads/fixtures/` (52 cases: clean NileGate documents + attacks), `expected.json`, `upload_questions.jsonl`; `docs/templates/NileGate_document_v1_example.docx` |
| `retrieval/Upload_validation.py` | retrieval | B-style phases | `rag/eval/uploads/validation_report.json` (every fixture verdict, corpus false positives 0, PDF / DOCX parity) |
| `retrieval/Upload_eval.py` | retrieval | B-style phases | `rag/eval/uploads/upload_eval_<date>.json` (local model choice, settings, floor, corpus baseline with a session, isolation, latency) |
| `retrieval/Upload_promotion.py` | retrieval | A (CLI) | promotion requests in `Data/incoming/promotion/` (review / approve / commit); `--selftest` uses a throwaway collection |
| `agents/LLM_smoke_test.py` | agents | A | nothing tracked (each provider key: live model list + one tool-calling request, through the response cache) |
| `agents/LLM_bakeoff.py` | agents | phases | `agents/eval/bakeoff_tasks.json` (T1–T4 + LITE + prompts, frozen: `TASKS_SHA256`), `agents/eval/llm_bakeoff_<date>.json` (scores, selection per role); Agents plan §7a |
| `agents/Tools_check.py` | agents | phases | `agents/tool_cache/` (git-ignored; the live PortWatch week 23): the Stage 1 tools of `pipelines/agents/tools/` each against its source, the audit views (migration 015) against the answer key and a Python auditor, the RBAC matrix (100 × 7), the skills; Agents plan Phase 4 §5a |
| `agents/Checkpointer_setup.py` | agents | A (deployment step) | the LangGraph checkpoint tables in schema `agent_state` (as the owner account, after migration 016; again after a `langgraph-checkpoint-postgres` upgrade); second run = no change |
| `agents/Weekly_pack.py` | agents | A (CLI) | `run --week W --as <Finance manager>` / `show` / `resume --decision approve\|edit\|reject --as <approver>` / `list`: the `weekly_pack` graph on PostgresSaver; a PPTX preview in `reports/_drafts/`, on approval `reports/2025-W<ww>/deck.pptx` + JSON files (git-ignored); ADR-050, ADR-051. Phase 8 (ADR-054): `scheduled` (what Task Scheduler runs: the next week of the replay as `PACK_RUN_AS`, one pending pack at a time, then the retention; `reports/_log/scheduled.jsonl`, a toast), `prune [--dry-run]`, `report` (G5); `run` / `resume` / `scheduled` traced in LangSmith when `LANGSMITH_API_KEY` is set |
| `agents/Scheduler_check.py` | agents | phases | nothing tracked (temp folders; check threads `weekly_pack:check:…`, deleted): the week picker, retention (archive then delete, pending never), scheduled firings end to end on fake models, the run identity + read-only CLI, the tracing contract (no network), the LangSmith read-back (one small trace; only with a key); Agents plan Phase 8 §5e, ADR-054 |
| `agents/Weekly_pack_check.py` | agents | phases | nothing tracked (temp folders; one PostgreSQL thread, deleted): models + roles, the deterministic nodes on 52 weeks, the fake-model pack on 52 weeks + the approval rules + the PPTX preview / `deck.pptx`, the rewrite routing (patch / whole deck / V8 stop), crash / resume across processes, real models on 4 weeks (only with `PACK_REAL_MODELS=1`; cached), the schema / dataset contract; Agents plan Phases 5–6 §5b / §5c |
| `agents/Finance_qa.py` | agents | A (CLI) | `ask "…" --as <employee> [--lang ar]`: one question to the finance Q&A agent (`graphs/finance_qa.py`, LangChain `create_agent`), RBAC from the employee; prints the status, the answer with its numbers filled from the tools, the evidence and any problem of the code check; nothing written; traced in LangSmith (`entry:qa`) with a key; plan §5f K6 |
| `agents/Finance_qa_check.py` | agents | phases | nothing (fake models, the real Stage 1 tools, no trace): the agent's answer paths (plain text → structured; the answer tool called directly; invalid twice → output_invalid), the answer brief + the 3-round tool cap, the code check + one patch, RBAC (an Operations employee refused), the model-call limit and the records, the CLI; plan §5f F2 (D-P7-6 / D-P7-7) |
| `agents/Deck_check.py` | agents | phases | nothing tracked (previews of weeks 10 / 23 in `Notebooks/_scratch/`): number slots, 52 clean decks through V1–V8, 100 planted wrong numbers (drafts and files), the real failures replayed; Agents plan Phase 6 §5c, ADR-051 |
| `agents/Golden_weeks.py` | agents | phases | `agents/eval/golden_weeks.json` (the 11 golden weeks by rule, frozen) and `golden_weeks_expected.json` (the evidence of each week, frozen once complete); PortWatch 2025 into `tool_cache/`: Agents plan Phase 7 §5d S1 |
| `agents/Qa_golden.py` | agents | phases | `agents/eval/finance_qa_golden.jsonl` (30 EN + 10 Egyptian Arabic questions, expected values from the tools, frozen): Agents plan Phase 7 §5d S3 |
| `agents/Stage1_eval.py` | agents | phases | Phases 1–4: nothing (frozen inputs, scorer self-tests, golden weeks + Q&A with fake models, 0 calls); Phase 5 with `EVAL_REAL_MODELS=1`: `agents/eval/stage1_eval_<date>.json` (the baseline, ADR-052) + decks in `Notebooks/_scratch/stage1_eval/`: Agents plan Phase 7 §5d S5–S6; `EVAL_TRACE=1` traces each pack / question in LangSmith (Phase 8, off by default) |

The agents scripts (Agents plan, Phase 0) are not in `run.py all` either (free LLM APIs with daily quotas). They use
`pipelines/agents/llm.py`: the provider registry (Gemini / Groq / OpenRouter), the model factory (LangChain chat
models, temperature 0, no library retries), the per-minute `Budget`, the persisted daily quota state and the response
cache `Data/processed/agents/eval/llm_cache/` (git-ignored): a re-run makes 0 calls, a quota-exhausted model waits for
the provider's next day; no data guard (all project data is synthetic or public, ADR-037 amendment 2).

The retrieval scripts are not in `run.py all` (they call paid / rate-limited APIs or need `ports-qdrant`). They share
`pipelines/lib/` (ADR-039): `common`, `chunks`, `embeddings`, `qdrant_store`, `evaluation` (ADR-040: retrieval /
ranking / context metrics), and for documents uploaded at inference time (RAG plan Phase 8): `upload_reader`
(PDF / DOCX reading in a child process, file-level and hidden-text findings), `screening` (injection patterns),
`uploads` (the "NileGate Document v1" shape, `validate_upload`, chunking), `local_embeddings` (ONNX Runtime model),
`session_store` (conversation-only uploads in memory, the session lane, promotion requests). The local ONNX model
(`bge-m3`, the session lane, ADR-043) is exported once by `tools/export_onnx.py` into `models/onnx/` (git-ignored); the
two rejected candidates were removed at the plan's close and `Upload_eval.py` reuses their recorded rows.

- **Level A**: rewritten by hand as functions and `main()`; exploration prints became assertions. Proof: the local run
  (`--compare`: the notebook's ✅ lines kept in order, new ones allowed; `files changed: 0`).
- **Level B**: generated by `uv run python tools/nb_to_script.py clean <stem>` from the archived notebook: the phase
  structure is the flow and stays linear (`# %% <Phase title>` sections, narrative as comments); only Jupyter's
  display rules became `print()`. Proof: `uv run python tools/nb_to_script.py check` (AST equal to the notebook) plus
  the local run.

`all` skips `MongoDB_loader` unless `--with-mongo` (each run reloads MongoDB and adds a load report; keep only the
newest report: its `load_run` is stamped on every document). `--hashseed N` fixes `PYTHONHASHSEED`: two runs with
different seeds that change a file reveal an output that depends on string-hash order (2026-10-01: none left).

Order of `run.py all`: smallest first; `LPI_methodology_chunking` before `LPI_Connecting_to_Compete_chunking` (it reads
its units); the generators before `MongoDB_loader`.
