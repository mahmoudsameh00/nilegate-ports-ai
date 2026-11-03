"""`sea_route`: the sea path between two ports, with passages closed on request (Agents plan §6a S2, P9-4, F1).

- Path = `searoute` 1.6.0 over the Eurostat MARNET network, run locally (no network call, deterministic). "Suez or the
  Cape" is the same call twice: once as is, once with `avoid=["suez"]` (the library's passage restrictions, verified
  2026-10-27: Singapore ↔ Rotterdam 8,383 / 11,871 nm vs the published 8,288 / 11,755). `northwest` (the Arctic
  passage) is always closed, as in the library's default.
- Length = the generator's rule (AIS_generator `sea_leg`, ADR-032 amendment): the two port points are added at the ends
  of the network path and the great-circle steps are summed, so a route here and a synthetic voyage's `route_nm` are
  measured the same way (`voyage_status` rebuilds those routes with the same helpers).
- No path with these passages closed (a port inside the Gulf of Suez with Suez closed, F1b): `searoute` returns length
  0 with a warning → `no_data`, never a guess. An unknown UN/LOCODE → `no_data`.
- With `speed_kn`, the sea days at that constant speed (harbour legs not modelled) and the position at the end of each
  sea day: the points `marine_weather` reads the weather at.
Access: `ports` is level 1 / Operations (everyone, `docs/rbac_mapping.md` §2).
"""
import warnings
from typing import cast, Literal

import numpy as np
import searoute
from langchain.tools import ToolRuntime, tool
from pydantic import BaseModel, Field, model_validator

from pipelines.agents.tools import context, db
from pipelines.agents.tools.schemas import Source, ToolResult

R_NM = 3440.065                      # = the generator's Earth radius in nautical miles
PASSAGES = ("suez", "babalmandab", "panama", "gibraltar", "bosporus", "ormuz", "malacca", "sunda")
ALWAYS_CLOSED = ("northwest",)
MAX_WAYPOINTS = 60
MAX_DAY_POINTS = 60                  # 60 sea days ≥ any voyage between our ports, even round the Cape at low speed
LOCODE = r"^[A-Z]{2}[A-Z2-9]{3}$"

_ports: dict[str, tuple[float, float]] | None = None


def ports() -> dict[str, tuple[float, float]]:
    """UN/LOCODE → (lat, lon) of every port in the database (837), read once."""
    global _ports
    if _ports is None:
        _ports = {r["locode"]: (float(r["lat"]), float(r["lon"]))
                  for r in db.fetch("SELECT locode, lat, lon FROM ports")}
    return _ports


def _xyz(lat, lon):
    la, lo = np.radians(lat), np.radians(lon)
    return np.stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)], axis=-1)


def gc_nm(lat1, lon1, lat2, lon2):
    """Great-circle distance (nm), the generator's formula."""
    a, b = _xyz(lat1, lon1), _xyz(lat2, lon2)
    return R_NM * np.arctan2(np.linalg.norm(np.cross(a, b), axis=-1), np.sum(a * b, axis=-1))


def _searoute(a, b, closed):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)      # "No path found …" is answered by the callers
        return searoute.searoute([a[1], a[0]], [b[1], b[0]], units="naut", restrictions=list(closed),
                                 return_passages=True)


def _with_ports(a, b, f):
    c = np.array(f["geometry"]["coordinates"], dtype=float).reshape(-1, 2)
    return np.r_[a[0], c[:, 1], b[0]], np.r_[a[1], (c[:, 0] + 180) % 360 - 180, b[1]]


def sea_leg(a: tuple[float, float], b: tuple[float, float]):
    """(lat, lon) of one leg of a synthetic voyage, exactly the generator's `sea_leg`: the network path with the port
    points at its ends, even when the network part has length 0 (two ports snapped to the same node)."""
    return _with_ports(a, b, _searoute(a, b, ALWAYS_CLOSED))


def sea_path(a: tuple[float, float], b: tuple[float, float], closed: tuple[str, ...] = ALWAYS_CLOSED):
    """(lat, lon, passages) of the sea path a → b with the port points at its ends; None when there is no path."""
    f = cast(dict, _searoute(a, b, closed))
    if f["properties"]["length"] <= 0 or len(f["geometry"]["coordinates"]) < 2:
        return None
    lat, lon = _with_ports(a, b, f)
    return lat, lon, sorted(f["properties"].get("traversed_passages") or [])


def line(lat, lon) -> dict:
    """A polyline with its cumulative length; repeated vertices dropped (the generator's `build_route` rule)."""
    step = gc_nm(lat[:-1], lon[:-1], lat[1:], lon[1:])
    keep = np.r_[True, step > 0.01]
    lat, lon = lat[keep], lon[keep]
    return {"lat": lat, "lon": lon, "cum": np.r_[0, np.cumsum(gc_nm(lat[:-1], lon[:-1], lat[1:], lon[1:]))]}


def point_at(r: dict, s) -> tuple[np.ndarray, np.ndarray]:
    """Positions (lat, lon) at along-route distances s (nm), on the great circle of each step."""
    s = np.atleast_1d(np.asarray(s, dtype=float))
    i = np.clip(np.searchsorted(r["cum"], s, side="right") - 1, 0, len(r["cum"]) - 2)
    frac = np.clip((s - r["cum"][i]) / (r["cum"][i + 1] - r["cum"][i]), 0, 1)[:, None]
    a, b = _xyz(r["lat"][i], r["lon"][i]), _xyz(r["lat"][i + 1], r["lon"][i + 1])
    om = np.arctan2(np.linalg.norm(np.cross(a, b), axis=-1), np.sum(a * b, axis=-1))[:, None]
    p = np.where(om > 1e-12, (np.sin((1 - frac) * om) * a + np.sin(frac * om) * b) / np.where(om > 1e-12, np.sin(om), 1),
                 a)
    return np.degrees(np.arctan2(p[:, 2], np.hypot(p[:, 0], p[:, 1]))), np.degrees(np.arctan2(p[:, 1], p[:, 0]))


def _simplified(r: dict) -> list[list[float]]:
    n = len(r["lat"])
    idx = range(n) if n <= MAX_WAYPOINTS else np.unique(np.linspace(0, n - 1, MAX_WAYPOINTS).round().astype(int))
    return [[round(float(r["lat"][k]), 4), round(float(r["lon"][k]), 4)] for k in idx]


class RouteArgs(BaseModel):
    origin: str = Field(pattern=LOCODE, description="UN/LOCODE of the departure port, e.g. SGSIN")
    destination: str = Field(pattern=LOCODE, description="UN/LOCODE of the arrival port, e.g. NLRTM")
    avoid: list[Literal[PASSAGES]] = Field(default_factory=list, max_length=len(PASSAGES),  # pyright: ignore[reportInvalidTypeForm]
                                           description="passages to keep closed, e.g. ['suez'] for the route round "
                                                       "the Cape of Good Hope; empty = the shortest sea route")
    speed_kn: float | None = Field(default=None, ge=4, le=25, description="constant speed in knots, to get the sea "
                                                                          "days and the position at the end of each day")

    @model_validator(mode="after")
    def _distinct(self):
        if self.origin == self.destination:
            raise ValueError("origin and destination must differ")
        return self


def sea_route(user, **args) -> ToolResult:
    a = RouteArgs.model_validate(args)
    if not context.permitted(user, context.PORTS):
        return context.denied("sea_route")
    closed = (*ALWAYS_CLOSED, *sorted(set(a.avoid)))
    flt = f"{a.origin} → {a.destination}, restrictions={list(closed)}"
    src = Source(kind="library", name="searoute 1.6.0 (Eurostat MARNET) + public.ports", filter=flt)
    known = ports()
    missing = [c for c in (a.origin, a.destination) if c not in known]
    if missing:
        return ToolResult(tool="sea_route", status="no_data", note=f"unknown UN/LOCODE {', '.join(missing)}")
    p = sea_path(known[a.origin], known[a.destination], closed)
    if p is None:
        return ToolResult(tool="sea_route", status="no_data",
                          note=f"no sea route from {a.origin} to {a.destination} with {', '.join(closed)} closed")
    r = line(p[0], p[1])
    dist = float(r["cum"][-1])
    row = {"origin": a.origin, "destination": a.destination, "avoid": sorted(set(a.avoid)),
           "distance_nm": round(dist, 1), "passages": p[2], "waypoints": _simplified(r)}
    note = None
    if a.speed_kn is not None:
        per_day = a.speed_kn * 24
        days = dist / per_day
        ends = np.arange(1, min(int(np.ceil(days)), MAX_DAY_POINTS) + 1) * per_day
        lat, lon = point_at(r, np.minimum(ends, dist))
        row |= {"speed_kn": a.speed_kn, "sea_days": round(days, 2),
                "day_points": [{"day": k + 1, "lat": round(float(la), 4), "lon": round(float(lo), 4)}
                               for k, (la, lo) in enumerate(zip(lat, lon))]}
        note = "sea days at a constant speed (harbour legs and canal waiting not modelled)"
    return ToolResult(tool="sea_route", status="ok", rows=[row], source=src, note=note)


@tool("sea_route", args_schema=RouteArgs)
def sea_route_tool(runtime: ToolRuntime, **args) -> dict:
    """Sea route between two ports (UN/LOCODE): distance in nautical miles, the straits and canals passed, simplified
    waypoints; close passages with `avoid` (e.g. ['suez'] = round the Cape); with `speed_kn`, the sea days and the
    position at the end of each day."""
    return sea_route(context.user_of(runtime), **args).model_dump(mode="json")
