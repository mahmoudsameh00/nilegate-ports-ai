# Monitoring_check — Final Checkpoint

Script: `pipelines/scripts/agents/Monitoring_check.py` · Plan: `docs/plans/Observability_Sentry_plan.md` S1 ·
ADR-062 · Module under test: `pipelines/agents/monitoring.py`.

## What it proves

Sentry is on only where the CLIs start it, sends errors / WARNING+ logs / the weekly pack's check-ins with the tags
that link it to LangSmith, never sends a secret or an LLM span, and never fails a run. Phases 1–5 use a recording
transport (0 network, 0 model calls, 0 database: the CLIs' probe is replaced by one that raises, their `reports/_log`
pointed at a temp folder).

## Steps

1. **Off and on** — no DSN: `init` False and `tag` / `capture` / `cron` are no-ops. With a DSN: no Anthropic /
   Google GenAI / httpx / LangChain / LangGraph / OpenAI / pymongo integration (`auto_enabling_integrations=False`),
   the 8 defaults present, `traces_sample_rate` None, logs on, `send_default_pii` False, release
   `nilegate-agents@0.1.0`.
2. **A captured exception** — one event tagged `entry` / `launched_by` / `thread_id` / `run_as` (a None label
   skipped); a fake secret in the message (`key=…`), in a variable named `token` (→ `[Filtered]`, the SDK scrubber),
   in an ordinary variable (→ `***`, `redact()`) and the DSN: none of them anywhere in the envelopes.
3. **Logging** — INFO → a breadcrumb only; WARNING → a Sentry log (body redacted); ERROR → a log and an event.
4. **Cron** — `in_progress` then `ok` (exit 0) / `error` (exit 2, or an exception that propagates), one
   `check_in_id`, the monitor config on every check-in. Then the real CLIs: `Weekly_pack.py scheduled --as 6` with a
   failing probe → exit 1, its own jsonl record (exit 1), the exception tagged `weekly_pack:scheduled` /
   `task_scheduler` and the check-ins `in_progress` → `error`; `Voyage_watch.py scheduled` the same but no check-in.
5. **Failures** — a transport that raises and an `init` that raises leave the run alone (monitoring off).
6. **Live** (only `MONITORING_LIVE=1` + `SENTRY_DSN`) — one test exception and one WARNING log with a `check_run` id,
   read back by Claude through the Sentry MCP. No check-in (D-S1-2).

## Problems and fixes

- **`sentry_sdk.flush()` raised the transport's error** (Phase 5, first run): the log batcher flushes on the caller's
  thread inside `flush`. Fix: `monitoring.flush()` catches and logs it, and the check flushes through it. The CLIs
  never call `sentry_sdk.flush` (the exit flush is the atexit integration's, and the real HTTP transport sends from a
  background worker), so no run was exposed.
- **Scope leaking between phases:** tags and breadcrumbs live on the isolation scope, which a new `init` keeps; every
  phase clears the isolation and current scopes before its `init`.
- **The Phase 5 client at the end:** the refusing transport would raise again at the final `close`; a working
  recorder is started before the broken-`init` case.

- **A stale `sys.argv` in the live event:** Phase 4 sets `sys.argv` for the CLIs; Sentry's argv integration reported
  `Voyage_watch.py scheduled --as 6` on Phase 6's event (issue PYTHON-2). Phase 4 now restores it after each CLI.

## Last run (2026-10-31)

Live run 6 / 6 ✅ (`MONITORING_LIVE=1`): issue PYTHON-2 and the WARNING log (`key=***`) read back through the Sentry
MCP with every tag. After the argv fix, Phases 1–5 ✅ again (Phase 6 not re-sent), 7 s, files changed 0. The three checks that load the CLIs as modules
(`Supervisor_tools_check.py`, `Supervisor_check.py`, `Voyage_watch_check.py`) ✅, files changed 0.
