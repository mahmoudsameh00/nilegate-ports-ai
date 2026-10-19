# Final Checkpoint — Weekly_pack_check (Agents plan Phase 5, 2026-10-19)

**What it proves:** the `weekly_pack` LangGraph workflow (`pipelines/agents/graphs/weekly_pack.py`) produces a
validated deck draft for any report week, stops with a stated status when it cannot, waits for a Finance manager's
decision, publishes only an approved draft, and resumes from PostgreSQL after its process dies. Design: plan §5b
(owner decisions P5-1…P5-8), ADR-050; models ADR-045 amendment 1.

| Phase | Step | Result (2026-10-19) |
|---|---|---|
| 0 | Models and roles (S1) | `DeckDraft` round trip; 5 invalid objects refused (slide 11, a web evidence id, edit without edits, approve with edits, a passing verdict with problems); the role rules with stub models: Exhausted / no key → the fallback, an invalid reply → one retry, two → `StructuredError`, both exhausted → `Exhausted`; `FakeRoles` through the real parser |
| 1 | Deterministic nodes on 52 weeks (S2) | 52 / 52 ready; path readiness → kpi → audit; warm-up notes on weeks 1–13; evidence = the tool functions called directly 52 / 52; live audit = the 3 reviewed duplicates (weeks 10 / 15 / 50); a week without invoices (forced) → `not_ready`; an Operations employee → `not_permitted`; no number in either state; 0 LLM calls |
| 2 | Fake-model pack on 52 weeks + approval (S3) | 52 / 52 reach the interrupt with a passing verdict and are published on approve (three files, title "Approved"); the ToolNode result = the tool 52 / 52 (the run context reaches the tool); reject saves nothing; week 23: a wrong-number edit fails the Validator and "approve" disappears, then an approve of the failing draft, an Operations manager, an unknown employee, a malformed decision and bullet 99 are refused and asked again, a correct edit passes, the CEO approves — eight steps in the log (G5) |
| 3 | Validator loop + rules (S3, S6) | a planted wrong number rewritten once; an always-wrong Writer stopped after two rewrites (`validation_failed`, no interrupt); 26 rule cases (roundings as returned / M / k / %, half away from zero, signs, ×100, "849.9 k", web numbers, unknown / missing evidence, the draft label, the deck shape, template allowlist, dates; a date never hides an amount) |
| 4 | Crash and resume (S5) | a subprocess exits (`os._exit(77)`) inside the Writer; 9 checkpoints in `agent_state`; this process resumes the thread: only writer → validator → approval → publisher (1 LLM call); result = an uninterrupted run on every compared key; `delete_thread` leaves 0 rows |
| 5 | Real models on weeks 5 / 10 / 23 / 49 (S6) | weeks 10 and 49 published, 5 and 23 `validation_failed` on real Writer errors (reviewed snapshot); 0 fallbacks; every call within its provider's per-minute limit (max 17.0K tokens, Gemini); a re-run makes 0 model calls |
| 6 | Contract (S3) | no tool schema has a user field or a field able to pick the evaluation copy; `dataset="test"` reaches `finance_test` through the node and the ToolNode; `search_documents` capped 8 → 3 |

## Problems and fixes
- **The Validator hid what it should catch.** Strings with digits in the cited evidence are blanked as identifiers
  (invoice numbers, week labels, dates); applied to web rows it blanked their titles, so "Canal revenue 7.5 M" citing
  a web result passed. Document / web rows now give neither numbers nor blankable strings (ADR-049); a rule case.
- **A false alarm in the check, not the code:** `finance_kpi`'s `dataset` (which KPI view) looked like a leak of the
  evaluation-copy switch; the contract check now looks for any field whose choices include test / live.
- **Real prompts did not fit Groq.** The first real run: 9.7K–17K tokens per Insight / Writer call, Groq refused
  ("Request too large", taken for a per-minute limit: 60 s waits, then the model stopped) and every call fell back.
  Owner: the pack's Insight / Writer on Gemini flash-lite + OpenRouter nemotron (ADR-045 amendment 1); `llm.py`
  caches a too-large request as a deterministic failure (`too_large`).
- **The model could not cite its own tool calls** (week 23 cited `suez_transits`): it never sees tool-call ids. The
  notes and Writer prompts now list every evidence id with its tool and arguments. A twice-invalid reply now ends the
  run as `output_invalid` instead of an exception (owner); quota exhaustion stays an exception (resumable).
- **Template text and dates** ("1 to 30 days", "90 plus", the warm-up footnote, "6 June 2025", RFC dates of news)
  failed the number check: a small allowlist and `DATE_RE` (owner; dates are required by `untrusted-content`).
- **What remains is the Writer's:** a sign dropped next to "down" and a share cited from `kpi.customers` — the
  Validator is right to refuse them; Phase 6 improves the Writer and binds each number to its field (G1).
- Deleting scratch files was refused in this session: `Notebooks/_scratch/` keeps the S1 / S6 helpers until the
  owner empties it.
