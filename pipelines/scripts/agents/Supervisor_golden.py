"""S2 Q&A golden set (Agents plan Phase 12, §6d step S1): operations + cross-product questions with RBAC twins and
Egyptian Arabic twins, frozen before the supervisor exists.

Plan:    docs/archive/2026-11-01_Agents_plan.md §6d (APPROVED 2026-10-29, P12-1…P12-5) and its S1 plan in Progress (APPROVED
         2026-10-29 with the owner's four answers: the customer bridge in, one pinned clock + explicit 2025 weeks, the
         partial answer scored on the result's status + refused tools and the text, 10 Arabic twins); §8a G2–G4.
Run:     uv run python tools/run.py pipelines/scripts/agents/Supervisor_golden.py  (from the project root)

Reads:   PostgreSQL read-only (PG_RO_USER) and MongoDB read-only (MONGO_RO_USER) through the Stage 1 / Stage 2 tool
         functions as the CEO at the pinned clock (finance_kpi, compute_toll, voyage_status, voyage_eta, vessel_params,
         sea_route, the route_advice graph's code part without its context); employees / roles / departments for the
         askers; `vessels.customer_id` for the customer bridge (a level-1 id, docs/rbac_mapping.md); the voyage file;
         Data/processed/agents/eval/route_cases.json; the pinned watch run reports/voyage_watch/
         voyage_watch_20260913T0000Z_1.json (its sha256 is stored in every watch item).
Writes:  Data/processed/agents/eval/supervisor_qa_golden.jsonl — one item per line, frozen: a re-run recomputes it and
         stops if anything differs; a later change only through a recorded REFREEZE (old sha prefix + reason).
Re-run:  safe (read-only). 0 model calls, 0 Open-Meteo / PortWatch / web calls (weather enters only through the pinned
         run's alerts; the route costs are computed without their news / traffic context).

The questions are written by hand (below), every expected value comes from a tool result at freeze time, so an item
never expects a number the data does not hold. The item format is the Stage 1 golden item (Qa_golden.py) plus:
`as_of` (the pinned clock), `products` (finance / operations), a `product` tag on each element (an element whose
selection depends on a finance result is a finance element), the status `partial` with `refused_any` (P12-3), and
value elements of the Stage 2 product tools (`route_advice`, `voyage_eta`, `watch_alerts`, the bridge `fleet_customers`)
whose contracts S2 implements as fixed here.

Phases
1. The clock and the askers.
2. ≈ 20 operations items (EN).
3. ≈ 10 cross-product items (EN).
4. RBAC twins (Operations → partial, Finance → operations answered, a CEO control).
5. Egyptian Arabic twins (G2) + freeze.
Final Checkpoint (narrative: pipelines/checkpoints/agents/Supervisor_golden.md).
"""
# %% Setup
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())
sys.path.insert(0, str(ROOT))
from pipelines.agents.graphs import route_advice  # noqa: E402
from pipelines.agents.graphs.models import RouteRequest  # noqa: E402
from pipelines.agents.tools import context, db, eta, finance, routes, tariff, vessels, voyages, weather  # noqa: E402

EVAL = ROOT / "Data" / "processed" / "agents" / "eval"
GOLDEN = EVAL / "supervisor_qa_golden.jsonl"
ROUTE_CASES = EVAL / "route_cases.json"
WATCH_THREAD = "voyage_watch:20260913T0000Z:1"
WATCH_FILE = ROOT / "reports" / "voyage_watch" / "voyage_watch_20260913T0000Z_1.json"
SENT0 = dict(weather.SENT)          # Open-Meteo requests sent by this process (must stay 0); no model is ever built here


# %% Phase 1 — The clock and the askers
# One clock for every item (owner answer 2, 2026-10-29): the data's as-of instant 2026-09-13T00:00Z = the clock of the
# latest saved watch run, which is pinned by its sha256 (a re-run of that run cannot shift the expected alerts
# silently). Finance questions name their 2025 week explicitly; the operations part is "now" = the clock.
# Askers by the Stage 1 v2 rule (D-P7-3): the two lowest employee ids per profile, a profile's questions alternating
# between them (the CEO is one person). Every Stage 2 resource is level 1 / Operations (ADR-055 / 057 / 058), so
# "RBAC both ways" = an Operations user is refused the finance part, a Finance user is answered the operations part.
CLOCK = context.DATA_AS_OF
CLOCK_ISO = CLOCK.isoformat().replace("+00:00", "Z")
assert CLOCK == datetime.fromisoformat("2026-09-13T00:00:00+00:00")
RUN = json.loads(WATCH_FILE.read_text(encoding="utf-8"))
WATCH_SHA = hashlib.sha256(WATCH_FILE.read_bytes()).hexdigest()
assert RUN["thread_id"] == WATCH_THREAD and RUN["as_of"].startswith("2026-09-13T00:00") and RUN["status"] == "ok"
assert RUN["fleet"]["weather_failed_points"] == 0, RUN["fleet"]         # a complete run (D-P11-2), not a degraded one


def lowest(role: str, dept: str | None, n: int) -> list[int]:
    rows = db.fetch("SELECT e.employee_id FROM employees e JOIN roles r USING (role_id) "
                    "JOIN departments d USING (department_id) WHERE r.role_name = %s "
                    + ("AND d.department_name = %s " if dept else "") + f"ORDER BY e.employee_id LIMIT {n}",
                    (role, dept) if dept else (role,))
    return [r["employee_id"] for r in rows]


ASKERS = {"ops_employee": lowest("employee", "Operations", 2), "ops_manager": lowest("manager", "Operations", 2),
          "finance_employee": lowest("employee", "Finance", 2), "ceo": lowest("ceo", None, 1)}
USERS = {k: [context.load_user(e) for e in v] for k, v in ASKERS.items()}
CEO = USERS["ceo"][0]
OPS_RES = (context.AIS_TRACKS, context.PORTS, context.VESSELS, context.VESSEL_PARAMS, context.TOLL_BANDS,
           context.PUBLIC_EXTERNAL)
assert all(u.department == "Operations" for u in USERS["ops_employee"] + USERS["ops_manager"])
assert all(u.department == "Finance" for u in USERS["finance_employee"])
assert all(context.permitted(u, *OPS_RES) for v in USERS.values() for u in v)          # level 1: everyone
# the refused side is the Operations *employee* (ceiling 1): an Operations manager's ceiling is 2, so the finance views
# (level 2 / Finance) are permitted to him (ADR-006; Stage 1 refused him only the level-3 HbR results, r03 / r03b)
assert not any(context.permitted(u, context.FINANCE_VIEWS) for u in USERS["ops_employee"])
assert all(context.permitted(u, context.FINANCE_VIEWS)
           for u in USERS["ops_manager"] + USERS["finance_employee"] + USERS["ceo"])
snapshot = {"ops_employee": [12, 17], "ops_manager": [2, 3], "finance_employee": [13, 24], "ceo": [1]}
assert ASKERS == snapshot, ASKERS
print(f"clock {CLOCK_ISO}; watch run {WATCH_THREAD} sha256 {WATCH_SHA[:16]}… ({RUN['fleet']['alerts_total']} alerts, "
      f"{RUN['fleet']['alerts_high']} high, weather unknown points {RUN['fleet']['weather_unknown_points']})")
print("askers:", {k: [(u.employee_id, u.role, u.department) for u in v] for k, v in USERS.items()})
print("✅ Phase 1 validation passed: one pinned clock + the pinned watch run; 7 askers by rule; everyone passes every "
      "Stage 2 resource; only the Operations employees fail the finance views (managers' ceiling 2)")


# %% Phase 2 — The operations items (EN)
# Asked by the Operations employees (the desk's audience; the watch items by the Operations managers, the watch's own
# identity), expected values from the tools as the CEO at the clock. Vessels picked by rule from the pinned run's
# fleet (lowest ids with the needed property), each pick asserted in the reviewed snapshot below.
# Element kinds (scored by S5's Stage2_eval.py, the Stage 1 kinds):
#   value     a slot bound to a cited result of `tool` whose arguments include `args`, on `row` (if given), with a
#             field in `field_any` (`values` stored for the record — the slot writes them)
#   name      the rendered answer names one of `text_any` (a vessel, a port, a status, a route, a date's forms)
#   direction the rendered answer carries the direction: one of `text_any`
# Every element carries `product` (operations / finance); relevance = the week (if any) + one metric word + the
# subject (a vessel's name or id forms, if any).
METRIC = {"position": ["position", "where", "at sea", "transit", "sailing", "underway", "next port", "heading"],
          "distance": ["nm", "nautical", "miles", "distance"], "eta": ["ETA", "arriv", "expected"],
          "status": ["anchor", "port", "berth", "arriv", "complet", "status"],
          "route": ["Suez", "Cape", "route"], "dues": ["dues", "toll", "Suez"], "fuel": ["fuel", "t/day", "tonnes"],
          "watch": ["alert", "wave", "wind", "weather", "storm"], "traffic": ["traffic", "transit"],
          "billed": ["bill", "revenue", "invoic"], "ar": ["receivable", "owe", "AR "], "overdue": ["overdue"],
          "customer": ["customer"]}
WATCHED = {e["vessel_id"]: e for e in RUN["etas"]}
ALERTS = {a["alert_id"]: a for a in RUN["alerts"]}
PORT_NAME = {r["locode"]: r["name"] for r in db.fetch("SELECT locode, name FROM ports")}
V_NAME = {r["vessel_id"]: r["vessel_name"] for r in db.fetch("SELECT vessel_id, vessel_name FROM vessels")}
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]


def res_json(r) -> dict:
    d = r.model_dump(mode="json")
    assert d["status"] == "ok", (d["tool"], d["status"], d.get("note"))
    return d


def value(tool: str, args: dict, fields: list[str], res: dict, row_key: str | None = None, row: str | None = None,
          product: str = "operations") -> dict:
    rows = res["rows"]
    r = rows[0] if row is None else next(x for x in rows if str(x[row_key]) == row)
    vals = {f: r[f] for f in fields}
    assert all(isinstance(v, (int, float)) and v is not None for v in vals.values()), (tool, args, row, vals)
    return {"kind": "value", "product": product, "tool": tool, "args": args, "row": row, "field_any": fields,
            "values": vals}


def name(*texts: str, product: str = "operations") -> dict:
    return {"kind": "name", "product": product, "text_any": list(dict.fromkeys(t for t in texts if t))}


def direction(words: list[str], product: str = "operations") -> dict:
    return {"kind": "direction", "product": product, "text_any": words}


AR_MONTHS = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر",
             "ديسمبر"]
AR_DIGITS = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")
ROUTE_WORDS = {"suez": ["Suez", "السويس"], "cape": ["Cape", "الرجاء الصالح"]}


def date_forms(ts: str) -> list[str]:
    """The written forms of a UTC instant's date: ISO, '21 September', 'September 21', 'Sep 21', '21 Sep', and the
    Egyptian Arabic '21 سبتمبر' in Western and Arabic-Indic digits (one list for both languages)."""
    d = pd.Timestamp(ts).tz_convert("UTC") if pd.Timestamp(ts).tzinfo else pd.Timestamp(ts)
    m, am = MONTHS[d.month - 1], AR_MONTHS[d.month - 1]
    return [d.strftime("%Y-%m-%d"), f"{d.day} {m}", f"{m} {d.day}", f"{m[:3]} {d.day}", f"{d.day} {m[:3]}",
            f"{d.day} {am}", f"{d.day} {am}".translate(AR_DIGITS)]


def vessel(vid: int, product: str = "operations") -> dict:
    return name(V_NAME[vid], f"vessel {vid}", f"#{vid}", f"السفينة {vid}", f"المركب {vid}", product=product)


def port(locode: str) -> dict:
    return name(locode, PORT_NAME.get(locode))


items: list[dict] = []
_turn = {k: 0 for k in ASKERS}


def add(qid: str, asker: str, question: str, status: str, elements: list[dict], metric: list[str],
        week: int | None = None, subject: int | None = None, **extra) -> None:
    ids = ASKERS[asker]
    employee = ids[_turn[asker] % len(ids)]             # the profile's two employees in turn (D-P7-3)
    _turn[asker] += 1
    products = extra.pop("products", None) or sorted({e["product"] for e in elements}) or ["operations"]
    items.append({"id": qid, "lang": "en", "asker": asker, "employee_id": employee, "question": question,
                  "expected_status": status, "as_of": CLOCK_ISO, "products": products, "elements": elements,
                  "relevance": {"week": week, "metric_any": sorted({w for m in metric for w in METRIC[m]}),
                                "subject_any": ([V_NAME[subject], str(subject)] if subject else [])},
                  **extra})


def status_of(vid: int) -> dict:
    return res_json(voyages.voyage_status(CEO, as_of=CLOCK, vessel_id=vid))


def eta_of(vid: int) -> dict:
    return res_json(eta.voyage_eta(CEO, as_of=CLOCK, vessel_id=vid))


OE, OM = "ops_employee", "ops_manager"
in_transit = sorted(v for v, e in WATCHED.items() if e["status"] == "In Transit")
anchored = sorted(v for v, e in WATCHED.items() if e["status"] == "Anchored")
# --- voyage status (4)
v1 = in_transit[0]
s1 = status_of(v1)
add("o01", OE, f"Where is {V_NAME[v1]} now and what is its next port?", "answered",
    [name("transit", "at sea", "sailing", "underway", "en route", "في الطريق", "مبحر", "بتبحر", "في البحر"), port(s1["rows"][0]["next_port"])],
    ["position"], subject=v1)
v2 = in_transit[1]
s2 = status_of(v2)
add("o02", OE, f"How many nautical miles does vessel {v2} still have to sail to its destination?", "answered",
    [value("voyage_status", {"vessel_id": v2}, ["distance_left_nm"], s2)], ["distance"], subject=v2)
v3 = anchored[0]
s3 = status_of(v3)
assert s3["rows"][0]["status_at_as_of"] == "Anchored"
add("o03", OE, f"Is {V_NAME[v3]} moving right now?", "answered", [name("anchor", "مخطاف", "راسي", "راسية", "رست")], ["status"], subject=v3)
completed = sorted(v for v in V_NAME if v not in WATCHED)
s4 = next(s for s in (status_of(v) for v in completed[:20]) if s["rows"][0]["arrival_ts"])
v4 = s4["rows"][0]["vessel_id"]
add("o04", OE, f"Has vessel {v4} finished its voyage, and when did it arrive?", "answered",
    [name("arriv", "complet", "finished", "port", "وصل", "وصلت", "خلص", "خلصت"), name(*date_forms(s4["rows"][0]["arrival_ts"]))], ["status"],
    subject=v4)
# --- ETA (4): voyage_eta = rule R at the clock; equal to the pinned run's ETA (asserted below)
v5, v6, v7, v8 = in_transit[2:6]
e5, e6, e7, e8 = (eta_of(v) for v in (v5, v6, v7, v8))
add("o05", OE, f"When will {V_NAME[v5]} arrive at {PORT_NAME[e5['rows'][0]['destination']]}?", "answered",
    [name(*date_forms(e5["rows"][0]["eta_utc"]))], ["eta"], subject=v5)
add("o06", OE, f"What is the ETA of vessel {v6} at its destination?", "answered",
    [name(*date_forms(e6["rows"][0]["eta_utc"])), port(e6["rows"][0]["destination"])], ["eta"], subject=v6)
add("o07", OE, f"How many hours until {V_NAME[v7]} reaches its destination?", "answered",
    [value("voyage_eta", {"vessel_id": v7}, ["eta_in_h"], e7)], ["eta"], subject=v7)
add("o08", OE, f"At what speed is vessel {v8} sailing for its ETA, and how far does it still have to go?", "answered",
    [value("voyage_eta", {"vessel_id": v8}, ["speed_kn"], e8), value("voyage_eta", {"vessel_id": v8},
                                                                      ["distance_left_nm"], e8)], ["eta", "distance"],
    subject=v8)
# --- route advice (4): the graph's code rows (no writer call, no context) for frozen route cases
CASES = {c["case"]: c for c in json.loads(ROUTE_CASES.read_text(encoding="utf-8"))["cases"]}


def route_rows(case: int) -> tuple[dict, dict]:
    c = CASES[case]
    req = RouteRequest(vessel_id=c["vessel_id"], origin=c["origin"], destination=c["destination"],
                       speed_kn=c["speed_kn"])
    out = route_advice.deterministic(CEO, req, CLOCK, with_context=False)
    assert out["status"] is None, (case, out["status"])
    args = {"vessel_id": c["vessel_id"], "origin": c["origin"], "destination": c["destination"]}
    if c["speed_kn"] is not None:            # v2 (D-P12-3): a case's speed is part of the question and of the call
        args["speed_kn"] = c["speed_kn"]
    return out["evidence"], args


def route_val(ev: dict, args: dict, row: str, fields: list[str]) -> dict:
    key = "route.difference" if row == "difference" else "route.compare"
    return value("route_advice", args, fields, ev[key], "route", row)


ev1, a1 = route_rows(1)
cheap1 = ev1["route.difference"]["rows"][0]["cheaper_route"]
add("o09", OE, f"Should vessel {a1['vessel_id']} go from Singapore to Rotterdam via Suez or the Cape? Which is "
               "cheaper and by how much?", "answered",
    [name(*ROUTE_WORDS[cheap1]), route_val(ev1, a1, "difference", ["change_total_sdr"])],
    ["route"], subject=a1["vessel_id"])
ev2, a2 = route_rows(2)
add("o10", OE, f"How many more sea days does vessel {a2['vessel_id']} need from Singapore to Rotterdam if it avoids "
               "Suez?", "answered", [route_val(ev2, a2, "difference", ["change_sea_days"])], ["route"],
    subject=a2["vessel_id"])
ev3, a3 = route_rows(3)
add("o11", OE, f"What Suez Canal dues would vessel {a3['vessel_id']} pay from Rotterdam to Singapore?", "answered",
    [route_val(ev3, a3, "suez", ["suez_dues_sdr"])], ["dues"], subject=a3["vessel_id"])
ev8, a8 = route_rows(8)
cheap8 = ev8["route.difference"]["rows"][0]["cheaper_route"]
assert a8.get("speed_kn") == 12.0 and all("speed_kn" not in a for a in (a1, a2, a3))
add("o12", OE, f"For vessel {a8['vessel_id']} sailing {a8['origin']} → {a8['destination']} at {a8['speed_kn']:g} "
               "knots, which route costs less in total, Suez or the Cape?", "answered",
    [name(*ROUTE_WORDS[cheap8]), route_val(ev8, a8, "difference", ["change_total_sdr"])],
    ["route"], subject=a8["vessel_id"])
# --- the watch (3): the pinned run's alerts and fleet row (tool watch_alerts, S2)
WATCH_ARGS = {"thread": WATCH_THREAD}
watch_res = {"rows": [{"alert_id": a["alert_id"], **a} for a in RUN["alerts"]]
             + [{"alert_id": "fleet", **{k: v for k, v in RUN["fleet"].items() if isinstance(v, (int, float))}}]}
high = sorted((a for a in RUN["alerts"] if a["severity"] == "high"), key=lambda a: a["vessel_id"])
add("o13", OM, "Which vessels have a high weather alert in the latest voyage watch?", "answered",
    [vessel(a["vessel_id"]) for a in high], ["watch"], watch_sha=WATCH_SHA)
w2 = high[1]
add("o14", OM, f"How high are the waves forecast on the next leg of {w2['vessel_name']}?", "answered",
    [value("watch_alerts", WATCH_ARGS, ["wave_height_max_m"], watch_res, "alert_id", w2["alert_id"])], ["watch"],
    subject=w2["vessel_id"], watch_sha=WATCH_SHA)
add("o15", OM, "How does Suez Canal traffic compare with a year earlier in the latest voyage watch?", "answered",
    [value("watch_alerts", WATCH_ARGS, ["change_transits_pct"], watch_res, "alert_id", "fleet"),
     direction(["up", "higher", "more", "increase", "+", "rose", "stable", "similar", "زاد", "أعلى", "أكتر", "مستقر"])], ["traffic"],
    watch_sha=WATCH_SHA)
# --- fuel (2) and distance (1)
f1 = res_json(vessels.vessel_params(CEO, vessel_id=a1["vessel_id"], speed_kn=14.0))
add("o16", OE, f"How much fuel does vessel {a1['vessel_id']} burn per day at 14 knots, and what does it cost?",
    "answered", [value("vessel_params", {"vessel_id": a1["vessel_id"], "speed_kn": 14.0}, ["fuel_t_per_day"], f1),
                 value("vessel_params", {"vessel_id": a1["vessel_id"], "speed_kn": 14.0}, ["fuel_cost_sdr_per_day"],
                       f1)], ["fuel"], subject=a1["vessel_id"])
f2 = res_json(vessels.vessel_params(CEO, vessel_type="Containerships", scnt_tons=60000.0, speed_kn=18.0))
add("o17", OE, "What is the daily fuel consumption of a containership of 60,000 SCNT at 18 knots?", "answered",
    [value("vessel_params", {"vessel_type": "Containerships", "scnt_tons": 60000.0, "speed_kn": 18.0},
           ["fuel_t_per_day"], f2)], ["fuel"])
d1 = res_json(routes.sea_route(CEO, origin="SGSIN", destination="NLRTM", avoid=["suez"]))
add("o18", OE, "How long is the sea route from Singapore to Rotterdam around the Cape of Good Hope?", "answered",
    [value("sea_route", {"origin": "SGSIN", "destination": "NLRTM", "avoid": ["suez"]}, ["distance_nm"], d1)],
    ["distance"])
# --- abstention (3): nothing in the data → "not in the data", no NileGate number (G3)
NO_NUMBER = {"no_nilegate_number": True}
nov = 9999
assert voyages.voyage_status(CEO, as_of=CLOCK, vessel_id=nov).status == "no_data"
add("a01", OE, f"Where is vessel {nov} now?", "not_in_data", [], ["position"], **NO_NUMBER)
add("a02", OE, "What is the live AIS position of the Ever Given right now?", "not_in_data", [], ["position"],
    **NO_NUMBER)
add("a03", OE, "How many ships will transit the Suez Canal in December 2026?", "not_in_data", [], ["traffic"],
    **NO_NUMBER)

# the ETAs of the tool at the clock = the pinned run's ETAs (the same rule R on the same fixes)
for v, e in ((v5, e5), (v6, e6), (v7, e7), (v8, e8)):
    assert e["rows"][0]["eta_utc"] == WATCHED[v]["eta_utc"], (v, e["rows"][0]["eta_utc"], WATCHED[v]["eta_utc"])
statuses = pd.Series([i["expected_status"] for i in items]).value_counts().to_dict()
picks = {"o01": v1, "o02": v2, "o03": v3, "o04": v4, "o05": v5, "o06": v6, "o07": v7, "o08": v8,
         "o09": (a1["vessel_id"], cheap1), "o12": (a8["vessel_id"], cheap8), "o13": [a["vessel_id"] for a in high],
         "o14": w2["vessel_id"]}
print("picks:", picks)
snapshot = {"ops": 21, "answered": 18, "not_in_data": 3,
            "picks": {"o01": 1, "o02": 2, "o03": 3, "o04": 7, "o05": 5, "o06": 6, "o07": 10, "o08": 12,
                      "o09": (21, "suez"), "o12": (6, "cape"), "o13": [234, 339, 420], "o14": 339}}
actual = {"ops": len(items), **{k: statuses.get(k, 0) for k in ("answered", "not_in_data")}, "picks": picks}
assert actual == snapshot, actual
assert len({i["id"] for i in items}) == len(items)
print("✅ Phase 2 validation passed: 21 operations items (18 answerable, 3 abstention), every expected value from a "
      "tool at the clock, the tool's ETAs = the pinned run's")


# %% Phase 3 — The cross-product items (EN)
# Asked by the Finance employees (they may read both products → `answered`). The finance part names its 2025 week; the
# operations part is "now" = the clock. Customer → vessels goes through the bridge `fleet_customers` (owner answer 1:
# S2 adds a code lookup over `vessels.customer_id`, a level-1 id; the customer's name and money stay level 2 / Finance);
# here the bridge is read straight from `vessels` as the CEO. An element whose selection depends on a finance result
# is a finance element (its RBAC twin drops it); `tools_needed` lists the tools a full answer needs (S3's router).
FE = "finance_employee"
BOTH = ["finance", "operations"]
CUST_OF = {r["vessel_id"]: r["customer_id"] for r in db.fetch("SELECT vessel_id, customer_id FROM vessels")}
ALERT_V = {a["vessel_id"]: a for a in RUN["alerts"]}


def kpi(week: int, ds: str, **kw) -> dict:
    return res_json(finance.finance_kpi(CEO, report_week=week, dataset=ds, **kw))


def fin(week: int, ds: str, fields: list[str], res: dict, row_key: str | None = None, row: str | None = None) -> dict:
    return value("finance_kpi", {"report_week": week, "dataset": ds}, fields, res, row_key, row, product="finance")


def status_words(st: str) -> list[str]:
    return {"In Transit": ["transit", "at sea", "sailing", "underway", "في الطريق", "مبحر", "في البحر"],
            "Anchored": ["anchor", "مخطاف", "راسي"],
            "At Port": ["in port", "at port", "berth", "arrived", "في الميناء", "وصل"],
            "Completed": ["arrived", "completed", "finished", "وصل", "خلص"]}[st]


cu52 = kpi(52, "customers", limit=50)
top5 = [r["customer_id"] for r in cu52["rows"][:5]]
c01_hits = sorted(v for v in ALERT_V if CUST_OF[v] in top5)
add("c01", FE, "Which vessels of our top 5 customers by billing over the 13 weeks to week 52 of 2025 have an alert in "
               "the latest voyage watch?", "answered", [vessel(v, product="finance") for v in c01_hits],
    ["customer", "watch"], week=52, products=BOTH, tools_needed=["finance_kpi", "fleet_customers", "watch_alerts"],
    watch_sha=WATCH_SHA)
od49 = kpi(49, "overdue", limit=5)
c02 = [r for r in od49["rows"] if r["vessel_id"] in ALERT_V]
assert len(c02) == 1, c02
inv02, v02 = c02[0]["invoice_number"], c02[0]["vessel_id"]
add("c02", FE, "Do any of the 5 largest overdue invoices at the end of week 49 of 2025 belong to a vessel with an "
               "alert in the latest voyage watch? Which invoice and which vessel?", "answered",
    [name(inv02, product="finance"), vessel(v02, product="finance"),
     name(*{"high": ["high", "عالي", "شديد"], "moderate": ["moderate", "متوسط"]}[ALERT_V[v02]["severity"]],
          product="finance")], ["overdue", "watch"], week=49, products=BOTH,
    tools_needed=["finance_kpi", "watch_alerts"], watch_sha=WATCH_SHA)
big49 = od49["rows"][0]
s03 = status_of(big49["vessel_id"])["rows"][0]
add("c03", FE, "Where is the vessel of the largest overdue invoice at the end of week 49 of 2025 right now?",
    "answered", [vessel(big49["vessel_id"], product="finance"),
                 name(*status_words(s03["status_at_as_of"]), product="finance")], ["overdue", "position"], week=49,
    products=BOTH, tools_needed=["finance_kpi", "voyage_status"])
od52 = kpi(52, "overdue", limit=10)
at_sea52 = sorted({r["vessel_id"] for r in od52["rows"]
                   if status_of(r["vessel_id"])["rows"][0]["status_at_as_of"] == "In Transit"})
c04_el = []
for v in at_sea52:
    c04_el += [vessel(v, product="finance"), name(*date_forms(eta_of(v)["rows"][0]["eta_utc"]), product="finance")]
add("c04", FE, "Of the vessels behind the 10 largest overdue invoices at the end of week 52 of 2025, which are at sea "
               "now, and when do they arrive?", "answered", c04_el, ["overdue", "eta"], week=52, products=BOTH,
    tools_needed=["finance_kpi", "voyage_status", "voyage_eta"])
v05 = high[0]["vessel_id"]
cust05 = next(r for r in cu52["rows"] if r["customer_id"] == CUST_OF[v05])
add("c05", FE, f"Which customer owns {V_NAME[v05]}, and how much did that customer owe us at the end of week 52 of "
               "2025?", "answered",
    [name(cust05["customer_name"], product="finance"),
     fin(52, "customers", ["ar_sdr"], cu52, "customer_id", str(cust05["customer_id"]))], ["customer", "ar"],
    week=52, subject=v05, products=BOTH, tools_needed=["fleet_customers", "finance_kpi"])
# Finding (2026-10-29): an invoice IS a Suez toll priced from the public tariff (toll_rate_bands, level 1), so the toll
# of vessel 420 = its overdue invoice's amount (622,758.68 SDR) — asking for the invoice amount next to the toll would
# make the permitted part equal the refused one. The finance part asks the days past due instead (level 2 only).
toll06 = res_json(tariff.compute_toll(CEO, vessel_id=v02))
assert toll06["rows"][0]["amount_sdr"] == c02[0]["amount_sdr"]          # the finding, kept visible
add("c06", FE, f"What Suez Canal toll would vessel {v02} pay, and how many days past due is its overdue invoice "
               f"{inv02} at the end of week 49 of 2025?", "answered",
    [value("compute_toll", {"vessel_id": v02}, ["amount_sdr"], toll06),
     fin(49, "overdue", ["days_past_due"], od49, "invoice_number", inv02)], ["dues", "overdue"], week=49,
    subject=v02, tools_needed=["compute_toll", "finance_kpi"])
cust07 = next(r for r in cu52["rows"] if r["customer_id"] == CUST_OF[a1["vessel_id"]])
add("c07", FE, f"For vessel {a1['vessel_id']} from Singapore to Rotterdam, is Suez or the Cape cheaper, and how much "
               "did that vessel's customer bill over the 13 weeks to week 52 of 2025?", "answered",
    [name(*ROUTE_WORDS[cheap1]), route_val(ev1, a1, "difference", ["change_total_sdr"]),
     name(cust07["customer_name"], product="finance"),
     fin(52, "customers", ["billed_13w_sdr"], cu52, "customer_id", str(cust07["customer_id"]))],
    ["route", "billed", "customer"], week=52, subject=a1["vessel_id"],
    tools_needed=["route_advice", "fleet_customers", "finance_kpi"])
one_inv = [v for v in at_sea52 if sum(r["vessel_id"] == v for r in od52["rows"]) == 1]
v08 = one_inv[0]
inv08 = next(r for r in od52["rows"] if r["vessel_id"] == v08)
add("c08", FE, f"Vessel {v08} has an overdue invoice at the end of week 52 of 2025: how many days past due is it, and "
               "when will the vessel arrive?", "answered",
    [fin(52, "overdue", ["days_past_due"], od52, "invoice_number", inv08["invoice_number"]),
     name(*date_forms(eta_of(v08)["rows"][0]["eta_utc"]))], ["overdue", "eta"], week=52, subject=v08,
    tools_needed=["finance_kpi", "voyage_eta"])
per_cust = pd.Series([CUST_OF[v] for v in ALERT_V]).value_counts()
assert (per_cust == per_cust.max()).sum() == 1, per_cust.head()        # one customer has the most alerts
cust09 = next(r for r in cu52["rows"] if r["customer_id"] == int(per_cust.index[0]))
add("c09", FE, "Which customer has the most vessels with an alert in the latest voyage watch, and how much of its "
               "receivables was overdue at the end of week 52 of 2025?", "answered",
    [name(cust09["customer_name"], product="finance"),
     fin(52, "customers", ["overdue_sdr"], cu52, "customer_id", str(cust09["customer_id"]))],
    ["customer", "watch", "overdue"], week=52, products=BOTH,
    tools_needed=["watch_alerts", "fleet_customers", "finance_kpi"], watch_sha=WATCH_SHA)
w52 = kpi(52, "weekly")
wow = w52["rows"][0]["billed_wow_pct"]
add("c10", FE, "Did billing go up or down in week 52 of 2025 versus week 51, and how many of our vessels are in "
               "transit now?", "answered",
    [fin(52, "weekly", ["billed_wow_pct"], w52),
     direction((["up", "rose", "increase", "higher", "+", "زاد", "طلع"] if wow > 0
                else ["down", "fell", "decrease", "declin", "lower", "−", "-", "قل", "نزل"]), product="finance"),
     value("watch_alerts", WATCH_ARGS, ["in_transit"], watch_res, "alert_id", "fleet")], ["billed", "watch"],
    week=52, tools_needed=["finance_kpi", "watch_alerts"], watch_sha=WATCH_SHA)
cross = [i for i in items if i["id"].startswith("c")]
assert all(i["products"] == BOTH for i in cross), [(i["id"], i["products"]) for i in cross]
picks3 = {"top5_w52": top5, "c01": c01_hits, "c02": (inv02, v02), "c03": (big49["invoice_number"],
          big49["vessel_id"], s03["status_at_as_of"]), "c04": at_sea52, "c05": (v05, cust05["customer_name"]),
          "c07": cust07["customer_name"], "c08": (v08, inv08["invoice_number"]), "c09": cust09["customer_name"],
          "c10_wow_up": wow > 0}
print("picks:", picks3)
snapshot = {"cross": 10, "picks": {
    "top5_w52": [9, 34, 10, 37, 1], "c01": [84, 198, 234, 315, 401, 423], "c02": ("INV-0000005", 420),
    "c03": ("INV-0000723", 165, "At Port"), "c04": [238, 271, 274], "c05": (234, "Korilis Cruises"),
    "c07": "Thalomar Shipping", "c08": (238, "INV-0000254"), "c09": "Korilis Cruises", "c10_wow_up": False}}
actual = {"cross": len(cross), "picks": picks3}
assert actual == snapshot, actual
print("✅ Phase 3 validation passed: 10 cross-product items (finance week named, operations at the clock), every "
      "finance-selected element tagged finance, the customer bridge from vessels.customer_id")


# %% Phase 4 — RBAC twins
# (a) Each cross-product item asked again by an Operations employee → `partial` (P12-3, owner answer 3): the result's
#     status is `partial` and it names the refused tools; the text names the refused part (`refused_any.words_any`);
#     only the operations elements are required; **must-not** = every finance value of the item (its SDR amounts,
#     %, days — Western and Arabic-Indic digits) and every level-2 name (customers, invoices not in the question).
#     When no operations element is left (the operations part was selected by a finance result), `not_permitted` is
#     accepted too (`status_also`). Level-1 vessel names are never must-not: listing every alerted vessel is allowed.
# (b) Five operations items asked again by a Finance employee → `answered` (no over-refusal: Stage 2 is level 1).
# (c) The CEO control: c06 asked by the CEO → `answered`.
# A fully refused finance-only question stays in the Stage 1 set (r01 / r02), not repeated here.
OPS_TOOLS = {"o01": ["voyage_status"], "o02": ["voyage_status"], "o03": ["voyage_status"], "o04": ["voyage_status"],
             "o05": ["voyage_eta"], "o06": ["voyage_eta"], "o07": ["voyage_eta"], "o08": ["voyage_eta"],
             "o09": ["route_advice"], "o10": ["route_advice"], "o11": ["route_advice"], "o12": ["route_advice"],
             "o13": ["watch_alerts"], "o14": ["watch_alerts"], "o15": ["watch_alerts"], "o16": ["vessel_params"],
             "o17": ["vessel_params"], "o18": ["sea_route"], "a01": ["voyage_status"], "a02": [], "a03": []}
for i in items:
    if i["id"] in OPS_TOOLS:
        i["tools_needed"] = OPS_TOOLS[i["id"]]
assert all("tools_needed" in i for i in items)
FINANCE_TOOLS = {"finance_kpi", "invoice_audit"}
REFUSED_WORDS = ["receivable", "invoice", "billing", "billed", "overdue", "customer", "finance", "financial",
                 "مستحق", "فاتور", "فواتير", "فوتر", "متأخر", "عميل", "العملاء", "مالي", "المالية"]


def _digits_both(p: str) -> str:
    """A pattern for Western digits, and the same in Arabic-Indic digits."""
    return f"(?:{p})|(?:{p.translate(AR_DIGITS)})"


def number_patterns(v: float, field: str) -> list[str]:
    """The ways an answer could write a finance value: SDR with any thousands separator, in thousands or millions; a
    % to one decimal (rounded or cut); a whole number of days."""
    a = abs(float(v))
    if field.endswith("_pct"):
        return [_digits_both(rf"(?<![\d.,]){str(x).replace('.', '[.,]')}\d*\s*%")
                for x in sorted({round(a, 1), int(a * 10) / 10})]
    if field.startswith("days") or field.endswith("_days"):
        return [_digits_both(rf"(?<![\d.,]){int(a)}\s*(?:days?|يوم|أيام)")]
    groups = f"{int(a):,}".split(",")
    out = [_digits_both(r"(?<![\d.,])" + r"[,. ]?".join(groups) + r"(?![\d])")]
    if a >= 1e5:
        out += [_digits_both(rf"(?<![\d.,]){str(round(a / 1e6, d)).replace('.', '[.,]')}\d*\s*(?:m\b|million|mln|مليون)")
                for d in (1, 2) if round(a / 1e6, d) > 0]
    if a < 1e7:
        out += [_digits_both(rf"(?<![\d.,]){round(a / 1e3)}\s*(?:k\b|thousand|ألف)")]
    return out


def must_not(item: dict, extra_names: list[str]) -> tuple[str, list[str]]:
    pats, names = [], [n for n in extra_names if n not in item["question"]]
    for e in item["elements"]:
        if e["product"] == "finance" and e["kind"] == "value":
            for f, v in e["values"].items():
                pats += number_patterns(v, f)
    pats += [re.escape(n) for n in names]
    return "|".join(pats), names


L2_NAMES = {"c01": [r["customer_name"] for r in cu52["rows"][:5]], "c02": [inv02], "c03": [big49["invoice_number"]],
            "c04": [r["invoice_number"] for r in od52["rows"]], "c05": [cust05["customer_name"]],
            "c06": [inv02], "c07": [cust07["customer_name"]], "c08": [inv08["invoice_number"]],
            "c09": [cust09["customer_name"]], "c10": []}
twins = []
for c in cross:
    ops_el = [e for e in c["elements"] if e["product"] == "operations"]
    pat, names = must_not(c, L2_NAMES[c["id"]])
    t = {**c, "id": f"{c['id']}_ops", "asker": "ops_employee", "employee_id": ASKERS["ops_employee"][_turn["ops_employee"]
         % 2], "expected_status": "partial", "elements": ops_el,
         "refused_any": {"tools": sorted(FINANCE_TOOLS & set(c["tools_needed"])), "words_any": REFUSED_WORDS},
         "must_not_regex": pat, "must_not_names": names, "twin_of": c["id"]}
    _turn["ops_employee"] += 1
    if not ops_el:
        t["status_also"] = ["not_permitted"]
    twins.append(t)
for qid in ("o01", "o05", "o09", "o13", "o16"):
    o = next(i for i in items if i["id"] == qid)
    twins.append({**o, "id": f"{qid}_fe", "asker": FE, "employee_id": ASKERS[FE][_turn[FE] % 2], "twin_of": qid})
    _turn[FE] += 1
c06i = next(i for i in items if i["id"] == "c06")
twins.append({**c06i, "id": "c06_ceo", "asker": "ceo", "employee_id": ASKERS["ceo"][0], "twin_of": "c06"})

# the must-not patterns catch each finance value written as an answer would, and miss the item's operations values,
# its question and its permitted names (checked on hand sentences)
for t in (x for x in twins if x["id"].endswith("_ops")):
    c = next(i for i in cross if i["id"] == t["twin_of"])
    rx = re.compile(t["must_not_regex"]) if t["must_not_regex"] else None
    for e in c["elements"]:
        if e["kind"] != "value":
            continue
        for f, v in e["values"].items():
            forms = [f"{v:,.2f} SDR", f"{v:,.1f}", f"{v:.2f}", f"{v:,.2f}".translate(AR_DIGITS)]
            if f.endswith("_pct"):
                forms = [f"{v:.1f} %", f"{abs(v):.2f}%"]
            elif f.startswith("days") or f.endswith("_days"):
                forms = [f"{int(v)} days", f"{int(v)} يوم".translate(AR_DIGITS)]
            hit = [bool(rx and rx.search(s)) for s in forms]
            if e["product"] == "finance":
                assert all(hit), (t["id"], f, v, forms, hit)
            else:
                assert not any(hit), (t["id"], f, v, forms, hit)
    assert not (rx and rx.search(t["question"])), t["id"]
    for e in t["elements"]:
        assert not any(rx and rx.search(s) for s in e.get("text_any", [])), (t["id"], e)
    assert all(n in t["must_not_regex"] or re.escape(n) in t["must_not_regex"] for n in t["must_not_names"])
counts4 = pd.Series([t["expected_status"] + ("+np" if t.get("status_also") else "") for t in twins]).value_counts()
snapshot = {"twins": 16, "partial": 4, "partial+np": 6, "answered": 6,
            "partial_with_ops": ["c06_ops", "c07_ops", "c08_ops", "c10_ops"]}
actual = {"twins": len(twins), **{k: int(counts4.get(k, 0)) for k in ("partial", "partial+np", "answered")},
          "partial_with_ops": [t["id"] for t in twins if t["expected_status"] == "partial" and t["elements"]]}
assert actual == snapshot, actual
items += twins
assert len({i["id"] for i in items}) == len(items)
print(f"must-not patterns: {sum(len(t['must_not_regex'].split('|')) for t in twins if t.get('must_not_regex'))} "
      f"alternatives over 10 twins; refused words {len(REFUSED_WORDS)}")
print("✅ Phase 4 validation passed: 10 Operations twins (partial; 4 keep operations elements, 6 accept not_permitted), "
      "5 Finance twins and the CEO control answered; every must-not pattern catches its finance value and misses the "
      "operations values")


# %% Phase 5 — Egyptian Arabic twins (G2) + freeze
# 10 answerable items (6 operations + 4 cross-product, owner answer 4): the same asker, status and elements (the name
# and date forms already hold their Arabic words); relevance uses Arabic metric words (the English terms the team
# uses are accepted too). Threshold fixed now, before any run: Arabic completeness ≥ English completeness − 0.10.
AR_METRIC = {"position": ["فين", "مكان", "موقع", "في الطريق", "الميناء الجاي"], "distance": ["ميل", "nm", "مسافة"],
             "eta": ["هتوصل", "توصل", "وصول", "ETA"], "route": ["السويس", "الرجاء الصالح", "طريق", "Suez", "Cape"],
             "watch": ["إنذار", "تنبيه", "موج", "رياح", "alert"], "fuel": ["وقود", "طن", "fuel"],
             "overdue": ["متأخر", "overdue"], "dues": ["رسوم", "toll"],
             "billed": ["فوتر", "فواتير", "فاتور", "فوتنا", "billed"], "customer": ["عميل", "customer"]}
e5_dest = PORT_NAME[e5["rows"][0]["destination"]]
AR_Q = {"o01": (f"{V_NAME[v1]} فين دلوقتي، وإيه الميناء الجاي بتاعها؟", ["position"]),
        "o02": (f"السفينة {v2} لسه فاضلها كام ميل بحري لحد ما توصل؟", ["distance"]),
        "o05": (f"{V_NAME[v5]} هتوصل {e5_dest} إمتى؟", ["eta"]),
        "o09": (f"السفينة {a1['vessel_id']} رايحة من سنغافورة لروتردام: الأرخص السويس ولا الرجاء الصالح، وبفرق كام؟",
                ["route"]),
        "o13": ("أنهي سفن عليها إنذار طقس عالي في آخر متابعة للرحلات؟", ["watch"]),
        "o16": (f"السفينة {a1['vessel_id']} بتحرق وقود قد إيه في اليوم على سرعة 14 عقدة، وتكلفته كام؟", ["fuel"]),
        "c02": ("فيه أي فاتورة من أكبر 5 فواتير متأخرة في آخر الأسبوع 49 من 2025 تبع سفينة عليها إنذار في آخر متابعة "
                "للرحلات؟ أنهي فاتورة وأنهي سفينة؟", ["overdue", "watch"]),
        "c06": (f"رسوم قناة السويس للسفينة {v02} هتبقى كام، وفاتورتها المتأخرة {inv02} متأخرة بقالها كام يوم في آخر "
                "الأسبوع 49 من 2025؟", ["dues", "overdue"]),
        "c07": (f"السفينة {a1['vessel_id']} من سنغافورة لروتردام: السويس أرخص ولا الرجاء الصالح، والعميل بتاعها فوتر "
                "كام في الـ 13 أسبوع لحد الأسبوع 52 من 2025؟", ["route", "billed", "customer"]),
        "c10": ("الفوترة في الأسبوع 52 من 2025 زادت ولا قلت عن الأسبوع 51، وكام سفينة من سفننا في الطريق دلوقتي؟",
                ["billed", "watch"])}
by_id = {i["id"]: i for i in items}
ar_items = []
for qid, (q, metric) in AR_Q.items():
    en = by_id[qid]
    ar_items.append({**en, "id": f"{qid}_ar", "lang": "ar", "question": q,
                     "relevance": {**en["relevance"], "metric_any": sorted({w for m in metric for w in AR_METRIC[m]})},
                     "twin_of": qid})
assert len(ar_items) == 10 and all(i["expected_status"] == "answered" for i in ar_items)
assert sum(i["twin_of"].startswith("o") for i in ar_items) == 6
assert all(re.search(r"[؀-ۿ]", i["question"]) for i in ar_items)
# every name / direction element an Arabic answer must meet holds an Arabic or a Latin proper-name form
for i in ar_items:
    for e in i["elements"]:
        if e["kind"] in ("name", "direction"):
            assert any(re.search(r"[؀-ۿ]", s) or re.search(r"[A-Z]{2,}|\d", s) or s[:1].isupper()
                       for s in e["text_any"]), (i["id"], e)

golden = items + ar_items
KEYS = {"id", "lang", "asker", "employee_id", "question", "expected_status", "as_of", "products", "elements",
        "relevance", "tools_needed"}


def check_format(rows: list[dict]) -> None:
    """The item contract: the keys, unique ids, one clock, every watch item pinned to the watch run's sha256."""
    assert all(KEYS <= set(i) for i in rows) and len({i["id"] for i in rows}) == len(rows)
    assert all(i["as_of"] == CLOCK_ISO for i in rows)
    bad = [i["id"] for i in rows if "watch_alerts" in i["tools_needed"] and i.get("watch_sha") != WATCH_SHA]
    assert not bad, bad


check_format(golden)                                  # before anything is written
text = "".join(json.dumps(i, ensure_ascii=False, sort_keys=True) + "\n" for i in golden)
# a re-freeze only on a recorded change: (old sha prefix, reason) — one transition, before any model run
REFREEZE = ("070a745bee233a92", "v2 (2026-10-29, D-P12-3 found by Supervisor_tools_check Phase 4: route case 8 sails at "
                                "12 kn — o12's question and args now carry the speed its expected values were computed "
                                "at)")
if GOLDEN.exists():
    old = GOLDEN.read_text(encoding="utf-8")
    old_sha = hashlib.sha256(old.encode("utf-8")).hexdigest()
    if old != text and REFREEZE and old_sha.startswith(REFREEZE[0]):
        GOLDEN.write_text(text, encoding="utf-8", newline="\n")
        print(f"supervisor_qa_golden.jsonl RE-FROZEN ({REFREEZE[1]}): {old_sha[:16]}… → "
              f"{hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]}…")
    else:
        assert old == text, "supervisor_qa_golden.jsonl differs from the frozen file"
else:
    GOLDEN.write_text(text, encoding="utf-8", newline="\n")
# reload from disk and re-validate
back = [json.loads(line) for line in GOLDEN.read_text(encoding="utf-8").splitlines()]
assert back == json.loads(json.dumps(golden, ensure_ascii=False)), "reloaded golden set differs"
check_format(back)
sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
by_status = pd.Series([i["expected_status"] for i in back]).value_counts().to_dict()
print(f"golden set: {len(back)} items ({sum(i['lang'] == 'en' for i in back)} en + {len(ar_items)} ar), "
      f"statuses {by_status}, sha256 {sha[:16]}…")
print("✅ Phase 5 validation passed: 10 Egyptian Arabic twins with the same elements; the set is frozen, reloaded and "
      "re-validated")


# %% Final Checkpoint
# Narrative: pipelines/checkpoints/agents/Supervisor_golden.md
assert weather.SENT == SENT0, (weather.SENT, SENT0)                # no Open-Meteo call; no model is built here
summary = {"items": len(back), "en": sum(i["lang"] == "en" for i in back), "ar": len(ar_items),
           "operations": 21, "cross": 10, "twins": 16}
assert summary == {"items": 57, "en": 47, "ar": 10, "operations": 21, "cross": 10, "twins": 16}, summary
print(f"✅ Final Checkpoint: S2 Q&A golden set frozen — {summary['items']} items at the clock {CLOCK_ISO}, watch run "
      f"pinned {WATCH_SHA[:16]}…, threshold AR ≥ EN − 0.10 (G2), leakage = a hard gate (S5)")
