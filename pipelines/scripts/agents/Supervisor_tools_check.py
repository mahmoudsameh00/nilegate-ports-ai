"""Supervisor tools check (Agents plan Phase 12, §6d step S2): the product tools, the golden contract, the RBAC matrix.

Plan:    docs/archive/2026-11-01_Agents_plan.md §6d and its S2 plan in Progress (APPROVED 2026-10-29 with the owner's answers: a new
         `registry.PRODUCTS` + this check; the watch run = the latest at or before the clock; a stopped advice keeps
         its code rows; `fleet_customers` resolves a vessel's name).
Run:     uv run python tools/run.py pipelines/scripts/agents/Supervisor_tools_check.py  (from the project root)

Reads:   PostgreSQL read-only (PG_RO_USER), MongoDB read-only (MONGO_RO_USER), the voyage file, the saved watch runs
         (reports/voyage_watch/), the frozen golden set Data/processed/agents/eval/supervisor_qa_golden.jsonl.
Writes:  route-advice check threads in agent_state (login ports_agent), every one deleted at the end; a throw-away
         external cache in the temp folder. Nothing under Data/processed.
Re-run:  safe. 0 real model calls (FakeRoles), 0 Open-Meteo calls, PortWatch / Tavily answered by a mock transport.

Phases
1. watch_alerts — the pinned run, the clock rule, filters, refusals; the CLI's reader moved unchanged.
2. fleet_customers — an independent SQL over `vessels`; ids, names, refusals; no customer name ever.
3. route_advice as a tool — FakeRoles + the real PostgresSaver: a thread per call, the code rows, the stopped advice.
4. The golden contract — every value element of the S2 golden set re-computed as its asker at the clock.
5. RBAC matrix + contract — 100 employees × the 4 product tools = ADR-006, the probe refused (leakage 0), schemas.
Final Checkpoint (narrative: pipelines/checkpoints/agents/Supervisor_tools_check.md).
"""
# %% Setup
import atexit
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
from langchain_core.messages import BaseMessage
from pydantic import ValidationError

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())
sys.path.insert(0, str(ROOT))
from pipelines.agents import checkpointer, roles  # noqa: E402
from pipelines.agents.graphs import route_advice as ra  # noqa: E402
from pipelines.agents.graphs import voyage_watch as vw  # noqa: E402
from pipelines.agents.graphs.models import RouteRequest  # noqa: E402
from pipelines.agents.tools import (context, db, external, finance, fleet, products, registry, watch,  # noqa: E402
                                    weather)
from pipelines.lib.retrieval import User, allowed  # noqa: E402

GOLDEN = ROOT / "Data" / "processed" / "agents" / "eval" / "supervisor_qa_golden.jsonl"
PINNED = "voyage_watch:20260913T0000Z:1"
CLOCK = context.DATA_AS_OF
SENT0 = dict(weather.SENT)
GOLD = [json.loads(line) for line in GOLDEN.read_text(encoding="utf-8").splitlines()]
ops_emp, fin_emp, ceo = context.load_user(12), context.load_user(13), context.load_user(1)
probe = User(0, "probe", 0, "Nowhere")                                   # below every ceiling, no department


class _Runtime:                       # what LangChain passes as ToolRuntime; only `.context` is read
    def __init__(self, ctx):
        self.context = ctx


def supervisor_threads() -> set[str]:
    """The route-advice threads the tool opened (metadata trigger `supervisor`; a refused call has a thread too)."""
    with checkpointer.pool().connection() as conn:
        rows = conn.execute("SELECT DISTINCT thread_id FROM checkpoints WHERE thread_id LIKE %s "
                            "AND metadata->>'trigger' = 'supervisor'", ("route_advice:%",)).fetchall()
    return {r["thread_id"] for r in rows}


THREADS_BEFORE = supervisor_threads()          # this check deletes only the threads it opens (any run's, at the end)


def _cleanup() -> None:                         # also when a phase fails: no check thread is left in agent_state
    s = checkpointer.saver()
    for t in supervisor_threads() - THREADS_BEFORE:
        s.delete_thread(t)


atexit.register(_cleanup)
print(f"golden items {len(GOLD)}; tools in the supervisor's union {len(registry.supervisor_tools(None))}; "
      f"supervisor threads before {len(THREADS_BEFORE)}")


# %% Phase 1 — watch_alerts
# The run is the latest saved run at or before the run context's clock (S2 decision 2); its rows are the run file's
# alerts (+ thread_id) and one fleet row of the numeric fleet counts — the contract the golden items fixed.
run_file = vw.run_file_path(vw.REPORTS_DIR, PINNED)
pinned = json.loads(run_file.read_text(encoding="utf-8"))
r1 = watch.watch_alerts(ops_emp, as_of=CLOCK)
assert r1.status == "ok" and r1.source.name == f"reports/voyage_watch/{run_file.name}", (r1.status, r1.source)
alerts1 = [r for r in r1.rows if r["alert_id"] != "fleet" and not r["alert_id"].startswith("customer/")]
cust1 = [r for r in r1.rows if r["alert_id"].startswith("customer/")]
fleet1 = next(r for r in r1.rows if r["alert_id"] == "fleet")
assert [a["alert_id"] for a in alerts1] == [a["alert_id"] for a in pinned["alerts"]]
assert all({k: v for k, v in a.items() if k not in ("thread_id", "customer_id")} == p
           for a, p in zip(alerts1, pinned["alerts"]))
assert all(r["thread_id"] == PINNED for r in r1.rows)
assert {k: v for k, v in fleet1.items() if k not in ("alert_id", "thread_id")} == \
    {k: v for k, v in pinned["fleet"].items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
# c1 C-d: each alert's customer_id = vessels.customer_id; one row per customer = an independent count
owner = {r["vessel_id"]: r["customer_id"] for r in db.fetch("SELECT vessel_id, customer_id FROM vessels")}
assert all(a["customer_id"] == owner[a["vessel_id"]] for a in alerts1)
want_c = {}
for p in pinned["alerts"]:
    c = want_c.setdefault(owner[p["vessel_id"]], {"v": set(), "n": 0, "h": 0})
    c["v"].add(p["vessel_id"])
    c["n"] += 1
    c["h"] += p["severity"] == "high"
assert {r["customer_id"]: (r["vessels_with_alerts"], r["alerts"], r["high_alerts"]) for r in cust1} == \
    {k: (len(v["v"]), v["n"], v["h"]) for k, v in want_c.items()}
by_cust = watch.watch_alerts(ops_emp, as_of=CLOCK, customer_ids=[34, 9])
by_vess = watch.watch_alerts(ops_emp, as_of=CLOCK, vessel_ids=[420, 5])
# the clock rule on the saved runs (more runs appear as the replay fires; these instants never change their answer)
early = watch.watch_alerts(ops_emp, as_of=datetime(2026, 9, 6, 6, tzinfo=timezone.utc))
noon = watch.watch_alerts(ops_emp, as_of=datetime(2026, 9, 6, 12, tzinfo=timezone.utc))
before = watch.watch_alerts(ops_emp, as_of=datetime(2026, 9, 5, 23, 59, tzinfo=timezone.utc))
clock_rule = {"06T06": early.rows[-1]["thread_id"], "06T12": noon.rows[-1]["thread_id"], "before": before.status}
one = watch.watch_alerts(ops_emp, as_of=CLOCK, vessel_id=339)
hi = watch.watch_alerts(ops_emp, as_of=CLOCK, high_only=True)
empty = Path(tempfile.mkdtemp(prefix="watch_empty_"))
none = watch.watch_alerts(ops_emp, as_of=CLOCK, folder=empty)
refused = watch.watch_alerts(probe, as_of=CLOCK)
try:
    context.RunContext(ops_emp, as_of=CLOCK + timedelta(hours=1))
    past_clock = "accepted"
except ValueError:
    past_clock = "refused"
spec = __import__("importlib.util").util.spec_from_file_location("voyage_watch_cli",
                                                                 ROOT / "pipelines/scripts/agents/Voyage_watch.py")
cli = __import__("importlib.util").util.module_from_spec(spec)
spec.loader.exec_module(cli)
assert cli.read_alerts is watch.read_alerts and cli.can_read is watch.can_read
actual_1 = {"alerts": len(alerts1), "fleet_alerts_total": fleet1["alerts_total"], "clock_rule": clock_rule,
            "vessel_339": [r["alert_id"] for r in one.rows], "high": [r["alert_id"] for r in hi.rows],
            "customers": [(r["customer_id"], r["vessels_with_alerts"]) for r in cust1][:3],
            "by_customer_34_9": [r["alert_id"] for r in by_cust.rows],
            "by_vessel_420_5": [r["alert_id"] for r in by_vess.rows],
            "empty": none.status, "probe": (refused.status, len(refused.rows)), "past_clock": past_clock}
REVIEWED_1 = {"alerts": 12, "fleet_alerts_total": 12,
              "clock_rule": {"06T06": "voyage_watch:20260906T0000Z:1", "06T12": "voyage_watch:20260906T1200Z:1",
                             "before": "no_data"},
              "vessel_339": ["339/weather", "customer/11", "fleet"],
              "high": ["234/weather", "339/weather", "420/weather", "customer/3", "customer/11", "customer/34",
                       "fleet"],
              "customers": [(34, 4), (11, 3), (3, 1)],
              "by_customer_34_9": ["234/weather", "84/weather", "198/weather", "315/weather", "401/weather",
                                   "customer/34", "customer/9", "fleet"],
              "by_vessel_420_5": ["420/weather", "customer/3", "fleet"],
              "empty": "no_data", "probe": ("not_permitted", 0), "past_clock": "refused"}
assert actual_1 == REVIEWED_1, actual_1
shutil.rmtree(empty, ignore_errors=True)
print("✅ Phase 1 validation passed: watch_alerts = the pinned run's alerts + fleet row; the run is the latest at or "
      "before the clock; filters, an empty folder and the probe as expected; the CLI reads the moved functions")


# %% Phase 2 — fleet_customers
# An independent SQL over `vessels` for the same questions; the rows never carry a customer's name (level 2).
def sql(where: str, params: tuple) -> list[dict]:
    return db.fetch("SELECT vessel_id, vessel_name, vessel_type, customer_id FROM vessels WHERE " + where
                    + " ORDER BY customer_id, vessel_id", params)


f_cust = fleet.fleet_customers(fin_emp, customer_ids=[34, 9, 34])
f_ves = fleet.fleet_customers(ops_emp, vessel_ids=[420, 234])
f_name = fleet.fleet_customers(ops_emp, vessel_name="  cruise   voyager 234 ")
f_part = fleet.fleet_customers(ops_emp, vessel_name="Voyager 339")
f_many = fleet.fleet_customers(ops_emp, vessel_name="Voyager")
f_none = fleet.fleet_customers(ops_emp, vessel_name="Ever Given")
f_probe = fleet.fleet_customers(probe, vessel_ids=[1])
assert f_cust.rows == sql("customer_id = ANY(%s)", ([9, 34],))
assert sorted(f_ves.rows, key=lambda r: r["vessel_id"]) == sorted(sql("vessel_id = ANY(%s)", ([234, 420],)),
                                                                  key=lambda r: r["vessel_id"])
bad_args = 0
for args in ({}, {"vessel_ids": [1], "vessel_name": "x"}, {"customer_ids": []}, {"vessel_ids": list(range(1, 52))}):
    try:
        fleet.fleet_customers(ops_emp, **args)
    except ValidationError:
        bad_args += 1
no_names = all(set(r) == {"vessel_id", "vessel_name", "vessel_type", "customer_id"}
               for res in (f_cust, f_ves, f_name, f_part) for r in res.rows)
actual_2 = {"customers_9_34": len(f_cust.rows), "vessels": [(r["vessel_id"], r["customer_id"]) for r in f_ves.rows],
            "name": [r["vessel_id"] for r in f_name.rows], "part": [r["vessel_id"] for r in f_part.rows],
            "many": f_many.status, "unknown": f_none.status, "probe": (f_probe.status, len(f_probe.rows)),
            "bad_args": bad_args, "no_customer_names": no_names}
REVIEWED_2 = {"customers_9_34": 98, "vessels": [(234, 34), (420, 3)], "name": [234], "part": [339], "many": "no_data",
              "unknown": "no_data", "probe": ("not_permitted", 0), "bad_args": 4, "no_customer_names": True}
assert actual_2 == REVIEWED_2, actual_2
print("✅ Phase 2 validation passed: fleet_customers = the SQL over vessels (customer → vessels, vessel → customer, a "
      "name → its id); ambiguous / unknown names → no_data; ids only; the probe refused")


# %% Phase 3 — route_advice as a tool
# FakeRoles (the real parser, no quota) + the real PostgresSaver; PortWatch / Tavily answered by a mock transport
# into a throw-away cache. Each call = a new thread `route_advice:<employee>:…`; the rows = the graph's code results
# (= `route_advice.deterministic`); a twice-bad advice → ok + the advice row `validation_failed` with no
# recommendation; an unreadable reply → `output_invalid`; the probe → not_permitted before any model call.
sent: list[httpx.Request] = []


def _fake_http(req: httpx.Request) -> httpx.Response:
    sent.append(req)
    if "arcgis" in req.url.host:
        where = req.url.params["where"]
        start = date.fromisoformat(re.search(r"date >= DATE '([\d-]+)'", where).group(1))
        n = 40 if start.year == 2025 else 41                 # a year earlier 40 a day, now 41: +2.5 %
        return httpx.Response(200, json={"features": [{"attributes": {
            "date": (start + timedelta(days=i)).isoformat(), "n_total": n, "n_container": 10, "n_tanker": 8,
            "n_dry_bulk": 6, "n_general_cargo": 3, "n_roro": 1, "capacity": 1_000_000}} for i in range(28)]})
    return httpx.Response(200, json={"results": [{"title": "Suez Canal traffic update", "url": "https://example.org/n",
                                                  "content": "Canal operations continue.",
                                                  "published_date": "2026-09-10"}]})


def good_advice(cheaper: str) -> dict:
    other = "cape" if cheaper == "suez" else "suez"
    name = {"suez": "via Suez", "cape": "round the Cape"}
    return {"recommendation": cheaper,
            "headline": f"Sail {name[cheaper]}: {{route.compare[{cheaper}]:total_sdr|M}} against "
                        f"{{route.compare[{other}]:total_sdr|M}} {name[other]}.",
            "reasons": [{"text": f"The voyage costs {{route.compare[{cheaper}]:total_sdr|M}} {name[cheaper]}, fuel and "
                                 f"dues together.", "evidence_ids": ["route.compare"]},
                        {"text": "The Suez dues for one transit are {route.compare[suez]:suez_dues_sdr|k}.",
                         "evidence_ids": ["route.compare"]}],
            "risks": []}


mode = {"m": "good", "calls": 0}


def script(role, messages: list[BaseMessage], tools, schema):
    mode["calls"] += 1
    text = "\n".join(str(x.content) for x in messages)
    cheaper = json.loads(re.search(r"\[route\.difference\] (\{.*\})", text).group(1))["cheaper_route"]
    if mode["m"] == "invalid":
        return {"recommendation": "suez", "reasons": []}              # not a RouteAdvice
    adv = good_advice(cheaper)
    if mode["m"] == "always_bad":
        adv["headline"] += " That is about 2.2 M SDR."               # a typed number, twice
    return adv


CASES = {c["case"]: c for c in json.loads((ROOT / "Data/processed/agents/eval/route_cases.json")
                                          .read_text(encoding="utf-8"))["cases"]}
fake = roles.FakeRoles(script)
saver, pool = checkpointer.saver(), checkpointer.pool()
threads: list[str] = []
tmp_cache = Path(tempfile.mkdtemp(prefix="supervisor_tools_cache_"))
real_http, real_today = external.HTTP, external.TODAY


def advise(user, m: str = "good", **args):
    mode["m"] = m
    res = products.run_route_advice(user, fake, as_of=CLOCK, saver=saver, pool=pool, **args)
    adv = next((r for r in res.rows if r["route"] == "advice"), None)
    if adv:
        threads.append(adv["thread_id"])
    return res, adv


def code_rows(case: int) -> list[dict]:
    c = CASES[case]
    out = ra.deterministic(ceo, RouteRequest(vessel_id=c["vessel_id"], origin=c["origin"], destination=c["destination"],
                                             speed_kn=c["speed_kn"]), CLOCK, with_context=False)["evidence"]
    return [r for k in ("route.compare", "route.difference") for r in out[k]["rows"]]


try:
    external.HTTP = httpx.Client(transport=httpx.MockTransport(_fake_http), timeout=external.TIMEOUT_S)
    external.TODAY = date(2026, 10, 27)
    os.environ.setdefault("TAVILY_API_KEY", "check-only-key")        # the mock answers; nothing leaves the machine
    for name in ("suez_transits", "web_search"):
        external._caches[name] = external.ExternalCache(name, tmp_cache)
    per_case, recs = {}, {}
    for case in (1, 2, 3, 8):
        c = CASES[case]
        speed = {"speed_kn": c["speed_kn"]} if c["speed_kn"] is not None else {}
        res, adv = advise(ops_emp, vessel_id=c["vessel_id"], origin=c["origin"], destination=c["destination"], **speed)
        assert res.status == "ok" and adv["status"] == "ok", (case, res.status, adv)
        got = [r for r in res.rows if r["route"] in ("suez", "cape", "direct", "difference")]
        assert got == code_rows(case), case                         # the code rows, untouched by the tool
        assert any(r["route"] == "traffic" for r in res.rows)
        per_case[case] = len(res.rows)
        recs[case] = adv["recommendation"]
    c1 = CASES[1]
    calls0 = mode["calls"]
    bad, adv_bad = advise(ops_emp, "always_bad", vessel_id=c1["vessel_id"], origin=c1["origin"],
                          destination=c1["destination"])
    inv, adv_inv = advise(ops_emp, "invalid", vessel_id=c1["vessel_id"], origin=c1["origin"],
                          destination=c1["destination"])
    calls_before_probe = mode["calls"]
    p_res, _ = advise(probe, vessel_id=c1["vessel_id"], origin=c1["origin"], destination=c1["destination"])
    probe_calls = mode["calls"] - calls_before_probe
    shape, adv_shape = advise(ops_emp, vessel_id=c1["vessel_id"], origin="EGPSD", destination="NLRTM")
    # the LangChain tool: the user and the clock from the run context; none → refused
    tool_ = products.make_route_advice_tool(fake, saver, pool)
    mode["m"] = "good"
    via_tool = tool_.func(_Runtime(context.RunContext(fin_emp, as_of=CLOCK)), vessel_id=c1["vessel_id"],
                          origin=c1["origin"], destination=c1["destination"])
    threads.append(next(r for r in via_tool["rows"] if r["route"] == "advice")["thread_id"])
    try:
        tool_.func(_Runtime(None), vessel_id=c1["vessel_id"], origin=c1["origin"], destination=c1["destination"])
        no_ctx = "ran"
    except PermissionError:
        no_ctx = "refused"
    prefixes = sorted({t.rsplit(":", 1)[0].split(":")[1] for t in threads})
    unique_threads = len(set(threads)) == len(threads)
finally:
    external.HTTP, external.TODAY = real_http, real_today
    shutil.rmtree(tmp_cache, ignore_errors=True)

actual_3 = {"rows_per_case": per_case, "recommendations": recs,
            "always_bad": (bad.status, adv_bad["status"], adv_bad["recommendation"],
                           sorted({r["route"] for r in bad.rows})),
            "invalid": (inv.status, adv_inv["status"], adv_inv["recommendation"]),
            "probe": (p_res.status, len(p_res.rows), probe_calls),
            "port_said": (shape.status, adv_shape["status"]), "via_tool": via_tool["status"], "no_context": no_ctx,
            "thread_employees": prefixes, "unique_threads": unique_threads,
            "network": sorted({r.url.host for r in sent})}
REVIEWED_3 = {"rows_per_case": {1: 5, 2: 5, 3: 5, 8: 5}, "recommendations": {1: "suez", 2: "suez", 3: "suez",
                                                                             8: "cape"},
              "always_bad": ("ok", "validation_failed", None, ["advice", "cape", "difference", "suez", "traffic"]),
              "invalid": ("ok", "output_invalid", None), "probe": ("not_permitted", 0, 0),
              "port_said": ("ok", "no_suez_on_route"), "via_tool": "ok", "no_context": "refused",
              "thread_employees": ["12", "13"], "unique_threads": True,
              "network": sorted({r.url.host for r in sent})}
assert actual_3 == REVIEWED_3, actual_3
assert all(h.endswith("arcgis.com") or "tavily" in h for h in actual_3["network"]), actual_3["network"]
print(f"route_advice: {len(threads)} threads, fake model calls {mode['calls']}, mock hosts {actual_3['network']}")
print("✅ Phase 3 validation passed: route_advice as a tool — a thread per call, the rows = the graph's code results, "
      "a stopped advice keeps its rows (validation_failed / output_invalid, no recommendation), the probe refused "
      "with 0 model calls, the wrapper refuses a missing context")


# %% Phase 4 — The golden contract
# Every `value` element of the frozen S2 golden set is re-computed by calling the registered tool function as the
# item's asker at the clock: a finance element of an Operations twin must come back not_permitted with no row; every
# other element must equal its frozen value. A watch element's `args.thread` is matched against the run the tool
# resolved (S2 decision 2: the model never names the run).
ROW_KEY = {("finance_kpi", "customers"): "customer_id", ("finance_kpi", "overdue"): "invoice_number",
           ("route_advice", None): "route", ("watch_alerts", None): "alert_id"}
FNS = {**{k: f for k, (_, f) in registry.STAGE1.items()}, **{k: f for k, (_, f) in registry.STAGE2.items()},
       **{k: f for k, (_, f) in registry.PRODUCTS.items()}}
users = {}
memo: dict[str, object] = {}
checked, refused_ok, mismatch = 0, 0, []
try:
    external.HTTP = httpx.Client(transport=httpx.MockTransport(_fake_http), timeout=external.TIMEOUT_S)
    external.TODAY = date(2026, 10, 27)
    tmp_cache = Path(tempfile.mkdtemp(prefix="supervisor_tools_cache_"))
    for name in ("suez_transits", "web_search"):
        external._caches[name] = external.ExternalCache(name, tmp_cache)
    by_id = {i["id"]: i for i in GOLD}
    for item in GOLD:
        u = users.setdefault(item["employee_id"], context.load_user(item["employee_id"]))
        els = [e for e in item["elements"] if e["kind"] == "value"]
        if item["expected_status"] == "partial":          # the twin dropped its finance elements: they must be refused
            els += [e for e in by_id[item["twin_of"]]["elements"] if e["kind"] == "value" and e["product"] == "finance"]
        for el in els:
            tool, args = el["tool"], dict(el["args"])
            key = json.dumps([u.employee_id, tool, args], sort_keys=True)
            if key not in memo:
                if tool == "watch_alerts":
                    memo[key] = watch.watch_alerts(u, as_of=CLOCK)
                elif tool == "route_advice":
                    mode["m"] = "good"
                    memo[key] = products.run_route_advice(u, fake, as_of=CLOCK, saver=saver, pool=pool, **args)
                    adv = next((r for r in memo[key].rows if r["route"] == "advice"), None)
                    threads.append(adv["thread_id"]) if adv else None
                elif tool == "finance_kpi":
                    memo[key] = finance.finance_kpi(u, limit=50, **args) if args["dataset"] in ("customers", "overdue") \
                        else finance.finance_kpi(u, **args)
                elif tool in ("voyage_status", "voyage_eta"):
                    memo[key] = FNS[tool](u, as_of=CLOCK, **args)
                else:
                    memo[key] = FNS[tool](u, **args)
            res = memo[key]
            if el["product"] == "finance" and item["asker"] == "ops_employee":
                ok = res.status == "not_permitted" and not res.rows
                refused_ok += ok
                mismatch += [] if ok else [(item["id"], tool, res.status)]
                continue
            if res.status != "ok":
                mismatch.append((item["id"], tool, res.status))
                continue
            if tool == "watch_alerts" and res.rows[-1]["thread_id"] != args.get("thread"):
                mismatch.append((item["id"], "watch run", res.rows[-1]["thread_id"]))
            rk = ROW_KEY.get((tool, args.get("dataset")))
            row = res.rows[0] if el["row"] is None else next((r for r in res.rows if str(r[rk]) == el["row"]), None)
            got = {f: row[f] for f in el["values"]} if row else None
            checked += 1
            if got != el["values"]:
                mismatch.append((item["id"], tool, el["row"], got, el["values"]))
finally:
    external.HTTP, external.TODAY = real_http, real_today
    shutil.rmtree(tmp_cache, ignore_errors=True)
assert not mismatch, mismatch[:5]
n_values = sum(e["kind"] == "value" for i in GOLD for e in i["elements"])
n_refused = sum(e["kind"] == "value" and e["product"] == "finance" for i in GOLD if i["expected_status"] == "partial"
                for e in by_id[i["twin_of"]]["elements"])
actual_4 = {"value_elements": n_values, "reproduced": checked, "finance_elements_of_twins": n_refused,
            "refused_as_expected": refused_ok,
            "tools": sorted({e["tool"] for i in GOLD for e in i["elements"] if e["kind"] == "value"})}
REVIEWED_4 = {"value_elements": 41, "reproduced": 41, "finance_elements_of_twins": 6, "refused_as_expected": 6,
              "tools": ["compute_toll", "finance_kpi", "route_advice", "sea_route", "vessel_params", "voyage_eta",
                        "voyage_status", "watch_alerts"]}
assert actual_4 == REVIEWED_4, actual_4
needed = sorted({t for i in GOLD for t in i["tools_needed"]})
assert set(needed) <= {t.name for t in registry.supervisor_tools(None)}, needed
print(f"golden contract: {checked} value elements reproduced, {refused_ok} finance elements refused to the Operations "
      f"employees; tools_needed {needed}")
print("✅ Phase 4 validation passed: every frozen value reproduced by its tool as its asker at the clock; every finance "
      "element of an Operations twin refused with no row; every tool an item needs is in the supervisor's union")


# %% Phase 5 — RBAC matrix + contract
# 100 employees × the 4 product tools = the ADR-006 expectation from each tool's resources (all level 1 → granted);
# the probe user is refused by all 4 with no row and no source (leakage 0; route_advice with 0 model calls); no
# model-facing schema has a user, dataset, clock or watch-run field; every wrapper refuses a missing run context.
RESOURCES = {"voyage_eta": [context.AIS_TRACKS, context.PORTS, context.VESSELS, context.VESSEL_PARAMS],
             "watch_alerts": [context.AIS_TRACKS, context.PORTS, context.VESSELS, context.VESSEL_PARAMS],
             "fleet_customers": [context.VESSELS],
             "route_advice": [context.VESSEL_PARAMS, context.VESSELS, context.AIS_TRACKS, context.PORTS,
                              context.TOLL_BANDS]}
c1 = CASES[1]
CALLS = {"voyage_eta": {"vessel_id": 5}, "watch_alerts": {}, "fleet_customers": {"vessel_ids": [1]},
         "route_advice": {"vessel_id": c1["vessel_id"], "origin": c1["origin"], "destination": c1["destination"]}}


def call(name: str, u):
    if name == "route_advice":
        mode["m"] = "good"
        r = products.run_route_advice(u, fake, as_of=CLOCK, saver=saver, pool=pool, **CALLS[name])
        adv = next((x for x in r.rows if x["route"] == "advice"), None)
        threads.append(adv["thread_id"]) if adv else None
        return r
    if name in ("voyage_eta", "watch_alerts"):
        return registry.PRODUCTS[name][1](u, as_of=CLOCK, **CALLS[name])
    return registry.PRODUCTS[name][1](u, **CALLS[name])


users_all = {r["employee_id"]: context.load_user(r["employee_id"]) for r in db.fetch("SELECT employee_id FROM employees")}
matrix_bad, granted = [], 0
try:
    external.HTTP = httpx.Client(transport=httpx.MockTransport(_fake_http), timeout=external.TIMEOUT_S)
    external.TODAY = date(2026, 10, 27)
    tmp_cache = Path(tempfile.mkdtemp(prefix="supervisor_tools_cache_"))
    for name in ("suez_transits", "web_search"):
        external._caches[name] = external.ExternalCache(name, tmp_cache)
    for emp_id, u in users_all.items():
        for name in RESOURCES:
            expect = all(allowed(u, r.level, r.department) for r in RESOURCES[name])
            res = call(name, u)
            ok = res.status == "ok" if expect else (res.status == "not_permitted" and not res.rows)
            granted += res.status == "ok"
            matrix_bad += [] if ok else [(emp_id, name, res.status)]
    calls0 = mode["calls"]
    leak = [(n, r.status) for n in RESOURCES for r in [call(n, probe)]
            if r.status != "not_permitted" or r.rows or r.source is not None]
    probe_model_calls = mode["calls"] - calls0
finally:
    external.HTTP, external.TODAY = real_http, real_today
    shutil.rmtree(tmp_cache, ignore_errors=True)
opened = supervisor_threads() - THREADS_BEFORE                  # incl. the refused calls' threads (no advice row)
assert set(threads) <= opened, sorted(set(threads) - opened)[:3]
for t in opened:
    saver.delete_thread(t)
assert not supervisor_threads() - THREADS_BEFORE
assert not matrix_bad, matrix_bad[:5]
assert not leak, leak

product_tools = {t.name: t for t in registry.supervisor_tools(fake) if t.name in RESOURCES}
FORBIDDEN = ("user", "employee_id", "dataset", "as_of", "runtime", "thread", "thread_id", "folder")
bad_schema = {n: sorted(f for f in t.tool_call_schema.model_json_schema()["properties"] if f in FORBIDDEN)
              for n, t in product_tools.items()}
assert not any(bad_schema.values()), bad_schema
no_ctx = 0
for n, t in product_tools.items():
    try:
        t.func(_Runtime(None), **CALLS[n])
    except PermissionError:
        no_ctx += 1
union = [t.name for t in registry.supervisor_tools(fake)]
actual_5 = {"employees": len(users_all), "calls_granted": granted, "matrix_mismatch": len(matrix_bad),
            "probe_leaks": len(leak), "probe_model_calls": probe_model_calls, "bad_schema": 0,
            "no_context_refused": no_ctx, "union": len(union), "union_unique": len(set(union)) == len(union)}
REVIEWED_5 = {"employees": 100, "calls_granted": 400, "matrix_mismatch": 0, "probe_leaks": 0, "probe_model_calls": 0,
              "bad_schema": 0, "no_context_refused": 4, "union": 14, "union_unique": True}
assert actual_5 == REVIEWED_5, actual_5
print(f"Phase 5: RBAC matrix 100 employees × 4 product tools = ADR-006 (400 granted), probe refused by all 4 with no "
      f"row and 0 model calls, no user / clock / run field in a schema, {no_ctx} / 4 wrappers refuse a missing "
      f"context; {len(opened)} check threads deleted (incl. {len(opened) - len(threads)} of refused calls)")
print("✅ Phase 5 validation passed: the RBAC matrix of the product tools = ADR-006, leakage 0, the contract holds")


# %% Final Checkpoint
# Narrative: pipelines/checkpoints/agents/Supervisor_tools_check.md
assert weather.SENT == SENT0, (weather.SENT, SENT0)
print(f"✅ Final Checkpoint: the supervisor's product tools — watch_alerts, fleet_customers, route_advice (graph as a "
      f"tool), voyage_eta — in registry.PRODUCTS; the golden contract reproduced ({checked} values, {refused_ok} "
      f"refusals); RBAC 400 / 400, leakage 0; 0 real model calls, 0 Open-Meteo calls")
