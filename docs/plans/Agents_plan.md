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

### 6a. Phase 9 — Stage 2 tools: concrete design (PROPOSED 2026-10-22; decisions S2-D1…S2-D5 + P9-1…P9-4 to answer before it starts)

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

**Checks:** `Stage2_tools_check.py` (each tool against its source; hand-computed routes Port Said → Rotterdam both
ways; RBAC matrix extended; failure modes: no key, timeout, bad input). **Not in Phase 9:** the `route_advice` and
`voyage_watch` graphs (Phases 10–11).

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

### SESSION HANDOFF (2026-10-23, §5f DONE) — read this first in the next session

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
