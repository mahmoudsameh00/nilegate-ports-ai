# Analytical gap assessment — the weekly pack, slide by slide

Status: **analysis document, rewritten 2026-10-31** for the weekly pack (owner's goal: improve the pack the agent
produces every week). Read-only: nothing in the agent, the deck code, the skills or the evaluation was changed — the
Stage 1 c4 evaluation (2026-11-01) compares the current code, so every change waits until after it.
Evidence: W12 viewed in PowerPoint slide by slide; W11 / W12 text; `render.py`, `style.py`, the `deck-style-guide`
and `weekly-variance-analysis` skills; ADR-051; the week-by-week analysis in `advanced_analytics_findings.md` (W1–W9).

## 1. What works and must stay

- **Number integrity:** slots, Validator V1–V8 and the file read-back — every number on W11 / W12 equals
  `kpi_weekly`. Any change keeps this contract (new numbers = new view columns = new slots).
- One template in code (`style.py`), native charts with exact values, approval before publishing, sources slide,
  warm-up footnote, external context kept on its own slide, the c4 fallback and budget-miss table.

## 2. Gaps

Priority: **P1** = the pack misleads or misses the main risk; **P2** = the reader cannot judge a number; **P3** =
look / polish.

### Content and analysis

| # | Gap | Slide | Evidence | Priority |
|---|---|---|---|---|
| C1 | **Customer receivables risk not shown** although it is in the evidence (`kpi.customers` has AR, overdue, rating): the #1 customer's AR ≈ 95 % of its own 13-week billing at W12 | 7 | W4 | P1 |
| C2 | **Titles and summary over-claim** ("Consistent Outperformance", "Stable Receivables", "Revenue Mix Growth"; external cause on the cover); the Validator checks numbers, not claims | 1, 2, 4, 5 | W9 | P1 |
| C3 | **No yardstick for weekly moves**: WoW tiles and drivers without the typical swing; week vs budget without the 13-week position | 3, 4 | W1, W2 | P1 |
| C4 | **Overdue unexplained**: one total and its WoW; no roll-forward (newly overdue vs paid), no "due this week collected" rate, no customer concentration (top 5 hold ~72 % of overdue) | 6 | W5, W6 | P2 |
| C5 | **DSO without its split** (terms vs delinquency, M12) | 6 | W7 | P2 |
| C6 | **Drivers without their invoice counts** (median 4 invoices; 19 % two or fewer) | 4 | W3 | P2 |
| C7 | **Comments repeat tiles** instead of adding something (skill rule "never repeat a tile" not enforced): slide 3, slide 6, slide 8 (three sentences restating 24 / 0 / 0.00) | 3, 6, 8 | W12 deck | P2 |
| C8 | **Empty audit slide 49 weeks of 52**: a full slide of zeros | 8 | 3 findings in the year | P2 |
| C9 | **Context slide is text only**; the skill asks for "Suez transits vs previous weeks" but no comparison is drawn; one figure is described two different ways (slide 2 vs 9) | 9 | W12 deck | P3 |
| C10 | Receivables trend unused: `kpi.trend` holds AR / DSO / overdue per week; only billed vs budget is drawn | 4 / 6 | evidence | P3 |

### Look and layout (seen in PowerPoint)

| # | Gap | Slide | Priority |
|---|---|---|---|
| L1 | **Two-line titles collide with content** (slide 7: the title's second line sits on the table header) — the title box is sized for one line | 7 (any long title) | P2 |
| L2 | **Accent rule under every title** (teal line) — reads as template filler; the pptx guidance avoids it | all | P3 |
| L3 | **DSO on slide 6 is loose text** ("DSO 54.2 days +2.6 days WoW") under the chart, not a tile | 6 | P3 |
| L4 | **Large empty areas** (slide 4 under the drivers table, slide 6 right side, slide 8 middle, slide 9) | 4, 6, 8, 9 | P3 |
| L5 | Slide 5: 13 full category names, sorted by billed, legend "Budget · Billed" (budget first); the message is variance, not size | 5 | P3 |
| L6 | Slide 2 and 9 are text only — the executive summary has no visual anchor | 2, 9 | P3 |
| L7 | The "Approved" badge is a large teal button on every slide; it competes with the content | all | P3 |
| L8 | Slide 10 (sources) is a technical audit table in the main flow | 10 | P3 (keep, restyle as an appendix page) |

## 3. Questions a manager asks of a weekly pack that it does not answer

1. Is this week's move normal or unusual? (C3)
2. Where do we stand over the last 13 weeks against the plan? (C3)
3. Who owes us the most relative to what they buy, and is it getting worse? (C1)
4. Why did overdue rise — new overdue or nothing collected? (C4)
5. How much of DSO can we act on? (C5)
6. Are the "drivers" real business or one transit? (C6)

## 4. Prioritised changes (all after c4)

| Priority | Change | Needs |
|---|---|---|
| P1 | Slide 7 → "Customers and receivables risk": AR, overdue, rating and AR / 13-week billing per top customer + a watchlist flag | `kpi.customers` already has AR / overdue / rating; the ratio and flag need a view column (migration 021) |
| P1 | Validator V9 claim check + Writer guidance (skills) for titles; no external cause in NileGate titles | code + skill edits (owner review of skills) |
| P1 | Typical-swing line on WoW tiles; 13-week variance line on slide 4 | view columns (migration 021) |
| P2 | Slide 6: DSO split tile, overdue roll-forward, due-this-week collected rate, top overdue customers | view columns (021) with a pandas reference |
| P2 | Drivers table: invoice counts this / last week | `kpi_weekly_category` previous-week count (021) |
| P2 | Slide 8: compact when no findings, with the year-to-date findings list | `invoice_audit` filtered `report_week ≤ w` — no new data |
| P2 | Comments that only repeat a tile are refused (V9 extension) | code |
| P3 | Layout: title box for two lines, no accent rule, DSO as a tile, smaller approval badge, slide 5 sorted by variance with short names, a Suez transit mini-chart on slide 9 | `style.py`, `render.py` |
