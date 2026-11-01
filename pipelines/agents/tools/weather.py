"""`marine_weather`: waves and wind at route points, one date per point (Agents plan §6a S7; P9-8, F5).

- Waves: Open-Meteo Marine (`wave_height_max`, `swell_wave_height_max`, `wind_wave_height_max`, metres), past and
  future dates in one call (start / end dates; forecast up to MARINE_AHEAD_DAYS ahead).
- Wind: Open-Meteo's Historical Forecast API for dates before today (the first hours of each model run stitched: what
  was forecast, close to what happened — a replay at 2026-09-13 reads this) and the Forecast API from today on
  (up to WIND_AHEAD_DAYS ahead); `wind_speed_10m_max`, `wind_gusts_10m_max` in knots. The result says which API served
  each value.
- All points go in one request per API (Open-Meteo takes comma lists of coordinates); each point keeps the value of
  its own date. Coordinates are rounded to 2 decimals (~1 km) so the cache key is stable.
- Through `external.cached_call` (ADR-049 (5)): 10 s timeout, no retry, any failure of any request →
  `context_unavailable` with no number at all (never half an answer), never cached; past windows cached for good.
- A point on land or beyond the horizon keeps a null value with a note — never a guess. Open-Meteo warns that marine
  data is "not suitable for coastal navigation": the caveat travels with every result. Free non-commercial API,
  CC BY 4.0: credit Open-Meteo.
Access: public external source, level 1 (everyone).
"""
from datetime import date, timedelta

from langchain.tools import ToolRuntime, tool
from pydantic import BaseModel, Field, model_validator

from pipelines.agents.tools import context, external
from pipelines.agents.tools.schemas import Source, ToolResult

MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
WIND_PAST_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
WIND_FUTURE_URL = "https://api.open-meteo.com/v1/forecast"
WAVES = ("wave_height_max", "swell_wave_height_max", "wind_wave_height_max")
WINDS = ("wind_speed_10m_max", "wind_gusts_10m_max")
MAX_POINTS = 30
MAX_WINDOW_DAYS = 92
MARINE_AHEAD_DAYS = 7
WIND_AHEAD_DAYS = 15
CAVEAT = ("Open-Meteo marine data has limited accuracy near coasts and is not suitable for coastal navigation; "
          "weather data by Open-Meteo.com (CC BY 4.0)")


class Point(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    date: date


class WeatherArgs(BaseModel):
    points: list[Point] = Field(min_length=1, max_length=MAX_POINTS,
                                description="route points, each with the date the vessel is there (e.g. the "
                                            "day_points of sea_route with their dates)")

    @model_validator(mode="after")
    def _window(self):
        days = (max(p.date for p in self.points) - min(p.date for p in self.points)).days
        if days >= MAX_WINDOW_DAYS:
            raise ValueError(f"the points' dates span more than {MAX_WINDOW_DAYS} days")
        return self


def _fetch(url: str, variables: tuple[str, ...], lats: list[float], lons: list[float], start: date, end: date,
           extra: dict):
    def fetch(client):
        r = client.get(url, params={"latitude": ",".join(map(str, lats)), "longitude": ",".join(map(str, lons)),
                                    "daily": ",".join(variables), "start_date": start.isoformat(),
                                    "end_date": end.isoformat(), "timezone": "UTC", **extra})
        if r.status_code != 200:
            raise external.Unavailable(f"Open-Meteo HTTP {r.status_code}")
        body = r.json()
        body = body if isinstance(body, list) else [body]
        if len(body) != len(lats):
            raise ValueError("one answer per point expected")
        out = []
        for loc in body:
            d = loc["daily"]
            series = {k: d[k] for k in variables}
            if any(len(v) != len(d["time"]) or not all(x is None or isinstance(x, (int, float)) for x in v)
                   for v in series.values()):
                raise ValueError("daily series of the wrong shape")
            out.append({"time": d["time"], **series})
        return out
    return fetch


# locations sent over the network (cache hits count 0): Open-Meteo counts a multi-location request once per location
# (free: 600 / min) — the voyage watch paces its batches with it (Phase 11, D-P11-2)
SENT = {"requests": 0, "locations": 0}


def _call(url, variables, lats, lons, start, end, extra=None):
    args = {"api": url, "lat": lats, "lon": lons, "start": start.isoformat(), "end": end.isoformat(),
            "daily": list(variables), **(extra or {})}
    try:
        entry, cached = external.cached_call("marine_weather", args, end,
                                             _fetch(url, variables, lats, lons, start, end, extra or {}))
    except external.Unavailable:
        SENT["requests"] += 1                    # a refused request was sent (and counted by the API) too
        SENT["locations"] += len(lats)
        raise
    if not cached:
        SENT["requests"] += 1
        SENT["locations"] += len(lats)
    return entry


def marine_weather(user, **args) -> ToolResult:
    a = WeatherArgs.model_validate(args)
    if not context.permitted(user, context.PUBLIC_EXTERNAL):
        return context.denied("marine_weather")
    today = external.today()
    lats = [round(p.lat, 2) for p in a.points]
    lons = [round(p.lon, 2) for p in a.points]
    first, last = min(p.date for p in a.points), max(p.date for p in a.points)
    calls = []                                       # (url, variables, start, end, extra)
    if first <= today + timedelta(days=MARINE_AHEAD_DAYS):
        calls.append((MARINE_URL, WAVES, first, min(last, today + timedelta(days=MARINE_AHEAD_DAYS)), None))
    if first < today:
        calls.append((WIND_PAST_URL, WINDS, first, min(last, today - timedelta(days=1)), {"wind_speed_unit": "kn"}))
    if last >= today and first <= today + timedelta(days=WIND_AHEAD_DAYS):
        calls.append((WIND_FUTURE_URL, WINDS, max(first, today), min(last, today + timedelta(days=WIND_AHEAD_DAYS)),
                      {"wind_speed_unit": "kn"}))
    try:
        answers = [(url, _call(url, var, lats, lons, s, e, extra)) for url, var, s, e, extra in calls]
    except external.Unavailable as exc:
        return ToolResult(tool="marine_weather", status="context_unavailable",
                          note=f"marine weather unavailable ({exc}); do not estimate it")
    rows, gaps = [], 0
    for i, p in enumerate(a.points):
        row = {"lat": lats[i], "lon": lons[i], "date": p.date.isoformat(), **{k: None for k in WAVES},
               "wind_speed_10m_max_kn": None, "wind_gusts_10m_max_kn": None, "wave_source": None, "wind_source": None}
        for url, entry in answers:
            loc = entry["payload"][i]
            if p.date.isoformat() not in loc["time"]:
                continue
            k = loc["time"].index(p.date.isoformat())
            if url == MARINE_URL:
                row |= {v: loc[v][k] for v in WAVES} | {"wave_source": "Open-Meteo Marine"}
            else:
                row |= {"wind_speed_10m_max_kn": loc["wind_speed_10m_max"][k],
                        "wind_gusts_10m_max_kn": loc["wind_gusts_10m_max"][k],
                        "wind_source": "Open-Meteo Historical Forecast" if url == WIND_PAST_URL else
                        "Open-Meteo Forecast"}
        gaps += any(row[k] is None for k in (*WAVES, "wind_speed_10m_max_kn"))
        rows.append(row)
    note = CAVEAT + (f"; {gaps} of {len(rows)} points without a value (on land, or beyond the forecast horizon of "
                     f"{MARINE_AHEAD_DAYS} days for waves / {WIND_AHEAD_DAYS} for wind): unknown, not calm"
                     if gaps else "")
    retrieved = min(external._retrieved(entry) for _, entry in answers) if answers else None
    return ToolResult(tool="marine_weather", status="ok" if answers else "no_data", rows=rows if answers else [],
                      note=note if answers else "every point is beyond the forecast horizon",
                      source=Source(kind="api", name=", ".join(url for url, _ in answers),
                                    filter=f"{len(rows)} points, {first.isoformat()} … {last.isoformat()}, daily max",
                                    retrieved_at=retrieved) if answers else None)


@tool("marine_weather", args_schema=WeatherArgs)
def marine_weather_tool(runtime: ToolRuntime, **args) -> dict:
    """Daily maximum wave height (m), swell, wind waves, wind speed and gusts (knots) at route points, one date per
    point (e.g. sea_route's day_points with their dates). Public Open-Meteo data; null = unknown (land or beyond the
    forecast horizon)."""
    return marine_weather(context.user_of(runtime), **args).model_dump(mode="json")
