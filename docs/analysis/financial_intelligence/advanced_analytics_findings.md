# Advanced analytics findings — what a weekly pack can reliably say

Status: **analysis document, rewritten 2026-10-31** for the weekly pack. Every weekly figure is **as of the report
week's Sunday** (payments dated later are not used). Money in SDR. Labels: **Fact** = measured; **Design fact** = read
in the generator; **Hypothesis**; **Recommendation**. W12 (2025-03-17 … 23, a warm-up week) and W11 are the examples
because they are the latest published packs; weeks 14–52 give the distributions.

---

## W1 — A week's billing change is usually noise; the pack needs a yardstick

- **Question:** when the pack says "billed −4.9 % WoW", is that news?
- **Method:** distribution of |billed WoW| over the year; rolling 13-week median |WoW| as a "typical swing".
- **Finding (Fact):** median |WoW| 21.6 %; 53 % of weeks move more than ±20 %; only one week (W23) is beyond 2 σ of the
  weekly mean — about two are expected by chance. The rolling 13-week median |WoW| is 10.4 % at W12, 22.4 % at W23,
  22.6 % at W52. W12's −4.9 % is inside the typical swing.
- **Design fact:** invoice dates are uniform over the year; no real trend or seasonality exists.
- **Implication for the pack:** each WoW tile should carry "typical weekly swing ±x %" (code-drawn, from a view), and
  the Writer should not call a within-swing move a "pullback" or a "rise".
- **Confidence:** High.

## W2 — Week vs budget is billing noise; the cumulative / 13-week view is the honest one

- **Finding (Fact):** weekly variance correlates 0.99 with billing. W12 is +9.8 % vs its weekly budget, but weeks 1–12
  together are **−3.7 %** and only 7 of those 12 weeks were above budget; the rolling 13-week variance is −5.8 % at
  W13, −5.2 % at W23, −14.0 % at W52 (the plan rises in H2, billing does not).
- **Implication:** slide 4's chart already shows the 13 weeks, but no number states the period's position, so the
  Writer titled W12's slide "Consistent Outperformance" against its own chart. A code-drawn "13 weeks: billed vs
  budget x %" line would anchor the title.
- **Confidence:** High.

## W3 — The week's "drivers" rest on a handful of invoices

- **Finding (Fact):** the top-3 categories by |WoW change| have a median of **4 invoices** across the two weeks; 19 %
  have two or fewer. The LNG category is the top driver in 21 of 51 weeks because its invoices are the largest.
- **Implication:** the drivers table should show the invoice counts (this week / last week) so a reader sees when a
  "driver" is one or two transits. (Correction 2026-10-31: the first study said drivers were "often single invoices";
  measured, that is 19 %, not most.)
- **Confidence:** High.

## W4 — Customer receivables risk is visible every week and never shown

- **Question:** who carries the receivables risk this week?
- **Method:** each customer's AR at the week's Sunday against its own 13-week billing (`kpi_customer_13w`: `ar_sdr`,
  `billed_13w_sdr`), with its rating.
- **Finding (Fact):** Belanor Tankers (rating B, 60-day terms, the #1 customer every week) holds AR equal to 89–98 % of
  its own 13-week billing (W12 95 %, W23 89 %, W39 97 %, W52 98 %) and 16–29 % of all receivables (weeks 14–52).
  Over weeks 14–52, 256 customer-weeks meet the watchlist rule (AR ≥ 1 M SDR and AR ≥ 80 % of the 13-week billing, or
  no 13-week billing at all) — eight customers (Levavia 39, Belanor 38, Nilomar 36, Korussa 31, Nilussa 21, Thalanor
  17, Quorondo 17, Ardanor 11 weeks). *(The first count, 245, missed customers with AR but no billing in 13 weeks —
  Korussa's unpaid invoices; the rule as built in migration 021 includes them.)*
- **Design fact:** these are the generator's slow / chronic-late / disputer customers; ratings B / C.
- **Implication:** slide 7 lists the top-10 by billing with rank and share only; the same evidence row already holds
  `ar_sdr`, `overdue_sdr`, `credit_rating`. A "receivables watchlist" (AR / 13-week billing, overdue, rating) is the
  single most useful weekly addition, at no new data cost for AR and overdue.
- **Confidence:** High.

## W5 — Overdue concentrates in five customers every week

- **Finding (Fact):** the five customers with most overdue hold a median **72.5 %** of overdue (60.7–91.3 %, weeks
  14–52); W11 68.1 %, W12 64.0 %.
- **Implication:** slide 6's "five largest overdue invoices" table is invoice-level; a customer-level view (who owes the
  overdue) is the actionable one for credit control.
- **Confidence:** High.

## W6 — Overdue moves by two flows the pack never separates

- **Method:** per week, invoices that became overdue that week (unpaid at Sunday) vs overdue invoices paid that week;
  and the cash falling due that week vs the part of it paid by Sunday.
- **Finding (Fact):** with "newly overdue" = invoices due from the previous Sunday to this Saturday and unpaid at this
  Sunday, and "overdue paid" = payments this week on invoices already overdue at the previous Sunday, the roll-forward
  closes exactly (residual 0.00 SDR on all weeks 2–52). W12: overdue +1.51 M = 2.63 M newly overdue − 1.12 M old
  overdue collected; W11: +2.19 M = 3.18 M − 0.99 M. *(Corrected in the validation pass: a first estimate counted
  invoices that fell overdue and were paid within the same week, leaving a 0.16 M gap.)* Of the
  cash falling due in a week, a median **46 %** is paid by its Sunday (p10 29 %, p90 60 %; W12 49 %, W11 35 %).
- **Implication:** "overdue rose 20.2 %" (W12) says nothing about why; an overdue roll-forward (opening → newly overdue
  → paid → closing) and a "due this week collected" rate explain it. These need view columns (they are KPIs — not to be
  computed in the tool or the deck).
- **Limitation:** the "due this week collected" rate is still an analysis figure; both go into SQL with a pandas
  reference (P2-7 style) before the deck uses them.
- **Confidence:** High for the roll-forward (exact identity); Medium for the collected rate.

## W7 — DSO: the controllable part is visible every week

- **Finding (Fact):** M12 splits DSO into terms (best possible) and delinquency: W11 51.6 = 42.0 + 9.6; W12 54.2 = 42.7
  + 11.5; W52 55.0 = 40.0 + 15.0. Weekly DSO moves are AR moves (90 %).
- **Implication:** the receivables slide shows DSO as a bare number with its WoW; the split says how much is
  controllable. Needs the M12 columns in `kpi_weekly` (migration 021).
- **Confidence:** High.

## W8 — Payment behaviour of the week

- **Finding (Fact):** of the payments received in a week, a median 35 % were on or before due (weeks 14–52; p10 23 %,
  p90 45 %); W12: 17 payments, 58.8 % on time, mean −0.3 days; W11: 15 payments, 53.3 %, +5.9 days.
- **Implication:** a one-line behaviour tile is possible, but the weekly number is small-sample (15–17 payments);
  better as a 13-week figure. Lower priority than W4–W7.
- **Confidence:** Medium.

## W9 — The Writer's text claims more than its numbers (seen in the approved W11 / W12)

- **Finding (Fact, from the decks):** every number is right (slots + Validator), but titles over-claim: W12 slide 4
  "Consistent Outperformance Against Budget" (7 of 12 weeks above, −3.7 % in total); slide 2 "Stable Receivables" (AR
  +6.1 %, overdue +20.2 %, DSO +2.6 days on the same deck); slide 5 "Revenue Mix Growth" (billing −4.9 %); the cover
  ties NileGate's billing to "Red Sea Disruptions" (external context on a NileGate claim); the Suez figure is "averaged
  45 per day during week 12" on slide 2 and "on March 23" on slide 9. Comments often repeat the tiles (slide 8: three
  sentences restating 24 / 0 / 0.00).
- **Implication:** the Validator checks numbers, not claims. A claim check (direction / stability words against the
  signs of the slide's own evidence; no external cause in a NileGate title) and code-given anchors (W1, W2) are needed.
- **Confidence:** High.

## Validation report (Anthropic Data plugin `/validate-data` method, 2026-10-31)

### Overall assessment: **Share with noted caveats**

### Methodology review
The question (what a weekly pack can reliably say) is answered on the right grain (report week, as of its Sunday);
sources are the `finance` views and base tables read-only; the population is the 996 invoices of the 52 report weeks;
definitions follow `docs/finance_metrics.md`, new ones are stated where used (typical swing, roll-forward, watchlist).

### Calculation spot-checks (each computed two ways)
- Belanor AR / 13-week billing at W12: snapshot 7,977,542.54 = view; invoices 8,366,495.15 = view; ratio 95.4 % — **verified**.
- Overdue roll-forward: residual 0.00 SDR on weeks 2–52 — **verified** (after the definition fix above).
- Weeks 1–12 vs budget: −3.68 % from `kpi_weekly` and from the category sums — **verified**.
- Top-5 overdue share at W12: 64.0 % from the snapshot and from `kpi_customer_13w` — **verified**.
- Typical swing at W12: median |WoW| of weeks 2–12 = 10.4 % — **verified** (n = 11, see caveats).
- W11 / W12 deck numbers = `kpi_weekly` — **verified**.

### Issues found
1. [Medium, fixed] Overdue-flow definition double-counted same-week overdue-and-paid invoices (0.16 M at W12).
2. [Low, fixed] "Drivers are often single invoices" (earlier study) — measured 19 %, median 4 invoices.
3. [Medium, closed — plan W-R7] Partial windows: the typical swing at W12 rests on 11 weeks and the "13-week"
   billing at W12 on 12 weeks (history starts 1 Jan) — the view columns expose the window length and the watchlist
   marker reads "warm-up" in weeks 1–13.
4. [Low, closed — plan W-R8] W8 (payment behaviour of a week) rests on 15–17 payments — shown as a 13-week on-time %
   instead, on slide 7 only.

### Pitfalls checked
Look-ahead (none: every figure as of its Sunday; the roll-forward uses `paid_date ≤` Sunday) · incomplete periods
(issue 3) · denominator shifts (none: the ratio's denominator is the same 13-week billing every week) · small samples
(issue 4) · correlation as causation (none claimed; Suez context kept apart) · multiple comparisons (no tests across
segments are claimed as findings) · average of averages (none: shares from sums).

### Visualization review
Existing charts start at zero and label units; the proposed variance bars are diverging around zero and the
roll-forward waterfall is drawn from zero with an invisible base (no truncated axis).

### Required caveats for stakeholders
- The data is synthetic: weekly billing has no real trend or seasonality; payment behaviour differs by design.
- Weeks 1–13 are the receivables warm-up; ratios and swings there use shorter windows.

---

## What a week cannot support (not to be shown or claimed)

- Trends, growth or decline from one or two weeks; forecasts; seasonality.
- Category "performance" from one week (median one invoice per category-week).
- A causal link between Suez / Red Sea news and NileGate's week.
- Payment-terms effects (confounded with segment and rating).

---

## Appendix A — Annual facts (from the earlier study, kept for the annual deck, ADR-061)

| # | Fact (2025, as of 2025-12-28) |
|---|---|
| F1 | billing flat (slope p = 0.95); weekly swings are noise |
| F2 | budget gap −34.21 M = volume +0.45 M + ticket −34.66 M (ballast pricing ≈ −21.0 M) |
| F3 | rolling 13-week variance −5.8 % → −17.9 % → −14.0 % (seasonal plan) |
| F4 | Belanor 14.5 % of revenue, 21.2 % of AR, 18.9 % of overdue, 0 % on time |
| F5 | overdue share A / B / C 8.6 / 28.1 / 63.3 %; four B customers pay 25+ days late |
| F6 | customer size vs lateness ρ = −0.03 |
| F7 | 90+ from week 22 to 1.29 M; Korussa 67–100 % from week 26 (3 invoices unpaid at 2026-03-31) |
| F8 | DSO 55.0 = 40.0 terms + 15.0 delinquency (about a quarter) |
| F9 | collecting the top-5 overdue customers → DSO 45.5 (arithmetic) |
| F10 | invoice-month cohorts Jan–Sep stable (on time 32–38 %, within 30 days 80–89 %) |
| F11 | collections lag billing ≈ 4 weeks (weak); Q1 is the warm-up |
| F12 | 19 customers = 80 % of revenue; HHI 516; no reliable concentration trend |
| F13 | 3 duplicate charges, 336.9 k (W10, W15, W50) |

Full numbers: `Data/processed/finance/executive_2025/numbers.json` (`pipelines/scripts/finance/Executive_analysis.py`).
