"""Weekly pack check (Agents plan Phase 5, §5b): the `weekly_pack` graph, its models and roles, node by node.

Plan:    docs/plans/Agents_plan.md §5b (owner decisions P5-1…P5-8, approved 2026-10-19); one phase per test of §5b.
Run:     uv run python tools/run.py pipelines/scripts/agents/Weekly_pack_check.py  (from the project root)

Reads:   PostgreSQL read-only (PG_RO_USER): employees / roles / departments, the finance views, the audit views.
         No LLM call in Phases 0–3 and 6 (stub and scripted fake models only).
Writes:  a throw-away temp folder for the published packs (the real `reports/` is never touched); checkpoints in
         memory (InMemorySaver), except Phase 4: one thread in agent_state (login ports_agent), deleted at the end.
Re-run:  safe (read-only on the database).

Phases (§5b "Tests")
0. Models and roles (S1): format rules of the structured outputs; the role rules — availability → fallback,
   validity → one retry then stop — with stub models; FakeRoles through the real parser.
1. Deterministic nodes (S2) on all 52 weeks: readiness gate, KPI and audit evidence = the tool functions called
   directly; a forced not-ready week and an Operations employee stop after the gate with no number in the state.
2. Fake-LLM pack (S3) on all 52 weeks to the interrupt and published on approve; the approval rules (P5-4, G5).
3. Validator loop (S3): a planted wrong number rewritten once; an always-wrong Writer stopped; 18 rule cases.
4. Crash and resume (S5): a subprocess killed inside the Writer; this process resumes the thread from PostgreSQL.
6. Contract (S3): no user / dataset field in a tool schema; the dataset only from the run context; search cap.
Final Checkpoint (pending phases listed).
"""
# %% Setup
import json
import os
import sys
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage
from pydantic import ValidationError

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())
sys.path.insert(0, str(ROOT))
from pipelines.agents import llm, roles  # noqa: E402
from pipelines.agents.graphs import models as m  # noqa: E402
from pipelines.lib import common  # noqa: E402

common.load_env(ROOT)
E = os.environ
DONE: list[int] = []

# %% Phase 0 — Models and roles (S1)
# The structured outputs hold format rules only (slide range, evidence-id shape, a verdict passes exactly when it has
# no problem, edits exactly with an "edit" decision); content rules are the Validator's. Roles: a model that is not
# available (quota, no key, cached failure) hands over to the fallback of another provider (ADR-045); a model that
# answers with an invalid object gets one retry with the error, then the run stops (StructuredError) — no silent switch.
draft = m.DeckDraft(title="NileGate Weekly Finance Pack — 2025-W23 — Draft for approval",
                    slide_titles=[m.SlideTitle(slide=i, title=f"t{i}") for i in range(1, m.SLIDES + 1)],
                    bullets=[m.Bullet(slide=2, text="Billed 1.23 M SDR", evidence_ids=["kpi.weekly"])])
round_trip = m.DeckDraft.model_validate(draft.model_dump(mode="json")) == draft
invalid = {"slide 11": lambda: m.Bullet(slide=11, text="x"),
           "web evidence id": lambda: m.Cited(text="x", evidence_ids=["web.1"]),
           "edit without edits": lambda: m.ApprovalDecision(decision="edit", approver_employee_id=3),
           "approve with edits": lambda: m.ApprovalDecision(decision="approve", approver_employee_id=3,
                                                            edits=[m.Edit(bullet=0, text="y")]),
           "passed with problems": lambda: m.Verdict(passed=True, problems=[m.Problem(rule="V2", message="x")])}
refused = []
for name, make in invalid.items():
    try:
        make()
    except ValidationError:
        refused.append(name)


class _Stub:
    """A model behind llm.LLM's interface: replies (or exceptions) in order."""

    def __init__(self, replies):
        self.replies = list(replies)

    def invoke(self, messages, tools=None, schema=None, method=None):
        nxt = self.replies.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return llm.Reply("k", nxt, None, True, 1.0, {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})


def _fc(args):
    return AIMessage(content="", tool_calls=[{"name": "Verdict", "args": args, "id": "1"}])


MAIN, FALLBACK = roles.ROLES["writer"]


def _role(main, fallback):
    r = roles.Role("writer", roles.ROLES["writer"], quota=None, cache_dir=None)
    r._llms = {MAIN.name: _Stub(main), FALLBACK.name: _Stub(fallback)}
    return r


def _outcomes(reply):
    return [c["outcome"].split(":")[0] for c in reply.calls]


Q = [HumanMessage("x")]
_has_key = llm.has_key
llm.has_key = lambda provider: True
role_cases = {}
r = _role([llm.Exhausted("quota")], [_fc({"passed": True})]).structured(Q, m.Verdict)
role_cases["exhausted → fallback"] = (r.model, _outcomes(r))
r = _role([_fc({"passed": "maybe"}), _fc({"passed": True})], []).structured(Q, m.Verdict)
role_cases["invalid → retry ok"] = (r.model, _outcomes(r), r.calls[-1]["total_tokens"])
try:
    _role([_fc({"passed": "?"}), _fc({"passed": "?"})], [_fc({"passed": True})]).structured(Q, m.Verdict)
    role_cases["invalid twice"] = "accepted"
except roles.StructuredError:
    role_cases["invalid twice"] = "StructuredError"
r = _role([llm.Exhausted("q")], [AIMessage(content="hi")]).invoke(Q)
role_cases["chat fallback"] = r.model
try:
    _role([llm.Exhausted("q")], [llm.Exhausted("q")]).invoke(Q)
    role_cases["both exhausted"] = "answered"
except llm.Exhausted:
    role_cases["both exhausted"] = "Exhausted"
llm.has_key = lambda provider: provider != MAIN.provider   # no key for the main → the fallback, no call to the main
r = _role([AssertionError("the main was called")], [AIMessage(content="hi")]).invoke(Q)
role_cases["no key → fallback"] = (r.model, _outcomes(r))
llm.has_key = _has_key


def _script(role, msgs, tools, schema):
    return {"passed": True, "problems": []} if schema is m.Verdict else AIMessage(content="hello")


fake = roles.FakeRoles(_script)
fake_ok = (fake.get("writer").structured(Q, m.Verdict).parsed == m.Verdict(passed=True)
           and fake.get("insight").invoke(Q).message.content == "hello")
try:
    roles.FakeRoles(lambda *a: {"passed": "?"}).get("writer").structured(Q, m.Verdict)
    fake_invalid = "accepted"
except roles.StructuredError:
    fake_invalid = "StructuredError"

actual = {"round_trip": round_trip, "refused": sorted(refused), "roles": sorted(roles.ROLES),
          "role_pairs": {n: [c.name for c in cs] for n, cs in roles.ROLES.items()}, "role_cases": role_cases,
          "fake_ok": fake_ok, "fake_calls": fake.calls, "fake_invalid": fake_invalid}
expected = {"round_trip": True, "refused": sorted(invalid), "roles": ["insight", "tools", "writer"],
            # ADR-045 amendment (owner 2026-10-19): the pack's Insight / Writer prompts do not fit Groq's 8K TPM
            "role_pairs": {"insight": ["gemini/gemini-3.5-flash-lite", "openrouter/nvidia/nemotron-3-super-120b-a12b:free"],
                           "writer": ["gemini/gemini-3.5-flash-lite", "openrouter/nvidia/nemotron-3-super-120b-a12b:free"],
                           "tools": ["gemini/gemini-3.5-flash-lite", "groq/openai/gpt-oss-20b"]},
            "role_cases": {"exhausted → fallback": (FALLBACK.name, ["exhausted", "ok"]),
                           "invalid → retry ok": (MAIN.name, ["invalid", "ok"], 15),
                           "invalid twice": "StructuredError", "chat fallback": FALLBACK.name,
                           "both exhausted": "Exhausted",
                           "no key → fallback": (FALLBACK.name, ["no_key", "ok"])},
            "fake_ok": True, "fake_calls": {"writer": 1, "insight": 1}, "fake_invalid": "StructuredError"}
assert actual == expected, actual
print(f"Phase 0: role cases {len(role_cases)}, invalid objects refused {len(refused)} / {len(invalid)}")
print("✅ Phase 0 validation passed: models round trip, format rules refuse 5 invalid objects, ADR-045 role pairs, "
      "fallback on availability, one retry then stop on validity, FakeRoles through the real parser")
DONE.append(0)

# %% Phase 1 — Deterministic nodes (S2)
# Data Readiness, KPI and Auditor are code, not agents (P5-1): readiness gates the week (R1 KPI row, R2 invoices,
# R3 no key nulls, R4 payments loaded through the as-of date); KPI and Auditor call the same tool functions the
# LangChain tools wrap, with the run's user from the context. The pack runs as a Finance manager (P5-5). Expected:
# all 52 weeks ready, warm-up notes on weeks 1–13, evidence = the tools called directly, the audit = the 3 reviewed
# live duplicates (weeks 10 / 15 / 50, Tools_check.py LIVE_FINDINGS). A week whose invoices are missing (forced) and
# an Operations employee stop at the gate: nothing after readiness runs and no number enters the state.
import tempfile  # noqa: E402
from decimal import ROUND_HALF_UP, Decimal  # noqa: E402

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.types import Command  # noqa: E402

from pipelines.agents.graphs import weekly_pack as wp  # noqa: E402
from pipelines.agents.tools import context, db  # noqa: E402

people = db.fetch("SELECT e.employee_id, r.role_name, d.department_name FROM employees e "
                  "JOIN roles r USING (role_id) JOIN departments d USING (department_id) ORDER BY e.employee_id")


def _first(role, dept=None):
    return next(p["employee_id"] for p in people if p["role_name"] == role and dept in (None, p["department_name"]))


fin_mgr = context.load_user(_first("manager", "Finance"))
ops_emp = context.load_user(_first("employee", "Operations"))
ops_mgr_id, ceo_id = _first("manager", "Operations"), _first("ceo")


# --- the fake models' script: replies built from the week's evidence (independent formatting) -----------------------
def _q(v, d):
    return Decimal(str(v)).quantize(Decimal(1).scaleb(-d), rounding=ROUND_HALF_UP)


def m_sdr(v, signed=False):       # millions, 2 decimals, half away from zero, the sign kept ("−" in the deck)
    q = _q(Decimal(str(v)) / 10 ** 6, 2)
    return (("+" if q > 0 else "") if signed else "") + f"{q:.2f}".replace("-", "−") + " M SDR"


def pct(v):
    return "n/a" if v is None else (("+" if v > 0 else "") + f"{_q(v, 2):.2f}".replace("-", "−") + " %")


class PackScript:
    """FakeRoles script. mode: good | wrong_once (the first draft carries a wrong number) | always_wrong.
    extra_audit: the Insight agent also calls invoice_audit through the ToolNode (the dataset contract)."""

    def __init__(self, mode="good", extra_audit=False):
        self.mode, self.extra_audit, self.week, self.ev = mode, extra_audit, None, None

    def set_week(self, week, ev):
        self.week, self.ev = week, ev

    def __call__(self, role, msgs, tools, schema):
        w = self.week
        if schema is None:                                   # insight_llm: one tool round, then a text answer
            if any(x.type == "tool" for x in msgs):
                return AIMessage(content="Findings ready.")
            calls = [{"name": "finance_kpi", "args": {"report_week": w, "dataset": "category"}, "id": f"cat_{w}"}]
            if self.extra_audit:
                calls.append({"name": "invoice_audit", "args": {"report_week": w}, "id": f"aud_{w}"})
            return AIMessage(content="", tool_calls=calls)
        k = self.ev["kpi.weekly"]["rows"][0]
        cats = self.ev["kpi.category"]["rows"]
        aud = self.ev["audit.week"]
        if schema is m.InsightNotes:
            flagged = {r["vessel_category"] for r in aud["rows"]}
            summary = [
                m.Cited(text=f"Billed {m_sdr(k['billed_sdr'])} in week {w} of 2025, {pct(k['billed_wow_pct'])} WoW",
                        evidence_ids=["kpi.weekly"]),
                m.Cited(text=f"Budget variance {m_sdr(k['budget_variance_sdr'], True)} "
                             f"({pct(k['budget_variance_pct'])})", evidence_ids=["kpi.weekly"]),
                m.Cited(text="Top drivers: " + ", ".join(c["vessel_category"] for c in cats[:3]),
                        evidence_ids=["kpi.category"]),
                m.Cited(text=f"AR {m_sdr(k['ar_sdr'])}, DSO {k['dso_days']} days", evidence_ids=["kpi.weekly"]),
                m.Cited(text=f"{aud['invoices_checked']} invoices checked, {aud['invoices_flagged']} flagged",
                        evidence_ids=["audit.week"])]
            drivers = [m.Driver(vessel_category=c["vessel_category"],
                                direction="up" if (c["billed_wow_change_sdr"] if c["billed_wow_change_sdr"]
                                                   is not None else c["budget_variance_sdr"]) >= 0 else "down",
                                flagged_by_audit=c["vessel_category"] in flagged, explanation="largest change",
                                evidence_ids=["kpi.category"]) for c in cats[:3]]
            return m.InsightNotes(summary=summary, drivers=drivers, caveats=[])
        assert schema is m.DeckDraft, schema
        notes = m.InsightNotes.model_validate(
            json.loads(msgs[-1].content.split("[insight notes]\n")[1].split("\n\n[validator]")[0]))
        rewrite = "[validator]" in msgs[-1].content
        wrong = self.mode == "always_wrong" or (self.mode == "wrong_once" and not rewrite)
        bullets = [m.Bullet(slide=1, text=f"{k['iso_week_label']}, {k['week_start']} to {k['week_end']}",
                            evidence_ids=["kpi.weekly"])]
        bullets += [m.Bullet(slide=2, text=s.text, evidence_ids=s.evidence_ids) for s in notes.summary]
        if wrong:                                      # a planted wrong number: billed + 0.01 M
            bullets[1] = m.Bullet(slide=2, text=f"Billed {m_sdr(k['billed_sdr'] + 10_000)} in week {w}",
                                  evidence_ids=["kpi.weekly"])
        bullets.append(m.Bullet(slide=3, text=f"Collected {k['collected_sdr']:,.2f} SDR; overdue "
                                              f"{m_sdr(k['overdue_sdr'])}", evidence_ids=["kpi.weekly"]))
        for o in self.ev["kpi.overdue"]["rows"][:1]:
            bullets.append(m.Bullet(slide=6, text=f"Largest overdue {o['invoice_number']}: {o['amount_sdr']:,.2f} "
                                                  f"SDR, {o['days_past_due']} days past due",
                                    evidence_ids=["kpi.overdue"]))
        for f in aud["rows"]:
            bullets.append(m.Bullet(slide=8, text=f"{f['invoice_number']}: {f['check_code']}, "
                                                  f"{f['difference_sdr']:,.2f} SDR at stake",
                                    evidence_ids=["audit.week"]))
        if not aud["rows"]:
            bullets.append(m.Bullet(slide=8, text=f"{aud['invoices_checked']} invoices checked, none flagged",
                                    evidence_ids=["audit.week"]))
        bullets.append(m.Bullet(slide=10, text="Sources: finance.kpi_weekly, finance.invoice_audit, "
                                               f"report_week = {w}", evidence_ids=["kpi.weekly"]))
        return m.DeckDraft(title=f"NileGate Weekly Finance Pack — {k['iso_week_label']} — Draft for approval",
                           slide_titles=[m.SlideTitle(slide=i, title=f"Slide title {chr(64 + i)}")
                                         for i in range(1, m.SLIDES + 1)], bullets=bullets)


script = PackScript()
fake = roles.FakeRoles(script)
REPORTS = Path(tempfile.mkdtemp(prefix="weekly_pack_check_"))
graph = wp.build_graph(fake, checkpointer=InMemorySaver(), reports_dir=REPORTS)
_threads = iter(range(1, 10_000))


def run(user, week, dataset="live", g=None, until=None, sc=None):
    """Start one run on a fresh thread: (visited nodes, state values, config). `until` = interrupt before a node."""
    g, sc = g or graph, sc or script
    sc.set_week(week, {**wp.kpi_evidence(fin_mgr, week), **wp.audit_evidence(fin_mgr, week, dataset)})
    cfg = {"configurable": {"thread_id": f"weekly_pack:{dataset}:2025-W{week:02d}:{next(_threads)}"}}
    visited = _stream(g, {"report_week": week}, cfg, context.RunContext(user, dataset), until)
    return visited, g.get_state(cfg).values, cfg


def _stream(g, inp, cfg, ctx, until=None):
    visited = []
    for upd in g.stream(inp, cfg, context=ctx, stream_mode="updates",
                        **({"interrupt_before": [until]} if until else {})):
        visited += [k for k in upd if not k.startswith("__")]
    return visited


def resume(cfg, decision, user=None, g=None, dataset="live"):
    g = g or graph
    visited = _stream(g, Command(resume=decision), cfg, context.RunContext(user or fin_mgr, dataset))
    return visited, g.get_state(cfg)


# --- Phase 4's crash child: this script re-run in a subprocess with CRASH_ENV set runs one pack on PostgresSaver and
# dies inside the Writer (os._exit: no cleanup, no exception handler, like a killed process); nothing below runs
CRASH_ENV, CRASH_CODE = "WEEKLY_PACK_CRASH_THREAD", 77
if os.environ.get(CRASH_ENV):
    from pipelines.agents import checkpointer

    _sc = PackScript()

    def _dying(role, msgs, tools, schema):
        if schema is m.DeckDraft:
            print("crash child: killed inside writer", flush=True)
            os._exit(CRASH_CODE)
        return _sc(role, msgs, tools, schema)

    _g = wp.build_graph(roles.FakeRoles(_dying), checkpointer.saver(), REPORTS / "crash_child")
    _sc.set_week(23, {**wp.kpi_evidence(fin_mgr, 23), **wp.audit_evidence(fin_mgr, 23, "live")})
    for _ in _g.stream({"report_week": 23}, {"configurable": {"thread_id": os.environ[CRASH_ENV]}},
                       context=context.RunContext(fin_mgr), stream_mode="updates", durability="sync"):
        pass
    print("crash child: the writer did not run", flush=True)
    os._exit(1)


paths, ready, warmup, equal, findings, keys = set(), 0, [], 0, {}, set()
for w in range(1, 53):
    visited, st, _ = run(fin_mgr, w, until="insight_llm")
    paths.add(tuple(visited))
    ready += st["readiness"]["ready"] and st["status"] == "running"
    if st["readiness"]["notes"]:
        warmup.append(w)
    keys |= set(st["evidence"])
    direct = {**wp.kpi_evidence(fin_mgr, w), **wp.audit_evidence(fin_mgr, w, "live")}
    equal += st["evidence"] == direct
    for f in st["evidence"]["audit.week"]["rows"]:
        findings[w] = findings.get(w, []) + [(f["invoice_number"], f["check_code"], f["duplicate_of"])]
    assert all(st["evidence"][k]["status"] == "ok" for k in st["evidence"]), (w, {k: v["status"] for k, v in
                                                                                  st["evidence"].items()})


class _NoInvoices:
    """db with the week's invoices missing: the gate must stop the run (R2)."""

    def fetch(self, sql, params=(), exact=False):
        if sql == wp.READINESS_SQL["invoices"]:
            return [{"n": 0, "key_nulls": 0}]
        return db.fetch(sql, params, exact)


wp.db = _NoInvoices()
try:
    forced_path, forced, _ = run(fin_mgr, 23)
finally:
    wp.db = db
denied_path, denied, _ = run(ops_emp, 23)


def numbers_in(state) -> int:
    return len(state.get("evidence") or {}) + len((state["readiness"].get("facts") or {}))


actual = {"pack_user": (fin_mgr.role, fin_mgr.department), "paths": sorted(paths), "weeks_ready": ready,
          "warmup_weeks": warmup, "evidence_keys": sorted(keys), "evidence_equal_direct": equal,
          "live_findings": findings,
          "forced": (forced_path, forced["status"], forced["readiness"]["checks"]["R2_invoices"],
                     numbers_in(forced) - 3),        # facts of the gate itself (invoices, as-of, horizon) only
          "denied": (denied_path, denied["status"], numbers_in(denied))}
expected = {"pack_user": ("manager", "Finance"), "paths": [("readiness", "kpi", "audit")], "weeks_ready": 52,
            "warmup_weeks": list(range(1, 14)),
            "evidence_keys": ["audit.week", "kpi.category", "kpi.customers", "kpi.overdue", "kpi.trend",
                              "kpi.weekly"],
            "evidence_equal_direct": 52,
            "live_findings": {10: [("INV-0000626", "duplicate_charge", "INV-0000293")],
                              15: [("INV-0000925", "duplicate_charge", "INV-0000491")],
                              50: [("INV-0000630", "duplicate_charge", "INV-0000262")]},
            "forced": (["readiness"], "not_ready", False, 0),
            "denied": (["readiness"], "not_permitted", 0)}
assert actual == expected, actual
assert fake.calls == {}, f"an LLM was called before the agent steps: {fake.calls}"
print(f"Phase 1: 52 weeks {ready} ready, findings in weeks {sorted(findings)}, forced reasons "
      f"{forced['readiness']['reasons']}")
print("✅ Phase 1 validation passed: readiness / kpi / audit on 52 weeks = the tools, warm-up notes 1–13, live audit "
      "= the 3 reviewed duplicates, a not-ready week and an Operations employee stop at the gate with no number")
DONE.append(1)

# %% Phase 2 — Fake-LLM pack on 52 weeks + approval (S3)
# The whole graph with scripted models (P5-7): Insight calls finance_kpi through the ToolNode (the run context reaches
# the tool: its result = the tool called directly), then notes, the Writer's draft, the Validator, the interrupt. Every
# week must reach the approval with a passing verdict and be published on "approve" (three files; the title loses
# "Draft for approval"). Then the approval rules on week 23 (P5-4): reject ends with nothing saved; an edit with a
# wrong number fails the Validator and comes back without "approve"; an approve of a failing draft, an Operations
# manager, an unknown employee and a malformed decision are refused and asked again; a correct edit passes; the CEO
# may approve. The approval log keeps every step (G5).
weeks_ok, published, tool_equal, interrupt_paths = 0, 0, 0, set()
for w in range(1, 53):
    visited, st, cfg = run(fin_mgr, w)
    snap = graph.get_state(cfg)
    payload = snap.interrupts[0].value if snap.interrupts else {}
    interrupt_paths.add(tuple(dict.fromkeys(visited)))
    weeks_ok += (snap.next == ("approval",) and st["status"] == "awaiting_approval" and st["verdict"]["passed"]
                 and payload.get("decisions") == ["approve", "edit", "reject"])
    direct = wp.finance.finance_kpi(fin_mgr, report_week=w, dataset="category").model_dump(mode="json")
    tool_equal += st["evidence"].get(f"insight.cat_{w}") == direct
    _, snap = resume(cfg, {"decision": "approve", "approver_employee_id": fin_mgr.employee_id})
    out = snap.values
    folder = REPORTS / f"2025-W{w:02d}"
    published += (out["status"] == "published" and sorted(p.name for p in folder.iterdir())
                  == ["approval.json", "deck_draft.json", "run.json"]
                  and "Approved" in json.loads((folder / "deck_draft.json").read_text(encoding="utf-8"))["title"]
                  and "Draft for approval" not in out["draft"]["title"] and not snap.next)

W = 23
# reject
g_rej = wp.build_graph(fake, InMemorySaver(), REPORTS / "reject")
_, st, cfg = run(fin_mgr, W, g=g_rej)
snap = resume(cfg, {"decision": "reject", "approver_employee_id": fin_mgr.employee_id, "comment": "not now"},
              g=g_rej)[1]
reject_case = (snap.values["status"], snap.next, (REPORTS / "reject").exists())

# edits and refusals
g_ed = wp.build_graph(fake, InMemorySaver(), REPORTS / "edit")
_, st, cfg = run(fin_mgr, W, g=g_ed)
billed_idx = 1                                              # first executive-summary bullet
steps = []


def step(decision):
    snap = resume(cfg, decision, g=g_ed)[1]
    steps.append((snap.values["approval_log"][-1]["outcome"], snap.values["verdict"]["passed"], snap.next,
                  (snap.interrupts[0].value["decisions"] if snap.interrupts else None)))
    return snap


k23 = script.ev["kpi.weekly"]["rows"][0]
step({"decision": "edit", "approver_employee_id": fin_mgr.employee_id,
      "edits": [{"bullet": billed_idx, "text": "Billed 9.99 M SDR in week 23 of 2025"}]})
step({"decision": "approve", "approver_employee_id": fin_mgr.employee_id})
step({"decision": "edit", "approver_employee_id": ops_mgr_id,
      "edits": [{"bullet": billed_idx, "text": "Billed x"}]})
step({"decision": "approve", "approver_employee_id": 999_999})
step({"decision": "maybe", "approver_employee_id": fin_mgr.employee_id})
step({"decision": "edit", "approver_employee_id": fin_mgr.employee_id,
      "edits": [{"bullet": 99, "text": "x"}]})
step({"decision": "edit", "approver_employee_id": fin_mgr.employee_id,
      "edits": [{"bullet": billed_idx, "text": f"Billing was {m_sdr(k23['billed_sdr'])} in week 23 of 2025"}]})
final = step({"decision": "approve", "approver_employee_id": ceo_id})
log = final.values["approval_log"]
edit_diff = log[0]["diff"][0]

actual = {"weeks_at_interrupt": weeks_ok, "published": published, "toolnode_equal_direct": tool_equal,
          "paths_to_interrupt": sorted(interrupt_paths), "reject": reject_case,
          "steps": steps, "final_status": final.values["status"],
          "log_outcomes": [e["outcome"] for e in log],
          "edit_diff": (edit_diff["slide"], "9.99" in edit_diff["after"]),
          "refusal_reasons": [e["reason"].split(":")[0].split(" (")[0] for e in log if e["outcome"] == "refused"],
          "approvers": sorted({e["approver"] for e in log if e.get("approver")})}
expected = {"weeks_at_interrupt": 52, "published": 52, "toolnode_equal_direct": 52,
            "paths_to_interrupt": [("readiness", "kpi", "audit", "insight_llm", "insight_tools", "insight_notes",
                                    "writer", "validator")],
            "reject": ("rejected", (), False),
            "steps": [("edited", False, ("approval",), ["edit", "reject"]),
                      ("refused", False, ("approval",), ["edit", "reject"]),
                      ("refused", False, ("approval",), ["edit", "reject"]),
                      ("refused", False, ("approval",), ["edit", "reject"]),
                      ("refused", False, ("approval",), ["edit", "reject"]),
                      ("refused", False, ("approval",), ["edit", "reject"]),
                      ("edited", True, ("approval",), ["approve", "edit", "reject"]),
                      ("approved", True, (), None)],
            "final_status": "published",
            "log_outcomes": ["edited", "refused", "refused", "refused", "refused", "refused", "edited", "approved"],
            "edit_diff": (2, True),
            "refusal_reasons": ["the draft fails the Validator", "manager / Operations may not approve the finance "
                                "pack", "unknown employee 999999", "invalid decision", "no bullet [99] in the draft"],
            "approvers": ["ceo / Operations", "manager / Finance"]}
assert actual == expected, actual
print(f"Phase 2: 52 weeks published; week 23 approval steps {[s[0] for s in steps]}")
print("✅ Phase 2 validation passed: 52 / 52 weeks reach the approval with a passing verdict and are published on "
      "approve; ToolNode results = the tool; reject saves nothing; wrong edits / approvers / decisions refused; G5 log")
DONE.append(2)

# %% Phase 3 — Validator loop (S3)
# A first draft with a planted wrong number (billed + 10,000 SDR, shown as M) must be caught, sent back with the
# diff, rewritten and passed (one rewrite); a Writer that never fixes it stops after two rewrites with
# validation_failed and no interrupt. Then the rules themselves on hand-made evidence: allowed roundings (as
# returned; M 2 decimals; k 1 decimal; % 1–2 decimals; half away from zero; the sign kept), the bake-off's recorded
# error "849.9 k" for −849,964.00 refused, numbers of document / web rows never accepted (ADR-049), identifiers and
# dates blanked, unknown evidence refused (V1), the draft label (V3), the deck's shape (V4).
loop = {}
for mode in ("wrong_once", "always_wrong"):
    sc = PackScript(mode)
    g = wp.build_graph(roles.FakeRoles(sc), InMemorySaver(), REPORTS / mode)
    visited, st, cfg = run(fin_mgr, W, g=g, sc=sc)
    loop[mode] = (visited.count("writer"), visited.count("validator"), st["status"], st.get("rewrites"),
                  st["verdict"]["passed"], tuple(g.get_state(cfg).next),
                  sorted({p["token"] for p in st["verdict"]["problems"]}))

ev = {"kpi.weekly": {"tool": "finance_kpi", "status": "ok", "source": {"name": "v", "filter": "f"},
                     "rows": [{"billed_sdr": -1234567.89, "x_sdr": -849964.0, "pct": 25.835, "days": 55.3,
                               "label": "2025-W23", "start": "2025-06-02", "n": 19}]},
      "insight.web": {"tool": "web_search", "status": "ok", "source": {"name": "t", "filter": "q"},
                      "rows": [{"title": "Canal revenue 7.5 M", "rank": 7}]},
      "audit.week": {"tool": "invoice_audit", "status": "ok", "source": {"name": "a", "filter": "w"}, "rows": [],
                     "invoices_checked": 19, "amount_at_stake_sdr": 0.0}}


def verdict_of(texts, title="NileGate Weekly Finance Pack — 2025-W23 — Draft for approval", ids=("kpi.weekly",),
               five=True):
    bl = [{"slide": 2, "text": t, "evidence_ids": list(ids)} for t in texts]
    bl += [{"slide": 2, "text": "filler", "evidence_ids": []}] * ((5 - len(bl)) if five else 0)
    d = {"title": title, "slide_titles": [{"slide": i, "title": "t"} for i in range(1, 11)], "bullets": bl}
    return wp.validate(d, ev, 23)


rule_cases = {
    "as returned −1,234,567.89": verdict_of(["−1,234,567.89 SDR"]).passed,
    "M −1.23": verdict_of(["−1.23 M SDR"]).passed,
    "M sign dropped 1.23": verdict_of(["1.23 M SDR"]).passed,
    "k −850.0": verdict_of(["−850.0 k SDR"]).passed,
    "k cut 849.9": verdict_of(["−849.9 k SDR"]).passed,
    "% 25.84": verdict_of(["+25.84 %"]).passed,
    "% 25.8": verdict_of(["25.8 %"]).passed,
    "% ×100 2583.5": verdict_of(["2583.5 %"]).passed,
    "days 55.3": verdict_of(["DSO 55.3 days"]).passed,
    "days rounded 55": verdict_of(["DSO 55 days"]).passed,
    "week / year / ids allowed": verdict_of(["week 23 of 2025, 2025-W23 from 2025-06-02, 19 invoices"]).passed,
    "web number refused": verdict_of(["Canal revenue 7.5 M"], ids=("insight.web",)).passed,
    "audit total": verdict_of(["19 invoices checked"], ids=("audit.week",)).passed,
    "unknown evidence": verdict_of(["19 invoices"], ids=("kpi.nope",)).passed,
    "no evidence": verdict_of(["19 invoices"], ids=()).passed,
    "label missing (V3)": verdict_of(["19 invoices"], title="NileGate Weekly Finance Pack").passed,
    "four bullets (V4)": verdict_of(["19 invoices"], five=False).passed,
    "title number": verdict_of([], title="Pack — 7 invoices — Draft for approval").passed,
    "template: aging buckets": verdict_of(["Aging 1-30 days, 31–60, 61-90 and 90+ buckets"]).passed,
    "template: warm-up footnote": verdict_of(["Receivables still building up since 1 Jan 2025"]).passed,
    "template: 13-week, top 10": verdict_of(["13-week trend; top 10 customers"]).passed,
    "not template: 1-31 days": verdict_of(["Aging 1-31 days"]).passed,
    "template: 1 to 30, 90 plus": verdict_of(["Aging 1 to 30 days and 90 plus days"]).passed,
    "dates: prose / RFC / ISO / US": verdict_of(["Reported on 6 June 2025, Fri, 05 Dec 2025 00:00:00 GMT, "
                                                 "2025-12-07, June 6, 2025 and in June 2025"], ids=()).passed,
    "date does not hide an amount": verdict_of(["On 6 June 2025 revenue was 7.5 M"], ids=()).passed,
    "no evidence, week / year only": verdict_of(["Week 23 of 2025"], ids=()).passed,
}
wrong_token = m_sdr(script.ev["kpi.weekly"]["rows"][0]["billed_sdr"] + 10_000).removesuffix(" SDR")
actual = {"loop": loop, "rule_cases": rule_cases}
expected = {"loop": {"wrong_once": (2, 2, "awaiting_approval", 1, True, ("approval",), []),
                     "always_wrong": (3, 3, "validation_failed", 2, False, (), [wrong_token])},
            "rule_cases": {"as returned −1,234,567.89": True, "M −1.23": True, "M sign dropped 1.23": False,
                           "k −850.0": True, "k cut 849.9": False, "% 25.84": True, "% 25.8": True,
                           "% ×100 2583.5": False, "days 55.3": True, "days rounded 55": False,
                           "week / year / ids allowed": True, "web number refused": False, "audit total": True,
                           "unknown evidence": False, "no evidence": False, "label missing (V3)": False,
                           "four bullets (V4)": False, "title number": False, "template: aging buckets": True,
                           "template: warm-up footnote": True, "template: 13-week, top 10": True,
                           "not template: 1-31 days": False, "no evidence, week / year only": True,
                           "template: 1 to 30, 90 plus": True, "dates: prose / RFC / ISO / US": True,
                           "date does not hide an amount": False}}
assert actual == expected, actual
print(f"Phase 3: loop {loop['wrong_once'][:4]} / {loop['always_wrong'][:4]}; {len(rule_cases)} rule cases")
print("✅ Phase 3 validation passed: a planted wrong number caught and rewritten once; an always-wrong Writer stops "
      f"after two rewrites; {len(rule_cases)} rule cases (roundings, signs, ×100, web numbers, evidence, label, "
      "shape, template allowlist)")
DONE.append(3)

# %% Phase 4 — Crash and resume on PostgresSaver (S5)
# P5-6: a real process dies mid-run. A subprocess (this script with CRASH_ENV) starts week 23 on the PostgreSQL
# checkpointer (schema agent_state, login ports_agent, durability "sync") and calls os._exit inside the Writer. This
# process — another process, a fresh graph object, nothing in memory — reads the thread from PostgreSQL: it stands
# before `writer`; resuming runs only writer → validator → the approval interrupt (no readiness / KPI / audit /
# Insight step again: 0 new tool rounds, 1 LLM call = the Writer), and the approved result equals an uninterrupted
# run on InMemorySaver. The thread is deleted at the end (delete_thread: agent_writer's DELETE).
import subprocess  # noqa: E402
import uuid  # noqa: E402

from pipelines.agents import checkpointer  # noqa: E402

thread = f"weekly_pack:live:2025-W{W:02d}:check-{uuid.uuid4().hex[:8]}"
child = subprocess.run([sys.executable, str(Path(__file__).resolve())], cwd=ROOT, capture_output=True, text=True,
                       env={**os.environ, CRASH_ENV: thread}, timeout=300)
child_said = [ln for ln in child.stdout.splitlines() if ln.startswith("crash child")]

saver = checkpointer.saver()
counting = PackScript()
fr = roles.FakeRoles(counting)
g_pg = wp.build_graph(fr, saver, REPORTS / "crash")
cfg = {"configurable": {"thread_id": thread}}
before = g_pg.get_state(cfg)
n_checkpoints = sum(1 for _ in saver.list(cfg))
counting.set_week(W, {**wp.kpi_evidence(fin_mgr, W), **wp.audit_evidence(fin_mgr, W, "live")})
resumed = []
for upd in g_pg.stream(None, cfg, context=context.RunContext(fin_mgr), stream_mode="updates", durability="sync"):
    resumed += [k for k in upd if not k.startswith("__")]
waiting = g_pg.get_state(cfg)
calls_after_resume = dict(fr.calls)
for upd in g_pg.stream(Command(resume={"decision": "approve", "approver_employee_id": fin_mgr.employee_id}), cfg,
                       context=context.RunContext(fin_mgr), stream_mode="updates", durability="sync"):
    resumed += [k for k in upd if not k.startswith("__")]
done_pg = g_pg.get_state(cfg).values

# the same week without a crash, in memory
sc_mem = PackScript()
g_mem = wp.build_graph(roles.FakeRoles(sc_mem), InMemorySaver(), REPORTS / "no_crash")
_, _, cfg_mem = run(fin_mgr, W, g=g_mem, sc=sc_mem)
resume(cfg_mem, {"decision": "approve", "approver_employee_id": fin_mgr.employee_id}, g=g_mem)
done_mem = g_mem.get_state(cfg_mem).values
SAME = ("status", "evidence", "insight", "draft", "verdict", "rewrites", "readiness")
differs = [k for k in SAME if done_pg.get(k) != done_mem.get(k)]

saver.delete_thread(thread)
left = sum(1 for _ in saver.list(cfg))

actual = {"child_exit": child.returncode, "child_said": child_said, "stopped_before": before.next,
          "checkpoints_written": n_checkpoints > 0, "state_had": sorted(k for k in ("evidence", "insight", "messages")
                                                                         if before.values.get(k)),
          "resumed_nodes": resumed, "waiting_at": waiting.next, "llm_calls_after_resume": calls_after_resume,
          "final_status": done_pg["status"], "differs_from_uninterrupted": differs, "thread_rows_left": left}
expected = {"child_exit": CRASH_CODE, "child_said": ["crash child: killed inside writer"],
            "stopped_before": ("writer",), "checkpoints_written": True,
            "state_had": ["evidence", "insight", "messages"],
            "resumed_nodes": ["writer", "validator", "approval", "publisher"], "waiting_at": ("approval",),
            "llm_calls_after_resume": {"writer": 1}, "final_status": "published", "differs_from_uninterrupted": [],
            "thread_rows_left": 0}
assert actual == expected, (actual, child.stderr[-1500:])
print(f"Phase 4: child exit {child.returncode}, {n_checkpoints} checkpoints in agent_state, resumed {resumed}")
print("✅ Phase 4 validation passed: a process killed inside the Writer resumes from PostgreSQL in another process, "
      "only writer → validator → approval re-run (1 LLM call), result = the uninterrupted run; thread deleted")
DONE.append(4)

# %% Phase 5 — Real models on four weeks (S6)
# P5-7: the real models and tools (PortWatch, Tavily, search_documents) on weeks 5 (warm-up), 10 (a duplicate
# charge), 23 and 49. Each week must reach a stated end — published (approved by the Finance manager when the draft
# passes), validation_failed or output_invalid — never an exception. P5-8 measured on the first run (2026-10-19):
# the pack's prompts are 9.7K–17K tokens, above Groq's 8K TPM → owner: the pack's Insight / Writer run on
# gemini-3.5-flash-lite with OpenRouter nemotron as the fallback (ADR-045 amendment); the gate is now "every call
# within its provider's per-minute token limit" (llm.PROVIDERS). Every reply is cached by llm.py, so a re-run makes
# 0 model calls (`fresh_calls`). The full summary goes to Notebooks/_scratch/weekly_pack_real.json for review.
REAL_WEEKS = (5, 10, 23, 49)


def _tpm(model_name: str) -> int:
    return llm.PROVIDERS[model_name.split("/", 1)[0]]["tpm"]



real_roles = roles.Roles()
real = {}
for w in REAL_WEEKS:
    g_real = wp.build_graph(real_roles, InMemorySaver(), REPORTS / "real")
    cfg = {"configurable": {"thread_id": f"weekly_pack:live:2025-W{w:02d}:real"}}
    error = None
    try:
        _stream(g_real, {"report_week": w}, cfg, context.RunContext(fin_mgr))
    except Exception as exc:  # noqa: BLE001 — reported: a stop must be a status, never an exception
        error = f"{type(exc).__name__}: {str(exc)[:300]}"
    snap = g_real.get_state(cfg)
    st = snap.values
    if snap.next == ("approval",) and st.get("verdict", {}).get("passed"):
        resume(cfg, {"decision": "approve", "approver_employee_id": fin_mgr.employee_id}, g=g_real)
        st = g_real.get_state(cfg).values
    usage = st.get("llm_usage") or []
    bl = (st.get("draft") or {}).get("bullets", [])
    failing = sorted({p["bullet"] for p in (st.get("verdict") or {}).get("problems", []) if p.get("bullet") is not None})
    real[w] = {"status": st.get("status"), "stop_reason": st.get("stop_reason"), "error": error,
               "next": list(snap.next),
               "failing_bullets": [(i, bl[i]["slide"], bl[i]["text"], bl[i]["evidence_ids"]) for i in failing],
               "over_tpm": [(c["node"], c["model"], c["total_tokens"]) for c in usage
                            if (c["total_tokens"] or 0) > _tpm(c["model"])],
               "verdict_passed": (st.get("verdict") or {}).get("passed"), "rewrites": st.get("rewrites"),
               "problems": [(p["rule"], p.get("token"), p["message"][:80]) for p in
                            (st.get("verdict") or {}).get("problems", [])][:8],
               "tool_rounds": wp._tool_rounds(st.get("messages") or []),
               "tools_called": sorted({x.name for x in st.get("messages") or [] if x.type == "tool"}),
               "calls": [(c["node"], c["model"], c["outcome"][:40], c["cached"], c["total_tokens"]) for c in usage],
               "retries_or_fallbacks": sum(c["outcome"] != "ok" for c in usage),
               "fallbacks": sum(c["outcome"] == "ok" and not c["model"].startswith(roles.ROLES[c["role"]][0].name)
                                for c in usage),
               "fresh_calls": sum(not c["cached"] and c["outcome"] == "ok" for c in usage),
               "max_total_tokens": max((c["total_tokens"] or 0 for c in usage), default=0),
               "summary": [b["text"] for b in (st.get("draft") or {}).get("bullets", []) if b["slide"] == 2]}
(ROOT / "Notebooks" / "_scratch" / "weekly_pack_real.json").write_text(
    json.dumps(real, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
for w, r in real.items():
    print(f"Phase 5 week {w}: {r['status']} | verdict {r['verdict_passed']} | rewrites {r['rewrites']} | tools "
          f"{r['tools_called']} | calls {len(r['calls'])} (fresh {r['fresh_calls']}, retries / fallbacks "
          f"{r['retries_or_fallbacks']}, answered by the fallback {r['fallbacks']}) | "
          f"max tokens {r['max_total_tokens']} | error {r['error']}")
actual = {w: (r["error"] is None and r["status"] in ("published", "validation_failed", "output_invalid"),
              r["over_tpm"] == []) for w, r in real.items()}
expected = {w: (True, True) for w in REAL_WEEKS}
assert actual == expected, actual
# reviewed snapshot (2026-10-19, owner's decisions applied): the two validation_failed weeks fail only on real Writer
# errors the Validator must catch — a sign dropped next to "down" (number-validation rule 5) and a share cited from
# kpi.customers instead of kpi.weekly; carried to Phase 6 (Writer). Cached: a re-run makes 0 model calls.
reviewed = {w: (r["status"], r["fresh_calls"], r["fallbacks"]) for w, r in real.items()}
assert reviewed == {5: ("validation_failed", 0, 0), 10: ("published", 0, 0), 23: ("validation_failed", 0, 0),
                    49: ("published", 0, 0)}, reviewed
print("✅ Phase 5 validation passed: real models on weeks 5 / 10 / 23 / 49 reach a stated end (2 published, 2 "
      "validation_failed on real Writer errors), every LLM call within its provider's per-minute token limit, "
      "0 model calls on a re-run")
DONE.append(5)

# %% Phase 6 — Contract: schemas, dataset, search cap (S3)
# No tool the Insight agent can call shows a user, employee or dataset field to the model (ADR-049); the dataset
# reaches the audit only through the run context — with dataset="test" (set only by the evaluation harness) both
# the Auditor node and an invoice_audit call through the ToolNode read finance_test, live runs read finance;
# search_documents is capped at three passages in the pack whatever k the model asks (P5-8).
props = {t.name: t.tool_call_schema.model_json_schema().get("properties", {}) for t in wp.STAGE1_TOOLS}
schema_fields = {n: set(p) for n, p in props.items()}
# a user field, or any field that can select the evaluation copy (finance_kpi's `dataset` picks a KPI view, not the
# copy: it is caught only if its choices include "test" / "live")
leaky = {n: sorted({f for f, spec in p.items() if f in {"user", "employee_id", "employee", "runtime"}
                    or {"test", "live"} & set(spec.get("enum", []))}) for n, p in props.items()}
ds = {}
for dataset in ("live", "test"):
    sc = PackScript(extra_audit=True)
    g = wp.build_graph(roles.FakeRoles(sc), InMemorySaver(), REPORTS / f"ds_{dataset}")
    _, st, _ = run(fin_mgr, 10, dataset=dataset, g=g, sc=sc)
    ds[dataset] = (st["evidence"]["audit.week"]["source"]["name"], st["evidence"]["insight.aud_10"]["source"]["name"],
                   st["evidence"]["audit.week"]["invoices_flagged"])
caps = [wp._cap_search(AIMessage(content="", tool_calls=[{"name": "search_documents", "args": a, "id": "s"}]))
        .tool_calls[0]["args"].get("k") for a in ({"query": "q", "k": 8}, {"query": "q"}, {"query": "q", "k": 2})]
actual = {"leaky_fields": {n: f for n, f in leaky.items() if f}, "tools": sorted(schema_fields), "dataset": ds,
          "search_k": caps}
expected = {"leaky_fields": {}, "tools": ["compute_toll", "finance_kpi", "invoice_audit", "search_documents",
                                          "suez_transits", "web_search"],
            "dataset": {"live": ("finance.invoice_audit", "finance.invoice_audit", 1),
                        "test": ("finance_test.invoice_audit", "finance_test.invoice_audit", 2)},
            "search_k": [3, 3, 2]}
assert actual == expected, actual
print(f"Phase 6: {actual}")
print("✅ Phase 6 validation passed: no user / dataset field in any tool schema; the dataset only from the run "
      "context (node and ToolNode); search_documents capped at 3 passages")
DONE.append(6)

# %% Final Checkpoint
# Narrative: pipelines/checkpoints/agents/Weekly_pack_check.md (every step, its problems and their fixes).
PHASES = {0: "models + roles", 1: "deterministic nodes", 2: "fake-LLM pack on 52 weeks + approval",
          3: "Validator loop", 4: "crash and resume (PostgresSaver)", 5: "real models on 4 weeks",
          6: "contract (schemas, dataset)"}
import shutil  # noqa: E402

shutil.rmtree(REPORTS, ignore_errors=True)                  # the throw-away published packs
pending = [f"{k} {v}" for k, v in PHASES.items() if k not in DONE]
assert DONE == sorted(DONE) and set(DONE) <= set(PHASES)
print(f"Final Checkpoint: done {DONE}; pending: {pending}")
print(f"✅ Final Checkpoint: {len(DONE)} / {len(PHASES)} phases passed")
