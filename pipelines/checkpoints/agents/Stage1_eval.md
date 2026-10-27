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
