# Final Checkpoint — Executive_deck (executive financial-intelligence deck, Phase C, 2026-10-31)

**What it proves:** the executive deck `reports/executive/2025/NileGate_2025_Financial_Review.pptx` (git-ignored, like
every pack under `reports/`; rebuilt by the script) carries only numbers written from `numbers.json`, every one
registered by a formatter, and a read-back of the saved file finds no unregistered number.

| Phase | Step | Result |
|---|---|---|
| 1 | Read `numbers.json`, `customers.csv`, the 13 chart PNGs | present |
| 2 | Build 17 slides with speaker notes: cover, summary (8 KPI tiles + 3 messages), 8 finding / decision slides, appendix A1–A7 | 13 charts, 2 native tables, stat callouts, an action band per finding slide |
| 3 | Read back the saved file | 129 numeric tokens (after the review), 0 unregistered; every picture has alt text; no year with a thousands separator; headline numbers on slides 2, 5, 6, 7, 8; 17 slides, 13 pictures, no shape off the page |
| Final | Summary asserted | pass; the pptx skill's `validate.py`: all validations passed |

Slide plan vs the storyboard: the 10 main slides follow it; the appendix grew from 4 to 7 because the category split
(V4), the aging heatmap (V7) and the segment shares (V6b) moved out of the main slides to keep one message per slide.

## Problems and fixes
- **Years printed as "2,025" / "2,026"** (the count formatter adds thousands separators). Found on the preview; the
  provenance check could not see it (the token normalises to 2025). Fixed with a year formatter `yr()` and an assert
  that no `20,dd` year reaches the deck.
- **Two-line titles** needed ≈ 0.95 in at 26 pt in a 0.9 in box → the title box starts at 0.3 in and is 1.1 in tall.
- **A finding corrected:** the storyboard said rating B "hides two of our slowest payers"; the build computes four B
  customers paying 25+ days late on average (Belanor, Nilomar, Dalavia, Cyravia). Title and findings updated.
- **Visual QA without PowerPoint automation:** exporting slides through PowerPoint (COM) was not permitted in this
  session and LibreOffice is not installed; slides were checked with an approximate preview renderer (PPTX geometry +
  Calibri metrics + the chart PNGs, a scratch QA aid) and a text-fit report: 0 issues after the fixes. Real
  PowerPoint rendering is the owner's review.
- **Review of 2026-10-31 (owner: "consider every point and defect we found, and review"):** (1) double rounding —
  numbers.json stored percentages with 2 decimals and the slide rounded again (27.2502 → 27.25 → "27.2 %"; the
  findings said 27.3 %): numbers.json now keeps 4 decimals and the formatters round half up once; (2) two data facts
  were typed as literals through `n()` (148 payments ignored, the B tail of 45 days) and one claim had no number ("some
  C pay more than 90 days late"): all three now come from numbers.json (`meta.payments_after_asof`,
  `F5.b_late_max`, `F5.c_late_over_90` = 6) and the payments horizon date from `meta.payments_horizon`; `n()`'s
  docstring states the rule; (3) slide 7 title "almost all of it" → the measured "88 %"; (4) slide 8 notes now say the
  top-5 scenario includes the 1.13 M still unpaid at the horizon (least certain); (5) audit table category names = the
  charts' short names; (6) alt text on all 13 pictures, asserted on read-back; (7) the V8 legend said "dispute" (an
  inference) → "unpaid at 2026-03-31" (a fact); (8) `EXEC_DECK_OUT` lets the deck be built elsewhere while the
  published one is open in PowerPoint (Windows locks it).
- **Charts are pictures, not native charts:** chosen for the waterfall, heatmap and labelled bubble chart that native
  python-pptx charts do not draw well; the numbers stay traceable through `numbers.json`. Native charts are a possible
  later step.
