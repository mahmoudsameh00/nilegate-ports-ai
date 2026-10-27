# Final Checkpoint — Deck_check (Agents plan Phase 6, 2026-10-19)

**What it proves:** the weekly deck of `pipelines/agents/deck/` — number slots, the Validator v2 that binds every
number to its field, the NileGate PPTX and its read-back (V8) — writes only numbers the tools returned, in the
allowed form, under the right name, and catches every planted wrong number in a test deck (the §5 done-when). Design:
plan §5c (owner decisions P6-1…P6-8), ADR-051.

| Phase | Step | Result (2026-10-19) |
|---|---|---|
| 1 | Slots (S1) | 39 text cases: 24 rendered (money as returned / M / k, percent 2 / 1, days, counts, public numbers; half away from zero; changes signed; `\|dir` up / down / unchanged; result totals; the audit invoice/check key), 15 refused, each message the fix (a wrong dataset names the result that has the field; a missing row gives the slot by key); the real evidence of weeks 10 + 23: 905 values, 1,820 formats + 396 `\|dir` rendered and read back by the Validator's own parser, 0 refused |
| 2 | 52 clean decks (S2, S3) | the slot Writer of `deck/sample.py` (16 bullets a week, 1,285 slots) passes V1–V7 on 52 / 52 weeks as slots and as literal text; the 52 rendered PPTX pass V8 (10 slides, 3 native charts, the tables of the week, the warm-up footnote on weeks 1–13 only); previews of weeks 10 / 23 for the owner |
| 3 | Planted wrong numbers (S2, S3) | **100 / 100 caught** where planted with the expected rule: 17 draft classes (digit, sign flipped / dropped, cut, × 100, k for M, another field / row / dataset, direction flipped, non-driver, unknown invoice, web number; slots on another field / row / dataset / slide) + 8 file classes (table cell, chart point, template text, "Approved" in a draft, KPI tile, Writer text, a box added, a shape deleted) × weeks 5 / 10 / 23 / 49 |
| 4 | Real failures replayed (S2, S6) | the 10 Phase 5 bullets: 8 now bind (a direction word carries the sign), the "no subject" and wrong-dataset bullets still refused; every finding of the five Phase 6 real runs: the recorded text refused with the expected rule and message, the fixed text passing (row by position, a total on one invoice, units / directions written twice, a NileGate figure on the context slide, the deck title on slide 1, two false alarms fixed) |

The real models run in `Weekly_pack_check.py` Phase 5 (not twice).

## Problems and fixes
- **Category names contain "/"** ("Roll-On/Roll-Off (Ro/Ro) Vessels"): row keys are never split; a key matches the
  first key field or all key fields joined (`INV-0000626/duplicate_charge`).
- **The literal form had 40 weeks of false alarms at first:** "…SDR, down 12.3 %" gave "down" to the number before
  it. Windows never cross a clause; after a number only comparatives count; a direction word signs a change only.
- **A failed slot was read as digits** ("|%1" → "1"): failed slots are blanked before literals are read.
- **python-pptx's reversed category axis** moved the value axis to the top: the bars are drawn smallest first.
- **Layout bugs only a picture shows** (a column too narrow for "+167.6 %", a footnote over the sources table):
  every layout change is checked on PowerPoint's PNG export.
- **A unit doubled behind a hyphen (2026-10-27, W12):** "{…dso_window_days|d}-day window" rendered "82 days-day
  window" — `normalize_text` knew only a spaced unit. It now drops the unit behind a hyphen too; Phase 4 replays the
  W12 sentence (one fix, passes, "82 days window").
