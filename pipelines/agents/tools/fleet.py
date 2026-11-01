"""The customer bridge (Agents plan Phase 12, §6d S2, owner answer 1 of S1): which vessels belong to which customer,
and a vessel's id from its name.

`fleet_customers` reads `vessels` only: `vessel_id`, `vessel_name`, `vessel_type`, `customer_id`. The customer id on a
vessel is a level-1 id (docs/rbac_mapping.md, row `vessels.customer_id`); the customer's name, terms and money are
level 2 / Finance and stay in `finance_kpi` (the `customers` dataset carries `customer_id`), so a cross-product
question joins the two by id and an Operations employee gets ids, never a customer's name.

Access: `vessels` is level 1 / Operations (ADR-006): every employee; the identity is still checked.
"""
from langchain.tools import ToolRuntime, tool
from pydantic import BaseModel, Field, model_validator

from pipelines.agents.tools import context, db
from pipelines.agents.tools.schemas import Source, ToolResult

COLS = "vessel_id, vessel_name, vessel_type, customer_id"
MAX_NAME_MATCHES = 5


class FleetArgs(BaseModel):
    customer_ids: list[int] | None = Field(default=None, min_length=1, max_length=40,
                                           description="the vessels of these customers (customer_id from finance_kpi)")
    vessel_ids: list[int] | None = Field(default=None, min_length=1, max_length=50,
                                         description="the customer_id of these vessels")
    vessel_name: str | None = Field(default=None, min_length=3, max_length=80,
                                    description="a vessel's name (or part of it) → its vessel_id")

    @model_validator(mode="after")
    def _one_way(self):
        given = [x is not None for x in (self.customer_ids, self.vessel_ids, self.vessel_name)]
        if sum(given) != 1:
            raise ValueError("give exactly one of customer_ids, vessel_ids, vessel_name")
        return self


def fleet_customers(user, **args) -> ToolResult:
    a = FleetArgs.model_validate(args)
    if not context.permitted(user, context.VESSELS):
        return context.denied("fleet_customers")
    if a.customer_ids is not None:
        ids = sorted(set(a.customer_ids))
        rows = db.fetch(f"SELECT {COLS} FROM vessels WHERE customer_id = ANY(%s) ORDER BY customer_id, vessel_id",
                        (ids,))
        flt = f"customer_id IN {ids}"
    elif a.vessel_ids is not None:
        ids = sorted(set(a.vessel_ids))
        rows = db.fetch(f"SELECT {COLS} FROM vessels WHERE vessel_id = ANY(%s) ORDER BY vessel_id", (ids,))
        flt = f"vessel_id IN {ids}"
    else:
        name = " ".join(a.vessel_name.split())
        rows = db.fetch(f"SELECT {COLS} FROM vessels WHERE lower(vessel_name) = lower(%s) ORDER BY vessel_id", (name,))
        flt = f"vessel_name = '{name}' (case-insensitive)"
        if not rows:                                   # a part of the name: at most a few candidates
            rows = db.fetch(f"SELECT {COLS} FROM vessels WHERE vessel_name ILIKE %s ORDER BY vessel_id LIMIT %s",
                            (f"%{name}%", MAX_NAME_MATCHES + 1))
            flt = f"vessel_name contains '{name}' (case-insensitive)"
            if len(rows) > MAX_NAME_MATCHES:
                return ToolResult(tool="fleet_customers", status="no_data",
                                  note=f"more than {MAX_NAME_MATCHES} vessels match '{name}': give the full name")
    if not rows:
        return ToolResult(tool="fleet_customers", status="no_data", note=f"no vessel where {flt}")
    return ToolResult(tool="fleet_customers", status="ok", rows=rows,
                      source=Source(kind="table", name="public.vessels", filter=flt),
                      note="customer_id only (the customer's name and money: finance_kpi, Finance)")


@tool("fleet_customers", args_schema=FleetArgs)
def fleet_customers_tool(runtime: ToolRuntime, **args) -> dict:
    """NileGate's vessels and their customer: the vessels of given customers, the customer_id of given vessels, or a
    vessel's id from its name. Ids only — the customer's name and money come from finance_kpi."""
    return fleet_customers(context.user_of(runtime), **args).model_dump(mode="json")
