# Langsmith_mirror — Final Checkpoint

Script: `pipelines/scripts/agents/Langsmith_mirror.py` · Plan: `docs/plans/Observability_Sentry_plan.md` S2 ·
ADR-062 amendment 1.

## What it does

Puts the frozen golden sets in LangSmith as datasets and every evaluation run as an experiment, so two candidates
can be compared item by item in the UI. It is a view only: the local frozen files (sha256 in git) and the code scorer
stay the acceptance rule (ADR-052); nothing is re-scored, no model is called.

## Steps

1. **Build (0 network)** — three datasets from the frozen files, each named with its file's sha256 prefix
   (`nilegate-finance-qa@5cf72ac3` 42 questions, `nilegate-supervisor-qa@722f3ca3` 57, `nilegate-golden-weeks@7589e7e7`
   11 weeks with their golden findings; the weeks' sha covers `golden_weeks.json` + `golden_findings.json`), so a
   REFREEZE becomes a new dataset. Every results run becomes experiment rows: packs → `golden-weeks` (scores
   published, numbers_ok, planted_recall, narrative_recall, false_alarms, claims_wrong, rewrites), Stage 1 Q&A →
   `finance-qa`, Stage 2 → `supervisor-qa` (completeness, relevance, status_ok, numbers_ok, traceable). Asserted:
   every row id is a dataset example, every score numeric or empty.
2. **Datasets (live)** — created once; an existing one is reused only if it holds exactly the frozen ids.
3. **Experiments (live)** — `client.evaluate` with a target that returns the stored answer and an evaluator that
   returns the stored code scores; metadata = results file, its sha256, run, part, tag, ADR-052 verdict. A results
   file + run already mirrored is skipped.
4. **Read-back (live)** — every experiment found under its dataset with one run per example.

## Problems and fixes

- **A run count below the dataset size on the first read-back** (`stage2_eval_2026-10-30_c1-qa-r2`): LangSmith's
  project stats lag a few seconds behind ingestion; the re-run a minute later read 57 / 57. The phase reports such
  counts instead of failing on them.

## Last run (2026-11-01)

Live: 3 datasets created, 12 experiments sent (base3 × 3, c4 × 3, dp127b × 2, stage2 2026-10-29 × 2, c1 × 2), all
read back; re-run: 3 reused, 0 sent, 12 already mirrored, counts complete. Files changed 0.

## How to use it after an evaluation

```powershell
$env:MIRROR_LIVE="1"; $env:MIRROR_RESULTS="<results file name>"; uv run python tools/run.py pipelines/scripts/agents/Langsmith_mirror.py
```
Then in LangSmith: Datasets & Experiments → the dataset → select two experiments → Compare.
