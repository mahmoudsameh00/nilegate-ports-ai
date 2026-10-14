# Plan — Multi-agent platform: Stage 1 the Weekly Finance Pack, Stage 2 the Operations Desk

- **Status:** APPROVED (2026-10-09) — every decision answered by the owner (§7 "Answers"); owner: "the same plan in
  two stages, prepare everything for the new session". Nothing is implemented yet; work starts at Phase 0 (handoff at
  the end).
- **Goal:** one multi-agent platform (LangChain components, LangGraph orchestration, LLMs through **free APIs**) on the
  data we built — PostgreSQL, MongoDB, the RAG corpus — and external tools, under the existing access control (ADR-006):
  - **Stage 1 — Weekly Finance Pack (the main product):** every week, with no manual work by the finance team, a
    **Power BI dashboard** of NileGate's finance KPIs stays current and a **PowerPoint report (English)** states what
    changed, why, which invoices need attention, and where every number comes from; then follow-up questions.
  - **Stage 2 — Operations Desk:** for the Operations department, **B Route & Cost Advisor** (Suez or Cape for a given
    vessel and voyage: distance, days, transit dues, fuel estimate, risk context) and **C Voyage & Disruption Watch**
    (ETA, delay risk, marine weather, Suez traffic, alerts).
  - One **Supervisor** answers questions across both products (e.g. "why did toll revenue drop this week?" may need
    finance KPIs, Suez transits and voyage data together).
- **Why these products:** recurring reporting is where finance teams lose the most time (vendor case studies: a weekly
  report of 6–8 h cut to < 1 h), invoice errors are a known leak (5–10 % of freight invoices carry an error); schedule
  reliability collapsed in 2025 (on-time arrivals 36 % → 13.9 %, carrier ETA error ≈ 15 h) and carriers decide Suez vs
  Cape per service. Stage 2 reuses Stage 1's foundation (tools, RBAC, checkpointer, Validator, evaluation), so it costs
  much less than Stage 1.
- **Order:** Stage 1 builds the foundation and ships the main product; Stage 2 starts after Stage 1's checkpoint.
- **Builds on:** ADR-003 (money in SDR), ADR-004 (progressive toll bands), ADR-006 (RBAC), ADR-011 (news via web
  search), ADR-012 (Supervisor + Analytics Agent; specialists when they earn it), ADR-013 (invoices: the database is
  the source of truth), ADR-016 (migrations), ADR-018 (star schema → its trigger is now: fact / dimension **views**),
  ADR-020 (only numbers that exist in the source — here: only numbers a tool returned), ADR-028 (real AIS vessels are
  reference data, never linked), ADR-031 (files first, one writer), ADR-032 (synthetic voyage rules), ADR-034
  (read-only role), ADR-037 (data policy → amended, §7), ADR-038 / ADR-040 (retrieval tool and its baseline),
  ADR-042 – ADR-044 and `docs/RETRIEVAL_FLOW.md` §2.1 (uploads are untrusted data).

---

## 1. Starting point (verified 2026-10-09)

| Input | State |
|---|---|
| `invoices` (PostgreSQL) | 1,000 rows, 2025-01-01 → 2025-12-30, **52 ISO weeks**, 11–29 invoices a week (median 19), 268,988,787 SDR in total; status Issued 361 / Pending 328 / Paid 311 (an end-of-2025 snapshot); every amount equals the progressive toll (ADR-004, 0 mismatches) |
| Missing for finance KPIs | no customer (who pays), no due date / payment terms, no payment date, no budget → no AR aging, DSO, collections, top customers, variance |
| `vessels` (500, SCNT tons, type, origin / destination LOCODE), `toll_rate_bands`, `ports` (837), `port_connections` | complete (ARCHITECTURE §4) |
| MongoDB | AIS 1.32 M positions (real samples + synthetic tracks of our 500 vessels up to 2026-09-13), `voyages_synthetic.parquet` (port sequence, legs on sea paths, ADR-032), EDI IFTMIN with `RFF+IV` (376 messages) |
| RAG | `search_documents` (RBAC, exact dense + rerank; baseline balanced 0.850); Suez Notes (tariff rules), USCG / IMO (incidents), HbR annual report |
| Access | `invoices` = level 2 / Finance; vessels, ports, AIS, EDI = level 1 / Operations; HbR financial results = level 3 (CEO only) (`docs/rbac_mapping.md`) |
| Keys in `.env` | `GEMINI_API_KEY` (Google AI Studio), `JINA_API_KEY`, `VOYAGE_API_KEY`; **no** Groq / OpenRouter / LangSmith / web-search / aisstream key yet |
| Packages | `searoute`, `httpx`, `psycopg`, `pymongo`, `qdrant-client` installed; no LangChain / LangGraph / python-pptx / matplotlib / psycopg-pool yet |
| Power BI | not installed |

---

# STAGE 1 — Weekly Finance Pack

## 2. What the finance team receives

**Dashboard (Power BI Desktop, PBIP project in git, DirectQuery on the `finance` views)** — pages: Overview (week KPIs
vs last week / vs budget), Revenue (by vessel category, laden / ballast, band, route), Receivables (AR aging buckets,
DSO, collections, overdue list), Customers (top 10, concentration), Exceptions (invoice audit findings).

**PowerPoint (English, generated, ~10 slides)** — 1 title + week; 2 executive summary (5 bullets, every number cited);
3 KPI tiles; 4 revenue trend (13 weeks) and the week's drivers; 5 revenue mix; 6 receivables and DSO; 7 top customers
and changes; 8 exceptions (audit findings, amounts at stake, proposed action); 9 context (Suez transits, relevant news,
the tariff rule that explains a change); 10 appendix: sources (view + filter for every number), data freshness, what
was not checked. Amounts in SDR (ADR-003).

**Q&A** — follow-up questions in natural language, answered with the same governed tools and the same RBAC.

## 3. Architecture (both stages)

```text
Windows Task Scheduler (weekly)  or  a user's question
 └─► LangGraph StateGraph "weekly_pack" (PostgresSaver checkpoints; report_week = the as-of week)
      1 Data Readiness agent  — week complete? row counts, nulls, duplicates, late invoices → gate (stop + explain)
      2 KPI agent             — calls the governed KPI tool only (SQL views, fixed definitions); no free SQL here
      3 A Invoice Auditor     — recomputes each invoice with the toll bands (compute_toll) → exceptions + evidence
      4 Insight agent         — explains WoW / vs budget changes by drill-down (category, laden/ballast, customer,
                                route) + external context (IMF PortWatch Suez transits, web news) + the tariff rules
                                (search_documents on the Suez Notes)
      5 Report Writer         — narrative + charts → PPTX (python-pptx; charts from the same views)
      6 Validator             — every number in the deck = a tool result (exact match after the stated rounding);
                                every claim has a source; fail → back to 5 with the diff (max 2 loops), then stop
      7 ⏸ interrupt: Finance manager approves / edits / rejects (human in the loop)
      8 Publisher             — saves the approved deck to `reports/<week>/` (save only, no email)
 Stage 2: "route_advice" (B) on request; "voyage_watch" (C) on a schedule (every N hours) and on request
 Supervisor (subagents-as-tools: KPI, Insight, Auditor, Knowledge; Stage 2 adds Route Advisor, Voyage Watch)
   → answers with citations; every node receives the user's RBAC context; tools enforce it in their queries.
```

Why a **workflow with agent steps** for the pack and not a free supervisor: the pack has a fixed shape, its numbers
must be reproducible, and each step can be tested on its own. The supervisor is used for questions.

**Tools (LangChain tools, each with RBAC, a Pydantic schema, tests, a cache and a timeout for external calls):**

| Tool | Source | Stage |
|---|---|---|
| `kpi(report_week, metric, breakdown)` | `finance` views | 1 |
| `invoice_audit(invoice_ids \| week)` | invoices + toll bands | 1 |
| `compute_toll(vessel_id \| category, condition, tons)` | `toll_rate_bands` (ADR-004) | 1 (also B) |
| `search_documents` | existing (ADR-038) | 1 |
| `suez_transits(from, to)` | IMF PortWatch | 1 (also B, C) |
| `web_search(query)` | news (ADR-011; provider chosen at Phase 4) | 1 (also B, C) |
| `sea_route(origin, destination, avoid)` | `searoute` (installed), e.g. avoiding Suez for the Cape route | 2 |
| `voyage_status(vessel_id \| mmsi)` / `query_operations` | MongoDB AIS + synthetic voyages | 2 |
| `vessel_live(bbox \| mmsi)` | aisstream.io (live, real vessels: reference only, ADR-028) | 2 |
| `marine_weather(lat, lon, time)` | Open-Meteo Marine (waves, wind; free, non-commercial, attribution) | 2 |

**Structured outputs (owner question, 2026-10-09):** every structured result (KPI rows, audit findings, the deck
outline, route comparisons, ETA estimates, Validator verdicts) is a **Pydantic model** — one class serves the LLM
(`with_structured_output`), the tools, the Validator and the tests; validators mirror the database CHECKs (invoice
number format, amounts ≥ 0, LOCODE format); the JSON schema is generated from it (`model_json_schema()`). Models stay
simple (shallow nesting, `Literal` instead of complex enums, no unions) because free providers support different
JSON-schema subsets; the method (`function_calling` / `json_schema` / `json_mode`) is chosen per model by the bake-off;
on failure: validate → one retry with the error → stop.

**Skills (owner, 2026-10-10):** the agents' procedures and company knowledge are **Agent Skills** — one folder per
skill with a `SKILL.md` (the open standard LangChain Deep Agents also uses: a one-line frontmatter description always
visible, the full instructions loaded only when needed, optional reference files). They live in git under
`pipelines/agents/skills/<name>/`, written by us (company knowledge exists nowhere else) and reviewable by the owner
without touching code. A small loader in the library (no new dependency): a workflow node loads its fixed skill
directly (no discovery call); the Q&A supervisor gets a `load_skill(name)` tool and sees only the descriptions.
Why it matters here: free tiers have small per-minute token limits (Groq 8K TPM), so prompts carry only the skill a
step needs. First skills: `finance-kpi-definitions`, `suez-toll-audit`, `weekly-variance-analysis`, `deck-style-guide`,
`number-validation`, `untrusted-content` (Stage 1); `route-cost-advice`, `voyage-eta-method` (Stage 2). Skills hold
instructions and references only; any script a skill points to is project code, reviewed like any other.
**Not used:** vendor-licensed docx / pptx / xlsx / pdf skills (proprietary licence: no copies or derivatives); skills from
open registries (2026 audits: ~13 % with a critical issue — credential theft, prompt injection inside SKILL.md).
**Development skills (for the coding assistant, not the agents):** `langchain-ai/langchain-skills` (official) installed in
the local skills folder at Phase 0 after review — licence checked, a pinned commit, every file read before install, only the
LangGraph / LangChain-core skills needed.

## 4. Data additions (Stage 1; synthetic, files first, one writer — ADR-031 pattern)

A generator script (fixed seed) writes CSVs + a manifest; a migration loads them; `verify_readonly.sql` gets a new
section; nothing existing is regenerated (ADR-013: invoices stay as they are).
- `customers` (~40 shipping lines / agents; name, country, segment, payment terms 30 / 45 / 60 days, payment behaviour
  class) and `vessels.customer_id` (each vessel billed to one customer; FK).
- invoice terms: `due_date` = invoice_date + the customer's terms (column or view).
- `payments` (invoice_number, paid_date, amount; no partial payments), **consistent with the end-of-2025 status**:
  Paid → fully paid on or before 2025-12-31; Issued / Pending → unpaid at 2025-12-31.
- `budget_weekly` (week, vessel_category, budget_sdr), derived by a documented rule (a seasonal plan ± a stated
  target), not fitted to the actuals. No second year (no YoY) for now.
- **As-of logic:** an invoice's status in week *w* is derived from the dates (issued, due, paid), not from the snapshot
  column, so each of the 52 weeks can be reported as it looked then.
- **Injected test cases (evaluation only):** a separate, labelled copy of a few weeks with known invoice errors and a
  budget miss, so the Auditor and the Insight agent are measured against ground truth. Never mixed into the real tables.
- The concrete rules (counts, shares, the budget rule) are shown to the owner before any generation (D6, as ADR-032).

### 4a. Phase 1 — concrete generation rules (APPROVED 2026-10-13 by the owner, as written)

**Finding that changed D6 (owner decision 2026-10-13):** the stored `invoices.status` was drawn at random over the
year (Q1: 64 Paid / 84 Issued / 95 Pending; 689 of 1,000 not Paid). Payments "consistent with the end-of-2025 status"
would make 69 % of the year's invoices unpaid at 2025-12-31 (DSO ≈ 250 days, receivables ≈ 2/3 of revenue) — a
collections crisis, not a normal company. **Decision:** payments follow each customer's terms and behaviour; the
stored `status` is **kept unchanged** (ADR-013, rule 2) and documented by a COMMENT as the original generator's label,
not the payment state; every finance view derives the status from the dates (as-of logic above). A reconciliation
count (label vs derived) is reported, not enforced. → ADR at the end of Phase 1.

| # | Rule (all with fixed seed 42; files first, then one migration — ADR-031 pattern) |
|---|---|
| R1 | **Customers: 40** synthetic shipping companies (Faker company stems + "Shipping / Lines / Maritime / Tankers / Cruises"; **no real company names**). Segment by the vessel types they operate: container lines 8, tanker operators 10 (crude, product, chemical, LNG, LPG), bulk / general cargo 10, Ro-Ro / vehicles 5, cruise 3, agents (mixed, "Other Vessels" / SFU) 4. Country: HQ countries of the shipping industry (e.g. Greece, Denmark, Switzerland, Germany, Singapore, Japan, China, Korea, UAE, Egypt, Saudi Arabia, Norway, Turkey, India), not the vessel's flag. |
| R2 | **`vessels.customer_id`** (FK, NOT NULL for all 500): each vessel goes to a customer of its segment; within a segment the vessel counts follow a Zipf-like weight so revenue is concentrated (target: top-10 customers ≈ 55–65 % of 2025 billing; reported, not tuned). |
| R3 | **Terms and rating:** `payment_terms_days` ∈ {30, 45, 60} (shares 40 / 40 / 20 %; agents and cruise mostly 30); `credit_rating` A / B / C stored. The **behaviour class** (prompt / normal / slow / chronic late / disputer) is **not stored** in the table — only in the generator manifest as evaluation ground truth (otherwise the Insight agent could read the answer). Rating correlates with behaviour (A mostly prompt / normal, C mostly slow / late / disputer). |
| R4 | **Payments** (table `payments`: invoice_number FK, paid_date, amount_sdr; one row per paid invoice, full amount, no partial payments): due_date = invoice_date + terms; paid_date = due_date + delay drawn per class — prompt −10…0 d, normal −3…+10, slow +10…+45, chronic late +30…+120; disputer: 40 % of its invoices never paid. Payments after **2026-03-31** are not generated (unpaid at the data horizon). Expected: DSO ≈ 45–60 days, a few % of 2025 invoices unpaid at the horizon (reported, not tuned). |
| R5 | **Due date:** not stored — `finance.fact_invoice` (Phase 2) computes it from the invoice date and the customer's terms (one source of truth). |
| R6 | **Weekly budget** (`budget_weekly`: iso_week 1–52 of 2025, vessel_category, budget_sdr): a **planning model independent of the 2025 invoices** — annual plan per category = vessels of the category × **2.0 Suez transits per vessel-year** (stated assumption) × `compute_toll` of the category's median SCNT laden; weekly = annual ÷ 52 × a documented seasonal factor (±6 %, peak in week 45, low in week 6). Not adjusted after seeing the actuals; the resulting gap to actual 2025 billing is reported as a fact of the data. |
| R7 | **Evaluation copy, never mixed with the real tables:** schema `finance_test` with 4 golden weeks copied and labelled (`test_case` column): planted invoice errors — wrong band rate, SCNT digit swap, laden / ballast swap, SFU priced as Ballast, a duplicate invoice — plus one budget miss; the answer key (expected findings) in `Data/processed/agents/eval/finance_test_answer_key.json`. |
| R8 | **Access (ADR-006, `docs/rbac_mapping.md`):** `customers`, `payments`, `budget_weekly`, `finance_test.*` = level 2 / Finance; `vessels.customer_id` is an id only (vessels stay level 1). |
| R9 | **Integrity (ADR-033):** CHECKs (terms ∈ {30, 45, 60}, rating ∈ {A, B, C}, amount > 0, paid_date ≥ invoice date, budget ≥ 0, iso_week 1–52, category in the 13-value list), FKs + indexes, UNIQUE(invoice_number) on payments, a COMMENT on every new table / column and on `invoices.status` (the label decision). One migration `012_finance_data.sql`, applied by the owner; then `schema_snapshot.sql` and a new `verify_readonly.sql` section (payment = invoice amount, one payment per invoice, every vessel has a customer, budget rows = 52 × categories). |
| R10 | **Workflow:** generator `pipelines/scripts/synthetic/Finance_generator.py` writes CSVs + manifest (with the behaviour classes and the answer key) to `Data/processed/synthetic/finance/`; a **dry run first** prints the distributions (concentration, DSO, unpaid share, budget gap, rating ↔ behaviour) for the owner's review before the migration is written; reload = no change. |

## 5. Phases

| Phase | Work | Done when |
|---|---|---|
| **Stage 1** | | |
| 0 | branch `feat/agents`; `uv add` langchain(-core), langgraph, the provider packages (Google GenAI, Groq, an OpenAI-compatible client for OpenRouter), `langgraph-checkpoint-postgres`, `psycopg-pool`, `pydantic`, `python-pptx`, `matplotlib`, `langsmith`; provider smoke test (each key, one call, tool calling on); `common.SECRET_KEYS` + `.env.example`; reviewed install of the official `langchain-skills` (LangGraph / core) into the local skills folder; **LLM bake-off on free APIs (§7a)**, Gemini first | every package pinned with `==` in `pyproject.toml`; bake-off results file; the model choice as an ADR; the ADR-037 amendment written |
| 1 | Finance data generator + migration(s) + audit (§4) | invariants pass (status ↔ payments, terms, FK, totals), reload = no change |
| 2 | `finance` schema: star views (`fact_invoice`, `fact_payment`, `dim_date` (ISO week), `dim_customer`, `dim_vessel`, `dim_toll_band`) + KPI views / functions per `report_week`; `docs/finance_metrics.md` (one definition per metric) | every KPI equals a hand-computed value on 3 chosen weeks; RBAC: a non-Finance employee gets nothing |
| 3 | Power BI Desktop (owner, guided): install, PBIP project `powerbi/`, DirectQuery to the views with a read-only login, the 5 pages; measures through the official Power BI Modeling MCP | the dashboard's numbers for 3 weeks = the KPI views |
| 4 | Stage 1 tools (§3) + tests; external tools behind a cache and a timeout ("context unavailable", never a guess); the skill loader + the Stage 1 skills (`pipelines/agents/skills/`) | each tool tested on its own; RBAC matrix 0 leakage; every skill parses (frontmatter, size budget) and is reviewed by the owner |
| 5 | LangGraph workflow + agents + PostgresSaver (`agent_state` schema, writer role: migration) + interrupt | a pack for any week runs end to end; resume after a crash works |
| 6 | PPTX template (NileGate style) + Writer + Validator | the Validator catches every planted wrong number in a test deck |
| 7 | Evaluation (§8) on golden weeks + finance Q&A golden questions | the D7 thresholds are met (or the owner decides) |
| 8 | Scheduling (Task Scheduler), LangSmith tracing, checkpoint retention | a scheduled run produces the pack and waits for approval |
| S1 ✔ | **Stage 1 checkpoint:** ADRs, ARCHITECTURE, ROADMAP, a PR; the plan stays active | — |
| **Stage 2** | | |
| 9 | Stage 2 tools: `sea_route` (Suez vs Cape distances; `searoute` restriction support checked here), `voyage_status`, `vessel_live` (aisstream.io), `marine_weather`; fuel / speed parameter table (S2-D3) | each tool tested; live tools degrade gracefully |
| 10 | **B Route & Cost Advisor** graph (`route_advice`): inputs vessel + origin / destination; outputs a Pydantic comparison (distance, sea days at the vessel's speed, Suez dues via `compute_toll`, fuel estimate from the parameter table, risk context: PortWatch trend + news) and a recommendation with its assumptions; the Validator checks every number | the S2 route cases (§8) pass |
| 11 | **C Voyage & Disruption Watch** graph (`voyage_watch`): ETA (baseline: remaining sea distance / recent speed), delay risk (weather on the next legs, Suez traffic), alerts saved to a table / file (save only) and shown on request; scheduled every N hours (S2-D1) | ETA error on replayed synthetic voyages beats the naive baseline (§8); alerts reproducible |
| 12 | Supervisor extended to both products; cross-product questions; RBAC matrix (Operations ↔ Finance) | S2 Q&A golden questions pass; RBAC leakage 0 |
| 13 | Close: ADRs, ARCHITECTURE, ROADMAP, archive the plan | — |

## 6. Stage 2 — Operations Desk (details)

- **Users:** Operations employees / managers and the CEO (level-1 operational data). Finance data stays invisible to
  them (level 2 / Finance), and the agents enforce that in their tools.
- **B Route & Cost Advisor.** "Should vessel X (Laden, 85,000 SCNT) sail Port Said → Rotterdam via Suez or the Cape?" →
  two routes from `sea_route`, sea days from the vessel's service speed, Suez transit dues from the progressive bands
  (SDR), fuel = days × consumption per day (by vessel type, a documented parameter table) × a bunker price **set by the
  owner and dated** (no free live bunker-price source), risk context from PortWatch and news. The answer always lists
  its assumptions; no number without a tool behind it.
- **C Voyage & Disruption Watch.** For our 500 synthetic vessels (voyages up to the as-of instant 2026-09-13, ADR-032):
  current position and next port, ETA, the weather on the next legs (Open-Meteo forecast at route points), Suez traffic,
  a delay-risk flag with reasons → alerts. Live AIS (aisstream.io) shows real traffic in a bounding box (e.g. Suez /
  Red Sea) as situational awareness only: real vessels are never linked to ours (ADR-028).
- **Evaluation ground truth:** the synthetic tracks know every real arrival time → cut a voyage at time *t*, predict,
  compare (MAE in hours) against the naive baseline; route cases hand-computed from the same formulas.

## 7. Decisions — Stage 1 (answered) and Stage 2 (to answer before Phase 9)

### Answers (owner, 2026-10-09)

| Decision | Answer |
|---|---|
| D1 LLM | **free APIs only**: Google AI Studio (key exists), Groq, OpenRouter → bake-off §7a; two models per role (main + fallback) |
| D2 Orchestration | StateGraph workflow for the pack (and Stage 2 graphs) + a supervisor with subagents-as-tools for Q&A (`langgraph-supervisor` is no longer maintained) |
| D3 Checkpointer | PostgresSaver, schema `agent_state`, a writer role (migration; `ports_readonly` cannot write), `setup()` as a deployment step, retention job |
| D4 Star schema | plain views in schema `finance` (ADR-018's preferred shape) |
| D5 Power BI | Desktop (free, no sign-in) + PBIP / TMDL in git + DirectQuery (current when opened, no refresh, no gateway) + the official Modeling MCP (model only; pages built once with the owner); PPTX from Python (export needs Fabric capacity). Upgrade path: a work / school account → Service as an adapter |
| D6 Synthetic finance | approved as proposed; concrete rules shown before generation |
| D7 Evaluation | strict: deck numbers 100 % (hard gate), planted errors found ≥ 95 %, false alarms ≤ 5 %, every claim traceable, RBAC leakage 0 |
| D8 Observability | LangSmith (free developer plan) |
| D9 Distribution | save only (`reports/<week>/`); no email |
| D10 Infrastructure | `psycopg_pool` now; Redis and DirectML stay deferred |
| D11 External tools | web search (news), IMF PortWatch, live AIS (aisstream.io), marine weather (Open-Meteo); no SDR-rate tool |
| D12 Clock | replay of 2025's 52 weeks (`report_week`) |
| Data policy | **ADR-037 amendment:** synthetic and public data may go to free tiers, minimized (aggregates instead of rows where possible, no employee names); real company data → paid tiers only. **Superseded 2026-10-14 (amendment 2, owner):** no data guard — every dataset is synthetic or public, the free APIs are used as if paid; uploads: `GEMINI_TIER=paid` in `.env` |
| Plan shape | one plan, two stages (Stage 2 = B + C) |
| D13 Runtime skills (2026-10-10) | Agent Skills (`SKILL.md` standard) written by us in `pipelines/agents/skills/` + our own small loader (workflow nodes load their fixed skill; the supervisor gets `load_skill`); no Deep Agents dependency for now |
| D14 Development skills (2026-10-10) | install the official `langchain-ai/langchain-skills` (LangGraph / core) in the local skills folder at Phase 0, after a review (licence, pinned commit, every file read) |

### Stage 2 decisions (recommended option first; answer before Phase 9)

- **S2-D1 — Alerts:** a scheduled `voyage_watch` run every N hours (Task Scheduler) writing alerts to a table / file,
  read on request (save only, like D9). *Alt:* a long-running monitor process; push notifications.
- **S2-D2 — ETA method:** rule-based baseline first (distance / recent speed + port-call allowance); a learned model
  only if it beats the baseline by a margin fixed beforehand. *Alt:* ML from the start.
- **S2-D3 — Fuel and speed parameters:** a documented table per vessel type (service speed, consumption / day) + a
  bunker price set by the owner with its date. *Alt:* a paid bunker-price feed.
- **S2-D4 — Live AIS scope:** one bounding box (Suez Canal + Red Sea), a short sampling window per run, no storage
  beyond a run's snapshot. *Alt:* store a rolling window in MongoDB (a new collection through the one writer).
- **S2-D5 — Thresholds** (fixed before the Stage 2 runs): route numbers 100 % from tools; ETA MAE better than the naive
  baseline; alert precision measured on planted weather / traffic events.

### 7a. LLM bake-off on free APIs (rules fixed before any run)

- **Candidates (verified 2026-10-09):** AI Studio — `gemini-3.8-flash`, `gemini-3.5-flash-lite`, `gemma-4-31b-it`
  (Pro models left the free tier on 2026-04-01; free limits are shown in AI Studio only; **the free tier may use inputs
  to improve Google's products**); Groq — `openai/gpt-oss-120b`, `qwen/qwen3.8-27b`, `openai/gpt-oss-20b` (free: 30 RPM,
  1,000 RPD, 8K TPM, 200K TPD per model, per organization; states no training on API data); OpenRouter `:free` —
  `nvidia/nemotron-3-super-120b-a12b`, `thinkingmachines/inkling`, `poolside/laguna-s-2.1` (20 RPM, **50 requests /
  day** across free models, 1,000 / day after a one-time $10; providers' data policies differ → privacy
  settings: "may train" allowed for synthetic data, "publish prompts" off). Free catalogues change: the script reads the live model list and skips a vanished model, reported.
- **Tasks (existing data only, no new tables):** T1 tool calling (20 questions; right tool, right arguments, right final
  number; tools: `compute_toll`, a weekly KPI over the existing invoices, `search_documents`); T2 grounded weekly summary
  (10 weeks of KPI tables → 5 bullets; every number in the text must appear in the table = hard gate; driver coverage);
  T3 structured output (an exceptions list as a Pydantic model; validity per method); T4 RAG answers on the frozen
  golden set (fact recall against `golden_facts.jsonl`, citation validity).
- **Also measured:** latency, requests and tokens per simulated pack (does a week fit the free quota?), 429 / error rate.
- **Rule:** a model with any number not in its input on T2 is out for Writer / Insight; among the rest, the best mean of
  T1, T3, T4 per role (Writer / Insight vs routing / tools), ties broken by quota fit; main + fallback per role.
- **Files first:** every response cached by (model, task item, prompt hash), so a run resumes across days without
  repeating calls; results in `Data/processed/agents/eval/llm_bakeoff_<date>.json`.

## 8. Evaluation

- **Stage 1 golden weeks:** ~10 of the 52 weeks chosen before any run (quiet weeks, peak weeks, a week with planted
  invoice errors, a budget miss, a week where Suez transits moved), with expected KPIs computed by SQL and expected
  findings written by hand.
- **Stage 1 golden questions:** ~30 finance questions (EN) with expected numbers / sources; RBAC cases (an Operations
  employee asking for receivables, a manager asking for level-3 HbR results).
- **Stage 2:** ~12 route cases (hand-computed); ETA on ~50 replayed synthetic voyages (MAE vs the naive baseline);
  planted weather / traffic events for alerts; ~20 operations questions + cross-product questions; RBAC both ways.
- **Measured:** number correctness, finding recall / false alarms, traceability, RBAC, latency, requests / tokens per
  run (free quotas), Validator loops. One results file per run = the baseline for the next change.

### 8a. Generation evaluation — PROPOSED (2026-10-11, owner asked; deterministic first)

Numbers are covered (bake-off T2 gate, Validator exact match, D7: deck numbers 100 %). What the model **says** around
the numbers is not yet measured. Every check below uses ground truth we already compute — no LLM judge unless noted.

| # | Check | How (deterministic) | Where |
|---|---|---|---|
| G1 | **Direction and attribution of claims** | a sentence naming a category / KPI with a direction word (rose, fell, up, down, increased, declined…) must agree with the sign of its WoW / vs-budget value; a category called a driver must be among the week's top-k \|change\| (k = 3); a category or KPI named must exist in the week's data | Validator rule (Phase 6, blocks the deck) + Phase 7 metric (claim accuracy, target 100 % on golden weeks) |
| G2 | **Arabic answers** (decided 2026-10-10: deferred from the bake-off) | the 24 Egyptian Arabic golden twins + Arabic versions of ~10 finance questions; facts get Arabic patterns written and frozen before any run; same recall / citation scoring as T4 | Phase 7 (Q&A); reported separately from English, threshold set before the run |
| G3 | **Correct refusal / abstention** | items with no answer in the context (e.g. q34-type, empty retrieval) and RBAC-denied questions must produce the "not in the documents" / "not permitted" answer and **no** fact or number; a hallucinated answer = failure | Phase 7: abstention precision / recall; RBAC cases already in §8 get this check |
| G4 | **Relevance and completeness (Q&A)** | each golden question lists its required elements (number + unit + period, or facts) → completeness = share present; relevance = the answer addresses the asked metric / period (the period and metric parsed from the question must appear) | Phase 7 metric; an LLM judge only as a reported second opinion, from another provider, calibrated on 20 answers the owner grades |
| G5 | **Human edits as a signal** | the approval step logs approve / edit / reject and the diff of an edited deck (which slide, which sentence) | Phase 5 (interrupt payload) + Phase 8 (stored per run); reported as edit rate, never auto-scored |
| G6 | **Acceptance rule for a change** (prompt, model, skill) | like ADR-040: a change is kept only if no hard gate regresses (numbers 100 %, G1 100 %, RBAC 0, abstention not lower) and the primary score (finding recall on golden weeks; Q&A completeness) does not fall by more than a stated margin; ties keep the simpler / cheaper setup | written as an ADR at Phase 7, before the first comparison |

Notes: the bake-off's T4 recall (0.46–0.67) uses strict fact patterns (e.g. the vessel name must be repeated), so it
ranks models fairly but is not an absolute accuracy; G2 / G4 freeze their own expected elements before any run.

## 9. Risks

| Risk | Mitigation |
|---|---|
| The LLM writes a wrong number | numbers only from tools; Validator exact match; human approval before saving the pack |
| Free quotas run out mid-pack | main + fallback model per role; cache; quota use measured per pack; checkpoints resume later |
| A free model disappears or changes | live model list checked each run; the bake-off re-run picks a replacement |
| Synthetic data looks unreal | rules approved first; distributions documented; labelled synthetic everywhere |
| DirectQuery limits some DAX | KPIs computed in SQL views; DAX measures stay simple; Import mode as a fallback |
| Power BI Service needs a work account | the design does not depend on it; the Service is an adapter |
| External APIs down / changed | cache + timeout; "context unavailable" instead of guessing |
| Data on free tiers (training) | ADR-037 amendment: synthetic / public only, minimized; real data → paid tiers |
| Agent changes the Power BI model badly | PBIP in git, review the diff, MCP on a branch |
| Fuel / ETA numbers read as facts | assumptions printed with every answer; parameters dated and owner-set |

## 10. Sources (research of 2026-10-08/09)

Freight invoice audit ranges (GingerControl, ShippyPro); agentic AI in forwarding (GoFreight, ATeam, Kognitos);
D&D automation (Windward); schedule reliability and ETA errors (Seatrade, DC Velocity, The Loadstar, ESA NAVISP);
Suez / Cape (SeaRates, GoFreight); OpenSanctions maritime docs; EU ETS 2026 (Hapag-Lloyd); IMF PortWatch (OpenBB docs,
UN presentation); Open-Meteo Marine; aisstream.io; LangChain migration guide (langgraph-supervisor); PostgresSaver
production notes; Langfuse vs LangSmith; Power BI export-to-file capacity requirement and refresh limits (Fabric
community, Microsoft blog); Power BI Modeling MCP (github.com/microsoft/powerbi-modeling-mcp); PostgreSQL connector
(Microsoft Learn: Npgsql bundled since 2019, Import and DirectQuery); Power BI Service needs a work or school account
(Microsoft Learn); Groq rate limits (console.groq.com/docs/rate-limits); OpenRouter pricing and free models; Gemini API
rate limits (ai.google.dev); FP&A reporting time (vendor case studies). Vendor figures are directional.

## Progress / deviations

- 2026-10-09 — plan written (PROPOSED), all decisions answered the same day (§7 "Answers"); structured outputs =
  Pydantic models; owner: one plan in two stages (Stage 2 = B Route & Cost Advisor + C Voyage & Disruption Watch) →
  APPROVED. File renamed from `Agents_Finance_Weekly_Pack_plan.md`.
- 2026-10-10 — owner: Agent Skills for the agents, written by us with our own loader (D13); the official
  `langchain-skills` for the coding assistant after review (D14); OpenRouter "may train" allowed for synthetic data.
- 2026-10-10 — **Phase 0 in progress.** Done: `common.SECRET_KEYS` + `.env.example`; 12 packages pinned (`uv add`, 49
  installed; no existing pin changed; pydantic 2.13.5 → 2.14.0, until then only transitive); 5 reviewed
  `langchain-skills` in the local skills folder (commit `16a992f0`, MIT; `README_third_party.md`; `langchain-dependencies`
  rejected: range pins contradict rule 6); `pipelines/agents/llm.py` (registry, factory, Budget, response cache, quota
  state); `LLM_smoke_test.py` passed for Gemini / Groq / OpenRouter (all 9 candidates served; OpenRouter key
  is_free_tier). Owner decisions (2026-10-10): layout `pipelines/agents/` + `pipelines/scripts/agents/` + frozen tasks
  / results in `Data/processed/agents/eval/` (cache git-ignored); all packages now; the smoke test goes through the
  cache; bake-off tools = `compute_toll` (self-check: 1,000 invoices, 0 mismatches), `weekly_kpi` (invoice_count /
  billed_sdr / mean_invoice_sdr per ISO week, optional category, **no status**), `search_documents` (the asker fixed
  by code; in T1 it returns the frozen top-8); T1 = 8 toll + 8 KPI + 4 search; T2 strict numbers (only k/M and
  decimals count as rounding; allowed: week number, 2025, |negative change|; WoW deltas precomputed; driver coverage
  = top-2 |WoW| categories named); T3 = 10 made-up tables × 8 invoices, 0–3 planted mismatches, flat
  `ExceptionsReport`, copy not compute, 3 methods (OpenRouter: function_calling only); T4 = 40 English golden
  questions, contexts = real `search_documents` top-8 for a ceiling-3 user frozen once, fact recall over the facts
  present in the context, citation validity; Arabic twins deferred to Phase 7; OpenRouter = a frozen stratified LITE
  subset (T1 8 / T2 4 / T3 4 / T4 8), the cross-provider ranking on LITE for all 9 models; selection: Writer /
  Insight gate T2 faithfulness 100 %, score mean(T2 driver coverage, T4 fact recall, T4 citation validity); Tools =
  mean(T1 accuracy, T3 validity × exactness); tie = < 5 points → quota fit → latency; no automatic relaxation of the
  gate; main + fallback from different providers; unfinished provider → LLM ADR PROPOSED + handoff.
- 2026-10-10 — **Bake-off deviations / findings.** (1) `compute_toll` self-check: the stored invoices follow no single
  rounding rule at the half cent (half-up leaves 34 one-cent differences, half-even 9; ADR-013) → the check compares
  the exact amount within half a cent (`verify_readonly.sql` §12 allows 0.01) + equal terminal rates; the tool rounds
  half-up like PostgreSQL. (2) The move to `D:\Project` checked every text file out with CRLF (171 / 178 data files),
  breaking the frozen golden hashes (content identical) → `.gitattributes` (`*.json / *.jsonl / *.csv` eol=lf; owner
  re-checked them out); every hashed text file of the project expects LF. (3) Tasks frozen and reviewed:
  `bakeoff_tasks.json` sha256 `ed6723f5…` (T4: 39 / 40 items with measurable facts; q34 none). (4) Free limits found:
  `gemini-3.8-flash` 20 requests / day (its 429) → **LITE only** (owner); `thinkingmachines/inkling:free` refuses plain
  API calls (403 "only available on agentic harnesses") → unavailable; Gemini / Groq 5xx and a local DNS outage
  stopped models for the run only (resumed from the cache). (5) Quota fit for ties = **packs per day** (daily request
  limit ÷ requests per pack; unknown limit → requests already served in a day, a lower bound), then TPM minutes, then
  latency (owner; the TPM-minutes measure favoured OpenRouter's nominal TPM).
- 2026-10-11 — **Scoring fixes after reviewing the first answers.** (6) T2: an empty visible answer (the output went
  to reasoning, gpt-oss-20b week 21) writes no number → not a gate failure (the decided rule), coverage 0, logged as
  `t2_answer_rate`; gpt-oss-120b's gate failure checked by hand and correct (`849.9 k` for −849,964 is a truncation,
  "13 categories" is not in the table). (7) T4: gpt-oss's native citations `【n†…】` count as citing passage n
  (owner), `t4_format_ok` logs whether the asked `[n]` format was used. (8) A per-minute 429 waits a full window
  (60 s) before its one retry (Groq's output-tokens-per-minute limit came back after 20 s on qwen).
- 2026-10-11 — `gemini/gemma-4-31b-it` → **LITE only** (owner): both request kinds succeed (11 tool calls, 11 final
  answers), but the free tier answers in 5–74 s (median ≈ 35 s) with intermittent 500s, so the full set would take
  weeks at one retry per failure.
- 2026-10-11 — **Repeated server errors** (owner): a 5xx on the same request (cache key) in two separate runs, each
  after its retry, is cached as `server_error_repeated` (the item scores as failed, the model continues);
  `llm_cache/server_failures.json` counts the runs. Seen on gemma: it failed `t1_search_1`'s second turn in two runs,
  then passed it in a third — its free-tier 500s are flaky, so the rule is keyed on repetition, not on a guessed
  cause. A loop of 6 runs completes gemma / laguna LITE item by item.
- 2026-10-11 — owner asked whether generation evals are covered: numbers yes, the words around them no → **§8a
  Generation evaluation (G1–G6) written as PROPOSED** (deterministic first; an LLM judge only as a calibrated second
  opinion). Awaiting the owner's review.
- 2026-10-12 — **Phase 0 CLOSED.** ADR-045 **Accepted** (owner) on a best-case bound: the two incomplete candidates
  miss only T4 items, and scoring them as perfect keeps them below the tie threshold (3.8 Flash ≤ 0.708 / 0.938,
  laguna ≤ 0.806 / 0.875). Final selection: Writer / Insight `qwen/qwen3.8-27b` (Groq) + `gemini-3.5-flash-lite`;
  Tools `gemini-3.5-flash-lite` + `openai/gpt-oss-20b` (Groq). 22 bake-off runs over three days; results
  `Data/processed/agents/eval/llm_bakeoff_2026-10-12.json`. Done-when of §5 Phase 0 met: every package pinned, the
  results file, the model ADR, the ADR-037 amendment.
- 2026-10-13 — **Phase 1 started: rules first.** Finding: `invoices.status` is a random label (69 % not Paid, evenly
  over the quarters) → owner: realistic payments, the status kept unchanged as a documented label (D6 amended). §4a
  R1–R10 written as PROPOSED for the owner's review; approved as written. Dry run (nothing written): top-10 customers
  57 % of billing, DSO 55 days, 0.6 % unpaid at the 2026-03-31 horizon, paid on or before due 36 % (owner: keep),
  budget 302.1 M vs actual 267.9 M (−11.3 %), label vs derived agree 379 / 1,000. **R7 deviation (owner):** the
  `finance_test` copy has **no `test_case` column** — the Auditor would read the answer; the labels live only in the
  answer key and the manifest (same reason as R3).
- 2026-10-13 — `Finance_generator.py` written (8 / 8 ✅) and run: 6 CSVs in `Data/processed/synthetic/finance/` +
  manifest, `finance_test_answer_key.json`, **migration `012_finance_data.sql` written** (one transaction); second run
  with another hash seed: 0 files changed. `verify_readonly.sql` §17 added, `rbac_mapping.md` (R8), `db/README.md`.
  **Next:** the owner applies 012 → schema snapshot → verify §17 → then the Phase 1 ADR (D6 amended + R1–R10) and
  Phase 1 closes ("reload = no change" already shown).
- 2026-10-14 — **Phase 1 CLOSED.** Owner applied 012 (all counts as generated), refreshed `schema_snapshot.sql`, ran
  the audit: §17 = 40 | 500 | 994 | 0 | 0 | 0 | 676 | 88 | 52, 0 errors; §14 / §15 clean except
  `tables_never_analyzed = 13` (an unclean Docker shutdown reset the statistics → `ANALYZE`). Done-when of §5
  Phase 1 met (invariants pass, reload = no change). ADR-046 written.
- 2026-10-14 — **Data guard removed (owner):** "the data is not real and not private, an educational project — treat
  it as a paid tier, no blocks". ADR-037 amendment 2; `llm.py` no longer takes `data_origin` (smoke test re-run:
  0 calls, cache keys unchanged); uploads opened by `GEMINI_TIER=paid` in `.env` (owner adds it). **Next: Phase 2** (`finance` schema: star views
  + KPI views per `report_week`, `docs/finance_metrics.md`). Bake-off for the record: 3.8 Flash 21 / 24, laguna 23 / 24
  (selection unchanged; results `llm_bakeoff_2026-10-13.json`).
- 2026-10-14 — **Phase 2 started: metric definitions first.** A draft of every metric computed with pandas from the
  CSV mirrors (no DB) for all 52 weeks, shown to the owner on week 27. Checks: AR roll-forward (AR(w) = AR(w−1) +
  billed − collected) holds on all 52 weeks; the two DSO formulas differ by −7.9…+8.8 days on weeks 14–52. Findings:
  no 2024 invoices → AR starts at 0 on 2025-01-01 and builds up to ≈ week 12; 4 invoices dated 2025-12-29/30 belong to
  ISO 2026-W01. **Owner decisions (2026-10-14, P2-1…P2-8):** (1) DSO = AR at week end ÷ billed in the last 91 days ×
  91 (count-back documented as a deferred alternative); (2) weeks 1–13 (fewer than 91 days of history): DSO uses the
  available window (2025-01-01 → Sunday, its length in days) and the row carries `is_warmup = true`; (3) strict ISO
  weeks, "as of" = Sunday 23:59; the 4 late-December invoices sit in 2026-W01, outside the 52 report weeks (counted
  in validation); (4) KPIs are **views only**, one row per `report_week` (Power BI reads them, the agent tool filters
  `WHERE report_week = %s`); no SQL functions; (5) RBAC: views stay plain, registered level 2 / Finance; the proof is
  a matrix over every employee with the existing Python predicate `pipelines/lib/retrieval.allowed()` (ADR-006,
  ADR-034); per ADR-006 a non-Finance **manager** (ceiling 2) may read level 2, so "a non-Finance employee gets
  nothing" = role `employee` (ceiling 1) outside Finance; (6) migration 013 also creates the group role
  `finance_bi` (NOLOGIN, USAGE + SELECT on `finance` only, read-only); its login user in Phase 3 by a script (password
  from `.env`, never in a migration); (7) hand-check weeks **5 (warm-up), 16 (quietest), 23 (peak), 49 (clean test
  week)** + an assert on the week-52 edge; (8) no `finance_test` views in Phase 2 (Auditor tool, Phase 4 / 7);
  (9) rounding once at the end of the KPI views: money 2 decimals, `*_pct` percent 2 decimals, days 1.
  Owner asked: every proposal as clickable choices (AskUserQuestion), recommendation first.
- 2026-10-14 — **Phase 2 CLOSED.** `db/migrations/013_finance_views.sql` written by hand, applied by the owner
  (12 views, COMMENT on every view and column, grants, group role `finance_bi`). Deviations: the view comments and
  `docs/rbac_mapping.md` register `finance.*` as **one unit, level 2 / Finance** (the dims over level-1 tables take the
  schema's level); `dim_vessel` carries the port names (`finance_bi` cannot join `public.ports`); new script area
  `pipelines/scripts/finance/`. `Finance_views_check.py` 7 / 7 ✅ (second run; the first stopped by design at the
  unreviewed snapshot): the 4 KPI views equal an independent pandas reference on all 52 weeks; invariants max diff
  0.000; hand-check snapshot reviewed by the owner (DSO 31.0 / 51.7 / 62.2 / 53.6 days for weeks 5 / 16 / 23 / 49);
  RBAC: ceo 1 + manager 10 + Finance employees 17 granted, 72 role-`employee` outside Finance denied (leakage 0);
  `finance_bi` reads 12 / 12 views, 0 / 15 tables outside `finance` (PostGIS catalog objects excluded: PUBLIC).
  `verify_readonly.sql` §18 added; ADR-047; `docs/finance_metrics.md`; checkpoint
  `pipelines/checkpoints/finance/Finance_views_check.md`. Done-when of §5 Phase 2 met. Schema snapshot refreshed and
  audit run by the assistant (owner asked): §18 = 12 | 0 | 0 | 455 | 52 | 1000 | 994 | 4 | 13, 12 | 0 | 0, roll-forward
  0.00; §15 clean (`db/audit/2026-10-14_after_013_report.txt`).
- 2026-10-14 — **Phase 3 started.** Machine: Power BI Desktop not installed, winget and VS Code present, 16 GB RAM.
  Owner: installs Power BI Desktop himself from the Microsoft Store. Written: `db/create_finance_bi_user.ps1` (login
  `ports_bi` from `.env` `PG_BI_USER` / `PG_BI_PASSWORD`, member of `finance_bi` only, read-only on the login itself)
  and `db/check_finance_bi_user.py` (finance readable; public / finance_test refused; writes refused by the session
  and by privileges); `.env.example` keys. Owner runs the create script (it writes `.env`): 11 / 11 PASS. Power BI
  Desktop **2.158.1304.0** installed by the owner from the Store (PBIR / TMDL are the default save formats since
  January 2026). **Owner decisions:** the model loads **11 views** (all but `dim_date`; `dim_week` is the one
  week dimension / slicer for every page); the model is built through the official **Power BI Modeling MCP** run
  by the coding assistant with Node.js — Node.js LTS **24.20.0** installed by winget (owner approved the download; hash
  verified), MCP **@microsoft/powerbi-modeling-mcp@1.0.0** (MIT, publisher microsoft1es; pinned, not @latest)
  registered in the project `.mcp.json` (stdio, `cmd /c npx`); the EULA is accepted by the owner in the first MCP
  session; the MCP loads only after the coding assistant restarts.
- 2026-10-14 — Owner connected Power BI (PostgreSQL connector, `127.0.0.1:5432` / `ports_logistics`, DirectQuery,
  login `ports_bi`, 11 views) and saved **`powerbi/NileGate_Finance.pbip`** (first as .pbix: the PBIP save option had
  to be enabled in Preview features; TMDL model + PBIR report). Checked: all 11 tables `mode: directQuery`, no
  credentials in the files, no relationships yet. `.gitignore`: `powerbi/**/.pbi/localSettings.json`, `cache.abf`,
  `powerbi/*.pbix`. **Owner decision P3-4:** the 13-week trend comes from a new SQL view → migration
  `014_finance_trend_view.sql` (`finance.kpi_weekly_trend`, 598 rows), applied by the assistant with the owner's approval;
  `Finance_views_check.py` 7 / 7 ✅ (trend rows = kpi_weekly), §18 = 13 | 0 | 0 | 455 | 52 | 1000 | 994 | 4 | 13 |
  598 and 13 | 0 | 0, 0 errors (`db/audit/2026-10-14_after_014_report.txt`); ADR-047 amendment.

### SESSION HANDOFF (2026-10-14, Phase 3 in progress) — read this first in the next session

- **State:** Phase 3 steps 1–3 done (Power BI Desktop 2.158 installed; login `ports_bi` in `finance_bi`, 11 / 11
  PASS; `powerbi/NileGate_Finance.pbip` saved with 11 DirectQuery tables, no relationships; migration 014
  `kpi_weekly_trend` applied). The session was restarted so the coding assistant loads the **`powerbi-modeling` MCP**
  (`.mcp.json`, `@microsoft/powerbi-modeling-mcp@1.0.0`; Node 24.20.0 — a fresh session sees it on PATH).
- **Next (assistant), through the MCP, Power BI Desktop open on the PBIP:** (0) the owner approves the project MCP
  server and accepts the Microsoft EULA (`accept_eula` only after he says yes); connect to "NileGate_Finance" in
  Power BI Desktop. (1) Add table `finance kpi_weekly_trend` (DirectQuery, same M as the others:
  `PostgreSQL.Database("127.0.0.1:5432", "ports_logistics")`, Schema `finance`). (2) Relationships, all many → one,
  single direction, to the dims: `dim_week[report_week]` ← `kpi_weekly`, `kpi_weekly_category`, `kpi_customer_13w`,
  `kpi_overdue_list`, `fact_ar_snapshot`, `kpi_weekly_trend` (`report_week`), `fact_invoice[invoice_report_week]`,
  `fact_payment[paid_report_week]`; `dim_customer[customer_id]` ← `fact_invoice`, `fact_payment`, `fact_ar_snapshot`,
  `kpi_customer_13w`, `kpi_overdue_list`; `dim_vessel[vessel_id]` ← `fact_invoice`, `fact_payment`,
  `fact_ar_snapshot`, `kpi_overdue_list`; `dim_toll_band[toll_rate_band_id]` ← `fact_invoice`. (3) Measures: simple
  only (SUM of fact amounts; SELECTEDVALUE of the week-grain KPI columns; percent columns ÷ 100 with a % format; SDR
  `#,0`), in display folders per page; hide keys / technical columns; friendly table names — **ask the owner** (naming,
  measure list) with AskUserQuestion before writing. Then save the PBIP, review the TMDL diff, and guide the owner
  through the 5 pages of §2 (visuals by hand; the MCP cannot build reports). Done when the dashboard numbers for 3
  weeks (5, 23, 49) = `kpi_weekly`.

### SESSION HANDOFF (2026-10-14, after Phase 2)

- **Phases 0, 1 and 2 are CLOSED.** Phase 2 (2026-10-14): ADR-047, migration 013 = schema `finance` (12 plain views;
  KPI views one row per `report_week`, no functions), `docs/finance_metrics.md` (M1–M11 + the hand-checked weeks),
  `pipelines/scripts/finance/Finance_views_check.py` 7 / 7 ✅, group role `finance_bi` (SELECT on `finance` only,
  read-only, NOLOGIN). **Next (assistant): Phase 3** — Power BI Desktop, guided, one step at a time: (1) the owner
  installs Power BI Desktop (free, no sign-in); (2) a script `db/create_finance_bi_user.ps1` like
  `create_readonly_user.ps1` (login from `.env` `PG_BI_USER` / `PG_BI_PASSWORD`, `GRANT finance_bi`, and
  `ALTER ROLE … SET default_transaction_read_only = on` on the login — role settings are not inherited); (3) PBIP
  project `powerbi/` in git, DirectQuery to the `finance` views (PostgreSQL connector: check the Npgsql requirement
  of the installed version first); (4) the 5 pages of §2 with simple DAX only (sums / selections of view columns);
  (5) the Power BI Modeling MCP for the model; done when the dashboard numbers for 3 weeks = `kpi_weekly`. Ask the
  owner each design choice with AskUserQuestion (clickable, recommendation first). Still pending: §8a (G1–G6) review.
- **Earlier handoff (Phase 1 close):** Phases 0 and 1 are CLOSED. Phase 1 (2026-10-14): ADR-046, migration 012 applied and verified (§17), finance
  data in `customers`, `vessels.customer_id`, `payments`, `budget_weekly`, `finance_test.*`; generator
  `pipelines/scripts/synthetic/Finance_generator.py`. **Next (assistant): Phase 2** — the `finance` schema: star views
  (`fact_invoice` with the derived due date and as-of status, `fact_payment`, `dim_date` ISO week, `dim_customer`,
  `dim_vessel`, `dim_toll_band`) + KPI views / functions per `report_week` + `docs/finance_metrics.md` (one definition
  per metric). Propose the metric definitions to the owner first (DSO formula, AR aging buckets, "collections", budget
  variance), then a migration 013; done when every KPI equals a hand-computed value on 3 chosen weeks and a non-Finance
  employee gets nothing. Still pending: the owner's review of §8a (G1–G6, PROPOSED); the last 5 bake-off T4 items
  (record only).
- **Also decided on 2026-10-14:** no data guard (ADR-037 amendment 2: all data synthetic / public, used as if paid;
  `llm.py` has no `data_origin`); chat in **Egyptian colloquial Arabic only** (owner asked many times — no MSA).
- **Environment notes:** Docker Desktop stops on reboots / sleep → start it, `docker start ports-postgres ports-qdrant`
  (owner may have set `--restart unless-stopped`), wait for `pg_isready -U postgres`; after an unclean shutdown the
  planner statistics are reset → owner runs `ANALYZE`. Owner actions still open: `GEMINI_TIER=paid` in `.env`;
  delete the superseded bake-off results `llm_bakeoff_2026-10-11.json` and `llm_bakeoff_2026-10-13.json` (ADR-045
  cites `llm_bakeoff_2026-10-12.json`); empty `Notebooks\_scratch\`.
- **Earlier handoff (2026-10-12):** Phase 0 is CLOSED (2026-10-12) — ADR-045 Accepted. **Next (assistant): Phase 1** — first show the owner the
  concrete generation rules of the finance data (§4: customers ~40, payment terms 30 / 45 / 60, payment behaviour
  classes, `vessels.customer_id`, payments consistent with the end-of-2025 status, `budget_weekly` rule, labelled
  test weeks with planted errors) as a proposal → owner approval → an ADR (D6) → generator script (fixed seed, CSVs +
  manifest, ADR-031 pattern) → migration (owner applies) → `verify_readonly.sql` section. Also pending: the owner's
  review of §8a (G1–G6, PROPOSED); one bake-off run on 2026-10-13 completes the last 5 T4 items for the record
  (3.8 Flash 4, laguna 1; cannot change the selection).
- **Earlier state (kept for reference):** Phase 0 done except the bake-off's last runs. Branch `feat/agents`. Installed and pinned: the 12
  packages (ARCHITECTURE §8). Written: `pipelines/agents/llm.py`, `pipelines/scripts/agents/LLM_smoke_test.py`
  (3 providers pass), `LLM_bakeoff.py` (tasks frozen `TASKS_SHA256 = ed6723f5…`, results
  `Data/processed/agents/eval/llm_bakeoff_2026-10-11.json`, narrative `pipelines/checkpoints/agents/LLM_bakeoff.md`),
  `.gitattributes`, `.env.example`, the local skills folder (5 reviewed langchain-skills), ADR-037 amendment, **ADR-045
  PROPOSED** (Writer / Insight qwen3.8-27b + gemini-3.5-flash-lite; Tools gemini-3.5-flash-lite + gpt-oss-20b).
  Every decision and deviation of Phase 0 is in "Progress / deviations" above.
- **Next (assistant):** (1) start Docker (`ports-postgres`, `ports-qdrant`; wait for `pg_isready`), re-run
  `uv run python tools/run.py pipelines/scripts/agents/LLM_bakeoff.py --timeout 14400` once per day until it prints
  `selection FINAL` — missing: `gemini/gemini-3.8-flash` (12 / 24 LITE; 20 requests / day) and
  `openrouter/poolside/laguna-s-2.1:free` (16 / 24 LITE; upstream 429, OpenRouter 50 / day); gemma finished its LITE
  on 2026-10-11 (selection unchanged). Replies come from
  `llm_cache/`, so a re-run only spends the missing calls. (2) If the selection changes, update ADR-045; then set it
  Accepted (or the owner accepts it as is if a candidate stays unavailable). (3) Close Phase 0 in "Progress", start
  **Phase 1** (finance data generator: show the concrete rules to the owner first, D6 → ADR).
- **Owner actions:** commit (commands given in chat); delete `Data/processed/agents/eval/llm_bakeoff_2026-10-11.json`
  (superseded by `llm_bakeoff_2026-10-12.json`; the 2026-10-10 file is already deleted); later `LANGCHAIN_API_KEY` (Phase 8), the web-search key (Phase 4), the
  aisstream.io key (Phase 9); `Notebooks\_scratch\` can be emptied when Phase 0 closes (deletions are denied for
  the assistant).
- **Owner preferences:** free tiers / free tools first; the assistant implements everything and reports (no TODO(human));
  chat in Egyptian Arabic, code and docs in English; one decision at a time, recommendation first.
