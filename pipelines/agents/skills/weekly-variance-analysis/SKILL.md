---
name: weekly-variance-analysis
description: The method for explaining a report week's changes — week over week and vs budget — by drill-down to vessel categories and customers, with external context (Suez transits, news, tariff notes) kept separate from NileGate's numbers.
stage: 1
reviewed_by_owner: 2026-10-19
---
# Weekly variance analysis

Goal: say **what changed, by how much, and why**, with every number taken from a tool result.

## Steps
1. `finance_kpi(week, "weekly")`: billed, collected, AR, overdue, DSO, budget variance, top-10 share and their WoW.
   If `is_warmup`, say that receivables and DSO are still building up (weeks 1–13).
2. `invoice_audit(week)` before naming any driver: a flagged invoice (above all a `duplicate_charge`) inflates or
   deflates its category's billing. If a driver holds a flagged invoice, say so in the same sentence — the change may
   be a billing error, not business.
3. `finance_kpi(week, "category")`: the rows come largest |`billed_wow_change_sdr`| first. The **drivers** of the
   week are the top 3 rows by |change|. Name a category as a driver only if it is among those three. Week 1 has no
   WoW (all NULL): take the drivers from the largest |`budget_variance_sdr`| instead and say so.
4. Budget: the company variance (`budget_variance_sdr`, `budget_variance_pct`) and, per category, which categories
   are furthest from budget. A category far above or below its budget while the others are close is worth one
   sentence.
5. Customers (`customers`): who entered or left the top 10 (`rank_13w` vs `rank_13w_prev`), and the top-10 share.
6. Receivables (`overdue`): the largest overdue invoices and the oldest buckets; DSO change in days.
7. Context, only after the numbers: `suez_transits` for the week and for the 4 weeks before (compare the mean daily
   transits); `web_search` for news of that week; `search_documents` for a tariff rule that explains a change.

## Writing rules
- A direction word (rose, fell, up, down, increased, declined) must agree with the sign of the value you cite.
- Write the number with its unit and period: "billed <billed_sdr> SDR in week <w>, <billed_wow_pct> % WoW".
- Do not compute new numbers (no sums, differences or shares of your own): if you need one, ask for a dataset that
  holds it or leave it out.
- Correlation is not cause: "Suez transits were lower that week (<mean> per day vs <previous mean>)" is context;
  never write that the canal caused a NileGate change unless a document or the data shows the link.
- If a tool says `context_unavailable` or `no_data`, write that the context is unavailable; never fill the gap.
- Background, never written as figures: about 19 invoices a week (large weekly swings are normal), and over the
  year actual billing is about 11 % below budget (planning assumption, not a weekly failure).

## Output (for the Report Writer)
- 5 bullets for the executive summary: headline revenue + WoW, budget variance, the top drivers, receivables / DSO,
  one context or risk line.
- For every bullet: the tool, dataset and filter it came from.
