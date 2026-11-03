---
name: deck-style-guide
description: The structure and writing style of the weekly finance PowerPoint pack (English, 10 slides, SDR): what code draws and what the Writer writes on each slide, number slots, titles, tone and the evidence each slide may cite.
stage: 1
reviewed_by_owner: 2026-11-02
---
# Weekly finance pack — deck style guide

Code draws every tile, table, chart and footnote, and slides 1 and 10. You write the slide titles and the bullets,
every number as a **slot** ("Numbers"). The Validator checks your words (V9), your numbers, then the file.

## Slides (in this order)
| Slide | Code draws | You write | You may cite |
|---|---|---|---|
| 1 Title | week, dates, the approval badge | deck title; slide 1 title = the week and the period in one line | `kpi.weekly` |
| 2 Summary | "week at a glance": billed WoW vs its typical swing, the period vs budget, overdue new / paid, DSO terms + late | exactly 5 bullets (`weekly-variance-analysis`) | every result |
| 3 KPI tiles | six tiles, each WoW with "typical ±x %" | ≤ 3 comments | `kpi.weekly` |
| 4 Revenue | 13-week billed vs budget; the period line; drivers with invoices this / last week | ≤ 3 | `kpi.trend`, `kpi.category`, `kpi.weekly`, `audit.week` |
| 5 Off plan | billed − budget bars per category; the budget-miss table | ≤ 3 | `kpi.category` |
| 6 Receivables | aging; overdue roll-forward; DSO terms / late; due this week collected; largest overdue | ≤ 3 | `kpi.weekly`, `kpi.overdue`, `kpi.trend` |
| 7 Customers | top 10: rating, AR, overdue, AR / 13-week billing, watch; top-10 share | ≤ 3: who moved, who is on the watchlist | `kpi.customers`, `kpi.weekly` |
| 8 Exceptions | findings + actions; with none, "N checked, none flagged" + the year's findings | ≤ 3 | `audit.week`, `audit.ytd` |
| 9 Context | Suez transits chart (when fetched) | ≤ 3 lines: transits, news (title, source, date), a tariff rule; or "External context unavailable" | Insight results only |
| 10 Appendix | sources, filters, freshness | — | — |

## Titles and claims (V9 refuses the rest)
- A title states the finding: "Receivables up 6.1 %", not "Receivables".
- "Stable", "steady", "flat" only when the week's change is under 2 % (DSO: 1 day).
- "Consistent", "sustained", "continued" only when the 13 weeks agree (`budget_variance_13w_pct` with the week; a
  level moving the same way two weeks running); else write the week and the period apart: "Above budget this week,
  below it over the year so far".
- A move inside its typical swing (`*_wow_typical_pct`) is "within its normal swing", never a pullback, surge or
  sharp move; a direction word must match the week's sign.
- No external cause (Red Sea, disruptions, markets) on slides 1–8: context is slide 9's and never explains a NileGate
  figure.
- A comment adds what the tiles do not show (a driver, a customer, a finding, the period); never repeat a tile.
- Short active sentences, one spelling per deck, no forecasts or advice beyond the audit's actions.

## Numbers: slots
Never type a NileGate number. Code writes the value, its sign and unit (`number-validation`):
- one-row results and totals: {kpi.weekly:billed_sdr|M} → "8.39 M SDR"; {audit.week:invoices_checked} → "19";
- lists, the row by its key: {kpi.category[Cruise Ships]:billed_wow_change_sdr|M} → "−1.07 M SDR";
- formats: money M, k or as returned; percent %1 or %2; days and counts none;
- a change is always signed; "|dir" writes "down 1.07 M SDR"; never repeat a slot's unit or direction.
A null cannot be a slot: write "not available" or "new". Name what a number is (billed, AR, budget …) and its
category, customer or invoice before it. Week and year may be digits; counts you write go in words.

## Footnotes (code)
Warm-up weeks 1–13: code writes "Receivables still building up since 1 Jan 2025" and "weeks 1–w" for the period.
