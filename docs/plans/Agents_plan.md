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

### SESSION HANDOFF (2026-10-19, Phase 4 CLOSED) — read this first in the next session

- **Phases 0–4 are CLOSED.** Phase 4: ADR-049; six tools in `pipelines/agents/tools/` (`registry.STAGE1_TOOLS`),
  migration 015 (audit views), six reviewed skills + `skill_loader.py`, `Tools_check.py` 8 / 8.
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
