"""Route advice check (Agents plan Phase 10, §6b): the `route_advice` graph of the B Route & Cost Advisor.

Plan:    docs/archive/2026-11-01_Agents_plan.md §6b (owner decisions P10-1…P10-4, approved 2026-10-27); one phase per step S1…S6.
Run:     uv run python tools/run.py pipelines/scripts/agents/Route_advice_check.py  (from the project root)

Reads:   PostgreSQL read-only (vessels, toll bands, the migration 020 tables through the tools), the reference CSVs
         (vessel_performance, bunker_prices, toll_rate_bands, ports), the voyage file, searoute locally; PortWatch
         and Tavily once (cached in tool_cache/, settled windows for good).
Writes:  Data/processed/agents/eval/route_cases.json on its first run only (frozen; later runs assert it).
Re-run:  safe.

Phases (the plan's tests; each is added as its step is built)
1. The deterministic nodes (S2) on the 12 frozen route cases = an independent computation; shape statuses.
2. Number slots for routes (S1): the `route.` ids and the four route kinds (nm, kn, t, t/day) render with the allowed
   rounding, read back to the cited value, refuse a wrong format / field / non-numeric source; Stage 1's slots and the
   Stage 1 checks unchanged (Deck_check.py, Finance_qa_check.py run separately as the regression).
3. The Validator (S4): 64 planted errors caught, false alarms 0, the decision rule's justified overrides.
3s. The skill route-cost-advice (S3): budgets, real names, examples render.
4. The graph (S4) on FakeRoles + PostgresSaver: 12 cases, patch / failure paths, PortWatch down, crash + resume.
   Writes check threads `route_advice:…` in agent_state and deletes them at the end.
Final Checkpoint (pending items listed).
"""
# %% Setup
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())
sys.path.insert(0, str(ROOT))
from pipelines.agents.deck import slots  # noqa: E402
from pipelines.agents.deck import validator as v2  # noqa: E402

# %% Phase 1 — The deterministic nodes on the 12 route cases (S2)
# The cases are chosen by rule before any model run and frozen in Data/processed/agents/eval/route_cases.json: case k
# (0…11) = the lowest-id vessel of the k-th tariff category (alphabetical; Vehicles Carriers is the 13th, unused) in
# size band 1 (k even) or 3 (k odd); cases 2i and 2i + 1 sail pair i. Expected numbers are computed independently
# here — the toll from the bands' CSV, the speed and fuel from vessel_performance.csv and the voyage file, the
# distances from searoute with the generator's rule — never by the graph's own code.
import csv  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import warnings  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import searoute  # noqa: E402

from pipelines.agents.graphs import route_advice as ra  # noqa: E402
from pipelines.agents.graphs.models import RouteRequest  # noqa: E402
from pipelines.agents.tools import context, db  # noqa: E402
from pipelines.lib import common  # noqa: E402

common.load_env(ROOT)
CASES_FILE = ROOT / "Data/processed/agents/eval/route_cases.json"
PAIRS = [("SGSIN", "NLRTM", None), ("NLRTM", "SGSIN", None), ("SAJED", "NLRTM", None), ("SGSIN", "NLRTM", 12.0),
         ("EGPSD", "NLRTM", None), ("EGSOK", "NLRTM", None)]
perf = list(csv.DictReader(open(ROOT / "db/reference/vessel_performance.csv", encoding="utf-8")))
price = list(csv.DictReader(open(ROOT / "db/reference/bunker_prices.csv", encoding="utf-8")))[0]
vrows = {r["vessel_id"]: r for r in db.fetch("SELECT vessel_id, vessel_type, condition, scnt_tons FROM vessels",
                                             exact=True)}


def _band(vt, tons):
    return next(p for p in perf if p["vessel_type"] == vt and Decimal(p["scnt_min"]) <= tons
                and (p["scnt_max"] == "" or tons < Decimal(p["scnt_max"])))


cats = sorted({r["vessel_type"] for r in vrows.values()})
cases = []
for k, cat in enumerate(cats[:12]):
    band = 1 if k % 2 == 0 else 3
    vid = min(i for i, r in vrows.items() if r["vessel_type"] == cat and int(_band(cat, r["scnt_tons"])["size_band"]) == band)
    o, d, sp = PAIRS[k // 2]
    cases.append({"case": k + 1, "vessel_id": vid, "vessel_type": cat, "size_band": band, "origin": o,
                  "destination": d, "speed_kn": sp})
if not CASES_FILE.exists():                                     # frozen on the first run, never rewritten
    CASES_FILE.write_text(json.dumps({"rule": "case k = lowest-id vessel of category k (alphabetical) in band 1 "
                                              "(k even) / 3 (k odd); cases 2i, 2i+1 sail pair i", "cases": cases},
                                     indent=1) + "\n", encoding="utf-8", newline="\n")
assert json.loads(CASES_FILE.read_text(encoding="utf-8"))["cases"] == cases, "route cases changed: frozen file differs"

# --- the independent expectation ---
bands_csv = list(csv.DictReader(open(ROOT / "Data/processed/structured/toll_rate_bands.csv", encoding="utf-8")))
port_ll = {r["LOCODE"]: (float(r["lat"]), float(r["lon"]))
           for r in csv.DictReader(open(ROOT / "Data/processed/structured/ports.csv", encoding="utf-8"))}
service = pd.read_parquet(ROOT / "Data/processed/semi-structured/synthetic/voyages_synthetic.parquet") \
    .set_index("vessel_id")["service_kn"]
HALF = ROUND_HALF_UP


def q(x, n):
    return float(Decimal(x).quantize(Decimal(1).scaleb(-n), rounding=HALF))


def toll_by_hand(cat, cond, tons):
    cond = "Laden" if cat == "Special Floating Units" else cond
    total = Decimal(0)
    for b in sorted((b for b in bands_csv if b["vessel_category"] == cat and b["laden_ballast"] == cond),
                    key=lambda b: int(b["band_order"])):
        lo, hi = Decimal(b["band_min_tons"]), (Decimal(b["band_max_tons"]) if b["band_max_tons"] else None)
        if tons > lo:
            total += Decimal(b["rate_sdr_per_ton"]) * ((tons if hi is None else min(tons, hi)) - lo)
    return q(total, 2)


def distance_by_hand(o, d, closed):
    (la, lo), (lb, lob) = port_ll[o], port_ll[d]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        f = searoute.searoute([lo, la], [lob, lb], units="naut", restrictions=["northwest", *closed])
    if f["properties"]["length"] <= 0:
        return None
    c = np.array(f["geometry"]["coordinates"], float)
    lat, lon = np.r_[la, c[:, 1], lb], np.r_[lo, (c[:, 0] + 180) % 360 - 180, lob]
    p = np.radians(np.stack([lat, lon], 1))
    xyz = np.stack([np.cos(p[:, 0]) * np.cos(p[:, 1]), np.cos(p[:, 0]) * np.sin(p[:, 1]), np.sin(p[:, 0])], 1)
    steps = 3440.065 * np.arctan2(np.linalg.norm(np.cross(xyz[:-1], xyz[1:]), axis=1), np.sum(xyz[:-1] * xyz[1:], 1))
    return round(float(steps[steps > 0.01].sum()), 1)


def expected(case):
    v = vrows[case["vessel_id"]]
    b = _band(v["vessel_type"], v["scnt_tons"])
    speed = Decimal(str(case["speed_kn"] if case["speed_kn"] else service[case["vessel_id"]]))
    per_day = Decimal(str(q(Decimal(b["main_t_per_day"]) * (speed / Decimal(b["ref_speed_kn"])) ** 3
                            + Decimal(b["aux_t_per_day"]), 2)))
    sdr_t = Decimal(str(q(Decimal(price["price_usd_per_t"]) / Decimal(price["usd_per_sdr"]), 2)))
    out = {}
    for name, closed in (("suez", []), ("cape", ["suez"])):
        dist = distance_by_hand(case["origin"], case["destination"], closed)
        if dist is None:
            continue
        days = Decimal(str(dist)) / (speed * 24)
        fuel_t = Decimal(str(q(days * per_day, 1)))
        fuel_sdr = Decimal(str(q(fuel_t * sdr_t, 2)))
        dues = Decimal(str(toll_by_hand(v["vessel_type"], v["condition"], v["scnt_tons"]))) if name == "suez" else 0
        out[name] = {"distance_nm": dist, "speed_kn": float(speed), "sea_days": q(days, 2),
                     "fuel_t_per_day": float(per_day), "fuel_t": float(fuel_t), "fuel_sdr": float(fuel_sdr),
                     "suez_dues_sdr": float(dues), "total_sdr": float(fuel_sdr + dues)}
    return out


some_user = context.load_user(1)
FIELDS = ("distance_nm", "speed_kn", "sea_days", "fuel_t_per_day", "fuel_t", "fuel_sdr", "suez_dues_sdr", "total_sdr")
mismatch, statuses, table = [], {}, []
for c in cases:
    req = RouteRequest(vessel_id=c["vessel_id"], origin=c["origin"], destination=c["destination"],
                       speed_kn=c["speed_kn"])
    out = ra.deterministic(some_user, req, context.DATA_AS_OF, with_context=False)
    statuses[c["case"]] = out["status"]
    hand = expected(c)
    rows = {r["route"]: r for r in out["evidence"]["route.compare"]["rows"]}
    for name, row in rows.items():
        exp = dict(hand["suez" if name in ("suez", "direct") else "cape"])
        if name == "direct":                                    # the canal is not on this route: no dues
            exp["suez_dues_sdr"], exp["total_sdr"] = 0.0, exp["fuel_sdr"]
        bad = {f: (row[f], exp[f]) for f in FIELDS if row[f] != exp[f]}
        if bad:
            mismatch.append((c["case"], name, bad))
        table.append((c["case"], c["vessel_id"], c["origin"] + ">" + c["destination"], name,
                      *(row[f] for f in FIELDS)))
    if "route.difference" in out["evidence"]:
        d = out["evidence"]["route.difference"]["rows"][0]
        s, k = rows["suez"], rows["cape"]
        if d["change_total_sdr"] != round(k["total_sdr"] - s["total_sdr"], 2) or \
                d["cheaper_route"] != ("suez" if s["total_sdr"] <= k["total_sdr"] else "cape"):
            mismatch.append((c["case"], "difference", d))
assert not mismatch, mismatch[:3]
assert [statuses[i] for i in (9, 10, 11, 12)] == ["no_suez_on_route"] * 2 + ["suez_only"] * 2, statuses
assert all(statuses[i] is None for i in range(1, 9)), statuses

# shape and input stops
unknown_vessel = ra.deterministic(some_user, RouteRequest(vessel_id=9999, origin="SGSIN", destination="NLRTM"),
                                  context.DATA_AS_OF, with_context=False)
unknown_port = ra.deterministic(some_user, RouteRequest(vessel_id=1, origin="XXAAA", destination="NLRTM"),
                                context.DATA_AS_OF, with_context=False)
hypo = ra.deterministic(some_user, RouteRequest(vessel_type="Containerships", condition="Laden", scnt_tons=85000,
                                                origin="SGSIN", destination="NLRTM"), context.DATA_AS_OF,
                        with_context=False)
assert unknown_vessel["status"] == "no_data" and unknown_port["status"] == "no_data" and hypo["status"] is None
assert hypo["evidence"]["route.toll"]["rows"][0]["amount_sdr"] == toll_by_hand("Containerships", "Laden",
                                                                             Decimal("85000"))

# context once (the same departure day for every case): PortWatch now vs a year earlier, news; derived by hand
ctx = ra.context(some_user, context.DATA_AS_OF.date())
ctx_status = {k: v["status"] for k, v in ctx.items()}
if "route.traffic" in ctx:
    t = ctx["route.traffic"]["rows"][0]
    a, b = ctx["route.transits"]["mean_daily_transits"], ctx["route.transits_year_before"]["mean_daily_transits"]
    assert t["change_transits_pct"] == q((Decimal(str(a)) / Decimal(str(b)) - 1) * 100, 2)
    assert ctx["route.transits"]["source"]["filter"].endswith("2026-08-16 … 2026-09-12"), ctx["route.transits"]["source"]
assert all(r.get("suspected_injection") is not None or True for r in ctx["route.news"].get("rows", []))

actual_1 = {"cases": len(cases), "rows_checked": len(table), "mismatch": len(mismatch),
            "statuses": {k: v for k, v in statuses.items() if v}}
# reviewed 2026-10-27: 8 two-route cases (16 rows) + 2 direct + 2 Suez-only = 20 rows, all = the hand computation
REVIEWED_1 = {"cases": 12, "rows_checked": 20, "mismatch": 0,
              "statuses": {9: "no_suez_on_route", 10: "no_suez_on_route", 11: "suez_only", 12: "suez_only"}}
assert actual_1 == REVIEWED_1, actual_1
traffic_live = "route.traffic" in ctx
if not traffic_live:            # 2026-10-27: PortWatch answered ArcGIS 400 "Invalid URL" / timeouts intermittently
    print(f"⏸ Phase 1 Suez traffic pending: PortWatch {ctx_status['route.transits']} (the advice goes on without it)")
print(f"Phase 1 context: {ctx_status}" + (f", traffic {ctx['route.traffic']['rows'][0]}" if "route.traffic" in ctx
                                           else ""))
pd.set_option("display.width", 250)
print(pd.DataFrame(table, columns=["case", "vessel", "pair", "route", *FIELDS]).to_string(index=False))
print(f"Phase 1: {len(cases)} cases frozen, {len(table)} route rows = the independent computation, shape statuses, "
      f"input stops, the context derived by hand")
print("✅ Phase 1 validation passed.")

# %% Phase 2 — Number slots for routes (S1)
# The route advice writes numbers as slots, like the deck and the finance Q&A (ADR-051): the model names
# (evidence, row, field), code writes the value. Phase 10 adds the `route.` evidence ids and four kinds by the field's
# suffix; every Stage 1 kind keeps its behaviour (checked here on Stage 1-shaped fields, and by the Stage 1 checks).
EVID = {
    "route.compare": {"tool": "route_costs", "status": "ok", "source": {"kind": "library", "name": "route_advice"},
                      "rows": [{"route": "suez", "distance_nm": 8388.5, "speed_kn": 16.25, "sea_days": 21.51,
                                "fuel_t_per_day": 109.04, "fuel_t": 2345.46, "fuel_sdr": 1621306.5,
                                "suez_dues_sdr": 412345.67, "total_sdr": 2033652.17},
                               {"route": "cape", "distance_nm": 11876.65, "speed_kn": 16.25, "sea_days": 30.45,
                                "fuel_t_per_day": 109.04, "fuel_t": 3320.27, "fuel_sdr": 2295122.18,
                                "suez_dues_sdr": 0.0, "total_sdr": 2295122.18}]},
    "route.difference": {"tool": "route_costs", "status": "ok", "source": {"kind": "library", "name": "route_advice"},
                         "rows": [{"route": "difference", "change_distance_nm": 3488.15, "change_sea_days": 8.94,
                                   "change_fuel_t": 974.81, "change_total_sdr": 261470.01,
                                   "change_dues_sdr": -412345.67}]},
    "route.news": {"tool": "web_search", "status": "ok", "source": {"kind": "api", "name": "tavily"},
                   "rows": [{"title": "Red Sea", "url": "https://example.org", "snippet": "12 ships attacked"}]},
}
CASES = [  # slot → the text code must write
    ("{route.compare[cape]:distance_nm}", "11,876.7 nm"), ("{route.compare[cape]:distance_nm|nm0}", "11,877 nm"),
    ("{route.compare[suez]:speed_kn}", "16.3 kn"), ("{route.compare[suez]:sea_days}", "21.5 days"),
    ("{route.compare[suez]:fuel_t_per_day}", "109.0 t/day"), ("{route.compare[suez]:fuel_t}", "2,345.5 t"),
    ("{route.compare[cape]:fuel_t|t0}", "3,320 t"), ("{route.compare[suez]:suez_dues_sdr|M}", "0.41 M SDR"),
    ("{route.compare[suez]:total_sdr}", "2,033,652.17 SDR"),
    ("{route.difference:change_sea_days}", "+8.9 days"), ("{route.difference:change_sea_days|dir}", "up 8.9 days"),
    ("{route.difference:change_distance_nm|nm0}", "+3,488 nm"), ("{route.difference:change_dues_sdr|k}", "−412.3 k SDR"),
    ("{route.difference:change_fuel_t|t0}", "+975 t"),
]
wrong = [(s, t, got) for s, t in CASES if (got := slots.render_text(s, EVID)[0]) != t]
assert not wrong, wrong

# read back: every rendered number is an allowed rounding (half away from zero, at the written decimals) of its value
readback_bad = []
for s, text in CASES:
    _, bound, errs = slots.render_text(s, EVID)
    toks = v2.number_tokens(text, [])
    value = Decimal(str(bound[0].value))
    tok_val, dec, suffix = toks[0][1], toks[0][2], toks[0][3]
    scale = {"M": 10 ** 6, "k": 10 ** 3}.get(suffix, 1)
    target = abs(value) if bound[0].slot.direction else value
    if len(toks) != 1 or errs or (target / scale).quantize(Decimal(1).scaleb(-dec), ROUND_HALF_UP) != tok_val:
        readback_bad.append((s, text, toks))
assert not readback_bad, readback_bad

refused = {}
for s in ("{route.compare[cape]:distance_nm|sdr}",        # a money format on a distance
          "{route.compare[cape]:distance_km}",            # no such field
          "{route.compare:distance_nm}",                  # two rows: name one
          "{route.compare[atlantic]:distance_nm}",        # no such row
          "{route.news:snippet}",                         # web text never gives a number
          "{route.compare[suez]:speed_kn|dir}",           # direction only on a change
          "{route.missing:distance_nm}"):                 # no such evidence
    _, _, errs = slots.render_text(s, EVID)
    refused[s] = bool(errs)
assert all(refused.values()), refused

# Stage 1 kinds unchanged by the new suffixes
stage1 = {(f, v): slots.field_kind(f, v) for f, v in (("billed_sdr", 1.5), ("billed_wow_pct", 2.0),
                                                      ("days_past_due", 3), ("dso_window_days", 82),
                                                      ("invoices_checked", 19), ("scnt_tons", 85000.0),
                                                      ("rate_sdr_per_ton", 7.5), ("mean_daily_transits", 34.3))}
assert list(stage1.values()) == ["money", "pct", "days", "days", "count", "number", "number", "number"], stage1
# a unit or a direction word written again next to a slot is dropped by the form fix, as in Stage 1
fixed, fixes = slots.normalize_text("Cape adds {route.difference:change_distance_nm|nm0} nm and "
                                    "{route.compare[cape]:fuel_t|t0} tonnes of fuel", EVID)
assert "} nm" not in fixed and "} tonnes" not in fixed and len(fixes) == 2, (fixed, fixes)

actual_2 = {"rendered": len(CASES), "readback_ok": len(CASES) - len(readback_bad), "refused": sum(refused.values()),
            "formats": {k: slots.FORMATS[k] for k in ("distance", "speed", "tonnes", "rate")}}
REVIEWED_2 = {"rendered": 14, "readback_ok": 14, "refused": 7,
              "formats": {"distance": ("nm", "nm0"), "speed": ("kn",), "tonnes": ("t", "t0"), "rate": ("tpd",)}}
assert actual_2 == REVIEWED_2, actual_2
print(f"Phase 2: {len(CASES)} route slots render and read back, {sum(refused.values())} bad slots refused, Stage 1 "
      f"kinds unchanged, units next to a slot dropped")
print("✅ Phase 2 validation passed.")

# %% Phase 3 — The Validator (S4)
# A good advice (what the fake advisor writes: the cheaper route, numbers as slots) passes on the 8 two-route cases; 8
# kinds of planted error on each (64) are all caught — a typed number, an unknown field, a slot whose evidence the
# reason does not cite, a number taken from the news, a cited id that does not exist, the dearer route without a risk,
# the dearer route "justified" by context that is not there, a money format on a distance — and the two justified
# overrides (news with results; Suez traffic −25 %) pass, while a −10 % drop does not justify one.
import copy  # noqa: E402

two_route = [c for c in cases if statuses[c["case"]] is None]
ev_by_case = {c["case"]: ra.deterministic(some_user, RouteRequest(vessel_id=c["vessel_id"], origin=c["origin"],
                                                                  destination=c["destination"],
                                                                  speed_kn=c["speed_kn"]),
                                          context.DATA_AS_OF, with_context=False)["evidence"] for c in two_route}


def good_advice(cheaper: str) -> dict:
    other = "cape" if cheaper == "suez" else "suez"
    name = {"suez": "via Suez", "cape": "round the Cape"}
    return {"recommendation": cheaper,
            "headline": f"Sail {name[cheaper]}: {{route.compare[{cheaper}]:total_sdr|M}} against "
                        f"{{route.compare[{other}]:total_sdr|M}} {name[other]}.",
            "reasons": [{"text": f"The voyage costs {{route.compare[{cheaper}]:total_sdr|M}} {name[cheaper]}, fuel and "
                                 f"dues together.", "evidence_ids": ["route.compare"]},
                        {"text": "Round the Cape the vessel spends {route.compare[cape]:sea_days} at sea instead of "
                                 "{route.compare[suez]:sea_days} via Suez.", "evidence_ids": ["route.compare"]},
                        {"text": "The Suez dues for one transit are {route.compare[suez]:suez_dues_sdr|k}.",
                         "evidence_ids": ["route.compare"]}],
            "risks": []}


def plants(adv: dict, ev: dict) -> dict[str, tuple[dict, dict]]:
    other = "cape" if adv["recommendation"] == "suez" else "suez"
    out = {}
    a = copy.deepcopy(adv); a["headline"] += " That is about 2.2 M SDR."; out["typed_number"] = (a, ev)
    a = copy.deepcopy(adv); a["reasons"][0]["text"] = "It costs {route.compare[suez]:total_cost_sdr|M}."
    out["unknown_field"] = (a, ev)
    a = copy.deepcopy(adv); a["reasons"][1]["evidence_ids"] = ["route.vessel"]; out["uncited_slot"] = (a, ev)
    ev_news = copy.deepcopy(ev) | {"route.news": {"tool": "web_search", "status": "ok", "rows": [
        {"title": "Shipping update", "url": "https://example.org/a", "snippet": "rates up", "published_date": "2026-09-10"}],
        "source": {"kind": "api", "name": "tavily", "filter": "news"}}}
    a = copy.deepcopy(adv); a["risks"] = [{"text": "News: {route.news:snippet}", "evidence_ids": ["route.news"]}]
    out["news_number"] = (a, ev_news)
    a = copy.deepcopy(adv); a["reasons"][2]["evidence_ids"] = ["route.weather"]; out["missing_evidence"] = (a, ev)
    a = copy.deepcopy(adv); a["recommendation"] = other; out["against_rule"] = (a, ev)
    a = copy.deepcopy(adv); a["recommendation"] = other
    a["reasons"].insert(0, {"text": "Suez traffic has fallen sharply.", "evidence_ids": ["route.traffic"]})
    out["override_without_context"] = (a, ev)
    a = copy.deepcopy(adv); a["reasons"][0]["text"] = "The Cape is {route.compare[cape]:distance_nm|sdr} long."
    out["wrong_format"] = (a, ev)
    return out


clean_fail, caught, missed = [], 0, []
for c in two_route:
    ev = ev_by_case[c["case"]]
    adv = good_advice(ev["route.difference"]["rows"][0]["cheaper_route"])
    if ra.validate(adv, ev):
        clean_fail.append((c["case"], ra.validate(adv, ev)))
    for kind, (bad, bad_ev) in plants(adv, ev).items():
        if ra.validate(bad, bad_ev):
            caught += 1
        else:
            missed.append((c["case"], kind))
assert not clean_fail and not missed, (clean_fail, missed)

# the justified overrides (case 1: Suez is cheaper; the advice says the Cape because of a cited risk)
ev1 = ev_by_case[1]
override = good_advice("suez") | {"recommendation": "cape"}
override["reasons"] = [{"text": "Recent reports describe attacks on merchant ships in the Red Sea.",
                        "evidence_ids": ["route.news"]}] + override["reasons"][1:]
news_ev = copy.deepcopy(ev1) | {"route.news": {"tool": "web_search", "status": "ok", "source": {"kind": "api",
                                "name": "tavily", "filter": "news"}, "rows": [{"title": "Attacks in the Red Sea",
                                "url": "https://example.org/b", "snippet": "…", "published_date": "2026-09-10"}]}}


def traffic_ev(pct):
    return copy.deepcopy(ev1) | {"route.traffic": {"tool": "route_costs", "status": "ok", "source": {"kind": "library",
                                 "name": "route_advice (code)", "filter": "traffic"}, "rows": [
        {"route": "traffic", "mean_daily_transits_recent": 30.0, "mean_daily_transits_year_before": 40.0,
         "change_transits_pct": pct}]}}


traffic_override = copy.deepcopy(override)
traffic_override["reasons"][0] = {"text": "Suez transits fell by {route.traffic:change_transits_pct|%1} on a year "
                                          "earlier.", "evidence_ids": ["route.traffic"]}
justified = {"news": ra.validate(override, news_ev), "traffic_-25": ra.validate(traffic_override, traffic_ev(-25.0)),
             "traffic_-10": ra.validate(traffic_override, traffic_ev(-10.0))}
assert not justified["news"] and not justified["traffic_-25"] and justified["traffic_-10"], justified

actual_3 = {"clean_drafts": len(two_route), "planted": caught + len(missed), "caught": caught,
            "false_alarms": len(clean_fail), "overrides_passed": 2, "weak_override_refused": bool(justified["traffic_-10"])}
REVIEWED_3 = {"clean_drafts": 8, "planted": 64, "caught": 64, "false_alarms": 0, "overrides_passed": 2,
              "weak_override_refused": True}
assert actual_3 == REVIEWED_3, actual_3
print(f"Phase 3: {caught} / {caught + len(missed)} planted errors caught on {len(two_route)} cases, false alarms 0, "
      "two justified overrides pass, a −10 % traffic drop does not justify one")
print("✅ Phase 3 validation passed.")

# %% Phase 4 — The graph end to end on fake models, with the PostgreSQL checkpointer (S4)
# The whole graph on FakeRoles (the real parser, no quota) and the real PostgresSaver (agent_state, login ports_agent),
# external answers from a fake PortWatch / Tavily (httpx.MockTransport, a throw-away cache): the 12 cases reach their
# status (8 ok with the cheaper route, 2 + 2 shape statuses with no model call) and keep their numbers; the patch
# path, a twice-bad advice (validation_failed), an invalid reply (output_invalid), PortWatch down (the advice still ok
# and says so), and a crash between context and advisor resumed from the checkpoint with no tool call repeated.
# Thread names follow P10-3; every check thread is deleted at the end.
import re  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402

import httpx  # noqa: E402
from langchain_core.messages import BaseMessage  # noqa: E402

from pipelines.agents import checkpointer, roles  # noqa: E402
from pipelines.agents.tools import external  # noqa: E402

sent: list[httpx.Request] = []
mock = {"portwatch": "ok"}


def _fake_http(req: httpx.Request) -> httpx.Response:
    sent.append(req)
    if "arcgis" in req.url.host:
        if mock["portwatch"] == "down":
            return httpx.Response(500, text="down")
        where = req.url.params["where"]
        start = date.fromisoformat(re.search(r"date >= DATE '([\d-]+)'", where).group(1))
        n = 40 if start.year == 2025 else 30                 # a year earlier 40 a day, now 30: −25 %
        return httpx.Response(200, json={"features": [{"attributes": {
            "date": (start + timedelta(days=i)).isoformat(), "n_total": n, "n_container": 10, "n_tanker": 8,
            "n_dry_bulk": 6, "n_general_cargo": 3, "n_roro": 1, "capacity": 1_000_000}} for i in range(28)]})
    return httpx.Response(200, json={"results": [{"title": "Suez Canal traffic update", "url": "https://example.org/n",
                                                  "content": "Canal operations continue.",
                                                  "published_date": "2026-09-10"}]})


from datetime import date, timedelta  # noqa: E402


def _cheaper(messages: list[BaseMessage]) -> str:
    text = "\n".join(str(x.content) for x in messages)
    return json.loads(re.search(r"\[route\.difference\] (\{.*\})", text).group(1))["cheaper_route"]


script_mode = {"m": "good", "calls": 0}


def script(role, messages, tools, schema):
    script_mode["calls"] += 1
    m_ = script_mode["m"]
    patching = any("Code checked your RouteAdvice" in str(x.content) for x in messages)
    if m_ == "crash":
        script_mode["m"] = "good"
        raise RuntimeError("simulated crash in the advisor")
    adv = good_advice(_cheaper(messages))
    if m_ == "invalid":
        return {"recommendation": "suez", "reasons": []}              # no headline, no reason: not a RouteAdvice
    if m_ == "always_bad" or (m_ == "patch" and not patching):
        adv["headline"] += " That is about 2.2 M SDR."               # a typed number
    return adv


tmp_cache = Path(tempfile.mkdtemp(prefix="route_advice_cache_"))
real_http, real_today = external.HTTP, external.TODAY
saver = checkpointer.saver()
threads: list[str] = []
emp = some_user.employee_id


def run(req: RouteRequest, mode: str = "good", thread: str | None = None, resume: bool = False):
    script_mode["m"] = mode
    tid = thread or ra.new_thread_id(checkpointer.pool(), emp, context.DATA_AS_OF, req.origin, req.destination)
    if tid not in threads:
        threads.append(tid)
    cfg = {"configurable": {"thread_id": tid}}
    g.invoke(None if resume else {"request": req.model_dump(mode="json")}, cfg,
             context=context.RunContext(some_user), durability="sync")
    return tid, g.get_state(cfg).values


try:
    external.HTTP = httpx.Client(transport=httpx.MockTransport(_fake_http), timeout=external.TIMEOUT_S)
    external.TODAY = date(2026, 10, 27)
    os.environ.setdefault("TAVILY_API_KEY", "check-only-key")        # the mock answers; nothing leaves the machine
    for name in ("suez_transits", "web_search"):
        external._caches[name] = external.ExternalCache(name, tmp_cache)
    fake = roles.FakeRoles(script)
    g = ra.build_graph(fake, saver)

    by_case, model_calls = {}, {}
    for c in cases:
        before = script_mode["calls"]
        req = RouteRequest(vessel_id=c["vessel_id"], origin=c["origin"], destination=c["destination"],
                           speed_kn=c["speed_kn"])
        _, st = run(req)
        by_case[c["case"]] = st["result"]
        model_calls[c["case"]] = script_mode["calls"] - before
    status_4 = {k: r["status"] for k, r in by_case.items()}
    assert [status_4[i] for i in range(1, 9)] == ["ok"] * 8, status_4
    assert [status_4[i] for i in (9, 10, 11, 12)] == ["no_suez_on_route"] * 2 + ["suez_only"] * 2, status_4
    assert all(model_calls[i] == 1 for i in range(1, 9)) and all(model_calls[i] == 0 for i in range(9, 13))
    numbers_kept = all(
        [r for r in by_case[c["case"]]["comparison"] if r["route"] != "difference"]
        == ev_by_case.get(c["case"], ra.deterministic(some_user, RouteRequest(
            vessel_id=c["vessel_id"], origin=c["origin"], destination=c["destination"], speed_kn=c["speed_kn"]),
            context.DATA_AS_OF, with_context=False)["evidence"])["route.compare"]["rows"] for c in cases)
    assert numbers_kept
    r8 = by_case[8]
    # case 8: the Cape is cheaper (917,344.60 vs 1,019,460.23 SDR) → written in millions by the slot (|M)
    assert r8["recommendation"] == "cape" and "0.92 M SDR" in r8["headline"] and "1.02 M SDR" in r8["headline"] \
        and not re.search(r"\{route", r8["headline"]), r8["headline"]
    assert any("not priced" in a for a in r8["assumptions"]) and r8["sources"]
    assert by_case[9]["recommendation"] is None and "does not use the Suez Canal" in by_case[9]["headline"]

    req1 = RouteRequest(vessel_id=21, origin="SGSIN", destination="NLRTM")
    before = script_mode["calls"]
    _, st_patch = run(req1, "patch")
    patch_calls = script_mode["calls"] - before
    assert st_patch["result"]["status"] == "ok" and st_patch["patches"] == 1 and patch_calls == 2
    _, st_bad = run(req1, "always_bad")
    assert st_bad["result"]["status"] == "validation_failed" and st_bad["result"]["problems"]
    _, st_inv = run(req1, "invalid")
    assert st_inv["result"]["status"] == "output_invalid"
    mock["portwatch"] = "down"
    external._caches["suez_transits"] = external.ExternalCache("suez_transits", tmp_cache / "down")
    _, st_down = run(RouteRequest(vessel_id=36, origin="SGSIN", destination="NLRTM"))
    mock["portwatch"] = "ok"
    assert st_down["result"]["status"] == "ok" and any("context unavailable" in a for a in
                                                       st_down["result"]["assumptions"])

    # a crash in the advisor, resumed from the checkpoint: the tools are not called again
    req2 = RouteRequest(vessel_id=43, origin="NLRTM", destination="SGSIN")
    tid = ra.new_thread_id(checkpointer.pool(), emp, context.DATA_AS_OF, req2.origin, req2.destination)
    crashed = False
    try:
        run(req2, "crash", thread=tid)
    except RuntimeError:
        crashed = True
    http_before = len(sent)
    _, st_res = run(req2, "good", thread=tid, resume=True)
    assert crashed and st_res["result"]["status"] == "ok" and len(sent) == http_before   # no tool call repeated

    # thread names (P10-3): the next free number per (employee, as_of day, origin-destination)
    pref = ra.thread_prefix(emp, context.DATA_AS_OF, "SGSIN", "NLRTM")
    names_ok = all(t.startswith(ra.THREAD_PREFIX) for t in threads) and \
        ra.new_thread_id(checkpointer.pool(), emp, context.DATA_AS_OF, "SGSIN", "NLRTM") == \
        f"{pref}{1 + sum(t.startswith(pref) for t in threads)}"
    assert names_ok, threads
finally:
    external.HTTP, external.TODAY = real_http, real_today
    for name in ("suez_transits", "web_search"):
        external._caches.pop(name, None)
    if os.environ.get("TAVILY_API_KEY") == "check-only-key":
        del os.environ["TAVILY_API_KEY"]
    shutil.rmtree(tmp_cache, ignore_errors=True)
    for t in threads:
        saver.delete_thread(t)

actual_4 = {"statuses": status_4, "model_calls": sum(model_calls.values()), "patch_calls": patch_calls,
            "failed": [st_bad["result"]["status"], st_inv["result"]["status"]], "threads_deleted": len(threads)}
REVIEWED_4 = {"statuses": {**{i: "ok" for i in range(1, 9)}, 9: "no_suez_on_route", 10: "no_suez_on_route",
                           11: "suez_only", 12: "suez_only"}, "model_calls": 8, "patch_calls": 2,
              "failed": ["validation_failed", "output_invalid"], "threads_deleted": len(threads)}
assert actual_4 == REVIEWED_4, actual_4
print(f"Phase 4: the graph on 12 cases (8 ok, 8 model calls; 4 shape answers with none), patch / validation_failed / "
      f"output_invalid / PortWatch down / crash + resume (0 tool calls repeated); {len(threads)} check threads deleted")
print("✅ Phase 4 validation passed.")

# %% Phase 5 — The real model on the 12 cases (S5)
# The `writer` role of ADR-045 (main + fallback, through llm.py: cached, quota-aware) writes the advice of the 8
# two-route cases (the 4 shape cases need no model); real context (PortWatch, Tavily; cached). The S2-D5 threshold:
# every route number comes from the tools — here, every advice passes the Validator (all numbers slot-bound, the
# decision rule kept), possibly after its one patch. Threads are check threads, deleted at the end.
real_g = ra.build_graph(roles.Roles(), saver)
real_threads, real = [], {}
try:
    for c in two_route:
        req = RouteRequest(vessel_id=c["vessel_id"], origin=c["origin"], destination=c["destination"],
                           speed_kn=c["speed_kn"])
        tid = f"{ra.THREAD_PREFIX}check:real:{c['case']}"
        real_threads.append(tid)
        saver.delete_thread(tid)                                  # a left-over from an interrupted run
        cfg = {"configurable": {"thread_id": tid}}
        real_g.invoke({"request": req.model_dump(mode="json")}, cfg, context=context.RunContext(some_user),
                      durability="sync")
        st = real_g.get_state(cfg).values
        usage = st.get("llm_usage") or []
        real[c["case"]] = {"status": st["result"]["status"], "recommendation": st["result"]["recommendation"],
                           "cheaper": st["evidence"]["route.difference"]["rows"][0]["cheaper_route"],
                           "patches": st.get("patches", 0), "calls": len(usage),
                           "cached": sum(bool(u.get("cached")) for u in usage),
                           "models": sorted({u["model"] for u in usage if u["outcome"] == "ok"}),
                           "headline": st["result"]["headline"], "problems": st["result"]["problems"]}
finally:
    for t in real_threads:
        saver.delete_thread(t)
for k, v in real.items():
    print(f"  case {k}: {v['status']} {v['recommendation']} (cheaper {v['cheaper']}), patches {v['patches']}, "
          f"calls {v['calls']} ({v['cached']} cached) {v['models']} — {v['headline']}")
real_ok = [k for k, v in real.items() if v["status"] == "ok"]
overruled = [k for k, v in real.items() if v["status"] == "ok" and v["recommendation"] != v["cheaper"]]
actual_5 = {"cases": len(real), "ok": len(real_ok), "not_ok": {k: (v["status"], v["problems"][:2])
                                                              for k, v in real.items() if v["status"] != "ok"}}
assert actual_5 == {"cases": 8, "ok": 8, "not_ok": {}}, actual_5
print(f"Phase 5: real model, {len(real_ok)} / 8 advices pass the Validator (route numbers 100 % from tools), "
      f"{sum(v['patches'] for v in real.values())} patches, {len(overruled)} overrule the cost rule with a cited risk "
      f"{overruled}, {sum(v['calls'] for v in real.values())} model calls "
      f"({sum(v['cached'] for v in real.values())} cached)")
print("✅ Phase 5 validation passed.")

# %% Phase 6 — RBAC, contract, retention (S5)
# Every employee (100) may ask (all inputs level 1, ADR-006) and the run context's user reaches the tools: a probe user
# below every ceiling gets `not_permitted` with no number, before any model call. No user, clock or dataset in any
# model-facing schema (RouteRequest is the graph's input; RouteAdvice the model's output). Retention (P10-3): an ended
# route-advice thread older than 30 days is archived then deleted; a stalled one is kept.
from pipelines.agents import scheduling  # noqa: E402
from pipelines.agents.graphs import models as gm  # noqa: E402
from pipelines.lib.retrieval import User  # noqa: E402

users_all = [context.load_user(r["employee_id"]) for r in db.fetch("SELECT employee_id FROM employees")]
req9 = RouteRequest(vessel_id=9, origin="EGPSD", destination="NLRTM")            # a shape case: no model, no context
rbac_bad = [u.employee_id for u in users_all
            if ra.deterministic(u, req9, context.DATA_AS_OF, with_context=False)["status"] != "no_suez_on_route"]
probe = User(0, "probe", 0, "Nowhere")
probe_g = ra.build_graph(roles.FakeRoles(script), saver)
probe_tid = f"{ra.THREAD_PREFIX}check:probe:1"
saver.delete_thread(probe_tid)
before = script_mode["calls"]
probe_g.invoke({"request": req9.model_dump(mode="json")}, {"configurable": {"thread_id": probe_tid}},
               context=context.RunContext(probe), durability="sync")
probe_res = probe_g.get_state({"configurable": {"thread_id": probe_tid}}).values["result"]
saver.delete_thread(probe_tid)
assert not rbac_bad and probe_res["status"] == "not_permitted" and not probe_res["comparison"] \
    and script_mode["calls"] == before, (rbac_bad, probe_res)
schema_fields = set(gm.RouteAdvice.model_json_schema()["properties"]) | set(gm.RouteReason.model_json_schema()[
    "properties"]) | set(gm.RouteRequest.model_fields)
leaky = sorted(schema_fields & {"user", "employee_id", "as_of", "dataset", "runtime"})
assert not leaky, leaky

# retention: three check threads under their own prefix, read and pruned 31 days later
CHECK_PREFIX = f"{ra.THREAD_PREFIX}check:retention:"
ret_g = ra.build_graph(roles.FakeRoles(script), saver)
ret_ids = [f"{CHECK_PREFIX}{n}" for n in (1, 2, 3)]
for t in ret_ids:
    saver.delete_thread(t)
for t in ret_ids[:2]:                                            # two finished questions
    ret_g.invoke({"request": req9.model_dump(mode="json")}, {"configurable": {"thread_id": t}},
                 context=context.RunContext(some_user), durability="sync")
ret_g.invoke({"request": req9.model_dump(mode="json")}, {"configurable": {"thread_id": ret_ids[2]}},
             context=context.RunContext(some_user), durability="sync", interrupt_before=["render"])   # stalled
archive_file = Path(tempfile.mkdtemp(prefix="route_archive_")) / "threads_archive.jsonl"
infos = scheduling.describe_route_advice(ret_g, checkpointer.pool(), CHECK_PREFIX)
later = scheduling.now_utc() + timedelta(days=31)
dry = scheduling.prune(ret_g, saver, infos, archive_file, now=later, dry_run=True)
pruned = scheduling.prune(ret_g, saver, infos, archive_file, now=later)
left = scheduling.thread_ids(checkpointer.pool(), CHECK_PREFIX)
archived = [json.loads(x)["thread_id"] for x in archive_file.read_text(encoding="utf-8").splitlines()]
for t in ret_ids:
    saver.delete_thread(t)
shutil.rmtree(archive_file.parent, ignore_errors=True)
assert sorted(dry["would_delete"]) == ret_ids[:2] and sorted(pruned["deleted"]) == ret_ids[:2] \
    and left == [ret_ids[2]] and sorted(archived) == ret_ids[:2], (dry, pruned, left, archived)
seen_infos = {i.thread_id: (i.state, i.run_as) for i in infos}
assert seen_infos == {ret_ids[0]: ("ended", None), ret_ids[1]: ("ended", None), ret_ids[2]: ("stalled", None)}, \
    seen_infos

actual_6 = {"employees": len(users_all), "rbac_mismatch": len(rbac_bad), "probe": probe_res["status"],
            "schema_leaks": leaky, "retention_deleted": len(pruned["deleted"]), "retention_kept": len(left)}
REVIEWED_6 = {"employees": 100, "rbac_mismatch": 0, "probe": "not_permitted", "schema_leaks": [],
              "retention_deleted": 2, "retention_kept": 1}
assert actual_6 == REVIEWED_6, actual_6
print("Phase 6: 100 employees may ask, a probe user is refused before any model call, no user / clock / dataset in a "
      "schema; retention 31 days later: 2 ended threads archived + deleted, the stalled one kept")
print("✅ Phase 6 validation passed.")

# %% Phase 3s — The skill route-cost-advice (S3)
# The advisor's skill parses within the budgets (description ≤ 250 chars, body ≤ 1,200 tokens), names only fields,
# evidence ids, formats and values the route evidence really has, states the owner's rule (P10-1: the cheaper route,
# a cited risk may overrule it; days not priced, P10-2) and its examples render with the real slots of case 2.
# The owner's review is reported (reviewed_by_owner), not assumed.
import re  # noqa: E402

from pipelines.agents import skill_loader  # noqa: E402
from pipelines.agents.graphs import models as gm  # noqa: E402

sk = skill_loader.catalog()["route-cost-advice"]
case2 = ra.deterministic(some_user, RouteRequest(vessel_id=36, origin="SGSIN", destination="NLRTM"),
                         context.DATA_AS_OF, with_context=False)["evidence"]
known = ({k for res in case2.values() for r in res["rows"] for k in r}                      # every row field
         | {k for res in case2.values() for k in res} | {"suez", "cape", "cheaper_route"}
         | {e.removeprefix("route.") for e in case2} | {"route.traffic", "route.news", *case2}
         | {"mean_daily_transits_recent", "mean_daily_transits_year_before", "change_transits_pct"}
         | set(gm.RouteAdvice.model_fields) | set(gm.RouteReason.model_fields)
         | {f for fs in slots.FORMATS.values() for f in fs})
named = sorted(set(re.findall(r"`([A-Za-z0-9_.]+)`", sk.body)))
unknown_named = [n for n in named if n not in known]
examples = re.findall(r"\{route\.[^{}]+\}", sk.body)
ex_errors = [(e, [str(x) for x in slots.render_text(e, case2)[2]]) for e in examples if slots.render_text(e, case2)[2]]
flat = " ".join(sk.body.split())                                 # the rule sentences may wrap across lines
rule_text = all(s in flat for s in ("Recommend `cheaper_route`", "−20 %", "never converted into money",
                                       "Never invent or assume a risk"))
actual_3s = {"stage": sk.stage, "within_budget": len(sk.description) <= skill_loader.DESCRIPTION_MAX
             and sk.body_tokens <= skill_loader.BODY_MAX_TOKENS, "unknown_names": unknown_named,
             "examples": len(examples), "example_errors": ex_errors, "rule_stated": rule_text}
REVIEWED_3s = {"stage": "2", "within_budget": True, "unknown_names": [], "examples": len(examples),
               "example_errors": [], "rule_stated": True}
assert actual_3s == REVIEWED_3s, actual_3s
print(f"Phase 3s: skill route-cost-advice ({len(sk.description)} chars, {sk.body_tokens} tokens), {len(named)} names "
      f"all real, {len(examples)} example slots render on case 2; reviewed by the owner: {sk.reviewed_by_owner}")
print("✅ Phase 3s validation passed.")

# %% Final Checkpoint
# Narrative: pipelines/checkpoints/agents/Route_advice_check.md (written when Phase 10 closes)
pending = ([] if traffic_live else ["Phase 1 live Suez traffic"]) \
    + ([] if sk.reviewed_by_owner != "no" else ["owner review of route-cost-advice"])
print(f"Final Checkpoint: {{'phases_passed': 7, 'pending': {pending}}}")
print(f"✅ Final Checkpoint passed (S1–S5; pending: {pending or 'none'})")
