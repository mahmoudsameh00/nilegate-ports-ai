"""ETA rules, next-leg points and "Suez ahead" for the voyage watch (Agents plan Phase 11, §6c P11-1…P11-4; F7–F10).

Everything here reads only what is known at the run's clock `t` — a `voyage_status` row (fixes with ts <= t), the
planned speed (`vessel_params`), the ports' positions, the route rebuilt from its port sequence — never the voyage
file's `arrival_ts` (the answer key, P9-7).

- **R, the rule-based ETA (the product, P11-1):** the distance left along the route at the recent sea speed (mean SOG
  of the last 6 h once the vessel has covered `MIN_COVERED_NM`, else its planned service speed), plus the port
  approach: the last `APPROACH_NM` at the harbour speed of the real NOAA harbour sample (6.7 kn, F7). Intermediate
  ports add no time (F2: the synthetic voyages pass them without a stop).
- **N, the naive baseline (P11-2, the S2-D5 bar):** the straight line from the last fix to the destination port at
  the last fix's SOG — the AIS-only estimate that knows neither the route nor the approach.
- **S, schedule, and R0, R without the approach:** references reported by the evaluation, never thresholds.
The data has no weather or traffic effect on speed (F7): an ETA is never corrected for weather; weather is a risk flag.
"""
import json
from datetime import datetime
from functools import cache
from typing import cast

import numpy as np
import pandas as pd
from langchain.tools import ToolRuntime, tool
from pydantic import BaseModel, Field

from pipelines.agents.tools import context, routes, vessels, voyages
from pipelines.agents.tools.schemas import Source, ToolResult
from pipelines.lib.common import project_root

NOAA_PROFILE = project_root() / "Data" / "processed" / "semi-structured" / "profiles" / "noaa_profile.json"
APPROACH_NM = 10.0          # the port approach sailed at harbour speed (pilotage waters; F7)
MIN_COVERED_NM = 20.0       # before this the recent speed may mix the departure harbour leg → the planned speed
MIN_SOG_KN = 1.0            # N: a last SOG below this says nothing about the passage → the planned speed
LEG_HOURS = (0, 24, 48, 72)  # the next-leg points: now and +1…3 days (P11-4)
# the canal proper on a MARNET path (F10): Port Said (31.265 N) and Sokhna (29.65 N) lie outside
SUEZ_BOX = {"lat": (30.0, 31.2), "lon": (32.25, 32.65)}


@cache
def harbour_kn() -> float:
    """The median implied moving speed of the real NOAA harbour sample (the profile the AIS generator used, F7)."""
    prof = json.loads(NOAA_PROFILE.read_text(encoding="utf-8"))["profile"]
    return round(float(prof["implied_kn_moving"]["0.5"]), 1)


def _ts(s: str) -> pd.Timestamp:
    return cast(pd.Timestamp, pd.Timestamp(s).tz_convert("UTC") if pd.Timestamp(s).tzinfo else pd.Timestamp(s, tz="UTC"))


def _iso(t: pd.Timestamp) -> str:
    return t.tz_convert("UTC").isoformat(timespec="minutes").replace("+00:00", "Z")


def sea_speed(status: dict, planned_kn: float) -> tuple[float, str]:
    """(knots, source) of the speed R uses for the open-sea part."""
    if status["recent_sog_kn"] and status["distance_covered_nm"] >= MIN_COVERED_NM:
        return float(status["recent_sog_kn"]), "recent speed (mean SOG of the last 6 h)"
    return float(planned_kn), "planned service speed (not yet 20 nm out: the recent speed may be harbour speed)"


def _hours_left(d: float, v: float, approach: bool = True) -> float:
    h = harbour_kn()
    if not approach:
        return d / v
    return (d - APPROACH_NM) / v + APPROACH_NM / h if d > APPROACH_NM else d / h


def eta_rule(status: dict, planned_kn: float, approach: bool = True) -> dict:
    """R (or R0 with `approach=False`) for an In Transit voyage_status row."""
    v, src = sea_speed(status, planned_kn)
    hours = _hours_left(float(status["distance_left_nm"]), v, approach)
    t0 = _ts(status["last_fix"]["ts"])
    eta = t0 + pd.Timedelta(hours=hours)
    asof = _ts(status["as_of"])
    return {"method": "R" if approach else "R0", "eta_utc": _iso(cast(pd.Timestamp, eta)),
            "eta_in_h": round((eta - asof).total_seconds() / 3600, 1), "speed_kn": round(v, 2), "speed_source": src,
            "distance_left_nm": status["distance_left_nm"], "approach_nm": APPROACH_NM if approach else 0.0,
            "harbour_kn": harbour_kn() if approach else None}


def eta_naive(status: dict, planned_kn: float) -> dict:
    """N: the straight line from the last fix to the destination port at the last SOG."""
    lat, lon = routes.ports()[status["destination"]]
    f = status["last_fix"]
    d = float(routes.gc_nm(np.array(f["lat"]), np.array(f["lon"]), np.array(lat), np.array(lon)))
    v = float(f["sog_kn"]) if f["sog_kn"] and f["sog_kn"] >= MIN_SOG_KN else float(planned_kn)
    eta = _ts(f["ts"]) + pd.Timedelta(hours=d / v)
    return {"method": "N", "eta_utc": _iso(cast(pd.Timestamp, eta)), "straight_nm": round(d, 1), "speed_kn": v}


def eta_schedule(status: dict, planned_kn: float) -> dict:
    """S: departure + the whole route at the planned speed (ignores where the vessel is)."""
    eta = _ts(status["departure_ts"]) + pd.Timedelta(hours=float(status["route_nm"]) / float(planned_kn))
    return {"method": "S", "eta_utc": _iso(cast(pd.Timestamp, eta))}


def next_leg_points(vessel_id: int, status: dict, eta: dict) -> list[dict]:
    """The vessel's position now and at +24 / +48 / +72 h along its route at R's sea speed, until the predicted
    arrival (the last point may be the destination); each with its UTC date (the weather's day)."""
    r = voyages.route_of(vessel_id)
    total = float(r["cum"][-1])
    covered, v = float(status["distance_covered_nm"]), float(eta["speed_kn"])
    asof = _ts(status["as_of"])
    lag_h = (asof - _ts(status["last_fix"]["ts"])).total_seconds() / 3600   # the last fix is up to ~10 min old
    out = []
    for h in LEG_HOURS:
        if h and h > eta["eta_in_h"]:
            break
        s = min(covered + v * (h + lag_h), total)
        lat, lon = routes.point_at(r, s)
        out.append({"hours_ahead_h": float(h), "along_nm": round(s, 1), "lat": round(float(lat[0]), 4),
                    "lon": round(float(lon[0]), 4), "date": (asof + pd.Timedelta(hours=h)).date().isoformat()})
    return out


def suez_ahead(vessel_id: int, covered_nm: float) -> bool:
    """Does the remaining route cross the canal (a vertex in SUEZ_BOX beyond the distance covered, F10)?"""
    r = voyages.route_of(vessel_id)
    lat, lon, cum = r["lat"], r["lon"], r["cum"]
    inside = ((lat >= SUEZ_BOX["lat"][0]) & (lat <= SUEZ_BOX["lat"][1]) & (lon >= SUEZ_BOX["lon"][0])
              & (lon <= SUEZ_BOX["lon"][1]))
    return bool((inside & (cum > covered_nm)).any())


# --- the tool (for the supervisor, Phase 12; the watch graph calls the functions directly) -------------------------

class EtaArgs(BaseModel):
    vessel_id: int = Field(ge=1, description="one of NileGate's vessels")


def voyage_eta(user, as_of: datetime | None = None, **args) -> ToolResult:
    """voyage_status + R for one vessel at the run's clock; a vessel not at sea has no ETA (said why)."""
    a = EtaArgs.model_validate(args)
    if not context.permitted(user, context.AIS_TRACKS, context.PORTS, context.VESSELS, context.VESSEL_PARAMS):
        return context.denied("voyage_eta")
    st = voyages.voyage_status(user, as_of=as_of, vessel_id=a.vessel_id)
    if st.status != "ok":
        return ToolResult(tool="voyage_eta", status=st.status, note=st.note)
    s = st.rows[0]
    if s["status_at_as_of"] != "In Transit":
        return ToolResult(tool="voyage_eta", status="no_data",
                          note=f"vessel {a.vessel_id} is {s['status_at_as_of']} at {s['as_of']}: no ETA to estimate"
                               + (" (at anchorage off its destination; the berth time is not in the data)"
                                  if s["status_at_as_of"] == "Anchored" else ""))
    p = vessels.vessel_params(user, vessel_id=a.vessel_id)
    planned = p.rows[0]["speed_kn"]
    e = eta_rule(s, planned)
    row = {"vessel_id": a.vessel_id, "as_of": s["as_of"], "destination": s["destination"],
           "next_port": s["next_port"], "distance_left_nm": s["distance_left_nm"], "eta_utc": e["eta_utc"],
           "eta_in_h": e["eta_in_h"], "speed_kn": e["speed_kn"], "speed_source": e["speed_source"],
           "approach_nm": APPROACH_NM, "harbour_kn": harbour_kn()}
    return ToolResult(tool="voyage_eta", status="ok", rows=[row],
                      source=Source(kind="table", name="voyage_status + vessel_params (rule R, Agents plan §6c)",
                                    filter=f"vessel_id = {a.vessel_id}, as of {s['as_of']}"),
                      note=("ETA = distance left / recent sea speed + the last 10 nm at harbour speed; no port stops, "
                            "no weather or congestion modelled (synthetic tracks)"))


@tool("voyage_eta", args_schema=EtaArgs)
def voyage_eta_tool(runtime: ToolRuntime, **args) -> dict:
    """The estimated time of arrival of one of NileGate's vessels at its destination, from its position and recent
    speed, as of the run's clock (no ETA for a vessel at anchor, in port or not yet departed)."""
    return voyage_eta(context.user_of(runtime), as_of=context.as_of_of(runtime), **args).model_dump(mode="json")
