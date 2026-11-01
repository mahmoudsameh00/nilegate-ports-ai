# Threat model — NileGate agents platform

Status: **first version 2026-11-01** (Engineering hygiene plan H2). Scope: what exists today — the data stores, the
retrieval tool, the agent graphs (`weekly_pack`, `finance_qa`, `route_advice`, `voyage_watch`, the supervisor), the
CLIs and the scheduled tasks, on one Windows machine. The API and the web frontend do not exist yet (ADR-060): their
items (XSS, CSRF, SSRF, CORS, authentication, rate limits per user) are added when they are built.

Each row: the risk, the control that exists (with its decision record and the check that proves it), and the gap.
"Control" means it exists and is tested; "Gap" means it is planned, partial or missing.

## OWASP Top 10 for LLM Applications (2025)

| # | Risk | Control today | Gap |
|---|---|---|---|
| LLM01 | Prompt injection (direct, and indirect through documents, uploads, web results) | Project rule 5: retrieved text is data, never instructions; the `untrusted-content` skill in every agent that reads documents; uploads pass a validator + three-layer injection screening in EN / MSA / Egyptian Arabic (`pipelines/lib/screening.py`, ADR-042) and stay labelled `untrusted_upload` (ADR-043); web results are never evidence for a number (ADR-049); the model cannot act on injected text — no write tool exists, every number is a code slot (ADR-051 / ADR-059) | No prompt-injection items in the frozen golden sets yet (ROADMAP: next frozen version); no red-team run against the supervisor |
| LLM02 | Sensitive information disclosure | RBAC inside every tool and inside Qdrant (sensitivity ceiling + owner department, ADR-006; leakage 0 on the RBAC matrices of `Tools_check.py`, `Supervisor_check.py`, `Stage2_eval.py`); the supervisor's code router never offers a refused tool (ADR-059); a stored answer is readable only by its asker and the CEO; secrets masked in logs, Sentry events and LangSmith-bound errors (`redact()`, `monitoring.py`, ADR-062); all project data is synthetic or public (ADR-037 amendment 2) | No `audit_log` of who asked what (PLANNED with the API); Sentry derives the client's location from its IP unless the owner turns "Prevent Storing of IP Addresses" on (plan D-S1-5) |
| LLM03 | Supply chain | Every dependency pinned `==` through uv with a lock file; versions at least two weeks old; dev tools separate; `pip-audit` run (H2) and Dependabot weekly PRs (`.github/dependabot.yml`); third-party Claude skills reviewed before use (`.claude/skills/README_third_party.md`) | **Open: 63 advisories in 8 packages** (2026-11-01 audit: pillow 39 → 13.0.0, filelock 13 → 4.2.1, pyasn1 4 → 0.6.5, tornado 3 → 6.6, certifi, dnspython, langgraph-checkpoint-postgres 3.1.3, pymongo 4.18.3) — upgrade after the 2026-11-02 firing with the full checks |
| LLM04 | Data and model poisoning | The corpus is ingested by reviewed scripts with reviewed snapshots (ADR-036); a manager's upload reaches the corpus only by promotion (ADR-044); golden sets are frozen with sha256 and change only by a recorded REFREEZE (ADR-053); models are hosted, not fine-tuned | The review queue (`nilegate-review`) feeds future golden items — each needs the owner's review before it enters a frozen set |
| LLM05 | Improper output handling | Model output is never executed and never written to a database; every number in a deck or answer is a slot filled by code from a tool result and read back (Validator v2 + V8, ADR-051; `check_answer` / `check_supervisor_answer`); a pack is published only after a human approval (ADR-050); PPTX text is written through python-pptx (no macros) | The future web UI must escape model text (ADR-060 item) |
| LLM06 | Excessive agency | Every agent tool is read-only (members of the read-only role `ports_readonly`, ADR-034; Power BI's `ports_bi` in `finance_bi`; MongoDB `nilegate_reader`); the only writer is the checkpointer login `ports_agent` on schema `agent_state`; the pack waits for a Finance manager's approval; the scheduled identity is checked at every firing (ADR-054) | — |
| LLM07 | System prompt leakage | Prompts and skills hold no secrets (keys live only in `.env`); skills are in git and reviewed by the owner | — |
| LLM08 | Vector and embedding weaknesses | The RBAC filter is applied inside the Qdrant query, not after it (ADR-038 / ADR-039); Qdrant listens on 127.0.0.1 with an API key; uploads live in a memory-only session store, never in the shared collection (ADR-043) | — |
| LLM09 | Misinformation | Code computes every figure; the Writer only words them (slots); claims checked by the scorer (claims 100 %, false alarms ≤ 5 %, ADR-052); abstention when the data does not hold the answer (`not_in_data`, the year guard D-P12-12); every answer traceable to its evidence ids | The Validator does not judge wording beyond numbers and fixed rules (Stage 1 checkpoint: four W12 sentences) — the weekly-pack plan's V9 claim check |
| LLM10 | Unbounded consumption | Free-tier quotas enforced in `llm.py` (per-day counters, cache, fallback; ADR-045); the supervisor offers ≤ 5 tools; one pending pack at a time; Open-Meteo paced under its per-minute limit (D-P11-2); scheduled tasks have run-time limits | Per-user limits arrive with the API |

## OWASP Agentic AI — threats and mitigations (selected, those that apply to this platform)

| # | Threat | Control today | Gap |
|---|---|---|---|
| T1 | Memory poisoning | Agent memory = PostgresSaver checkpoints per thread, written only by the graphs; no long-term memory shared across users; retention archives then deletes ended threads (ADR-054) | — |
| T2 | Tool misuse | Typed tool arguments (pydantic, ADR-049); the run context carries the user and the dataset, the model cannot choose them; refused tools never offered (ADR-059) | — |
| T3 | Privilege compromise | The user comes from the run context, checked in PostgreSQL; the scheduled identities (`PACK_RUN_AS`, `WATCH_RUN_AS`) must hold the right role; an approval is checked against the approver's role | No authentication layer yet (the CLIs trust `--as`) — the API phase adds it |
| T5 | Cascading hallucination | Each graph validates its own output in code before anything leaves it; the supervisor checks the product tools' rows, not their prose | — |
| T8 | Repudiation and untraceability | One `agent_state` thread + one LangSmith trace per run, linked by `thread_id`, also tagged in Sentry (ADR-062); the approval log outlives the thread (archive) | `audit_log` table PLANNED |
| T10 | Overwhelming the human in the loop | One pending pack at a time; a degraded pack is marked for the approver (c4); a toast only when a pack waits or a high alert exists | — |
| T11 | Unexpected code execution | No code-execution tool; uploads: active PDF / DOCX content rejected, DOCX XML parsed with defusedxml (ADR-042) | — |

## How this file is kept

Updated when a control or a gap changes (a new tool, a new store, the API). The next frozen golden-set version adds
prompt-injection items (LLM01 gap); the dependency upgrade closes the LLM03 gap.
