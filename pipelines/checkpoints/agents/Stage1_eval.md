# Stage1_eval — Final Checkpoint

Script: `pipelines/scripts/agents/Stage1_eval.py` (Agents plan Phase 7, §5d steps S5–S6; gates D7 + §8a; acceptance
rule ADR-052).

## Steps
1. **Frozen inputs.** `golden_weeks.json`, `golden_weeks_expected.json`, `golden_findings.json`,
   `finance_qa_golden.jsonl`: hash prefixes asserted, so nothing is scored against an answer key edited after a run.
   Packs run and are approved by the Finance manager with the lowest id (approve only; G5 edit rate = Phase 8).
2. **Scorers proven first** on hand-made decks (the sample slot draft on the frozen evidence, published by hand,
   then changed one way each) and answers (written from the golden elements): every metric passes its good case and
   catches its failure — tampered evidence, an invoice wrongly called a duplicate (clean week 49), LNG wrongly
   called below budget (week 36), a direction word against its sign, a non-driver called a driver, an untraced
   number, a strong word on the flat week 41, a value from the wrong week, a refusal with a number, a level-3 leak,
   an answer instead of an abstention.
3. **Golden weeks with fake models** (0 calls): 11 / 11 published, deck numbers 100 %, planted 5 / 5 in the slide-8
   table of the published PPTX, false alarms 0, claims 100 %, traceability 100 %.
4. **Q&A with fake answers** (0 calls): 38 questions through `finance_qa` (r03 / r04 need live retrieval):
   completeness EN / AR 1.0, abstention 1.0, leakage 0.
5. **Real models** (`EVAL_REAL_MODELS=1`, two repeats, ADR-052): see the plan's Progress for the results and the
   D7 verdict; results file `Data/processed/agents/eval/stage1_eval_<date>.json` (the baseline).

## Metric definitions (as coded)
- Deck numbers: a published deck whose structured evidence equals the frozen evidence, every slot resolves, the
  Validator passed (V8 read-back by the publisher).
- Planted found: the 5 planted invoice errors (D-P7-1) in the slide-8 table text of the published PPTX.
- Narrative recall: the "narrative" findings of `golden_findings.json` met in the Writer's texts of slides 2–8 (a
  slot of the evidence / row / field, or the row named; Suez context = a slide-9 bullet citing a suez_transits
  result).
- False alarms: an invoice named next to an error word that the week's audit did not flag; a named category called
  below budget with variance ≥ 0. Rate = false / (false + right).
- Claims (G1, independent of the Validator): a direction word within 40 characters before a change slot agrees with
  its sign; categories in a "driv…" sentence are in the week's top three.
- Q&A completeness: value elements = a bound slot of the expected tool / arguments / row / field; names, directions
  and facts by text. Relevance = the week number and a metric word in the answer. Abstention: expected refusals with
  the expected status and no number; leakage: a refused item with a number or a level-3 fact.

## Problems and fixes
- Prints were block-buffered into the run log (no progress for 40 min): `sys.stdout.reconfigure(line_buffering=True)`.
- The free tier of flash-lite is 500 requests / day: the first c1 attempt lost its main model mid-run and mixed in
  the OpenRouter fallback (not comparable). The harness now stops a run when a main model's daily quota is gone and
  resumes from the caches the next provider day (D-P7-11); `--timeout 14400` for real runs.
- A Q&A prompt example first quoted the r04 answer itself (a leak of the expected answer into the prompt) — replaced
  by a placeholder before any run.
- Validator false alarms found by the runs (week labels, "week N" rows, month-name dates) fixed with Deck_check cases
  (D-P7-9, D-P7-12).

## Results
- Baseline `stage1_eval_2026-10-19.json`: D7 not met (packs 4 / 11, 8 / 11; planted 2 / 5, 1 / 5).
- c1 `stage1_eval_2026-10-20_c1.json`: ADR-052 keep (better) — planted 5 / 5 both runs, recall 0.69, Q&A EN 0.96 /
  AR 1.0, leakage 0; D7 not met (abstention 0.86, traceability 0.996 in one run). c2 prepared (D-P7-12).
- c2 rejected (2026-10-21); c3 `stage1_eval_2026-10-22_c3.json` accepted by an owner exception (ADR-052).
- **Confirmation run `stage1_eval_2026-10-23_confirm.json` = the final Stage 1 baseline (plan §5f F8):** packs
  7 / 11 · 10 / 11, planted 2 / 6 · 3 / 6 (stopped packs carry no deck), deck numbers / claims / traceability 100 %,
  leakage 0, abstention 1.0, Q&A EN 0.96 / AR 0.95, recall 0.79; D7 not met on `planted_all` only.
- **A scorer false positive found by that run (D-P8-16):** `false_alarms()` counted every invoice number in an error
  sentence, so the original of a flagged duplicate ("INV-9000292 … duplicate of INV-0000292") was an alarm — the
  run's only two alarms were such true sentences. Fixed by rule (the original named beside its flagged duplicate is
  not called wrong) with two Phase 2 cases (`duplicate_with_original`, `duplicate_with_other`); the results file is
  kept as scored.

## The qa scope (D-P12-7, 2026-10-30)
- **Why:** the owner changed the Stage 1 skill `finance-qa` in Phase 12 (the supervisor's partial-answer exception),
  so by ADR-052 it is a Stage 1 change. It reaches only the Q&A agent, so running the 11 packs again would cost
  hundreds of requests to measure nothing that changed.
- **What:** `EVAL_SCOPE=qa` skips the packs; a run is complete with its 42 answers; its gates are the ones the Q&A
  can fail (`traceability_100`, `rbac_leakage_0`, `abstention_recall_100`), its primaries `qa_completeness_en` /
  `qa_completeness_ar`; D7 is not judged (it needs the packs). `adr052()` compares only the gates and primaries the
  candidate measured. The default `all` behaves as before.
- **Proof at 0 calls:** a setup step on `stage1_eval_2026-10-23_confirm.json`: its own Q&A view = a tie, EN completeness
  0.90 = reject, a leak = `rbac_leakage_0` regressed, AR 1.0 = keep (better). Phases 1–4 re-run ✅, 0 files changed.
- **The run:** `EVAL_REAL_MODELS=1 EVAL_SCOPE=qa EVAL_TAG=dp127 EVAL_BASELINE=stage1_eval_2026-10-23_confirm.json`
  (fresh caches `llm_cache/eval_dp127_r1|r2/`), scheduled for 2026-10-31 09:30 local.
- **Result 1 (`stage1_eval_2026-10-31_dp127.json`, 162 calls): reject** — run 2's a01 ("week 12 of 2024") answered
  with 2025-W12's billing, so `rbac_leakage_0` (a refusal with a number) and `abstention_recall_100` regressed; a01
  had passed all 12 earlier runs.
- **Fix (D-P12-12, owner):** `finance_qa.check_answer` refuses a bound `finance_kpi` / `invoice_audit` figure when the
  question names a year other than 2025 (Western or Arabic digits; the supervisor passes the user's own question as
  `asked`); Phase 2 gained the cases (2024 and ٢٠٢٤ refused, 2025 passes); `Supervisor_check.py` a finance 2024 answer
  refused, a Suez 2024 answer passes.
- **Result 2 (`stage1_eval_2026-10-31_dp127b.json`, 160 calls): keep (better)** — no gate regressed, completeness EN /
  AR 1.0 in both runs; a01 in run 2 took one rewrite (3 calls) after the guard refused the 2025 figure.

## Candidate c4 — the planted findings reach the deck (2026-10-30, coded; compared 2026-11-01)
- **Why:** in the final baseline the code found every planted error, but 2 / 6 · 3 / 6 reached a deck: a pack whose
  Writer failed its two rewrites stopped with no deck (slide 8's code audit table lost with it), and the budget miss
  depended on the Writer saying it.
- **What (ADR-051 amendment 3):** the pack's code `fallback` replaces only the failing texts and validates again
  (`degraded` shown to the approver); slide 5 gets a code budget-miss table (M9a: budget ≥ 1 M SDR, ≤ −25 %).
- **Harness:** `EVAL_SCOPE=packs` (pack gates `deck_numbers_100`, `planted_all`, `false_alarms_le_5pct`,
  `claims_100`, `traceability_100`; primary narrative recall), `EVAL_C4=0` = the before side (`use_fallback=False`, no
  table); the scorer also finds a planted budget miss in slide 5's `tbl:budget_miss`.
- **Phase 3c (0 calls):** a fake Writer that never passes (a typed wrong number, patches that change nothing, no
  budget-miss sentence): with c4 11 / 11 decks, every one degraded with summary bullet 0 replaced, planted 6 / 6
  (t36-b from the table), deck numbers / claims 100 %, false alarms 0; before c4 0 / 11, 0 / 6. The rule names a
  category only in test week 36 (LNG) across the 11 golden weeks.
- **The live comparison:** 3 runs `base3` (before) + 3 runs `c4`, packs only, one provider day (2026-11-01).
- **Result (task "NileGate Stage1 c4 eval (once)", 09:30, exit 0):** `stage1_eval_2026-11-01_base3.json` — published
  8 / 11 in each run (2–3 `validation_failed`, 1 `output_invalid`), planted 2 / 6 · 3 / 6 · 0 / 6, narrative recall
  0.7471, false alarms 0; `stage1_eval_2026-11-01_c4.json` — published 11 · 10 · 11 / 11 (the one miss
  `output_invalid`, which the fallback does not cover), **planted 6 / 6 in all three runs**, narrative recall 0.9655
  (+0.2184), deck numbers / claims / traceability 100 %. As scored: ADR-052 **reject** — `false_alarms_le_5pct`
  regressed in run 1 (0.25: live week 15).
- **A scorer false positive, again (D-C4-1):** that one sentence — "The flagged duplicate invoice under Chemical
  Tankers & Other Liquid Bulk Tankers matched original invoice INV-0000491." — is **true** (INV-0000925 duplicates
  INV-0000491, both Chemical Tankers, 73,950.26 SDR; golden finding l15-a). D-P8-16's rule exempted the original only
  when the duplicate's own number was in the sentence; here the duplicate was only described. Hand-checked: **real
  false alarms 0 in all six runs** → no gate regressed; owner (2026-11-01): **c4 accepted** on the hand-check, the
  results files kept as scored (not re-scored, as D-P8-16). Fix: `false_alarms()` also exempts the original of a
  flagged duplicate when the sentence calls it the original (`ORIGINAL_WORDS`: "original", "الأصل"); Phase 2 gains
  `original_named_as_original` (0) and `original_called_duplicate` (an original called a duplicate is still 1) →
  Phases 1–4 + 3c ✅, 0 files changed.
