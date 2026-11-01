# Implementation roadmap — improving the weekly finance pack

Status: **APPROVED (2026-10-31)** — owner: "close every open note and point"; decisions W-R1…W-R6 taken as
recommended, validation issues closed in the specification below. **Timing (corrected 2026-10-31):** only the code the
Stage 1 c4 evaluation runs on 2026-11-01 09:30 must wait — the deck (`render.py`, `style.py`), the Validator, the
Writer, the agent's skills and the tools — because c4 compares that code as it is. The **SQL layer (Phase A) may start
now**: `finance_kpi` reads explicit column lists (`pipelines/agents/tools/finance.py`), so columns added to the views
change no evidence, no prompt and no c4 run. This file is the plan of the weekly-pack work (`docs/plans/` keeps only
`Agents_plan.md`; after c4 the owner may move it there as the Agents plan's next item).

Owner's goal (2026-10-31): improve the **weekly pack** the agent produces — its analysis, its numbers' context and its
look — not a separate yearly deck. Study: `data_landscape.md`, `advanced_analytics_findings.md` (W1–W9),
`analytical_gap_assessment.md` (C1–C10, L1–L8), `visualization_recommendations.md`, `executive_deck_storyboard.md`
(the new 10-slide storyboard).

Quality gate: the study passed the Anthropic Data plugin's `/validate-data` method ("share with noted caveats";
report in `advanced_analytics_findings.md`); the same gate is applied before the new pack is shared (Phase E).

## Constraints

- **Number contract (ADR-051) stays:** every number on a slide comes from a view column through a slot or a bound
  value; V1–V8 and the file read-back stay; new numbers = new view columns (KPIs only in SQL, ADR-047), never computed
  in the tool, the renderer or by the Writer.
- **Leakage:** every new weekly column is as of the report week's Sunday (`paid_date ≤ week_end`).
- **Writer cost:** Writer prompts ≤ ~12.4K tokens today on the free tier; new evidence fields are added only where a
  slide uses them; the quota is the free Gemini tier (ADR-045).
- **Evaluation:** the golden weeks, planted errors and the ADR-052 rule decide whether the new pack is kept (a
  candidate **c5** against the c4 result); slides 5 and 8 keep the code-drawn budget-miss and audit tables c4 relies on.
- Migrations are applied by the owner; skills are reviewed by the owner; one owner commit per stage.

## Decisions (taken 2026-10-31, owner: "close every open point" — all as recommended)

| # | Decision | Decided |
|---|---|---|
| W-R1 | Watchlist rule on slide 7 | AR ≥ 1 M SDR **and** (AR ≥ 80 % of its own 13-week billing, or no 13-week billing at all — a customer that stopped buying but still owes) (W4: 256 customer-weeks in weeks 14–52, eight customers); in warm-up weeks 1–13 the flag is NULL and the marker reads "warm-up" (validation issue 3) |
| W-R2 | "Typical weekly swing" | the median \|WoW\| of the last 13 weeks (at least 8 weeks; blank before) — robust to one outlier week |
| W-R3 | Overdue roll-forward definitions | "newly overdue" = invoices due from the previous Sunday to this Saturday and unpaid at this Sunday; "overdue paid" = payments this week on invoices already overdue at the previous Sunday — validated 2026-10-31: the residual is 0.00 SDR on weeks 2–52 (to be asserted in `Finance_views_check.py`) |
| W-R4 | Slide 8 without findings | compact line + year-to-date findings list (week ≤ w) |
| W-R5 | Look | remove the title accent rule; two-line title box; smaller approval badge; slide 5 as variance bars with short names; Suez mini-chart on slide 9 |
| W-R6 | Claim check (V9) | refuse a title / bullet whose direction or stability word contradicts the slide's own evidence, an external cause attached to a NileGate number, and a comment that only restates a tile |
| W-R7 | Partial windows (validation issue 3) | every rolling column comes with its window length (`roll_window_weeks`: 1 … 13); the deck writes "weeks 1–w" instead of "13 weeks" while it is below 13; the watchlist marker reads "warm-up" in weeks 1–13 |
| W-R8 | Weekly payment behaviour (validation issue 4) | not a weekly figure (15–17 payments a week): a 13-week on-time % per customer and in total (`ontime_13w_pct`, payments made by the Sunday), shown on slide 7 only |

## Phases

### A — SQL: migration 021 (DONE 2026-10-31)
- `finance.kpi_weekly` + `dso_best_days`, `dso_delinquency_days` (M12); `billed_13w_sdr`, `budget_13w_sdr`,
  `budget_variance_13w_pct` (weeks 1 … w before week 13); `billed_wow_typical_pct`, `collected_wow_typical_pct`,
  `ar_wow_typical_pct`, `overdue_wow_typical_pct` (W-R2); `overdue_new_sdr`, `overdue_paid_sdr`, `due_week_sdr`,
  `due_week_collected_sdr`, `due_week_collected_pct` (W-R3).
  `roll_window_weeks` (W-R7); `ontime_13w_pct` (W-R8).
- `finance.kpi_customer_13w` + `ar_to_billed_13w_pct`, `is_watchlist` (W-R1, warm-up aware), `ontime_13w_pct` (W-R8).
- `finance.kpi_weekly_category` + `invoices_prev`.
- `finance_test` twins where the evaluation reads them (migration 017 pattern).
- `docs/finance_metrics.md`: M12 columns, M13 (typical swing), M14 (overdue roll-forward), M15 (watchlist).
- **Done when:** `Finance_views_check.py` gets an independent pandas reference for every new column and passes on all
  52 weeks; `verify_readonly.sql` + schema snapshot refreshed.

- Safe before c4: views gain columns at the end only (`CREATE OR REPLACE VIEW` keeps the existing columns and their
  order); the tool's explicit column lists, the Power BI tables and the `finance_test` twins read by c4 see no change —
  checked by re-running `Tools_check.py` and `Finance_views_check.py` (old phases) after the owner applies it.

### B — Tools (after c4)
- `finance_kpi` returns the new columns in the existing results (no new tool); `Tools_check.py` extended.
- **Done when:** the Writer's prompt size for W12 stays within the free-tier budget (measured, not assumed).

### C — Deck (`render.py`, `style.py`) (after c4)
- Slides as in the storyboard: tiles with typical swing; slide 4 period line + invoice counts; slide 5 variance bars;
  slide 6 DSO split tile, roll-forward, due-collected rate, top overdue customers; slide 7 risk table + watch marker;
  slide 8 compact / YTD list; slide 9 Suez mini-chart; slide 10 as appendix; layout fixes L1–L8.
- Every new element carries a contract name (`bind:` / `tbl:` / `chart:`), read back by V8.
- **Done when:** `Deck_check.py` — every clean golden deck passes V1–V8, every planted wrong number is still caught,
  and the new elements are read back.

### D — Validator V9 and the skills (after c4)
- V9 (W-R6) in `validator.py` with a patch message the Writer can act on; `deck-style-guide` and
  `weekly-variance-analysis` updated (title rules, no tile restating, the new evidence) — owner review of both skills.
- **Done when:** `Deck_check.py` plants the W11 / W12 over-claims (and their variants) and V9 catches them, with no
  false alarm on the clean golden decks.

### E — Evaluation: candidate c5 (after c4)
- `Stage1_eval.py` c5 vs the c4 result under ADR-052 (same golden weeks, planted errors, quality gates; live runs on
  the free quota).
- **Done when:** ADR-052 "keep"; then ADR-051 amendment 4 records the new pack.

### F — Power BI alignment (optional)
- The new columns on the Overview / Receivables / Customers pages so the dashboard and the pack show the same numbers.

## Risks

| Risk | Mitigation |
|---|---|
| A claim check that refuses good titles (false alarms) | built from planted cases and the clean golden decks; measured like ADR-051's V-checks |
| Writer prompt growth on the free tier | only the fields a slide uses; measured in Phase B |
| Definitions of new KPIs drifting between SQL, deck and Power BI | one view column each, a pandas reference, documented in `finance_metrics.md` |
| c5 changing what c4 measured | slides 5 and 8's code-drawn tables kept; ADR-052 comparison decides |

---

## Progress / deviations (handoff)

- 2026-10-31 **Phase A written and dry-run, waiting for the owner to apply 021:** `db/migrations/021_weekly_pack_kpis.sql`
  (16 columns on `kpi_weekly`, 3 on `kpi_customer_13w`, 1 on `kpi_weekly_category`, every column commented); run
  read-only as plain queries: the existing columns of the three views come out identical (values and NULLs), the new
  ones equal an independent pandas reference — `Finance_views_check.py` Phase 7 (new) passed on the dry bodies; the
  roll-forward residual is 0.00 on all weeks. `docs/finance_metrics.md` M9b, M12 (now columns), M13–M16.
  **Defect fixed on the way:** `Finance_views_check.py` had failed Phase 3 since migration 015 (it expected 13 views;
  `invoice_audit` makes 14) — the list and the Phase 6 grant count now include it; the live check passes 7 / 7 with
  Phase 7 "pending 021". **Deviation:** W-R1's count is 256 customer-weeks (not 245): the built rule also flags a
  customer with AR ≥ 1 M and no 13-week billing (Korussa).
- 2026-10-31 **Phase A DONE — migration 021 applied** (owner: "أيوه، طبّقها"; BEGIN / 3 CREATE VIEW / 20 COMMENT /
  COMMIT, `ANALYZE`): `Finance_views_check.py` 8 / 8 (Phase 7 on the live views); `Tools_check.py` 10 / 10 after one
  check change — its Phase 3 guard demanded the tool's column lists equal the views' and stopped on the new columns
  (by design); it now requires the tool's columns to be the views' leading ones and the trailing ones to equal a
  reviewed `PENDING_021` set (removed in Phase B), and the reference rows read the tool's columns. The tool itself is
  unchanged (c4 evidence unchanged). `Executive_analysis.py` files changed 0; snapshot refreshed;
  `db/audit/2026-10-31_after_021_report.txt` (14 views, 0 uncommented columns, 0 errors).
- Next: c4 (2026-11-01 09:30) → Phase B (`finance_kpi` returns the 021 columns, `PENDING_021` removed from
  `Tools_check.py`, the `finance_test` twins get the same columns) → C → D → E.

## History (before the rewrite of 2026-10-31)

- **Annual executive deck (ADR-061):** built on a misread scope — the first request was understood as a yearly
  executive presentation. Delivered `pipelines/scripts/finance/Executive_analysis.py` / `Executive_charts.py` /
  `Executive_deck.py` (17-slide deck in `reports/executive/2025/`), KPI M12 in `finance_metrics.md`, Power BI Executive
  page + 12 measures. The owner kept it as a separate year-end product (2026-10-31: "leave it as it is").
- **Fixes kept:** Power BI Exceptions page (status card + all-year findings table, slicer → table NoFilter), Overview
  noise subtitle, `Revenue 2025 SDR`.
- **Earlier decisions:** D-R1 (no weekly-pack change before c4) → this plan; D-R2 (Power BI Revenue route / band charts
  kept); D-R3 (M12 as a `kpi_weekly` column after c4) → Phase A; D-R4 (the findings go into the weekly pack) → this plan.
- **Corrections found during the reviews:** the 90+ owner share (67–100 % from week 26, not every week), four slow B
  payers (not two), DSO range 51.4–64.7, delinquency ≈ a quarter of DSO, drivers' invoice counts (median 4, not
  "mostly single invoices").
