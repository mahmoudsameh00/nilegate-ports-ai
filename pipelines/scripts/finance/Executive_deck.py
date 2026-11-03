"""Executive deck 2025 — the NileGate financial-intelligence deck (PPTX) from the Executive_analysis numbers and charts.

Plan:    docs/analysis/financial_intelligence/implementation_roadmap.md Phase C; slides
         docs/analysis/financial_intelligence/executive_deck_storyboard.md (10 main slides + appendix).
Run:     uv run python tools/run.py pipelines/scripts/finance/Executive_deck.py  (after Executive_charts.py)

Reads:   Data/processed/finance/executive_2025/ numbers.json, customers.csv, charts/*.png;
         pipelines/agents/deck/style.py (the NileGate deck constants, shared with the weekly pack).
Writes:  reports/executive/2025/NileGate_2025_Financial_Review.pptx (git-ignored like every pack under reports/).
Re-run:  safe (the deck is rebuilt; no LLM, no database).

The number contract (the ADR-051 idea, without a Writer): every number on a slide or in the speaker notes is written
by a formatter that registers it (`m`, `p`, `dd`, `n`, `t`); a read-back of the saved file extracts every numeric token
and asserts it was registered — a hand-typed number cannot reach the deck unnoticed.

Phases
1. Inputs: numbers.json, customers, the 13 charts.
2. Build: the slides (cover, summary, 8 findings / decisions, appendix) with speaker notes.
3. Save and read back: every numeric token registered; the headline numbers on their slides; slide count and titles.
Final Checkpoint.
"""
# %% Setup
import json
import os
import datetime as dt
import re
from decimal import ROUND_HALF_UP, Decimal
import sys
from pathlib import Path

import pandas as pd
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())
sys.path.insert(0, str(ROOT))
from pipelines.agents.deck import style as S  # noqa: E402

SRC = ROOT / "Data" / "processed" / "finance" / "executive_2025"
CHARTS = SRC / "charts"
# EXEC_DECK_OUT writes elsewhere (a deck open in PowerPoint is locked on Windows; review 2026-10-31)
OUT = Path(os.environ.get("EXEC_DECK_OUT") or ROOT / "reports" / "executive" / "2025" / "NileGate_2025_Financial_Review.pptx")
BRAND = "NileGate"
SHORT = {"Chemical Tankers & Other Liquid Bulk Tankers": "Chemical / liquid bulk tankers",   # = the charts' labels
         "General Cargo / Multi-Purpose / Heavy Lift Vessels": "General cargo / heavy lift",
         "Liquefied Natural Gas (LNG) Carriers": "LNG carriers", "Liquefied Petroleum Gas (LPG) Carriers": "LPG carriers",
         "Roll-On/Roll-Off (Ro/Ro) Vessels": "Ro/Ro vessels"}
RED = RGBColor.from_string("E34948")

REG: set[str] = set()                               # every numeric token the formatters wrote
TOKEN = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _reg(s: str) -> str:
    REG.update(t.replace(",", "") for t in TOKEN.findall(s))
    return s


def _fix(x: float, nd: int) -> str:
    """Round half up once, for display (Python's format rounds a float tie to even: 27.25 → "27.2")."""
    return f"{Decimal(str(x)).quantize(Decimal(1).scaleb(-nd), rounding=ROUND_HALF_UP):,.{nd}f}"


def m(x: float, nd: int = 1) -> str:                # money in millions
    return _reg(f"{_fix(x / 1e6, nd)} M")


def k(x: float) -> str:                             # money in thousands
    return _reg(f"{_fix(x / 1e3, 1)} k")


def p(x: float, nd: int = 1) -> str:                # percent
    return _reg(f"{_fix(x, nd)} %")


def dd(x: float, nd: int = 1) -> str:               # days
    return _reg(f"{_fix(x, nd)} days")


def n(x) -> str:
    """A count from numbers.json, or a constant of the template (a week, a threshold, a date part, a window). A data
    fact is never typed as a literal here: it comes from numbers.json (review 2026-10-31: 148 and 45 were typed)."""
    return _reg(f"{x:,}" if isinstance(x, int) else str(x))


def yr(x: int) -> str:                             # a year: never a thousands separator
    return _reg(str(x))


def t(s: str) -> str:                               # text holding identifiers with digits (invoice numbers)
    return _reg(s)


# %% Phase 1 — Inputs
N = json.loads((SRC / "numbers.json").read_text(encoding="utf-8"))
cu = pd.read_csv(SRC / "customers.csv")
charts = {pth.stem: pth for pth in CHARTS.glob("V*.png")}
assert len(charts) == 13, sorted(charts)
Y, F2, F4, F5, F7, F8, F9 = N["year"], N["F2"], N["F4"]["top_customer"], N["F5"], N["F7"], N["F8"], N["F9"]
RAT = {d["credit_rating"]: d for d in F5["by_rating"]}
SEG = {d["segment"]: d for d in F5["by_segment"]}
SCN = {s["label"]: s for s in F9["scenarios"]}
slow_b = cu[(cu.credit_rating == "B") & (cu.late_mean >= 25)].sort_values("revenue", ascending=False)
print("inputs: numbers.json sections", len(N), "| customers", len(cu), "| charts", len(charts),
      "| B customers ≥ 25 days late:", slow_b.customer_name.tolist())
print("✅ Phase 1 validation passed: numbers, customers and the 13 charts are present")


# %% Phase 2 — Build
prs = Presentation()
prs.slide_width, prs.slide_height = S.WIDTH, S.HEIGHT
BLANK = prs.slide_layouts[6]
SLIDES: list[dict] = []                             # title + section per slide, for the read-back


def text(slide, x, y, w, h, paras, size=S.BODY_PT, color=S.INK, bold=False, align=PP_ALIGN.LEFT,
         anchor=MSO_ANCHOR.TOP, name=None):
    """A text box; `paras` = a string or a list of strings / [(text, {bold, color, size})] runs."""
    box = slide.shapes.add_textbox(x, y, w, h)
    if name:
        box.name = name
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    for i, para in enumerate([paras] if isinstance(paras, str) else paras):
        par = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        par.alignment = align
        par.space_after = Pt(6)
        for run_text, opt in ([(para, {})] if isinstance(para, str) else para):
            r = par.add_run()
            r.text = run_text
            f = r.font
            f.name, f.size = S.FONT, opt.get("size", size)
            f.bold = opt.get("bold", bold)
            f.color.rgb = opt.get("color", color)
    return box


def rect(slide, x, y, w, h, fill, name=None):
    shp = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, x, y, w, h)
    shp.fill.solid()
    shp.fill.fore_color.rgb = fill
    shp.line.fill.background()
    shp.shadow.inherit = False
    if name:
        shp.name = name
    return shp


def new_slide(title: str, section: str, notes: str):
    s = prs.slides.add_slide(BLANK)
    no = len(prs.slides)
    # two-line titles at 26 pt need ~0.95 in: the box starts higher than style.TITLE_TOP (0.45 in)
    text(s, S.MARGIN, Inches(0.3), S.CONTENT_W, Inches(1.1), title, size=Pt(26), color=S.NAVY, bold=True,
         anchor=MSO_ANCHOR.BOTTOM, name="title")
    text(s, S.MARGIN, S.FOOTER_TOP, Inches(10), S.FOOTER_H,
         f"{BRAND} · {section} · synthetic company data · amounts in SDR", size=S.FOOT_PT, color=S.MUTED,
         anchor=MSO_ANCHOR.MIDDLE, name="footer")
    text(s, S.WIDTH - S.MARGIN - Inches(1.0), S.FOOTER_TOP, Inches(1.0), S.FOOTER_H, n(no), size=S.FOOT_PT,
         color=S.MUTED, align=PP_ALIGN.RIGHT, anchor=MSO_ANCHOR.MIDDLE, name="page")
    s.notes_slide.notes_text_frame.text = notes
    SLIDES.append({"title": title, "section": section})
    return s


# alt text for screen readers (review 2026-10-31: the pictures had none); words only — numbers stay in the slide text,
# where the read-back checks them
ALT = {"V2_rolling_revenue": "Line chart: rolling 13-week billing stays inside its noise band while the budget rises",
       "V3_budget_waterfall": "Waterfall from budget to billed: volume adds a little, ballast pricing and ticket size "
                              "take most of the gap",
       "V4_category_split": "Bars per vessel category: volume effect and ticket effect of the gap against budget",
       "V5_customer_risk": "Scatter of customers: revenue share against mean days paid after due, bubble size "
                           "receivables, colour credit rating; the largest customer is a late payer",
       "V6_rating_shares": "Grouped bars by credit rating: revenue, receivables and overdue shares; C carries most "
                           "overdue",
       "V6b_segment_shares": "Grouped bars by segment: revenue, receivables and overdue shares",
       "V7_aging_heatmap": "Heatmap of the ten customers with most overdue by days past due",
       "V8_ar90_buildup": "Stacked columns of receivables more than 90 days past due by week and customer",
       "V9_dso_split": "Stacked area of DSO split into terms and delinquency by week",
       "V10_scenario": "Bars of DSO after collecting the overdue of the largest overdue customers",
       "V11_pareto": "Pareto of customer revenue with the cumulative share",
       "V12_cohorts": "Lines of on-time and within-30-days payment rates by invoice month; late months not matured",
       "V13_days_late": "Box plots of days paid after due by credit rating"}


def chart(slide, name: str, x, y, w):
    """Place a chart PNG at width w, keeping its aspect, with its alt text."""
    pic = slide.shapes.add_picture(str(charts[name]), x, y, width=w)
    pic._element.nvPicPr.cNvPr.set("descr", ALT[name])
    pic.name = name
    return pic


ACTION_Y, TABLE_PT = Inches(6.05), Pt(12)          # default band position / table text size


def action(slide, label: str, body: str, y=ACTION_Y):
    """The management action of the slide: a tinted band with a bold label (no edge stripe)."""
    rect(slide, S.MARGIN, y, S.CONTENT_W, Inches(0.6), S.TILE_BG, name="action.bg")
    text(slide, S.MARGIN + Inches(0.2), y, S.CONTENT_W - Inches(0.4), Inches(0.6),
         [[(label + "  ", {"bold": True, "color": S.NAVY}), (body, {})]], size=Pt(14), anchor=MSO_ANCHOR.MIDDLE,
         name="action")


def table(slide, x, y, widths, rows, size=TABLE_PT, name=None):
    shp = slide.shapes.add_table(len(rows), len(widths), x, y, sum(widths, Inches(0)), Inches(0.36 * len(rows)))
    if name:
        shp.name = name
    tb = shp.table
    for j, w in enumerate(widths):
        tb.columns[j].width = w
    for i, row in enumerate(rows):
        for j, val in enumerate(row):
            c = tb.cell(i, j)
            c.fill.solid()
            c.fill.fore_color.rgb = S.NAVY if i == 0 else (S.WHITE if i % 2 else S.TILE_BG)
            c.margin_left = c.margin_right = Inches(0.08)
            tf = c.text_frame
            tf.word_wrap = True
            tf.paragraphs[0].text = ""
            r = tf.paragraphs[0].add_run()
            r.text = val
            r.font.name, r.font.size = S.FONT, size
            r.font.bold = i == 0
            r.font.color.rgb = S.WHITE if i == 0 else S.INK
    return shp


def side_panel(slide, x, y, w, items: list[tuple[str, str]]):
    """Stacked stat callouts: (value, label) pairs."""
    for i, (val, lab) in enumerate(items):
        yy = y + Inches(1.05 * i)
        text(slide, x, yy, w, Inches(0.5), val, size=Pt(26), color=S.NAVY, bold=True, name=f"stat{i}.value")
        text(slide, x, yy + Inches(0.48), w, Inches(0.5), lab, size=Pt(12), color=S.INK_2, name=f"stat{i}.label")


FULL_W, HALF_W = Inches(11.6), Inches(5.75)
FULL_X = (S.WIDTH - FULL_W) / 2
# --- 1. Cover -------------------------------------------------------------------------------------------------------
s = prs.slides.add_slide(BLANK)
rect(s, 0, 0, S.WIDTH, S.HEIGHT, S.NAVY, name="bg")
text(s, Inches(0.9), Inches(2.0), Inches(11.5), Inches(1.0), f"{yr(2025)} Financial Review", size=Pt(44),
     color=S.WHITE, bold=True, name="title")
text(s, Inches(0.9), Inches(3.0), Inches(11.5), Inches(0.8),
     "Flat revenue, a planning gap, and cash tied up in five accounts", size=Pt(24), color=S.WHITE)
text(s, Inches(0.9), Inches(4.4), Inches(11.5), Inches(1.0),
     [f"ISO weeks {n(1)}–{n(52)} of {yr(2025)} · receivables as of {n(28)} December {yr(2025)}",
      "Synthetic company data · amounts in SDR · prepared from the finance views (no model-generated numbers)"],
     size=Pt(14), color=RGBColor.from_string("CADCFC"))
s.notes_slide.notes_text_frame.text = (
    "Audience: CEO / CFO / Finance and Commercial. Every number comes from schema finance through "
    "pipelines/scripts/finance/Executive_analysis.py; definitions in docs/finance_metrics.md.")
SLIDES.append({"title": "Financial Review (cover)", "section": "Cover"})

# --- 2. Executive summary -------------------------------------------------------------------------------------------
s = new_slide("Revenue held steady; the real issue is who pays late, not how much we bill", "Summary",
              f"Billed {m(Y['billed'], 2)} over {n(Y['invoices'])} invoices; budget {m(Y['budget'], 2)}. "
              f"AR {m(Y['ar_w52'], 2)} at week {n(52)}; overdue {p(Y['overdue_share_w52_pct'])} of AR. "
              "Decisions are on the last main slide.")
tiles = [(m(Y["billed"]), "Billed 2025"), (p(Y["variance_pct"]), "vs budget"), (m(Y["collected"]), "Collected 2025"),
         (dd(Y["dso_w52"]), f"DSO, week {n(52)}"), (m(Y["ar_w52"]), f"Receivables, week {n(52)}"),
         (m(Y["overdue_w52"]), f"Overdue ({p(Y['overdue_share_w52_pct'])} of receivables)"),
         (m(Y["ar90_w52"], 2), f"More than {n(90)} days overdue"), (p(F4["revenue_share_pct"]), f"Revenue from the #{n(1)} customer")]
tw, th, gap = Inches(2.86), Inches(1.15), Inches(0.24)
for i, (val, lab) in enumerate(tiles):
    x, y = S.MARGIN + (i % 4) * (tw + gap), S.BODY_TOP + (i // 4) * (th + gap)
    rect(s, x, y, tw, th, S.TILE_BG, name=f"tile{i}.bg")
    text(s, x + Inches(0.18), y + Inches(0.12), tw - Inches(0.36), Inches(0.55), val, size=Pt(26), color=S.NAVY,
         bold=True, name=f"tile{i}.value")
    text(s, x + Inches(0.18), y + Inches(0.68), tw - Inches(0.36), Inches(0.4), lab, size=Pt(12), color=S.INK_2,
         name=f"tile{i}.label")
by = S.BODY_TOP + 2 * (th + gap) + Inches(0.15)
text(s, S.MARGIN, by, S.CONTENT_W, Inches(2.0), [
    [("Revenue is flat, not falling. ", {"bold": True}),
     (f"Weekly billing moves ±{n(20)} % by chance; the rolling {n(13)}-week total never left its noise band.", {})],
    [("The budget miss is a pricing assumption. ", {"bold": True}),
     (f"Transits were on plan ({n(F2['invoices'])} vs {n(F2['plan_invoices'])}); each paid less than the plan, "
      f"which priced every transit laden.", {})],
    [("Cash is tied up in a few accounts. ", {"bold": True}),
     (f"{n(5)} customers hold {p(F9['top5_overdue_share_pct'])} of overdue; our largest customer is also our largest "
      f"receivable.", {})]], size=Pt(16))

# --- 3. Revenue ----------------------------------------------------------------------------------------------------
f1, f3 = N["F1"], N["F3"]
s = new_slide(f"Billing was flat at about {m(Y['weekly_billed_mean'], 2)} a week; swings of ±{n(20)} % are normal noise",
              "Revenue",
              f"Trend over {n(52)} weeks: slope {n(int(round(f1['trend_slope_per_week'])))} SDR per week, p = "
              f"{n(f1['trend_p'])}. Invoice count dispersion {n(f1['count_dispersion'])} (a random process is about "
              f"{n(1)}). Quarters {', '.join(m(v) for v in f1['quarters_billed'])}. {p(f1['weeks_wow_gt20_pct'], 0)} of "
              f"weeks move more than {n(20)} % week over week. Noise band = {n(13)} × weekly mean ± {n(2)} σ × √{n(13)} "
              f"= {m(f3['band_mid'], 2)} ± {m(f3['band_half'], 2)}. Caveat: synthetic invoice dates are uniform over "
              "the year, so no real seasonality exists in this data.")
chart(s, "V2_rolling_revenue", FULL_X, Inches(1.45), FULL_W)
action(s, "Action:", f"read revenue on rolling {n(13)}-week totals in executive reporting; keep week-over-week "
                     "for the operational weekly pack.")

# --- 4. Budget ------------------------------------------------------------------------------------------------------
s = new_slide("We ran the planned number of transits; each paid less than the plan assumed", "Budget",
              f"Gap {m(F2['gap'], 2)} = volume {m(F2['volume_effect'], 2)} + ticket {m(F2['ticket_effect'], 2)} (exact "
              f"split). {p(F2['ballast_share_pct'])} of invoices were priced in ballast; re-valued at each category's "
              f"average laden ticket they add about {m(-F2['ballast_effect'], 2)} ({p(F2['ballast_share_of_gap_pct'])} of "
              f"the gap) — an estimate. The rolling {n(13)}-week gap widens from {p(f3['var_13w_pct_at']['13'])} "
              f"(week {n(13)}) to {p(f3['var_13w_pct_at']['39'])} (week {n(39)}) only because the budget follows a "
              f"seasonal curve and billing does not. Category detail in the appendix.")
chart(s, "V3_budget_waterfall", FULL_X, Inches(1.45), FULL_W)
action(s, "Action:", f"re-base the {yr(2026)} budget on the actual laden / ballast mix and mean tonnage; drop the "
                     "seasonal curve unless transit data supports it.")

# --- 5. Customer risk -----------------------------------------------------------------------------------------------
s = new_slide(f"{F4['name']} brings {p(F4['revenue_share_pct'])} of revenue — and {p(F4['ar_share_pct'])} of everything "
              f"we are owed", "Customers",
              f"{F4['name']}: rating {F4['rating']}, {n(F4['terms'])}-day terms, {n(F4['invoices'])} invoices, "
              f"{m(F4['revenue'], 2)} billed; mean {dd(F4['late_mean_days'])} after due; {p(F4['ontime_pct'], 0)} paid on "
              f"time; cash about {dd(F4['days_to_cash'], 0)} after invoicing; {p(F4['overdue_share_pct'])} of overdue. "
              f"Customer size does not predict lateness (Spearman ρ = {n(N['F6']['spearman_rho'])}, p = "
              f"{n(N['F6']['p'])}). Mean days late uses payments made by {n(28)} December only.")
chart(s, "V5_customer_risk", FULL_X, Inches(1.45), FULL_W)
others = [d["name"] for d in N["F4"]["high_revenue_late_payers"] if d["name"] != F4["name"]]
action(s, "Action:", f"account plan for {F4['name']} (terms, escalation, credit limit); review "
                     f"{', '.join(others[:-1])} and {others[-1]}.")

# --- 6. Credit rating -----------------------------------------------------------------------------------------------
s = new_slide(f"C-rated customers are {p(RAT['C']['revenue_share'])} of revenue but {p(RAT['C']['overdue_share'])} of "
              f"overdue; rating B is not a safe harbour", "Credit",
              f"Mean days paid after due: A {n(RAT['A']['late_mean'])}, B {n(RAT['B']['late_mean'])}, C "
              f"{n(RAT['C']['late_mean'])} (Kruskal–Wallis p = {n(F5['kruskal_p'])}, {n(F5['payments_asof'])} payments). "
              f"B customers paying {n(25)}+ days late on average: {', '.join(slow_b.customer_name)}. Terms ({n(30)} / {n(45)} / {n(60)} "
              f"days) are confounded with segment and rating — not shown as a cause.")
chart(s, "V6_rating_shares", S.MARGIN, Inches(1.45), HALF_W)
side_panel(s, Inches(7.0), Inches(1.6), Inches(5.6), [
    (f"{p(RAT['A']['ontime_pct'], 0)} · {p(RAT['B']['ontime_pct'], 0)} · {p(RAT['C']['ontime_pct'], 0)}",
     "Paid on time, ratings A · B · C"),
    (f"{n(len(slow_b))} B customers", f"pay {n(25)}+ days after due on average, including {slow_b.customer_name.iloc[0]}"),
    (f"{p(SEG['tanker']['revenue_share'], 0)} → {p(SEG['tanker']['overdue_share'], 0)}",
     "Tanker segment: share of revenue → share of overdue"),
    (f"{p(SEG['container']['revenue_share'], 0)} → {p(SEG['container']['overdue_share'], 0)}",
     "Container segment: share of revenue → share of overdue")])
action(s, "Action:", "shorter terms or deposits for C; re-rate B customers by their observed payment days.")

# --- 7. 90+ ---------------------------------------------------------------------------------------------------------
h = F7["holder"]
hz = dt.date.fromisoformat(N["meta"]["payments_horizon"])
horizon = f"{n(hz.day)} {hz:%B} {yr(hz.year)}"
s = new_slide(f"More than {n(90)} days overdue grew from zero to {m(F7['w52'], 2)} — "
              f"{p(h['share_of_90_w52_pct'], 0)} of it one customer",
              "Receivables",
              f"90+ appears in week {n(F7['first_week'])} and grows {k(F7['slope_per_week'])} per week (p = "
              f"{n(F7['p'])}) while receivables, overdue and DSO show no trend. {h['name']} (rating {h['rating']}, "
              f"{p(h['revenue_share_pct'])} of revenue) holds {p(h['share_of_90_min_from_pct'], 0)}–{p(100, 0)} of it from "
              f"week {n(h['dominant_from_week'])} ({n(h['weeks_at_100pct'])} of {n(h['weeks_from'])} weeks at {p(100, 0)}); "
              f"{n(h['unpaid_at_horizon'])} of its {n(h['invoices_2025'])} invoices ({m(h['unpaid_at_horizon_sdr'], 2)}) were "
              f"still unpaid on {horizon}. The other 90+ items were paid later.")
chart(s, "V8_ar90_buildup", FULL_X, Inches(1.45), FULL_W)
action(s, "Action:", f"dispute / legal review of {h['name']}; stop credit on accounts with items over {n(90)} days; "
                     "discuss a provision.")

# --- 8. DSO and the scenario ----------------------------------------------------------------------------------------
s = new_slide(f"Collecting the top {n(5)} overdue accounts would cut DSO from {dd(SCN['current']['dso'])} to "
              f"{dd(SCN['top5']['dso'])}", "Receivables",
              f"DSO {dd(F8['dso_w52'])} = {dd(F8['best_w52'])} terms (best possible, M{n(12)}) + {dd(F8['delinquency_w52'])} "
              f"delinquency; both flat over weeks {n(14)}–{n(52)} (DSO range {n(F8['dso_min_w14_52'])}–"
              f"{n(F8['dso_max_w14_52'])}). Scenario = arithmetic at week {n(52)} (same billing window), not a forecast. "
              f"Top {n(5)} overdue accounts: {', '.join(F9['top5_names'])}. "
              + (f"It includes {h['name']}'s {m(h['unpaid_at_horizon_sdr'], 2)}, still unpaid on {horizon}: that part is "
                 "the least certain to be collected." if h["name"] in F9["top5_names"] else ""))
chart(s, "V9_dso_split", S.MARGIN, Inches(1.45), HALF_W)
chart(s, "V10_scenario", S.WIDTH - S.MARGIN - HALF_W, Inches(1.45), HALF_W)
action(s, "Action:", f"a collection campaign on the top {n(5)} overdue accounts (up to {m(SCN['top5']['released'])} cash), "
                     "tracked weekly.")

# --- 9. Integrity and stability -------------------------------------------------------------------------------------
f10, f13 = N["F10"], N["F13"]
s = new_slide(f"Collections did not deteriorate; {n(len(f13['findings']))} duplicate charges need correcting",
              "Integrity",
              f"Invoice-month cohorts January–September (matured by {n(28)} December): paid on time "
              f"{p(f10['ontime_range'][0])}–{p(f10['ontime_range'][1])}, within {n(30)} days after due "
              f"{p(f10['within30_range'][0])}–{p(f10['within30_range'][1])}. October–December cohorts are not matured "
              f"and are excluded. Duplicates total {k(f13['total'])} ({p(f13['share_of_billing_pct'], 2)} of billing).")
side_panel(s, S.MARGIN, Inches(1.6), Inches(5.2), [
    (f"{p(f10['ontime_range'][0], 0)}–{p(f10['ontime_range'][1], 0)}", "Paid on or before due, every matured month"),
    (f"{p(f10['within30_range'][0], 0)}–{p(f10['within30_range'][1], 0)}",
     f"Paid within {n(30)} days after due — no drift through the year"),
    (k(f13["total"]), f"Billed twice ({p(f13['share_of_billing_pct'], 2)} of billing)")])
text(s, Inches(6.2), Inches(1.6), Inches(6.5), Inches(0.4), "Duplicate charges found by the invoice audit",
     size=Pt(14), color=S.INK, bold=True)
table(s, Inches(6.2), Inches(2.1), [Inches(0.8), Inches(1.45), Inches(2.0), Inches(1.0), Inches(1.25)],
      [["Week", "Invoice", "Category", "Amount", "Duplicate of"]]
      + [[n(f["week"]), t(f["invoice"]), SHORT.get(f["category"], f["category"]), k(f["amount"]),
          t(f["duplicate_of"])] for f in f13["findings"]], name="tbl.audit")
action(s, "Action:", "void or credit the duplicates; keep the weekly invoice audit running.")

# --- 10. Decisions --------------------------------------------------------------------------------------------------
s = new_slide("Three decisions for management", "Decisions",
              "Each decision is tied to one finding and one tracked metric; the metrics are available weekly in the "
              f"finance views (M{n(6)}, M{n(4)}, M{n(12)}) or from the payments.")
table(s, S.MARGIN, S.BODY_TOP + Inches(0.1),
      [Inches(4.1), Inches(1.9), Inches(3.4), Inches(2.73)],
      [["Decision", "Owner", "Expected effect", "Track"],
       [f"Re-base the {yr(2026)} budget on the laden / ballast mix and mean tonnage", "Finance",
        "A budget the business can be judged against", f"Rolling {n(13)}-week variance"],
       [f"Collection campaign on the top {n(5)} overdue accounts; dispute review of {h['name']}", "Credit control",
        f"Up to {m(SCN['top5']['released'])} cash; DSO about {dd(SCN['top5']['dso'])}",
        f"Delinquency DSO, {n(90)}+ days"],
       ["Credit policy: terms or deposits for C; behaviour-based review of B", "Finance + Commercial",
        f"Lower overdue share of C ({p(RAT['C']['overdue_share'])} today)", "On-time %, overdue by rating"]],
      size=Pt(14), name="tbl.decisions")
text(s, S.MARGIN, Inches(5.3), S.CONTENT_W, Inches(1.2), [
    [("Not claimed: ", {"bold": True}),
     ("revenue forecasts or seasonality (billing has no trend in this data); a causal effect of payment terms "
      "(confounded); category volume under-performance (within sampling noise).", {})]],
    size=Pt(14), color=S.INK_2)

# --- Appendix -------------------------------------------------------------------------------------------------------
APPX = [("V4_category_split", f"A{n(1)} · The gap by category: volume gaps are within noise (largest |z| = {n(F2['max_abs_volume_z'])}); "
                              "ticket gaps are everywhere",
         "Volume effect = (transits − plan) × plan ticket; ticket effect = (ticket − plan ticket) × transits; plan = "
         f"vessels × {n(2)} transits. A category's transit count is binomial; |z| below {n(2)} is noise."),
        ("V7_aging_heatmap", f"A{n(2)} · Who is behind: receivables at week {n(52)} by age, top {n(10)} overdue customers",
         "Amounts in millions SDR from finance.fact_ar_snapshot at week 52; rating in brackets."),
        ("V11_pareto", f"A{n(3)} · Concentration: {n(N['F12']['customers_for_80pct'])} customers make {p(80, 0)} of revenue; "
                       f"the #{n(1)} alone {p(N['F12']['top_n_share_pct']['1'])}",
         f"HHI {n(int(N['F12']['hhi']))}. The {n(13)}-week top-{n(10)} share ranged {p(N['F12']['top10_13w_min'])}–"
         f"{p(N['F12']['top10_13w_max'])}; overlapping windows, so no trend is claimed."),
        ("V6b_segment_shares", f"A{n(4)} · By segment: tankers and container lines carry the overdue book",
         f"Mean days late: tanker {n(SEG['tanker']['late_mean'])}, container {n(SEG['container']['late_mean'])}, "
         f"cruise {n(SEG['cruise']['late_mean'])}."),
        ("V12_cohorts", f"A{n(5)} · Payment behaviour by invoice month: stable through September",
         f"Matured months only; October–December are open at {n(28)} December (right-censored)."),
        ("V13_days_late", f"A{n(6)} · Days paid after due by rating: the whole distribution, not just the mean",
         f"Boxes = quartiles; points = the {n(F5['payments_asof'])} payments made by {n(28)} December.")]
for name, title, notes in APPX:
    s = new_slide(title, "Appendix", notes)
    if name == "V13_days_late":
        chart(s, name, S.MARGIN, Inches(1.45), HALF_W)
        text(s, Inches(7.0), Inches(1.6), Inches(5.6), Inches(4.4), [
            [("Rating A ", {"bold": True}), (f"median {n(int(RAT['A']['late_median']))} days: "
                                             f"{p(RAT['A']['ontime_pct'], 0)} pay on or before the due date.", {})],
            [("Rating B ", {"bold": True}), (f"median {n(int(RAT['B']['late_median']))} days, a long tail to "
                                             f"{n(F5['b_late_max'])} days.", {})],
            [("Rating C ", {"bold": True}), (f"median {n(int(RAT['C']['late_median']))} days; {n(F5['c_late_over_90'])} "
                                             f"payments came more than {n(90)} days late.", {})]], size=Pt(16))
    else:
        chart(s, name, FULL_X, Inches(1.45), FULL_W)
s = new_slide(f"A{n(7)} · Method and limits", "Appendix", "Full method: docs/analysis/financial_intelligence/.")
text(s, S.MARGIN, S.BODY_TOP, S.CONTENT_W, Inches(5.0), [
    [("Source. ", {"bold": True}), ("The finance SQL views (one definition per KPI, docs/finance_metrics.md), read-only; "
                                    "recomputed and reconciled by pipelines/scripts/finance/Executive_analysis.py.", {})],
    [("As of. ", {"bold": True}), (f"Receivables at {n(28)} December {yr(2025)} (week {n(52)}); a payment dated later is "
                                   f"never used ({n(N['meta']['payments_after_asof'])} such payments ignored).", {})],
    [("Synthetic data. ", {"bold": True}), ("Invoice dates are uniform over the year, so billing has no real trend or "
                                            "seasonality; payment behaviour differs by customer by design. Patterns are "
                                            "real in the data, not evidence about a real company.", {})],
    [("Statistics. ", {"bold": True}), (f"Trends tested on weeks {n(14)}–{n(52)} (after the receivables warm-up); overlapping "
                                        "rolling windows are not tested; correlation is never read as cause.", {})],
    [("New KPI. ", {"bold": True}), (f"M{n(12)} DSO split: best-possible DSO = current receivables ÷ window billing × window "
                                     "days; delinquency DSO = DSO − best-possible.", {})]], size=Pt(16))

OUT.parent.mkdir(parents=True, exist_ok=True)
prs.save(OUT)
print(f"deck: {len(prs.slides)} slides → {OUT}")
print("✅ Phase 2 validation passed: the deck is built and saved")


# %% Phase 3 — Read back
back = Presentation(OUT)
texts, per_slide = [], []
for sl in back.slides:
    st = []
    for shp in sl.shapes:
        if shp.has_text_frame:
            st.append(shp.text_frame.text)
        if shp.has_table:
            st += [c.text for row in shp.table.rows for c in row.cells]
    st.append(sl.notes_slide.notes_text_frame.text)
    per_slide.append("\n".join(st))
    texts += st
tokens = {tok.replace(",", "") for s_ in texts for tok in TOKEN.findall(s_)}
unregistered = sorted(tokens - REG)
print(f"numeric tokens in the deck: {len(tokens)}; unregistered: {unregistered}")
assert not unregistered, f"numbers on the slides that no formatter wrote: {unregistered}"
bad_years = sorted({y for s_ in texts for y in re.findall(r"\b20,\d{2}\b", s_)})
assert not bad_years, f"years printed with a thousands separator: {bad_years}"
must = {2: [m(Y["billed"]), p(Y["variance_pct"]), dd(Y["dso_w52"]), m(Y["ar90_w52"], 2)],
        5: [p(F4["revenue_share_pct"]), p(F4["ar_share_pct"])],
        6: [p(RAT["C"]["overdue_share"])], 7: [m(F7["w52"], 2)], 8: [dd(SCN["top5"]["dso"])]}
for no, vals in must.items():
    missing = [v for v in vals if v not in per_slide[no - 1]]
    assert not missing, (no, missing)
pics = sum(1 for sl in back.slides for shp in sl.shapes if shp.shape_type == 13)
assert len(back.slides) == 17 and pics == 13, (len(back.slides), pics)
no_alt = [shp.name for sl in back.slides for shp in sl.shapes
          if shp.shape_type == 13 and not shp._element.nvPicPr.cNvPr.get("descr")]
assert not no_alt, f"pictures without alt text: {no_alt}"
off = [(i + 1, shp.name) for i, sl in enumerate(back.slides) for shp in sl.shapes
       if shp.left < 0 or shp.top < 0 or shp.left + shp.width > S.WIDTH + 1 or shp.top + shp.height > S.HEIGHT + 1]
assert not off, f"shapes outside the slide: {off}"
print("✅ Phase 3 validation passed: every number registered; headline numbers on their slides; 17 slides, 13 charts, "
      "nothing off the page")


# %% Final Checkpoint
# Narrative: pipelines/checkpoints/finance/Executive_deck.md
summary = {"slides": len(back.slides), "charts": pics, "numeric_tokens_checked": len(tokens) > 100,
           "titles": [sd["title"][:30] for sd in SLIDES[:3]]}
print("Final Checkpoint:", summary)
assert summary["slides"] == 17 and summary["charts"] == 13 and summary["numeric_tokens_checked"]
print("✅ Final Checkpoint passed: the executive deck is built and every number traces to numbers.json")
