"""LLM bake-off on free APIs (Agents plan Phase 0, §7a): which model per role (Writer / Insight, Tools / routing).

Plan:    docs/plans/Agents_plan.md §7a + "Progress / deviations" (owner decisions 2026-10-10).
Run:     uv run python tools/run.py pipelines/scripts/agents/LLM_bakeoff.py --timeout 14400
         (project root; ports-postgres and ports-qdrant up)

Reads:   PostgreSQL read-only (toll_rate_bands, invoices, vessels; the RBAC user lookup); Qdrant + the query cache +
         Jina (only while freezing the T4 contexts); Data/processed/rag/eval/golden_set.jsonl + golden_facts.jsonl
         (frozen); .env (the provider keys; a missing key = that provider skipped, reported)
Writes:  Data/processed/agents/eval/bakeoff_tasks.json (frozen once, in git; its SHA-256 is reviewed into
         TASKS_SHA256); Data/processed/agents/eval/llm_bakeoff_<UTC date>.json (results, in git);
         Data/processed/agents/eval/llm_cache/ (every reply, git-ignored)
Re-run:  safe and resumable: the tasks file is never rebuilt (its hash is asserted; the deterministic parts are
         rebuilt in memory and compared), every reply comes from the cache, a model whose daily quota is exhausted
         is skipped until the provider's day ends (no retry loop). A re-run on a later day completes what is missing.

Rules (fixed before any model call)
- Tasks and expected answers are written and frozen (SHA-256) BEFORE any model call: the first run stops after
  Phase 2; Phase 3 refuses to start until TASKS_SHA256 equals the file's hash.
- Data policy (ADR-037 amendment): T1–T3 send synthetic aggregates / made-up invoices (no rows of the real tables,
  no names), T4 public document passages; `llm.LLM.invoke` refuses anything else on a free tier.
- T1 tool calling (20: 8 compute_toll, 8 weekly_kpi, 4 search_documents): right tool, right arguments, right final
  number (search: the final answer states a fact of the frozen passages). Tools run locally and deterministically;
  in T1, search_documents returns the item's frozen passages whatever the query.
- T2 grounded weekly summary (10 weeks): every number written in digits must be a table value at the precision it
  is written with (only k / M and decimals count as rounding; allowed: the week, the previous week, 2025, the
  absolute value of a negative change) = hard gate; driver coverage = the two categories with the largest
  |WoW change| named.
- T3 structured output (10 made-up tables × 8 invoices, 0–3 planted mismatches): `ExceptionsReport` validity per
  method (function_calling / json_schema / json_mode; OpenRouter function_calling only) × exactness (the exact set of
  (invoice, issue) and the copied amounts).
- T4 RAG answers (the 40 English golden questions; passages = the real search_documents top-8 for the CEO, frozen):
  fact recall over the facts the passages state (facts the question alone states are not measurable), citation
  validity (every [n] exists and each recalled fact is stated by a cited passage).
- OpenRouter (50 requests / day): a frozen stratified LITE subset (T1 8 / T2 4 / T3 4 / T4 8); the cross-provider
  ranking uses LITE for all models; Gemini and Groq also run the full set.
- Selection: Writer / Insight = only models with 100 % T2 faithfulness on every T2 item they ran, score =
  mean(T2 driver coverage, T4 fact recall, T4 citation validity); Tools = mean(T1 accuracy, T3 validity × exactness
  with the model's best method); a tie (< 5 points) → quota fit (minutes of TPM per simulated pack) → latency; no
  automatic relaxation of the gate; main + fallback from different providers. Incomplete runs → PROPOSED.
"""
# %% Setup
import datetime as dt
import hashlib
import json
import os
import random
import re
import statistics
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Literal

import psycopg
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, ValidationError, field_validator

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())
sys.path.insert(0, str(ROOT))
from pipelines.agents import llm  # noqa: E402
from pipelines.lib import common, evaluation, retrieval  # noqa: E402
from pipelines.lib.chunks import compose  # noqa: E402

common.load_env(ROOT)
EVAL = llm.EVAL_DIR
RAG_EVAL = ROOT / "Data" / "processed" / "rag" / "eval"
TASKS_FILE = EVAL / "bakeoff_tasks.json"
TASKS_SHA256 = "ed6723f5c993ba98718ca1936821d3b622e84524c0f4299f54444987374eaab2"   # reviewed freeze, owner 2026-10-10
GOLDEN_SHA256 = "a187b4966f250211d7498b87d34d56b518af41d851cf8570716fce01f2dbb8bc"   # as in Evaluation.py
FACTS_SHA256 = "09b5f5b6892133806a9c11a006490c31c63782e560cb9a038977b1d2f5998d25"
CEO = 1
YEAR = 2025
CATEGORIES = ["Chemical Tankers & Other Liquid Bulk Tankers", "Containerships", "Crude Oil Tankers", "Cruise Ships",
              "Dry Bulk Vessels", "General Cargo / Multi-Purpose / Heavy Lift Vessels",
              "Liquefied Natural Gas (LNG) Carriers", "Liquefied Petroleum Gas (LPG) Carriers", "Other Vessels",
              "Petroleum Product Tankers", "Roll-On/Roll-Off (Ro/Ro) Vessels", "Special Floating Units",
              "Vehicles Carriers"]                          # = vessels_vessel_type_chk / toll_rate_bands CHECK
ALIASES = {  # how a summary may name a category (driver coverage)
    "Chemical Tankers & Other Liquid Bulk Tankers": r"chemical|liquid bulk", "Containerships": r"container",
    "Crude Oil Tankers": r"crude", "Cruise Ships": r"cruise", "Dry Bulk Vessels": r"dry bulk",
    "General Cargo / Multi-Purpose / Heavy Lift Vessels": r"general cargo|multi.?purpose|heavy.?lift",
    "Liquefied Natural Gas (LNG) Carriers": r"\bLNG\b|natural gas", "Liquefied Petroleum Gas (LPG) Carriers":
    r"\bLPG\b|petroleum gas", "Other Vessels": r"other vessels", "Petroleum Product Tankers": r"petroleum product",
    "Roll-On/Roll-Off (Ro/Ro) Vessels": r"ro.?ro|roll.?on", "Special Floating Units": r"special floating|\bSFUs?\b",
    "Vehicles Carriers": r"vehicle"}
TIE = 0.05
LITE_ONLY = {"gemini/gemini-3.8-flash"}   # owner 2026-10-10: its free tier allows 20 requests / day (the 429 says so)
UNAVAILABLE = {  # candidates the free API refuses for good (the reason is the provider's answer)
    "openrouter/thinkingmachines/inkling:free": "403 on 2026-10-10: 'only available on agentic harnesses'"}
PACK = {"writer_insight": {"T2": 6, "T4": 3}, "tools": {"T1": 12, "T3": 4}}   # requests per simulated weekly pack


def pg():
    e = os.environ
    return psycopg.connect(host=e["PGHOST"], port=e["PGPORT"], dbname=e["PGDATABASE"], user=e["PG_RO_USER"],
                           password=e["PG_RO_PASSWORD"], options="-c default_transaction_read_only=on",
                           connect_timeout=5)


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# %% Phase 1 — Tools (deterministic, local) and their self-check
# compute_toll implements ADR-004 (amount = Σ rate × tons inside each band; Special Floating Units always Laden);
# weekly_kpi aggregates the existing invoices by ISO week of 2025 (no status: the stored status is the end-of-2025
# snapshot, not the status "as of" a week — that is Phase 1–2 work). Self-check: compute_toll reproduces the amount
# and the terminal rate of all 1,000 invoices.
with pg() as conn:
    band_rows = conn.execute("SELECT vessel_category, laden_ballast, band_order, band_label, band_min_tons, "
                             "band_max_tons, rate_sdr_per_ton FROM toll_rate_bands ORDER BY 1, 2, 3").fetchall()
    inv_rows = conn.execute("SELECT i.invoice_number, i.invoice_date, i.scnt_tons, i.amount, i.rate_sdr_per_ton, "
                            "v.vessel_type, v.condition FROM invoices i JOIN vessels v USING (vessel_id)").fetchall()

BANDS: dict[tuple[str, str], list[tuple]] = {}
for cat, lb, order, label, lo, hi, rate in band_rows:
    BANDS.setdefault((cat, lb), []).append((order, label, lo, hi, rate))


def sdr(x: Decimal) -> float:
    """2 decimals, half away from zero, like PostgreSQL's round(numeric, 2). The stored invoices follow no single
    rounding rule at the half cent (ADR-013: built in PostgreSQL, origin of the rounding unknown; half-up leaves 34
    one-cent differences, half-even 9), so the self-check compares the exact amount with a half-cent tolerance."""
    return float(x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def toll(vessel_category: str, laden_ballast: str, scnt_tons: float) -> dict:
    lb = "Laden" if vessel_category == "Special Floating Units" else laden_ballast   # ADR-004
    tons, amount, terminal = Decimal(str(scnt_tons)), Decimal(0), None
    for _, label, lo, hi, rate in BANDS[(vessel_category, lb)]:
        if tons > lo:
            amount += rate * ((tons if hi is None else min(tons, hi)) - lo)
            terminal = (label, rate)
    return {"vessel_category": vessel_category, "laden_ballast_priced": lb, "scnt_tons": float(tons),
            "amount_sdr": sdr(amount), "terminal_band": terminal[0], "rate_sdr_per_ton": float(terminal[1]),
            "_exact": amount}


INV = [(d, a, c) for _, d, _, a, _, c, _ in inv_rows if d.isocalendar().year == YEAR]
KPI_METRICS = ("invoice_count", "billed_sdr", "mean_invoice_sdr")


def kpi(iso_week: int, metric: str, vessel_category: str = "All") -> dict:
    amounts = [a for d, a, c in INV if d.isocalendar().week == iso_week and vessel_category in ("All", c)]
    if metric == "invoice_count":
        value = len(amounts)
    elif metric == "billed_sdr":
        value = sdr(sum(amounts, Decimal(0)))
    else:
        value = sdr(sum(amounts, Decimal(0)) / len(amounts)) if amounts else None
    return {"iso_week": iso_week, "year": YEAR, "metric": metric, "vessel_category": vessel_category, "value": value,
            "currency": None if metric == "invoice_count" else "SDR"}


mismatch, cent_rounding, max_diff = [], 0, Decimal(0)   # db/verify_readonly.sql §12 allows 0.01; we allow 0.005
for number, _, tons, amount, rate, cat, cond in inv_rows:
    t = toll(cat, cond, float(tons))
    max_diff = max(max_diff, abs(t["_exact"] - amount))
    if abs(t["_exact"] - amount) > Decimal("0.005") or Decimal(str(t["rate_sdr_per_ton"])) != rate:
        mismatch.append(number)
    cent_rounding += Decimal(str(t["amount_sdr"])) != amount

Category = Literal[tuple(CATEGORIES)]


class TollArgs(BaseModel):
    vessel_category: Category = Field(description="the vessel category of the Suez Canal tariff")
    laden_ballast: Literal["Laden", "Ballast"] = Field(description="the vessel's condition")
    scnt_tons: float = Field(description="Suez Canal Net Tonnage (SCNT)")


class KpiArgs(BaseModel):
    iso_week: int = Field(description="ISO week number of 2025, 1 to 52")
    metric: Literal[KPI_METRICS] = Field(description="invoice_count, billed_sdr (total) or mean_invoice_sdr")
    vessel_category: Literal[tuple(CATEGORIES + ["All"])] = Field(
        description="one vessel category, or All for every category")


class SearchArgs(BaseModel):
    query: str = Field(description="what to look for, in a few words")


def _stub(**_) -> str:  # the runner executes the tools itself (run_tool); the schemas are what the model sees
    raise RuntimeError("executed by run_tool")


TOOLS = [
    StructuredTool.from_function(_stub, name="compute_toll", args_schema=TollArgs, description=(
        "Compute the Suez Canal transit dues (SDR) of one transit from the official progressive toll bands.")),
    StructuredTool.from_function(_stub, name="weekly_kpi", args_schema=KpiArgs, description=(
        "One KPI of NileGate's Suez transit invoices for one ISO week of 2025: the number of invoices, the total "
        "billed (SDR) or the mean invoice (SDR), for all categories or one vessel category.")),
    StructuredTool.from_function(_stub, name="search_documents", args_schema=SearchArgs, description=(
        "Search NileGate's document library (maritime regulations, incident investigation reports, logistics "
        "benchmarks, the Suez tariff notes) for passages that answer a question.")),
]


def run_tool(name: str, args: dict, item: dict) -> str:
    try:
        if name == "compute_toll":
            a = TollArgs.model_validate(args)
            return json.dumps({k: v for k, v in toll(**a.model_dump()).items() if not k.startswith("_")})
        if name == "weekly_kpi":
            a = KpiArgs.model_validate(args)
            if not 1 <= a.iso_week <= 52:
                return json.dumps({"error": "iso_week must be 1 to 52 (ISO weeks of 2025)"})
            return json.dumps(kpi(a.iso_week, a.metric, a.vessel_category))
        if name == "search_documents":
            SearchArgs.model_validate(args)
            return format_passages(item.get("passages", []))
        return json.dumps({"error": f"unknown tool {name}"})
    except ValidationError as e:
        return json.dumps({"error": "invalid arguments", "detail": str(e)[:400]})


def format_passages(passages: list[dict]) -> str:
    if not passages:
        return "No relevant passages found."
    return "\n\n".join(f"[{i}] {p['text']}" for i, p in enumerate(passages, 1))


assert len(band_rows) == 177 and len(BANDS) == 25, (len(band_rows), len(BANDS))
assert sorted({c for c, _ in BANDS}) == sorted(CATEGORIES)
assert len(inv_rows) == 1000 and not mismatch, f"compute_toll mismatches: {len(mismatch)} {mismatch[:5]}"
reviewed = {"bands": 177, "band_pairs": 25, "invoices": 1000, "invoices_iso_2025": 996, "mismatches": 0,
            "cent_rounding": 34}
actual = {"bands": len(band_rows), "band_pairs": len(BANDS), "invoices": len(inv_rows), "invoices_iso_2025": len(INV),
          "mismatches": len(mismatch), "cent_rounding": cent_rounding}
assert actual == reviewed, actual
print(f"✅ Phase 1 validation passed: compute_toll reproduces all 1,000 invoices (exact amount within half a cent, "
      f"max |diff| {max_diff:.4f} SDR; terminal rates equal; {cent_rounding} stored amounts are rounded the other way "
      f"at the half cent); weekly_kpi over {len(INV)} invoices of ISO {YEAR} (4 of 2026-W01 excluded); 3 tool schemas")


# %% Phase 2 — Tasks frozen before any model call (T1–T4, LITE, prompts)
# The tasks file holds everything a model sees and everything a score uses (questions, tables, passages, facts,
# expected answers, prompts). It is written once; afterwards only its hash is checked, and the deterministic parts
# (T1 toll / KPI, T2, T3) are rebuilt in memory and must be identical (data drift guard).
PROMPTS = {
    "T1_system": ("You are NileGate's finance and operations assistant. Use the tools for every number and every "
                  "document fact; never compute or recall a number yourself. Call a tool, read its result, then "
                  "answer in one or two sentences that state the number (with its unit) or the fact."),
    "T2_system": ("You are NileGate's finance analyst. Write exactly 5 bullet points (each line starts with '- ') "
                  "summarizing the week from the KPI table. Rules: copy every number from the table exactly, or "
                  "round it with k / M or fewer decimals; never calculate a new number (no sums, differences, "
                  "shares or ranks) and write no number that is not in the table (refer to the week as 'week N'). "
                  "Name the vessel categories that drove the change against the previous week."),
    "T3_system": ("You are NileGate's invoice auditor. Compare billed_sdr with expected_sdr for every invoice in "
                  "the table. List every invoice where they differ: issue 'overbilled' if billed_sdr > "
                  "expected_sdr, 'underbilled' if billed_sdr < expected_sdr, and copy both amounts exactly. If "
                  "every invoice matches, return an empty list. Return JSON of the form "
                  "{\"exceptions\": [{\"invoice_number\": \"INV-0000000\", \"issue\": \"overbilled\", "
                  "\"billed_sdr\": 0.0, \"expected_sdr\": 0.0}]}."),
    "T4_system": ("Answer the question using only the numbered passages. After each sentence, cite the passages "
                  "that support it, like [2] or [1][3]. If the passages do not contain the answer, say that the "
                  "documents do not answer it. Answer in at most 5 sentences."),
}

T1_TOLL = [  # (category, condition, SCNT, question); 0 = the band boundary case (tons = the first band's upper limit)
    ("Containerships", "Laden", 85_000, "What Suez Canal transit dues does a laden containership of 85,000 SCNT pay?"),
    ("Crude Oil Tankers", "Ballast", 120_000,
     "How much would a crude oil tanker in ballast, 120,000 SCNT, pay in Suez transit dues?"),
    ("Liquefied Natural Gas (LNG) Carriers", "Laden", 95_500,
     "Compute the Suez toll for a loaded LNG carrier measuring 95,500 Suez Canal net tons."),
    ("Special Floating Units", "Ballast", 30_000,
     "A special floating unit of 30,000 SCNT is transiting without cargo. What are its Suez transit dues?"),
    ("Containerships", "Laden", 0, "What does a laden containership of exactly {tons:,} SCNT pay to transit the Suez "
                                   "Canal?"),
    ("Dry Bulk Vessels", "Laden", 47_250, "Suez dues for a laden dry bulk carrier of 47,250 SCNT?"),
    ("Vehicles Carriers", "Ballast", 61_000,
     "How much does a vehicles carrier in ballast with 61,000 SCNT pay for a Suez transit?"),
    ("Cruise Ships", "Laden", 72_800, "What is the Suez Canal transit charge for a laden cruise ship of 72,800 SCNT?"),
]
T1_KPI = [  # (ISO week, metric, category, question)
    (14, "invoice_count", "All", "How many Suez transit invoices did NileGate issue in ISO week 14 of 2025?"),
    (30, "billed_sdr", "Cruise Ships", "What was the total amount billed to cruise ships in week 30 of 2025, in SDR?"),
    (45, "mean_invoice_sdr", "All", "What was the average invoice amount in ISO week 45 of 2025?"),
    (8, "billed_sdr", "All", "What were the total Suez dues billed in week 8 of 2025?"),
    (22, "invoice_count", "Containerships", "How many containership invoices were there in week 22 of 2025?"),
    (37, "mean_invoice_sdr", "Petroleum Product Tankers",
     "What was the average invoice for petroleum product tankers in ISO week 37 of 2025?"),
    (51, "billed_sdr", "Liquefied Natural Gas (LNG) Carriers", "How much did we bill LNG carriers in week 51 of 2025?"),
    (3, "invoice_count", "All", "How many invoices were issued in the third ISO week of 2025?"),
]
T2_WEEKS = [6, 11, 16, 21, 26, 31, 36, 41, 46, 51]
T3_ERRORS = [0, 1, 2, 3, 1, 2, 0, 3, 1, 2]           # planted mismatches per table
T4_TYPES = ["incident", "definition", "benchmark", "money"]
LITE_SPEC = {"T1": ["t1_toll_1", "t1_toll_2", "t1_toll_4", "t1_kpi_1", "t1_kpi_2", "t1_kpi_3", "t1_search_1",
                    "t1_search_2"],
             "T2": ["t2_w11", "t2_w26", "t2_w36", "t2_w51"]}


def build_t1_numeric() -> list[dict]:
    items = []
    boundary = BANDS[("Containerships", "Laden")][0][3]
    for i, (cat, lb, tons, q) in enumerate(T1_TOLL, 1):
        tons = tons or int(boundary)
        t = toll(cat, lb, tons)
        items.append({"id": f"t1_toll_{i}", "kind": "toll", "question": q.format(tons=tons), "tool": "compute_toll",
                      "args": {"vessel_category": cat, "laden_ballast": lb, "scnt_tons": float(tons)},
                      "accept_laden_ballast": ["Laden", "Ballast"] if cat == "Special Floating Units" else [lb],
                      "expected": t["amount_sdr"]})
    for i, (week, metric, cat, q) in enumerate(T1_KPI, 1):
        v = kpi(week, metric, cat)["value"]
        assert v, f"KPI item {i}: no invoices for {cat} in week {week}"
        items.append({"id": f"t1_kpi_{i}", "kind": "kpi", "question": q, "tool": "weekly_kpi",
                      "args": {"iso_week": week, "metric": metric, "vessel_category": cat}, "expected": v})
    return items


def week_table(week: int) -> dict:
    rows, totals = [], {"invoices": 0, "billed": 0, "prev": 0}
    for cat in CATEGORIES:
        n = kpi(week, "invoice_count", cat)["value"]
        cur, prev = round(kpi(week, "billed_sdr", cat)["value"]), round(kpi(week - 1, "billed_sdr", cat)["value"])
        if n == 0 and prev == 0:
            continue
        rows.append({"category": cat, "invoices": n, "billed_sdr": cur, "wow_change_sdr": cur - prev,
                     "wow_change_pct": round(100 * (cur - prev) / prev, 1) if prev else None})
        totals["invoices"] += n
        totals["billed"] += cur
        totals["prev"] += prev
    total = {"category": "Total", "invoices": totals["invoices"], "billed_sdr": totals["billed"],
             "wow_change_sdr": totals["billed"] - totals["prev"],
             "wow_change_pct": round(100 * (totals["billed"] - totals["prev"]) / totals["prev"], 1)}
    drivers = [r["category"] for r in sorted(rows, key=lambda r: (-abs(r["wow_change_sdr"]), r["category"]))[:2]]
    return {"rows": rows, "total": total, "drivers": drivers}


def table_text(week: int, t: dict) -> str:
    head = "| category | invoices | billed_sdr | wow_change_sdr | wow_change_pct |\n|---|---|---|---|---|\n"

    def fmt(r: dict) -> str:
        pct = "n/a (no billing last week)" if r["wow_change_pct"] is None else f"{r['wow_change_pct']:+.1f}%"
        return f"| {r['category']} | {r['invoices']} | {r['billed_sdr']:,} | {r['wow_change_sdr']:+,} | {pct} |"
    return (f"NileGate Suez transit invoices, week {week} of {YEAR} (ISO), compared with week {week - 1}.\n"
            + head + "\n".join(fmt(r) for r in [*t["rows"], t["total"]]))


def build_t2() -> list[dict]:
    out = []
    for w in T2_WEEKS:
        t = week_table(w)
        values = []
        for r in [*t["rows"], t["total"]]:
            values += [r["invoices"], r["billed_sdr"], r["wow_change_sdr"]]
        pcts = [r["wow_change_pct"] for r in [*t["rows"], t["total"]] if r["wow_change_pct"] is not None]
        out.append({"id": f"t2_w{w}", "week": w, "table": table_text(w, t), "values": values, "pct_values": pcts,
                    "allowed": [w, w - 1, YEAR], "drivers": t["drivers"]})
    return out


def build_t3() -> list[dict]:
    rng = random.Random(42)
    out, serial = [], 9_100_000
    for i, n_err in enumerate(T3_ERRORS, 1):
        rows, truth = [], []
        err_at = set(rng.sample(range(8), n_err))
        for j in range(8):
            serial += rng.randint(1, 40)
            cat = rng.choice(CATEGORIES)
            lb = "Laden" if cat == "Special Floating Units" else rng.choice(["Laden", "Ballast"])
            tons = rng.randint(5, 150) * 1000 + rng.choice([0, 250, 500, 750])
            expected = toll(cat, lb, tons)["amount_sdr"]
            billed = expected
            if j in err_at:
                billed = round(expected * (1 + rng.choice([-1, 1]) * rng.uniform(0.01, 0.15)), 2)
                truth.append({"invoice_number": f"INV-{serial:07d}",
                              "issue": "overbilled" if billed > expected else "underbilled",
                              "billed_sdr": billed, "expected_sdr": expected})
            rows.append({"invoice_number": f"INV-{serial:07d}", "vessel_category": cat, "laden_ballast": lb,
                         "scnt_tons": tons, "billed_sdr": billed, "expected_sdr": expected})
        table = ("| invoice_number | vessel_category | laden_ballast | scnt_tons | billed_sdr | expected_sdr |\n"
                 "|---|---|---|---|---|---|\n" + "\n".join(
                     f"| {r['invoice_number']} | {r['vessel_category']} | {r['laden_ballast']} | {r['scnt_tons']:,} | "
                     f"{r['billed_sdr']:.2f} | {r['expected_sdr']:.2f} |" for r in rows))
        out.append({"id": f"t3_{i:02d}", "planted": n_err, "table": table, "truth": truth})
    return out


def load_frozen(name: str, sha: str) -> list[dict]:
    p = RAG_EVAL / name
    assert sha256_file(p) == sha, f"{name} is not the frozen file"
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_t4_and_search() -> tuple[list[dict], list[dict]]:
    golden = load_frozen("golden_set.jsonl", GOLDEN_SHA256)
    facts = {r["qid"]: r["facts"] for r in load_frozen("golden_facts.jsonl", FACTS_SHA256)}
    qs = [g for g in golden if g["kind"] == "query" and g["lang"] == "en"]
    assert len(qs) == 40 and all(g["qid"] in facts for g in qs)
    r = retrieval.Retriever(rerank_max_wait=180)    # the production defaults (ADR-038), patient reranker
    t4 = []
    for g in qs:
        res = r.search(g["question"], CEO)
        assert res.request["reranked"], f"{g['qid']}: the reranker was skipped (rate limit) — re-run the freeze"
        passages = [{"chunk_id": x["chunk_id"], "text": compose(x["title"], x["text"])} for x in res.results]
        fm = evaluation.FactMatcher(facts[g["qid"]])
        present = set().union(*(fm.facts_in(p["text"]) for p in passages)) - fm.facts_in(g["question"])
        t4.append({"id": f"t4_{g['qid']}", "qid": g["qid"], "type": g["type"], "question": g["question"],
                   "passages": passages, "facts": facts[g["qid"]], "measurable_facts": sorted(present)})
    search = []
    for typ in T4_TYPES:   # one search item per golden type, the first whose passages state a fact
        it = next(x for x in t4 if x["type"] == typ and x["measurable_facts"])
        search.append({"id": f"t1_search_{len(search) + 1}", "kind": "search", "question": it["question"],
                       "tool": "search_documents", "qid": it["qid"], "passages": it["passages"],
                       "facts": it["facts"], "measurable_facts": it["measurable_facts"]})
    return t4, search


def lite_ids(tasks: dict) -> dict:
    t3 = [next(x["id"] for x in tasks["T3"] if x["planted"] == n) for n in (0, 1, 2, 3)]
    t4 = []
    for typ in T4_TYPES:   # two per golden type; a type with fewer is filled from the others, in qid order
        t4 += [x["id"] for x in tasks["T4"] if x["type"] == typ and x["measurable_facts"]][:2]
    t4 += [x["id"] for x in tasks["T4"] if x["measurable_facts"] and x["id"] not in t4][:8 - len(t4)]
    return {**LITE_SPEC, "T3": t3, "T4": t4}


def deterministic_part(tasks: dict) -> dict:
    return {"T1": [x for x in tasks["T1"] if x["kind"] != "search"], "T2": tasks["T2"], "T3": tasks["T3"],
            "prompts": tasks["prompts"]}


# The number rule of T1 / T2 (owner 2026-10-10: strict) — a written number matches a value at the precision it is
# written with; only k / M (and words) and fewer decimals count as rounding, trailing zeros do not. Tested on hand
# cases here, before any model call.
NUM_RE = re.compile(r"(?<![\d.,])(?P<sign>[-+−])?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
                    r"(?:\s?(?P<suf>%|percent\b|k\b|K\b|thousand\b|M\b|mn\b|million\b|bn\b|billion\b))?")
SCALE = {"k": 1e3, "K": 1e3, "thousand": 1e3, "M": 1e6, "mn": 1e6, "million": 1e6, "bn": 1e9, "billion": 1e9}
LIST_MARK = re.compile(r"(?m)^\s*(?:\d+[.)]|[-*•])\s+")


def numbers(text: str) -> list[dict]:
    out = []
    for mt in NUM_RE.finditer(LIST_MARK.sub("", text)):
        raw = mt.group("num").replace(",", "")
        suf = mt.group("suf") or ""
        out.append({"text": mt.group(0).strip(), "value": float(raw), "decimals": len(raw.split(".")[1]) if "." in raw
                    else 0, "scale": SCALE.get(suf, 1.0), "pct": suf in ("%", "percent"),
                    "sign": {"-": -1, "−": -1, "+": 1}.get(mt.group("sign") or "", 0)})
    return out


def matches(tok: dict, value: float) -> bool:
    """An unsigned number may state a negative value ("fell by 5,120"); a signed one must have the value's sign."""
    if tok["sign"] and value and (tok["sign"] > 0) != (value > 0):
        return False
    tol = 0.5 * 10 ** -tok["decimals"] + 1e-9
    return abs(abs(value) / tok["scale"] - tok["value"]) <= tol


def one(text: str) -> dict:
    toks = numbers(text)
    assert len(toks) == 1, (text, toks)
    return toks[0]


HAND_CASES = [  # (written, table value, must match)
    ("1,234,567", 1_234_567, True), ("1.2M", 1_234_567, True), ("1.23 million", 1_234_567, True),
    ("1.3M", 1_234_567, False), ("1,235", 1_234.6, True), ("1,234", 1_234.6, False), ("1,200", 1_234.6, False),
    ("12.3%", 12.34, True), ("12%", 12.34, True), ("12.4%", 12.34, False), ("-5,120", -5_120, True),
    ("5,120", -5_120, True), ("-5,120", 5_120, False), ("+3.5%", -3.5, False), ("85k", 85_000, True),
    ("85,000.00", 85_000, True), ("2025", 2025, True)]
for written, value, expect in HAND_CASES:
    assert matches(one(written), value) == expect, (written, value, expect)
assert [t["text"] for t in numbers("- week 14: 17 invoices\n1. Cruise ships +3.5% (W14)")] == ["14", "17", "+3.5%",
                                                                                                "14"]
assert one("12.3%")["pct"] and not one("1.2M")["pct"]

rebuilt = {"T1": build_t1_numeric(), "T2": build_t2(), "T3": build_t3(), "prompts": PROMPTS}
if not TASKS_FILE.exists():
    t4, search = build_t4_and_search()
    tasks = {"version": 1, "prompts": PROMPTS, "T1": rebuilt["T1"] + search, "T2": rebuilt["T2"],
             "T3": rebuilt["T3"], "T4": t4}
    tasks["lite"] = lite_ids(tasks)
    EVAL.mkdir(parents=True, exist_ok=True)
    TASKS_FILE.write_text(json.dumps(tasks, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    print(f"tasks written: {TASKS_FILE.relative_to(ROOT).as_posix()}")
tasks = json.loads(TASKS_FILE.read_text(encoding="utf-8"))
file_sha = sha256_file(TASKS_FILE)
assert deterministic_part(tasks) == json.loads(json.dumps(rebuilt)), "T1 / T2 / T3 / prompts differ from the frozen file"
counts = {k: len(tasks[k]) for k in ("T1", "T2", "T3", "T4")}
lite_counts = {k: len(v) for k, v in tasks["lite"].items()}
all_ids = {x["id"] for k in ("T1", "T2", "T3", "T4") for x in tasks[k]}
assert counts == {"T1": 20, "T2": 10, "T3": 10, "T4": 40}, counts
assert lite_counts == {"T1": 8, "T2": 4, "T3": 4, "T4": 8}, lite_counts
assert all(i in all_ids for v in tasks["lite"].values() for i in v)
assert sum(len(x["truth"]) for x in tasks["T3"]) == sum(T3_ERRORS)
assert all(len(x["passages"]) == 8 for x in tasks["T4"])
measurable = sum(1 for x in tasks["T4"] if x["measurable_facts"])
print(f"tasks: {counts}; LITE {lite_counts}; T4 items with measurable facts: {measurable}/40; "
      f"T3 planted mismatches: {sum(T3_ERRORS)}; sha256 {file_sha}")
if TASKS_SHA256 is None:
    print("✅ Phase 2 validation passed: tasks frozen; review them, set TASKS_SHA256 to the hash above, re-run. "
          "No model was called.")
    raise SystemExit(0)
assert file_sha == TASKS_SHA256, "the tasks file is not the reviewed freeze"
print(f"✅ Phase 2 validation passed: tasks file = the reviewed freeze ({file_sha[:12]}…), deterministic parts "
      f"rebuilt identical, LITE ids valid")


# %% Phase 3 — Runs (Gemini first, then Groq, then OpenRouter LITE); every reply cached
class InvoiceException(BaseModel):
    invoice_number: str
    issue: Literal["overbilled", "underbilled"]
    billed_sdr: float
    expected_sdr: float

    @field_validator("invoice_number")
    @classmethod
    def _number(cls, v: str) -> str:            # mirrors invoices_number_format_chk
        if not re.fullmatch(r"INV-[0-9]{7}", v):
            raise ValueError("invoice_number must match INV-nnnnnnn")
        return v

    @field_validator("billed_sdr", "expected_sdr")
    @classmethod
    def _amount(cls, v: float) -> float:        # mirrors invoices_amount_chk (amounts are never negative)
        if v < 0:
            raise ValueError("amounts are >= 0")
        return v


class ExceptionsReport(BaseModel):
    exceptions: list[InvoiceException]


METHODS = {"gemini": ["function_calling", "json_schema", "json_mode"],
           "groq": ["function_calling", "json_schema", "json_mode"], "openrouter": ["function_calling"]}
THINK_RE = re.compile(r"(?s)<think>.*?</think>")


def visible(text: str) -> str:
    return THINK_RE.sub("", text or "").strip()


def call_info(r: llm.Reply) -> dict:
    return {"cached": r.cached, "latency_ms": r.latency_ms, "tokens": (r.usage or {}).get("total_tokens")}


def run_t1(m: llm.LLM, item: dict) -> dict:
    msgs = [SystemMessage(tasks["prompts"]["T1_system"]), HumanMessage(item["question"])]
    calls, info = [], []
    for _ in range(3):
        r = m.invoke(msgs, data_origin="synthetic", tools=TOOLS)
        info.append(call_info(r))
        if not r.ok:
            return {"error": r.error, "calls": calls, "answer": None, "requests": info}
        msg = r.message
        if not msg.tool_calls:
            return {"answer": visible(llm.message_text(msg)), "calls": calls, "requests": info}
        msgs.append(msg)
        for i, c in enumerate(msg.tool_calls):
            calls.append({"name": c["name"], "args": c["args"]})
            msgs.append(ToolMessage(run_tool(c["name"], c["args"], item), tool_call_id=c.get("id") or f"call_{i}",
                                    name=c["name"]))
    return {"answer": None, "calls": calls, "requests": info, "note": "no final answer after 3 tool rounds"}


def run_t2(m: llm.LLM, item: dict) -> dict:
    r = m.invoke([SystemMessage(tasks["prompts"]["T2_system"]), HumanMessage(item["table"])],
                 data_origin="synthetic")
    return {"answer": visible(llm.message_text(r.message)) if r.ok else None, "error": r.error,
            "requests": [call_info(r)]}


def run_t3(m: llm.LLM, item: dict) -> dict:
    out = {}
    for method in METHODS[m.provider]:
        r = m.invoke([SystemMessage(tasks["prompts"]["T3_system"]), HumanMessage(item["table"])],
                     data_origin="synthetic", schema=ExceptionsReport, method=method)
        parsed, why = llm.parse_structured(r, ExceptionsReport)
        out[method] = {"valid": parsed is not None, "why": why, "requests": [call_info(r)],
                       "exceptions": [e.model_dump() for e in parsed.exceptions] if parsed else None}
    return out


def run_t4(m: llm.LLM, item: dict) -> dict:
    msgs = [SystemMessage(tasks["prompts"]["T4_system"]),
            HumanMessage(f"Passages:\n\n{format_passages(item['passages'])}\n\nQuestion: {item['question']}")]
    r = m.invoke(msgs, data_origin="public")
    return {"answer": visible(llm.message_text(r.message)) if r.ok else None, "error": r.error,
            "requests": [call_info(r)]}


RUNNERS = {"T1": run_t1, "T3": run_t3, "T2": run_t2, "T4": run_t4}   # tools role first, then writer role
quota = llm.QuotaState()
by_id = {x["id"]: x for k in ("T1", "T2", "T3", "T4") for x in tasks[k]}
models_info, outcomes = {}, {}
import httpx  # noqa: E402

with httpx.Client(timeout=30.0) as client:
    for provider, cfg in llm.PROVIDERS.items():
        if not llm.has_key(provider):
            for model in cfg["candidates"]:
                models_info[f"{provider}/{model}"] = {"status": "skipped", "why": f"{cfg['key']} missing"}
            continue
        served = llm.available_models(provider, client)
        for model in cfg["candidates"]:
            name = f"{provider}/{model}"
            if model not in served:
                models_info[name] = {"status": "skipped", "why": "not served today (live model list)"}
                continue
            if name in UNAVAILABLE:
                models_info[name] = {"status": "skipped", "why": UNAVAILABLE[name]}
                continue
            lite_only = provider == "openrouter" or name in LITE_ONLY
            subset = tasks["lite"] if lite_only else {k: [x["id"] for x in tasks[k]] for k in RUNNERS}
            m = llm.LLM(provider, model, quota=quota)
            res, stop = {k: {} for k in RUNNERS}, None
            for task, runner in RUNNERS.items():
                for item_id in subset[task]:
                    if stop:
                        break
                    try:
                        res[task][item_id] = runner(m, by_id[item_id])
                    except llm.Exhausted as e:
                        stop = str(e)
            planned = sum(len(subset[k]) for k in RUNNERS)
            done = sum(len(v) for v in res.values())
            models_info[name] = {"status": "complete" if done == planned else "partial", "planned": planned,
                                 "done": done, "set": "lite" if lite_only else "full",
                                 "calls": m.calls, "cache_hits": m.hits, "stopped": stop}
            outcomes[name] = res
            print(f"{name}: {done}/{planned} items ({m.calls} calls, {m.hits} cached)"
                  + (f" — stopped: {stop[:160]}" if stop else ""), flush=True)

n_complete = sum(1 for v in models_info.values() if v["status"] == "complete")
print(f"✅ Phase 3 validation passed: {len(models_info)} candidates — {n_complete} complete, "
      f"{sum(1 for v in models_info.values() if v['status'] == 'partial')} partial, "
      f"{sum(1 for v in models_info.values() if v['status'] == 'skipped')} skipped; "
      f"generation calls this run: {sum(v.get('calls', 0) for v in models_info.values())}")


# %% Phase 4 — Scores (deterministic, no LLM judge) and the selection per role
def t1_score(item: dict, out: dict) -> dict:
    calls = out.get("calls", [])
    ok_tool = any(c["name"] == item["tool"] for c in calls)
    if item["kind"] == "toll":
        def good(a):
            return (a.get("vessel_category") == item["args"]["vessel_category"]
                    and a.get("laden_ballast") in item["accept_laden_ballast"]
                    and abs(float(a.get("scnt_tons", -1)) - item["args"]["scnt_tons"]) < 1e-6)
    elif item["kind"] == "kpi":
        def good(a):
            return all(a.get(k) == v for k, v in item["args"].items())
    else:
        def good(a):
            return isinstance(a.get("query"), str) and len(a["query"].strip()) >= 3
    ok_args = any(c["name"] == item["tool"] and good(c["args"] or {}) for c in calls)
    answer = out.get("answer") or ""
    if item["kind"] == "search":
        fm = evaluation.FactMatcher(item["facts"])
        stated = fm.facts_in(item["question"] + "\n" + answer) - fm.facts_in(item["question"])
        ok_answer = bool(stated & set(item["measurable_facts"]))
    else:
        ok_answer = any(not t["pct"] and matches(t, item["expected"]) for t in numbers(answer))
    return {"tool": ok_tool, "args": ok_args, "answer": ok_answer, "correct": ok_tool and ok_args and ok_answer}


def t2_score(item: dict, out: dict) -> dict:
    answer = out.get("answer")
    if not answer:   # no visible text (e.g. the output budget went to reasoning): no number written, nothing covered
        return {"answered": False, "faithful": True, "coverage": 0.0, "bullets": 0, "unsupported": []}
    values = item["values"] + item["allowed"]
    bad = [t["text"] for t in numbers(answer)
           if not any(matches(t, v) for v in (item["pct_values"] if t["pct"] else values))]
    named = [d for d in item["drivers"] if re.search(ALIASES[d], answer, re.I)]
    bullets = sum(1 for line in answer.splitlines() if re.match(r"\s*[-*•]\s+", line))
    return {"answered": True, "faithful": not bad, "coverage": len(named) / len(item["drivers"]), "bullets": bullets,
            "unsupported": bad[:10]}


def t3_score(item: dict, out: dict) -> dict:
    truth = {(e["invoice_number"], e["issue"]): e for e in item["truth"]}
    per = {}
    for method, r in out.items():
        if not r["valid"]:
            per[method] = {"valid": False, "exact": False, "score": 0.0}
            continue
        got = {(e["invoice_number"], e["issue"]): e for e in r["exceptions"]}
        exact = (got.keys() == truth.keys() and len(got) == len(r["exceptions"])
                 and all(abs(got[k]["billed_sdr"] - v["billed_sdr"]) < 0.01
                         and abs(got[k]["expected_sdr"] - v["expected_sdr"]) < 0.01 for k, v in truth.items()))
        per[method] = {"valid": True, "exact": exact, "score": float(exact)}
    return per


CITE_RE = re.compile(r"\[(\d+(?:\s*[,;]\s*\d+)*)\]")
NATIVE_CITE_RE = re.compile(r"【(\d+)†[^】]*】")   # gpt-oss's trained format; accepted (owner 2026-10-11), format logged


def t4_score(item: dict, out: dict) -> dict:
    answer = out.get("answer") or ""
    fm = evaluation.FactMatcher(item["facts"])
    measurable = set(item["measurable_facts"])
    stated = (fm.facts_in(item["question"] + "\n" + answer) - fm.facts_in(item["question"])) & measurable
    asked = {int(n) for grp in CITE_RE.findall(answer) for n in re.split(r"\s*[,;]\s*", grp)}
    native = {int(n) for n in NATIVE_CITE_RE.findall(answer)}
    cited = asked | native
    in_range = bool(cited) and all(1 <= n <= len(item["passages"]) for n in cited)
    supported = {f for f in stated if any(f in fm.facts_in(item["passages"][n - 1]["text"]) for n in cited
                                          if 1 <= n <= len(item["passages"]))}
    return {"recall": len(stated) / len(measurable) if measurable else None,
            "citation": (len(supported) / len(stated) if stated else 1.0) if in_range else 0.0,
            "format_ok": bool(asked) and not native, "cited": sorted(cited), "stated": sorted(stated)}


SCORERS = {"T1": t1_score, "T2": t2_score, "T3": t3_score, "T4": t4_score}


def mean(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.fmean(xs), 4) if xs else None


def metrics(name: str, ids: dict | None) -> dict:
    """The role metrics of one model over `ids` (LITE) or over every item it ran (None)."""
    res = outcomes.get(name, {})
    pick = lambda task: [(by_id[i], res[task][i]) for i in (ids[task] if ids else res[task]) if i in res[task]]  # noqa: E731
    t1 = [t1_score(it, o) for it, o in pick("T1")]
    t2 = [t2_score(it, o) for it, o in pick("T2")]
    t3 = [t3_score(it, o) for it, o in pick("T3")]
    t4 = [t4_score(it, o) for it, o in pick("T4")]
    methods = {mt: mean([s[mt]["score"] for s in t3 if mt in s]) for mt in METHODS[name.split("/")[0]]}
    validity = {mt: mean([float(s[mt]["valid"]) for s in t3 if mt in s]) for mt in methods}
    best = max((mt for mt in methods if methods[mt] is not None), key=lambda mt: methods[mt], default=None)
    return {"n": {"T1": len(t1), "T2": len(t2), "T3": len(t3), "T4": len(t4)},
            "t1_accuracy": mean([float(s["correct"]) for s in t1]),
            "t1_tool": mean([float(s["tool"]) for s in t1]), "t1_args": mean([float(s["args"]) for s in t1]),
            "t2_faithful_all": all(s["faithful"] for s in t2) if t2 else None,   # None = no T2 item ran yet
            "t2_faithfulness": mean([float(s["faithful"]) for s in t2]),
            "t2_answer_rate": mean([float(s["answered"]) for s in t2]),
            "t4_format_ok": mean([float(s["format_ok"]) for s in t4]),
            "t2_coverage": mean([s["coverage"] for s in t2]),
            "t2_unsupported_examples": [u for s in t2 for u in s["unsupported"]][:8],
            "t3_by_method": methods, "t3_validity_by_method": validity, "t3_best_method": best,
            "t3_score": methods.get(best) if best else None,
            "t4_recall": mean([s["recall"] for s in t4]), "t4_citation": mean([s["citation"] for s in t4])}


def quota_fit(name: str) -> dict:
    provider = name.split("/")[0]
    res, cfg, out = outcomes.get(name, {}), llm.PROVIDERS[provider], {}
    tok, lat = {}, {}
    for task in RUNNERS:
        reqs = []
        for o in res.get(task, {}).values():
            reqs += [q for v in (o.values() if task == "T3" else [o]) for q in v.get("requests", [])]
        tok[task] = mean([q["tokens"] for q in reqs])
        lat[task] = statistics.median([q["latency_ms"] for q in reqs if q["latency_ms"]]) if any(
            q["latency_ms"] for q in reqs) else None
    known, seen = quota.daily_limit(provider, name.split("/", 1)[1])
    for role, mix in PACK.items():
        tokens = sum(n * (tok[t] or 0) for t, n in mix.items())
        requests = sum(mix.values())
        out[role] = {"requests_per_pack": requests, "tokens_per_pack": round(tokens),
                     "daily_limit": known, "daily_requests_seen": seen,
                     # owner 2026-10-10: quota fit = packs per day (the daily request limit binds on free tiers);
                     # an unknown limit counts with the requests already served in one day (a lower bound)
                     "packs_per_day": round((known or seen) / requests, 1), "packs_per_day_is_lower_bound": not known,
                     "tpm_minutes_per_pack": round(tokens / cfg["tpm"], 2),
                     "median_latency_ms": mean([lat[t] for t in mix])}
    return out


lite = tasks["lite"]
table = {}
for name, info in models_info.items():
    if name not in outcomes:
        continue
    lm, fm_ = metrics(name, lite), metrics(name, None)
    complete_lite = all(len([i for i in lite[t] if i in outcomes[name][t]]) == len(lite[t]) for t in RUNNERS)
    writer = mean([lm["t2_coverage"], lm["t4_recall"], lm["t4_citation"]])
    tools = mean([lm["t1_accuracy"], lm["t3_score"]])
    table[name] = {"lite": lm, "full": fm_ if info["set"] == "full" else None, "complete_lite": complete_lite,
                   "gate_t2": fm_["t2_faithful_all"], "score_writer_insight": writer, "score_tools": tools,
                   "quota_fit": quota_fit(name)}


def select(role: str) -> dict:
    key = "score_writer_insight" if role == "writer_insight" else "score_tools"
    elig = [(n, r) for n, r in table.items() if r["complete_lite"] and r[key] is not None
            and (role != "writer_insight" or r["gate_t2"])]
    elig.sort(key=lambda nr: -nr[1][key])
    ordered, i = [], 0
    while i < len(elig):        # tie groups: within TIE of the group's best → quota fit, then latency
        group = [e for e in elig[i:] if elig[i][1][key] - e[1][key] < TIE]
        group.sort(key=lambda nr: (-nr[1]["quota_fit"][role]["packs_per_day"],
                                   nr[1]["quota_fit"][role]["tpm_minutes_per_pack"],
                                   nr[1]["quota_fit"][role]["median_latency_ms"] or 1e9))
        ordered += group
        i += len(group)
    main = ordered[0][0] if ordered else None
    fallback = next((n for n, _ in ordered if main and n.split("/")[0] != main.split("/")[0]), None)
    return {"main": main, "fallback": fallback, "ranking": [(n, r[key]) for n, r in ordered],
            "excluded_by_gate": [n for n, r in table.items() if role == "writer_insight" and r["gate_t2"] is False],
            "incomplete": [n for n, r in table.items() if not r["complete_lite"]]}


selection = {role: select(role) for role in PACK}
all_done = all(v["status"] in ("complete", "skipped") for v in models_info.values()) and not any(
    v["status"] == "skipped" and "missing" in v["why"] for v in models_info.values())
status = "FINAL" if all_done and all(s["main"] and s["fallback"] for s in selection.values()) else "PROPOSED"
results = {"date_utc": dt.datetime.now(dt.timezone.utc).date().isoformat(), "tasks_sha256": file_sha,
           "status": status, "models": models_info, "scores": table, "selection": selection,
           "rules": {"tie": TIE, "pack": PACK, "methods": METHODS},
           "outcomes": outcomes}
OUT = EVAL / f"llm_bakeoff_{results['date_utc']}.json"
OUT.write_text(json.dumps(results, ensure_ascii=False, indent=1, default=str), encoding="utf-8", newline="\n")
for name, r in table.items():
    lm = r["lite"]
    gate = {True: "pass", False: "FAIL", None: "n/a"}[r["gate_t2"]]
    print(f"{name}: writer {r['score_writer_insight']} (gate {gate}; cov "
          f"{lm['t2_coverage']}, recall {lm['t4_recall']}, cite {lm['t4_citation']}) | tools {r['score_tools']} "
          f"(T1 {lm['t1_accuracy']}, T3 {lm['t3_score']} {lm['t3_best_method']})"
          f"{'' if r['complete_lite'] else ' [LITE incomplete]'}")
for role, s in selection.items():
    print(f"{role}: main {s['main']}, fallback {s['fallback']}; gate-excluded {len(s['excluded_by_gate'])}, "
          f"incomplete {len(s['incomplete'])}")
print(f"✅ Phase 4 validation passed: scores for {len(table)} models, selection {status}, "
      f"results → {OUT.relative_to(ROOT).as_posix()}")


# %% Final Checkpoint
back = json.loads(OUT.read_text(encoding="utf-8"))
assert back["tasks_sha256"] == TASKS_SHA256 == sha256_file(TASKS_FILE)
assert set(back["models"]) == {f"{p}/{m}" for p, c in llm.PROVIDERS.items() for m in c["candidates"]}
assert all(v["status"] in ("complete", "partial", "skipped") for v in back["models"].values())
assert back["status"] in ("FINAL", "PROPOSED")
print(f"✅ Final Checkpoint: tasks frozen ({TASKS_SHA256[:12]}…), {n_complete}/9 candidates complete, selection "
      f"{back['status']} — narrative in pipelines/checkpoints/agents/LLM_bakeoff.md")
