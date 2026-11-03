"""Ask NileGate's supervisor one question — finance, operations or both (Agents plan Phase 12, §6d S4; the agent:
`pipelines/agents/graphs/supervisor.py`). Replaces the Stage 1 CLI `Finance_qa.py` (owner, 2026-10-29).

Commands (from the project root):
    uv run python pipelines/scripts/agents/Ask.py ask "Where is Cruise Voyager 234 now?" --as 12
    uv run python pipelines/scripts/agents/Ask.py ask "كام فوترنا في الأسبوع 23 من 2025؟" --as 13
    uv run python pipelines/scripts/agents/Ask.py ask "…" --as 13 [--lang en|ar] [--as-of 2026-09-10T12:00]
        one question as employee 13 (role and department from PostgreSQL): the code router picks the tools, drops the
        ones this user may not use (that part is named in the answer, never guessed), the agent answers with every
        number filled by code from the tools; prints the status, the answer, the refused part, the evidence, the
        code check's problems, the model calls (fresh / cached) and the thread. The language is detected from the
        question unless --lang is given; the clock defaults to the data's as-of instant and may only move back.
        One thread `ask:<employee>:<as_of>:<n>` in agent_state per question; traced in LangSmith (project
        nilegate-agents) when LANGSMITH_API_KEY is set.
    uv run python pipelines/scripts/agents/Ask.py show <thread> --as 13     a stored answer (the asker or the CEO)
    uv run python pipelines/scripts/agents/Ask.py list --as 13              the asker's questions (the CEO: all)
    uv run python pipelines/scripts/agents/Ask.py prune [--dry-run]         the 30-day retention by hand

Reads:   PostgreSQL / MongoDB read-only through the tools, the saved watch runs, Qdrant + Gemini + Jina for document
         questions, PortWatch / Tavily (cached) for a route's context, the `tools` role's models (ADR-045; llm.py
         cache and quota: a repeated question is answered from the cache, 0 calls) and, for a route question, the
         `writer` role (one call, the route advice).
Writes:  checkpoints in agent_state (login ports_agent): the question's thread (+ a route advice's own thread);
         reports/_log/threads_archive.jsonl on prune; LangSmith traces when a key exists.
Re-run:  `ask` always starts a new thread; `show` / `list` read only.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())
sys.path.insert(0, str(ROOT))
from pipelines.agents import checkpointer, monitoring, scheduling, tracing  # noqa: E402
from pipelines.agents import roles as roles_mod  # noqa: E402
from pipelines.agents.graphs import supervisor as sv  # noqa: E402
from pipelines.agents.tools import context  # noqa: E402

LOG = ROOT / "reports" / scheduling.LOG_DIR


def graph(roles=None, saver=None, pool=None):
    saver = saver or checkpointer.saver()
    return sv.build_graph(roles, saver, saver=saver, pool=pool or checkpointer.pool())


def answer(question: str, employee: int, lang: str | None = None, as_of: datetime | None = None, roles=None,
           launched_by: str = "cli") -> tuple[dict, bool]:
    """(final state, traced). `roles` = `Roles()` (real models) unless a check passes `FakeRoles`."""
    user = context.load_user(employee)
    as_of = context.RunContext(user, as_of=as_of or context.DATA_AS_OF).as_of      # refuses a clock past the data
    lang = lang or sv.detect_lang(question)
    r = sv.route(question, user)
    g = graph(roles or roles_mod.Roles())
    tid = sv.new_thread_id(checkpointer.pool(), employee, as_of)
    # `refused` alone lets one LangSmith rule filter (has(tags, "refused")) find every partial answer (Observability S3)
    tags = ("graph:supervisor", f"lang:{lang}", *(["refused"] if r.refused else []), *[f"refused:{t}" for t in r.refused])
    monitoring.tag(thread_id=tid, run_as=employee)
    with tracing.trace(tid, entry="ask", run_as=employee, launched_by=launched_by, extra_tags=tags) as traced:
        st = sv.ask(g, question, user, lang, as_of, thread=tid, metadata={"trigger": launched_by})
    return st, traced


def summary(st: dict) -> dict:
    usage = st.get("llm_usage") or []
    status = st.get("status")
    return {"thread": st.get("thread_id"), "status": "output_invalid" if status in (None, "running") else status,
            "answer": st.get("rendered"),
            "not_permitted": [sv.REFUSED_PART.get(t, t) for t in st.get("refused") or []],
            "evidence": {eid: {"tool": r.get("tool"), "status": r.get("status"),
                               "source": (r.get("source") or {}).get("name")}
                         for eid, r in sorted((st.get("evidence") or {}).items())},
            "problems": st.get("problems") or [], "stop_reason": st.get("stop_reason"),
            "model_calls": len(usage), "cached": sum(bool(c.get("cached")) for c in usage)}


def owner_of(thread_id: str) -> int | None:
    head = thread_id.removeprefix(sv.THREAD_PREFIX).split(":", 1)[0]
    return int(head) if thread_id.startswith(sv.THREAD_PREFIX) and head.isdigit() else None


def can_read(viewer, thread_id: str) -> bool:
    """A stored answer may hold the asker's finance figures: the asker and the CEO only (S4 decision 4)."""
    return viewer.role == "ceo" or owner_of(thread_id) == viewer.employee_id


def show(thread_id: str, viewer, g=None) -> dict:
    if not can_read(viewer, thread_id):
        return {"error": f"not permitted: {thread_id} is another employee's question (the asker and the CEO only)"}
    g = g or graph()
    st = g.get_state({"configurable": {"thread_id": thread_id}}).values
    return {**summary({**st, "thread_id": thread_id}), "question": st.get("question")} if st else \
        {"error": f"no thread {thread_id}"}


def questions(viewer, g=None) -> list:
    g = g or graph()
    prefix = sv.THREAD_PREFIX if viewer.role == "ceo" else f"{sv.THREAD_PREFIX}{viewer.employee_id}:"
    return scheduling.describe_ask(g, checkpointer.pool(), prefix)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("ask")
    a.add_argument("question")
    a.add_argument("--as", dest="employee", type=int, required=True)
    a.add_argument("--lang", choices=["en", "ar"])
    a.add_argument("--as-of", help="YYYY-MM-DDTHH:MM in UTC (default: the data's as-of instant)")
    s = sub.add_parser("show")
    s.add_argument("thread")
    s.add_argument("--as", dest="employee", type=int, required=True)
    li = sub.add_parser("list")
    li.add_argument("--as", dest="employee", type=int, required=True)
    pr = sub.add_parser("prune")
    pr.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    monitoring.init(entry=f"ask:{args.cmd}")

    if args.cmd == "ask":
        as_of = (datetime.fromisoformat(args.as_of).replace(tzinfo=timezone.utc) if args.as_of else None)
        st, traced = answer(args.question, args.employee, args.lang, as_of)
        print(json.dumps(summary(st), ensure_ascii=False, indent=1, default=str))
        print(f"LangSmith: {tracing.describe(traced)}")
        return
    g = graph()                                                   # reading only: no model is called
    if args.cmd == "prune":
        out = scheduling.prune(g, checkpointer.saver(), scheduling.describe_ask(g, checkpointer.pool()),
                               LOG / "threads_archive.jsonl", dry_run=args.dry_run)
        print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
        return
    viewer = context.load_user(args.employee)
    if args.cmd == "show":
        print(json.dumps(show(args.thread, viewer, g), ensure_ascii=False, indent=1, default=str))
        return
    infos = questions(viewer, g)
    for i in infos:
        print(f"{i.thread_id}  {i.state:<8} {i.status or '-'}  {i.last_at:%Y-%m-%d %H:%M}")
    print(f"{len(infos)} question(s)")


if __name__ == "__main__":
    main()
