"""Finance Q&A check (Agents plan §5f F2, D-P7-6 / D-P7-7): the `create_agent` Q&A agent on fake models.

Plan:    docs/plans/Agents_plan.md §5f (owner decisions 2026-10-22: the Q&A on LangChain create_agent; its own check).
Run:     uv run python tools/run.py pipelines/scripts/agents/Finance_qa_check.py  (from the project root)

Reads:   PostgreSQL read-only through the real Stage 1 tools (finance_kpi), employees / roles. No LLM call (scripted
         fake models only); no LangSmith trace (the key is blanked for this process).
Writes:  nothing.
Re-run:  safe.

Phases
1. The model adapter's answer paths: a plain-text reply → the answer asked for through `structured` → answered; the
   model calling the answer tool itself → answered without a structured call; two invalid answers → output_invalid.
2. The middleware: the answer brief on every request (the evidence ids once a tool ran); after 3 tool rounds only the
   answer tool is bound.
3. The code check + one patch: a typed number fixed by the patch → answered; wrong twice → validation_failed.
4. RBAC with the real tools: an Operations employee asking for receivables → the tool refuses → not_permitted, no
   number; an "answered" over a refused tool → patched, then validation_failed.
5. Limits and records: an answer tool called with invalid arguments every time → the call limit ends the run →
   output_invalid; usage, calls and slot-form fixes recorded.
6. The operator CLI (`Finance_qa.py answer`) on fake models: summary keys, untraced without a key.
Final Checkpoint (pending phases listed).
"""
# %% Setup
import os
import sys
from pathlib import Path

from langchain_core.messages import AIMessage

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "pipelines" / "scripts" / "agents"))
os.environ["LANGSMITH_API_KEY"] = os.environ["LANGCHAIN_API_KEY"] = ""      # no trace from a check (§5e P8-4)
import Finance_qa as cli  # noqa: E402

from pipelines.agents import roles  # noqa: E402
from pipelines.agents.graphs import finance_qa as qa  # noqa: E402
from pipelines.agents.graphs import models as m  # noqa: E402
from pipelines.agents.tools import context, db  # noqa: E402

DONE: list[int] = []
people = db.fetch("SELECT e.employee_id, r.role_name, d.department_name FROM employees e "
                  "JOIN roles r USING (role_id) JOIN departments d USING (department_id) ORDER BY e.employee_id")


def first(role, dept):
    return next(p["employee_id"] for p in people if (p["role_name"], p["department_name"]) == (role, dept))


FIN_EMP, OPS_EMP = context.load_user(first("employee", "Finance")), context.load_user(first("employee", "Operations"))
KPI = ("finance_kpi", {"report_week": 23, "dataset": "weekly"})
GOOD = "NileGate billed {insight.c1:billed_sdr|M} in week 23 of 2025."


def names(tools) -> list[str]:
    return sorted(qa._tool_name(t) for t in tools or [])


class Script:
    """FakeRoles script: `plan` = what each model call returns, in order; the last entry repeats."""

    def __init__(self, plan):
        self.plan, self.n, self.seen = plan, 0, []

    def __call__(self, role, msgs, tools, schema):
        step = self.plan[min(self.n, len(self.plan) - 1)]
        self.n += 1
        self.seen.append({"schema": schema.__name__ if schema else None, "tools": names(tools),
                          "brief": msgs[-1].content if msgs else ""})
        kind, val = step
        if kind == "tool":
            return AIMessage(content="", tool_calls=[{"name": val[0], "args": val[1], "id": f"c{self.n}"}])
        if kind == "text":
            return AIMessage(content=val)
        if kind == "answer_call":                       # the model calls the answer tool itself
            return AIMessage(content="", tool_calls=[{"name": qa.ANSWER_TOOL, "args": val, "id": f"a{self.n}"}])
        if kind == "structured":                       # only for a structured() request
            assert schema is m.QaAnswer, f"step {self.n}: expected a structured request, got tools {names(tools)}"
            return val
        raise ValueError(kind)


def run(plan, user=FIN_EMP, question="How much did we bill in week 23?", lang="en"):
    s = Script(plan)
    st = qa.ask(qa.build_graph(roles.FakeRoles(s)), question, user, lang, thread="check")
    return s, st


ans = lambda text, status="answered", ids=("insight.c1",): {"status": status, "answer": text,  # noqa: E731
                                                            "evidence_ids": list(ids)}

# %% Phase 1 — The adapter's answer paths
s_a, a = run([("tool", KPI), ("text", "found it"), ("structured", ans(GOOD))])
s_b, b = run([("tool", KPI), ("answer_call", ans(GOOD))])
s_c, c = run([("tool", KPI), ("text", "found it"), ("structured", {"status": "maybe", "answer": 3})])
actual = {"fallback": (a["status"], a["rendered"][:22], [x["schema"] for x in s_a.seen]),
          "direct": (b["status"], b["rendered"][:22], [x["schema"] for x in s_b.seen]),
          "invalid": (c["status"], c["stop_reason"][:10])}
expected = {"fallback": ("answered", "NileGate billed 8.39 M", [None, None, "QaAnswer"]),
            "direct": ("answered", "NileGate billed 8.39 M", [None, None]),
            "invalid": ("output_invalid", "qa_answer:")}
assert actual == expected, {k: (actual[k], expected[k]) for k in actual if actual[k] != expected[k]}
print(f"Phase 1: {actual}")
print("✅ Phase 1 validation passed: plain text → structured answer; the answer tool called directly; two invalid "
      "answers → output_invalid")
DONE.append(1)

# %% Phase 2 — The middleware: brief and tool cap
s_d, d = run([("tool", KPI), ("tool", KPI), ("tool", KPI), ("text", "enough"), ("structured", ans(GOOD))])
tools_per_call = [x["tools"] for x in s_d.seen]
actual = {"status": d["status"], "brief_every_call": all("Evidence you may cite" in x["brief"] for x in s_d.seen),
          "ids_after_tool": "insight.c1" in s_d.seen[1]["brief"], "first_has_none": "(none yet" in s_d.seen[0]["brief"],
          "stage1_bound": ["finance_kpi" in t for t in tools_per_call[:4]],
          "answer_tool_always": all(qa.ANSWER_TOOL in t for t in tools_per_call[:4]),
          "fourth_only_answer": tools_per_call[3] == [qa.ANSWER_TOOL], "evidence": len(d["evidence"])}
expected = {"status": "answered", "brief_every_call": True, "ids_after_tool": True, "first_has_none": True,
            "stage1_bound": [True, True, True, False], "answer_tool_always": True, "fourth_only_answer": True,
            "evidence": 3}
assert actual == expected, {k: (actual[k], expected[k]) for k in actual if actual[k] != expected[k]}
print(f"Phase 2: tools per call {[len(t) for t in tools_per_call]}")
print("✅ Phase 2 validation passed: the brief on every request (evidence ids once a tool ran); after 3 tool rounds "
      "only the answer tool")
DONE.append(2)

# %% Phase 3 — Check + one patch
TYPED = "NileGate billed 8.99 M SDR in week 23 of 2025."
s_e, e = run([("tool", KPI), ("answer_call", ans(TYPED)), ("answer_call", ans(GOOD))])
s_f, f = run([("tool", KPI), ("answer_call", ans(TYPED))])
actual = {"fixed": (e["status"], e.get("patches"), e["problems"]),
          # the patch message is in the stored history (the brief is added per request, not stored)
          "patch_in_history": any(str(getattr(x, "content", "")).startswith("Your answer had these problems")
                                  for x in e["messages"]),
          "twice": (f["status"], f.get("patches"), bool(f["problems"]) and "typed as text" in f["problems"][0])}
expected = {"fixed": ("answered", 1, []), "patch_in_history": True, "twice": ("validation_failed", 1, True)}
assert actual == expected, {k: (actual[k], expected[k]) for k in actual if actual[k] != expected[k]}
print(f"Phase 3: {actual}")
print("✅ Phase 3 validation passed: a typed number fixed by one patch; wrong twice → validation_failed")
DONE.append(3)

# %% Phase 4 — RBAC with the real tools
q = "What were our receivables in week 23?"
_, g_ = run([("tool", KPI), ("answer_call", ans("Your role has no access to NileGate's receivables (Finance data).",
                                                "not_permitted"))], user=OPS_EMP, question=q)
_, h = run([("tool", KPI), ("answer_call", ans(GOOD))], user=OPS_EMP, question=q)
actual = {"refused_tool": g_["evidence"]["insight.c1"]["status"], "status": g_["status"], "bound": g_["bound"],
          "answered_over_refusal": (h["status"], any("refused" in p for p in h["problems"]))}
expected = {"refused_tool": "not_permitted", "status": "not_permitted", "bound": [],
            "answered_over_refusal": ("validation_failed", True)}
assert actual == expected, {k: (actual[k], expected[k]) for k in actual if actual[k] != expected[k]}
print(f"Phase 4: {actual}")
print("✅ Phase 4 validation passed: the tool refuses an Operations employee → not_permitted, no number; an answer "
      "over a refused tool → validation_failed")
DONE.append(4)

# %% Phase 5 — Limits and records
s_i, i = run([("answer_call", {"status": "answered"})])            # invalid arguments every time
FIXABLE = "NileGate billed {insight.c1:billed_sdr|n} in week 23 of 2025."   # a count format on money → default M
_, j = run([("tool", KPI), ("answer_call", ans(FIXABLE))])
actual = {"limit": (i["status"], len(i["llm_usage"]), s_i.n), "calls": j["calls"],
          "normalized": bool(j["normalized"]), "fixed_status": j["status"], "usage_nodes": {u["node"] for u in j["llm_usage"]}}
expected = {"limit": ("output_invalid", qa.MAX_MODEL_CALLS, qa.MAX_MODEL_CALLS),
            "calls": {"insight.c1": {"tool": "finance_kpi", "args": KPI[1]}}, "normalized": True,
            "fixed_status": "answered", "usage_nodes": {"qa_agent"}}
assert actual == expected, {k: (actual[k], expected[k]) for k in actual if actual[k] != expected[k]}
print(f"Phase 5: {actual}")
print("✅ Phase 5 validation passed: the call limit ends a run with invalid answers (output_invalid); usage, calls "
      "and slot-form fixes recorded")
DONE.append(5)

# %% Phase 6 — The operator CLI on fake models
st, traced = cli.answer("How much did we bill in week 23?", FIN_EMP.employee_id,
                        roles=roles.FakeRoles(Script([("tool", KPI), ("answer_call", ans(GOOD))])))
out = cli.summary(st)
actual = {"keys": sorted(out), "status": out["status"], "evidence_tool": out["evidence"]["insight.c1"]["tool"],
          "traced": traced}
expected = {"keys": ["answer", "cached", "evidence", "model_calls", "problems", "status", "stop_reason"],
            "status": "answered", "evidence_tool": "finance_kpi", "traced": False}
assert actual == expected, {k: (actual[k], expected[k]) for k in actual if actual[k] != expected[k]}
print(f"Phase 6: {out['answer']}")
print("✅ Phase 6 validation passed: the CLI answers through the agent and is untraced without a key")
DONE.append(6)

# %% Final Checkpoint
# Narrative: pipelines/checkpoints/agents/Finance_qa_check.md (every step, its problems and their fixes).
PHASES = {1: "answer paths", 2: "middleware", 3: "check + patch", 4: "RBAC", 5: "limits + records", 6: "CLI"}
pending = [f"{k} {v}" for k, v in PHASES.items() if k not in DONE]
print(f"Final Checkpoint: done {DONE}; pending: {pending}")
print(f"✅ Final Checkpoint: {len(DONE)} / {len(PHASES)} phases passed")
