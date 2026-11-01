"""The saved voyage-watch runs as a tool (Agents plan Phase 12, §6d S2; the runs: ADR-058, `graphs/voyage_watch.py`).

`watch_alerts` reads one saved run file of `reports/voyage_watch/` — the latest run **at or before the run context's
clock** (S2 decision 2, as ADR-055's clock: the model never picks the run, so it can never read a run made after its
clock) — and returns its alerts (one row per alert, keyed `alert_id`) plus one row `alert_id = "fleet"` with the
run's fleet counts (vessels watched, in transit, alerts, Suez-ahead vessels, `change_transits_pct`). Every row
carries the run's `thread_id`; `source.filter` names the run.

`read_alerts` / `can_read` / `run_files` moved here from the CLI `pipelines/scripts/agents/Voyage_watch.py` (which
imports them; behaviour unchanged): a tool must not import a script.

Access: the runs hold level-1 / Operations data (AIS tracks, ports, vessels, the fuel parameters behind the ETAs):
every employee may read them, the identity is still checked (ADR-006, P11-8).
"""
import json
import re
from datetime import datetime
from pathlib import Path

from langchain.tools import ToolRuntime, tool
from pydantic import BaseModel, Field

from pipelines.agents.graphs import voyage_watch as vw
from pipelines.agents.tools import context, db
from pipelines.agents.tools.schemas import Source, ToolResult

RUN_FILE = re.compile(r"voyage_watch\w*?_(\d{8}T\d{4}Z)_(\d+)")
STAMP = "%Y%m%dT%H%MZ"


def can_read(user) -> bool:
    """The saved alerts hold level-1 Operations data (AIS tracks, ports, vessels): ADR-006 decides (P11-8)."""
    return context.permitted(user, context.AIS_TRACKS, context.PORTS, context.VESSELS, context.VESSEL_PARAMS)


def _runs(folder: Path) -> list[tuple[tuple[str, int], Path]]:
    found = []
    for p in folder.glob("voyage_watch*.json"):               # = the thread id with ':' → '_' (any watch prefix)
        x = RUN_FILE.fullmatch(p.stem)
        if x:
            found.append(((x[1], int(x[2])), p))
    return sorted(found)


def run_files(folder: Path = vw.REPORTS_DIR) -> list[Path]:
    """The run files, oldest first (by the run's clock, then its number)."""
    return [p for _, p in _runs(folder)]


def read_alerts(user, thread: str | None = None, vessel: int | None = None, high: bool = False,
                folder: Path = vw.REPORTS_DIR) -> dict:
    """The saved alerts of one run (the latest by default), filtered; refused when the identity may not read them."""
    if not can_read(user):
        return {"status": "not_permitted", "note": "not permitted for this user (ADR-006)"}
    files = [vw.run_file_path(folder, thread)] if thread else run_files(folder)[-1:]
    if not files or not files[0].exists():
        return {"status": "no_data", "note": "no saved watch run" + (f" for {thread}" if thread else "")}
    r = json.loads(files[0].read_text(encoding="utf-8"))
    al = [a for a in r.get("alerts") or [] if (vessel is None or a["vessel_id"] == vessel)
          and (not high or a["severity"] == "high")]
    return {"status": "ok", "thread_id": r["thread_id"], "as_of": r["as_of"], "brief_status": r.get("brief_status"),
            "headline": r.get("headline"), "alerts": al, "of": len(r.get("alerts") or [])}


def run_at(as_of: datetime, folder: Path = vw.REPORTS_DIR) -> Path | None:
    """The latest saved run whose clock is at or before `as_of` (then the highest run number), or None."""
    cut = as_of.strftime(STAMP)
    runs = [p for (stamp, _), p in _runs(folder) if stamp <= cut]
    return runs[-1] if runs else None


class WatchArgs(BaseModel):
    vessel_id: int | None = Field(default=None, ge=1, description="only this vessel's alerts (the fleet row is "
                                                                  "always returned)")
    vessel_ids: list[int] | None = Field(default=None, min_length=1, max_length=50,
                                         description="only the alerts of these vessels (e.g. the vessels of overdue "
                                                     "invoices)")
    customer_ids: list[int] | None = Field(default=None, min_length=1, max_length=40,
                                           description="only the alerts of these customers' vessels (customer_id from "
                                                       "finance_kpi)")
    high_only: bool = Field(default=False, description="only the high alerts")


def watch_alerts(user, as_of: datetime | None = None, folder: Path = vw.REPORTS_DIR, **args) -> ToolResult:
    a = WatchArgs.model_validate(args)
    as_of = context.RunContext(user, as_of=as_of or context.DATA_AS_OF).as_of      # the clock rules of the context
    if not can_read(user):
        return context.denied("watch_alerts")
    path = run_at(as_of, folder)
    clock = as_of.strftime(STAMP)
    if path is None:
        return ToolResult(tool="watch_alerts", status="no_data", note=f"no saved voyage-watch run at or before {clock}")
    r = json.loads(path.read_text(encoding="utf-8"))
    tid = r["thread_id"]
    alerts = r.get("alerts") or []
    # c1 C-d (Agents plan Phase 12): the join in code — each alert's vessel → its customer_id (`vessels`, a level-1
    # id); the customer's name and money stay in finance_kpi
    vids = sorted({x["vessel_id"] for x in alerts})
    cust = {row["vessel_id"]: row["customer_id"] for row in
            db.fetch("SELECT vessel_id, customer_id FROM vessels WHERE vessel_id = ANY(%s)", (vids,))} if vids else {}
    keep_v = set(a.vessel_ids or []) | ({a.vessel_id} if a.vessel_id is not None else set())
    keep_c = set(a.customer_ids or [])
    al = [{"alert_id": x["alert_id"], **x, "customer_id": cust.get(x["vessel_id"]), "thread_id": tid} for x in alerts
          if (not keep_v or x["vessel_id"] in keep_v) and (not keep_c or cust.get(x["vessel_id"]) in keep_c)
          and (not a.high_only or x["severity"] == "high")]
    by_c: dict[int, list[dict]] = {}
    for x in al:
        if x["customer_id"] is not None:
            by_c.setdefault(x["customer_id"], []).append(x)
    customers = [{"alert_id": f"customer/{c}", "customer_id": c,
                  "vessels_with_alerts": len({x["vessel_id"] for x in xs}), "alerts": len(xs),
                  "high_alerts": sum(x["severity"] == "high" for x in xs), "thread_id": tid}
                 for c, xs in sorted(by_c.items(), key=lambda kv: (-len({x["vessel_id"] for x in kv[1]}), kv[0]))]
    fleet = {"alert_id": "fleet", **{k: v for k, v in (r.get("fleet") or {}).items()
                                     if isinstance(v, (int, float)) and not isinstance(v, bool)}, "thread_id": tid}
    flt = (f"the latest saved run at or before {clock}: {tid} (clock {r['as_of']})"
           + (f"; vessel_id IN {sorted(keep_v)}" if keep_v else "")
           + (f"; customer_id IN {sorted(keep_c)}" if keep_c else "")
           + ("; severity = high" if a.high_only else ""))
    note = (f"{len(al)} of {len(r.get('alerts') or [])} alerts of the run; brief {r.get('brief_status')}; "
            "rules: waves ≥ 4 m or wind ≥ 34 kn (high 6 m / 48 kn) at now / +24 / +48 / +72 h, Suez traffic ≤ −20 % "
            "(high −40 %) with the canal ahead; a missing weather value is unknown, never calm")
    return ToolResult(tool="watch_alerts", status="ok", rows=al + customers + [fleet], note=note,
                      source=Source(kind="table", name=f"reports/voyage_watch/{path.name}", filter=flt))


@tool("watch_alerts", args_schema=WatchArgs)
def watch_alerts_tool(runtime: ToolRuntime, **args) -> dict:
    """The alerts of the latest voyage watch (weather on the vessels' next legs, Suez traffic) as of the run's clock,
    and the fleet's counts (vessels in transit, at anchor, alerts, vessels with the Suez Canal ahead, the Suez traffic
    change vs a year earlier). Each alert row has its vessel's customer_id and a severity (high / moderate: name it);
    one row per customer with alerts (`customer/<id>`: vessels_with_alerts, high_alerts); filter by vessel_ids or
    customer_ids to join with finance rows in one call."""
    return watch_alerts(context.user_of(runtime), as_of=context.as_of_of(runtime), **args).model_dump(mode="json")
