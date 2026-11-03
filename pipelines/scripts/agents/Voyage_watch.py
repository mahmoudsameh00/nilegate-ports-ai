"""Run and read the voyage watch (C Voyage & Disruption Watch, Agents plan Phase 11 §6c; the graph:
`graphs/voyage_watch.py`).

Commands (from the project root):
    uv run python pipelines/scripts/agents/Voyage_watch.py run --as 2 [--as-of 2026-09-13T00:00]
        one watch of the whole fleet as employee 2 (role and department from PostgreSQL; the tools apply RBAC,
        ADR-006): ETAs, alerts, the brief; thread `voyage_watch:<as_of>:<n>` in agent_state, the run file
        reports/voyage_watch/<thread>.json (save only, P11-5); traced in LangSmith when LANGSMITH_API_KEY is set
    uv run python pipelines/scripts/agents/Voyage_watch.py scheduled [--as 2]
        what Windows Task Scheduler runs every 12 h (P11-7): resume a run stopped mid-way, else the next instant of
        the replay (the data's as-of instant − 7 days … the as-of instant, every 12 h), else nothing ("done"); then
        the 30-day retention of the watch threads; one line in reports/_log/voyage_watch.jsonl; a Windows toast when
        a run has high alerts. Identity: WATCH_RUN_AS in .env (an Operations manager), or --as
    uv run python pipelines/scripts/agents/Voyage_watch.py alerts --as 13 [--thread <id>] [--vessel 36] [--high]
        the saved alerts of the latest run (or of one thread), read on request (S2-D1); every employee may read
        them (level 1, P11-8), the identity is still checked
    uv run python pipelines/scripts/agents/Voyage_watch.py show <thread>     where a run stands and its result
    uv run python pipelines/scripts/agents/Voyage_watch.py list              the watch threads
    uv run python pipelines/scripts/agents/Voyage_watch.py prune [--dry-run] the 30-day retention by hand

Reads:   PostgreSQL read-only and MongoDB read-only through the tools, the voyage file, Open-Meteo + PortWatch
         (cached), the `writer` role's models (ADR-045; llm.py cache and quota) — one call per run with alerts.
Writes:  checkpoints in agent_state (login ports_agent); reports/voyage_watch/ (git-ignored); reports/_log/.
Re-run:  `run` always starts a new thread; `scheduled` never starts a second run while one is stalled (it resumes
         it) and starts nothing after the replay is complete.
Exit:    0 done; 1 the run raised (the thread waits at its checkpoint); 2 a database did not answer within
         PROBE_WAIT_MIN; 3 the scheduled identity is not an Operations manager.
"""
import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())
sys.path.insert(0, str(ROOT))
from pipelines.agents import checkpointer, monitoring, roles, scheduling, tracing  # noqa: E402
from pipelines.agents.graphs import voyage_watch as vw  # noqa: E402
from pipelines.agents.tools import context, db, mongo, watch  # noqa: E402
from pipelines.lib.common import load_env, redact  # noqa: E402

LOG = ROOT / "reports" / scheduling.LOG_DIR
PROBE_WAIT_MIN, PROBE_EVERY_S = 30, 60      # Docker Desktop starts after logon: the firing waits for the databases
LOCK_STALE_H = 2


def graph(with_models: bool = True):
    return vw.build_graph(roles.Roles() if with_models else None, checkpointer.saver(), vw.REPORTS_DIR)


def run(employee: int, as_of: datetime, g=None, launched_by: str = "cli") -> tuple[str, dict, bool]:
    """(thread id, final state, traced): one watch of the whole fleet."""
    user = context.load_user(employee)
    ctx = context.RunContext(user, as_of=as_of)                  # refuses a clock past the data
    g = g or graph()
    tid = vw.new_thread_id(checkpointer.pool(), as_of)
    cfg = {"configurable": {"thread_id": tid}, "metadata": {"run_as": employee, "trigger": launched_by}}
    monitoring.tag(thread_id=tid, run_as=employee)
    with tracing.trace(tid, entry="voyage_watch", run_as=employee, launched_by=launched_by,
                       extra_tags=("graph:voyage_watch",)) as traced:
        g.invoke({"request": {}}, cfg, context=ctx, durability="sync")
    return tid, g.get_state(cfg).values, traced


def summary(st: dict) -> dict:
    r = st.get("result") or {}
    usage = st.get("llm_usage") or []
    f = r.get("fleet") or {}
    return {"status": r.get("status"), "as_of": r.get("as_of"), "brief_status": r.get("brief_status"),
            "fleet": {k: f.get(k) for k in ("vessels_watched", "in_transit", "anchored", "alerts_total", "alerts_high",
                                            "alerts_moderate", "suez_ahead_vessels", "weather_points",
                                            "weather_unknown_points", "change_transits_pct")},
            "headline": r.get("headline"), "items": [i["text"] for i in r.get("items") or []],
            "alerts": [f"{a['alert_id']:<18} {a['severity']:<8} {a['vessel_name']} → {a['destination']} "
                       f"ETA {a['eta_utc']}: {a['reason']}" for a in (r.get("alerts") or [])[:25]],
            "assumptions": r.get("assumptions"), "problems": r.get("problems"), "run_file": r.get("run_file"),
            "model_calls": len(usage), "cached": sum(bool(c.get("cached")) for c in usage)}


# the saved-run readers live in the tool module since Phase 12 S2 (a tool must not import a script); kept as names here
# for the CLI's commands and Voyage_watch_check.py
can_read, run_files, read_alerts = watch.can_read, watch.run_files, watch.read_alerts


def probe() -> str | None:
    """None when PostgreSQL (both logins) and MongoDB answer, else the last error."""
    deadline, err = time.monotonic() + PROBE_WAIT_MIN * 60, None
    while True:
        try:
            with checkpointer.pool().connection() as conn:
                conn.execute("SELECT 1")
            db.fetch("SELECT 1 AS ok")
            mongo.database().command("ping")
            return None
        except Exception as exc:  # noqa: BLE001 — any failure to reach a database means "not yet"
            err = f"{type(exc).__name__}: {exc}"
            checkpointer.close()
            db.close()
        if time.monotonic() >= deadline:
            return err
        time.sleep(PROBE_EVERY_S)


def scheduled_tracer(thread_id: str, run_as: int | None):
    """The firing's graph run: a LangSmith trace, and the same thread id as a Sentry tag (the link between the two)."""
    monitoring.tag(thread_id=thread_id, run_as=run_as)
    return tracing.trace(thread_id, entry="voyage_watch", run_as=run_as, launched_by="task_scheduler",
                         extra_tags=("graph:voyage_watch",))


def scheduled(employee: int | None) -> int:
    LOG.mkdir(parents=True, exist_ok=True)
    rec = {"at": scheduling.now_utc().isoformat(timespec="seconds"), "cmd": "voyage_watch scheduled"}
    lock = LOG / "voyage_watch.lock"
    if lock.exists() and time.time() - lock.stat().st_mtime < LOCK_STALE_H * 3600:
        rec["skipped"] = "another firing is running (lock)"
        scheduling.append_jsonl(LOG / "voyage_watch.jsonl", rec)
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
        run_as = employee or int(os.environ.get("WATCH_RUN_AS") or 0)
        try:
            user = context.load_user(run_as) if run_as else None
        except PermissionError:               # an unknown employee id
            user = None
        if not scheduling.allowed_watch_run_as(user):
            rec["error"], code = f"scheduled identity {run_as or 'unset'} is not an Operations manager (WATCH_RUN_AS)", 3
            return code
        rec["run_as"] = run_as
        rec.update(scheduling.fire_watch(graph(), checkpointer.saver(), checkpointer.pool(), user,
                                         LOG / "threads_archive.jsonl", context.DATA_AS_OF, tracer=scheduled_tracer))
        res = rec.get("result") or {}
        if res.get("high"):
            rec["toast"] = scheduling.toast("NileGate Voyage Watch",
                                            f"{res['high']} high alert(s) of {res['alerts']} ({res['thread_id']})")
    except Exception as exc:  # noqa: BLE001 — logged for the owner; the thread (if any) waits at its checkpoint
        rec["error"], code = redact(f"{type(exc).__name__}: {exc}")[:600], 1
        rec["trace"] = redact(traceback.format_exc(limit=3))[-1200:]
        monitoring.capture(exc)
    finally:
        rec["exit"] = code
        scheduling.append_jsonl(LOG / "voyage_watch.jsonl", rec)
        lock.unlink(missing_ok=True)
        print(json.dumps({k: v for k, v in rec.items() if k != "trace"}, ensure_ascii=False, default=str, indent=1))
    return code


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--as", dest="employee", type=int, required=True)
    r.add_argument("--as-of", help="YYYY-MM-DDTHH:MM (UTC; default: the data's as-of instant)")
    sch = sub.add_parser("scheduled")
    sch.add_argument("--as", dest="employee", type=int)
    al = sub.add_parser("alerts")
    al.add_argument("--as", dest="employee", type=int, required=True)
    al.add_argument("--thread")
    al.add_argument("--vessel", type=int)
    al.add_argument("--high", action="store_true")
    s = sub.add_parser("show")
    s.add_argument("thread")
    sub.add_parser("list")
    pr = sub.add_parser("prune")
    pr.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    monitoring.init(entry=f"voyage_watch:{a.cmd}", launched_by="task_scheduler" if a.cmd == "scheduled" else "cli")

    if a.cmd == "scheduled":                      # errors only: the free plan's one cron monitor is the weekly pack's
        raise SystemExit(scheduled(a.employee))
    if a.cmd == "run":
        as_of = (datetime.strptime(a.as_of, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc) if a.as_of
                 else context.DATA_AS_OF)
        tid, st, traced = run(a.employee, as_of)
        print(json.dumps({"thread": tid, **summary(st)}, ensure_ascii=False, indent=1, default=str))
        print(f"LangSmith: {tracing.describe(traced)}")
        return
    if a.cmd == "alerts":
        out = read_alerts(context.load_user(a.employee), a.thread, a.vessel, a.high)
        print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
        return
    g = graph(with_models=False)                                  # reading only: no model is called
    if a.cmd == "show":
        st = g.get_state({"configurable": {"thread_id": a.thread}}).values
        print(json.dumps(summary(st) if st else {"error": f"no thread {a.thread}"}, ensure_ascii=False, indent=1,
                         default=str))
        return
    infos = scheduling.describe_voyage_watch(g, checkpointer.pool())
    if a.cmd == "list":
        for i in infos:
            print(f"{i.thread_id}  {i.state:<8} {i.status or '-'}  {i.last_at:%Y-%m-%d %H:%M}  run_as {i.run_as}")
        print(f"{len(infos)} run(s); next: {scheduling.plan_watch(infos, context.DATA_AS_OF).reason}")
        return
    out = scheduling.prune(g, checkpointer.saver(), [scheduling.as_thread_info(i) for i in infos],
                           LOG / "threads_archive.jsonl", dry_run=a.dry_run)
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
