"""Run the Weekly Finance Pack for one report week, and decide on it (Agents plan §5b, P5-4 / P5-5).

Commands (from the project root):
    uv run python pipelines/scripts/agents/Weekly_pack.py run --week 23 --as 12
        start a new attempt of week 23 as employee 12 (a Finance manager: the pack's run identity); it stops at the
        approval (prints the draft with bullet numbers and the path of the PPTX preview in reports/_drafts/) or at a
        stated stop status; on approval reports/2025-W23/ gets deck.pptx + deck_draft.json + approval.json + run.json
    uv run python pipelines/scripts/agents/Weekly_pack.py show --thread weekly_pack:live:2025-W23:1
        where a thread stands, and the draft waiting for a decision
    uv run python pipelines/scripts/agents/Weekly_pack.py resume --thread weekly_pack:live:2025-W23:1 --as 12 \
        --decision approve | reject | edit [--edits edits.json] [--comment "…"]
        decide as employee 12 (a Finance manager or the CEO, checked in PostgreSQL); edits.json =
        [{"bullet": 3, "text": "…"}] — an edit goes back through the Validator and waits again
    uv run python pipelines/scripts/agents/Weekly_pack.py list [--week 23]
        the threads in agent_state
    uv run python pipelines/scripts/agents/Weekly_pack.py scheduled [--as 12]
        what Windows Task Scheduler runs (Phase 8, §5e): the next week of the replay as the scheduled identity
        (PACK_RUN_AS in .env, or --as), or wait while a pack waits for approval, or resume a pack stopped mid-run;
        then the retention; one line in reports/_log/scheduled.jsonl; a Windows toast when a pack waits
    uv run python pipelines/scripts/agents/Weekly_pack.py prune [--dry-run]
        retention by hand: archive, then delete ended threads older than 30 days (never a pending one)
    uv run python pipelines/scripts/agents/Weekly_pack.py report
        G5: approve / edit / reject counts and the edited slides of every decided pack

Reads:   PostgreSQL (read-only tools; the checkpoints through ports_agent), the LLM APIs of ADR-045 (cached), the
         external tools (cached). Writes: checkpoints in agent_state; on approval reports/2025-W<ww>/ (git-ignored);
         reports/_log/ (scheduled.jsonl, threads_archive.jsonl).
Re-run:  `run` always starts a new attempt (a new thread); `resume` continues one; `scheduled` never starts a second
         pack while one waits (§5e P8-1). The evaluation copy (`dataset="test"`) is not offered here: only the
         evaluation harness sets it (ADR-049).
Exit:    0 done (including "wait" / "done"); 1 the pack raised (the thread waits at its checkpoint); 2 the database
         did not answer within PROBE_WAIT_MIN; 3 the scheduled identity is not a Finance manager.
"""
import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())
sys.path.insert(0, str(ROOT))
from langgraph.types import Command  # noqa: E402

from pipelines.agents import checkpointer, roles, scheduling, tracing  # noqa: E402
from pipelines.agents.graphs import weekly_pack as wp  # noqa: E402
from pipelines.agents.tools import context, db  # noqa: E402
from pipelines.lib.common import load_env, redact  # noqa: E402

PREFIX = scheduling.LIVE_PREFIX
REPORTS = ROOT / "reports"
LOG = REPORTS / scheduling.LOG_DIR
PROBE_WAIT_MIN, PROBE_EVERY_S = 30, 60      # Docker Desktop starts after logon: the firing waits for PostgreSQL
LOCK_STALE_H = 2


def threads(week: int | None = None) -> list[str]:
    return scheduling.thread_ids(checkpointer.pool(), f"{PREFIX}{week:02d}:" if week else PREFIX)


def next_attempt(week: int) -> str:
    used = [int(t.rsplit(":", 1)[1]) for t in threads(week) if t.rsplit(":", 1)[1].isdigit()]
    return f"{PREFIX}{week:02d}:{max(used, default=0) + 1}"


def probe() -> str | None:
    """None when both logins answer (the checkpointer's and the read-only tools'), else the last error."""
    deadline, err = time.monotonic() + PROBE_WAIT_MIN * 60, None
    while True:
        try:
            with checkpointer.pool().connection() as conn:
                conn.execute("SELECT 1")
            db.fetch("SELECT 1 AS ok")
            return None
        except Exception as exc:  # noqa: BLE001 — any failure to reach the database means "not yet"
            err = f"{type(exc).__name__}: {exc}"
            checkpointer.close()
            db.close()
        if time.monotonic() >= deadline:
            return err
        time.sleep(PROBE_EVERY_S)


def scheduled(employee: int | None) -> int:
    LOG.mkdir(parents=True, exist_ok=True)
    rec = {"at": scheduling.now_utc().isoformat(timespec="seconds"), "cmd": "scheduled"}
    lock = LOG / "scheduled.lock"
    if lock.exists() and time.time() - lock.stat().st_mtime < LOCK_STALE_H * 3600:
        rec["skipped"] = "another firing is running (lock)"
        scheduling.append_jsonl(LOG / "scheduled.jsonl", rec)
        print(rec["skipped"])
        return 0
    lock.write_text(str(os.getpid()), encoding="utf-8")
    code = 0
    try:
        err = probe()
        if err:
            rec["error"], code = f"database unreachable: {redact(err)[:300]}", 2
            return code
        load_env(ROOT)
        run_as = employee or int(os.environ.get("PACK_RUN_AS") or 0)
        try:
            user = context.load_user(run_as) if run_as else None
        except PermissionError:               # an unknown employee id
            user = None
        if not scheduling.allowed_run_as(user):
            rec["error"], code = f"scheduled identity {run_as or 'unset'} is not a Finance manager (PACK_RUN_AS)", 3
            return code
        rec["run_as"] = run_as
        rec.update(scheduling.fire(graph(), checkpointer.saver(), checkpointer.pool(), user, REPORTS,
                                   tracer=lambda t, r: tracing.trace(t, entry="scheduled", run_as=r,
                                                                     launched_by="task_scheduler")))
    except Exception as exc:  # noqa: BLE001 — logged for the owner; the thread (if any) waits at its checkpoint
        rec["error"], code = redact(f"{type(exc).__name__}: {exc}")[:600], 1
        rec["trace"] = redact(traceback.format_exc(limit=3))[-1200:]
    finally:
        rec["exit"] = code
        scheduling.append_jsonl(LOG / "scheduled.jsonl", rec)
        lock.unlink(missing_ok=True)
        print(json.dumps({k: v for k, v in rec.items() if k != "trace"}, ensure_ascii=False, default=str, indent=1))
    return code


def graph():
    return wp.build_graph(roles.Roles(), checkpointer.saver())


def show(g, cfg) -> None:
    snap = g.get_state(cfg)
    st = snap.values
    print(f"thread {cfg['configurable']['thread_id']} | status {st.get('status')} | next {list(snap.next) or 'END'}")
    for r in (st.get("readiness") or {}).get("reasons", []):
        print(f"  not ready: {r}")
    verdict = st.get("verdict") or {}
    for p in verdict.get("problems", []):
        print(f"  validator {p['rule']} slide {p.get('slide')} bullet {p.get('bullet')}: {p['message']}")
    draft = st.get("draft")
    if draft:                     # the slots filled: what the deck says (Phase 6); edits are written in this form
        draft = wp.v2.render_draft(draft, st.get("evidence") or {})
        print(f"  {draft['title']}")
        titles = {t["slide"]: t["title"] for t in draft["slide_titles"]}
        for i, b in enumerate(draft["bullets"]):
            print(f"  [{i:2d}] slide {b['slide']:2d} ({titles.get(b['slide'], '')[:30]}): {b['text']}  "
                  f"<{', '.join(b['evidence_ids'])}>")
    if st.get("preview"):
        print(f"  preview (open it before deciding): {st['preview']['path']}")
    if snap.interrupts:
        print(f"  waiting for a decision: {snap.interrupts[0].value['decisions']}")
    for e in st.get("approval_log") or []:      # a refusal's reason, else the approver's comment
        print(f"  log {e['at']} {e['outcome']} by {e.get('approver_employee_id')}: "
              f"{e.get('reason') or e.get('comment') or ''}")
    if st.get("normalized"):
        print(f"  slot-form fixes made by code (D-P7-14): {len(st['normalized'])}")
    if st.get("published"):
        print(f"  published: {st['published']['folder']}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--week", type=int, required=True, choices=range(1, 53), metavar="1..52")
    r.add_argument("--as", dest="employee", type=int, required=True)
    s = sub.add_parser("show")
    s.add_argument("--thread", required=True)
    d = sub.add_parser("resume")
    d.add_argument("--thread", required=True)
    d.add_argument("--as", dest="employee", type=int, required=True)
    d.add_argument("--decision", required=True, choices=["approve", "edit", "reject"])
    d.add_argument("--edits", type=Path)
    d.add_argument("--comment")
    lst = sub.add_parser("list")
    lst.add_argument("--week", type=int)
    sch = sub.add_parser("scheduled")
    sch.add_argument("--as", dest="employee", type=int)
    pr = sub.add_parser("prune")
    pr.add_argument("--dry-run", action="store_true")
    sub.add_parser("report")
    a = ap.parse_args()

    if a.cmd == "list":
        print("\n".join(threads(a.week)) or "no thread")
        return
    if a.cmd == "scheduled":
        raise SystemExit(scheduled(a.employee))
    g = graph()
    if a.cmd in ("prune", "report"):
        infos = scheduling.describe_all(g, checkpointer.pool(), PREFIX)
        if a.cmd == "prune":
            out = scheduling.prune(g, checkpointer.saver(), infos, LOG / "threads_archive.jsonl", dry_run=a.dry_run)
        else:
            out = scheduling.approval_report(scheduling.report_entries(g, infos, REPORTS))
        print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
        return
    if a.cmd == "show":
        show(g, {"configurable": {"thread_id": a.thread}})
        return
    if a.cmd == "run":
        user = context.load_user(a.employee)
        cfg = {"configurable": {"thread_id": next_attempt(a.week)}, "metadata": {"run_as": a.employee}}
        print(f"running week {a.week} as employee {a.employee} ({user.role} / {user.department})")
        with tracing.trace(cfg["configurable"]["thread_id"], entry="run", run_as=a.employee) as traced:
            for upd in g.stream({"report_week": a.week}, cfg, context=context.RunContext(user),
                                stream_mode="updates", durability="sync"):
                print("  done:", ", ".join(k for k in upd if not k.startswith("__")) or "interrupt")
    else:
        cfg = {"configurable": {"thread_id": a.thread}}
        # the run keeps its identity (P5-5): the tools after an edit and the publisher's record act as the employee
        # who started the pack (checkpoint metadata), not as the approver, who only decides (checked in the graph)
        run_as = next((s.metadata.get("run_as") for s in g.get_state_history(cfg) if s.metadata.get("run_as")), None)
        if run_as is None:
            raise SystemExit(f"thread {a.thread}: no run identity in its checkpoints (not started by this CLI)")
        ctx = context.RunContext(context.load_user(run_as))
        decision = {"decision": a.decision, "approver_employee_id": a.employee, "comment": a.comment}
        if a.edits:
            decision["edits"] = json.loads(a.edits.read_text(encoding="utf-8"))
        with tracing.trace(a.thread, entry="resume", run_as=run_as) as traced:
            for upd in g.stream(Command(resume=decision), cfg, context=ctx, stream_mode="updates",
                                durability="sync"):
                print("  done:", ", ".join(k for k in upd if not k.startswith("__")) or "interrupt")
    print(f"  LangSmith: {f'traced in project {tracing.PROJECT}' if traced else 'off (no LANGSMITH_API_KEY)'}")
    show(g, cfg)


if __name__ == "__main__":
    main()
