"""The `weekly_pack` LangGraph workflow (Agents plan §3, §5b, §5c): one report week → a validated deck draft → the
Finance manager's approval → the NileGate PPTX saved.

Phase 6 (§5c): the Writer writes numbers as slots (`deck/slots.py`), code draws the fixed parts of the deck
(`deck/render.py`), the Validator binds every number to its field (`deck/validator.py`, V1–V7) and reads the rendered
file back (`deck/readback.py`, V8); a rewrite is a patch of the failing texts only (`DeckPatch`).

- The user and the dataset are the run context (`RunContext`, `context_schema`), passed on every invoke and resume,
  never kept in the state and never visible to a model (ADR-049).
- The state holds JSON-only values (tool results as `ToolResult.model_dump(mode="json")`, Pydantic outputs dumped),
  so every checkpoint is plain data and a resumed run reads exactly what the crashed one wrote.
- Deterministic nodes (P5-1): `readiness` (gate), `kpi`, `audit`, `validator`, `approval`, `publisher`. Agent steps:
  `insight_llm` ⇄ `insight_tools` (`ToolNode(STAGE1_TOOLS)`, which hands the run context to the tools), then
  `insight_notes` and `writer` (one structured call each). Every LLM call goes through `roles` (ADR-045 over llm.py).
- A node that is interrupted or crashes is re-run from its start on resume: `approval` does nothing before its
  `interrupt()`, and every node only returns state updates (the validator's preview and the publisher's files are
  overwritten, never appended).

Evidence ids (`graphs/models.py`): `kpi.<dataset>`, `audit.week`, `insight.<tool_call_id>`.
"""
import hashlib
import json
import operator
import re
import shutil
from datetime import datetime, timezone
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
from pipelines.agents.deck import readback, render, slots
from pipelines.agents.deck import validator as v2
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
DRAFT_LABEL, APPROVED_LABEL = v2.DRAFT_LABEL, "Approved"
NUMERIC_TOOLS = slots.NUMERIC_TOOLS    # NileGate's structured tools (ADR-049) + public structured context


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
    preview: dict | None               # the draft PPTX the approver opens: {path, sha256} (Phase 6)
    normalized: Annotated[list[str], operator.add]   # slot-form fixes made by code on the Writer's text (D-P7-14)
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

def kpi_evidence(user, report_week: int, dataset: str = "live") -> dict[str, dict]:
    """`dataset` = the run context's: "test" reads the evaluation copy's twin views (migration 017, Phase 7)."""
    return {f"kpi.{d}": finance.finance_kpi(user, source=dataset, report_week=report_week, dataset=d,
                                            **({"limit": RANKED_LIMIT} if d in finance.RANKED else {})
                                            ).model_dump(mode="json")
            for d in KPI_DATASETS}


def kpi(state: PackState, runtime: Runtime[RunContext]) -> dict:
    ctx = runtime.context
    return {"evidence": {**state.get("evidence", {}), **kpi_evidence(ctx.user, state["report_week"], ctx.dataset)}}


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
        keys = slots.row_keys(res) if len(res.get("rows") or []) > 1 else ()
        keyed = f", rows keyed by {'/'.join(keys)}" if keys else ""
        lines.append(f"- {eid}: {what}, status {res.get('status')}{keyed}")
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


# --- 5 Report Writer (Phase 6, §5c: slots, the code-drawn parts, the patch rewrite) ---------------------------------

SLOT_RULES = """Numbers: never type a NileGate number. Write a slot; code fills it with the allowed rounding, the sign and
the unit, from the field you name:
  {{<evidence id>:<field>|<format>}}          one-row results (kpi.weekly) and result totals (audit.week)
  {{<evidence id>[<row>]:<field>|<format>}}   lists: <row> = the row's key value (the key is named in the evidence list)
Formats: money M (2 decimals, "M SDR"), k (1 decimal), sdr (as returned); percent %1 or %2; days and counts none.
Add |dir to a change field (wow, change, variance, difference) to write "up 3.2 %" / "down 1.07 M SDR".
A slot writes its own unit: never write SDR, % or days after a slot ("{{kpi.weekly:ar_sdr|M}} SDR" is wrong);
with |dir it also writes "up" / "down": no direction word right before it ("rose {{…|dir}}" is wrong).
Examples: "Billed {{kpi.weekly:billed_sdr|M}} in week {week}, {{kpi.weekly:billed_wow_pct|%1|dir}} WoW"
          "Cruise Ships billed {{kpi.category[Cruise Ships]:billed_wow_change_sdr|M|dir}} WoW"
          "{{audit.week:invoices_checked}} invoices checked, {{audit.week:invoices_flagged}} flagged"
A null field (no WoW in week 1) cannot be a slot: write "not available". Say what each number is (billed, collected,
AR, overdue, DSO, budget, share) and name its category, customer or invoice before it. Counts of things you write
yourself go in words ("three drivers"); the week and year may be digits."""

WRITER_TASK = """You are the Report Writer of NileGate's Weekly Finance Pack. Write the deck for ISO week {week} of
{year} as a DeckDraft. Code draws the title slide, the KPI tiles, every table and chart and the sources slide; you
write only:
- title: "NileGate Weekly Finance Pack — {label} — {draft}"
- slide_titles: one per slide 1 to 10, each stating the slide's finding (slide 1: the week's headline)
- bullets, slides 2 to 9 only: slide 2 exactly five (the executive summary); slides 3 to 8 at most three comments
  each; slide 9 the external context lines (or "External context unavailable"), never a NileGate figure.
Evidence each slide may cite (the bullet's evidence_ids, and its slots): {slide_map}

{slot_rules}

{skills}"""

PATCH_TASK = """You are the Report Writer of NileGate's Weekly Finance Pack (ISO week {week} of {year}). The Validator
refused the texts below in your draft. Return a DeckPatch with one fix per text: the whole corrected text and, for a
bullet, its evidence ids. Keep what was right; fix exactly the problems listed.
Evidence each slide may cite: {slide_map}

{slot_rules}"""


def _slide_map() -> str:
    return "; ".join(f"{s}: {', '.join(ids) or 'none (code)'}" for s, ids in v2.SLIDE_EVIDENCE.items())


def _writer_skills(evidence: dict) -> str:
    names = ["deck-style-guide", "number-validation"]
    if (evidence.get("audit.week") or {}).get("rows"):
        names.append("suez-toll-audit")
    return "\n\n".join(skill_loader.load(n) for n in names)


def _patchable(problems: list[dict]) -> bool:
    """A patch replaces texts; a wrong deck shape (V4: bullet counts, missing titles) needs the whole deck again."""
    return not any(p["rule"] == "V4" for p in problems)


def _fix_list(draft: dict, problems: list[dict]) -> tuple[str, list[str]]:
    """The failing texts with their problems grouped (the rewrite's whole feedback) and the evidence they may use."""
    groups: dict[tuple, list[str]] = {}
    for p in problems:
        if p.get("bullet") is not None:
            key = ("bullet", p["bullet"])
        elif p.get("slide") is not None:
            key = ("slide_title", p["slide"])
        else:
            key = ("title", 0)
        groups.setdefault(key, []).append(f"{p['rule']} {p.get('token') or ''}: {p['message']}".replace("  ", " "))
    titles = {t["slide"]: t["title"] for t in draft["slide_titles"]}
    lines, ids = [], set()
    for (target, idx), msgs in sorted(groups.items()):
        if target == "bullet":
            b = draft["bullets"][idx]
            text, cited = b["text"], list(b["evidence_ids"])
            lines.append(f"- target bullet, index {idx} (slide {b['slide']}), evidence_ids {cited}: "
                         f"{json.dumps(text, ensure_ascii=False)}")
        elif target == "slide_title":
            text, cited = titles.get(idx, ""), []
            lines.append(f"- target slide_title, index {idx}: {json.dumps(text, ensure_ascii=False)}")
        else:
            text, cited = draft["title"], []
            lines.append(f"- target title, index 0: {json.dumps(text, ensure_ascii=False)}")
        lines += [f"    problem {msg}" for msg in msgs]
        # the evidence this fix needs: what the text cites or slots, and what the problems point to (the hints)
        ids |= set(cited) | {s.eid for s in slots.find_slots(text)}
        ids |= set(re.findall(r"\b(?:kpi|audit|insight)\.[A-Za-z0-9_.:-]*[A-Za-z0-9_]", " ".join(msgs)))
    return "\n".join(lines), sorted(ids)


def merge_patch(draft: dict, patch: m.DeckPatch) -> dict:
    """The draft with the fixes applied; a fix to a text that does not exist is ignored (the Validator runs again on
    the whole deck)."""
    d = json.loads(json.dumps(draft))
    titles = {t["slide"]: t for t in d["slide_titles"]}
    for f in patch.fixes:
        if f.target == "bullet" and 0 <= f.index < len(d["bullets"]):
            d["bullets"][f.index]["text"] = f.text
            if f.evidence_ids:
                d["bullets"][f.index]["evidence_ids"] = f.evidence_ids
        elif f.target == "slide_title" and f.index in titles:
            titles[f.index]["title"] = f.text
        elif f.target == "title":
            d["title"] = f.text
    return d


def make_writer(roles):
    def writer(state: PackState) -> dict:
        ev = state["evidence"]
        verdict = state.get("verdict")
        rewrite = bool(verdict and not verdict["passed"] and state.get("draft_origin") == "writer")
        week, label = state["report_week"], _week_label(ev)
        index = "[evidence ids you may cite]\n" + evidence_index(ev, state.get("messages") or [])
        try:
            if rewrite and _patchable(verdict["problems"]):
                fixes, needed = _fix_list(state["draft"], verdict["problems"])
                msgs = [SystemMessage(PATCH_TASK.format(week=week, year=REPORT_YEAR, slide_map=_slide_map(),
                                                        slot_rules=SLOT_RULES.format(week=week))),
                        HumanMessage("\n\n".join([f"[texts to fix]\n{fixes}", index,
                                                  digest(ev, [e for e in needed if e in ev])]))]
                reply = roles.get("writer").structured(msgs, m.DeckPatch)
                draft = merge_patch(state["draft"], reply.parsed)
            else:
                body = [digest(ev), digest(ev, [k for k in ev if k.startswith("insight.")]), index,
                        "[insight notes]\n" + json.dumps(state["insight"], ensure_ascii=False)]
                if rewrite:      # a wrong deck shape: the whole deck again, with the problems and the draft
                    body.append("[validator] your previous draft failed these checks; fix them and return the whole "
                                "deck:\n" + json.dumps(verdict["problems"], ensure_ascii=False)
                                + "\n[previous draft]\n" + json.dumps(state["draft"], ensure_ascii=False))
                msgs = [SystemMessage(WRITER_TASK.format(week=week, year=REPORT_YEAR, label=label, draft=DRAFT_LABEL,
                                                         slide_map=_slide_map(),
                                                         slot_rules=SLOT_RULES.format(week=week),
                                                         skills=_writer_skills(ev))),
                        HumanMessage("\n\n".join(b for b in body if b))]
                reply = roles.get("writer").structured(msgs, m.DeckDraft)
                draft = reply.parsed.model_dump(mode="json")
        except StructuredError as exc:
            return _stop("writer", exc)
        draft, fixed = normalize_draft(draft, ev)
        return {"draft": draft, "draft_origin": "writer", "rewrites": state.get("rewrites", 0) + rewrite,
                "llm_usage": _usage("writer", reply), "normalized": fixed}
    return writer


def normalize_draft(draft: dict, evidence: dict) -> tuple[dict, list[str]]:
    """The slot-form fixes of `slots.normalize_text` on every Writer text (Phase 7, D-P7-14): a format the field
    does not allow, a key on a one-row result, a unit or direction word written twice. Numbers are untouched (code
    writes them); a human edit is not normalized (it is checked as written)."""
    d, fixed = json.loads(json.dumps(draft)), []
    for b in d["bullets"]:
        b["text"], f = slots.normalize_text(b["text"], evidence)
        fixed += f
        # a slot names its evidence: list it among the bullet's citations when the Writer left it out (c3, D-P7-15)
        missing = [s.eid for s in slots.find_slots(b["text"]) if s.eid not in (b.get("evidence_ids") or [])]
        if missing:
            b["evidence_ids"] = [*(b.get("evidence_ids") or []), *dict.fromkeys(missing)]
            fixed.append(f"bullet {b['text'][:40]!r}: evidence ids {sorted(set(missing))} added from its slots")
    for t in d["slide_titles"]:
        t["title"], f = slots.normalize_text(t["title"], evidence)
        fixed += f
    return d, fixed


# --- 6 Validator (Phase 6, §5c: V1–V7 on the draft, V8 on the rendered file) --------------------------------------
# `deck/validator.py` binds every number to its field; when the draft passes, the deck is rendered and read back
# (V8) and the preview the approver opens is saved. A V8 problem is a renderer fault, not the Writer's: the run stops.

def _preview_stem(thread_id: str | None) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", thread_id or "run")


def _preview_path(reports_dir: Path, thread_id: str | None, sha256: str) -> Path:
    # a new file per content (D-P8-17): the approver keeps the previous preview open in PowerPoint, which locks it,
    # so an edit must never write over it; the same content (a resume after a crash) gets the same name
    return reports_dir / "_drafts" / f"{_preview_stem(thread_id)}_{sha256[:10]}.pptx"


def _drop_previews(reports_dir: Path, thread_id: str | None, keep: Path | None = None) -> list[str]:
    """Remove this thread's previews (all passes, and the one-file name of before D-P8-17) except `keep`; a file
    still open in PowerPoint is left and named in the result (the next pass, publish or reject tries again)."""
    drafts, stem, locked = reports_dir / "_drafts", _preview_stem(thread_id), []
    if not drafts.is_dir():
        return locked
    for p in [*drafts.glob(f"{stem}_*.pptx"), drafts / f"{stem}.pptx"]:
        if p == keep or not p.is_file():
            continue
        try:
            p.unlink()
        except PermissionError:
            locked.append(p.name)
    return locked


def make_validator(reports_dir: Path):
    def validator(state: PackState, config: RunnableConfig) -> dict:
        week, ev = state["report_week"], state["evidence"]
        v = v2.validate(state["draft"], ev, week)
        out = {"preview": None}                          # a failing draft has no preview
        if v.passed:
            data = render.render(state["draft"], ev, state["readiness"], DRAFT_LABEL)
            problems = readback.validate_pptx(data, state["draft"], ev, state["readiness"], DRAFT_LABEL)
            if problems:
                v = m.Verdict(passed=False, problems=problems)
            else:
                sha = hashlib.sha256(data).hexdigest()
                path = _preview_path(reports_dir, config["configurable"].get("thread_id"), sha)
                path.parent.mkdir(parents=True, exist_ok=True)
                if not (path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == sha):
                    path.write_bytes(data)                   # a new name per content: never the file the approver has open
                out["preview"] = {"path": path.as_posix(), "sha256": sha}
                _drop_previews(reports_dir, config["configurable"].get("thread_id"), keep=path)
        waiting = v.passed or state.get("draft_origin") == "edit"
        return {**out, "verdict": v.model_dump(mode="json"), "status": "awaiting_approval" if waiting else "running"}
    return validator


def after_validator(state: PackState) -> str:
    problems = state["verdict"]["problems"]
    if any(p["rule"] == "V8" for p in problems):
        return "stop_failed"                   # the renderer and its own read-back disagree: never shown or saved
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


def make_approval(reports_dir: Path):
    def node(state: PackState, config: RunnableConfig) -> dict:
        return approval(state, config, reports_dir)
    return node


def approval(state: PackState, config: RunnableConfig, reports_dir: Path) -> dict:
    audit_res = state["evidence"].get("audit.week", {})
    raw = interrupt({
        "thread_id": config["configurable"].get("thread_id"), "report_week": state["report_week"],
        "draft": state["draft"], "verdict": state["verdict"], "readiness_notes": state["readiness"]["notes"],
        # what the approver reads: the slots filled; the PPTX preview exists only for a passing draft
        "draft_rendered": v2.render_draft(state["draft"], state["evidence"]), "preview": state.get("preview"),
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
        _drop_previews(reports_dir, config["configurable"].get("thread_id"))   # D9: save only what is approved
        return {"approval_log": [{**entry, "outcome": "rejected"}], "status": "rejected", "preview": None}
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
               "models": sorted({c["model"] for c in usage if c["outcome"] == "ok"}),
               # D-P7-14: every slot-form fix code made on the Writer's text stays visible (report: form_fixes)
               "normalized": state.get("normalized") or []}
        # the approved deck: rendered with "Approved", read back (V8) before it is saved — never a file that differs
        data = render.render(draft, state["evidence"], state["readiness"], APPROVED_LABEL)
        problems = readback.validate_pptx(data, draft, state["evidence"], state["readiness"], APPROVED_LABEL)
        if problems:
            raise RuntimeError(f"the approved deck fails its read-back (V8): {problems[:3]}")
        run["deck_sha256"] = hashlib.sha256(data).hexdigest()
        files = {"deck_draft.json": draft, "approval.json": state["approval_log"], "run.json": run}
        for name, obj in files.items():
            (folder / name).write_text(json.dumps(obj, indent=1, ensure_ascii=False, sort_keys=True, default=str),
                                       encoding="utf-8", newline="\n")
        (folder / "deck.pptx").write_bytes(data)
        _drop_previews(reports_dir, config["configurable"].get("thread_id"))
        drafts = reports_dir / "_drafts"
        if drafts.is_dir() and not any(drafts.iterdir()):
            shutil.rmtree(drafts)
        return {"status": "published", "draft": draft, "preview": None,
                "published": {"folder": folder.as_posix(), "files": sorted([*files, "deck.pptx"]), "at": _now()}}
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
    reports_dir = reports_dir or project_root() / "reports"
    g.add_node("validator", make_validator(reports_dir))
    g.add_node("stop_failed", stop_failed)
    g.add_node("approval", make_approval(reports_dir))
    g.add_node("publisher", make_publisher(reports_dir))
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
