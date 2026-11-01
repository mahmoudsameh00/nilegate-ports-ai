"""Ask the route advisor (B Route & Cost Advisor, Agents plan Phase 10 §6b; the graph: `graphs/route_advice.py`).

Commands (from the project root):
    uv run python pipelines/scripts/agents/Route_advice.py ask --vessel 36 --from SGSIN --to NLRTM --as 13
    uv run python pipelines/scripts/agents/Route_advice.py ask --type Containerships --condition Laden --scnt 85000 \
        --from SGSIN --to NLRTM --as 13 [--speed 14] [--as-of 2026-09-13]
        one question as employee 13 (role and department from PostgreSQL; the tools apply RBAC, ADR-006): prints the
        status, the recommendation, the comparison table, the reasons and risks with their numbers filled from the
        tools, the assumptions and the sources; one thread `route_advice:<employee>:<as_of>:<from>-<to>:<n>` in
        agent_state (P10-3); traced in LangSmith (project nilegate-agents) when LANGSMITH_API_KEY is set.
    uv run python pipelines/scripts/agents/Route_advice.py show <thread>     the stored answer of a thread
    uv run python pipelines/scripts/agents/Route_advice.py list --as 13      that employee's questions

Reads:   PostgreSQL read-only through the tools, searoute locally, PortWatch + Tavily (cached), the `writer` role's
         models (ADR-045; llm.py cache and quota).
Writes:  checkpoints in agent_state (login ports_agent); deleted after 30 days by the retention
         (`Weekly_pack.py prune`, and every scheduled firing). LangSmith traces when a key exists.
Re-run:  `ask` always starts a new thread; `show` / `list` read only.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())
sys.path.insert(0, str(ROOT))
from pipelines.agents import checkpointer, monitoring, roles as roles_mod, scheduling, tracing  # noqa: E402
from pipelines.agents.graphs import route_advice as ra  # noqa: E402
from pipelines.agents.graphs.models import RouteRequest  # noqa: E402
from pipelines.agents.tools import context  # noqa: E402


def ask(req: RouteRequest, employee: int, as_of: datetime, roles=None) -> tuple[str, dict, bool]:
    """(thread id, final state, traced). `roles` = `Roles()` (real models) unless a check passes `FakeRoles`."""
    user = context.load_user(employee)
    ctx = context.RunContext(user, as_of=as_of)                  # refuses a clock past the data
    g = ra.build_graph(roles or roles_mod.Roles(), checkpointer.saver())
    tid = ra.new_thread_id(checkpointer.pool(), employee, as_of, req.origin, req.destination)
    cfg = {"configurable": {"thread_id": tid}, "metadata": {"run_as": employee, "trigger": "cli"}}
    monitoring.tag(thread_id=tid, run_as=employee)
    with tracing.trace(tid, entry="route_advice", run_as=employee, extra_tags=("graph:route_advice",)) as traced:
        g.invoke({"request": req.model_dump(mode="json")}, cfg, context=ctx, durability="sync")
    return tid, g.get_state(cfg).values, traced


def summary(st: dict) -> dict:
    r = st.get("result") or {}
    usage = st.get("llm_usage") or []
    return {"status": r.get("status"), "recommendation": r.get("recommendation"), "headline": r.get("headline"),
            "comparison": r.get("comparison"), "reasons": r.get("reasons"), "risks": r.get("risks"),
            "assumptions": r.get("assumptions"), "problems": r.get("problems"),
            "sources": [f"{s['evidence']}: {s['tool']} {s['status']} — {s.get('name')} ({s.get('filter')})"
                        for s in r.get("sources") or []],
            "model_calls": len(usage), "cached": sum(bool(c.get("cached")) for c in usage)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("ask")
    a.add_argument("--vessel", type=int)
    a.add_argument("--type", dest="vessel_type")
    a.add_argument("--condition", choices=["Laden", "Ballast"])
    a.add_argument("--scnt", type=float)
    a.add_argument("--from", dest="origin", required=True)
    a.add_argument("--to", dest="destination", required=True)
    a.add_argument("--speed", type=float)
    a.add_argument("--as", dest="employee", type=int, required=True)
    a.add_argument("--as-of", help="YYYY-MM-DD, the departure day (default: the data's as-of instant)")
    s = sub.add_parser("show")
    s.add_argument("thread")
    li = sub.add_parser("list")
    li.add_argument("--as", dest="employee", type=int, required=True)
    args = ap.parse_args()
    monitoring.init(entry=f"route_advice:{args.cmd}")

    if args.cmd == "ask":
        req = RouteRequest(vessel_id=args.vessel, vessel_type=args.vessel_type, condition=args.condition,
                           scnt_tons=args.scnt, origin=args.origin.upper(), destination=args.destination.upper(),
                           speed_kn=args.speed)
        as_of = (datetime.strptime(args.as_of, "%Y-%m-%d").replace(tzinfo=timezone.utc) if args.as_of
                 else context.DATA_AS_OF)
        tid, st, traced = ask(req, args.employee, as_of)
        print(json.dumps({"thread": tid, **summary(st)}, ensure_ascii=False, indent=1, default=str))
        print(f"LangSmith: {tracing.describe(traced)}")
        return
    g = ra.build_graph(None, checkpointer.saver())               # reading only: no model is called
    if args.cmd == "show":
        st = g.get_state({"configurable": {"thread_id": args.thread}}).values
        print(json.dumps(summary(st) if st else {"error": f"no thread {args.thread}"}, ensure_ascii=False, indent=1,
                         default=str))
        return
    infos = scheduling.describe_route_advice(g, checkpointer.pool(), f"{ra.THREAD_PREFIX}{args.employee}:")
    for i in infos:
        print(f"{i.thread_id}  {i.state:<8} {i.status or '-'}  {i.last_at:%Y-%m-%d %H:%M}")
    print(f"{len(infos)} question(s)")


if __name__ == "__main__":
    main()
