"""Run the Weekly Finance Pack for one report week, and decide on it (Agents plan §5b, P5-4 / P5-5).

Commands (from the project root):
    uv run python pipelines/scripts/agents/Weekly_pack.py run --week 23 --as 12
        start a new attempt of week 23 as employee 12 (a Finance manager: the pack's run identity); it stops at the
        approval (prints the draft with bullet numbers) or at a stated stop status
    uv run python pipelines/scripts/agents/Weekly_pack.py show --thread weekly_pack:live:2025-W23:1
        where a thread stands, and the draft waiting for a decision
    uv run python pipelines/scripts/agents/Weekly_pack.py resume --thread weekly_pack:live:2025-W23:1 --as 12 \
        --decision approve | reject | edit [--edits edits.json] [--comment "…"]
        decide as employee 12 (a Finance manager or the CEO, checked in PostgreSQL); edits.json =
        [{"bullet": 3, "text": "…"}] — an edit goes back through the Validator and waits again
    uv run python pipelines/scripts/agents/Weekly_pack.py list [--week 23]
        the threads in agent_state

Reads:   PostgreSQL (read-only tools; the checkpoints through ports_agent), the LLM APIs of ADR-045 (cached), the
         external tools (cached). Writes: checkpoints in agent_state; on approval reports/2025-W<ww>/ (git-ignored).
Re-run:  `run` always starts a new attempt (a new thread); `resume` continues one. The evaluation copy
         (`dataset="test"`) is not offered here: only the evaluation harness sets it (ADR-049).
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())
sys.path.insert(0, str(ROOT))
from langgraph.types import Command  # noqa: E402

from pipelines.agents import checkpointer, roles  # noqa: E402
from pipelines.agents.graphs import weekly_pack as wp  # noqa: E402
from pipelines.agents.tools import context  # noqa: E402

PREFIX = "weekly_pack:live:2025-W"


def threads(week: int | None = None) -> list[str]:
    like = f"{PREFIX}{week:02d}:%" if week else f"{PREFIX}%"
    with checkpointer.pool().connection() as conn:
        rows = conn.execute("SELECT DISTINCT thread_id FROM checkpoints WHERE thread_id LIKE %s ORDER BY 1",
                            (like,)).fetchall()
    return [r["thread_id"] for r in rows]


def next_attempt(week: int) -> str:
    used = [int(t.rsplit(":", 1)[1]) for t in threads(week) if t.rsplit(":", 1)[1].isdigit()]
    return f"{PREFIX}{week:02d}:{max(used, default=0) + 1}"


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
    if draft:
        print(f"  {draft['title']}")
        titles = {t["slide"]: t["title"] for t in draft["slide_titles"]}
        for i, b in enumerate(draft["bullets"]):
            print(f"  [{i:2d}] slide {b['slide']:2d} ({titles.get(b['slide'], '')[:30]}): {b['text']}  "
                  f"<{', '.join(b['evidence_ids'])}>")
    if snap.interrupts:
        print(f"  waiting for a decision: {snap.interrupts[0].value['decisions']}")
    for e in st.get("approval_log") or []:
        print(f"  log {e['at']} {e['outcome']} by {e.get('approver_employee_id')}: {e.get('reason') or ''}")
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
    a = ap.parse_args()

    if a.cmd == "list":
        print("\n".join(threads(a.week)) or "no thread")
        return
    g = graph()
    if a.cmd == "show":
        show(g, {"configurable": {"thread_id": a.thread}})
        return
    if a.cmd == "run":
        user = context.load_user(a.employee)
        cfg = {"configurable": {"thread_id": next_attempt(a.week)}, "metadata": {"run_as": a.employee}}
        print(f"running week {a.week} as employee {a.employee} ({user.role} / {user.department})")
        for upd in g.stream({"report_week": a.week}, cfg, context=context.RunContext(user), stream_mode="updates",
                            durability="sync"):
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
        for upd in g.stream(Command(resume=decision), cfg, context=ctx, stream_mode="updates", durability="sync"):
            print("  done:", ", ".join(k for k in upd if not k.startswith("__")) or "interrupt")
    show(g, cfg)


if __name__ == "__main__":
    main()
