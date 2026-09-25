> **ARCHIVED — historical record, not a source of truth.**
> First architecture proposal ("Data Analyst Agent" / NileGate), pasted from another assistant session. Its pgvector-first recommendation was not adopted (Qdrant + MongoDB were chosen, ADR-001). DuckDB, Redis and the star schema are deferred (ADR-018). Long-term ideas (tool registry, guardrails, evaluation, observability) are tracked in docs/ROADMAP.md.
> Current sources of truth: the project rules, `ARCHITECTURE.md`, `docs/`.

---

We are starting a production-oriented AI project called: \*\*Data Analyst Agent\*\*…

Worked for 1m 18s

## Data Analyst Agent — Architecture Proposal

Build this initially as a modular monolith: one deployable application with clear internal boundaries. This keeps the MVP practical while preserving paths to scale specific components later.

### 1. Overall system architecture

```
API/UI
  → Application services
    → Agent orchestrator
      → Controlled tools
        → Analytics data | RAG | Power BI | Python sandbox
    → Guardrails, audit, observability, evaluation
```

- **Agents** make decisions and compose an analysis plan.
- **Tools** perform deterministic, permissioned actions.
- **Services** implement reusable business logic, such as semantic metric definitions and SQL validation.
- **Infrastructure** hosts databases, vector search, queues, secrets, and deployment runtime.

This division prevents an LLM from directly operating critical systems.

### 2. Agent architecture and responsibilities

Start with a **Supervisor** and a single **Analytics Agent**. Add specialist agents only where toolsets and evaluation needs justify them.

| AgentResponsibilityBoundary |                                                                                    |                                                        |
| --------------------------- | ---------------------------------------------------------------------------------- | ------------------------------------------------------ |
| Supervisor                  | Routes requests, owns workflow/state, delegates and synthesizes the final response | Does not query data directly                           |
| Analytics Agent             | Plans analysis, interprets results, requests SQL/Python tools                      | Cannot execute unrestricted code or access credentials |
| Knowledge Specialist        | Retrieves and evaluates company-policy/operational knowledge                       | Cannot assert numerical facts without sources          |
| Power BI Specialist         | Translates report/model questions into approved Power BI queries                   | No direct API credentials or unrestricted refreshes    |
| Validator                   | Checks grounding, calculations, citations, policy compliance                       | Does not replace the primary analysis                  |

The Validator can initially be a deterministic validation service plus optional LLM critique, rather than a permanently independent agent.

### 3. Cooperation and state flow

Use a typed task state rather than free-form agent chat.

```
Request
 → classify and authorize
 → Supervisor creates AnalysisTask
 → plan: data / knowledge / Power BI needs
 → tool calls produce evidence artifacts
 → Analytics Agent interprets artifacts
 → Validator checks answer + evidence
 → sourced response
```

An `AnalysisTask` should retain: user context, permissions, normalized request, plan, tool-call records, evidence IDs, intermediate findings, budget limits, and final answer. Agents exchange structured messages, references to artifacts, and confidence—not raw hidden reasoning.

### 4. Tool architecture

Expose a small tool registry with explicit contracts:

- `query_analytics_data`: read-only parameterized SQL over approved views.
- `run_analysis`: constrained Python jobs on tool-produced data only.
- `retrieve_knowledge`: hybrid search with filters and citations.
- `query_powerbi`: execute approved semantic-model queries.
- `inspect_powerbi_metadata`: schemas, reports, measures, lineage.
- `render_visualization`: deterministic charts/tables from validated results.

Each tool should declare input schema, output schema, authorization scope, timeout, cost limit, audit fields, and idempotency behavior. Tools belong below agents because their actions must remain deterministic and independently testable.

### 5. Data architecture

Use a warehouse-centered analytical model:

- **Operational source layer:** synthetic shipments, containers, customers, vessels, routes, ports, milestones/events, incidents, delays, invoices, and costs.
- **Canonical layer:** validated and normalized entities with stable IDs and change history.
- **Analytics layer:** star schema for BI and agent querying.

Core facts: Shipment Event, Container Movement, Delay, Cost, Incident.
Core dimensions: Date, Customer, Container, Vessel, Route, Port, Carrier, Delay Reason.

Use incremental ingestion with source metadata, load timestamps, data-quality checks, and lineage. Public maritime datasets should remain separately versioned and clearly labeled as external.

### 6. Dynamic RAG architecture

RAG is a knowledge pipeline, not conversation history.

```
Documents/connectors
 → change detection
 → parsing + metadata extraction
 → chunking
 → embeddings/index + keyword index
 → hybrid retrieval + reranking
 → cited passages
```

Every chunk needs document ID, version, source, owner, access classification, effective dates, checksum, and ingestion timestamp. Updates should re-index only changed content; deletion events must remove or tombstone relevant chunks. Retrieval must filter by user authorization before ranking.

### 7. Power BI integration

Treat Power BI as an external analytics platform:

- Metadata service retrieves workspaces, semantic-model schemas, measures, report metadata, and lineage.
- Query service runs constrained DAX/semantic queries against approved models.
- Refresh/write operations are separate privileged workflows requiring explicit approval.
- Map business metrics to a shared semantic glossary so SQL and Power BI answers mean the same thing.

Keep Power BI tokens and API details inside the integration adapter, never in prompts or agent state.

### 8. Memory architecture

Use three separate layers:

- **Working state:** short-lived, task-scoped state held by the orchestrator.
- **Long-term memory:** narrowly scoped, user-approved preferences or reusable organizational context only when justified.
- **RAG knowledge:** governed document corpus with citations and lifecycle management.

Do not use long-term conversational memory as a source of business truth.

### 9. Guardrails and security

Architectural controls should include:

- Authentication, role-based access, and row/column-level data policies.
- Read-only SQL by default, allowlisted views, AST-based query validation, row/time limits.
- Isolated Python execution with no network, restricted packages, quotas, and ephemeral storage.
- Tool authorization per task and per user.
- PII classification, redaction policies, and audit logging.
- Prompt-injection defenses: treat retrieved text as untrusted data, not instructions.
- Output checks for unsupported claims, missing citations, data leakage, and unsafe actions.
- Explicit approval workflows for refreshes, exports, writes, or sensitive analysis.

### 10. Evaluation architecture

Keep evaluation data and runs independent from development data.

Evaluate:

- Routing and delegation decisions.
- SQL/DAX correctness and execution success.
- Calculation correctness against known answers.
- RAG retrieval precision, citation coverage, and grounded answer quality.
- Power BI task success.
- Guardrail enforcement and prompt-injection resilience.
- Latency, cost, and regression over time.

Create versioned NileGate “golden tasks” with fixtures, expected outputs, allowed evidence, and pass criteria. Run them in CI before promoting prompts, tools, datasets, or model configurations.

### 11. Observability

Implement a shared trace ID across API request, orchestration, tools, retrieval, and model calls.

Capture:

- Task route and agent decisions.
- Tool parameters, redacted outputs, retries, and failure classes.
- Retrieval queries, selected chunks, and citations.
- SQL/DAX/Python execution metrics.
- Latency, token use, model cost, and budgets.
- Guardrail decisions and approvals.
- Evaluation-run metadata and outcomes.

This belongs across all layers because failures in AI systems are often interactions between layers, not isolated model errors.

### 12. Deployment and infrastructure

For local development:

- Docker Compose for API, database/warehouse emulator, vector store, and observability dependencies.

For production:

- Containerized modular monolith behind an API gateway.
- Managed relational/warehouse and object storage.
- Managed secrets and identity provider.
- Background worker/queue for ingestion and long-running analysis.
- Kubernetes only when operational scale, availability, or worker scaling requires it.

Avoid splitting agents into microservices until scaling, ownership, or security isolation creates a concrete need.

### 13. Recommended stack and trade-offs

| AreaMVP recommendationWhy / trade-off |                                             |                                                                         |
| ------------------------------------- | ------------------------------------------- | ----------------------------------------------------------------------- |
| API                                   | Python + FastAPI                            | Strong data/AI ecosystem; Python runtime discipline needed              |
| Data                                  | PostgreSQL + dbt-style transformations      | Simple, SQL-native; move large workloads to a warehouse later           |
| Analytics                             | DuckDB for local/sandboxed analysis         | Fast analytical queries; not the primary shared operational store       |
| Orchestration                         | Typed Python workflow/state machine         | Testable and provider-neutral; less “magic” than agent frameworks       |
| RAG                                   | PostgreSQL + pgvector initially             | Fewer moving parts; dedicated vector DB later if scale demands it       |
| Jobs                                  | Redis-backed worker queue                   | Practical ingestion/background tasks; introduces operational dependency |
| Power BI                              | Microsoft REST/XMLA integration adapter     | First-class integration; licensing/tenant configuration constraints     |
| Observability                         | OpenTelemetry-compatible traces and metrics | Avoid vendor lock-in                                                    |
| LLM                                   | Provider adapter supporting OpenAI first    | Strong capability; requires robust cost/fallback controls               |
| Identity/secrets                      | Enterprise IdP + managed secret store       | Necessary for production; adds setup overhead                           |

### 14. Proposed project structure

```
data-analyst-agent/
  docs/
    architecture/
    adr/
    data-contracts/
    evaluation/
  apps/
    api/
    worker/
  src/
    orchestration/
    agents/
    tools/
    services/
    data/
    rag/
    powerbi/
    security/
    observability/
    evaluation/
  tests/
    unit/
    integration/
    e2e/
    evals/
  infra/
    docker/
    compose/
    kubernetes/
  configs/
  migrations/
```

Use Architecture Decision Records (`docs/adr`) for choices likely to evolve: warehouse, vector store, orchestration library, and Power BI access model.

### 15. MVP versus future architecture

**MVP**

- One Supervisor and one Analytics Agent.
- Synthetic NileGate data in PostgreSQL.
- Read-only validated SQL and constrained Python.
- Small document corpus with dynamic ingestion basics.
- Power BI metadata/query adapter stub or limited read-only integration.
- Citations, audit trail, basic evaluations, Docker Compose.

**Later**

- Dedicated Power BI and Knowledge specialists.
- Real/public data feeds and incremental pipelines.
- Semantic metric catalog and cross-system lineage.
- Advanced reranking, event-driven document connectors.
- Approval workflows, tenant-level authorization, advanced evaluation dashboards.
- Horizontal worker scaling and Kubernetes.

### 16. Main risks and trade-offs

- **Premature multi-agent complexity:** begin with one orchestrator and limited specialists; prove value with evaluations.
- **Metric inconsistency across SQL and Power BI:** mitigate through a governed business glossary and semantic contracts.
- **LLM-generated query risk:** never permit raw unrestricted execution; validate and constrain every tool call.
- **RAG staleness and access leakage:** version documents, enforce retrieval-time authorization, and support deletions.
- **Synthetic-data realism:** design against real operational relationships and validate scenarios with domain experts before relying on generated conclusions.
- **Power BI integration constraints:** tenant configuration, licensing, and semantic-model permissions may determine feasible query paths.
- **Evaluation debt:** build golden tasks early; otherwise quality regressions become invisible.
- **Cost/latency:** enforce budgets, cache safe metadata/retrieval results, and reserve expensive multi-step workflows for complex questions.

The key recommendation is to make the initial system a governed analytics platform with agentic orchestration—not a collection of autonomous agents. That gives NileGate a credible MVP while keeping specialized agents, public data feeds, and production scale as deliberate next steps.

3:26 PM

Ask for approval

5.6 TerraMedium

IDE context

Work locallyLocal