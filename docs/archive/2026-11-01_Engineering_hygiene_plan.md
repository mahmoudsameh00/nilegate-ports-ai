# Plan — Engineering hygiene: lint + types + CI, security, diagrams

## Implementation record (read this first)

- **Status: IMPLEMENTED (2026-11-01)** — approved and done the same day (owner: "Engineering hygiene (Recommended)"
  and "pyright (Recommended)", after "مش عايز استنى كل شوية": one round of choices, then the whole task); archived
  the same day. It ran while `docs/plans/Observability_Sentry_plan.md` waited for Monday's check-in, so it was kept
  out of `docs/plans/` (one active plan).
- **Results:**
  - **H1 lint + types + CI:** `ruff==0.17.1`, `pyright==1.1.414` (+ `nodeenv`) as uv dev tools (lock: those 3 added,
    0 versions changed); `pyproject.toml` `[tool.ruff]` / `[tool.pyright]`; `tools/lint_ratchet.py` +
    `tools/lint_baseline.json` (325: ruff 49, pyright 276) — proved by a planted unused import (exit 1, "NEW ruff F401");
    `.github/workflows/ci.yml` (ratchet, `Monitoring_check.py`, `Langsmith_mirror.py` Phase 1).
  - **H2 security:** `.github/dependabot.yml` (uv + GitHub Actions, weekly); `pip-audit` on the locked runtime set:
    **63 advisories in 8 packages** (pillow 39 → 13.0.0, filelock 13 → 4.2.1, pyasn1 4 → 0.6.5, tornado 3 → 6.6,
    certifi → 2026.10.18, dnspython → 2.9.0, langgraph-checkpoint-postgres → 3.1.3, pymongo → 4.18.3);
    `docs/THREAT_MODEL.md` (OWASP LLM Top 10 2025 + OWASP Agentic AI threats T1–T3, T5, T8, T10, T11).
  - **H3 diagrams:** `ARCHITECTURE.md` §1.1 — the system, `weekly_pack`, `route_advice` + `voyage_watch`, the
    supervisor, in Mermaid, with the branch conditions read from the graph code; the stale overview lines (supervisor
    "PLANNED", "no Q&A step") corrected.
- **Deviations / decisions (recommended options, logged):** (1) a **ratchet** instead of fixing the findings now — 68
  pyright errors are in `weekly_pack.py`, which the scheduled pack runs on 2026-11-02 10:30; (2) the ruff rule set is
  bug-focused (E4 / E7 / E9 / F / B) with the project's script idioms ignored (from 490 findings to 49); (3) **no
  dependency upgrade today** for the same reason — one upgrade change with the full checks after Monday's firing;
  (4) Claude could not delete the ratchet's probe file: `tools/_ratchet_probe.py` holds only a comment — the owner
  deletes it.
- **Lasting decisions:** ADR-063.
- **Next (follow-ups):** the dependency upgrade (closes THREAT_MODEL LLM03); pay down the baseline file by file
  (`weekly_pack.py` first, after the weekly-pack Phases B–E); prompt-injection items in the next frozen golden set
  (LLM01); the first CI run when the owner pushes.

---

- **Status (original):** APPROVED 2026-11-01 as the ROADMAP's "engineering hygiene" item (owner 2026-10-30: free
  tools only, no paid plan).
- **Scope (from the ROADMAP):** (H1) ruff + a type checker + GitHub Actions running what needs no database; (H2)
  Dependabot + `pip-audit` + `docs/THREAT_MODEL.md` (OWASP Top 10 for LLM / Agentic applications → control or gap);
  (H3) Mermaid diagrams in `ARCHITECTURE.md`: the overview and the four graphs.
- **Constraints:** nothing that changes the behaviour of the code the 2026-11-02 scheduled firings run; Claude never
  runs git (the owner pushes, which starts CI); dependencies only through uv, pinned, at least two weeks old.
