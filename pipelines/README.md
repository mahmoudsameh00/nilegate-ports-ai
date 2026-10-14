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

The agents scripts (Agents plan, Phase 0) are not in `run.py all` either (free LLM APIs with daily quotas). They use
`pipelines/agents/llm.py`: the provider registry (Gemini / Groq / OpenRouter), the model factory (LangChain chat
models, temperature 0, no library retries), the per-minute `Budget`, the persisted daily quota state and the response
cache `Data/processed/agents/eval/llm_cache/` (git-ignored): a re-run makes 0 calls, a quota-exhausted model waits for
the provider's next day, and a free tier accepts only `data_origin` "public" or "synthetic" (ADR-037 amendment).

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
