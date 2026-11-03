---
name: weekly-variance-analysis
description: The method for explaining a report week's changes — week over week and vs budget — by drill-down to vessel categories and customers, with external context (Suez transits, news, tariff notes) kept separate from NileGate's numbers.
stage: 1
reviewed_by_owner: 2026-11-02
---
# Weekly variance analysis

Goal: say **what changed, by how much, and why**, with every number taken from a tool result.

## Steps
1. `finance_kpi(week, "weekly")`: billed, collected, AR, overdue, DSO, budget variance, top-10 share and their WoW.
   Read each WoW against its **typical swing** (`billed_wow_typical_pct` …, the median |WoW| of 13 weeks): inside
   it, the week is normal; about 19 invoices a week make ±20 % moves common. NULL in warm-up weeks: say "not yet".
   If `is_warmup`, say that receivables and DSO are still building up (weeks 1–13).
2. `invoice_audit(week)` before naming any driver: a flagged invoice (above all a `duplicate_charge`) inflates or
   deflates its category's billing. If a driver holds a flagged invoice, say so in the same sentence — the change may
   be a billing error, not business. With no finding this week, `audit.ytd` lists the year's findings.
3. `finance_kpi(week, "category")`: the rows come largest |`billed_wow_change_sdr`| first. The **drivers** of the
   week are the top 3 rows by |change|. Name a category as a driver only if it is among those three, with its
   invoices this week (`invoices_billed`) and last (`invoices_prev`): one transit is not a trend. Week 1 has no
   WoW (all NULL): take the drivers from the largest |`budget_variance_sdr`| instead and say so.
4. Budget: the week (`budget_variance_pct`) **and** the period (`budget_variance_13w_pct`, weeks 1–w before
   week 13): when they disagree, say both — the week is noise, the period is the position.
5. Receivables: the overdue roll-forward (`overdue_new_sdr` fell due unpaid, `overdue_paid_sdr` of older overdue
   collected), DSO on terms (`dso_best_days`) and late (`dso_delinquency_days`), `due_week_collected_pct`; the
   largest overdue invoices.
6. Customers (`customers`): who entered or left the top 10 (`rank_13w` vs `rank_13w_prev`); the watchlist
   (`is_watchlist`: AR at least 1 M SDR and at least 80 % of its own 13-week billing, `ar_to_billed_13w_pct`).
7. Context, only after the numbers: `suez_transits` for the week and the 4 weeks before; `web_search` for that
   week's news; `search_documents` for a tariff rule that explains a change.

## Writing rules
- A direction or stability word must agree with the sign and size of the value you cite (V9). A category is
  "below budget" only when its own `budget_variance_sdr` is negative; positive = above budget.
- A finding from `audit.ytd` that is not this week's: name its week ("… of week 10") or say "year to date".
- Do not compute new numbers (no sums, differences or shares of your own): if you need one, ask for a dataset that
  holds it or leave it out.
- Correlation is not cause: Suez transits or news are context on slide 9; never write that they caused a NileGate
  change unless a document or the data shows the link.
- If a tool says `context_unavailable` or `no_data`, write that the context is unavailable; never fill the gap.
- Background, never written as figures: over the year actual billing is about 11 % below budget (planning
  assumption, not a weekly failure).

## Output (for the Report Writer)
- 5 summary bullets: billing with its swing; the period against budget; the top driver with its invoice count;
  receivables (overdue flow, watchlist); one audit or context line.
- For every bullet: the tool, dataset and filter it came from.
