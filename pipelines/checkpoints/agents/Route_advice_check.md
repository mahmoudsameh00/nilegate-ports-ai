# Final Checkpoint — Route_advice_check (Agents plan Phase 10, 2026-10-27)

**What it proves:** the `route_advice` graph (B Route & Cost Advisor, ADR-057) computes every number of its answer in
code from the Stage 2 tools (= an independent computation), lets the model only choose and explain through number
slots, refuses every planted wrong number and every recommendation that breaks the owner's cost rule, survives a
crash, keeps one thread per question for 30 days, and the real model's advice passes on all frozen cases. Design: plan
§6b (owner decisions P10-1…P10-4), the skill `route-cost-advice` (reviewed by the owner 2026-10-27).

| Phase | Step | Result (2026-10-27) |
|---|---|---|
| 1 | Deterministic nodes (S2) on the 12 cases frozen in `route_cases.json` (rule: lowest-id vessel of category k, band 1 / 3) | 20 route rows = the independent computation (toll from the bands' CSV, fuel from `vessel_performance.csv` + the voyage file, distances from searoute directly); cases 9–10 `no_suez_on_route`, 11–12 `suez_only`; unknown vessel / port → no_data; a hypothetical vessel's toll by hand; the traffic change derived by hand when PortWatch answers |
| 2 | Number slots for routes (S1) | 14 route slots render (nm, kn, t, t/day, days, SDR) and read back as an allowed rounding; 7 bad slots refused; Stage 1 kinds unchanged; a unit written again next to a slot dropped |
| 3 | The Validator (S4) | 64 / 64 planted errors caught on the 8 two-route cases (typed number, unknown field, uncited slot, a news number, a missing evidence id, the dearer route without a risk, an override citing absent context, a money format on a distance); 0 false alarms; overrides by news / a −25 % traffic drop pass, a −10 % drop does not |
| 3s | The skill (S3) | 226 chars, 1,153 tokens (≤ 1,200), 42 named fields all real, 8 example slots render on case 2, the rule sentences present; reviewed by the owner |
| 4 | The graph on FakeRoles + the real PostgresSaver (S4), fake PortWatch / Tavily | 12 cases: 8 ok (8 model calls; case 8 → the Cape), 4 shape answers with no call; patch (2 calls), validation_failed, output_invalid, PortWatch down → ok + "context unavailable", a crash in the advisor resumed with 0 tool calls repeated; check threads deleted |
| 5 | The real model (S5), `writer` role (flash-lite answered) | 8 / 8 advices pass the Validator (S2-D5: route numbers 100 % from tools); first run 11 calls, 3 patches; later runs cached (9 / 9); 0 overrules (no risk in the context) |
| 6 | RBAC, contract, retention (S5) | 100 employees may ask; a probe user below every ceiling → not_permitted before any model call; no user / clock / dataset in a schema; 31 days later: 2 ended threads archived + deleted, the stalled one kept |

Whole run: all phases ✅, pending none, ~40 s, files changed 0 (cached). Regression after the shared changes:
`Deck_check.py` 4 / 4, `Finance_qa_check.py` 6 / 6, `Weekly_pack_check.py` 6 / 7 (real models skipped by design),
`Tools_check.py` 8 / 8, `Scheduler_check.py` 6 / 6. CLI smoke: `Route_advice.py ask --vessel 36 --from SGSIN --to
NLRTM --as 13` → ok, Suez, traced.

## Problems and fixes

1. **The slots were finance-shaped (S1).** Ids `kpi.` / `audit.` / `insight.` and kinds by finance suffixes → the
   `route.` id and four route kinds added (additive; the Stage 1 checks prove nothing else moved). Difference fields
   are named `change_*` so the sign is always written; `_t_per_day` is tested before `_t`.
2. **Tools_check asserted the whole skills catalogue (S3, D-P10-1).** A new skill would have broken Stage 1's check →
   it checks the stage-1 skills only; the stage-2 skill is checked here.
3. **The skill body sat exactly at the 1,200-token cap (S3).** Two sentences trimmed (1,153) so the owner's review
   could change wording without breaking the budget.
4. **A rule sentence wrapped across lines (S3).** The check's text match failed → it compares whitespace-normalised
   text.
5. **PortWatch's ArcGIS service answered 400 "Invalid URL" and timeouts intermittently (S2–S5).** Not our code (the
   same query succeeded minutes apart) → `context_unavailable` as designed; the check marks the live traffic pending
   when it happens and the fake PortWatch of Phase 4 makes the graph test independent of it.
6. **A wrong assertion (S4).** The headline writes totals with `|M` ("0.92 M SDR"), not "917" → the test reads the
   rendered form.
7. **`describe_route_advice` read the employee after the listed prefix (S5).** A narrower prefix made the thread number
   the employee → always the field after `route_advice:`.

## Notes for later phases

- The Validator checks numbers and the decision rule, not the wording of context claims (case 7's headline speaks of
  "regional tensions" with no number): a semantic check of risk claims against the cited news is a possible later step.
- Phase 11 (`voyage_watch`): the synthetic voyages pass intermediate ports without a stop (§6a F2), so a rule-based
  ETA will be nearly exact; the baseline comparison must allow for it.
