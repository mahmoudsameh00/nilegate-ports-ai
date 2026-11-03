# Stage2_eval — Final Checkpoint

Script: `pipelines/scripts/agents/Stage2_eval.py` (Agents plan Phase 12, §6d step S5; owner answers of 2026-10-29: the
done-when fixed before any run, two runs on one provider day, values typed from a tool's text reported only, a failed
gate stops and is reported).

## The done-when (fixed 2026-10-29, before any run)
Hard gates in every run: RBAC leakage 0; every Operations twin `partial` (or its allowed `not_permitted`) with the
refused part named and no leak; abstention 100 %; numbers 100 % (no code-check problem on an answered / partial
item); traceability 100 %. Primary: completeness EN ≥ 0.85 and AR ≥ EN − 0.10.

## Steps
1. **Frozen inputs:** the S2 golden set (sha256 `722f3ca3b7bf86f7…`, v2), `route_cases.json`, the pinned watch run
   (sha256 `3164190cbbfa106f…` = every watch item's `watch_sha`); 57 items (44 answered, 10 partial, 3 not_in_data),
   7 askers.
2. **The scorers on hand-made states** (real evidence): a value element is met by tool + args (a watch element by the
   run the tool resolved, since the model never names it) + field + **the row by the tool's own key field in the
   evidence row** (`customer_id`, `invoice_number`, `vessel_category`, `route`, `alert_id`) + the frozen value — the
   Stage 1 scorer's "label up to the first /" would read `234/weather` as `234` and could not match a customers row
   named by id. Six element cases, the twin's refused part (named / unnamed / not refused), its leaks (a refused
   figure in the text, a bound slot of a refused tool), abstention with a number, an untraced slot, Arabic relevance
   with Arabic-Indic digits — each passes its good case and catches its failure; all gates pass on perfect answers.
3. **The harness on fake models** (0 calls): the 33 runnable golden items score 1.0 with their frozen status,
   relevance 1.0, 0 leaks.
4. **Real models:** see the results below.

## Results — first real evaluation (2026-10-29, the baseline attempt)
- **Run 1 complete (57 items, 147 fresh + 25 cached calls, ≈ 694K tokens, 0 fallbacks):** every hard gate passed —
  RBAC leakage **0**, twins **10 / 10** (partial, refused part named, no leak), abstention **3 / 3**, numbers 1.0,
  traceability 1.0; completeness **EN 0.70** (< 0.85: the done-when **not met**), **AR 0.90** (≥ EN − 0.10);
  relevance EN 0.82 / AR 0.90; 1 value typed from a tool's text (reported only). Not fully right: o01 (+ o01_fe,
  o01_ar), o03, o11, o12, c01, c02, c03, c06 (+ c06_ceo), c07, c09.
- **Run 2 stopped at item 28 / 57** (22 answered, 3 not_in_data, 3 validation_failed, 0 leaks): Gemini answered 503
  "UNAVAILABLE" (high demand, not the quota: 254 flash-lite requests used that day) and the Groq fallback refused
  the request as too large → no results file (written only for complete runs); partial results in
  `Notebooks/_scratch/stage2_eval_partial.json`.
- **Why the English completeness is low (run 1, read item by item):** (a) `voyage_status` returns `last_fix` as a
  nested dict and the model cited `last_fix.lat` / `rows[0].amount_sdr` as slots, which slots cannot address → 6 items
  `validation_failed` although their content was right (o01 named BEANR); (b) the cross-product joins: c01 found 2 of
  the 6 alerted vessels, **c07 named the wrong customer** (Belenta Bulk for Thalomar Shipping — a bound figure of
  the wrong row), c09 gave NileGate's total overdue instead of the customer's; (c) route fields: o11 cited the
  Cape − Suez difference (−132,330.83) as "the dues", o12 gave both totals, not the difference; (d) c02 omitted
  "high"; c03 typed the latitude / longitude.
- **Request size (D-P12-5, now measured):** the largest real call was **17,727 tokens** (c01: the customers list +
  the watch result + the skill), 2.5× the S3 estimate (the providers count the tool schemas and the system prompt
  in full) — the Groq fallback (8K TPM) cannot serve the large cross-product questions.

## The baseline (complete, 2026-10-29): `stage2_eval_2026-10-29.json`
Run 2 resumed the same day after Gemini's 503 cleared (`EVAL_FULL=1`; run 1 replayed entirely from the reply cache:
172 cached, 0 fresh — the harness reproduces itself; run 2 58 fresh + 102 cached calls, 0 fallbacks).

| | run 1 | run 2 | mean |
|---|---|---|---|
| completeness EN | 0.6985 | 0.826 | **0.7622** (< 0.85) |
| completeness AR | 0.90 | 0.875 | **0.8875** (≥ EN − 0.10) |
| relevance EN / AR | 0.82 / 0.90 | 0.85 / 0.90 | |
| RBAC leakage · twins · abstention · numbers · traceability | 0 · 1.0 · 1.0 · 1.0 · 1.0 | 0 · 1.0 · 1.0 · 1.0 · 1.0 | every hard gate passed |
| largest call | 17,727 tokens | 20,502 tokens | |

**Done-when: NOT MET** (completeness EN only). Not fully right in both runs: o01 (+ o01_fe, o01_ar), o03, c01, c06 (+
c06_ceo), c07 (+ c07_ar in run 2) — the targets of candidate c1 (plan Progress, C-a…C-d).

## Candidate c1 (complete, 2026-10-30): `stage2_eval_2026-10-30_c1.json` — kept, the baseline now
Run 1 resumed from its reply cache after the daily quota stop (125 cached + 39 fresh calls), run 2 150 fresh + 19
cached, both on 2026-10-30 (the scheduled task, 09:30–09:50 local); 0 fallbacks, 0 failed calls.

| | run 1 | run 2 | mean |
|---|---|---|---|
| completeness EN | 1.0 | 0.9632 | **0.9816** (≥ 0.85) |
| completeness AR | 0.95 | 0.95 | **0.95** (≥ EN − 0.10) |
| relevance EN / AR | 0.9706 / 1.0 | 0.9412 / 1.0 | |
| RBAC leakage · twins · abstention · numbers · traceability | 0 · 1.0 · 1.0 · 1.0 · 1.0 | 0 · 1.0 · 1.0 · 1.0 · 1.0 | every gate passed |
| largest call | 17,463 tokens | 16,783 tokens | |

**Done-when: MET. ADR-052 vs the 2026-10-29 baseline: keep (better)** (no gate regressed; EN +0.2194, AR +0.0625).
Not fully right: o01_ar (both runs), o01 + o01_fe and c07 (run 2) — o01 drops the voyage status word, c07 run 2 the
saving; every other baseline failure (o03, c01, c06, c07 run 1) is right now.

## Problems and fixes
- **The scheduled run's console (2026-10-30):** `tools/run.py` raised `UnicodeEncodeError` printing the ✅ lines to the
  task's cp1252 stdout after the script had finished, so the changed-files report and the exit code were lost (task
  result 1); the results file and `Notebooks/_scratch/run_Stage2_eval.log` are complete.
- **D-P12-9:** the stop after a failed gate covered the hard gates only, so repeat 2 started after run 1's
  completeness gate failed (the owner's answer was: any failed gate stops); fixed — any failed gate of the done-when
  stops the evaluation.
- The "all gates on perfect answers" case first had no Arabic item, so the Arabic gate compared against `None`; the
  case now holds a correct Arabic answer (the gate itself unchanged).
