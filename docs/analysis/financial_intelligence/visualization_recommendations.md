# Visualization recommendations — the weekly pack

Status: **analysis document, rewritten 2026-10-31** for the weekly pack. Proposals only; nothing changed (after c4).
Rules that bind every proposal: **native python-pptx charts** drawn by code with the evidence's exact values (ADR-051
P6-4 — V8 reads them back; matplotlib images were rejected there); billed blue, budget grey, one categorical hue per
series (`style.py`, dataviz method); every number a bound value or slot; one message per chart; no chart that a week's
data cannot support (`advanced_analytics_findings.md`, "What a week cannot support").

## 1. Per slide

| Slide | Today | Proposed visual | Fields (view → evidence) | Why this form | Priority |
|---|---|---|---|---|---|
| 2 Summary | 5 bullets | 5 bullets + a **"week at a glance" strip** of four mini-tiles: billed vs typical swing, 13-week vs budget, overdue change split (new / paid), DSO = terms + delinquency | `kpi.weekly` new columns | gives the summary a visual anchor and the yardsticks before the text | P2 |
| 3 KPI tiles | 6 tiles + WoW | same tiles; under each WoW a muted **"typical ±x %"** (13-week median \|WoW\|) | `kpi_weekly.*_wow_typical_pct` (021) | a tile's change becomes readable without a chart | P1 |
| 4 Revenue trend | 13-week line billed vs budget; drivers table | line kept + a code line **"13 weeks: billed x M vs budget y M (z %)"**; drivers table + **invoices (this / last week)** columns | `kpi_weekly.billed_13w_sdr`, `budget_13w_sdr`; `kpi_weekly_category.invoices_prev` (021) | anchors the title in the period; shows when a driver is one transit | P1 |
| 5 Revenue mix | bars billed vs budget, sorted by billed, long names | **variance bars** (billed − budget per category, diverging around zero, sorted by variance), short names; budget-miss table kept | `kpi.category` (existing) | the slide's message is "where are we off plan", not "who is biggest" | P3 |
| 6 Receivables | aging columns; DSO as text; top-5 overdue invoices | aging columns kept; **DSO tile with its split** (terms / delinquency); **overdue roll-forward** (opening → +newly overdue → −paid → closing, a 4-bar waterfall drawn as stacked columns with an invisible base, native); **"due this week collected x %"**; the table becomes **top overdue customers** (customer, rating, overdue, oldest bucket) | `kpi_weekly` M12 + flow columns (021); `kpi.customers` overdue / rating | explains *why* overdue moved and *who* owes it | P2 |
| 7 Customers | top-10 table by 13-week billing + top-10 share tile | **"Customers and receivables risk" table**: rank, customer, rating, 13-week billing, AR, overdue, **AR / 13-week billing** with a flag icon-free marker (bold + "watch") when ≥ the owner's threshold; top-10 share tile kept | `kpi.customers` (AR, overdue, rating exist) + ratio / flag (021) | the main weekly risk in one place, sorted as today so ranks still read | P1 |
| 8 Exceptions | three tiles + table (or "no invoice flagged") | with findings: unchanged; **without findings**: one compact line ("24 invoices checked, none flagged") + the **year-to-date findings list** (week, invoice, check, amount, status) | `invoice_audit` with `report_week ≤ w` | no empty slide; the open corrections stay visible until fixed | P2 |
| 9 Context | three text lines | a **mini line chart of daily Suez transits** (the week vs the 4 weeks before, from `suez_transits`) + news list (title, source, date) | the `suez_transits` result already fetched | the skill's "transits vs previous weeks" made visible; still apart from NileGate numbers | P3 |
| 10 Sources | full-width table | same content, smaller type, titled "Appendix — data sources" | unchanged | an audit trail, not a message | P3 |

## 2. Rejected for a weekly pack

| Candidate | Why not |
|---|---|
| Category trend lines per week | median one invoice per category-week: noise |
| Forecast / next-week projection | no trend exists in the data (uniform dates) |
| Pie / donut of categories or customers | shares compare badly; the tables carry them |
| Images (matplotlib) | V8 cannot read them back (ADR-051) |
| A 13-colour category chart | dataviz caps categorical hues; categories are named on the axis |

## 3. Style changes (`style.py`, `render.py`)

| Item | Change | Why |
|---|---|---|
| Title box | two lines without overlapping the body (taller box or body start below a measured title) | L1 (slide 7 collision) |
| Accent rule under titles | remove | L2 |
| Approval badge | smaller, footer-aligned | L7 |
| Comments | fixed column (right of the visual) or band under it, consistent per slide type | L4 |
| Muted secondary text | for "typical ±x %" and "this / last week" counts — `INK_2` / `MUTED` | readable hierarchy |

## 4. Power BI alignment

The same new view columns serve Power BI (DirectQuery): the Overview cards can carry the typical swing, Receivables
the DSO split and roll-forward, Customers the AR / 13-week billing ratio — so the deck and the dashboard keep one
number per KPI (ADR-047).
