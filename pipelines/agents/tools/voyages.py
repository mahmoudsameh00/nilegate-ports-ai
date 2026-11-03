"""Our 500 synthetic voyages (ADR-032) and `voyage_status` (Agents plan §6a S6; P9-6, P9-7, F2–F4).

`voyages_synthetic.parquet` holds one voyage per vessel (route `A>B>C`, departure, service speed, …) and also the
generator's truth — `arrival_ts` — which for a voyage still at sea at the as-of instant is the answer key of the ETA
evaluation (F2, P9-7): no tool returns it before the vessel has arrived, and the AIS-declared ETA (`ais_vessels.eta_raw`,
the same truth, F4) is never read.

`voyage_status` sees the world at the run context's `as_of` (never later than the data's as-of instant):
- fixes = MongoDB `ais_positions` of the vessel's MMSI (PostgreSQL `vessels`, the system of record, ADR-028), synthetic
  only, `ts <= as_of`, read with the read-only user (P9-6);
- the route = rebuilt from its port sequence with `searoute` leg by leg, the generator's rule (F3: = `route_nm`);
- distance covered = the last fix projected on the route; where the route passes the same water twice, the projection
  closest to the track's odometer (the under-way fixes' summed steps) wins;
- status at `as_of` from the track itself (navstat of the last fix, a track that stopped = completed), so a cut at an
  earlier t is honest — never `vessels.status`, which describes the data's as-of instant.
Intermediate ports are waypoints without a stop in this data (F2): "next port" = the next one along the route.
Access: AIS tracks and ports are level 1 / Operations; the MMSI lookup reads `vessels` (level 1 / Operations).
"""
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from langchain.tools import ToolRuntime, tool
from pydantic import BaseModel, Field

from pipelines.agents.tools import context, db, mongo, routes
from pipelines.agents.tools.schemas import Source, ToolResult
from pipelines.lib.common import project_root

VOYAGES_FILE = project_root() / "Data" / "processed" / "semi-structured" / "synthetic" / "voyages_synthetic.parquet"
RECENT_H = 6                 # recent speed = mean SOG of the under-way fixes in the last 6 h
STOPPED_H = 3                # a moored track whose last fix is older than this at as_of has ended (completed)
SNAP_NM = 2.0                # a fix is "on" a route segment within this distance
PORT_TOL_NM = 0.5            # a port this close behind the vessel counts as passed
COURSE_TOL_DEG = 60          # a projection whose route course is this close to the fix's COG runs the same way

_voyages: pd.DataFrame | None = None
_routes: dict[int, dict] = {}


def voyages() -> pd.DataFrame:
    """The voyage file indexed by vessel_id (read-only copy in memory)."""
    global _voyages
    if _voyages is None:
        _voyages = pd.read_parquet(VOYAGES_FILE).set_index("vessel_id", verify_integrity=True)
    return _voyages


def route_of(vessel_id: int) -> dict:
    """The voyage's polyline rebuilt from its port sequence (+ the along-route distance of every port)."""
    if vessel_id not in _routes:
        pts = voyages().at[vessel_id, "route"].split(">")
        known = routes.ports()
        lat, lon, port_cum, total = [], [], [0.0], 0.0
        for a, b in zip(pts[:-1], pts[1:]):
            leg = routes.sea_leg(known[a], known[b])          # the generator's rule (F3), zero-length network part too
            total += float(routes.line(leg[0], leg[1])["cum"][-1])
            port_cum.append(total)
            lat.append(leg[0] if not lat else leg[0][1:])
            lon.append(leg[1] if not lon else leg[1][1:])
        r = routes.line(np.concatenate(lat), np.concatenate(lon))
        _routes[vessel_id] = r | {"ports": pts, "port_cum": np.array(port_cum)}
    return _routes[vessel_id]


def _project(r: dict, lat: float, lon: float) -> np.ndarray:
    """Along-route distances of the projections of (lat, lon) on every segment within SNAP_NM. On the sphere: the
    generator moves along each step's great circle (slerp), and steps can be hundreds of nm long, where a flat
    projection drifts by miles."""
    A, B = routes._xyz(r["lat"][:-1], r["lon"][:-1]), routes._xyz(r["lat"][1:], r["lon"][1:])
    P = routes._xyz(np.array(lat), np.array(lon))
    n = np.cross(A, B)
    nn = np.linalg.norm(n, axis=-1, keepdims=True)
    n = np.where(nn > 1e-12, n / np.where(nn > 1e-12, nn, 1), 0)
    Pp = P - np.sum(P * n, axis=-1, keepdims=True) * n             # P on the plane of the step's great circle
    seg = np.arctan2(np.linalg.norm(np.cross(A, B), axis=-1), np.sum(A * B, axis=-1))
    along = np.arctan2(np.sum(np.cross(A, Pp) * n, axis=-1), np.sum(A * Pp, axis=-1))
    along = np.clip(along, 0, seg)
    frac = np.where(seg > 1e-12, along / np.where(seg > 1e-12, seg, 1), 0)[:, None]
    om = seg[:, None]
    Q = np.where(om > 1e-12, (np.sin((1 - frac) * om) * A + np.sin(frac * om) * B) / np.where(om > 1e-12, np.sin(om), 1),
                 A)                                                 # the closest point of the step
    d = routes.R_NM * np.arctan2(np.linalg.norm(np.cross(Q, P), axis=-1), np.sum(Q * P, axis=-1))
    s = r["cum"][:-1] + frac[:, 0] * (r["cum"][1:] - r["cum"][:-1])
    # course of the route at each projection: the bearing from it to the step's end (the generator's COG rule)
    qlat, qlon = np.degrees(np.arctan2(Q[:, 2], np.hypot(Q[:, 0], Q[:, 1]))), np.degrees(np.arctan2(Q[:, 1], Q[:, 0]))
    p1, p2 = np.radians(qlat), np.radians(r["lat"][1:])
    dl = np.radians(r["lon"][1:] - qlon)
    crs = np.degrees(np.arctan2(np.sin(dl) * np.cos(p2), np.cos(p1) * np.sin(p2) - np.sin(p1) * np.cos(p2) * np.cos(dl)))
    keep = d <= SNAP_NM if (d <= SNAP_NM).any() else np.arange(len(d)) == int(np.argmin(d))
    return np.stack([s[keep], crs[keep] % 360], axis=1)


def _covered(cand: np.ndarray, cog, odometer: float) -> float:
    """The projection whose route course matches the fix's course (the two passes of a port visit run opposite ways),
    then the one closest to the odometer (which runs a little short: 10-min steps cut the corners)."""
    if cog is not None and len(cand) > 1:
        diff = np.abs((cand[:, 1] - cog + 180) % 360 - 180)
        if (diff <= COURSE_TOL_DEG).any():
            cand = cand[diff <= COURSE_TOL_DEG]
    return float(cand[np.argmin(np.abs(cand[:, 0] - odometer)), 0])


class StatusArgs(BaseModel):
    vessel_id: int = Field(ge=1, description="one of NileGate's vessels")


def _iso(t) -> str:
    return pd.Timestamp(t).tz_convert("UTC").isoformat().replace("+00:00", "Z")


def voyage_status(user, as_of: datetime | None = None, **args) -> ToolResult:
    a = StatusArgs.model_validate(args)
    as_of = context.RunContext(user, as_of=as_of or context.DATA_AS_OF).as_of      # the clock rules of the context
    if not context.permitted(user, context.AIS_TRACKS, context.PORTS, context.VESSELS):
        return context.denied("voyage_status")
    v = db.fetch("SELECT mmsi FROM vessels WHERE vessel_id = %s", (a.vessel_id,))
    voy = voyages()
    if not v or a.vessel_id not in voy.index:
        return ToolResult(tool="voyage_status", status="no_data", note=f"no vessel / voyage {a.vessel_id}")
    mmsi, row = v[0]["mmsi"], voy.loc[a.vessel_id]
    flt = f"vessel_id = {a.vessel_id} (MMSI {mmsi}), synthetic fixes with ts <= {_iso(as_of)}"
    src = Source(kind="table", name="mongodb:ais_positions + voyages_synthetic.parquet", filter=flt)
    fixes = list(mongo.database().ais_positions.find(
        {"meta.mmsi": mmsi, "meta.real_or_synthetic": "synthetic", "ts": {"$lte": as_of}},
        {"_id": 0, "ts": 1, "loc": 1, "sog": 1, "cog": 1, "navstat": 1}).sort("ts", 1))
    if not fixes:
        return ToolResult(tool="voyage_status", status="no_data", note=f"no AIS fix of vessel {a.vessel_id} at or "
                                                                       f"before {_iso(as_of)}")
    last = fixes[-1]
    r = route_of(a.vessel_id)
    total = float(r["cum"][-1])
    moving = [f for f in fixes if f["navstat"] == 0]
    departed = bool(moving)
    if last["navstat"] == 5 and not departed:
        status, covered = "Not departed", 0.0
    elif last["navstat"] == 5 and last["ts"] < as_of - timedelta(hours=STOPPED_H):
        status, covered = "Completed", total
    elif last["navstat"] == 5:
        status, covered = "At Port", total
    else:
        status = "Anchored" if last["navstat"] == 1 else "In Transit"
        ref = moving[-1] if status == "Anchored" else last
        ll = np.array([f["loc"]["coordinates"][::-1] for f in moving + ([] if ref is moving[-1] else [ref])])
        odometer = float(routes.gc_nm(ll[:-1, 0], ll[:-1, 1], ll[1:, 0], ll[1:, 1]).sum()) if len(ll) > 1 else 0.0
        lon0, lat0 = ref["loc"]["coordinates"]
        covered = _covered(_project(r, lat0, lon0), ref.get("cog"), odometer)
    left = max(total - covered, 0.0)
    ahead = [p for p, c in zip(r["ports"], r["port_cum"]) if c > covered + PORT_TOL_NM]
    recent = [f["sog"] for f in moving if f["ts"] >= as_of - timedelta(hours=RECENT_H)]
    lon_l, lat_l = last["loc"]["coordinates"]
    out = {"vessel_id": a.vessel_id, "voyage_no": row["voyage_no"], "as_of": _iso(as_of),
           "origin": row["origin_locode"], "destination": row["destination_locode"], "route": r["ports"],
           "route_nm": round(total, 1), "status_at_as_of": status,
           "departure_ts": _iso(row["departure_ts"]) if departed else None,
           "last_fix": {"ts": _iso(last["ts"]), "lat": round(lat_l, 5), "lon": round(lon_l, 5), "sog_kn": last["sog"],
                        "cog": last["cog"], "navstat": last["navstat"]},
           "recent_sog_kn": round(float(np.mean(recent)), 2) if recent else None,
           "distance_covered_nm": round(covered, 1), "distance_left_nm": round(left, 1),
           "next_port": ahead[0] if ahead and status in ("In Transit", "Anchored", "Not departed") else None,
           "ports_left": ahead if status in ("In Transit", "Anchored", "Not departed") else [],
           "arrival_ts": _iso(row["arrival_ts"]) if row["arrival_ts"] <= as_of and status in ("At Port", "Completed")
           else None}
    note = ("distances along the route at the last fix; intermediate ports are passed without a stop in this data; "
            "no ETA here — estimate it from distance_left_nm and the speed")
    return ToolResult(tool="voyage_status", status="ok", rows=[out], source=src, note=note)


@tool("voyage_status", args_schema=StatusArgs)
def voyage_status_tool(runtime: ToolRuntime, **args) -> dict:
    """Where one of NileGate's vessels is on its current voyage: last AIS position and speed, status, next port, ports
    left and the distance covered / left along the route, as of the run's clock."""
    return voyage_status(context.user_of(runtime), as_of=context.as_of_of(runtime), **args).model_dump(mode="json")
