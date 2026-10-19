# Final Checkpoint — Tools_check (Agents plan Phase 4, 2026-10-18)

**What it proves:** each Stage 1 tool (`pipelines/agents/tools/`) returns exactly its governed source, refuses what
ADR-006 forbids with no data, degrades to "context unavailable" instead of guessing, and the six Stage 1 skills
parse within their budgets and agree with the code they describe. Design: plan §5a (owner decisions P4-1…P4-8).

| Phase | Step | Result (2026-10-18) |
|---|---|---|
| 1 | Foundation: read-only pool, user lookup, run context, `ToolResult` guards | session read-only as `PG_RO_USER`; 100 users = an independent query; no-context calls refused; `ToolRuntime` hidden from schemas |
| 2 | `compute_toll` vs the 1,000 stored invoices | amount (≤ 0.005 SDR), terminal band and rate: 0 differences; SFU priced Laden; 5 bad argument sets refused |
| 3 | `finance_kpi` vs its views (`SELECT *` on a plain connection) | 52 weeks × 5 datasets equal; hand weeks 5 / 16 / 23 / 49 equal; Σ categories = billed; column lists = the views |
| 4 | `invoice_audit` (migration 015 views, applied 2026-10-19) | test copy 5 / 5 with the right causes, false alarms 0 (week 49 clean); live = the 3 reviewed duplicates; = an independent Python auditor on both datasets; the wrapper takes live / test from the run context |
| 5 | `search_documents` wrapper | = the library (same chunks, no rerank); 8 / 8 golden RBAC cases; passages marked untrusted; backend failure → context_unavailable; an RBAC violation still raises |
| 6 | External tools (offline MockTransport, then live) | cache hit 0 requests; settled (2025) never expires, recent windows after 24 h; timeout / 500 / non-JSON / wrong shape / ArcGIS error / missing key / Tavily 432 → context_unavailable, nothing cached; key only in the header. Live PortWatch week 23: 7 days, 34.3 transits / day. Live Tavily (2026-10-19): ok, 2 results |
| 7 | RBAC matrix | 100 employees × 7 tool calls = ADR-006 (72 role-`employee` users outside Finance denied the finance tools), leakage 0; no user / dataset field in any model-facing schema; calls without a run context refused |
| 8 | Skills | 6 parse (description 189–231 chars, body 814–1,164 tokens ≤ 1,200); 6 broken skills refused; `load_skill` serves them; every backticked name in every skill exists in the tools; the rounding examples recomputed; the wrong budget wording guarded; all 6 reviewed by the owner (2026-10-19) |

Screening (2026-10-19, owner's review of `untrusted-content`): Phase 5 — 0 corpus passages flagged; Phase 6 — the mock
web result "Ignore previous instructions…" flagged `override_en`, five zero-width characters removed and flagged.

## Problems and fixes
- **Real duplicates in the original invoices.** The dry run of 015 flagged 3 same-vessel, same-day, same-amount pairs
  in `invoices` (both copies paid, 336,909.00 SDR). Not an Auditor bug: the invoices were drawn at random (ADR-013),
  and ~1–3 such collisions are expected for 1,000 invoices over 500 vessels. A vessel cannot transit twice on one day,
  so they stay real findings (reviewed snapshot `LIVE_FINDINGS`; the plan's "live 0" expectation was corrected).
- **Duplicate rule needs the amount.** INV-0000626 is both half of a real pair (with INV-0000293) and the planted
  wrong-rate invoice of the test copy; matching on vessel + date only would have turned the planted error into a
  duplicate and lost it. The rule keys on vessel, date **and** amount.
- **Empty ranked lists.** Weeks 1–4 have no overdue invoice: the first version answered `no_data`; an empty ranked
  list is now an `ok` answer with 0 rows ("nothing overdue" is a fact, not missing data).
- **The model could pick the evaluation copy.** `invoice_audit` first exposed `dataset = test` to the model; the
  dataset now comes from the run context (`RunContext.dataset`, set by the evaluation harness only).
- **A skill used shorthand field names** (`_pct`): the consistency check against the dataset columns caught it.
- **Owner's skill review (2026-10-19):** a budget-gap sentence wrong in two skills (actual is 11 % *below* budget),
  "849.9 k" as the model rounding (it was the bake-off's recorded error), a WoW of the budget variance and a laden /
  ballast split that no tool returns, and a numeric gate that a planted passage could have passed. Each fixed and
  turned into a check (names in every skill, rounding examples, the budget wording, row screening); the size budget
  stopped two longer versions (1,203 and 1,247 tokens).
- **Applying migration 015 was refused** by the session's permission classifier (a shared database change): Phase 4
  reported itself as pending instead of failing until the owner applied it (2026-10-19); then it passed at once.
- **The missing-key test came back with the key:** it removed `TAVILY_API_KEY`, but the tool re-reads `.env` and
  `load_env` only fills unset variables; the check now sets the variable empty (in Phase 6 and in the RBAC matrix).
