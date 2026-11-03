# Observability plan — Sentry errors, logs and one cron monitor; the LangSmith mirror after c4

Status: **IMPLEMENTED (2026-11-02)** — approved 2026-10-31 (owner: "موافق، ابدأ S1"; S2–S4 approved 2026-11-01 as one batch).

## Implementation record (2026-11-02)

- **S1 (2026-10-31):** Sentry errors + WARNING+ logs from the four CLIs' `main()` only (`pipelines/agents/monitoring.py`,
  `sentry-sdk==2.72.0`, the LangChain / AI integrations off, no spans); the one cron monitor `nilegate-weekly-pack`
  on `Weekly_pack.py scheduled`; `Monitoring_check.py`. **Closed 2026-11-02:** the first real check-in arrived ok at
  2026-11-02T08:30Z (≈ 42 s, exit 0, week 13 awaiting approval), no issue in the last 24 h.
- **S2 (2026-11-01):** `Langsmith_mirror.py` — the frozen evaluations mirrored as 3 LangSmith datasets + experiments,
  0 model calls, idempotent.
- **S3 (2026-11-01):** annotation queue `nilegate-review` + an automation rule (errors and `refused` traces).
- **S4 (2026-11-01):** Sentry "new issue" email alert 6273246.
- **Deviations:** D-S1-1…D-S1-6, D-S2-1, D-S3-1 (Progress below). **Open for the owner:** D-S1-5 (event geo = the
  laptop's IP, nothing changed) and **D-S1-6** — connect the monitor's detector 10829356 to alert 6273246 (Sentry →
  Alerts → 6273246 → add `nilegate-weekly-pack` as a source); until then a missed / failed Monday makes a cron issue
  but no email.
- **Lasting decision:** ADR-062 (+ amendment 1).


`docs/plans/` held two plans for one day (owner 2026-10-31); `Agents_plan.md` closed after Stage 1 candidate c4 and
was archived on 2026-11-01 (`docs/archive/2026-11-01_Agents_plan.md`) — this file is now the only active plan.

## Owner answers already taken (2026-10-31, as clickable choices)

- **O1 — the one free cron monitor:** the weekly pack (`Weekly_pack.py scheduled`, Monday 10:30). The voyage watch
  (every 12 h) gets error capture only: on a laptop that sleeps at night a 12-hour monitor would report missed
  check-ins most nights.
- **O2 — timing:** S1 is coded **today**, outside the code the c4 evaluation runs on 2026-11-01 09:30.
- **O3 — this file:** in `docs/plans/` now (above).
- **O4 — scope:** errors + the cron monitor + **Sentry Logs** (`logging` WARNING and above). No tracing, no LLM
  spans: LangSmith stays the only LLM tracer (ADR-054).

## Facts read (2026-10-31)

- Sentry: organization `terbo` (region `https://us.sentry.io`), one project `python` — read through the Sentry MCP
  (the owner's claude.ai connector, not in `.mcp.json`).
- Developer (free) plan, `sentry.io/pricing`: 5k errors, **1 cron monitor** (+ $0.78 each beyond it), 1 uptime
  monitor, 1 user, 30-day lookback, 5 GB logs, 5M spans.
- `sentry-sdk` on PyPI: 2.73.0 is the latest (the pin is chosen at `uv add`, a release at least two weeks old).
  Sentry's LangChain integration **turns itself on** when `langchain` is installed (Sentry docs, "LangChain"), as do
  the other AI integrations — left at the defaults, every model call would become a Sentry span.
- Entry points: `Weekly_pack.py` (`run` / `resume` / `scheduled` / …), `Voyage_watch.py`, `Ask.py`,
  `Route_advice.py`. Three checks load two of these CLIs as modules (`Supervisor_check.py` → `Ask.py`;
  `Voyage_watch_check.py`, `Supervisor_tools_check.py` → `Voyage_watch.py`) → Sentry starts only inside `main()`.
- `Weekly_pack.py scheduled` catches every exception and turns it into an exit code (0 ok, 1 exception, 2 database
  unreachable, 3 wrong identity) logged in `reports/_log/scheduled.jsonl` → Sentry's excepthook never sees it; the
  capture must be explicit there.
- **c4's code** (`Stage1_eval.py` imports): `llm`, `roles`, `tracing`, `deck/*`, `graphs/*`, `tools/*` — not
  `scheduling.py` and not the four CLIs.

## Constraints

- **c4 freeze (until the c4 task ends on 2026-11-01):** S1 touches only a new module, the four CLI scripts,
  `.env.example`, `pyproject.toml` / `uv.lock` and docs — never `tracing.py`, `llm.py`, `graphs/`, `deck/`, `tools/`,
  skills, `scheduling.py` or `Stage1_eval.py`.
- **`uv add` adds one package.** If `uv.lock` changes the version of any package already locked, the add is undone
  (`uv remove`) and the owner is asked (c4 runs on this `.venv`).
- **Tonight's voyage-watch firing (22:30)** runs the code on disk: S1's checks pass before then, or `Voyage_watch.py`
  is left unchanged until tomorrow.
- **Off unless asked:** no `SENTRY_DSN` → no Sentry at all. Checks and evaluations never call `init` (a planted
  failure must not spend the 5k errors).
- **A Sentry failure never fails a run**, like LangSmith (ADR-054): `init`, capture and flush swallow their own
  errors; flush waits ≤ 5 s.
- **Secrets:** the DSN lives only in `.env` (the owner adds it); events pass through `redact()`
  (`pipelines/lib/common.py`) and the SDK's scrubber; `send_default_pii=False`.
- **The Sentry MCP:** Claude reads issues, events and logs freely; resolving, assigning or commenting needs the
  owner's yes per change (ROADMAP, 2026-10-30).

## S1 — Sentry in the CLIs (today)

1. **`pipelines/agents/monitoring.py`** (next to `tracing.py`):
   - `init(entry, launched_by="cli", transport=None) -> bool` — `sentry_sdk.init(dsn, environment=SENTRY_ENVIRONMENT
     or "local", release="nilegate-agents@<pyproject version>", auto_enabling_integrations=False,
     traces_sample_rate=None, send_default_pii=False, include_local_variables=True, enable_logs=True,
     integrations=[LoggingIntegration(level=INFO, event_level=ERROR, sentry_logs_level=WARNING)],
     before_send=… redact …, before_send_log=… redact …)`. `auto_enabling_integrations=False` drops LangChain /
     LangGraph / OpenAI / Google GenAI / httpx / pymongo; the defaults (excepthook, logging, atexit, dedupe, stdlib,
     threading, argv, modules) stay. Exact option names confirmed in the installed SDK before coding.
   - `tag(**labels)` — scope tags `entry`, `launched_by`, `thread_id` (the same id as the LangSmith metadata and the
     `agent_state` thread: the link between the two tools), `run_as`.
   - `capture(exc)` — for exceptions a CLI catches and turns into an exit code.
   - `cron(slug)` — a context manager: check-in `in_progress`, then `ok` (exit 0) or `error`, with the monitor
     config sent by the SDK (upsert, no click in the UI): crontab `30 10 * * 1`, timezone `Africa/Cairo`,
     `checkin_margin` 720 min (the task starts when the owner logs on after a missed start), `max_runtime` 60 min
     (the task's 1 h limit), failure / recovery thresholds 1.
   - `flush()` at exit (≤ 5 s).
2. **The four CLIs, inside `main()` only:** `monitoring.init(entry=<cmd>, launched_by=…)`; `tag(thread_id=…)` where
   the thread is known; `Weekly_pack.py scheduled` inside `cron("nilegate-weekly-pack")` and `capture(exc)` next to
   its existing `scheduled.jsonl` record; `Voyage_watch.py`'s scheduled path: `capture` next to its own error record,
   no cron.
3. **`.env.example`:** `SENTRY_DSN=` and `SENTRY_ENVIRONMENT=` with a comment (what is sent, what is not).
4. **`pipelines/scripts/agents/Monitoring_check.py`** — 0 model calls, 0 network by default (a recording transport):
   - Phase 1 — off without a DSN; nothing imported from the AI integrations is active; no tracing.
   - Phase 2 — an exception in a fake CLI run → one event with the tags; a secret placed in a local variable and in
     the message comes back `***`.
   - Phase 3 — WARNING → one Sentry log, INFO → a breadcrumb only, ERROR → an event.
   - Phase 4 — `cron`: `in_progress` then `ok`; an exception → `error`; exit 1 / 2 / 3 → `error`; the monitor
     config as above.
   - Phase 5 — a transport that raises → the run still exits with its own code.
   - Phase 6 (live, only `MONITORING_LIVE=1` + a DSN) — one test event + one check-in on a test slug; Claude reads
     them back through the Sentry MCP.
   - Plus the three checks that load the CLIs as modules, on fake models (they must still import and pass).
   - Checkpoint narrative `pipelines/checkpoints/agents/Monitoring_check.md`.
5. **The owner:** copies the DSN of project `python` (Settings → Client Keys) into `.env` as `SENTRY_DSN`.
6. **Docs:** ADR-062 (Sentry: errors + logs + one cron monitor, AI integrations off, LangSmith stays the tracer,
   the `thread_id` tag), `ARCHITECTURE.md` (observability row), `docs/ROADMAP.md`, `pipelines/README.md`,
   `CLAUDE.md` (stack line), `.env.example`.

**Done-when (S1):** `Monitoring_check.py` Phases 1–5 ✅ and Phase 6 read back through the MCP; the three CLI-loading
checks ✅; the first real `scheduled` firing (Monday 2026-11-02 10:30) shows an `ok` (or `error`) check-in on monitor
`nilegate-weekly-pack`; `uv.lock` changed by `sentry-sdk` (and its new dependencies) only.

## Later steps (after c4, each approved before its code)

- **S2 — LangSmith Datasets & Experiments as a mirror** (ROADMAP 2026-10-30): after each evaluation, a copy of the
  frozen golden set (its sha256 in the dataset description) and the per-item results from the reply cache (0 new
  model calls) are logged as an experiment. The local golden sets and the code scorer stay authoritative (ADR-052).
  Touches `Stage1_eval.py` / `Stage2_eval.py` → after c4.
- **S3 — a LangSmith automation rule:** a trace with an error or a `refused:` tag goes to an annotation queue (no LLM
  judge); free-plan limits checked first. A standing configuration → the owner's yes before it is created.
- **S4 — Sentry alerts:** the default "new issue" email plus the cron monitor's missed / failed alert; the owner's yes
  before any rule is changed.

## Progress / deviations

- 2026-10-31 — plan written (PROPOSED); approved the same day.
- 2026-10-31 — **S1 coded and checked (0 model calls, 0 network).** `uv add sentry-sdk==2.72.0` (2.73.0 is 9 days old;
  `uv.lock` compared package by package: added `sentry-sdk` only, 0 versions changed, 0 removed). API confirmed in the
  installed SDK: `enable_logs`, `before_send_log`, `auto_enabling_integrations`, `LoggingIntegration(sentry_logs_level)`,
  `sentry_sdk.crons.capture_checkin`; the auto-enabling list holds Anthropic / GoogleGenAI / Httpx / Langchain /
  Langgraph / OpenAI / OpenAIAgents / PyMongo. `pipelines/agents/monitoring.py` (`init`, `tag`, `capture`, `cron`,
  `flush`); the four CLIs: `init` in `main()` with entry `<cli>:<cmd>`, `tag(thread_id, run_as)` where a thread starts
  (in the scheduled firings through a `scheduled_tracer` that also opens the LangSmith trace), `capture(exc)` in both
  scheduled firings' `except`, `Weekly_pack.py scheduled` inside `cron("nilegate-weekly-pack")`. `.env.example`:
  `SENTRY_DSN`, `SENTRY_ENVIRONMENT`. ADR-062; ARCHITECTURE (observability row + ADR table).
  - **D-S1-1 (finding, fixed):** `sentry_sdk.flush()` lets a transport's exception through when the log batcher flushes
    (Phase 5 failed on it) → `monitoring.flush()` catches and logs it. The real HTTP transport sends from a background
    worker, so the CLIs were not exposed; the exit flush (atexit) never changes an exit code.
  - **D-S1-2 (deviation):** Phase 6 (live) sends one event + one WARNING log, **no check-in** — a check-in from a check
    would take the plan's only cron monitor or put a wrong status on the pack's. The cron is proven by the first real
    firing (Monday 2026-11-02 10:30).
  - **D-S1-3 (design detail):** no explicit flush in the CLIs: `shutdown_timeout=5` lets the atexit integration send
    what is queued (≤ 5 s).
  - Checks: `Monitoring_check.py` **5 / 6 ✅** (Phase 6 pending the DSN), `Supervisor_tools_check.py` ✅,
    `Supervisor_check.py` ✅, `Voyage_watch_check.py` ✅ (Phases 1–7 + 4s) — all 0 files changed. None of c4's code
    touched (`Stage1_eval.py` and its imports).
  - **Next:** the owner puts the DSN of project `python` in `.env` → `MONITORING_LIVE=1` run of `Monitoring_check.py`
    → Claude reads the event + log back through the Sentry MCP → Monday's firing shows the first check-in → S1 closed.
- 2026-10-31 — **Phase 6 live ✅ (6 / 6), read back through the Sentry MCP:** issue **PYTHON-2** "RuntimeError:
  Monitoring_check live test d21b28c44809" (1 event, handled) with tags `entry` monitoring_check:live, `launched_by`
  check, `thread_id` monitoring_check:d21b28c44809, `check_run`, `environment` local, `release`
  nilegate-agents@0.1.0; the WARNING log "Monitoring_check live log d21b28c44809 key=***" (the fake secret masked).
  No span was sent (the event carries only the SDK's propagation trace id). Resolved through the MCP with the owner's
  yes ("أيوه، resolve"), no comment added.
  - **D-S1-4 (finding, fixed in the check):** the live event's `sys.argv` extra read `Voyage_watch.py scheduled --as 6`
    — Phase 4 set `sys.argv` for the CLIs and never restored it (the argv integration reports it). Phase 4 now restores
    it; Phases 1–5 re-run ✅ (Phase 6 not re-sent: each run spends one of the 5k errors).
  - **D-S1-5 (finding, for the owner, nothing changed):** the event shows `user.geo` = Cairo, Egypt although
    `send_default_pii=False`: Sentry's server derives it from the connection's IP. Turning it off is a project setting
    (project `python` → Settings → Security & Privacy → "Prevent Storing of IP Addresses"), the owner's to change.
  - **Open:** Monday 2026-11-02 10:30 — the first check-in of `nilegate-weekly-pack` (the monitor is created by it).
- 2026-11-01 — **S2–S4 APPROVED as one batch (owner, choices as recommended: "التلاتة ورا بعض", "اعملها إنت",
  "Scheduled check الساعة 11:00"):** run S2 → S3 → S4 without stopping between steps (small decisions = the
  recommended option, logged here); Claude creates the standing configurations itself (the LangSmith annotation queue +
  automation rule, the Sentry alert); the first check-in is verified by a one-time Claude scheduled task
  (`nilegate-sentry-first-checkin`, 2026-11-02 11:00 local), which also connects the new monitor to the alert and writes
  the result here.
- 2026-11-01 — **S4 done (Sentry alerts):** the project already had "Send a notification for high priority issues"
  (email, issue owners → active members; it fired for PYTHON-2). Added alert **6273246** "NileGate: new, regressed or
  reappeared issue (any priority)" on project `python`'s issue stream → the same email action, 30-min interval, so a
  medium-priority error (e.g. a caught exception from a scheduled firing) also reaches the owner. The cron monitor
  does not exist until its first check-in; the Monday task connects its detector to 6273246.
- 2026-11-01 — **S2 done (LangSmith mirror):** `pipelines/scripts/agents/Langsmith_mirror.py` — 3 datasets
  (`nilegate-finance-qa@5cf72ac3` 42, `nilegate-supervisor-qa@722f3ca3` 57, `nilegate-golden-weeks@7589e7e7` 11; named
  by the frozen files' sha256) and 12 experiments (base3 × 3, c4 × 3, dp127b × 2, stage2 2026-10-29 × 2, c1 × 2):
  stored answers + stored code scores, 0 model calls; Phases 1–4 ✅; the re-run sent 0 (idempotent). D-S2-1: the
  first read-back saw one experiment short (LangSmith stats lag; 57 / 57 a minute later) → reported, not failed.
  Not wired into `Stage1_eval.py` / `Stage2_eval.py` (recommended: no change to the frozen harness); after an
  evaluation, run the mirror with `MIRROR_RESULTS=<file>` (checkpoint `Langsmith_mirror.md`).
- 2026-11-01 — **S3 done (review queue):** annotation queue `nilegate-review` + automation rule "nilegate: errors and
  refused parts -> review" on `nilegate-agents` (filter `and(eq(is_root, true), or(eq(status, "error"),
  has(tags, "refused")))`, sampling 1.0, created by REST `POST /api/v1/runs/rules` — the langsmith 0.14.7 SDK has no
  rule method; accepted on the free plan). `Ask.py` now adds a plain `refused` tag when any part is refused
  (`Supervisor_check.py` ✅ 9 lines, 0 files changed). Test: an Operations employee (12) asked a finance question →
  `not_permitted`, 0 model calls, traced with `refused` (D-S3-1: the first try used employee 2, an Operations
  *manager*, who may read finance (D-P12-1) → answered, 2 flash-lite calls). **The rule worked:** the refused run
  reached `nilegate-review` within the wait (the queue held 3 items: the rule also matched earlier root runs).
- **Next:** the Monday task (2026-11-02 11:00) verifies the first check-in and closes S1 → then this plan is complete:
  implementation record, archive, ROADMAP, `/graphify . --update`, the owner's commit.
- 2026-11-02 — **First real check-in verified (scheduled task `nilegate-sentry-first-checkin`, 11:00 local).**
  `reports/_log/scheduled.jsonl` last line: `at` 2026-11-02T08:30:06Z, `cmd` scheduled, **`exit` 0**, no `error`,
  decision `start` (next week of the replay) → week **13**, thread `weekly_pack:live:2025-W13:1`, result `pending` /
  `awaiting_approval` (the pack waits for the owner's approval), retention deleted nothing, `traced` true.
  Sentry: monitor **`nilegate-weekly-pack`** exists (created by this check-in; project `python`, `30 10 * * 1`
  Africa/Cairo, margin 720, max runtime 60), environment `local` status **ok**, one check-in **ok** at
  2026-11-02T08:30Z (duration 42,328 ms ≈ 42 s), next expected 2026-11-09T08:30Z;
  https://terbo.sentry.io/crons/python/nilegate-weekly-pack/ . Issues in `python` seen in the last 24 h: none.
  The check-in status matches the jsonl record (exit 0 → ok).
  - **D-S1-6 (deviation, open for the owner):** the monitor's detector is **10829356** (type
    `monitor_check_in_failure`, `workflowIds` []), but connecting it to alert 6273246 (`update_alert_rule`,
    `addDetectorIds ["10829356"]`) was **refused by the session's permission classifier** (standing-rule change in an
    unattended run) → **not connected**; nothing else changed in Sentry. To do: the owner connects it (Sentry → Alerts →
    6273246 → add the monitor `nilegate-weekly-pack` as a source), or approves the call in a live session. Until then a
    missed / failed Monday firing makes a cron issue but sends no email through 6273246.
  - **S1 CLOSED — the first real check-in arrived.**
