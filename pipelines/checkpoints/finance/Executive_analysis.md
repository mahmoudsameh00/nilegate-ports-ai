# Final Checkpoint — Executive_analysis (executive financial-intelligence deck, Phase A, 2026-10-31)

**What it proves:** every number the executive deck may show (findings F1–F13 of
`docs/analysis/financial_intelligence/advanced_analytics_findings.md`) is computed from the `finance` views, reconciles
with `kpi_weekly`, respects the as-of date 2025-12-28 (no later payment used), and is frozen in a reviewed snapshot.
Outputs: `Data/processed/finance/executive_2025/` (`numbers.json` + 5 chart series).

| Phase | Step | Result |
|---|---|---|
| 1 | Read the views read-only as `PG_RO_USER` | 1,000 invoices, 52 weeks, 676 week × category, 7,033 snapshot rows, 2,080 week × customer, 3 audit findings, 13 categories / 500 vessels — equal to the reviewed counts |
| 2 | Recompute as-of figures from the invoices | billing 267,892,000.68, AR week 52 40,693,503.44, overdue 11,089,028.88, DSO 55.0 = `kpi_weekly`; 148 payments dated after the as-of date ignored |
| 3 | Revenue and budget (F1–F3) | trend p = 0.95, count dispersion 0.80; rolling 13-week billing inside its noise band in 100 % of weeks; gap −34.21 M = volume +0.45 M + ticket −34.66 M (ballast ≈ −21.00 M, 61 %); largest category volume \|z\| = 1.99 |
| 4 | Customers and credit (F4–F6, F12) | Belanor Tankers 14.5 / 21.2 / 18.9 % of revenue / AR / overdue; overdue share A / B / C 8.6 / 28.1 / 63.3 %; size vs lateness ρ = −0.03; HHI 516 |
| 5 | Receivables (F7–F11) | 90+ from week 22, +32.3 k / week; Korussa 67–100 % from week 26; DSO 55.0 = 40.0 best-possible + 15.0 delinquency (M12); scenarios 55.0 → 48.1 / 45.5 / 41.8 / 40.0; cohorts Jan–Sep mature; billing → cash peak lag 4 weeks |
| 6 | Billing integrity (F13) | 3 duplicate charges, 336,909.00 SDR, all `error` |
| 7 | Save, reload | `numbers.json` reloads equal; 5 CSVs reload with their shapes |
| Final | Reviewed snapshot of the headline numbers | equal; a second run reports `files changed: 0` |

## Problems and fixes
- **A finding corrected by the full computation:** the investigation said the 90+ owner held "88–100 % in every
  week" and that Levavia's week-52 90+ item was unpaid at the horizon. Computed on every week, the 90+ bucket was
  opened by Nilenta Maritime (weeks 22–25, paid in June), Korussa holds 67–100 % only from week 26 (100 % in 20 / 27
  weeks), and Levavia's items cross 90 days and are then paid (week-52 item paid 2026-01-09). The findings, the
  storyboard and the visual list were corrected; the snapshot freezes the corrected values.
- **WoW share:** "52 % of weeks" counted the NULL week 1 in the denominator; over the 51 weeks with a WoW it is 53 %.
- **Budget total in the snapshot:** the first run stopped on a hand-typed budget total; the value was taken from the
  view (302,099,899.07) and reviewed against the rounded 302.10 M of the findings.
- **Leakage:** `fact_invoice.paid_date` runs to 2026-03-31; every as-of figure filters `paid_date ≤ 2025-12-28` and an
  assert guards it.
- **Ballast estimate:** the ballast re-valuation uses category average tickets (tonnage differs by invoice); it is
  reported as an estimate, the volume / ticket split itself is exact (asserted to sum to the gap).
