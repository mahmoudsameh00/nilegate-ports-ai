"""Stage 2 tools check (Agents plan Phase 9, §6a "Concrete design"): each Operations tool tested on its own.

Plan:    docs/archive/2026-11-01_Agents_plan.md §6a (owner decisions P9-1…P9-8, approved 2026-10-27); one phase per step S1…S8.
Run:     uv run python tools/run.py pipelines/scripts/agents/Stage2_tools_check.py  (from the project root)

Reads:   PostgreSQL read-only (PG_RO_USER): employees / roles / departments; MongoDB as the read-only user
         MONGO_RO_USER (ais_positions, ais_vessels).
Writes:  nothing (a refused write to MongoDB is attempted on purpose and must fail).
Re-run:  safe (read-only).

Phases (the plan's steps; later phases are added as their step is built)
0. Foundation (S1): the clock in the run context (`as_of`: default = the data's as-of instant, timezone-aware, never
   past the data), calls without a run context refused, the Stage 2 registry, the MongoDB reader (reads, cannot
   write, different from the app user).
Final Checkpoint (pending items listed).
"""
# %% Setup
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())
sys.path.insert(0, str(ROOT))
from pymongo.errors import OperationFailure  # noqa: E402

from pipelines.agents.tools import context, mongo, registry  # noqa: E402
from pipelines.lib import common  # noqa: E402

common.load_env(ROOT)
E = os.environ

# %% Phase 0 — Foundation (S1)
# Stage 2 reads a replayed world: the synthetic tracks end at the as-of instant 2026-09-13T00:00Z (ADR-032) and the
# ETA evaluation cuts a voyage at an earlier t. The clock therefore travels in the run context like the user and the
# dataset (ADR-049 (2)): the model never sees or sets it, nothing can move it past the data, and the existing
# positional calls RunContext(user) / RunContext(user, dataset) keep working with the default.
some_user = context.load_user(1)
ctx = context.RunContext(some_user)
assert ctx.as_of == context.DATA_AS_OF == datetime(2026, 9, 13, tzinfo=timezone.utc)
assert context.RunContext(some_user, "test").as_of == context.DATA_AS_OF          # Stage 1 call shape unchanged
earlier = context.DATA_AS_OF - timedelta(days=30)
assert context.RunContext(some_user, as_of=earlier).as_of == earlier
refused_clock = []
for bad in (datetime(2026, 9, 1), context.DATA_AS_OF + timedelta(seconds=1)):     # naive; past the data
    try:
        context.RunContext(some_user, as_of=bad)
    except ValueError:
        refused_clock.append(bad.isoformat())


class _Runtime:                       # what LangChain passes as ToolRuntime; only `.context` is read
    def __init__(self, ctx):
        self.context = ctx


assert context.as_of_of(_Runtime(context.RunContext(some_user, as_of=earlier))) == earlier
no_context_refused = 0
for rt in (_Runtime(None), _Runtime({"user": some_user, "as_of": earlier}), object()):
    try:
        context.as_of_of(rt)
    except PermissionError:
        no_context_refused += 1

assert isinstance(registry.STAGE2, dict) and not set(registry.STAGE2) & set(registry.STAGE1)

# MongoDB through the read-only user (P9-6): it authenticates as MONGO_RO_USER with role read on the project
# database only; reading works, writing is refused by the server.
mongo_status = "pending"
if not E.get("MONGO_RO_USER"):
    print("⏸ Phase 0 MongoDB reader pending: MONGO_RO_USER not in .env (db/mongo/005_create_reader_user.js)")
    mongo_actual = None
else:
    assert E["MONGO_RO_USER"] != E["MONGO_APP_USER"], "the reader must not be the app user"
    mdb = mongo.database()
    status = mdb.command("connectionStatus")["authInfo"]
    who = [u["user"] for u in status["authenticatedUsers"]]
    roles = sorted((r["role"], r["db"]) for r in status["authenticatedUserRoles"])
    one = mdb.ais_positions.find_one({"meta.real_or_synthetic": "synthetic"}, {"_id": 0, "ts": 1, "meta.mmsi": 1})
    write_refused = 0
    for attempt in (lambda: mdb["_privilege_check"].insert_one({"t": datetime.now(timezone.utc)}),
                    lambda: mdb.ais_vessels.update_one({"vessel_id": 1}, {"$set": {"x": 1}}),
                    lambda: mdb.ais_positions.delete_many({"meta.mmsi": "000000000"})):
        try:
            attempt()
        except OperationFailure as e:
            write_refused += e.code == 13                   # Unauthorized
    mongo_actual = {"users": who, "roles": roles, "read_ok": one is not None and "ts" in one,
                    "write_refused": write_refused}
    assert mongo_actual == {"users": [E["MONGO_RO_USER"]], "roles": [("read", E["MONGO_DB"])], "read_ok": True,
                            "write_refused": 3}, mongo_actual
    mongo_status = "passed"

actual_0 = {"refused_clock": len(refused_clock), "no_context_refused": no_context_refused,
            "stage2_tools": sorted(registry.STAGE2), "mongo_reader": mongo_status}
REVIEWED_0 = {"refused_clock": 2, "no_context_refused": 3, "stage2_tools": ["marine_weather", "sea_route", "vessel_params", "voyage_status"],
              "mongo_reader": mongo_status}
assert actual_0 == REVIEWED_0, actual_0
print(f"Phase 0: {actual_0}")
print("✅ Phase 0 validation passed.")

# %% Phase 1 — sea_route (S2)
# "Suez or the Cape" = the same route asked twice, once with Suez closed (P9-4: the library's restrictions, F1). The
# distances are checked against an independent published pair (Singapore ↔ Rotterdam 8,288 nm via Suez, 11,755 nm
# via the Cape; Port of Rotterdam Authority, quoted by Hellenic Shipping News 2024-01) within ±3 %, both ways; Port
# Said ↔ Rotterdam is the case where closing Suez changes nothing (the port is the canal's Mediterranean end, F1a);
# Sokhna (inside the Gulf of Suez) with Suez closed has no route at all (F1b). Single-leg synthetic voyages are
# measured with the generator's rule, so sea_route = their route_nm. The 12 cases frozen here are §8's route cases.
import pandas as pd  # noqa: E402
from langchain.tools import ToolRuntime  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from pipelines.agents.tools import routes  # noqa: E402

CASES = [("SGSIN", "NLRTM", []), ("SGSIN", "NLRTM", ["suez"]), ("NLRTM", "SGSIN", []), ("NLRTM", "SGSIN", ["suez"]),
         ("SAJED", "NLRTM", []), ("SAJED", "NLRTM", ["suez"]), ("EGPSD", "NLRTM", []), ("EGPSD", "NLRTM", ["suez"]),
         ("NLRTM", "EGPSD", ["suez"]), ("SGSIN", "NLRTM", ["babalmandab"]), ("EGSOK", "NLRTM", ["suez"]),
         ("EGSOK", "SGSIN", [])]
res = {}
for o, d, av in CASES:
    r = routes.sea_route(some_user, origin=o, destination=d, avoid=av)
    assert r.model_dump() == routes.sea_route(some_user, origin=o, destination=d, avoid=av).model_dump()  # same twice
    res[(o, d, tuple(av))] = r
got = {f"{o}>{d}" + "".join(f"-{p}" for p in av): (r.rows[0]["distance_nm"], r.rows[0]["passages"])
       if r.status == "ok" else r.status for (o, d, av), r in res.items()}
print({k: v[0] if isinstance(v, tuple) else v for k, v in got.items()})

PUBLISHED = {"suez": 8288, "cape": 11755}
for o, d in (("SGSIN", "NLRTM"), ("NLRTM", "SGSIN")):
    via_suez, via_cape = res[(o, d, ())].rows[0], res[(o, d, ("suez",))].rows[0]
    assert abs(via_suez["distance_nm"] / PUBLISHED["suez"] - 1) <= 0.03 and "suez" in via_suez["passages"]
    assert abs(via_cape["distance_nm"] / PUBLISHED["cape"] - 1) <= 0.03 and "south_africa" in via_cape["passages"]
    assert "suez" not in via_cape["passages"]
ps = [res[k].rows[0] for k in (("EGPSD", "NLRTM", ()), ("EGPSD", "NLRTM", ("suez",)), ("NLRTM", "EGPSD", ("suez",)))]
assert len({p["distance_nm"] for p in ps}) == 1 and all(p["passages"] == ["gibraltar"] for p in ps)        # F1a
assert "south_africa" in res[("SGSIN", "NLRTM", ("babalmandab",))].rows[0]["passages"]                    # Red Sea case
nopath = res[("EGSOK", "NLRTM", ("suez",))]
assert nopath.status == "no_data" and not nopath.rows and "no sea route" in nopath.note                    # F1b

# speed → sea days and one point per sea day, the last one at the destination port
sp = routes.sea_route(some_user, origin="SGSIN", destination="NLRTM", speed_kn=15).rows[0]
assert sp["sea_days"] == round(sp["distance_nm"] / 360, 2) and len(sp["day_points"]) == int(-(-sp["distance_nm"] // 360))
assert (sp["day_points"][-1]["lat"], sp["day_points"][-1]["lon"]) == tuple(round(x, 4) for x in routes.ports()["NLRTM"])
assert sp["waypoints"][0] == [round(x, 4) for x in routes.ports()["SGSIN"]] and len(sp["waypoints"]) <= 60

# the generator's measure: single-leg synthetic voyages (no fallback) = sea_route's distance
voy = pd.read_parquet(ROOT / "Data/processed/semi-structured/synthetic/voyages_synthetic.parquet")
single = voy[(voy.route.str.count(">") == 1) & ~voy.route_fallback]
leg_diff = [abs(routes.sea_route(some_user, origin=v.origin_locode, destination=v.destination_locode)
                .rows[0]["distance_nm"] - v.route_nm) for v in single.itertuples()]
assert max(leg_diff) <= 0.1, max(leg_diff)

refused_args = 0
for bad in ({"origin": "sgsin", "destination": "NLRTM"}, {"origin": "SGSIN", "destination": "SGSIN"},
            {"origin": "SGSIN", "destination": "NLRTM", "avoid": ["northwest"]},
            {"origin": "SGSIN", "destination": "NLRTM", "speed_kn": 40}):
    try:
        routes.sea_route(some_user, **bad)
    except ValidationError:
        refused_args += 1
unknown = routes.sea_route(some_user, origin="XXAAA", destination="NLRTM")
assert unknown.status == "no_data" and "XXAAA" in unknown.note

rt = ToolRuntime(state={}, context=context.RunContext(some_user), config={}, stream_writer=lambda *_: None,
                 tool_call_id="t1", store=None)
wrapped = routes.sea_route_tool.invoke({"origin": "SGSIN", "destination": "NLRTM", "avoid": ["suez"], "runtime": rt})
assert wrapped == res[("SGSIN", "NLRTM", ("suez",))].model_dump(mode="json")
schema_fields = set(routes.sea_route_tool.tool_call_schema.model_json_schema()["properties"])
assert schema_fields == {"origin", "destination", "avoid", "speed_kn"}, schema_fields

actual_1 = {"distance_nm": {k: v[0] if isinstance(v, tuple) else v for k, v in got.items()},
            "single_legs": len(single), "refused_args": refused_args}
# reviewed 2026-10-27: the generator's measure (port points at both ends) is ~5 nm longer than searoute's own
# network length (8,383 → 8,388.5); Singapore ↔ Rotterdam +1.2 % / +1.0 % vs the published pair; the same both ways
REVIEWED_1 = {"distance_nm": {"SGSIN>NLRTM": 8388.5, "SGSIN>NLRTM-suez": 11876.7, "NLRTM>SGSIN": 8388.5,
                              "NLRTM>SGSIN-suez": 11876.7, "SAJED>NLRTM": 4036.3, "SAJED>NLRTM-suez": 11005.1,
                              "EGPSD>NLRTM": 3315.8, "EGPSD>NLRTM-suez": 3315.8, "NLRTM>EGPSD-suez": 3315.8,
                              "SGSIN>NLRTM-babalmandab": 11876.7, "EGSOK>NLRTM-suez": "no_data",
                              "EGSOK>SGSIN": 4987.7},
              "single_legs": 9, "refused_args": 4}
assert actual_1 == REVIEWED_1, actual_1
print(f"Phase 1: {len(CASES)} route cases, {len(single)} single-leg voyages = route_nm (max |diff| "
      f"{max(leg_diff):.3f} nm), {refused_args} bad argument sets refused")
print("✅ Phase 1 validation passed.")

# %% Phase 2 — migration 020 + vessel_params (S4–S5)
# The two tables are exactly the reviewed CSVs (rendered into migration 020); every one of our 500 vessels gets one
# band, its own service speed and a fuel figure that follows main × (v / v_ref)³ + aux; the money is the dated VLSFO
# price ÷ the dated USD-per-SDR rate (hand value 936.50 / 1.354820 = 691.24 SDR / t).
import csv  # noqa: E402
from decimal import Decimal  # noqa: E402

from pipelines.agents.tools import db, vessels  # noqa: E402


def _csv(name):
    return list(csv.DictReader(open(ROOT / "db" / "reference" / name, encoding="utf-8")))


def _same(table_rows, csv_rows, keys):
    a = sorted(tuple("" if r[k] is None else str(r[k]) for k in keys) for r in table_rows)
    b = sorted(tuple(r[k] for k in keys) for r in csv_rows)
    norm = lambda t: tuple(str(Decimal(x).normalize()) if x.replace(".", "", 1).isdigit() else x for x in t)  # noqa
    return [norm(t) for t in a] == [norm(t) for t in b]


vp_csv, bp_csv = _csv("vessel_performance.csv"), _csv("bunker_prices.csv")
vp_db = db.fetch("SELECT * FROM vessel_performance", exact=True)
bp_db = db.fetch("SELECT * FROM bunker_prices", exact=True)
assert len(vp_db) == len(vp_csv) == 39 and _same(vp_db, vp_csv, list(vp_csv[0])), "vessel_performance <> its CSV"
assert len(bp_db) == len(bp_csv) == 1 and _same(bp_db, bp_csv, list(bp_csv[0])), "bunker_prices <> its CSV"

vrows = {r["vessel_id"]: r for r in db.fetch("SELECT vessel_id, vessel_type, scnt_tons FROM vessels")}
by_vessel = {vid: vessels.vessel_params(some_user, vessel_id=vid).rows[0] for vid in vrows}
bad_band, bad_speed, bad_fuel = [], [], []
for vid, r in by_vessel.items():
    b = next(p for p in vp_csv if p["vessel_type"] == r["vessel_type"] and float(p["scnt_min"]) <= vrows[vid]["scnt_tons"]
             and (p["scnt_max"] == "" or vrows[vid]["scnt_tons"] < float(p["scnt_max"])))
    bad_band += [vid] if int(b["size_band"]) != r["size_band"] else []
    bad_speed += [vid] if r["speed_kn"] != float(voy.loc[voy.vessel_id == vid, "service_kn"].iloc[0]) else []
    expect = float(b["main_t_per_day"]) * (r["speed_kn"] / float(b["ref_speed_kn"])) ** 3 + float(b["aux_t_per_day"])
    bad_fuel += [vid] if abs(r["fuel_t_per_day"] - expect) > 0.006 else []
assert not (bad_band or bad_speed or bad_fuel), (bad_band[:5], bad_speed[:5], bad_fuel[:5])
bands_used = sorted({(r["vessel_type"], r["size_band"]) for r in by_vessel.values()})

# the cube law and the money, by hand on one band (Containerships band 2: 101.1 + 7.9 t / day at 16.3 kn)
at_ref = vessels.vessel_params(some_user, vessel_type="Containerships", scnt_tons=100000, speed_kn=16.3).rows[0]
slow = vessels.vessel_params(some_user, vessel_type="Containerships", scnt_tons=100000, speed_kn=16.3 * 0.8).rows[0]
assert (at_ref["size_band"], at_ref["cube_factor"], at_ref["fuel_t_per_day"]) == (2, 1.0, 109.0)
assert slow["main_t_per_day"] == round(101.1 * 0.512, 2) and slow["fuel_t_per_day"] == round(101.1 * 0.512 + 7.9, 2)
assert at_ref["price_sdr_per_t"] == 691.24 and at_ref["fuel_cost_sdr_per_day"] == round(109.0 * 936.50 / 1.354820, 2)
assert (at_ref["price_date"], at_ref["rate_date"]) == ("2026-10-26", "2026-10-26")
ref_default = vessels.vessel_params(some_user, vessel_type="Containerships", scnt_tons=100000).rows[0]
assert ref_default["speed_source"].startswith("IMO") and ref_default["speed_kn"] == 16.3
edges = [vessels.vessel_params(some_user, vessel_type="Containerships", scnt_tons=t).rows[0]["size_band"]
         for t in (88999.9, 89000, 152999.9, 153000)]
assert edges == [1, 2, 2, 3], edges                                      # lower bound inclusive, upper exclusive

refused_params = 0
for bad in ({}, {"vessel_id": 1, "vessel_type": "Containerships", "scnt_tons": 1000},
            {"vessel_type": "Containerships"}, {"vessel_type": "Tug", "scnt_tons": 1000},
            {"vessel_type": "Containerships", "scnt_tons": 0}, {"vessel_id": 1, "speed_kn": 40}):
    try:
        vessels.vessel_params(some_user, **bad)
    except ValidationError:
        refused_params += 1
missing = vessels.vessel_params(some_user, vessel_id=9999)
assert missing.status == "no_data" and not missing.rows

wrapped_p = vessels.vessel_params_tool.invoke({"vessel_id": 1, "runtime": rt})
assert wrapped_p == vessels.vessel_params(some_user, vessel_id=1).model_dump(mode="json")
assert set(vessels.vessel_params_tool.tool_call_schema.model_json_schema()["properties"]) == \
    {"vessel_id", "vessel_type", "scnt_tons", "speed_kn"}

v1 = by_vessel[1]
actual_2 = {"vessels": len(by_vessel), "bands_used": len(bands_used), "refused_args": refused_params,
            "vessel_1": {k: v1[k] for k in ("vessel_type", "size_band", "speed_kn", "cube_factor", "fuel_t_per_day",
                                            "fuel_cost_sdr_per_day")}}
# reviewed 2026-10-27: vessel 1 = a Special Floating Unit of band 1 at its 8.97 kn service speed:
# (8.97 / 8.5)³ = 1.1752 → 7.5 × 1.1752 + 1.4 = 10.21 t / day → × 691.24 SDR / t = 7,060.40 SDR / day
REVIEWED_2 = {"vessels": 500, "bands_used": 39, "refused_args": 6,
              "vessel_1": {"vessel_type": "Special Floating Units", "size_band": 1, "speed_kn": 8.97,
                           "cube_factor": 1.1752, "fuel_t_per_day": 10.21, "fuel_cost_sdr_per_day": 7060.4}}
assert actual_2 == REVIEWED_2, actual_2
print(f"Phase 2: tables = CSVs (39 + 1), {len(by_vessel)} vessels each in its band at its service speed, "
      f"{len(bands_used)} bands used, cube law + SDR price by hand, {refused_params} bad argument sets refused")
print("✅ Phase 2 validation passed.")

# %% Phase 3 — voyage_status (S6)
# At the data's as-of instant every one of the 500 voyages must agree with the generator: the last fix = MongoDB's
# latest, the rebuilt route = route_nm, the status read from the track = vessels.status, and for the 219 vessels at
# sea the distance left = the generator's own remaining distance at that fix (its timeline: harbour speed over the
# first / last 10 nm, a constant service speed between, implied exactly by departure → arrival). Then the cut: at an
# earlier t the tool uses no later fix and returns no arrival time — and never the declared ETA (P9-7).
import json  # noqa: E402

import numpy as np  # noqa: E402

from pipelines.agents.tools import voyages  # noqa: E402

HARBOUR_KN = round(json.loads((ROOT / "Data/processed/semi-structured/profiles/noaa_profile.json")
                              .read_text(encoding="utf-8"))["profile"]["implied_kn_moving"]["0.5"], 1)
status_pg = {r["vessel_id"]: r["status"] for r in db.fetch("SELECT vessel_id, status FROM vessels")}
vs = {vid: voyages.voyage_status(some_user, vessel_id=vid) for vid in sorted(status_pg)}
assert all(r.status == "ok" for r in vs.values())
rows3 = {vid: r.rows[0] for vid, r in vs.items()}
V = voy.set_index("vessel_id")

len_diff = max(abs(r["route_nm"] - V.at[vid, "route_nm"]) for vid, r in rows3.items())
status_mismatch = [vid for vid, r in rows3.items() if r["status_at_as_of"] != status_pg[vid]]
assert len_diff <= 0.1 and not status_mismatch, (len_diff, status_mismatch[:5])

fix_diff_s = max(abs((pd.Timestamp(r["last_fix"]["ts"]) - V.at[vid, "last_fix_ts"]).total_seconds())
                 for vid, r in rows3.items())
assert fix_diff_s < 1, fix_diff_s                                        # = the generator's last fix


def truth_covered(vid, t):
    """The generator's along-route distance at time t (its speed profile, service speed implied by the timeline)."""
    L, dep, arr = V.at[vid, "route_nm"], V.at[vid, "departure_ts"], V.at[vid, "arrival_ts"]
    a1, a2 = min(10.0, L / 2), max(L - 10.0, L / 2)
    total_h = (arr - dep).total_seconds() / 3600
    service = (a2 - a1) / (total_h - a1 / HARBOUR_KN - (L - a2) / HARBOUR_KN)
    T = np.cumsum([0.0, a1 / HARBOUR_KN, (a2 - a1) / service, (L - a2) / HARBOUR_KN])
    return float(np.interp((pd.Timestamp(t) - dep).total_seconds() / 3600, T, [0.0, a1, a2, L]))


at_sea = [vid for vid, s in status_pg.items() if s == "In Transit"]
left_err = {vid: abs(rows3[vid]["distance_left_nm"] - (V.at[vid, "route_nm"]
                                                        - truth_covered(vid, rows3[vid]["last_fix"]["ts"])))
            for vid in at_sea}
anchored_err = max(abs(rows3[vid]["distance_left_nm"] - 5.0) for vid, s in status_pg.items() if s == "Anchored")
arrived = [vid for vid, s in status_pg.items() if s in ("At Port", "Completed")]
assert max(left_err.values()) <= 2.0, sorted(left_err.items(), key=lambda kv: -kv[1])[:5]
assert anchored_err <= 2.0, anchored_err                                 # anchorage 5 nm before the destination
assert all(rows3[vid]["distance_left_nm"] == 0 and rows3[vid]["arrival_ts"] for vid in arrived)
assert all(rows3[vid]["arrival_ts"] is None and rows3[vid]["next_port"] == rows3[vid]["ports_left"][0]
           for vid in at_sea)

# the cut: half-way between departure and the as-of instant, for every vessel at sea
cut_bad = []
for vid in at_sea:
    t = V.at[vid, "departure_ts"] + (context.DATA_AS_OF - V.at[vid, "departure_ts"]) / 2
    r = voyages.voyage_status(some_user, as_of=t.to_pydatetime(), vessel_id=vid).rows[0]
    late_fix = pd.Timestamp(r["last_fix"]["ts"]) > t
    err = abs(r["distance_covered_nm"] - truth_covered(vid, r["last_fix"]["ts"]))
    if late_fix or r["arrival_ts"] is not None or r["status_at_as_of"] != "In Transit" or err > 2.0:
        cut_bad.append((vid, late_fix, r["status_at_as_of"], round(err, 2)))
assert not cut_bad, cut_bad[:5]
before = voyages.voyage_status(some_user, as_of=(V.at[at_sea[0], "departure_ts"] - pd.Timedelta(hours=3))
                               .to_pydatetime(), vessel_id=at_sea[0]).rows[0]
assert before["status_at_as_of"] == "Not departed" and before["departure_ts"] is None and before["distance_covered_nm"] == 0
too_early = voyages.voyage_status(some_user, as_of=datetime(2026, 1, 1, tzinfo=timezone.utc), vessel_id=at_sea[0])
assert too_early.status == "no_data" and not too_early.rows

# no answer key anywhere: no declared ETA field, no time after the run's clock
leaks = [vid for vid, r in rows3.items() if "eta" in json.dumps(r).lower() or any(
    isinstance(x, str) and x[:4] == "2026" and len(x) > 10 and pd.Timestamp(x) > context.DATA_AS_OF
    for x in [r["departure_ts"], r["arrival_ts"], r["last_fix"]["ts"], r["as_of"]] if x)]
assert not leaks, leaks[:5]
try:
    voyages.voyage_status(some_user, as_of=context.DATA_AS_OF + timedelta(hours=1), vessel_id=1)
    raise AssertionError("a clock past the data was accepted")
except ValueError:
    pass

rt_cut = ToolRuntime(state={}, context=context.RunContext(some_user, as_of=earlier), config={},
                     stream_writer=lambda *_: None, tool_call_id="t3", store=None)
assert voyages.voyage_status_tool.invoke({"vessel_id": at_sea[0], "runtime": rt_cut}) == \
    voyages.voyage_status(some_user, as_of=earlier, vessel_id=at_sea[0]).model_dump(mode="json")
assert set(voyages.voyage_status_tool.tool_call_schema.model_json_schema()["properties"]) == {"vessel_id"}

counts = pd.Series([r["status_at_as_of"] for r in rows3.values()]).value_counts().to_dict()
actual_3 = {"statuses": counts, "max_left_err_nm": round(float(max(left_err.values())), 2), "cut_vessels": len(at_sea)}
# reviewed 2026-10-27: statuses = vessels.status exactly; the largest distance-left error is vessel 250 (1.79 nm, the
# odometer tie-break on a long route); port visits that retrace the same water are told apart by the fix's course
REVIEWED_3 = {"statuses": {"In Transit": 219, "At Port": 130, "Anchored": 78, "Completed": 73},
              "max_left_err_nm": 1.79, "cut_vessels": 219}
assert actual_3 == REVIEWED_3, actual_3
print(f"Phase 3: 500 voyages = the generator (route, last fix, status), distance left within "
      f"{max(left_err.values()):.2f} nm for {len(at_sea)} at sea, the cut uses no later fix, no answer key")
print("✅ Phase 3 validation passed.")

# %% Phase 4 — marine_weather (S7)
# Offline first (httpx.MockTransport, a throw-away cache folder, a fixed "today" = 2026-10-27): each point keeps its
# own date's value; past dates read the Historical Forecast API for wind, later dates the Forecast API, waves the Marine
# API; an answer is cached and the second call sends 0 requests; a timeout, HTTP 500, a non-JSON body or a payload of
# the wrong shape gives context_unavailable with no rows and nothing cached; a land point / a date beyond the horizon
# stays null with a note. Then one live call: 3 points on 2026-09-13 (the probe of §6a F5), cached for good.
import shutil  # noqa: E402
import tempfile  # noqa: E402
from datetime import date as _date  # noqa: E402

import httpx  # noqa: E402

from pipelines.agents.tools import external, weather  # noqa: E402

tmp_cache = Path(tempfile.mkdtemp(prefix="weather_cache_check_"))
real_http, real_today = external.HTTP, external.TODAY
sent: list[httpx.Request] = []
wmode = {"m": "ok"}


def _om(req: httpx.Request) -> httpx.Response:
    """A fake Open-Meteo: value = day of month (+ 0.1 per point index) for waves, × 10 for wind; point 2 = land."""
    sent.append(req)
    m = wmode["m"]
    if m == "timeout":
        raise httpx.ReadTimeout("slow", request=req)
    if m == "500":
        return httpx.Response(500, text="oops")
    if m == "notjson":
        return httpx.Response(200, text="<html>maintenance</html>")
    q = req.url.params
    lats = q["latitude"].split(",")
    start, end = _date.fromisoformat(q["start_date"]), _date.fromisoformat(q["end_date"])
    days = [(start + timedelta(days=k)) for k in range((end - start).days + 1)]
    out = []
    for i in range(len(lats) - (1 if m == "badshape" else 0)):
        d = {"time": [x.isoformat() for x in days]}
        for v in q["daily"].split(","):
            scale = 10 if "wind" in v and "wave" not in v else 1
            d[v] = [None if i == 2 else round((x.day + i / 10) * scale, 2) for x in days]
        out.append({"latitude": float(lats[i]), "daily": d})
    return httpx.Response(200, json=out if len(out) != 1 else out[0])


P3 = [{"lat": 32.27, "lon": 30.55, "date": "2026-09-13"}, {"lat": 13.0, "lon": 43.2, "date": "2026-09-14"},
      {"lat": 30.0, "lon": 31.2, "date": "2026-09-15"}]                     # the third point is on land (Cairo)
try:
    external.HTTP = httpx.Client(transport=httpx.MockTransport(_om), timeout=external.TIMEOUT_S)
    external.TODAY = _date(2026, 10, 27)
    external._caches["marine_weather"] = external.ExternalCache("marine_weather", tmp_cache)

    w1 = weather.marine_weather(some_user, points=P3)
    n1 = len(sent)
    w2 = weather.marine_weather(some_user, points=P3)
    hosts_past = sorted({r.url.host for r in sent})
    assert w1.status == "ok" and w2.model_dump() == w1.model_dump() and len(sent) == n1 == 2   # cached: 0 requests
    assert [r["wave_height_max"] for r in w1.rows] == [13.0, 14.1, None]                       # own date per point
    assert [r["wind_speed_10m_max_kn"] for r in w1.rows] == [130.0, 141.0, None]
    assert w1.rows[0]["wind_source"] == "Open-Meteo Historical Forecast" and "1 of 3 points" in w1.note
    assert "not suitable for coastal navigation" in w1.note and w1.source.retrieved_at

    future = weather.marine_weather(some_user, points=[{"lat": 32.27, "lon": 30.55, "date": "2026-10-29"},
                                                       {"lat": 13.0, "lon": 43.2, "date": "2026-11-08"}])
    fr = future.rows
    assert fr[0]["wind_source"] == "Open-Meteo Forecast" and fr[0]["wave_height_max"] == 29.0
    assert fr[1]["wave_height_max"] is None and fr[1]["wind_speed_10m_max_kn"] == 81.0           # waves: > 7 days
    beyond = weather.marine_weather(some_user, points=[{"lat": 1.0, "lon": 1.0, "date": "2026-12-01"}])
    assert beyond.status == "no_data" and not beyond.rows

    weather_failures = {}
    for k, m in enumerate(("timeout", "500", "notjson", "badshape")):
        wmode["m"] = m
        pts = [{"lat": 10.0 + k, "lon": 60.0, "date": "2026-08-01"}, {"lat": 11.0 + k, "lon": 61.0, "date": "2026-08-02"}]
        r = weather.marine_weather(some_user, points=pts)
        weather_failures[m] = (r.status, len(r.rows))
    wmode["m"] = "ok"
    cached_entries = len(external._caches["marine_weather"].entries)
    assert all(v == ("context_unavailable", 0) for v in weather_failures.values()), weather_failures
    assert cached_entries == 4, cached_entries          # P3 (marine + past wind) + future (marine + wind); failures 0

    refused_w = 0
    for bad in ({"points": []}, {"points": [P3[0]] * 31}, {"points": [{"lat": 95, "lon": 0, "date": "2026-09-13"}]},
                {"points": [{"lat": 0, "lon": 0, "date": "2026-01-01"}, {"lat": 0, "lon": 0, "date": "2026-06-01"}]}):
        try:
            weather.marine_weather(some_user, **bad)
        except ValidationError:
            refused_w += 1
    wrapped_w = weather.marine_weather_tool.invoke({"points": P3, "runtime": rt})
    assert wrapped_w == w1.model_dump(mode="json")
    assert set(weather.marine_weather_tool.tool_call_schema.model_json_schema()["properties"]) == {"points"}
finally:
    external.HTTP, external.TODAY = real_http, real_today
    external._caches.pop("marine_weather", None)
    shutil.rmtree(tmp_cache, ignore_errors=True)

# live: the three probe points of §6a F5 on 2026-09-13 (eastern Mediterranean, Bab el-Mandeb, off the Cape)
LIVE = [{"lat": 32.27, "lon": 30.55, "date": "2026-09-13"}, {"lat": 13.0, "lon": 43.2, "date": "2026-09-13"},
        {"lat": -35.0, "lon": 20.0, "date": "2026-09-13"}]
live_w = weather.marine_weather(some_user, points=LIVE)
weather_live = live_w.status == "ok"
if weather_live:
    live_vals = [(r["wave_height_max"], r["wind_speed_10m_max_kn"]) for r in live_w.rows]
    assert all(r["wave_source"] == "Open-Meteo Marine" and r["wind_source"] == "Open-Meteo Historical Forecast"
               for r in live_w.rows)
else:
    live_vals = None
    print(f"⏸ Phase 4 live Open-Meteo pending: {live_w.status} ({live_w.note})")

actual_4 = {"failures": weather_failures, "refused_args": refused_w, "hosts_past": hosts_past,
            "live": live_vals if weather_live else "pending"}
# reviewed 2026-10-27: the live values = the §6a F5 probe of the same day (waves m, wind kn)
REVIEWED_4 = {"failures": {m: ("context_unavailable", 0) for m in ("timeout", "500", "notjson", "badshape")},
              "refused_args": 4, "hosts_past": ["historical-forecast-api.open-meteo.com", "marine-api.open-meteo.com"],
              "live": [(0.84, 12.2), (0.52, 15.9), (4.14, 32.7)] if weather_live else "pending"}
assert actual_4 == REVIEWED_4, actual_4
print(f"Phase 4: own date per point, past / future APIs, cache (0 requests on repeat), 4 failure modes → "
      f"context_unavailable, land / horizon → null, {refused_w} bad argument sets refused, live = {actual_4['live']}")
print("✅ Phase 4 validation passed.")

# %% Phase 5 — RBAC matrix + contract (S8)
# Every employee (100) × every Stage 2 tool = the ADR-006 expectation computed independently from the tool's resources
# (all level 1 → every role, every department is granted). No real user is refused a level-1 resource, so the refusal
# path is proven with a probe user below every ceiling: each tool answers not_permitted with no row and no source
# (leakage 0). No model-facing schema has a user, dataset or clock field, and no wrapper runs without a RunContext.
from pipelines.lib.retrieval import User, allowed  # noqa: E402

CALLS = {"sea_route": {"origin": "SGSIN", "destination": "NLRTM"}, "vessel_params": {"vessel_id": 1},
         "voyage_status": {"vessel_id": 1}, "marine_weather": {"points": LIVE}}
RESOURCES = {"sea_route": [context.PORTS], "vessel_params": [context.VESSEL_PARAMS, context.VESSELS,
                                                              context.AIS_TRACKS],
             "voyage_status": [context.AIS_TRACKS, context.PORTS, context.VESSELS],
             "marine_weather": [context.PUBLIC_EXTERNAL]}
assert set(CALLS) == set(RESOURCES) == set(registry.STAGE2)
users_all = {r["employee_id"]: context.load_user(r["employee_id"]) for r in db.fetch("SELECT employee_id FROM employees")}
matrix_bad, granted = [], 0
for emp_id, u in users_all.items():
    for name, (_, fn) in registry.STAGE2.items():
        expect = all(allowed(u, r.level, r.department) for r in RESOURCES[name])
        res = fn(u, **CALLS[name])
        ok = res.status == "ok" if expect else (res.status == "not_permitted" and not res.rows)
        granted += res.status == "ok"
        matrix_bad += [] if ok else [(emp_id, name, res.status)]
assert not matrix_bad, matrix_bad[:5]

probe = User(0, "probe", 0, "Nowhere")                                   # below every ceiling, no department
leak = []
for name, (_, fn) in registry.STAGE2.items():
    r = fn(probe, **CALLS[name])
    if r.status != "not_permitted" or r.rows or r.source is not None:
        leak.append((name, r.status))
assert not leak, leak

bad_schema = {name: sorted(f for f in t.tool_call_schema.model_json_schema()["properties"]
                           if f in ("user", "employee_id", "dataset", "as_of", "runtime"))
              for name, (t, _) in registry.STAGE2.items()}
assert not any(bad_schema.values()), bad_schema
no_ctx = 0
for name, (t, _) in registry.STAGE2.items():
    try:
        t.func(_Runtime(None), **CALLS[name])
    except PermissionError:
        no_ctx += 1

actual_5 = {"employees": len(users_all), "calls_granted": granted, "matrix_mismatch": len(matrix_bad),
            "probe_leaks": len(leak), "no_context_refused": no_ctx}
REVIEWED_5 = {"employees": 100, "calls_granted": 400, "matrix_mismatch": 0, "probe_leaks": 0, "no_context_refused": 4}
assert actual_5 == REVIEWED_5, actual_5
print(f"Phase 5: RBAC matrix 100 employees × 4 tools = ADR-006 (400 granted), probe user refused by all 4 with no "
      f"row (leakage 0), no user / dataset / clock field in any schema, {no_ctx} / 4 wrappers refuse a missing context")
print("✅ Phase 5 validation passed.")

# %% Final Checkpoint
# Narrative: pipelines/checkpoints/agents/Stage2_tools_check.md (written when Phase 9 closes)
pending = ([] if mongo_status == "passed" else ["Phase 0 MongoDB reader (MONGO_RO_USER not set / not created)"]) + \
          ([] if weather_live else ["Phase 4 live Open-Meteo (no answer)"])
summary = {"phases_passed": (mongo_status == "passed") + 5, "pending": pending}
print(f"Final Checkpoint: {summary}")
print(f"✅ Final Checkpoint passed (S1–S8; pending: {pending or 'none'})")
