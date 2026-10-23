---
name: suez-toll-audit
description: How NileGate's Suez transit invoices are priced (progressive toll bands) and how to read, rank and act on invoice_audit findings (duplicate charge, tonnage, amount, rate). Load before reporting invoice exceptions.
stage: 1
reviewed_by_owner: 2026-10-22
---
# Suez toll audit

## How an invoice should be priced (ADR-004)
- Dues = Σ rate × tons **inside each band** of the vessel's category and condition (Laden / Ballast): progressive,
  like tax brackets; the terminal band holds the last ton. Special Floating Units are always priced Laden.
- Tonnage = the vessel's Suez Canal Net Tonnage (SCNT). Money in SDR.
- `compute_toll` gives the correct amount with its band-by-band breakdown; use it to explain a finding, never to
  invent one.
- **Tariff Notes:** ballast product tankers' Crude Oil ballast rates are already in the bands. A ballast chemical
  tanker billed at the Crude Oil ballast toll may be right (if it is an oil / chemical tanker): `review` =
  `manual_review` — report it "for manual review", never as an error or money at stake. No OBO category.

## What `invoice_audit` checks (each row = one finding; no row = the invoice passed)
| check_code | Meaning | Typical action |
|---|---|---|
| `duplicate_charge` | same vessel, date and amount under another number (`duplicate_of` = the original); a vessel cannot transit twice a day | void it; if paid, credit note / refund |
| `tonnage_mismatch` | invoice SCNT ≠ the vessel's SCNT | correct the tonnage |
| `amount_mismatch` | billed ≠ the progressive toll (> 0.01 SDR) | corrected invoice for `difference_sdr` (credit if > 0, supplement if < 0) |
| `rate_mismatch` | stored rate ≠ the terminal band's rate | correct the rate |

`probable_cause` of an amount mismatch (the first hypothesis that reproduces the billed amount):
- `flat_terminal_rate` — every ton billed at the terminal band's rate instead of progressively.
- `condition_swapped` — priced as Ballast instead of Laden, or the reverse.
- `sfu_priced_ballast` — a Special Floating Unit priced as Other Vessels / Ballast.
- `billed_on_invoice_tonnage` — priced on the wrong tonnage written on the invoice.
- `notes_crude_ballast_rate` — the tariff Notes case above (manual review).
- `unexplained` — none of the above: say so and ask for a manual review; do not guess a cause.

## How to report findings
- Order by amount at stake (`difference_sdr`, largest |value| first). `difference_sdr` > 0 = overbilled (the
  customer is owed money), < 0 = underbilled (NileGate is owed money). Report both directions.
- Quote the numbers exactly as returned: `billed_sdr`, `expected_sdr`, `difference_sdr`, `amount_at_stake_sdr`,
  `invoices_checked`, `invoices_flagged`. Cite the view and filter of the result's `source`.
- The total at stake is `amount_at_stake_sdr`; never add the rows yourself (one invoice can carry two findings).
- A `tonnage_mismatch` with `difference_sdr` 0 is a data error, not a money error (the amount is right): list it
  separately as "records to correct", not among the amounts at stake.
- Use the `evidence` text to explain in one sentence why the invoice is wrong.
- A week with no finding is good news: say "N invoices checked, none flagged".
- If the result's note says "evaluation copy with planted errors", the run is an evaluation (set by the system,
  never by you): report the findings the same way, they are not NileGate's invoices.

## Known findings in the real invoices (reviewed 2026-10-18)
Three duplicate pairs, both copies paid: INV-0000626 (of INV-0000293, week 10), INV-0000925 (of INV-0000491,
week 15), INV-0000630 (of INV-0000262, week 50). Real exceptions, not tool errors: report them like any other.
