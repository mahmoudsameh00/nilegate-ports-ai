"""Who is asking, and the access check every tool runs first (Agents plan §5a P4-3, ADR-006, ADR-034).

- The user is read once per run / question from PostgreSQL (role ceiling + department) and travels in the run
  context (`RunContext`, LangChain `ToolRuntime.context`), which the model never sees: no tool schema has a user or
  employee field, so a model cannot ask as someone else.
- The rule is the one of the document tool (`retrieval.allowed`): level <= ceiling, or own department and level <= 2.
  Each tool names the resource it reads (level + owner department, `docs/rbac_mapping.md`) and checks it before any
  query; a refusal is a `not_permitted` result with no rows.
- The clock (Stage 2, Agents plan §6a): `as_of` travels in the same run context. Only the graph or the evaluation
  harness sets it, never the model — a model-chosen instant could move a replayed cut past *t* and read the future.
  Stage 1 tools ignore it.
"""
from dataclasses import dataclass
from datetime import datetime, timezone

from pipelines.agents.tools import db
from pipelines.agents.tools.schemas import ToolResult
from pipelines.lib.retrieval import User, allowed


@dataclass(frozen=True)
class Resource:
    name: str
    level: int
    department: str


# docs/rbac_mapping.md §2; external public sources are level 1 like the public documents (§4)
FINANCE_VIEWS = Resource("finance.*", 2, "Finance")
FINANCE_TEST = Resource("finance_test.*", 2, "Finance")
TOLL_BANDS = Resource("toll_rate_bands", 1, "Finance")
VESSELS = Resource("vessels", 1, "Operations")
PUBLIC_EXTERNAL = Resource("public external sources", 1, "Operations")
PORTS = Resource("ports", 1, "Operations")
# MongoDB ais_positions / ais_vessels (§3) and their generator file voyages_synthetic.parquet (same data, same row)
AIS_TRACKS = Resource("ais_positions + voyages_synthetic", 1, "Operations")
VESSEL_PARAMS = Resource("vessel_performance + bunker_prices", 1, "Operations")      # migration 020

# the synthetic data's as-of instant (ADR-032): no fix is later than it
DATA_AS_OF = datetime(2026, 9, 13, tzinfo=timezone.utc)


@dataclass(frozen=True)
class RunContext:
    user: User
    # which invoices the audit reads: "live" in every real run; "test" (the evaluation copy with planted errors) is
    # set only by the evaluation harness — the model can never choose it
    dataset: str = "live"
    # the instant the Stage 2 tools see the world at (fixes with ts <= as_of only); the harness moves it back to cut
    # a voyage at t, nothing moves it past the data
    as_of: datetime = DATA_AS_OF

    def __post_init__(self):
        if self.dataset not in ("live", "test"):
            raise ValueError(f"unknown dataset {self.dataset!r}")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware (UTC)")
        if self.as_of > DATA_AS_OF:
            raise ValueError(f"as_of {self.as_of.isoformat()} is after the data's as-of instant {DATA_AS_OF.isoformat()}")


def load_user(employee_id: int) -> User:
    rows = db.fetch("SELECT r.role_name, r.allowed_sensitivity_level, d.department_name FROM employees e "
                    "JOIN roles r USING (role_id) JOIN departments d USING (department_id) "
                    "WHERE e.employee_id = %s", (employee_id,))
    if not rows:
        raise PermissionError(f"unknown employee {employee_id}: no access")
    r = rows[0]
    return User(employee_id, r["role_name"], int(r["allowed_sensitivity_level"]), r["department_name"])


def user_of(runtime) -> User:
    """The user of a LangChain tool call; a call without a run context is refused (no anonymous access)."""
    ctx = getattr(runtime, "context", None)
    if not isinstance(ctx, RunContext):
        raise PermissionError("tool called without a RunContext: no user, no access")
    return ctx.user


def dataset_of(runtime) -> str:
    user_of(runtime)                                   # same refusal without a RunContext
    return runtime.context.dataset


def as_of_of(runtime) -> datetime:
    user_of(runtime)                                   # same refusal without a RunContext
    return runtime.context.as_of


def permitted(user: User, *resources: Resource) -> bool:
    return all(allowed(user, r.level, r.department) for r in resources)


def denied(tool: str) -> ToolResult:
    return ToolResult(tool=tool, status="not_permitted", note="not permitted for this user (ADR-006)")
