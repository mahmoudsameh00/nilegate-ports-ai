"""The product graphs as tools of the supervisor (Agents plan Phase 12, §6d P12-2, S2).

`route_advice` runs the ADR-057 graph (`graphs/route_advice.py`) as one tool call: its own PostgresSaver thread
`route_advice:<employee>:<as_of>:<from>-<to>:<n>` (resumable, kept 30 days by the same retention as the CLI's), the
run context's user and clock, its own Validator and number slots — the supervisor only cites its rows, it never
recomputes a route number. Built per agent by `make_route_advice_tool(roles)`, so a check injects fake roles. Inside
a traced supervisor question the graph's runs appear under that question's trace (no trace of its own here).

Rows (the contract the S2 Q&A golden items fix): the graph's code results, one row per `route` — `suez` / `cape` /
`direct` (route.compare), `difference` (Cape − Suez, with `cheaper_route`), `traffic` (Suez transits vs a year
earlier, when PortWatch answered) — plus one row `route = "advice"`: the graph status, the recommendation, the
rendered headline / reasons / risks / assumptions and the `thread_id`.

Statuses (S2 decision 3): ok / no_suez_on_route / suez_only → `ok` with the rows; an advice its Validator stops
(`validation_failed`) or an unreadable model reply (`output_invalid`) → still `ok` with the code rows and the advice row
marked with that status and no recommendation (the numbers are the code's; only the words failed); not_permitted /
no_data → the same status, no rows. Access is checked by the graph's tools before any model call (level 1).
"""
from datetime import datetime

from langchain.tools import ToolRuntime, tool
from langchain_core.runnables import RunnableConfig
from pydantic import Field

from pipelines.agents import checkpointer as cp
from pipelines.agents.graphs import route_advice as ra
from pipelines.agents.graphs.models import RouteRequest
from pipelines.agents.tools import context
from pipelines.agents.tools.schemas import Source, ToolResult

CODE_ROWS = ("route.compare", "route.difference", "route.traffic")
WORDS_FAILED = ("validation_failed", "output_invalid")


class RouteAdviceArgs(RouteRequest):
    vessel_id: int | None = Field(default=None, ge=1, description="one of NileGate's vessels (or give vessel_type + "
                                                                  "condition + scnt_tons for a hypothetical vessel)")
    vessel_type: str | None = Field(default=None, description="tariff vessel category of a hypothetical vessel")
    condition: str | None = Field(default=None, description="Laden or Ballast (a hypothetical vessel)")
    scnt_tons: float | None = Field(default=None, gt=0, description="Suez Canal Net Tonnage of a hypothetical vessel")
    origin: str = Field(pattern=r"^[A-Z]{2}[A-Z2-9]{3}$", description="UN/LOCODE of the departure port, e.g. SGSIN")
    destination: str = Field(pattern=r"^[A-Z]{2}[A-Z2-9]{3}$", description="UN/LOCODE of the arrival port, e.g. NLRTM")
    speed_kn: float | None = Field(default=None, ge=4, le=25, description="speed in knots (default: the vessel's "
                                                                          "service speed)")


def _rows(res: dict | None) -> list[dict]:
    res = res or {}
    return list(res.get("rows") or []) if res.get("status") == "ok" else []


def run_route_advice(user, roles, as_of: datetime | None = None, saver=None, pool=None, **args) -> ToolResult:
    """One route question through the graph in a new thread; the ToolResult of the module docstring."""
    req = RouteRequest.model_validate(RouteAdviceArgs.model_validate(args).model_dump())
    ctx = context.RunContext(user, as_of=as_of or context.DATA_AS_OF)          # refuses a clock past the data
    pool = pool or cp.pool()
    g = ra.build_graph(roles, saver or cp.saver())
    tid = ra.new_thread_id(pool, user.employee_id, ctx.as_of, req.origin, req.destination)
    cfg: RunnableConfig = {"configurable": {"thread_id": tid},
                           "metadata": {"run_as": user.employee_id, "trigger": "supervisor"}}
    g.invoke({"request": req.model_dump(mode="json")}, cfg, context=ctx, durability="sync")
    st = g.get_state(cfg).values
    res, status, ev = st.get("result") or {}, st.get("status") or "ok", st.get("evidence") or {}
    if status in ("not_permitted", "no_data"):
        return ToolResult(tool="route_advice", status=status,
                          note="; ".join(res.get("problems") or []) or f"route advice: {status} (thread {tid})")
    rows = [r for key in CODE_ROWS for r in _rows(ev.get(key))]
    if not rows:                                    # nothing computed (a route or vessel the tools could not read)
        return ToolResult(tool="route_advice", status="context_unavailable",
                          note=f"route advice ended {status} with no computed rows (thread {tid})")
    failed = status in WORDS_FAILED
    rows.append({"route": "advice", "status": status, "recommendation": None if failed else res.get("recommendation"),
                 "headline": None if failed else res.get("headline"),
                 "reasons": [] if failed else res.get("reasons") or [], "risks": [] if failed else res.get("risks") or [],
                 "assumptions": res.get("assumptions") or [], "problems": res.get("problems") or [],
                 "thread_id": tid})
    flt = (f"{req.origin} → {req.destination}, "
           + (f"vessel_id = {req.vessel_id}" if req.vessel_id is not None
              else f"{req.vessel_type} / {req.condition} / {req.scnt_tons} SCNT")
           + (f" at {req.speed_kn} kn" if req.speed_kn is not None else "") + f", as of {ctx.as_of.isoformat()}")
    note = ("numbers computed by code (sea_route, vessel_params, compute_toll; days = distance / (speed × 24)); "
            + ("the advice failed its Validator — cite the rows, give no recommendation" if failed
               else "the advice passed the route Validator (the cheaper route unless a cited risk)"))
    return ToolResult(tool="route_advice", status="ok", rows=rows, note=note,
                      source=Source(kind="library", name=f"route_advice graph (thread {tid})", filter=flt))


def make_route_advice_tool(roles, saver=None, pool=None):
    """The `route_advice` LangChain tool bound to `roles` (real `Roles()` or a check's `FakeRoles`)."""

    @tool("route_advice", args_schema=RouteAdviceArgs)
    def route_advice_tool(runtime: ToolRuntime, **args) -> dict:
        """Suez Canal or the Cape of Good Hope for one voyage: distance, sea days, fuel and its cost in SDR, the Suez
        dues, the Cape − Suez difference and the cheaper route, with a validated recommendation (one of NileGate's
        vessels, or a hypothetical one). Rows by `route`: the Suez dues = the `suez` row's suez_dues_sdr; the saving
        or extra of the Cape = the `difference` row's change_* fields (change_total_sdr, change_sea_days)."""
        return run_route_advice(context.user_of(runtime), roles, as_of=context.as_of_of(runtime), saver=saver,
                                pool=pool, **args).model_dump(mode="json")

    return route_advice_tool
