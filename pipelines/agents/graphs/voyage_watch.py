"""The `voyage_watch` graph (C Voyage & Disruption Watch, Agents plan Phase 11, §6c; ADR-055 tools, ADR-057 pattern).

Every N hours (P11-7) and on request: where each of our vessels at sea is, its ETA, the delay risk on its next legs
(weather) and from Suez traffic → alerts, saved (save only, S2-D1). Code computes everything that is a number or a
decision; the model only writes a short brief over the alerts, with number slots, and a code Validator checks it.

- **1 fleet:** the voyages with `departure_ts <= as_of` (known once a vessel has sailed; `arrival_ts` is never used
  to choose, F9) → `voyage_status` at the clock → In Transit (ETA + alerts) and Anchored (listed, P11-10).
- **2 eta:** rule R (`tools/eta.py`, P11-1) + the next-leg points now / +24 / +48 / +72 h.
- **3 weather:** `marine_weather` in batches of ≤ 30 distinct points; a failed batch → its points unknown, said.
- **4 traffic:** PortWatch, the 28 days before the clock vs a year earlier (`route_advice.traffic`), and which
  vessels still have the canal ahead (F10).
- **5 alerts:** the fixed rules of P11-4 → `watch.alerts` (rows keyed `vessel_id/kind`) + `watch.fleet`; the run
  file is written here, before any model call, so a model failure never loses an alert.
- **6 brief / 7 validator:** one structured call of the `writer` role (skill `voyage-watch-brief`) only when there
  are alerts; the Validator: slots bound to the cited alerts, no typed number (copied dates must be a cited alert's),
  every high alert cited; one patch, then the brief is dropped (`validation_failed`) — the alerts stand.
- **8 render:** `VoyageWatchResult`, the run file rewritten with the brief.
Evidence ids `watch.<name>`; results kept as plain data (the checkpoint, P11-5).
"""
# pyright: reportTypedDictNotRequiredAccess=false
# (the state is total=False: a node runs only after the node that sets the keys it reads; LangGraph's config
#  always carries `configurable` — ADR-063 amendment 2)
import json
import operator
import os
import re
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, cast, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from pipelines.agents import skill_loader
from pipelines.agents.deck import slots
from pipelines.agents.deck import validator as v2
from pipelines.agents.graphs import models as m
from pipelines.agents.graphs import route_advice as ra
from pipelines.agents.roles import StructuredError
from pipelines.agents.tools import context, db, eta, vessels, voyages, weather
from pipelines.agents.tools.context import RunContext
from pipelines.agents.tools.schemas import Source, ToolResult
from pipelines.lib.common import project_root

REPORTS_DIR = project_root() / "reports" / "voyage_watch"
WATCHED = ("In Transit", "Anchored")
# P11-4, fixed before any measurement: Douglas sea state 6 / 7, Beaufort 8 / 10, the ADR-057 traffic threshold
WAVE_MODERATE_M, WAVE_HIGH_M = 4.0, 6.0
WIND_MODERATE_KN, WIND_HIGH_KN = 34.0, 48.0
TRAFFIC_MODERATE_PCT, TRAFFIC_HIGH_PCT = -20.0, -40.0
SEVERITY = {"high": 2, "moderate": 1}
CODE = "voyage_watch (code)"


def _result(tool: str, rows: list[dict], flt: str) -> dict:
    return ToolResult(tool=tool, status="ok", rows=rows,
                      source=Source(kind="library", name=CODE, filter=flt)).model_dump(mode="json")


# --- 1 fleet --------------------------------------------------------------------------------------------------------

def fleet(user, as_of: datetime, vessel_ids: list[int] | None = None) -> tuple[list[dict], dict, str | None]:
    """(status rows of the watched vessels, counts by status, stop status or None)."""
    if not context.permitted(user, context.AIS_TRACKS, context.PORTS, context.VESSELS, context.VESSEL_PARAMS):
        return [], {}, "not_permitted"
    voy = voyages.voyages()
    ids = sorted(int(i) for i in voy.index[voy["departure_ts"] <= as_of])
    if vessel_ids is not None:
        ids = [i for i in ids if i in set(vessel_ids)]
    names = {r["vessel_id"]: r["vessel_name"] for r in db.fetch("SELECT vessel_id, vessel_name FROM vessels")}
    rows, counts = [], Counter()
    for vid in ids:
        st = voyages.voyage_status(user, as_of=as_of, vessel_id=vid)
        if st.status != "ok":
            counts["no_fix"] += 1
            continue
        s = st.rows[0]
        counts[s["status_at_as_of"]] += 1
        if s["status_at_as_of"] in WATCHED:
            rows.append(s | {"vessel_name": names.get(vid)})
    return rows, dict(sorted(counts.items())), (None if rows else "no_data")


# --- 2 eta ----------------------------------------------------------------------------------------------------------

def etas(user, rows: list[dict]) -> list[dict]:
    """One row per watched vessel: R for those at sea (+ their next-leg points), "at anchorage" for the others."""
    out = []
    for s in rows:
        base = {"vessel_id": s["vessel_id"], "vessel_name": s["vessel_name"], "status": s["status_at_as_of"],
                "destination": s["destination"], "next_port": s["next_port"],
                "distance_left_nm": s["distance_left_nm"], "last_fix_ts": s["last_fix"]["ts"]}
        if s["status_at_as_of"] != "In Transit":
            out.append(base | {"eta_utc": None, "eta_in_h": None, "speed_kn": None, "points": [],
                               "suez_ahead": False, "note": "at anchorage off its destination: berth time not in the "
                                                            "data, no ETA"})
            continue
        planned = vessels.vessel_params(user, vessel_id=s["vessel_id"]).rows[0]["speed_kn"]
        e = eta.eta_rule(s, planned)
        out.append(base | {"eta_utc": e["eta_utc"], "eta_in_h": e["eta_in_h"], "speed_kn": e["speed_kn"],
                           "speed_source": e["speed_source"], "points": eta.next_leg_points(s["vessel_id"], s, e),
                           "suez_ahead": eta.suez_ahead(s["vessel_id"], s["distance_covered_nm"])})
    return out


# --- 3 weather ------------------------------------------------------------------------------------------------------

def _pkey(p: dict) -> tuple:
    return (round(p["lat"], 2), round(p["lon"], 2), p["date"])


# Open-Meteo's free limit is 600 calls / min counted per location (a 30-point request = 30 calls): the first
# scheduled firing (2026-10-29, 380 vessels, 1,448 points × 2 APIs sent within a minute) lost 848 points → the
# batches are paced under LOCATIONS_PER_MIN of network sends (cache hits are free) and the failed batches retried
# once after RETRY_WAIT_S (D-P11-2). The checks' mocks set both to None / 0.
LOCATIONS_PER_MIN: int | None = 400
RETRY_WAIT_S = 65


def _pace(window: list[tuple[float, int]], need: int) -> None:
    """Wait until `need` more locations fit in the last 60 s of network sends."""
    if LOCATIONS_PER_MIN is None:
        return
    while True:
        now = time.monotonic()
        window[:] = [(t, n) for t, n in window if now - t < 60]
        if sum(n for _, n in window) + need <= LOCATIONS_PER_MIN:
            return
        time.sleep(max(0.5, 60 - (now - window[0][0])))


def weather_at(user, eta_rows: list[dict]) -> tuple[dict, dict]:
    """({point key: weather row or None}, summary). Distinct points sorted (reproducible batches) → marine_weather
    ≤ 30 at a time, paced under Open-Meteo's per-minute limit; a batch that still fails after one retry leaves its
    points unknown (None), counted with the reason, never guessed."""
    keys = sorted({_pkey(p) for r in eta_rows for p in r["points"]}, key=lambda k: (k[2], k[0], k[1]))
    batches = [keys[i:i + weather.MAX_POINTS] for i in range(0, len(keys), weather.MAX_POINTS)]
    out, sources, errors, window, retried = {}, set(), Counter(), [], 0
    for attempt in (1, 2):
        failed = []
        if attempt == 2 and batches:
            retried = sum(len(b) for b in batches)
            time.sleep(RETRY_WAIT_S)
        for batch in batches:
            _pace(window, 3 * len(batch))                 # up to 3 requests (waves, past wind, future wind)
            before = weather.SENT["locations"]
            res = weather.marine_weather(user, points=[{"lat": k[0], "lon": k[1], "date": k[2]} for k in batch])
            window.append((time.monotonic(), weather.SENT["locations"] - before))
            if res.status != "ok":
                failed.append(batch)
                if attempt == 2:
                    errors[(res.note or res.status)[:120]] += 1
                continue
            sources.add(cast(Any, res.source).name)         # status ok: the source is set
            out |= {k: row for k, row in zip(batch, res.rows)}
        batches = failed
        if not failed:
            break
    out |= {k: None for b in batches for k in b}
    unknown = sum(1 for k, w in out.items() if w is None or w["wave_height_max"] is None
                  or w["wind_speed_10m_max_kn"] is None)
    return out, {"weather_points": len(keys), "weather_failed_points": sum(len(b) for b in batches),
                 "weather_unknown_points": unknown, "weather_retried_points": retried,
                 "weather_errors": dict(errors), "weather_sources": sorted(sources)}


# --- 4 traffic ------------------------------------------------------------------------------------------------------

def traffic(user, as_of: datetime) -> dict:
    """route_advice's PortWatch comparison (the 28 days before the clock vs a year earlier), as watch.* evidence."""
    ev = ra.traffic(user, as_of.date())
    out = {"watch.transits": ev["route.transits"], "watch.transits_year_before": ev["route.transits_year_before"]}
    if "route.traffic" in ev:
        out["watch.traffic"] = ev["route.traffic"]
    return out


# --- 5 alerts -------------------------------------------------------------------------------------------------------

def _severity_weather(wave, wind) -> str | None:
    if (wave is not None and wave >= WAVE_HIGH_M) or (wind is not None and wind >= WIND_HIGH_KN):
        return "high"
    if (wave is not None and wave >= WAVE_MODERATE_M) or (wind is not None and wind >= WIND_MODERATE_KN):
        return "moderate"
    return None


def weather_alert(r: dict, wx: dict) -> dict | None:
    """The worst next-leg point of one vessel (highest severity, then the earliest), or None."""
    hits = []
    for p in r["points"]:
        w = wx.get(_pkey(p))
        if not w:
            continue
        sev = _severity_weather(w["wave_height_max"], w["wind_speed_10m_max_kn"])
        if sev:
            hits.append((-SEVERITY[sev], p["hours_ahead_h"], sev, p, w))
    if not hits:
        return None
    _, _, sev, p, w = min(hits, key=lambda h: (h[0], h[1]))
    why = []
    if w["wave_height_max"] is not None and w["wave_height_max"] >= WAVE_MODERATE_M:
        why.append(f"waves {w['wave_height_max']} m ≥ {WAVE_MODERATE_M} m")
    if w["wind_speed_10m_max_kn"] is not None and w["wind_speed_10m_max_kn"] >= WIND_MODERATE_KN:
        why.append(f"wind {w['wind_speed_10m_max_kn']} kn ≥ {WIND_MODERATE_KN} kn")
    return {"date": p["date"], "lat": p["lat"], "lon": p["lon"], "hours_ahead_h": p["hours_ahead_h"],
            "wave_height_max_m": w["wave_height_max"], "wind_speed_10m_max_kn": w["wind_speed_10m_max_kn"],
            "wind_gusts_10m_max_kn": w.get("wind_gusts_10m_max_kn"), "wave_source": w.get("wave_source"),
            "wind_source": w.get("wind_source"), "severity": sev, "reason": "; ".join(why)}


def alerts(eta_rows: list[dict], wx: dict, traffic_ev: dict) -> list[dict]:
    """The rules of P11-4 → alert rows (high first, then by vessel), ids `<vessel_id>/<kind>`."""
    t = (traffic_ev.get("watch.traffic") or {}).get("rows") or []
    change = t[0]["change_transits_pct"] if t else None
    out = []
    for r in eta_rows:
        if r["status"] != "In Transit":
            continue
        base = {"vessel_id": r["vessel_id"], "vessel_name": r["vessel_name"], "destination": r["destination"],
                "next_port": r["next_port"], "eta_utc": r["eta_utc"], "eta_in_h": r["eta_in_h"]}
        w = weather_alert(r, wx)
        if w:
            out.append({"alert_id": f"{r['vessel_id']}/weather", "kind": "weather", **base, **w})
        if r["suez_ahead"] and change is not None and change <= TRAFFIC_MODERATE_PCT:
            sev = "high" if change <= TRAFFIC_HIGH_PCT else "moderate"
            out.append({"alert_id": f"{r['vessel_id']}/suez_traffic", "kind": "suez_traffic", **base,
                        "severity": sev, "change_transits_pct": change,
                        "mean_daily_transits_recent": t[0]["mean_daily_transits_recent"],
                        "mean_daily_transits_year_before": t[0]["mean_daily_transits_year_before"],
                        "date": r["eta_utc"][:10],
                        "reason": f"Suez Canal ahead; transits {change} % vs a year earlier ≤ "
                                  f"{TRAFFIC_MODERATE_PCT} %"})
    return sorted(out, key=lambda a: (-SEVERITY[a["severity"]], a["vessel_id"], a["kind"]))


def fleet_row(as_of: datetime, counts: dict, eta_rows: list[dict], alert_rows: list[dict], wx_summary: dict,
              traffic_ev: dict) -> dict:
    t = (traffic_ev.get("watch.traffic") or {}).get("rows") or []
    sev = Counter(a["severity"] for a in alert_rows)
    return {"as_of": eta._iso(eta._ts(as_of.isoformat())), "vessels_watched": len(eta_rows),
            "in_transit": counts.get("In Transit", 0), "anchored": counts.get("Anchored", 0),
            "at_port": counts.get("At Port", 0), "completed": counts.get("Completed", 0),
            "alerts_total": len(alert_rows), "alerts_high": sev.get("high", 0),
            "alerts_moderate": sev.get("moderate", 0),
            "weather_alerts": sum(a["kind"] == "weather" for a in alert_rows),
            "suez_traffic_alerts": sum(a["kind"] == "suez_traffic" for a in alert_rows),
            "suez_ahead_vessels": sum(r["suez_ahead"] for r in eta_rows),
            "weather_points": wx_summary["weather_points"], "weather_unknown_points": wx_summary["weather_unknown_points"],
            "weather_failed_points": wx_summary["weather_failed_points"],
            "weather_retried_points": wx_summary.get("weather_retried_points", 0),
            "change_transits_pct": t[0]["change_transits_pct"] if t else None}


def deterministic(user, as_of: datetime, vessel_ids: list[int] | None = None) -> dict:
    """Nodes 1–5 together (the check calls it directly): {status, counts, etas, weather_summary, evidence}."""
    rows, counts, stop = fleet(user, as_of, vessel_ids)
    if stop:
        return {"status": stop, "counts": counts, "etas": [], "evidence": {}}
    er = etas(user, rows)
    wx, wsum = weather_at(user, er)
    tev = traffic(user, as_of)
    al = alerts(er, wx, tev)
    ev = tev | {"watch.alerts": _result("watch_alerts", al, "the P11-4 rules over the next-leg weather and Suez "
                                                            "traffic"),
                "watch.fleet": _result("watch_fleet", [fleet_row(as_of, counts, er, al, wsum, tev)],
                                       "the watched fleet at the clock")}
    return {"status": None, "counts": counts, "etas": er, "weather_summary": wsum, "evidence": ev}


# --- 6 brief (one structured call, role writer, skill voyage-watch-brief) ------------------------------------------

MAX_PATCHES = 1
DIGEST_MODERATE = 20                    # the brief reads every high alert and at most this many moderate ones
BRIEF_TASK = """You write the voyage watch brief for NileGate's Operations desk with the skill below. Return a WatchBrief
(call the WatchBrief tool): a headline and up to six items. Every number is a slot over the evidence listed; each item
lists in alert_ids the alerts it is about. Cite every high alert.

{skills}"""
PATCH_TASK = """Code checked your WatchBrief and found these problems:
{problems}
Return the whole WatchBrief again with every problem fixed; keep what was right."""
DIGEST_FIELDS = ("alert_id", "severity", "vessel_name", "destination", "next_port", "eta_utc", "eta_in_h", "date",
                 "hours_ahead_h", "wave_height_max_m", "wind_speed_10m_max_kn", "change_transits_pct", "reason")


def _rows(res: dict | None) -> list[dict]:
    return (res or {}).get("rows") or []


def brief_digest(evidence: dict) -> str:
    """What the brief writer reads: the fleet counts and the alerts (high all, moderate up to DIGEST_MODERATE)."""
    f = _rows(evidence.get("watch.fleet"))[0]
    al = _rows(evidence.get("watch.alerts"))
    high = [a for a in al if a["severity"] == "high"]
    mod = [a for a in al if a["severity"] != "high"]
    lines = [f"[question] the voyage watch at {f['as_of']}: which vessels are at risk on their next legs?",
             "[evidence ids you may cite] watch.fleet (one row), watch.alerts (rows keyed vessel_id/kind, e.g. "
             "watch.alerts[36/weather])", f"[watch.fleet] {json.dumps(f, ensure_ascii=False)}"]
    for a in high + mod[:DIGEST_MODERATE]:
        lines.append("[watch.alerts] " + json.dumps({k: a.get(k) for k in DIGEST_FIELDS if a.get(k) is not None},
                                                    ensure_ascii=False))
    if len(mod) > DIGEST_MODERATE:
        lines.append(f"[note] {len(mod) - DIGEST_MODERATE} more moderate alerts are listed by code in the alert "
                     "table; count them with {watch.fleet:alerts_moderate}")
    return "\n".join(lines)


# --- 7 validator (code) ---------------------------------------------------------------------------------------------

DATE_TOKEN_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?Z?)?\b")


def _strings(evidence: dict) -> list[str]:
    """Identifiers that may hold digits and are not numbers: vessel names ("Special Voyager 001"), LOCODEs, alert
    ids (F11) — longest first, so a name is blanked before a shorter part of it."""
    al = _rows(evidence.get("watch.alerts"))
    out = {a["vessel_name"] for a in al if a.get("vessel_name")} | {a["alert_id"] for a in al}
    out |= {a[k] for a in al for k in ("destination", "next_port") if a.get(k)}
    return sorted(out, key=len, reverse=True)


def validate(brief: dict, evidence: dict) -> list[str]:
    """The problems of a WatchBrief (empty = it passes): cited alerts exist; every slot resolves and cites
    watch.alerts / watch.fleet, an alert slot only an alert its item cites; no typed number (names, LOCODEs and alert
    ids blanked, F11); a copied date = the date or ETA of a cited alert (or the clock's day); every high alert cited."""
    problems = []
    al = {a["alert_id"]: a for a in _rows(evidence.get("watch.alerts"))}
    cited_all = {i for it in brief["items"] for i in it["alert_ids"]}
    texts = [("headline", brief["headline"], sorted(cited_all))]
    texts += [(f"items[{i}]", it["text"], it["alert_ids"]) for i, it in enumerate(brief["items"])]
    strings = _strings(evidence)
    clock_day = _rows(evidence.get("watch.fleet"))[0]["as_of"][:10]
    for where, text, ids in texts:
        unknown = [i for i in ids if i not in al]
        if unknown:
            problems.append(f"{where}: cites alerts that do not exist {unknown}")
        _, bound, errors = slots.render_text(text, evidence)
        problems += [f"{where}: {e}" for e in errors]
        for b in bound:
            if b.slot.eid not in ("watch.alerts", "watch.fleet"):
                problems.append(f"{where}: {b.slot.raw} — cite watch.alerts or watch.fleet only")
            elif b.slot.eid == "watch.alerts" and b.row is not None:
                aid = _rows(evidence["watch.alerts"])[b.row]["alert_id"]
                if aid not in ids:
                    problems.append(f"{where}: {b.slot.raw} is about alert {aid}, not in its alert_ids")
        plain = slots.SLOT_RE.sub(" ", text)
        allowed = {al[i][k].rstrip("Z") for i in ids if i in al for k in ("date", "eta_utc") if al[i].get(k)}
        allowed |= {d[:10] for d in allowed} | {clock_day}
        for d in DATE_TOKEN_RE.findall(plain):
            if d.rstrip("Z").replace(" ", "T") not in allowed:
                problems.append(f"{where}: date {d} is not the date or ETA of an alert it cites")
        typed = v2.number_tokens(plain, strings)
        if typed:
            problems.append(f"{where}: number(s) typed instead of a slot: {[t[0] for t in typed]}")
    missing = sorted(i for i, a in al.items() if a["severity"] == "high" and i not in cited_all)
    if missing:
        problems.append(f"high alerts not cited by any item: {missing}")
    return problems


def normalize_brief(brief: dict, evidence: dict) -> tuple[dict, list[str]]:
    """The slot-form fixes of Stage 1 (a unit written twice, a disallowed format, …); numbers are never touched."""
    fixes = []
    brief = json.loads(json.dumps(brief))
    brief["headline"], f = slots.normalize_text(brief["headline"], evidence)
    fixes += f
    for it in brief["items"]:
        it["text"], f = slots.normalize_text(it["text"], evidence)
        fixes += f
    return brief, fixes


# --- 8 render + the run file ----------------------------------------------------------------------------------------

def assumptions(evidence: dict) -> list[str]:
    f = _rows(evidence.get("watch.fleet"))[0]
    out = [f"ETA = distance left along the route / recent sea speed (mean SOG of the last 6 h) + the last "
           f"{eta.APPROACH_NM:g} nm at {eta.harbour_kn()} kn (real NOAA harbour sample); no port stops, no weather "
           "or congestion slow-down modelled (synthetic tracks).",
           f"Weather alert: daily maximum waves ≥ {WAVE_MODERATE_M} m or wind ≥ {WIND_MODERATE_KN:g} kn at the "
           f"vessel's position now and at +24 / +48 / +72 h (high: ≥ {WAVE_HIGH_M} m or ≥ {WIND_HIGH_KN:g} kn); "
           "Open-Meteo data, not for coastal navigation; a missing value is unknown, not calm.",
           f"Suez traffic alert: the canal ahead and IMF PortWatch transits of the 28 days before the clock "
           f"≤ {TRAFFIC_MODERATE_PCT:g} % vs a year earlier (high ≤ {TRAFFIC_HIGH_PCT:g} %)."]
    if f["weather_unknown_points"]:
        out.append(f"{f['weather_unknown_points']} of {f['weather_points']} weather points without a value "
                   "(land, coast, beyond the horizon or the service failed): no alert can come from them.")
    if f["weather_failed_points"]:
        out.append(f"{f['weather_failed_points']} weather points failed after one retry (Open-Meteo did not answer): "
                   "this run's weather alerts are incomplete.")
    if f["change_transits_pct"] is None:
        out.append("Suez traffic context unavailable (IMF PortWatch did not answer): no traffic alert this run.")
    return out


def sources(evidence: dict) -> list[dict]:
    return [{"evidence": eid, "tool": res["tool"], "status": res["status"], **(res.get("source") or {})}
            for eid, res in sorted(evidence.items())]


def stamp(as_of: datetime) -> str:
    return as_of.strftime("%Y%m%dT%H%MZ")


def run_file_path(folder: Path, thread_id: str) -> Path:
    return folder / (thread_id.replace(":", "_") + ".json")


def write_run_file(folder: Path, thread_id: str, result: dict) -> str:
    """reports/voyage_watch/<thread id, ':' → '_'>.json, written atomically (save only, P11-5)."""
    folder.mkdir(parents=True, exist_ok=True)
    path = run_file_path(folder, thread_id)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"thread_id": thread_id, **result}, ensure_ascii=False, indent=1, sort_keys=True)
                   + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, path)
    return str(path)


def eta_table(eta_rows: list[dict]) -> list[dict]:
    return [{k: r.get(k) for k in ("vessel_id", "vessel_name", "status", "destination", "next_port", "eta_utc",
                                   "eta_in_h", "distance_left_nm", "speed_kn", "suez_ahead", "last_fix_ts", "note")}
            for r in eta_rows]


def result_of(state: dict, as_of: datetime) -> dict:
    """The VoyageWatchResult fields from a state (the alerts node writes it before the brief, render after)."""
    ev = state.get("evidence") or {}
    status = state.get("status") or "ok"
    out = {"status": status, "as_of": as_of.isoformat(), "problems": state.get("problems") or [],
           "sources": sources(ev)}
    if status != "ok":
        return out | {"fleet": {"counts": state.get("counts") or {}}}
    out |= {"fleet": _rows(ev.get("watch.fleet"))[0] | {"counts": state.get("counts") or {},
                                                        "weather_errors": (state.get("weather_summary") or {})
                                                        .get("weather_errors") or {}},
            "etas": eta_table(state.get("etas") or []), "alerts": _rows(ev.get("watch.alerts")),
            "brief_status": state.get("brief_status"), "assumptions": assumptions(ev)}
    if state.get("brief_status") == "ok":
        fill = lambda t: slots.render_text(t, ev)[0]          # noqa: E731
        b = state["brief"]
        out |= {"headline": fill(b["headline"]),
                "items": [{"text": fill(it["text"]), "alert_ids": it["alert_ids"]} for it in b["items"]],
                "problems": []}
    return out


# --- the graph ------------------------------------------------------------------------------------------------------

class WatchState(TypedDict, total=False):
    request: dict
    status: str | None
    counts: dict
    vessels: list[dict]
    etas: list[dict]
    weather: dict
    weather_summary: dict
    evidence: dict
    brief: dict
    brief_status: str | None
    problems: list[str]
    patches: int
    normalized: list[str]
    llm_usage: Annotated[list[dict], operator.add]
    run_file: str
    result: dict


def _wx_out(wx: dict) -> dict:
    return {"|".join(map(str, k)): v for k, v in wx.items()}            # tuple keys → plain JSON for the checkpoint


def _wx_in(wx: dict) -> dict:
    return {(float(k.split("|")[0]), float(k.split("|")[1]), k.split("|")[2]): v for k, v in wx.items()}


def _thread(config) -> str:
    return config["configurable"]["thread_id"]


def make_nodes(roles, reports_dir: Path) -> dict:
    def node_fleet(state: WatchState, runtime: Runtime[RunContext]) -> dict:
        req = m.WatchRequest.model_validate(state.get("request") or {})
        rows, counts, stop = fleet(runtime.context.user, runtime.context.as_of, req.vessel_ids)
        return {"vessels": rows, "counts": counts, "status": stop}

    def node_eta(state: WatchState, runtime: Runtime[RunContext]) -> dict:
        return {"etas": etas(runtime.context.user, state["vessels"])}

    def node_weather(state: WatchState, runtime: Runtime[RunContext]) -> dict:
        wx, wsum = weather_at(runtime.context.user, state["etas"])
        return {"weather": _wx_out(wx), "weather_summary": wsum}

    def node_traffic(state: WatchState, runtime: Runtime[RunContext]) -> dict:
        return {"evidence": traffic(runtime.context.user, runtime.context.as_of)}

    def node_alerts(state: WatchState, runtime: Runtime[RunContext], config) -> dict:
        tev, as_of = state["evidence"], runtime.context.as_of
        al = alerts(state["etas"], _wx_in(state["weather"]), tev)
        ev = tev | {"watch.alerts": _result("watch_alerts", al, "the P11-4 rules over the next-leg weather and Suez "
                                                                "traffic"),
                    "watch.fleet": _result("watch_fleet", [fleet_row(as_of, state["counts"], state["etas"], al,
                                                                     state["weather_summary"], tev)],
                                           "the watched fleet at the clock")}
        brief_status = None if al else "no_alerts"
        # saved before any model call (P11-5): a brief that fails, or a crash in it, never loses an alert
        path = write_run_file(reports_dir, _thread(config),
                              result_of({**state, "evidence": ev, "brief_status": brief_status}, as_of))
        return {"evidence": ev, "brief_status": brief_status, "run_file": path}

    def node_brief(state: WatchState) -> dict:
        skills = "\n\n".join(skill_loader.load(s) for s in ("voyage-watch-brief", "untrusted-content"))
        msgs = [SystemMessage(BRIEF_TASK.format(skills=skills)), HumanMessage(brief_digest(state["evidence"]))]
        if state.get("problems"):
            msgs.append(HumanMessage(PATCH_TASK.format(problems="\n".join(f"- {p}" for p in state["problems"]))
                                     + "\n[your previous WatchBrief]\n" + json.dumps(state["brief"])))
        try:
            reply = roles.get("writer").structured(msgs, m.WatchBrief)
        except StructuredError as exc:
            return {"brief_status": "output_invalid", "problems": [f"brief: {str(exc)[:300]}"],
                    "llm_usage": [{"node": "brief", **c} for c in exc.calls]}
        draft, fixes = normalize_brief(reply.parsed.model_dump(mode="json"), state["evidence"])
        return {"brief": draft, "patches": state.get("patches", 0) + bool(state.get("problems")),
                "normalized": (state.get("normalized") or []) + fixes,
                "llm_usage": [{"node": "brief", **c} for c in reply.calls]}

    def node_validator(state: WatchState) -> dict:
        problems = validate(state["brief"], state["evidence"])
        if problems and state.get("patches", 0) >= MAX_PATCHES:
            return {"problems": problems, "brief_status": "validation_failed"}
        return {"problems": problems, "brief_status": None if problems else "ok"}

    def node_render(state: WatchState, runtime: Runtime[RunContext], config) -> dict:
        out = result_of(cast(dict, state), runtime.context.as_of)
        if out["status"] == "ok":
            out["run_file"] = str(run_file_path(reports_dir, _thread(config)))
        res = m.VoyageWatchResult.model_validate(out).model_dump(mode="json")
        if out["status"] == "ok":                 # the file = the final result (the alerts node wrote it first)
            write_run_file(reports_dir, _thread(config), res)
        return {"result": res, "status": out["status"]}

    return {"fleet": node_fleet, "eta": node_eta, "weather": node_weather, "traffic": node_traffic,
            "alerts": node_alerts, "brief": node_brief, "validator": node_validator, "render": node_render}


def _after_fleet(state):
    return "render" if state.get("status") else "eta"


def _after_alerts(state):
    return "render" if state.get("brief_status") == "no_alerts" else "brief"


def _after_brief(state):
    return "render" if state.get("brief_status") == "output_invalid" else "validator"


def _after_validator(state):
    return "render" if state.get("brief_status") in ("ok", "validation_failed") else "brief"


def build_graph(roles, checkpointer=None, reports_dir: Path = REPORTS_DIR):
    """The compiled voyage watch graph; `roles` = `roles.Roles()` (real models) or `roles.FakeRoles(script)`. Invoke
    with {"request": WatchRequest dump}, `context=RunContext(user, as_of=…)` and a thread id (`new_thread_id`)."""
    g = StateGraph(WatchState, context_schema=RunContext)
    for name, fn in make_nodes(roles, reports_dir).items():
        g.add_node(name, fn)
    g.add_edge(START, "fleet")
    g.add_conditional_edges("fleet", _after_fleet, ["eta", "render"])
    g.add_edge("eta", "weather")
    g.add_edge("weather", "traffic")
    g.add_edge("traffic", "alerts")
    g.add_conditional_edges("alerts", _after_alerts, ["brief", "render"])
    g.add_conditional_edges("brief", _after_brief, ["validator", "render"])
    g.add_conditional_edges("validator", _after_validator, ["brief", "render"])
    g.add_edge("render", END)
    return g.compile(checkpointer=checkpointer)


THREAD_PREFIX = "voyage_watch:"


def thread_prefix(as_of: datetime, prefix: str = THREAD_PREFIX) -> str:
    return f"{prefix}{stamp(as_of)}:"


def new_thread_id(pool, as_of: datetime, prefix: str = THREAD_PREFIX) -> str:
    """`voyage_watch:<as_of %Y%m%dT%H%MZ>:<n>`, n = the next free number (P11-5)."""
    p = thread_prefix(as_of, prefix)
    with pool.connection() as conn:
        rows = conn.execute("SELECT DISTINCT thread_id FROM checkpoints WHERE thread_id LIKE %s",
                            (p.replace("_", r"\_") + "%",)).fetchall()
    used = [int(x.group(1)) for r in rows if (x := re.fullmatch(re.escape(p) + r"(\d+)", r["thread_id"]))]
    return f"{p}{max(used, default=0) + 1}"


def parse_thread(thread_id: str, prefix: str = THREAD_PREFIX) -> tuple[datetime, int] | None:
    """(the run's clock, n) of `<prefix><%Y%m%dT%H%MZ>:<n>`; other ids are not ours."""
    x = re.fullmatch(re.escape(prefix) + r"(\d{8}T\d{4}Z):(\d+)", thread_id)
    if not x:
        return None
    return datetime.strptime(x[1], "%Y%m%dT%H%MZ").replace(tzinfo=context.DATA_AS_OF.tzinfo), int(x[2])
