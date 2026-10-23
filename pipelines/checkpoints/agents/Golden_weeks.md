# Golden_weeks — Final Checkpoint

Script: `pipelines/scripts/agents/Golden_weeks.py` (Agents plan Phase 7, §5d step S1; acceptance rule ADR-052).

## Steps
1. **Rules → weeks.** The §5d rules, fixed before any run, applied to `finance.kpi_weekly`, `finance.invoice_audit`
   and IMF PortWatch (weekly sums of daily Suez transits, ISO weeks of 2025). Each live rule orders the weeks by its
   criterion and takes the first one not taken (ties → lowest week); change / level rules use weeks 14–52 (1–13 =
   warm-up, covered by week 5). Result (frozen in `Data/processed/agents/eval/golden_weeks.json`, sha256
   `ea13800db38c1a96…`):

   | Week | Dataset | Seen | Rule (value) |
   |---:|---|---|---|
   | 10 | test | seen | answer key: planted errors (wrong band rate, SCNT digit swap) |
   | 23 | test | seen | answer key: planted errors (laden / ballast swap, duplicate) |
   | 36 | test | unseen | answer key: planted errors (SFU priced ballast) + the budget miss (LNG × 1.5) |
   | 49 | test | seen | answer key: clean week (false-alarm check) |
   | 5 | live | seen | warm-up week (fixed) |
   | 48 | live | unseen | peak: max billed_sdr (7,126,037.19) |
   | 41 | live | unseen | quiet: min \|billed_wow_pct\| (−0.33) |
   | 16 | live | unseen | trough: min billed_sdr (2,934,677.21) |
   | 47 | live | unseen | live budget miss: min budget_variance_pct (−47.01) |
   | 15 | live | unseen | a real duplicate charge (INV-0000925 of INV-0000491) |
   | 24 | live | unseen | Suez transits moved most: max \|WoW\| (+17.08 %) |

2. **Expected evidence.** The pack's own evidence calls (`weekly_pack.kpi_evidence` / `audit_evidence`, as the CEO)
   per golden week. Live weeks: complete. Test weeks: their KPI evidence needs the twin views of migration 017 (S2) —
   pending; a draft is written to `Notebooks/_scratch/` and `golden_weeks_expected.json` is frozen only when all 11
   weeks are complete. The 5 planted invoice errors are in the test audit evidence; week 49 has none.
3. **Expected findings** (`Data/processed/agents/eval/golden_findings.json`): written by hand from the evidence, each
   with where it must appear (code table vs Writer narrative) — DRAFT for the owner's review, frozen after it.

## Problems and fixes
- PortWatch serves ≤ 1,000 records and the tool ≤ 120-day windows: the year is read in four windows (2024-12-23 →
  2025-12-28, one extra week as the base of week 1's WoW); settled windows are cached forever (first run: one cache
  file changed, later runs 0 calls).
- Week numbers 10 / 23 / 36 / 49 are taken by the test weeks, so a live rule never picks them (more variety; the live
  duplicate week 10 is skipped for 15).
- 2026-10-22 (plan §5f F3, owner D-P7-1): migration 018 made test week 36's LNG budget a real miss, so the frozen
  evidence changed. A frozen file is now re-frozen only through `REFREEZE` — the file's current sha256 must start with
  the prefix named there, with its reason (one transition; afterwards the guard holds again, proven by a second run:
  0 files changed). `golden_weeks_expected.json` `bb3b1a3bd8cf178c…` → `7909ccfb0d2385b0…`; the script reads answer
  key v2 and asserts the miss's variance (−33.33 %) in the frozen evidence. Findings v3 (`golden_findings.json`
  `dc6e32484944798a…`): t36-b is the planted miss (planted = 5 invoice errors + this miss).
