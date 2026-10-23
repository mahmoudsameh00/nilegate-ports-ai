"""`invoice_audit`: the Invoice Auditor's findings for a report week or a list of invoices (Agents plan §5a S5).

Reads the audit views of migration 015 — `finance.invoice_audit` (the real invoices) or, for evaluation only,
`finance_test.invoice_audit` (the copy with planted errors, §4a R7). The checks and the probable causes are computed
in SQL (one definition for this tool and the dashboard's Exceptions page, P4-2 / P4-6); this tool only filters, counts
and sums. Findings are ordered by |difference| (largest amount at stake first).

Amount at stake = Σ over flagged invoices of the largest |difference| of the invoice (an invoice with two findings,
e.g. a wrong tonnage that also changed the amount, is counted once). Since migration 019 a finding has `review`:
'error', or 'manual_review' for an invoice priced by a tariff Notes rule (a ballast chemical tanker at the Crude Oil
ballast rates — right if it is an oil/chemical tanker): those are counted apart (`invoices_manual_review`), never
flagged as errors nor added to the amount at stake.
Access: level 2 / Finance for both datasets (ADR-006, docs/rbac_mapping.md).
"""
from typing import Literal

from langchain.tools import ToolRuntime, tool
from pydantic import BaseModel, Field, model_validator

from pipelines.agents.tools import context, db
from pipelines.agents.tools.schemas import Source, ToolResult

VIEWS = {"live": "finance.invoice_audit", "test": "finance_test.invoice_audit"}
# invoices checked = every invoice of the source in the week (no finding = passed)
CHECKED = {"live": "SELECT invoice_number FROM finance.fact_invoice WHERE invoice_report_week = %s",
           "test": "SELECT i.invoice_number FROM finance_test.invoices i JOIN finance.dim_date d "
                   "ON d.date_day = i.invoice_date WHERE d.report_week = %s"}
SOURCE_TABLE = {"live": "public.invoices", "test": "finance_test.invoices"}
COLUMNS = ("report_week", "invoice_number", "invoice_date", "vessel_id", "vessel_name", "vessel_category",
           "vessel_condition", "check_code", "probable_cause", "billed_sdr", "expected_sdr", "difference_sdr",
           "duplicate_of", "evidence", "review")


class AuditArgs(BaseModel):
    report_week: int | None = Field(default=None, ge=1, le=52, description="audit every invoice of this ISO week "
                                                                           "of 2025")
    invoice_numbers: list[str] | None = Field(default=None, min_length=1, max_length=50,
                                              description="or audit these invoices (INV-0000123 format)")
    dataset: Literal["live", "test"] = Field(default="live", description="live = NileGate's invoices; test = the "
                                                                         "evaluation copy with planted errors")

    @model_validator(mode="after")
    def _one_way(self):
        if (self.report_week is None) == (self.invoice_numbers is None):
            raise ValueError("give report_week or invoice_numbers (exactly one)")
        if self.invoice_numbers and any(not (len(n) == 11 and n.startswith("INV-") and n[4:].isdigit())
                                        for n in self.invoice_numbers):
            raise ValueError("invoice numbers look like INV-0000123")
        return self


class AuditToolArgs(BaseModel):
    """What the model sees: no `dataset` — the run context decides live or test (the model cannot pick the copy
    with planted errors)."""
    report_week: int | None = Field(default=None, ge=1, le=52, description="audit every invoice of this ISO week "
                                                                           "of 2025")
    invoice_numbers: list[str] | None = Field(default=None, min_length=1, max_length=50,
                                              description="or audit these invoices (INV-0000123 format)")


class AuditResult(ToolResult):
    invoices_checked: int | None = None
    invoices_flagged: int | None = None
    amount_at_stake_sdr: float | None = None
    findings_by_check: dict[str, int] | None = None
    invoices_manual_review: int | None = None        # priced by a tariff Notes rule: a person decides (019)


def totals(rows: list[dict]) -> tuple[dict[str, float], dict[str, int], set[str]]:
    """(the largest |difference| per invoice with an error, findings per check, invoices for manual review)."""
    stake: dict[str, float] = {}
    by_check: dict[str, int] = {}
    review = {r["invoice_number"] for r in rows if r["review"] == "manual_review"}
    for r in rows:
        by_check[r["check_code"]] = by_check.get(r["check_code"], 0) + 1
        if r["review"] == "error":
            stake[r["invoice_number"]] = max(stake.get(r["invoice_number"], 0.0), abs(r["difference_sdr"]))
    return stake, by_check, review


def invoice_audit(user, **args) -> ToolResult:
    a = AuditArgs.model_validate(args)
    resource = context.FINANCE_VIEWS if a.dataset == "live" else context.FINANCE_TEST
    if not context.permitted(user, resource):
        return context.denied("invoice_audit")
    view = VIEWS[a.dataset]
    order = "abs(difference_sdr) DESC, invoice_number, check_code"
    if a.report_week is not None:
        rows = db.fetch(f"SELECT {', '.join(COLUMNS)} FROM {view} WHERE report_week = %s ORDER BY {order}",
                        (a.report_week,))
        checked = {r["invoice_number"] for r in db.fetch(CHECKED[a.dataset], (a.report_week,))}
        flt, unknown = f"report_week = {a.report_week}", []
    else:
        nums = sorted(set(a.invoice_numbers))
        rows = db.fetch(f"SELECT {', '.join(COLUMNS)} FROM {view} WHERE invoice_number = ANY(%s) ORDER BY {order}",
                        (nums,))
        checked = {r["invoice_number"] for r in db.fetch(
            f"SELECT invoice_number FROM {SOURCE_TABLE[a.dataset]} WHERE invoice_number = ANY(%s)", (nums,))}
        flt, unknown = f"invoice_number IN ({', '.join(nums)})", [n for n in nums if n not in checked]
    if not checked:
        return AuditResult(tool="invoice_audit", status="no_data",
                           note=f"no invoice in {SOURCE_TABLE[a.dataset]} for {flt}")
    stake, by_check, review = totals(rows)
    notes = [f"{len(checked)} invoices checked, {len(stake)} flagged"]
    if review:
        notes.append(f"{len(review)} for manual review (a tariff Notes rule may apply)")
    if unknown:
        notes.append(f"not found: {', '.join(unknown)}")
    if a.dataset == "test":
        notes.append("evaluation copy with planted errors, not NileGate's invoices")
    return AuditResult(tool="invoice_audit", status="ok", rows=rows, note="; ".join(notes),
                       source=Source(kind="view", name=view, filter=flt),
                       invoices_checked=len(checked), invoices_flagged=len(stake),
                       amount_at_stake_sdr=round(sum(stake.values()), 2), findings_by_check=by_check,
                       invoices_manual_review=len(review))


@tool("invoice_audit", args_schema=AuditToolArgs)
def invoice_audit_tool(runtime: ToolRuntime, **args) -> dict:
    """Audit Suez transit invoices against the official progressive toll bands: duplicate charges, wrong tonnage,
    wrong amounts (with the probable cause) and wrong rates, with the amount at stake, for one report week or a list
    of invoices. No finding = the invoice passed."""
    return invoice_audit(context.user_of(runtime), dataset=context.dataset_of(runtime), **args).model_dump(mode="json")
