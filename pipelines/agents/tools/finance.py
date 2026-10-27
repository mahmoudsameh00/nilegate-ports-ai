"""`finance_kpi`: the Weekly Finance Pack KPIs of one report week, read from the `finance` views (Agents plan §5a S3).

One tool with a closed `dataset` choice (owner P4-1): each dataset is one view filtered by `report_week`, so the
numbers are exactly those of the Power BI dashboard (DirectQuery on the same views, ADR-048) and of
`docs/finance_metrics.md`. No KPI is computed here (ADR-047). The column lists are explicit, so a changed view cannot
silently change what the agents see; the check script compares them with the views.

Access: the `finance` views are level 2 / Finance (ADR-006): Finance staff, every manager and the CEO.
"""
from typing import Literal

from langchain.tools import ToolRuntime, tool
from pydantic import BaseModel, Field

from pipelines.agents.tools import context, db
from pipelines.agents.tools.schemas import Source, ToolResult

# dataset → (view, columns, order); `limit` applies to the ranked lists only
DATASETS = {
    "weekly": ("finance.kpi_weekly", (
        "report_week", "iso_week_label", "week_start", "week_end", "is_warmup", "invoices_billed", "billed_sdr",
        "payments_received", "collected_sdr", "ar_invoices", "ar_sdr", "overdue_invoices", "overdue_sdr",
        "aging_current_sdr", "aging_1_30_sdr", "aging_31_60_sdr", "aging_61_90_sdr", "aging_90_plus_sdr",
        "dso_window_days", "dso_window_billed_sdr", "dso_days", "budget_sdr", "budget_variance_sdr",
        "budget_variance_pct", "top10_share_13w_pct", "billed_wow_pct", "collected_wow_pct", "ar_wow_pct",
        "overdue_wow_pct", "dso_wow_days"), "report_week"),
    # the week's drivers first: largest |WoW change| (M10), then by name
    "category": ("finance.kpi_weekly_category", (
        "report_week", "vessel_category", "invoices_billed", "billed_sdr", "budget_sdr", "budget_variance_sdr",
        "budget_variance_pct", "billed_prev_sdr", "billed_wow_change_sdr", "billed_wow_pct"),
        "abs(billed_wow_change_sdr) DESC NULLS LAST, vessel_category"),
    "customers": ("finance.kpi_customer_13w", (
        "report_week", "customer_id", "customer_name", "segment", "country", "credit_rating", "payment_terms_days",
        "billed_week_sdr", "billed_13w_sdr", "share_13w_pct", "rank_13w", "rank_13w_prev", "is_top10", "ar_sdr",
        "overdue_sdr"), "rank_13w"),
    "overdue": ("finance.kpi_overdue_list", (
        "report_week", "as_of_date", "invoice_number", "customer_id", "customer_name", "vessel_id", "vessel_name",
        "vessel_category", "invoice_date", "due_date", "amount_sdr", "days_past_due", "aging_bucket",
        "rank_by_amount"), "rank_by_amount"),
    "trend": ("finance.kpi_weekly_trend", (
        "report_week", "trend_week", "week_offset", "is_report_week", "trend_week_label", "trend_week_end",
        "is_warmup", "invoices_billed", "billed_sdr", "collected_sdr", "ar_sdr", "overdue_sdr", "dso_days",
        "budget_sdr", "budget_variance_sdr", "budget_variance_pct", "top10_share_13w_pct"), "trend_week"),
}
RANKED = {"customers", "overdue"}
# the evaluation copy (run context dataset "test", set by the harness only; migration 017): billed and budget come
# from finance_test; the other datasets stay on the live views (the copy has no payments or customers of its own)
TEST_VIEWS = {"weekly": "finance_test.kpi_weekly", "category": "finance_test.kpi_weekly_category"}


class KpiArgs(BaseModel):
    report_week: int = Field(ge=1, le=52, description="ISO week of 2025, 1 to 52 (as of its Sunday 23:59)")
    dataset: Literal["weekly", "category", "customers", "overdue", "trend"] = Field(description=(
        "weekly = the week's KPIs (billed, collected, AR, aging, overdue, DSO, budget variance, top-10 share, WoW); "
        "category = billed vs budget and WoW change per vessel category, largest change first (the drivers); "
        "customers = customers ranked on the trailing 13 weeks; overdue = overdue invoices, largest first; "
        "trend = the 13-week trend ending at the week"))
    limit: int = Field(default=10, ge=1, le=50, description="rows of the ranked lists (customers, overdue)")


def finance_kpi(user, source: str = "live", **args) -> ToolResult:
    """`source` = the run context's dataset (live / test), never a model argument (ADR-049)."""
    a = KpiArgs.model_validate(args)
    if source not in ("live", "test"):
        raise ValueError(f"unknown source {source!r}")
    resources = (context.FINANCE_VIEWS,) + ((context.FINANCE_TEST,) if source == "test" else ())
    if not context.permitted(user, *resources):
        return context.denied("finance_kpi")
    view, cols, order = DATASETS[a.dataset]
    if source == "test":
        view = TEST_VIEWS.get(a.dataset, view)
    sql = f"SELECT {', '.join(cols)} FROM {view} WHERE report_week = %s ORDER BY {order}"
    flt = f"report_week = {a.report_week}"
    params: tuple = (a.report_week,)
    if a.dataset in RANKED:
        sql += " LIMIT %s"
        params += (a.limit,)
        flt += f" ORDER BY {order} LIMIT {a.limit}"
    rows = db.fetch(sql, params)
    if not rows and a.dataset not in RANKED:   # an empty ranked list is an answer (e.g. no overdue invoice yet)
        return ToolResult(tool="finance_kpi", status="no_data", note=f"{view}: no rows for {flt}")
    notes = []
    if a.dataset in RANKED:
        total = db.fetch(f"SELECT count(*) AS n FROM {view} WHERE report_week = %s", (a.report_week,))[0]["n"]
        notes.append(f"{len(rows)} of {total} rows (ranked by {order})")
    if a.dataset == "weekly" and rows[0]["is_warmup"]:
        notes.append(f"warm-up week: receivables still building up since 2025-01-01, DSO on a "
                     f"{rows[0]['dso_window_days']}-day window instead of 91")
    if source == "test":
        notes.append("evaluation copy: billed and budget from finance_test; receivables, collections and the "
                     "previous week from the live views" if a.dataset in TEST_VIEWS
                     else "live data: the evaluation copy has no customers, payments or trend of its own")
    return ToolResult(tool="finance_kpi", status="ok", rows=rows, note="; ".join(notes) or None,
                      source=Source(kind="view", name=view, filter=flt))


@tool("finance_kpi", args_schema=KpiArgs)
def finance_kpi_tool(runtime: ToolRuntime, **args) -> dict:
    """NileGate's weekly finance KPIs (SDR) for one report week of 2025, from the governed finance views — the same
    numbers as the Power BI dashboard. Choose one dataset per call."""
    return finance_kpi(context.user_of(runtime), source=context.dataset_of(runtime), **args).model_dump(mode="json")
