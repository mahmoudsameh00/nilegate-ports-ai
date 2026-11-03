# Implementation roadmap — improving the weekly finance pack

## Implementation record

Status: **IMPLEMENTED (2026-11-03)** — every phase A–F done; the plan stays in this folder (not moved, see
`docs/archive/README.md`), the progress section below is the full history.

- **A — SQL (2026-10-31):** migration 021 — 16 columns on `finance.kpi_weekly` (DSO split, 13-week billed / budget /
  variance, typical swings W-R2, overdue roll-forward W-R3, due-this-week rate, `roll_window_weeks` W-R7,
  `ontime_13w_pct` W-R8), 3 on `kpi_customer_13w` (watchlist W-R1, AR / billed, on-time), `invoices_prev` on
  `kpi_weekly_category`; `Finance_views_check.py` 8 / 8 (independent pandas reference, roll-forward residual 0.00).
  Migration 022 (2026-11-01): the `finance_test` twins get the same columns (017 rule).
- **B — Tools:** `finance_kpi` returns the 021 columns; `audit.ytd` (the year's audit findings to the report week,
  code-only `through_week`); Writer prompt +279 tokens (largest call ≈ 12.7K), within the free tier.
- **C — Deck:** the storyboard's slides (week-at-a-glance strip, typical swing under the tiles, period line, variance
  bars, overdue roll-forward chart, DSO split, receivables-risk table + watch marker, year-to-date findings, Suez
  chart, appendix); deviation D-C-1 (slide 6 shows the largest overdue invoices). Layout fixes D-C5-3 (comment boxes
  sized to their wrap, table cells' paragraph mark) and titles stepped to one line (2026-11-03). `Deck_check.py` 6 / 6.
- **D — Validator V9 + skills:** claim check rules 1–5 (external cause, stability / direction / consistency words,
  dramatic words inside the typical swing, comments restating tiles) and 6–8 after c5 (a category's budget word vs its
  own variance, an earlier finding's week, no doubled unit — D-C5-1); 28 planted over-claims caught, 0 false alarms on
  the 52 clean decks. Skills `deck-style-guide` and `weekly-variance-analysis` rewritten and **reviewed by the owner
  2026-11-02**. Scorer change D-D-1 (`holds_frozen`).
- **E — Evaluation:** c5 hand-check → V9 rules 6–8 → **c5b kept on the owner's hand-check** (D-C5-2; every hard gate in
  all three runs, false alarms 0; recall −0.0345 from one pack the Writer never produced): ADR-051 amendment 4,
  ADR-052 fifth use, ADR-053 result note. Baseline for Stage 1 packs: `stage1_eval_2026-11-02_c5b.json`.
- **F — Power BI (2026-11-02):** 20 columns + 15 measures (view values only, no DAX recompute), cards on Overview /
  Receivables, the Customers top-10 table with watchlist, AR / billed and on-time (ADR-048 amendment 1).
- **First live pack on the new code:** W13:1 (old code, no 021 evidence) rejected; W13:2 approved by the owner and
  published `reports/2025-W13/` (2026-11-03).
- **No-regression re-run (2026-11-03, D-RR-1):** finance Q&A vs dp127b "tie: keep", every gate; Stage 2 vs c1 stopped
  after repeat 1 on the Arabic gate by one Writer slot-form error on a non-finance item — every `finance_kpi` number
  right on the hand-check; the owner closed on the hand-check (ADR-052 sixth use). Baselines unchanged (Stage 2 c1,
  Q&A dp127b).
- **Open for the owner (not this plan):** Sentry D-S1-6 (connect monitor `nilegate-weekly-pack` to alert 6273246);
  delete the old parallel copy `D:\Project_wip`. Next phase: FastAPI (plan to be written in a new session).

## Plan

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
- 2026-11-01 — **c4 kept → Phases B–E start (owner choices, one round):** migration 022 applied by Claude after a dry
  run; candidate c5 runs as a one-time Windows task the morning after Phases B–D pass on fake models (a fresh
  provider day, like c4); the two skill edits (`deck-style-guide`, `weekly-variance-analysis`) are reviewed by the owner
  with the c5 results (a rejected edit = a re-run). **Timing:** no runtime code changes before the scheduled pack of
  Monday 2026-11-02 10:30 has finished; the dependency upgrade (`docs/plans/Dependency_upgrade_plan.md`) goes first, so
  B–D are checked on the upgraded `.venv`.
- 2026-11-01 — **Migration 022 written and dry-run** (`db/migrations/022_finance_test_weekly_pack_kpis.sql`): the twins
  `finance_test.kpi_weekly` / `kpi_weekly_category` append the 021 columns. Rule of 017 kept — from the copy: the 13-week
  billed / budget (the live 13-week sums with the report week swapped for the copy's) and their %; live: the window
  length, the DSO split, the typical swings, the roll-forward, the due-this-week rate, on-time %, a category's
  `invoices_prev`. Dry run as plain read-only queries: the 017 columns identical (0 rows differ in either view), 52
  category rows with `invoices_prev`; week 36's 13-week budget = live + 1,840,492.72 (the planted miss), variance
  −16.42 % vs live −14.32 %. Not applied yet (after the Monday firing).
- 2026-11-01 — **Migration 022 APPLIED** (owner: "022 دلوقتي + نسخة شغل موازية": it touches only the evaluation
  twins, which the Monday firing never reads): BEGIN / 2 CREATE VIEW / 17 COMMENT / COMMIT, `ANALYZE`, snapshot
  refreshed, `db/audit/2026-11-01_after_022_report.txt` 0 errors (identical to the 021 report). **B–D are coded in the
  parallel copy `D:\Project_wip`** (dependency plan D-U3) and copied into `D:\Project` after the firing.
- 2026-11-01 — **Phase B DONE (in the copy):** `finance_kpi` returns the 021 columns (weekly + 16, category +
  `invoices_prev`, customers + 3; the `weekly` description names them); `Tools_check.py` 10 / 10 — `PENDING_021` gone, the
  tool's lists must equal the live views' **and the twins'** columns, Phase 3b recomputes the three swapped 13-week
  columns and `invoices_prev`. Digest: category + invoice counts, customers + rating / AR-to-billed / watch / on-time.
  **Prompt size measured** (the project's `est_tokens`, W12 live): digest 1,631 → 1,910 tokens (+279) → the largest
  Writer call ≈ 12.7K of flash-lite's 250K TPM (nemotron 1M) — within the free tier.
- 2026-11-01 — **Phase C DONE (in the copy), `Deck_check.py` 4 / 4:** `render.py` / `style.py` per the storyboard —
  slide 2 "week at a glance" strip (billed WoW + typical swing, the period vs budget, overdue new / paid, DSO terms +
  late); slide 3 "typical ±x %" under the four WoW tiles ("not yet (warm-up)" while NULL); slide 4 the period line
  ("Weeks 1–w:" / "13 weeks:") + invoices this / last week in the drivers table; slide 5 **variance bars** (billed −
  budget, sorted, short names, grey below / blue above; the c4 budget-miss table kept with full names); slide 6 aging +
  **overdue roll-forward** chart (last week's overdue from `kpi.trend` → newly overdue → paid → now; from week 2) + DSO
  tile with terms / late payment + "due this week, collected x % of y"; slide 7 the **receivables-risk table** (rank,
  previous, customer, rating, 13-week billing, AR, overdue, AR / billed, watch / warm-up) + the rule line; slide 8 without
  findings: "N invoices checked this week, none flagged" + the **year-to-date findings table** (`audit.ytd`, new evidence:
  `invoice_audit` with a code-only `through_week` flag, never in the model's schema); slide 9 the **Suez transits chart**
  when the Insight agent fetched `suez_transits`; slide 10 "Appendix — data sources"; no accent rule, a two-line title
  box, a footer-sized badge. Slot rule: a typical swing is a size, not a change (`slots.is_change`, no sign).
  Validator slide map: 2 may cite `audit.*`, 4 + `kpi.weekly`, 6 + `kpi.trend`, 8 + `audit.ytd`.
  Checks re-snapshotted after review: Phase 1 read-back 905 → 1,011 values (the new columns, 0 refused); Phase 2 4
  charts from week 2 (week 1: 3), tables + the YTD table; Phase 3's table-cell mutation moved to column 4 (the same
  13-week billing, now after "Rating"). Previews rendered and looked at slide by slide (PowerPoint export, W12).
  **Deviation D-C-1:** slide 6 keeps the largest overdue *invoices* (top 3) instead of "top overdue customers" — the
  customers evidence is the top 10 by billing, a per-customer overdue ranking is no view column; the invoice table names
  the customer and the bucket.
- 2026-11-01 — **Phase D DONE (in the copy), `Deck_check.py` 5 / 5:** **V9** in `validator.py` (`claim_problems`, run on
  slides 1–8 and the deck title after V1–V7; `Problem.rule` + "V9"): (1) an external cause (Red Sea, disruptions,
  markets …) on a NileGate slide; (2) "stable / steady / flat / held" with the family's |WoW| ≥ 2 % (DSO ≥ 1 day);
  (2b) a title's direction word with no number in its clause against the week's sign ("Revenue mix growth" with
  billing −4.9 %), unless the clause names a category / customer; (3) "consistent / sustained / continued …" — against
  budget both `budget_variance_pct` and `budget_variance_13w_pct` must agree, for a level the last two trend moves;
  (4) in a title, a dramatic word (pullback, surge, sharp …) for a move inside the typical swing; (5) a comment made only
  of slot values the slide's tiles show (slides 3, 6, 7, 8), naming no row. Each message says the fix (patchable).
  `sample.py` (the fake Writer and the c4 fallback) writes comments that add a fact (payments, invoices, overdue flow,
  the top customer's share and AR, the year's largest finding) and tolerates evidence frozen before 021.
  Skills rewritten, **`reviewed_by_owner: no` until the owner's review with c5**: `deck-style-guide` (the new slides,
  "Titles and claims (V9 refuses the rest)"; 1,176 / 1,200 tokens) and `weekly-variance-analysis` (typical swing,
  the period vs the week, invoice counts, the roll-forward, DSO split, the watchlist; 1,048 tokens).
  `Deck_check.py` Phase 5 (new): 11 over-claim classes from the approved W11 / W12 decks (stable receivables,
  consistent outperformance, revenue mix growth, Red Sea on the cover, comments repeating tiles, + variants) planted
  alone in W11 and W12 → **22 / 22 caught by V9 alone**; the storyboard's four W12 titles pass V1–V9 (slide 1 needed
  "against budget" in its second sentence for V7 — the number rule, not V9); **0 V9 false alarms** on the 52 clean decks
  in both forms (slot and literal). Defects met on the way, fixed: the clause splitter cut at a decimal point; rule 5
  read a one-row result's row 0 as a row; literal numbers can bind a tile by value (rule 5 now judges slot values only).
  `Tools_check.py` Phase 4: `audit.ytd` = the weekly audits put together (live 12 / 52, test 49), `through_week` absent
  from the model's schema.
- 2026-11-01 — **The other checks on the copy, after review (0 files changed each):** `Weekly_pack_check.py` 7 / 7
  (evidence keys + `audit.ytd`); `Supervisor_check.py` ✅ (largest request 7,137 → 7,339 est. tokens: the supervisor
  sees the 021 columns too; still under its budget); `Stage1_eval.py` Phases 1–4 + 3c ✅ (fake models: 11 / 11 published,
  deck numbers 100 %, planted 6 / 6); Scheduler 7 ✅, Supervisor_tools 6 ✅, Voyage_watch 9 ✅, Monitoring 5 / 6 (6 is
  live-only), Finance_views 8 ✅; lint ratchet ✅ (ruff 48, pyright 276).
  **D-D-1 (scorer change, for the owner):** `Stage1_eval.py`'s `evidence_equal_frozen` required the run's evidence to
  *equal* the frozen `golden_weeks_expected.json`; Phase B / C add columns and `audit.ytd`, so every pack scored deck
  numbers 0. Now `holds_frozen`: every frozen value present and unchanged, additions allowed — the frozen file is not
  refrozen (ADR-053 untouched), Phase 2's "tampered evidence" case is still caught.
  **Open:** copy into `D:\Project` after the Monday firing → the checks there → c5 (one-time Windows task, the next
  provider day) → ADR-052 decision → ADR-051 amendment 4; the owner's review of the two skills. **Not covered by c5:**
  the finance Q&A and the Stage 2 supervisor also read `finance_kpi`, now with 16 more weekly columns — a Q&A
  (`EVAL_SCOPE=qa`) and `Stage2_eval.py` re-run on later provider days would confirm no regression.
- 2026-11-02 — **Phases B–D in `D:\Project`:** after the Monday firing (08:30Z, exit 0) the 18 files were copied in
  (each original unchanged since the copy), `uv sync --frozen`; every check green there with 0 files changed (Deck 5 / 5,
  Tools 10, Weekly_pack 6 / 7 + Phase 5 opt-in, Stage1_eval fake ✅, the others as before), lint baseline 325 → 324.
  **Phase E scheduled:** Windows task "NileGate Stage1 c5 eval (once)" Tuesday 2026-11-03 09:30 (packs only, 3 repeats,
  `EVAL_C4=1`, `EVAL_TAG=c5`, baseline `stage1_eval_2026-11-01_c4.json`, 4 h limit; log
  `reports/_log/stage1_eval_c5_task.log`). Next: read the result under ADR-052, hand-check any scored false alarm
  (D-C4-1), the owner reviews the two skills with it → keep = ADR-051 amendment 4 + this plan closed.
- 2026-11-02 — **Phase E moved to today (owner: "why wait?"):** the Gemini day had restarted at 10:00 Cairo with 1
  request used, so c5 ran at once (the Windows task and the Claude review task of 2026-11-03 removed). **c5**
  (`stage1_eval_2026-11-02_c5.json`, 3 runs, 202 calls, ~28 min) vs c4: planted 6 / 6 in every run, published 33 / 33
  (c4 32 / 33), deck numbers / claims / traceability 1.0, narrative recall 0.9885 (c4 0.9655); harness "tie: keep";
  false alarms as scored 0.35 / 0.22 / 0.15. Rewrites: 32 / 33 packs needed two (c4 18 / 33), ~105 s a pack.
  **Hand-check of all 11 scored false alarms:** 9 true — earlier weeks' findings from `audit.ytd` (INV-0000626 week 10,
  INV-0000925 week 15, INV-9000292 week 23, INV-0000769 week 36: invoice, check and amount right); of these one (live
  W16 r3) gave no week ("Duplicate charge check identified invoice INV-0000626 …"), read as this week's. **2 real
  errors**: live W24 "Crude Oil Tankers missed budget by +0.42 M SDR" (billed 0.84 M vs budget 0.41 M = above) and
  "Ro/Ro Vessels missed budget by +0.17 M SDR" (above too) — V9 judged budget direction in titles only. Plus a unit
  twice ("+81.8 k SDR thousand SDR").
  - **D-C5-1 (owner: fix and re-run c5b today):** V9 rules 6–8 — a category's budget position must agree with its own
    `budget_variance_sdr`; an `audit.ytd` finding not of this week must carry its week or a year-to-date word; no unit
    after a slot that already writes it. Replayed on the c5 sentences: the 4 wrong caught, the 4 right pass. Deck_check
    Phase 5: 14 classes, 28 planted, all caught by V9 alone; the 52 clean decks pass. The scorer: `false_alarms()`
    exempts an earlier week's finding told with its week or as year to date (Phase 2 `ytd_with_week` 0,
    `ytd_as_this_week` 1). Skill `weekly-variance-analysis`: two lines (a category's budget word; an earlier finding's
    week). Checks: Deck 5 / 5, Stage1_eval fake ✅, Weekly_pack 6 / 7, Tools 10 ✅, lint ✅.
  - Quota: c5 + c5b ≈ 404 of 500 today → the finance Q&A (`EVAL_SCOPE=qa`, vs `dp127b`) and `Stage2_eval.py` (vs c1)
    run tomorrow as one Windows task "NileGate Stage2 + QA re-run c5 (once)", 2026-11-03 10:15 (Stage 2 first).
- 2026-11-02 — **c5b** (`stage1_eval_2026-11-02_c5b.json`, 3 runs, 200 calls, ~24 min, baseline c4): every hard gate in
  all three runs — false alarms 0 / 0 / 0, planted 6 / 6, numbers / claims / traceability 1.0; published 32 / 33 (= c4);
  narrative recall 0.931 vs 0.9655 → harness **reject** (−0.0345 > 0.03). Hand-check: one pack (r3 live W16) never
  produced — the Writer twice typed an evidence id "kpi.overdry," (schema refusal, before any check; c4 lost r2 live
  W24 the same way); on published packs 81 / 83 vs 84 / 84 (r2 W41 collections move, r3 W10 summary naming the
  exceptions). No code-fallback texts found in the 33 decks.
  - **D-C5-2 (owner: "نحتفظ بـ c5b بعد مراجعة يدوية"):** c5b kept as Writer variance (ADR-052 amendment 2) with every
    gate improved or equal → ADR-051 amendment 4, ADR-052 fifth use, ADR-053 result note. The two skills: the owner
    reviews them himself (`reviewed_by_owner: no` until then).
  - **Open:** the owner's skill review; tomorrow's Stage 2 + Q&A re-run (10:15) → read under ADR-052; Phase F
    (Power BI, optional). Then this plan's implementation record.
- 2026-11-02 — **Phase F DONE (owner: "نعملها النهارده"):** the 021 columns added to the Power BI model through the Modeling
  MCP (20 columns, 15 measures, all `SELECTEDVALUE` / ÷ 100 of the view — no DAX recompute), checked against SQL (weeks
  5 / 24 / 48 equal) and against the Executive page's DAX (equal where both exist); visuals built on screen and saved:
  Overview "Budget Variance 13w %" card; Receivables card row (DSO best / late days, overdue new / paid, due
  collected %); Customers top-10 table + Watchlist, AR / billed 13w, On-time 13w. ADR-048 amendment 1. (A second empty
  Power BI instance opened by mistake was closed at once; the auto-recovery prompt was cancelled, no file removed.)
- 2026-11-02 — **Skills reviewed by the owner** (`reviewed_by_owner: 2026-11-02` on `deck-style-guide` and
  `weekly-variance-analysis`). **D-C5-3 (layout, owner: "صلّحه"):** the c5b W48 deck, re-read as images, showed what the
  short fake texts never did: slide 6's three comments overlapped (fixed 0.62 in boxes) and slide 7's table ran under
  the watch rule (every table cell's paragraph mark kept the theme's 18 pt, so PowerPoint drew rows ~0.39 in whatever
  the run size). `render.py`: comment boxes as tall as their estimated wrap (`_text_h`, 0.55 em a character), the type
  stepping down to 10 pt to fit above the footer / footnote; the cells' paragraph mark sized to the run; slide 4's
  period line narrowed off the comments column; slide 8's comments follow the year's table. Deck_check **Phase 6**
  (long real-length comments on weeks 5 and 48: every comment box above the footer, clear of every element and of each
  other; slide 7's table above the watch rule) → 6 / 6; Stage1_eval fake ✅, Weekly_pack 6 / 7, lint ✅. Rendering only:
  no Writer, Validator or scorer change, so c5b's result stands (ADR-052 amendment 2: a non-Writer change is not a new
  Writer comparison). W48 re-rendered from c5b's own texts: no overlap.
- 2026-11-03 — **W13, the first live pack on the new code.** The scheduled W13:1 (2026-11-02 08:30, old code) could
  not be published: the publisher re-renders from the thread's evidence, which had no 021 columns / `audit.ytd`
  (dry run: `SlotError … budget_variance_13w_pct`). Owner: reject it (reason logged) and run a fresh attempt → W13:2
  (`Weekly_pack.py run --week 13 --as 6`): degraded — V9 dropped three Writer comments (two repeating slide 3's tiles,
  one "held" for overdue +17.14 %), 12 slot-form fixes; the owner reviewed the 10 slides and approved → published
  `reports/2025-W13/` (V8 clean). The scheduler continues with W14 on 2026-11-09.
- 2026-11-03 — **Titles on one line (owner: slide 2's title left "M SDR" alone on a second line):** `render._title_size`
  steps a title from 26 down to 20 pt until it fits one line (bold Calibri ≈ 0.45 em a character, measured on W13);
  a title too long even at 20 pt keeps 26 pt on two lines. Slide 4's drivers table: the WoW column widened so
  "−100.0 %" stays on one line. Deck 6 / 6, Stage1_eval fake ✅, Weekly_pack 6 / 7, lint ✅. The published W13 file is
  left as approved (its sha256 is in `run.json`); the next packs get the new titles.
- 2026-11-03 — **Stage 2 + finance Q&A re-run (Windows task "NileGate Stage2 + QA re-run c5 (once)", 10:15–10:49,
  exit 0; 317 of flash-lite's 500 requests that day).** Purpose: confirm that `finance_kpi`'s 16 new weekly columns
  (021) cause no regression in the two other agents that read it.
  - **Finance Q&A** (`stage1_eval_2026-11-03_c5qa.json`, 2 runs, vs `stage1_eval_2026-10-31_dp127b.json`): every gate
    in both runs (traceability 1.0, RBAC leakage 0, abstention recall 1.0); completeness EN 0.9783 (−0.0217) / AR 1.0
    → harness "tie: keep". The one item below 1.0 — r04 run 1 (Port of Rotterdam annual report, a document question,
    no `finance_kpi`) — was refused by the Q&A checker for the citation's page number "page 82" read as a typed
    number; run 2 answered it. Not a regression.
  - **Stage 2** (vs `stage2_eval_2026-10-30_c1.json`): the harness **stopped after repeat 1** — gate
    `arabic_ge_en_minus_0_10` (AR 0.825 vs EN 0.9485); the other six gates held (leakage 0, twins, abstention, numbers,
    traceability 1.0, EN ≥ 0.85). No results file by design; the partial file kept as
    `Data/processed/agents/eval/stage2_eval_2026-11-03_c5_partial.json`. **Hand-check of every item below 1.0:** the
    15 items that called `finance_kpi` — 13 at 1.0; c07 / c07_ar 0.75: the customer's 13-week billing (4.56 M SDR, the
    `finance_kpi` part) right in both, the Suez saving (the `route_advice` part) left out — c07 scored 0.75 in c1 run 2
    too. The gate fell on **o16_ar** (vessel fuel cost, `vessel_params`, no finance): the Writer wrote a malformed slot
    (`{insight.call_…:fuel_cost_sdr_per_day|money_sdr}`, no row) → `validation_failed`, 0.0; without it AR = 0.925, gap
    0.02. o01 / o01_fe / o01_ar 0.5: position and next port right, the word "in transit" missing (c1 had 0.5 on these
    too); o08 0.5: the text has both numbers right (11.8 kn, 2,349.6 nm), the scorer credited one value only; c04_ops
    `not_permitted` instead of `partial` (as c1 run 2).
  - **D-RR-1 (owner, 2026-11-03: "close on the hand-check"):** no regression attributable to the 021 columns — every
    `finance_kpi` number in both agents is right; the Stage 2 stop is one Writer slot-form error on a non-finance item
    (Writer variance, ADR-052 amendment 2). Not re-run; the Stage 2 baseline stays c1, the Q&A baseline stays dp127b.
    Recorded as ADR-052's sixth use.

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
