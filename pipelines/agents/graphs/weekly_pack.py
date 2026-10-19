"""The `weekly_pack` LangGraph workflow (Agents plan §3, §5b): one report week → a validated deck draft → the
Finance manager's approval → saved.

- The user and the dataset are the run context (`RunContext`, `context_schema`), passed on every invoke and resume,
  never kept in the state and never visible to a model (ADR-049).
- The state holds JSON-only values (tool results as `ToolResult.model_dump(mode="json")`, Pydantic outputs dumped),
  so every checkpoint is plain data and a resumed run reads exactly what the crashed one wrote.
- Deterministic nodes (P5-1): `readiness` (gate), `kpi`, `audit`, `validator`, `approval`, `publisher`. Agent steps:
  `insight_llm` ⇄ `insight_tools` (`ToolNode(STAGE1_TOOLS)`, which hands the run context to the tools), then
  `insight_notes` and `writer` (one structured call each). Every LLM call goes through `roles` (ADR-045 over llm.py).
- A node that is interrupted or crashes is re-run from its start on resume: `approval` does nothing before its
  `interrupt()`, and every node only returns state updates (the publisher's files are overwritten, never appended).

Evidence ids (`graphs/models.py`): `kpi.<dataset>`, `audit.week`, `insight.<tool_call_id>`.
"""
import json
import operator
import re
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.runtime import Runtime
from langgraph.types import interrupt
from pydantic import ValidationError

from pipelines.agents import skill_loader
from pipelines.agents.graphs import models as m
from pipelines.agents.roles import StructuredError
from pipelines.agents.tools import audit as audit_tool
from pipelines.agents.tools import context, db, finance
from pipelines.agents.tools.context import RunContext
from pipelines.agents.tools.registry import STAGE1_TOOLS
from pipelines.lib.common import project_root

Status = Literal["running", "not_ready", "not_permitted", "output_invalid", "validation_failed", "awaiting_approval",
                 "rejected", "published"]
KPI_DATASETS = ("weekly", "category", "customers", "overdue", "trend")
RANKED_LIMIT = 10                      # customers / overdue rows handed to the agents (the deck shows a top 10)
MAX_TOOL_ROUNDS = 4                    # Insight tool rounds (P5-1); the last round has no tools bound
MAX_REWRITES = 2                       # Writer rewrites after a failed Validator, then stop (§3)
SEARCH_K = 3                           # passages per search_documents call in the pack (P5-8: Groq 8K TPM)
REPORT_YEAR = 2025                     # D12: replay of 2025's 52 ISO weeks
DRAFT_LABEL, APPROVED_LABEL = "Draft for approval", "Approved"
# tools whose numeric fields may be cited: NileGate's structured tools (ADR-049) + public structured context
NUMERIC_TOOLS = {"finance_kpi", "invoice_audit", "compute_toll", "suez_transits"}


class PackState(TypedDict, total=False):
    report_week: int
    status: Status
    stop_reason: str
    readiness: dict
    evidence: dict[str, dict]
    messages: Annotated[list[AnyMessage], add_messages]
    insight: dict
    draft: dict
    draft_origin: Literal["writer", "edit"]
    verdict: dict
    rewrites: int
    approval_log: Annotated[list[dict], operator.add]
    published: dict
    llm_usage: Annotated[list[dict], operator.add]


def _usage(node: str, reply) -> list[dict]:
    return [{"node": node, **c} for c in reply.calls]


# --- 1 Data Readiness -----------------------------------------------------------------------------------------------
# Gate before any agent step: the week must be complete enough to report. Reasons are written for the person who
# reads the stopped run. Non-gating facts (a warm-up week) are notes, not failures.

READINESS_SQL = {
    "kpi_row": "SELECT week_end, is_warmup FROM finance.kpi_weekly WHERE report_week = %s",
    "invoices": "SELECT count(*) AS n, "
                "count(*) FILTER (WHERE customer_id IS NULL OR due_date IS NULL OR amount_sdr IS NULL "
                "OR vessel_category IS NULL OR priced_condition IS NULL) AS key_nulls "
                "FROM finance.fact_invoice WHERE invoice_report_week = %s",
    "payments_through": "SELECT max(paid_date) AS d FROM finance.fact_payment",
}


def check_readiness(user, report_week: int) -> dict:
    """The gate's checks for one week (R1–R4 of §5b). Plain function: the node and the check script call it."""
    if not context.permitted(user, context.FINANCE_VIEWS):
        return {"ready": False, "permitted": False, "checks": {}, "reasons": ["not permitted (ADR-006)"],
                "notes": []}
    kpi_row = db.fetch(READINESS_SQL["kpi_row"], (report_week,))
    inv = db.fetch(READINESS_SQL["invoices"], (report_week,))[0]
    through = db.fetch(READINESS_SQL["payments_through"])[0]["d"]
    week_end = kpi_row[0]["week_end"] if kpi_row else None
    checks = {
        "R1_kpi_row": bool(kpi_row),
        "R2_invoices": inv["n"] > 0,
        "R3_key_nulls_zero": inv["key_nulls"] == 0,
        "R4_payments_through_as_of": bool(week_end and through and through >= week_end),
    }
    reasons = {
        "R1_kpi_row": f"finance.kpi_weekly has no row for week {report_week}",
        "R2_invoices": f"no invoice dated in week {report_week}",
        "R3_key_nulls_zero": f"{inv['key_nulls']} invoices of the week miss a key field (customer, due date, "
                             "amount, category, condition)",
        "R4_payments_through_as_of": f"payments are loaded only through {through}, before the as-of date {week_end}",
    }
    notes = []
    if kpi_row and kpi_row[0]["is_warmup"]:
        notes.append("warm-up week (1–13): receivables and DSO still building up since 2025-01-01")
    return {"ready": all(checks.values()), "permitted": True, "checks": checks,
            "reasons": [reasons[k] for k, ok in checks.items() if not ok], "notes": notes,
            "facts": {"invoices": inv["n"], "week_end": week_end.isoformat() if week_end else None,
                      "payments_through": through.isoformat() if through else None}}


def readiness(state: PackState, runtime: Runtime[RunContext]) -> dict:
    r = check_readiness(runtime.context.user, state["report_week"])
    status = "running" if r["ready"] else ("not_permitted" if not r["permitted"] else "not_ready")
    return {"readiness": r, "status": status, "evidence": {}, "rewrites": 0}


def after_readiness(state: PackState) -> str:
    return "kpi" if state["status"] == "running" else END


# --- 2 KPI ----------------------------------------------------------------------------------------------------------

def kpi_evidence(user, report_week: int) -> dict[str, dict]:
    return {f"kpi.{d}": finance.finance_kpi(user, report_week=report_week, dataset=d,
                                            **({"limit": RANKED_LIMIT} if d in finance.RANKED else {})
                                            ).model_dump(mode="json")
            for d in KPI_DATASETS}


def kpi(state: PackState, runtime: Runtime[RunContext]) -> dict:
    return {"evidence": {**state.get("evidence", {}), **kpi_evidence(runtime.context.user, state["report_week"])}}


# --- 3 Invoice Auditor ----------------------------------------------------------------------------------------------

def audit_evidence(user, report_week: int, dataset: str) -> dict[str, dict]:
    return {"audit.week": audit_tool.invoice_audit(user, report_week=report_week, dataset=dataset)
            .model_dump(mode="json")}


def audit(state: PackState, runtime: Runtime[RunContext]) -> dict:
    ctx = runtime.context
    return {"evidence": {**state["evidence"], **audit_evidence(ctx.user, state["report_week"], ctx.dataset)}}


# --- evidence digest (what the agents read) -------------------------------------------------------------------------
# Compact pipe tables instead of every row and field (P5-8: a Groq request must fit 8K tokens per minute). The full
# rows stay in the state: the Validator checks numbers against them, not against the digest.

DIGEST_FIELDS = {
    "kpi.weekly": None,                                               # one row: every field
    "kpi.category": ("vessel_category", "billed_sdr", "billed_wow_change_sdr", "billed_wow_pct", "budget_sdr",
                     "budget_variance_sdr", "budget_variance_pct"),
    "kpi.customers": ("rank_13w", "rank_13w_prev", "customer_name", "billed_13w_sdr", "share_13w_pct", "ar_sdr",
                      "overdue_sdr"),
    "kpi.overdue": ("rank_by_amount", "invoice_number", "customer_name", "amount_sdr", "days_past_due",
                    "aging_bucket"),
    "kpi.trend": ("trend_week_label", "billed_sdr", "budget_sdr", "budget_variance_pct"),
    "audit.week": ("invoice_number", "vessel_category", "check_code", "probable_cause", "billed_sdr", "expected_sdr",
                   "difference_sdr", "duplicate_of"),
}
AUDIT_TOTALS = ("invoices_checked", "invoices_flagged", "amount_at_stake_sdr")


def _cell(v) -> str:
    return "" if v is None else str(v)


def digest(evidence: dict[str, dict], ids=None) -> str:
    parts = []
    for eid in ids or DIGEST_FIELDS:
        res = evidence.get(eid)
        if res is None:
            continue
        src = res.get("source") or {}
        head = f"[{eid}] {res['tool']} status={res['status']}"
        if src:
            head += f" source={src.get('name')} ({src.get('filter')})"
        if res.get("note"):
            head += f" note: {res['note']}"
        lines = [head]
        if eid == "audit.week" and res["status"] == "ok":
            lines.append(" | ".join(f"{k}={_cell(res.get(k))}" for k in AUDIT_TOTALS))
        rows = res.get("rows") or []
        fields = DIGEST_FIELDS.get(eid) or (tuple(rows[0]) if rows else ())
        if rows:
            if eid == "kpi.weekly":
                lines += [f"{k}={_cell(rows[0][k])}" for k in fields]
            else:
                lines.append(" | ".join(fields))
                lines += [" | ".join(_cell(r.get(k)) for k in fields) for r in rows]
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


# --- 4 Insight (agent with tools) -----------------------------------------------------------------------------------

INSIGHT_TASK = """You are the Insight agent of NileGate's Weekly Finance Pack (ISO week {week} of {year}).
The KPI and invoice-audit results of the week are already fetched below, each with its evidence id. Use your tools
only for what is not there: a drill-down, external context for the week (suez_transits for the week and the four
weeks before, web_search for that week's news, search_documents for a tariff rule, at most {k} passages). The
user's identity and access are handled by the system; never ask for them. When you have enough, answer with a short
plain-text summary of your findings and stop calling tools.

{skills}"""

NOTES_TASK = ("Now return the InsightNotes for week {week}: five summary bullets in the skill's order, at most three "
              "drivers, the external context kept apart, and the caveats. Every number copied exactly from a tool "
              "result, with the evidence ids it comes from — only ids from this list, never a tool name:\n{ids}")


def _week_label(evidence: dict) -> str:
    rows = evidence.get("kpi.weekly", {}).get("rows") or [{}]
    return rows[0].get("iso_week_label") or "?"


def _cap_search(msg: AIMessage) -> AIMessage:
    """search_documents in the pack returns at most SEARCH_K passages (P5-8), whatever k the model asked for. The
    reply is changed before it is stored, so the history the model sees next matches the tool result."""
    if not any(c["name"] == "search_documents" for c in msg.tool_calls):
        return msg
    calls = [{**c, "args": {**c["args"], "k": min(int(c["args"].get("k") or SEARCH_K), SEARCH_K)}}
             if c["name"] == "search_documents" else c for c in msg.tool_calls]
    return msg.model_copy(update={"tool_calls": calls})


def _tool_rounds(messages: list) -> int:
    return sum(1 for x in messages if isinstance(x, AIMessage) and x.tool_calls)


def _evidence_id(tool_call_id: str) -> str:
    return "insight." + re.sub(r"[^A-Za-z0-9_.:-]", "_", tool_call_id)


def _tool_evidence(messages: list) -> dict[str, dict]:
    out = {}
    for x in messages:
        if isinstance(x, ToolMessage):
            try:
                res = json.loads(x.content) if isinstance(x.content, str) else x.content
            except json.JSONDecodeError:
                res = None
            if not isinstance(res, dict) or "status" not in res:
                res = {"tool": x.name, "status": "context_unavailable", "rows": [], "source": None,
                       "note": f"tool error: {str(x.content)[:200]}"}
            out[_evidence_id(x.tool_call_id)] = res
    return out


def evidence_index(evidence: dict[str, dict], messages: list) -> str:
    """One line per evidence id: what it is. The model never sees its own tool-call ids, so without this list it
    cites tool names (seen in S6: "suez_transits" as an evidence id)."""
    calls = {_evidence_id(c["id"]): c for x in messages if isinstance(x, AIMessage) for c in x.tool_calls}
    lines = []
    for eid, res in sorted(evidence.items()):
        what = (f"{calls[eid]['name']}({json.dumps(calls[eid]['args'], ensure_ascii=False)})" if eid in calls
                else res.get("tool"))
        lines.append(f"- {eid}: {what}, status {res.get('status')}")
    return "\n".join(lines)


def _stop(node: str, exc: Exception) -> dict:
    """A model that answered twice with an invalid object: re-running reads the same cached replies, so the run ends
    with a stated status (owner 2026-10-19); quota exhaustion is not caught — the thread waits at its checkpoint."""
    return {"status": "output_invalid", "stop_reason": f"{node}: {str(exc)[:400]}",
            "llm_usage": [{"node": node, **c} for c in getattr(exc, "calls", [])]}


def after_agent_step(nxt: str):
    def route(state: PackState) -> str:
        return END if state.get("status") == "output_invalid" else nxt
    return route


def make_insight_llm(roles):
    def insight_llm(state: PackState) -> dict:
        msgs = list(state.get("messages") or [])
        new = []
        if not msgs:
            skills = "\n\n".join(skill_loader.load(s) for s in ("weekly-variance-analysis", "untrusted-content"))
            new = [SystemMessage(INSIGHT_TASK.format(week=state["report_week"], year=REPORT_YEAR, k=SEARCH_K,
                                                     skills=skills)),
                   HumanMessage(digest(state["evidence"]))]
            msgs = new
        tools = STAGE1_TOOLS if _tool_rounds(msgs) < MAX_TOOL_ROUNDS else None
        reply = roles.get("insight").invoke(msgs, tools=tools)
        ai = _cap_search(reply.message)
        return {"messages": [*new, ai], "llm_usage": _usage("insight_llm", reply),
                "evidence": {**state["evidence"], **_tool_evidence(state.get("messages") or [])}}
    return insight_llm


def after_insight_llm(state: PackState) -> str:
    last = state["messages"][-1]
    return "insight_tools" if isinstance(last, AIMessage) and last.tool_calls else "insight_notes"


def make_insight_notes(roles):
    def insight_notes(state: PackState) -> dict:
        evidence = {**state["evidence"], **_tool_evidence(state["messages"])}
        ask = HumanMessage(NOTES_TASK.format(week=state["report_week"],
                                             ids=evidence_index(evidence, state["messages"])))
        try:
            reply = roles.get("insight").structured([*state["messages"], ask], m.InsightNotes)
        except StructuredError as exc:
            return {**_stop("insight_notes", exc), "evidence": evidence}
        return {"insight": reply.parsed.model_dump(mode="json"), "evidence": evidence,
                "llm_usage": _usage("insight_notes", reply)}
    return insight_notes


# --- 5 Report Writer ------------------------------------------------------------------------------------------------

WRITER_TASK = """You are the Report Writer of NileGate's Weekly Finance Pack. Write the deck for ISO week {week} of
{year} as a DeckDraft: the title "NileGate Weekly Finance Pack — {label} — {draft}", one title for each slide 1 to
10, and the bullets of every slide with the evidence ids their numbers come from. Copy every number exactly from the
evidence (allowed roundings only); write structural counts in words.

{skills}"""


def _writer_skills(evidence: dict) -> str:
    names = ["deck-style-guide", "number-validation"]
    if (evidence.get("audit.week") or {}).get("rows"):
        names.append("suez-toll-audit")
    return "\n\n".join(skill_loader.load(n) for n in names)


def make_writer(roles):
    def writer(state: PackState) -> dict:
        ev = state["evidence"]
        verdict = state.get("verdict")
        rewrite = bool(verdict and not verdict["passed"] and state.get("draft_origin") == "writer")
        body = [digest(ev), digest(ev, [k for k in ev if k.startswith("insight.")]),
                "[evidence ids you may cite]\n" + evidence_index(ev, state.get("messages") or []),
                "[insight notes]\n" + json.dumps(state["insight"], ensure_ascii=False)]
        if rewrite:
            body.append("[validator] your previous draft failed these checks; fix them and return the whole deck:\n"
                        + json.dumps(verdict["problems"], ensure_ascii=False)
                        + "\n[previous draft]\n" + json.dumps(state["draft"], ensure_ascii=False))
        msgs = [SystemMessage(WRITER_TASK.format(week=state["report_week"], year=REPORT_YEAR,
                                                 label=_week_label(ev), draft=DRAFT_LABEL,
                                                 skills=_writer_skills(ev))),
                HumanMessage("\n\n".join(b for b in body if b))]
        try:
            reply = roles.get("writer").structured(msgs, m.DeckDraft)
        except StructuredError as exc:
            return _stop("writer", exc)
        return {"draft": reply.parsed.model_dump(mode="json"), "draft_origin": "writer",
                "rewrites": state.get("rewrites", 0) + rewrite, "llm_usage": _usage("writer", reply)}
    return writer


# --- 6 Validator (first version, P5-2) ------------------------------------------------------------------------------
# V1 a sentence with a number cites existing evidence; V2 every number token equals a numeric field of the cited
# evidence (titles: of any evidence) after an allowed rounding (number-validation: as returned; M 2 decimals; k 1
# decimal; % 1 or 2 decimals; half away from zero; the sign kept); V3 the draft label; V4 the deck's shape. Numbers
# of document / web rows are never candidates (ADR-049). The report week and year are run parameters (allowed).

NUM_RE = re.compile(r"(?<![\w.])([+\-−])?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(?:\s?(%|k\b|M\b))?")
# Template text with digits that is not a tool number (owner 2026-10-19: a small allowlist now, the full template's
# in Phase 6): the aging bucket names, the warm-up footnote (deck-style-guide), the 13-week window, "top 10".
TEMPLATE_RE = re.compile(r"(?i)receivables still building up since 1 jan(?:uary)? 2025"
                         r"|\b(?:1|31|61)\s?(?:[-–]|to)\s?(?:30|60|90)(?:\s?days)?\b|\b90\s?\+|\b90 plus\b"
                         r"|\bover 90 days\b|\b13[- ]weeks?\b|\btop[- ]10\b")
# Dates and times are never amounts: a source's date must be cited (untrusted-content rule 5), and S6 showed web
# dates in every form ("6 June 2025", "Fri, 05 Dec 2025 00:00:00 GMT", "2025-12-07"). Blanked everywhere.
_MON = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
DATE_RE = re.compile(rf"(?i)\b\d{{4}}-\d{{2}}-\d{{2}}(?:[T ]\d{{2}}:\d{{2}}(?::\d{{2}})?Z?)?\b"
                     rf"|\b\d{{1,2}}\s{_MON},?\s\d{{4}}\b|\b{_MON}\s\d{{1,2}},?\s\d{{4}}\b|\b{_MON}\s\d{{4}}\b"
                     rf"|\b\d{{2}}:\d{{2}}(?::\d{{2}})?\s?(?:gmt|utc)?\b")


def number_tokens(text: str, strings: list[str]) -> list[tuple[str, Decimal, int, str | None]]:
    """(token, signed value, decimals, suffix) of every number in `text` after the template text and the
    identifiers, dates and labels of the evidence (`strings`) are blanked out."""
    text = DATE_RE.sub(" ", TEMPLATE_RE.sub(" ", text))
    for s in strings:
        text = text.replace(s, " ")
    out = []
    for mt in NUM_RE.finditer(text):
        sign, whole, frac, suffix = mt.groups()
        val = Decimal(whole.replace(",", "") + (f".{frac}" if frac else ""))
        out.append((mt.group(0).strip(), -val if sign in ("-", "−") else val, len(frac or ""), suffix))
    return out


def _quant(v: Decimal, d: int) -> Decimal:
    return v.quantize(Decimal(1).scaleb(-d), rounding=ROUND_HALF_UP)   # ROUND_HALF_UP = half away from zero


def number_matches(value: Decimal, decimals: int, suffix: str | None, candidate) -> bool:
    c = Decimal(str(candidate))
    if suffix == "M":
        return decimals == 2 and _quant(c / 10 ** 6, 2) == value
    if suffix == "k":
        return decimals == 1 and _quant(c / 10 ** 3, 1) == value
    if suffix == "%":
        return (decimals in (1, 2) and _quant(c, decimals) == value) or c == value
    return c == value


def _numbers_and_strings(res: dict) -> tuple[list, list[str]]:
    nums, strs = [], []
    values = [v for r in res.get("rows") or [] for v in r.values()]
    values += [v for k, v in res.items() if k not in ("rows", "source", "tool", "status", "note")]
    if res.get("tool") not in NUMERIC_TOOLS:
        # document / web rows give neither numbers nor blankable strings: blanking their text (a title, a snippet)
        # would hide the very numbers ADR-049 forbids ("Canal revenue 7.5 M" must fail, not vanish)
        return nums, strs
    for v in values:
        if isinstance(v, bool) or v is None:
            continue
        if isinstance(v, (int, float)):
            nums.append(v)
        elif isinstance(v, str) and re.search(r"\d", v):
            strs.append(v)            # identifiers, dates, labels of structured rows (INV-0000626, 2025-W23)
    return nums, strs


def validate(draft: dict, evidence: dict, report_week: int) -> m.Verdict:
    d = m.DeckDraft.model_validate(draft)
    problems: list[m.Problem] = []
    pool = {eid: _numbers_and_strings(res) for eid, res in evidence.items() if res.get("status") == "ok"}
    all_strings = sorted({s for _, ss in pool.values() for s in ss}, key=len, reverse=True)
    allowed = [report_week, REPORT_YEAR]

    def checked_tokens(text: str, strings: list[str]):
        return [t for t in number_tokens(text, strings) if not (t[3] is None and t[2] == 0 and t[1] in allowed)]

    def check(text: str, cands: list, strings: list[str], slide: int | None, bullet: int | None):
        for tok, val, dec, suf in checked_tokens(text, strings):
            if not any(number_matches(val, dec, suf, c) for c in cands):
                problems.append(m.Problem(rule="V2", slide=slide, bullet=bullet, token=tok,
                                          message=f"{tok!r} is not a number of the cited evidence (allowed "
                                                  "roundings only)"))

    if DRAFT_LABEL not in d.title:
        problems.append(m.Problem(rule="V3", message=f'the title must say "{DRAFT_LABEL}"'))
    every = [c for ns, _ in pool.values() for c in ns]
    check(d.title, every, all_strings, None, None)
    for st in d.slide_titles:
        check(st.title, every, all_strings, st.slide, None)
    for i, b in enumerate(d.bullets):
        unknown = [e for e in b.evidence_ids if e not in pool]
        if unknown:
            problems.append(m.Problem(rule="V1", slide=b.slide, bullet=i,
                                      message=f"cites evidence that does not exist or has no data: {unknown}"))
        cited = [e for e in b.evidence_ids if e in pool]
        strings = sorted({s for e in cited for s in pool[e][1]}, key=len, reverse=True)
        if not cited and checked_tokens(b.text, all_strings):
            problems.append(m.Problem(rule="V1", slide=b.slide, bullet=i, message="a number without evidence"))
            continue
        check(b.text, [c for e in cited for c in pool[e][0]], strings, b.slide, i)
    titles = sorted(st.slide for st in d.slide_titles)
    if titles != list(range(1, m.SLIDES + 1)):
        problems.append(m.Problem(rule="V4", message=f"one title per slide 1–{m.SLIDES} needed, got {titles}"))
    summary = sum(1 for b in d.bullets if b.slide == 2)
    if summary != 5:
        problems.append(m.Problem(rule="V4", slide=2, message=f"the executive summary needs five bullets, got "
                                                                f"{summary}"))
    return m.Verdict(passed=not problems, problems=problems)


def validator(state: PackState) -> dict:
    v = validate(state["draft"], state["evidence"], state["report_week"])
    waiting = v.passed or state.get("draft_origin") == "edit"
    return {"verdict": v.model_dump(mode="json"), "status": "awaiting_approval" if waiting else "running"}


def after_validator(state: PackState) -> str:
    if state["verdict"]["passed"] or state.get("draft_origin") == "edit":
        return "approval"                      # a failed human edit goes back to the human, with the problems
    return "writer" if state.get("rewrites", 0) < MAX_REWRITES else "stop_failed"


def stop_failed(state: PackState) -> dict:
    return {"status": "validation_failed"}


# --- 7 Approval (human in the loop, P5-4) ---------------------------------------------------------------------------

def approver_check(employee_id: int) -> tuple[bool, str]:
    """A Finance manager or the CEO may decide (read from PostgreSQL at every decision)."""
    try:
        u = context.load_user(employee_id)
    except PermissionError:
        return False, f"unknown employee {employee_id}"
    if u.role == "ceo" or (u.role == "manager" and u.department == "Finance"):
        return True, f"{u.role} / {u.department}"
    return False, f"{u.role} / {u.department} may not approve the finance pack (Finance manager or CEO only)"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def approval(state: PackState, config: RunnableConfig) -> dict:
    audit_res = state["evidence"].get("audit.week", {})
    raw = interrupt({
        "thread_id": config["configurable"].get("thread_id"), "report_week": state["report_week"],
        "draft": state["draft"], "verdict": state["verdict"], "readiness_notes": state["readiness"]["notes"],
        "audit": {k: audit_res.get(k) for k in AUDIT_TOTALS},
        "decisions": ["approve", "edit", "reject"] if state["verdict"]["passed"] else ["edit", "reject"]})
    entry = {"at": _now(), "decision": None, "approver_employee_id": None}

    def refused(why: str) -> dict:
        return {"approval_log": [{**entry, "outcome": "refused", "reason": why}], "status": "awaiting_approval"}

    try:
        d = m.ApprovalDecision.model_validate(raw)
    except ValidationError as exc:
        return refused(f"invalid decision: {exc.errors()[0]['msg']}")
    entry.update(decision=d.decision, approver_employee_id=d.approver_employee_id, comment=d.comment)
    ok, who = approver_check(d.approver_employee_id)
    if not ok:
        return refused(who)
    entry["approver"] = who
    if d.decision == "approve":
        if not state["verdict"]["passed"]:
            return refused("the draft fails the Validator: edit or reject it")
        return {"approval_log": [{**entry, "outcome": "approved"}], "status": "awaiting_approval"}
    if d.decision == "reject":
        return {"approval_log": [{**entry, "outcome": "rejected"}], "status": "rejected"}
    bullets = state["draft"]["bullets"]
    bad = [e.bullet for e in d.edits if e.bullet >= len(bullets)]
    if bad:
        return refused(f"no bullet {bad} in the draft (0–{len(bullets) - 1})")
    new = [dict(b) for b in bullets]
    diff = []
    for e in d.edits:
        diff.append({"bullet": e.bullet, "slide": new[e.bullet]["slide"], "before": new[e.bullet]["text"],
                     "after": e.text})
        new[e.bullet]["text"] = e.text
    return {"approval_log": [{**entry, "outcome": "edited", "diff": diff}],
            "draft": {**state["draft"], "bullets": new}, "draft_origin": "edit", "status": "awaiting_approval"}


def after_approval(state: PackState) -> str:
    outcome = state["approval_log"][-1]["outcome"]
    return {"approved": "publisher", "rejected": END, "edited": "validator", "refused": "approval"}[outcome]


# --- 8 Publisher (save only, D9) ------------------------------------------------------------------------------------

def make_publisher(reports_dir: Path):
    def publisher(state: PackState, config: RunnableConfig, runtime: Runtime[RunContext]) -> dict:
        week = state["report_week"]
        folder = reports_dir / f"{REPORT_YEAR}-W{week:02d}"
        folder.mkdir(parents=True, exist_ok=True)
        draft = {**state["draft"], "title": state["draft"]["title"].replace(DRAFT_LABEL, APPROVED_LABEL)}
        u, usage = runtime.context.user, state.get("llm_usage") or []
        run = {"thread_id": config["configurable"].get("thread_id"), "report_week": week,
               "dataset": runtime.context.dataset,
               "run_as": {"employee_id": u.employee_id, "role": u.role, "department": u.department},
               "readiness": state["readiness"], "verdict": state["verdict"], "rewrites": state.get("rewrites", 0),
               "sources": {eid: res.get("source") for eid, res in sorted(state["evidence"].items())},
               "llm_calls": len(usage), "llm_cached": sum(c["cached"] for c in usage),
               "max_total_tokens": max((c["total_tokens"] or 0 for c in usage), default=0),
               "models": sorted({c["model"] for c in usage if c["outcome"] == "ok"})}
        files = {"deck_draft.json": draft, "approval.json": state["approval_log"], "run.json": run}
        for name, obj in files.items():
            (folder / name).write_text(json.dumps(obj, indent=1, ensure_ascii=False, sort_keys=True, default=str),
                                       encoding="utf-8", newline="\n")
        return {"status": "published", "draft": draft,
                "published": {"folder": folder.as_posix(), "files": sorted(files), "at": _now()}}
    return publisher


# --- graph ----------------------------------------------------------------------------------------------------------

def build_graph(roles: Any, checkpointer=None, reports_dir: Path | None = None):
    """The compiled workflow; `roles` = `roles.Roles()` (real models) or `roles.FakeRoles(script)` (checks)."""
    g = StateGraph(PackState, context_schema=RunContext)
    g.add_node("readiness", readiness)
    g.add_node("kpi", kpi)
    g.add_node("audit", audit)
    g.add_node("insight_llm", make_insight_llm(roles))
    g.add_node("insight_tools", ToolNode(STAGE1_TOOLS))
    g.add_node("insight_notes", make_insight_notes(roles))
    g.add_node("writer", make_writer(roles))
    g.add_node("validator", validator)
    g.add_node("stop_failed", stop_failed)
    g.add_node("approval", approval)
    g.add_node("publisher", make_publisher(reports_dir or project_root() / "reports"))
    g.add_edge(START, "readiness")
    g.add_conditional_edges("readiness", after_readiness, ["kpi", END])
    g.add_edge("kpi", "audit")
    g.add_edge("audit", "insight_llm")
    g.add_conditional_edges("insight_llm", after_insight_llm, ["insight_tools", "insight_notes"])
    g.add_edge("insight_tools", "insight_llm")
    g.add_conditional_edges("insight_notes", after_agent_step("writer"), ["writer", END])
    g.add_conditional_edges("writer", after_agent_step("validator"), ["validator", END])
    g.add_conditional_edges("validator", after_validator, ["approval", "writer", "stop_failed"])
    g.add_edge("stop_failed", END)
    g.add_conditional_edges("approval", after_approval, ["publisher", "validator", "approval", END])
    g.add_edge("publisher", END)
    return g.compile(checkpointer=checkpointer)
