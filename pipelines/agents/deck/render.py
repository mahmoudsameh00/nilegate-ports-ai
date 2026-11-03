"""The NileGate weekly deck renderer (Agents plan §5c, P6-2 / P6-4 / P6-7): draft + evidence → a 10-slide PPTX.

Two steps, so the Validator can check the file against the same intent the renderer drew from:
1. `build_spec(draft, evidence, readiness, label)` — every element of every slide as data: its **name**, its kind
   and what it must show. Names carry the contract V8 checks:
   - `tpl:<key>`   fixed template text (brand, footers, labels, headers, footnotes) — the full template allowlist;
   - `bind:{…}`    one code-rendered value, the slot text of its field (a tile's number);
   - `txt:<key>`   the Writer's text with its slots filled (`txt:title`, `txt:b<i>` = bullet i of the draft);
   - `tbl:<name>`  a table: header cells are template text, data cells are labels from the evidence or bindings;
   - `chart:<name>` a native chart: categories and series = the tool's exact values (axis formats show M / k);
   - `deco:<key>`  a shape without text (backgrounds, rules).
2. `render(...)` draws the spec with python-pptx and returns the file bytes. No number is computed here: values come
   from the evidence through `slots` (the same formatting as the Writer's slots), so the deck and the draft agree.
The code-rendered parts follow deck-style-guide (slides 1, 3 tiles, every table and chart, the footnotes, slide 10).
Weekly-pack plan Phase C (storyboard, W-R2 / W-R4 / W-R5 / W-R7): a "week at a glance" strip on slide 2, the typical
swing under the tiles, the 13-week period line and invoice counts on slide 4, variance bars on slide 5, the overdue
roll-forward and the DSO split on slide 6, the receivables-risk table on slide 7, the year-to-date findings on slide 8
in a week without findings, the Suez transits chart on slide 9, slide 10 as an appendix; no accent rule under titles.
"""
import io
from dataclasses import dataclass, field
from typing import cast

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION, XL_MARKER_STYLE, XL_TICK_LABEL_POSITION
from pptx.enum.dml import MSO_LINE_DASH_STYLE
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Emu, Inches, Pt

from pipelines.agents.deck import slots
from pipelines.agents.deck import style as S

SLIDES = 10
BRAND = "NileGate Weekly Finance Pack"
WARMUP_FOOTNOTE = "Receivables still building up since 1 Jan 2025"
CONTEXT_NOTE = "External context: public data and news, not NileGate figures"
UNIT_NOTE = "Amounts in SDR"
# proposed action per audit check (skill suez-toll-audit)
ACTIONS = {"duplicate_charge": "Void it; if paid, credit note / refund",
           "tonnage_mismatch": "Correct the tonnage",
           "amount_mismatch": "Corrected invoice for the difference",
           "rate_mismatch": "Correct the rate"}
RECORD_ONLY = "Record to correct (no money at stake)"
AGING = (("aging_current_sdr", "Current"), ("aging_1_30_sdr", "1–30 days"), ("aging_31_60_sdr", "31–60 days"),
         ("aging_61_90_sdr", "61–90 days"), ("aging_90_plus_sdr", "90+ days"))
TILES = (("Billed", "billed_sdr", "M", "billed_wow_pct", "WoW"),
         ("Collected", "collected_sdr", "M", "collected_wow_pct", "WoW"),
         ("AR", "ar_sdr", "M", "ar_wow_pct", "WoW"),
         ("Overdue", "overdue_sdr", "M", "overdue_wow_pct", "WoW"),
         ("DSO", "dso_days", None, "dso_wow_days", "WoW"),
         ("Budget variance", "budget_variance_sdr", "M", "budget_variance_pct", "vs budget"))
# weekly-pack plan (storyboard S3, W-R2): a tile's WoW and its typical swing (M13)
SWING_OF = {"billed_wow_pct": "billed_wow_typical_pct", "collected_wow_pct": "collected_wow_typical_pct",
            "ar_wow_pct": "ar_wow_typical_pct", "overdue_wow_pct": "overdue_wow_typical_pct"}
# slide 5's variance bars name categories short (L5); the tables keep the full names
SHORT = {"Chemical Tankers & Other Liquid Bulk Tankers": "Chemical tankers",
         "Containerships": "Containerships", "Crude Oil Tankers": "Crude oil tankers", "Cruise Ships": "Cruise ships",
         "Dry Bulk Vessels": "Dry bulk", "General Cargo / Multi-Purpose / Heavy Lift Vessels": "General cargo",
         "Liquefied Natural Gas (LNG) Carriers": "LNG carriers", "Liquefied Petroleum Gas (LPG) Carriers": "LPG carriers",
         "Other Vessels": "Other vessels", "Petroleum Product Tankers": "Product tankers",
         "Roll-On/Roll-Off (Ro/Ro) Vessels": "Ro/Ro", "Special Floating Units": "Floating units",
         "Vehicles Carriers": "Vehicle carriers"}
# slide 6's overdue roll-forward (M14): last week's overdue → + newly overdue → − overdue paid → this week's
FLOW_STEPS = ("Overdue last week", "Newly overdue", "Overdue paid", "Overdue now")
# slide 7's watch marker (M15, W-R1); NULL = a warm-up week (1–13)
WATCH = {True: "watch", None: "warm-up", False: ""}
WATCH_RULE = "Watch: AR ≥ 1 M SDR and ≥ 80 % of its own 13-week billing (or none billed); warm-up before week 14"
# c4 (owner 2026-10-30, docs/finance_metrics.md): a large category billed well below its budget, drawn on slide 5 by
# code. Small categories swing to −100 % every week; with this floor the rule matched once in the 52 live + 4 test
# weeks (test week 36, LNG, the planted miss).
BUDGET_MISS_MIN_SDR, BUDGET_MISS_PCT, BUDGET_MISS_ROWS = 1_000_000, -25.0, 2
DRAW_BUDGET_MISS = True            # False only for the evaluation's before-c4 side (Stage1_eval.py EVAL_C4=0)
BUDGET_MISS_HEAD = "Below budget this week (a weekly budget of at least 1 M SDR, billed at least 25 % short)"


def _action(r: dict) -> str:
    """The proposed action of an audit finding (skill suez-toll-audit)."""
    return (RECORD_ONLY if r["check_code"] == "tonnage_mismatch" and not r["difference_sdr"]
            else ACTIONS.get(r["check_code"], "Manual review"))


def budget_misses(evidence: dict) -> list[dict]:
    """The `kpi.category` rows the rule calls a budget miss, the largest shortfall first."""
    rows = [r for r in evidence["kpi.category"]["rows"]
            if (r.get("budget_sdr") or 0) >= BUDGET_MISS_MIN_SDR and r.get("budget_variance_pct") is not None
            and r["budget_variance_pct"] <= BUDGET_MISS_PCT]
    return sorted(rows, key=lambda r: (r["budget_variance_pct"], r["vessel_category"]))


@dataclass
class Cell:
    text: str
    bind: str | None = None          # slot text when the cell is a tool number


@dataclass
class El:
    name: str
    kind: str                        # text | table | chart | deco
    box: tuple                       # left, top, width, height (EMU)
    text: str = ""
    style: dict = field(default_factory=dict)
    cells: list = None  # pyright: ignore[reportAssignmentType]  (table: rows of Cell; None on other elements)
    widths: tuple = ()               # table column widths (fractions)
    chart: dict = None  # pyright: ignore[reportAssignmentType]  (chart elements only) — {"type", "categories", "series": [(name, values)], "fmt", "highlight"}


def _in(*v):
    return tuple(Inches(x) for x in v)


def _title_size(text: str):
    """The largest title size from 26 down to 20 pt that keeps the title on one line (owner 2026-11-03: W13's slide 2
    title wrapped "M SDR" alone onto a second line); a title too long even at 20 pt keeps 26 pt on two lines. Bold
    Calibri runs ~0.45 em a character (measured: 75–76 characters fill the 12.13 in line at 26 pt)."""
    width_pt = S.CONTENT_W / 12700
    for pt in range(int(S.TITLE_PT.pt), 19, -1):
        if len(text) <= width_pt / (pt * 0.45):
            return Pt(pt)
    return S.TITLE_PT


def _text_h(text: str, w, size) -> Emu:
    """A wrapped text's height in a box `w` wide: lines at ~0.55 em a character (Calibri-like body text, rounded up),
    1.2 line spacing, plus the text frame's top and bottom insets."""
    pt = size / 12700
    per_line = max(1, int(w / 12700 / (pt * 0.55)))
    lines = sum(max(1, -(-len(p) // per_line)) for p in text.split("\n"))
    return Emu(int(lines * pt * 1.2 * 12700) + Inches(0.1))


def _bind(eid, f, fmt=None, row=None, direction=False) -> str:
    return slots.binding(eid, f, fmt, row, direction)


def _cell(ev, eid, f, fmt=None, row=None) -> Cell:
    b = _bind(eid, f, fmt, row)
    return Cell(slots.bound_text(b, ev), b)


# --- the spec -------------------------------------------------------------------------------------------------------

class _Spec:
    def __init__(self, draft: dict, evidence: dict, readiness: dict, label: str):
        self.d, self.ev, self.ready, self.label = draft, evidence, readiness or {}, label
        self.k = evidence["kpi.weekly"]["rows"][0]
        self.week_label = self.k["iso_week_label"]
        self.titles = {st["slide"]: slots.render_text(st["title"], evidence)[0] for st in draft["slide_titles"]}
        self.bullets = {}
        for i, b in enumerate(draft["bullets"]):
            self.bullets.setdefault(b["slide"], []).append((i, slots.render_text(b["text"], evidence)[0]))

    # common parts
    def frame(self, s: int) -> list[El]:
        y = S.FOOTER_TOP
        # W-R5 / L1–L2: a title box for two lines, no accent rule under it
        out = [El("txt:title", "text", (S.MARGIN, S.TITLE_TOP, S.CONTENT_W, S.TITLE_H), self.titles.get(s, ""),
                  {"size": _title_size(self.titles.get(s, "")), "bold": True, "color": S.NAVY, "anchor": "bottom"}),
               El("tpl:footer", "text", (S.MARGIN, y, Inches(7), S.FOOTER_H),
                  f"NileGate · {BRAND.removeprefix('NileGate ')} · {self.week_label} · {UNIT_NOTE}",
                  {"size": S.FOOT_PT, "color": S.MUTED}),
               El("tpl:page", "text", (S.WIDTH - S.MARGIN - Inches(0.8), y, Inches(0.8), S.FOOTER_H), f"{s} / {SLIDES}",
                  {"size": S.FOOT_PT, "color": S.MUTED, "align": "right"}),
               self.badge(S.WIDTH - S.MARGIN - Inches(0.9) - S.BADGE_W, y)]
        return out

    def badge(self, x, y, w=S.BADGE_W, h=S.FOOTER_H) -> El:
        approved = self.label != "Draft for approval"
        return El("tpl:label", "text", (x, y, w, h), self.label,
                  {"size": S.BADGE_PT, "bold": True, "color": S.WHITE if approved else S.INK, "align": "center",
                   "fill": S.APPROVED_BG if approved else S.LABEL_BG, "shape": "rounded", "anchor": "middle"})

    def comments(self, s: int, x, y, w, step=S.COMMENT_H) -> list[El]:
        """The slide's comments stacked from `y`, each box as tall as its wrapped text (at least `step`); the type
        steps down to 10 pt until they fit above the footnote / footer (c5b W48: three real comments overlapped on
        slide 6 in fixed-height boxes)."""
        items = self.bullets.get(s, [])
        bottom = (S.FOOTNOTE_TOP if self.k.get("is_warmup") else S.FOOTER_TOP) - Inches(0.08)
        size = S.BODY_PT if s == 2 else S.SMALL_PT + Pt(2)
        hs = [max(step, _text_h(t, w, size)) for _, t in items]
        while y + sum(hs) > bottom and size > Pt(10):
            size = Emu(size - Pt(1))
            hs = [max(step, _text_h(t, w, size)) for _, t in items]
        out, top = [], y
        for (i, text), h in zip(items, hs):
            out.append(El(f"txt:b{i}", "text", (x, top, w, h), text, {"size": size, "color": S.INK}))
            top += h
        return out

    def footnote(self) -> list[El]:
        if not self.k.get("is_warmup"):
            return []
        return [El("tpl:footnote", "text", (S.MARGIN, S.FOOTNOTE_TOP, S.CONTENT_W, Inches(0.3)), WARMUP_FOOTNOTE,
                   {"size": S.FOOT_PT, "color": S.MUTED, "italic": True})]

    def period(self) -> str:
        """W-R7: the rolling window's name — "13 weeks", or "weeks 1–w" while the year has fewer weeks."""
        n = self.k.get("roll_window_weeks") or 0
        return "13 weeks" if n >= 13 else f"weeks 1–{self.k['report_week']}"

    def value(self, eid: str, f: str, fmt, box, size: int = S.SMALL_PT, bold=False, color=S.INK, row=None) -> El:
        """One bound value: the element is named by its binding (V8 re-reads it from the evidence)."""
        b = _bind(eid, f, fmt, row)
        return El(f"bind:{b}", "text", box, slots.bound_text(b, self.ev), {"size": size, "bold": bold, "color": color})

    def tile(self, name: str, box, label: str) -> list[El]:
        x, y, w, _ = box
        return [El(f"deco:{name}", "deco", box, style={"fill": S.TILE_BG, "edge": S.NILE}),
                El(f"tpl:{name}.label", "text", (x + Inches(0.15), y + Inches(0.08), w - Inches(0.3), Inches(0.32)),
                   label, {"size": S.TILE_LABEL_PT, "color": S.INK_2, "bold": True})]

    def muted(self, key: str, text: str, box, italic=False) -> El:
        return El(f"tpl:{key}", "text", box, text, {"size": S.SMALL_PT, "color": S.MUTED, "italic": italic})

    # slides
    def s1(self) -> list[El]:
        k = self.k
        return [El("deco:bg", "deco", (0, 0, S.WIDTH, S.HEIGHT), style={"fill": S.NAVY}),
                El("deco:rule", "deco", _in(0.9, 2.55, 1.6, 0.08), style={"fill": S.NILE}),
                El("tpl:brand", "text", _in(0.9, 1.4, 11.5, 1.0), BRAND,
                   {"size": S.BRAND_PT, "bold": True, "color": S.WHITE}),
                El("tpl:week", "text", _in(0.9, 2.8, 11.5, 0.6),
                   f"{k['iso_week_label']} · {k['week_start']} – {k['week_end']}",
                   {"size": S.WEEK_PT, "color": S.WHITE}),
                El("txt:title", "text", _in(0.9, 3.6, 11.5, 1.2), self.titles.get(1, ""),
                   {"size": Pt(24), "color": S.WHITE}),
                El("tpl:unit", "text", _in(0.9, 6.2, 6, 0.4), f"Finance · weekly report · {UNIT_NOTE}",
                   {"size": S.SMALL_PT, "color": S.WHITE}),
                self.badge(*_in(10.9, 6.2, 1.6, 0.35))]

    def s2(self) -> list[El]:
        """W-R5 / L6: a "week at a glance" strip of four mini-tiles above the five bullets."""
        out, k = self.frame(2), "kpi.weekly"
        gap, h = Inches(0.2), Inches(1.15)
        w = Emu(int((S.CONTENT_W - 3 * gap) / 4))
        y = S.BODY_TOP
        xs = [S.MARGIN + n * (w + gap) for n in range(4)]
        big, i2 = Pt(18), Inches(0.15)
        # 1 billed WoW against its typical swing (M13)
        out += self.tile("glance0", (xs[0], y, w, h), "Billed, week on week")
        out.append(self.value(k, "billed_wow_pct", "%1", (xs[0] + i2, y + Inches(0.38), w - 2 * i2,
                                                                 Inches(0.4)), big, True))
        out += self.swing("glance0", "billed_wow_typical_pct", (xs[0] + i2, y + Inches(0.78), w - 2 * i2))
        # 2 the period against budget (M9b)
        out += self.tile("glance1", (xs[1], y, w, h), f"Billed vs budget, {self.period()}")
        out.append(self.value(k, "budget_variance_13w_pct", "%1", (xs[1] + i2, y + Inches(0.38), w - 2 * i2,
                                                                          Inches(0.4)), big, True))
        # 3 the overdue flow of the week (M14)
        out += self.tile("glance2", (xs[2], y, w, h), "Overdue: new and paid")
        out += [self.muted("glance2.new", "newly overdue", (xs[2] + i2, y + Inches(0.42), Inches(1.25), Inches(0.3))),
                self.value(k, "overdue_new_sdr", "M", (xs[2] + Inches(1.4), y + Inches(0.4), w - Inches(1.5),
                                                               Inches(0.32)), S.SMALL_PT + Pt(2), True),
                self.muted("glance2.paid", "paid", (xs[2] + i2, y + Inches(0.76), Inches(1.25), Inches(0.3))),
                self.value(k, "overdue_paid_sdr", "M", (xs[2] + Inches(1.4), y + Inches(0.74), w - Inches(1.5),
                                                                Inches(0.32)), S.SMALL_PT + Pt(2), True)]
        # 4 DSO = terms + delinquency (M12)
        out += self.tile("glance3", (xs[3], y, w, h), "DSO")
        out += [self.value(k, "dso_days", None, (xs[3] + i2, y + Inches(0.38), w - 2 * i2, Inches(0.4)), big,
                           True),
                self.muted("glance3.terms", "terms", (xs[3] + i2, y + Inches(0.8), Inches(0.5), Inches(0.3))),
                self.value(k, "dso_best_days", None, (xs[3] + Inches(0.6), y + Inches(0.8), Inches(0.9),
                                                      Inches(0.3))),
                self.muted("glance3.late", "late", (xs[3] + Inches(1.5), y + Inches(0.8), Inches(0.4), Inches(0.3))),
                self.value(k, "dso_delinquency_days", None, (xs[3] + Inches(1.88), y + Inches(0.8),
                                                             w - Inches(1.93), Inches(0.3)))]
        top = y + h + Inches(0.25)
        for n, (i, text) in enumerate(self.bullets.get(2, [])):
            yy = top + Inches(n * 0.72)
            out += [El(f"deco:mark{n}", "deco", (S.MARGIN, yy + Inches(0.1), Inches(0.12), Inches(0.12)),
                       style={"fill": S.NILE}),
                    El(f"txt:b{i}", "text", (S.MARGIN + Inches(0.3), yy, S.CONTENT_W - Inches(0.3), Inches(0.68)),
                       text, {"size": S.BODY_PT, "color": S.INK})]
        return out

    def swing(self, name: str, field: str, box) -> list[El]:
        """W-R2: "typical ±x %" (the 13-week median |WoW|); blank-free: "typical swing: not yet" while NULL."""
        x, y, w = box
        if self.k.get(field) is None:
            return [self.muted(f"{name}.typical", "typical swing: not yet (warm-up)", (x, y, w, Inches(0.3)), True)]
        return [self.muted(f"{name}.typical", "typical ±", (x, y, Inches(0.8), Inches(0.3))),
                self.value("kpi.weekly", field, "%1", (x + Inches(0.8), y, w - Inches(0.8), Inches(0.3)),
                           color=S.MUTED)]

    def s3(self) -> list[El]:
        out, gap, th = self.frame(3), Inches(0.2), Inches(1.6)
        tw = Emu(int((S.CONTENT_W - 2 * gap) / 3))
        for n, (label, f, fmt, ch, ch_label) in enumerate(TILES):
            x, y = S.MARGIN + (n % 3) * (tw + gap), S.BODY_TOP + (n // 3) * (th + gap)
            vb, cb = _bind("kpi.weekly", f, fmt), _bind("kpi.weekly", ch, "%2" if ch.endswith("_pct") else None)
            out += [El(f"deco:tile{n}", "deco", (x, y, tw, th), style={"fill": S.TILE_BG, "edge": S.NILE}),
                    El(f"tpl:tile{n}.label", "text", (x + Inches(0.2), y + Inches(0.1), tw, Inches(0.35)), label,
                       {"size": S.TILE_LABEL_PT, "color": S.INK_2, "bold": True}),
                    El(f"bind:{vb}", "text", (x + Inches(0.2), y + Inches(0.42), tw - Inches(0.3), Inches(0.55)),
                       slots.bound_text(vb, self.ev), {"size": S.TILE_VALUE_PT, "bold": True, "color": S.INK}),
                    El(f"bind:{cb}", "text", (x + Inches(0.2), y + Inches(0.98), Inches(1.6), Inches(0.35)),
                       slots.bound_text(cb, self.ev), {"size": S.TILE_LABEL_PT, "color": S.INK}),
                    El(f"tpl:tile{n}.change", "text", (x + Inches(1.8), y + Inches(0.98), Inches(1.4), Inches(0.35)),
                       ch_label, {"size": S.TILE_LABEL_PT, "color": S.MUTED})]
            if ch in SWING_OF:
                out += self.swing(f"tile{n}", SWING_OF[ch], (x + Inches(0.2), y + Inches(1.25), tw - Inches(0.3)))
        out += self.comments(3, S.MARGIN, S.BODY_TOP + 2 * (th + gap), S.CONTENT_W)
        return out + self.footnote()

    def drivers(self):
        rows = self.ev["kpi.category"]["rows"]
        by = ("billed_wow_change_sdr" if any(r["billed_wow_change_sdr"] is not None for r in rows)
              else "budget_variance_sdr")
        return sorted(rows, key=lambda r: -abs(r[by] or 0))[:3], by

    def s4(self) -> list[El]:
        out, k = self.frame(4), "kpi.weekly"
        trend = self.ev["kpi.trend"]["rows"]
        cats = [r["trend_week_label"] for r in trend]
        hi = next((i for i, r in enumerate(trend) if r.get("is_report_week")), len(trend) - 1)
        out.append(El("chart:trend", "chart", _in(0.6, 1.55, 5.6, 3.3), chart={
            "type": "line", "categories": cats, "fmt": S.AXIS_M, "highlight": hi,
            "series": [("Billed", [r["billed_sdr"] for r in trend]), ("Budget", [r["budget_sdr"] for r in trend])]}))
        # the period line under the chart (M9b): "13 weeks: billed x vs budget y, z"
        y, row = Inches(4.95), Inches(0.32)
        out += [El("tpl:period.label", "text", _in(0.6, 4.95, 1.2, 0.32), self.period().capitalize() + ":",
                   {"size": S.SMALL_PT, "bold": True, "color": S.INK_2}),
                self.muted("period.billed", "billed", _in(1.8, 4.95, 0.55, 0.32)),
                self.value(k, "billed_13w_sdr", "M", (Inches(2.3), y, Inches(1.2), row)),
                self.muted("period.budget", "vs budget", _in(3.5, 4.95, 0.8, 0.32)),
                self.value(k, "budget_13w_sdr", "M", (Inches(4.3), y, Inches(1.2), row)),
                self.value(k, "budget_variance_13w_pct", "%1", (Inches(5.5), y, Inches(0.85), row), bold=True)]  # ends before the comments column (6.45 in)
        top, by = self.drivers()
        flagged = {r["vessel_category"] for r in self.ev["audit.week"]["rows"]}
        if by == "billed_wow_change_sdr":
            head = ["Driver", "Billed", "WoW change", "WoW"]
            body = [[Cell(r["vessel_category"]), _cell(self.ev, "kpi.category", "billed_sdr", "M", r["vessel_category"]),
                     _cell(self.ev, "kpi.category", "billed_wow_change_sdr", "M", r["vessel_category"]),
                     _cell(self.ev, "kpi.category", "billed_wow_pct", "%1", r["vessel_category"])] for r in top]
        else:
            head = ["Driver (week one: vs budget)", "Billed", "vs budget", "vs budget %"]
            body = [[Cell(r["vessel_category"]), _cell(self.ev, "kpi.category", "billed_sdr", "M", r["vessel_category"]),
                     _cell(self.ev, "kpi.category", "budget_variance_sdr", "M", r["vessel_category"]),
                     _cell(self.ev, "kpi.category", "budget_variance_pct", "%1", r["vessel_category"])] for r in top]
        # invoices this / last week: when a driver is one transit (storyboard S4)
        for row, r in zip(body, top):
            row += [_cell(self.ev, "kpi.category", "invoices_billed", None, r["vessel_category"]),
                    _cell(self.ev, "kpi.category", "invoices_prev", None, r["vessel_category"]),
                    Cell("audit finding" if r["vessel_category"] in flagged else "")]
        out.append(El("tbl:drivers", "table", _in(6.45, 1.6, 6.28, 1.9), cells=[[Cell(h) for h in head + [
            "Invoices", "Last week", "Audit"]]] + body,
            widths=(0.26, 0.14, 0.15, 0.13, 0.10, 0.12, 0.10), style={"size": Pt(10)}))   # WoW fits "−100.0 %"
        out += self.comments(4, Inches(6.45), Inches(3.75), Inches(6.28), Inches(0.62))
        return out

    def s5(self) -> list[El]:
        """W-R5 / L5: variance bars (billed − budget per category, sorted, short names); the c4 budget-miss table."""
        out = self.frame(5)
        # a bar chart draws its first category at the bottom: the largest shortfall first puts the largest excess on
        # top (no reversed axis, which moves the value axis to the top)
        rows = sorted(self.ev["kpi.category"]["rows"],
                      key=lambda r: (r["budget_variance_sdr"] or 0, r["vessel_category"]))
        misses = budget_misses(self.ev) if DRAW_BUDGET_MISS else []
        out.append(El("chart:variance", "chart", _in(0.6, 1.5, 8.3, 4.2 if misses else 5.0), chart={
            "type": "bar", "categories": [SHORT.get(r["vessel_category"], r["vessel_category"]) for r in rows],
            "fmt": S.AXIS_M, "diverging": True,
            "series": [("Billed − budget", [r["budget_variance_sdr"] for r in rows])]}))
        if misses:                     # c4: drawn by code, so a budget miss never depends on the Writer saying it
            shown = misses[:BUDGET_MISS_ROWS]
            more = f" — the largest {len(shown)} of {len(misses)}" if len(misses) > len(shown) else ""
            out.append(El("tpl:budget_miss", "text", _in(0.6, 5.75, 8.3, 0.3), BUDGET_MISS_HEAD + more,
                          {"size": S.SMALL_PT, "bold": True, "color": S.INK}))
            out.append(El("tbl:budget_miss", "table", _in(0.6, 6.05, 8.3, 0.25 * (len(shown) + 1)), cells=[
                [Cell(h) for h in ("Category", "Billed", "Budget", "vs budget %")]] + [
                [Cell(r["vessel_category"]),
                 _cell(self.ev, "kpi.category", "billed_sdr", "M", r["vessel_category"]),
                 _cell(self.ev, "kpi.category", "budget_sdr", "M", r["vessel_category"]),
                 _cell(self.ev, "kpi.category", "budget_variance_pct", "%1", r["vessel_category"])] for r in shown],
                widths=(0.46, 0.18, 0.18, 0.18), style={"size": Pt(10)}))
        out += self.comments(5, Inches(9.2), S.BODY_TOP + Inches(0.2), Inches(3.5), Inches(1.4))
        return out

    def s6(self) -> list[El]:
        """Storyboard S6: aging, the overdue roll-forward (M14), the DSO split (M12) + cash due this week."""
        out, k = self.frame(6), "kpi.weekly"
        out.append(El("chart:aging", "chart", _in(0.6, 1.5, 4.1, 2.6), chart={
            "type": "column", "categories": [lbl for _, lbl in AGING], "fmt": S.AXIS_M,
            "series": [("Receivables by age", [self.k[f] for f, _ in AGING])]}))
        trend = self.ev["kpi.trend"]["rows"]
        prev = next((r for r in trend if r.get("week_offset") == -1), None)
        if prev is not None:
            out.append(El("chart:overdue_flow", "chart", _in(4.85, 1.5, 4.0, 2.6), chart={
                "type": "column", "categories": list(FLOW_STEPS), "fmt": S.AXIS_M, "steps": True,
                "series": [("Overdue flow", [prev["overdue_sdr"], self.k["overdue_new_sdr"],
                                             self.k["overdue_paid_sdr"], self.k["overdue_sdr"]])]}))
        else:
            out.append(self.muted("overdue_flow.none", "Overdue flow: from week 2", _in(4.85, 1.6, 4.0, 0.4), True))
        # the DSO tile with its split and the week's cash due
        x, y, w = Inches(9.0), Inches(1.5), Inches(3.73)
        out += self.tile("dso", (x, y, w, Inches(2.6)), "DSO")
        i2 = Inches(0.15)
        out += [self.value(k, "dso_days", None, (x + i2, y + Inches(0.38), Inches(1.7), Inches(0.45)), Pt(20),
                           True),
                self.value(k, "dso_wow_days", None, (x + Inches(1.9), y + Inches(0.45), Inches(1.2),
                                                           Inches(0.35))),
                self.muted("dso.change", "WoW", (x + Inches(3.05), y + Inches(0.45), Inches(0.6), Inches(0.35))),
                self.muted("dso.terms", "on terms", (x + i2, y + Inches(0.95), Inches(1.6), Inches(0.3))),
                self.value(k, "dso_best_days", None, (x + Inches(1.9), y + Inches(0.95), Inches(1.6),
                                                            Inches(0.3))),
                self.muted("dso.late", "late payment", (x + i2, y + Inches(1.28), Inches(1.6), Inches(0.3))),
                self.value(k, "dso_delinquency_days", None, (x + Inches(1.9), y + Inches(1.28), Inches(1.6),
                                                                   Inches(0.3))),
                self.muted("due.label", "Due this week, collected", (x + i2, y + Inches(1.75), Inches(2.2),
                                                                      Inches(0.3))),
                self.value(k, "due_week_collected_pct", "%1", (x + Inches(2.4), y + Inches(1.75),
                                                                      Inches(1.2), Inches(0.3)), bold=True),
                self.muted("due.of", "of", (x + i2, y + Inches(2.08), Inches(0.35), Inches(0.3))),
                self.value(k, "due_week_sdr", "M", (x + Inches(0.5), y + Inches(2.08), Inches(2.0),
                                                          Inches(0.3)))]
        od = self.ev["kpi.overdue"]["rows"][:3]
        if od:
            body = [[Cell(r["invoice_number"]), Cell(r["customer_name"]),
                     _cell(self.ev, "kpi.overdue", "amount_sdr", None, r["invoice_number"]),
                     _cell(self.ev, "kpi.overdue", "days_past_due", None, r["invoice_number"]),
                     Cell(r["aging_bucket"])] for r in od]
            out.append(El("tbl:overdue", "table", _in(0.6, 4.3, 7.6, 1.3), cells=[[Cell(h) for h in (
                "Largest overdue", "Customer", "Amount", "Past due", "Bucket")]] + body,
                widths=(0.18, 0.34, 0.2, 0.13, 0.15), style={"size": Pt(10)}))
        else:
            out.append(El("tpl:overdue.none", "text", _in(0.6, 4.3, 7.6, 0.5), "No overdue invoice this week",
                          {"size": S.BODY_PT, "color": S.INK_2}))
        out += self.comments(6, Inches(8.5), Inches(4.3), Inches(4.23), Inches(0.62))
        return out + self.footnote()

    def s7(self) -> list[El]:
        """Storyboard S7: customers and receivables risk — AR / 13-week billing and the watch marker (M15, W-R1)."""
        out = self.frame(7)
        cu = self.ev["kpi.customers"]["rows"][:10]
        body = [[_cell(self.ev, "kpi.customers", "rank_13w", None, r["customer_name"]),
                 _cell(self.ev, "kpi.customers", "rank_13w_prev", None, r["customer_name"]), Cell(r["customer_name"]),
                 Cell(r.get("credit_rating") or ""),
                 _cell(self.ev, "kpi.customers", "billed_13w_sdr", "M", r["customer_name"]),
                 _cell(self.ev, "kpi.customers", "ar_sdr", "M", r["customer_name"]),
                 _cell(self.ev, "kpi.customers", "overdue_sdr", "M", r["customer_name"]),
                 _cell(self.ev, "kpi.customers", "ar_to_billed_13w_pct", "%1", r["customer_name"]),
                 Cell(WATCH.get(r.get("is_watchlist"), ""))] for r in cu]
        out.append(El("tbl:customers", "table", _in(0.6, 1.55, 12.13, 3.6), cells=[[Cell(h) for h in (
            "Rank", "Previous", "Customer", "Rating", "Billed, 13 weeks", "AR", "Overdue", "AR / billed",
            "Watch")]] + body,
            widths=(0.06, 0.08, 0.3, 0.07, 0.12, 0.1, 0.1, 0.09, 0.08), style={"size": Pt(10)}))
        share = _bind("kpi.weekly", "top10_share_13w_pct", "%1")
        out += [El("deco:tile", "deco", _in(9.0, 5.35, 3.73, 1.15), style={"fill": S.TILE_BG, "edge": S.NILE}),
                El("tpl:share.label", "text", _in(9.15, 5.42, 3.4, 0.35), "Top-10 share, 13 weeks",
                   {"size": S.TILE_LABEL_PT, "bold": True, "color": S.INK_2}),
                El(f"bind:{share}", "text", _in(9.15, 5.8, 3.4, 0.55), slots.bound_text(share, self.ev),
                   {"size": Pt(22), "bold": True, "color": S.INK}),
                self.muted("watch.rule", WATCH_RULE, _in(0.6, 5.12, 8.2, 0.3), True)]
        out += self.comments(7, S.MARGIN, Inches(5.45), Inches(8.2), Inches(0.42))
        return out

    def s8(self) -> list[El]:
        out = self.frame(8)
        rows = self.ev["audit.week"]["rows"][:8]
        if rows:
            for n, (label, f, fmt) in enumerate((("Invoices checked", "invoices_checked", None),
                                                 ("Flagged", "invoices_flagged", None),
                                                 ("Amount at stake", "amount_at_stake_sdr", None))):
                x = S.MARGIN + n * Inches(4.1)
                b = _bind("audit.week", f, fmt)
                out += [El(f"deco:tile{n}", "deco", (x, S.BODY_TOP, Inches(3.8), Inches(1.1)),
                           style={"fill": S.TILE_BG, "edge": S.NILE}),
                        El(f"tpl:tile{n}.label", "text", (x + Inches(0.2), S.BODY_TOP + Inches(0.08), Inches(3.4),
                                                          Inches(0.35)), label,
                           {"size": S.TILE_LABEL_PT, "bold": True, "color": S.INK_2}),
                        El(f"bind:{b}", "text", (x + Inches(0.2), S.BODY_TOP + Inches(0.42), Inches(3.4),
                                                 Inches(0.55)),
                           slots.bound_text(b, self.ev), {"size": Pt(22), "bold": True, "color": S.INK})]
            out.append(El("tbl:audit", "table", _in(0.6, 2.95, 12.13, 2.2), cells=[[Cell(h) for h in (
                "Invoice", "Vessel category", "Check", "Difference", "Proposed action")]] + [
                [Cell(r["invoice_number"]), Cell(r["vessel_category"]), Cell(r["check_code"]),
                 _cell(self.ev, "audit.week", "difference_sdr", None, f"{r['invoice_number']}/{r['check_code']}"),
                 Cell(_action(r))] for r in rows],
                widths=(0.13, 0.27, 0.15, 0.15, 0.30)))
            out += self.comments(8, S.MARGIN, Inches(5.35), S.CONTENT_W)
            return out
        # W-R4: no finding this week → one compact line + the year-to-date findings
        out += [self.value("audit.week", "invoices_checked", None, _in(0.6, 1.6, 0.6, 0.4), S.BODY_PT, True),
                El("tpl:audit.none", "text", _in(1.2, 1.6, 8.0, 0.4), "invoices checked this week, none flagged",
                   {"size": S.BODY_PT, "color": S.INK_2})]
        ytd = (self.ev.get("audit.ytd") or {}).get("rows") or []
        if ytd:
            shown = ytd[:8]
            more = f" — the largest {len(shown)} of {len(ytd)}" if len(ytd) > len(shown) else ""
            out.append(El("tpl:ytd.head", "text", _in(0.6, 2.25, 12.13, 0.35),
                          f"Findings this year, weeks 1–{self.k['report_week']}{more}",
                          {"size": S.SMALL_PT + Pt(2), "bold": True, "color": S.INK}))
            out.append(El("tbl:audit_ytd", "table", _in(0.6, 2.65, 12.13, 0.32 * (len(shown) + 1)), cells=[
                [Cell(h) for h in ("Week", "Invoice", "Vessel category", "Check", "Difference", "Proposed action")]] + [
                [Cell(f"W{r['report_week']}"), Cell(r["invoice_number"]), Cell(r["vessel_category"]),
                 Cell(r["check_code"]),
                 _cell(self.ev, "audit.ytd", "difference_sdr", None, f"{r['invoice_number']}/{r['check_code']}"),
                 Cell(_action(r))] for r in shown],
                widths=(0.07, 0.13, 0.25, 0.14, 0.13, 0.28), style={"size": Pt(10)}))
            top = Inches(2.65 + 0.32 * (len(shown) + 1) + 0.35)      # the comments follow the year's table
        else:
            out.append(El("tpl:ytd.none", "text", _in(0.6, 2.25, 12.13, 0.4), "No finding this year so far",
                          {"size": S.BODY_PT, "color": S.INK_2}))
            top = Inches(2.9)
        out += self.comments(8, S.MARGIN, min(Inches(5.35), top), S.CONTENT_W)
        return out

    def suez(self) -> dict | None:
        """The daily Suez transits the Insight agent fetched (the longest result; none → no chart)."""
        found = [res for _, res in sorted(self.ev.items()) if res.get("tool") == "suez_transits"
                 and res.get("status") == "ok" and res.get("rows")]
        return max(found, key=lambda r: len(r["rows"])) if found else None

    def s9(self) -> list[El]:
        out = self.frame(9)
        tr = self.suez()
        if tr:                          # W-R5: the skill's "transits vs the previous weeks", made visible
            out.append(El("chart:suez", "chart", _in(0.6, 1.55, 6.0, 3.6), chart={
                "type": "line", "categories": [r["date"] for r in tr["rows"]], "fmt": "#,##0",
                "series": [("Suez Canal transits a day", [r["n_total"] for r in tr["rows"]])]}))
            out += self.comments(9, Inches(6.9), S.BODY_TOP + Inches(0.1), Inches(5.83), Inches(1.1))
        else:
            out += self.comments(9, S.MARGIN, S.BODY_TOP + Inches(0.1), S.CONTENT_W, Inches(0.8))
        out.append(El("tpl:context.note", "text", (S.MARGIN, S.FOOTNOTE_TOP, S.CONTENT_W, Inches(0.3)), CONTEXT_NOTE,
                      {"size": S.FOOT_PT, "color": S.MUTED, "italic": True}))
        return out

    def s10(self) -> list[El]:
        out = self.frame(10)
        out.append(self.muted("appendix", "Appendix — data sources", _in(0.6, 0.12, 6.0, 0.3)))
        body = []
        flagged = False
        for eid, res in sorted(self.ev.items()):
            src = res.get("source") or {}
            flagged |= any(r.get("suspected_injection") for r in res.get("rows") or [])
            body.append([Cell(eid), Cell(res.get("tool") or ""), Cell(src.get("name") or ""),
                         Cell(src.get("filter") or ""), Cell(res.get("status") or ""),
                         Cell(src.get("retrieved_at") or "")])
        row_h = 0.38                                         # a 9 pt row as PowerPoint draws it
        out.append(El("tbl:sources", "table", _in(0.6, 1.55, 12.13, row_h * (len(body) + 1)), cells=[[Cell(h) for h in (
            "Evidence", "Tool", "Source", "Filter", "Status", "Retrieved")]] + body,
            widths=(0.17, 0.12, 0.2, 0.27, 0.1, 0.14), style={"size": Pt(9)}))
        facts = self.ready.get("facts") or {}
        missing = [eid for eid, res in sorted(self.ev.items()) if res.get("status") != "ok"]
        lines = [f"Data as of {facts.get('week_end')}; payments loaded through {facts.get('payments_through')}",
                 "Not checked: " + (", ".join(missing) if missing else "nothing — every source answered")]
        if flagged:
            lines.append("A retrieved passage was flagged as a possible injection and used as data only")
        y = Inches(1.55) + Inches(row_h) * (len(body) + 1) + Inches(0.2)
        for n, line in enumerate(lines):
            out.append(El(f"tpl:fresh{n}", "text", (S.MARGIN, y + n * Inches(0.34), S.CONTENT_W, Inches(0.32)), line,
                          {"size": S.SMALL_PT - Pt(1), "color": S.INK_2}))
        return out


def build_spec(draft: dict, evidence: dict, readiness: dict, label: str) -> list[list[El]]:
    sp = _Spec(draft, evidence, readiness, label)
    return [getattr(sp, f"s{s}")() for s in range(1, SLIDES + 1)]


# --- drawing --------------------------------------------------------------------------------------------------------

def _text(slide, e: El):
    st = e.style
    if st.get("fill") is not None:
        shp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE if st.get("shape") == "rounded"
                                     else MSO_SHAPE.RECTANGLE, *e.box)
        shp.fill.solid()
        shp.fill.fore_color.rgb = st["fill"]
        shp.line.fill.background()
        shp.shadow.inherit = False
    else:
        shp = slide.shapes.add_textbox(*e.box)
    shp.name = e.name
    tf = shp.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(0.04)
    tf.vertical_anchor = {"bottom": MSO_ANCHOR.BOTTOM, "middle": MSO_ANCHOR.MIDDLE}.get(cast(str, st.get("anchor")),
                                                                                    MSO_ANCHOR.TOP)
    p = tf.paragraphs[0]
    p.alignment = {"right": PP_ALIGN.RIGHT, "center": PP_ALIGN.CENTER}.get(cast(str, st.get("align")), PP_ALIGN.LEFT)
    r = p.add_run()
    r.text = e.text
    f = r.font
    f.name, f.size, f.bold, f.italic = S.FONT, st.get("size", S.BODY_PT), st.get("bold", False), st.get("italic",
                                                                                                        False)
    f.color.rgb = st.get("color", S.INK)


def _deco(slide, e: El):
    shp = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, *e.box)
    shp.name = e.name
    shp.fill.solid()
    shp.fill.fore_color.rgb = e.style["fill"]
    if e.style.get("edge") is not None:
        shp.line.color.rgb = e.style["edge"]
        shp.line.width = Pt(1)
    else:
        shp.line.fill.background()
    shp.shadow.inherit = False


def _table(slide, e: El):
    rows, cols = len(e.cells), len(e.cells[0])
    gf = slide.shapes.add_table(rows, cols, e.box[0], e.box[1], e.box[2], Emu(int(Inches(0.32) * rows)))
    gf.name = e.name
    t = gf.table
    total = e.box[2]
    for j, frac in enumerate(e.widths or [1 / cols] * cols):
        t.columns[j].width = Emu(int(total * frac))
    size = e.style.get("size", Pt(11))
    for i, row in enumerate(e.cells):
        for j, c in enumerate(row):
            cell = t.cell(i, j)
            cell.fill.solid()
            cell.fill.fore_color.rgb = S.NAVY if i == 0 else (S.WHITE if i % 2 else S.TILE_BG)
            cell.margin_left = cell.margin_right = Inches(0.06)
            cell.margin_top = cell.margin_bottom = Inches(0.03)
            tf = cell.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.alignment = PP_ALIGN.RIGHT if (c.bind and i) else PP_ALIGN.LEFT
            r = p.add_run()
            r.text = c.text
            r.font.name, r.font.size, r.font.bold = S.FONT, size, i == 0
            r.font.color.rgb = S.WHITE if i == 0 else S.INK
            # the paragraph mark keeps the theme's 18 pt unless sized: PowerPoint then draws every row ~0.39 in tall
            # whatever the run size (c5b W48: slide 7's table ran under the watch rule)
            p._p.get_or_add_endParaRPr().set("sz", str(round(size / 127)))


def _chart(slide, e: El):
    c = e.chart
    data = CategoryChartData(number_format="General")
    data.categories = c["categories"]
    for name, values in c["series"]:
        data.add_series(name, values)
    kind = {"line": XL_CHART_TYPE.LINE_MARKERS, "bar": XL_CHART_TYPE.BAR_CLUSTERED,
            "column": XL_CHART_TYPE.COLUMN_CLUSTERED}[c["type"]]
    gf = slide.shapes.add_chart(kind, *e.box, data)
    gf.name = e.name
    ch = gf.chart
    ch.font.name, ch.font.size = S.FONT, Pt(11)
    ch.font.color.rgb = S.INK_2
    ch.has_legend = len(c["series"]) > 1
    if ch.has_legend:
        ch.legend.position = XL_LEGEND_POSITION.TOP
        ch.legend.include_in_layout = False
    va = ch.value_axis
    va.tick_labels.number_format = c["fmt"]
    va.tick_labels.number_format_is_linked = False
    va.has_major_gridlines = True
    va.major_gridlines.format.line.color.rgb = S.GRID
    va.format.line.fill.background()
    ca = ch.category_axis
    ca.tick_labels.font.size = Pt(10)
    ca.format.line.color.rgb = S.GRID
    plot = ch.plots[0]
    colors = [S.SERIES_1, S.COMPARISON]
    if c["type"] == "line":
        for n, s in enumerate(plot.series):
            s.smooth = False
            s.format.line.color.rgb = colors[n]
            s.format.line.width = Pt(2.25)
            s.marker.style = XL_MARKER_STYLE.CIRCLE
            s.marker.size = 5
            s.marker.format.fill.solid()
            s.marker.format.fill.fore_color.rgb = colors[n]
            s.marker.format.line.color.rgb = colors[n]
            if n:
                s.format.line.dash_style = MSO_LINE_DASH_STYLE.DASH
        hi = c.get("highlight")
        if hi is not None and plot.series:
            pt = plot.series[0].points[hi]
            pt.marker.style = XL_MARKER_STYLE.CIRCLE
            pt.marker.size = 10
            pt.marker.format.fill.solid()
            pt.marker.format.fill.fore_color.rgb = S.HIGHLIGHT
            pt.marker.format.line.color.rgb = S.HIGHLIGHT
    else:
        plot.gap_width = 60
        if len(plot.series) > 1:
            plot.overlap = -10
        for n, s in enumerate(plot.series):
            s.format.fill.solid()
            s.format.fill.fore_color.rgb = colors[n]
            s.invert_if_negative = False
        if c.get("diverging"):          # below budget grey, above budget blue (one hue per sign, dataviz)
            ca.tick_label_position = XL_TICK_LABEL_POSITION.LOW     # names left of the bars, not on them
            _point_fills(plot.series[0], [S.SERIES_1 if (v or 0) >= 0 else S.COMPARISON
                                          for v in c["series"][0][1]])
        if c.get("steps"):              # the roll-forward: the two levels blue, newly overdue orange, paid grey
            _point_fills(plot.series[0], [S.SERIES_1, S.HIGHLIGHT, S.COMPARISON, S.SERIES_1])


def _point_fills(series, colors):
    """One fill per point; each point also says "do not invert if negative" (PowerPoint draws a negative point
    without its own flag white)."""
    for i, rgb in enumerate(colors):
        pt = series.points[i]
        pt.format.fill.solid()
        pt.format.fill.fore_color.rgb = rgb
        d_pt = series._element.get_or_add_dPt_for_point(i)
        if d_pt.find(qn("c:invertIfNegative")) is None:
            flag = OxmlElement("c:invertIfNegative")
            flag.set("val", "0")
            d_pt.idx.addnext(flag)


def render(draft: dict, evidence: dict, readiness: dict, label: str) -> bytes:
    prs = Presentation()
    prs.slide_width, prs.slide_height = S.WIDTH, S.HEIGHT
    blank = prs.slide_layouts[6]
    for els in build_spec(draft, evidence, readiness, label):
        slide = prs.slides.add_slide(blank)
        for e in els:
            {"text": _text, "deco": _deco, "table": _table, "chart": _chart}[e.kind](slide, e)
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()
