# Supervisor_check — Final Checkpoint

Script: `pipelines/scripts/agents/Supervisor_check.py` (Agents plan Phase 12, §6d step S3; owner answers of
2026-10-29: the router drops the tools a user may not use, the `load_skill` tool, the new skill `supervisor-qa`, the
D-P12-2 code rule). FakeRoles + the real tools; 0 real model calls, 0 Open-Meteo calls; PortWatch / Tavily answered by
a mock transport; the route-advice threads it opens deleted at the end (also on a failure).

## Code checked
- `pipelines/agents/graphs/supervisor.py` — the router (`route`: 12 rules in English + Egyptian Arabic, the bridge
  after the finance tool, a default set of operations / public tools), the access split (`TOOL_RESOURCES`, a refused
  tool never offered, every part refused → `not_permitted` with no model call), `check_supervisor_answer`, the agent
  (`create_agent` + `SupervisorTurn`: brief, routed tools only, ≤ 5 tool rounds, a tool-call guard, the code check,
  one patch; `ModelCallLimitMiddleware` 11), `ask`.
- `graphs/models.py` `SupervisorAnswer` (+ `partial`); `deck/slots.py` (`route_advice` keyed by `route`,
  `watch_alerts` by `alert_id`); the skill `pipelines/agents/skills/supervisor-qa/SKILL.md` (1,096 tokens, stage 2,
  `reviewed_by_owner: no` — the owner reviews it before S5).

## Steps
1. **Router** on the 57 golden items: every `tools_needed` routed (recall 100 %), mean 2.67 / max 5 tools; the
   refused part = the frozen `refused_any.tools` on the 10 Operations twins, empty on the others; an unmatched
   question → the default set; an Operations employee's finance-only question → nothing offered, `finance_kpi`
   refused; an Operations manager is refused nothing. `TOOL_RESOURCES` = the tools' own answer on 88 calls (11
   role / department profiles × 8 local tools).
2. **`check_supervisor_answer`** on real evidence: 6 right answers (an ETA, a route, a partial answer, the watch rows
   by `alert_id` incl. `fleet`, Arabic, a customer id from a cited row) pass with 0 problems; 10 / 10 planted errors
   caught (a typed figure, an unknown id, a partial answer that does not name the refused part, `answered` while a
   part is refused, a toll stated as an invoice in English and in Arabic (D-P12-2), a wrong row key, Arabic-Indic
   digits typed, `partial` with nothing refused, an id no cited row holds).
2s. **The skills (owner review 2026-10-29):** `supervisor-qa` (1,176 tokens, 22 names, 3 example slots) and
   `finance-qa` (1,105) within budget; every backticked name a real tool / argument / field / row label / status /
   skill; every example slot a field of a real result; the rules stated; the review's two changes checked — an
   Egyptian Arabic example with a slot, and `finance-qa`'s exception for the supervisor's partial answer; both
   `reviewed_by_owner: 2026-10-29`.
3. **The agent end to end** on scripted fake models for the 33 runnable golden items (30 with value elements + 3
   abstentions): the frozen status and every frozen value bound (27 answered, 3 partial, 3 not_in_data), `load_skill`
   on half of them, `route_advice` running inside (its writer played by the same script); patch → answered; twice
   bad → `validation_failed`; a model that never answers → `output_invalid` within the call limit.
4. **RBAC inside the agent:** an Operations employee's c06 twin — `finance_kpi` not offered; a model that calls it
   anyway gets `not_permitted` from code and the finance function runs 0 times; the toll is answered → `partial`; a
   question refused in every part → `not_permitted` with no model call.

5. **The CLI `Ask.py` (S4):** `Ask.answer` on fake models with the real PostgresSaver at a check clock
   (2026-09-12T23:59Z, so the check's threads never meet a real question): English, Egyptian Arabic, a partial answer
   and an all-refused question → 4 ended threads `ask:<employee>:20260912T2359Z:<n>` (the refusal stored as an ended
   thread, 0 model calls); `show` = the stored answer for the asker and the CEO, refused to another employee; `list` =
   one's own questions (the CEO: all); the 30-day retention keeps them fresh, archives then deletes them aged; a trace
   read back from LangSmith (`entry:ask`, `graph:supervisor`, `lang:en`, `launched_by:check`).

## Problems and fixes
- **`durability="sync"` without a checkpointer** fails in langgraph 1.2.14 (`SyncPregelLoop` has no
  `_put_checkpoint_fut`): `supervisor.ask` passes it only when the graph keeps checkpoints.
- **A refused-in-every-part question never runs the graph**, so nothing would be stored: it is written with
  `update_state(..., as_node="SupervisorTurn.after_model")` + `jump_to: end` → an ended thread (`next = ()`) that the
  retention treats like any finished question (tried first: `__end__` does not exist as a node, `model` leaves the
  thread mid-run).
- **D-P12-5 — request size on the Groq fallback:** the first measure (≈ 9,614 est tokens) came from the fake model
  asking every ranked finance list at `limit=50`; at the tool's default limit (10 rows — every row the golden items
  need is in the top 10) the largest request is ≈ 6,969 est tokens (c10: the weekly row + the whole watch result).
  `est_tokens` counts 3 characters a token (conservative); at 4 (English JSON) every request fits Groq's 8K minus the
  1,500 output reserve. Recorded, nothing changed; the real runs of S5 show the providers' own counts.
- The first rogue model of Phase 4 never fetched the toll, so its `partial` was rightly rejected (the only
  structured result was a refusal → the base check demands `not_permitted`); the rogue now fetches the toll.
- The no-model-call check first compared the number of roles called, not the calls; it now sums the calls.
- The "≥ 40 runnable items" guess was wrong: 30 golden items carry value elements; the snapshot says 33.
