# Final Checkpoint — Scheduler_check (Agents plan Phase 8, 2026-10-20)

**What it proves:** a scheduled firing (`Weekly_pack.py scheduled` → `pipelines/agents/scheduling.fire`) makes the
right week of the 2025 replay, never starts a second pack while one waits for approval, resumes a pack stopped
mid-run with the identity it started with, and the retention archives an ended thread before deleting it and never
touches a pending one; the G5 report counts each decided pack once. Design: plan §5e (owner decisions P8-1…P8-4),
ADR-050 (threads, statuses, run identity), D3 (retention).

| Phase | Step | Result (2026-10-20) |
|---|---|---|
| 0 | Week picker (P8-1) | 10 hand-made cases: empty → W01; after W10 → W11; a pending pack → wait (also before a stalled one); a stalled thread → resume; one stopped attempt → retry; two → the week skipped; a reject = an attempt; published on retry → next week; W52 published → done; 4 thread ids parsed (a check's `…:check-1a2b`, a one-digit week and the test dataset are not ours) |
| 1 | Retention rules (P8-3), dry run | 7 hand-made threads: ended + older than 30 days → 2 would go; ended 29 days kept; pending 90 days kept and reported; stalled 20 days kept and reported; nothing deleted |
| 2 | Firings end to end (PostgresSaver, fake models) | 7 firings on the prefix `weekly_pack:check:2025-W`: W01 start → waits; same day → wait (no second attempt); edit (another Finance manager) → back through the Validator → approve → published (4 files); W02 wrong twice → `validation_failed` ×2 → skipped; W03 rejected; W03:2 raises inside the Writer (a quota stand-in) → the next firing resumes it → waits; run identity = the scheduled Finance manager on all 5 threads; 31 days later: dry run deletes nothing, then 4 ended threads archived and deleted (0 checkpoint rows left), the pending W03:2 kept and reported; G5 report: 2 decided (1 published, 1 rejected), 1 edited, edit rate 0.5, edited slide 2; every check thread deleted |
| 3 | Run identity + CLI | only a Finance manager is a scheduled identity (a Finance employee, an Operations manager and the CEO refused); `prune --dry-run` and `report` run on the live threads (exit 0, nothing deleted; W10 approved without edits → edit rate 0.0) |
| 4 | Tracing contract (P8-4, S2; added 2026-10-21) | child process, fake key, endpoint `127.0.0.1:9` (refused: nothing leaves the machine): off before / after `tracing.trace`, on inside it with project `nilegate-agents`, 5 tags (`weekly_pack`, entry, launched_by, week, dataset) and 7 metadata fields; the run's result unchanged although every upload failed; the run's own error propagates; an empty key = off; no `LANGSMITH_TRACING` / `LANGCHAIN_TRACING_V2` in the environment or `.env.example`; `LANGSMITH_API_KEY` redacted (`SECRET_KEYS`). Child 47 s — the final flush waits for the refused uploads |
| 5 | LangSmith read-back (S2) | 2026-10-21, with the owner's key: one fake-model scheduled firing on the check prefix (W01:1 → awaiting_approval) traced; its root run found by thread id in `nilegate-agents` (14 runs in the trace, no error), 5 tags, metadata week / attempt / run_as 6 / entry / launched_by `check` (+ the checkpoint's own `trigger: scheduled`); the checkpoint metadata = the run identity only |

## Problems and fixes
- None at the first run (4 / 4). Design points settled while writing it (plan Progress, D-P8-1…D-P8-4): a stalled
  thread is resumed before anything new; a rejected pack counts as an attempt; the firing waits for PostgreSQL
  itself (Docker Desktop starts after logon); a lock file stops two firings running at once.
- S2 (2026-10-21), Phases 4–5 added, 5 / 6 at the first run (Phase 5 pending). Design points (plan Progress,
  D-P8-5…D-P8-7): tracing is a context around the graph run, never an environment switch, so `Stage1_eval.py` and
  the checks stay untraced without being edited; `scheduling.fire` takes the tracer as an argument (the check's
  firings are untraced unless Phase 5 passes one); a LangSmith outage costs ≈ 45 s of flush at the end of a run,
  never the run.
- Phase 5, first run with the key: the trace was found and tagged, but its metadata said `trigger: scheduled`, not
  the tracer's `check` — the graph config's metadata (written by `scheduling.fire` for the checkpoint) wins over the
  tracing context's on a shared key. Fix: the tracer's key is `launched_by` (tag `launched_by:…`), never a key the
  checkpoint metadata uses; the check asserts both. 6 / 6 at the second run (91 s, 0 LLM calls).
- 2026-10-22, a later run: Phase 5 found the root run but fewer than 5 runs in its trace — the root is ingested
  before its child runs. Fix: the read-back waits for the children too (up to 3 min). 6 / 6 (74 s).
- Beyond this check (plan Progress, S3): the real Task Scheduler firings on 2026-10-22 — two stopped on a Gemini 503
  in the Insight node, the third resumed the same thread and reached the approval — are the done-when of Phase 8;
  this check proves the same rules on fake models.
