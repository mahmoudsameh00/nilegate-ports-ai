# Final Checkpoint — Executive_charts (executive financial-intelligence deck, Phase B, 2026-10-31)

**What it proves:** the 13 charts of the executive deck (V2–V13 of
`docs/analysis/financial_intelligence/visualization_recommendations.md`) are drawn from the Executive_analysis outputs
only, at their slide sizes, and the totals they draw equal `numbers.json`. Output:
`Data/processed/finance/executive_2025/charts/*.png` (200 dpi; full width 12.0 × 4.6 in, half 5.9 × 4.6 in).

| Phase | Step | Result |
|---|---|---|
| 1 | Read `numbers.json` + 7 CSV series | 52 weeks, 40 customers, 13 categories, 12 cohorts, 842 payments |
| 2 | V2 rolling band, V3 waterfall, V4 category split | waterfall ends on 267,892,000.68; the split sums to the −34.21 M gap |
| 3 | V5 risk matrix, V6 / V6b shares, V11 Pareto, V13 days late | shares and medians equal `numbers.json` F5 |
| 4 | V7 heatmap, V8 90+, V9 DSO split, V10 scenario, V12 cohorts | 90+ week 52 = 1,286,102.15; DSO split 40.0 + 15.0; scenarios 55.0 → 40.0 |
| 5 | Files, pixel sizes, drawn numbers | 13 / 13 |
| Final | Reviewed snapshot | equal; a second run reports `files changed: 0` (deterministic PNGs) |

Colour: the dataviz method on the deck's own colours (`pipelines/agents/deck/style.py`): categorical blue / orange /
aqua (validator: all checks pass on white; aqua below 3:1 contrast → every aqua mark is labelled), grey for the budget
and totals, blue ↔ red polarity for the waterfall (pass), one blue ramp for the heatmap. One y-axis per chart (the
Pareto's bars and cumulative line share the percent axis).

## Problems and fixes (found by looking at every rendered chart)
- **Label collisions on the risk matrix (V5):** five customers sit around 3–4 % revenue and 28–30 days late. Fixed with
  a greedy label placer (`place_labels`): candidate offsets, the first free one wins, leader lines for moved labels,
  an assert when no place is free. Two bugs on the way: matplotlib's `Annotation` extent includes the leader line
  (labels looked blocked) and the text position is stale until `update_positions` is called.
- **Legends over data:** V4 (bottom left, over the smallest categories) → upper right; V8 (over the week-24 bar, the
  week-52 label cut off) → a 30 % head room and a one-row legend.
- **V10 "terms floor" text over the last bar** → moved to the right of the bars with its value.
- **V6b segment shares cramped** (6 groups × 3 labels in half width: "12%12%") → full width.
- **V13 median labels over the jittered points** → above each group.
- **Top white space** of fixed-size figures → `tight_layout` in `save()` for every chart.
- **Static images:** the method's hover layer does not apply to slide PNGs; values are labelled on the marks instead.
