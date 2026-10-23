# Final Checkpoint — Finance_qa_check (Agents plan §5f F2, 2026-10-22)

**What it proves:** the finance Q&A agent, rebuilt on LangChain `create_agent` (owner decision D-P7-6), keeps the
contract of the Phase 7 graph — the llm.py cache / quota / fallback on every call (through `RoleChatModel`), the
run context in the tools (RBAC, ADR-006 / ADR-049), the `QaAnswer` with number slots, the code check
`check_answer` and one patch — and the operator CLI `Finance_qa.py` (plan §5f K6). Fake models only; the real
Stage 1 tools.

| Phase | Step | Result (2026-10-22) |
|---|---|---|
| 1 | Answer paths | a plain-text reply → the adapter asks `structured` for the QaAnswer → answered ("NileGate billed 8.39 M …", week 23); the model calling the answer tool itself → answered without a structured request; two invalid answers → output_invalid with the stop reason |
| 2 | Middleware | the answer brief (language, evidence ids, slot rules) on every request — "none yet" before a tool ran, `insight.c1` after; tools per call: Stage 1 + the answer tool for 3 rounds, then only the answer tool |
| 3 | Check + patch | a typed "8.99 M SDR" → refused → the patch message in the history → the slot answer → answered (patches 1, no problem left); typed twice → validation_failed |
| 4 | RBAC (real tools) | an Operations employee asking for receivables: `finance_kpi` returns not_permitted → status not_permitted, no bound number; an "answered" over the refused tool → patched → validation_failed |
| 5 | Limits + records | an answer tool called with invalid arguments every time → `ToolStrategy` sends the error back each time → the model-call limit (8) ends the run → output_invalid; `calls` (evidence id → tool + args), `llm_usage` (node `qa_agent`) and a slot-form fix (a count format on money → M) recorded |
| 6 | CLI | `Finance_qa.answer` on fake models → status, filled answer, evidence (tool, status, source), problems, model calls; untraced without a key |

## Problems and fixes
- First run: an expected value was the test copy's week 23 (8.99 M); live week 23 is 8.39 M — the expectation fixed.
- Phase 5 found a bug in the new agent: the `after_model` check validated the answer tool's arguments itself and
  crashed on invalid ones before `ToolStrategy` could send the error back to the model. Fix: invalid arguments are
  left to `ToolStrategy` (its retry counts toward the call limit). 6 / 6 at the next run.
- Real models after the check (2026-10-22, 6 flash-lite calls, traced): "How much did we bill in week 23?" (Finance
  employee 13) → answered in 2 calls (the model called the answer tool itself); an Egyptian Arabic question on week
  49's overdue invoices (Finance employee 24) → answered (its wording closer to Modern Standard Arabic — measured by
  the confirmation evaluation, F8); an Operations employee asking for receivables → not_permitted, no number.
