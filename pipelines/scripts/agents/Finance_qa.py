"""Ask the finance Q&A agent one question (Agents plan §5f K6; the agent: `pipelines/agents/graphs/finance_qa.py`).

Commands (from the project root):
    uv run python pipelines/scripts/agents/Finance_qa.py ask "How much did we bill in week 23?" --as 13
    uv run python pipelines/scripts/agents/Finance_qa.py ask "كام فاتورة اتأخرت في أسبوع 49؟" --as 13 --lang ar
        one question as employee 13 (the role and department come from PostgreSQL; the tools apply RBAC, ADR-006):
        prints the status, the answer with its numbers filled from the tools, the evidence (tool, source) and any
        problem the code check found; traced in LangSmith (project nilegate-agents) when LANGSMITH_API_KEY is set.

Reads:   PostgreSQL read-only through the tools, Qdrant + Gemini + Jina for document questions, the `tools` role's
         models (ADR-045; llm.py cache and quota: a repeated question is answered from the cache, 0 calls).
Writes:  nothing (no checkpointer: one question, one run); LangSmith traces when a key exists.
Re-run:  safe.
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())
sys.path.insert(0, str(ROOT))
from pipelines.agents import roles as roles_mod  # noqa: E402
from pipelines.agents import tracing  # noqa: E402
from pipelines.agents.graphs import finance_qa as qa  # noqa: E402
from pipelines.agents.tools import context  # noqa: E402


def answer(question: str, employee: int, lang: str = "en", roles=None) -> tuple[dict, bool]:
    """(final state, traced). `roles` = `Roles()` (real models) unless a check passes `FakeRoles`."""
    user = context.load_user(employee)
    graph = qa.build_graph(roles or roles_mod.Roles())
    thread = f"qa:cli:{employee}:{time.time_ns()}"
    with tracing.trace(thread, entry="qa", run_as=employee, extra_tags=(f"lang:{lang}",)) as traced:
        st = qa.ask(graph, question, user, lang, thread=thread)
    return st, traced


def summary(st: dict) -> dict:
    return {"status": st.get("status"), "answer": st.get("rendered"),
            "evidence": {eid: {"tool": r.get("tool"), "status": r.get("status"),
                               "source": (r.get("source") or {}).get("name")}
                         for eid, r in sorted((st.get("evidence") or {}).items())},
            "problems": st.get("problems") or [], "stop_reason": st.get("stop_reason"),
            "model_calls": len(st.get("llm_usage") or []),
            "cached": sum(bool(c.get("cached")) for c in st.get("llm_usage") or [])}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("ask")
    a.add_argument("question")
    a.add_argument("--as", dest="employee", type=int, required=True)
    a.add_argument("--lang", choices=["en", "ar"], default="en")
    args = ap.parse_args()
    st, traced = answer(args.question, args.employee, args.lang)
    print(json.dumps(summary(st), ensure_ascii=False, indent=1, default=str))
    print(f"LangSmith: {f'traced in project {tracing.PROJECT}' if traced else 'off (no LANGSMITH_API_KEY)'}")


if __name__ == "__main__":
    main()
