# Data landscape — what the weekly finance pack reads

Status: **analysis document, rewritten 2026-10-31** for the owner's actual goal: improve the **weekly pack** the agent
produces every week (`pipelines/agents/graphs/weekly_pack.py`), not a yearly deck. Read-only study; nothing in the
database, the agent, the deck code, the skills or `Data/processed/agents/eval/` was changed. Companion files:
`advanced_analytics_findings.md`, `analytical_gap_assessment.md`, `visualization_recommendations.md`,
`executive_deck_storyboard.md` (the weekly deck storyboard), `implementation_roadmap.md`.

Method: the agent's code and skills read in full where they shape the deck (`render.py`, the `deck-style-guide`,
`weekly-variance-analysis` skills, ADR-051 and its amendments); the published packs W11 / W12 read as text and W12
viewed slide by slide in PowerPoint; SQL on the `finance` views with the read-only login, every weekly figure computed
**as of the report week's Sunday** (no later payment); the generator code for what the data can and cannot show.

## 1. How a weekly pack is made (existing)

```text
readiness → kpi → audit → insight_llm ⇄ insight_tools → insight_notes → writer → validator ─► approval → publisher
                                                                          │          ▲  ╲ fail ×2 → fallback (c4)
                                                                          └─ patch ──┘
```

| Step | What it does | Data |
|---|---|---|
| `kpi` | five `finance_kpi` calls for the report week | `kpi.weekly` (`finance.kpi_weekly`), `kpi.category` (`kpi_weekly_category`), `kpi.customers` (`kpi_customer_13w`, top 10), `kpi.overdue` (`kpi_overdue_list`, top 10), `kpi.trend` (`kpi_weekly_trend`) |
| `audit` | `invoice_audit(week)` | `audit.week` (`finance.invoice_audit` + checked count) |
| `insight_*` | a model calls `suez_transits`, `web_search`, `search_documents` for external context | public data / news (untrusted text, kept apart) |
| `writer` | the model writes slide titles, 5 summary bullets, ≤ 3 comments on slides 3–8, the context slide — **every number a slot** | the evidence above |
| `validator` | V1–V8: citations, numbers bound to (evidence, row, field), signs, drivers = top 3, file read-back | — |
| `approval` | the owner approves / edits (interrupt) | preview PPTX |
| `publisher` | `reports/<week>/deck.pptx` + `deck_draft.json`, `run.json`, `approval.json` | — |

Code draws slide 1, the tiles, every table and chart, the footnotes and slide 10 (`render.py`, `style.py`); the model
never types a NileGate number. Schedule: Monday 10:30, the next replay week (ADR-054).

## 2. The evidence one report week receives (W12 as the example)

| Evidence | Rows | Fields the deck uses today | Fields available but unused |
|---|---:|---|---|
| `kpi.weekly` | 1 | billed, collected, AR, overdue, DSO and their WoW; budget variance; top-10 share; `is_warmup` | the five aging buckets (only the chart uses them), `dso_window_billed_sdr` / `dso_window_days`, `ar_invoices`, `overdue_invoices`, `invoices_billed` |
| `kpi.category` | 13 | billed, budget, variance %, WoW change | `invoices_billed` (how many invoices sit behind a "driver") |
| `kpi.customers` | 10 | rank, previous rank, 13-week billing, share | **`ar_sdr`, `overdue_sdr`, `credit_rating`, `segment`, `payment_terms_days`** — the customer risk is in the evidence and never shown |
| `kpi.overdue` | ≤ 10 | invoice, customer, amount, days past due, bucket (top 5 drawn) | vessel, due date |
| `kpi.trend` | ≤ 13 | billed, budget per week | AR, DSO, overdue per week (a receivables trend is possible with no new data) |
| `audit.week` | findings | checked, flagged, at stake, findings table | — |

## 3. Data facts that bound what a week can say

| Fact | Evidence | Consequence for the weekly pack |
|---|---|---|
| Invoice dates are uniform over 2025 (generator); about 19 invoices a week | `kpi_weekly.invoices_billed` mean 19.15, variance 15.4 | A single week's billing is a draw: median \|WoW\| 21.6 %, 53 % of weeks move > ±20 %. The pack must say how big a "normal" swing is. |
| The budget prices every transit laden at median tonnage, with a seasonal curve | `budget_weekly`, generator | Week-vs-budget is mostly billing noise (r = 0.99); the 13-week view is the readable one. |
| Payment behaviour differs by customer by design (prompt … chronic late, disputer); rating correlates | `fact_payment`, `dim_customer` | Customer-level receivables risk is **real in the data every week** — the most useful weekly content the pack does not show. |
| Receivables start at 0 on 2025-01-01 | `is_warmup` weeks 1–13 | AR, DSO and collections of weeks 1–13 are not comparable with later weeks (footnote exists). |
| Payments run to 2026-03-31 | `fact_invoice.paid_date` | Every weekly statement must use the as-of views (they do); new weekly measures must too. |
| 3 live audit findings in the year (W10, W15, W50) | `invoice_audit` | 49 of 52 weekly packs show an empty audit slide. |

## 4. Data quality for weekly use

| Check | Result |
|---|---|
| Weekly KPIs vs an independent pandas reference | equal on all 52 weeks (`Finance_views_check.py`, 7 / 7) |
| W11 / W12 deck numbers vs `kpi_weekly` | equal (re-checked 2026-10-31) |
| Category-week sparsity | 22 % of category-weeks have no invoice; median 1 invoice per category-week |
| Drivers | the week's top-3 categories by \|WoW change\| have a median of 4 invoices across the two weeks; 19 % have two or fewer |
| Leakage | none in the views; any new weekly measure must filter `paid_date ≤ week end` |

## 5. Related outputs (not the weekly pack)

- **Power BI** (`powerbi/`): the same `finance` views; the Exceptions page was fixed on 2026-10-31 (status card,
  all-year findings table) and an Overview note added; an Executive page exists (see below).
- **Annual executive deck** (ADR-061, `pipelines/scripts/finance/Executive_*.py`,
  `reports/executive/2025/`): built earlier on a misread scope; the owner kept it as a separate year-end product
  (2026-10-31). Its findings are summarised in `advanced_analytics_findings.md`, Appendix A.
- **KPI definitions:** `docs/finance_metrics.md` M1–M12 (M12, the DSO split, added 2026-10-31).
