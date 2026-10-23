"""Deck check (Agents plan Phase 6, §5c): number slots, the NileGate PPTX, the Validator v2 and its planted numbers.

Plan:    docs/plans/Agents_plan.md §5c (owner decisions P6-1…P6-8, approved 2026-10-19); one phase per test of §5c.
Run:     uv run python tools/run.py pipelines/scripts/agents/Deck_check.py  (from the project root)

Reads:   PostgreSQL read-only (PG_RO_USER): employees / roles / departments, the finance views, the audit views.
         No LLM call in Phases 1–4.
Writes:  nothing yet (later phases: a throw-away temp folder for the rendered decks).
Re-run:  safe (read-only on the database).

Phases (§5c "Tests")
1. Slots (S1): syntax, every format, rounding half away from zero, signs, |dir, refused slots with their fix;
   every rendered value passes the Validator's rounding rule on the real evidence of weeks 10 and 23.
2. 52 clean decks of a slot Writer pass V1–V7, as slots and as literal text (S2); the rendered PPTX and V8 (S3).
3. Planted wrong numbers: 17 classes × the golden weeks 5 / 10 / 23 / 49, 100 % caught (S2); PPTX classes (S3).
4. The real failures replayed: the Phase 5 run (S2) and the first Phase 6 run (S6). Real models: Weekly_pack_check
   Phase 5.
Final Checkpoint (pending phases listed).
"""
# %% Setup
import os
import sys
from pathlib import Path

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())
sys.path.insert(0, str(ROOT))
from pipelines.agents.deck import slots  # noqa: E402
from pipelines.lib import common  # noqa: E402

common.load_env(ROOT)
E = os.environ
DONE: list[int] = []

# %% Phase 1 — Slots (S1)
# The Writer refers to a number, code writes it (P6-1): `{evidence id[row key]:field|format|dir}`. Checked on
# hand-made evidence: each kind's formats (money as returned / M / k, percent 2 / 1 decimals, days, counts, public
# numbers as returned), rounding half away from zero with the sign kept (−849,964.00 → −850.0 k), changes always
# signed, |dir (P6-3) writing up / down / unchanged, result-level fields (audit totals), row keys incl. the audit's
# invoice/check pair; refused: unknown evidence, a failed result, a web result (ADR-049), a missing row, an ambiguous
# key, a field cited from the wrong result (the S6 week-23 error: the hint names the result that has it), a wrong
# format, |dir on a level, a null, a text field, a malformed slot. Then on the real evidence of weeks 10 and 23 every
# numeric field in every allowed format is rendered and read back by the Validator's own parser
# (`deck/validator.number_tokens` / `number_matches`): the renderer never writes a number the Validator would refuse.
from pipelines.agents.graphs import weekly_pack as wp  # noqa: E402
from pipelines.agents.deck import validator as v2  # noqa: E402
from pipelines.agents.tools import context, db  # noqa: E402

people = db.fetch("SELECT e.employee_id, r.role_name, d.department_name FROM employees e "
                  "JOIN roles r USING (role_id) JOIN departments d USING (department_id) ORDER BY e.employee_id")
fin_mgr = context.load_user(next(p["employee_id"] for p in people
                                 if p["role_name"] == "manager" and p["department_name"] == "Finance"))


def _res(tool, view, rows, **extra):
    return {"tool": tool, "status": "ok", "rows": rows, "source": {"kind": "view", "name": view, "filter": "f"},
            "note": None, **extra}


EV = {
    "kpi.weekly": _res("finance_kpi", "finance.kpi_weekly", [{
        "iso_week_label": "2025-W23", "is_warmup": False, "invoices_billed": 19, "billed_sdr": 8394785.98,
        "collected_wow_pct": -15.76, "budget_variance_sdr": -849964.0, "budget_variance_pct": 25.835,
        "dso_days": 55.3, "dso_wow_days": -1.0, "billed_wow_pct": None, "top10_share_13w_pct": 59.47,
        "ar_sdr": 47630979.69}]),
    "kpi.category": _res("finance_kpi", "finance.kpi_weekly_category", [
        {"vessel_category": "Crude Oil Tankers", "billed_sdr": 2114698.27, "billed_wow_change_sdr": 2114698.27,
         "billed_wow_pct": 125.0},
        {"vessel_category": "Cruise Ships", "billed_sdr": 703818.24, "billed_wow_change_sdr": -1070881.98,
         "billed_wow_pct": -60.34},
        {"vessel_category": "Dry Bulk Vessels", "billed_sdr": 899613.8, "billed_wow_change_sdr": 0.0,
         "billed_wow_pct": 0.0}]),
    "kpi.customers": _res("finance_kpi", "finance.kpi_customer_13w", [
        {"customer_name": "Alpha Lines", "share_13w_pct": 9.125, "rank_13w": 1},
        {"customer_name": "Beta Maritime", "share_13w_pct": 7.5, "rank_13w": 2}]),
    "kpi.overdue": _res("finance_kpi", "finance.kpi_overdue_list", [
        {"invoice_number": "INV-0000123", "amount_sdr": 1234.5, "days_past_due": 1}]),
    "audit.week": _res("invoice_audit", "finance.invoice_audit", [
        {"invoice_number": "INV-0000626", "check_code": "duplicate_charge", "difference_sdr": 81837.02},
        {"invoice_number": "INV-0000626", "check_code": "amount_mismatch", "difference_sdr": -5.0}],
        invoices_checked=19, invoices_flagged=1, amount_at_stake_sdr=81837.02,
        findings_by_check={"duplicate_charge": 1}),
    "insight.suez": _res("suez_transits", "portwatch", [{"date": "2025-06-02", "n_total": 31, "capacity": 1.25e6}],
                         mean_daily_transits=32.4),
    "insight.web": _res("web_search", "tavily", [{"title": "Canal revenue 7.5 M", "rank": 7}]),
    "insight.down": {"tool": "suez_transits", "status": "context_unavailable", "rows": [], "source": None,
                     "note": "timeout"},
}

TEXT_CASES = {
    "money as returned": "{kpi.weekly:billed_sdr}",
    "money M": "{kpi.weekly:billed_sdr|M}",
    "money k, change signed, half away": "{kpi.weekly:budget_variance_sdr|k}",
    "money M, change": "{kpi.weekly:budget_variance_sdr|M}",
    "pct default 2, half away": "{kpi.weekly:budget_variance_pct}",
    "pct 1": "{kpi.weekly:budget_variance_pct|%1}",
    "pct negative 1": "{kpi.weekly:collected_wow_pct|%1}",
    "days float": "{kpi.weekly:dso_days}",
    "days change": "{kpi.weekly:dso_wow_days}",
    "days int singular": "{kpi.overdue[INV-0000123]:days_past_due}",
    "count": "{kpi.weekly:invoices_billed} invoices",
    "dir down pct": "{kpi.weekly:collected_wow_pct|%1|dir}",
    "dir up money M": "{kpi.category[Crude Oil Tankers]:billed_wow_change_sdr|M|dir}",
    "dir down money M": "{kpi.category[Cruise Ships]:billed_wow_change_sdr|M|dir}",
    "dir unchanged": "{kpi.category[Dry Bulk Vessels]:billed_wow_change_sdr|dir}",
    "dir without format": "{kpi.weekly:dso_wow_days|dir}",
    "level stays unsigned": "{kpi.category[Cruise Ships]:billed_sdr|M}",
    "row key, pct": "{kpi.customers[Alpha Lines]:share_13w_pct|%1}",
    "audit pair key": "{audit.week[INV-0000626/duplicate_charge]:difference_sdr}",
    "audit pair key, negative": "{audit.week[INV-0000626/amount_mismatch]:difference_sdr}",
    "audit total": "{audit.week:invoices_checked} invoices checked, {audit.week:amount_at_stake_sdr|k} at stake",
    "public number result-level": "{insight.suez:mean_daily_transits} transits a day",
    "public number large": "{insight.suez[2025-06-02]:capacity}",
    "sentence": "Collected {kpi.weekly:ar_sdr|M}; DSO {kpi.weekly:dso_days} in week 23 of 2025",
    # refused (the fix the Writer reads)
    "unknown evidence": "{kpi.nope:billed_sdr}",
    "failed result": "{insight.down:n_total}",
    "web result": "{insight.web:rank}",
    "missing row": "{kpi.category[Tugs]:billed_sdr}",
    "ambiguous key": "{audit.week[INV-0000626]:difference_sdr}",
    "list without key": "{kpi.category:billed_sdr}",
    "key on one row": "{kpi.weekly[x]:billed_sdr}",
    "wrong dataset (S6 week 23)": "{kpi.customers:top10_share_13w_pct}",
    "wrong dataset, keyed": "{kpi.customers[Alpha Lines]:top10_share_13w_pct}",
    "format not allowed": "{kpi.weekly:top10_share_13w_pct|M}",
    "dir on a level": "{kpi.weekly:billed_sdr|M|dir}",
    "null (WoW n/a)": "{kpi.weekly:billed_wow_pct}",
    "text field": "{kpi.weekly:iso_week_label}",
    "flag field": "{kpi.weekly:is_warmup}",
    "malformed": "Billed {kpi.weekly billed_sdr} and {kpi.weekly:billed_sdr|M",
}


def _render(text):
    out, bound, errors = slots.render_text(text, EV)
    return out if not errors else "ERR " + " | ".join(e.message for e in errors)


text_actual = {k: _render(t) for k, t in TEXT_CASES.items()}

# the Validator's parser reads back every rendered value of the real evidence (weeks 10 and 23)
readback = {"values": 0, "formats": 0, "dir": 0, "failed": []}
for w in (10, 23):
    real = {**wp.kpi_evidence(fin_mgr, w), **wp.audit_evidence(fin_mgr, w, "live")}
    for eid, res in real.items():
        keys = slots.row_keys(res)
        for i, row in enumerate(res["rows"]):
            for field, value in row.items():
                kind = slots.field_kind(field, value)
                if kind is None:
                    continue
                readback["values"] += 1
                key = f"[{'/'.join(str(row[k]) for k in keys)}]" if keys else ""
                for fmt in slots.FORMATS[kind]:
                    for direction in ((False, True) if slots.is_change(field) else (False,)):
                        slot = "{" + f"{eid}{key}:{field}|{fmt}" + ("|dir" if direction else "") + "}"
                        text, bound, errors = slots.render_text(slot, real)
                        toks = v2.number_tokens(text, [])
                        target = abs(value) if direction else value
                        if direction and value == 0:          # "unchanged": no number to read back
                            ok = not errors and text == "unchanged" and not toks
                        else:
                            ok = (not errors and len(toks) == 1 and bound[0].row == i
                                  and v2.number_matches(toks[0][1], toks[0][2], toks[0][3], target))
                        readback["dir" if direction else "formats"] += 1
                        if not ok:
                            readback["failed"].append((w, slot, text, [e.message for e in errors]))

# reviewed snapshot (2026-10-19): the rendered text of each case, and the read-back counts of weeks 10 + 23
ERR_IDS = "audit.week, insight.down, insight.suez, insight.web, kpi.category, kpi.customers, kpi.overdue, kpi.weekly"
text_expected = {
    "money as returned": "8,394,785.98 SDR", "money M": "8.39 M SDR",
    "money k, change signed, half away": "−850.0 k SDR", "money M, change": "−0.85 M SDR",
    "pct default 2, half away": "+25.84 %", "pct 1": "+25.8 %", "pct negative 1": "−15.8 %",
    "days float": "55.3 days", "days change": "−1.0 days", "days int singular": "1 day", "count": "19 invoices",
    "dir down pct": "down 15.8 %", "dir up money M": "up 2.11 M SDR", "dir down money M": "down 1.07 M SDR",
    "dir unchanged": "unchanged", "dir without format": "down 1.0 days", "level stays unsigned": "0.70 M SDR",
    "row key, pct": "9.1 %", "audit pair key": "+81,837.02 SDR", "audit pair key, negative": "−5.00 SDR",
    "audit total": "19 invoices checked, 81.8 k SDR at stake",
    "public number result-level": "32.4 transits a day", "public number large": "1,250,000.0",
    "sentence": "Collected 47.63 M SDR; DSO 55.3 days in week 23 of 2025",
    "unknown evidence": f"ERR no evidence 'kpi.nope'; cite one of: {ERR_IDS}",
    "failed result": "ERR insight.down has status context_unavailable: no number from it",
    "web result": "ERR insight.web is a web_search result: document and web text never gives a number (ADR-049); "
                  "write it as context without a slot",
    "missing row": "ERR no row 'Tugs' in kpi.category (key vessel_category); rows: Crude Oil Tankers, Cruise Ships, "
                   "Dry Bulk Vessels — name the row by its vessel_category, e.g. "
                   "{kpi.category[Crude Oil Tankers]:billed_sdr}",
    "ambiguous key": "ERR 'INV-0000626' matches 2 rows of audit.week: name one of INV-0000626/duplicate_charge, "
                     "INV-0000626/amount_mismatch",
    "list without key": "ERR kpi.category has 3 rows: name one as kpi.category[<vessel_category>]",
    "key on one row": "ERR kpi.weekly has one row: drop [x]",
    "wrong dataset (S6 week 23)": "ERR kpi.customers has no field 'top10_share_13w_pct'; it is in kpi.weekly",
    "wrong dataset, keyed": "ERR kpi.customers has no field 'top10_share_13w_pct'; it is in kpi.weekly",
    "format not allowed": "ERR format 'M' not allowed for top10_share_13w_pct (pct): use %2 or %1",
    "dir on a level": "ERR |dir only on a change field (wow, change, variance, difference), not billed_sdr",
    "null (WoW n/a)": "ERR billed_wow_pct is null in kpi.weekly (not available this week): write 'not available' "
                      "without a slot",
    "text field": "ERR iso_week_label is not a number ('2025-W23'): copy it as text",
    "flag field": "ERR is_warmup is not a number (False): copy it as text",
    "malformed": "ERR malformed slot: write {<evidence id>[<row>]:<field>|<format>} | malformed slot: write "
                 "{<evidence id>[<row>]:<field>|<format>}",
}
actual = {"text": text_actual, "readback": readback}
expected = {"text": text_expected, "readback": {"values": 905, "formats": 1820, "dir": 396, "failed": []}}
assert actual == expected, {k: v for k, v in text_actual.items() if text_expected.get(k) != v} or readback
refused = sum(v.startswith("ERR") for v in text_actual.values())
print(f"Phase 1: {len(TEXT_CASES)} text cases ({refused} refused with their fix); read-back of weeks 10 + 23: "
      f"{readback['values']} values, {readback['formats']} formats + {readback['dir']} |dir, 0 refused")
print(f"✅ Phase 1 validation passed: slots — every format, half away from zero, signs and |dir as reviewed; "
      f"{refused} wrong slots refused with the fix (wrong dataset names the result that has the field); "
      f"{readback['formats'] + readback['dir']} rendered values of the real weeks pass the Validator's parser")
DONE.append(1)

# %% Phase 2 — 52 clean decks (S2: drafts; S3 adds the rendered PPTX)
# The false-alarm base of the Validator v2: a deterministic slot Writer (the §5c deck: slide titles, five summary
# bullets, at most three comments on slides 3–8, a context line on 9, nothing on 1 and 10; nulls written as "not
# available") drafts every week of 2025 from the week's real evidence; every draft must pass V1–V7 with no problem.
import copy  # noqa: E402
import re  # noqa: E402

from pipelines.agents.deck import validator as v2  # noqa: E402

LABEL = "Draft for approval"


def week_evidence(w):
    return {**wp.kpi_evidence(fin_mgr, w), **wp.audit_evidence(fin_mgr, w, "live")}


from pipelines.agents.deck.sample import slot_draft, top3  # noqa: E402

EVS, DRAFTS, RENDERED, clean, clean_lit = {}, {}, {}, {}, {}


def problems_of(verdict):
    return [(p.rule, p.slide, p.bullet, p.token, p.message) for p in verdict.problems]


for w in range(1, 53):
    EVS[w] = week_evidence(w)
    DRAFTS[w] = slot_draft(w, EVS[w])
    clean[w] = problems_of(v2.validate(DRAFTS[w], EVS[w], w))
    # the same deck with every slot filled = what a human edit looks like: literal numbers, bound by search
    RENDERED[w] = v2.render_draft(DRAFTS[w], EVS[w])
    clean_lit[w] = problems_of(v2.validate(RENDERED[w], EVS[w], w))
false_alarms = {w: p for w, p in clean.items() if p}
false_alarms_lit = {w: p for w, p in clean_lit.items() if p}
n_slots = sum(len(slots.find_slots(b["text"])) for d in DRAFTS.values() for b in d["bullets"])
n_bullets = sum(len(d["bullets"]) for d in DRAFTS.values())
# the PPTX of every week (S3): rendered from the slot draft, read back, V8 = 0 problems
import time  # noqa: E402

from pipelines.agents.deck import readback, render  # noqa: E402

PPTX, READY, v8_clean, shape_counts, warm_notes = {}, {}, {}, {}, []
t0 = time.time()
for w in range(1, 53):
    READY[w] = wp.check_readiness(fin_mgr, w)
    PPTX[w] = render.render(DRAFTS[w], EVS[w], READY[w], LABEL)
    v8_clean[w] = [(p.slide, p.token, p.message) for p in readback.validate_pptx(PPTX[w], DRAFTS[w], EVS[w],
                                                                                   READY[w], LABEL)]
    got = readback.read(PPTX[w])
    kinds = [it["kind"] for sl in got for _, it in sl]
    shape_counts[w] = (len(got), kinds.count("chart"), kinds.count("table"))
    if any(n == "tpl:footnote" for sl in got for n, _ in sl):
        warm_notes.append(w)
render_s = time.time() - t0
for pw in (10, 23):                       # for the owner's look (Notebooks/_scratch is git-ignored): a week with an
    (ROOT / "Notebooks" / "_scratch" / f"deck_preview_2025-W{pw}.pptx").write_bytes(PPTX[pw])   # audit finding
v8_false = {w: p for w, p in v8_clean.items() if p}
tables = {w: c[2] for w, c in shape_counts.items()}

actual = {"bullets": n_bullets, "slots": n_slots, "false_alarms": false_alarms, "false_alarms_lit": false_alarms_lit,
          "v8_false": v8_false, "slides_charts": sorted({c[:2] for c in shape_counts.values()}),
          "audit_table_weeks": sorted(w for w in tables if EVS[w]["audit.week"]["rows"]),
          "tables_ok": all(tables[w] == 3 + bool(EVS[w]["audit.week"]["rows"]) + bool(EVS[w]["kpi.overdue"]["rows"])
                           for w in tables),
          "footnote_weeks": warm_notes}
# reviewed snapshot (2026-10-19): 16 bullets a week, 1,285 slots, no problem on any week in any form; every deck 10
# slides and 3 native charts; tables = drivers + customers + sources, + overdue when there is one, + audit in the
# weeks with findings (10 / 15 / 50); the warm-up footnote on weeks 1–13 only
expected = {"bullets": 832, "slots": 1285, "false_alarms": {}, "false_alarms_lit": {}, "v8_false": {},
            "slides_charts": [(10, 3)], "audit_table_weeks": [10, 15, 50], "tables_ok": True,
            "footnote_weeks": list(range(1, 14))}
assert actual == expected, actual
print(f"Phase 2: 52 drafts, {n_bullets} bullets, {n_slots} slots; problems: slot form 0, literal form 0; 52 PPTX "
      f"rendered and read back in {render_s:.0f} s, V8 problems 0; previews of weeks 10 / 23 in Notebooks/_scratch/")
print("✅ Phase 2 validation passed: 52 / 52 weeks of the slot Writer pass V1–V7 as slots and as literal text, and "
      "their rendered PPTX pass V8 (10 slides, 3 native charts, the tables of the week, warm-up footnote on 1–13)")
DONE.append(2)

# %% Phase 3 — Planted wrong numbers (S2: drafts; S3 adds the PPTX)
# §5 done-when: the Validator catches every planted wrong number in a test deck. A frozen catalogue of mutation
# classes, each planted alone in a clean deck of the golden weeks 5 (warm-up), 10 (duplicate charge), 23, 49:
# in the rendered (literal) deck — what a human edit can do — a digit changed, a sign flipped, a sign dropped, a cut
# instead of a rounding, × 100, k for M, another field of the same row, the same field of another row, another
# dataset, a direction word flipped, a non-driver called a driver, an unknown invoice number, a web number; in the
# slot deck — what the Writer can do — a slot on another field, on another row, on another dataset, on another slide's
# evidence. Caught = the deck fails, the mutated bullet is named, with the expected rule. Classes whose data does not
# exist in a week (e.g. no negative change to drop a sign from) are reported as not applicable.
from decimal import ROUND_DOWN, Decimal  # noqa: E402

GOLDEN = (5, 10, 23, 49)


def _idx(d, slide, n=0):
    return [i for i, b in enumerate(d["bullets"]) if b["slide"] == slide][n]


def _sub_first_number(text, fn):
    mt = v2.NUM_RE.search(text)
    return text[:mt.start()] + fn(mt.group(0)) + text[mt.end():]


def _plant(base, i, text=None, ids=None):
    d = copy.deepcopy(base)
    if text is not None:
        d["bullets"][i]["text"] = text
    if ids is not None:
        d["bullets"][i]["evidence_ids"] = ids
    return d


def mutations(w, ev, lit, slt):
    """class → (draft, evidence, bullet index, expected rule) or None (not applicable this week)."""
    k = ev["kpi.weekly"]["rows"][0]
    cats = ev["kpi.category"]["rows"]
    drivers, _ = top3(ev)
    c1 = drivers[0]
    out = {}
    b0, b1, b2 = _idx(lit, 2, 0), _idx(lit, 2, 1), _idx(lit, 2, 2)
    out["digit changed"] = (_plant(lit, b0, _sub_first_number(lit["bullets"][b0]["text"], lambda t: re.sub(
        r"(\d)(?=\D*$)", lambda d: str((int(d.group(1)) + 1) % 10), t))), ev, b0, "V2")
    t1 = lit["bullets"][b1]["text"]
    flip = t1.replace("−", "\0").replace("+", "−").replace("\0", "+", 1) if "−" in t1 else t1.replace("+", "−", 1)
    out["sign flipped"] = (_plant(lit, b1, flip), ev, b1, "V2")
    # the S6 error: a negative change written without its sign and without a direction word
    neg = [c for c in cats if (c["billed_wow_pct"] or 0) < 0]
    i5 = _idx(lit, 5, 0)
    out["sign dropped"] = ((_plant(lit, i5, f"{neg[0]['vessel_category']} billed changed "
                                            f"{abs(neg[0]['billed_wow_pct']):.2f} % WoW"), ev, i5, "V2")
                           if neg else None)
    rounded = slots.format_value("billed_sdr", k["billed_sdr"], "M").split(" ")[0]
    words = {"billed_sdr": "Billed", "collected_sdr": "Collected", "ar_sdr": "AR", "overdue_sdr": "Overdue"}
    cuts = [(words[f], f"{(Decimal(str(k[f])) / scale).quantize(q, rounding=ROUND_DOWN):,}",
             slots.format_value(f, k[f], fmt).split(" ")[0], fmt)
            for fmt, scale, q in (("M", 10 ** 6, Decimal("0.01")), ("k", 10 ** 3, Decimal("0.1"))) for f in words]
    cut = next(((wd, c, fmt) for wd, c, r, fmt in cuts if c != r), None)
    i3b = _idx(lit, 3, 1)
    out["cut, not rounded"] = ((_plant(lit, i3b, f"{cut[0]} {cut[1]} {cut[2]} SDR"), ev, i3b, "V2")
                               if cut else None)
    i7 = _idx(lit, 7, 0)
    out["× 100"] = (_plant(lit, i7, _sub_first_number(lit["bullets"][i7]["text"],
                                                      lambda t: f"{Decimal(t.rstrip(' %')) * 100} %")), ev, i7, "V2")
    out["k for M"] = (_plant(lit, b0, lit["bullets"][b0]["text"].replace(" M SDR", " k SDR", 1)), ev, b0, "V2")
    coll = slots.format_value("collected_sdr", k["collected_sdr"], "M").split(" ")[0]
    out["another field, same row"] = ((_plant(lit, b0, lit["bullets"][b0]["text"].replace(rounded, coll, 1)),
                                       ev, b0, "V7") if coll != rounded else None)
    other = next((c for c in cats if c["vessel_category"] != c1 and slots.format_value(
        "billed_sdr", c["billed_sdr"], "M") != slots.format_value("billed_sdr", next(
            r for r in cats if r["vessel_category"] == c1)["billed_sdr"], "M")), None)
    out["same field, another row"] = (
        _plant(lit, i5, f"{c1} billed {slots.format_value('billed_sdr', other['billed_sdr'], 'M')}"), ev, i5, "V2")
    out["another dataset"] = (_plant(lit, i7, ids=["kpi.customers"]), ev, i7, "V2")
    # the first bullet with a written direction ("…, down 15.8 % WoW") gets the opposite word
    i3 = next((i for i, b in enumerate(lit["bullets"]) if re.search(r", (?:down|up) \d", b["text"])), None)
    if i3 is not None:
        t3 = lit["bullets"][i3]["text"]
        t3 = re.sub(r", (down|up) (?=\d)", lambda d: ", up " if d.group(1) == "down" else ", down ", t3, count=1)
        out["direction flipped"] = (_plant(lit, i3, t3), ev, i3, "V6")
    else:
        out["direction flipped"] = None
    t2 = lit["bullets"][b2]["text"]
    outsider = next(c["vessel_category"] for c in cats if c["vessel_category"] not in drivers)
    out["non-driver called a driver"] = (_plant(lit, b2, t2.replace(drivers[2], outsider, 1)), ev, b2, "V7")
    i8 = _idx(lit, 8, 0) if ev["audit.week"]["rows"] else _idx(lit, 6, 1)
    t8 = lit["bullets"][i8]["text"]
    inv = v2.INVOICE_RE.search(t8)
    out["unknown invoice"] = (_plant(lit, i8, t8.replace(inv.group(0), "INV-0009999")), ev, i8, "V7") if inv else None
    ev_web = {**ev, "insight.web": {"tool": "web_search", "status": "ok", "rows": [{"title": "Canal revenue 7.5 M"}],
                                    "source": {"kind": "api", "name": "tavily", "filter": "q"}, "note": None}}
    i9 = _idx(lit, 9, 0)
    out["web number"] = (_plant(lit, i9, "Canal revenue 7.5 M SDR this week", ["insight.web"]), ev_web, i9, "V2")
    # the slot deck
    s3 = _idx(slt, 3, 0)
    out["slot: another field"] = (_plant(slt, s3, slt["bullets"][s3]["text"].replace(
        "kpi.weekly:collected_sdr", "kpi.weekly:billed_sdr")), ev, s3, "V7")
    s5 = _idx(slt, 5, 0)
    out["slot: another row"] = (_plant(slt, s5, slt["bullets"][s5]["text"].replace(
        f"[{c1}]:billed_sdr", f"[{drivers[1]}]:billed_sdr", 1)), ev, s5, "V7")
    s7 = _idx(slt, 7, 0)
    out["slot: another dataset"] = (_plant(slt, s7, slt["bullets"][s7]["text"].replace(
        "kpi.weekly:top10", "kpi.customers:top10")), ev, s7, "V2")
    s8 = _idx(slt, 8, 0)
    out["slot: another slide's evidence"] = (_plant(slt, s8, f"{c1} billed {{kpi.category[{c1}]:billed_sdr|M}}"),
                                             ev, s8, "V5")
    return out


planted, applicable = {}, {}
for w in GOLDEN:
    for cls, case in mutations(w, EVS[w], RENDERED[w], DRAFTS[w]).items():
        applicable.setdefault(cls, []).append(w if case else None)
        if case is None:
            continue
        d, ev, i, rule = case
        ver = v2.validate(d, ev, w)
        on_bullet = {p.rule for p in ver.problems if p.bullet == i}
        planted[(w, cls)] = (not ver.passed, rule in on_bullet, sorted(on_bullet))

# the PPTX file (P6-7): one change at a time in the saved deck, as someone editing the file would make it
import io  # noqa: E402

from pptx import Presentation  # noqa: E402
from pptx.chart.data import CategoryChartData  # noqa: E402
from pptx.util import Inches  # noqa: E402


def _bump(t):
    return re.sub(r"(\d)(?=\D*$)", lambda d: str((int(d.group(1)) + 1) % 10), t, count=1)


def _edit_file(data, slide, name, fn):
    prs = Presentation(io.BytesIO(data))
    sh = next(s for s in prs.slides[slide - 1].shapes if s.name == name)
    fn(prs.slides[slide - 1], sh)
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def _set_run(sh, text):
    sh.text_frame.paragraphs[0].runs[0].text = text


def _cell_bump(sl, sh):
    c = sh.table.cell(1, 3)
    c.text_frame.paragraphs[0].runs[0].text = _bump(c.text)


def _chart_bump(sl, sh):
    plot = sh.chart.plots[0]
    data = CategoryChartData(number_format="General")
    data.categories = [str(c) for c in plot.categories]
    for n, s in enumerate(plot.series):
        vals = list(s.values)
        if n == 0:
            vals[-1] = vals[-1] + 1000.0
        data.add_series(s.name, vals)
    sh.chart.replace_data(data)


def _add_box(sl, sh):
    tb = sl.shapes.add_textbox(Inches(1), Inches(6), Inches(3), Inches(0.4))
    tb.text_frame.text = "Billed 9.99 M SDR"


BILLED_TILE = "bind:{kpi.weekly:billed_sdr|M}"
FILE_MUTATIONS = {   # class → (slide, shape, edit)
    "file: table cell": (7, "tbl:customers", _cell_bump),
    "file: chart point": (4, "chart:trend", _chart_bump),
    "file: template text": (3, "tpl:footer", lambda sl, sh: _set_run(sh, sh.text_frame.text.replace("SDR", "USD"))),
    "file: label approved in a draft": (3, "tpl:label", lambda sl, sh: _set_run(sh, "Approved")),
    "file: tile value": (3, BILLED_TILE, lambda sl, sh: _set_run(sh, _bump(sh.text_frame.text))),
    "file: Writer text": (2, None, lambda sl, sh: _set_run(sh, _bump(sh.text_frame.text))),
    "file: text box added": (6, "tpl:footer", _add_box),
    "file: shape deleted": (3, BILLED_TILE, lambda sl, sh: sh._element.getparent().remove(sh._element)),
}
for w in GOLDEN:
    b0 = f"txt:b{_idx(DRAFTS[w], 2, 0)}"
    for cls, (slide, name, fn) in FILE_MUTATIONS.items():
        applicable.setdefault(cls, []).append(w)
        bad_file = _edit_file(PPTX[w], slide, name or b0, fn)
        probs = readback.validate_pptx(bad_file, DRAFTS[w], EVS[w], READY[w], LABEL)
        on = sorted({p.rule for p in probs if p.slide == slide})
        planted[(w, cls)] = (bool(probs), "V8" in on and (name is not None or any(p.token == b0 for p in probs)),
                             on)

missed = {k: v for k, v in planted.items() if not (v[0] and v[1])}
not_applicable = {c: [w for w, a in zip(GOLDEN, ws) if a is None] for c, ws in applicable.items() if None in ws}
by_rule = {}
for (w, cls), (_, _, rules) in planted.items():
    by_rule[cls] = sorted(set(by_rule.get(cls, [])) | set(rules))
actual = {"classes": len(applicable), "planted": len(planted), "missed": missed, "not_applicable": not_applicable}
# reviewed snapshot (2026-10-19): 17 draft classes + 8 file classes × 4 golden weeks, every one caught where it was
# planted (the bullet, or the slide for the file) with its rule
expected = {"classes": 25, "planted": 100, "missed": {}, "not_applicable": {}}
assert actual == expected, actual
print(f"Phase 3: {len(planted)} planted ({len(applicable)} classes × {len(GOLDEN)} weeks), caught "
      f"{len(planted) - len(missed)}; rules on the mutated bullet: "
      + "; ".join(f"{c} {'/'.join(r)}" for c, r in by_rule.items()))
print(f"✅ Phase 3 validation passed: {len(planted)} / {len(planted)} planted wrong numbers caught with the expected "
      "rule where planted (literal and slot drafts V2 / V5 / V6 / V7; the saved PPTX V8: cell, chart point, template "
      "text, label, tile, Writer text, added box, deleted shape); 0 missed")
DONE.append(3)

# %% Phase 4 — The Phase 5 real failures replayed (S2)
# The bullets that failed weeks 5 and 23 in the S6 real run (Notebooks/_scratch/weekly_pack_real.json, frozen here)
# against the same evidence. Under the Phase 6 rules a direction word carries the sign of a change (P6-3): "down
# 30.78 %" for −30.78 is right English, so those bullets now bind; the share cited from kpi.customers stays wrong
# (G1: the value is kpi.weekly's) and the hint says where it lives.
S6_FAILED = {
    5: [("The top drivers were Liquefied Natural Gas (LNG) Carriers (up 1892095.01 SDR), Chemical Tankers & Other "
         "Liquid Bulk Tankers (up 771986.8 SDR), and Dry Bulk Vessels (down 399940.41 SDR).", ["kpi.category"]),
        ("Dry Bulk Vessels decreased by 399940.41 SDR to 899613.8 SDR, down 30.78 % week-on-week.", ["kpi.category"]),
        ("Dry Bulk Vessels billed 899613.8 SDR, down 30.78 % week-on-week.", ["kpi.category"]),
        ("Cruise Ships billed 543313.45 SDR, down 15.02 % week-on-week.", ["kpi.category"]),
        ("Roll-On/Roll-Off (Ro/Ro) Vessels billed 520634.94 SDR, down 36.15 % week-on-week.", ["kpi.category"]),
        ("Crude Oil Tankers billed 164581.53 SDR, and General Cargo / Multi-Purpose / Heavy Lift Vessels billed "
         "60504.52 SDR, down 80.99 % week-on-week.", ["kpi.category"])],
    23: [("Collected revenue was 5263662.35 SDR, down 15.8 % week-on-week, while AR invoices totaled 162 amounting "
          "to 47630979.69 SDR.", ["kpi.weekly"]),
         ("Collected revenue totaled 5263662.35 SDR, down 15.8 % WoW.", ["kpi.weekly"]),
         ("Cruise Ships billed 703818.24 SDR, down 1070881.98 SDR or 60.3 % WoW in week 23 of 2025.",
          ["kpi.category"]),
         ("Top ten customers generated 59.5 % of total billings over the 13-week period ending in week 23 of 2025.",
          ["kpi.customers"])],
}
replay = {}
for w, bullets in S6_FAILED.items():
    for n, (text, ids) in enumerate(bullets):
        replay[(w, n)] = [(r, t, msg) for r, t, msg in v2.check_text(text, EVS[w], ids, w)[1]]
actual = {k: [(r, t) for r, t, _ in v] for k, v in replay.items()}
# reviewed snapshot (2026-10-19): 8 of the 10 recorded bullets are right under P6-3 (the direction word carries the
# sign); week 5 bullet 1 never says what decreased (billing) → V7 ×3; week 23's share from kpi.customers → V2 with the
# hint naming kpi.weekly
expected = {(5, 0): [], (5, 1): [("V7", "399940.41"), ("V7", "899613.8"), ("V7", "30.78 %")], (5, 2): [],
            (5, 3): [], (5, 4): [], (5, 5): [], (23, 0): [], (23, 1): [], (23, 2): [],
            (23, 3): [("V2", "59.5 %")]}
assert actual == expected, actual
assert "kpi.weekly:top10_share_13w_pct" in replay[(23, 3)][0][2], replay[(23, 3)]
flagged = sum(bool(v) for v in actual.values())

# The first real run of the slot Writer (Phase 6 S6, 2026-10-19: weeks 5 / 10 / 23 ended validation_failed after two
# patches each). Each recorded failing bullet, then the text its problem message asks for, which must pass:
# a row named by its position ("[1]") and the unit written again after the slot; the week's audit total put on one
# invoice (the fix: that invoice's own field); "91 days days" after a days slot — and the S6 false alarm it sat next
# to, "a DSO window billed amount" refused because only the field's first family (DSO) counted.
P6_REAL = {
    5: [("Overdue invoice INV-0000211 for customer Cyravia Lines stood at {kpi.overdue[1]:amount_sdr|k} SDR with "
         "{kpi.overdue[1]:days_past_due} days past due.", ["kpi.overdue"]),
        ("Overdue invoice INV-0000211 for customer Cyravia Lines stood at {kpi.overdue[INV-0000211]:amount_sdr|k} "
         "with {kpi.overdue[INV-0000211]:days_past_due} past due.", ["kpi.overdue"])],
    10: [("Flagged invoice INV-0000626 carried a duplicate charge of {audit.week:amount_at_stake_sdr|M}.",
          ["audit.week"]),
         ("Flagged invoice INV-0000626 carried a duplicate charge of "
          "{audit.week[INV-0000626/duplicate_charge]:difference_sdr}.", ["audit.week"])],
    23: [("DSO window reached {kpi.weekly:dso_window_days} days with a DSO window billed amount of "
          "{kpi.weekly:dso_window_billed_sdr|M}.", ["kpi.weekly"]),
         ("DSO window reached {kpi.weekly:dso_window_days} with a DSO window billed amount of "
          "{kpi.weekly:dso_window_billed_sdr|M}.", ["kpi.weekly"])],
}
replay6 = {(w, n): v2.check_text(t, EVS[w], ids, w)[1] for w, cases in P6_REAL.items()
           for n, (t, ids) in enumerate(cases)}
actual6 = {k: [(r, t) for r, t, _ in v] for k, v in replay6.items()}
expected6 = {(5, 0): [("V2", "{kpi.overdue[1]:amount_sdr|k}"), ("V2", "{kpi.overdue[1]:days_past_due}")],
             (5, 1): [],
             (10, 0): [("V7", "{audit.week:amount_at_stake_sdr|M}")], (10, 1): [],
             (23, 0): [("V2", "{kpi.weekly:dso_window_days}")], (23, 1): []}
assert actual6 == expected6, actual6
hints = ["{kpi.overdue[INV-0000211]:amount_sdr|k}" in replay6[(5, 0)][0][2],
         "{audit.week[INV-0000626/duplicate_charge]:difference_sdr}" in replay6[(10, 0)][0][2],
         "drop the extra 'days'" in replay6[(23, 0)][0][2]]
assert all(hints), [v[0][2] for k, v in replay6.items() if v]
# run 2, week 10: a NileGate figure slotted on the context slide from an Insight result without that field; the
# message must say what the fix is (slide 9 is context only), not only where the field lives (kpi.weekly, which
# slide 9 may not cite). Planted in the clean week-10 deck; a finance_kpi result cited there is refused the same way.
d10 = copy.deepcopy(DRAFTS[10])
i9 = _idx(d10, 9, 0)
ev10 = {**EVS[10], "insight.call_1156556": {**EVS[10]["kpi.category"]}}            # an Insight drill-down result
d10["bullets"][i9] = {"slide": 9, "text": "Collected payments totaled {insight.call_1156556:collected_sdr|M} in "
                                          "week 10.", "evidence_ids": ["insight.call_1156556"]}
on9 = [(p.rule, p.message) for p in v2.validate(d10, ev10, 10).problems if p.bullet == i9]
context_rule = [r for r, msg in on9 if r == "V5" and "slide 9 is external context only" in msg]
assert context_rule == ["V5"] and v2.validate(DRAFTS[10], ev10, 10).passed, on9

# run 3 (the unit rule added to the prompt): three right sentences refused by the Validator itself — the after-window
# "budget" of the next slot outvoted "Billed" before the first; a row named after its number ("… on 2025-03-09") was
# matched to the row named earlier in the sentence. Both fixed; the right sentences pass, a swapped row still fails.
suez = {"tool": "suez_transits", "status": "ok", "source": {"kind": "api", "name": "portwatch", "filter": "f"},
        "note": None, "rows": [{"date": "2025-03-03", "n_total": 31}, {"date": "2025-03-09", "n_total": 28}]}
RUN3 = {
    "billed then budget (week 5)": (5, "Billed revenue for week 2025-W05 reached {kpi.trend[2025-W05]:billed_sdr|M} "
                                       "against a budget of {kpi.trend[2025-W05]:budget_sdr|M}.", ["kpi.trend"]),
    "billed then variance (week 49)": (49, "Billing in week 2025-W47 reached {kpi.trend[2025-W47]:billed_sdr|M} with "
                                           "budget variance of {kpi.trend[2025-W47]:budget_variance_pct|%2|dir}.",
                                       ["kpi.trend"]),
    "row named after (week 10)": (10, "PortWatch showed total transits of {insight.s[2025-03-03]:n_total} on "
                                      "2025-03-03 and {insight.s[2025-03-09]:n_total} on 2025-03-09.", ["insight.s"]),
    "row swapped (must fail)": (10, "PortWatch showed total transits of {insight.s[2025-03-09]:n_total} on 2025-03-03 "
                                    "and {insight.s[2025-03-03]:n_total} on 2025-03-09.", ["insight.s"]),
}
run3 = {k: sorted({r for r, _, _ in v2.check_text(t, {**EVS[w], "insight.s": suez}, ids, w)[1]})
        for k, (w, t, ids) in RUN3.items()}
assert run3 == {"billed then budget (week 5)": [], "billed then variance (week 49)": [], "row named after (week 10)": [],
                "row swapped (must fail)": ["V7"]}, run3

# run 4 (4 / 4 published) looked at as PNG: "up up 25.8 %" (a direction word before a |dir slot) and slide 1's title
# copied from the deck title, so the approved deck still said "Draft for approval" — both now caught.
RUN4 = {
    "up before |dir": "NileGate billed {kpi.weekly:billed_sdr|M} in week 23, up {kpi.weekly:billed_wow_pct|%1|dir} "
                      "week-on-week.",
    "rose before |dir": "Overdue receivables rose {kpi.weekly:overdue_wow_pct|%1|dir} to {kpi.weekly:overdue_sdr|M}.",
    "fixed": "NileGate billed {kpi.weekly:billed_sdr|M} in week 23, {kpi.weekly:billed_wow_pct|%1|dir} week-on-week.",
}
run4 = {k: sorted({r for r, _, _ in v2.check_text(t, EVS[23], ["kpi.weekly"], 23)[1]}) for k, t in RUN4.items()}
d23 = copy.deepcopy(DRAFTS[23])
d23["slide_titles"][0]["title"] = d23["title"]
run4["slide 1 title = deck title"] = sorted({p.rule for p in v2.validate(d23, EVS[23], 23).problems})
assert run4 == {"up before |dir": ["V2"], "rose before |dir": ["V2"], "fixed": [],
                "slide 1 title = deck title": ["V3"]}, run4
# Phase 7 baseline (Stage1_eval, 2026-10-19, D-P7-9): three right trend sentences refused by the Validator itself —
# "week 48" read as a typed number (only the run's own week was allowed), and "week 48" not seen as naming the row
# 2025-W48. Fixed: an integer 1–52 written right after "week" is a week label; "week N" names the trend row 2025-WNN.
# The right sentences pass; a swapped week and a bare number (not a week) still fail.
RUN7 = {
    "trend week literal (test 49)": (49, "Billed revenue moved from {kpi.trend[2025-W48]:billed_sdr|M} in week 48 to "
                                         "{kpi.trend[2025-W49]:billed_sdr|M} in week 49."),
    "week named as 'week N' (live 48)": (48, "Billed revenue in week 48 recovered to {kpi.trend[2025-W48]:billed_sdr|M} "
                                             "compared to {kpi.trend[2025-W47]:billed_sdr|M} in week 2025-W47."),
    "week N of 2025 (live 24)": (24, "Billed {kpi.trend[2025-W24]:billed_sdr|M} in week 24 of 2025 compared with "
                                     "{kpi.trend[2025-W23]:billed_sdr|M} in week 23 of 2025 ."),
    "weeks swapped (must fail)": (49, "Billed revenue moved from {kpi.trend[2025-W49]:billed_sdr|M} in week 48 to "
                                      "{kpi.trend[2025-W48]:billed_sdr|M} in week 49."),
    "a bare number (must fail)": (49, "Billed {kpi.trend[2025-W49]:billed_sdr|M} on 48 invoices."),
}
run7 = {k: sorted({r for r, _, _ in v2.check_text(t, EVS[w], ["kpi.trend"], w)[1]}) for k, (w, t) in RUN7.items()}
assert run7 == {"trend week literal (test 49)": [], "week named as 'week N' (live 48)": [],
                "week N of 2025 (live 24)": [], "weeks swapped (must fail)": ["V7"],
                "a bare number (must fail)": ["V2"]}, run7
# candidate c1 (2026-10-20, D-P7-12): context dates written as words ("on November 24") read as typed numbers on
# slide 9. A day written with an exact month name is a date; a typed transit count still fails; "market 12" is no date.
RUN7B = {
    "month-name date": "Suez daily transits recorded {insight.s[2025-03-09]:n_total} transits on March 9.",
    "day before month": "Transits reached {insight.s[2025-03-03]:n_total} on 3 March.",
    "typed count (must fail)": "Suez daily transits recorded 99 transits on March 9.",
    "not a month (must fail)": "Transits reached {insight.s[2025-03-03]:n_total}, a market 12 above the norm.",
}
run7b = {k: sorted({r for r, _, _ in v2.check_text(t, {**EVS[10], "insight.s": suez}, ["insight.s"], 10)[1]})
         for k, t in RUN7B.items()}
assert run7b == {"month-name date": [], "day before month": [], "typed count (must fail)": ["V2"],
                 "not a month (must fail)": ["V2"]}, run7b
# candidate c2 (2026-10-21, D-P7-13): two right sentences refused in test weeks 10 / 23 — a period's dates read as the
# row a slot must be ("ranged between {03-03} and {03-04} … during the week of 2025-03-03 to 2025-03-09"), and an
# audited invoice's billed amount called its "amount". A period names no row; "amount" / "charge" names billed_sdr on
# an invoice_audit row only. A row swapped outside the period and "amount" for a week's billed total still fail.
aud10 = EVS[10]["audit.week"]
inv10 = aud10["rows"][0]
key10 = f"{inv10['invoice_number']}/{inv10['check_code']}"
RUN7C = {
    "date range": ("Transits ranged between {insight.s[2025-03-03]:n_total} and {insight.s[2025-03-09]:n_total} "
                   "calls per day during the week of 2025-03-03 to 2025-03-09.", ["insight.s"]),
    "invoice amount": (f"Invoice {inv10['invoice_number']} was flagged with an amount of "
                       f"{{audit.week[{key10}]:billed_sdr|k}}.", ["audit.week"]),
    "row swapped outside a period (must fail)": ("Transits were {insight.s[2025-03-09]:n_total} on 2025-03-03.",
                                                 ["insight.s"]),
    "amount outside the audit (must fail)": ("The week's amount was {kpi.weekly:billed_sdr|M}.", ["kpi.weekly"]),
}
run7c = {k: sorted({r for r, _, _ in v2.check_text(t, {**EVS[10], "insight.s": suez}, ids, 10)[1]})
         for k, (t, ids) in RUN7C.items()}
assert run7c == {"date range": [], "invoice amount": [], "row swapped outside a period (must fail)": ["V7"],
                 "amount outside the audit (must fail)": ["V7"]}, run7c
# D-P7-14: the slot-form errors that stopped real packs in c1 / c2 (a format the field does not allow, a unit or a
# direction word written twice, a key on a one-row result) are fixed by code before the Validator
# (`slots.normalize_text`); the numbers are untouched. Errors of meaning (an unknown field, another row) are left as
# they are and still fail.
NORM = {
    "|k on days (c2 test 23)": (23, "DSO registered at {kpi.weekly:dso_days|k}, {kpi.weekly:dso_wow_days|k|dir} WoW.",
                                ["kpi.weekly"]),
    "|k on a count (c2 test 10)": (10, "Suez daily transits were {insight.s[2025-03-09]:n_total|k} on 2025-03-09.",
                                   ["insight.s"]),
    "unit twice (c1 test 23)": (10, f"Invoice {inv10['invoice_number']} had a difference of "
                                    f"{{audit.week[{key10}]:difference_sdr|M}} SDR.", ["audit.week"]),
    "direction twice": (23, "NileGate billed {kpi.weekly:billed_sdr|M}, up {kpi.weekly:billed_wow_pct|%1|dir} WoW.",
                        ["kpi.weekly"]),
    "key on one row": (23, "DSO was {kpi.weekly[2025-W23]:dso_days} in week 23.", ["kpi.weekly"]),
    "unknown field (must fail)": (10, "Transits averaged {insight.s[2025-03-03]:transits}.", ["insight.s"]),
    "another row (must fail)": (10, "Transits were {insight.s[2025-03-09]:n_total|k} on 2025-03-03.", ["insight.s"]),
}
norm_fixes, norm_rules = {}, {}
for k, (w, t, ids) in NORM.items():
    ev = {**EVS[w], "insight.s": suez}
    fixed_text, fixes = slots.normalize_text(t, ev)
    norm_fixes[k] = len(fixes)
    norm_rules[k] = sorted({r for r, _, _ in v2.check_text(fixed_text, ev, ids, w)[1]})
assert norm_rules == {"|k on days (c2 test 23)": [], "|k on a count (c2 test 10)": [], "unit twice (c1 test 23)": [],
                      "direction twice": [], "key on one row": [], "unknown field (must fail)": ["V2"],
                      "another row (must fail)": ["V7"]}, norm_rules
assert norm_fixes == {"|k on days (c2 test 23)": 2, "|k on a count (c2 test 10)": 1, "unit twice (c1 test 23)": 1,
                      "direction twice": 1, "key on one row": 1, "unknown field (must fail)": 0,
                      "another row (must fail)": 1}, norm_fixes
# the 52 clean slot drafts need no fix (normalize is a no-op on a right draft)
assert all(not slots.normalize_text(b["text"], EVS[w])[1] for w in range(1, 53) for b in DRAFTS[w]["bullets"])
print(f"Phase 4: {len(actual)} recorded Phase 5 bullets: {len(actual) - flagged} now bind, {flagged} still wrong "
      f"(no subject; share from the wrong dataset → hint kpi.weekly); 3 recorded Phase 6 failures caught with the "
      f"exact fix in the message, and the 3 fixed texts pass")
print("✅ Phase 4 validation passed: the real failures replayed — Phase 5: signs carried by direction words now bind "
      "(P6-3), the wrong-dataset share is still caught, a sentence without its subject is named (V7); Phase 6: a "
      "row by position, a total on one invoice, a unit written twice — each refused with the slot that fixes it")
DONE.append(4)

# %% Final Checkpoint
# Narrative: pipelines/checkpoints/agents/Deck_check.md (written when Phase 6 closes).
# (§5c listed a Phase 5 "real models" here: it is Weekly_pack_check.py Phase 5 — the real pack, its V1–V8 and the
# published deck.pptx — so it is not run twice)
PHASES = {1: "slots", 2: "52 clean decks (V1–V8)", 3: "planted wrong numbers", 4: "real failures replayed"}
pending = [f"{k} {v}" for k, v in PHASES.items() if k not in DONE]
assert DONE == sorted(DONE) and set(DONE) <= set(PHASES)
print(f"Final Checkpoint: done {DONE}; pending: {pending}")
print(f"✅ Final Checkpoint: {len(DONE)} / {len(PHASES)} phases passed")
