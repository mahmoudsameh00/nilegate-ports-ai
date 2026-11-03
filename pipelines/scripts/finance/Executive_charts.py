"""Executive charts 2025 — the PNG charts of the executive deck (V2–V13), from the Executive_analysis outputs.

Plan:    docs/analysis/financial_intelligence/implementation_roadmap.md Phase B; chart list
         docs/analysis/financial_intelligence/visualization_recommendations.md.
Run:     uv run python tools/run.py pipelines/scripts/finance/Executive_charts.py  (after Executive_analysis.py)

Reads:   Data/processed/finance/executive_2025/ numbers.json + the CSV series (no database access).
Writes:  Data/processed/finance/executive_2025/charts/V*.png (200 dpi, sized for the 16:9 slide grid of
         pipelines/agents/deck/style.py).
Re-run:  safe (deterministic; same input → same PNG bytes).

Colour (dataviz method, validated with the skill's validate_palette.js on the white slide, 2026-10-31):
categorical slots 1–3 = blue #2A78D6, orange #EB6834, aqua #1BAF7A (all checks pass; aqua is below 3:1 contrast, so
every aqua mark carries a direct label); a reference / comparison = grey #A3A29C; polarity (waterfall) = blue ↔ red
#E34948 with grey totals (pass); magnitude (heatmap) = one blue ramp. Text never wears a series colour. One y-axis per
chart. The PNGs are static (a slide): the "hover layer" of the method does not apply; values are labelled instead.

Phases
1. Inputs and style.
2. Revenue and budget charts: V2 rolling band, V3 waterfall, V4 category split.
3. Customer and credit charts: V5 risk matrix, V6 rating / segment shares, V11 Pareto, V13 days late by rating.
4. Receivables charts: V7 aging heatmap, V8 90+ build-up, V9 DSO split, V10 scenario, V12 cohorts.
5. Validation: every chart file, its pixel size, and the chart data equal numbers.json.
Final Checkpoint.
"""
# %% Setup
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.text import Text  # noqa: E402
from matplotlib.ticker import FuncFormatter, PercentFormatter  # noqa: E402

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())
sys.path.insert(0, str(ROOT))
SRC = ROOT / "Data" / "processed" / "finance" / "executive_2025"
OUT = SRC / "charts"
DPI = 200
FULL, HALF = (12.0, 4.6), (5.9, 4.6)            # inches: full content width / half, under a slide title

BLUE, ORANGE, AQUA, GREY, RED = "#2A78D6", "#EB6834", "#1BAF7A", "#A3A29C", "#E34948"
INK, INK_2, MUTED, GRID = "#0B0B0B", "#52514E", "#8A8984", "#E5E4E0"
BLUE_RAMP = ["#FFFFFF", "#CDE2FB", "#86B6EF", "#3987E5", "#1C5CAB", "#0D366B"]
RATING_COLOUR = {"A": BLUE, "B": ORANGE, "C": AQUA}

plt.rcParams.update({
    "font.family": "Calibri", "font.size": 11, "axes.edgecolor": GRID, "axes.labelcolor": INK_2,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": GRID,
    "grid.linewidth": 0.6, "axes.axisbelow": True, "xtick.color": MUTED, "ytick.color": MUTED,
    "text.color": INK, "legend.frameon": False, "savefig.facecolor": "white", "axes.facecolor": "white",
    "svg.hashsalt": "nilegate", "lines.linewidth": 2})
M = FuncFormatter(lambda v, _: f"{v / 1e6:,.0f} M")
M1 = FuncFormatter(lambda v, _: f"{v / 1e6:,.1f} M")


def place_labels(ax, points: list[tuple[float, float, str]]) -> None:
    """Direct labels without collisions: each label takes the first candidate offset whose box overlaps no other
    label and no axes edge (greedy, in the order given — put the most important point first)."""
    fig = ax.figure
    fig.canvas.draw()
    taken, frame = [], ax.get_window_extent()
    cands = [(9, 4), (9, -24), (-9, 4), (-9, -24), (9, 22), (-9, 22), (9, -42), (-9, -42), (24, 40), (-24, 40),
             (24, -58), (-24, -58)]
    for x, y, text in points:
        for dx, dy in cands:
            t = ax.annotate(text, (x, y), xytext=(dx, dy), textcoords="offset points", fontsize=9, color=INK_2,
                            ha="left" if dx > 0 else "right",
                            arrowprops=None if (dx, dy) == cands[0] else {"arrowstyle": "-", "color": MUTED, "lw": 0.6,
                                                                          "shrinkA": 0, "shrinkB": 5})
            # the text box only (Annotation's own extent includes its leader line)
            renderer = fig.canvas.get_renderer()
            t.update_positions(renderer)
            bb = Text.get_window_extent(t, renderer).expanded(1.04, 1.1)
            inside = frame.x0 <= bb.x0 and bb.x1 <= frame.x1 and frame.y0 <= bb.y0 and bb.y1 <= frame.y1
            if inside and not any(bb.overlaps(o) for o in taken):
                taken.append(bb)
                break
            t.remove()
        else:
            raise AssertionError(f"no free place for the label {text!r}")


def save(fig, name: str) -> Path:
    path = OUT / f"{name}.png"
    fig.tight_layout()
    fig.savefig(path, dpi=DPI, bbox_inches=None, metadata={"Software": None})
    plt.close(fig)
    return path


def mfmt(v: float, nd: int = 1) -> str:
    return f"{v / 1e6:,.{nd}f} M"


# %% Phase 1 — Inputs
N = json.loads((SRC / "numbers.json").read_text(encoding="utf-8"))
wk = pd.read_csv(SRC / "weekly.csv")
cu = pd.read_csv(SRC / "customers.csv")
cat = pd.read_csv(SRC / "categories.csv")
a90 = pd.read_csv(SRC / "ar90_by_customer.csv")
coh = pd.read_csv(SRC / "cohorts.csv")
aging = pd.read_csv(SRC / "aging_w52_by_customer.csv")
pay = pd.read_csv(SRC / "payments_asof.csv")
OUT.mkdir(parents=True, exist_ok=True)
assert len(wk) == 52 and len(cu) == 40 and len(cat) == 13 and len(coh) == 12
print("inputs:", {"weekly": len(wk), "customers": len(cu), "categories": len(cat), "ar90 rows": len(a90),
                  "aging customers": len(aging), "payments": len(pay)})
print("✅ Phase 1 validation passed: the analysis outputs are present with their expected shapes")
made: dict[str, dict] = {}                      # chart → the numbers it draws (checked in Phase 5)


# %% Phase 2 — Revenue and budget charts
# V2: rolling 13-week billed vs budget inside the noise band of a 13-week sum (F1, F3)
r = wk[wk.report_week >= 13]
fig, ax = plt.subplots(figsize=FULL)
ax.fill_between(r.report_week, r.band_lo, r.band_hi, color="#CDE2FB", lw=0, label="Noise band (±2σ, no trend)")
ax.plot(r.report_week, r.budget_13w, color=GREY, label="Budget, rolling 13 weeks")
ax.plot(r.report_week, r.billed_13w, color=BLUE, label="Billed, rolling 13 weeks")
for s, c in ((r.billed_13w, INK), (r.budget_13w, INK_2)):
    ax.annotate(mfmt(s.iloc[-1]), (52, s.iloc[-1]), xytext=(6, 0), textcoords="offset points", va="center",
                color=c, fontsize=10)
ax.yaxis.set_major_formatter(M)
ax.set_xlim(13, 55.5)
ax.set_ylim(0, max(r.budget_13w.max(), r.band_hi.max()) * 1.12)
ax.set_xlabel("Report week (2025; rolling windows start at week 13)")
ax.legend(loc="lower left", ncols=3)
made["V2_rolling_revenue"] = {"billed_13w_w52": float(r.billed_13w.iloc[-1]), "band_mid": float(r.band_lo.iloc[0] + r.band_hi.iloc[0]) / 2}
save(fig, "V2_rolling_revenue")

# V3: budget → actual waterfall (F2). Totals grey; a gain blue, a loss red (polarity); every step labelled.
f2 = N["F2"]
steps = [("Budget 2025", N["year"]["budget"], "total"), (f"Volume\n({f2['invoices']:,} vs {f2['plan_invoices']:,} transits)", f2["volume_effect"], "step"),
         ("Ballast pricing\n(budget priced all laden)", f2["ballast_effect"], "step"),
         ("Other ticket / tonnage", f2["other_ticket_effect"], "step"), ("Billed 2025", N["year"]["billed"], "total")]
fig, ax = plt.subplots(figsize=FULL)
level = 0.0
for i, (label, v, kind) in enumerate(steps):
    if kind == "total":
        ax.bar(i, v, color=GREY, width=0.6, edgecolor="white", linewidth=2)
        ax.annotate(mfmt(v), (i, v), xytext=(0, 4), textcoords="offset points", ha="center", va="bottom", fontsize=11)
        level = v
    else:
        bottom = level if v >= 0 else level + v
        ax.bar(i, abs(v), bottom=bottom, color=BLUE if v >= 0 else RED, width=0.6, edgecolor="white", linewidth=2)
        ax.annotate(f"{v / 1e6:+,.2f} M", (i, max(level, level + v)), xytext=(0, 4), textcoords="offset points",
                    ha="center", va="bottom", fontsize=11)
        ax.plot([i - 0.7, i + 0.3], [level, level], color=MUTED, lw=0.8, ls=":")
        level += v
ax.set_xticks(range(len(steps)), [s[0] for s in steps])
ax.yaxis.set_major_formatter(M)
ax.set_ylim(0, N["year"]["budget"] * 1.12)
ax.grid(axis="x", visible=False)
made["V3_budget_waterfall"] = {"end": level, "billed": N["year"]["billed"]}
save(fig, "V3_budget_waterfall")

# V4: per category, the gap split into volume and ticket effects (F2); categories sorted by their total gap
c4 = cat.sort_values("variance", ascending=False).reset_index(drop=True)
fig, ax = plt.subplots(figsize=FULL)
y = np.arange(len(c4))
h = 0.38
ax.barh(y + h / 2, c4.volume_effect, height=h, color=BLUE, edgecolor="white", linewidth=1, label="Volume effect (transits vs plan)")
ax.barh(y - h / 2, c4.ticket_effect, height=h, color=ORANGE, edgecolor="white", linewidth=1, label="Ticket effect (SDR per transit vs plan)")
ax.axvline(0, color=MUTED, lw=0.8)
short = {"Chemical Tankers & Other Liquid Bulk Tankers": "Chemical / liquid bulk tankers",
         "General Cargo / Multi-Purpose / Heavy Lift Vessels": "General cargo / heavy lift",
         "Liquefied Natural Gas (LNG) Carriers": "LNG carriers", "Liquefied Petroleum Gas (LPG) Carriers": "LPG carriers",
         "Roll-On/Roll-Off (Ro/Ro) Vessels": "Ro/Ro vessels"}
ax.set_yticks(y, [f"{short.get(c, c)}  ({v / 1e6:+.1f} M)" for c, v in zip(c4.vessel_category, c4.variance)])
ax.xaxis.set_major_formatter(M)
ax.grid(axis="y", visible=False)
ax.legend(loc="upper right")
ax.set_xlabel("Contribution to the gap vs budget, SDR (category total in brackets)")
made["V4_category_split"] = {"sum": float(c4.volume_effect.sum() + c4.ticket_effect.sum()), "gap": f2["gap"]}
fig.tight_layout()
save(fig, "V4_category_split")
print("V2, V3, V4 drawn; waterfall end", f"{level:,.2f}")
print("✅ Phase 2 validation passed: the waterfall ends on billed 2025; the category split sums to the gap")


# %% Phase 3 — Customer and credit charts
# V5: risk matrix — revenue share (x) × mean days paid after due (y), bubble area = AR at week 52, colour = rating
v5 = cu.dropna(subset=["late_mean"])
fig, ax = plt.subplots(figsize=FULL)
xm, ym = cu.revenue_share.median(), 10
ax.axvline(xm, color=MUTED, lw=0.8, ls="--")
ax.axhline(ym, color=MUTED, lw=0.8, ls="--")
ax.axhline(0, color=GRID, lw=0.8)
for rating in "ABC":
    d = v5[v5.credit_rating == rating]
    ax.scatter(d.revenue_share, d.late_mean, s=30 + d.ar / 2.5e4, color=RATING_COLOUR[rating], alpha=0.85,
               edgecolor="white", linewidth=2, label=f"Rating {rating}")
label_ids = set(cu.nlargest(1, "revenue").customer_id) | set(cu.nlargest(5, "overdue").customer_id) \
    | set(cu[(cu.revenue_share >= xm) & (cu.late_mean >= ym)].customer_id)
ax.text(cu.revenue_share.max(), ym + 1, "late payers ↑", ha="right", fontsize=9, color=MUTED)
ax.text(xm + 0.15, v5.late_mean.max() + 8, "larger customers →", fontsize=9, color=MUTED)
ax.xaxis.set_major_formatter(PercentFormatter(decimals=0))
ax.set_xlabel("Share of 2025 revenue")
ax.set_ylabel("Mean days paid after due date")
ax.set_ylim(v5.late_mean.min() - 6, v5.late_mean.max() + 12)
leg = ax.legend(loc="upper right", ncols=3, title="Bubble size = receivables at week 52", title_fontsize=9)
for hnd in leg.legend_handles:
    hnd.set_sizes([60])
lab = v5[v5.customer_id.isin(label_ids)].sort_values("ar", ascending=False)
place_labels(ax, [(c.revenue_share, c.late_mean, f"{c.customer_name} · AR {mfmt(c.ar)}") for c in lab.itertuples()])
made["V5_customer_risk"] = {"customers": len(v5), "top": cu.iloc[0].customer_name}
save(fig, "V5_customer_risk")


# V6: revenue / AR / overdue share by rating and by segment (F5)
def shares(by: str, order: list[str], name: str, size) -> dict:
    g = cu.groupby(by)[["revenue_share", "ar_share", "overdue_share"]].sum().reindex(order)
    fig, ax = plt.subplots(figsize=size)
    x, w = np.arange(len(g)), 0.26
    for k, (col, lab, colour) in enumerate((("revenue_share", "Revenue 2025", BLUE),
                                            ("ar_share", "Receivables wk 52", ORANGE),
                                            ("overdue_share", "Overdue wk 52", AQUA))):
        bars = ax.bar(x + (k - 1) * w, g[col], width=w, color=colour, edgecolor="white", linewidth=2, label=lab)
        ax.bar_label(bars, labels=[f"{v:.0f}%" for v in g[col]], fontsize=9, padding=2, color=INK_2)
    ax.set_xticks(x, [f"Rating {i}" if by == "credit_rating" else i.capitalize() for i in g.index])
    ax.yaxis.set_major_formatter(PercentFormatter(decimals=0))
    ax.set_ylim(0, g.values.max() * 1.18)
    ax.grid(axis="x", visible=False)
    ax.legend(loc="upper left", ncols=3 if by != "credit_rating" else 1)
    save(fig, name)
    return g.round(1).to_dict("index")


made["V6_rating_shares"] = shares("credit_rating", ["A", "B", "C"], "V6_rating_shares", HALF)
seg_order = cu.groupby("segment").revenue_share.sum().sort_values(ascending=False).index.tolist()
made["V6b_segment_shares"] = shares("segment", seg_order, "V6b_segment_shares", FULL)   # 6 groups need the width

# V11: Pareto — customer revenue share by rank and the cumulative share, one percent axis
fig, ax = plt.subplots(figsize=FULL)
rank = np.arange(1, len(cu) + 1)
ax.bar(rank, cu.revenue_share, color=BLUE, edgecolor="white", linewidth=1, label="Revenue share")
ax.plot(rank, cu.cum_revenue_share, color=ORANGE, marker="o", markersize=4, label="Cumulative share")
ax.axhline(80, color=MUTED, lw=0.8, ls="--")
n80 = N["F12"]["customers_for_80pct"]
ax.annotate(f"{n80} customers = 80 %", (n80, cu.cum_revenue_share.iloc[n80 - 1]), xytext=(10, -22),
            textcoords="offset points", fontsize=10, color=INK_2)
ax.annotate(f"#1 {cu.customer_name.iloc[0]}: {cu.revenue_share.iloc[0]:.1f} %", (1, cu.revenue_share.iloc[0]),
            xytext=(12, 4), textcoords="offset points", fontsize=10, color=INK_2)
ax.yaxis.set_major_formatter(PercentFormatter(decimals=0))
ax.set_ylim(0, 105)
ax.set_xlabel("Customers ranked by 2025 revenue")
ax.set_xlim(0.3, len(cu) + 0.7)
ax.grid(axis="x", visible=False)
ax.legend(loc="center right")
made["V11_pareto"] = {"top1": float(cu.revenue_share.iloc[0]), "n80": n80}
save(fig, "V11_pareto")

# V13: days paid after due by rating — the distribution, not just the mean
fig, ax = plt.subplots(figsize=HALF)
data = [pay[pay.credit_rating == k].late_days for k in "ABC"]
rng = np.random.default_rng(42)
for i, d in enumerate(data, start=1):
    ax.scatter(i + rng.uniform(-0.18, 0.18, len(d)), d, s=6, color=BLUE, alpha=0.25, lw=0)
ax.boxplot(data, positions=[1, 2, 3], widths=0.5, showfliers=False,
           medianprops={"color": INK, "lw": 2}, boxprops={"color": INK_2}, whiskerprops={"color": INK_2},
           capprops={"color": INK_2})
for i, d in enumerate(data, start=1):
    ax.annotate(f"median {d.median():+.0f} d", (i, d.max()), xytext=(0, 6), textcoords="offset points",
                ha="center", va="bottom", fontsize=10, color=INK)          # above the points, clear of the box
ax.axhline(0, color=MUTED, lw=0.8, ls="--")
ax.set_xticks([1, 2, 3], ["Rating A", "Rating B", "Rating C"])
ax.set_ylabel("Days paid after due date (≤ 0 = on time)")
ax.grid(axis="x", visible=False)
made["V13_days_late"] = {k: float(d.median()) for k, d in zip("ABC", data)}
save(fig, "V13_days_late")
print("V5, V6, V6b, V11, V13 drawn; rating shares", made["V6_rating_shares"]["C"])
print("✅ Phase 3 validation passed: customer and credit charts drawn from customers.csv / payments_asof.csv")


# %% Phase 4 — Receivables charts
# V7: aging heatmap at week 52 — the 10 customers with the most overdue, amount per bucket (one blue ramp)
buckets = ["current", "1-30", "31-60", "61-90", "90+"]
ag = aging.copy()
for b in buckets:
    if b not in ag:
        ag[b] = 0.0
ag["overdue"] = ag[buckets[1:]].sum(axis=1)
ag = ag.nlargest(10, "overdue").reset_index(drop=True)
mat = ag[buckets].to_numpy() / 1e6
fig, ax = plt.subplots(figsize=FULL)
cmap = LinearSegmentedColormap.from_list("blue", BLUE_RAMP)
ax.imshow(mat, cmap=cmap, aspect="auto", vmin=0, vmax=mat.max())
for i in range(mat.shape[0]):
    for j in range(mat.shape[1]):
        v = mat[i, j]
        ax.text(j, i, "–" if v == 0 else f"{v:.2f}", ha="center", va="center", fontsize=10,
                color="white" if v > mat.max() * 0.55 else INK)
ax.set_xticks(range(len(buckets)), ["Current (not due)", "1–30 days", "31–60 days", "61–90 days", "90+ days"])
ax.set_yticks(range(len(ag)), [f"{n} ({r})" for n, r in zip(ag.customer_name, ag.credit_rating)])
ax.tick_params(length=0)
ax.grid(False)
for s in ax.spines.values():
    s.set_visible(False)
ax.set_xlabel("Receivables at week 52 by days past due, M SDR (rating in brackets)")
made["V7_aging_heatmap"] = {"overdue_top10": float(ag.overdue.sum())}
fig.tight_layout()
save(fig, "V7_aging_heatmap")

# V8: the 90+ bucket by week, stacked by customer (F7)
p = a90.pivot_table(index="report_week", columns="customer_name", values="amount_sdr", aggfunc="sum").fillna(0.0)
p = p.reindex(range(int(p.index.min()), 53), fill_value=0.0)
holder = N["F7"]["holder"]["name"]
order = [holder] + sorted(c for c in p.columns if c != holder)
fig, ax = plt.subplots(figsize=FULL)
bottom = np.zeros(len(p))
for k, c in enumerate(order):
    ax.bar(p.index, p[c], bottom=bottom, width=0.8, color=[BLUE, ORANGE, AQUA][k], edgecolor="white", linewidth=1,
           # facts only: "unpaid at the horizon" is measured; "dispute" would be an inference (review 2026-10-31)
           label=c + (f" (unpaid at {N['meta']['payments_horizon']})" if c == holder else " (paid later)"))
    bottom += p[c].to_numpy()
ax.annotate(f"{mfmt(bottom[-1], 2)} at week 52", (52, bottom[-1]), xytext=(-10, 8), textcoords="offset points",
            ha="right", fontsize=10, color=INK)
ax.yaxis.set_major_formatter(M1)
ax.set_ylim(0, p.sum(axis=1).max() * 1.3)          # head room for the legend above the week-24 peak
ax.set_xlabel("Report week (2025)")
ax.set_ylabel("Receivables more than 90 days past due")
ax.grid(axis="x", visible=False)
ax.legend(loc="upper left", ncols=3)
made["V8_ar90_buildup"] = {"w52": float(bottom[-1])}
save(fig, "V8_ar90_buildup")

# V9: DSO split — best-possible (terms) + delinquency, weeks 14–52 (M12, F8)
d = wk[wk.report_week > 13]
fig, ax = plt.subplots(figsize=HALF)
ax.stackplot(d.report_week, d.dso_best, d.dso_delinquency, colors=[GREY, ORANGE],
             labels=["Terms (best possible)", "Delinquency (paid late)"], edgecolor="white", linewidth=1)
ax.plot(d.report_week, d.dso_days, color=INK, lw=1, label="DSO")
last = d.iloc[-1]
ax.annotate(f"{last.dso_best:.0f} d", (52, last.dso_best / 2), xytext=(4, 0), textcoords="offset points",
            va="center", fontsize=10)
ax.annotate(f"{last.dso_delinquency:.0f} d", (52, last.dso_best + last.dso_delinquency / 2), xytext=(4, 0),
            textcoords="offset points", va="center", fontsize=10)
ax.set_xlim(14, 55)
ax.set_ylim(0, d.dso_days.max() * 1.25)
ax.set_xlabel("Report week (2025, after warm-up)")
ax.set_ylabel("Days")
ax.legend(loc="upper left", ncols=2, fontsize=9)
made["V9_dso_split"] = {"best": float(last.dso_best), "delinquency": float(last.dso_delinquency)}
save(fig, "V9_dso_split")

# V10: collection scenario — DSO after collecting the overdue of the N largest overdue customers (arithmetic)
sc = N["F9"]["scenarios"]
fig, ax = plt.subplots(figsize=HALF)
labels = ["Today" if s["label"] == "current" else ("All overdue" if s["label"] == "all" else f"Top {s['label'][3:]}")
          for s in sc]
bars = ax.bar(range(len(sc)), [s["dso"] for s in sc], color=[GREY] + [BLUE] * (len(sc) - 1), width=0.6,
              edgecolor="white", linewidth=2)
ax.bar_label(bars, labels=[f"{s['dso']:.1f} d" + ("" if s["released"] == 0 else f"\n−{mfmt(s['released'])}")
                           for s in sc], fontsize=9, padding=2)
ax.axhline(N["F8"]["best_w52"], color=MUTED, lw=0.8, ls="--")
ax.set_xlim(-0.5, len(sc) + 0.5)
ax.text(len(sc) - 0.45, N["F8"]["best_w52"] + 1, f"terms floor\n{N['F8']['best_w52']:.1f} d", ha="left",
        fontsize=9, color=MUTED)
ax.set_xticks(range(len(sc)), labels)
ax.set_ylabel("DSO at week 52, days")
ax.set_ylim(0, 70)
ax.set_xlabel("Overdue collected from the N largest overdue customers")
ax.grid(axis="x", visible=False)
made["V10_scenario"] = {"dso": [s["dso"] for s in sc]}
save(fig, "V10_scenario")

# V12: invoice-month cohorts — matured months solid, months not yet matured at the as-of date marked
fig, ax = plt.subplots(figsize=FULL)
mat_ = coh[coh.mature]
imm = coh[~coh.mature]
for col, colour, lab in (("within30_pct", BLUE, "Paid within 30 days after due"),
                         ("ontime_pct", ORANGE, "Paid on or before due")):
    ax.plot(mat_.month, mat_[col], color=colour, marker="o", markersize=5, label=lab)
    ax.plot(imm.month, imm[col], color=colour, ls=":", marker="o", markersize=5, markerfacecolor="white")
    ax.annotate(f"{mat_[col].min():.0f}–{mat_[col].max():.0f} %", (mat_.month.iloc[-1], mat_[col].iloc[-1]),
                xytext=(8, 8), textcoords="offset points", fontsize=10, color=INK_2)
ax.axvspan(imm.month.min() - 0.5, 12.5, color="#F5F4F0", lw=0)
ax.text(imm.month.mean(), 95, "not matured at 28 Dec\n(not comparable)", ha="center", fontsize=9, color=MUTED)
ax.set_xticks(range(1, 13), ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])
ax.yaxis.set_major_formatter(PercentFormatter(decimals=0))
ax.set_ylim(0, 105)
ax.set_xlabel("Invoice month (2025)")
ax.legend(loc="lower left")
made["V12_cohorts"] = {"mature": mat_.month.tolist()}
save(fig, "V12_cohorts")
print("V7, V8, V9, V10, V12 drawn; 90+ week 52", f"{bottom[-1]:,.2f}")
print("✅ Phase 4 validation passed: receivables charts drawn from weekly / ar90 / aging / cohorts")


# %% Phase 5 — Validation: files, sizes, and the drawn numbers against numbers.json
EXPECTED = {"V2_rolling_revenue": FULL, "V3_budget_waterfall": FULL, "V4_category_split": FULL,
            "V5_customer_risk": FULL, "V6_rating_shares": HALF, "V6b_segment_shares": FULL, "V11_pareto": FULL,
            "V13_days_late": HALF, "V7_aging_heatmap": FULL, "V8_ar90_buildup": FULL, "V9_dso_split": HALF,
            "V10_scenario": HALF, "V12_cohorts": FULL}
assert set(made) == set(EXPECTED), set(made) ^ set(EXPECTED)
for name, size in EXPECTED.items():
    im = plt.imread(OUT / f"{name}.png")
    assert im.shape[:2] == (round(size[1] * DPI), round(size[0] * DPI)), (name, im.shape)
assert abs(made["V3_budget_waterfall"]["end"] - N["year"]["billed"]) < 0.05
assert abs(made["V4_category_split"]["sum"] - N["F2"]["gap"]) < 0.05
assert abs(made["V8_ar90_buildup"]["w52"] - N["year"]["ar90_w52"]) < 0.05
assert round(made["V9_dso_split"]["best"], 1) == N["F8"]["best_w52"]
assert made["V10_scenario"]["dso"] == [s["dso"] for s in N["F9"]["scenarios"]]
assert made["V12_cohorts"]["mature"] == N["F10"]["mature_months"]
by_rating = {d["credit_rating"]: d for d in N["F5"]["by_rating"]}
assert all(abs(made["V6_rating_shares"][k]["overdue_share"] - by_rating[k]["overdue_share"]) < 0.051 for k in "ABC")
assert {k: round(v, 1) for k, v in made["V13_days_late"].items()} == {d["credit_rating"]: d["late_median"] for d in N["F5"]["by_rating"]}
print("charts:", len(EXPECTED), "→", OUT.relative_to(ROOT))
print("✅ Phase 5 validation passed: 13 charts at their slide sizes; drawn totals equal numbers.json")


# %% Final Checkpoint
# Narrative: pipelines/checkpoints/finance/Executive_charts.md (the owner's visual review of each chart is recorded there)
summary = {"charts": len(EXPECTED), "waterfall_end": round(made["V3_budget_waterfall"]["end"], 2),
           "ar90_w52": round(made["V8_ar90_buildup"]["w52"], 2), "dso_scenarios": made["V10_scenario"]["dso"]}
REVIEWED = {"charts": 13, "waterfall_end": 267892000.68, "ar90_w52": 1286102.15,
            "dso_scenarios": [55.0, 48.1, 45.5, 41.8, 40.0]}
print("Final Checkpoint:", summary)
assert summary == REVIEWED, summary
print("✅ Final Checkpoint passed: the charts draw the reviewed numbers")
