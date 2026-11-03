# Dependency upgrade plan — close the 2026-11-01 pip-audit findings (ADR-063, THREAT_MODEL LLM03)

Status: **IMPLEMENTED (2026-11-02)** — approved 2026-11-01 (owner, as clickable choices below).

## Implementation record (2026-11-02)

- After the Monday firing (2026-11-02T08:30Z, exit 0, week 13 awaiting approval) the 18 files done in `D:\Project_wip`
  (D-U3) were copied into `D:\Project` — each original first confirmed unchanged since the copy (sha256) — and
  `uv sync --frozen` moved exactly the 9 versions (D-U4).
- Audit 63 advisories in 8 packages → **"No known vulnerabilities found"** (`pip-audit` 2.9.0).
- Checks in `D:\Project`, every one "files changed: 0": Deck 5 / 5, Weekly_pack 6 / 7 (Phase 5 = real models, opt-in
  as always), Tools 10 ✅, Scheduler 6 / 6, Supervisor ✅, Supervisor_tools ✅, Voyage_watch ✅, Monitoring 5 / 6 (Phase 6
  live-only), Stage1_eval ✅ (fake models), Finance_views ✅; lint ratchet ✅ (ruff 48, pyright 276), baseline updated
  (325 → 324).
- Deviations: D-U3 (parallel copy), D-U4 (`langgraph-checkpoint` 4.3.0). Exception to the two-week rule: pyasn1 0.6.5
  and tornado 6.6 (D-U2). Recorded as a note under ADR-063; THREAT_MODEL LLM03 gap closed.
- The copy `D:\Project_wip` is no longer needed (the owner deletes it).

## Findings (2026-11-01, `uvx --from pip-audit==2.9.0 pip-audit` on `uv export --frozen --no-hashes --no-dev`)

63 advisories in 8 packages. Release dates read from PyPI on 2026-11-01:

| Package | Locked | Target (lowest fixing version) | Released | Age on 2026-11-02 | Pulled in by |
|---|---|---|---|---|---|
| pillow | 12.3.0 | 13.0.0 (39 advisories) | 2026-10-16 | 17 d | the project (direct, `>=12.3.0`), matplotlib, python-pptx, rapidocr |
| filelock | 4.0.12 | 4.2.1 (13) | 2026-10-17 | 16 d | huggingface-hub ← tokenizers |
| pyasn1 | 0.6.4 | 0.6.5 (4) | 2026-10-27 | **6 d** | pyasn1-modules ← google-auth |
| tornado | 6.5.10 | 6.6 (3) | 2026-10-21 | **12 d** | ipykernel, jupyter-client |
| certifi | 2026.7.22 | 2026.10.18 | 2026-10-18 | 15 d | httpx, httpcore |
| dnspython | 2.8.0 | 2.9.0 | 2026-10-09 | 24 d | pymongo |
| langgraph-checkpoint-postgres | 3.1.2 | 3.1.3 | 2026-10-12 | 21 d | the project (direct) |
| pymongo | 4.18.2 | 4.18.3 | 2026-10-08 | 25 d | the project (direct) |

## Owner decisions (2026-11-01)

- **D-U1 — versions:** the lowest version that fixes the advisories (patch releases for the two direct pins:
  checkpoint-postgres 3.1.3, pymongo 4.18.3 — not 3.2.0 / 4.19.0).
- **D-U2 — the two young releases:** pyasn1 0.6.5 and tornado 6.6 are taken now although younger than two weeks
  (security fixes) — a recorded exception to ADR-063's two-week rule.
- (Weekly-pack plan, same round: migration 022 applied by Claude after a dry run; candidate c5 runs the morning after
  Phases B–D pass on fake models; the two skill edits reviewed by the owner with the c5 results.)

## Steps

1. Direct pins in `pyproject.toml` through uv: `uv add pillow==13.0.0 langgraph-checkpoint-postgres==3.1.3
   pymongo==4.18.3` (pillow moves from `>=` to `==` like every other pin).
2. Transitive packages in the lock only: `uv lock --upgrade-package filelock==4.2.1 --upgrade-package pyasn1==0.6.5
   --upgrade-package tornado==6.6 --upgrade-package certifi==2026.10.18 --upgrade-package dnspython==2.9.0`, then
   `uv sync`.
3. `uv.lock` compared package by package with the committed one: only the 8 packages may change version (a new or
   changed dependency of theirs is listed and explained; anything else is undone and reported).
4. Audit again: `uv export --frozen --no-hashes --no-dev` → `pip-audit` — 0 advisories, or each remaining one explained.
5. Checks (each must keep **0 files changed**): `Deck_check.py`, `Weekly_pack_check.py`, `Tools_check.py`,
   `Scheduler_check.py`, `Supervisor_check.py`, `Supervisor_tools_check.py`, `Voyage_watch_check.py`,
   `Monitoring_check.py`, `Stage1_eval.py` (fake models), `Finance_views_check.py`; `tools/lint_ratchet.py`.
6. Docs: THREAT_MODEL LLM03 (gap closed), ADR-063 note (the upgrade + the D-U2 exception), ROADMAP; this plan archived.

**Done when:** the audit is clean (or each advisory explained), every check passes with 0 files changed, the lint
ratchet passes, and `uv.lock` changed only as step 3 allows.

## Progress / deviations

- 2026-11-01 — plan written and approved (owner choices above); waiting for the 2026-11-02 firing.
- 2026-11-01 — **D-U3 (owner, "022 دلوقتي + نسخة شغل موازية"): the upgrade is done and checked in a parallel copy
  `D:\Project_wip`** (the project without `.git`, its own `.venv`, `models/` as a junction; a sha256 manifest of the copy
  taken at copy time lists what to bring back). The real `D:\Project` and its `.venv` stay untouched until the Monday
  firing has finished; then `pyproject.toml` + `uv.lock` are copied over, `uv sync`, and the checks re-run there.
  - Steps 1–2 as written. **D-U4 (deviation):** `langgraph-checkpoint-postgres` 3.1.3 requires
    `langgraph-checkpoint>=4.3.0` → a ninth package moves, 4.2.0 → **4.3.0** (2026-10-12), held below 4.3.1
    (2026-10-26, 6 days old) by `uv lock --upgrade-package langgraph-checkpoint==4.3.0`. Its DB migrations are the same
    10 statements as before (identical sha256) and `setup()` is never called by the project → no `agent_state` change.
  - `uv.lock` compared package by package: 0 added, 0 removed, 9 versions changed (the 8 + `langgraph-checkpoint`),
    no dependency list changed. `pyproject.toml`: the three direct pins (pillow `>=12.3.0` → `==13.0.0`).
  - Audit: before **63 advisories in 8 packages** → after **"No known vulnerabilities found"**.
  - Checks on the copy (`tools/run.py`, every one "files changed: 0"): Deck 5 ✅, Weekly_pack 7 ✅, Tools 10 ✅,
    Scheduler 7 ✅, Supervisor 9 ✅, Supervisor_tools 6 ✅, Voyage_watch 9 ✅, Monitoring 5 / 6 ✅ (Phase 6 is live-only,
    as before), Stage1_eval 6 ✅ (fake models), Finance_views 8 ✅; lint ratchet ✅ (ruff 49, pyright 276 ≤ baseline).
