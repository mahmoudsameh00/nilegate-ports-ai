"""Synthetic AIS generator — tracks for our 500 vessels

Converted from Notebooks/semi_structured/AIS_generator.ipynb (2026-10-01) by tools/nb_to_script.py: same cells, same order; `# %% cell N` = notebook cell N.
Run from the project root: uv run python tools/run.py pipelines/scripts/semi_structured/AIS_generator.py

Reads:   Data/processed/semi-structured/profiles/; PostgreSQL (vessels, ports)
Writes:  Data/processed/semi-structured/synthetic/ (AIS parquet files + ais_generation_manifest.json)
Re-run:  safe: fixed seed, rewrites the same files
Final Checkpoint (what was done, problems, fixes): pipelines/checkpoints/semi_structured/AIS_generator.md
"""
from IPython.display import display  # outside Jupyter it prints the value (added by the conversion)


def _display_result(value):
    """A notebook shows the value of a cell's last expression unless it is None (added by the conversion)."""
    if value is not None:
        display(value)

# %% [markdown] cell 0
# # Synthetic AIS generator — tracks for our 500 vessels
#
# Plan: `docs/plans/SemiStructured_MongoDB_plan.md`, Phase 6 (ADR-028, ADR-032). Output: files only, in
# `Data/processed/semi-structured/synthetic/` — the loader notebook is the only writer to MongoDB (ADR-031).
#
# **Inputs (read-only):** PostgreSQL `vessels` (incl. `mmsi`, migration 005), `ports`, `port_connections`; the reviewed
# profiles of `AIS_EDI_profiling.ipynb` (harbour speed, reporting behaviour, the implied-speed threshold).
#
# **Decisions applied:** D10 as-of instant `2026-09-13T00:00:00Z`; D11 fixes every 10 min when moving and every 60 min
# when stationary; D12 shortest path over `port_connections`; D9 one static record per vessel for `ais_vessels`.
# Every vessel gets its own random stream `default_rng([42, vessel_id])`, so a vessel's track does not depend on the
# order in which vessels are processed.

# %% [markdown] cell 1
# ## Phase 1 — Inputs
#
# PostgreSQL is read in a read-only transaction. The row counts and a hash of the vessel rows go into the generation
# manifest, so an artifact can always be traced to the database state it was generated from.

# %% cell 2
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg
import searoute
from global_land_mask import globe
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components, dijkstra


def find_root(start: Path) -> Path:
    for p in [start, *start.parents]:
        if (p / "pyproject.toml").exists() and (p / "Data").is_dir():
            return p
    raise FileNotFoundError("project root not found above " + str(start))


ROOT = find_root(Path.cwd())
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())
ENV = os.environ
SEMI = ROOT / "Data" / "processed" / "semi-structured"
OUT = SEMI / "synthetic"
SEED = 42
ASOF = datetime(2026, 9, 13, tzinfo=timezone.utc)


def pg_frame(conn, sql: str) -> pd.DataFrame:
    cur = conn.execute(sql)
    return pd.DataFrame(cur.fetchall(), columns=[d.name for d in cur.description])


with psycopg.connect(host=ENV["PGHOST"], port=ENV["PGPORT"], dbname=ENV["PGDATABASE"], user=ENV["PGUSER"],
                     password=ENV["PGPASSWORD"], options="-c default_transaction_read_only=on") as conn:
    vessels = pg_frame(conn, "SELECT vessel_id, imo_number, mmsi, vessel_name, vessel_type, flag_country, "
                             "origin_locode, destination_locode, status FROM vessels ORDER BY vessel_id")
    ports = pg_frame(conn, "SELECT locode, name, lon, lat FROM ports ORDER BY locode")
    conns = pg_frame(conn, "SELECT port1_locode, port2_locode, ST_NPoints(geom) AS npts, "
                           "ST_Length(geom::geography) / 1852.0 AS nm FROM port_connections")

prof_noaa = json.loads((SEMI / "profiles" / "noaa_profile.json").read_text(encoding="utf-8"))["profile"]
prof_aishub = json.loads((SEMI / "profiles" / "aishub_profile.json").read_text(encoding="utf-8"))
vessel_rows_sha = hashlib.sha256(vessels.to_csv(index=False).encode()).hexdigest()
print("vessels:", len(vessels), "| ports:", len(ports), "| connections:", len(conns), "| vessels sha:", vessel_rows_sha[:12])

# %% cell 3
# ---- Phase 1 validation ------------------------------------------------------------------------------------------
assert len(vessels) == 500 and vessels["mmsi"].notna().all() and vessels["mmsi"].is_unique
assert len(ports) == 837 and len(conns) == 19990
assert (conns["npts"] == 2).all(), "a connection has intermediate vertices: the leg model below assumes 2-point lines"
print("✅ Phase 1 validation passed.")

# %% [markdown] cell 4
# ## Phase 2 — Parameters: what comes from the profiles, what is a documented default
#
# | Parameter | Value | Source |
# |---|---|---|
# | Harbour speed (first / last 10 nm of a voyage) | NOAA median implied speed of moving steps | profile (`noaa_profile.json`) |
# | Teleport threshold | NOAA p99 implied speed, rounded up | profile |
# | Reporting interval | 10 min moving, 60 min stationary (± 30 s jitter) | decision D11 (profile: ~70 s / ~180 s, thinned) |
# | Open-sea service speed per vessel type | ranges below | **documented default**: the samples hold harbour traffic only |
# | Stay at origin before departure | 6 h moored | default |
# | Anchorage | 5 nm before the destination, on the route | default |
# | Status timeline | see Phase 4 | plan 6.3 |
#
# AIS ship-type codes for our 13 Suez vessel categories follow ITU-R M.1371 Table 53 (70 cargo, 80 tanker, 60 passenger,
# 90 other). The open-sea speed ranges are typical service speeds per category; they are defaults, not measurements.

# %% cell 5
HARBOUR_KN = round(prof_noaa["implied_kn_moving"]["0.5"], 1)
TELEPORT_KN = float(np.ceil(prof_noaa["implied_kn_moving"]["0.99"]))
MOVE_DT_S, STAT_DT_S, JITTER_S = 600, 3600, 30
APPROACH_NM, ANCHOR_BEFORE_NM, PRE_DEPARTURE_H = 10.0, 5.0, 6
TYPE_PARAMS = {  # vessel_type: (AIS ship type code, service speed min kn, max kn)
    "Containerships": (70, 16.0, 20.0),
    "General Cargo / Multi-Purpose / Heavy Lift Vessels": (70, 11.0, 14.0),
    "Dry Bulk Vessels": (70, 11.0, 14.0),
    "Vehicles Carriers": (70, 16.0, 19.0),
    "Roll-On/Roll-Off (Ro/Ro) Vessels": (70, 15.0, 19.0),
    "Crude Oil Tankers": (80, 12.0, 15.0),
    "Petroleum Product Tankers": (80, 12.0, 15.0),
    "Chemical Tankers & Other Liquid Bulk Tankers": (80, 12.0, 15.0),
    "Liquefied Natural Gas (LNG) Carriers": (80, 16.0, 19.0),
    "Liquefied Petroleum Gas (LPG) Carriers": (80, 14.0, 17.0),
    "Cruise Ships": (60, 16.0, 20.0),
    "Other Vessels": (90, 10.0, 14.0),
    "Special Floating Units": (90, 5.0, 10.0),
}
STATUS_NAVSTAT = {"In Transit": 0, "Anchored": 1, "At Port": 5, "Completed": 5}  # final NAVSTAT per status
print({"HARBOUR_KN": HARBOUR_KN, "TELEPORT_KN": TELEPORT_KN})

# %% cell 6
# ---- Phase 2 validation ------------------------------------------------------------------------------------------
assert set(TYPE_PARAMS) == set(vessels["vessel_type"]), set(vessels["vessel_type"]) ^ set(TYPE_PARAMS)
assert set(STATUS_NAVSTAT) == set(vessels["status"])
assert all(lo < hi < TELEPORT_KN for _, lo, hi in TYPE_PARAMS.values()), "service speeds must stay under the teleport threshold"
assert 4 < HARBOUR_KN < 10 and 25 <= TELEPORT_KN <= 40
print("✅ Phase 2 validation passed.")

# %% [markdown] cell 7
# ## Phase 3 — Routes: port sequence over `port_connections`, sea path for every leg
#
# **Port sequence (owner decision 6, D12).** Every connection is a 2-point line between two ports (checked in Phase 1),
# so the network is a graph of ports. A vessel calls at the ports of the shortest path (by geodesic length) from its
# origin to its destination (`scipy.sparse.csgraph.dijkstra`). A vessel whose destination is not in the origin's
# component sails directly (one leg), flagged `route_fallback`.
#
# **Leg geometry (ADR-032 amendment, 2026-09-27).** The first version drew each leg as a great circle between the two
# ports: **49 % of the under-way fixes were on land** (vessel 1 crossed Central Europe). Each leg now follows a sea path
# computed by `searoute` (Eurostat MARNET maritime network, including the Suez and Panama canals), with the two port
# points added at the ends; the route is the chain of those vertices. Sea paths are ~40 % longer than great circles,
# so voyages are longer and depart earlier. Computing sea paths for all 19,990 connections to re-rank the network
# would take ~1 h, so the port sequence still comes from the geodesic Dijkstra.
#
# The land check uses `global_land_mask` (1 km grid). Port points are UN/LOCODE town coordinates, mostly on land in a
# 1 km grid (720 / 837), so the check applies to under-way fixes **more than 20 nm from every port of the route**.

# %% cell 8
R_NM = 3440.065
port_idx = {l: i for i, l in enumerate(ports["locode"])}
PORT_LL = ports.set_index("locode")[["lat", "lon"]].astype(float)


def to_xyz(lat, lon):
    la, lo = np.radians(lat), np.radians(lon)
    return np.stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)], axis=-1)


def to_latlon(xyz):
    xyz = xyz / np.linalg.norm(xyz, axis=-1, keepdims=True)
    return np.degrees(np.arcsin(np.clip(xyz[..., 2], -1, 1))), np.degrees(np.arctan2(xyz[..., 1], xyz[..., 0]))


def gc_nm(lat1, lon1, lat2, lon2):
    a, b = to_xyz(lat1, lon1), to_xyz(lat2, lon2)
    return R_NM * np.arctan2(np.linalg.norm(np.cross(a, b), axis=-1), np.sum(a * b, axis=-1))


def bearing(lat1, lon1, lat2, lon2):
    p1, p2, dl = np.radians(lat1), np.radians(lat2), np.radians(np.asarray(lon2) - np.asarray(lon1))
    x = np.sin(dl) * np.cos(p2)
    y = np.cos(p1) * np.sin(p2) - np.sin(p1) * np.cos(p2) * np.cos(dl)
    return (np.degrees(np.arctan2(x, y)) + 360) % 360


graph = coo_matrix((conns["nm"], (conns["port1_locode"].map(port_idx), conns["port2_locode"].map(port_idx))),
                   shape=(len(port_idx), len(port_idx))).tocsr()
n_comp, comp = connected_components(graph, directed=False)
origins = sorted({port_idx[o] for o in vessels["origin_locode"]})
dist, pred = dijkstra(graph, directed=False, indices=origins, return_predecessors=True)
orow = {o: i for i, o in enumerate(origins)}
inv_idx = {i: l for l, i in port_idx.items()}


def route_ports(o: str, d: str) -> tuple[list[str], bool]:
    r, t = orow[port_idx[o]], port_idx[d]
    if not np.isfinite(dist[r, t]):
        return [o, d], True
    path = [t]
    while path[-1] != port_idx[o]:
        path.append(pred[r, path[-1]])
    return [inv_idx[i] for i in reversed(path)], False


SEA_LEGS = {}  # (from, to) -> (lat, lon) vertices of the sea path, port points included


def sea_leg(a: str, b: str):
    """Sea path between two ports (searoute, Eurostat MARNET network), with the two port points added at the ends."""
    if (a, b) not in SEA_LEGS:
        pa, pb = PORT_LL.loc[a], PORT_LL.loc[b]
        f = searoute.searoute([pa["lon"], pa["lat"]], [pb["lon"], pb["lat"]], units="naut")
        c = np.array(f["geometry"]["coordinates"], dtype=float)
        lon = np.r_[pa["lon"], (c[:, 0] + 180) % 360 - 180, pb["lon"]]
        lat = np.r_[pa["lat"], c[:, 1], pb["lat"]]
        SEA_LEGS[(a, b)] = (lat, lon)
    return SEA_LEGS[(a, b)]


def build_route(pts: list[str]) -> dict:
    lat, lon = [], []
    for a, b in zip(pts[:-1], pts[1:]):
        la, lo = sea_leg(a, b)
        lat.append(la if not lat else la[1:]); lon.append(lo if not lon else lo[1:])
    lat, lon = np.concatenate(lat), np.concatenate(lon)
    step = gc_nm(lat[:-1], lon[:-1], lat[1:], lon[1:])
    keep = np.r_[True, step > 0.01]  # drop repeated vertices (zero-length steps)
    lat, lon = lat[keep], lon[keep]
    return {"lat": lat, "lon": lon, "cum": np.r_[0, np.cumsum(gc_nm(lat[:-1], lon[:-1], lat[1:], lon[1:]))]}


routes = {}
for v in vessels.itertuples():
    pts, fallback = route_ports(v.origin_locode, v.destination_locode)
    routes[v.vessel_id] = {"ports": pts, "fallback": fallback, **build_route(pts)}
route_nm = pd.Series({k: r["cum"][-1] for k, r in routes.items()})
print("components:", n_comp, "| fallback routes:", sum(r["fallback"] for r in routes.values()),
      "| legs per route (median/max):", int(np.median([len(r["ports"]) - 1 for r in routes.values()])),
      max(len(r["ports"]) - 1 for r in routes.values()), "| route nm:", route_nm.describe()[["min", "50%", "max"]].round(0).to_dict())

# %% cell 9
# ---- Phase 3 validation ------------------------------------------------------------------------------------------
for vid, r in routes.items():
    v = vessels.loc[vessels["vessel_id"] == vid].iloc[0]
    assert r["ports"][0] == v["origin_locode"] and r["ports"][-1] == v["destination_locode"]
    assert np.all(np.diff(r["cum"]) > 0), f"vessel {vid}: zero-length step"
    o, d = PORT_LL.loc[v["origin_locode"]], PORT_LL.loc[v["destination_locode"]]
    assert (r["lat"][0], r["lon"][0]) == (o["lat"], o["lon"]) and (r["lat"][-1], r["lon"][-1]) == (d["lat"], d["lon"])
    assert np.abs(r["lon"]).max() <= 180 and np.abs(r["lat"]).max() <= 90
    if not r["fallback"]:  # every leg is a real connection
        assert all(graph[port_idx[a], port_idx[b]] > 0 or graph[port_idx[b], port_idx[a]] > 0
                   for a, b in zip(r["ports"][:-1], r["ports"][1:]))
actual_3 = {"fallback_vessels": sorted(int(k) for k, r in routes.items() if r["fallback"]),
            "route_nm_total": int(round(route_nm.sum())), "sea_legs": len(SEA_LEGS),
            "route_vertices": int(sum(len(r["lat"]) for r in routes.values()))}
REVIEWED_3 = {"fallback_vessels": [323, 442], "route_nm_total": 3809439,  # reviewed 2026-09-27 (sea paths)
              "sea_legs": 1476, "route_vertices": 62947}
if REVIEWED_3:
    assert actual_3 == REVIEWED_3, f"routes changed: {actual_3}"
else:
    print("snapshot pending review:", json.dumps(actual_3))
print("✅ Phase 3 validation passed.")

# %% [markdown] cell 10
# ## Phase 4 — Voyage timeline per vessel, consistent with `vessels.status`
#
# Each vessel's track covers its **current voyage**, from 6 h moored at the origin before departure until the as-of
# instant (or until it stops reporting). This refines D10: a fixed 30-day window would cut long voyages (up to ~11,400
# nm, i.e. more than 30 days for a slow unit) so their tracks would not start at the origin; the as-of instant stays
# `2026-09-13T00:00Z` and no fix is later than it.
#
# | `vessels.status` | Timeline (random draws from the vessel's own stream) | Last NAVSTAT |
# |---|---|---|
# | `In Transit` | at the as-of instant the vessel has covered a fraction U(0.05, 0.95) of its voyage time | 0 under way |
# | `Anchored` | reached an anchorage 5 nm before the destination U(2, 72) h before the as-of instant, at anchor since | 1 at anchor |
# | `At Port` | arrived U(6, 96) h before the as-of instant, moored at the destination since | 5 moored |
# | `Completed` | arrived U(3, 10) days before the as-of instant, moored 12 h, then the track ends | 5 moored |
#
# Speed along the route: harbour speed over the first and last 10 nm, the vessel's service speed U(min, max) of its
# type in between. Moving fixes every 10 min, stationary fixes every 60 min, each ± 30 s. Reported values carry small
# noise (SOG σ 0.2 kn, COG σ 1°, heading σ 2°; positions at berth / anchor jitter by metres), rounded like AIS.

# %% cell 11
def point_on_route(r: dict, s: np.ndarray):
    """Positions (lat, lon) and course (bearing to the end of the current leg) at along-route distances s (nm)."""
    i = np.clip(np.searchsorted(r["cum"], s, side="right") - 1, 0, len(r["cum"]) - 2)
    frac = np.clip((s - r["cum"][i]) / (r["cum"][i + 1] - r["cum"][i]), 0, 1)
    a, b = to_xyz(r["lat"][i], r["lon"][i]), to_xyz(r["lat"][i + 1], r["lon"][i + 1])
    omega = np.arctan2(np.linalg.norm(np.cross(a, b), axis=-1), np.sum(a * b, axis=-1))[:, None]
    f = frac[:, None]
    p = (np.sin((1 - f) * omega) * a + np.sin(f * omega) * b) / np.sin(omega)
    lat, lon = to_latlon(p)
    crs = bearing(lat, lon, r["lat"][i + 1], r["lon"][i + 1])
    at_end = frac >= 1  # exactly on the next waypoint: use the bearing of that leg's end direction
    crs = np.where(at_end, bearing(r["lat"][i], r["lon"][i], r["lat"][i + 1], r["lon"][i + 1]), crs)
    return lat, lon, crs


def ticks(start: datetime, end: datetime, step_s: int, rng) -> list[datetime]:
    """Report times from start (inclusive) to end (inclusive when it falls on the grid), step ± jitter."""
    n = int((end - start).total_seconds() // step_s)
    base = [start + timedelta(seconds=k * step_s) for k in range(n + 1)]
    jit = rng.integers(-JITTER_S, JITTER_S + 1, size=len(base))
    jit[0] = 0
    out = [t + timedelta(seconds=int(j)) for t, j in zip(base, jit)]
    return [t for t in out if start <= t <= end]


def stay(lat0, lon0, times, navstat, sigma_deg, rng, phase):
    n = len(times)
    hdg = int(rng.integers(0, 360))
    return pd.DataFrame({"ts": times, "lat": lat0 + rng.normal(0, sigma_deg, n), "lon": lon0 + rng.normal(0, sigma_deg, n),
                         "sog": np.round(np.abs(rng.normal(0, 0.05, n)), 1), "cog": np.nan, "heading": float(hdg),
                         "navstat": navstat, "phase": phase})


def generate_vessel(v):
    """Track (DataFrame) and voyage record of one vessel; depends only on the vessel row, its route and its own stream."""
    rng = np.random.default_rng([SEED, v.vessel_id])
    r = routes[v.vessel_id]
    L = r["cum"][-1]
    code, lo, hi = TYPE_PARAMS[v.vessel_type]
    service = float(rng.uniform(lo, hi))
    a1, a2 = min(APPROACH_NM, L / 2), max(L - APPROACH_NM, L / 2)
    S = np.array([0.0, a1, a2, L])
    T = np.cumsum([0.0, a1 / HARBOUR_KN, (a2 - a1) / service, (L - a2) / HARBOUR_KN])  # hours
    end_s = L - ANCHOR_BEFORE_NM if v.status == "Anchored" else L
    t_end_h = float(np.interp(end_s, S, T))

    if v.status == "In Transit":
        moving_h = float(rng.uniform(0.05, 0.95)) * T[-1]
        departure = ASOF - timedelta(hours=moving_h)
        arrival, stop = departure + timedelta(hours=float(T[-1])), ASOF
    elif v.status == "Anchored":
        arrival = ASOF - timedelta(hours=float(rng.uniform(2, 72)))
        departure, stop = arrival - timedelta(hours=t_end_h), ASOF
    elif v.status == "At Port":
        arrival = ASOF - timedelta(hours=float(rng.uniform(6, 96)))
        departure, stop = arrival - timedelta(hours=t_end_h), ASOF
    else:  # Completed
        arrival = ASOF - timedelta(days=float(rng.uniform(3, 10)))
        departure, stop = arrival - timedelta(hours=t_end_h), arrival + timedelta(hours=12)
    departure, arrival, stop = (t.replace(microsecond=0) for t in (departure, arrival, stop))

    # 1) moored at the origin before departure
    o_lat, o_lon = PORT_LL.loc[v.origin_locode, ["lat", "lon"]]
    parts = [stay(o_lat, o_lon, ticks(departure - timedelta(hours=PRE_DEPARTURE_H), departure - timedelta(seconds=1),
                                      STAT_DT_S, rng), 5, 0.0005, rng, "moored_origin")]
    # 2) under way: departure -> min(arrival at end_s, as-of)
    move_end = min(departure + timedelta(hours=t_end_h), ASOF) if v.status == "In Transit" else departure + timedelta(hours=t_end_h)
    mt = ticks(departure, move_end, MOVE_DT_S, rng)
    if v.status != "In Transit" and mt[-1] != move_end:
        mt.append(move_end)  # an exact fix at the arrival instant
    th = np.array([(t - departure).total_seconds() / 3600 for t in mt])
    s = np.interp(th, T, S)
    lat, lon, crs = point_on_route(r, s)
    spd = np.where((s < a1) | (s > a2), HARBOUR_KN, service)
    n = len(mt)
    cog = np.round((crs + rng.normal(0, 1.0, n)) % 360, 1) % 360
    parts.append(pd.DataFrame({"ts": mt, "lat": lat, "lon": lon,
                               "sog": np.round(np.clip(spd + rng.normal(0, 0.2, n), 0.5, None), 1),
                               "cog": cog, "heading": np.round(cog + rng.normal(0, 2.0, n)) % 360,
                               "navstat": 0, "phase": "under_way"}))
    # 3) after arrival
    if v.status == "Anchored":
        a_lat, a_lon, _ = point_on_route(r, np.array([end_s]))
        st = ticks(move_end + timedelta(seconds=STAT_DT_S), stop, STAT_DT_S, rng)
        parts.append(stay(a_lat[0], a_lon[0], st, 1, 0.002, rng, "anchored"))
    elif v.status in ("At Port", "Completed"):
        d_lat, d_lon = PORT_LL.loc[v.destination_locode, ["lat", "lon"]]
        st = ticks(move_end + timedelta(seconds=STAT_DT_S), stop, STAT_DT_S, rng)
        parts.append(stay(d_lat, d_lon, st, 5, 0.0005, rng, "moored_destination"))

    trk = pd.concat([p for p in parts if len(p)], ignore_index=True)
    trk.insert(0, "vessel_id", v.vessel_id)
    return trk, {"vessel_id": v.vessel_id, "voyage_no": f"{departure:%y%m}-{v.vessel_id:03d}",
                 "status": v.status, "origin_locode": v.origin_locode, "destination_locode": v.destination_locode,
                 "departure_ts": departure, "arrival_ts": arrival, "last_fix_ts": trk["ts"].max(),
                 "route": ">".join(r["ports"]), "route_nm": round(float(L), 1), "route_fallback": r["fallback"],
                 "service_kn": round(service, 2), "ais_ship_type": code}


results = [generate_vessel(v) for v in vessels.itertuples()]
track_parts, voyage_rows = [t for t, _ in results], [w for _, w in results]
tracks = pd.concat(track_parts, ignore_index=True)
voyages = pd.DataFrame(voyage_rows)
tracks = tracks.merge(vessels[["vessel_id", "mmsi", "imo_number"]], on="vessel_id").rename(columns={"imo_number": "imo"})
tracks["ts"] = pd.to_datetime(tracks["ts"], utc=True)
tracks = tracks.sort_values(["vessel_id", "ts"], kind="stable").reset_index(drop=True)
tracks["navstat"] = tracks["navstat"].astype(int)
print("fixes:", len(tracks), "| by phase:", tracks["phase"].value_counts().to_dict())
print("departures:", voyages["departure_ts"].min(), "->", voyages["departure_ts"].max())

# %% cell 12
# ---- Phase 4 validation ------------------------------------------------------------------------------------------
g = tracks.groupby("vessel_id")
dt_s = g["ts"].diff().dt.total_seconds()
step_nm = gc_nm(g["lat"].shift().to_numpy(), g["lon"].shift().to_numpy(), tracks["lat"].to_numpy(), tracks["lon"].to_numpy())
implied_kn = pd.Series(step_nm, index=tracks.index) / (dt_s / 3600)
first, last = g.head(1).set_index("vessel_id"), g.tail(1).set_index("vessel_id")
vv = vessels.set_index("vessel_id")
d_start = gc_nm(first["lat"], first["lon"], PORT_LL.loc[vv.loc[first.index, "origin_locode"], "lat"].to_numpy(),
                PORT_LL.loc[vv.loc[first.index, "origin_locode"], "lon"].to_numpy())
d_end = pd.Series(gc_nm(last["lat"], last["lon"], PORT_LL.loc[vv.loc[last.index, "destination_locode"], "lat"].to_numpy(),
                        PORT_LL.loc[vv.loc[last.index, "destination_locode"], "lon"].to_numpy()), index=last.index)
status = vv["status"]

assert (dt_s.dropna() > 0).all(), "timestamps not strictly increasing per vessel"
assert tracks["ts"].max() <= pd.Timestamp(ASOF), "a fix after the as-of instant"
assert implied_kn.dropna().max() <= TELEPORT_KN, f"teleport: {implied_kn.max():.1f} kn"
assert (d_start <= 1.0).all(), "a track does not start at its origin port"
assert (d_end[status[status.isin(["At Port", "Completed"])].index] <= 1.0).all(), "arrived vessel not at destination"
anch = status[status == "Anchored"].index
# the anchorage is 5 nm before the destination ALONG the route; a sea path bends near the port, so the straight-line
# distance is at most 5 nm (+ the anchor swing) and can be shorter
print("anchorage straight-line distance to destination (nm):", d_end[anch].describe()[["min", "50%", "max"]].round(2).to_dict())
assert d_end[anch].between(0.5, ANCHOR_BEFORE_NM + 0.5).all(), "anchorage not near the destination"
transit = status[status == "In Transit"].index
assert (last.loc[transit, "navstat"] == 0).all() and (pd.Timestamp(ASOF) - last.loc[transit, "ts"]).max() <= pd.Timedelta(
    seconds=MOVE_DT_S + JITTER_S), "vessel in transit not reporting at the as-of instant"
assert (last["navstat"] == status.map(STATUS_NAVSTAT)).all(), "last NAVSTAT inconsistent with vessels.status"
assert tracks[["lat", "lon"]].abs().le([90, 180]).all().all() and tracks["cog"].dropna().between(0, 359.99).all()
assert tracks["heading"].between(0, 359).all() and tracks["sog"].between(0, 102.2).all()
assert len(tracks) <= 2_000_000, "volume above the D11 bound"
for vid in (1, 137, 323, 442, 500):  # reproducibility: any vessel regenerated alone gives the same track
    again, _ = generate_vessel(vessels[vessels["vessel_id"] == vid].iloc[0])
    again["ts"] = pd.to_datetime(again["ts"], utc=True)
    stored = tracks[tracks["vessel_id"] == vid].reset_index(drop=True)
    pd.testing.assert_frame_equal(again[["ts", "lat", "lon", "sog", "cog", "heading", "navstat", "phase"]],
                                  stored[["ts", "lat", "lon", "sog", "cog", "heading", "navstat", "phase"]],
                                  check_dtype=False)
# land check: under-way fixes more than 20 nm from every port of the vessel's route must be at sea
far = np.zeros(len(tracks), dtype=bool)
for vid, idx in tracks.groupby("vessel_id").groups.items():
    rp = PORT_LL.loc[routes[vid]["ports"]]
    sub = tracks.loc[idx]
    dmin = np.min([gc_nm(sub["lat"].to_numpy(), sub["lon"].to_numpy(), la, lo) for la, lo in zip(rp["lat"], rp["lon"])], axis=0)
    far[np.asarray(idx)] = dmin > 20
open_sea = far & (tracks["phase"] == "under_way").to_numpy()
on_land = globe.is_land(tracks["lat"].to_numpy(), tracks["lon"].to_numpy())
land_share = float((open_sea & on_land).sum() / open_sea.sum())
print(f"under-way fixes > 20 nm from the route ports: {int(open_sea.sum())} | on land: {int((open_sea & on_land).sum())} "
      f"({land_share:.2%})")
actual_4 = {"fixes": len(tracks), "by_phase": tracks["phase"].value_counts().sort_index().to_dict(),
            "max_implied_kn": round(float(implied_kn.max()), 2), "max_start_nm": round(float(d_start.max()), 3),
            "open_sea_fixes_on_land": int((open_sea & on_land).sum())}
# reviewed 2026-09-27: the remaining land-flagged open-sea fixes lie in waterways narrower than the 1 km mask — Suez
# Canal (largest share), Panama Canal, Dardanelles, Scheldt, St. Lawrence Seaway, Elbe / Kiel Canal, Amazon, Cook Inlet
assert land_share < 0.015, f"too many open-sea fixes on land: {land_share:.2%}"
REVIEWED_4 = {
    "fixes": 1310619, "by_phase": {"anchored": 3055, "moored_destination": 7388, "moored_origin": 3000, "under_way": 1297176},
    "max_implied_kn": 19.82, "max_start_nm": 0.088, "open_sea_fixes_on_land": 12156}
if REVIEWED_4:
    assert actual_4 == REVIEWED_4, f"tracks changed: {actual_4}"
else:
    print("snapshot pending review:", json.dumps(actual_4))
print("✅ Phase 4 validation passed.")

# %% [markdown] cell 13
# ## Phase 5 — Static records for `ais_vessels` (decision D9)
#
# One static / voyage record per vessel, as its AIS transponder would broadcast it: identity copied from PostgreSQL
# (`mmsi`, `imo_number`, `vessel_name`, `vessel_id`), the AIS ship type of its category, destination = its destination
# UN/LOCODE, ETA = the planned arrival in AIS form (`MM-DD HH:MM`, no year), transceiver class A (SOLAS ships).
# PostgreSQL holds no dimensions or draught, so those stay `null` rather than invented. The call sign is synthetic and
# visibly so (`NGX` + 4 digits, unique, drawn from a fixed stream); the loader checks it never equals a real call sign.

# %% cell 14
cs_rng = np.random.default_rng([SEED, 0])
call_signs = [f"NGX{n:04d}" for n in cs_rng.choice(10_000, size=len(vessels), replace=False)]
static = vessels[["vessel_id", "mmsi", "imo_number", "vessel_name", "vessel_type", "destination_locode"]].merge(
    voyages[["vessel_id", "arrival_ts", "ais_ship_type"]], on="vessel_id").merge(
    tracks.groupby("vessel_id")["ts"].max().rename("last_seen"), on="vessel_id")
static = pd.DataFrame({
    "vessel_id": static["vessel_id"], "mmsi": static["mmsi"], "imo": static["imo_number"], "call_sign": call_signs,
    "name": static["vessel_name"], "ship_type": static["ais_ship_type"],
    "ship_type_category": static["ais_ship_type"].map({60: "passenger", 70: "cargo", 80: "tanker", 90: "other type"}),
    "length_m": np.nan, "beam_m": np.nan, "draught_m": np.nan,
    "destination_raw": static["destination_locode"], "destination_locode": static["destination_locode"],
    "eta_raw": pd.to_datetime(static["arrival_ts"], utc=True).dt.strftime("%m-%d %H:%M"),
    "transceiver_class": "A", "last_seen": static["last_seen"]})

# %% cell 15
# ---- Phase 5 validation ------------------------------------------------------------------------------------------
assert len(static) == 500 and static["mmsi"].is_unique and static["call_sign"].is_unique
assert (static.set_index("vessel_id")[["mmsi", "imo", "name"]]
        == vv[["mmsi", "imo_number", "vessel_name"]].rename(columns={"imo_number": "imo", "vessel_name": "name"})).all().all()
assert static["ship_type_category"].notna().all() and static["eta_raw"].str.fullmatch(r"\d{2}-\d{2} \d{2}:\d{2}").all()
print("✅ Phase 5 validation passed.")

# %% [markdown] cell 16
# ## Phase 6 — Save, reload, manifest
#
# Three Parquet files and a manifest. `src_row` is the row number in `ais_positions_synthetic.parquet`: the loader stores
# it in every document, so each synthetic fix can be traced back to its artifact row (the same coverage rule as for the
# real samples). The manifest records the seed, the as-of instant, every parameter, the PostgreSQL row hash the tracks
# were generated from, and a content hash per file (pandas row hashes, independent of Parquet encoding details).

# %% cell 17
OUT.mkdir(parents=True, exist_ok=True)
positions_out = tracks[["vessel_id", "mmsi", "imo", "ts", "lat", "lon", "sog", "cog", "heading", "navstat", "phase"]].copy()
positions_out.insert(0, "src_row", np.arange(len(positions_out)))
files = {"ais_positions_synthetic.parquet": positions_out, "ais_vessels_synthetic.parquet": static,
         "voyages_synthetic.parquet": voyages}


def content_sha(df: pd.DataFrame) -> str:
    return hashlib.sha256(pd.util.hash_pandas_object(df, index=False).to_numpy().tobytes()).hexdigest()


for name, df in files.items():
    df.to_parquet(OUT / name, index=False)
manifest = {
    "generator": "Notebooks/semi_structured/AIS_generator.ipynb", "seed": SEED, "asof_utc": ASOF.isoformat(),
    "params": {"harbour_kn": HARBOUR_KN, "teleport_kn": TELEPORT_KN, "move_dt_s": MOVE_DT_S, "stat_dt_s": STAT_DT_S,
               "jitter_s": JITTER_S, "approach_nm": APPROACH_NM, "anchor_before_nm": ANCHOR_BEFORE_NM,
               "pre_departure_h": PRE_DEPARTURE_H, "type_params": TYPE_PARAMS, "status_navstat": STATUS_NAVSTAT},
    "inputs": {"vessels_rows_sha256": vessel_rows_sha, "vessels": len(vessels), "ports": len(ports),
               "port_connections": len(conns), "profiles": ["noaa_profile.json", "aishub_profile.json"]},
    "outputs": {name: {"rows": len(df), "content_sha256": content_sha(df)} for name, df in files.items()},
}
_display_result((OUT / "ais_generation_manifest.json").write_text(json.dumps(manifest, indent=1, default=str) + "\n", encoding="utf-8"))

# %% cell 18
# ---- Phase 6 validation ------------------------------------------------------------------------------------------
reloaded = {name: pd.read_parquet(OUT / name) for name in files}
for name, df in files.items():
    assert content_sha(reloaded[name]) == manifest["outputs"][name]["content_sha256"], f"{name}: reload differs"
assert reloaded["ais_positions_synthetic.parquet"]["src_row"].is_unique
assert str(reloaded["ais_positions_synthetic.parquet"]["ts"].dt.tz) == "UTC"
m2 = json.loads((OUT / "ais_generation_manifest.json").read_text(encoding="utf-8"))
assert m2["outputs"] == json.loads(json.dumps(manifest["outputs"]))
actual_6 = {name: v["content_sha256"] for name, v in manifest["outputs"].items()}
REVIEWED_6 = {  # reviewed 2026-09-27 (sea paths)
    "ais_positions_synthetic.parquet": "2c38de137971aca585893625b747813d55a49b45177e0cdd68baab5710103ae5",
    "ais_vessels_synthetic.parquet": "6327fb306660dba5d9b5582c90f704a15850c49be6e40f3914415244dd983144",
    "voyages_synthetic.parquet": "ce87ae9889d94d73250efdeaa8ad796b901cb587014207923d2915ca888c1b29"}
if REVIEWED_6:
    assert actual_6 == REVIEWED_6, f"artifacts changed: {actual_6}"
else:
    print("snapshot pending review:", json.dumps(actual_6))
print("✅ Phase 6 validation passed.")

# %% [markdown] cell 19
# ## Final Checkpoint

# %% cell 20
final = {"vessels": len(vessels), "fixes": len(tracks), "fallback_routes": REVIEWED_3["fallback_vessels"],
         "status": vessels["status"].value_counts().sort_index().to_dict(),
         "max_implied_kn": actual_4["max_implied_kn"], "teleport_kn": TELEPORT_KN,
         "open_sea_land_share_pct": round(100 * land_share, 2),
         "departure_range": [str(voyages["departure_ts"].min()), str(voyages["departure_ts"].max())],
         "artifacts": sorted(files) + ["ais_generation_manifest.json"]}
REVIEWED_FINAL = {"vessels": 500, "fixes": 1310619, "fallback_routes": [323, 442],
                  "status": {"Anchored": 78, "At Port": 130, "Completed": 73, "In Transit": 219},
                  "max_implied_kn": 19.82, "teleport_kn": 30.0, "open_sea_land_share_pct": 0.96,
                  "departure_range": ["2026-06-24 03:55:08+00:00", "2026-09-12 15:24:41+00:00"],
                  "artifacts": ["ais_positions_synthetic.parquet", "ais_vessels_synthetic.parquet",
                                "voyages_synthetic.parquet", "ais_generation_manifest.json"]}
assert final == REVIEWED_FINAL, f"final summary changed: {final}"
print(json.dumps(final, indent=1))
print("✅ Final Checkpoint validation passed.")

# %% [markdown] cell 21
# Final Checkpoint: see pipelines/checkpoints/semi_structured/AIS_generator.md
