"""Voyage watch check (Agents plan Phase 11, §6c): ETA rules, alerts, the `voyage_watch` graph (C Voyage & Disruption
Watch).

Plan:    docs/archive/2026-11-01_Agents_plan.md §6c (decisions P11-1…P11-10, autonomous grant 2026-10-27, owner to review); one
         phase per step S1…S5.
Run:     uv run python tools/run.py pipelines/scripts/agents/Voyage_watch_check.py  (from the project root)

Reads:   PostgreSQL read-only (vessels, migration 020 tables through the tools), MongoDB AIS fixes (read-only user), the
         voyage file (its `arrival_ts` = the answer key: read by THIS check only, never by a predictor), searoute
         locally, the NOAA harbour profile.
Writes:  Data/processed/agents/eval/eta_cases.json and eta_eval.json on their first run only (frozen; later runs
         assert them).
Re-run:  safe.

Phases (the plan's tests; each is added as its step is built)
1. ETA rules (S1) on the 50 frozen voyages: R (the product), N (the naive baseline, the S2-D5 bar), S and R0
   (references) against the generator's arrival; MAE(R) < MAE(N); the ML margin of S2-D2; no predictor input after
   the cut.
2. Next-leg points and Suez ahead (S2) against the generator's timeline and searoute's passages.
3. Alert rules (S3) on planted weather / traffic events: precision and recall, reproducible, sensitivity.
4. The brief's slots and Validator (S3): planted errors caught, clean briefs pass. 4s. The skill voyage-watch-brief.
5. The graph (S4) on FakeRoles + PostgresSaver: every path, the run file, crash + resume.
6. The real model once (S5) on the live (cached) weather and traffic.
7. RBAC, contract, the replay planner, firings + retention, the alert reader (S5).
   Phases 5–7 write check threads `voyage_watch_check:…` in agent_state and delete them at the end.
Final Checkpoint (pending items listed).
"""
# %% Setup
import sys
from pathlib import Path

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())
sys.path.insert(0, str(ROOT))
import json  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from pipelines.agents.tools import context, db, eta, vessels, voyages  # noqa: E402
from pipelines.lib import common  # noqa: E402

common.load_env(ROOT)
EVAL = ROOT / "Data/processed/agents/eval"
OPS_MANAGER = 2                                     # an Operations manager (F9 probe: employees 2 and 3)
ops_user = context.load_user(OPS_MANAGER)
assert (ops_user.role, ops_user.department) == ("manager", "Operations"), ops_user


def freeze(path: Path, obj) -> None:
    """Write on the first run, assert equal on every later run (a reviewed artifact never changes silently)."""
    text = json.dumps(obj, indent=1, ensure_ascii=False) + "\n"
    if not path.exists():
        path.write_text(text, encoding="utf-8", newline="\n")
    assert json.loads(path.read_text(encoding="utf-8")) == json.loads(text), f"{path.name} changed: frozen file differs"


# %% Phase 1 — ETA rules on the 50 frozen voyages (S1)
# The cases follow §6c's rule, fixed before any prediction: 25 arrived voyages (At Port + Completed) and 25 at sea (In
# Transit), each list sorted by vessel_id, ranks round(i × n / 25); route fallbacks excluded; Anchored out (their
# arrival_ts is the anchorage, F8). Cuts at 25 / 50 / 75 % of the sailing time, kept when ≤ the data's as-of instant,
# plus the as-of instant for the voyages at sea. arrival_ts places the cut (sampling) and scores the prediction; the
# predictors see voyage_status at the cut (fixes ts <= cut, no arrival_ts) and the planned speed only.
voy = voyages.voyages()
truth = voy["arrival_ts"]


def pick(statuses: tuple[str, ...]) -> list[int]:
    ids = sorted(int(i) for i in voy.index[voy["status"].isin(statuses) & ~voy["route_fallback"]])
    return [ids[round(i * len(ids) / 25)] for i in range(25)]


cases = []
for group, ids in (("arrived", pick(("At Port", "Completed"))), ("at_sea", pick(("In Transit",)))):
    for vid in ids:
        dep, arr = voy.at[vid, "departure_ts"], truth[vid]
        cuts = [(f"{int(f * 100)}%", (dep + (arr - dep) * f).floor("s")) for f in (0.25, 0.5, 0.75)]
        cuts = [(lab, c) for lab, c in cuts if c <= context.DATA_AS_OF]
        if group == "at_sea":
            cuts.append(("as_of", pd.Timestamp(context.DATA_AS_OF)))
        cases += [{"vessel_id": vid, "group": group, "cut": lab, "t": c.isoformat()} for lab, c in cuts]
freeze(EVAL / "eta_cases.json", {"rule": "Agents plan §6c: 25 arrived (At Port + Completed) + 25 In Transit, ranks "
                                         "round(i*n/25) by vessel_id, fallbacks out; cuts 25/50/75 % of the sailing "
                                         "time <= the as-of instant, + the as-of instant for the voyages at sea",
                                 "cases": cases})

preds, guard = [], {"arrival_seen": 0, "fix_after_cut": 0, "not_in_transit": 0}
planned_cache: dict[int, float] = {}
for c in cases:
    t = pd.Timestamp(c["t"]).to_pydatetime()
    st = voyages.voyage_status(ops_user, as_of=t, vessel_id=c["vessel_id"])
    assert st.status == "ok", (c, st.note)
    s = st.rows[0]
    guard["arrival_seen"] += s["arrival_ts"] is not None or "eta_raw" in json.dumps(s)
    guard["fix_after_cut"] += pd.Timestamp(s["last_fix"]["ts"]) > pd.Timestamp(t)
    if s["status_at_as_of"] != "In Transit":
        guard["not_in_transit"] += 1
        continue
    vid = c["vessel_id"]
    if vid not in planned_cache:
        planned_cache[vid] = vessels.vessel_params(ops_user, vessel_id=vid).rows[0]["speed_kn"]
    p = planned_cache[vid]
    est = {"R": eta.eta_rule(s, p), "R0": eta.eta_rule(s, p, approach=False), "N": eta.eta_naive(s, p),
           "S": eta.eta_schedule(s, p)}
    left_h = (truth[vid] - pd.Timestamp(t)).total_seconds() / 3600
    preds.append({**c, "remaining_h": round(left_h, 2), "speed_source": est["R"]["speed_source"].split(" (")[0],
                  **{f"err_{k}_h": round((pd.Timestamp(e["eta_utc"]) - truth[vid]).total_seconds() / 3600, 3)
                     for k, e in est.items()}})
P = pd.DataFrame(preds)


def stats(err: pd.Series) -> dict:
    a = err.abs()
    return {"mae_h": round(float(a.mean()), 3), "median_h": round(float(a.median()), 3),
            "p90_h": round(float(a.quantile(0.9)), 3), "max_h": round(float(a.max()), 3),
            "bias_h": round(float(err.mean()), 3)}


bucket = pd.cut(P["remaining_h"], [0, 24, 120, np.inf], labels=["<24h", "1-5d", ">5d"])
results = {"predictions": len(P), "by_group": P["group"].value_counts().sort_index().to_dict(),
           "by_cut": P["cut"].value_counts().sort_index().to_dict(),
           "mean_remaining_h": round(float(P["remaining_h"].mean()), 2),
           "methods": {k: stats(P[f"err_{k}_h"]) for k in ("R", "N", "S", "R0")},
           "R_by_bucket": {str(b): stats(P.loc[bucket == b, "err_R_h"]) | {"n": int((bucket == b).sum())}
                           for b in ("<24h", "1-5d", ">5d")},
           "R_speed_source": P["speed_source"].value_counts().to_dict()}
mae = {k: v["mae_h"] for k, v in results["methods"].items()}
results["threshold_R_beats_N"] = mae["R"] < mae["N"]
ml_needed = mae["R"] > 2.0 and mae["R"] > 0.05 * results["mean_remaining_h"]
results["ml_margin"] = {"rule": "a learned model only if MAE(R) > 2 h and > 5 % of the mean remaining hours",
                        "needed": ml_needed}
worst = P.loc[P["err_R_h"].abs().idxmax(), ["vessel_id", "cut", "remaining_h", "err_R_h", "speed_source"]].to_dict()
results["R_worst"] = {k: (int(v) if k == "vessel_id" else v) for k, v in worst.items()}
FREEZE_EVAL = True                                  # set after the first clean run was reviewed (2026-10-27); no tuning after it
if FREEZE_EVAL:
    freeze(EVAL / "eta_eval.json", {"plan": "§6c P11-1…P11-3", "data_as_of": context.DATA_AS_OF.isoformat(),
                                    **results})
print({"guard": guard, "predictions": results["predictions"], "mae_h": mae, "ml_needed": ml_needed,
       "R_worst": results["R_worst"]})
print({"R_by_bucket": {b: (v["n"], v["mae_h"]) for b, v in results["R_by_bucket"].items()},
       "R_speed_source": results["R_speed_source"]})

assert guard == {"arrival_seen": 0, "fix_after_cut": 0, "not_in_transit": 0}, guard
assert results["threshold_R_beats_N"], f"S2-D5 not met: MAE(R) {mae['R']} h ≥ MAE(N) {mae['N']} h"
assert eta.harbour_kn() == 6.7
reviewed_1 = {"cases": 126, "predictions": 126, "mae_h": {"R": 0.885, "N": 117.826, "S": 1.636, "R0": 1.274},
              "ml_needed": False}
actual_1 = {"cases": len(cases), "predictions": len(P), "mae_h": mae, "ml_needed": ml_needed}
print("Phase 1 snapshot:", actual_1)
assert not reviewed_1 or actual_1 == reviewed_1, (actual_1, reviewed_1)
print("✅ Phase 1 validation passed.")

# %% Phase 2 — Next-leg points and Suez ahead (S2)
# The watch reads the weather where each vessel will be now and at +24 / +48 / +72 h (P11-4). Truth here = the
# generator's own timeline (AIS_generator.py Phase 4, its parameters read from its manifest): harbour speed over the
# first / last approach, the voyage's service speed between; the geometry is the rebuilt route (= route_nm, ADR-055).
# Points are dropped after the predicted arrival; a point kept or dropped differently from the truth is counted.
# Suez ahead (F10): on every route at departure = "a leg traverses suez" by searoute directly; at the end = never;
# for the fleet at sea: a later leg through the canal → ahead; neither the current nor a later leg → not ahead.
import warnings  # noqa: E402

import searoute  # noqa: E402

from pipelines.agents.tools import routes  # noqa: E402

gen = json.loads((ROOT / "Data/processed/semi-structured/synthetic/ais_generation_manifest.json")
                 .read_text(encoding="utf-8"))["params"]
H_KN, APP_NM = gen["harbour_kn"], gen["approach_nm"]


def true_along(vid: int, at: pd.Timestamp) -> float:
    """The generator's along-route distance at `at`; the service speed implied by its timeline (the file's
    `service_kn` is rounded to 2 decimals: 0.005 kn over 1,900 h is 10 nm — found 2026-10-28, as Phase 9 did)."""
    L = float(voyages.route_of(vid)["cum"][-1])
    a1, a2 = min(APP_NM, L / 2), max(L - APP_NM, L / 2)
    total_h = (truth[vid] - voy.at[vid, "departure_ts"]).total_seconds() / 3600
    service = (a2 - a1) / (total_h - a1 / H_KN - (L - a2) / H_KN)
    T = np.cumsum([0.0, a1 / H_KN, (a2 - a1) / service, (L - a2) / H_KN])
    return float(np.interp((at - voy.at[vid, "departure_ts"]).total_seconds() / 3600, T, [0.0, a1, a2, L]))


asof_ts = pd.Timestamp(context.DATA_AS_OF)
at_sea = sorted(int(i) for i in voy.index[voy["status"] == "In Transit"])
fleet_status, fleet_eta, fleet_pts = {}, {}, {}
leg_err = {h: [] for h in eta.LEG_HOURS}
kept_mismatch, pos_err = 0, []
for vid in at_sea:
    s = voyages.voyage_status(ops_user, vessel_id=vid).rows[0]
    planned = vessels.vessel_params(ops_user, vessel_id=vid).rows[0]["speed_kn"]
    e = eta.eta_rule(s, planned)
    pts = eta.next_leg_points(vid, s, e)
    fleet_status[vid], fleet_eta[vid], fleet_pts[vid] = s, e, pts
    true_left_h = (truth[vid] - asof_ts).total_seconds() / 3600
    kept_mismatch += sum((h == 0 or h <= true_left_h) != any(p["hours_ahead_h"] == h for p in pts)
                         for h in eta.LEG_HOURS)
    r = voyages.route_of(vid)
    for p in pts:
        st = true_along(vid, asof_ts + pd.Timedelta(hours=p["hours_ahead_h"]))
        leg_err[int(p["hours_ahead_h"])].append(p["along_nm"] - st)
        tl, tn = routes.point_at(r, st)
        pos_err.append(float(routes.gc_nm(np.array(p["lat"]), np.array(p["lon"]), tl, tn)[0]))
        assert p["date"] == (asof_ts + pd.Timedelta(hours=p["hours_ahead_h"])).date().isoformat()
leg_stats = {h: round(float(np.abs(v).max()), 2) for h, v in leg_err.items() if v}
n_points = sum(len(v) for v in fleet_pts.values())
print({"vessels": len(at_sea), "points": n_points, "max_along_err_nm_by_h": leg_stats,
       "max_pos_err_nm": round(max(pos_err), 2), "kept_mismatch": kept_mismatch})


def leg_passages(a: str, b: str) -> set[str]:
    P_ = routes.ports()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        f = searoute.searoute([P_[a][1], P_[a][0]], [P_[b][1], P_[b][0]], units="naut", return_passages=True)
    return set(f["properties"].get("traversed_passages") or [])


all_ids = sorted(int(i) for i in voy.index[~voy["route_fallback"]])
leg_cache: dict[tuple[str, str], set[str]] = {}
start_mismatch, end_true = [], 0
for vid in all_ids:
    ports_ = voy.at[vid, "route"].split(">")
    legs = [leg_cache.setdefault((a, b), leg_passages(a, b)) for a, b in zip(ports_[:-1], ports_[1:])]
    if eta.suez_ahead(vid, 0.0) != any("suez" in x for x in legs):
        start_mismatch.append(vid)
    end_true += eta.suez_ahead(vid, float(voyages.route_of(vid)["cum"][-1]) + 1)
fleet_suez = {"ahead": 0, "bound_violations": [], "decided_by_box": 0}
for vid in at_sea:
    r, s = voyages.route_of(vid), fleet_status[vid]
    ports_ = r["ports"]
    k = int(np.searchsorted(r["port_cum"], s["distance_covered_nm"], side="right") - 1)
    legs = ([set()] if voy.at[vid, "route_fallback"] else             # a fallback = one great-circle leg
            [leg_cache.setdefault((a, b), leg_passages(a, b)) for a, b in zip(ports_[:-1], ports_[1:])])
    later, current = any("suez" in x for x in legs[k + 1:]), "suez" in legs[min(k, len(legs) - 1)]
    ahead = eta.suez_ahead(vid, s["distance_covered_nm"])
    fleet_suez["ahead"] += ahead
    if (later and not ahead) or (not later and not current and ahead):
        fleet_suez["bound_violations"].append(vid)
    fleet_suez["decided_by_box"] += current and not later
routes_through = sum(eta.suez_ahead(v, 0.0) for v in all_ids)
print({"routes": len(all_ids), "through_suez": routes_through, "start_mismatch": start_mismatch,
       "end_true": end_true, "fleet_suez": fleet_suez})

assert kept_mismatch == 0 and start_mismatch == [] and end_true == 0 and fleet_suez["bound_violations"] == []
# 10 nm < the marine model's grid (≈ 0.25°, 15 nm): a point this close reads the same weather cell or its neighbour
assert max(pos_err) <= 10.0, "a next-leg point more than 10 nm from the vessel's true position"
# reviewed 2026-10-28: 810 points for 219 vessels; at h = 0 the error is Phase 9's (≤ 1.75 nm), it grows with the
# 6 h mean SOG's noise to 7.1 nm at +72 h; 40 of the 219 still have the canal ahead (55 decided inside a leg)
reviewed_2 = {"vessels": 219, "points": 810, "routes_through_suez": 173, "fleet_suez_ahead": 40,
              "decided_by_box": 55, "max_pos_err_nm": 7.1}
actual_2 = {"vessels": len(at_sea), "points": n_points, "routes_through_suez": routes_through,
            "fleet_suez_ahead": fleet_suez["ahead"], "decided_by_box": fleet_suez["decided_by_box"],
            "max_pos_err_nm": round(max(pos_err), 1)}
print("Phase 2 snapshot:", actual_2)
assert not reviewed_2 or actual_2 == reviewed_2, (actual_2, reviewed_2)
print("✅ Phase 2 validation passed.")

# %% Phase 3 — Alert rules on planted weather and traffic events (S3)
# A fake Open-Meteo (httpx.MockTransport, a throw-away cache) answers every requested point from a planted storm
# field: calm (1.5 m, 15 kn) except discs of 40 nm on one UTC day, each centred on the TRUE position (Phase 2's
# generator timeline) of a chosen vessel at +0 / 24 / 48 / 72 h — waves 5.0 m (moderate) / 7.0 m (high), wind 40 kn
# (moderate) / 52 kn (high), near-threshold 3.9 m + 33.9 kn (no alert), null (a coast: unknown, no alert). The truth
# for every vessel = the worst disc its true positions fall in (any vessel, planted or passing by). A fake PortWatch
# answers −30 % (moderate), −45 % (high), −10 % (none) or fails; the truth = "suez" in searoute's passages from the
# vessel's true position to its next port, or on a later leg. Precision / recall targets (§6c P11-9, fixed before):
# ≥ 0.95 each. The same inputs twice → identical alerts (reproducible).
import re  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402
from collections import Counter  # noqa: E402
from datetime import date, timedelta  # noqa: E402

import httpx  # noqa: E402

from pipelines.agents.graphs import voyage_watch as vw  # noqa: E402
from pipelines.agents.tools import external, weather  # noqa: E402
import time  # noqa: E402

DISC_NM = 40.0
PACE = (vw.LOCATIONS_PER_MIN, vw.RETRY_WAIT_S)
vw.LOCATIONS_PER_MIN, vw.RETRY_WAIT_S = None, 0      # the mocks answer at once: no pacing, no retry wait (D-P11-2)
CALM = {"wave": 1.5, "wind": 15.0}
TYPES = [("wave_moderate", 5.0, 15.0, "moderate"), ("wave_high", 7.0, 15.0, "high"),
         ("wind_moderate", 1.5, 40.0, "moderate"), ("wind_high", 1.5, 52.0, "high"),
         ("near_threshold", 3.9, 33.9, None), ("null", None, None, None)]
true_pts = {}                                    # vid → [(h, lat, lon, date)] kept by the truth (h ≤ true arrival)
for vid in at_sea:
    left = (truth[vid] - asof_ts).total_seconds() / 3600
    r = voyages.route_of(vid)
    true_pts[vid] = []
    for h in eta.LEG_HOURS:
        if h and h > left:
            break
        la, lo = routes.point_at(r, true_along(vid, asof_ts + pd.Timedelta(hours=h)))
        true_pts[vid].append((h, float(la[0]), float(lo[0]), (asof_ts + pd.Timedelta(hours=h)).date().isoformat()))
discs = []
for i, vid in enumerate(at_sea[::7]):
    kind, wave, wind, sev = TYPES[i % len(TYPES)]
    h, la, lo, d = true_pts[vid][min(i % 4, len(true_pts[vid]) - 1)]
    discs.append({"vid": vid, "type": kind, "lat": la, "lon": lo, "date": d, "wave": wave, "wind": wind, "sev": sev})


def field(lat: float, lon: float, d: str) -> dict:
    """The planted weather at a point: the worst disc that covers it on its day, else calm."""
    hit = [x for x in discs if x["date"] == d
           and float(routes.gc_nm(np.array(lat), np.array(lon), np.array(x["lat"]), np.array(x["lon"]))) <= DISC_NM]
    if not hit:
        return CALM
    if any(x["type"] == "null" for x in hit):
        return {"wave": None, "wind": None}
    return {"wave": max(x["wave"] for x in hit), "wind": max(x["wind"] for x in hit)}


mock = {"portwatch": "ok", "change": -0.30, "requests": 0}


def fake_http(req: httpx.Request) -> httpx.Response:
    mock["requests"] += 1
    p = req.url.params
    if "arcgis" in req.url.host:
        if mock["portwatch"] == "down":
            return httpx.Response(500, text="down")
        start = date.fromisoformat(re.search(r"date >= DATE '([\d-]+)'", p["where"]).group(1))
        n = 40 if start.year == 2025 else round(40 * (1 + mock["change"]))
        return httpx.Response(200, json={"features": [{"attributes": {
            "date": (start + timedelta(days=k)).isoformat(), "n_total": n, "n_container": 10, "n_tanker": 8,
            "n_dry_bulk": 6, "n_general_cargo": 3, "n_roro": 1, "capacity": 1_000_000}} for k in range(28)]})
    lats, lons = [float(x) for x in p["latitude"].split(",")], [float(x) for x in p["longitude"].split(",")]
    d0, d1 = date.fromisoformat(p["start_date"]), date.fromisoformat(p["end_date"])
    days = [(d0 + timedelta(days=k)).isoformat() for k in range((d1 - d0).days + 1)]
    body = []
    for la, lo in zip(lats, lons):
        f = [field(la, lo, d) for d in days]
        if "marine" in req.url.host:
            daily = {"wave_height_max": [x["wave"] for x in f], "swell_wave_height_max": [x["wave"] for x in f],
                     "wind_wave_height_max": [x["wave"] for x in f]}
        else:
            daily = {"wind_speed_10m_max": [x["wind"] for x in f], "wind_gusts_10m_max": [x["wind"] for x in f]}
        body.append({"daily": {"time": days, **daily}})
    return httpx.Response(200, json=body)


tmp_dirs: list[Path] = []


def fresh_caches() -> None:
    d = Path(tempfile.mkdtemp(prefix="voyage_watch_cache_"))
    tmp_dirs.append(d)
    for name in ("marine_weather", "suez_transits"):
        external._caches[name] = external.ExternalCache(name, d)


def true_weather(vid: int) -> str | None:
    worst = None
    for _, la, lo, d in true_pts[vid]:
        f = field(la, lo, d)
        s = vw._severity_weather(f["wave"], f["wind"])
        if s and (worst is None or vw.SEVERITY[s] > vw.SEVERITY[worst]):
            worst = s
    return worst


def true_suez_ahead(vid: int) -> bool:
    s, r = fleet_status[vid], voyages.route_of(vid)
    k = int(np.searchsorted(r["port_cum"], s["distance_covered_nm"], side="right") - 1)
    ports_ = r["ports"]
    if voy.at[vid, "route_fallback"]:
        return False
    if any("suez" in leg_cache[(a, b)] for a, b in zip(ports_[k + 1:-1], ports_[k + 2:])):
        return True
    _, la, lo, _ = true_pts[vid][0]
    nxt = routes.ports()[ports_[min(k + 1, len(ports_) - 1)]]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        f = searoute.searoute([lo, la], [nxt[1], nxt[0]], units="naut", return_passages=True)
    return "suez" in (f["properties"].get("traversed_passages") or [])


def score(pred: dict, expected: dict) -> dict:
    tp = sum(1 for v in pred if v in expected)
    out = {"alerts": len(pred), "expected": len(expected), "tp": tp,
           "precision": round(tp / len(pred), 4) if pred else 1.0,
           "recall": round(tp / len(expected), 4) if expected else 1.0,
           "severity_agree": sum(pred[v] == expected[v] for v in pred if v in expected),
           "false_alarms": sorted(v for v in pred if v not in expected),
           "missed": sorted(v for v in expected if v not in pred)}
    return out


real_http, real_today = external.HTTP, external.TODAY
try:
    external.HTTP = httpx.Client(transport=httpx.MockTransport(fake_http), timeout=external.TIMEOUT_S)
    external.TODAY = date(2026, 10, 27)
    fresh_caches()
    names = {r["vessel_id"]: r["vessel_name"] for r in db.fetch("SELECT vessel_id, vessel_name FROM vessels")}
    er = vw.etas(ops_user, [fleet_status[v] | {"vessel_name": names[v]} for v in at_sea])
    wx, wsum = vw.weather_at(ops_user, er)
    tev = vw.traffic(ops_user, context.DATA_AS_OF)
    al = vw.alerts(er, wx, tev)
    fresh_caches()
    wx2, _ = vw.weather_at(ops_user, er)
    al2 = vw.alerts(er, wx2, vw.traffic(ops_user, context.DATA_AS_OF))
    reproducible = al == al2
    exp_w = {v: s for v in at_sea if (s := true_weather(v))}
    pred_w = {a["vessel_id"]: a["severity"] for a in al if a["kind"] == "weather"}
    weather_score = score(pred_w, exp_w)
    suez_truth = {v for v in at_sea if true_suez_ahead(v)}
    traffic_scores, mode_ev = {}, {}
    for label, change, status in (("-30%", -0.30, "ok"), ("-45%", -0.45, "ok"), ("-10%", -0.10, "ok"),
                                  ("down", -0.30, "down")):
        mock["change"], mock["portwatch"] = change, status
        fresh_caches()
        t_ev = vw.traffic(ops_user, context.DATA_AS_OF)
        a_t = vw.alerts(er, wx, t_ev)
        pred_t = {a["vessel_id"]: a["severity"] for a in a_t if a["kind"] == "suez_traffic"}
        sev = "high" if change <= -0.40 else "moderate"
        exp_t = {v: sev for v in suez_truth} if status == "ok" and change <= -0.20 else {}
        traffic_scores[label] = score(pred_t, exp_t) | {"traffic": "watch.traffic" in t_ev}
        mode_ev[label] = (t_ev, a_t)
    # sensitivity (reported, not a gate): storms smaller than the next-leg points' error (≤ 7.1 nm, Phase 2) — the
    # 40 nm discs above test the rules, these show where the dead reckoning starts to miss
    sensitivity = {}
    for radius in (10.0, 5.0):
        DISC_NM = radius
        fresh_caches()
        wx_s, _ = vw.weather_at(ops_user, er)
        pred_s = {a["vessel_id"]: a["severity"] for a in vw.alerts(er, wx_s, {}) if a["kind"] == "weather"}
        exp_s = {v: s for v in at_sea if (s := true_weather(v))}
        sensitivity[f"{radius:g} nm"] = {k: v for k, v in score(pred_s, exp_s).items()
                                         if k in ("alerts", "expected", "precision", "recall")}
    DISC_NM = 40.0
    # D-P11-2: Open-Meteo refuses (429) past 600 locations / min. (a) the first 6 requests refused → the failed
    # batches come back on the retry, nothing lost; (b) pacing on a fake clock: no 60 s window sends more than the
    # budget, and the same 810 points from the cache wait for nothing.
    import types  # noqa: E402

    flaky = {"left": 6}

    def flaky_http(req):
        if "open-meteo" in req.url.host and flaky["left"] > 0:
            flaky["left"] -= 1
            return httpx.Response(429, text="Too many requests")
        return fake_http(req)
    external.HTTP = httpx.Client(transport=httpx.MockTransport(flaky_http), timeout=external.TIMEOUT_S)
    fresh_caches()
    wx_f, wsum_f = vw.weather_at(ops_user, er)
    retry_ok = (wsum_f["weather_failed_points"], wsum_f["weather_retried_points"] > 0, wx_f == wx)
    external.HTTP = httpx.Client(transport=httpx.MockTransport(fake_http), timeout=external.TIMEOUT_S)
    clock, sends, sleeps = {"t": 0.0}, [], []
    vw.time = types.SimpleNamespace(monotonic=lambda: clock["t"],
                                    sleep=lambda s: (sleeps.append(s), clock.update(t=clock["t"] + s)))
    real_call = weather._call

    def timed_call(url, variables, lats, *a, **k):
        before = weather.SENT["locations"]
        out_ = real_call(url, variables, lats, *a, **k)
        if weather.SENT["locations"] > before:
            sends.append((clock["t"], len(lats)))
        clock["t"] += 0.3                                   # a network answer takes time
        return out_
    try:
        weather._call = timed_call
        vw.LOCATIONS_PER_MIN = 400
        fresh_caches()
        vw.weather_at(ops_user, er)
        peak = max(sum(n for t, n in sends if t0 <= t < t0 + 60) for t0, _ in sends)
        paced_min = round(clock["t"] / 60, 1)
        sleeps.clear()
        vw.weather_at(ops_user, er)                         # the same points again: all from the cache
        cached_sleeps = len(sleeps)
    finally:
        weather._call, vw.time, vw.LOCATIONS_PER_MIN = real_call, time, None
    pacing = {"peak_locations_per_60s": peak, "fake_minutes": paced_min, "cached_sleeps": cached_sleeps}
finally:
    external.HTTP, external.TODAY = real_http, real_today
    for name in ("marine_weather", "suez_transits"):
        external._caches.pop(name, None)
    for d in tmp_dirs:
        shutil.rmtree(d, ignore_errors=True)
print({"discs": len(discs), "by_type": dict(Counter(x["type"] for x in discs)), "weather_points": wsum,
       "reproducible": reproducible})
print({"weather": weather_score, "sensitivity": sensitivity})
print({"traffic": {k: {x: v[x] for x in ("alerts", "expected", "precision", "recall", "false_alarms", "missed")}
                   for k, v in traffic_scores.items()}})

all_scores = [weather_score] + [s for s in traffic_scores.values() if s["expected"]]
assert reproducible, "the same inputs gave different alerts"
assert all(s["precision"] >= 0.95 and s["recall"] >= 0.95 for s in all_scores), all_scores
assert weather_score["severity_agree"] == weather_score["tp"], "a severity differs from the planted one"
assert traffic_scores["-10%"]["alerts"] == 0 and traffic_scores["down"]["alerts"] == 0
assert not traffic_scores["down"]["traffic"] and wsum["weather_unknown_points"] > 0
print({"retry": retry_ok, "pacing": pacing})
assert retry_ok == (0, True, True), retry_ok                     # D-P11-2: refused batches recovered, same weather
assert pacing["peak_locations_per_60s"] <= 400 and pacing["cached_sleeps"] == 0, pacing
# reviewed 2026-10-28: 32 discs (22 that should alert → 27 vessels incl. passers-by); weather and traffic
# precision = recall = 1.0, severities agree; 6 null points unknown; 5 nm discs (< the 7.1 nm dead-reckoning
# error) miss 1 of 22 — the limit, reported
reviewed_3 = {"discs": 32, "weather": {"alerts": 27, "expected": 27, "tp": 27, "precision": 1.0, "recall": 1.0},
              "traffic": {"-30%": (40, 1.0, 1.0), "-45%": (40, 1.0, 1.0), "-10%": (0, 1.0, 1.0),
                          "down": (0, 1.0, 1.0)}, "unknown_points": 6,
              "sensitivity_5nm_recall": 0.9545}
actual_3 = {"discs": len(discs), "weather": {k: weather_score[k] for k in ("alerts", "expected", "tp", "precision",
                                                                         "recall")},
            "traffic": {k: (v["alerts"], v["precision"], v["recall"]) for k, v in traffic_scores.items()},
            "unknown_points": wsum["weather_unknown_points"],
            "sensitivity_5nm_recall": sensitivity["5 nm"]["recall"]}
print("Phase 3 snapshot:", actual_3)
assert not reviewed_3 or actual_3 == reviewed_3, (actual_3, reviewed_3)
print("✅ Phase 3 validation passed.")

# %% Phase 4 — The brief's slots and Validator (S3)
# A clean brief is built by code from the evidence (the same function answers for the fake model in Phase 5): every
# high alert cited, numbers as slots, dates copied from the alerts. Then planted errors, each in its own copy: a typed
# number (headline / item / percent), a shifted date or ETA, a slot on an alert the item does not cite, an invented
# alert id, a high alert left out, a slot on another evidence id (route.*, watch.transits), an unknown field, a wrong
# format. Every one must be caught; the clean briefs of three evidence sets must pass (false alarms 0), and the
# slot-form normaliser must not touch them. The new kinds: metres and hours render and read back.
import copy  # noqa: E402

from pipelines.agents.deck import slots  # noqa: E402


def evidence_of(t_ev: dict, al_: list[dict]) -> dict:
    counts = dict(Counter(fleet_status[v]["status_at_as_of"] for v in at_sea))
    return t_ev | {"watch.alerts": vw._result("watch_alerts", al_, "check"),
                   "watch.fleet": vw._result("watch_fleet", [vw.fleet_row(context.DATA_AS_OF, counts, er, al_, wsum,
                                                                          t_ev)], "check")}


def _say(a: dict) -> str:
    aid = a["alert_id"]
    if a["kind"] == "suez_traffic":
        return (f"Suez Canal transits are {{watch.alerts[{aid}]:change_transits_pct|%1}} against a year earlier, "
                f"with the canal still ahead of {a['vessel_name']} (to {a['destination']}, ETA {a['eta_utc']})")
    what = (f"waves of {{watch.alerts[{aid}]:wave_height_max_m}}" if (a.get("wave_height_max_m") or 0) >= vw.WAVE_MODERATE_M
            else f"wind of {{watch.alerts[{aid}]:wind_speed_10m_max_kn}}")
    return f"{a['vessel_name']} (to {a['destination']}, ETA {a['eta_utc']}) meets {what} on {a['date']}"


def good_brief(ev: dict) -> dict:
    """A clean WatchBrief: the Suez traffic alerts in one item (a fleet-wide event, D-P11-1), the weather alerts high
    first in groups of up to 8 (first alert spoken, the rest named); at most 6 items."""
    al_ = vw._rows(ev["watch.alerts"])
    order = [a for a in al_ if a["severity"] == "high"] + [a for a in al_ if a["severity"] != "high"]
    suez = [a for a in order if a["kind"] == "suez_traffic"]
    wx_ = [a for a in order if a["kind"] == "weather"]
    groups = ([suez] if suez else []) + [wx_[i:i + 8] for i in range(0, len(wx_), 8)]
    groups = sorted(groups, key=lambda g_: -max(vw.SEVERITY[a["severity"]] for a in g_))[:6]
    items = []
    for g_ in groups:
        others = ", ".join(a["vessel_name"] for a in g_[1:3])            # at most three vessels named (the skill)
        rest = (f" and the other vessels of {{watch.fleet:{g_[0]['kind'] + '_alerts'}}} {g_[0]['kind']} alerts"
                if len(g_) > 3 else "")
        items.append({"text": _say(g_[0]) + (f"; also {others}{rest}" if others else "") + ".",
                      "alert_ids": [a["alert_id"] for a in g_]})
    head = order[0]["alert_id"]
    return {"headline": f"{{watch.fleet:alerts_total}} alerts on the next legs, {{watch.fleet:alerts_high}} high; the "
                        f"first is about {order[0]['vessel_name']} ({head}).", "items": items}


sets = {"weather + Suez −30 %": evidence_of(*mode_ev["-30%"]), "weather + Suez −45 %": evidence_of(*mode_ev["-45%"]),
        "weather only": evidence_of(*mode_ev["-10%"])}
clean = {k: good_brief(ev) for k, ev in sets.items()}
false_alarms = {k: vw.validate(b, sets[k]) for k, b in clean.items()}
norm_fixes = {k: vw.normalize_brief(b, sets[k])[1] for k, b in clean.items()}
ev4 = sets["weather + Suez −30 %"]
b0 = clean["weather + Suez −30 %"]
highs = [a for a in vw._rows(ev4["watch.alerts"]) if a["severity"] == "high"]
mods = [a for a in vw._rows(ev4["watch.alerts"]) if a["severity"] == "moderate"]


def mutate(fn):
    b = copy.deepcopy(b0)
    fn(b)
    return b


def _shift_day(text: str, iso: str) -> str:
    return text.replace(iso, (date.fromisoformat(iso[:10]) + timedelta(days=1)).isoformat() + iso[10:], 1)


plants = []
for i in range(min(5, len(b0["items"]))):
    it = b0["items"][i]
    first = next(a for a in vw._rows(ev4["watch.alerts"]) if a["alert_id"] == it["alert_ids"][0])
    stranger = next(a for a in vw._rows(ev4["watch.alerts"]) if a["alert_id"] not in it["alert_ids"])
    plants += [
        (f"typed number in item {i}", lambda b, i=i: b["items"][i].update(text=b["items"][i]["text"] + " About 7.0 m.")),
        (f"typed percent in item {i}", lambda b, i=i: b["items"][i].update(text=b["items"][i]["text"] + " Down 30 %.")),
        (f"shifted ETA in item {i}", lambda b, i=i, f=first: b["items"][i].update(
            text=_shift_day(b["items"][i]["text"], f["eta_utc"]))),
        (f"slot on an uncited alert in item {i}", lambda b, i=i, s=stranger: b["items"][i].update(
            text=b["items"][i]["text"] + f" ETA in {{watch.alerts[{s['alert_id']}]:eta_in_h}}.")),
        (f"invented alert id in item {i}", lambda b, i=i: b["items"][i]["alert_ids"].append("9999/weather")),
        (f"slot on route evidence in item {i}", lambda b, i=i: b["items"][i].update(
            text=b["items"][i]["text"] + " Costs {route.compare[suez]:total_sdr|M}.")),
        (f"slot on watch.transits in item {i}", lambda b, i=i: b["items"][i].update(
            text=b["items"][i]["text"] + " Mean {watch.transits:mean_daily_transits}.")),
        (f"unknown field in item {i}", lambda b, i=i, f=first: b["items"][i].update(
            text=b["items"][i]["text"] + f" Swell {{watch.alerts[{f['alert_id']}]:swell_m}}.")),
        (f"wrong format in item {i}", lambda b, i=i, f=first: b["items"][i].update(
            text=b["items"][i]["text"] + f" ETA in {{watch.alerts[{f['alert_id']}]:eta_in_h|M}}.")),
    ]
plants += [("typed number in headline", lambda b: b.update(headline="27 alerts on the next legs.")),
           ("a high alert left out", lambda b: [it["alert_ids"].remove(highs[-1]["alert_id"]) for it in b["items"]
                                               if highs[-1]["alert_id"] in it["alert_ids"]]),
           ("all high alerts left out", lambda b: b.update(items=[it for it in b["items"]
                                                                  if not set(it["alert_ids"]) & {h["alert_id"]
                                                                                                 for h in highs}]
                                                           or [{"text": "Nothing to report.",
                                                                "alert_ids": [mods[0]["alert_id"]]}])),
           ("a date of another day in headline", lambda b: b.update(headline=b["headline"] + " Since 2026-09-01."))]
caught = {name: bool(vw.validate(mutate(fn), ev4)) for name, fn in plants}
missed_plants = [n for n, c in caught.items() if not c]
kinds = {"height": slots.format_value("wave_height_max_m", 5.04), "hours": slots.format_value("eta_in_h", 41.25),
         "change pct": slots.format_value("change_transits_pct", -30.0, "%1")}
print({"clean_problems": {k: len(v) for k, v in false_alarms.items()}, "norm_fixes": {k: len(v) for k, v in
                                                                                     norm_fixes.items()},
       "plants": len(plants), "caught": sum(caught.values()), "missed": missed_plants, "kinds": kinds,
       "highs": len(highs), "items": len(b0["items"])})
assert all(not v for v in false_alarms.values()), false_alarms
assert all(not v for v in norm_fixes.values()), norm_fixes
assert len(plants) >= 40 and not missed_plants, missed_plants
assert kinds == {"height": "5.0 m", "hours": "41.3 h", "change pct": "−30.0 %"}, kinds
assert slots.field_kind("wave_height_max", 3.0) == "number" and slots.field_kind("vessel_id", 3) == "count"
print("✅ Phase 4 validation passed.")

# %% Phase 4s — The skill voyage-watch-brief (S3)
# The brief's skill parses within the budgets, names only fields, evidence ids, formats and values the watch evidence
# really has, states its rules (every high alert cited, dates copied, numbers as slots) and its example slots use
# real fields with allowed formats. The owner's review is reported (reviewed_by_owner), not assumed.
from pipelines.agents import skill_loader  # noqa: E402
from pipelines.agents.graphs import models as gm  # noqa: E402

sk = skill_loader.catalog()["voyage-watch-brief"]
fields = {k: v for res in ev4.values() for r in res["rows"] for k, v in r.items()}
known = (set(fields) | {e for e in ev4} | {"high", "moderate", "weather", "suez_traffic", "vessel_id/kind"}
         | set(gm.WatchBrief.model_fields) | set(gm.WatchItem.model_fields)
         | {f for fs in slots.FORMATS.values() for f in fs})
named = sorted(set(re.findall(r"`([A-Za-z0-9_./\[\]]+)`", sk.body)))
unknown_named = [n for n in named if n not in known and not re.fullmatch(r"watch\.alerts\[\d+/\w+\]|\d+/\w+", n)]
example_slots = slots.find_slots(sk.body)
bad_examples = [s.raw for s in example_slots if s.field not in fields or (
    s.fmt and s.fmt not in slots.FORMATS[slots.field_kind(s.field, fields[s.field])])]
flat = " ".join(sk.body.split())
rules = all(x in flat for x in ("Every high alert must be in some item's `alert_ids`", "dates only",
                                "Every number is a slot", "never \"calm\""))
actual_4s = {"stage": sk.stage, "within_budget": len(sk.description) <= skill_loader.DESCRIPTION_MAX
             and sk.body_tokens <= skill_loader.BODY_MAX_TOKENS, "unknown_names": unknown_named,
             "example_slots": len(example_slots), "bad_examples": bad_examples, "rules_stated": rules}
print(f"Phase 4s: skill voyage-watch-brief ({len(sk.description)} chars, {sk.body_tokens} tokens), "
      f"{len(named)} names, reviewed by the owner: {sk.reviewed_by_owner}", actual_4s)
assert actual_4s == {"stage": "2", "within_budget": True, "unknown_names": [], "example_slots": len(example_slots),
                     "bad_examples": [], "rules_stated": True}, actual_4s
print("✅ Phase 4s validation passed.")

# %% Phase 5 — The graph end to end on fake models, with the PostgreSQL checkpointer (S4)
# The whole graph on FakeRoles (the real parser, no quota), the real PostgresSaver (agent_state, login ports_agent),
# the fake Open-Meteo / PortWatch of Phase 3 and a throw-away reports folder, over a subset of the fleet (40 at sea +
# 5 at anchor + 3 in port — the fleet node is the same code for 500): alerts → one model call and a brief; no alert →
# no call; the patch path; a twice-bad brief (validation_failed) and an invalid reply (output_invalid) keep every
# alert; PortWatch down and Open-Meteo down → ok, said in the assumptions; only moored vessels → no_data; a crash in
# the brief → the run file already holds the alerts, the resume repeats no tool call. The run file = the final state.
# Every check thread is deleted at the end.
from langchain_core.messages import BaseMessage  # noqa: E402

from pipelines.agents import checkpointer, roles  # noqa: E402
from pipelines.agents.graphs import models as wm  # noqa: E402


def fake_brief(messages: list[BaseMessage]) -> dict:
    """The clean brief of Phase 4, rebuilt from what the model reads (the digest's alert lines)."""
    text = "\n".join(str(x.content) for x in messages)
    rows = [json.loads(x) for x in re.findall(r"^\[watch\.alerts\] (\{.*\})$", text, flags=re.M)]
    rows = [r | {"kind": r["alert_id"].split("/")[1]} for r in rows]
    return good_brief({"watch.alerts": {"rows": rows}})


script_mode = {"m": "good", "calls": 0}


def script(role, messages, tools, schema):
    script_mode["calls"] += 1
    m_ = script_mode["m"]
    patching = any("Code checked your WatchBrief" in str(x.content) for x in messages)
    if m_ == "crash":
        script_mode["m"] = "good"
        raise RuntimeError("simulated crash in the brief")
    if m_ == "invalid":
        return {"headline": "", "items": []}                          # not a WatchBrief
    b = fake_brief(messages)
    if m_ == "always_bad" or (m_ == "patch" and not patching):
        b["headline"] += " About 27 alerts."                          # a typed number
    return b


status_calls = {"n": 0}
real_status = voyages.voyage_status


def counted_status(*a, **k):
    status_calls["n"] += 1
    return real_status(*a, **k)


anchored_ids = sorted(int(i) for i in voy.index[voy["status"] == "Anchored"])[:5]
port_ids = sorted(int(i) for i in voy.index[voy["status"] == "At Port"])[:3]
planted = [d["vid"] for d in discs]
subset = sorted(set(at_sea[:28] + planted[:12])) + anchored_ids + port_ids
quiet = [v for v in at_sea if v not in {d["vid"] for d in discs} and not true_weather(v)
         and not true_suez_ahead(v)][:6]
tmp_reports = Path(tempfile.mkdtemp(prefix="voyage_watch_reports_"))
saver = checkpointer.saver()
threads5: list[str] = []
CHECK_PREFIX = "voyage_watch_check:"


def run(vessel_ids, mode="good", thread=None, resume=False):
    script_mode["m"] = mode
    tid = thread or vw.new_thread_id(checkpointer.pool(), context.DATA_AS_OF, CHECK_PREFIX)
    if tid not in threads5:
        threads5.append(tid)
    cfg = {"configurable": {"thread_id": tid}}
    g5.invoke(None if resume else {"request": {"vessel_ids": vessel_ids}}, cfg,
              context=context.RunContext(ops_user), durability="sync")
    return tid, g5.get_state(cfg).values


out5 = {}
try:
    external.HTTP = httpx.Client(transport=httpx.MockTransport(fake_http), timeout=external.TIMEOUT_S)
    external.TODAY = date(2026, 10, 27)
    voyages.voyage_status = counted_status
    fake = roles.FakeRoles(script)
    g5 = vw.build_graph(fake, saver, tmp_reports)
    mock["change"], mock["portwatch"] = -0.30, "ok"

    def case(name, ids, mode="good", **mock_set):
        mock.update(mock_set)
        fresh_caches()
        before = script_mode["calls"]
        tid, st = run(ids, mode)
        r = st["result"]
        out5[name] = {"status": r["status"], "brief": r["brief_status"], "calls": script_mode["calls"] - before,
                      "alerts": len(r["alerts"]), "tid": tid, "result": r}
        return r

    r_ok = case("ok", subset)
    file_ok = json.loads(Path(r_ok["run_file"]).read_text(encoding="utf-8"))
    file_is_state = {k: v for k, v in file_ok.items() if k != "thread_id"} == r_ok
    r_quiet = case("no_alerts", quiet, change=-0.10)
    r_patch = case("patch", subset, "patch", change=-0.30)
    r_bad = case("validation_failed", subset, "always_bad")
    r_inv = case("output_invalid", subset, "invalid")
    r_pw = case("portwatch_down", subset, portwatch="down")
    mock["portwatch"] = "ok"
    r_moored = case("no_data", port_ids)

    # Open-Meteo down: every marine request answers 500
    def down_http(req):
        return httpx.Response(500, text="down") if "open-meteo" in req.url.host else fake_http(req)
    external.HTTP = httpx.Client(transport=httpx.MockTransport(down_http), timeout=external.TIMEOUT_S)
    r_wx = case("open_meteo_down", subset)
    external.HTTP = httpx.Client(transport=httpx.MockTransport(fake_http), timeout=external.TIMEOUT_S)

    # crash in the brief → the run file is there with the alerts; resume: no fleet / weather / traffic call again
    fresh_caches()
    script_mode["m"] = "crash"
    tid_c = vw.new_thread_id(checkpointer.pool(), context.DATA_AS_OF, CHECK_PREFIX)
    threads5.append(tid_c)
    crashed = False
    try:
        g5.invoke({"request": {"vessel_ids": subset}}, {"configurable": {"thread_id": tid_c}},
                  context=context.RunContext(ops_user), durability="sync")
    except RuntimeError:
        crashed = True
    snap = g5.get_state({"configurable": {"thread_id": tid_c}})
    file_c = json.loads(vw.run_file_path(tmp_reports, tid_c).read_text(encoding="utf-8"))
    alerts_saved = len(file_c["alerts"]) == out5["ok"]["alerts"] and file_c["brief_status"] is None
    n_status, n_http = status_calls["n"], mock["requests"]
    _, st_c = run(subset, "good", thread=tid_c, resume=True)
    resumed = {"next_before": list(snap.next), "status_calls": status_calls["n"] - n_status,
               "http": mock["requests"] - n_http, "brief": st_c["result"]["brief_status"]}
finally:
    voyages.voyage_status = real_status
    external.HTTP, external.TODAY = real_http, real_today
    for name in ("marine_weather", "suez_transits"):
        external._caches.pop(name, None)
    for d in tmp_dirs:
        shutil.rmtree(d, ignore_errors=True)
    for t in threads5:
        saver.delete_thread(t)
    shutil.rmtree(tmp_reports, ignore_errors=True)
left = len([t for t in threads5 if g5.get_state({"configurable": {"thread_id": t}}).values])
summary5 = {k: (v["status"], v["brief"], v["calls"], v["alerts"]) for k, v in out5.items()}
print({"cases": summary5, "file_is_state": file_is_state, "crashed": crashed, "alerts_saved": alerts_saved,
       "resumed": resumed, "threads_left": left, "tid": out5["ok"]["tid"]})

assert summary5["ok"][:3] == ("ok", "ok", 1) and summary5["ok"][3] > 0 and r_ok["headline"] and r_ok["items"]
assert not any("{watch" in x["text"] for x in r_ok["items"]) and file_is_state
assert summary5["no_alerts"] == ("ok", "no_alerts", 0, 0)
assert summary5["patch"][:3] == ("ok", "ok", 2)
assert summary5["validation_failed"][:3] == ("ok", "validation_failed", 2) and r_bad["headline"] is None
assert summary5["output_invalid"][:3] == ("ok", "output_invalid", 1)
assert summary5["validation_failed"][3] == summary5["output_invalid"][3] == summary5["ok"][3], "an alert was lost"
assert not any(a["kind"] == "suez_traffic" for a in r_pw["alerts"]) and any(
    "Suez traffic context unavailable" in x for x in r_pw["assumptions"])
assert summary5["no_data"][:2] == ("no_data", None)
assert not any(a["kind"] == "weather" for a in r_wx["alerts"]) and r_wx["fleet"]["weather_failed_points"] > 0 \
    and any("without a value" in x for x in r_wx["assumptions"])
assert crashed and alerts_saved and resumed == {"next_before": ["brief"], "status_calls": 0, "http": 0, "brief": "ok"}
assert re.fullmatch(r"voyage_watch_check:20260913T0000Z:\d+", out5["ok"]["tid"]) and left == 0
assert wm.VoyageWatchResult.model_validate(r_ok)
print("✅ Phase 5 validation passed.")

# %% Phase 6 — The real model once, on the live (cached) weather and traffic (S5)
# The whole fleet at the data's as-of instant, real Open-Meteo (Historical Forecast for these past days) and
# PortWatch through the tools' cache (settled windows kept for good), the real `writer` role (ADR-045, llm.py cache:
# a re-run makes no call). The live alerts have no truth (real weather): their counts are reported; the brief must
# pass the Validator — a failure is reported as is (the alerts stand either way). A check thread, deleted after.
vw.LOCATIONS_PER_MIN, vw.RETRY_WAIT_S = PACE           # the real services: paced (cached here: nothing to wait for)
tmp_reports6 = Path(tempfile.mkdtemp(prefix="voyage_watch_real_"))
g6 = vw.build_graph(roles.Roles(), saver, tmp_reports6)
tid6 = vw.new_thread_id(checkpointer.pool(), context.DATA_AS_OF, CHECK_PREFIX)
try:
    g6.invoke({"request": {}}, {"configurable": {"thread_id": tid6}}, context=context.RunContext(ops_user),
              durability="sync")
    st6 = g6.get_state({"configurable": {"thread_id": tid6}}).values
finally:
    saver.delete_thread(tid6)
    shutil.rmtree(tmp_reports6, ignore_errors=True)
r6 = st6["result"]
usage6 = st6.get("llm_usage") or []
f6 = r6["fleet"]
real6 = {"status": r6["status"], "brief": r6["brief_status"], "watched": f6["vessels_watched"],
         "alerts": f6["alerts_total"], "high": f6["alerts_high"], "weather_alerts": f6["weather_alerts"],
         "suez_alerts": f6["suez_traffic_alerts"], "change_transits_pct": f6["change_transits_pct"],
         "weather_points": f6["weather_points"], "unknown_points": f6["weather_unknown_points"],
         "model_calls": len(usage6), "cached": sum(bool(c.get("cached")) for c in usage6),
         "models": sorted({c.get("model") for c in usage6}), "problems": r6["problems"][:3]}
print({"real": real6})
print({"headline": r6.get("headline"), "items": [i["text"] for i in r6.get("items") or []][:3]})
assert r6["status"] == "ok" and f6["vessels_watched"] == 297 and f6["in_transit"] == 219
assert r6["brief_status"] in ("ok", "no_alerts", "validation_failed", "output_invalid")
brief_real_ok = r6["brief_status"] in ("ok", "no_alerts")
# reviewed 2026-10-28 (live answers now cached for good: settled windows): 297 watched, 12 weather alerts (3 high),
# 5 of 810 points unknown, PortWatch +2.7 % (no traffic alert); the real brief passed the Validator on its first
# reply. The first live run had 213 points unknown (Open-Meteo batches failed: never cached) and 7 alerts — the
# designed degradation; the counts below are the complete answer.
reviewed_6 = {"status": "ok", "brief": "ok", "watched": 297, "alerts": 12, "high": 3, "weather_alerts": 12,
              "suez_alerts": 0, "change_transits_pct": 2.7, "weather_points": 810, "unknown_points": 5}
assert {k: real6[k] for k in reviewed_6} == reviewed_6, real6
print("✅ Phase 6 validation passed." + ("" if brief_real_ok else f" (brief: {r6['brief_status']} — reported)"))

# %% Phase 7 — RBAC, contract, the replay planner, retention, the alert reader (S5)
# Every employee (100) may read the watch (all inputs level 1, ADR-006); a probe user below every ceiling → the graph
# says not_permitted before any tool reads (no voyage_status call, no model call) and the reader refuses it. No user,
# clock or dataset in a model-facing schema; the ETA tool without a run context is refused, with one it equals rule
# R. The planner: start at the first replay instant, the next one, resume a stalled run first, a run by hand counts
# for its instant, done after the last; the scheduled identity = an Operations manager only. Two firings on fake
# models + mocks (the whole fleet at 2026-09-06 and 09-06 12:00), a crash in the third resumed by the fourth, then
# the retention 31 days later deletes the ended threads (archived first). Check threads use their own prefix.
import importlib.util  # noqa: E402

from langchain.tools import ToolRuntime  # noqa: E402

vw.LOCATIONS_PER_MIN, vw.RETRY_WAIT_S = None, 0      # mocks again

from pipelines.agents import scheduling  # noqa: E402
from pipelines.lib.retrieval import User  # noqa: E402

spec = importlib.util.spec_from_file_location("voyage_watch_cli", ROOT / "pipelines/scripts/agents/Voyage_watch.py")
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)
emps = [context.load_user(i) for i in range(1, 101)]
rbac_bad = [u.employee_id for u in emps if not cli.can_read(u)]
probe = User(0, "probe", 0, "Nowhere")
status_calls["n"], before_calls = 0, script_mode["calls"]
voyages.voyage_status = counted_status
tmp_reports7 = Path(tempfile.mkdtemp(prefix="voyage_watch_reports7_"))
g7 = vw.build_graph(roles.FakeRoles(script), saver, tmp_reports7)
tid_p = f"{CHECK_PREFIX}probe:1"
try:
    g7.invoke({"request": {}}, {"configurable": {"thread_id": tid_p}}, context=context.RunContext(probe),
              durability="sync")
    probe_res = g7.get_state({"configurable": {"thread_id": tid_p}}).values["result"]
finally:
    voyages.voyage_status = real_status
    saver.delete_thread(tid_p)
probe_reads = {"status_calls": status_calls["n"], "model_calls": script_mode["calls"] - before_calls}
reader_probe = cli.read_alerts(probe, folder=tmp_reports7)["status"]

rt = ToolRuntime(state={}, context=context.RunContext(ops_user), config={}, stream_writer=lambda *_: None,
                 tool_call_id="t1", store=None)
eta_vid = at_sea[3]
tool_eta = eta.voyage_eta_tool.invoke({"vessel_id": eta_vid, "runtime": rt})
eta_equal = tool_eta["status"] == "ok" and tool_eta["rows"][0]["eta_utc"] == fleet_eta[eta_vid]["eta_utc"]
anch = eta.voyage_eta(ops_user, vessel_id=anchored_ids[0])
try:
    eta.voyage_eta_tool.invoke({"vessel_id": eta_vid, "runtime": ToolRuntime(
        state={}, context=None, config={}, stream_writer=lambda *_: None, tool_call_id="t2", store=None)})
    no_ctx_refused = False
except PermissionError:
    no_ctx_refused = True
schema_fields = {"voyage_eta": set(eta.voyage_eta_tool.tool_call_schema.model_json_schema()["properties"]),
                 "WatchBrief": set(wm.WatchBrief.model_fields), "WatchItem": set(wm.WatchItem.model_fields)}
leaky = {k: v & {"user", "employee_id", "as_of", "dataset", "clock"} for k, v in schema_fields.items()}

# the planner on hand-made infos
grid = scheduling.watch_grid(context.DATA_AS_OF)
W = scheduling.WatchInfo
t0 = scheduling.now_utc()
p_empty = scheduling.plan_watch([], context.DATA_AS_OF)
p_next = scheduling.plan_watch([W("a", grid[0], 1, "ended", "ok", t0, 2)], context.DATA_AS_OF)
p_resume = scheduling.plan_watch([W("a", grid[0], 1, "ended", "ok", t0, 2), W("b", grid[1], 1, "stalled", None, t0, 2)],
                                 context.DATA_AS_OF)
p_hand = scheduling.plan_watch([W("a", grid[-1], 1, "ended", "ok", t0, 2)], context.DATA_AS_OF)
p_done = scheduling.plan_watch([W(f"t{k}", t, 1, "ended", "ok", t0, 2) for k, t in enumerate(grid)],
                               context.DATA_AS_OF)
planner = {"grid": (len(grid), vw.stamp(grid[0]), vw.stamp(grid[-1])),
           "empty": (p_empty.action, p_empty.thread_id), "next": (p_next.action, vw.stamp(p_next.as_of)),
           "resume": (p_resume.action, p_resume.thread_id), "hand": (p_hand.action, vw.stamp(p_hand.as_of)),
           "done": p_done.action}
identity = {e: scheduling.allowed_watch_run_as(context.load_user(e)) for e in (1, 2, 3, 6)}

# firings on fake models + mocks, own prefix; then the retention 31 days later
firings, archive7 = [], tmp_reports7 / "threads_archive.jsonl"
try:
    external.HTTP = httpx.Client(transport=httpx.MockTransport(fake_http), timeout=external.TIMEOUT_S)
    external.TODAY = date(2026, 10, 27)
    mock["change"], mock["portwatch"] = -0.30, "ok"
    fresh_caches()
    for mode in ("good", "good", "crash", "good"):
        script_mode["m"] = mode
        try:
            rec = scheduling.fire_watch(g7, saver, checkpointer.pool(), ops_user, archive7, context.DATA_AS_OF,
                                        prefix=CHECK_PREFIX)
            firings.append((rec["decision"]["action"], vw.stamp(rec["decision"]["as_of"]), rec["result"]["status"],
                            rec["result"]["brief"], rec["result"]["alerts"] > 0))
            if rec["result"]["brief"] != "ok":
                print("firing problems:", g7.get_state({"configurable": {"thread_id": rec["result"]["thread_id"]}})
                      .values["result"]["problems"][:2])
        except RuntimeError:
            firings.append(("crash",))
    reader_ops = cli.read_alerts(context.load_user(4), folder=tmp_reports7)
    reader_fin = cli.read_alerts(context.load_user(6), folder=tmp_reports7, high=True)
    infos7 = scheduling.describe_voyage_watch(g7, checkpointer.pool(), CHECK_PREFIX)
    later = scheduling.now_utc() + timedelta(days=31)
    kept_recent = scheduling.prune(g7, saver, [scheduling.as_thread_info(i) for i in infos7], archive7)
    pruned = scheduling.prune(g7, saver, [scheduling.as_thread_info(i) for i in infos7], archive7, now=later)
    archived = len(archive7.read_text(encoding="utf-8").splitlines()) if archive7.exists() else 0
finally:
    external.HTTP, external.TODAY = real_http, real_today
    for name in ("marine_weather", "suez_transits"):
        external._caches.pop(name, None)
    for d in tmp_dirs:
        shutil.rmtree(d, ignore_errors=True)
    for t in scheduling.thread_ids(checkpointer.pool(), CHECK_PREFIX):
        saver.delete_thread(t)
    shutil.rmtree(tmp_reports7, ignore_errors=True)
left7 = scheduling.thread_ids(checkpointer.pool(), CHECK_PREFIX)
print({"rbac_bad": rbac_bad, "probe": probe_res["status"], "probe_reads": probe_reads, "reader_probe": reader_probe,
       "eta_equal": eta_equal, "anchored": (anch.status, (anch.note or "")[:60]), "no_ctx_refused": no_ctx_refused,
       "leaky": leaky})
print({"planner": planner, "identity": identity})
print({"firings": firings, "reader": (reader_ops["status"], reader_ops.get("thread_id"), len(reader_ops["alerts"]),
                                      reader_fin["status"], len(reader_fin["alerts"])),
       "retention": (len(kept_recent["deleted"]), len(pruned["deleted"]), archived), "left": left7})

assert rbac_bad == [] and probe_res["status"] == "not_permitted" and probe_reads == {"status_calls": 0,
                                                                                    "model_calls": 0}
assert reader_probe == "not_permitted" and eta_equal and anch.status == "no_data" and no_ctx_refused
assert all(not v for v in leaky.values()), leaky
assert planner == {"grid": (15, "20260906T0000Z", "20260913T0000Z"),
                   "empty": ("start", "voyage_watch:20260906T0000Z:1"), "next": ("start", "20260906T1200Z"),
                   "resume": ("resume", "b"), "hand": ("start", "20260906T0000Z"), "done": "done"}, planner
assert identity == {1: False, 2: True, 3: True, 6: False}, identity      # CEO, Ops managers, a Finance manager
assert firings[:2] == [("start", "20260906T0000Z", "ok", "ok", True), ("start", "20260906T1200Z", "ok", "ok", True)]
assert firings[2] == ("crash",) and firings[3][:3] == ("resume", "20260907T0000Z", "ok"), firings
assert reader_ops["status"] == "ok" and reader_ops["thread_id"].endswith("20260907T0000Z:1") and reader_ops["alerts"]
assert reader_fin["status"] == "ok"
assert (len(kept_recent["deleted"]), len(pruned["deleted"]), archived) == (0, 3, 3) and left7 == []
print("✅ Phase 7 validation passed.")

# %% Final Checkpoint
# The narrative (steps, problems, fixes) is pipelines/checkpoints/agents/Voyage_watch_check.md.
pending = [] if brief_real_ok else [f"Phase 6 real brief {r6['brief_status']}"]
final = {"phases_passed": 9, "eta_mae_h": mae, "alert_precision_recall": (weather_score["precision"],
                                                                         weather_score["recall"]),
         "brief_plants_caught": f"{sum(caught.values())}/{len(plants)}", "real_brief": r6["brief_status"],
         "skill_reviewed_by_owner": sk.reviewed_by_owner}
print(f"Final Checkpoint: {final | {'pending': pending}}")
print(f"✅ Final Checkpoint passed (S1–S5, Phases 1–7 + 4s; pending: {pending or 'none'})")
