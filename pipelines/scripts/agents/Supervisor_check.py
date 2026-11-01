"""Supervisor check (Agents plan Phase 12, §6d step S3): the code router, the answer check, the agent on fake models.

Plan:    docs/archive/2026-11-01_Agents_plan.md §6d and its S3 plan in Progress (APPROVED 2026-10-29 with the owner's answers: the
         router drops the tools a user may not use, the `load_skill` tool, the new skill `supervisor-qa`, the D-P12-2
         code rule).
Run:     uv run python tools/run.py pipelines/scripts/agents/Supervisor_check.py  (from the project root)

Reads:   PostgreSQL / MongoDB read-only through the tools, the voyage file, the saved watch runs, the frozen golden
         set Data/processed/agents/eval/supervisor_qa_golden.jsonl.
Writes:  route-advice threads of the agent's tool calls in agent_state (every one deleted at the end, also on a
         failure); a throw-away external cache. Nothing under Data/processed.
Re-run:  safe. 0 real model calls (FakeRoles), 0 Open-Meteo calls; PortWatch / Tavily answered by a mock transport.

Phases
1. The router on the golden questions + the access split = the tools' own access.
2. check_supervisor_answer on hand answers: right ones pass, every planted error is caught.
3. The agent end to end on scripted fake models for the golden items (+ the patch, validation_failed and the call
   limit); the largest model request measured in tokens.
4. RBAC inside the agent: a refused tool is never offered and never runs; every part refused → no model call.
Final Checkpoint (narrative: pipelines/checkpoints/agents/Supervisor_check.md).
"""
# %% Setup
import atexit
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

import httpx
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())
sys.path.insert(0, str(ROOT))
from pipelines.agents import checkpointer, roles, skill_loader  # noqa: E402
from pipelines.agents.graphs import route_advice as ra  # noqa: E402
from pipelines.agents.graphs import supervisor as sv  # noqa: E402
from pipelines.agents.graphs.models import RouteRequest  # noqa: E402
from pipelines.agents.tools import (context, db, eta, external, finance, fleet, registry, tariff, watch,  # noqa: E402
                                    weather)

GOLDEN = ROOT / "Data" / "processed" / "agents" / "eval" / "supervisor_qa_golden.jsonl"
GOLD = [json.loads(line) for line in GOLDEN.read_text(encoding="utf-8").splitlines()]
BY_ID = {i["id"]: i for i in GOLD}
CLOCK = context.DATA_AS_OF
SENT0 = dict(weather.SENT)
USERS: dict[int, object] = {}
ceo, ops_emp, fin_emp = context.load_user(1), context.load_user(12), context.load_user(13)


def user(eid: int):
    return USERS.setdefault(eid, context.load_user(eid))


def supervisor_threads() -> set[str]:
    with checkpointer.pool().connection() as conn:
        rows = conn.execute("SELECT DISTINCT thread_id FROM checkpoints WHERE thread_id LIKE %s "
                            "AND metadata->>'trigger' = 'supervisor'", ("route_advice:%",)).fetchall()
    return {r["thread_id"] for r in rows}


THREADS_BEFORE = supervisor_threads()


def _cleanup() -> None:                         # also when a phase fails: no check thread is left in agent_state
    s = checkpointer.saver()
    for t in supervisor_threads() - THREADS_BEFORE:
        s.delete_thread(t)


atexit.register(_cleanup)
print(f"golden items {len(GOLD)}; skills {len(skill_loader.catalog())} (supervisor-qa "
      f"{skill_loader.est_tokens(skill_loader.load('supervisor-qa'))} tokens)")


# %% Phase 1 — The router on the golden questions + the access split
# Every tool a golden item needs must be routed (recall 100 %), ≤ MAX_TOOLS offered; the refused part of an
# Operations twin = its frozen `refused_any.tools`, and nothing is refused to anyone else. The access split's resource
# table must predict each tool's own answer for one employee of every (role, department) profile.
miss, ref_bad, sizes = [], [], []
for i in GOLD:
    r = sv.route(i["question"], user(i["employee_id"]))
    if not set(i["tools_needed"]) <= set(r.tools) | set(r.refused):
        miss.append((i["id"], sorted(set(i["tools_needed"]) - set(r.tools) - set(r.refused))))
    if sorted(r.refused) != sorted((i.get("refused_any") or {}).get("tools", [])):
        ref_bad.append((i["id"], r.refused))
    sizes.append(len(r.tools))
assert not miss, miss
assert not ref_bad, ref_bad
extra = {"unmatched": sv.route("Tell me something useful.", ops_emp).tools,
         "finance_only_ops": (sv.route("What were total receivables at the end of week 23?", ops_emp).tools,
                              sv.route("What were total receivables at the end of week 23?", ops_emp).refused),
         "manager_finance": sv.route("What were total receivables at the end of week 23?", context.load_user(2)).refused}
profiles = db.fetch("SELECT DISTINCT ON (r.role_name, d.department_name) e.employee_id FROM employees e "
                    "JOIN roles r USING (role_id) JOIN departments d USING (department_id) "
                    "ORDER BY r.role_name, d.department_name, e.employee_id")
SAMPLE = {"finance_kpi": (finance.finance_kpi, {"report_week": 23, "dataset": "weekly"}),
          "compute_toll": (tariff.compute_toll, {"vessel_id": 420}),
          "voyage_eta": (lambda u, **a: eta.voyage_eta(u, as_of=CLOCK, **a), {"vessel_id": 5}),
          "watch_alerts": (lambda u, **a: watch.watch_alerts(u, as_of=CLOCK, **a), {}),
          "fleet_customers": (fleet.fleet_customers, {"vessel_ids": [1]}),
          **{n: (f, a) for n, (_, f) in registry.STAGE2.items() for a in [
              {"sea_route": {"origin": "SGSIN", "destination": "NLRTM"}, "vessel_params": {"vessel_id": 1},
               "voyage_status": {"vessel_id": 1}}.get(n)] if a is not None}}
split_bad = []
for p in profiles:
    u = user(p["employee_id"])
    for name, (fn, args) in SAMPLE.items():
        predicted = context.permitted(u, *sv.TOOL_RESOURCES[name])
        actual = fn(u, **args).status != "not_permitted"
        split_bad += [] if predicted == actual else [(u.employee_id, u.role, u.department, name)]
assert not split_bad, split_bad
actual_1 = {"items": len(GOLD), "recall_misses": 0, "max_tools": max(sizes), "refused_twins":
            sum(bool(sv.route(i["question"], user(i["employee_id"])).refused) for i in GOLD), **extra,
            "profiles": len(profiles), "split_checks": len(profiles) * len(SAMPLE)}
REVIEWED_1 = {"items": 57, "recall_misses": 0, "max_tools": 5, "refused_twins": 10,
              "unmatched": sv.DEFAULT_TOOLS, "finance_only_ops": ([], ["finance_kpi"]), "manager_finance": [],
              "profiles": actual_1["profiles"], "split_checks": actual_1["split_checks"]}
assert actual_1 == REVIEWED_1 and actual_1["profiles"] >= 10, actual_1
print(f"router: mean {sum(sizes) / len(sizes):.2f} tools, max {max(sizes)}; access split = the tools' own answer on "
      f"{actual_1['split_checks']} calls ({actual_1['profiles']} profiles × {len(SAMPLE)} tools)")
print("✅ Phase 1 validation passed: every needed tool routed on the 57 golden items, ≤ 5 offered, the refused part "
      "= the frozen one on the 10 Operations twins and empty elsewhere; the access table = the tools' own access")


# %% Phase 2 — check_supervisor_answer on hand answers
# Real evidence from the tools (as the CEO at the clock); right answers must pass with 0 problems, each planted error
# must give at least one problem.
def ev(res, tool=None) -> dict:
    d = res.model_dump(mode="json") if hasattr(res, "model_dump") else res
    return {**d, "tool": tool or d["tool"]}


c1 = json.loads((ROOT / "Data/processed/agents/eval/route_cases.json").read_text(encoding="utf-8"))["cases"][0]
route_rows = ra.deterministic(ceo, RouteRequest(vessel_id=c1["vessel_id"], origin=c1["origin"],
                                                destination=c1["destination"]), CLOCK, with_context=False)["evidence"]
EV = {"insight.c1": ev(eta.voyage_eta(ceo, as_of=CLOCK, vessel_id=5)),
      "insight.c2": ev(tariff.compute_toll(ceo, vessel_id=420)),
      "insight.c3": {"tool": "route_advice", "status": "ok",
                     "rows": route_rows["route.compare"]["rows"] + route_rows["route.difference"]["rows"],
                     "source": {"kind": "library", "name": "route_advice graph", "filter": "check"}},
      "insight.c4": ev(watch.watch_alerts(ceo, as_of=CLOCK)),
      "insight.c5": ev(fleet.fleet_customers(ceo, vessel_ids=[234]))}
NOACCESS = "Your role has no access to the invoices (Finance data)."
A = lambda text, status="answered", ids=("insight.c1",): {"status": status, "answer": text,  # noqa: E731
                                                          "evidence_ids": list(ids)}
GOOD = {
    "eta": (A("Crude Voyager 005 is expected at its destination on 2026-09-15, {insight.c1:eta_in_h} from now."),
            "When will Crude Voyager 005 arrive?", "en", []),
    "route": (A("Via Suez: it saves {insight.c3[difference]:change_total_sdr|M} against the Cape; the Suez dues are "
                "{insight.c3[suez]:suez_dues_sdr|k}.", ids=("insight.c3",)),
              "Should vessel 21 go from Singapore to Rotterdam via Suez or the Cape?", "en", []),
    "partial": (A("The Suez Canal toll of vessel 420 is {insight.c2:amount_sdr|k}. " + NOACCESS, "partial",
                  ("insight.c2",)),
                "What Suez Canal toll would vessel 420 pay, and how many days past due is its overdue invoice?",
                "en", ["finance_kpi"]),
    "watch": (A("Cruise Voyager 234 has a high alert: waves of {insight.c4[234/weather]:wave_height_max_m} on its next "
                "leg; the fleet has {insight.c4[fleet]:alerts_high} high alerts.", ids=("insight.c4",)),
              "Which vessels have a high weather alert?", "en", []),
    "arabic": (A("السفينة 234 عليها إنذار عالي: الموج {insight.c4[234/weather]:wave_height_max_m} في الرحلة الجاية.",
                 ids=("insight.c4",)), "أنهي سفن عليها إنذار طقس عالي؟", "ar", []),
    "id_from_row": (A("Cruise Voyager 234 belongs to customer 34.", ids=("insight.c5",)),
                    "Which customer owns Cruise Voyager 234?", "en", []),
}
PLANTED = {
    "typed_figure": (A("The toll of vessel 420 is 622,758.68 SDR.", ids=("insight.c2",)), "Toll of vessel 420?", "en",
                     []),
    "unknown_id": (A("ETA {insight.c1:eta_in_h}.", ids=("insight.zz",)), "ETA of vessel 5?", "en", []),
    "partial_unnamed": (A("The toll of vessel 420 is {insight.c2:amount_sdr|k}.", "partial", ("insight.c2",)),
                        "Toll of vessel 420 and its invoice?", "en", ["finance_kpi"]),
    "answered_refused": (A("The toll of vessel 420 is {insight.c2:amount_sdr|k}. " + NOACCESS, ids=("insight.c2",)),
                         "Toll of vessel 420 and its invoice?", "en", ["finance_kpi"]),
    "toll_as_invoice": (A("Vessel 420's invoice is for {insight.c2:amount_sdr|k}. " + NOACCESS, "partial",
                          ("insight.c2",)), "Toll of vessel 420 and its invoice?", "en", ["finance_kpi"]),
    "toll_as_invoice_ar": (A("فاتورة السفينة 420 قيمتها {insight.c2:amount_sdr|k}. دورك مالوش صلاحية على الفواتير.",
                             "partial", ("insight.c2",)), "رسوم السفينة 420 وفاتورتها؟", "ar", ["finance_kpi"]),
    "wrong_row_key": (A("Waves {insight.c4[999/weather]:wave_height_max_m}.", ids=("insight.c4",)), "Waves?", "en", []),
    "arabic_digits_typed": (A("الرسوم ٦٢٢٧٥٨ SDR.", ids=("insight.c2",)), "رسوم السفينة 420؟", "ar", []),
    "partial_nothing_refused": (A("The toll is {insight.c2:amount_sdr|k}. " + NOACCESS, "partial", ("insight.c2",)),
                                "Toll of vessel 420?", "en", []),
    "id_not_in_rows": (A("Vessel 777 is expected at {insight.c1:eta_in_h}.", ids=("insight.c1",)), "ETA?", "en", []),
}
good_problems = {k: sv.check_supervisor_answer(a, EV, q, lang, ref)[2] for k, (a, q, lang, ref) in GOOD.items()}
planted_problems = {k: sv.check_supervisor_answer(a, EV, q, lang, ref)[2] for k, (a, q, lang, ref) in PLANTED.items()}
assert not any(good_problems.values()), {k: v for k, v in good_problems.items() if v}
missed = [k for k, v in planted_problems.items() if not v]
assert not missed, missed
rendered_ar = sv.check_supervisor_answer(*[GOOD["arabic"][i] for i in (0,)], EV, GOOD["arabic"][1], "ar")[0]
print(f"rendered (ar): {rendered_ar}")
print(f"planted → first problem: { {k: v[0][:70] for k, v in planted_problems.items()} }")
print(f"✅ Phase 2 validation passed: {len(GOOD)} right answers pass with 0 problems, {len(PLANTED)} / "
      f"{len(PLANTED)} planted errors caught (typed figures in both digit sets, ids, row keys, the partial rules, "
      "D-P12-2 in English and Arabic)")


# D-P12-8 (the S4 smoke: "61.3 h ساعة"): a unit written again after a slot is dropped in Egyptian Arabic as in
# English; a word that is not the slot's unit stays
from pipelines.agents.deck import slots as _slots  # noqa: E402

NORM = {"خلال {insight.c1:eta_in_h} ساعة من دلوقتي.": "خلال {insight.c1:eta_in_h} من دلوقتي.",
        "in {insight.c1:eta_in_h} hours.": "in {insight.c1:eta_in_h}.",
        "الموج {insight.c4[234/weather]:wave_height_max_m} متر.": "الموج {insight.c4[234/weather]:wave_height_max_m}.",
        "{insight.c1:eta_in_h} ساعات": "{insight.c1:eta_in_h}",
        "{insight.c1:eta_in_h} سفينة": "{insight.c1:eta_in_h} سفينة"}
norm_wrong = {t: got for t, want in NORM.items() if (got := _slots.normalize_text(t, EV)[0]) != want}
assert not norm_wrong, norm_wrong
print(f"✅ Phase 2 (D-P12-8): {len(NORM)} unit cases — the unit after a slot dropped in Arabic and English, another "
      "word kept")


# candidate c1 (C-a + C-c): the model view flattens nested fields and drops the fields the answers never need; a slot
# citing a nested path or the result's own path is rewritten to the flattened field
from pipelines.agents.tools import voyages  # noqa: E402

vs = sv.model_view(voyages.voyage_status(ceo, as_of=CLOCK, vessel_id=1).model_dump(mode="json"))
wv = sv.model_view(EV["insight.c4"])
paths = {"At {insight.c1[0]:last_fix.lat|none}.": "At {insight.c1[0]:last_fix_lat|none}.",
         "Toll {insight.c2:rows[0].amount_sdr|sdr}.": "Toll {insight.c2:amount_sdr|sdr}.",
         "ETA {insight.c1:eta_in_h}.": "ETA {insight.c1:eta_in_h}."}
paths_wrong = {t: got for t, want in paths.items() if (got := sv.normalize_paths(t)[0]) != want}
# candidate c1 (C-d): a cited customers row must be the customer of the vessel in the evidence (c07's wrong customer)
cu52 = finance.finance_kpi(ceo, report_week=52, dataset="customers").model_dump(mode="json")
own21 = fleet.fleet_customers(ceo, vessel_ids=[21]).model_dump(mode="json")
cid21 = own21["rows"][0]["customer_id"]
right_name = next(r["customer_name"] for r in cu52["rows"] if r["customer_id"] == cid21)
wrong_name = next(r["customer_name"] for r in cu52["rows"] if r["customer_id"] != cid21)
EVJ = {"insight.f": cu52, "insight.v": own21}
CALLSJ = {"insight.v": {"tool": "fleet_customers", "args": {"vessel_ids": [21]}}}
join_q = "How much did vessel 21's customer bill over the 13 weeks to week 52 of 2025?"
join_ok = sv.check_supervisor_answer(A(f"Vessel 21's customer {right_name} billed {{insight.f[{right_name}]:billed_13w_sdr|M}}"
                                       ".", ids=("insight.f", "insight.v")), EVJ, join_q, "en", [], CALLSJ)[2]
join_bad = sv.check_supervisor_answer(A(f"Vessel 21's customer {wrong_name} billed {{insight.f[{wrong_name}]:billed_13w_sdr|M}}"
                                        ".", ids=("insight.f", "insight.v")), EVJ, join_q, "en", [], CALLSJ)[2]
join_no_link = sv.check_supervisor_answer(A(f"{wrong_name} billed {{insight.f[{wrong_name}]:billed_13w_sdr|M}}.",
                                            ids=("insight.f",)), {"insight.f": cu52}, "Top customer billing?", "en")[2]
# the year rule (D-P12-12): the right customer's 2025 figure for a 2024 question is refused; the same rows from a
# non-finance tool keep their own years (a 2024 Suez question is answerable); the appended ids are not years
right_answer = A(f"Vessel 21's customer {right_name} billed {{insight.f[{right_name}]:billed_13w_sdr|M}}.",
                 ids=("insight.f", "insight.v"))
year_fin = sv.check_supervisor_answer(right_answer, EVJ, join_q.replace("2025", "2024"), "en", [], CALLSJ)[2]
EVS = {"insight.s": {"tool": "suez_transits", "status": "ok", "source": {"kind": "api", "name": "portwatch"},
                     "note": None, "rows": [{"date": "2024-03-20", "n_total": 60}]}}
year_other = sv.check_supervisor_answer(
    A("On 2024-03-20, {insight.s[2024-03-20]:n_total} ships transited the Suez Canal.", ids=("insight.s",)), EVS,
    "How many ships transited the Suez Canal on 20 March 2024?", "en", [], {})[2]
actual_c1 = {"flat_last_fix": sorted(k for k in vs["rows"][0] if k.startswith("last_fix")),
             "nested_left": [k for r in vs["rows"] + wv["rows"] for k, v in r.items() if isinstance(v, dict)],
             "dropped": (any("route" in r for r in vs["rows"]),
                         any(k in r for r in wv["rows"] for k in ("lat", "lon", "reason", "wave_source"))),
             "kept": all("wave_height_max_m" in r for r in wv["rows"] if "/weather" in r["alert_id"]),
             "paths_wrong": paths_wrong, "join": (len(join_ok), len(join_bad), len(join_no_link)),
             "year": (len(year_fin), len(year_other), all("2024" in p for p in year_fin))}
REVIEWED_C1 = {"flat_last_fix": ["last_fix_cog", "last_fix_lat", "last_fix_lon", "last_fix_navstat", "last_fix_sog_kn",
                                 "last_fix_ts"], "nested_left": [], "dropped": (False, False), "kept": True,
               "paths_wrong": {}, "join": (0, 1, 0), "year": (1, 0, True)}
assert actual_c1 == REVIEWED_C1, actual_c1
print(f"✅ Phase 2 (c1): the model view flattens last_fix into 6 fields and drops the unneeded ones; "
      f"{len(paths)} slot-path cases; the join guard catches a wrong customer ({wrong_name} for {right_name}) and "
      "passes the right one and an answer with no vessel link")


# %% Phase 2s — The skills supervisor-qa and finance-qa (the owner's review of 2026-10-29)
# supervisor-qa parses within the budgets and names only tools, arguments, fields, row labels and statuses the
# supervisor really has; its example slots use real fields of real tool results (the evidence of Phase 2); it states
# its rules. The two review changes are checks: an Egyptian Arabic example with a slot (review point 2), and
# finance-qa's exception for the supervisor's partial answer (review point 1: finance-qa itself changed — a Stage 1
# skill, so a Stage 1 comparison is owed under ADR-052). The owner's review is reported (reviewed_by_owner).
from pipelines.agents.deck import slots  # noqa: E402

cat = skill_loader.catalog()
sq, fqs = cat["supervisor-qa"], cat["finance-qa"]
tool_objs = registry.supervisor_tools(None) + [skill_loader.load_skill_tool]
known = ({t.name for t in tool_objs}
         | {a for t in tool_objs for a in t.tool_call_schema.model_json_schema()["properties"]}
         | {k for res in EV.values() for r in res["rows"] for k in r}
         | set(sv.m.SupervisorAnswer.model_fields["status"].annotation.__args__) | set(cat)
         | {"suez", "cape", "difference", "fleet", "234/weather", "customers", "insight.c1"})
named = sorted({x.split("(")[0] for x in re.findall(r"`([A-Za-z0-9_./\[\]=(),-]+)`", sq.body)})
unknown_named = [x for x in named if x not in known and not re.fullmatch(r"insight\.c\d+(\[[^\]]+\])?", x)]
ex = slots.find_slots(sq.body)
ev_fields = {k for res in EV.values() for r in res["rows"] for k in r}
bad_examples = [s.raw for s in ex if s.field not in ev_fields]
flat = " ".join(sq.body.split())
rules = all(x in flat for x in ("join them **by ids**", "status `partial`", "never put a toll next to an invoice",
                                "No live AIS", "in the question's language"))
arabic_example = any(re.search(r"[؀-ۿ]", line) and slots.find_slots(line)
                     for line in sq.body.split("\n- ") if line.lstrip().startswith('"') or "→" in line)
fq_flat = " ".join(fqs.body.split())
fq_exception = all(x in fq_flat for x in ("Exception — the supervisor", "status `partial`", "`supervisor-qa`"))
actual_2s = {"stage": sq.stage, "within_budget": all(len(s.description) <= skill_loader.DESCRIPTION_MAX and
                                                     s.body_tokens <= skill_loader.BODY_MAX_TOKENS for s in (sq, fqs)),
             "unknown_names": unknown_named, "bad_examples": bad_examples, "example_slots": len(ex),
             "rules_stated": rules, "arabic_example": bool(arabic_example), "finance_qa_exception": fq_exception,
             "reviewed": (sq.reviewed_by_owner, fqs.reviewed_by_owner)}
REVIEWED_2S = {"stage": "2", "within_budget": True, "unknown_names": [], "bad_examples": [], "example_slots": 3,
               "rules_stated": True, "arabic_example": True, "finance_qa_exception": True,
               "reviewed": ("2026-10-29", "2026-10-29")}
assert actual_2s == REVIEWED_2S, actual_2s
print(f"skills: supervisor-qa {sq.body_tokens} tokens ({len(named)} names, {len(ex)} example slots), finance-qa "
      f"{fqs.body_tokens} tokens; reviewed by the owner {actual_2s['reviewed']}")
print("✅ Phase 2s validation passed: supervisor-qa within budget, every name and example slot real, its rules stated, "
      "an Egyptian Arabic example; finance-qa carries the supervisor's partial-answer exception; both reviewed")


# %% Phase 3 — The agent end to end on scripted fake models
# For every golden item with value elements (and every abstention) a scripted model plays the right turn: load the
# skill `supervisor-qa` (every second item), call the tools of the item's permitted value elements in one round, then
# return a SupervisorAnswer with one slot per element (+ the refused part named for an Operations twin). The real
# router, tools (as the item's asker at the clock), middleware, slot rendering and checks run: the status must be the
# frozen one and every bound value the frozen value. The route advisor's `writer` call is played by the same script.
# Then the patch path, validation_failed and the call limit; every model request is measured in tokens.
sent: list[httpx.Request] = []


def _fake_http(req: httpx.Request) -> httpx.Response:
    sent.append(req)
    if "arcgis" in req.url.host:
        where = req.url.params["where"]
        start = date.fromisoformat(re.search(r"date >= DATE '([\d-]+)'", where).group(1))
        n = 40 if start.year == 2025 else 41
        return httpx.Response(200, json={"features": [{"attributes": {
            "date": (start + timedelta(days=i)).isoformat(), "n_total": n, "n_container": 10, "n_tanker": 8,
            "n_dry_bulk": 6, "n_general_cargo": 3, "n_roro": 1, "capacity": 1_000_000}} for i in range(28)]})
    return httpx.Response(200, json={"results": [{"title": "Suez Canal traffic update", "url": "https://example.org/n",
                                                  "content": "Canal operations continue.",
                                                  "published_date": "2026-09-10"}]})


def good_advice(cheaper: str) -> dict:
    other = "cape" if cheaper == "suez" else "suez"
    return {"recommendation": cheaper,
            "headline": f"Sail via {cheaper}: {{route.compare[{cheaper}]:total_sdr|M}} against "
                        f"{{route.compare[{other}]:total_sdr|M}}.",
            "reasons": [{"text": f"The voyage costs {{route.compare[{cheaper}]:total_sdr|M}} via {cheaper}, fuel and "
                                 "dues together.", "evidence_ids": ["route.compare"]}],
            "risks": []}


LABEL = {}                                        # (tool, dataset, row) → the slot's row key text


def row_label(el: dict) -> str | None:
    if el["row"] is None:
        return None
    if el["tool"] == "finance_kpi" and el["args"]["dataset"] == "customers":
        key = ("customers", el["args"]["report_week"], el["row"])
        if key not in LABEL:
            rows = finance.finance_kpi(ceo, report_week=el["args"]["report_week"], dataset="customers", limit=50).rows
            LABEL[key] = next(r["customer_name"] for r in rows if str(r["customer_id"]) == el["row"])
        return LABEL[key]
    return el["row"]


def tool_args(el: dict) -> dict:
    # the model never names the watch run; ranked finance lists at the tool's default limit (10 rows — every row the
    # golden items need is in the top 10, and a 50-row list alone would not fit a free tier's request)
    return {k: v for k, v in el["args"].items() if k != "thread"}


def est(obj) -> int:
    return skill_loader.est_tokens(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, default=str))


class Play:
    """The scripted model of one item: skill → tool calls → the answer (`bad` modes for the patch / failure paths)."""

    def __init__(self, item: dict, with_skill: bool, mode: str = "good"):
        self.item, self.with_skill, self.mode, self.n = item, with_skill, mode, 0
        self.els = [e for e in item["elements"] if e["kind"] == "value"]
        keys = list(dict.fromkeys(json.dumps([e["tool"], tool_args(e)], sort_keys=True) for e in self.els))
        self.calls = [(json.loads(k)[0], json.loads(k)[1], f"c{j + 1}") for j, k in enumerate(keys)]
        self.cid = {k: f"c{j + 1}" for j, k in enumerate(keys)}
        self.sizes: list[int] = []

    def answer(self, patched: bool) -> dict:
        parts = []
        for e in self.els:
            cid = self.cid[json.dumps([e["tool"], tool_args(e)], sort_keys=True)]
            lab = row_label(e)
            parts.append("{insight." + cid + (f"[{lab}]" if lab else "") + ":" + e["field_any"][0] + "}")
        ar = self.item["lang"] == "ar"
        text = ("الأرقام: " if ar else "The figures: ") + ", ".join(parts) + "."
        status = self.item["expected_status"]
        if status == "partial":
            text += " دورك مالوش صلاحية على بيانات المالية والفواتير." if ar else \
                " Your role has no access to the finance data and invoices (Finance)."
        if status == "not_in_data":
            text = "مفيش البيانات دي عندنا." if ar else "This is not in NileGate's data."
        if self.mode == "always_bad" or (self.mode == "patch" and not patched):
            text += " That is about 2.2 M SDR."
        return {"status": status, "answer": text, "evidence_ids": [f"insight.{c}" for _, _, c in self.calls]}

    def __call__(self, role, msgs, tools, schema):
        if role == "writer":                                           # the route advisor inside route_advice
            t = "\n".join(str(x.content) for x in msgs)
            return good_advice(json.loads(re.search(r"\[route\.difference\] (\{.*\})", t).group(1))["cheaper_route"])
        self.n += 1
        self.sizes.append(est([str(x.content) for x in msgs]) + est([convert_to_openai_tool(t) for t in tools or []]))
        skill_done = any(isinstance(x, ToolMessage) and x.name == sv.SKILL_TOOL for x in msgs)
        data_done = any(isinstance(x, ToolMessage) and x.name not in (sv.SKILL_TOOL, sv.ANSWER_TOOL) for x in msgs)
        patched = any("Your answer had these problems" in str(x.content) for x in msgs)
        if self.mode == "loop":                                        # never answers
            return AIMessage(content="", tool_calls=[{"name": "voyage_status", "args": {"vessel_id": 1},
                                                      "id": f"loop{self.n}"}])
        if self.with_skill and not skill_done:
            return AIMessage(content="", tool_calls=[{"name": sv.SKILL_TOOL, "args": {"name": "supervisor-qa"},
                                                      "id": f"s{self.n}"}])
        if self.calls and not data_done:
            return AIMessage(content="", tool_calls=[{"name": t, "args": a, "id": c} for t, a, c in self.calls])
        return AIMessage(content="", tool_calls=[{"name": sv.ANSWER_TOOL, "args": self.answer(patched),
                                                  "id": f"a{self.n}"}])


class Dispatch:                                    # FakeRoles needs one callable; the current play answers
    play: Play | None = None

    def __call__(self, role, msgs, tools, schema):
        return self.play(role, msgs, tools, schema)


dispatch = Dispatch()
fake = roles.FakeRoles(dispatch)
saver, pool = checkpointer.saver(), checkpointer.pool()
graph = sv.build_graph(fake, saver=saver, pool=pool)
tmp_cache = Path(tempfile.mkdtemp(prefix="supervisor_check_cache_"))
real_http, real_today = external.HTTP, external.TODAY


def play(item: dict, with_skill: bool, mode: str = "good", n: int = 0) -> tuple[dict, Play]:
    dispatch.play = Play(item, with_skill, mode)
    st = sv.ask(graph, item["question"], user(item["employee_id"]), item["lang"], CLOCK,
                thread=f"check:{item['id']}:{mode}:{n}")
    return st, dispatch.play


results, wrong, sizes3, per_item = {}, [], [], {}
try:
    external.HTTP = httpx.Client(transport=httpx.MockTransport(_fake_http), timeout=external.TIMEOUT_S)
    external.TODAY = date(2026, 10, 27)
    os.environ.setdefault("TAVILY_API_KEY", "check-only-key")        # the mock answers; nothing leaves the machine
    for name in ("suez_transits", "web_search"):
        external._caches[name] = external.ExternalCache(name, tmp_cache)
    runnable = [i for i in GOLD if any(e["kind"] == "value" for e in i["elements"])
                or i["expected_status"] == "not_in_data"]
    for k, item in enumerate(runnable):
        st, p = play(item, with_skill=k % 2 == 0)
        sizes3 += p.sizes
        per_item[item["id"]] = max(p.sizes)
        ok_status = st["status"] == item["expected_status"] or st["status"] in item.get("status_also", [])
        got = {(b["field"], b["value"]) for b in st.get("bound") or []}
        want = {(e["field_any"][0], e["values"][e["field_any"][0]]) for e in p.els}
        results[item["id"]] = st["status"]
        if not ok_status or got != want or st.get("problems"):
            wrong.append((item["id"], st["status"], st.get("problems"), sorted(want - got)[:2]))
    assert not wrong, wrong[:4]
    patch_item = BY_ID["o07"]
    st_patch, _ = play(patch_item, False, "patch")
    st_bad, _ = play(patch_item, False, "always_bad")
    st_loop, p_loop = play(patch_item, False, "loop")
finally:
    external.HTTP, external.TODAY = real_http, real_today
    shutil.rmtree(tmp_cache, ignore_errors=True)
by_status = {s: sum(v == s for v in results.values()) for s in sorted(set(results.values()))}
print("largest requests per item:", sorted(per_item.items(), key=lambda kv: -kv[1])[:8])
print("items over 6,500 tokens:", sorted(k for k, v in per_item.items() if v > 6_500))
# the request budget of the `tools` role's Groq fallback: 8K tokens per minute minus llm.py's output reserve (1,500).
# est_tokens counts 3 characters a token (conservative; English JSON ≈ 4): D-P12-5 records the two items over the
# conservative count — at 4 characters a token every request fits.
BUDGET = 8_000 - 1_500
over = sorted(k for k, v in per_item.items() if v > BUDGET)
actual_3 = {"items_run": len(results), "statuses": by_status, "wrong": 0,
            "patch": (st_patch["status"], st_patch.get("patches")), "always_bad": st_bad["status"],
            "loop": (st_loop["status"], p_loop.n <= sv.MAX_MODEL_CALLS),
            "max_request_est_tokens": max(sizes3), "over_conservative_budget": over,
            "fits_at_4_chars_per_token": max(sizes3) * 3 / 4 <= BUDGET}
REVIEWED_3 = {"items_run": 33, "statuses": {"answered": 27, "not_in_data": 3, "partial": 3}, "wrong": 0,
              "patch": ("answered", 1), "always_bad": "validation_failed", "loop": ("output_invalid", True),
              "max_request_est_tokens": 7137, "over_conservative_budget": ["c10", "c10_ar"],
              "fits_at_4_chars_per_token": True}
assert actual_3 == REVIEWED_3, actual_3
print(f"agent: {len(results)} golden items run end to end, statuses {by_status}; largest request "
      f"≈ {max(sizes3)} est tokens (messages + tool schemas, 3 chars a token), median "
      f"{sorted(sizes3)[len(sizes3) // 2]}; over the conservative budget {over}; "
      f"mock hosts {sorted({r.url.host for r in sent})}")
print("✅ Phase 3 validation passed: the agent on fake models reaches the frozen status and binds every frozen value on "
      "every runnable golden item (skills loaded on half of them, route_advice inside); patch → answered, twice bad → "
      "validation_failed, a model that never answers → output_invalid within the call limit; request sizes recorded "
      "(2 items over the conservative Groq budget, all fit at 4 chars a token: D-P12-5)")


# %% Phase 4 — RBAC inside the agent
# An Operations employee's question with a finance part: the finance tool is not offered, and a model that calls it
# anyway gets not_permitted from code without the tool running (the finance function is counted); a question whose
# every routed part is refused ends not_permitted with no model call.
real_kpi = finance.finance_kpi
kpi_runs = {"n": 0}


def counting_kpi(*a, **k):
    kpi_runs["n"] += 1
    return real_kpi(*a, **k)


class Rogue(Play):
    def __call__(self, role, msgs, tools, schema):
        self.offered = sorted(convert_to_openai_tool(t)["function"]["name"] for t in tools or [])
        done = {x.name for x in msgs if isinstance(x, ToolMessage)}
        if "finance_kpi" not in done:                                   # the refused tool, called anyway
            return AIMessage(content="", tool_calls=[{"name": "finance_kpi", "args": {"report_week": 49,
                                                                                   "dataset": "overdue"}, "id": "r1"}])
        if "compute_toll" not in done:
            return AIMessage(content="", tool_calls=[{"name": "compute_toll", "args": {"vessel_id": 420}, "id": "r2"}])
        return AIMessage(content="", tool_calls=[{"name": sv.ANSWER_TOOL, "args": {
            "status": "partial", "answer": "The Suez Canal toll of vessel 420 is {insight.r2:amount_sdr|k}. Your role "
                                           "has no access to the invoices (Finance data).",
            "evidence_ids": ["insight.r2"]}, "id": "ra"}])


twin = BY_ID["c06_ops"]
try:
    finance.finance_kpi = counting_kpi
    dispatch.play = Rogue(twin, False)
    st_rogue = sv.ask(graph, twin["question"], user(twin["employee_id"]), "en", CLOCK, thread="check:rogue")
    calls_before = sum(fake.calls.values())
    st_refused = sv.ask(graph, "What were total receivables at the end of week 23?", ops_emp, None, CLOCK,
                        thread="check:refused")
    calls_after = sum(fake.calls.values())
finally:
    finance.finance_kpi = real_kpi
rogue_ev = st_rogue.get("evidence") or {}
actual_4 = {"offered_has_finance": "finance_kpi" in dispatch.play.offered,
            "rogue_result": [(v["tool"], v["status"], len(v.get("rows") or [])) for v in rogue_ev.values()],
            "finance_runs": kpi_runs["n"], "rogue_status": st_rogue["status"],
            "all_refused": (st_refused["status"], st_refused["llm_usage"], calls_before == calls_after),
            "refusal_names_part": "finance data" in st_refused["rendered"]}
REVIEWED_4 = {"offered_has_finance": False,
              "rogue_result": [("finance_kpi", "not_permitted", 0), ("compute_toll", "ok", 1)], "finance_runs": 0,
              "rogue_status": "partial", "all_refused": ("not_permitted", [], True), "refusal_names_part": True}
assert actual_4 == REVIEWED_4, actual_4
print("✅ Phase 4 validation passed: a refused tool is never offered and a call of it never runs (not_permitted, no "
      "row, the finance function ran 0 times); a question refused in every part → not_permitted with no model call")


# %% Phase 5 — The CLI Ask.py: a thread and a trace per question (S4)
# `Ask.answer` on fake models with the real PostgresSaver, at a clock one minute before the data's as-of instant (the
# check's threads `ask:<employee>:20260912T2359Z:<n>` never meet a real question at the default clock): English,
# Egyptian Arabic, a partial answer and an all-refused question (stored as an ended thread with no model call);
# `show` returns the stored answer to the asker and the CEO and refuses another employee; `list` shows an employee
# only their own questions; the 30-day retention archives then deletes them (a fresh one is kept); one question is
# read back from LangSmith when a key exists (fake models: the trace only, no LLM call).
import importlib.util  # noqa: E402
import time  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

spec = importlib.util.spec_from_file_location("ask_cli", ROOT / "pipelines/scripts/agents/Ask.py")
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)
from pipelines.agents import scheduling, tracing  # noqa: E402

CHECK_CLOCK = CLOCK - timedelta(minutes=1)
ASK_BEFORE = set(scheduling.thread_ids(pool, sv.THREAD_PREFIX))
since = datetime.now(timezone.utc) - timedelta(minutes=1)
asked = {}
try:
    external.HTTP = httpx.Client(transport=httpx.MockTransport(_fake_http), timeout=external.TIMEOUT_S)
    external.TODAY = date(2026, 10, 27)
    tmp_cache = Path(tempfile.mkdtemp(prefix="supervisor_check_cache_"))
    for name in ("suez_transits", "web_search"):
        external._caches[name] = external.ExternalCache(name, tmp_cache)
    for qid in ("o07", "o05_ar", "c06_ops"):
        it = BY_ID[qid]
        dispatch.play = Play(it, with_skill=False)
        st, traced = cli.answer(it["question"], it["employee_id"], None, CHECK_CLOCK, roles=fake, launched_by="check")
        asked[qid] = (cli.summary(st), traced, it["employee_id"])
    st, traced = cli.answer("What were total receivables at the end of week 23?", ops_emp.employee_id, None,
                            CHECK_CLOCK, roles=fake, launched_by="check")
    asked["refused"] = (cli.summary(st), traced, ops_emp.employee_id)
finally:
    external.HTTP, external.TODAY = real_http, real_today
    shutil.rmtree(tmp_cache, ignore_errors=True)
g_read = cli.graph()
new = sorted(set(scheduling.thread_ids(pool, sv.THREAD_PREFIX)) - ASK_BEFORE)
shown = {k: cli.show(s["thread"], user(e), g_read) for k, (s, _, e) in asked.items()}
same = all({x: shown[k][x] for x in ("status", "answer", "not_permitted")} ==
           {x: s[x] for x in ("status", "answer", "not_permitted")} for k, (s, _, _) in asked.items())
other = cli.show(asked["o07"][0]["thread"], context.load_user(24 if asked["o07"][2] != 24 else 13), g_read)
by_ceo = cli.show(asked["c06_ops"][0]["thread"], ceo, g_read)
listed_ok = all({i.thread_id for i in cli.questions(user(e), g_read)} & set(new)
                == {s["thread"] for s, _, e2 in asked.values() if e2 == e} for e in {e for _, _, e in asked.values()})
listed_ceo = {i.thread_id for i in cli.questions(ceo, g_read)} >= set(new)
infos = [i for i in scheduling.describe_ask(g_read, pool) if i.thread_id in new]
tmp_archive = Path(tempfile.mkdtemp(prefix="ask_archive_")) / "threads_archive.jsonl"
kept = scheduling.prune(g_read, saver, infos, tmp_archive)                                    # all fresh: kept
aged = scheduling.prune(g_read, saver, infos, tmp_archive, now=datetime.now(timezone.utc) + timedelta(days=31))
archived = [json.loads(x)["thread_id"] for x in tmp_archive.read_text(encoding="utf-8").splitlines()]
left = set(scheduling.thread_ids(pool, sv.THREAD_PREFIX)) & set(new)
trace = "pending: no LANGSMITH_API_KEY"
if tracing.has_key():
    from langsmith import Client
    client, root = Client(), None
    want = asked["o07"][0]["thread"]
    for _ in range(36):                                                 # ingestion lag: up to 3 min
        root = next((r for r in client.list_runs(project_name=tracing.PROJECT, is_root=True, start_time=since)
                     if ((r.extra or {}).get("metadata") or {}).get("thread_id") == want), None)
        if root:
            break
        time.sleep(5)
    assert root is not None, f"no root run of {want} in LangSmith project {tracing.PROJECT}"
    trace = sorted(set(root.tags) & {"entry:ask", "launched_by:check", "graph:supervisor", "lang:en"})
actual_5 = {"statuses": {k: s["status"] for k, (s, _, _) in asked.items()},
            "refused_calls": asked["refused"][0]["model_calls"], "threads": len(new),
            "thread_names": all(t.startswith("ask:") and ":20260912T2359Z:" in t for t in new),
            "traced": {k: t for k, (_, t, _) in asked.items()} == {k: tracing.has_key() for k in asked},
            "show_same": same, "show_other": "error" in other, "show_ceo": by_ceo.get("status"),
            "list_own_only": listed_ok, "list_ceo_all": listed_ceo, "ended": sorted({i.state for i in infos}),
            "prune_fresh_deleted": len(kept.get("deleted") or []), "prune_aged_deleted": len(aged.get("deleted") or []),
            "archived": sorted(archived) == new, "left": len(left)}
REVIEWED_5 = {"statuses": {"o07": "answered", "o05_ar": "answered", "c06_ops": "partial", "refused": "not_permitted"},
              "refused_calls": 0, "threads": 4, "thread_names": True, "traced": True, "show_same": True,
              "show_other": True, "show_ceo": "partial", "list_own_only": True, "list_ceo_all": True,
              "ended": ["ended"],
              "prune_fresh_deleted": 0, "prune_aged_deleted": 4, "archived": True, "left": 0}
assert actual_5 == REVIEWED_5, actual_5
print(f"Ask.py: {len(new)} threads {new[:2]}…; LangSmith read-back {trace}")
print("✅ Phase 5 validation passed: Ask.py stores one ended thread per question (incl. the all-refused one, 0 model "
      "calls), show = the stored answer for the asker and the CEO only, list = own questions, the 30-day retention "
      "archives and deletes them; traced exactly when a key exists")


# %% Final Checkpoint
# Narrative: pipelines/checkpoints/agents/Supervisor_check.md
assert weather.SENT == SENT0, (weather.SENT, SENT0)
_cleanup()
assert not supervisor_threads() - THREADS_BEFORE
print(f"✅ Final Checkpoint: the supervisor (router + access split + SupervisorAnswer checks + the agent) on fake models "
      f"— router recall 100 % on 57 items, {len(PLANTED)} / {len(PLANTED)} planted answer errors caught, "
      f"{actual_3['items_run']} golden items end to end, largest request ≈ {actual_3['max_request_est_tokens']} est "
      "tokens, "
      "RBAC inside the agent; 0 real model calls, 0 Open-Meteo calls")
