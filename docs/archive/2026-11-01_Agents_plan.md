# Plan — Multi-agent platform: Stage 1 the Weekly Finance Pack, Stage 2 the Operations Desk

## Implementation record (read this first)

- **Status: IMPLEMENTED (2026-11-01)** — Phases 0–12 done on the owner's machine (Stage 1: Phases 0–8 + §5f + candidate
  c4; Stage 2: Phases 9–12); archived the same day.
- **Results — Stage 1, the Weekly Finance Pack:** the `finance` star + KPI views (migrations 012–019, 021), the Power
  BI dashboard (PBIP, DirectQuery, 6 pages + Executive), the Stage 1 tools + reviewed skills, the LangGraph
  `weekly_pack` (PostgresSaver in `agent_state`, approval interrupt, number slots, Validator v2 + V8, the NileGate
  PPTX, the code fallback of c4), the scheduled firing every Monday 10:30 with retention and LangSmith, the finance
  Q&A agent. Evaluation (ADR-052 / ADR-053): the final baseline `stage1_eval_2026-10-23_confirm.json` missed D7 only
  on `planted_all`; **candidate c4 met it** (2026-11-01: planted 6 / 6 in all three runs, published 32 / 33 vs 24 / 33,
  narrative recall 0.9655 vs 0.7471; kept on a hand-check, D-C4-1). The Q&A after the `finance-qa` change:
  `stage1_eval_2026-10-31_dp127b.json`, every gate, completeness EN / AR 1.0.
- **Results — Stage 2, the Operations Desk:** the Stage 2 tools (ADR-055, no live AIS ADR-056), `route_advice`
  (ADR-057), `voyage_watch` every 12 h (ETA MAE 0.885 h vs naive 117.8 h; ADR-058), the supervisor over both
  products with a code router and partial answers (`Ask.py`; ADR-059). Done-when met by candidate c1
  `stage2_eval_2026-10-30_c1.json` (completeness EN 0.98 / AR 0.95, leakage 0).
- **Deviations (details in "Progress / deviations"):** D7 was first closed as not met by the owner (Phase 7, then the
  confirmation run) and met only by c4 after Stage 2; the finance Q&A moved to `create_agent` and its CLI was replaced
  by the supervisor's `Ask.py`; Phase 11 ran in an autonomous session, reviewed afterwards; the Groq fallback cannot
  take the supervisor's large requests (ADR-045 amendment 3); a code year guard after D-P12-7's reject (D-P12-12);
  two scorer false positives of the same family, both true sentences (D-P8-16, D-C4-1); side work kept by the owner:
  the annual executive deck (ADR-061, a misread scope), the weekly-pack improvement study + migration 021
  (`docs/analysis/financial_intelligence/`), and Sentry S1 started before this close (ADR-062,
  `docs/plans/Observability_Sentry_plan.md`).
- **Lasting decisions:** ADR-045 – ADR-059 (+ amendments), ADR-060 (the web frontend, PLANNED), ADR-061, ADR-062.
- **Next:** the one Stage 2 commit by the owner (Stage 2 + c4 + Sentry S1); the active plan is
  `docs/plans/Observability_Sentry_plan.md` (S1's first real check-in Monday 2026-11-02, then S2–S4); then the
  weekly-pack improvement Phases B–E (candidate c5 vs c4) and FastAPI (`docs/ROADMAP.md`).

---

- **Status (original):** APPROVED (2026-10-09) — every decision answered by the owner (§7 "Answers"); owner: "the same plan in
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
| S1 ✔ | **Stage 1 checkpoint:** ADRs, ARCHITECTURE, ROADMAP, a PR; the plan stays active | **DONE 2026-10-27:** PR mahmoudsameh00/nilegate-ports-ai#1 (`feat/agents` → `master`, 16 commits) merged by the owner, merge commit `5e49ad6` |
| **Stage 2** | | |
| 9 ✔ | Stage 2 tools: `sea_route` (Suez vs Cape distances; `searoute` restriction support checked here), `voyage_status`, ~~`vessel_live` (aisstream.io)~~ (dropped, P9-2 / ADR-056), `marine_weather`; fuel / speed parameter table (S2-D3) + `vessel_params` | each tool tested; live tools degrade gracefully — **DONE 2026-10-27** (§6a, ADR-055; `Stage2_tools_check.py` Phases 0–5 ✅) |
| 10 ✔ | **B Route & Cost Advisor** graph (`route_advice`): inputs vessel + origin / destination; outputs a Pydantic comparison (distance, sea days at the vessel's speed, Suez dues via `compute_toll`, fuel estimate from the parameter table, risk context: PortWatch trend + news) and a recommendation with its assumptions; the Validator checks every number | the S2 route cases (§8) pass — **DONE 2026-10-27** (§6b, ADR-057; `Route_advice_check.py` all phases ✅, real model 8 / 8) |
| 11 ✔ | **C Voyage & Disruption Watch** graph (`voyage_watch`): ETA (baseline: remaining sea distance / recent speed), delay risk (weather on the next legs, Suez traffic), alerts saved to a table / file (save only) and shown on request; scheduled every N hours (S2-D1) | ETA error on replayed synthetic voyages beats the naive baseline (§8); alerts reproducible — **DONE 2026-10-28** (§6c, ADR-058; `Voyage_watch_check.py` Phases 1–7 + 4s ✅: MAE 0.885 h vs naive 117.8 h; planted events precision = recall = 1.0; autonomous grant, owner to review) |
| 12 | Supervisor extended to both products; cross-product questions; RBAC matrix (Operations ↔ Finance) | S2 Q&A golden questions pass; RBAC leakage 0 |
| 13 | Close: ADRs, ARCHITECTURE, ROADMAP, archive the plan | — |

### 5a. Phase 4 — Stage 1 tools + skills: concrete design (APPROVED 2026-10-18 by the owner; decisions P4-1…P4-8)

**Owner decisions (2026-10-18, all the recommended option):** P4-1 one KPI tool with a closed `dataset` choice;
P4-2 Auditor = SQL views (migration 015) + an independent Python `compute_toll` cross-check; P4-3 the user is
injected by the graph, never an LLM argument; P4-4 web search = Tavily free tier (called with `httpx`, no new
package); P4-5 the evaluation copy gets a twin view in schema `finance_test` (never in `finance`); P4-6 the Auditor
diagnoses the cause with fixed checks; P4-7 external cache frozen for past windows, TTL 24 h when a window reaches
today, timeout 10 s, failure → `context_unavailable`; P4-8 skill body ≤ 1,200 tokens, description ≤ 250 chars.

**Files (new):** `pipelines/agents/tools/` — `context.py` (user + RBAC guard), `db.py` (read-only `psycopg_pool`,
`PG_RO_USER`, `default_transaction_read_only`), `schemas.py` (Pydantic results), `tariff.py`, `finance.py`,
`audit.py`, `documents.py`, `external.py`, `__init__.py` (`STAGE1_TOOLS`); `pipelines/agents/skills.py` (loader +
`load_skill`); `pipelines/agents/skills/<name>/SKILL.md` ×6; `db/migrations/015_invoice_audit_views.sql`;
`pipelines/scripts/agents/Tools_check.py` (percent format, ✅ lines, Final Checkpoint; the project's test form — no
pytest). Nothing existing is changed except `.env.example` / `common.SECRET_KEYS` (`TAVILY_API_KEY`), the docs, and
`verify_readonly.sql` (a §19 for the audit views).

**Common contract (every tool).** A plain Python function `f(user, **args)` (testable without an LLM) + a LangChain
wrapper whose args schema the model sees; the wrapper takes the user from the run context (`ToolRuntime.context`),
so **no tool schema has a user / employee field** (P4-3). `User` and `allowed()` are reused from
`pipelines/lib/retrieval.py` (one RBAC rule, ADR-006); the user is read once per run / question from PostgreSQL.
Each result is a Pydantic model with `status` ∈ {`ok`, `not_permitted`, `context_unavailable`, `no_data`}, the rows,
and `source` (view / table / URL + the exact filter) for the Validator and the deck's appendix. `not_permitted`
carries no number and no row. Parameterized SQL only; no free SQL anywhere.

| Tool | Args (what the model sees) | Reads | Access (ADR-006) | Result |
|---|---|---|---|---|
| `finance_kpi` | `report_week` 1–52, `dataset` ∈ {`weekly`, `category`, `customers`, `overdue`, `trend`}, `limit` (customers / overdue, default 10) | `finance.kpi_weekly` / `kpi_weekly_category` / `kpi_customer_13w` / `kpi_overdue_list` / `kpi_weekly_trend`, `WHERE report_week = %s` | level 2 / Finance | rows exactly as the view (the Power BI numbers), `is_warmup`, source |
| `invoice_audit` | `report_week` or `invoice_numbers` (≤ 50), `dataset` ∈ {`live`, `test`} | `finance.invoice_audit` / `finance_test.invoice_audit` | level 2 / Finance | findings + invoices checked + amount at stake, source |
| `compute_toll` | `vessel_category`, `laden_ballast`, `scnt_tons` (or `vessel_id`) | `toll_rate_bands` (+ `vessels`) | level 1 | amount, terminal band and rate, the band-by-band breakdown (SFU → Laden, ADR-004) |
| `search_documents` | `query`, optional filters (ADR-039) | existing `retrieval.search_documents` | per chunk (existing) | the existing result with citations |
| `suez_transits` | `start`, `end` (dates) | IMF PortWatch daily chokepoint transits (Suez Canal; public ArcGIS service, field names verified at implementation) | level 1 | daily transit calls (+ by vessel type if published), a 7-day mean, source URL + retrieval date |
| `web_search` | `query`, `start_date`, `end_date` | Tavily search API (`TAVILY_API_KEY`) | level 1 | ≤ 5 results: title, URL, published date, snippet — **untrusted text** (`untrusted-content` skill; ADR-011) |

**Migration 015 — audit views (P4-2, P4-5, P4-6).** `finance.invoice_audit` over `invoices` and the twin
`finance_test.invoice_audit` over `finance_test.invoices` (same SQL; the vessel's category and condition come from
`vessels`, since the test copy has no condition column). Expected amount = the progressive toll of the **vessel's**
SCNT (Σ rate × tons inside each band; SFU → Laden). One row per finding, `check_code`:
`tonnage_mismatch` (invoice SCNT ≠ vessel SCNT — catches the digit swap whose amount is right),
`amount_mismatch` (|billed − expected| > 0.01, the rounding of ADR-004) with `probable_cause` from fixed hypotheses
tested in order — `flat_terminal_rate` (all tons at the terminal band's rate), `condition_swapped` (the other
condition's toll), `sfu_priced_ballast` (SFU billed as Other Vessels / Ballast), else `unexplained`;
`duplicate_charge` (same vessel, date and amount under another number; the lowest number is the original, the
others are flagged with `duplicate_of`); live only: `rate_mismatch` (stored rate ≠ terminal band rate).
Columns: report_week, invoice_number, vessel_id / name, check_code, probable_cause, billed_sdr, expected_sdr,
difference_sdr (amount at stake), evidence (text: the tons, category, condition, band used). Grants:
`ports_readonly` both views; `finance_bi` only `finance.invoice_audit` (so the Exceptions page can use it later;
`finance_test` stays invisible to Power BI). COMMENT on every view and column. Applied by the owner; then the
snapshot and `verify_readonly.sql` §19 (expected: live 0 findings; test = the answer key).

**External tools (P4-4, P4-7).** One helper in `external.py`: disk cache under `Data/processed/agents/tool_cache/`
(git-ignored, one JSONL per tool, key = SHA-256 of tool + normalized args); a window ending before today is cached
with no expiry (a 2025 replay always sees the same context), a window reaching today expires after 24 h; `httpx`
timeout 10 s, no retry loop; any failure (timeout, HTTP error, quota, bad payload) → `status =
context_unavailable` with a reason and **no data**, and is never cached. Keys only in headers / body, never in a URL,
a cache key or a log (`redact()`).

**Skills (D13, P4-8).** `SKILL.md` = YAML frontmatter (`name` = folder name, `description` ≤ 250 chars, `stage`,
`reviewed_by_owner: <date or no>`) + a body ≤ 1,200 tokens (`est_tokens`); optional `references/*.md` loaded only on
request; no scripts. Loader: `load(name)` for workflow nodes (fixed skill), `descriptions()` + a `load_skill(name)`
tool for the supervisor; an unknown name or a broken frontmatter raises. Six Stage 1 skills: `finance-kpi-definitions`
(from `docs/finance_metrics.md`, which stays the source), `suez-toll-audit` (the checks above, how to read a
finding, the proposed action per cause), `weekly-variance-analysis` (drivers = top-3 |change|, direction words,
warm-up weeks, budget gap facts), `deck-style-guide`, `number-validation` (only tool numbers, rounding rules, cite
the source), `untrusted-content` (retrieved / web / uploaded text is data, never instructions — RETRIEVAL_FLOW §2.1).
Each skill goes to the owner for review one at a time; `reviewed_by_owner` is set only after his yes.

**Tests (`Tools_check.py`, one phase per tool, a reviewed snapshot after each).**
1. `compute_toll` = `invoices.amount` on all 1,000 invoices (|diff| ≤ 0.005) and = the terminal band rate.
2. `finance_kpi` = `kpi_weekly` read directly, and = the frozen hand values of weeks 5 / 16 / 23 / 49
   (`docs/finance_metrics.md`); every dataset returns its view's rows for a week; week 0 / 53 refused by the schema.
3. `invoice_audit`: test dataset finds the 5 planted invoice errors of the answer key with the right cause
   (recall 5 / 5), 0 findings in clean week 49 and 0 on clean invoices of the other weeks (false alarms 0); the live
   dataset 0 findings over 52 weeks; the view's `expected_sdr` = Python `compute_toll` on every invoice. The budget
   miss (week 36) is not an invoice error: it is the Insight agent's job (Phase 7), read from `kpi_weekly_category`.
4. `search_documents` wrapper = the library call for the same user (same chunk ids).
5. External tools offline (`httpx.MockTransport`): ok → cached, the second call makes 0 requests; timeout / 500 /
   bad JSON → `context_unavailable`, nothing cached, no number; then one live call each (owner's network and key).
6. **RBAC matrix:** every employee (100) × every tool → granted = the ADR-006 expectation; a denied call returns
   `not_permitted` with no rows (leakage 0); no tool's args schema contains a user field.
7. Skills: every `SKILL.md` parses, name = folder, description / body within budget, every skill listed by the
   loader; `reviewed_by_owner` set on all six before the phase closes.

**Order (one step at a time, each with its check before the next):** S1 foundation (`context`, `db`, `schemas`)
→ S2 `compute_toll` → S3 `finance_kpi` → S4 migration 015 (owner applies) → S5 `invoice_audit` → S6
`search_documents` wrapper → S7 external tools (owner creates the Tavily key) → S8 RBAC matrix → S9 skill loader +
the six skills (owner review) → S10 close (ADR-049, ARCHITECTURE, ROADMAP, `rbac_mapping.md`, handoff).

### 5b. Phase 5 — the `weekly_pack` graph, PostgresSaver, approval: concrete design (APPROVED 2026-10-19 by the owner, as written; IMPLEMENTED 2026-10-19, ADR-050 — deviations D-P5-1…D-P5-9 in Progress)

**Owner decisions (2026-10-19, all the recommended option; AskUserQuestion):** P5-1 hybrid nodes — Data
Readiness, KPI and Auditor are deterministic code calling the tool functions with the run's user (no LLM); Insight
is an agent (LLM ↔ `ToolNode(STAGE1_TOOLS)` loop, then one structured call); the Writer is one structured call;
P5-2 Writer = a structured `DeckDraft` (no PPTX yet), Validator = a first deterministic number check with the loop
back to the Writer (max 2 rewrites, then stop) — the PPTX template, the template-text allowlist and the G1 rules
stay in Phase 6; P5-3 migration 016: schema `agent_state` + NOLOGIN role `agent_writer` with DML only (default
privileges), a login `ports_agent` created from `.env` by a script, `setup()` run with the owner account as a
deployment step — the runtime login cannot run DDL; P5-4 the approver must be a Finance manager or the CEO (checked
in PostgreSQL at resume); an edit goes back through the Validator and to a new interrupt; reject ends the run; the
decision + diff are logged (G5); P5-5 a scheduled pack runs as a configured Finance manager (`--as <employee_id>`),
not the CEO (least privilege: no level 3); P5-6 resume is proven by killing a real process mid-run; P5-7 the 52
weeks run end to end with a fake LLM, the real models run on 4 weeks (cached); P5-8 Insight binds all six
`STAGE1_TOOLS`, gets compact KPI / audit summaries (not all rows), `search_documents` with `k = 3`, and every LLM
call's tokens are measured (fail > 7,000 against Groq's 8K TPM, then the owner decides).

**Graph (LangGraph `StateGraph`, `context_schema = RunContext`, `durability = "sync"`):**

```text
START → readiness ─(not ready / not permitted)→ END (status + reasons, no LLM call)
          └→ kpi → audit → insight_llm ⇄ insight_tools (ToolNode(STAGE1_TOOLS), ≤ 4 rounds) → insight_notes
          → writer → validator ─(fail, rewrites < 2)→ writer
                       ├─(fail, 2 rewrites)→ END (validation_failed + the diff)
                       └─(pass)→ approval ⏸ interrupt ─ approve → publisher → END (published)
                                                     ├ edit → validator (→ approval again)
                                                     ├ reject → END (rejected)
                                                     └ approver not allowed → approval again (refusal logged)
```

| Node | Kind | Reads | Writes to state | Skill (`skill_loader.load`) |
|---|---|---|---|---|
| `readiness` | code | `finance.kpi_weekly`, `finance.fact_invoice` for the week (parameterized, read-only pool; RBAC `FINANCE_VIEWS` first) | `readiness` {ready, checks, reasons}: R1 the week's KPI row exists; R2 invoices in the week > 0; R3 0 nulls in the key fields (customer, due date, amount, category); R4 as-of ≤ the data horizon 2026-03-31; notes (warm-up week) do not gate | — |
| `kpi` | code | `finance_kpi` × 5 datasets (weekly, category, customers 10, overdue 10, trend) | `evidence["kpi.<dataset>"]` = the `ToolResult` dumps | — |
| `audit` | code | `invoice_audit(report_week)` with the context's dataset (`live`; `test` only from the harness) | `evidence["audit.week"]` + a summary (findings by code, amount at stake) | — |
| `insight_llm` / `insight_tools` | agent (Writer / Insight role) | compact summaries of the evidence; tool calls through `ToolNode`, which passes `RunContext` to the tools | `messages` (add_messages); each tool result also as `evidence["insight.<tool_call_id>"]` | `weekly-variance-analysis`, `untrusted-content` |
| `insight_notes` | one structured call | the loop's messages | `insight` (`InsightNotes`: drivers, explanations, context items, each with evidence ids) | (same) |
| `writer` | one structured call (Writer role) | summaries + `insight` + the Validator's last diff | `draft` (`DeckDraft`), `rewrites` | `deck-style-guide`, `number-validation` (+ `suez-toll-audit` when the week has findings) |
| `validator` | code | `draft`, `evidence` | `verdict` {passed, problems} | — |
| `approval` | `interrupt()` | the payload below | `approval_log` (every decision, refusal and edit diff) | — |
| `publisher` | code | approved `draft` | `reports/2025-W<ww>/deck_draft.json`, `approval.json`, `run.json` (models, calls, tokens); "Draft for approval" replaced | — |

**State (`TypedDict`, JSON-only values so every checkpoint is plain data):** `report_week`, `status` ∈ {running,
not_ready, not_permitted, validation_failed, awaiting_approval, rejected, published}, `readiness`, `evidence`
(dict id → ToolResult dump), `messages`, `insight`, `draft`, `verdict`, `rewrites`, `approval_log`, `published`,
`llm_usage` (per call: role, model, cached, tokens). The user and the dataset are **not** in the state: they come
from the run context on every invocation (and resume), as in ADR-049.

**Models (new `pipelines/agents/graphs/models.py`, Pydantic, shallow):** `InsightNotes`, `DeckDraft` (title, slides
→ bullets {text, evidence_ids}), `Verdict`, `ApprovalDecision` {decision ∈ approve / edit / reject,
`approver_employee_id`, `edits` [{slide, bullet, text}], `comment`}. Interrupt payload: report week, thread id, the
draft, the verdict, readiness notes, audit summary. Resume: `Command(resume=ApprovalDecision.model_dump())`.

**LLM roles (new `pipelines/agents/roles.py`, over `llm.py` only):** role → (main, fallback) of ADR-045 with each
model's structured method (`function_calling` qwen / flash-lite, `json_schema` gpt-oss); `Exhausted` on the main →
the fallback; usage recorded. The graph receives the roles as a dependency (`build_graph(roles, checkpointer)`), so
the check script can pass a `FakeRoles` (same `invoke(...) → Reply` interface, scripted replies built from the
evidence numbers; variants with a planted wrong number for the Validator loop).

**Validator, first version (P5-2):** V1 every bullet with a digit cites ≥ 1 existing evidence id of a structured tool
(`finance_kpi`, `invoice_audit`, `compute_toll`; ADR-049: never a document or web row); V2 every number token (sign,
decimals, %, k / M) equals a numeric field of the cited evidence after the `number-validation` rounding (half away
from zero, sign kept, `*_pct` already percent); V3 the title says "Draft for approval". The problems list is the diff
sent back to the Writer.

**Checkpointer (P5-3; D3).** `db/migrations/016_agent_state.sql` (applied by the owner): `CREATE SCHEMA agent_state`
(owner postgres); `CREATE ROLE agent_writer NOLOGIN`; CONNECT on the database, USAGE on `agent_state`, `ALTER DEFAULT
PRIVILEGES FOR ROLE postgres IN SCHEMA agent_state GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES` (+ sequences) to
`agent_writer`; nothing in `public` or `finance`; `ports_readonly` and `finance_bi` get nothing (checkpoints hold
level-2 Finance numbers: `rbac_mapping.md` gets `agent_state` = level 2 / Finance, at rest). COMMENTs. Then
`db/create_agent_user.ps1` (login `ports_agent` ∈ `agent_writer`, `search_path = agent_state`, password from / into
`.env` as `PG_AGENT_USER` / `PG_AGENT_PASSWORD`, like `create_finance_bi_user.ps1`) + `db/check_agent_user.py`
(checkpoint tables writable, DDL refused, `public` / `finance` refused). Deployment step:
`pipelines/scripts/agents/Checkpointer_setup.py` runs `PostgresSaver.setup()` as the owner account with
`search_path = agent_state` (autocommit; the library's own migrations) and lists the tables. Runtime:
`pipelines/agents/checkpointer.py` — one `psycopg_pool` on `ports_agent` (autocommit, `dict_row`,
`prepare_threshold=0`, as the library requires). `verify_readonly.sql` §20 (schema, grants, tables). **To verify at
implementation (UNCERTAIN):** the table names and DDL of `langgraph-checkpoint-postgres` 3.1.2 and that its
`setup()` runs entirely inside the `search_path` schema.

**Run identity and threads (P5-5).** `thread_id = weekly_pack:<dataset>:2025-W<ww>:<attempt>`; the same week twice =
a new attempt number, never the same thread. CLI `pipelines/scripts/agents/Weekly_pack.py`: `run --week 23 --as
<employee_id>` (stops at the interrupt, prints the payload summary) and `resume --thread <id> --decision
approve|edit|reject --as <employee_id> [--edits file.json]`. `--dataset test` is not offered by the CLI (harness only).
`reports/` is generated output → git-ignored.

**Tests (`pipelines/scripts/agents/Weekly_pack_check.py`, percent format, ✅ lines, reviewed snapshots, Final
Checkpoint; `InMemorySaver` until migration 016, then PostgresSaver):**
1. Deterministic nodes on all 52 weeks: readiness ready 52 / 52; evidence = the tool functions called directly; a
   forced not-ready case ends with no LLM call; an Operations employee → `not_permitted`, no number in the state.
2. Fake-LLM pack on all 52 weeks: each reaches the interrupt with the Validator passed; approve → the three files;
   reject → `rejected`, nothing published; an edit with a wrong number → refused by the Validator; an approver who is
   not a Finance manager / CEO → refused, interrupt again; the approval log holds every step.
3. Validator loop: a planted wrong number → caught → rewritten → pass; an always-wrong Writer → `validation_failed`
   after 2 rewrites.
4. Crash and resume (P5-6): a subprocess runs a week and `os._exit`s inside `writer`; the main process resumes the
   same thread: the nodes before it are not re-run (0 new tool or LLM calls), the final state = an uninterrupted run.
5. Real models (P5-7) on weeks 5 (warm-up), 10 (duplicate charge), 23, 49: each reaches the interrupt or a stated
   stop status (reported: Validator passes, rewrites, fallbacks); every LLM call ≤ 7,000 tokens (P5-8); cached, so a
   re-run makes 0 calls.
6. Contract: no tool schema has a user field (re-checked through `ToolNode`); `dataset="test"` reaches the audit only
   through the harness context.

**Order (one step at a time, each with its check):** S1 `models.py` + `roles.py` + `FakeRoles` → S2 the deterministic
nodes (test 1) → S3 Insight loop + Writer + Validator + approval + publisher on `InMemorySaver` (tests 2, 3, 6) → S4
migration 016 + login script + check (the owner applies; asked first) + `Checkpointer_setup.py` + `verify_readonly`
§20 + snapshot → S5 PostgresSaver + crash / resume (test 4) → S6 real models on the 4 weeks + the CLI (test 5) → S7
close (ADR-050, ARCHITECTURE, ROADMAP, `rbac_mapping.md`, checkpoint narrative, handoff).

**Files (new):** `pipelines/agents/graphs/__init__.py`, `graphs/models.py`, `graphs/weekly_pack.py` (state, nodes,
`build_graph`), `pipelines/agents/roles.py`, `pipelines/agents/checkpointer.py`, `db/migrations/016_agent_state.sql`,
`db/create_agent_user.ps1`, `db/check_agent_user.py`, `pipelines/scripts/agents/Checkpointer_setup.py`,
`Weekly_pack.py`, `Weekly_pack_check.py`, `pipelines/checkpoints/agents/Weekly_pack_check.md`. **Changed:**
`.env.example` + `common.SECRET_KEYS` (`PG_AGENT_PASSWORD`), `.gitignore` (`reports/`), `db/verify_readonly.sql`
(§20), the docs. Nothing in the Phase 4 tools or skills changes.

**Carried, not in Phase 5:** Validator allowlist / G1 / PPTX (Phase 6); the planted budget miss in
`finance_test.budget_weekly` (Phase 7); the Exceptions page from `finance.invoice_audit` (Power BI, separate step);
the tariff Notes rules (later migration); retention of old checkpoints and LangSmith (Phase 8).

### 5c. Phase 6 — NileGate PPTX template, Writer, Validator: concrete design (PROPOSED 2026-10-19; decisions P6-1…P6-8 answered; APPROVED 2026-10-19 by the owner, as written; IMPLEMENTED 2026-10-19, ADR-051 — deviations D-P6-1…D-P6-16 in Progress)

**Owner decisions (2026-10-19, all eight the recommended option; AskUserQuestion):** P6-1 slots, P6-2 code writes the
fixed parts, P6-3 direction written by code (`|dir`), P6-4 native PowerPoint charts, P6-5 template as code, P6-6
patch rewrite, P6-7 the Validator reads the PPTX back, P6-8 gate = the planted-number test, real models reported.

**Inputs (Phase 5 S6, `weekly_pack_real.json`).** Week 5 failed on "Dry Bulk Vessels … down 30.78 %" and "(down
399940.41 SDR)" for −30.78 / −399,940.41; week 23 on "down 15.8 %", "down 1070881.98 SDR" and "Top ten customers
generated 59.5 %" cited from `kpi.customers` (the value is `kpi.weekly.top10_share_13w_pct`); week 49 passed with
"down −43.08 %" (right, but a double negative). So the Writer's errors are **signs next to direction words** and
**the wrong evidence id**, not wrong digits. The Validator's hole: V2 accepts a number equal to **any** numeric field of
the cited evidence (a category's value under another category's name passes). Writer prompts 10–17K tokens; a
rewrite resends the whole draft (+ 3–5K). The template allowlist is a regex of five phrases.

**Decisions (recommended option first; the owner answers):**

| # | Question | Recommended | Alternative(s) |
|---|---|---|---|
| P6-1 | How numbers enter the Writer's text | **References (slots)** — the Writer writes `{kpi.weekly:billed_wow_pct\|%1}`, code fills the formatted value; every number is bound to its field by construction | (B) free text + a declared (evidence, row, field) per number in the bullet; (C) free text, the Validator infers the field |
| P6-2 | What code writes vs the Writer | **Code**: slide 1, the KPI tiles (3), every table and chart, the footnotes, slide 10; **Writer**: the slide titles, the 5 summary bullets, ≤ 3 comment bullets on slides 3–8, the context bullets of slide 9 | (B) the Writer writes every bullet as now, code only lays them out |
| P6-3 | How a negative change is written | **Direction + magnitude written by code** (`\|dir` → "down 30.8 %"); a direction word the Writer writes itself is checked against the sign (G1) | (B) always a signed number ("−30.8 %"), the Writer's direction words checked |
| P6-4 | Charts | **Native PowerPoint charts** (python-pptx `add_chart`: editable by Finance, their values readable back by the Validator — probed 2026-10-19 on 1.0.2) | (B) matplotlib PNG images (the plan's first idea; a picture the Validator cannot read) |
| P6-5 | The template | **Template as code** (`deck/style.py`: 16:9, NileGate palette, fixed category colours, positions; blank layout); a designed `.pptx` with named layouts can replace it later | (B) the owner designs a `.pptx` in PowerPoint first, code fills its placeholders |
| P6-6 | The rewrite | **Patch**: the Writer gets only the failing bullets / titles with their problems grouped and a fix hint, returns replacements, code merges them | (B) the whole deck again, problems de-duplicated |
| P6-7 | The rendered file | **The Validator also reads the PPTX back** (every text, table cell and chart point) before the approval and before publishing | (B) validate the draft only; the renderer is trusted |
| P6-8 | Done-when and real models | **Gate = the planted-number test** (100 % caught, the expected rule, 0 false alarms on 52 clean decks); real models on weeks 5 / 10 / 23 / 49 **reported** (target: 4 / 4 reach the approval; a miss goes to the owner) | (B) also a gate on 4 / 4 real weeks |

**Deck = code parts + Writer parts (P6-2).** Evidence per slide (V5) — the Writer may cite only these ids on a slide:

| Slide | Code renders | Writer writes | Evidence allowed |
|---|---|---|---|
| 1 Title | "NileGate Weekly Finance Pack", `iso_week_label`, `week_start – week_end`, the label "Draft for approval" | — | `kpi.weekly` |
| 2 Executive summary | — | title + exactly 5 bullets (weekly-variance-analysis order) | `kpi.*`, `audit.week` |
| 3 KPI tiles | six tiles: billed, collected, AR, overdue, DSO, budget variance; WoW only where the view has one; warm-up footnote | title + ≤ 3 comments | `kpi.weekly` |
| 4 Revenue trend | chart: 13-week billed vs budget, the week highlighted; table: top 3 drivers (category, billed, change, WoW %) | title + ≤ 3 comments | `kpi.trend`, `kpi.category`, `audit.week` |
| 5 Revenue mix | chart: billed by vessel category (fixed colours), budget marker | title + ≤ 3 comments | `kpi.category` |
| 6 Receivables | chart: aging buckets; table: the 5 largest overdue invoices; DSO + change; warm-up footnote | title + ≤ 3 comments | `kpi.weekly`, `kpi.overdue` |
| 7 Customers | table: top 10 on 13 weeks (rank, previous rank, billed, share); the top-10 share | title + ≤ 3 comments | `kpi.customers`, `kpi.weekly` |
| 8 Exceptions | table: findings by amount at stake (+ action from `suez-toll-audit`); or "N invoices checked, none flagged" | title + ≤ 3 comments | `audit.week` |
| 9 Context | — | title + context bullets (source + date), "context unavailable" where a tool said so | `insight.*` |
| 10 Sources and freshness | every evidence's tool, view / API and filter; readiness facts; retrieval times; what was not checked; the injection notice (untrusted-content) | — | — |

**Slots (P6-1, `deck/slots.py`, one module for the renderer, the approval payload and the Validator).** Syntax
`{<evidence id>:<field>|<format>}` for one-row results (`kpi.weekly`, the audit totals) and
`{<evidence id>[<row key>]:<field>|<format>}` for lists — key = `vessel_category` (category), `customer_name`
(customers), `invoice_number` (overdue, audit), `trend_week_label` (trend). Formats, allowed by the field's suffix
(number-validation rule 2): `_sdr` → `sdr` (as returned, thousands separators) / `M` (2 decimals) / `k` (1 decimal);
`_pct` → `%2` / `%1`; `_days` → `d` (1 decimal); counts → `n`; change fields (`*_wow_*`, `*_change_*`,
`*variance*`) are always signed ("+" / "−") unless `|dir` (P6-3: "up 30.8 %", "down 1.07 M SDR", "unchanged"). Half
away from zero (the existing `_quant`). Literal digits left in the Writer's text: only the report week / year,
identifiers and dates of the cited evidence, and nothing else (structural counts in words, rule 8).

**Validator v2 (code, `validate(draft, evidence, week)` + `validate_pptx(path, draft, evidence)`):**
- **V1** citations exist and have data (as now). **V5** a bullet cites only its slide's allowed evidence.
- **V2 slots** resolve: the evidence id has status ok, the row key matches exactly one row, the field exists, is
  numeric and not null, the format is allowed for the field. The problem names what exists ("`kpi.customers` has no
  field `top10_share_13w_pct`; `kpi.weekly` has it") — the fix the Writer needs, in one line.
- **V2 literals** (a human edit, or a Writer that ignores the slots): a literal number is **bound to a field** — it
  must equal, after an allowed rounding, a field of a row the sentence names (category, customer, invoice, week
  label; a one-row result: its row); a number that only matches another row or another dataset fails (G1, closes the
  "any field" hole). "down 30.78 %" binds to −30.78 (the word carries the sign, P6-3); "down +x", "fell" with a
  positive value, a negative value with "up" fail.
- **V6 direction (G1)**: a direction word (up / down, rose / fell, increased / decreased / declined / dropped / grew,
  above / below budget) in the clause of a change value (slot or bound literal) must agree with its sign.
- **V7 attribution (G1)**: a category called a driver is among the week's top 3 by |`billed_wow_change_sdr`| (week
  1: |`budget_variance_sdr`|); every vessel category and invoice number written exists in the week's evidence; a slot
  sits in a clause with a word of its field's family (billed / revenue, collected / collections, AR / receivables,
  overdue, DSO, budget, share) and not under another family's word — a right number under the wrong label fails.
- **V3** the draft label, **V4** the deck's shape (10 slide titles, 5 summary bullets, ≤ 3 comments per slide).
- **V8 the PPTX read back (P6-7)**: the renderer names every shape (`tpl:<key>` fixed text, `bind:<evidence>…` a
  bound value, `txt:<slide>.<bullet>` Writer text); `validate_pptx` reopens the file and checks: every `tpl:` shape
  = its template constant exactly (**the full template allowlist, by construction** — the regex goes), every bound
  text / table cell / chart point = its field in its format, every `txt:` shape = `render_text` of the draft, no
  shape without a name. A number changed in the file, not only in the draft, is caught.

**Writer (P6-1, P6-6).** The prompt gives, per slide, its purpose, the evidence it may cite and the slot syntax with
three examples; the rounding rules leave the prompt (code formats). Output: `DeckDraft` (unchanged shape, text with
slots). A rewrite gets a `DeckPatch` request: the failing bullets / titles only, problems grouped per bullet with a
one-line fix hint, the evidence they cite — not the previous draft — and returns replacements by index; code merges
them and the Validator runs on the whole deck again (max 2 rewrites, as now). Tokens per call measured and reported
(expected below the S6 12–17K).

**Rendering and graph (P6-4, P6-5, P6-7).** New package `pipelines/agents/deck/`: `style.py` (16:9, the NileGate
palette, 13 fixed category colours, fonts, positions), `slots.py`, `render.py` (`render(draft, evidence, readiness,
label) → bytes`, one function per slide, native charts and tables), `readback.py` (PPTX → named items for V8). The
`validator` node renders in memory and runs V8 after V1–V7; the approval payload gains the path of a draft preview
(`reports/2025-W<ww>/draft/deck.pptx`, overwritten); the `publisher` renders the approved deck with "Approved",
re-runs V8 on the saved file and writes `deck.pptx` next to the three JSON files. The state stays JSON (path +
SHA-256, never the bytes).

**Tests.** New `pipelines/scripts/agents/Deck_check.py` (percent format, ✅ lines, reviewed snapshots, Final
Checkpoint): (1) slot cases (syntax, every format, rounding half away from zero, signs, `|dir`, refused formats);
(2) 52 clean decks from the fake Writer rendered → V1–V8 pass on 52 / 52 (false alarms 0), 10 slides, native charts,
footnotes on weeks 1–13 only; (3) **planted wrong numbers** — a frozen catalogue of mutation classes (a digit changed,
sign flipped, a cut instead of a rounding, × 100, k ↔ M, another field of the same row, the same field of another
row, another dataset, a direction word flipped, a non-driver called a driver, an unknown invoice number, a template
phrase changed, a table cell / chart point changed in the file, a web number) on weeks 5 / 10 / 23 / 49, in the draft
and in the PPTX → 100 % caught with the expected rule; (4) the recorded S6 failures replayed (caught); (5) real models
on weeks 5 / 10 / 23 / 49 with the new Writer (≈ 20 fresh flash-lite calls; cached after). `Weekly_pack_check.py`:
`PackScript` writes slots, the Phase 3 rule cases move to the new rules, Phase 5 re-snapshotted.

**Order (one step at a time, each with its check):** S1 `deck/slots.py` + Deck_check Phase 1 → S2 Validator v2
(V1–V7, literal binding) + Phase 3 on drafts → S3 `style.py` + `render.py` + `readback.py` + V8 + Phases 2–3 on the
PPTX (the owner opens one rendered deck) → S4 Writer prompt + `DeckPatch` rewrite + graph / payload / publisher +
`Weekly_pack_check.py` → S5 skills `deck-style-guide` and `number-validation` updated (slots, code parts, `|dir`) →
**owner re-review** → S6 real models (Phase 5 of both scripts) → S7 close (ADR-051, ARCHITECTURE, ROADMAP,
checkpoint narrative, handoff).

**Files (new):** `pipelines/agents/deck/__init__.py`, `style.py`, `slots.py`, `render.py`, `readback.py`,
`pipelines/scripts/agents/Deck_check.py`, `pipelines/checkpoints/agents/Deck_check.md`. **Changed:**
`pipelines/agents/graphs/weekly_pack.py` (Writer prompt, patch rewrite, Validator v2, payload, publisher),
`graphs/models.py` (`DeckPatch`, rules V5–V8), the two skills, `Weekly_pack_check.py`, `Weekly_pack.py` (show the
preview path), the docs. No migration, no new package (python-pptx 1.0.2 is pinned; matplotlib stays pinned, unused
by the pack if P6-4 = A).

**Not in Phase 6:** golden weeks and G2–G6 metrics (Phase 7); laden / ballast split (needs a view); the Power BI
Exceptions page; scheduling (Phase 8).

### 5d. Phase 7 — evaluation on golden weeks + finance Q&A: concrete design (PROPOSED 2026-10-19; §8a reviewed and decisions P7-1…P7-4 answered; APPROVED 2026-10-19 by the owner, as written; IMPLEMENTED 2026-10-20, ADR-053 — deviations D-P7-1…D-P7-12 in Progress; CLOSED by the owner with D7 not met, candidate c2 carried)

**Owner decisions (2026-10-19, AskUserQuestion, all the recommended option).** §8a review: **G1** as written + the
Writer style notes counted and reported (not blocking); **G2** ~10 Egyptian Arabic finance questions now (patterns and
threshold frozen before any run, scored apart from English); the 24 document twins wait for the Supervisor (Phase
12), their retrieval is already measured (ADR-040); **G3** abstention / RBAC cases inside the ~30 questions, hard
gate; **G4** deterministic only, no LLM judge (deferred: another provider, quota, 20 owner-graded answers);
**G5** reported only, measured from real approvals in Phase 8 (Phase 7 checks the diff is logged); **G6** margin 0.03,
every compared setup run twice (model variance: runs 2 / 4 / 5 of Phase 6 published 3 / 4 / 3 with one prompt).
Phase 7: **P7-1** a small finance Q&A agent (below), **P7-2** the budget miss read through twin views (migration 017),
**P7-3** `InMemorySaver` for eval runs, **P7-4** a temp folder per eval run (table).

| # | Question | Recommended | Alternative(s) |
|---|---|---|---|
| P7-3 | Checkpointer of the evaluation runs | **`InMemorySaver`** — the eval threads do not fill `agent_state` (no retention job yet); PostgresSaver and resume were proven in Phase 5 (test 4) and stay in `Weekly_pack_check` | (B) PostgresSaver with `weekly_pack:eval:…` thread ids, deleted after the run |
| P7-4 | Where an eval pack is published | **a temp folder per run** (`%TEMP%`, removed after scoring; decks of failed or sampled weeks copied to `Notebooks/_scratch/`) — `reports/` keeps only real packs | (B) `reports/_eval/<run>/` (git-ignored) |

**What Phase 7 measures (D7 + §8a), all deterministic:**

| Metric | Definition | Gate (D7 / §8a) |
|---|---|---|
| Deck numbers | every number of a published deck bound to its (evidence, row, field) and equal to it (V2 / V8, re-checked by the harness against the frozen expected KPIs, not only the Validator) | **100 %** (hard) |
| Planted errors found | of the 5 planted invoice errors (the planted budget miss is not a miss: D-P7-1): reported in the published deck where expected (below) | **≥ 95 %** = 5 / 5 on every repeat (hard) |
| False alarms | an invoice called wrong / a category called a budget miss that is not in the expected findings (clean week 49 + the live weeks) ÷ findings reported | **≤ 5 %** (hard) |
| Claim accuracy (G1) | direction + attribution claims of the published decks re-checked by an independent rule set on the frozen expected values (drivers = top 3, signs, named rows exist) | **100 %** (hard) |
| Traceability | every number of a deck / an answer has a citation (slots: by construction) and the citation's source is in the sources slide / the answer's sources | **100 %** (hard) |
| RBAC leakage | a denied question's answer holds no number / fact of the denied resource | **0** (hard) |
| Abstention (G3) | recall and precision of "not in the data" / "not permitted" on the abstention items | recall **100 %** (hard), precision reported |
| Narrative finding recall | expected narrative findings of the golden weeks (drivers named, budget miss named, warm-up caveat, live duplicates noted) present in the summary / comments | primary score (G6) |
| Q&A completeness (G4) | share of a question's required elements present (number + unit + period, or the fact); relevance = the week and metric of the question appear | primary score (G6); EN and AR apart |
| Style notes (G1 extension) | counts: a direction word before a signed slot ("up +18.64 %"), a bullet with no number and no named row after a patch, an adjective from a frozen list in a title (surged, plunged, soared…) | reported |
| Cost / runtime | calls, tokens in / out per pack and per question, fallbacks, Validator rewrites, latency, publish rate (packs reaching the approval / published) | reported; quota per run below |

**Golden weeks (~11, chosen by a script before any run, `Golden_weeks.py`; the list and its hash frozen).**
- **Test dataset (`finance_test`, `dataset="test"`):** weeks **10, 23, 36, 49** — the 5 planted invoice errors, the
  planted budget miss (week 36, LNG Carriers, budget × 1.5) and the clean week 49 (false-alarm check).
- **Live dataset, by stated rules on `finance.kpi_weekly` / `kpi_weekly_category` (ties → lowest week; a week picked
  twice → the next one):** a warm-up week (week **5**, already a Phase 6 week), the quiet week (smallest
  |`billed_wow_pct`|, weeks 14–52), the peak week (max `billed_sdr`), the trough week (min `billed_sdr`, weeks 14–52),
  the largest live budget miss (min `budget_variance_pct`, weeks 14–52), a week with a real duplicate charge (week
  **15** or **50**, Phase 4 finding (d)), the week where Suez transits moved most (largest |WoW| of weekly PortWatch
  transits in 2025, from the frozen `suez_transits` cache).
- Weeks 5 / 10 / 23 / 49 shaped the Phase 6 prompts and Validator → results are reported **seen vs unseen** (an honest
  view of how much the tuning fit those weeks).
- **Expected KPIs by SQL:** the script freezes, per golden week, the rows of `kpi.weekly`, `kpi.category`,
  `kpi.customers` (top 10), `kpi.overdue` (top 5) and `audit.week` from the views (test weeks from the twin views) into
  `Data/processed/agents/eval/golden_weeks.json` (+ SHA-256 in the manifest).
- **Expected findings by hand:** per week, a short list written by the assistant from those rows and reviewed by the
  owner before any run — each finding = {id, kind (driver / budget_miss / invoice_error / duplicate / caveat), the
  row key (category / invoice), where it must appear (table by code / narrative by the Writer)}. Invoice findings come
  from the answer key; the narrative ones are what a finance analyst would say first.

**The planted budget miss (P7-2) — migration `017_finance_test_kpi.sql` (owner applies).** Two twin views in
`finance_test`, same columns as their live views so `finance_kpi` only switches the view name:
`finance_test.kpi_weekly` and `finance_test.kpi_weekly_category`, for the 4 test weeks only: billed / invoices /
budget / variance from `finance_test.invoices` + `finance_test.budget_weekly`; WoW against the **live** previous week
(the copy holds no week w−1; stated in the view comment); AR / aging / overdue / DSO / top-10 share taken from the
live row (the copy has no payments; stated). `finance_kpi` reads the twins when the run context says `test`
(`category` / `weekly` only; `customers`, `overdue`, `trend` stay live, with a note). The test copy is invisible to
`finance_bi` (as the audit twin). ~~Read: in week 36 the LNG row shows budget × 1.5 and a large negative variance —
expected narrative finding "LNG Carriers billed far below budget".~~ **D-P7-1:** it does not — LNG stays above budget
(+37.63 %, live +106.44 %); the twins still give the test weeks consistent books (billed with the planted errors).
`Tools_check.py` gets a case: test weeks = the views recomputed in pandas from the copy, live weeks unchanged.

**Finance Q&A golden set (frozen before any run, `Data/processed/agents/eval/finance_qa_golden.jsonl` + hash).**
~30 English questions, written by the assistant, reviewed by the owner:
- 22 answerable: week KPI lookups (billed, collected, AR, overdue, DSO, budget variance) ~8; WoW / vs budget ~5;
  drivers by category ~3; customers / top-10 share ~3; overdue invoices ~2; a toll computation (`compute_toll`) ~1.
- 4 abstention: a week outside 2025, a metric that does not exist (e.g. profit margin), a customer that does not
  exist, a future week.
- 4 RBAC: an Operations employee asking for receivables / the overdue list; a Finance employee and a manager asking
  for the level-3 HbR financial results (CEO only); the CEO asking the same (answerable — the control case).
- Each item: question, user (employee id), expected status (answered / not_in_data / not_permitted), required elements
  (tool, dataset, week, row key, field, value — from the views at freeze time), relevance tokens (week, metric).
- **Arabic (G2):** Egyptian Arabic versions of 10 answerable items, same expected elements; Arabic relevance patterns
  (أسبوع / الأسبوع + the number, the metric's Arabic words) frozen with them; threshold fixed before the run:
  AR completeness ≥ EN completeness − 0.10.

**The finance Q&A agent (P7-1, `pipelines/agents/graphs/finance_qa.py`).** One LangChain agent (`create_agent`) on the
`tools` role (ADR-045: flash-lite + gpt-oss-20b), with `STAGE1_TOOLS` + `load_skill`, `context_schema = RunContext`
(user and dataset from the run, never from the model, ADR-049). Its final answer is a Pydantic `QaAnswer` {status:
answered / not_in_data / not_permitted, text with **slots** (`deck/slots.py`, the same syntax), cited evidence ids};
code fills the slots from the tool results kept in the run and checks them with the Validator's slot and literal rules
(V1 / V2 / V6 / V7 subset); a failing answer gets one patch, then status `validation_failed`. A tool's
`not_permitted` must end in status `not_permitted` with no number (code check). Answer language = the question's
language; `|dir` gets an Arabic rendering (ارتفع / انخفض / بدون تغيير) in `slots.py`. A short skill
`finance-qa` (≤ 1,200 tokens: answer shape, slots, abstention, sources) — reviewed by the owner like the others.
Phase 12 grows this agent into the Supervisor.

**G6 acceptance rule → ADR-052, written before the first comparison (step S1).** A change (prompt, model, skill) is
kept only if, over two runs each of baseline and candidate: no hard gate fails (deck numbers 100 %, planted 6 / 6,
false alarms ≤ 5 %, G1 100 %, traceability 100 %, RBAC 0, abstention recall 100 %), and neither primary (narrative
finding recall on golden weeks; Q&A completeness, EN and AR) falls by more than **0.03** (mean of the two runs);
ties keep the simpler / cheaper setup. The first full run is the baseline file
`Data/processed/agents/eval/stage1_eval_<date>.json`.

**Quota per run (measured in Phase 6: a pack ≤ 7 calls — Insight ≤ 4 rounds, Writer 1, ≤ 2 patches — each ≤ 12.4K
tokens).** One full evaluation = 11 weeks × 2 repeats ≈ ≤ 154 pack calls (≤ 1.9M input tokens, flash-lite) + 40
questions × 2 repeats × ~3 calls ≈ 240 Q&A calls (~5K tokens each, ≈ 1.2M). flash-lite's free daily limit is not
published → every reply cached (`llm.py`), the run resumes the next day where it stopped, quota use printed per phase;
the OpenRouter fallback (50 requests / day) is counted and reported; the harness first runs with fake models (0
calls). A repeat with a cache hit is not a repeat: the second run uses a run salt in the cache key (a fresh call).

**Harness `pipelines/scripts/agents/Stage1_eval.py`** (percent format, ✅ lines, reviewed snapshots, Final
Checkpoint `pipelines/checkpoints/agents/Stage1_eval.md`): Phase 1 the frozen inputs (golden weeks, findings, Q&A set:
hashes, expected values = the views now); Phase 2 the scorers on hand-made good / bad decks and answers (each metric
proven to catch its failure — a scorer that never fails proves nothing); Phase 3 the golden weeks with fake models (0 calls,
every gate passes); Phase 4 Q&A with fake answers; Phase 5 real models (only with
`EVAL_REAL_MODELS=1`): packs + questions, two repeats, the results file, D7 verdict printed.

**Order (one step at a time, each with its check):** S1 ADR-052 (G6) + `Golden_weeks.py` (weeks by rule, expected KPIs)
→ owner reviews the expected findings → S2 migration 017 (owner applies; snapshot + `verify_readonly.sql` new section
by the assistant) + `finance_kpi` test switch + `Tools_check` case → S3 the Q&A golden set (EN + AR) → owner review,
frozen → S4 `finance_qa.py` + `QaAnswer` + skill `finance-qa` (owner review) + fake-model check → S5 `Stage1_eval.py`
Phases 1–4 → S6 real models (Phase 5), the results file, the D7 verdict → owner decides → S7 close (ADRs, ARCHITECTURE,
ROADMAP, checkpoint narrative, handoff).

**Files (new):** `db/migrations/017_finance_test_kpi.sql`, `pipelines/scripts/agents/Golden_weeks.py`,
`Stage1_eval.py`, `pipelines/agents/graphs/finance_qa.py`, `pipelines/agents/skills/finance-qa/SKILL.md`,
`Data/processed/agents/eval/golden_weeks.json`, `finance_qa_golden.jsonl`, `stage1_eval_<date>.json`,
`pipelines/checkpoints/agents/Stage1_eval.md`, `Golden_weeks.md`. **Changed:** `pipelines/agents/tools/finance.py`
(test twins), `pipelines/agents/deck/slots.py` (Arabic `|dir`), `graphs/models.py` (`QaAnswer`),
`pipelines/agents/roles.py` only if the Q&A needs its own role entry, `Tools_check.py`, `db/verify_readonly.sql`,
`docs/rbac_mapping.md` (the twins), `docs/decisions.md` (ADR-052), the docs at close. No new package.

**Not in Phase 7:** an LLM judge (G4); the 24 Arabic document twins (Phase 12); edit rate from real approvals (G5,
Phase 8); the Power BI Exceptions page; scheduling, LangSmith (Phase 8).

### 5e. Phase 8 — scheduling, LangSmith tracing, checkpoint retention: concrete design (PROPOSED 2026-10-20; decisions P8-1…P8-4 answered; APPROVED 2026-10-20 by the owner, as written; IMPLEMENTED 2026-10-22, ADR-054 — deviations D-P8-1…D-P8-12 in Progress; CLOSED 2026-10-22)

**Owner decisions (2026-10-20, AskUserQuestion, all the recommended option):** P8-1 the next week of the replay, one
pending pack at a time; P8-2 weekly, Monday 10:30, logged-on only, retries, log + toast; P8-3 archive, then delete
ended threads older than 30 days, pending never deleted; P8-4 tracing on the operator entry points only.

**Done when (§5):** a run started by Windows Task Scheduler produces the pack and waits at the approval; the owner
then approves (or edits / rejects) it through the CLI. **Starting point (seen 2026-10-20):** `agent_state` holds one
thread (`weekly_pack:live:2025-W10:1`, published; `reports/2025-W10/`); `Weekly_pack.py run --week N --as E` starts
a pack by hand; `.env.example` and `common.SECRET_KEYS` already name `LANGCHAIN_API_KEY` (no key set); `langsmith`
0.14.7 is installed; `agent_writer` already has DELETE (migration 016) → **no migration in Phase 8**, no new package.

| # | Question | Recommended | Alternative(s) |
|---|---|---|---|
| P8-1 | Which week a scheduled run makes (D12: replay of 2025) | **The next week of the replay:** the week after the highest published week (W10 → W11, …); **one pending pack at a time** — if a thread waits at the approval, the run starts nothing and logs "waiting for approval of W<ww>"; a week whose last attempt stopped (`validation_failed`, `output_invalid`, `not_ready`) is retried once on the next firing with a new attempt, then skipped and logged | (B) today's ISO week number → the same week of 2025 (2026-10-20 → W43; jumps, gaps); (C) a fixed week in a config file |
| P8-2 | When and how the task runs | **Weekly, Monday 10:30 Cairo time** (after the Gemini daily reset: midnight Pacific = 09:00–10:00 Cairo all year), "run only when the user is logged on" (no stored Windows password; Docker Desktop runs only after logon anyway), "run as soon as possible after a missed start", retry twice every 30 min on failure, 1 h time limit; a PostgreSQL / Docker probe first (down → exit code + log, the retry handles it); one log line per firing in `reports/_log/scheduled.jsonl` + a Windows toast "W<ww> waits for your approval" (built-in WinRT, no module) | (B) daily 10:30 (one 2025 week per day: faster replay, same quota rules); (C) log only, no toast |
| P8-3 | Checkpoint retention (D3; `agent_writer` DELETE) | **Archive, then delete whole threads:** a thread that **ended** (published / rejected / any stop status) and whose last checkpoint is older than **30 days** → its approval log, status and stop reason appended to `reports/_log/threads_archive.jsonl` (the G5 record outlives the thread; a published pack already has `approval.json` / `run.json`), then `PostgresSaver.delete_thread`; a thread **waiting at the approval is never deleted** (reported when older than 14 days); `--dry-run` prints what would go; runs at the end of every scheduled firing and by hand (`Weekly_pack.py prune`) | (B) keep every thread, prune only old checkpoints inside a thread (keeps the latest; saves less, more code: no library call for it); (C) by hand only |
| P8-4 | LangSmith tracing (D8, free developer plan) | **On for the operator entry points only:** `Weekly_pack.py` (run / resume / scheduled) and the Q&A when a key exists; **off** in the checks and in `Stage1_eval.py` unless `EVAL_TRACE=1` (one evaluation ≈ 400 calls; the free plan's monthly trace allowance is for real runs); project `nilegate-agents`; each trace tagged with thread id, week, dataset, run identity; full inputs / outputs (all data synthetic or public, ADR-037 amendment 2); the key name becomes `LANGSMITH_API_KEY` (`.env.example`, `SECRET_KEYS` — the library still reads `LANGCHAIN_API_KEY`); tracing failure never fails a run | (B) on everywhere through `.env`; (C) off by default, `--trace` per command |

**Fixed with the design (not a separate question):** the scheduled run identity = a Finance manager set in `.env`
(`PACK_RUN_AS`, P5-5; checked in PostgreSQL at start); the task is registered by a PowerShell script in the repo
(`ops/scheduler/register_weekly_pack.ps1`, owner runs it once; `-Unregister` removes it); the scheduled command is
`Weekly_pack.py scheduled` (idempotent: two firings the same day never start two attempts); **G5 edit rate** =
`Weekly_pack.py report` over `reports/2025-W*/approval.json` + the archive (approve / edit / reject counts, edited
slides and sentences) — reported, never scored; the pack runs on flash-lite (≈ 6 calls a pack; quota guard of
D-P7-11 unchanged); `web_search` returns `context_unavailable` until Tavily's monthly credits reset (the pack already
handles it: the context slide says so).

**Order (one step at a time, each with its check):** S1 the week picker + `scheduled` / `prune` / `report` commands
on fake models and a temporary thread prefix (`weekly_pack:check:`) → `Scheduler_check.py` (picker rules, one pending
at a time, idempotent firing, retention: archive lines then delete, pending untouched, the run identity survives) →
S2 LangSmith: the owner creates the key (free developer plan) and puts it in `.env`; tracing wired; one fake-model run
read back from LangSmith (`langsmith.Client`: the trace, its tags) → S3 the task registered by the owner; one firing
by `Start-ScheduledTask` (real models) reaches the approval → owner decides through the CLI → `report` shows the
decision → S4 close (ADR-054, ARCHITECTURE, ROADMAP, checkpoint narrative, handoff).

**Files (new):** `pipelines/agents/scheduling.py` (week picker, retention, archive), `pipelines/agents/tracing.py`
(on / off + tags over `langsmith`), `ops/scheduler/register_weekly_pack.ps1`,
`pipelines/scripts/agents/Scheduler_check.py`, `pipelines/checkpoints/agents/Scheduler_check.md`. **Changed:**
`Weekly_pack.py` (commands `scheduled`, `prune`, `report`), `pipelines/lib/common.py` (`SECRET_KEYS`),
`.env.example`, `Stage1_eval.py` (`EVAL_TRACE`), the docs at close.

**Not in Phase 8 (carried):** candidate c2 (one full evaluation on a fresh provider day; can share a day with
scheduled packs: ≈ 400 + 6 < 500); the owner's review of skill `finance-qa`, D-P7-1…D-P7-12 and the Q&A golden set
notes; the Power BI Exceptions page; tariff Notes rules.

**Amended 2026-10-21 (owner, while candidate c3 is under test):** the `Stage1_eval.py` change (`EVAL_TRACE`) and the
Q&A entry point's tracing wait until c3 is judged — tracing is a context around each graph run (D-P8-5), so the
evaluation stays untraced unedited; S3's real firing on 2026-10-22 after c3 finishes. (Done 2026-10-22: `EVAL_TRACE`
added, D-P8-11.)

### 5f. Phases 7–8 closure — no open point left (PROPOSED 2026-10-22; owner decisions C-1…C-4 answered; APPROVED 2026-10-22 by the owner: "ابدأ", order F1…F9; DONE 2026-10-23 — F8 = the final Stage 1 baseline, D7 not met on `planted_all`; deviations D-P8-13…D-P8-16 in Progress)

**Why:** before the one commit of Phases 7–8 and the Stage 1 checkpoint, the owner asked that no point stay carried
or unclear. Inventory 2026-10-22 (plan Progress / handoffs, ROADMAP, ADRs, skills, Power BI, live probes):

| # | Open point | How it closes (owner decision 2026-10-22, AskUserQuestion) | Needs |
|---|---|---|---|
| K1 | Owner reviews: D-P7-1…D-P7-15, the ADR-052 reading for a failing baseline, skill `finance-qa` (`reviewed_by_owner: no`), the Q&A golden set, findings v2 | **C-1: one by one in the chat**; each accepted point recorded (`reviewed_by_owner: <date>` for the skill), each change made and checked | owner |
| K2 | D-P7-15 not measured in a real run; D7 missed by one slot; scorer notes (q14 / q01_ar relevance words, r04's number form) | **C-2: one confirmation evaluation** (2 runs, ≈ 400 flash-lite calls) on 2026-10-23 after 07:00 UTC, golden set **frozen**; it is a measurement, not a tuning candidate: its results = the final Stage 1 baseline and the D7 verdict; the scorer notes become documented limits in ADR-053 | quota day |
| K3 | ADR-045 fallback broken (OpenRouter nemotron → 404 on every request) | **C-3: a new free fallback**: smoke test of free OpenRouter models able to take the 10–17K-token prompts, then a forced-fallback pack on weeks 5 / 10 / 23 / 49 (≈ 30 OpenRouter calls, no flash-lite); ADR-045 amendment 2 | OpenRouter |
| K4 | Power BI Exceptions page = placeholder | **C-4: build it now** from `finance.invoice_audit` with the Power BI Modeling MCP (table + visuals, each explained; ADR-048 patterns) | Power BI Desktop open |
| K5 | Tariff Notes rules not modelled by the audit | **C-4: migration 018** — an invoice of a Notes category (ballast Petroleum Product / Chemical tankers, OBO) whose price differs from its own bands is `manual_review`, not an error (twin view too); a planted case in `Tools_check.py`; owner sees the SQL before it is applied | migration |
| K6 | Q&A tracing (no operator entry point) | a small operator CLI `Finance_qa.py ask "…" --as E [--lang ar]` (traced like the pack; fake-model check) | — |
| K7 | `langsmith` `list_runs` deprecated after 2027-01-31 | move `Scheduler_check.py` Phase 5 to the replacement API if the installed 0.14.7 offers a sync one; else pin the reason in the check's header (the check fails loudly if the call disappears) | — |
| K8 | CLI approval log prints `reason` (empty) instead of the `--comment` text | `Weekly_pack.py show` prints the comment | — |
| K9 | "Tavily monthly credits used up" | **closed 2026-10-22 by a probe:** plan Researcher, 40 / 1,000 used; one live `web_search` → ok, 2 rows — the carry was stale | — |

**K1 outcome (2026-10-22, Progress):** 13 points accepted, 5 changed — they add work before the confirmation run.

**Order (each step with its check; the evaluation measures everything at once, so it runs last):**
- **F1 small code:** K8 (`show` prints the comment), K7 (`list_runs` → the replacement API or a pinned note),
  D-P7-14's promise (every code fix of a slot's form counted in `run.json` and `Weekly_pack.py report`) →
  `Scheduler_check`, `Weekly_pack_check`, `Deck_check`.
- **F2 the Q&A on `create_agent` (D-P7-6)** + a chat-model adapter over `llm.py` (cache, quota, fallback unchanged)
  + middleware (tool-call limit ≤ 3 rounds, the answer check + one patch) + `Finance_qa_check.py` (D-P7-7) + the
  operator CLI `Finance_qa.py` (K6, traced) → `Stage1_eval.py` Phase 4 unchanged in result.
- **F3 the planted budget miss (D-P7-1):** migration 018 (one `finance_test.budget_weekly` row: LNG, W36 = billed ×
  1.5) + the generator's rule + `verify_readonly.sql` section + snapshot; `Golden_weeks.py` re-freezes the test
  weeks' evidence; findings v3; the miss scorer (Phase 2 cases); planted gate 6 / 6 (ADR-052 / ADR-053 amended).
- **F4 the Q&A golden set v2 (D-P7-3, D-P7-4, scorer notes):** two askers per profile, +1 Finance-employee level-3
  question (31 EN + 10 AR), the metric synonyms and number forms by rule → `Qa_golden.py` re-freeze.
- **F5 migration 019 (K5):** Notes categories priced off their own bands → `manual_review` in `finance.invoice_audit`
  and its twin; a planted case in `Tools_check.py`; the SQL shown to the owner before it is applied.
- **F6 Power BI Exceptions page (K4):** `finance.invoice_audit` into the model (DirectQuery, `ports_bi`), a findings
  table + KPI cards + the "manual review" note; numbers = the view for 3 weeks.
- **F7 the new fallback (K3):** smoke test of free OpenRouter models (context ≥ 32K, tool calling, structured
  output), a forced-fallback pack on weeks 5 / 10 / 23 / 49 → ADR-045 amendment 2.
- **F8 the confirmation evaluation (K2):** two runs on the first fresh provider day after F1–F7 (≈ 400 flash-lite
  calls), against c3 — **a measurement**: its file is the final Stage 1 baseline; D7 met or not, reported as is.
- **F9 close:** ADR-045 / 049 / 051 / 052 / 053 / 054 updates, ARCHITECTURE, ROADMAP, CLAUDE.md, handoff → the owner's
  one commit → the Stage 1 checkpoint (§5 "S1 ✔": a PR of `feat/agents`) → Phase 9 (§6a).

**Not in scope (older, not Phases 7–8; listed so nothing is hidden):** ROADMAP known issues — `tools/nb_to_script.py
check` "checkpoint differs" ×6, the guard-hook confirmation on Windows, `SyntheticGenerator` not reproducible on
Linux, the undocumented toll CSV extraction.

## 6. Stage 2 — Operations Desk (details)

- **Users:** Operations employees / managers and the CEO (level-1 operational data). Finance data stays invisible to
  them (level 2 / Finance), and the agents enforce that in their tools.
- **B Route & Cost Advisor.** "Should vessel X (Laden, 85,000 SCNT) sail Singapore → Rotterdam via Suez or the Cape?"
  (corrected 2026-10-27: the first example, Port Said → Rotterdam, never uses the canal — §6a F1a) →
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

### 6a. Phase 9 — Stage 2 tools: concrete design (draft 2026-10-22; P9-1…P9-4 answered 2026-10-23; concrete design PROPOSED 2026-10-27; P9-5…P9-8 answered; APPROVED 2026-10-27 by the owner, as written; IMPLEMENTED 2026-10-27, ADR-055 / ADR-056 — deviations D-P9-1…D-P9-11 in Progress)

*The draft table and P9-1…P9-4 below are kept as written; the concrete design follows them ("Concrete design").*

**Goal (§5):** the Operations tools, each tested on its own; live tools degrade gracefully. **Starting point:**
`searoute` 1.6.0 installed (ADR-032 used it for the synthetic tracks), MongoDB AIS / EDI + `voyages_synthetic.parquet`,
the Stage 1 tool contract (ADR-049: `f(user, **args) → ToolResult`, RBAC first, the user from the run context, cache +
10 s timeout + `context_unavailable`), `compute_toll` (the Suez dues), PortWatch.

| Tool | Source | Returns | RBAC / failure |
|---|---|---|---|
| `sea_route` | `searoute` (MARNET), Suez vs Cape by the library's passage restrictions (support checked first, P9-4) | distance (nm), the route's waypoints (simplified), the passages used | level 1 public; deterministic, no network |
| `voyage_status` | MongoDB `ais_positions` + `voyages_synthetic.parquet` (our 500 vessels, as of 2026-09-13) | last position, speed, next port, legs left, distance left | level 1 Operations; the app user (read only) |
| `vessel_live` | aisstream.io WebSocket (free key, P9-2), one bounding box, a short window (S2-D4) | real vessels seen (counts by type, a few positions) — situational only, never linked to ours (ADR-028) | public external; no key / timeout → `context_unavailable` |
| `marine_weather` | Open-Meteo Marine + Forecast (free, no key) at route points | wave height, wind, swell per point and day | public external; cached per (point, day) |
| parameters | a documented table per vessel type (service speed, fuel t / day; sources cited) + the bunker price set by the owner with its date (S2-D3) | — | read by `route_advice` (Phase 10) |

| # | Question | Recommended | Alternative(s) |
|---|---|---|---|
| P9-1 | Where the parameter table lives | a reference CSV in `db/reference/` loaded by **migration** into a small table (documented, sourced; the DB is the source, like the toll bands) | a Python constant; a JSON file read by the tool |
| P9-2 | aisstream.io | the owner creates the free key (`AISSTREAM_API_KEY`); the tool samples ≤ 30 s per call | skip live AIS in Stage 2 (synthetic tracks only) |
| P9-3 | Bunker price | one VLSFO price in USD / t set by the owner with its date, converted to SDR at a dated rate stored beside it (money in SDR, ADR-003) | quote fuel in tonnes only (no money) |
| P9-4 | Suez vs Cape | `searoute`'s restriction list (block Suez → the Cape route) if supported; else two fixed corridors through waypoints | always the shortest path + a Cape alternative by waypoints |

**Answers (owner, 2026-10-23, AskUserQuestion):** P9-1 **CSV in `db/reference/` + migration** (recommended); P9-2
**no live AIS in Stage 2** (the alternative): `vessel_live` leaves Phase 9, the synthetic tracks only, no aisstream.io
key — D11 narrowed (web search, PortWatch, marine weather), ADR at Phase 9 close; P9-3 **one dated VLSFO price in
USD / t → SDR at a dated rate** (recommended); P9-4 **`searoute` restrictions, support checked first, else two fixed
corridors** (recommended).

**Checks (draft):** `Stage2_tools_check.py` (each tool against its source; hand-computed routes Port Said → Rotterdam
both ways; RBAC matrix extended; failure modes: no key, timeout, bad input). **Not in Phase 9:** the `route_advice` and
`voyage_watch` graphs (Phases 10–11).

#### Concrete design (PROPOSED 2026-10-27; APPROVED 2026-10-27 by the owner, as written)

**Verified facts (2026-10-27, read-only probes; scripts and outputs in the session's scratchpad, summary in the shared
notes).**
- **F1 `searoute` 1.6.0 supports restrictions (P9-4 → the library, no fixed corridors).** `searoute(origin, destination,
  units="naut", restrictions=[…], return_passages=True)`; passages: `babalmandab`, `bosporus`, `gibraltar`, `suez`,
  `panama`, `ormuz`, `northwest`, `malacca`, `sunda`, `chili`, `south_africa`, `bering`; the default list is
  `["northwest"]` and must be kept when a passage is added. Singapore ↔ Rotterdam 8,383 nm (malacca, babalmandab, suez,
  gibraltar) / with Suez blocked 11,871 nm (sunda, south_africa), the same both ways — published 8,288 / 11,755 nm (Port
  of Rotterdam Authority, via trade press): +1.1 % / +1.0 %. Jeddah → Rotterdam 4,026 / 10,995 nm. Blocking Bab
  el-Mandeb alone also sends Singapore round the Cape (the Red Sea case). First call ~1.2 s (network load), then ms.
- **F1a Port Said ↔ Rotterdam never uses the canal:** 3,310 nm via Gibraltar both ways, identical with Suez blocked —
  Port Said is the canal's Mediterranean end. §6's example question ("Port Said → Rotterdam via Suez or the Cape") has
  no Cape alternative: the route cases use origins east of the canal (Singapore, Jeddah, …) and keep Port Said ↔
  Rotterdam as the case where "avoid Suez" changes nothing. **F1b** A port inside the Gulf of Suez (Sokhna) with Suez
  blocked has no path: `searoute` returns length 0, an empty line and a `UserWarning` (no exception).
- **F2 `voyages_synthetic.parquet`** (500 × 13: vessel_id, voyage_no, status, origin / destination_locode,
  departure_ts, arrival_ts, last_fix_ts, route `A>B>C`, route_nm, route_fallback, service_kn, ais_ship_type):
  In Transit 219, At Port 130, Anchored 78, Completed 73. `arrival_ts` is the generator's truth; for the 219 In Transit
  vessels it lies after the as-of instant (up to 2026-11-23) = the ETA evaluation's answer key. Intermediate ports are
  waypoints with no dwell (the generator sails origin → destination at the vessel's `service_kn`, harbour speed over
  the first / last 10 nm): S2-D2's port-call allowance is 0 in this data (a Phase 11 note).
- **F3 Route geometry is reproducible:** rebuilding each route from `route` with `searoute` per leg (the generator's
  `sea_leg` rule, ports' lon / lat) gives `route_nm` for 498 / 498 routes (|diff| ≤ 0.05 nm; 1,474 legs, 11 s); the 2
  fallback vessels (323, 442) are one great-circle leg.
- **F4 MongoDB:** `ais_positions` = `ts`, `meta{mmsi, imo, source, real_or_synthetic, load_run, source_sha256}`, `loc`
  (GeoJSON), `sog`, `cog`, `heading`, `navstat`, `src_row`, `sensitivity_level`, `department`; index `mmsi_ts` → a
  vessel's last fixes in ms. `ais_vessels` (synthetic) has `vessel_id`, `destination_locode` and `eta_raw` = the
  generator's `arrival_ts` (`%m-%d %H:%M`): **the answer key again** (P9-7). The app user is `readWrite` (ADR-027).
- **F5 Open-Meteo (free, no key):** Marine `https://marine-api.open-meteo.com/v1/marine`, daily `wave_height_max`,
  `swell_wave_height_max`, `wind_wave_height_max` (hourly too), `forecast_days` ≤ 8, `past_days` ≤ 92, and
  `start_date` / `end_date` on past days (probe 2026-09-13…15: values at 3 points); several points in one request
  (comma lists → a JSON list); a land point → `null`. Wind: Historical Forecast API
  `https://historical-forecast-api.open-meteo.com/v1/forecast` (from ~2022; the first hours of each model run
  stitched) with `daily=wind_speed_10m_max,wind_gusts_10m_max&wind_speed_unit=kn` (probe ok); future days from
  `https://api.open-meteo.com/v1/forecast` (same parameters). Free non-commercial: < 10,000 calls / day, 5,000 / h,
  600 / min, 300,000 / month, CC BY 4.0 (credit Open-Meteo + providers); how a multi-point request is counted is not
  stated (UNCERTAIN — a route is ≤ 30 points, far below either way). The docs warn: limited coastal accuracy, "not
  suitable for coastal navigation" → a caveat in every result.
- **F6 Parameters:** the synthetic speeds come from the generator's documented ranges (`TYPE_PARAMS`, min–max kn per
  type) and each voyage's own `service_kn`; SCNT spans 5–15× inside a type (Containerships 14,322–194,578; Crude
  17,991–291,826) → one fuel figure per type would be off by multiples (P9-5). Fuel source: Fourth IMO GHG Study 2020
  (full report + annexes, `ghgsmart.imo.org`), per ship type and size bin; the exact tables are read at S3 (UNCERTAIN
  until then; fallback: the Third IMO GHG Study 2014 annex tables).

**Common contract:** ADR-049 unchanged — `f(user, **args) → ToolResult`, RBAC first, no user field in any schema,
parameterized SQL, external calls through `external.cached_call` (10 s, failure → `context_unavailable`, never
cached; settled windows frozen). **One addition — the clock from the run context:** `RunContext` gains `as_of`
(UTC datetime; default `2026-09-13T00:00Z`, the data's as-of instant, ADR-032). Only the graph / the evaluation
harness sets it, never the model: a model-chosen `as_of` could move a replayed cut past *t* and read the future
(ADR-049 (2) extended from the dataset to the clock). Stage 1 tools ignore it.

| Tool | Args (what the model sees) | Reads | Access (ADR-006) | Result |
|---|---|---|---|---|
| `sea_route` | `origin`, `destination` (UN/LOCODE, must exist in `ports`), `avoid` ⊂ {suez, babalmandab, panama, gibraltar, bosporus, ormuz, malacca, sunda} (closed list, default none), `speed_kn` (optional, 4–25) | `ports` (lon / lat) + `searoute` locally (restrictions = northwest + avoid; no network) | level 1 (`ports`, public) | `distance_nm`, `passages` used, `waypoints` (simplified, ≤ 60 points), with `speed_kn`: `sea_days` and `day_points` (lat, lon, day n at the end of each sea day — the input of `marine_weather`); no path (F1b) → `no_data` "no sea route with these passages closed"; source = "searoute 1.6.0 MARNET, restrictions=[…]" |
| `vessel_params` | `vessel_id`, or (`vessel_type`, `scnt_tons`, `condition`); `speed_kn` (optional) | `vessel_performance` + `bunker_prices` (migration 020), `vessels`, the voyage's `service_kn` | level 1 / Operations | service speed (the vessel's own `service_kn` when it has a voyage, else the row's reference speed), fuel t / day at that speed (cube law from the reference speed: F × (v / v_ref)³), the size band row used + its source, the bunker price (USD / t, its date), USD per SDR (its date), the price in SDR / t |
| `voyage_status` | `vessel_id` (1–500) | MongoDB `ais_positions` (fixes with `ts ≤ as_of`) + `voyages_synthetic.parquet` (route, ports, departure) + the rebuilt route (F3, cached in memory) | level 1 / Operations (`rbac_mapping.md` §3) | `as_of`, last fix (ts, lat, lon, sog, cog, navstat), recent speed (mean SOG of under-way fixes in the last 6 h), status at `as_of` (from the track's navstat, so a cut at *t* is honest — not `vessels.status`), next port, ports left, distance covered / left (nm along the route from the snapped last fix), departure; `arrival_ts` only when ≤ `as_of`; never `eta_raw` (P9-7) |
| `marine_weather` | `points` (1–30 of {lat, lon, date}) | Open-Meteo Marine (waves) + Historical Forecast (wind, dates ≤ today) / Forecast (later dates) | public external, level 1 | per point and date: `wave_height_max` m, `swell_wave_height_max` m, `wind_wave_height_max` m, `wind_speed_10m_max` kn, `wind_gusts_10m_max` kn; a land / null value stays null with a note; source + retrieved_at + attribution + the coastal caveat |

Reused unchanged from Stage 1: `compute_toll` (the Suez dues of the Suez route), `suez_transits` (traffic),
`web_search` (news), `search_documents`. Replay note: at `as_of = 2026-09-13` the "next days" are past days, so the
weather is the Historical Forecast series — close to what happened (slightly kinder than a real 7-day forecast); the
result says which API served each date.

**Migration 020 — `020_vessel_performance.sql` (P9-1, P9-3, P9-5).** Two tables in `public`, rendered from sourced CSVs
in `db/reference/` (INSERT rows generated from the CSV, as migration 010 was from its mirror; the check compares the
table with the CSV row for row):
- `vessel_performance` — `vessel_type` (the 13-value CHECK of ADR-033), `size_band` 1–3, `scnt_min` / `scnt_max`
  (null = open last band; contiguous per type, like the toll bands), `ref_speed_kn`, `fuel_t_per_day` (at sea, at the
  reference speed, main + auxiliary engines), `source`, `source_ref` (study, table, page); UNIQUE (type, band).
  `ref_speed_kn` = the midpoint of the generator's range (F6), so the parameters and the synthetic tracks agree.
- `bunker_prices` — `fuel` (CHECK `VLSFO`), `price_usd_per_t` > 0, `price_date`, `usd_per_sdr` > 0, `rate_date`,
  `price_source`, `rate_source`, `set_by` (the owner). The tool uses the latest row and names both dates; at S4 Claude
  shows a public price (e.g. a published global VLSFO average) and the IMF USD per SDR rate of that date, and the
  owner sets the row.
- CHECKs + COMMENT on every table / column (ADR-033), SELECT through `ports_readonly`'s default privileges, not
  `finance_bi`; `rbac_mapping.md` §2: both level 1 / Operations (a market price, not company finance).
  `verify_readonly.sql` §20: row counts, bands contiguous, every vessel maps to exactly one row. Applied by the owner;
  snapshot + audit by Claude.

**MongoDB read-only access (P9-6).** `voyage_status` reads through a new user with role `read` on `ports_logistics`
(`db/mongo/005_create_reader_user.js` via `run.ps1`, `.env` `MONGO_RO_USER` / `MONGO_RO_PASSWORD`,
`common.SECRET_KEYS`), like `PG_RO_USER` for PostgreSQL; a refused write is part of the check.

**Tests (`pipelines/scripts/agents/Stage2_tools_check.py`, one phase per tool, a reviewed snapshot after each).**
1. `sea_route`: Singapore ↔ Rotterdam both ways via Suez and with `avoid=[suez]` within ±3 % of the published 8,288 /
   11,755 nm, with the expected passages; Jeddah → Rotterdam; Port Said ↔ Rotterdam = 3,310 nm with and without Suez
   (F1a); Sokhna → Rotterdam with Suez blocked → `no_data` (F1b); `avoid=[babalmandab]` → the Cape; unknown LOCODE /
   bad `avoid` refused by the schema; two calls identical. The ~12 cases frozen here are §8's route cases.
2. Migration 020 + `vessel_params`: the tables = the CSVs; every vessel (500) maps to one band; fuel at the reference
   speed = the row, at 0.8 × speed = 0.512 × the row; the SDR price = USD price / rate (hand value).
3. `voyage_status` on all 500 at the default `as_of`: last fix = MongoDB's latest; rebuilt length = `route_nm`
   (≤ 0.1 nm); covered + left = `route_nm` (±1 nm); for In Transit, distance left = the generator's own remaining
   distance at the as-of (from its timeline, ±2 nm); status at `as_of` = `vessels.status` (500 / 500); a cut at
   departure + 50 % uses no fix after it and returns no `arrival_ts`; no result contains `eta_raw` or a future time.
4. `marine_weather` offline (`httpx.MockTransport`): ok → cached, the second call makes 0 requests; timeout / 500 / bad
   JSON → `context_unavailable`, nothing cached; > 30 points refused; a land point → null + note; then one live call
   (3 points on 2026-09-13, the probe's values in the snapshot).
5. RBAC + contract: 100 employees × the 4 tools = the ADR-006 expectation (all level 1 → granted; Finance tools still
   refused to Operations as before); no args schema has a user / dataset / `as_of` field; a call without a
   `RunContext` refused; the Mongo reader cannot write.
6. Regression: `Tools_check.py` 8 / 8 after the `RunContext` change.

**Order (one step at a time, each with its check):** S1 foundation (`RunContext.as_of`, `registry.STAGE2`, the Mongo
reader user — owner OK first) → S2 `sea_route` → S3 the parameter CSV with its sources (owner reviews every row) → S4
migration 020 (SQL shown, owner applies; the bunker price set by the owner) → S5 `vessel_params` → S6 `voyage_status`
→ S7 `marine_weather` → S8 RBAC + regression → S9 close: ADR-055 (Stage 2 tools, the clock in the run context) and
ADR-056 (no live AIS in Stage 2 — D11 narrowed, P9-2), ARCHITECTURE, ROADMAP, `rbac_mapping.md`, the §6 example
question fixed (F1a), handoff.

**Files (new):** `pipelines/agents/tools/` — `routes.py` (`sea_route` + the route rebuild shared with
`voyage_status`), `vessels.py` (`vessel_params`), `voyages.py` (`voyage_status`), `weather.py` (`marine_weather`),
`mongo.py` (read-only client); `db/reference/vessel_performance.csv` + `bunker_prices.csv` (sources in their header
comments / `db/README.md`); `db/migrations/020_vessel_performance.sql`; `db/mongo/005_create_reader_user.js`;
`pipelines/scripts/agents/Stage2_tools_check.py` + `pipelines/checkpoints/agents/Stage2_tools_check.md`. **Changed:**
`tools/context.py` (`as_of`, resources), `tools/registry.py` (`STAGE2`), `.env.example`, `common.SECRET_KEYS`,
`db/verify_readonly.sql` (§20), the docs. No new package (`searoute`, `httpx`, `pymongo`, `shapely` via geopandas are
installed).

| # | Question (new, 2026-10-27) | Recommended | Alternative(s) |
|---|---|---|---|
| P9-5 | Fuel granularity | per vessel type × 3 SCNT size bands (≈ 39 sourced rows) + the cube law for speed | one row per type + a size formula (SCNT^⅔); one row per type, no size |
| P9-6 | MongoDB access for the tools | a new read-only user (role `read`) | the existing app user (`readWrite`) |
| P9-7 | AIS-declared ETA (`eta_raw` = the answer key) | never returned by `voyage_status` | returned, labelled "declared ETA", masked by the harness |
| P9-8 | Weather for replayed (past) dates | Marine with dates + Historical Forecast for wind (verified F5) | forecast for today's dates only (no replay weather) |

**Answers (owner, 2026-10-27, AskUserQuestion — all the recommended option):** P9-5 **type × 3 SCNT size bands +
the cube law**; P9-6 **a new read-only MongoDB user**; P9-7 **`eta_raw` never returned** (nor `arrival_ts` before
arrival); P9-8 **Marine with dates + Historical Forecast for wind**. The design above already reads these answers;
next: the owner's approval of §6a as a whole.

### 6b. Phase 10 — the `route_advice` graph (B Route & Cost Advisor): concrete design (PROPOSED 2026-10-27; decisions P10-1…P10-4 answered the same day — see "Answers" at the end; APPROVED 2026-10-27 by the owner, as written; IMPLEMENTED 2026-10-27, ADR-057 — deviations D-P10-1 / D-P10-2 in Progress)

**Goal (§5 row 10):** "Should this vessel sail A → B via Suez or the Cape?" → a Pydantic comparison of the two routes
(distance, sea days at the vessel's speed, Suez dues, fuel and its cost in SDR, risk context) and a recommendation
that lists its assumptions; **no number without a tool behind it** (S2-D5: route numbers 100 % from tools). Done when
the S2 route cases (§8) pass. **Starting point:** the Phase 9 tools (ADR-055) + `compute_toll`, `suez_transits`,
`web_search` (ADR-049); the Stage 1 patterns — hybrid workflow nodes (ADR-050), number slots + a code Validator
(ADR-051), roles with main + fallback and `FakeRoles` (ADR-045, ADR-050 (7)), skills (D13).

**Verified facts it depends on (2026-10-27):** every input tool exists and is tested (`Stage2_tools_check.py` 0–5,
`Tools_check.py` 8 / 8); `sea_route` returns `passages`, so "does the shortest route use Suez?" is a field, not a guess
(Port Said → Rotterdam: no — F1a; Sokhna → Rotterdam with Suez closed: no route — F1b); `compute_toll(vessel_id)`
prices the vessel's condition (SFU → Laden); `web_search` takes a date window, `suez_transits` a window ≤ 120 days
(PortWatch publishes ~ a week late; settled windows cached for good). **The number slots of Stage 1 are
finance-shaped** (`deck/slots.py`: ids `kpi.` / `audit.` / `insight.`, kinds money / pct / days / count by the field's
suffix) → Phase 10 extends them additively (id prefix `route.`, kinds `_nm` distance, `_kn` speed, `_t` tonnes,
`sea_days`), guarded by the Stage 1 checks (`Deck_check.py`, `Finance_qa_check.py`) unchanged.

**The graph** (`pipelines/agents/graphs/route_advice.py`, a LangGraph `StateGraph`; the user and the clock from
`RunContext`, the clock = the departure day):

| # | Node | Kind | What it does | Out (state) |
|---|---|---|---|---|
| 1 | `inputs` | code | `vessel_id` (its type, condition, SCNT, service speed) or a hypothetical vessel (`vessel_type`, `condition`, `scnt_tons`, optional `speed_kn`); `origin`, `destination` (UN/LOCODE); `vessel_params` → speed, fuel / day, SDR price | `evidence["route.vessel"]` |
| 2 | `routes` | code | `sea_route` as is; if its `passages` contain `suez`, again with `avoid=["suez"]` | `route.suez`, `route.cape`; status `no_suez_on_route` (the shortest route does not use the canal: one route, no question) or `suez_only` (no route with Suez closed) |
| 3 | `costs` | code | per route: sea days = distance / (speed × 24); fuel t = days × fuel / day; fuel SDR = t × SDR / t; Suez dues = `compute_toll` (Suez route only, one transit); total SDR; the differences Cape − Suez (days, t, SDR, dues saved, net); exact Decimal, rounded once | `route.compare` (one row per route + a `difference` row) |
| 4 | `context` | code | `suez_transits` (P10-4 window) and `web_search` (news, window up to the clock); untrusted text screened (ADR-049 (5)); any failure → that item says "context unavailable", the advice goes on without it | `route.transits`, `route.news` |
| 5 | `advisor` | LLM (role `writer`, one structured call; skill `route-cost-advice`) | `RouteAdvice`: `recommendation` ∈ {suez, cape}, a headline and ≤ 5 reasons written with number slots (`{route.compare[cape]:fuel_sdr\|M}`), each reason citing its evidence ids; risks only from `route.transits` / `route.news` | draft |
| 6 | `validator` | code | every number token is a slot bound to a numeric field of the cited evidence (ADR-051's rule; news / web rows never give numbers); every citation exists; the recommendation follows the rule of P10-1; fail → one patch with the problems (as the finance Q&A, MAX_PATCHES = 1), then `validation_failed` | verdict |
| 7 | `render` | code | the answer: the comparison table drawn by code from `route.compare`, the recommendation and reasons with the slots filled, the **assumptions list written by code** (speed and its source, fuel at sea at constant speed by the cube law, harbour legs and canal waiting not modelled, the VLSFO price and both dates, one Suez transit in the vessel's condition, IMO yearly averages, time not priced (P10-2)), the sources with retrieval times | `RouteAdviceResult` |

**Statuses:** `ok`, `no_suez_on_route`, `suez_only`, `not_permitted`, `no_data` (unknown vessel / port),
`output_invalid` (twice-invalid structured reply), `validation_failed`; the two route-shape statuses still return the
one route's numbers without calling the model. **Access:** every input is level 1 (ADR-006, `rbac_mapping.md` §2 /
§4a) → open to every employee, as the tools are; the graph adds no gate of its own. **Models:** role `writer` of
ADR-045 (main + fallback, one retry on an invalid reply); ≈ 1–2 model calls per question. **Interface:** CLI
`pipelines/scripts/agents/Route_advice.py ask --vessel 123 --from SGSIN --to NLRTM --as <employee> [--as-of …]`
(prints the table, the advice, assumptions and sources); later the supervisor (Phase 12) calls the graph as a tool.

**Files (new):** `pipelines/agents/graphs/route_advice.py`, models in `graphs/models.py` (`RouteReason`,
`RouteAdvice`, `RouteAdviceResult`), `pipelines/agents/skills/route-cost-advice/SKILL.md` (owner review),
`pipelines/scripts/agents/Route_advice.py` (CLI), `pipelines/scripts/agents/Route_advice_check.py` + checkpoint
narrative, `Data/processed/agents/eval/route_cases.json` (frozen). **Changed (additive):** `deck/slots.py` (the
`route.` id and the route kinds), the docs.

**Route cases (§8, frozen before any model run):** 12 = 6 route pairs × 2 vessels (a small and a large one of
different categories, by rule: the band 1 / band 3 vessel with the lowest id), the pairs = Phase 1's frozen
`sea_route` cases + their reverse: Singapore → Rotterdam, Rotterdam → Singapore, Jeddah → Rotterdam, Singapore →
Rotterdam with a slow speed (12 kn), Port Said → Rotterdam (`no_suez_on_route`), Sokhna → Rotterdam (`suez_only`).
Expected numbers computed **independently** in the check (Decimal formulas over the CSVs, the toll bands and the
frozen distances), never by the graph's own code.

**Tests (`Route_advice_check.py`, one phase per step, reviewed snapshots):**
1. Deterministic nodes on the 12 cases = the independent computation (100 %, every field); the two shape statuses.
2. Slots: the `route.` ids and kinds format right (nm, kn, t, days, SDR); Stage 1's `Deck_check.py` and
   `Finance_qa_check.py` still pass (the extension is additive).
3. Validator: ≥ 50 planted wrong numbers in drafts (typed numbers, a slot on the wrong route, a news number, a wrong
   citation, a recommendation against the rule) all caught; 0 false alarms on the 12 clean drafts.
4. The graph end to end on `FakeRoles` (12 cases; patch path; output_invalid; context unavailable → the advice still
   ok and says so).
5. Real model on the 12 cases (cached through `llm.py`; free quota ≈ 12–24 calls): every number slot-bound, the
   recommendation follows the rule, no validation_failed — the S2-D5 threshold "route numbers 100 % from tools".
6. RBAC + contract: 100 employees can ask; the run context's user reaches every tool; no user / clock in any model
   input schema.

**Order (one step at a time, each with its check):** S1 slots extension (+ Stage 1 regression) → S2 models + the
deterministic nodes 1–4 + the route cases frozen (owner sees the 12 expected rows) → S3 the skill `route-cost-advice`
(owner review) → S4 advisor + validator + render on FakeRoles → S5 the CLI + real model on the 12 cases → S6 close
(ADR-057, ARCHITECTURE, ROADMAP, handoff). Nothing committed until Stage 2 closes (owner).

| # | Question (new, 2026-10-27) | Recommended | Alternative(s) |
|---|---|---|---|
| P10-1 | Who decides the recommendation | code ranks the two routes by total cost (fuel + dues, SDR); the model recommends the cheaper one **unless** a cited risk item (news / a Suez traffic drop) justifies the other — the Validator checks this rule | code decides by cost only, the model only explains; the model decides freely from the numbers |
| P10-2 | The value of time (the Cape adds days) | days reported, **not priced** (no free charter-rate source); stated in the assumptions | an owner-set daily charter rate per vessel category (a new table, migration 021) priced into the total |
| P10-3 | What is kept of an advice | no checkpointer (one invocation, no approval); each answer saved as JSON in `reports/route_advice/` (save only, git-ignored) + LangSmith trace | a PostgresSaver thread per question; nothing saved |
| P10-4 | Risk context | PortWatch: the 28 days up to the clock vs the same 28 days a year earlier (the traffic trend) + news of the last 14 days | also `marine_weather` on each route's first 7 sea days; no external context (numbers only) |

**Answers (owner, 2026-10-27, AskUserQuestion):** P10-1 **the cheaper route unless a cited risk justifies the other**
(recommended); P10-2 **days reported, not priced** (recommended); P10-3 **a PostgresSaver thread per question + the
LangSmith trace** (the alternative, not the JSON file); P10-4 **PortWatch 28 days vs a year earlier + news of 14
days** (recommended). What P10-3 changes in the design above:
- **Checkpointer:** the existing PostgresSaver in schema `agent_state` (runtime login `ports_agent`, ADR-050 (5)),
  `durability="sync"`; one thread per question, `route_advice:<employee_id>:<as_of date>:<origin>-<destination>:<n>`
  (n = the next free number), so a question can be re-read later (`Route_advice.py show <thread>` / `list --as …`)
  and an interrupted run resumes at its last node. No `interrupt()` (advice, not a publication). No JSON file.
- **Retention:** today's job (ADR-054) deletes only `weekly_pack:` threads → it also deletes `route_advice:` threads
  older than 30 days (`scheduling.py` prefix list; `Scheduler_check.py` extended: a route-advice thread older than
  30 days goes, a recent one stays, a pending pack is never touched).
- **Trace:** `Route_advice.py ask` runs inside the LangSmith per-run context of `pipelines/agents/tracing.py`
  (project `nilegate-agents`, tag `entry:route_advice`) when `LANGSMITH_API_KEY` is set — never `LANGSMITH_TRACING`.
- **Tests:** phase 4 adds a crash between `context` and `advisor` → resume from the checkpoint with no repeated tool
  call; phase 6 adds the thread naming and the retention cases. Files changed also: `pipelines/agents/scheduling.py`,
  `Scheduler_check.py`.

### 6c. Phase 11 — the `voyage_watch` graph (C Voyage & Disruption Watch): concrete design (PROPOSED 2026-10-27; APPROVED 2026-10-27 by the owner's autonomous grant ("work on your own until I come back", memory `autonomous-when-owner-away`) — every choice = the recommended option, decisions P11-1…P11-10 below, **reviewed and approved by the owner 2026-10-29** (with D-P11-1, D-P11-2); IMPLEMENTED 2026-10-28,
ADR-058 — deviation D-P11-1 at the end)

**Goal (§5 row 11):** for our synthetic fleet at the run's clock: where each vessel is, its ETA, the delay risk on its
next legs (weather) and from Suez traffic → alerts saved (save only, S2-D1) and shown on request; scheduled every N
hours. **Done when:** the ETA error on replayed synthetic voyages beats the naive baseline (S2-D5) and the alerts are
reproducible; alert precision measured on planted weather / traffic events (S2-D5). **Starting point:** the Phase 9
tools (ADR-055: `voyage_status` with the clock `as_of`, `marine_weather`, `vessel_params`, `routes`), `suez_transits`
(ADR-049), the Phase 10 pattern (ADR-057: code computes, one model call explains with number slots, a code Validator,
a PostgresSaver thread, the same retention), the Phase 8 scheduler pattern (ADR-054).

**Verified facts it depends on (2026-10-27, read-only probes; scratch scripts in the session's scratchpad).**
- **F7 The generator's speed profile (`AIS_generator.py` Phase 4, read):** harbour speed 6.7 kn over the first and
  last 10 nm (`HARBOUR_KN` = the median implied moving speed of the real NOAA harbour sample,
  `profiles/noaa_profile.json`), the voyage's constant `service_kn` in between, SOG noise σ 0.2 kn, no weather or
  traffic effect on speed, no dwell at intermediate ports (F2). **Consequence, said before measuring:** a rule that
  knows the route and the recent speed reproduces the generator's arrival almost exactly; the ETA score measures how
  well the tools rebuild the data, not how good the rule would be on real voyages (real ETAs carry port congestion,
  weather slow-downs, speed changes). The weather cannot change an ETA in this data → weather is a **risk flag**, never
  an ETA correction.
- **F8 `arrival_ts` by status:** In Transit / At Port / Completed = arrival at the berth (along-route end); **Anchored
  = arrival at the anchorage 5 nm before the destination** (the berth time is not in the data) → Anchored voyages are
  not ETA cases; the watch reports them "at anchorage off <port> since …", no ETA.
- **F9 Fleet at the clock (voyage_status on every voyage with `departure_ts <= as_of`):** at 2026-09-13T00:00Z 500
  candidates → In Transit 219, Anchored 78, At Port 130, Completed 73 (34.8 s); at 2026-09-06T00:00Z 404 candidates →
  In Transit 380, Completed 19, At Port 5 (14.7 s). `departure_ts` (known once a vessel has sailed) is the only
  pre-filter: `arrival_ts` is never used to choose who is watched.
- **F10 The canal on a MARNET path:** Singapore → Rotterdam passes vertices (30.214, 32.558), (30.318, 32.382),
  (31.103, 32.31) → "Suez ahead" = a route vertex in the box lat 30.0–31.2, lon 32.25–32.65 beyond the distance
  covered (Port Said 31.265 N and Sokhna 29.65 N lie outside the box: a voyage that ends at Port Said from the
  Mediterranean does not cross the canal).
- **F11 Vessel names carry digits** ("Special Voyager 001") → the brief's Validator blanks names and LOCODEs before
  looking for typed numbers (`validator.number_tokens(text, strings)`).
- **F12 Open-Meteo quota:** < 10,000 calls / day (F5); whether a multi-location request counts once or per location is
  **UNCERTAIN** → budgeted per location: ≤ 380 vessels × 4 points × 2 APIs ≈ 3,000 per firing → every 12 h, not 6 h.

**ETA — the rules fixed before any measurement (P11-1, P11-2, P11-3).** All from what is known at the cut *t*
(voyage_status at `as_of = t`, the planned speed from `vessel_params`, the port's position):
- **R — the rule-based ETA (the product):** `d` = `distance_left_nm` along the route; `v` = `recent_sog_kn` (mean SOG
  of the under-way fixes of the last 6 h) when `distance_covered_nm` ≥ 20 nm, else the planned service speed
  (`vessel_params.speed_kn`: the vessel may still be in its departure harbour leg); approach allowance **A = 10 nm at
  6.7 kn** (the real NOAA harbour profile, F7); ETA = t + (d − A) / v + A / 6.7 h when d > A, else t + d / 6.7 h.
  Port-call allowance at intermediate ports = 0 (F2). The ETA time = the last fix's time + the hours (the last fix is
  at most minutes before t).
- **N — the naive baseline (the S2-D5 threshold):** t + great-circle distance (last fix → destination port) / the
  last fix's SOG (planned speed when SOG < 1 kn): the AIS-only estimate that knows neither the route nor the port
  approach.
- **References, reported, not thresholds:** **S** "schedule" = departure + `route_nm` / planned speed (ignores the
  position; nearly exact here because the speed is constant — F7, said plainly); **R0** = R without the approach
  allowance (what the allowance is worth).
- **Cases (frozen in `Data/processed/agents/eval/eta_cases.json` before the first prediction):** 50 voyages =
  25 arrived (At Port + Completed, 203) + 25 In Transit (219), each list sorted by vessel_id, the voyages at ranks
  round(i × n / 25), i = 0…24; route fallbacks (2) excluded first. Cuts at 25 / 50 / 75 % of the sailing time
  (departure → `arrival_ts`), kept only when ≤ the data's as-of instant, and the In Transit voyages also at the as-of
  instant itself (the watch's real case). `arrival_ts` places a cut (sampling) but never reaches a predictor.
- **Measures:** MAE in hours (|ETA − arrival_ts|), median, p90, max, the mean signed error (bias), by remaining-time
  bucket (< 24 h, 1–5 days, > 5 days). **Threshold (S2-D5): MAE(R) < MAE(N)** over all predictions. **ML margin
  (S2-D2, fixed now):** a learned model is built only if MAE(R) > 2 h **and** > 5 % of the mean remaining hours;
  otherwise it is recorded as not needed in this data.

**Alerts — the rules fixed before any measurement (P11-4).** Per watched vessel, deterministic code:
- **weather:** the next-leg points = the vessel's position now and at +24 / +48 / +72 h along its route at the ETA's
  speed `v` (points after the predicted arrival dropped; the last point may be the destination port), each with its
  date → `marine_weather`; an alert when a point has `wave_height_max` ≥ **4.0 m** (Douglas sea state 6, "very rough")
  or `wind_speed_10m_max` ≥ **34 kn** (Beaufort 8, gale); severity **high** at ≥ 6.0 m (Douglas 7 "high") or ≥ 48 kn
  (Beaufort 10, storm), else **moderate**. One weather alert per vessel: the worst point (highest severity, then the
  earliest). A null value (land, coast, beyond the horizon) is "unknown", never calm, never an alert; counted.
- **suez_traffic:** the canal ahead on the vessel's remaining route (F10) and PortWatch's mean daily transits of the
  28 days before the clock vs the same 28 days a year earlier at **−20 %** or lower (the ADR-057 threshold; high at
  −40 %). PortWatch unavailable → no traffic alert, the run says "Suez traffic context unavailable".
- **No news alerts:** news is untrusted text with no measurable truth (the watch does not call `web_search`).
- **Alert id** `<vessel_id>/<kind>`; each alert carries its numbers (wave m, wind kn, hours ahead, the ETA and
  `eta_in_h`, the traffic change), its point and date, and the source of each value.

**The graph** (`pipelines/agents/graphs/voyage_watch.py`, a LangGraph `StateGraph`; the user and the clock from
`RunContext`):

| # | Node | Kind | What it does | Out (state) |
|---|---|---|---|---|
| 1 | `fleet` | code | voyages with `departure_ts <= as_of` → `voyage_status` each → keep In Transit + Anchored | `vessels` (status rows), `watch.fleet` counts; none → `no_data` |
| 2 | `eta` | code | R per In Transit vessel (`tools/eta.py`) + its next-leg points; Anchored: "at anchorage", no ETA | `etas` |
| 3 | `weather` | code | `marine_weather` in batches of ≤ 30 points (deduplicated); a failed batch → its points unknown, said | `weather` |
| 4 | `traffic` | code | `suez_transits` 28 days vs a year earlier → `change_transits_pct`; Suez-ahead flags | `watch.traffic` |
| 5 | `alerts` | code | the rules above → `watch.alerts` (rows keyed `vessel_id/kind`); **saves the run file** | `alerts`, file |
| 6 | `brief` | LLM (role `writer`, one structured call; skill `voyage-watch-brief`) — only when there are alerts | `WatchBrief`: a headline + ≤ 6 items, each citing alert ids, numbers as slots | draft |
| 7 | `validator` | code | slots bound to the cited alerts / fleet; no typed number (dates are copied and must equal a cited alert's date / ETA; names and LOCODEs blanked); every cited alert exists; every **high** alert is cited; one patch, then the brief is dropped (`validation_failed`) — the alerts stand | verdict |
| 8 | `render` | code | `VoyageWatchResult` (status, fleet counts, ETAs, alerts, the brief rendered, assumptions written by code, sources, problems); rewrites the run file with the brief | result |

**Statuses:** run `ok` / `no_data` / `not_permitted`; `brief_status` `ok` / `no_alerts` (no model call) /
`output_invalid` / `validation_failed`. **Save (P11-5):** one PostgresSaver thread per run,
`voyage_watch:<as_of %Y%m%dT%H%MZ>:<n>` (resumable; 30-day retention by the same `prune`), and one JSON file per run
`reports/voyage_watch/<as_of>_<n>.json` (git-ignored, written atomically; outlives the thread) — read on request by
`Voyage_watch.py alerts`; no table, no migration. **Access (P11-8):** every input is level 1 / Operations (ADR-006)
→ every employee may read the alerts (as the route advice); the scheduled run identity is an Operations manager
(`WATCH_RUN_AS` in `.env`, checked at every firing; employees 2 and 3). **Models (P11-6):** ≤ 2 calls per run (one +
one patch), none when there is no alert.

**Schedule (P11-7):** Task Scheduler every **12 h** (10:30 and 22:30 local, F12) → `Voyage_watch.py scheduled`:
a stalled run is resumed first; else the next replay instant = the last finished run's clock + 12 h, starting at the
data's as-of instant − 7 days (2026-09-06T00:00Z), up to the as-of instant (15 firings), then `done` (as the weekly
replay, D12). Registered by `ops/scheduler/register_voyage_watch.ps1` — **written, not registered** (the owner runs
it). Each firing prunes `voyage_watch:` threads older than 30 days.

**Tests (`pipelines/scripts/agents/Voyage_watch_check.py`, one phase per step, reviewed snapshots):**
1. ETA rules on the frozen cases: R, N, S, R0 against `arrival_ts`; the threshold MAE(R) < MAE(N); the ML margin
   decision; no predictor reads `arrival_ts` or a fix after the cut (the tool's guard, re-asserted).
2. Next-leg points and Suez-ahead: positions = an independent computation on the generator's timeline (the voyage
   file + searoute directly); the canal box on the routes that cross it.
3. Alert rules + planted events (P11-9): a mock Open-Meteo with planted storm boxes (waves, wind, near-threshold
   negatives, a null coast) and a mock PortWatch (−30 %, −10 %, down) over the real fleet at the as-of instant; the
   truth = the generator's true positions at +0…72 h computed in the check; **precision and recall** (targets fixed
   now: ≥ 0.95 each), false alarms listed; the same run twice → identical alerts (reproducible).
4. Slots + the brief's Validator: ≥ 40 planted errors caught (a typed number, a wrong date, a slot on the wrong alert,
   an invented alert id, a high alert left out, a news-like number), 0 false alarms on clean briefs.
5. The graph on FakeRoles + the real PostgresSaver: ok with alerts (1 call), no alerts (0 calls), patch, output_invalid
   and validation_failed (alerts still saved), PortWatch / Open-Meteo down, a crash in `brief` resumed from the
   checkpoint with no tool call repeated; the run file = the state; thread naming; retention.
6. The real model once at the as-of instant with the live (cached) weather: the brief passes the Validator (or the
   failure is reported as is); the live alert counts reported (no truth for real weather).
7. RBAC + contract + scheduling: 100 employees may read; a probe user → not_permitted before any read; no user /
   clock in a model-facing schema; the replay planner (start, next, resume, done) and the run identity rule.
Regression: `Stage2_tools_check.py`, `Route_advice_check.py`, `Tools_check.py`, `Scheduler_check.py`,
`Deck_check.py` + `Finance_qa_check.py` (the slots extension).

**Order:** S1 §6c + `eta.py` + the frozen cases + Phase 1 → S2 next-leg points + Suez ahead (Phase 2) → S3 slots
(`watch.` ids, `_m` metres, `_h` hours) + alert rules + planted events (Phases 3–4) → S4 the skill + the graph +
store (Phase 5) → S5 CLI + scheduler + real model + RBAC (Phases 6–7) → S6 close (ADR-058, docs, handoff).

**Files (new):** `pipelines/agents/tools/eta.py` (the rules R / N / S, next-leg points, Suez ahead), 
`pipelines/agents/graphs/voyage_watch.py`, models in `graphs/models.py` (`WatchItem`, `WatchBrief`,
`VoyageWatchResult`), `pipelines/agents/skills/voyage-watch-brief/SKILL.md` (reviewed by the owner 2026-10-29),
`pipelines/scripts/agents/Voyage_watch.py` (CLI: `run | scheduled | alerts | show | list | prune`),
`ops/scheduler/register_voyage_watch.ps1`, `pipelines/scripts/agents/Voyage_watch_check.py` + checkpoint narrative,
`Data/processed/agents/eval/eta_cases.json` (frozen). **Changed (additive):** `deck/slots.py` (`watch.` ids, two
kinds), `scheduling.py` (the watch's replay planner + `describe_voyage_watch`), `.env.example` (`WATCH_RUN_AS`), the docs.

| # | Decision (autonomous grant, 2026-10-27; the recommended option taken) | Taken | Alternative(s) not taken |
|---|---|---|---|
| P11-1 | ETA rule | R: along-route distance left / recent sea speed + a 10 nm approach at the real harbour speed; port calls 0 (F2) | distance / service speed; a learned model first |
| P11-2 | Naive baseline for S2-D5 | N: straight line to the destination / last SOG (AIS only) + references S, R0 reported | S as the baseline (it is near exact here: no honest bar) |
| P11-3 | ETA cases | 50 voyages (25 arrived + 25 at sea) × cuts 25 / 50 / 75 % + the as-of instant; Anchored out (F8) | all 500 voyages; one cut per voyage |
| P11-4 | Alert rules | weather ≥ 4 m / 34 kn (high 6 m / 48 kn) on +0…72 h; Suez −20 % (high −40 %); no news alerts | news-driven alerts; a 7-day horizon |
| P11-5 | Where alerts live | a thread per run + a JSON file per run in `reports/voyage_watch/` | a new table (migration 021) |
| P11-6 | The model's part | one `writer` brief per run with alerts, slots + Validator; alerts never depend on it | no model at all; a model per vessel |
| P11-7 | Schedule | every 12 h, replay from as-of − 7 days to the as-of instant, then done | every 6 h (quota, F12); real time at the as-of instant only |
| P11-8 | Access | read: every employee (level 1); scheduled identity: an Operations manager | Operations only |
| P11-9 | Planted events | mock Open-Meteo storm boxes + PortWatch drops, truth from the generator's timeline, targets ≥ 0.95 | real weather only (no truth) |
| P11-10 | Watched vessels | In Transit (ETA + alerts) and Anchored (listed, no ETA / weather); departed vessels only | every vessel incl. moored |

**Deviation (implementation, 2026-10-28):** **D-P11-1** — a Suez drop alerts every vessel with the canal ahead (at
−45 %: 40 high + 14 high weather alerts), which 6 items × 8 ids could not cite → `WatchItem.alert_ids` up to 60 (one
Suez item lists them all) and an item names at most three vessels (400 characters); the skill says so. Results and
fixes: the handoff in Progress, `pipelines/checkpoints/agents/Voyage_watch_check.md`, ADR-058.
**D-P11-2 (2026-10-29, the first scheduled firing):** Open-Meteo's free limit of 600 calls / min is counted per location (F12 confirmed in practice): the firing at 2026-09-06 (380 vessels, 1,448 points × 2 APIs sent within a minute) lost 848 points and PortWatch did not answer either (exit 0, 8 alerts — incomplete) → `weather_at` paces its batches under 400 network locations / min (cache hits free; `weather.SENT` counts what was sent), retries the failed batches once after 65 s, and records the reason (`weather_errors`); the assumptions say when a run's weather is incomplete. A full fleet now takes ≈ 4–8 min. Checked in Phase 3 (6 refused requests → 0 lost; pacing peak 360 / 60 s on a fake clock; cached points wait 0 s).

### 6d. Phase 12 — the supervisor over both products: concrete design (PROPOSED 2026-10-28 by the autonomous session; **APPROVED 2026-10-29 by the owner: P12-1…P12-5 all as recommended**)

**Goal (§5 row 12):** one question box for NileGate employees over both stages — finance (Stage 1) and operations
(Stage 2) — with cross-product questions ("which vessels at risk this week belong to our top-5 customers by
receivables?") and the RBAC both ways (Operations ↔ Finance). **Done when:** the S2 Q&A golden questions pass
(§8: ~20 operations + cross-product) and RBAC leakage is 0. **Starting point:** the finance Q&A agent
(`graphs/finance_qa.py`: LangChain `create_agent` on `RoleChatModel`, `QaTurn` middleware with slot checks, one
patch, `ModelCallLimitMiddleware`; "Phase 12 grows this agent into the Supervisor"), the Stage 2 tools (ADR-055),
the two Stage 2 graphs (ADR-057, ADR-058), the D2 decision (a supervisor with subagents-as-tools;
`langgraph-supervisor` is unmaintained).

**Proposed shape:**
- **One agent, more tools (not a hierarchy):** `create_agent` with `STAGE1_TOOLS` + `STAGE2_TOOLS` + three
  product tools — `route_advice` (the ADR-057 graph run as a tool: one thread per question, its result's rows as
  evidence), `voyage_eta` (ADR-058's tool) and `watch_alerts` (the latest saved run, filtered: `Voyage_watch.read_alerts`
  as a tool) — and `load_skill` (D13) for the skills of both stages. Free-tier context budget (Groq 8K TPM): the
  tool list is filtered per question by a cheap code router (finance words / vessel ids / ports) before the model
  sees it, so one request carries ≤ ~8 tool schemas.
- **Answers with slots everywhere:** the same `check_answer` (Stage 1) extended with the `route.` / `watch.` ids;
  the route advice's and the watch's own Validators stay inside their graphs; the supervisor never retypes a number.
- **RBAC both ways:** each tool already checks the run context's user (ADR-049 / ADR-055); a cross-product answer is
  only as wide as the narrowest tool the user may use — an Operations employee asking "the receivables of the
  customers whose vessels are at risk" gets the vessels (level 1) and a `not_permitted` part for receivables
  (level 2 / Finance), said, never guessed. The CEO (level 3) sees both.
- **Evaluation:** a frozen S2 golden set (≈ 20 operations + ≈ 10 cross-product + RBAC twins asked by an Operations
  and a Finance employee), expected numbers from the tools by code, scored like Stage 1 (G1–G4, ADR-052's rule);
  leakage 0 = a hard gate.
- **Interface:** CLI `Ask.py "…" --as E [--lang ar]` (the finance Q&A CLI grows), LangSmith per question; FastAPI
  stays later.

| # | Question for the owner | Recommended | Alternative(s) |
|---|---|---|---|
| P12-1 | Supervisor shape | one `create_agent` with all tools behind a code router | a supervisor calling a finance agent and an operations agent as tools (two levels: more calls on the free quota) |
| P12-2 | Route advice inside Q&A | the graph as a tool (its own thread, Validator, slots) | the supervisor calls the Stage 2 tools itself (numbers not reproduced by the route Validator) |
| P12-3 | Cross-product RBAC | a partial answer with the refused part named | refuse the whole question when any part is refused |
| P12-4 | Golden set size | ≈ 30 questions + RBAC twins, frozen before any run | the finance golden set's 42 + 30 (more quota per evaluation) |
| P12-5 | Language | English + Egyptian Arabic answers (as G2) | English only in Stage 2 |

**Order (PROPOSED 2026-10-29, Phase 12 session; the golden set first, as P12-4 says):** S1 the S2 Q&A golden set
frozen (`Supervisor_golden.py`, 0 model calls) → S2 the product tools in the registry (`route_advice`, `voyage_eta`,
`watch_alerts`, the cross-product bridge S1 decides) + the RBAC matrix over every tool → S3 the code router + the
supervisor agent (`graphs/supervisor.py`, grown from `finance_qa.py`; `check_answer` with the `route.` / `watch.`
ids; the partial answer) on fake models → S4 CLI `Ask.py` + LangSmith per question → S5 `Stage2_eval.py` (scorers
proven on hand-made failures first, then the real run; leakage 0 = the hard gate) → S6 close (ADR-059, docs). Each
step's detail is written in Progress and approved before its code.

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
- **Answers (owner, 2026-10-23):** S2-D1 **a scheduled `voyage_watch` every N hours, alerts saved** (recommended);
  S2-D2 **rule-based ETA first**, ML only past a margin fixed beforehand (recommended); S2-D3 **answered by P9-1 + P9-3**
  (a documented table by migration + a dated VLSFO price); S2-D4 **dropped** (P9-2: no live AIS); S2-D5 **as
  proposed** (recommended). Phase 9 may start after the Stage 1 checkpoint (§6a).

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

### 8a. Generation evaluation — PROPOSED (2026-10-11, owner asked; deterministic first) — REVIEWED by the owner 2026-10-19 (G1–G6 answered; how each applies: §5d)

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
- 2026-10-14 — **Phase 3 model built through the Power BI Modeling MCP** (owner accepted the EULA in chat; the assistant
  connected to the Desktop instance). (1) Table `kpi_weekly_trend` added (DirectQuery, same M) — first query failed
  with `The key didn't match any rows`: Desktop had been opened before migration 014 and the M engine caches the
  source's navigation table for the session; fixed by save + reopen (privileges were fine: `finance_bi` / `ports_bi`
  SELECT = t). 598 rows, week 23 → 13, week 5 → 5. (2) 18 relationships as in the handoff, many → one, single
  direction, **Assume referential integrity off** on purpose (an INNER JOIN would drop the 4 invoices of 2026-W01 and
  the 152 payments paid in 2026); dims checked unique first; no `dim_vessel → dim_customer` (would make ambiguous
  paths). **Owner decisions (P3-5…P3-8):** friendly table names (Weekly KPIs, Category KPIs, Weekly Trend, Customer
  KPIs 13w, Overdue List, Invoices, Payments, AR Snapshot, Week, Customer, Vessel, Toll Band; the source view in each
  description); all measures in `Weekly KPIs`, display folders 1 Overview / 2 Revenue / 3 Receivables / 4 Customers /
  5 Trend; the proposed measure list (36); every column `summarizeBy = None` (161), keys / technical / measured KPI
  columns hidden (69); `Week[iso_week_label]` sorted by `report_week`, `AR Snapshot[aging_bucket]` by its order.
  Measure rules: week-grain KPIs = `SELECTEDVALUE` of the `kpi_weekly` column (blank over several weeks; percent ÷ 100);
  semi-additive tables (AR Snapshot, Overdue List, Customer KPIs 13w, Weekly Trend) guarded by
  `HASONEVALUE(Week[report_week])`; additive facts (Invoices, Payments) plain SUM. No KPI logic in DAX (ADR-047).
  Checked by DAX through the MCP for weeks 5 / 23 / 49: facts via relationships = `kpi_weekly` (billed, collected,
  AR, overdue, category variance) to the cent, DSO 31.0 / 62.2 / 53.6, warm-up note only on week 5; with no week
  selected the semi-additive measures are blank. **Saving:** Ctrl+S did not write MCP changes while Desktop showed
  "relationships modified, need to be refreshed manually"; after *Refresh now* (metadata only, DirectQuery) File →
  Save wrote the TMDL (22:40): `relationships.tmdl`, 12 renamed table files, 36 measures; no credentials in
  `powerbi/`. Cosmetic leftovers: relationship names auto-generated from the old `finance …` table names; the
  `PBI_QueryOrder` annotation in `model.tmdl` still lists the old query names (Desktop rewrites it).
- 2026-10-14 — **Page 1 Overview built** (owner chose: the assistant builds it on screen through computer use while the
  owner watches — the step-by-step text guide was too dense; teach mode not available). Layout (owner decision P3-9):
  title; `Week[iso_week_label]` slicer (dropdown, single select, visual filter "is not (Blank)" — the blank member
  comes from the 4 invoices / 152 payments outside the 52 weeks); one new-Card visual with 6 callouts (Billed,
  Collected, AR, Overdue, DSO, Budget Variance %) each with a reference label (the matching WoW measure; Budget
  Variance SDR under the % card); clustered column "Billed vs Budget (SDR)" with data labels; a card Week Label /
  Invoices Billed / Top10 Share 13w %; a card `Warm-up Note`. Positions set in General → Properties on the 1920×1080
  page. Model changes by MCP: the money measures of folder 1 now `#,0.00` (the new Card ignores `,,` scaling and
  auto-abbreviates: `#,0.00` → "8.39M"; Budget Variance SDR `+#,0.00;-#,0.00;0.00`); `Warm-up Note` returns a sentence
  for both cases (blank only when not one week). Checked on screen for W05 / W23 / W49 against `kpi_weekly` (all
  cards, WoW labels, invoices, top-10 share, warm-up note); "--" on Collected / Overdue WoW of W05 is correct (W04 =
  0 → NULL in SQL). Saved 23:28 (page + 6 visuals in PBIR, model TMDL), no credentials. Lesson: `open_application`
  started a second, empty Power BI process — use the existing window (owner brings it to front).
- 2026-10-15 — **Page 2 Revenue built** (owner first tried to click it himself; the tiny targets at ~40 % zoom failed,
  so he asked the assistant to build it on screen and explain each visual's data — memory updated). Layout (owner decision
  P3-10): title; the week slicer synced from Overview (View → Sync slicers: sync on both pages, visible on Revenue);
  card Revenue SDR / Invoice Count / SCNT Tons; clustered bar "Billed vs Budget by vessel category" from
  `Category KPIs` (axis `Category KPIs[vessel_category]` + new measure **`Category Billed SDR`** = SUM of
  `kpi_weekly_category.billed_sdr` — `Category KPIs` and `Invoices` meet only through `Week`, so the category axis must
  come from the same table as the budget); line "Billed vs Budget — last 13 weeks" (`Weekly Trend[trend_week_label]`,
  Trend Billed / Budget SDR); donut Laden vs Ballast (`Invoices[priced_condition]`); bar by `Toll Band[band_label]`
  (the invoice's top band reached); bar Top 10 routes (`Vessel[route]`, visual filter Top N 10 by Revenue SDR — 28
  routes in W23, almost one vessel each). Money measures of folder 2 / trend now `#,0.00`. Checked by DAX: Revenue SDR
  = Billed for W05 / W23 / W49; categories, laden + ballast and bands each sum to the week's billed (W23 8,394,785.98;
  W49 4,056,397.94). Saved 17:35 (8 visuals). Environment: Docker had exited (255) after a reboot → Power BI opened at
  15:13 without the model ("actively refused"); the assistant restarted `ports-postgres`, owner reopened the PBIP; the old
  window was closed (Stop-Process) and its auto-recovery files were kept ("view later"), not deleted.
- 2026-10-15 — **Phase 3 review with the owner** (before any commit of the pages). Deviations from §5 Phase 3 listed
  and accepted: table 12 `kpi_weekly_trend` (014), no `dim_date`, friendly names, `Category Billed SDR`, money format
  `#,0.00`, `Warm-up Note` text, Top 10 routes, pages built by the assistant on screen with the owner watching (D5 said
  "with the owner"). **Owner decisions:** P3-11 the **Exceptions page is a placeholder** in Phase 3 (title + a note that
  it fills when the Auditor tool exists, Phase 4 / 7 — no `finance_test` views before then, P2-8); P3-12 Docker
  containers `ports-postgres`, `ports-mongo`, `ports-qdrant` set to `--restart unless-stopped` (done by the assistant,
  verified). Remaining for Phase 3: pages Receivables, Customers, Exceptions (placeholder); then close (ROADMAP,
  ARCHITECTURE, ADR-048 for the Power BI model rules).
- 2026-10-15 — **Page 3 Receivables built** (the assistant on screen, explained per visual; owner decision P3-13 layout):
  title; slicer added to the sync group (sync + visible); new-Card AR / Overdue / DSO / Collected (the Overview
  measures, so both pages show one number) with WoW reference labels; column chart `AR by Bucket SDR` by
  `AR Snapshot[aging_bucket]` (sorted by `aging_bucket_order`; data labels 2 decimals); line `Trend DSO Days` over
  `Weekly Trend[trend_week_label]`; table from `Overdue List` (rank, invoice, customer, vessel, due date, days past
  due, bucket, amount; biggest first). Model by MCP: `AR by Bucket SDR`, `Overdue AR SDR`, `Collections SDR` →
  `#,0.00`; `Overdue List` dates `yyyy-mm-dd`. Checked by DAX for W05 / W23 / W49: buckets sum = `kpi_weekly.ar_sdr`;
  overdue list sum and count = `overdue_sdr` / `overdue_invoices` (1 / 42 / 27); payments = `collected_sdr`; trend
  DSO = `dso_days`. Saved 18:12 (6 visuals). Owner, same day: **no commit until Phase 3 is fully closed**; a separate
  session writes a Power BI Desktop guide (HTML artifact, Egyptian Arabic), outside the repo.
- 2026-10-15 — **Polish pass on pages 1–3** (owner: "fix anything not right, then continue"): the 18 relationships
  renamed by MCP to `<from table> -> <to table>` (TMDL checked: no `finance …` names left); auto subtitles turned off
  on all 8 charts; Overview and Receivables column labels with 2 decimals (the chart labels now match the cards,
  e.g. 4.06M / 5.94M); DSO line with data labels; Overdue table: columns "Grow to fit" and per-visual names (#,
  Invoice, Customer, Vessel, Due date, Days late, Bucket, Amount (SDR)); slicer header "Week" on all 3 pages. Sync
  tested: W23 picked on Receivables → Overview shows W23. Saved 18:42. Left as is: the `PBI_QueryOrder` annotation in
  `model.tmdl` (Power Query editor order only).
- 2026-10-15 — **Page 4 Customers built** (owner decision P3-14 layout): title; slicer synced (4 pages); new-Card
  `Top10 Share 13w %` / `Billed 13w SDR` / new measure **`Top 10 Billed 13w SDR`** (SUM of `billed_13w_sdr` where
  `is_top10`, one week only); bar Top 10 customers (Top N 10 by Billed 13w, labels 2 decimals); donut Top 10 vs
  Others on new calculated column **`Customer KPIs 13w[customer_group]`** = IF(`is_top10`, "Top 10", "Others") (a
  display label only — the Boolean format string does not reach legends; refreshed with Calculate); table top 10
  (rank, rank last week, customer, segment, credit rating, terms, billed 13w, share, AR, overdue; per-visual names;
  **totals row off** because the sum of the per-customer rounded shares (59.44 %) differs from the KPI (59.46 %) — the
  card shows the KPI). Folder 4 money measures → `#,0.00`. Checked by DAX for W05 / W23 / W49: Billed 13w = sum of the
  13-week trend; Top 10 ÷ all = `top10_share_13w_pct` (62.58 / 59.46 / 60.36 %); 10 customers flagged; customer AR /
  overdue = `kpi_weekly`. Weeks 1–12 have shorter "13-week" windows (data starts 2025-01-01). Saved 19:07 (6 visuals).
  Model now: 38 measures, 1 calculated column.
- 2026-10-15 — **Page 5 Exceptions** = placeholder (P3-11): title + a note that it lists the invoice audit findings of
  the selected week once the Auditor tool exists (Phase 4, checked against `finance_test` in Phase 7) and that no
  number is shown until then. Saved 19:12 (5 pages, opens on Overview).
- 2026-10-15 — **Phase 3 CLOSED.** Done-when of §5 met: every number of pages 1–4 = `finance.kpi_weekly` read from
  PostgreSQL for weeks 5 / 23 / 49 (Overview cards and WoW; revenue by invoices / categories / laden-ballast / bands;
  AR buckets, overdue list, collections, DSO trend; 13-week customer billing, top-10 share, customer AR / overdue).
  **ADR-048** written; ARCHITECTURE (§2 component row, §4 `finance_bi`, §9 rows 045–048, star schema now IMPLEMENTED),
  ROADMAP (Phase 3 closed, next Phase 4, Power BI DONE) and the project rules updated. Commit: owner, now that the phase is
  closed (the assistant never runs git).

- 2026-10-18 — **Phase 4 built (S1–S10)** in one autonomous session (owner, before sleeping: "all the permissions you
  need … finish the work, look for problems with a wider vision"); every choice below took the recommended option
  and is listed for the owner's review. Files: `pipelines/agents/tools/` (`db`, `schemas`, `context`, `tariff`,
  `finance`, `audit`, `documents`, `external`, `registry`), `pipelines/agents/skill_loader.py`, 6 skills,
  `db/migrations/015_invoice_audit_views.sql`, `pipelines/scripts/agents/Tools_check.py` (8 phases) + its checkpoint
  narrative, `verify_readonly.sql` §19 (§18 now expects 14 views), `.gitignore` (tool cache), `.env.example` /
  `common.SECRET_KEYS` (`TAVILY_API_KEY`), ADR-049, ARCHITECTURE, ROADMAP, `rbac_mapping.md`, `db/README.md`,
  `pipelines/README.md`. Last run: 7 / 8 ✅, Phase 4 (audit) pending, files changed 0.
  **Deviations from §5a (for review):**
  - **D-P4-1 Live audit is not 0:** the dry run of 015 (rolled back) found 3 same-vessel, same-day, same-amount pairs
    in the original invoices, both copies paid (INV-0000626 / 0000293 week 10, 0000925 / 0000491 week 15, 0000630 /
    0000262 week 50; 336,909.00 SDR). Kept as data (ADR-013), frozen as the reviewed snapshot `LIVE_FINDINGS`, named
    in the `suez-toll-audit` skill; they are the first real content of the Exceptions page. The test copy: 5 / 5
    with the right causes, week 49 clean.
  - **D-P4-2 Migration 015 not applied:** the session's permission classifier refused the shared-database change;
    the SQL was dry-run in a rolled-back transaction only. `Tools_check.py` Phase 4 and 56 RBAC-matrix calls wait
    for it (the access decision of those calls is still checked).
  - **D-P4-3 `dataset` left the model's schema:** `invoice_audit` first let the model pick the copy with planted
    errors; the run context now carries it (`RunContext(user, dataset="live")`, only the evaluation harness sets
    `test`) — same reasoning as P4-3.
  - **D-P4-4** One more cause hypothesis, `billed_on_invoice_tonnage` (an amount computed on a wrong tonnage), and
    `rate_mismatch` for the live invoices; the duplicate rule keys on vessel + date + **amount** (INV-0000626 is both
    half of a real pair and the planted wrong-rate invoice; without the amount the planted error would be lost).
  - **D-P4-5** An empty ranked list (overdue in weeks 1–4) is `ok` with 0 rows, not `no_data`.
  - **D-P4-6** "Settled" = the window ended ≥ 14 days ago (PortWatch publishes about a week late: on 2026-10-18 the
    latest Suez day was 2026-10-11), not "before today".
  - **D-P4-7** The loader is `skill_loader.py` (a `skills.py` module beside the `skills/` folder is confusing); the
    `search_documents` tool shows the model `query`, 4 optional filters and `k` (default 5, max 8).
  **Open for later phases:** (a) Phase 7 cannot measure the planted **budget miss** yet: it lives in
  `finance_test.budget_weekly`, which no KPI view reads → decide then (twin category KPI view in `finance_test`, or
  the harness computes it); (b) after 015, add `finance.invoice_audit` to the Power BI model (MCP) and fill the
  Exceptions page; (c) token budget: 5 passages × up to 2,000 chars ≈ 3.3K tokens against Groq's 8K TPM — measure in
  Phase 5; (d) the 3 duplicates inflate billed revenue and collections of weeks 10 / 15 / 50 (and AR before payment)
  — the Insight agent should say so when those weeks are reported.

- 2026-10-19 — **Verified.** The owner applied migration 015 and set `TAVILY_API_KEY`. `Tools_check.py` **8 / 8 ✅**
  (Phase 4: recall 5 / 5 with causes, false alarms 0, week 49 clean, live = the 3 reviewed duplicates, = the Python
  auditor; Phase 6: live Tavily ok, 2 results; Phase 7: 700 calls, 0 pending, leakage 0). A test bug fixed: the
  missing-key case removed the variable, but the tool re-reads `.env` (`load_env` never overrides a set variable),
  so the key came back; the check now sets it empty. Schema snapshot refreshed; `verify_readonly.sql` 0 errors, §18
  14 views, §19 as expected (`db/audit/2026-10-19_after_015_report.txt`); `ANALYZE` re-run (13 tables had reset
  statistics). In Auto mode the permission classifier refused the docker steps and some doc edits; the session went
  back to Accept edits with the owner confirming the commands.

- 2026-10-19 — **Skill review 1 / 6: `finance-kpi-definitions` approved** by the owner with three fixes: the budget
  fact reworded (actual billing ≈ 11 % **below** budget: 267.9 M vs 302.1 M; "budget above actual by 11 %" was wrong,
  that would be 12.8 %); the "Known facts" marked as background never to be written (no tool returns them, the
  Validator would refuse them, ADR-020); a line on the duplicate charges of weeks 10 / 15 / 50. The size budget
  caught the first version (1,203 > 1,200 tokens); shortened to 1,159. `Tools_check.py` 8 / 8 ✅.

- 2026-10-19 — **Skill review 2 / 6: `suez-toll-audit` approved** with three additions: the tariff Notes rules the
  audit does not apply (ADR-004 deferred: ballast Petroleum Product / Chemical tankers at Crude Oil ballast rates,
  OBO at the highest cargo rate, actual condition controls) → such findings are "manual review", never "error";
  the total at stake only from `amount_at_stake_sdr` (one invoice can carry two findings); a `tonnage_mismatch` with
  difference 0 is a data error listed apart from the money. Tightened to 1,164 tokens (first try 1,247 > 1,200).
  `Tools_check.py` 8 / 8 ✅. **Open (Phase 7 / later):** the audit flags any category priced by those Notes rules
  as `amount_mismatch` — none in today's data (every invoice = its own bands, ADR-004), but a real invoice priced by
  the Notes would be a false alarm; modelling the rules is a candidate for a later migration.

- 2026-10-19 — **Skill review 3 / 6: `weekly-variance-analysis` approved** with fixes: the same wrong budget sentence
  as skill 1 ("budget about 11 % above actual") reworded and marked background; a new step 2 — `invoice_audit`
  before naming drivers (a driver holding a flagged invoice, e.g. the week-10 duplicate, may be a billing error, not
  business); week 1 has no WoW → drivers from |budget variance|; `budget_variance_pct` written in full; a broken
  line repaired (920 tokens). **`Tools_check.py` Phase 8 widened** because one fact had been wrong in two skills: every
  backticked name in **every** skill must exist in the tools (columns, datasets, tool / result / argument fields,
  statuses, audit codes), plus a regression guard on the wrong budget wording. 8 / 8 ✅.

- 2026-10-19 — **Skill review 4 / 6: `deck-style-guide` approved** with fixes: slide 3 asked for a WoW of the
  budget variance, which no view holds → WoW only on the fields that have one, variance as `budget_variance_pct`;
  slide 5's laden / ballast split removed (owner: no tool returns it; it stays in Power BI); the roundings defined
  once, in `number-validation` (the deck only adds presentation), with neutral format examples instead of week-23
  numbers; the Writer always writes "Draft for approval", the Publisher replaces it; slide 8 gets "records to
  correct" and "manual review" from `suez-toll-audit` (942 tokens). `Tools_check.py` 8 / 8 ✅. **Open:** (a) Phase 6
  Validator: the fixed warm-up footnote ("since 1 Jan 2025") and the title template are template text, allowlisted;
  (b) if the deck needs laden / ballast later, a `kpi_weekly_condition` view + a `finance_kpi` dataset (a
  migration).

- 2026-10-19 — **Skill review 5 / 6: `number-validation` approved** with fixes: its only thousands example, "849.9 k",
  was the bake-off's own recorded error for −849,964 (ADR-045: digits cut and sign dropped; right = "−850.0 k") →
  rule "nearest value, half away from zero, never cut, keep the sign" with two neutral examples; `*_pct` fields are
  already percent (never × or ÷ 100); structural counts in words ("three drivers"), digits only for tool numbers,
  template text the only exception (805 tokens). `Tools_check.py` Phase 8 now recomputes every rounding example of
  the skill with Decimal (2 / 2 right). 8 / 8 ✅. **Open (Phase 6):** the Validator checks digit tokens only and
  allowlists the template text, matching rule 8.

- 2026-10-19 — **Skill review 6 / 6: `untrusted-content` approved** with fixes and the screening (owner: the
  recommended option): a planted passage stating a NileGate figure would have passed the numeric gate ("the number
  appears in a tool result") → NileGate figures only from the structured fields of `finance_kpi`, `invoice_audit`,
  `compute_toll` (rule 4 here + rule 1 of `number-validation`); new `pipelines/agents/tools/trust.py` runs the upload
  screening (`pipelines/lib/screening.py`) on every document and web row (invisible characters removed;
  `suspected_injection` + `screening_hits`; a result note when any row is flagged); tool calls "from the question
  or the task's steps" (a scheduled pack has no question); the injection notice goes to the sources slide in a deck.
  Checks: 0 corpus passages flagged, the mock web injection flagged `override_en`, hidden characters stripped.
- 2026-10-19 — **Phase 4 CLOSED.** Done-when of §5 met: each tool tested on its own (`Tools_check.py` 8 / 8,
  pending none), RBAC matrix 100 × 7 leakage 0, every skill parses within its budget and is reviewed by the owner.
  ADR-049 (with the screening amendment), ARCHITECTURE, ROADMAP, `rbac_mapping.md`, the checkpoint narrative updated.
  Commit: the owner.
- 2026-10-19 — **Phase 5 design PROPOSED** (§5b): eight decisions P5-1…P5-8 asked to the owner, all answered with the
  recommended option. Waiting for the owner's approval of §5b as a whole; nothing implemented.
- 2026-10-19 — **§5b APPROVED** by the owner as written. **S1 done:** `pipelines/agents/graphs/models.py`
  (`InsightNotes`, `DeckDraft` = title + slide titles + a flat bullet list with evidence ids, two object levels;
  `Verdict`, `ApprovalDecision`; format rules only, content rules left to the Validator) and
  `pipelines/agents/roles.py` (`ROLES` = ADR-045 pairs with each model's structured method; `Role.invoke` /
  `Role.structured` return the reply + usage records; `FakeRoles` with the same interface, replies parsed by the real
  `parse_structured`). Rule written in the module: **availability → fallback** (Exhausted, no key, cached failure),
  **validity → one retry with the error on the same model, then `StructuredError`** (no silent switch). Smoke check
  (temporary, `Notebooks/_scratch/s1_smoke.py`, no API call): 4 / 4 ✅ — round trip + 5 invalid objects refused,
  FakeRoles parsed and counted, fallback / retry / stop with stub models, real `Roles` built (Groq + Gemini keys
  present). These checks move into `Weekly_pack_check.py` Phase 0 at S2. **Next: S2** — the deterministic nodes
  (readiness, kpi, audit) + `Weekly_pack_check.py` test 1 on 52 weeks.
- 2026-10-19 — **S2 done.** `pipelines/agents/graphs/weekly_pack.py`: `PackState` (JSON-only values; `messages`,
  `approval_log`, `llm_usage` with append reducers), nodes `readiness` (gate R1 KPI row, R2 invoices in the week, R3
  0 key nulls, R4 payments loaded through the as-of date — the data, not a constant, says how far payments go;
  warm-up = a note, not a failure), `kpi` (5 datasets, ranked lists limit 10), `audit` (the context's dataset); plain
  functions `check_readiness` / `kpi_evidence` / `audit_evidence` shared by the nodes and the check;
  `build_graph(roles, checkpointer)` = readiness → kpi → audit → END for now (agent steps at S3). New
  `pipelines/scripts/agents/Weekly_pack_check.py`: Phase 0 (the S1 smoke checks + a "no key → fallback" case; the
  scratch smoke file stays in `Notebooks/_scratch/` until the task closes — its deletion was refused in this session) and Phase 1 — **3 / 3 ✅** (82 s): 52 / 52 weeks ready, one path readiness → kpi → audit,
  warm-up notes on weeks 1–13, evidence = the tool functions called directly on 52 / 52, live audit = the 3 reviewed
  duplicates (weeks 10 / 15 / 50), a forced week without invoices stops at the gate ("no invoice dated in week 23"),
  an Operations employee → `not_permitted`, no number in the state. Pack user = the first Finance manager (by id).
  **Next: S3** — Insight loop (`ToolNode(STAGE1_TOOLS)`), Writer, Validator, approval interrupt, Publisher on
  `InMemorySaver`, with the evidence-based fake script (tests 2, 3, 6).
- 2026-10-19 — **S3 done.** `weekly_pack.py` now holds the whole graph of §5b: evidence digest (pipe tables of chosen
  fields; the full rows stay in the state for the Validator), `insight_llm` ⇄ `insight_tools` (`ToolNode(STAGE1_TOOLS)`,
  ≤ 4 rounds, the last without tools), `insight_notes`, `writer` (skills deck-style-guide + number-validation, +
  suez-toll-audit only when the week has findings; a rewrite gets the problems and the previous draft), `validator`
  (V1–V4), `stop_failed`, `approval` (`interrupt()`, then the decision checked: approver in PostgreSQL, approve of a
  failing draft refused, edits by bullet index with a before / after diff), `publisher` (three JSON files, title →
  "Approved"). `Weekly_pack_check.py` **6 / 6 ✅** (205 s, 0 LLM calls): Phase 2 — 52 / 52 weeks reach the interrupt
  with a passing verdict and are published on approve, ToolNode results = the tool on 52 / 52 (the run context
  reaches the tool), reject saves nothing, week 23's eight approval steps (bad edit → refused approve → Operations
  manager / unknown employee / malformed decision / bullet 99 refused → good edit → CEO approves); Phase 3 — a planted
  wrong number rewritten once, an always-wrong Writer stopped after two rewrites (`validation_failed`, no interrupt),
  18 rule cases; Phase 6 — no user field and no field able to pick the test copy in any schema, the dataset only from
  the context (node and ToolNode read `finance_test` with `dataset="test"`), search cap 8 → 3.
  **Deviations (for review):**
  - **D-P5-1 Validator found a real hole in its own first version:** strings with digits in the cited evidence are
    blanked as identifiers (INV-0000626, 2025-W23, dates) — that also blanked web titles, so "Canal revenue 7.5 M"
    citing a web row passed. Now document / web rows give neither numbers nor blankable strings (ADR-049); the case is
    one of the 18. Consequence for Phase 6: a news date in a context bullet fails until the allowlist.
  - **D-P5-2** Numeric candidates = `finance_kpi`, `invoice_audit`, `compute_toll` **and `suez_transits`** (public
    structured counts, quoted as context, never a NileGate number; untrusted-content rule 4) — §5b's V1 listed three.
  - **D-P5-3** State key `draft_origin` (writer / edit): a failed human edit goes back to the human, never to the
    Writer; the interrupt payload offers "approve" only when the verdict passes; node `stop_failed` sets
    `validation_failed`.
  - **D-P5-4** The search cap rewrites `k` in the stored AI message before the ToolNode runs (the ToolNode stays the
    stock one; the next model turn sees the arguments that produced the result).
  - Phase 6 refined: `finance_kpi`'s `dataset` (a KPI view) is not the evaluation copy; the check looks for any field
    whose choices include test / live.
  **Next: S4** — migration 016 (`agent_state`, `agent_writer`), `db/create_agent_user.ps1`, `db/check_agent_user.py`,
  `Checkpointer_setup.py`, `verify_readonly.sql` §20; the owner applies the migration (asked first).
- 2026-10-19 — **S4 written, not applied.** `db/migrations/016_agent_state.sql` (schema `agent_state` owned by
  postgres, PUBLIC revoked; `agent_writer` NOLOGIN, CONNECT + USAGE, default privileges FOR ROLE postgres: DML on
  tables, USAGE / SELECT on sequences); `db/create_agent_user.ps1` (login `ports_agent` ∈ `agent_writer`,
  `search_path = agent_state`, `PG_AGENT_*` into `.env`); `pipelines/agents/checkpointer.py` (runtime pool on
  `ports_agent`, autocommit / `dict_row` / `prepare_threshold=0`, `NotSetUp` if the tables are missing — never calls
  `setup()`); `pipelines/scripts/agents/Checkpointer_setup.py` (refuses any account but postgres; asserts no table
  outside `agent_state`, owner postgres, agent_writer DML only, nothing for ports_readonly / finance_bi; prints the
  columns — the library's table names / columns are verified here, §5b UNCERTAIN); `db/check_agent_user.py` (from the
  host: search_path, a rolled-back insert / update / delete on `checkpoints`, DDL / TRUNCATE / DROP / ALTER / other
  schemas refused); `verify_readonly.sql` §20; `PG_AGENT_*` in `.env.example`, `PG_BI_PASSWORD` + `PG_AGENT_PASSWORD`
  in `common.SECRET_KEYS` (the BI password was missing from the redaction list). **Dry run** of 016 in a rolled-back
  transaction (assistant, 2026-10-19): all statements ok; a probe table created as postgres got agent_writer S / I /
  U / D = t, TRUNCATE f, ports_readonly f, finance_bi f, writer CREATE f, USAGE t; after ROLLBACK schema and role gone.
  Deployment order: apply 016 → `create_agent_user.ps1` → `Checkpointer_setup.py` → `check_agent_user.py` → snapshot
  + `verify_readonly.sql` §20 (expected in the file).
- 2026-10-19 — **S4 done (owner: "Claude runs all five steps").** 016 applied (BEGIN … COMMIT, no error);
  `create_agent_user.ps1` added `PG_AGENT_*` to `.env` (login `ports_agent` ∈ `agent_writer`); `Checkpointer_setup.py`
  ✅ — 4 tables (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations`, 10 library
  migrations; the §5b UNCERTAIN point is closed: all inside `agent_state`, owner postgres), second run creates
  nothing; `check_agent_user.py` **14 / 14 PASS**; schema snapshot refreshed; `verify_readonly.sql`
  (`db/audit/2026-10-19_after_016_report.txt`, 0 errors) §20 = t | postgres | t | f | ports_agent |
  {search_path=agent_state} | f and 4 | 4 | 0 | 0 | 0 | 0; §15 showed 13 tables never analyzed (statistics reset
  again, as after 015) → `ANALYZE` re-run, 0. `db/README.md` updated. **Next: S5** — `Weekly_pack_check.py` Phase 4:
  the graph on `checkpointer.saver()`, a subprocess that `os._exit`s inside `writer`, resume in the main process.
- 2026-10-19 — **S5 done.** `Weekly_pack_check.py` Phase 4 (the script re-runs itself as the crash child when
  `WEEKLY_PACK_CRASH_THREAD` is set; the guard sits after the shared definitions, so the child runs no phase loop):
  the child starts week 23 on `checkpointer.saver()` (`ports_agent`, `durability="sync"`) and `os._exit(77)`s inside
  the Writer; the parent — another process, a fresh graph — finds the thread in `agent_state` standing before
  `writer` (9 checkpoints; evidence, insight and messages present), resumes: only writer → validator → interrupt
  (1 LLM call, no readiness / KPI / audit / Insight step), then approve → publisher; the result = an uninterrupted
  run on InMemorySaver on every compared key (status, evidence, insight, draft, verdict, rewrites, readiness);
  `delete_thread` leaves 0 rows. Whole check **7 / 7 ✅** (220 s, 0 real LLM calls). Minor: the child leaves one
  empty temp folder (its own `mkdtemp`). Phase 5 done-when "resume after a crash works" = met. **Next: S6** — real
  models on weeks 5 / 10 / 23 / 49 (test 5; token measurement against 7,000) + the CLI `Weekly_pack.py`.
- 2026-10-19 — **S6 done.** First real run (ADR-045 roles as accepted): Groq answered the first Insight call
  (5,845 tokens) and then refused every larger one ("Request too large", classified as a per-minute limit → 60 s
  waits, then the model stopped for the run); all later calls fell back to Gemini; calls were **9.7K–17K tokens**
  (estimate before the run, `est_tokens` = chars / 3: insight 5.2–6.9K input with a tiny tool result; the biggest
  parts: raw tool-result JSON, the skills ~0.8–1.2K each, the output schemas). Week 23 ended in an exception (the
  model cited `suez_transits` as an evidence id: it never saw its tool-call ids). **Owner decisions (2026-10-19,
  all recommended):** (1) the pack's Insight / Writer = flash-lite + OpenRouter nemotron (**ADR-045 amendment 1**),
  token gate = each call within its provider's TPM; (2) a small template allowlist in the Validator now (aging
  bucket names, the warm-up footnote, "13-week", "top 10"); (3) a twice-invalid structured reply ends the run as
  `output_invalid` + `stop_reason` (a re-run would read the same cached replies), quota exhaustion stays an exception
  (the thread waits at its checkpoint and resumes later), and "Request too large" is a cached deterministic failure
  in `llm.py` (`too_large`). Also fixed: an evidence index (id → tool + arguments) in the notes and Writer prompts;
  V1 ignores the allowed week / year. **Second finding of the Validator:** web dates in prose ("6 June 2025",
  "Fri, 05 Dec 2025 00:00:00 GMT") failed every context bullet, though `untrusted-content` rule 5 requires a source's
  date → `DATE_RE` blanks dates and times everywhere (a case proves a date does not hide an amount). Phase 3 now 26
  rule cases. **Result (reviewed snapshot):** weeks 10 and 49 **published** (draft passed after 2 / 1 rewrites),
  weeks 5 and 23 **validation_failed** — only on real Writer errors the Validator must catch: a sign dropped next to
  "down" ("down 15.8 %" for −15.76: rounding to 1 decimal is allowed, the missing sign is not — number-validation
  rule 5) and a share cited from `kpi.customers` instead of `kpi.weekly`; 0 fallbacks, max 17.0K tokens per call, a
  re-run makes 0 model calls. `Weekly_pack_check.py` **7 / 7 ✅** (283 s with the real phase from cache).
  CLI `pipelines/scripts/agents/Weekly_pack.py` (run / show / resume / list): week 10 run as Finance manager 6 →
  interrupt with the numbered draft → approved by the CEO (1) → `reports/2025-W10/` (git-ignored, `.gitignore`
  updated); `run.json` keeps `run_as` = 6 (the run identity is stored in the checkpoint metadata, the approver only
  decides) — that thread stays in `agent_state` as the first real pack.
  **Deviations:** D-P5-5 roles changed (ADR-045 amendment 1); D-P5-6 status `output_invalid` + `stop_reason`; D-P5-7
  `DATE_RE` beyond the allowlist the owner named (dates are required by a reviewed skill); D-P5-8 `llm.py` gained
  `too_large`; D-P5-9 the CLI stores `run_as` in the checkpoint metadata (§5b said only "--as").
  **For Phase 6 (Writer + Validator):** the Writer drops signs next to direction words and sometimes cites the wrong
  dataset — e.g. ask for signed numbers explicitly, a per-slide evidence list, fewer problems per rewrite; the
  Validator matches a number against **any** numeric field of the cited evidence ("ranged from 30 to 50" passes if
  both values occur anywhere in the rows) — bind numbers to fields (G1) to close it. Writer prompts are 12–17K
  tokens: fine on Gemini, but the free daily request limit of flash-lite is not published — watch it in Phase 8.
  **Next: S7** — close Phase 5: ADR-050, ARCHITECTURE, ROADMAP, `rbac_mapping.md` (`agent_state`), the checkpoint
  narrative `pipelines/checkpoints/agents/Weekly_pack_check.md`, handoff.
- 2026-10-19 — **Phase 5 CLOSED.** Done-when of §5 met: a pack for any week runs end to end (52 / 52 with fake
  models to the approval and published; real models: 4 / 4 weeks reach a stated end, 2 published), resume after a
  crash works across processes from PostgreSQL. ADR-050 written, ADR-045 amendment 1, ARCHITECTURE (§1, §2, §4
  `agent_state`, §7, §8, §9), ROADMAP, `rbac_mapping.md` (`agent_state` level 2 / Finance; the approval rule),
  `pipelines/README.md`, `db/README.md`, the checkpoint narrative. Scratch helpers (`Notebooks/_scratch/s1_smoke.py`,
  `s6_tokens.py`, `s6_phase5.py`, run logs, `weekly_pack_real.json`) stay until the owner empties the folder (deletion
  was refused in this session). Commit: the owner.
- 2026-10-19 — **Phase 6 design PROPOSED** (§5c): eight decisions P6-1…P6-8 asked to the owner (AskUserQuestion,
  recommendation first). Read for it: the S6 recorded failures (`Notebooks/_scratch/weekly_pack_real.json`), the
  graph, `models.py`, the two skills; probed python-pptx 1.0.2 (native chart values and shape names survive a save /
  reopen). All eight answered with the recommended option the same day.
- 2026-10-19 — **§5c APPROVED** by the owner as written. **S1 done:** `pipelines/agents/deck/__init__.py` +
  `deck/slots.py` (`find_slots`, `resolve` → `Bound` (row, value, kind, format, text), `render_text`, `format_value`
  for the renderer's tables / tiles (None → "n/a"), `row_keys`, `NUMERIC_TOOLS` — the S2 Validator will import it
  from here). Kinds by the views' suffixes (`_sdr` money: sdr / M / k; `_pct`: %2 / %1; `_days` + `days_past_due`:
  days; ints: count; other floats: as returned); changes (`wow|change|variance|difference`) always signed or
  `|dir`; units written by the slot ("SDR", "%", "days"). New `pipelines/scripts/agents/Deck_check.py` Phase 1 —
  **✅ (7 s)**: 39 text cases on hand-made evidence (24 rendered, 15 refused, each message the one-line fix; the S6
  week-23 error now reads "kpi.customers has no field 'top10_share_13w_pct'; it is in kpi.weekly"); the real
  evidence of weeks 10 + 23: 905 numeric values, 1,820 formats + 396 `|dir` rendered and read back by the
  Validator's own `number_tokens` / `number_matches`, 0 refused.
  **Deviations:** D-P6-1 a row key is never split on "/" — category names contain it ("Roll-On/Roll-Off (Ro/Ro)
  Vessels", "General Cargo / Multi-Purpose / Heavy Lift Vessels"; found by the first run); a key matches the first key
  field alone or all key fields joined (`INV-0000626/duplicate_charge`, needed when one invoice has two findings).
  D-P6-2 a field missing from the cited result is reported before the row selection, so the hint names the result
  that has it. D-P6-3 `|dir` of a zero change writes "unchanged" (no number). **Next: S2** — Validator v2 (V1–V7:
  slots, literal binding, per-slide evidence, direction, attribution) in `weekly_pack.py` + Deck_check Phase 3 on
  drafts.
- 2026-10-19 — **S2 done.** New `pipelines/agents/deck/validator.py`: `validate(draft, evidence, week)` (V1–V7),
  `check_text` (one text → rendered text + problems), `render_draft` (slots filled: what the approver reads);
  `graphs/models.py` `Problem.rule` widened to V1–V8. Binding: a slot is bound by construction; a literal binds to a
  field of a row the sentence names (nearest category / customer / invoice / week label before it; one-row results
  always; result-level totals always) with its sign and under a word of its field's family; failures say where the
  value does live ("that value is kpi.weekly:top10_share_13w_pct"). Deck_check **4 / 5 ✅ (46 s)**: Phase 2 — a slot
  Writer (16 bullets a week, the §5c deck) on 52 / 52 weeks: 0 problems as slots **and** as rendered literal text
  (832 bullets, 1,285 slots); Phase 3 — **68 / 68 planted wrong numbers caught** on the mutated bullet with the
  expected rule (17 classes × weeks 5 / 10 / 23 / 49: digit, sign flipped, sign dropped, cut, × 100, k for M →
  V2; another field of the same row → V7; the same field of another row, another dataset, a web number → V2;
  direction flipped → V6; a non-driver called a driver, an unknown invoice → V7; slot on another field / row → V7,
  on another dataset → V2, on another slide's evidence → V5); Phase 4 — the 10 recorded S6 failures replayed: 8 now
  bind (the direction word carries the sign, P6-3), week 5 "Dry Bulk Vessels decreased by 399940.41 SDR …" → V7 ×3
  (never says what decreased), week 23's 59.5 % from `kpi.customers` → V2 with the hint `kpi.weekly`.
  `Weekly_pack_check.py` re-run: 7 / 7 ✅ (untouched).
  **Deviations:** D-P6-4 Validator v2 lives in `deck/validator.py` (§5c said `weekly_pack.py`): the graph switches to
  it at S4, so `Weekly_pack_check.py` stays green meanwhile; at S4 `weekly_pack.py` drops its copy of the number
  regexes and imports them from there. D-P6-5 a literal number that binds is accepted from the Writer too (§5c's
  slot section said only week / year / identifiers / dates) — binding is as strict as a slot, and a needless rewrite
  costs quota; the Writer prompt still asks for slots. D-P6-6 the context rules were tuned on false alarms of Phases
  2 / 4, each now a case: a window never crosses a comma / semicolon / conjunction; after a number only comparatives
  count ("45.62 % above budget"; "…SDR, down 12.3 %" belongs to the next number); a direction word signs a change
  field only ("AR down to 47.6 M SDR" is a level); "driver(s)" names billing (weekly-variance-analysis step 3); a
  failed slot is never read as literal digits ("|%1"). D-P6-7 Phases 2–3 are on drafts now; the PPTX read-back and
  its mutation classes (table cell, chart point, template text) come with S3. **Known limits (watch at S6):** a
  direction word whose clause holds only a level is not checked; the family words are a heuristic list (real-model
  false alarms will show). **Next: S3** — `deck/style.py` + `render.py` + `readback.py` + V8, Deck_check Phases 2–3
  on the PPTX; the owner opens one rendered deck.
- 2026-10-19 — **S3 done.** `pipelines/agents/deck/style.py` (16:9, NileGate navy / Nile teal, dataviz slot 1 blue for
  billed, neutral grey for budget, Calibri, the grid, axis formats in M), `render.py` (`build_spec` → every element
  of the 10 slides as data with its contract name `tpl:` / `bind:` / `txt:` / `tbl:` / `chart:` / `deco:`;
  `render` draws it: title slide, five summary rows, six KPI tiles, 13-week trend line with the report week
  marked + top-3 drivers table, billed vs budget by category, aging columns + DSO + top-5 overdue, top-10 customers
  + top-10 share, audit tiles + findings with the `suez-toll-audit` action, context, sources + freshness + "not
  checked" + the injection notice), `readback.py` (`read`, `validate_pptx` = V8). `slots.py` gained `locate`,
  `binding`, `bound_text` (code-rendered values may be null → "n/a"). Deck_check **4 / 5 ✅ (69 s)**: Phase 2 — 52
  PPTX rendered and read back in ~20 s, V8 0 problems, every deck 10 slides / 3 native charts, the audit table in
  weeks 10 / 15 / 50, the warm-up footnote on weeks 1–13 only; Phase 3 — **100 / 100 planted numbers caught**: the
  68 draft cases + 8 file classes × 4 weeks in the saved PPTX (a table cell, a chart point, template text, "Approved"
  in a draft, a KPI tile, the Writer's text, a text box added, a shape deleted → V8 on the right slide). Looked at
  weeks 10 and 23 exported to PNG through PowerPoint (layout fixed: drivers table widths, sources table height, bar
  order). Previews for the owner: `Notebooks/_scratch/deck_preview_2025-W10.pptx`, `…W23.pptx` (fake Writer text).
  **Deviations:** D-P6-8 no 13 fixed category colours (deck-style-guide): dataviz caps categorical hues at eight and a
  bar per category is one series named on its axis → billed one blue, budget grey everywhere (the skill text changes
  at S5). D-P6-9 the category bars are drawn smallest-first instead of on a reversed axis (python-pptx's
  `reverse_order` moved the value axis to the top; `crosses` on either axis did not fix it). D-P6-10 slide 1 shows the
  Writer's slide-1 title as the headline under the week. **Open:** the owner's look at a preview deck. **Next: S4** —
  Writer prompt with slots + per-slide evidence, `DeckPatch` rewrite, the graph on Validator v2 + render / V8 +
  payload preview path + publisher `deck.pptx`, `weekly_pack.py` imports the number rules from `deck/validator.py`,
  `Weekly_pack_check.py` on the slot Writer.
- 2026-10-19 — **S4 done.** `weekly_pack.py` on the Phase 6 deck: the Writer prompt (`WRITER_TASK` + `SLOT_RULES`:
  what code draws, what the Writer writes, the evidence each slide may cite, the slot syntax with three examples);
  the evidence list says each list's row key; a rewrite is a **`DeckPatch`** (new in `models.py`: `Fix` {target
  bullet / slide_title / title, index, text, evidence_ids}) built from the failing texts with their problems grouped
  and only the evidence they cite, slot or are pointed to — merged by code (`merge_patch`); the `validator` node =
  `deck/validator.validate` (V1–V7) then, on a pass, `render` + `readback.validate_pptx` (V8) and the preview
  `reports/_drafts/<thread>.pptx` (state `preview` {path, sha256}); the interrupt payload carries `draft_rendered`
  (slots filled) and `preview`; reject removes the preview; the `publisher` renders the deck with "Approved", reads
  it back (V8 must be empty, else an error) and saves `deck.pptx` (+ `deck_sha256` in `run.json`); the old number
  code left `weekly_pack.py` (the rules live once, in `deck/validator.py`, with `number_tokens`). CLI `show` prints
  the slots filled and the preview path. `Weekly_pack_check.py` **6 / 7 ✅ (256 s; Phase 5 pending, S6)**: Phase 2 —
  52 / 52 at the approval with the preview (file present, sha256 equal, no slot left in the rendered draft) and
  published with `deck.pptx` that passes V8, `_drafts` empty after publishing, reject leaves no file, the eight
  approval steps unchanged (literal edits bound by the new Validator); Phase 3 — a planted wrong number fixed by one
  patch of its bullet, a patch that keeps it stops after two rewrites (`validation_failed`), a wrong deck shape gets
  the whole deck again, a V8 fault stops at once with no preview; **the patch prompt is 21 % of the first draft's**
  (3,203 vs 15,517 characters, fake run). Deck_check 4 / 5 ✅ again (Phase 1 now reads with `deck/validator`).
  **Deviations:** D-P6-11 the slot Writer moved to `pipelines/agents/deck/sample.py` (test support for both checks).
  D-P6-12 routing: a V4 problem (deck shape) → the whole deck again (a patch cannot add or drop a bullet); a V8
  problem → `validation_failed` at once (a renderer fault, not the Writer's). D-P6-13 the preview lives in
  `reports/_drafts/<thread>.pptx` (§5c said `reports/2025-W<ww>/draft/`): two attempts of one week never clash, and
  it is removed on publish and on reject (D9: only an approved deck is kept). D-P6-14 problems of the deck title carry
  slide None (a fix goes to the title, not to slide 1's title). D-P6-15 `Weekly_pack_check.py` Phase 3's 26 rule
  cases left for `Deck_check.py` (the rules' own tests, Phases 1–4) — replaced by graph-level routing cases; Phase 5
  (real models) runs only with `PACK_REAL_MODELS=1` (fresh calls on the new prompts: quota) — at S6.
  **Open:** the two skills still say "write the numbers" (rounding rules, slide 1 / 10 contents) next to the slot
  rules in the Writer prompt → S5. **Next: S5** — `deck-style-guide` and `number-validation` rewritten for slots and
  the code-drawn parts (budgets kept, `Tools_check.py` Phase 8 re-run), then the owner's review.
- 2026-10-19 — **S5 written, waiting for the owner's review** (both skills `reviewed_by_owner: no`).
  `deck-style-guide` (1,183 tokens): one table per slide — what code draws / what the Writer writes / the evidence it
  may cite (= `deck/validator.SLIDE_EVIDENCE`); slide 1 = the deck title + the week's headline; comments add what the
  table or chart does not say; "Numbers: slots" (syntax, formats, signed changes, "|dir", nulls in words, name the
  measure and the row); charts and the warm-up footnote are code's (billed blue, budget grey — D-P6-8 replaces the
  13 category colours). `number-validation` (1,124 tokens): the Validator binds each number to one field; new rule 4
  "say what it is and whose it is"; rule 6 (was 5) a direction word may carry the sign ("down 15.8 %" for −15.76)
  and must agree with it; rules otherwise kept (the two rounding examples, recomputed by `Tools_check.py`).
  Checks: `Tools_check.py` 8 / 8 ✅ (83 s; pending only "owner review of 2 skills"), `Weekly_pack_check.py` 6 / 7 ✅
  (the first-draft prompt grew to 17,002 characters with the table; the patch stays 3,203 = 19 %).
  **Next:** the owner's review of the two skills → S6 (real models, `PACK_REAL_MODELS=1`).
- 2026-10-19 — **S5 done: both skills approved by the owner as written** (`reviewed_by_owner: 2026-10-19`);
  `Tools_check.py` 8 / 8 ✅, pending none. **Next: S6** — real models on weeks 5 / 10 / 23 / 49 with the new Writer
  (`PACK_REAL_MODELS=1 uv run python tools/run.py pipelines/scripts/agents/Weekly_pack_check.py`; ≈ 20 fresh
  flash-lite calls, cached after), the reviewed snapshot of Phase 5 renewed, Deck_check Phase 5.
- 2026-10-19 — **S6: real models (weeks 5 / 10 / 23 / 49).** Docker Desktop was not running (first attempt: pool
  timeout in Phase 1, no model call) → started by the assistant; the containers came back by themselves. **Run 1**
  (new prompts): 1 / 4 published (week 49, 0 rewrites); weeks 5 / 10 / 23 `validation_failed` after two patches;
  max 12.4K tokens per call (17.0K before Phase 6). Reviewed: week 5 — a row named by position
  (`{kpi.overdue[1]:…}`) and "SDR" written again after the slot; week 10 — the week's `amount_at_stake_sdr` put on
  one invoice; week 23 — **a false alarm** ("a DSO window billed amount": `dso_window_billed_sdr` counted only as
  DSO) next to a real "91 days days". The patches failed because the messages did not say what to write.
  **Validator changes (each now a Deck_check Phase 4 case, with the fixed text that passes):** a field belongs to
  every family its name holds (`field_families`); a missing row's message gives the slot by key; a total on one row
  says so and gives that row's own fields; a unit written again after a slot is a V2 problem (new catch). **Run 2**
  (first drafts from cache, patches fresh): **3 / 4 published** (weeks 5 / 23 / 49 after 2 / 1 / 1 patches, each
  `deck.pptx` read back by the publisher), week 10 `validation_failed` on a real Writer error — a NileGate figure
  (collected) on the context slide 9, slotted from an Insight result without that field (the message names
  `kpi.weekly`, which slide 9 may not cite, so two patches could not fix it); 0 fallbacks, every call within its
  TPM, max 12.4K tokens. `Weekly_pack_check.py` **7 / 7 ✅** (Phase 5 re-snapshotted; a re-run from cache: 0 calls,
  0 files changed). `Deck_check.py` **4 / 4 ✅** (its §5c Phase 5 "real models" = `Weekly_pack_check` Phase 5,
  not run twice — D-P6-16). Open for the owner (P6-8: a miss goes to the owner): week 10.
  **Owner: "fix the message and re-run".** Slide 9 now says what the fix is (a NileGate figure or result there → V5
  "slide 9 is external context only … drop it"). **Run 3** (the prompt also got "a slot writes its own unit", owner's
  choice after "SDR" was written twice in weeks 5 and 10): 1 / 4 — three **Validator false alarms** on right
  sentences (the after-window "budget" of the next slot outvoted "Billed" before the first; a row named after its
  number matched to the row named earlier). Fixed: the measure counts if named before the number, in the last noun
  phrase before it, or right after it; a row is looked for in the number's own clause first. **Run 4: 4 / 4
  published.** Looked at as PNG: "up up 25.8 %" (a direction word before a |dir slot) and slide 1's title copied from
  the deck title, so an approved deck said "Draft for approval" → V2 / V3 rules + one prompt line ("no direction word
  right before a |dir slot"); `deck-style-guide` trimmed to 1,200 tokens. **Run 5: 3 / 4** (weeks 5 / 10 / 49
  published, two patches each; week 23 `validation_failed` on a real Writer error, "{kpi.weekly:dso_days|d} days",
  that two patches did not fix). **Owner: keep 3 / 4 and close Phase 6** (runs 2 / 4 / 5: 3 / 4 / 3 published — model
  variance; every failure since run 3 a true positive). Snapshot = run 5; the published real decks are in
  `Notebooks/_scratch/deck_real_2025-W05 / W10 / W49.pptx`. Every finding of runs 1–5 is a Deck_check Phase 4 case
  (the recorded text refused with the expected rule and message, the fixed text passing). Checks: Weekly_pack_check
  7 / 7 ✅ (cached: 0 calls), Deck_check 4 / 4 ✅ (100 / 100 planted, 0 false alarms on 52 weeks), Tools_check 8 / 8 ✅.
  **For Phase 7 (Writer quality, seen in the run-5 decks, not errors):** "up +18.64 %" (a direction word before a
  signed slot: redundant, agreeing), a context bullet emptied of its numbers by a patch ("Daily Suez transits
  averaged across the reporting period"), adjectives in titles ("Surged"). **Next: S7** — close Phase 6.
- 2026-10-19 — **Phase 6 CLOSED.** Done-when of §5 met: the Validator catches every planted wrong number in a test
  deck (`Deck_check.py` Phase 3: 100 / 100, in drafts and in the PPTX file; 0 false alarms on 52 clean decks). ADR-051
  written; ARCHITECTURE (§1, §2 new row `pipelines/agents/deck/`, the `weekly_pack` row, §7, §9), ROADMAP,
  `pipelines/README.md`, checkpoint narratives (`Deck_check.md` new, `Weekly_pack_check.md` Phase 6 update). Scratch
  files of the task (`Notebooks/_scratch/`: previews, the real decks, run logs, `weekly_pack_real.json`) stay until the
  owner looks at them and empties the folder. Commit: the owner.
- 2026-10-19 — **Phase 7 started: design PROPOSED (§5d).** The owner reviewed §8a (G1–G6, each the recommended
  option) and answered P7-1…P7-4 (a small finance Q&A agent; the budget miss through twin views, migration 017;
  `InMemorySaver` for eval runs; a temp folder per eval run). **§5d APPROVED by the owner (2026-10-19, as written).**
- 2026-10-19 — **S1 done (pending the owner's review of the findings).** ADR-052 written (G6: two runs each, hard
  gates, primaries −0.03 margin, ties → simpler / cheaper). `pipelines/scripts/agents/Golden_weeks.py` ✅ 3 / 3
  (17 s): 11 golden weeks by rule, frozen in `golden_weeks.json` (sha256 `ea13800db38c1a96…`) — test 10 / 23 / 36 /
  49; live 5 (warm-up), 48 (peak), 41 (quiet, −0.33 %), 16 (trough), 47 (live budget miss −47.01 %), 15 (real
  duplicate INV-0000925), 24 (Suez transits +17.08 % WoW); 7 unseen. Expected evidence complete for the 7 live weeks;
  test weeks pending migration 017 (draft in `Notebooks/_scratch/golden_weeks_expected_draft.json`). PortWatch 2025
  cached (one cache file changed, later runs 0 calls). Expected findings DRAFT `golden_findings.json` (34 findings;
  where = code table / Writer narrative). Checkpoint `Golden_weeks.md`. **Owner (2026-10-19): findings approved as
  drafted; drivers = the top driver must be named, 2nd / 3rd optional.** Frozen v1 sha256 `4ee0f808db12c25e…` (v2 at
  S2 adds only the test weeks' driver findings). **Next: S2** — migration 017 (twin views `finance_test.kpi_weekly` /
  `kpi_weekly_category`; the owner applies), `finance_kpi` / `kpi_evidence` test switch, `Tools_check` case, then
  re-run `Golden_weeks.py` (expected evidence frozen for all 11 weeks).
- 2026-10-19 — **S2 in progress.** `db/migrations/017_finance_test_kpi.sql` written (twins `finance_test.kpi_weekly` /
  `kpi_weekly_category`: billed / budget from the copy, receivables and the WoW base from the live views) +
  `verify_readonly.sql` §21. Read-only probe of the view bodies (SELECT only, no DDL): 52 / 4 rows, the live columns
  equal, clean week 49 = live exactly, billed test − live = −23,600.00 / +598,696.79 / −64,363.84 (weeks 10 / 23 / 36:
  the planted errors), one budget row changed. **D-P7-1 (finding, owner decision):** the planted budget miss is not a
  miss — the generator raised the budget of the week's **top** category (LNG, live +106.44 % above budget) by × 1.5,
  so LNG stays above budget (+37.63 %). Owner: drop it from the planted findings (copy and generator unchanged);
  D7 planted = the 5 invoice errors (5 / 5); `golden_findings.json` v1.1 (t36-b = "LNG must not be called a miss");
  ADR-052 gate amended (5 / 5); the real budget miss is covered by live week 47 (−47.01 %). Next: the owner applies
  017 → snapshot + audit (assistant) → `finance_kpi` test switch.
- 2026-10-19 — **S2 done.** Owner: "apply 017 yourself, then snapshot + audit and continue S2"; later "I'm going
  to sleep, continue" → autonomous mode (recommended options, each decision logged as D-P7-n for review). Migration
  017 applied by the assistant (BEGIN … COMMIT, no error); `schema_snapshot.sql` refreshed; `verify_readonly.sql` §21
  = expected (52 | 4 | 0 | 0 | 1 | −23,600.00 | 598,696.79 | −64,363.84; f | f | t | t), 0 errors
  (`db/audit/2026-10-19_after_017_report.txt`); `ANALYZE` re-run. `finance_kpi(user, source=…)` reads the twins
  for `weekly` / `category` when the run context says test (the wrapper passes `dataset_of(runtime)`; customers /
  overdue / trend stay live with a note; test needs `finance_test.*` too); `weekly_pack.kpi_evidence(user, week,
  dataset)` and the KPI node pass the run's dataset. **D-P7-2:** `slots.ROW_KEYS_BY_VIEW` gained the two twins (the
  sample Writer found no row key for `finance_test.kpi_weekly_category` — caught by Weekly_pack_check Phase 6).
  Checks: `Tools_check.py` **9 / 9 ✅** (new Phase 3b: the twins = an independent Decimal recompute from the copy,
  56 rows; week 5 in test → no_data; customers live; wrapper source from the run context; Operations employee
  denied), `Weekly_pack_check.py` **7 / 7 ✅** (`PACK_REAL_MODELS=1`, cached: 0 calls; Phase 6 contract now also
  asserts the KPI sources per dataset). `Golden_weeks.py` ✅ 3 / 3: `golden_weeks_expected.json` frozen (11 / 11
  weeks, 254 KB, sha256 `bb3b1a3bd8cf178c…`). Findings **v2** (`golden_findings.json`, 38 findings, sha256
  `3a5bde86b7a8d0df…`): top drivers of the test weeks t10-d Petroleum Product Tankers, t23-d Crude Oil Tankers,
  t36-d LNG, t49-b LNG (owner to review). Note: test week 10 is a warm-up week (weeks 1–13). `docs/rbac_mapping.md`
  lists the twins. **Next: S3** (Q&A golden set).
- 2026-10-19 — **Owner, before sleeping (AskUserQuestion):** keep-awake requested (granted); **S6 real models may
  run tonight up to the free daily limit** (replies cached, a run resumes where it stopped; OpenRouter fallback
  counted). Everything else autonomous: recommended options, each decision D-P7-n here; the owner reviews in the
  morning (the Q&A golden set and the `finance-qa` skill are frozen as v1 "assistant-reviewed, owner review
  pending").
- 2026-10-19 — **S3 done** (owner review pending). `pipelines/scripts/agents/Qa_golden.py` ✅ 4 / 4 →
  `finance_qa_golden.jsonl` (40 items: 30 EN — 22 answerable + the CEO control, 4 abstention, 3 refused — and 10
  Egyptian Arabic twins; sha256 `d7d1e94f449c137d…`). **D-P7-3:** askers by rule (lowest employee_id per profile:
  Finance employee 13, Operations employee 12, Operations manager 2, CEO 1). **D-P7-4:** the RBAC set = 2 Operations
  employee refusals + the Operations manager asking for the HbR level-3 revenue (status `not_permitted` or
  `not_in_data` accepted: the document filter hides it, so "not in the documents" is also right; must not leak the
  level-3 facts) + the CEO control (answered, €940.4 million) — the plan's "a Finance employee" variant dropped to
  keep 30. **D-P7-5:** element kinds `value` (slot binding) / `name` / `direction` / `fact`; G2 threshold AR ≥ EN −
  0.10. Checkpoint `Qa_golden.md`. **Next: S4** (finance Q&A agent).
- 2026-10-19 — **S4 done** (skill review pending). `pipelines/agents/graphs/finance_qa.py`: `qa_llm` ⇄ `qa_tools`
  (`ToolNode(STAGE1_TOOLS)`, ≤ 3 tool rounds) → `qa_answer` (`QaAnswer`: status answered / not_in_data /
  not_permitted, text with slots, evidence ids) → `qa_check` (`check_answer`: unknown ids, slot errors, a NileGate
  number typed as a literal, a refusal holding a number, "answered" when every structured tool refused, a direction
  word against its sign) → one patch → `validation_failed`. `models.QaAnswer`; `slots.DIR_WORDS` + `lang` (Arabic
  `|dir`: ارتفع / انخفض / بدون تغيير; English default unchanged); skill `finance-qa` (`reviewed_by_owner: no`).
  **D-P7-6:** the agent is a LangGraph graph on the `tools` role through `roles.py` (cache, quota, fallback), not
  LangChain's `create_agent` (it would bypass `llm.py`); it reuses the pack's evidence-id / search-cap helpers.
  **D-P7-7:** the fake-model check of S4 lives in `Stage1_eval.py` Phase 4 (no separate script). `Tools_check.py`
  Phase 8 → 7 skills (QaAnswer fields + slot formats are known names); **10 / 10 ✅**, pending: the owner's review of
  `finance-qa`.
- 2026-10-19 — **S5 done.** `pipelines/scripts/agents/Stage1_eval.py` ✅ 5 / 5 (22 s, 0 model calls): Phase 1 the
  four frozen inputs (hash prefixes asserted); Phase 2 the scorers on hand-made decks / answers — each catches its
  failure (tampered evidence, an invoice wrongly called a duplicate in clean week 49, LNG wrongly called below budget
  in week 36, a direction word against its sign, a non-driver called a driver, an untraced number, a strong word on
  the flat week 41, a value from the wrong week, a refusal with a number, a level-3 leak, an answer instead of an
  abstention); Phase 3 the 11 golden weeks with fake models: 11 / 11 published, deck numbers 100 %, planted 5 / 5 in
  the slide-8 table, false alarms 0, claims 100 %, traceability 100 % (sample-draft narrative recall 0.97); Phase 4
  the Q&A graph with fake answers on 38 questions: completeness EN / AR 1.0, abstention 1.0, leakage 0 (r03 / r04
  need live retrieval: Phase 5). **D-P7-8:** a false alarm is an invoice named next to an error word (not any
  invoice: the overdue list names invoices too) or a named category called below budget with variance ≥ 0; planted =
  the 5 invoice errors in the published deck's slide-8 table (read from the PPTX); ADR-052 repeat k uses its own cache
  folder `llm_cache/eval_r<k>/` (a fresh set of calls), the quota state shared. **Next: S6** (real models).
- 2026-10-19/20 — **S6 baseline (real models, two runs, 2,509 s, ≈ 380 fresh calls, ≈ 1.93 M tokens, 0 fallbacks,
  one transient Gemini 503 retried): D7 NOT MET.** `stage1_eval_2026-10-19.json`. Run 1 / run 2: packs published
  4 / 11 and 8 / 11; planted found 2 / 5 and 1 / 5 (a planted error is found only when its test week publishes);
  narrative recall 0.41 / 0.76 (seen 0.50 / 0.50, unseen 0.29 / 0.86); false alarms 0; claims 100 %; deck
  numbers 100 % on every published deck; traceability 1.0 / 0.99; Q&A completeness EN 0.91 / 0.96, AR 1.0 / 1.0
  (G2 met); abstention recall 1.0 / 0.86; RBAC leakage 0. Gates failed: planted 5 / 5 (both runs), traceability and
  abstention (run 2). **Diagnosis** (failed packs replayed from the caches, 0 calls): real Writer errors the
  Validator caught (an evidence id `audit.week:invoice_audit`; "SDR" after a slot; categories outside the top three
  called drivers; the audit total put on one invoice; a NileGate figure on slide 9; context numbers typed on slide 9)
  **and Validator false alarms in 3 weeks of run 1** (test 49, live 48, live 24): "week 48" in a trend sentence
  read as a typed number, "week 48" not seen as naming row 2025-W48, and "{W48} in week 48 to {W49} in week 49" bound
  to the nearer name. Q&A: slots tried on document passages (r03 / r04) and `[row]` on a one-row result (q12).
  Scorer note for the owner: q14's relevance is 0 although the answer names the category and week ("Crude Oil Tankers
  drove …"), because its metric words are "categor" / "vessel" — kept (frozen), reported.
- 2026-10-20 — **D-P7-9 (Validator false alarms fixed, the Phase 6 way):** an integer 1–52 right after "week" is a
  week label; "week N" names the trend row 2025-WNN; a row named right after its number ("{…} in week 49", "{…} on
  2025-03-09") is its row. `Deck_check.py` Phase 4 gains the three recorded sentences (pass) + a swapped week and a
  bare number (still fail); **4 / 4 ✅** (52 clean decks, 100 / 100 planted). **D-P7-10 (Q&A prompt):** a one-row
  result takes no `[row]`; document figures are quoted as text with the document, never a slot (the example uses a
  placeholder — a first draft quoted the r04 answer itself, removed before any run). **ADR-052 reading for a
  failing baseline (D-P7-10, owner review):** "no hard gate regresses" (a gate the baseline already fails may stay
  failed or improve) — the literal "every gate passes" would block every improvement while the baseline fails one.
  Candidate **c1** = D-P7-9 + D-P7-10, two runs on fresh caches (`llm_cache/eval_c1_r1/`, `eval_c1_r2/`), compared
  with the baseline by `Stage1_eval.py` (`EVAL_TAG=c1`, `EVAL_BASELINE`).
- 2026-10-20 — **c1, first attempt: invalid (no result).** **D-P7-11 finding: `gemini-3.5-flash-lite`'s free tier
  allows 500 requests a day** (Gemini's 429 names it: `generate_content_free_tier_requests, limit: 500`; ADR-045 had
  it as "not published"). The baseline (≈ 380 calls) + c1's first weeks exhausted it at 03:09 UTC (06:09 Cairo); the
  rest of c1 run 1 went to the OpenRouter fallback (49 / 50 requests that day) — slow (up to 2,572 s a pack) and a
  mix of models, so the run is not comparable; `tools/run.py` stopped it at its 2-hour timeout. **Consequences:**
  one full evaluation (two runs ≈ 400 calls) per provider day; the harness now **stops a run when a main model's daily
  quota is gone** (an item finished after that is dropped; a re-run the next provider day resumes from the caches
  with the main model — the fallback's cached replies are never used while the main model answers). Quota resets at
  07:00 UTC (10:00 Cairo). Next: c1 again after the reset, `--timeout 14400`.
- 2026-10-20 — **c1 done (2,272 s, 0 fallbacks): ADR-052 verdict "keep (better)"** — `stage1_eval_2026-10-20_c1.json`
  (= the new baseline). No gate regressed; **planted 5 / 5 in both runs** (the gate now passes); narrative recall
  0.69 (+0.10; run 1 0.90, run 2 0.48 — seen weeks 1.0 / 1.0, unseen 0.86 / 0.29); Q&A EN 0.96 (+0.02), AR 1.0;
  packs 10 / 11 and 6 / 11; false alarms 0; claims 100 %; leakage 0. **D7 still NOT MET:** abstention 0.86 in both
  runs (r03: the Operations manager's HbR question answered "answered" with level-1 context and no level-3 fact — no
  leak, a wrong status) and traceability 0.996 in run 1 (one slot not in its bullet's evidence ids). Replay of c1's
  failed packs (0 calls): Writer errors (the audit total put on one invoice; categories outside the top three called
  drivers; "days" after a slot; an unknown field `transits`) and **two Validator false alarms on slide 9: "on
  November 24" read as a typed number** (dates written with a month name). Scorer notes for the owner (frozen set,
  kept): q14 and q01_ar relevance 0 on right answers (metric words too narrow: "categor" / "vessel"; "فوتر" misses
  "فوتناه" / "فاتورة"); r04's fact pattern wants "940.4 million" and misses the right "940,355 thousand".
  **D-P7-12 (candidate c2, prepared, not run — today's flash-lite quota ≈ 140 left < one evaluation):** the
  Validator reads a day written with an exact month name as a date (Deck_check Phase 4: two right sentences pass, a
  typed count and "market 12" still fail; 4 / 4 ✅); the Q&A checker counts a passage's title as quoted text; the
  answer prompt says "answered only if the evidence holds what was asked, else not_in_data". With these, the cached
  Phase 6 run 5 now publishes 4 / 4 (`Weekly_pack_check` Phase 5 snapshot updated; 7 / 7 ✅, 0 calls). Run c2 on the
  next provider day: `EVAL_TAG=c2`, `EVAL_BASELINE=stage1_eval_2026-10-20_c1.json`.
- 2026-10-20 — **Phase 7 CLOSED (owner: "close Phase 7 and keep C2 for later").** Done-when of §5: "the D7
  thresholds are met (or the owner decides)" → the owner decided, with D7 not met (c1: abstention 0.86, traceability
  0.996 in one run, publish rate 10 / 11 and 6 / 11; every other gate passed). ADR-053 written, ADR-052 first use
  recorded; ARCHITECTURE (components, `finance_test` twins, §7 Q&A interface, §9 ADR-052 / 053), ROADMAP,
  `pipelines/README.md`, `db/README.md`, `docs/rbac_mapping.md`, checkpoint narratives (`Golden_weeks.md`,
  `Qa_golden.md`, `Stage1_eval.md`). Checks at close: Tools_check 10 / 10, Weekly_pack_check 7 / 7 (cached),
  Deck_check 4 / 4, Golden_weeks 3 / 3, Qa_golden 4 / 4, Stage1_eval Phases 1–4 ✅ (0 calls). Scratch kept for the
  owner's look: `Notebooks/_scratch/stage1_eval/` (the published eval decks), `deck_real_2025-W*.pptx`, run logs.
  Commit: the owner.
- 2026-10-21 — **Carry: c2 run (owner: "we were to continue C2 too").** Started automatically after the 07:00 UTC
  quota reset (Docker restarted first), two runs, 0 fallbacks: `stage1_eval_2026-10-21_c2.json`. **ADR-052: reject**
  — `planted_5_of_5` regressed (1 / 5 in both runs: test weeks 10 and 23 did not publish). Primaries: narrative
  recall 0.71 (+0.02), Q&A EN 0.93 (−0.02, within the margin), AR 1.0. **What c2 fixed:** abstention 0.86 → **1.0**
  in both runs (the "not_in_data" status line); the month-name date false alarms gone (live 48 / 47 published in
  run 1). **Why the test weeks failed** (replayed from the caches, 0 calls): real Writer errors (`|k` on `n_total`
  and on `dso_days`) and two borderline Validator refusals — "ranged between {03-03} and {03-04} … during the week of
  2025-03-03 to 2025-03-09" (the second slot bound to the range's first date) and "a duplicate charge with an amount
  of {billed_sdr}" ("amount" is not in the billed family). Q&A: q22 `[0]` on a one-row result again, q20 "days days"
  and a typed number. **c1 stays the baseline.** Open for a later candidate (owner's call): keep c2's Q&A lines (they
  fixed abstention) and teach the Validator a date range and "amount" for one invoice's billed field; the publish
  rate varies run to run (model variance), so the planted gate needs every test week to publish.
- 2026-10-21 — **Owner: "c3 tomorrow" (AskUserQuestion: keep c2's code as a candidate under test, add the two
  Validator fixes, run on the next provider day; the alternatives were reverting to c1 or keeping c2 as an
  exception).** **D-P7-13 (c3 = c2 + two Validator fixes):** a period ("the week of 2025-03-03 to 2025-03-09")
  names no row; "amount" / "charge" names `billed_sdr` on an `invoice_audit` row only. `Deck_check.py` Phase 4 gains
  the two recorded sentences (pass) + a row swapped outside a period and "amount" for a week's billed total (still
  fail); **4 / 4 ✅** (52 clean decks, 100 / 100 planted). `Weekly_pack_check.py` **7 / 7 ✅** (cached real phase, 0
  calls). Until c3's verdict the code holds a candidate under test, not a kept change. Run on 2026-10-22 after
  07:00 UTC (10:00 Cairo), Docker running:
  `$env:EVAL_REAL_MODELS='1'; $env:EVAL_REPEATS='2'; $env:EVAL_TAG='c3'; $env:EVAL_BASELINE='stage1_eval_2026-10-20_c1.json'; uv run python tools/run.py pipelines/scripts/agents/Stage1_eval.py --timeout 14400`.
  If ADR-052 rejects c3 too, the owner chooses: revert to c1's code, or accept the variance and stop tuning here.
- 2026-10-21 — **Owner: "handle every problem with a clear impact; start Phase 8 in a new session if it does not
  wait on Phase 7's results".** Phase 8 does not wait on c3 → started in its own session `agents-phase-8` (same
  folder) with constraints: no edits to the files under test, fake models, ≤ 20 real calls a day and none on c3's day
  before it finishes, no commit. **D-P7-14 (added to c3; ADR-051 amendment 1):** `slots.normalize_text` fixes the
  slot form before the Validator — a disallowed format → the field's default (money `M`), a key on a one-row result
  dropped, a unit / direction word written twice dropped; numbers untouched, meaning errors left to the Validator;
  wired into the pack Writer (`weekly_pack.normalize_draft`, state `normalized`) and the Q&A answer
  (`finance_qa`, state `normalized`). These were the recurring causes of unpublished packs (c2's test weeks 10 / 23)
  and of Q&A `validation_failed` (q12, q22, q20). Checks: Deck_check **4 / 4 ✅** (7 normalize cases: 5 recorded
  sentences pass, an unknown field and another row still fail; the 52 clean drafts unchanged), Weekly_pack_check
  **7 / 7 ✅** (cached real weeks now one patch instead of two; 4 fresh calls once, then 0), Stage1_eval 1–4 ✅.
  **c3 = c2 + D-P7-13 + D-P7-14**, run 2026-10-22 (command above). Not handled (no clear impact on the system):
  the frozen golden set's narrow relevance words and r04's fact pattern (measurement only; changing them after the
  runs would shape the score — owner note kept).
- 2026-10-22 — **c3 run (owner: "continue"; Docker started by the assistant, quota fresh): ADR-052 reject by the
  margin only** — `stage1_eval_2026-10-22_c3.json`. No gate regressed; packs 10 / 11 in **both** runs; planted 5 / 5
  both; narrative recall **0.88** (+0.19; seen 1.0 / 1.0, unseen 0.86 / 0.86); abstention 1.0 both; false alarms 0;
  claims 100 %; leakage 0; Q&A EN 0.96 (=), **AR 0.95 (−0.05 > 0.03)**. The AR drop is one item (q20_ar, run 1) refused
  by the Q&A checker for the digits in a vessel's name ("Liquefied Voyager 165"); the same checker refused "page 82"
  (r04) and "first 5000 tons" (q22). **D7 missed only traceability in run 1 (0.9954: one slot not listed in its
  bullet's evidence ids).** **D-P7-15 (c4 = c3 + two form fixes, "clear impact" per the owner):** the Q&A checker
  allows a number that appears inside a tool's own text values (names, band labels, citations — as the deck
  Validator already blanks them); `normalize_draft` adds a slot's evidence id to its bullet's `evidence_ids` when the
  Writer left it out. Stage1_eval Phase 2 gains a checker case (a vessel name passes, a typed amount is still
  refused); checks: Stage1_eval 1–4 ✅, Deck_check 4 / 4 ✅, Weekly_pack_check 7 / 7 ✅ (cached, 0 calls). Run c4 on
  2026-10-23 after 07:00 UTC: `EVAL_TAG='c4'`, same command, baseline c1.
- 2026-10-22 — **Owner (AskUserQuestion on a stopping rule): "accept c3 now and stop".** c3 accepted by an owner
  exception to ADR-052 (recorded there) → **baseline = `stage1_eval_2026-10-22_c3.json`**; c4 is not run; tuning
  stopped. D-P7-15 stays in the code (deterministic checks only; the next real evaluation measures it). Final Phase 7
  numbers (c3): packs 10 / 11 in both runs, planted 5 / 5, narrative recall 0.88, Q&A EN 0.96 / AR 0.95, abstention
  1.0, false alarms 0, claims 100 %, leakage 0; D7 not met by one slot (traceability 0.9954 in one run). The Phase 8
  session was told its quota constraint is lifted.
- 2026-10-20 — **Phase 8 design §5e PROPOSED → APPROVED** (P8-1…P8-4 all recommended, then "approve as written").
- 2026-10-20 — **Phase 8 S1 done.** `pipelines/agents/scheduling.py` (week picker `plan`, `describe` / `describe_all`,
  `prune` = archive then `delete_thread`, `approval_report` + `report_entries` (G5), `toast`, `fire` = one scheduled
  firing, `allowed_run_as`); `Weekly_pack.py` gets `scheduled [--as]`, `prune [--dry-run]`, `report` (exit codes
  0 / 1 / 2 / 3, log `reports/_log/scheduled.jsonl`, archive `reports/_log/threads_archive.jsonl`); `list` now over
  `scheduling.thread_ids` (same output). `Scheduler_check.py` **4 / 4 ✅** at the first run (28 s, 0 LLM calls,
  0 files changed); narrative `pipelines/checkpoints/agents/Scheduler_check.md`. Live G5 today: 1 pack decided (W10),
  edit rate 0.0. **Deviations (design points the section did not fix):** D-P8-1 a thread stopped mid-run (an
  exception such as a quota, ADR-050 (6)) is **resumed** by the next firing before anything new (after "wait");
  D-P8-2 a **rejected** pack counts as an attempt that ended without a deck (retried once, then the week skipped);
  D-P8-3 the firing **waits for PostgreSQL itself** (`probe`: every 60 s for up to 30 min, both logins) — Task
  Scheduler's restart-on-failure is not reliable for an action's non-zero exit code (it targets a task that fails
  to start), and Docker Desktop starts after logon; the task's own restart settings stay as a second line; D-P8-4 a **lock file**
  (`reports/_log/scheduled.lock`, stale after 2 h) besides the task's "do not start a new instance". The toast is
  not exercised by the check (no pop-up during checks); S3's real firing shows it.
- 2026-10-21 — **S1 re-verified** (`Scheduler_check.py` 4 / 4 ✅, 0 calls) and **owner decisions for S2 / S3 while
  c3 is under test** (AskUserQuestion, all the recommended option): (a) `EVAL_TRACE` in `Stage1_eval.py` and the Q&A
  entry point are **deferred until c3 is judged** (both files are code under test); (b) build S2 now, the owner adds
  the key later; (c) **S3's real firing on 2026-10-22 after c3 finishes** (≈ 400 + 6 < 500 flash-lite requests;
  registering the task can happen any time: it first fires by itself on Monday 2026-10-26 10:30).
- 2026-10-21 — **S2 built, read-back pending the key.** `pipelines/agents/tracing.py` (`trace(thread_id, entry,
  run_as, trigger)` = `langsmith.tracing_context(enabled=True, project_name="nilegate-agents", tags, metadata)` only
  when a key exists; `labels` from the thread id; `global_switch`; final flush with errors swallowed);
  `Weekly_pack.py` `run` / `resume` wrapped (prints "LangSmith: traced … / off") and `scheduled` passes
  `tracer=` to `scheduling.fire` (new argument, None = untraced; the log record gets `traced`);
  `common.SECRET_KEYS` + `LANGSMITH_API_KEY` (the old name kept: the library reads both); `.env.example`:
  `PACK_RUN_AS`, `LANGSMITH_API_KEY`, `LANGSMITH_ENDPOINT` and a warning never to set `LANGSMITH_TRACING`.
  `Scheduler_check.py` gains Phase 4 (tracing contract in a child process, fake key, refused local endpoint — no
  network) and Phase 5 (read-back with `langsmith.Client`, only with a key): **5 / 6 ✅, Phase 5 pending** (75 s,
  0 LLM calls, 0 files changed). **Deviations:** D-P8-5 tracing is a **context around each graph run, never an
  environment switch** (`LANGSMITH_TRACING` unset) — `Stage1_eval.py` and the checks stay untraced without an edit,
  which replaces §5e's `EVAL_TRACE` until c3 is judged; D-P8-6 the trace labels go through the tracing context, **not
  the graph config**, so the checkpoint metadata stays the run identity alone (Phase 5 asserts it); D-P8-7 a
  LangSmith outage costs ≈ 45 s of flush at the end of a run (measured: 47 s with the refused endpoint), never the
  run. Not exercised yet: `run` / `resume` traced for real (S3 shows them).
- 2026-10-21 — **S2 done.** The owner set `LANGSMITH_API_KEY` (free developer plan, US) and `PACK_RUN_AS=6` (Anna
  Baldwin, Finance manager; 7 = the other one) in `.env`. `Scheduler_check.py` Phase 5: one fake-model scheduled
  firing traced and read back from `nilegate-agents` (root run + 14 runs, 5 tags, metadata) → **6 / 6 ✅** (91 s,
  0 LLM calls, 0 files changed). **D-P8-8:** the first read-back showed `trigger: scheduled` instead of the tracer's
  value — the graph config's metadata (the checkpoint's, set by `scheduling.fire`) wins over the tracing context's
  on a shared key → the tracer's key is **`launched_by`** (cli / task_scheduler / check), never a checkpoint key.
- 2026-10-22 — **S3 done (done-when met).** The c3 freeze ended (owner accepted c3; the Phase 7 session lifted the
  "do not edit" list) and the owner said "كمل إنت للآخر لحد ما تقفل الـ phase" — the assistant carried S3 → S4,
  the recommended option at each point. `ops/scheduler/register_weekly_pack.ps1` written (parse-checked) and **run
  by the assistant** on the owner's go-ahead (**D-P8-9**: §5e had the owner registering it): task "NileGate Weekly
  Finance Pack", Monday 10:30, Interactive / Limited, start when available, restart 2 × 30 min, 1 h, IgnoreNew;
  the start time built as an exact `[datetime]` (`-At "10:30"` alone carried the current seconds); the action =
  `powershell -WindowStyle Hidden -Command` → `uv run … Weekly_pack.py scheduled`, output appended to
  `reports/_log/scheduled_console.log`, `exit $LASTEXITCODE` (the task result = the CLI's exit code). **Three
  firings** by `Start-ScheduledTask`: #1 started W11:1 → Gemini flash-lite 503 "high demand" in `insight_llm`
  (after its one 20 s retry), the fallback OpenRouter nemotron → 404 → exit 1, the thread waits at its checkpoint;
  a tiny Gemini request passed (200); #2 resumed W11:1 → the same 503 → exit 1 (each request failed in one run
  only: nothing cached as failed); #3, 30 min later, **resumed W11:1 and reached the approval** — Validator passed,
  preview `reports/_drafts/weekly_pack_live_2025-W11_1.pptx`, toast shown, exit 0, `traced: true`; retention kept 2
  threads. Traces of the three firings in `nilegate-agents` (`launched_by:task_scheduler`, `week:2025-W11`, the two
  errors in their traces). flash-lite today 384 / 500. **D-P8-10:** the ADR-045 fallback is **broken**: OpenRouter
  lists `nvidia/nemotron-3-super-120b-a12b:free`, but every request (also a 5-token ping) gets NVIDIA's 404
  "Function not found for account" (last success 2026-10-11) → `llm.py` caches it as `model_missing` for that
  request — the pack has no working fallback today (carried: an ADR-045 amendment, measured by ADR-052).
  **D-P8-11:** `EVAL_TRACE=1` added to `Stage1_eval.py` once c3 was judged (`tracing.trace(…, extra_tags=)` for the
  golden key / question id; off by default); **the Q&A has no operator entry point** (only the evaluation and
  `Qa_golden.py` call it), so its tracing waits for the Supervisor (Phase 12). **D-P8-12:** `Scheduler_check.py`
  Phase 5 failed once on `runs_in_trace ≥ 5` (the root run was ingested before its child runs) → it now waits for
  the children too (up to 3 min). **The decision on W11 is left to the owner** (the human approval is the point of
  the phase; the assistant does not approve for him): until he decides, Monday's firing logs "wait".
- 2026-10-22 — **S4 close.** Checks: `Scheduler_check.py` **6 / 6 ✅** (74 s), `Weekly_pack_check.py` 7 / 7
  (`PACK_REAL_MODELS=1`, cached, 0 calls), `Deck_check.py` 4 / 4, `Stage1_eval.py` Phases 1–4 ✅ (0 calls). Docs:
  **ADR-054**, ARCHITECTURE (§2 component, §7 interfaces, §9), ROADMAP, CLAUDE.md, `pipelines/README.md`, the
  checkpoint narrative. **Phase 8 CLOSED.** Carried: the owner's W11 decision → `Weekly_pack.py report` (first live
  G5 numbers from a scheduled pack); the ADR-045 fallback; `langsmith` `list_runs` is deprecated after 2027-01-31
  (`Scheduler_check.py` Phase 5 → `client.runs.query`); the Q&A tracing (Phase 12).
- 2026-10-22 — **W11 decided (owner: "شغل انت كل حاجة بنفسك" — the assistant took the decision on his
  instruction).** Approver = Finance manager **7** (the run identity is 6: a second person approves): `edit` of
  bullet 6 ("…with down 25.5 % WoW change" → "Payments received reached 3.98 M SDR in week 11, down 25.5 % WoW.") →
  Validator passed → `approve` → published `reports/2025-W11/` (deck.pptx + 3 JSON); both CLI steps traced
  (`entry:resume`). **First G5 numbers with a scheduled pack:** 2 packs decided (W10, W11), 2 published, 0 rejected,
  1 edited → **edit rate 0.5**, edited slide 3 once. Seen while deciding: the CLI's approval log prints `reason`,
  empty for these decisions (the `--comment` text is stored as `comment`) — cosmetic, carried. Monday's firing
  (2026-10-26) makes W12.

- 2026-10-22 — **§5f closure started (owner: "close every unclear point, leave no carry, check first, then plan the
  next phase").** Inventory → §5f K1–K9; owner decisions C-1 (reviews one by one in the chat), C-2 (one confirmation
  evaluation 2026-10-23, set frozen after the K1 changes), C-3 (a new free fallback), C-4 (Exceptions page + Notes
  rules now). K9 closed by a probe (Tavily 40 / 1,000; `web_search` ok). **K1 round 1–2 (owner answers):**
  - **D-P7-1 → changed:** the owner wants a **real planted budget miss**: test week 36, LNG budget = its billed × 1.5
    (→ −33.3 %), one row of `finance_test.budget_weekly` by **migration 018**, the generator's rule changed the same
    way (budget from billed, not from budget); then golden evidence re-frozen, findings **v3** (t36-b "LNG must be
    called a miss"), planted gate **6 / 6** with a scorer for the miss (ADR-052 / ADR-053 amended).
  - **D-P7-2 → accepted** (the twins' row keys = the live views').
  - **D-P7-3 → changed:** **two askers per profile** (Finance employee 13 + 24, Operations employee 12 + 17,
    Operations manager 2 + 3; the CEO 1 alone), the questions of a profile alternating between the two by order;
    golden set re-frozen.
  - **D-P7-4 → changed:** **+1 question**: a Finance employee asks the HbR level-3 revenue → `not_permitted` or
    `not_in_data`, no leak (level 3 is above the owner-department rule, ADR-006) → 31 EN + 10 AR.
  - **Round 3:** **D-P7-5 accepted** (element kinds; G2 AR ≥ EN − 0.10). **D-P7-6 → changed:** the owner wants the
    Q&A agent on **LangChain `create_agent`** (+ middleware: call limits, the answer check), its model a chat-model
    adapter over `llm.py` so the cache / quota / fallback rules still hold; `check_answer` and the one patch kept as
    the contract. **D-P7-7 → changed:** a separate **`Finance_qa_check.py`** (fake models: the graph, the checker
    cases, RBAC, the patch, the K6 CLI), next to `Stage1_eval.py` Phase 4. **D-P7-8 accepted** + the budget-miss
    scorer of D-P7-1 (LNG called a miss on the category slide or the summary; proven on hand-made cases in
    `Stage1_eval.py` Phase 2).
  - **Round 4: accepted as written:** D-P7-9 (Validator week labels / rows), D-P7-10 (Q&A prompt lines — carried
    into the `create_agent` version), the **ADR-052 reading for a failing baseline** ("no hard gate regresses"),
    D-P7-11 (500 / day; a run stops when the main model's quota is gone).
  - **Round 5: accepted as written:** D-P7-12, D-P7-13, D-P7-14 (with the promise made in the question: every code
    fix of a slot's form is recorded and shown in the run record / `report`, so model form errors stay visible),
    D-P7-15.
  - **Round 6:** skill **`finance-qa` approved as written** (`reviewed_by_owner: 2026-10-22`); findings **v2
    accepted** → v3 after migration 018 (t36-b "LNG must be called a miss"); the Q&A golden set is re-frozen anyway
    (D-P7-3 / D-P7-4), so **the scorer notes are fixed in the same re-freeze** (by rule, no answer from a run:
    metric synonyms for q14 / q01_ar — category / vessel category, فاتورة / فواتير / فوتناه — and both number forms
    for r04, "940.4 million" / "940,355 thousand"). **K1 closed: 18 / 18 points decided** (13 accepted, 5 changed: D-P7-1, -3, -4, -6, -7).
- 2026-10-22 — **§5f APPROVED ("ابدأ"). F1 done:** K8 `Weekly_pack.py show` prints the approver's comment (a
  refusal's reason first); D-P7-14's promise — the publisher writes `normalized` into `run.json`, the archive keeps
  it, `report` gains `form_fixes` {packs, fixes} (live now: **W11 had 5 slot-form fixes by code**, W10 predates the
  field); K7 decided: `langsmith` 0.14.7's `runs.query` is async-only (`AsyncPaginator`) and wants project ids, so
  `list_runs` stays, the reason pinned in `Scheduler_check.py`'s header (it fails loudly if the call disappears; a
  langsmith upgrade re-checks it). Checks: Scheduler_check 6 / 6, Weekly_pack_check 7 / 7 (cached, 0 calls),
  Deck_check 4 / 4.
- 2026-10-22 — **F2 done (D-P7-6 / D-P7-7 / K6).** `graphs/finance_qa.py` rebuilt on **`create_agent`**:
  `RoleChatModel` (a `BaseChatModel` over `roles.get("tools")`: llm.py cache / quota / fallback on every call; a
  plain-text reply while the answer tool is bound → `roles.structured(QaAnswer)`, the old validated path, returned as
  an answer-tool call), `ToolStrategy(QaAnswer, handle_errors=True)`, middleware `QaTurn` (`wrap_model_call`: the
  answer brief — language, evidence ids, slot rules — on every request, not stored; Stage 1 tools removed after 3
  rounds; `after_model`: `normalize_text` + `check_answer` → one patch by `jump_to` the model, else the final
  status) + `ModelCallLimitMiddleware(run_limit=8)`. `check_answer`, the slot rules, `ask()` and the state the
  harness reads are unchanged. New: **`Finance_qa_check.py` 6 / 6 ✅** (answer paths, brief + tool cap, patch, RBAC
  with the real tools, call limit + records, CLI; one real bug found and fixed — invalid answer arguments are left to
  `ToolStrategy`), narrative `Finance_qa_check.md`; **`Finance_qa.py ask "…" --as E [--lang ar]`** (traced:
  `entry:qa`). `Stage1_eval.py` Phases 1–4 ✅ (38 questions, completeness EN / AR 1.0, 0 calls). Real models (6
  flash-lite calls): week 23 billed answered in 2 calls; an Arabic question answered (wording closer to MSA — F8
  measures it); an Operations employee's receivables → not_permitted. **Note for F8:** the prompt shape changed
  (the brief on every request, the answer as a tool), so the confirmation run makes fresh Q&A calls.
- 2026-10-22 — **F3 done (D-P7-1: a real planted budget miss).** `Finance_generator.py` Phase 8 (R7 amendment 1):
  budget of test week 36's top category = its billed in the copy × 1.5 → **migration 018** (one guarded `UPDATE`:
  LNG 1,316,745.48 → 2,718,323.04 SDR, −33.33 %; the week −25.85 %), `finance_test_budget_v2.csv`,
  `finance_test_answer_key_v2.json`; the 012 files re-verified (0 changed). 018 shown to the owner, **applied by the
  assistant** on his yes; `ANALYZE`; snapshot refreshed; `verify_readonly.sql` new §22 = expected, 0 errors
  (`db/audit/2026-10-22_after_018_report.txt`); `db/README.md`. `Golden_weeks.py`: reads key v2, asserts the miss in
  the evidence, **controlled re-freeze** (`REFREEZE`: the old sha prefix + reason, one transition) —
  `golden_weeks_expected.json` bb3b1a3b… → **7909ccfb…**; a second run 0 changed. **Findings v3** (`dc6e3248…`): t36-b
  = planted `budget_miss` (narrative: LNG named and called below budget / a miss). `Stage1_eval.py`: planted = 5
  table errors + the miss (`PLANTED = 6`, gate `planted_all`; `adr052()` reads the old `planted_5_of_5` of earlier
  results files), the miss kept out of narrative recall; Phase 2 cases (a false miss on SFU, +25.53 %; the planted
  miss found / silent); the fake Writer says "below its budget" when the top driver is under budget → Phase 3 **6 / 6**.
  `Tools_check.py` Phase 3b snapshot −33.33 (was +37.63) → **10 / 10**. Narratives: `Finance_generator.md`,
  `Golden_weeks.md`.
- 2026-10-22 — **F4 done (Q&A golden set v2).** `Qa_golden.py`: two askers per profile by rule (13 / 24, 12 / 17,
  2 / 3, CEO 1), alternating in order; **r03b** (the second Operations manager, else unused) and **r05** (a Finance
  employee asks the HbR level-3 revenue → not_permitted / not_in_data, no leak); scorer notes by rule — category type
  names in the category words, «فاتور» / «فوتنا» in Arabic billing, r04's "940,355 thousand"; **32 EN + 10 AR = 42**;
  re-frozen by a recorded transition `d7d1e94f…` → **`5cf72ac3…`** (second run 0 changed). `Stage1_eval.py`:
  hash + `N_QUESTIONS = 42`, Phase 4 38 questions (the 4 document ones live) → 1–4 ✅. Narrative `Qa_golden.md`.
- 2026-10-22 — **F5 done (K5: the tariff Notes rules).** Read in our own corpus (chunk
  `suez_notes_ballast_combined_carrier_rates`) and checked against `toll_rate_bands` — **D-P8-13 (a finding that
  narrowed K5):** ballast Petroleum Product → Crude Oil ballast rates is **already in the tables** (identical bands);
  ballast "Oil/Chemical Tankers" → Crude Oil ballast rates is not, and our category "Chemical Tankers & Other Liquid
  Bulk Tankers" is wider, so such an invoice may be right → **manual review**; OBO: none of our 13 categories; "actual
  condition upon transit": already priced. **Migration 019** (built from 015 by exact replacements; tested read-only
  first; shown to the owner, applied by the assistant on his yes): hypothesis `notes_crude_ballast_rate`, last column
  `review` (`manual_review` | `error`); snapshot, `verify_readonly.sql` §23, 0 errors, `db/README.md`. `audit.py`:
  `review` in the rows, `totals()` (manual review never flagged nor at stake), `invoices_manual_review`; skill
  `suez-toll-audit` updated (owner approved the wording in the 019 question; tightened to the 1,200-token budget
  that Tools_check caught). `Tools_check.py` Phase 4: the independent Python auditor has the rule; the planted
  invoice through 019's body (crude toll → manual_review; a wrong amount → error; its own toll → no finding); the
  file's output = the applied view's on every column; `totals()`; Phase 8 knows the two new names → **10 / 10**.
  Evidence re-frozen (`REFREEZE`): `7909ccfb…` → **`1f2bad35…`** (rows carry `review`). **D-P8-14:** the audit JSON
  is in the Insight conversation, so `Weekly_pack_check` Phase 5 went to the model again (17 fresh calls, once): 2 / 4
  published, weeks 23 / 49 stopped by V7 on real Writer errors (LNG called a driver outside the top three; a slot on
  another row than the named Cruise Ships) — replayed from the cache, true positives, snapshot updated → **7 / 7**,
  0 calls on a re-run. Deck_check 4 / 4, Stage1_eval 1–4 ✅, Finance_qa_check 6 / 6. flash-lite today 407 / 500.
- 2026-10-22 — **F6 done (K4: the Power BI Exceptions page), data verified; the on-screen look is the owner's.**
  Model through the Modeling MCP on the TMDL folder (`ConnectFolder` → `ExportToTmdlFolder`; the other files kept
  their format): table **`Invoice Audit`** (DirectQuery on `finance.invoice_audit`, 15 columns incl. `review`),
  relationship `Invoice Audit -> Week` (many-to-one, single direction, like the 18 others), 3 thin measures in
  `Weekly KPIs` / folder "5 Exceptions" — `Audit Findings`, `Invoices Flagged` (review = error), `Invoices Manual
  Review` (HASONEVALUE-guarded counts; no "amount at stake" in DAX: its definition — the largest |difference| per
  invoice — lives in SQL / the tool, ADR-047). Page (PBIR, written from the existing visuals' shapes): the synced
  week slicer (copied from Receivables), a card of the 3 measures, the findings table (13 columns, by difference),
  the placeholder text replaced by a note (error vs manual review, the same view as the agents' tool). Opened in
  Power BI Desktop; DAX through the MCP = `invoice_audit` for weeks 10 / 15 / 23 / 49 / 50 (findings 1 / 1 / 0 / 0 /
  1, flagged equal, manual review 0, Σ difference 81,837.02 / 73,950.26 / 0 / 0 / 181,121.72 = the tool's amount at
  stake). The screen check through computer use was declined by the owner → he looks at the page once (it is open).
- 2026-10-22 — **F7 in progress (the new fallback).** Free OpenRouter models with tools + context ≥ 32K: 16.
  Smoke test through `llm.py` (one tool call + one structured object each): `gemma-4-31b-it` / `gemma-4-26b-a4b-it`
  429 upstream (busy); **`dots-3-note-preview` ok / ok**; **`nemotron-3.5-super-vl` ok / ok** (so the old 404 is
  `nemotron-3-super` itself, retired upstream, not NVIDIA). Forced-fallback pack (Insight + Writer on
  `nemotron-3.5-super-vl`, weeks 5 / 10 / 23 / 49): **inconclusive** — week 5 `output_invalid` (two invalid objects:
  a warning in itself), weeks 10 / 23 / 49 never ran (a 502, then the owner's connection dropped: `getaddrinfo
  failed`). OpenRouter 27 / 50 today. Next: retest on a stable connection — both passing candidates, 2 weeks each
  (≈ 24 calls) — and keep the one that publishes (ADR-045 amendment 2).
- 2026-10-23 — **F7 done (new session after the handoff; owner asleep, full autonomy — the recommended option).**
  Retest on a stable connection (weeks 5 / 23, Insight + Writer forced onto the candidate): `dots-3-note-preview`
  **0 / 2** (week 5 an empty DeckDraft → V3 / V4; week 23 two invalid replies → output_invalid);
  `nemotron-3.5-super-vl` **1 / 2** (week 23 passed the Validator after one patch, max 39K tokens; week 5 two empty
  replies, cached from the first run → output_invalid). **D-P8-15: the fallback = `nvidia/nemotron-3.5-super-vl:free`**
  — a partial fallback (1 / 2), better than none: when it fails, the pack waits for the next firing as before
  (D-P8-1). `roles.NEMOTRON` and `Weekly_pack_check` Phase 0's role pairs already carried it (written by a parallel
  session that ran the same retest at the same time and reached the same choice — checked 2026-10-23 00:07, no
  conflicting edit); **ADR-045 amendment 2** written. OpenRouter 44 / 50 on 2026-10-22.
  Check after the change: `Weekly_pack_check.py` **7 / 7 ✅** (Phase 0 = the new role pairs; Phase 5 from the cache,
  0 calls). The second session was stopped by the owner; this session carries F8–F9 alone (owner, 2026-10-23).
- 2026-10-23 — **F8 scheduled (decision, recommended option, owner asleep):** the confirmation evaluation needs
  Gemini's fresh day (midnight Pacific = 07:00 UTC), so a background waiter starts it once at **07:05 UTC**, only
  after any other pipeline script has ended (never two runs on the same quota); it keeps the machine awake only
  while it lives (`SetThreadExecutionState`, no setting changed). Command = the handoff's (`EVAL_TAG='confirm'`,
  2 runs, baseline c3, `--timeout 14400`). F9 docs that do not depend on F8 done meanwhile: ADR-054's stale
  "no fallback" line → amendment 2; ARCHITECTURE (pack row and §8: the new fallback; Power BI: 13 DirectQuery
  views); ROADMAP (§5f status block).
- 2026-10-23 — **F8 started late (deviation):** the app closed the session at ≈ 06:00 local, which stopped the waiter
  and a check batch (Deck_check cut mid-run; the scratchpad with the waiter script was cleared). Restarted by hand
  at **07:33 UTC** (fresh flash-lite day), same command. **F9 checks (no model call), run while F8 runs:**
  Tools_check 10 / 10, Weekly_pack_check 7 / 7 (00:09), Deck_check 4 / 4, Finance_qa_check 6 / 6, Scheduler_check
  6 / 6, Golden_weeks / Qa_golden 0 changed (11 weeks, 42 items) — the only files changed during them were F8's
  own cache (`eval_confirm_r1/`, `usage.json`).
- 2026-10-23 — **F8 done: the confirmation evaluation = the final Stage 1 baseline
  `stage1_eval_2026-10-23_confirm.json`; D7 NOT MET (reported as is, C-2).** 2 runs, 29 min, 290 calls (275 fresh,
  0 fallbacks, 1 failed; flash-lite only). Run 1 / run 2: packs published **7 / 11 · 10 / 11**; deck numbers 100 %
  both; **planted 2 / 6 · 3 / 6**; claims 100 % both; **traceability 100 % both** (c3's one-slot miss gone: D-P7-15's
  evidence-id fix measured); RBAC leakage 0; abstention 1.0; narrative recall 0.66 · 0.93 (mean 0.79, c3 0.88);
  Q&A EN 0.96 · 0.96, AR 1.0 · 0.90 (means = c3's; G2 holds). **Why planted fails:** a test week whose pack the
  Validator stops publishes no deck, so its planted findings count as missed — run 1 test weeks 10 and 36, run 2
  test week 23 (no wrong deck was published: the safety holds, the cost is recall); run 2 test week 36 published
  without calling LNG a miss (t36-b). Same pattern as Phase 7: Writer variance on the free model, caught by the
  Validator. **ADR-052 as printed:** "reject" vs c3 (gates `planted_all`, `false_alarms_le_5pct`; recall −0.086) —
  informative only: F8 is a measurement, not a candidate, and its file is the baseline by the owner's C-2.
- 2026-10-23 — **D-P8-16 (scorer false positive found in F8, fixed by rule; owner asleep, recommended option):** the
  false-alarm rate as scored (0.33 · 0.25) came from exactly two sentences, both **true**: "INV-9000292 … duplicate of
  INV-0000292" (t23-a / t23-c) and "INV-0000925 duplicated INV-0000491" (l15-a / l15-b) — the scorer counted every
  invoice number of an error sentence, so the *original* of a flagged duplicate became an alarm. Hand-checked: **real
  false alarms 0 in both runs**, so the only gate D7 really misses is `planted_all`. Fix in `Stage1_eval.py`
  `false_alarms()`: the original of a flagged duplicate named in the same sentence is not called wrong; Phase 2 gains
  `duplicate_with_original` (0 alarms, 1 finding) and `duplicate_with_other` (an unflagged invoice in the same
  sentence is still 1) → Phases 1–4 ✅, 0 changed. The results file is **not** re-scored (frozen measurement; a
  re-score would need the same tag's caches, i.e. overwriting it); the correction is recorded here and in ADR-053.
- 2026-10-27 — **First missed-Monday firing (W12) + two findings.** The machine was off on Monday 2026-10-26; at
  logon on 10-27 the task started by itself (08:57, "start when available"), waited for PostgreSQL while Docker
  Desktop came up (pool timeouts in the console log, D-P8-3 working), started `weekly_pack:live:2025-W12:1` on real
  models and reached the approval (Validator passed, 8 slot-form fixes by code, toast, traced, exit 0). The
  assistant read the draft: numbers bound (V1–V8), four sentences with wording faults the Validator does not judge —
  "82 days-day window" (a unit doubled with a hyphen: `normalize_text` knows "days days", not "days-day"), "a down
  7.9 % change", "increased by up", "rose by up". **Owner (AskUserQuestion): edit the four sentences, then approve**;
  approver = Finance manager 7 (the run identity is 6).
  - **D-P8-17 (finding): an edit while the approver has the preview open crashes the validator node** —
    `PermissionError` writing `reports/_drafts/<thread>.pptx`, because PowerPoint locks the file that `show` tells the
    approver to open. The thread waits safely at its checkpoint (next = validator, the edit kept) and resumes once
    the file is closed (`Weekly_pack.py scheduled`, D-P8-1). A first resume by a waiter script failed the same way
    (PowerPoint released the file for a moment, then locked it again; that firing is logged in `scheduled.jsonl`).
    **Fixed the same day (owner: "fix D-P8-17 and days-day, then continue W12"):** the preview is named by its
    content (`<thread>_<sha10>.pptx`: an edit writes a new file next to the open one, a resume after a crash finds
    the same name and writes nothing); older previews of the thread are removed when free, a locked one is left and
    removed at the next pass, publish or reject (`_drop_previews`; `approval` became `make_approval(reports_dir)`).
    `Weekly_pack_check.py` Phase 2 gains the case with the preview locked like PowerPoint (Windows share mode 0):
    the edit reaches the approval again with a new preview, the open file untouched; approve after closing →
    published, `_drafts` gone → **7 / 7 ✅** (Phase 5 cached, 0 calls).
  - **D-P8-19 (fixed): "82 days-day window"** — `normalize_text` now drops the unit after a slot also behind a hyphen
    (`\s*-?\s*<unit>`); `Deck_check.py` Phase 4 gains the W12 sentence (1 fix, passes, renders "82 days window") →
    **4 / 4 ✅**. Scheduler_check 6 / 6, Finance_qa_check 6 / 6 (the Q&A uses the same normalize). Stage1_eval
    Phases 1–4 to re-run after the owner's own evaluation run (`EVAL_TAG=mytest`, started before these edits).
  - **W12 published:** `Weekly_pack.py scheduled` resumed the thread from its checkpoint (the four edits through the
    Validator: passed, a new preview), then **approved by Finance manager 7** → `reports/2025-W12/`. G5 now: 4 packs
    decided (W08 = the owner's manual test, rejected), 3 published, 2 edited → edit rate 0.5; form fixes 24 in 3
    packs. Monday 2026-11-02 10:30 makes W13.
- 2026-10-27 — **The owner's own evaluation run (`EVAL_TAG=mytest`, 2 runs, ≈ 280 fresh flash-lite calls; started
  10:22, before the D-P8-17 / D-P8-19 edits, which do not touch what it measures):** `stage1_eval_2026-10-27_mytest.json`.
  Run 1 / run 2: packs 7 / 11 · 8 / 11, planted 2 / 6 · 4 / 6, **false alarms 0 · 0** (the D-P8-16 scorer fix seen
  live: the gate passes now), deck numbers / claims / traceability 100 %, leakage 0, abstention 1.0, recall
  0.66 · 0.79, Q&A EN 0.96 / AR 1.0 · 0.90; D7 not met (planted only, as on 10-23). **D-P8-20 (finding, for the
  owner, nothing changed):** this is the **same code** as the confirm baseline, yet `adr052()` printed "reject"
  (no gate regressed; narrative recall −0.069, mean 0.72 vs 0.79) — run-to-run variance of the free Writer is larger
  than ADR-052's 0.03 margin, so the rule could reject an unchanged setup against itself. To decide before the next
  comparison (e.g. a wider margin, more runs, or recall on a fixed set of published decks). Stage1_eval Phases 1–4
  after it: ✅, 0 files changed.
  - **D-P8-18 (finding, fixed with the owner's yes): the trigger was stored with a UTC offset**
    (`2026-10-22T10:30:00+03:00`), so after Egypt's DST end (2026-10-29/30) the task would fire at 09:30 local =
    07:30 UTC, before the Gemini reset (08:00 UTC after US DST ends) — P8-2's reason for 10:30. `register_weekly_pack.ps1`
    now stores the start without an offset (local wall-clock time, follows DST) and fails if the stored trigger has an
    offset or the next run is not at the asked time; re-registered by the assistant: StartBoundary
    `2026-10-27T10:30:00`, next run 2026-11-02 10:30. ADR-054 amendment 2.

- 2026-10-29 — **Phase 12 S1 plan — the S2 Q&A golden set (PROPOSED, for the owner; no code yet).** §6d gained its
  step order (S1…S6, above). Facts checked read-only for this plan: every Stage 2 input is level 1 / Operations
  (ADR-055 / 057 / 058, `rbac_mapping.md` §2), so "RBAC both ways" means *Operations → finance is refused, Finance →
  operations is answered* (the twin proves no over-refusal); `vessels.customer_id` is a level-1 id while the customer's
  details are level 2 / Finance (`rbac_mapping.md` row `vessels.customer_id`); the finance rows that already carry a
  `vessel_id` are `finance_kpi` `overdue` (and `invoice_audit`), while `customers` carries `customer_id` + `ar_sdr`
  and no tool maps a customer to its vessels today; finance is a 2025 replay (weeks 1–52), operations a 2026-09 replay
  (clock ≤ 2026-09-13T00:00Z); the latest saved watch run is `voyage_watch:20260913T0000Z:1` (`reports/voyage_watch/`).
  - **Script** `pipelines/scripts/agents/Supervisor_golden.py` (percent cells, `tools/run.py`, the `Qa_golden.py`
    pattern). Reads, read-only: PostgreSQL (`PG_RO_USER`) and MongoDB (`nilegate_reader`) through the tool functions
    as the CEO at the pinned clock, the voyage file, `route_cases.json`, the pinned watch run file. Writes
    `Data/processed/agents/eval/supervisor_qa_golden.jsonl` — frozen: a re-run recomputes and stops on any difference;
    a later change only through a recorded `REFREEZE` (old sha prefix + reason). **0 model calls, 0 Open-Meteo calls**
    (weather enters only through the pinned run's alerts), safe to re-run. Narrative
    `pipelines/checkpoints/agents/Supervisor_golden.md`.
  - **Phase 1 — clock and askers.** The clock = 2026-09-13T00:00Z (the data's as-of = the pinned watch run's clock;
    its file sha256 stored in every watch item, so a re-run of that run cannot shift the answers silently). Askers by
    the v2 rule (two lowest ids per profile): Operations employees 12 / 17, Operations managers 2 / 3, Finance
    employees 13 / 24, the CEO 1. Asserted: Operations users pass every Stage 2 resource and fail `FINANCE_VIEWS`;
    Finance users pass both.
  - **Phase 2 — ≈ 20 operations items (EN)**, asked by the Operations employees (the desk's audience), hand-written,
    expected values from the tools by code: voyage status ×4 (`voyage_status`: status, next port, distance left nm),
    ETA ×4 (`voyage_eta`: ETA instant, hours left), route advice ×4 (the `route_advice` graph's **code rows** for a
    frozen route case — cheaper route, Cape − Suez days / SDR, Suez dues — no writer call), watch ×3 (the pinned run's
    alerts: a vessel's wave height / wind, the high alerts, the Suez-ahead vessels), fuel ×2 (`vessel_params` at a
    stated speed), distance ×1 (`sea_route` via the Cape), abstention ×3 (`not_in_data`: a vessel id not in the fleet,
    a real ship's live position — no live AIS, ADR-056 —, a time after the clock). Vessels picked by rule (lowest ids
    at sea at the clock with the needed property: a high alert, Suez ahead, …), each pick printed as a reviewed snapshot.
  - **Phase 3 — ≈ 10 cross-product items (EN)**, asked by the Finance employees (they may read both products →
    `answered`): the finance part names an explicit 2025 week, the operations part is "now" (= the clock) — e.g. "the
    overdue invoices of week 49: where are those vessels now and when do they arrive?", "does the vessel of the
    largest overdue invoice of week 49 have an alert?", plus the customer-based ones the bridge decision allows
    (decision 1 below).
  - **Phase 4 — RBAC twins.** Each cross-product item asked again by an Operations employee → expected
    `partial` (P12-3): the operations elements required, the refused part named (`refused_any`: tool `finance_kpi`
    / `invoice_audit` + EN / AR words such as receivable, overdue, invoice, مستحقات, فواتير), **must-not**: no
    number of the refused part (its SDR values as patterns, Western and Arabic-Indic digits) and no customer name
    when only the level-1 id is allowed; 5 operations items asked again by a Finance employee → `answered` (no
    over-refusal); 1 CEO control (a cross item, answered). A fully refused item (an Operations employee asking a
    finance-only question) stays in the Stage 1 set (r01–r05), not repeated here.
  - **Phase 5 — Egyptian Arabic twins (P12-5, G2):** 10 answerable items (6 operations + 4 cross-product), same
    elements, Arabic relevance words written and frozen before any run; threshold fixed now: AR completeness ≥ EN
    completeness − 0.10 (the Stage 1 rule).
  - **Item format** = the Stage 1 golden items (`id`, `lang`, `asker`, `employee_id`, `question`, `expected_status`,
    `elements` with `value` / `name` / `direction` / `fact`, `relevance`, `must_not_regex`) + `as_of`, `products`
    (`finance` / `operations`), a new status `partial` with `refused_any`, and a `value` element's `tool` may be
    `route_advice` / `voyage_eta` / `watch_alerts` (the S2 tool names), its ids the `route.` / `watch.` slot ids.
  - **Validation cells:** every expected value non-null and from a cited tool result; every picked vessel's property
    re-checked; askers' permissions as above; counts per kind and per status; must-not patterns match the refused
    rows and none of the permitted answer's values (checked on hand sentences); frozen sha; a second run changes 0
    files; LLM and Open-Meteo counters 0. Size ≈ 30 EN + 15 twins + 1 control + 10 AR ≈ **56 items** (one
    evaluation ≈ 56 questions × ≈ 3–4 calls + the route advice's writer ≈ 200 flash-lite requests, inside the 500 / day;
    ADR-052's two runs per side = one provider day per side).
  - **Decisions for the owner (asked as choices, recommended first):** (1) the customer bridge — customer-based cross
    items in, S2 adds a code lookup customer → vessel ids (level 1, the id rule) **vs** only the `vessel_id` links the
    finance rows already carry (overdue / audit); (2) the clock — one pinned clock + explicit 2025 weeks **vs** "this
    week" mapped to the latest finance week; (3) the partial answer — the agent's result carries `status = partial` +
    the refused tools, the text names the refused part, scored on both **vs** text words only; (4) the Arabic twins —
    10 **vs** every answerable item (≈ 25, ≈ +60 requests per run).
  - **Owner answers (2026-10-29), all four as recommended:** (1) customer-based cross items in — S2 adds the code
    lookup customer → vessel ids (level 1); (2) one pinned clock 2026-09-13T00:00Z + explicit 2025 weeks; (3) the
    partial answer scored on the result's `status = partial` + refused tools **and** the text; (4) 10 Arabic twins.
    **S1 plan APPROVED 2026-10-29** by the owner as written with these answers.
- 2026-10-29 — **Phase 12 S1 DONE: the S2 Q&A golden set frozen.** `pipelines/scripts/agents/Supervisor_golden.py`
  Phases 1–5 + Final Checkpoint ✅ (narrative `pipelines/checkpoints/agents/Supervisor_golden.md`):
  `Data/processed/agents/eval/supervisor_qa_golden.jsonl` **57 items** (47 EN + 10 AR; 21 operations, 10
  cross-product, 16 RBAC twins; 44 answered, 10 partial, 3 not_in_data), sha256 `070a745bee233a92…`; a second run
  changed 0 files; 0 model / Open-Meteo calls. Clock 2026-09-13T00:00Z, watch run `voyage_watch:20260913T0000Z:1`
  pinned (sha256 `3164190cbbfa106f…`). Contracts S2 must implement as fixed by the items: `watch_alerts` (args
  `thread`; rows = the run's alerts keyed `alert_id` + one row `alert_id = "fleet"` with the fleet counts and
  `change_transits_pct`), `route_advice` (rows `route` = suez / cape / difference of the graph's code results),
  `voyage_eta`, `fleet_customers` (customer ↔ vessel ids from `vessels.customer_id`, level 1, no names); each item's
  `tools_needed` is the router's target. Size 57 vs the plan's ≈ 56 (the CEO control counted apart).
  - **D-P12-1 (finding, applied):** Operations *managers* may read the finance views (ceiling 2 ≥ level 2; Stage 1
    refused them only the level-3 HbR results) → the refused side of "RBAC both ways" is the Operations *employee*;
    the twins are asked by employees 12 / 17.
  - **D-P12-2 (finding, for the owner, nothing in the data changed):** an invoice **is** a Suez toll priced from the
    public tariff (`toll_rate_bands`, level 1), so `compute_toll(vessel_id=420)` = the overdue invoice INV-0000005's
    amount (622,758.68 SDR): an Operations employee can always compute any invoice's amount, while the invoice's
    existence, status and payment stay level 2. Caught by the must-not check (the permitted value matched the refused
    one); c06 asks the days past due instead and the equality is asserted. Not a leak by `rbac_mapping.md` (the tariff
    is public, ADR-006), but the cross-product answers should never put the toll next to "your invoice" for a refused
    user — a rule for S3's partial answer.
- 2026-10-29 — **Phase 12 S2 plan — the product tools + the RBAC matrix (PROPOSED, for the owner; no code yet).**
  Facts read for it: `registry.STAGE2` has 4 tools and `Stage2_tools_check.py` Phase 5 asserts exactly those 4
  (400 granted calls); `voyage_eta` is already a LangChain tool in `tools/eta.py` but in no registry; `read_alerts`
  lives in the CLI script `Voyage_watch.py` (a tool must not import a script); `Route_advice.ask` builds the graph
  with `Roles()` + the PostgresSaver and one thread per question; the graph's statuses are ok / no_suez_on_route /
  suez_only / not_permitted / no_data / output_invalid / validation_failed, while `ToolResult` knows only ok /
  not_permitted / context_unavailable / no_data; all 500 vessel names end with their id (a synthetic artifact).
  - **Code (additive):** `pipelines/agents/tools/watch.py` — `watch_alerts` + `read_alerts` moved here from the CLI
    (the CLI and `Voyage_watch_check.py` import it; behaviour unchanged); `pipelines/agents/tools/fleet.py` —
    `fleet_customers`; `pipelines/agents/tools/products.py` — `make_route_advice_tool(roles)` (the graph as a tool,
    roles injected, so a check passes fake roles); `registry.PRODUCTS` (`voyage_eta`, `watch_alerts`,
    `fleet_customers`; `route_advice` built per agent from the factory) and `registry.supervisor_tools(roles)` =
    STAGE1 + STAGE2 + PRODUCTS with unique names. `STAGE1` / `STAGE2` unchanged, so `Tools_check.py` and
    `Stage2_tools_check.py` stay as they are.
  - **`watch_alerts(vessel_id?, high_only?)`** → rows = the run's alerts (keyed `alert_id`, + `thread_id`) and one
    row `alert_id = "fleet"` (the fleet counts and `change_transits_pct`), the golden items' contract; the run = the
    latest saved run **at or before the run context's clock** (decision 2), named in `source.filter`; level 1
    (`can_read`, ADR-006); no run → `no_data`.
  - **`fleet_customers(customer_ids? | vessel_ids? | vessel_name?)`** → rows `vessel_id`, `vessel_name`,
    `vessel_type`, `customer_id` from `vessels` (level 1 / Operations: ids only, never a customer's name or money —
    those stay in `finance_kpi`, level 2); ≤ 50 ids; unknown → `no_data`.
  - **`route_advice(vessel_id | vessel_type + condition + scnt_tons, origin, destination, speed_kn?)`** → runs the
    ADR-057 graph in its own thread `route_advice:<employee>:<as_of>:<from>-<to>:<n>` with the run context's user and
    clock (LangSmith per run as today); rows = the graph's code rows (`route` = suez / cape / direct / difference) +
    one row `route = "advice"` (recommendation, the rendered headline / reasons / risks, `thread_id`, the graph
    status); shape statuses (`no_suez_on_route`, `suez_only`) are `ok` with their rows; a refused user →
    `not_permitted` before any model call; an advice that fails its Validator → decision 3.
  - **Check** `pipelines/scripts/agents/Supervisor_tools_check.py` (fake roles + the real checkpointer, 0 real model
    calls, 0 Open-Meteo calls): Phase 1 `watch_alerts` = the pinned run file (rows, fleet row, clock resolution: at
    2026-09-13T00:00Z → the pinned run; at 2026-09-06T06:00Z → the 09-06T00 run; before the first run → no_data);
    Phase 2 `fleet_customers` = an independent SQL over `vessels`; Phase 3 `route_advice` on fake roles: a thread per
    call, rows = `route_advice.deterministic`, the Validator-failure path, the refused probe before any model call;
    PortWatch / Tavily read from their caches (the route context), a miss → `context_unavailable` as the graph does;
    **Phase 4 the golden contract**: every `value` element of `supervisor_qa_golden.jsonl` re-computed by calling the
    registered tool function **as the item's asker** at the clock — a finance element of an Operations twin must be
    `not_permitted` with no row, every other one must equal its frozen value; Phase 5 the RBAC matrix 100 employees ×
    the 4 product tools = ADR-006, the probe user refused by all with no row (leakage 0), no user / dataset / clock
    field in any model-facing schema, the union list has unique names; `Tools_check.py` 8 / 8 and
    `Stage2_tools_check.py` re-run unchanged; `Voyage_watch_check.py` re-run after the move.
  - **Docs:** `docs/rbac_mapping.md` rows for the three new tools; ARCHITECTURE and the ADR at S6.
  - **Decisions for the owner (asked as choices, recommended first):** (1) where the tools live — a new
    `registry.PRODUCTS` + a new check **vs** added to `STAGE2` (its check's 400-call snapshot changes); (2) which watch
    run — the latest at or before the clock, never a model argument (as ADR-055's clock) **vs** a `thread` argument the
    model fills; (3) an advice its Validator stops — `ok` with the code rows and the advice row marked
    `validation_failed` (the numbers are the code's) **vs** `context_unavailable` with no rows; (4) a vessel named in a
    question — `fleet_customers` also resolves `vessel_name` → id **vs** the model reads the id from the name (true
    only of this synthetic data).
  - **Owner answers (2026-10-29), all four as recommended:** (1) a new `registry.PRODUCTS` + the new check
    `Supervisor_tools_check.py`; (2) the latest saved watch run at or before the clock, never a model argument (the
    golden items' `args.thread` is matched against the run the tool resolved, a scorer rule for S5); (3) a stopped
    advice → `ok` with the code rows + the advice row marked `validation_failed`; (4) `fleet_customers` resolves
    `vessel_name` → id. **S2 plan APPROVED 2026-10-29** by the owner as written with these answers.
- 2026-10-29 — **Phase 12 S2 DONE: the product tools + the RBAC matrix.** New `pipelines/agents/tools/watch.py`
  (`watch_alerts`; `read_alerts` / `can_read` / `run_files` moved from the CLI, which imports them), `fleet.py`
  (`fleet_customers`), `products.py` (`route_advice` as a tool: `run_route_advice`, `make_route_advice_tool(roles)`,
  thread metadata `trigger: supervisor`), `registry.PRODUCTS` + `supervisor_tools(roles)` (14 unique tools); STAGE1 /
  STAGE2 unchanged. `pipelines/scripts/agents/Supervisor_tools_check.py` Phases 1–5 + Final Checkpoint ✅ (narrative
  `pipelines/checkpoints/agents/Supervisor_tools_check.md`; 0 real model calls, 0 Open-Meteo calls, ≈ 150 s): the
  pinned run + the clock rule, `fleet_customers` = SQL, route_advice's code rows = `deterministic` with the
  stopped-advice paths, **all 41 golden value elements reproduced as their askers and the 6 finance elements of the
  Operations twins refused**, RBAC 100 × 4 = ADR-006, leakage 0. `docs/rbac_mapping.md` gained the four tool rows.
  - **D-P12-3 (finding, fixed):** golden item o12 (route case 8) left out the case's 12 kn → the S2 Q&A golden set
    re-frozen v2 through its recorded transition `070a745bee233a92…` → `722f3ca3b7bf86f7…` (before any model run).
  - **D-P12-4 (finding, fixed):** a refused route call opens a thread with no row, and failed runs skipped the
    cleanup → 20 check threads were left in `agent_state`; deleted (only `trigger: supervisor` ones; the one `cli`
    thread kept); the check now deletes every new `supervisor` thread at the end and at exit.
- 2026-10-29 — **Phase 12 S3 plan — the code router + the supervisor agent (PROPOSED, for the owner; no code yet).**
  Facts read for it: `graphs/finance_qa.py` = `create_agent` on the `tools` role (flash-lite + gpt-oss-20b on Groq,
  8K TPM) through `RoleChatModel`, `QaTurn` (answer brief per request, ≤ 3 tool rounds, `check_answer` + one patch),
  `ModelCallLimitMiddleware` 8, `QaAnswer` (answered / not_in_data / not_permitted); `slots.ROW_KEYS_BY_TOOL` keys
  `watch_alerts` rows by `vessel_id/kind` (the S2 fleet row has neither) and `route_advice` is not in `NUMERIC_TOOLS`
  (only `route_costs`); `check_answer` allows literal numbers only from the question, cited passages, tool text
  values, weeks 1–53 and years — a vessel id written as "vessel 420" counts as typed.
  - **Code:** `pipelines/agents/graphs/supervisor.py` (new; `finance_qa.py` stays as it is for Stage 1 and its checks)
    reusing `RoleChatModel`, the evidence helpers and `check_answer`:
    - **Router (code, P12-1):** question words (EN + Egyptian Arabic) → products and tools — finance words → `finance_kpi`
      (+ `invoice_audit` on audit words), toll / dues → `compute_toll`, document words → `search_documents`, a vessel
      (id / name) or position / arrival words → `fleet_customers`, `voyage_status`, `voyage_eta`, route words →
      `route_advice` (+ `sea_route` for a distance), alert / weather / traffic words → `watch_alerts`, fuel →
      `vessel_params`, customer + vessel → `fleet_customers`, news → `web_search`; nothing matched → a small default
      set; ≤ 8 tools per question. Then the **user's access** (ADR-006, the tools' own resources): a routed tool the
      user may not use is dropped and recorded as a refused part (decision 1).
    - **Answer:** `SupervisorAnswer` = `QaAnswer` + the status `partial`; the refused tools are set by code from the
      router, never by the model; the brief tells the model which part it may not answer and in which language.
    - **Checks (`check_supervisor_answer`, on top of `check_answer`):** literal ids allowed when a cited row holds them
      (`vessel_id`, `customer_id`, `voyage_no`); `partial` only with a refused part, and the text names it (the EN / AR
      words of the golden set's `refused_any`); `answered` while a needed part was refused → `partial`; `not_permitted`
      when every routed tool was refused; D-P12-2 (decision 4); then one patch, else `validation_failed`, as Stage 1.
    - **Slots (additive):** `route_advice` in `NUMERIC_TOOLS` keyed by `route`; `watch_alerts` keyed by `alert_id`
      (the same labels for alerts — `36/weather` — plus `fleet`; the voyage watch's own slots unchanged, its check
      re-run).
    - **Limits:** ≤ 4 tool rounds (a cross-product question needs finance → bridge → operations), ≤ 10 model calls;
      the skills in the system prompt chosen by the router per product (decision 2), the new skill (decision 3).
  - **Check** `pipelines/scripts/agents/Supervisor_check.py` (FakeRoles, 0 real model calls): Phase 1 the router on
    the 57 golden items — every `tools_needed` routed (recall 100 %), ≤ 8 tools, the refused part = the golden
    `refused_any.tools` for every Operations twin and none for the others; Phase 2 `check_supervisor_answer` on hand
    answers (right ones pass; planted: a typed figure, an unknown id, `partial` without naming the refused part,
    `answered` while refused, a toll next to "your invoice" for a refused user, a wrong row key, an Arabic answer with
    Arabic-Indic digits typed) — every planted error caught, 0 false alarms; Phase 3 the agent end to end on scripted
    fake models for every golden item (the right tool calls → the right status, slots bound to the frozen values) +
    the patch path + `validation_failed` + the call limit; the largest request measured in tokens against the free
    tiers (Groq 8K TPM); Phase 4 RBAC in the agent: an Operations employee's agent has no finance tool bound, a fake
    model that calls one anyway gets no row and no number; Phase 5 `Finance_qa_check.py` 6 / 6 and
    `Voyage_watch_check.py` re-run unchanged.
  - **Not in S3:** the CLI `Ask.py` + LangSmith (S4), real models and the scorer (S5).
  - **Decisions for the owner (asked as choices, recommended first):** (1) a refused part — the router drops the
    tools the user may not use and code names the refused part (no call, no number can reach the model) **vs** every
    routed tool bound and the tools refuse (one call more per refused part); (2) skills — chosen by the router into the
    system prompt (0 extra calls; a deviation from §6d's `load_skill` tool) **vs** a `load_skill` tool the model calls;
    (3) the skill — a new `supervisor-qa` skill (both products, partial answers, Egyptian Arabic; the owner reviews it
    before S5) **vs** the `finance-qa` skill extended; (4) D-P12-2 — a code rule (in a `partial` answer a sentence with a
    `compute_toll` slot may not name an invoice) **vs** a skill line only.
  - **Owner answers (2026-10-29):** (1) as recommended — the router drops the tools the user may not use, code names
    the refused part; (2) **the alternative — the `load_skill` tool** (D13's own design: `skill_loader.load_skill_tool`
    exists, "the Q&A supervisor sees `descriptions()` and gets the `load_skill` tool"; §6d as written) → the system
    prompt carries the one-line descriptions of the skills of the routed products (+ `supervisor-qa`, `untrusted-content`),
    `load_skill` is always bound on top of the ≤ 8 data tools, a skill's text is never evidence (excluded from the
    evidence index and from the literal-number allowances), the limits become ≤ 5 tool rounds (a skill + 4 data
    rounds) and ≤ 11 model calls, and the Phase 3 token measurement includes a loaded skill; ≈ +1 call per question
    (≈ +57 per evaluation run, inside flash-lite's 500 / day); (3) as recommended — a new `supervisor-qa` skill, owner
    review before S5; (4) as recommended — the D-P12-2 code rule. **S3 plan APPROVED 2026-10-29** by the owner as
    written with these answers.
- 2026-10-29 — **Phase 12 S3 DONE (fake models): the router + the supervisor agent.** New
  `pipelines/agents/graphs/supervisor.py` (router of 12 rules EN + Egyptian Arabic, the access split
  `TOOL_RESOURCES`, `check_supervisor_answer`, `SupervisorChatModel`, `SupervisorTurn` with a tool-call guard,
  `build_graph`, `ask`), `graphs/models.SupervisorAnswer` (+ `partial`), `deck/slots.py` (`route_advice` keyed by
  `route`, `watch_alerts` by `alert_id` — the same labels, + `fleet`), the skill `supervisor-qa` (1,096 tokens,
  **`reviewed_by_owner: no` — the owner reviews it before S5**); `finance_qa.py` unchanged.
  `pipelines/scripts/agents/Supervisor_check.py` Phases 1–4 + Final Checkpoint ✅ (narrative
  `pipelines/checkpoints/agents/Supervisor_check.md`; 0 real model calls): router recall 100 % on the 57 golden items
  (≤ 5 tools, the refused part = the frozen one on the 10 Operations twins), the access table = the tools' own access
  on 88 calls, 6 right answers pass / 10 / 10 planted errors caught, the agent end to end on 33 golden items (27
  answered, 3 partial, 3 not_in_data, every frozen value bound), patch / validation_failed / call limit, a refused
  tool never offered and never run, every part refused → no model call.
  - **Deviations:** an all-refused question ends `not_permitted` in code with a fixed sentence (EN / AR) and no model
    call (the plan said only "a check rule"; decision 1 makes the model call useless there); the plain-text
    untrusted-content rule is one line in the system prompt (the skill itself stays loadable).
  - **D-P12-5 (finding, for the owner, nothing changed):** the largest model request ≈ 6,969 est tokens (c10 / c10_ar:
    the weekly row + the whole watch result) — over the conservative Groq budget (8K − 1,500 reserve at 3 chars a
    token), inside it at 4 chars a token; the first measure (≈ 9.6K) came from the fake model asking 50-row lists. If
    the Groq fallback meets a 413 in S5, the remedy is a compact watch result for the model (fewer fields per alert).
- 2026-10-29 — **Phase 12 S4 plan — the CLI `Ask.py`, a thread and a trace per question (PROPOSED, for the owner; no
  code yet).** Facts read for it: `Finance_qa.py` (Stage 1 CLI) keeps no checkpointer ("one question, one run") and
  traces each question with `tracing.trace(..., entry="qa")`; `Finance_qa_check.py` Phase 6 tests that CLI on fake
  models; one retention rule serves the packs, the route advice and the watch (`scheduling.prune` with
  `describe_route_advice` / `describe_voyage_watch`: a thread with no next node = ended, deleted after 30 days, archived
  first), run by every scheduled firing and `Weekly_pack.py prune`.
  - **`pipelines/scripts/agents/Ask.py`:** `ask "…" --as E [--lang en|ar] [--as-of …]` (the language detected from
    the question when not given; the clock defaults to the data's as-of and may only move back, as every Stage 2 CLI)
    → prints the status, the answer with its numbers filled by code, the refused part (if any), the evidence (tool,
    status, source), the problems the code check found, the model calls (cached or fresh) and the thread; `show
    <thread>` (the stored answer), `list [--as E]`, `prune [--dry-run]`. LangSmith per question (`tracing.trace`, entry
    `ask`, tags: language, products, refused tools; the route advice's graph inside the same trace), never the global
    switch (ADR-054).
  - **Thread per question (decision 1):** `ask:<employee>:<as_of %Y%m%dT%H%MZ>:<n>` in `agent_state` (the
    PostgresSaver, login `ports_agent`), `durability="sync"`; `scheduling.describe_ask` + the same `prune` (30 days,
    archive first), added to the scheduled firings' prune and to `Ask.py prune`; `docs/rbac_mapping.md` row (one
    question and its answer, read back only through `Ask.py show` / `list`, which check the identity — who may read
    it is decision 4).
  - **Check** = `Supervisor_check.py` Phase 5 (fake models, 0 real calls): the CLI end to end (EN, AR, a partial
    answer, an all-refused question with no model call), the thread stored and read back by `show` (= the run's
    state), `list`, `show` refused to another employee, `prune --dry-run` on a thread aged past 30 days (archived +
    deleted in a temp archive, a fresh one kept), one traced question read back from LangSmith when a key exists
    (fake models: no LLM call, the trace only); `Finance_qa_check.py` 6 / 6, `Scheduler_check.py` re-run after the
    prune change.
  - **Decisions for the owner (asked as choices, recommended first):** (1) a PostgresSaver thread per question with
    the 30-day retention (an audit of every answer, `show`, ready for follow-ups in the API phase) **vs** no thread, as
    `Finance_qa.py` (nothing stored, the trace only); (2) the CLI — a new `Ask.py`, `Finance_qa.py` kept as the Stage 1
    CLI **vs** `Finance_qa.py` replaced by `Ask.py`; (3) a real-model smoke in S4 — two questions (an English
    cross-product one and an Egyptian Arabic one, ≈ 10 flash-lite requests) after the owner's review of the skill
    `supervisor-qa` **vs** no real call before S5; (4) who may read a stored answer (`show`) — the asker and the CEO
    **vs** also the asker's department manager.
  - **Owner answers (2026-10-29):** (1) a thread per question with the 30-day retention, **tracing kept** (with a
    note: the finance Q&A CLI goes the same way); (2) **`Ask.py` replaces `Finance_qa.py` completely** (asked once more
    to be sure: "Ask.py مكانها بالكامل") → `pipelines/scripts/agents/Finance_qa.py` is removed, `Ask.py` is the only
    Q&A CLI and every question — finance, operations or both — goes to the supervisor with a thread and a trace;
    `Finance_qa_check.py` Phase 6 (the CLI on fake models) moves to `Ask.py`; the Stage 1 agent
    `graphs/finance_qa.py` stays (`Stage1_eval.py` and the Stage 1 baseline use it; its checks Phases 1–5 unchanged);
    the docs naming the CLI (`CLAUDE.md`, `ARCHITECTURE.md`, `docs/ROADMAP.md`, `pipelines/README.md`,
    `docs/rbac_mapping.md`, the Stage 1 walk-through) point to `Ask.py`; (3) the two-question real smoke after the
    owner's review of `supervisor-qa`; (4) `show` / `list`: the asker and the CEO. **S4 plan APPROVED 2026-10-29** by
    the owner as written with these answers.
- 2026-10-29 — **Phase 12 S4 code DONE (fake models); the real smoke waits for the owner's review of `supervisor-qa`.**
  New `pipelines/scripts/agents/Ask.py` (`ask` / `show` / `list` / `prune`; a thread `ask:<employee>:<as_of>:<n>` +
  a LangSmith trace `entry:ask` per question; `show` / `list` for the asker and the CEO); `supervisor.ask` stores the
  thread (`metadata`, `durability="sync"` with a checkpointer), `new_thread_id`, `THREAD_PREFIX`; a refused-in-every-
  part question is stored as an ended thread (`update_state` as the agent's last node + `jump_to: end`);
  `scheduling._describe_questions` (route advice + ask) + `describe_ask` + `fire(..., ask_graph=)`;
  `Weekly_pack.py` prunes the ask threads in its scheduled firing and `prune`; **`Finance_qa.py` removed** (owner),
  `Finance_qa_check.py` now 5 phases (its CLI phase moved); the docs that named it point to `Ask.py`
  (ARCHITECTURE, CLAUDE, ROADMAP, pipelines/README, the Stage 1 walk-through, the check narrative);
  `docs/rbac_mapping.md` row for the `ask:` threads. `Supervisor_check.py` Phase 5 ✅ (4 threads, the all-refused one
  with 0 model calls, show / list access, retention, the LangSmith read-back).
  - **D-P12-6 (finding, fixed):** `durability="sync"` fails without a checkpointer in langgraph 1.2.14 → passed only
    when the graph keeps checkpoints.
- 2026-10-29 — **Owner review of the skill `supervisor-qa`** (point by point): (1) the clash with `finance-qa` step 3
  (a refused tool → `not_permitted`) — **the owner chose to change `finance-qa` itself** (not the recommended line in
  `supervisor-qa`): step 3 gained the supervisor's exception (the brief lists a part as not permitted → answer the
  rest, name it, status `partial`; `not_permitted` only when nothing asked is permitted), `reviewed_by_owner:
  2026-10-29`; (2) an Egyptian Arabic example added to `supervisor-qa` (1,176 tokens); (3) `supervisor-qa`
  `reviewed_by_owner: 2026-10-29`. Each change is a check: `Supervisor_check.py` Phase 2s (both skills within budget,
  every name and example slot real, the rules stated, the Arabic example, `finance-qa`'s exception, both reviewed);
  `Tools_check.py`'s skill phase knows the supervisor's statuses and the skill names. Re-run: Supervisor_check ✅
  (the largest request 6,969 → 7,050 est tokens: the loaded skill grew), Tools_check ✅, Finance_qa_check 5 / 5 ✅.
  - **D-P12-7 (owed, for the owner):** `finance-qa` is a Stage 1 skill loaded whole into the Stage 1 Q&A agent's
    system prompt, so by ADR-052 its change is a Stage 1 change: before the next Stage 1 evaluation or baseline, the
    Q&A part is compared against `stage1_eval_2026-10-23_confirm.json` (two runs per side; amendment 2's fixed-deck
    mode / `--runs 3` are still not coded). The new lines only apply when the brief lists a refused part, which the
    Stage 1 brief never does.
- 2026-10-29 — **Phase 12 S4 real smoke (owner: "شغّلها"; 2 questions, 7 fresh flash-lite calls, traced in
  LangSmith, both threads kept as real records):**
  - **c02 (English, finance + watch, Finance employee 24)** → thread `ask:24:20260913T0000Z:1`, `answered`, 3 model
    calls, 0 problems: INV-0000005 → Containerships Voyager 420 with a weather alert (= the frozen answer); the
    invoice amount as a slot (622.8 k SDR). Two notes for S5: it did not say the alert is **high** (the golden item's
    third element → 2 / 3); it wrote "waves 6.84 m ≥ 4.0 m" as text, allowed because the alert's `reason` string holds
    those digits (the Stage 1 rule D-P7-15 for digits inside tool text values) — the value is right, but unbound.
  - **o05_ar (Egyptian Arabic, ETA, Operations employee 12)** → thread `ask:12:20260913T0000Z:1`, `answered`, 4 model
    calls (it resolved the name through `fleet_customers` first), 0 problems: arrival 2026-09-15 (= the frozen
    answer), in Egyptian Arabic.
  - **D-P12-8 (finding, cosmetic — fixed 2026-10-29 with the owner's yes):** "61.3 h ساعة" — the slot writes its
    unit (`h`) and the model added the Arabic word after it; `slots.normalize_text` dropped a unit word after a slot
    only in English (D-P8-19). Now `slots.UNIT_OF_KIND` holds the Egyptian Arabic unit words too (ساعة / ساعات, يوم /
    أيام, ميل / ميل بحري / أميال, عقدة, طن / أطنان, متر / أمتار, ٪; longest first) and the match groups them; 5 cases in
    `Supervisor_check.py` Phase 2 (Arabic and English units dropped, another word kept). The number is never touched.
- 2026-10-29 — **Phase 12 S5 plan — `Stage2_eval.py`, the S2 Q&A evaluation (PROPOSED, for the owner; no code yet).**
  Facts read for it: `Stage1_eval.py`'s Q&A scorer (`element_met`, `score_qa`) matches a value by the call's tool +
  args and the bound row's label cut at the first "/" — right for categories, wrong here: a watch row is labelled
  `234/weather`, and a golden customers row is named by `customer_id` while the slot names it by `customer_name`; the
  golden watch items carry `args.thread`, which the model never sends (S2 decision 2); Stage 1 evaluates with an
  `InMemorySaver` (P7-3) and a cache salt per repeat (ADR-052); one Stage 2 run ≈ 57 questions × ≈ 3.5 calls + the
  route advice's writer calls ≈ 210 flash-lite requests (500 a day).
  - **`pipelines/scripts/agents/Stage2_eval.py`** (the `Stage1_eval.py` pattern; Phases 1–3 cost 0 calls):
    1. **Frozen inputs:** the golden set sha256 `722f3ca3b7bf86f7…`, the pinned watch run's sha256, `route_cases.json`;
       the askers.
    2. **The scorers on hand-made states**, each must catch its failure: a value element matched by tool + args (a
       watch element by the run the tool resolved, not `args.thread`) + **the row by its key field in the evidence
       row** (`customer_id`, `invoice_number`, `route`, `alert_id`); name / direction / date forms (EN + AR); a
       partial twin — the result's refused tools ⊇ `refused_any.tools`, a refused word in the text, the operations
       elements, **leak** = a must-not pattern or name in the text or any bound value of a refused tool; an
       abstention with a number = a failure; relevance (week, metric word, subject).
    3. **Fake models end to end** (the `Supervisor_check.py` scripted model on the 33 runnable items): every score
       1.0, 0 leaks — the harness itself proven before a real call.
    4. **Real models** (`EVAL_REAL_MODELS=1`): all 57 items, `EVAL_REPEATS` runs (repeat k = its own cache folder),
       an `InMemorySaver` for the questions and the route advice inside (no thread left in `agent_state`), a partial
       results file resumed after a quota stop, `EVAL_TRACE=1` for LangSmith; the results file
       `Data/processed/agents/eval/stage2_eval_<date>.json` = the Stage 2 baseline; the verdict below.
  - **Reported, never deciding:** model calls / tokens / cached per item, latency, patches, routes, values typed from
    a tool's text (the S4 smoke's "6.84 m"), the Groq fallback's use and any 413 (D-P12-5).
  - **Decisions for the owner (asked as choices, recommended first):** (1) **the done-when (§5 row 12), fixed now,
    before any run:** hard gates — RBAC leakage 0, every Operations twin `partial` (or `not_permitted` where allowed)
    with its refused part named, abstention 100 %, numbers 100 % (no problem left by the code check on an answered
    item), traceability 100 %; primary — completeness EN ≥ 0.85 and AR ≥ EN − 0.10 **vs** EN ≥ 0.90; (2) the runs — two
    (ADR-052), one per provider day (≈ 210 requests each) **vs** one; (3) values typed from a tool's text — reported
    only **vs** counted as a numbers failure; (4) a failed gate — stop and report to the owner (a change is then a
    candidate under ADR-052) **vs** one candidate fix tried at once.
  - **Owner answers (2026-10-29):** (1) as recommended — **the done-when is fixed now:** hard gates RBAC leakage 0,
    every Operations twin `partial` (or its allowed `not_permitted`) with the refused part named, abstention 100 %,
    numbers 100 %, traceability 100 %; primary completeness EN ≥ 0.85 and AR ≥ EN − 0.10; (2) **"خلص كله ف يوم
    واحد"** — the two runs of ADR-052 on the same provider day (≈ 420 flash-lite requests + the smoke's 7, of 500; a
    run the quota stops resumes from its cache the next day, as `Stage1_eval.py`); (3) as recommended — values typed
    from a tool's text are reported only; (4) as recommended — a failed gate stops the evaluation and is reported to the
    owner. **S5 plan APPROVED 2026-10-29** by the owner as written with these answers.
- 2026-10-29 — **Phase 12 S5: `Stage2_eval.py` built (Phases 1–3 ✅, 0 calls) and the first real evaluation run —
  the done-when NOT met; stopped for the owner.** Phases: frozen inputs (golden v2 `722f3ca3…`, the pinned watch run),
  the scorers on hand-made states (a row matched by the tool's own key field; the watch run by what the tool
  resolved), the harness on fake models (33 items at 1.0, 0 leaks). Real run 1 (complete): **RBAC leakage 0, twins
  10 / 10, abstention 3 / 3, numbers 1.0, traceability 1.0 — every hard gate passed**; completeness **EN 0.70 (< 0.85)**,
  AR 0.90; run 2 stopped at item 28 (Gemini 503 + the Groq fallback "too large"; 0 leaks). No results file (complete
  runs only); the narrative and the item-by-item reading: `pipelines/checkpoints/agents/Stage2_eval.md`.
  - **Causes (run 1):** (a) `voyage_status`'s nested `last_fix` cited as slots → 6 `validation_failed`; (b) weak
    cross-product joins — **c07 named the wrong customer with a bound figure** (Belenta Bulk for Thalomar Shipping),
    c01 2 / 6 vessels, c09 the company total for the customer's; (c) route fields (o11 the difference as the dues, o12
    the totals); (d) c02 "high" unsaid, c03 coordinates typed.
  - **D-P12-5 measured:** the largest real call 17,727 tokens (2.5× the S3 estimate) — the Groq fallback cannot serve
    the large questions.
  - **D-P12-9 (deviation, fixed):** the code stopped only on a hard gate, so repeat 2 started after the completeness
    gate failed; the owner's rule is any gate → fixed in `Stage2_eval.py`.
  - **Owner answers (2026-10-29):** (1) **the candidate = all four fixes** — C-a flatten `voyage_status`'s `last_fix`
    into row fields (slot-addressable), C-b `supervisor-qa` lines (dues from the `suez` row, savings from the
    `difference` row, a customer's name and overdue from its own `finance_kpi` row by `customer_id`, an alert's
    severity said), C-c compact tool results for the model (fewer fields per watch alert / customer row: the 17.7K
    request, D-P12-5), C-d a code join tool (customers ↔ vessels ↔ alerts in code, for c01 / c07 / c09) — the C-d
    tool needs its own design, approved before code; (2) **run 2 finished tomorrow first** (the baseline's two runs)
    → `EVAL_FULL=1` added (every repeat runs even after a failed gate; harness only, the agent untouched).
  - **Order (so the baseline stays one setup):** no change to the agent, its skills or its tools until run 2 is
    complete (a changed prompt would miss run 2's cache and mix two setups in one run) → resume
    `$env:EVAL_REAL_MODELS='1'; $env:EVAL_FULL='1'; uv run python tools/run.py pipelines/scripts/agents/Stage2_eval.py`
    after the Gemini reset (run 1 from the reply cache, run 2 from `llm_cache/s2eval_r2/` + ≈ 100 fresh calls) →
    `stage2_eval_<date>.json` = the Stage 2 baseline → the C-a…C-d plan (C-d designed) → the owner's approval → code →
    the candidate's two runs (`EVAL_TAG=c1`) → ADR-052 against the baseline.
- 2026-10-29 — **Candidate c1 plan — C-a…C-d (PROPOSED, for the owner; no code until the baseline's run 2 is
  complete).** Facts read for it: `voyage_status`'s nested `last_fix` is read by `eta.py` (rule R), the voyage watch
  graph and `Stage2_tools_check.py` (which also asserts the LangChain wrapper returns exactly the plain function's
  result) — flattening inside the tool breaks three consumers; the 17.7K request (c01) was mostly
  `fleet_customers(customer_ids=[top 5])` (≈ 150 vessel rows) + the watch result + the customers list + the skill;
  `supervisor-qa` is at 1,176 / 1,200 tokens (C-b lines in it need a trim and a re-review).
  - **C-a + C-c — a model view at the supervisor boundary** (`SupervisorTurn.wrap_tool_call`, after the tool ran):
    rows flattened one level (`last_fix.lat` → `last_fix_lat`, …) and per-tool fields the answers never need dropped
    (watch alerts: `lat`, `lon`, `reason` — the text that let "6.84 m" be typed —, the two `*_source` names; voyage
    status: the full `route` list; the route advice row: `problems`); the evidence = what the model saw (the slots
    bind to it); the tools, their contracts (ADR-055 / 057 / 058) and their checks unchanged; the golden contract
    (`Supervisor_tools_check.py` Phase 4) unchanged.
  - **C-d — the join in code:** `watch_alerts` gains `customer_id` on every alert row (`vessels.customer_id`, level 1),
    `customer_ids` / `vessel_ids` filters (c01: the alerts of the top-5 customers' vessels in one call; c02: the
    alerts of the overdue invoices' vessels) and one summary row per customer with alerts (`alert_id =
    "customer/<id>"`: `customer_id`, `vessels_with_alerts`, `high`) (c09); plus a **code guard** in
    `check_supervisor_answer`: a cited `finance_kpi` customers row must be the customer of the vessel the answer
    cites when the evidence holds that vessel's `customer_id` (c07's wrong customer → a problem → one patch).
  - **C-b — the hints:** in the product tools' descriptions (`route_advice`: the dues are the `suez` row's
    `suez_dues_sdr`, the saving the `difference` row's `change_total_sdr`; `watch_alerts`: name each alert's
    severity, the customer filters) and one line of the code brief (a customer's name and money come from its own
    `finance_kpi` row, matched by `customer_id`).
  - **Checks:** `Supervisor_check.py` (the model view on every tool, a planted wrong-customer answer caught, the
    golden items end to end again), `Supervisor_tools_check.py` (the new `watch_alerts` rows and filters = SQL + the
    pinned file; the RBAC matrix), the request sizes re-measured; then `EVAL_TAG=c1` two runs and ADR-052 against the
    baseline.
  - **Decisions for the owner (asked as choices, recommended first):** (1) C-a + C-c — the model view at the
    supervisor boundary **vs** changing the tools themselves (three consumers + their checks); (2) C-d — `watch_alerts`
    extended + the code guard **vs** a new separate tool; (3) C-b — product-tool descriptions + the code brief (no skill
    change) **vs** lines in `supervisor-qa` (trimmed to budget, the owner reviews it again); (4) the Groq fallback if a
    request still exceeds it after c1 — flash-lite alone for those questions, recorded as an ADR-045 note **vs** a
    small bake-off for a bigger-context fallback of the `tools` role.
  - **Owner answers (2026-10-29), all four as recommended:** (1) the model view at the supervisor boundary; (2)
    `watch_alerts` extended + the code guard; (3) C-b in the product tools' descriptions + the code brief (no skill
    change); (4) flash-lite alone for a request the Groq fallback cannot take, as an ADR-045 note. **c1 plan APPROVED
    2026-10-29** by the owner ("ابدأ c1") as written with these answers, after the baseline was complete.
- 2026-10-29 — **The Stage 2 baseline is complete: `stage2_eval_2026-10-29.json`** (owner: "كمل" → run 2 resumed the
  same day, `EVAL_FULL=1`; run 1 replayed from the cache, 0 fresh calls). Both runs: **every hard gate passed**
  (leakage 0, twins 10 / 10, abstention, numbers, traceability 1.0); completeness EN 0.6985 / 0.826 → **mean 0.7622 <
  0.85**, AR 0.90 / 0.875 → mean 0.8875 (≥ EN − 0.10); largest call 20,502 tokens; 0 fallbacks. **Done-when NOT MET**
  (completeness EN). Wrong in both runs: o01 (×3), o03, c01, c06 (×2), c07 — c1's targets. c06's slot
  `{…:rows[0].amount_sdr}` (a one-row result cited with the result's own path) joins C-a: the model view's
  normalization rewrites a dotted path to its flattened field (`last_fix.lat` → `last_fix_lat`) and drops a
  `rows[0].` prefix — both certain fixes of the slot form, never of the number (D-P7-14).
- 2026-10-29 — **Candidate c1 coded (0 real calls).** `graphs/supervisor.py`: `model_view` (rows flattened one
  level, `MODEL_DROP` per tool: watch `lat` / `lon` / `reason` / `*_source`, voyage status `route`, route advice
  `problems`) applied in `SupervisorTurn.wrap_tool_call` after a routed tool ran; `normalize_paths` (`last_fix.lat` →
  `last_fix_lat`, `rows[0].` dropped) before `slots.normalize_text`; the join guard in `check_supervisor_answer` (a
  cited customers row must be a customer the operations evidence links to: `fleet_customers` / `watch_alerts` rows
  or their `customer_ids` filter); one brief line (joins by `customer_id`, name each alert's severity).
  `tools/watch.py`: `customer_id` on every alert row, `vessel_ids` / `customer_ids` filters, one `customer/<id>` row
  per customer with alerts (`vessels_with_alerts`, `alerts`, `high_alerts`), the description says so;
  `tools/products.py`: the route rows' meaning in `route_advice`'s description. Checks: `Supervisor_tools_check.py`
  Phase 1 (the alert rows = the file + `customer_id` = SQL; the customer rows = an independent count; the filters)
  ✅; `Supervisor_check.py` c1 cases (the model view, 3 slot paths, the join guard catches the wrong customer and
  passes the right one) + the 33 golden items end to end again ✅ (largest request est 7,050 → 7,137: longer
  descriptions + the customer rows); `docs/rbac_mapping.md` `watch_alerts` row. **The candidate's two real runs**
  need ≈ 350 flash-lite requests and 188 were left on 2026-10-29 → the next provider day, both runs the same day:
  `$env:EVAL_REAL_MODELS='1'; $env:EVAL_TAG='c1'; $env:EVAL_FULL='1'; $env:EVAL_BASELINE='stage2_eval_2026-10-29.json';
  uv run python tools/run.py pipelines/scripts/agents/Stage2_eval.py` — `Stage2_eval.py` now applies ADR-052 itself
  (`adr052()`, proven on the baseline file: equal = tie, worse = reject, better = keep). Re-run after c1:
  Supervisor_check (9 validation lines), Supervisor_tools_check, Stage2_eval Phases 1–3, Stage2_tools_check,
  Voyage_watch_check ✅, 0 files changed.
- 2026-10-29 — **c1 real run 1 started the same day (owner: "ابدأ دلوقتي") and stopped at item 38 / 57** on Gemini's
  daily quota (429 RESOURCE_EXHAUSTED at 413 flash-lite requests by our counter, not 500 — the provider counts more
  than `usage.json`); no item mixed models (D-P7-11); resumes from `llm_cache/s2eval_c1_r1/` on the next provider day
  (Gemini resets at midnight Pacific = 07:00 UTC on 2026-10-30). **Early read of the 38 items (not a result):**
  completeness 0.943 vs the baseline's 0.764 / 0.888 on the same items, 0 leaks; every item wrong in both baseline
  runs reached so far is right now — **o01, o03, c01, c06, c07** (c07: the right customer). Still wrong: o11 (a format
  the slot grammar does not parse: `|money_k_sdr` → "malformed slot"), c03 (a text field `as_of` cited as a slot).
  Both are slot-form errors of the model; **not fixed inside c1** (a change mid-run would mix two setups) — noted for a
  later candidate: normalize an unknown format word to the field's default, and copy a non-numeric field as text.
- 2026-10-30 — **c1's two real runs complete (the scheduled task "NileGate Stage2 Eval c1 (once)", fired 09:30:30
  local = 07:30 UTC, the first day after Egypt's DST end; finished 09:50): `stage2_eval_2026-10-30_c1.json`,
  done-when MET.** Run 1 resumed from `llm_cache/s2eval_c1_r1/` (125 cached + 39 fresh calls), run 2 150 fresh + 19
  cached; 0 fallbacks, 0 failed calls, largest call 17,463 / 16,783 tokens, typed-from-text 0.

  | | run 1 | run 2 | mean | baseline mean |
  |---|---|---|---|---|
  | completeness EN | 1.0 | 0.9632 | **0.9816** (≥ 0.85) | 0.7622 |
  | completeness AR | 0.95 | 0.95 | **0.95** (≥ EN − 0.10) | 0.8875 |
  | relevance EN / AR | 0.9706 / 1.0 | 0.9412 / 1.0 | | |
  | leakage · twins · abstention · numbers · traceability | 0 · 1.0 · 1.0 · 1.0 · 1.0 | 0 · 1.0 · 1.0 · 1.0 · 1.0 | every gate passed | |

  **ADR-052 vs `stage2_eval_2026-10-29.json`: "keep (better)"** — no gate regressed, completeness EN +0.2194, AR
  +0.0625. **c1 is kept = the Stage 2 baseline.** Not fully right: run 1 `o01_ar`; run 2 `o01`, `o01_fe`, `o01_ar`,
  `c07`. Of the baseline's both-run failures (o01 ×3, o03, c01, c06 ×2, c07) only **o01** stays: the answers give the
  position and BEANR but drop the voyage status word ("in transit"; the Arabic says only "موجودة حالياً") — a name
  element, not a number; c07 run 2 gave both route costs but not the saving (`difference.change_total_sdr`).
  o11 and c03 (the early read's slot-form errors) scored 1.0 in both runs. `c03_ops` / `c04_ops` run 2 answered
  `not_permitted` (allowed by the golden set's `status_also`: no permitted element in those twins). **Problem:** the
  task's output (`reports/_log/stage2_eval_c1_task.log`) ends in a `UnicodeEncodeError` in `tools/run.py` printing the
  ✅ lines to a cp1252 stdout (the scheduler's redirect), so its changed-files report and exit code were lost
  (task result 1); the script itself finished (its Phase 4 and Final Checkpoint ✅ in
  `Notebooks/_scratch/run_Stage2_eval.log`). The agent was not changed during the runs.
- 2026-10-30 — **S6 close started (owner answers, both as recommended):** (1) the close papers today with 0 model
  calls, D-P12-7 tomorrow on a fresh provider day, the one Stage 2 commit after it; (2) `tools/run.py` fixed —
  `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` at the start of `main()`; proven with
  `PYTHONIOENCODING=cp1252` + a redirect (`Supervisor_golden.py`: ✅ lines and the files report printed, exit 0, 0
  files changed). c1's full log kept as `Notebooks/_scratch/run_Stage2_eval_c1_2026-10-30.log`. (3) **D-P12-7 —
  the Q&A part alone (owner):** `Stage1_eval.py` gained `EVAL_SCOPE=qa` (packs skipped; gates `traceability_100`,
  `rbac_leakage_0`, `abstention_recall_100`; primaries `qa_completeness_en` / `_ar`; D7 not judged; `adr052()`
  compares only what the candidate measured), proven at 0 calls on the confirm baseline (tie / reject / leak
  regressed / keep better); Phases 1–4 ✅, 0 files changed. The baseline's Q&A part: EN 0.9565, AR 0.95, gates all
  passed. Windows task **"NileGate Stage1 QA eval D-P12-7 (once)"** — one trigger 2026-10-31 09:30 local (07:30 UTC,
  after Gemini's 07:00 UTC reset; the US DST ends 2026-11-01), 3 h limit, deleted a day after it expires; runs
  `EVAL_REAL_MODELS=1 EVAL_SCOPE=qa EVAL_TAG=dp127 EVAL_BASELINE=stage1_eval_2026-10-23_confirm.json` → log
  `reports/_log/stage1_eval_dp127_task.log`, results `stage1_eval_2026-10-31_dp127.json` (≈ 2 × 90 fresh calls,
  the confirm runs' Q&A share). (4) **Papers written:** ADR-059 (the supervisor) + ADR-045 amendment 3 (flash-lite
  alone for the requests the Groq fallback cannot take) in `docs/decisions.md`; ARCHITECTURE (the supervisor row
  IMPLEMENTED, API / auth / audit_log stay PLANNED; the supervisor interface); ROADMAP (current phase, the agents
  row); CLAUDE.md (project paragraph); `docs/rbac_mapping.md` already held the four product-tool rows and the `ask:`
  threads (no change); the checkpoints `Stage2_eval.md` (c1) and `Stage1_eval.md` (the qa scope). **Left for after
  D-P12-7:** its result here + in ADR-059, then the plan lifecycle (the implementation record at the top, the move to
  `docs/archive/2026-10-3x_Agents_plan.md`, the archive README row, ROADMAP's next step), `/graphify . --update`, and
  the git commands for the owner's one Stage 2 commit (no AI attribution).
- 2026-10-30 — **Stage 1 candidate c4 — the planted findings always reach the deck (PROPOSED, for the owner; no code
  yet). Owner (2026-10-30): close the `planted_all` point with "a code deck when the text fails", before the Stage 2
  commit.** Facts read for it: in the final Stage 1 baseline (`stage1_eval_2026-10-23_confirm.json`) the code found
  every planted error, but planted = 2 / 6 · 3 / 6 because a pack whose Writer fails its 2 rewrites ends
  `validation_failed` with **no deck** (`stop_failed`), so slide 8's audit table — drawn by code from `audit.week`
  (`render.py` `tbl:audit`) — is lost with it (run 1 test 10 / 36, run 2 test 23); the 6th (t36-b, LNG −33.33 % vs
  budget) depends on the Writer saying it (run 2 test 36 published without it). The safety held (no wrong deck).
  Category budget variance is noisy (small categories at −100 % every week); **a category with a weekly budget ≥ 1 M
  SDR that billed ≥ 25 % below it** matched exactly once in the 52 live + 4 test weeks — test week 36 LNG (the planted
  one) — read-only query on `finance` / `finance_test.kpi_weekly_category`, 2026-10-30.
  - **C4-a — the fallback draft (code):** `after_validator` sends a draft that still fails after `MAX_REWRITES`
    (not V8) to a new code node `fallback` instead of `stop_failed`: each failing bullet is replaced by code — a
    failing summary bullet (slide 2) by the fixed code template of its position (billed + WoW, collected, open AR,
    overdue, DSO: slots on `kpi.weekly`, valid by construction), a failing comment (slides 3–8) dropped (0–3 allowed),
    a failing context line (slide 9) by a fixed sentence without numbers; the Writer's passing bullets stay. The draft
    goes through the same Validator + V8 (`draft_origin: "fallback"`); if it still fails → `stop_failed` as today.
  - **C4-b — the budget-miss line (code, every pack):** slide 5 gets a code-drawn line from `kpi.category` (like
    `tpl:audit.none`): the categories with budget ≥ 1 M SDR and variance ≤ −25 % ("Below budget: …, billed … vs …
    (−33.33 %)"), nothing when none; V8 reads it back. The Writer's prompt and skills unchanged.
  - **C4-c — the approver sees it:** the interrupt payload and `Weekly_pack.py`'s approval report carry `degraded`
    (which bullets code replaced); approve / edit / reject as for any passing draft; `run.json` records `degraded`.
  - **C4-d — the scorer:** planted t36-b is also found in slide 5's code line (the PPTX text, like slide 8's table);
    every other metric unchanged; Phase 2 gains the cases (a degraded deck carries the audit table; the code line
    names LNG on test 36 only; a fallback that still fails publishes nothing).
  - **Checks (0 calls):** `Weekly_pack_check.py` (the fallback path on fake models: a Writer failing 3 times → a
    degraded deck at approval → published; V8 on the code line), `Deck_check.py` (the line rendered / read back, none
    on a week without a miss), `Stage1_eval.py` Phases 1–4 (fake: planted 6 / 6 also when the fake Writer fails).
  - **Evaluation (ADR-052 amendment 2):** the publication now depends on the Writer's variance, so a live comparison,
    three runs per side, packs only (`EVAL_SCOPE=packs`, added next to `qa`): the current code without c4 (tag
    `base3`) and c4 (tag `c4`), the same provider day, ≈ 6 × 50 = 300 flash-lite calls (one day; after D-P12-7's day).
    Primary narrative recall (margin 0.03), the pack gates; `planted_all` expected to pass.
  - **Docs:** ADR-050 / ADR-051 amendments (the fallback and the code line), `docs/finance_metrics.md` (the
    budget-miss rule), ARCHITECTURE, the checkpoints; the skill `deck-style-guide` only if its slide-5 text names
    the line (owner review then).
  - **Decisions for the owner (asked as choices, recommended first):** (1) the fallback: replace the failing bullets
    only **vs** a code-only deck (every Writer bullet dropped); (2) the budget-miss rule: budget ≥ 1 M SDR and ≤ −25 %
    **vs** ≤ −33 % **vs** no size floor; (3) the approver may approve a degraded deck **vs** edit / reject only; (4) the
    evaluation: 3 + 3 packs-only runs on one day **vs** 2 c4 runs against the confirm file (cheaper, but Writer
    variance can decide it).
  - **Owner answers (2026-10-30), all four as recommended:** (1) replace the failing bullets only; (2) budget ≥ 1 M
    SDR and ≤ −25 %; (3) a degraded deck may be approved like any passing draft; (4) 3 + 3 packs-only runs on one
    provider day. **c4 plan APPROVED 2026-10-30** by the owner ("ابدأ c4") as written with these answers.
- 2026-10-30 — **c4 coded and checked on fake models (0 model calls).** `graphs/weekly_pack.py`: `fallback_draft()` +
  node `fallback` (`after_validator`: rewrites spent → `fallback` → `validator`; a failing fallback → `stop_failed`),
  `degraded` in the state, the interrupt payload and `run.json`, `build_graph(..., use_fallback=True)` (False = the
  before side); `deck/render.py`: `budget_misses()` + slide 5's `tpl:budget_miss` / `tbl:budget_miss` (the chart
  4.2 in high when a miss is drawn), `DRAW_BUDGET_MISS`; `deck/sample.py` docstring (now also the fallback's source);
  `Weekly_pack.py show` prints DEGRADED; `scheduling.approval_report` counts `degraded`. `Stage1_eval.py`:
  `EVAL_SCOPE=packs`, `EVAL_C4`, the scorer reads slide 5's table (`pptx_table_rows`), Phase 3c (`FakeFailingPack`).
  **Checks:** Stage1_eval Phases 1–4 + **3c ✅** (with c4 11 / 11, planted 6 / 6, numbers / claims 100 %; before c4
  0 / 11, 0 / 6; the rule names only test week 36's LNG); Weekly_pack_check **6 / 7 ✅** (Phase 3: `always_wrong` →
  fallback → approval, `always_wrong_no_fallback` stops as before; Phase 5 = real models); Deck_check **4 / 4 ✅**;
  Scheduler_check **6 / 6 ✅** (its stopped-pack scenario now on `use_fallback=False`, `degraded` in the report keys);
  0 files changed by any. Docs: `docs/finance_metrics.md` M9a, ADR-051 amendment 3, ADR-050 amendment 1.
  **The comparison (scheduled, owner's 3 + 3):** Windows task **"NileGate Stage1 c4 eval (once)"** — 2026-11-01
  09:30 local (Gemini resets 07:00 UTC that day: the US DST ends at 02:00 PDT), 4 h limit: `EVAL_SCOPE=packs
  EVAL_REPEATS=3 EVAL_C4=0 EVAL_TAG=base3` → `stage1_eval_2026-11-01_base3.json` (log
  `reports/_log/stage1_eval_base3_task.log`, the run log copied to `Notebooks/_scratch/run_Stage1_eval_base3.log`),
  then only if that file exists `EVAL_C4=1 EVAL_TAG=c4 EVAL_BASELINE=stage1_eval_2026-11-01_base3.json` →
  `stage1_eval_2026-11-01_c4.json` (log `reports/_log/stage1_eval_c4_task.log`). A quota stop resumes from the
  caches with the same command on the next provider day.
- 2026-10-30 — **D-P12-10 (deviation, fixed; owner: "أيوه، صلّحه"):** `tracing.labels()` tagged every trace
  `weekly_pack`, so the `Ask.py` / `Route_advice.py` / `Voyage_watch.py` traces and the Stage 2 evaluation's were
  found by a LangSmith filter on that tag. Now only a pack's thread id (`weekly_pack:<dataset>:<year>-W<ww>:<attempt>`)
  gets `weekly_pack` + `graph:weekly_pack` (the other entry points already name `graph:<name>` in `extra_tags`), so
  `graph:` filters every product the same way; traces sent before today keep the old tags. Tags only: no graph,
  scorer or checkpoint change, so the scheduled D-P12-7 / c4 evaluations are unaffected. `Scheduler_check.py`
  Phase 4 expects the new pack tags and that a foreign (`ask:`) thread gets only `entry:` / `launched_by:`;
  **Scheduler_check 6 / 6 ✅** (Phase 5 read back live from LangSmith), 0 files changed.
- 2026-10-30 — **D-P12-11 (owner's choice "لينك دلوقتي"): the trace link in the CLIs.** The `agent_state` thread and
  the LangSmith Threads tab were already joined by `thread_id` (metadata); what was missing was a click. `tracing.trace`
  also collects the block's root runs (`collect_runs`); `tracing.last_url()` builds the link of the first one
  (`Client.get_run_url`, deprecated after 2027-01-31 like `list_runs`; the collector's copy names the project
  `default`, so the run id goes with `read_project(nilegate-agents).id`; ≈ 1 s, two API calls, only when asked; a
  failure → "link unavailable", never a failed run); `tracing.describe()` = the `LangSmith:` line of `Ask.py`,
  `Route_advice.py`, `Voyage_watch.py` and `Weekly_pack.py` (run / resume). Scheduled firings print nothing new (no
  one reads them live; saving the link in `run.json` / the report = the observability plan). `Scheduler_check.py`:
  Phase 4 asserts one root run collected and the off line; Phase 5 asserts the link opens the firing's root run.
  **Scheduler_check 6 / 6 ✅**, 0 files changed. **Datasets & Experiments:** owner chose the mirror after Stage 2
  (ROADMAP, with Sentry); nothing changes in the evaluation harness before the scheduled D-P12-7 / c4 runs.
- 2026-10-31 — **D-P12-7 run (task "NileGate Stage1 QA eval D-P12-7 (once)", 09:30, 1,038 s, 162 flash-lite calls):
  ADR-052 REJECT** vs `stage1_eval_2026-10-23_confirm.json` → `stage1_eval_2026-10-31_dp127.json` (kept as scored).
  Run 1 clean (gates all pass, completeness EN 0.9565, AR 1.0); run 2: gates `rbac_leakage_0` and
  `abstention_recall_100` regressed by **one item, a01** ("What did NileGate bill in week 12 of 2024?", expected
  `not_in_data`): answered "NileGate billed 6.11 M SDR in week 12 of 2025 across 24 invoices (data for 2024 is not
  available)" — a 2025 figure in place of an abstention (the scorer's "refusal with a number" = a leak; not an access
  leak: the figure was the asker's own level). a01 had been right in all 12 earlier runs (6 results files); one run
  cannot tell variance from the `finance-qa` change. Primaries mean EN 0.9783 / AR 1.0 (+0.022 / +0.05).
- 2026-10-31 — **D-P12-12 (owner's choice: a code guard + the run again):** `finance_qa.check_answer` refuses an
  answer that binds a finance figure (`finance_kpi` / `invoice_audit`) when the question names a year other than
  `FINANCE_YEAR` 2025 (Western or Arabic digits) → the agent is asked to rewrite as `not_in_data` (else
  `validation_failed`). The supervisor gets it through `check_supervisor_answer` (`asked=` the user's question, since
  the appended row ids are not years); other tools keep their own years (a 2024 Suez question stays answerable). The S2
  golden set names another year only in a03 (Suez 2026, no finance tool) → the Stage 2 baseline is unaffected.
  Checks: `Stage1_eval.py` Phase 2 (2024 / ٢٠٢٤ refused, 2025 passes) ✅ all phases, `Supervisor_check.py` (the finance
  2024 answer refused, a Suez 2024 answer passes) ✅ 9 lines, `Finance_qa_check.py` ✅ 5 / 5; 0 files changed.
  The run again: tag `dp127b`, same command, fresh caches.
- 2026-10-31 — **D-P12-7 DONE: `stage1_eval_2026-10-31_dp127b.json` = ADR-052 "keep (better)"** vs confirm: no gate
  regressed in either run (traceability, leakage 0, abstention 1.0), completeness EN 1.0 / AR 1.0 in both runs
  (+0.0435 / +0.05). a01: run 1 `not_in_data` in 2 calls; **run 2 needed the guard** (3 calls: a 2025 figure refused,
  rewritten "NileGate's finance data only covers 2025 …") → the failure of `dp127` was real model behaviour, now closed
  in code. 160 fresh flash-lite calls (328 today). Unchanged from confirm: r03 / r03b / r05 (a level-3 document for a
  refused asker) end `not_in_data` instead of `not_permitted` — no figure, gates pass. **Next: c4 (2026-11-01 09:30).**
- 2026-11-01 — **c4 compared live (task "NileGate Stage1 c4 eval (once)", 09:30, exit 0) and KEPT.**
  `stage1_eval_2026-11-01_base3.json` (the code without c4): published 8 / 11 per run, planted 2 · 3 · 0 / 6,
  narrative recall 0.7471, false alarms 0 — only `planted_all` failed. `stage1_eval_2026-11-01_c4.json`: published
  11 · 10 · 11 (the miss `output_invalid`), **planted 6 / 6 in all three runs**, recall 0.9655 (+0.2184), deck numbers /
  claims / traceability 100 %. As scored: ADR-052 **reject** — `false_alarms_le_5pct` regressed in run 1 (0.25).
  - **D-C4-1 (scorer false positive, the D-P8-16 family):** the one "false alarm" — live week 15, "The flagged
    duplicate invoice under Chemical Tankers & Other Liquid Bulk Tankers matched original invoice INV-0000491." — is
    true (INV-0000925 duplicates INV-0000491: same vessel, date, 73,950.26 SDR, Chemical Tankers; golden l15-a). The
    D-P8-16 rule exempted an original only when the duplicate's number was in the sentence. Real false alarms 0 in all
    six runs. **Owner (2026-11-01, choices as recommended): c4 accepted on the hand-check (results files kept as
    scored, as D-P8-16); the scorer fixed:** `false_alarms()` also exempts an original the sentence calls the original
    (`ORIGINAL_WORDS`); Phase 2 + `original_named_as_original` (0) / `original_called_duplicate` (1) → `Stage1_eval.py`
    Phases 1–4 + 3c ✅, 0 files changed. ADR-051 amendment 3 marked kept, ADR-053 result note, checkpoint updated.
  - **D7 `planted_all` met by c4.** **Next:** the plan lifecycle (implementation record, archive, ROADMAP,
    `/graphify . --update`) → the one Stage 2 commit (+ c4 + Sentry S1) by the owner.
- 2026-10-31 — **Sentry started before the Stage 2 commit (owner's choice):** `docs/plans/Observability_Sentry_plan.md`
  (PROPOSED) sits next to this plan until c4 closes it; its S1 touches only a new `monitoring.py`, the four CLIs,
  `.env.example` and `pyproject.toml` / `uv.lock` — none of the code c4 runs (`Stage1_eval.py` and its imports).

### SESSION HANDOFF (2026-10-29, Phase 12 S1 DONE) — read this first in the next session

- **Phase 12 S1 done:** §6d gained its step order (S1…S6); the S2 Q&A golden set is frozen (57 items, sha256
  `070a745bee233a92…`, `Supervisor_golden.py` ✅, 0 calls); findings D-P12-1 (applied) and D-P12-2 (for the owner) in
  Progress above. **S2 done (2026-10-29):** `registry.PRODUCTS` (`voyage_eta`, `watch_alerts`, `fleet_customers`) +
  `route_advice` as a tool + `supervisor_tools(roles)`; `Supervisor_tools_check.py` ✅ (golden contract 41 / 41, 6
  refusals, RBAC 400 / 400, leakage 0, 115 check threads deleted, 0 files changed); `Voyage_watch_check.py`,
  `Stage2_tools_check.py`, `Tools_check.py` re-run ✅, 0 files changed; the golden set is v2 (`722f3ca3b7bf86f7…`,
  D-P12-3). **S3 done on fake models (2026-10-29):** `graphs/supervisor.py` + `Supervisor_check.py` ✅ (router recall
  100 %, 10 / 10 planted answer errors, 33 golden items end to end, RBAC inside the agent); D-P12-5 (request size)
  for the owner; the skill `supervisor-qa` waits for the owner's review. **S4 plan written** (`Ask.py` with a thread +
  a trace per question; owner answers: a thread per question, `Ask.py` **replaces** `Finance_qa.py`, a two-question
  real smoke after the skill review, `show` for the asker and the CEO). **S4 code done (2026-10-29)** — `Ask.py`,
  the `ask:` threads + retention, `Supervisor_check.py` Phase 5 ✅, `Finance_qa.py` removed. **Skill review done
  (2026-10-29):** `supervisor-qa` + `finance-qa` reviewed (finance-qa changed by the owner's choice → D-P12-7, a
  Stage 1 comparison owed). **S4 real smoke done (2026-10-29):** c02 (EN) and o05_ar (AR) both `answered` with the
  frozen facts, 7 flash-lite calls, traced; notes: the "high" severity unsaid, a value typed from a `reason` string,
  D-P12-8 (an Arabic unit doubled after a slot — fixed the same day). **S4 closed.** **Next: the S5 plan**
  (`Stage2_eval.py`: the scorer on the frozen golden set, proven on hand-made failures first, then the real runs;
  leakage 0 = the hard gate); D-P12-7 (the Stage 1 comparison after the finance-qa change) stays owed. **S5 plan
  written** with the owner's answers (done-when fixed: hard gates + completeness EN ≥ 0.85, AR ≥ EN − 0.10; two runs
  on one provider day; typed-from-text values reported only; a failed gate stops and is reported). **S5 first real
  evaluation (2026-10-29):** run 1 complete — every hard gate passed (leakage 0, twins 10 / 10), **completeness EN
  0.70 < 0.85 → the done-when not met**, AR 0.90; run 2 stopped at item 28 (Gemini 503 + Groq "too large"); causes
  and D-P12-9 in Progress. **Baseline complete the same day:** `stage2_eval_2026-10-29.json` — hard gates all
  passed in both runs, completeness EN mean 0.7622 (< 0.85), AR 0.8875 → done-when NOT MET. **Candidate c1 planned**
  (C-a + C-c the model view at the supervisor boundary + slot-path normalization, C-b hints in the product tools'
  descriptions + the brief, C-d `watch_alerts` with `customer_id` / filters / per-customer rows + a wrong-customer code
  guard; the Groq fallback: flash-lite alone for the big requests). **c1 coded and checked; its run 1 stopped at
  38 / 57 on the daily quota** (early read 0.943 vs 0.76 / 0.89 on the same items, 0 leaks). **Next (2026-10-30,
  after 07:00 UTC):** resume, untouched code —
  `$env:EVAL_REAL_MODELS='1'; $env:EVAL_TAG='c1'; $env:EVAL_FULL='1'; $env:EVAL_BASELINE='stage2_eval_2026-10-29.json'; uv run python tools/run.py pipelines/scripts/agents/Stage2_eval.py`
  (run 1 from its cache + 19 items, then run 2 ≈ 160 calls) → the ADR-052 verdict → if kept and the done-when met:
  S6 close (ADR-059, docs, the one Stage 2 commit by the owner). **Scheduled by the assistant (owner: "جدولها",
  2026-10-29):** Windows Task Scheduler task **"NileGate Stage2 Eval c1 (once)"** — one trigger 2026-10-30 09:30 local
  wall-clock (no offset, D-P8-18; = 07:30 UTC after Egypt's DST end, half an hour after the Gemini reset), logged-on
  only, start when available, 3 h limit, deletes itself a day after it expires (end 2026-10-31 09:30); output →
  `reports/_log/stage2_eval_c1_task.log` (+ the usual `Notebooks/_scratch/run_Stage2_eval.log`, the results file
  `stage2_eval_2026-10-30_c1.json` if both runs complete). **Result (2026-10-30): both runs complete, done-when MET**
  (completeness EN 0.9816, AR 0.95, every hard gate passed), **ADR-052 "keep (better)" → c1 = the Stage 2 baseline**;
  details in Progress. **S6 started 2026-10-30** (ADR-059, ADR-045 am. 3, ARCHITECTURE / ROADMAP / CLAUDE.md written;
  `tools/run.py` cp1252 fix; `Stage1_eval.py` `EVAL_SCOPE=qa`; D-P12-10 the LangSmith pack tag + D-P12-11 the trace link in the CLIs, Scheduler_check 6 / 6; LangSmith
Datasets as a mirror → ROADMAP after Stage 2). **2026-10-31: D-P12-7 done** — the scheduled run rejected (a01 answered
2024 with a 2025 figure in run 2) → D-P12-12 the year guard in code (owner) → `dp127b` = keep (better), every gate in
both runs; details in Progress. The next step below is now c4 only. **Next (2026-10-31, after 09:30 local):** read
  task "NileGate Stage1 QA eval D-P12-7 (once)" (`Get-ScheduledTaskInfo`, `reports/_log/stage1_eval_dp127_task.log`,
  `stage1_eval_2026-10-31_dp127.json`, the printed `ADR-052 vs …`) → record it (Progress, ADR-059, Stage1_eval.md) →
  if kept: wait for c4. **Then (2026-11-01, after 09:30 local):** read task "NileGate Stage1 c4 eval (once)" (base3 +
  c4, 3 packs-only runs each, the printed `ADR-052 vs stage1_eval_2026-11-01_base3.json`) → record it (Progress,
  ADR-051 am. 3, Stage1_eval.md) → if c4 kept and D-P12-7 kept: **the owner's walk-throughs (owner 2026-10-31):**
  update `docs/CHECKPOINT_agents_stage1.md` (what changed for Stage 1 after 2026-10-23: `Ask.py` replacing
  `Finance_qa.py`, the `finance-qa` exception + D-P12-7, the year guard D-P12-12, c4 + its result as the new final
  Stage 1 result, D7, the LangSmith tags / links D-P12-10 / D-P12-11) and write `docs/CHECKPOINT_agents_stage2.md` in
  the same form (Egyptian Arabic; Phases 9–12 + the closure: goals, choices, problems, files, final results, lessons,
  next; listed in `CLAUDE.md` "Where things are") → the plan's implementation record + archive + the owner's one
  commit (Stage 2 + c4); a reject → report to the owner. Was owed (now scheduled): D-P12-7 (the Stage 1 Q&A comparison after
  the `finance-qa` change). ADR-052 amendment 2: three runs = `EVAL_REPEATS=3` (used by c4, live, both sides the same
  day); the fixed-deck mode stays uncoded (c4 changes which decks are published, so it cannot be measured on fixed
  decks). Nothing committed (Stage 2 + c4 commit once).

### SESSION HANDOFF (2026-10-29, open points closed + knowledge graph)

- **Owner review (2026-10-29), everything as recommended:** P11-1…P11-10, D-P11-1, D-P11-2 approved; skill
  `voyage-watch-brief` `reviewed_by_owner: 2026-10-29` (`Voyage_watch_check.py` re-run ✅, files changed 0);
  **§6d APPROVED** — P12-1 one `create_agent` behind a code router, P12-2 `route_advice` as a tool, P12-3 a partial
  answer naming the refused part, P12-4 ≈ 30 golden questions + RBAC twins frozen first, P12-5 English + Egyptian
  Arabic. **D-P8-20 decided** → ADR-052 amendment 2 (non-Writer changes on a fixed deck set, Writer changes three
  runs per side, margin 0.03; the fixed-deck mode and `--runs 3` in `Stage1_eval.py` are **not coded yet** — write
  them before the next Stage 1 comparison).
- **Consistency pass:** the task-registration and D-P11-2 statements synced in CLAUDE.md, ARCHITECTURE, ROADMAP,
  ADR-058; `docs/RETRIEVAL_FLOW.md` and `docs/DATA_MAP.md` carry a 2026-10-29 status note (the tools built vs the
  planned `query_records` / `query_operations`, still not built; Phase 12 decides when a golden question needs them).
- **Knowledge graph (graphify; local output, ignored by version control):** `graphify-out/graph.json` 3,148 nodes /
  8,196 edges / 148 communities; every doc node linked to code, SQL and ADRs (1,037 checked link edges stored in the
  docs' semantic cache); scope in `.graphifyignore` (no Data / powerbi / Notebooks / models / docs/archive / db audit
  outputs); hooks rebuild the code part after each commit; CLAUDE.md § Knowledge graph says how to use it. After doc
  edits `/graphify . --update` re-extracts the changed docs and drops their link edges, so re-link those (a doc that
  was only reworded can keep its cache entry instead).
- **Insights for later (no action now):** eleven older scripts keep their own `load_env` / `find_root` /
  `load_env_file` instead of `pipelines/lib/common.py` (Documents_registry, Golden_set, Provider_smoke_test,
  AIS_EDI_profiling, AIS_generator, EDI_generator, MongoDB_loader, ExtractPortsConnection, SyntheticGenerator,
  db/export_vessels_mirror) — a refactor only together with their re-verification; the JS extractor reads `ADR-027`
  in the mongo script comments as isolated `ADR-0027` nodes (a graph artifact).
- **Next session: Phase 12** in the §6d order (the golden set frozen before any run first).

### SESSION HANDOFF (2026-10-29, first scheduled firing + D-P11-2)

- **Owner (2026-10-29):** `WATCH_RUN_AS=2` added to `.env`, `register_voyage_watch.ps1` run → task "NileGate Voyage Watch" Ready, triggers 10:30 + 22:30 local (no offset). **First firing by `Start-ScheduledTask`** (06:56): exit 0, `voyage_watch:20260906T0000Z:1` (380 at sea, 8 alerts / 1 high, brief ok, traced, toast shown) — but **848 of 1,448 weather points failed** (Open-Meteo's per-minute limit, counted per location) and PortWatch did not answer → **D-P11-2** (pacing + one retry + the reason recorded, §6c). That run stays as it is (an honest record; re-running it would spend ≈ 2,900 of the day's 10,000 Open-Meteo calls). `Voyage_watch_check.py` ✅ (Phase 3 tests the retry and the pacing), `Stage2_tools_check.py` ✅ after the `weather.SENT` counter. Next firing 10:30 → 2026-09-06T12:00Z (≈ 8 min paced).
- **Reader note:** `Voyage_watch.py alerts` shows the run with the latest *clock*, so the smoke run at 2026-09-13 stays "latest" until the replay reaches it; `--thread voyage_watch:20260906T0000Z:1` reads a replay run.

### SESSION HANDOFF (2026-10-28, Phase 11 CLOSED — autonomous session)

- **Phase 11 closed (S4–S6), owner to review:** the decisions P11-1…P11-10 (§6c table), D-P11-1, the skill
  `voyage-watch-brief` (`reviewed_by_owner: no`). `Voyage_watch_check.py` **Phases 1–7 + 4s ✅, pending none**, files
  changed 0 once cached: S4 Phase 5 — the graph on FakeRoles + PostgresSaver (9 paths; validation_failed /
  output_invalid keep every alert; a crash in the brief → the run file already holds the alerts, the resume repeats 0
  tool calls); S5 Phase 6 — **the real model once**: 297 watched, 12 live weather alerts (3 high), PortWatch +2.7 %,
  the brief passed the Validator on its first reply (flash-lite, 1 call, cached); Phase 7 — RBAC 100 employees, a
  probe user refused with 0 reads, the replay planner, four firings on the whole fleet (start, start, crash,
  resume), retention 3 / 3. Fixes found: the run file ≠ the final state (defaults) → render writes the validated
  result; the alert reader knew one prefix; the fake brief > 400 characters → the skill names at most three vessels.
  A first live run met failing Open-Meteo batches (213 / 810 points unknown — never cached, said), the next complete.
- **New files:** `tools/eta.py`, `graphs/voyage_watch.py`, `skills/voyage-watch-brief/`, `scripts/agents/Voyage_watch.py`,
  `Voyage_watch_check.py`, `ops/scheduler/register_voyage_watch.ps1`, `checkpoints/agents/Voyage_watch_check.md`,
  `eval/eta_cases.json` + `eta_eval.json`. **Changed (additive):** `deck/slots.py`, `graphs/models.py`,
  `graphs/route_advice.py` (`traffic()` extracted), `scheduling.py`, `.env.example` (`WATCH_RUN_AS`), the docs
  (ADR-058, ARCHITECTURE, ROADMAP, CLAUDE.md, rbac §4a, pipelines/README, §5 row 11 ✔).
- **For the owner (not done by design):** add `WATCH_RUN_AS=2` (or 3) to `.env`, then
  `powershell -NoProfile -ExecutionPolicy Bypass -File ops\scheduler\register_voyage_watch.ps1` (10:30 + 22:30).
  Nothing committed (one commit when Stage 2 closes).
- **§6d written as PROPOSED** (Phase 12 supervisor; P12-1…P12-5 for the owner) — no Phase 12 code.
- **Regression (2026-10-28), files changed 0 in all:** `Voyage_watch_check.py` ✅ (cached), `Stage2_tools_check.py`
  ✅, `Route_advice_check.py` ✅ (after `traffic()`), `Tools_check.py` ✅, `Scheduler_check.py` 6 / 6, `Deck_check.py`
  4 / 4, `Finance_qa_check.py` 6 / 6. **CLI smoke:** `Voyage_watch.py run --as 2` → thread
  `voyage_watch:20260913T0000Z:1` (a real run: kept until the 30-day retention; it counts for the replay's last
  instant), ok, 12 alerts / 3 high, brief ok, 1 model call (cached), traced in LangSmith, file
  `reports/voyage_watch/voyage_watch_20260913T0000Z_1.json`; `alerts --as 13 --high` → 234 / 339 / 420 weather;
  `list` → next replay instant 2026-09-06T00:00Z. `Notebooks/_scratch/run_*.log` are this session's logs (the owner
  removes them with the older leftovers).

### SESSION HANDOFF (2026-10-28, Phase 11 S2 + S3 DONE — autonomous session)

- **S2 done:** Phase 2 ✅ — 810 next-leg points of the 219 at sea against the generator's timeline: ≤ 1.75 nm at
  h = 0 (Phase 9's figure), ≤ 7.1 nm at +72 h (the 6 h mean SOG's noise), points kept / dropped as the truth 810 / 810;
  Suez ahead = searoute's passages on all 498 routes, 40 of the 219 still have the canal ahead. **Fix found:** the
  next-leg points started at the last fix, not at the clock (up to 10 min of sailing) → dead-reckoned from the clock.
  The check's own truth first used the file's `service_kn` (rounded to 2 decimals → 6 nm over 1,900 h): now the
  timeline's implied speed, as Phase 9.
- **S3 done:** `deck/slots.py` additively (`watch.` ids, `watch_alerts` keyed `vessel_id/kind`, `watch_fleet`,
  `voyage_eta`; kinds `_m` metres, `_h` hours + their units); `graphs/models.py` (`WatchRequest`, `WatchItem`,
  `WatchBrief`, `VoyageWatchResult`); `graphs/voyage_watch.py` (the 8 nodes, alert rules, Validator, run file, thread
  naming); `route_advice.traffic()` extracted from `context()` (same calls; Route_advice_check = regression); skill
  `voyage-watch-brief` (227 chars, 1,023 tokens, **reviewed_by_owner: no — owner review pending**). Phase 3 ✅:
  planted storms (32 discs, 6 kinds) → weather precision = recall = 1.0 (27 / 27, severities agree), Suez −30 % /
  −45 % → 40 / 40, −10 % and PortWatch down → 0, near-threshold and null discs → no alert, reproducible; sensitivity
  (reported): 10 nm discs 22 / 22, 5 nm discs recall 0.95 (smaller than the dead-reckoning error). Phase 4 ✅: 49 / 49
  planted brief errors caught, 0 false alarms on 3 clean briefs, the normaliser touches none. Phase 4s ✅.
  **D-P11-1:** a Suez drop alerts every vessel with the canal ahead (54 high alerts at −45 %) → `WatchItem.alert_ids`
  up to 60 (one Suez item for all), the skill says so.
- **Docker note:** Docker Desktop was not running on 2026-10-28 (the machine had restarted) → started by Claude
  (`Docker Desktop.exe`), the three containers came up by themselves.
- **Next: S4** — Phase 5: the graph on FakeRoles + PostgresSaver (alerts → 1 call, none → 0 calls, patch,
  output_invalid, validation_failed, PortWatch / Open-Meteo down, crash in `brief` + resume, run file = state).

### SESSION HANDOFF (2026-10-28, Phase 11 S1 DONE — autonomous session)

- **S1 done:** `pipelines/agents/tools/eta.py` (rules R / R0 / N / S, `harbour_kn()` = 6.7 from the NOAA profile,
  `next_leg_points`, `suez_ahead`, the tool `voyage_eta` — not yet in a registry, Phase 12 binds it);
  `Data/processed/agents/eval/eta_cases.json` **frozen** before the first prediction (126 cuts of 50 voyages: 75 on
  the 25 arrived + 51 on the 25 at sea); `Voyage_watch_check.py` Phase 1 ✅ and its results **frozen** in
  `eta_eval.json` after the first clean run (no tuning after it). **ETA result (126 predictions): MAE R 0.885 h,
  N 117.826 h, S 1.636 h, R0 1.274 h** → S2-D5 met (R < N); the ML margin (MAE(R) > 2 h and > 5 % of the mean
  remaining 366.6 h) not reached → no ML. Worst R −10.8 h (vessel 77, cut 25 %, 2,033 h left: the 6 h mean SOG's
  noise over 85 days). Honest reading (F7): R reproduces the generator; S is near exact too because the speed is
  constant; N's error is the straight line vs the real route. Buckets: < 24 h n = 1, 1–5 d n = 21, > 5 d n = 104.
- **Next: S2** — next-leg points + Suez ahead, Phase 2 against the generator's timeline.

### SESSION HANDOFF (2026-10-27, Phase 11 design written — autonomous session)

- **Owner asleep; autonomous grant (memory `autonomous-when-owner-away`).** §6c written and marked "APPROVED by the
  autonomous grant, owner to review" (decisions P11-1…P11-10, facts F7–F12; ETA rules R / N / S / R0, the cases
  rule, the ML margin, the alert rules and precision targets all fixed **before** any measurement). Nothing
  committed (one commit when Stage 2 closes). **Next: S1** — `tools/eta.py` + the frozen `eta_cases.json` +
  `Voyage_watch_check.py` Phase 1.

### SESSION HANDOFF (2026-10-27, Phase 10 CLOSED)

- **Phase 10 closed (S6):** ADR-057 in `docs/decisions.md`; ARCHITECTURE (overview diagram, the component row,
  §7 interface, ADR table), `docs/rbac_mapping.md` §4a (the graph + its threads), `pipelines/README.md` (the CLI and the
  check), `pipelines/checkpoints/agents/Route_advice_check.md` (phases, 7 problems and fixes, notes), §5 row 10 ✔,
  ROADMAP, CLAUDE.md. Deviations: D-P10-1 (Tools_check Phase 8 = stage-1 skills only), D-P10-2 (the retention test in
  Route_advice_check). Nothing committed (one commit when Stage 2 closes).
- **Next: Phase 11 — the `voyage_watch` graph** (C Voyage & Disruption Watch: ETA baseline, delay risk from the weather
  on the next legs and Suez traffic, alerts saved, scheduled every N hours — S2-D1): write its concrete design as
  PROPOSED (§6c), the owner's approval before code. Mind §6a F2 (no port stops in the synthetic voyages: a
  rule-based ETA is nearly exact) when fixing the baseline rule.

### SESSION HANDOFF (2026-10-27, Phase 10 S5 DONE)

- Regression + smoke (2026-10-27): `Scheduler_check.py` 6 / 6, files changed 0; `Route_advice.py ask --vessel 36
  --from SGSIN --to NLRTM --as 13` → thread `route_advice:13:2026-09-13:SGSIN-NLRTM:1`, ok, Suez (2.23 M vs 2.46 M
  SDR), 1 model call (cached), 3 comparison rows, 6 assumptions, 10 sources, traced in LangSmith; `list --as 13` shows
  it (ended, ok). That thread is a real question: it stays until the 30-day retention.

- **S5 done:** CLI `pipelines/scripts/agents/Route_advice.py` (`ask --vessel | --type --condition --scnt --from --to
  [--speed] --as [--as-of]`, `show <thread>`, `list --as`; LangSmith tag `graph:route_advice`); retention:
  `scheduling.describe_route_advice()` (route threads as ThreadInfo → the same `prune`), `fire(..., route_graph=)` and
  `Weekly_pack.py scheduled` / `prune` pass the route graph (`route_graph()`, no model). **D-P10-2:** the retention test
  lives in `Route_advice_check.py` Phase 6, not in `Scheduler_check.py` (its frozen snapshots untouched; it runs as
  the regression). **Fix found by Phase 6:** `describe_route_advice` read the employee after the listed prefix (a
  narrower prefix made the thread number the employee) → always after `route_advice:`.
- `Route_advice_check.py` **all phases ✅, pending none** (7 + 3s): Phase 5 real model (flash-lite, the writer role's
  main): 8 / 8 advices pass the Validator — every number slot-bound, the rule kept (case 8 → the Cape, the cheaper);
  first run 11 calls, 3 patches; the third run 9 / 9 cached, files changed 0 (the context had changed between runs:
  PortWatch answered again, so the prompts differed). 0 overrules (no risk in the context). Phase 6: 100 employees
  may ask, a probe user → not_permitted before any model call, no user / clock / dataset in a schema, retention 31
  days later: 2 ended threads archived + deleted, the stalled one kept.
- **Observation for the owner:** case 7's headline says "traffic remains stable despite regional tensions" — a
  qualitative claim with no number (the Validator checks numbers and the rule, not the wording of context claims).
- **Next: S6 close** — ADR-057, ARCHITECTURE, ROADMAP, CLAUDE.md, `pipelines/README.md`, checkpoint narrative
  `Route_advice_check.md`, rbac §4a (the graph), the plan's row 10 ✔.

### SESSION HANDOFF (2026-10-27, Phase 10 S4 DONE)

- **S4 done:** `graphs/route_advice.py` — the advisor (one `writer` structured call with skills route-cost-advice +
  untrusted-content over `advisor_digest`: the question, the computed rows, the context; news marked untrusted; the
  Stage 1 slot-form fixes via `normalize_advice`), `validate()` (every cited id exists; slots resolve; no typed number
  — dates only; a slot's evidence cited by its reason; the rule: the dearer route only when the **first** reason
  cites `route.news` with results or `route.traffic` ≤ −20 %), `assumptions()` (written by code), `sources()`,
  `shape_headline()`, the StateGraph (inputs → routes → costs → context → advisor ⇄ validator (1 patch) → render;
  `failed` for not_permitted / no_data / output_invalid / validation_failed; shape statuses skip the model),
  `new_thread_id()` (`route_advice:<employee>:<as_of date>:<o>-<d>:<n>`). `Route_advice_check.py` Phases 3 + 4 ✅:
  64 / 64 planted errors caught, 0 false alarms on the 8 two-route cases, the news / −25 % overrides pass, −10 %
  refused; the graph on FakeRoles + the real PostgresSaver: 8 ok (8 model calls, case 8 → the Cape), 4 shape answers
  (0 calls), patch (2 calls), validation_failed, output_invalid, PortWatch down → ok + "context unavailable", crash
  in the advisor resumed with 0 tool calls repeated; check threads deleted (0 `route_advice:` threads left).
- **Not yet (S5):** the CLI `Route_advice.py` (ask / show / list) + LangSmith context, the retention of
  `route_advice:` threads (`scheduling.py` + `Scheduler_check.py`), the real model on the 12 cases (Phase 5), the
  RBAC / contract phase (6).

### SESSION HANDOFF (2026-10-27, Phase 10 S3 DONE)

- **Owner (2026-10-27, AskUserQuestion):** the skill `route-cost-advice` approved as it is (`reviewed_by_owner:
  2026-10-27`), the −20 % traffic-drop threshold confirmed (recommended). `Tools_check.py` after D-P10-1: 8 / 8 ✅,
  pending none, files changed 0. Next: S4 (advisor + validator + render on
  FakeRoles; checkpointer + thread naming; the Validator enforces the rule).

### SESSION HANDOFF (2026-10-27, Phase 10 S3 waiting for the owner's skill review)

- **S3 drafted:** `pipelines/agents/skills/route-cost-advice/SKILL.md` (stage 2, 226 chars, 1,153 tokens,
  `reviewed_by_owner: no`): the evidence fields, the decision rule (cheaper route; overrule only with a cited risk —
  a `route.news` item on attacks / closure / serious disruption, or `change_transits_pct` ≤ −20 %; no risk evidence =
  the cheaper route; days never priced), RouteAdvice's shape, numbers as slots (route formats), literal numbers =
  dates only, three examples. `Route_advice_check.py` Phase 3s ✅ (budgets, 42 named fields all real, 8 example slots
  render on case 2, the rule sentences present). **D-P10-1:** `Tools_check.py` Phase 8 now checks the stage-1 skills
  only (the new skill is stage 2, checked by Route_advice_check); regression run in progress. **New parameter for the
  owner's review:** the −20 % traffic-drop threshold.
- **Next:** the owner reviews the skill → `reviewed_by_owner: <date>` → S4 (advisor + validator + render on
  FakeRoles; the Validator enforces the rule).

### SESSION HANDOFF (2026-10-27, Phase 10 S2 DONE)

- **S2 done:** `graphs/models.py` + `RouteRequest`, `RouteReason`, `RouteAdvice`, `RouteAdviceResult`
  (`ROUTE_EVIDENCE_ID = route.<name>`); `graphs/route_advice.py` nodes 1–4 as functions (`inputs`, `route_pair`,
  `toll`, `costs`, `context`, `deterministic`): costs from the tools' shown (rounded) numbers so the table adds up by
  hand; `route.compare` rows suez / cape / direct, `route.difference` (Cape − Suez, `change_*`, `cheaper_route`),
  `route.traffic` (PortWatch 28 days vs a year earlier, `change_transits_pct`). `Data/processed/agents/eval/
  route_cases.json` **frozen** (12 cases by rule: lowest-id vessel of category k in band 1 / 3; vessels 21, 36, 43, 15,
  37, 17, 66, 6, 9, 2, 39, 149). `Route_advice_check.py` Phase 1 ✅: 20 route rows = an independent computation (toll
  from the bands' CSV, fuel from the performance CSV + the voyage file, distances from searoute directly), cases 9–10
  `no_suez_on_route`, 11–12 `suez_only`, unknown vessel / port → no_data, a hypothetical vessel's toll by hand.
  Case 8 (LPG band 3, ballast, 12 kn): **the Cape is cheaper** (917,344.60 vs 1,019,460.23 SDR: dues > extra fuel) —
  the rule's other branch is in the set.
- **External (pending, not our code):** on 2026-10-27 PortWatch's ArcGIS service answered 400 "Invalid URL" and
  timeouts intermittently (the same query succeeded once minutes earlier) → `suez_transits` = context_unavailable, as
  designed; the check marks "Phase 1 live Suez traffic" pending. News (Tavily) ok, cached.
- **Next: S3** — the skill `route-cost-advice` (owner review), then S4 advisor + validator + render on FakeRoles.

### SESSION HANDOFF (2026-10-27, Phase 10 S1 in progress)

- **§6b approved by the owner (2026-10-27, as written).** S1 code done: `pipelines/agents/deck/slots.py` extended
  additively — `NUMERIC_TOOLS` + the Stage 2 tools and `route_costs`, `ROW_KEYS_BY_TOOL` for them (`route_costs`
  keyed by `route`), the `route.` evidence id, kinds by suffix `_nm` distance (`nm` / `nm0`), `_kn` speed (`kn`),
  `_t_per_day` rate (`tpd`), `_t` tonnes (`t` / `t0`), their units for the form fix. Difference fields carry
  `change` in their names (`change_sea_days`, …) so their sign is always written. New
  `pipelines/scripts/agents/Route_advice_check.py` Phase 2 ✅ (14 route slots render + read back, 7 bad slots refused,
  Stage 1 kinds unchanged, units next to a slot dropped). Note for S4: Stage 1's `number_matches` takes a plain
  number only when exact, so the route Validator must accept the kinds' 0 / 1-decimal roundings itself.
- **S1 closed — regression after the slots change (2026-10-27):** `Deck_check.py` 4 / 4, `Finance_qa_check.py`
  6 / 6, `Weekly_pack_check.py` 6 / 7 (the 7th = Phase 5 real models, skipped by design without
  `PACK_REAL_MODELS=1`, as before), `Tools_check.py` 8 / 8; files changed 0 in all four. **Next: S2** — models +
  the deterministic nodes 1–4 + the 12 route cases frozen (shown to the owner).

### SESSION HANDOFF (2026-10-27, Phase 10 design PROPOSED)

- **§6b written** (Phase 10 `route_advice`): 7 nodes (inputs, routes, costs, context = code; advisor = one `writer`
  call with number slots; validator = code, one patch; render = code incl. the assumptions list), statuses
  (`no_suez_on_route`, `suez_only`, …), the slots extension (`route.` ids, nm / kn / t / sea days), 12 frozen route
  cases computed independently, `Route_advice_check.py` 6 phases, order S1…S6. Owner answers P10-1…P10-4 recorded
  (P10-3 = PostgresSaver thread per question + trace → retention extended to `route_advice:` threads). **Waiting
  for the owner's approval of §6b as a whole; no code.** The owner already removed this phase's `_scratch` files.

### SESSION HANDOFF (2026-10-27, Phase 9 CLOSED)

- **Phase 9 closed (S9):** ADR-055 (Stage 2 tools, the clock in the run context, migration 020, the answer key never
  returned) and ADR-056 (no live AIS, D11 narrowed) in `docs/decisions.md`; ARCHITECTURE (components, §4 two tables,
  §7 interfaces + MongoDB reader, ADR table), `docs/rbac_mapping.md` (§2 two tables, §3 the voyage file + reader,
  §4a four tools), `db/README.md` (snapshot line, audit), `db/mongo/README.md` (005), `pipelines/README.md`,
  `pipelines/checkpoints/agents/Stage2_tools_check.md` (phases, 7 problems and fixes, notes for Phases 10–11), §5
  row 9 ✔, §6's example question corrected (F1a), ROADMAP, CLAUDE.md. `_scratch` cleanup **pending**: deleting
  `Notebooks/_scratch/imo_ghg4/` (the 28 MB IMO PDF) and `run_Stage2_tools_check.log` was refused by the session's
  permissions → the owner removes them (Stage 1 leftovers are his too). Final run: Phases 0–5 ✅, files changed 0.
- **Deviations D-P9-1…D-P9-11** are listed in the S1–S6 handoffs below (Phase 0, run.ps1, `Source.kind library`,
  ref speed = IMO SOG, main + aux, raw IMO columns, §24, no condition argument, `sea_leg`, spherical projection, COG).
- **Nothing committed** (owner: one commit when Stage 2 closes).
- **Next: Phase 10 — the `route_advice` graph** (B Route & Cost Advisor): write its concrete design as PROPOSED
  (inputs, the comparison model, the Validator rule "no number without a tool", the ~12 route cases of §8 from
  Phase 1's frozen cases), the owner's approval before code. Open Stage 1 decision D-P8-20 still not part of it.

### SESSION HANDOFF (2026-10-27, Phase 9 S8 DONE)

- **S8 closed:** `Stage2_tools_check.py` Phase 5 ✅ — RBAC matrix 100 employees × the 4 Stage 2 tools = the ADR-006
  expectation from each tool's resources (all level 1: 400 / 400 granted); a probe user below every ceiling is
  refused by all 4 with no row and no source (leakage 0); no user / employee / dataset / as_of / runtime field in any
  model-facing schema; 4 / 4 wrappers refuse a call without a RunContext. Whole check: Phases 0–5 ✅, pending none,
  64 s, files changed 0 (the live weather now read from its settled cache). `Tools_check.py` regression 8 / 8 ✅
  (+ 3b), pending none, files changed 0 (135 s) — Stage 1's matrix (Finance tools refused to Operations) unchanged.
- **Next: S9 close** — ADR-055 (Stage 2 tools: contract, the clock in the run context, the facts F1–F6, D-P9-1…11)
  and ADR-056 (no live AIS in Stage 2, D11 narrowed, P9-2); ARCHITECTURE (components, interfaces, schema §4 two tables,
  MongoDB reader), ROADMAP, `rbac_mapping.md` (§2 two tables, §3 the voyage file, §4a Stage 2 tools), §6 example
  question (F1a), `pipelines/checkpoints/agents/Stage2_tools_check.md`, `pipelines/README.md`, `db/mongo/README.md`
  (005), the README snapshot line, `_scratch` cleanup (IMO PDF, logs) — then the plan's Phase 9 row ✔.

### SESSION HANDOFF (2026-10-27, Phase 9 S7 DONE)

- **S7 closed:** `pipelines/agents/tools/weather.py` (`marine_weather(points ≤ 30 of {lat, lon, date})`, dates within
  92 days; waves = Open-Meteo Marine up to today + 7; wind in kn = Historical Forecast API before today, Forecast API
  from today up to + 15; one request per API for all points, each point keeps its own date; coordinates rounded to
  2 decimals; through `external.cached_call`; any failed request → `context_unavailable`, no partial numbers; land /
  beyond the horizon → null + note "unknown, not calm"; the coastal caveat + CC BY 4.0 credit in every note),
  `STAGE2["marine_weather"]`. `Stage2_tools_check.py` Phase 4 ✅ first run: offline (MockTransport, fixed today
  2026-10-27): own date per point, past → historical-forecast + marine hosts, future → forecast, cached (0 requests on
  repeat), timeout / 500 / not JSON / wrong shape → context_unavailable with nothing cached, 4 bad argument sets
  refused, wrapper = function; **live** 3 probe points on 2026-09-13 = the §6a F5 probe (waves 0.84 / 0.52 / 4.14 m,
  wind 12.2 / 15.9 / 32.7 kn), cached for good in `Data/processed/agents/tool_cache/marine_weather.jsonl`
  (git-ignored; created by this run). Pending none.
- **Next: S8** — RBAC matrix (100 employees × the 4 Stage 2 tools, Phase 5) + `Tools_check.py` regression; then
  S9 close (ADR-055 / ADR-056, ARCHITECTURE, ROADMAP, `rbac_mapping.md`, §6 example question, checkpoint narrative,
  `_scratch` cleanup incl. the IMO PDF, README snapshot line).

### SESSION HANDOFF (2026-10-27, Phase 9 S6 DONE)

- **S6 closed:** `pipelines/agents/tools/voyages.py` (`voyage_status(vessel_id)`, clock from the run context; MMSI from
  PostgreSQL, synthetic fixes `ts <= as_of` from MongoDB as `nilegate_reader`; the route rebuilt leg by leg with
  `routes.sea_leg` = the generator's rule; covered distance = the last under-way fix projected on the route **on the
  sphere**, the projection chosen by the fix's COG vs the route's course (± 60°), then the closest to the odometer;
  status from the track: navstat 0 In Transit, 1 Anchored, 5 + no move Not departed, 5 + last fix > 3 h old
  Completed, else At Port; next port / ports left; `arrival_ts` only once arrived and ≤ `as_of`; never `eta_raw`),
  `STAGE2["voyage_status"]`. `Stage2_tools_check.py` Phase 3 ✅ (49 s run): route = `route_nm` (≤ 0.1 nm) and last
  fix = the generator's for all 500, status = `vessels.status` 500 / 500 (219 / 130 / 78 / 73), distance left vs the
  generator's own timeline ≤ 1.79 nm for the 219 at sea, anchored ≈ 5 nm, the cut half-way to the as-of for all
  219 (no later fix, no arrival, ≤ 2 nm), before departure = Not departed, no fix → no_data, a clock past the data
  refused, no answer-key field or future time in any result; snapshot frozen.
- **Fixes found by the check (deviations):** D-P9-9 `routes.sea_leg` added — two ports snapped to the same network node
  give a zero-length searoute path, which `sea_path` (rightly, for `sea_route`) calls "no route", but the generator
  still routes through that node (48 routes were off by up to 78.7 nm); D-P9-10 projection on the sphere instead of a
  local plane (long MARNET steps); D-P9-11 port visits that retrace the same water are told apart by COG (the
  odometer alone ran a few nm short and picked the wrong pass, vessel 100: 9.5 nm).
- **Next: S7 `marine_weather`** (`tools/weather.py`, Open-Meteo Marine + Historical Forecast / Forecast, ≤ 30 points,
  `external.cached_call`; Phase 4 offline MockTransport + one live call).

### SESSION HANDOFF (2026-10-27, Phase 9 S5 DONE)

- **S5 closed:** `pipelines/agents/tools/vessels.py` (`vessel_params`: `vessel_id` or `vessel_type` + `scnt_tons`,
  optional `speed_kn`; speed = argument > the vessel's `service_kn` > the band's IMO reference speed; fuel / sea day
  = main × (v / v_ref)³ + aux; SDR price = latest VLSFO ÷ USD per SDR, both dates returned; exact Decimal, rounded
  once), `pipelines/agents/tools/voyages.py` (the voyage file loader, extended in S6), resource
  `context.VESSEL_PARAMS`, `STAGE2["vessel_params"]`. **D-P9-8:** no `condition` argument (§6a listed one) — the IMO
  figures are yearly averages over laden and ballast. `Stage2_tools_check.py` Phase 2 ✅: tables = the CSVs (39 + 1),
  500 vessels each in its band at its own service speed (39 bands used), the cube law and 691.24 SDR / t by hand,
  band edges (lower inclusive, upper exclusive), 6 bad argument sets refused, wrapper = function; snapshot frozen
  (vessel 1: SFU band 1, 8.97 kn, 10.21 t / day, 7,060.40 SDR / day). Files changed 0.
- **Next: S6 `voyage_status`** (MongoDB fixes ≤ `as_of`, the rebuilt route, next port, distance left; no
  `eta_raw`, no `arrival_ts` before arrival; Phase 3 of the check).

### SESSION HANDOFF (2026-10-27, Phase 9 S4 DONE)

- **Migration 020 applied** by Claude (owner confirmed the price row and said apply): dry run rolled back (39 + 1
  rows) → BEGIN / 2 CREATE TABLE / INSERT 0 39 / INSERT 0 1 / 25 COMMENT / COMMIT → `ANALYZE` → snapshot refreshed
  → `db/audit/2026-10-27_after_020_report.txt`, 0 errors, §24 = expected `39 | 13 | 0 | 0 | 0 | 0 | 1 | 691.24 | t | f`;
  the rest = the 019 report except the two new tables (`ports_readonly` reads 16 / 16, writes 0). `db/README.md`
  updated (status row, §24, reference files). Note for the snapshot's header line in README: still says 2026-09-27.
- **Next: S5 `vessel_params`** (`tools/vessels.py`, resource `VESSEL_PARAMS` level 1 / Operations,
  `STAGE2["vessel_params"]`, Phase 2 of the check: tables = CSVs, cube law, SDR price).

### SESSION HANDOFF (2026-10-27, Phase 9 S4 SQL shown, waiting to apply)

- **S4 drafted:** `db/migrations/020_vessel_performance.sql` (135 lines, rendered by a scratch script from
  `db/reference/vessel_performance.csv` + `db/reference/bunker_prices.csv`): tables `vessel_performance` (PK type +
  band, 6 CHECKs incl. the 13-value list, open band 3 only) and `bunker_prices` (PK fuel + date, VLSFO only,
  positive), INSERTs, a COMMENT on every table / column; SELECT via `ports_readonly`'s default privileges.
  **Proposed price row (owner to confirm):** VLSFO 936.50 USD / t, Ship & Bunker G20 average, 2026-10-26; USD per
  SDR 1.354820, IMF SDR valuation, 2026-10-26 → 691.24 SDR / t. `db/verify_readonly.sql` **§24** (D-P9-7: §20 was
  taken by migration 016) — expected `39 | 13 | 0 | 0 | 0 | 0 | 1 | 691.24 | t | f`; pre-checked from the CSV: 500
  vessels each in one band, derived values = PostgreSQL's half-up rounding.
- **Next:** the owner confirms (or changes) the price row and says apply → dry run (rolled back), apply, ANALYZE,
  snapshot, `verify_readonly.sql` → audit file; then S5 `vessel_params`.

### SESSION HANDOFF (2026-10-27, Phase 9 S3 DONE)

- **Owner (2026-10-27, AskUserQuestion):** D-P9-4 `ref_speed_kn` = IMO's average SOG (recommended), D-P9-5 main + aux
  split (recommended), the 39 rows approved as they are. The full table was printed in the reply right after the
  approval; any row change before S4 just re-runs the scratch builder. **Next: S4** — migration 020 SQL shown to the
  owner (tables `vessel_performance` with the CSV's columns + `bunker_prices`), the bunker price row set by him.

### SESSION HANDOFF (2026-10-27, Phase 9 S3 waiting for the owner's review)

- S2 snapshot: `single_legs` frozen at 9. **S3 drafted:** `db/reference/vessel_performance.csv` (39 rows = 13 types ×
  3 SCNT bands) from the **Fourth IMO GHG Study 2020, Table 35** (2018 detailed results, printed pp. 99–101; PDF
  downloaded with the owner's OK to `Notebooks/_scratch/imo_ghg4/`, 28,686,552 bytes, SHA-256 `0dadcab7…44411b`,
  git-ignored, removed at Phase 9 close). Built by a scratch script (values transcribed from the PDF text). Rules:
  bands = tertiles of our vessels' SCNT per type (rounded to 1,000; band 1 from 0, band 3 open); each band → one IMO
  bin by rank (small / medium / large of the trading fleet; our SCNT cannot be converted to dwt / TEU / cbm);
  `main_t_per_day` = main kt × 1,000 / days at sea, `aux_t_per_day` = aux kt × 1,000 / 365, `ref_speed_kn` = IMO's
  average SOG at sea; the raw IMO numbers kept beside the derived ones.
- **Deviations proposed (owner to confirm with the review):** D-P9-4 `ref_speed_kn` = IMO's average SOG (the speed the
  consumption was measured at), not the generator's range midpoint of §6a — the tool applies the cube law to the
  vessel's own `service_kn`; D-P9-5 fuel split into `main_t_per_day` (cube law) + `aux_t_per_day` (constant) instead
  of one `fuel_t_per_day`; D-P9-6 extra raw columns (IMO type, bin, unit, days at sea, main / aux kt).
- **Next:** the owner's row-by-row review → then S4 (migration 020 SQL shown + the bunker price row).

### SESSION HANDOFF (2026-10-27, Phase 9 S2 DONE)

- **No commit until Stage 2 closes** (owner, 2026-10-27): keep this handoff current; one commit at the Stage 2 close.
- **S2 closed:** `pipelines/agents/tools/routes.py` (`sea_route`: `origin`, `destination`, `avoid` ⊂ 8 passages,
  `speed_kn`; northwest always closed; length = the generator's rule — port points at both ends + great-circle sum;
  no path / unknown LOCODE → `no_data`; with speed: `sea_days` + `day_points`; shared helpers `ports`, `gc_nm`,
  `sea_path`, `line`, `point_at` for `voyage_status`), `registry.STAGE2["sea_route"]`, `schemas.Source.kind` +
  `"library"` (D-P9-3: searoute is neither a view, a table nor an API). `Stage2_tools_check.py` Phase 1 ✅: 12 route
  cases frozen (Singapore ↔ Rotterdam 8,388.5 / 11,876.7 nm both ways, +1.2 % / +1.0 % vs the published 8,288 /
  11,755; Jeddah 4,036.3 / 11,005.1; Port Said ↔ Rotterdam 3,315.8 with and without Suez; Bab el-Mandeb closed → the
  Cape; Sokhna with Suez closed → `no_data`), 9 single-leg voyages = `route_nm` (|diff| 0.000), 4 bad argument sets
  refused, wrapper = plain function, schema has no user field. Files changed 0.
- **Next: S3** — the parameter CSV `db/reference/vessel_performance.csv` (13 types × 3 SCNT bands, fuel t / day at the
  reference speed from the Fourth IMO GHG Study 2020 annex, reference speed = the generator's range midpoint), every
  row with its source; the owner reviews every row before S4 (migration 020).
- Note: the auto-mode safety check failed intermittently on large edits this session; edits went in small pieces.

### SESSION HANDOFF (2026-10-27, Phase 9 S1 DONE)

- **S1 closed:** the owner added `MONGO_RO_USER` / `MONGO_RO_PASSWORD` to `.env`; Claude ran
  `db/mongo/run.ps1 005_create_reader_user.js` (owner's OK) → user `nilegate_reader`, role `read` on
  `ports_logistics`. `Stage2_tools_check.py` Phase 0 ✅ with the reader (authenticates as itself, role read only,
  reads `ais_positions`, 3 / 3 writes refused with Unauthorized), pending none, files changed 0. `Tools_check.py`
  8 / 8 ✅ (+3b). Fix during the run: pymongo refuses attribute access to a `_`-prefixed collection → `mdb["…"]`.
- **Next: S2 `sea_route`** (`tools/routes.py`, `STAGE2["sea_route"]`, Phase 1 of the check: §6a's route cases).
  The owner commits S1 + the plan / ROADMAP edits of 2026-10-27 first (git is his).

### SESSION HANDOFF (2026-10-27, Phase 9 S1 in progress)

- The owner created the Stage 2 branch from `master` (2026-10-27). **S1 code done:** `tools/context.py`
  (`RunContext.as_of`, default `DATA_AS_OF` = 2026-09-13T00:00Z, must be timezone-aware and ≤ the data;
  `as_of_of(runtime)`; resources `PORTS`, `AIS_TRACKS`), `tools/registry.py` (`STAGE2` empty, filled per step),
  `tools/mongo.py` (read-only client on `MONGO_RO_USER`), `db/mongo/005_create_reader_user.js` (role `read`),
  `db/mongo/run.ps1` (passes `RO_USER` / `RO_PWD`), `.env.example`, `common.SECRET_KEYS` (`MONGO_RO_PASSWORD`),
  `pipelines/scripts/agents/Stage2_tools_check.py` Phase 0 (clock + registry ✅; MongoDB reader pending).
- **Deviations:** D-P9-1 `Stage2_tools_check.py` starts with a Phase 0 (foundation, S1) that §6a did not list — the
  reader's refused write lives there instead of Phase 5; D-P9-2 `db/mongo/run.ps1` changed (not in §6a's file list) to
  pass the reader's credentials without values on the command line.
- **Open in S1:** the owner adds `MONGO_RO_USER` / `MONGO_RO_PASSWORD` to `.env`, then (his OK) Claude runs
  `run.ps1 005_create_reader_user.js` and re-runs the check (Phase 0 must pass with the reader). `Tools_check.py`
  regression after the `RunContext` change: 8 / 8 ✅ + 3b, pending none, files changed 0 (2026-10-27, 126 s).

### SESSION HANDOFF (2026-10-27, Phase 9 design APPROVED)

- **§6a approved by the owner on 2026-10-27, as written** ("موافق على تصميم §6a زي ما هو"). Next: the owner creates the
  Stage 2 branch from `master` and says so; then **S1** (`RunContext.as_of`, `registry.STAGE2`, the read-only Mongo
  user — its script shown and the owner's OK before it runs). The uncommitted plan / ROADMAP edits of 2026-10-27
  go with the first Stage 2 commit.

### SESSION HANDOFF (2026-10-27, Phase 9 design PROPOSED)

- **Phase 9's concrete design is written** in §6a "Concrete design (PROPOSED 2026-10-27)": verified facts F1–F6
  (read-only probes: `searoute` restrictions work — Singapore ↔ Rotterdam 8,383 / 11,871 nm, +1 % vs published;
  **Port Said ↔ Rotterdam never uses the canal** (F1a), so §6's example question changes; the route geometry rebuilds
  to `route_nm` for 498 / 498; `arrival_ts` and `ais_vessels.eta_raw` = the ETA answer key; Open-Meteo past dates +
  wind in kn verified), tools `sea_route`, `vessel_params`, `voyage_status`, `marine_weather`, `RunContext.as_of`,
  migration 020 (`vessel_performance`, `bunker_prices`), a read-only Mongo user, `Stage2_tools_check.py` 6 phases,
  order S1…S9.
- **Waiting for the owner:** decisions P9-5…P9-8 answered 2026-10-27 (all recommended); his approval of §6a as a
  whole is still open. No code yet.
  The owner creates the Stage 2 branch from `master` before S1 (git is his).
- Nothing changed outside this plan and ROADMAP; the probe scripts live in the session scratchpad only.

### SESSION HANDOFF (2026-10-27, STAGE 1 CHECKPOINT DONE → Stage 2 starts)

- **Stage 1 is closed:** PR #1 (`feat/agents` → `master`) merged by the owner on 2026-10-27 (merge `5e49ad6`). Final
  baseline `stage1_eval_2026-10-23_confirm.json` (D7 not met on planted findings only, accepted by C-2); a second run
  of the same code `stage1_eval_2026-10-27_mytest.json` (false alarms 0). After the merge, uncommitted: this handoff,
  §5 row S1 ✔, ROADMAP — the owner commits them with the first Stage 2 change.
- **Live system:** the weekly pack fires every Monday 10:30 local (trigger in local time since D-P8-18); W08 (test,
  rejected), W10–W12 published; Monday 2026-11-02 makes W13 and waits for the owner's approval.
- **D-P8-20 — DECIDED 2026-10-29 by the owner (ADR-052 amendment 2):** run-to-run variance of narrative recall
  (0.07) exceeds ADR-052's 0.03 margin → non-Writer changes are compared on a fixed deck set (the baseline's
  published decks, re-scored), Writer changes on three runs per side; margin 0.03. The fixed-deck mode and `--runs 3`
  in `Stage1_eval.py` are written before the next comparison.
- **Next: Stage 2, Phase 9 (Stage 2 tools)** — decisions answered 2026-10-23 (§6a answers: P9-1 CSV + migration, P9-2
  **no live AIS** (`vessel_live` out, D11 narrowed), P9-3 a dated VLSFO price → SDR, P9-4 `searoute` restrictions else
  two corridors; §7: S2-D1 scheduled `voyage_watch`, S2-D2 rule-based ETA first, S2-D3 = P9-1 + P9-3, S2-D4
  dropped, S2-D5 as proposed). First step: write the concrete Phase 9 design (§6a) as PROPOSED — tools `sea_route`,
  `voyage_status`, `marine_weather`, the vessel parameter table (migration), `Stage2_tools_check.py` — verify the
  facts it depends on first (`searoute` 1.6.0 restriction support, the MongoDB AIS / voyages fields, Open-Meteo
  Marine fields), then the owner's approval before any code. Branch: the owner creates it from `master` (git is the
  owner's).
- `Notebooks/_scratch/` holds Stage 1 leftovers (F7 script, logs, decks, `pr_stage1.md`): the owner may empty it.

### SESSION HANDOFF (2026-10-23, §5f DONE)

- **§5f F1–F9 done.** F7: fallback `nvidia/nemotron-3.5-super-vl:free` (ADR-045 am. 2, D-P8-15). F8: final Stage 1
  baseline `stage1_eval_2026-10-23_confirm.json`, **D7 not met on `planted_all` only** (stopped packs → no deck);
  the scored false alarms were a scorer false positive, fixed by rule (D-P8-16; ADR-053 result + scorer limits;
  ADR-052 fourth use). F9: ADRs 045 / 049 / 052 / 053 / 054, ARCHITECTURE, ROADMAP, CLAUDE.md updated; every check
  green on 2026-10-23 (Tools 10 / 10, Weekly_pack 7 / 7, Deck 4 / 4, Finance_qa 6 / 6, Scheduler 6 / 6, Stage1_eval
  1–4, Golden_weeks / Qa_golden 0 changed). The plan stays active (Stage 2 follows).
- **Next:** (1) the owner runs the ONE commit command (git is blocked for the assistant; no AI attribution);
  (2) the Stage 1 checkpoint PR of `feat/agents` → `master` (owner's go-ahead); (3) Phase 9 — its decisions are
  **answered 2026-10-23** (§6a answers: P9-2 = no live AIS, the rest recommended; §7 S2-D1…S2-D5): write the
  concrete Phase 9 design from them, then start.
- **Follow-up, not a gate:** the Writer's publish rate on the free model (3 of 22 test-week packs stopped by the
  Validator in F8; true positives).
- **Never Save in Power BI** unless the Exceptions page looks right (the owner looks once).

### SESSION HANDOFF (2026-10-22 late, §5f F1–F6 done, F7 open)

- **§5f (APPROVED):** F1 small code ✅, F2 Q&A on `create_agent` + `Finance_qa_check.py` 6 / 6 + CLI ✅, F3 planted
  budget miss (migration 018) ✅, F4 Q&A golden set v2 (42) ✅, F5 tariff Notes rule (migration 019) ✅, F6 Power BI
  Exceptions page ✅ (data verified by DAX; the on-screen look not seen: computer use is blocked by a setting — the
  owner checks W15 = 1 finding INV-0000925 73,950.26; **never Save in Power BI before the commit** unless the page
  looks right). Checks green at the end: Tools_check 10 / 10, Weekly_pack_check 7 / 7 (cached), Deck_check 4 / 4,
  Stage1_eval 1–4 ✅, Scheduler_check 6 / 6, Finance_qa_check 6 / 6, Golden_weeks / Qa_golden 0 changed.
- **F7 open:** retest the fallback on a stable connection — `nvidia/nemotron-3.5-super-vl:free` and
  `dots-studio/dots-3-note-preview:free` (scratch script pattern: force `r._roles["insight"/"writer"]` onto the
  candidate, weeks 5 / 23; OpenRouter free = 50 / day); keep the one that publishes → `roles.py` (replace `NEMOTRON`),
  `Weekly_pack_check` Phase 0 expectations, ADR-045 amendment 2. If none publishes: no fallback, a stopped pack waits
  for the next firing (D-P8-1), recorded.
- **F8:** the confirmation evaluation on the first fresh flash-lite day (after 07:00 UTC):
  `$env:EVAL_REAL_MODELS='1'; $env:EVAL_REPEATS='2'; $env:EVAL_TAG='confirm'; $env:EVAL_BASELINE='stage1_eval_2026-10-22_c3.json'; uv run python tools/run.py pipelines/scripts/agents/Stage1_eval.py --timeout 14400`
  — a measurement (planted gate now 6 / 6, 42 questions, the Q&A on create_agent); its file = the final Stage 1
  baseline; D7 reported as is.
- **F9:** ADRs (045 am. 2, 049 note on 019, 052 `planted_all`, 053 v3 findings / v2 golden set / scorer limits /
  F8 result, 054 `form_fixes`), ARCHITECTURE (Power BI row: 13 DirectQuery tables, 41 measures, 19 relationships,
  Exceptions page; Stage 1 evaluation row; §7 Finance Q&A interface), ROADMAP, CLAUDE.md, the archive of nothing (the
  plan stays active), then ONE commit command for the owner (git is blocked for the assistant; no AI attribution),
  then the Stage 1 checkpoint PR (owner's go-ahead), then the Phase 9 decisions (§6a P9-1…P9-4, §7 S2-D1…D5).

### SESSION HANDOFF (2026-10-22, Phase 8 CLOSED)

- **Phases 0–8 are CLOSED.** Phase 8 = §5e + ADR-054: the Task Scheduler task (registered on the owner's machine,
  Monday 10:30), `Weekly_pack.py scheduled | prune | report`, retention, LangSmith per graph run;
  `Scheduler_check.py` 6 / 6. `.env`: `LANGSMITH_API_KEY`, `PACK_RUN_AS=6` (never `LANGSMITH_TRACING`).
- W11 decided 2026-10-22 (edit + approve by manager 7, published; G5 edit rate 0.5 over W10 + W11). Monday
  2026-10-26 10:30 the task makes W12.
- **Then (owner, 2026-10-22): close every open point first — §5f.** K1 reviews done (13 accepted, 5 changed), K9
  closed; the work is F1…F9 in §5f (PROPOSED, waiting for the owner's go-ahead); the one commit comes after F9;
  Phase 9 design §6a (PROPOSED; S2-D1…D5 + P9-1…P9-4 answered before it starts).
- **Next: the Stage 1 checkpoint** (§5 row "S1 ✔": ADRs / ARCHITECTURE / ROADMAP are current → a PR of
  `feat/agents`, the plan stays active), then the Stage 2 decisions (§7 S2-D1…) before Phase 9.
- **Carry:** the ADR-045 fallback (nemotron 404) — a new fallback for Insight / Writer, chosen and measured
  (ADR-052); `list_runs` deprecation; Q&A tracing (Phase 12); the Phase 7 carries (owner reviews of D-P7-…, skill
  `finance-qa`, the Q&A golden set notes; Power BI Exceptions page; tariff Notes rules).

### SESSION HANDOFF (2026-10-21, Phase 8 S2 done)

- Phase 8 design = §5e (APPROVED 2026-10-20; P8-1…P8-4). **S1 done**, **S2 done** (Progress 2026-10-21,
  D-P8-5…D-P8-8): `tracing.py`, hooks in `Weekly_pack.py` / `scheduling.fire`, `Scheduler_check.py` **6 / 6 ✅**;
  `.env` has `LANGSMITH_API_KEY` and `PACK_RUN_AS=6` (never `LANGSMITH_TRACING`).
- **Then S3 on 2026-10-22 after c3 finishes** (owner decision): `ops/scheduler/register_weekly_pack.ps1` (still to
  write), the owner registers the task, one `Start-ScheduledTask` firing on real models reaches the approval (≈ 6
  calls; toast shown), the owner decides through the CLI, `report` shows it. Then S4 close (ADR-054).
- **Frozen until c3 is judged:** `Stage1_eval.py` (`EVAL_TRACE`), `finance_qa.py` (Q&A tracing), the Validator /
  slots / Writer parts; at most 20 real calls a day, none on 2026-10-22 before c3 finishes. No migration, no new
  package. Commit: the owner.

### SESSION HANDOFF (2026-10-20, Phase 8 S1 done)

- Phase 8 design = §5e (APPROVED 2026-10-20 by the owner, as written; P8-1…P8-4 all recommended). **S1 done**
  (Progress, D-P8-1…D-P8-4): `scheduling.py`, `Weekly_pack.py scheduled | prune | report`, `Scheduler_check.py`
  4 / 4 ✅. **Next: S2 LangSmith** — the owner creates a LangSmith key (free developer plan; note the region: EU →
  `LANGSMITH_ENDPOINT`) and adds `LANGSMITH_API_KEY` + `PACK_RUN_AS=<a Finance manager id>` to `.env`; then
  `pipelines/agents/tracing.py`, `SECRET_KEYS` / `.env.example`, one fake-model run read back with
  `langsmith.Client`. Then S3 (the task registered by the owner, one real firing), S4 close (ADR-054). No migration,
  no new package.

### SESSION HANDOFF (2026-10-20, Phase 7 CLOSED)

- **Phases 0–7 are CLOSED.** Phase 7: ADR-053 (+ ADR-052 first use); golden weeks / findings / Q&A golden set
  frozen; migration 017 (twins); `graphs/finance_qa.py` + skill `finance-qa`; `Stage1_eval.py`; baseline =
  `stage1_eval_2026-10-20_c1.json` (D7 not met: abstention 0.86, traceability 0.996 in one run, publish rate
  10 / 11 and 6 / 11; planted 5 / 5, leakage 0, Q&A EN 0.96 / AR 1.0). Owner closed it with these misses.
- **Next: Phase 8** (§5) — scheduling (Task Scheduler), LangSmith tracing, checkpoint retention; done when a scheduled
  run produces the pack and waits for approval. Start by proposing the Phase 8 design to the owner (AskUserQuestion,
  recommendation first). Mind the quota: flash-lite = 500 free requests / day (a pack ≈ 6 calls).
- **Carry:** candidate **c2 ran 2026-10-21 → rejected by ADR-052** (planted gate regressed; abstention fixed to 1.0 —
  see Progress); c1 stays the baseline; **c3 prepared** (D-P7-13: c2 + Validator date ranges and "amount" for an
  invoice's billed field; D-P7-14: code fixes the slot form before the Validator; Deck_check 4 / 4,
  Weekly_pack_check 7 / 7) → **c3 ran 2026-10-22 and was accepted by the owner (exception to ADR-052) = the baseline
  `stage1_eval_2026-10-22_c3.json`; tuning stopped, c4 not run** (D-P7-15 kept, not measured in a real run); Phase 8
  runs in its own session `agents-phase-8` — run it 2026-10-22 after 07:00 UTC (command
  in Progress); the code is a candidate under test until then. Owner reviews: D-P7-1…D-P7-12, the ADR-052 reading for a failing baseline, skill `finance-qa`
  (`reviewed_by_owner: no`), the Q&A golden set and findings v2, the narrow relevance words (q14, q01_ar) and r04's
  fact pattern; G5 edit rate from real approvals (Phase 8); Tavily monthly credits used up (web_search →
  context_unavailable until the month resets); Power BI Exceptions page; tariff Notes rules.

### SESSION HANDOFF (2026-10-20, Phase 7 S6 in progress)

- **Done (S1–S5 + the S6 baseline):** ADR-052; golden weeks / expected evidence / findings v2 / Q&A golden set all
  frozen (hashes in Progress); migration 017 applied (twins), `finance_kpi` test switch; `graphs/finance_qa.py` +
  skill `finance-qa` (owner review pending); `Stage1_eval.py` (Phases 1–4 ✅, 0 calls); baseline
  `stage1_eval_2026-10-19.json`: **D7 NOT MET** (packs 4 / 11 and 8 / 11 published, planted 2 / 5 and 1 / 5; Q&A
  strong: EN 0.91 / 0.96, AR 1.0, leakage 0). Validator false alarms fixed (D-P7-9, Deck_check 4 / 4), Q&A prompt
  lines (D-P7-10), quota guard (D-P7-11: flash-lite = 500 requests / day → one full evaluation per day).
- **c1 kept (ADR-052 "keep (better)") = the baseline now** (`stage1_eval_2026-10-20_c1.json`): planted 5 / 5, recall
  0.69, Q&A EN 0.96 / AR 1.0, leakage 0; D7 still not met (abstention 0.86 — r03's status; traceability 0.996 in one
  run; publish rate 10 / 11 and 6 / 11). **c2 prepared (D-P7-12), not run** (quota). Next: run c2 on a fresh provider
  day (command in Progress), then the owner decides (accept with the misses documented, or more Writer work — §5 "or
  the owner decides"), S7 close.
- **For the owner's review:** D-P7-1 … D-P7-11 (Progress), the ADR-052 reading for a failing baseline, skill
  `finance-qa`, the Q&A golden set and findings v2, the q14 relevance note.
- Checks now: Tools_check 10 / 10, Weekly_pack_check 7 / 7 (cached), Deck_check 4 / 4, Golden_weeks 3 / 3,
  Qa_golden 4 / 4, Stage1_eval 1–4 ✅.

### SESSION HANDOFF (2026-10-19, Phase 7 S1 done)

- **Phase 7 design = §5d (APPROVED 2026-10-19; §8a G1–G6 reviewed, P7-1…P7-4 all recommended).** ADR-052 (G6
  acceptance rule) written. S1 done: `Golden_weeks.py` ✅ 3 / 3, 11 golden weeks frozen (`golden_weeks.json`),
  expected findings v1 reviewed and frozen (`golden_findings.json`, 34 findings); test weeks' expected evidence waits
  for migration 017.
- **Next: S2** (§5d order): `db/migrations/017_finance_test_kpi.sql` → the owner applies (the assistant refreshes
  the snapshot and runs `verify_readonly.sql` with a new section) → `finance_kpi` reads the twins in a test run
  (`kpi_evidence(user, week, dataset)`), `Tools_check` case → re-run `Golden_weeks.py` → findings v2 (test drivers).
  Then S3 the Q&A golden set (30 EN + 10 AR, owner review).

### SESSION HANDOFF (2026-10-19, Phase 6 CLOSED)

- **Phases 0–6 are CLOSED.** Phase 6: ADR-051; `pipelines/agents/deck/` (slots, Validator v2 V1–V7, template as code,
  renderer, read-back V8, the sample slot draft), `weekly_pack.py` on it (slot Writer, `DeckPatch` rewrites, preview
  in `reports/_drafts/`, `deck.pptx` published), the skills `deck-style-guide` / `number-validation` rewritten
  (owner-reviewed). Checks: `Deck_check.py` 4 / 4 (100 / 100 planted numbers), `Weekly_pack_check.py` 7 / 7 (Phase 5
  only with `PACK_REAL_MODELS=1`; cached: 0 calls), `Tools_check.py` 8 / 8.
- **Next: Phase 7** (§5) — evaluation (§8) on golden weeks + finance Q&A golden questions; done when the D7
  thresholds are met (or the owner decides). Start by proposing the Phase 7 design to the owner (AskUserQuestion,
  recommendation first); first get the owner's review of §8a (G1–G6, still PROPOSED). Inputs: the Writer quality
  notes of S6 (redundant "up +x %", a context bullet emptied by a patch, adjectives in titles; real runs publish 3–4
  of 4 weeks: variance), the planted budget miss in `finance_test.budget_weekly` (needs a way to read it), G6 as an ADR
  before the first comparison.
- **Carry:** Power BI Exceptions page from `finance.invoice_audit`; tariff Notes rules; Phase 8: scheduling,
  LangSmith, checkpoint retention, the free daily limit of flash-lite (watch it); temp folders left by failed check
  runs (`%TEMP%\weekly_pack_check_*`) can be deleted.

### SESSION HANDOFF (2026-10-19, Phase 5 CLOSED) — read this first in the next session

- **Phases 0–5 are CLOSED.** Phase 5: ADR-050; `pipelines/agents/graphs/weekly_pack.py` (+ `models.py`),
  `pipelines/agents/roles.py` (ADR-045 amendment 1: the pack's Insight / Writer on Gemini flash-lite + OpenRouter
  nemotron), `pipelines/agents/checkpointer.py`; migration 016 (`agent_state`, `agent_writer`, login `ports_agent`);
  CLI `pipelines/scripts/agents/Weekly_pack.py`; `Weekly_pack_check.py` 7 / 7 (real phase cached: 0 model calls).
- **Phase 6 design = §5c (APPROVED 2026-10-19, P6-1…P6-8 all recommended). S1 done (`deck/slots.py`), S2 done
  (`deck/validator.py`), S3 done (`deck/style.py`, `render.py`, `readback.py` = V8; Deck_check 4 / 5 ✅, 100 / 100
  planted numbers caught in drafts and files), S4 done (the graph on slots / patch / V1–V8 / preview / `deck.pptx`;
  Weekly_pack_check 6 / 7 ✅, Phase 5 at S6 with `PACK_REAL_MODELS=1`); S5 done (the two skills rewritten for slots,
  approved by the owner); next S6 — real models (Progress, last entry).**
- **Next: Phase 6** (§5) — PPTX template (NileGate style) + Writer + Validator; done when the Validator catches every
  planted wrong number in a test deck. Start by proposing the Phase 6 design to the owner (AskUserQuestion,
  recommendation first). Inputs from Phase 5 (S6 Progress): the Writer drops signs next to direction words and
  sometimes cites the wrong dataset (weeks 5 / 23 `validation_failed`); the Validator matches a number against any
  numeric field of the cited evidence — bind numbers to fields (G1 of §8a); the full template allowlist (titles,
  footnotes); the Writer prompt is 12–17K tokens (fine on Gemini; the free daily limit of flash-lite is not
  published — watch it); `DeckDraft` → PPTX rendering with charts from the same evidence.
- **Carry into later phases:** Phase 7 needs a way to read the planted budget miss (`finance_test.budget_weekly`);
  Power BI Exceptions page from `finance.invoice_audit`; tariff Notes rules not modelled by the audit; Phase 8:
  scheduling, LangSmith, checkpoint retention (`agent_writer` has DELETE for it), the first real thread
  `weekly_pack:live:2025-W10:1` stays in `agent_state`.
- Still open from before: the owner's review of §8a (G1–G6, PROPOSED).

### SESSION HANDOFF (2026-10-19, Phase 4 CLOSED)

- **Phases 0–4 are CLOSED.** Phase 4: ADR-049; six tools in `pipelines/agents/tools/` (`registry.STAGE1_TOOLS`),
  migration 015 (audit views), six reviewed skills + `skill_loader.py`, `Tools_check.py` 8 / 8.
- **Phase 5 design = §5b (PROPOSED 2026-10-19, decisions P5-1…P5-8 answered); implement after the owner approves
  §5b, starting at S1.**
- **Next: Phase 5** (§5) — the LangGraph `weekly_pack` StateGraph (Data Readiness → KPI → Auditor → Insight → Writer
  → Validator → interrupt → Publisher, §3), PostgresSaver in a schema `agent_state` with a writer role (a migration:
  ask the owner), resume after a crash. Bind `registry.STAGE1_TOOLS`; pass `RunContext(user)` (and
  `dataset="test"` only in the evaluation harness); each node loads its fixed skill with `skill_loader.load`. Start
  by proposing the Phase 5 design to the owner (AskUserQuestion, recommendation first).
- **Carry into later phases** (Progress above): Phase 6 Validator = digits of tool numbers from structured fields
  only, template text allowlisted, the Writer always "Draft for approval"; Phase 7 needs a way to read the planted
  budget miss (`finance_test.budget_weekly`); Power BI Exceptions page from `finance.invoice_audit`; token budget of
  `search_documents` against Groq's 8K TPM; tariff Notes rules not modelled by the audit.
- Still open from before: the owner's review of §8a (G1–G6, PROPOSED).
- Then close Phase 4 (ROADMAP: CLOSED; the owner commits) and start **Phase 5** (LangGraph workflow + PostgresSaver,
  `agent_state` schema + writer role = a migration, interrupt). Phase 5 binds `registry.STAGE1_TOOLS` and passes
  `RunContext(user)` as the graph's context.
- Still open from before: the owner's review of §8a (G1–G6, PROPOSED).

### SESSION HANDOFF (2026-10-15, Phase 3 CLOSED)

- **Phases 0–3 are CLOSED.** Phase 3 (2026-10-15): ADR-048; `powerbi/NileGate_Finance.pbip` — DirectQuery on the
  `finance` views via `ports_bi`, model by the Power BI Modeling MCP (38 thin measures, 1 label column, 18
  relationships), 5 pages with one synced week slicer (Exceptions = placeholder). Owner to commit the whole phase.
- **Next (assistant): Phase 4** (§5) — Stage 1 tools (§3) + tests: the finance KPI tool reading the `finance` views by
  `report_week` (same numbers as the dashboard), the Auditor tool over the invoices vs the tariff (it fills the
  Exceptions page later), external tools behind a cache and a timeout ("context unavailable", never a guess); the
  skill loader + the Stage 1 skills in `pipelines/agents/skills/`. Done when each tool is tested on its own, the RBAC
  matrix shows 0 leakage, every skill parses (frontmatter, size budget) and is reviewed by the owner. Start by
  re-reading §3 and §4 R7 (`finance_test`), then propose the tool list and interfaces to the owner (AskUserQuestion,
  recommendation first). Still open: the owner's review of §8a (G1–G6, PROPOSED).
- **Power BI notes for later phases:** open the PBIP only with PostgreSQL up (containers restart with Docker now);
  after MCP edits clear the "refresh manually" banner, then File → Save and check file times in `powerbi/`; a new
  page must be added to the slicer's sync group (View → Sync slicers, select the slicer on Overview first).

### SESSION HANDOFF (2026-10-15, Revenue page done)

- **State:** the semantic model is complete and saved in `powerbi/` (12 tables, 18 relationships, 36 measures in
  `Weekly KPIs`, display folders per page; see Progress 2026-10-14 "Phase 3 model built"). Verified by DAX for weeks
  5 / 23 / 49 = `kpi_weekly`. **Pages 1 Overview and 2 Revenue done and checked** (Progress "Page 1 Overview built",
  "Page 2 Revenue built"); 37 measures (36 + `Category Billed SDR`). Full review 2026-10-15: every number of both
  pages = `finance.kpi_weekly` read straight from PostgreSQL for W05 / W23 / W49 (billed, invoices, budget, AR, DSO;
  revenue via invoices, categories, laden + ballast and bands all sum to billed); both slicers in sync group
  `iso_week_label` with the "is not (Blank)" filter saved. Owner to commit (the assistant never runs git).
- **Next (the assistant builds on screen by computer use and explains each visual's data, owner watches; the MCP cannot
  build report visuals):** pages 4–5 of §2, one page at a time; add each new page to the slicer in View → Sync
  slicers (select the slicer on Overview first); (1) Overview: DONE; (3) Receivables: DONE 2026-10-15; (2) Revenue: DONE — `Revenue SDR` by vessel category, laden /
  ballast (`Invoices[priced_condition]`), band, route + `Trend Billed SDR` over `Weekly Trend[trend_week_label]`;
  (3) Receivables: `AR by Bucket SDR` by `AR Snapshot[aging_bucket]`, DSO, `Collections SDR`, the Overdue List table;
  (4) Customers: top 10 from `Customer KPIs 13w` (`is_top10`, `rank_13w`), `Top10 Share 13w %`; (5) Exceptions:
  placeholder until the Auditor tool (Phase 4 / 7) — owner decision P3-11. Before closing Desktop after MCP edits: clear the "refresh
  manually" banner, then File → Save, and check file times in `powerbi/`. Done when the page numbers for weeks 5, 23,
  49 = `kpi_weekly` (then close Phase 3: ROADMAP, ARCHITECTURE §, ADR if needed).

### SESSION HANDOFF (2026-10-14, Phase 3 in progress)

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
