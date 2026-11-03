# Weekly pack storyboard — the improved NileGate Weekly Finance Pack

Status: **storyboard, rewritten 2026-10-31** for the weekly pack the agent produces every week (the file name is
kept from the earlier study). PROPOSED; implementation after the Stage 1 c4 evaluation (`implementation_roadmap.md`).
Still 10 slides (the Validator's deck shape V4 and the evaluation's slide checks stay valid); code draws every number,
the Writer writes titles, bullets and comments with slots. The example titles are for **W12** (2025-03-17 … 23) and
are written the way the new claim check would accept them; their overdue-flow figures follow the validated
roll-forward (W6, residual 0) — the final values come from the view columns.

## Narrative of one week

1. **What happened this week** — billing, collections, receivables, each against its normal swing.
2. **Where we stand over 13 weeks** — against plan, so one week is read in context.
3. **Why** — the drivers (with how many invoices), the overdue flows.
4. **Who** — the customers carrying receivables risk; the overdue owners.
5. **What to do** — audit corrections, watchlist customers to chase.
6. **Outside** — external context, apart from NileGate numbers.

## Slides

### S1 — Cover
- **Code:** brand, week, dates, status badge (smaller), "Amounts in SDR".
- **Writer title (W12 example):** "Week 12: billing 9.8 % above its weekly budget; the year so far 3.7 % short" — the
  week and the period in one line, no external cause (before week 13 the "period" is weeks 1 … w).

### S2 — Executive summary
- **Code:** "week at a glance" strip — billed vs typical swing, 13-week vs budget, overdue change (new / paid), DSO
  (terms + delinquency).
- **Writer:** exactly 5 bullets (skill `weekly-variance-analysis`): headline billing with its swing, the 13-week
  position, the top driver with its invoice count, receivables (overdue flow + watchlist), one audit / context line.
- **Title (W12):** "A normal week for billing; overdue up 1.5 M as new invoices fell due".

### S3 — KPI tiles
- **Code:** the six tiles; under each WoW a muted "typical ±x %"; warm-up footnote.
- **Writer:** ≤ 3 comments that add something (never a tile restated — V9).
- **Title (W12):** "Billing −4.9 % WoW is within the typical ±10.4 % swing; receivables up 6.1 %".

### S4 — Revenue against plan
- **Code:** 13-week line billed vs budget (week marked) + the line "13 weeks: billed x M vs budget y M (z %)"; drivers
  table with invoices this / last week; audit flag column.
- **Title (W12):** "Above budget this week, 3.7 % below it over the year so far".

### S5 — Where we are off plan (categories)
- **Code:** variance bars per category (diverging, sorted, short names); budget-miss table (M9a, c4).
- **Title (W12):** "Dry bulk and LPG billed most above budget; product tankers furthest below".

### S6 — Receivables: why overdue moved
- **Code:** aging columns; DSO tile with terms / delinquency; overdue roll-forward (opening → newly overdue → paid →
  closing); "due this week collected x %"; top overdue customers (customer, rating, overdue, oldest bucket).
- **Title (W12):** "Overdue rose 1.5 M: 2.6 M fell due unpaid, 1.1 M of older overdue was collected".

### S7 — Customers and receivables risk
- **Code:** top-10 by 13-week billing with rating, AR, overdue, AR / 13-week billing and a "watch" marker at the
  owner's threshold; top-10 share tile.
- **Writer:** who entered / left the top 10; who is on the watchlist.
- **Title (W12):** "Belanor Tankers owes 95 % of what it billed in 13 weeks".

### S8 — Exceptions
- **Code:** findings tiles + table when there are findings; otherwise one line ("24 checked, none flagged") and the
  year-to-date findings list with their status.
- **Title (W12):** "No new billing errors; the week-10 duplicate charge stays on the year's list" (the data holds no
  correction status, so the pack cannot say "still open").

### S9 — External context
- **Code:** daily Suez transits, the week vs the 4 weeks before (mini line chart); news list (title, source, date);
  "External context: public data and news, not NileGate figures".
- **Writer:** ≤ 3 lines; never a cause of a NileGate number.

### S10 — Appendix: data sources
- **Code:** unchanged content, smaller, titled as an appendix.

## Title rules the claim check (V9) enforces

| Rule | Example refused | Example accepted |
|---|---|---|
| A direction / stability word agrees with the signs of the slide's own evidence | "Stable receivables" with AR +6.1 % | "Receivables up 6.1 %" |
| "Consistent", "sustained", "persistent" need the 13-week evidence to agree | "Consistent outperformance" (7 of 12 weeks, −3.7 %) | "Above budget this week, below it over 13 weeks" |
| A within-swing move is not called a rise / fall headline | "Billing pullback" at −4.9 % (swing ±10.4 %) | "Billing within its normal swing" |
| No external cause attached to a NileGate number | "… amid Red Sea disruptions" on the cover | context only on S9 |
| A comment must add a fact not on the slide's tiles / table | "A total of 0 invoices were flagged" | "The week-10 duplicate (81.8 k) is the only finding this year" |
