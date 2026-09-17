# Ports & Logistics AI — Master Checkpoint

## 0. Purpose

This is the hand-off document for the next ChatGPT session. It records the completed work, final decisions, current database state, deferred business rules, RAG architecture, future phases, and the exact starting point for the next session.

**Working style:** The assistant guides and explains; the user executes commands/code and reports outputs. Continue strictly step-by-step. Do not rebuild completed PostgreSQL work unless validation proves it is necessary.

**Review pass applied to this version — 6 corrections, none require rebuilding PostgreSQL:**

1. Resolved an internal contradiction: Section 4 said the Special Floating Units definition "belongs in the RAG knowledge layer," but Section 8 excluded the Suez tariff from the RAG corpus entirely. Fixed by adding the Suez Canal Tolls PDF **Notes section only** (not the numeric tables) as a 6th RAG source.
2. `LPI.pdf` (the report with actual indicator data and the Egypt benchmark example) was missing from the RAG file inventory — only `LPI_Methodology.pdf` was listed. Both are now tracked as separate, required files.
3. **Correction to this correction**: the "24 USCG reports" figure was flagged as unverified in the previous review pass. That flag was itself wrong — the 24 reports are real and sourced directly from the official USCG Marine Casualty Reports page (`dco.uscg.mil/.../Marine-Casualty-Reports/`). Confirmed count restored to 24. See also the added distinction in Section 9 between these real reports and the separately-planned synthetic incident reports — they serve different purposes and neither replaces the other.
4. Normalized a few filenames to match what is actually on disk (`MSC-MEPC_3-Circ_4-Rev_1.pdf`, `Transit_Dues_Rates.pdf`) instead of slightly different earlier spellings.
5. Made the `sensitivity_level` design explicit: it is a numeric ceiling (1/2/3, matching the three roles), not the named-array scheme (`public`/`internal`/`confidential`/`executive`) considered earlier. This is now stated as final, not ambiguous.
6. Updated the next-session paste-in message (Section 25) to reflect corrections 2 and 3 instead of repeating the unverified figures.

---

## 1. Final project goal

Build a Ports & Logistics AI system for learning and job readiness, combining:

- Structured operational data
- Semi-structured operational data
- Unstructured business knowledge
- Live/current information
- AI agents
- RBAC/security
- Evaluation
- Observability

Final high-level architecture:

```text
Structured        Semi-structured       Unstructured
PostgreSQL        MongoDB               Qdrant
+ PostGIS

       +-------------- Governed Tool Layer --------------+
                              |
                       Supervisor Agent
                              |
                       Analytics Agent
                              |
                    SQL / RAG / Web / Analysis
```

**Final vector database decision: Qdrant.**

We intentionally use a dedicated vector database because the project is educational/job-oriented and should also be ready for a larger RAG corpus. PostgreSQL remains the relational system of record; Qdrant owns vector retrieval.

---

## 2. Original data plan

### Structured → PostgreSQL/PostGIS

| Source | Target | Purpose |
|---|---|---|
| attributed_ports.geojson | ports | Primary geographic reference |
| port_flows.shp/.dbf | port_connections | Port-to-port network |
| Suez Canal Tolls PDF | toll_rate_bands | Real pricing reference (SDR only, no currency-conversion table) |

The ports dataset provides the geographic reference. Related operational entities use LOCODE.

### Semi-structured → MongoDB

| Source | Purpose |
|---|---|
| ais_data.json | Real vessel/NAVSTAT diversity |
| NOAA_AccessAIS.csv | Movement physics: speed, direction, stops |
| IFTMIN_D12A_sample.edi | EDIFACT structure/template |

### RAG → Qdrant

Core corpus:

1. HbR Annual Report
2. LPI — **two separate files, both required**: `LPI.pdf` (Connecting to Compete 2025 — contains the actual indicator data, including a real Egypt benchmark example) and `LPI_Methodology.pdf` (methodology/user guide only, no indicator figures). Do not treat them as one document.
3. IMO MSC-MEPC Circular
4. USCG BOIR reports — **24 real reports**, sourced from the official USCG Marine Casualty Reports page (`https://www.dco.uscg.mil/Our-Organization/Assistant-Commandant-for-Prevention-Policy-CG-5P/Inspections-Compliance-CG-5PC-/Office-of-Investigations-Casualty-Analysis/Marine-Casualty-Reports/`). Ingested as-is — real historical incidents, not tied to this project's synthetic vessels/ports. See Section 9 for how these differ from the separately-planned synthetic incident reports.
5. FBL Template
6. **Suez Canal Tolls PDF — Notes section only** (not the numeric tables, which already live in `toll_rate_bands`). Added because it is the only place the OBO/Combined-Carrier rule, the inspection-refusal rule, the Oil/Chemical Tanker mapping, and the Special Floating Units definition exist in writable form. Without it, none of the Section 7 deferred business rules are retrievable by an agent, even as unautomated reference text.

RAG metadata should support document identity, version, source, ownership, department, sensitivity/access classification, effective dates, checksum, ingestion timestamp, page and chunk information.

---

## 3. Completed phases

### Phase A — Docker + PostgreSQL/PostGIS — COMPLETE

Container: `ports-postgres`

Image: `postgis/postgis:16-3.5`

Database: `ports_logistics`

Volume: `ports-postgres-data`

Port: `5432`

Useful commands:

```powershell
docker start ports-postgres
docker exec -it ports-postgres psql -U postgres -d ports_logistics
```

PostGIS is installed and working.

### Phase B — Ports — COMPLETE

Source: `attributed_ports.geojson`

Original features: 856

After deduplicating LOCODE: 837

Table:

```sql
ports(
    locode VARCHAR(5) PRIMARY KEY,
    name TEXT NOT NULL,
    country TEXT NOT NULL,
    function CHAR(8) NOT NULL,
    status CHAR(2) NOT NULL,
    outflows DOUBLE PRECISION NOT NULL,
    lon DOUBLE PRECISION NOT NULL,
    lat DOUBLE PRECISION NOT NULL,
    geom GEOMETRY(Point, 4326) NOT NULL
)
```

Validation completed: no nulls, no duplicate LOCODEs, valid coordinates and PostGIS geometry.

### Phase C — Port connections — COMPLETE

Source: `port_flows.shp/.dbf`

Original rows: 20,554

After exact duplicate removal: 19,990

Table:

```sql
port_connections(
    port1_locode VARCHAR(5) NOT NULL,
    port2_locode VARCHAR(5) NOT NULL,
    flows DOUBLE PRECISION NOT NULL,
    country1 TEXT NOT NULL,
    country2 TEXT NOT NULL,
    geom GEOMETRY(LineString, 4326) NOT NULL,
    PRIMARY KEY (port1_locode, port2_locode),
    FOREIGN KEY (port1_locode) REFERENCES ports(locode),
    FOREIGN KEY (port2_locode) REFERENCES ports(locode)
)
```

Validation completed: valid LOCODE FKs, LineString geometry, SRID 4326, non-null geometry.

---

## 4. Suez Canal toll modeling — COMPLETE

Source: Suez Canal Authority Transit Dues Rates, applicable from 1 January 2023.

The source uses **Suez Canal Net Tonnage (SCNT) SDR/SCNT**.

Rates are progressive bands, not a single flat rate.

Typical bands:

- First 5000
- Next 5000
- Next 10000
- Next 20000
- Next 30000
- Next 50000
- The Rest

Containerships additionally has `Next 60000`.

Table: `toll_rate_bands`

Rows: 177

Categories: 13

Fields include:

- vessel category
- Laden/Ballast
- band order
- band label
- minimum tons
- maximum tons
- SDR per ton

Conceptual calculation:

```text
total_toll = sum(rate_per_band × tonnage_inside_that_band)
```

**Removed:** an earlier version of this schema included an `accepted_currencies` table (10 payment currencies from the source PDF). It has been dropped — the database now keeps every amount in SDR only and does not model currency conversion at all. If multi-currency invoicing is needed later, that is a new decision, not a restoration of this table.

### Important business rules from the source

1. Ballast Petroleum Product Tankers → ballast Crude Oil Tanker rates.
2. Ballast Oil/Chemical Tankers → ballast Crude Oil Tanker rates.
3. Laden Combined Carriers/OBO → cargo-dependent rates; if multiple cargo types, use the highest applicable rate.
4. Ballast OBO → ballast Dry Bulk Vessel rates.
5. Refusal/abstention from transit inspection → use Suez Canal Gross Tonnage and collect applicable additional charges.
6. Special Floating Units include yachts, dredgers, rigs, floating docks, fishing vessels, navy ships, tugboats, research vessels and other specialized non-cargo/passenger floating units.
7. Actual vessel condition at transit controls the applicable dues.

OBO and inspection-refusal logic were deliberately not forced into the current synthetic schema. They are future business-rule scenarios.

### Review note (this pass)

These deferred items do not block the RAG phase — they are an isolated, non-breaking gap in the `invoices` pricing logic, unrelated to document ingestion. The one thing they do require: the source text describing them (Suez Canal Tolls PDF Notes) must be added to the RAG corpus so they stay retrievable as reference even while unautomated. That correction is applied in Sections 2, 8 and 9 below.

---

## 5. Synthetic operational database — COMPLETE

### Departments

5 rows:

- Operations
- Customs
- Finance
- HR
- IT

### Roles

| Role | Allowed sensitivity |
|---|---:|
| employee | 1 |
| manager | 2 |
| ceo | 3 |

Roles are not directly tied to departments. Employees reference both role and department.

### Employees

100 total:

- 1 CEO
- 10 managers
- 89 employees

Generated reproducibly with a fixed Faker seed.

### Vessels

500 rows.

Fields include:

- IMO number
- vessel name
- vessel type
- flag country
- SCNT
- origin LOCODE
- destination LOCODE
- condition
- status

Origins and destinations reference real ports.

### Containers

1,000 rows.

Fields include:

- container number
- container type
- size
- status
- vessel ID
- origin LOCODE
- destination LOCODE

Containers are linked to vessels.

### Invoices

1,000 rows.

Current schema:

```sql
invoices(
    invoice_id SERIAL PRIMARY KEY,
    invoice_number TEXT NOT NULL UNIQUE,
    vessel_id INT NOT NULL REFERENCES vessels(vessel_id),
    toll_rate_band_id INT REFERENCES toll_rate_bands(id),
    invoice_date DATE NOT NULL,
    scnt_tons NUMERIC NOT NULL,
    rate_sdr_per_ton NUMERIC,
    amount NUMERIC NOT NULL,
    description TEXT,
    status TEXT NOT NULL
)
```

**Decision:** `invoices` is a General Invoices table, not a dedicated Suez-invoice table.

The `currency` column was intentionally removed.

`toll_rate_band_id` was retained as a reference to the pricing band used as a pricing source for generated invoices.

`amount` is the full progressive calculated amount.

`rate_sdr_per_ton` is the applicable terminal band rate, not an average rate for the entire vessel.

Validation completed: 1,000 rows, unique invoice numbers, valid vessel/band IDs and no missing required pricing values.

---

## 6. Current public business tables

Expected business tables:

```text
containers
departments
employees
invoices
port_connections
ports
roles
toll_rate_bands
vessels
```

`accepted_currencies` was dropped (see Section 4) — not part of the current schema. All monetary values are SDR only.

PostGIS system tables also exist. Do not delete `spatial_ref_sys` or other PostGIS system tables.

---

## 7. Settled corrections and decisions

### SDR vs USD

Correct as-is. Tariff rates are denominated in SDR/SCNT, and every stored/calculated amount stays in SDR — no currency conversion or accepted-currency list is modeled (that table was dropped, see Section 4/6). Do not reintroduce USD conversion without an explicit decision to do so.

### Progressive tiers

Correctly modeled. Do not replace them with one rate per vessel.

### Ballast Petroleum Product Tanker

Source explicitly maps it to ballast Crude Oil Tanker rates. Numerical rates already align where applicable; explicit generator mapping can be added later for semantic clarity.

### Ballast Oil/Chemical Tanker

Explicit application mapping is not fully implemented yet. This is a future business-rule improvement, not a reason to rebuild the current DB.

### OBO / Combined Carrier

Not modeled yet. Future scenarios may need cargo type(s), multiple cargoes and highest-rate selection.

### Inspection refusal

Not modeled yet. Future scenario may need gross tonnage and additional-charge logic.

### Special Floating Units

The source provides the definition and current tariff data has Laden rates only. The current generator used Laden for these synthetic invoices. The definition belongs in the RAG knowledge layer.

---

## 8. RAG corpus inventory — known status

Known files in the project/library context:

### Available

- `HbR_Annual_report_2025_highlights.pdf`
- `LPI.pdf` — **was missing from earlier versions of this inventory; contains the actual LPI 2.0 indicator data (Figures 7 & 8: Egypt benchmark vs regional/income peers). Confirm this file, not just the methodology guide, is what gets ingested.**
- `LPI_Methodology.pdf`
- `MSC-MEPC_3-Circ_4-Rev_1.pdf`
- `FBL_template.pdf`
- `Transit_Dues_Rates.pdf` (Suez Canal Authority — Notes section is the RAG-relevant part; the numeric tables already live in `toll_rate_bands`)

### USCG

**Status: confirmed — 24 real reports.** Source: the official USCG Marine Casualty Reports page (`https://www.dco.uscg.mil/Our-Organization/Assistant-Commandant-for-Prevention-Policy-CG-5P/Inspections-Compliance-CG-5PC-/Office-of-Investigations-Casualty-Analysis/Marine-Casualty-Reports/`). One of the 24 has been directly read in this project so far: `Critical_Port_Infrastructure_Risks_PWSA_BOIR_Redacted.pdf` (55 pages — the DALI / Francis Scott Key Bridge inquiry, appendices C–M redacted). The next session should confirm all 24 files are present on disk before bulk ingestion, but the count itself is real, not a placeholder.

These 24 are real historical incident reports — they will not reference this project's synthetic vessels, ports, or containers. They are the general regulatory/domain-knowledge layer. A **separate** synthetic incident-report generator (Section 14) still has a reason to exist: it produces incidents that reference this project's own `vessels`/`ports`/`containers` rows, using the 24 real reports as few-shot style/structure grounding. Neither replaces the other — tag them with different `source_type` values (`real_regulatory_report` vs `synthetic_internal_incident`) so retrieval can distinguish general maritime-safety knowledge from company-specific operational incidents.

### Important distinction — resolved

Earlier drafts of this checkpoint said the Suez tariff was "not one of the primary RAG documents," which contradicted Section 4's own note that the Special Floating Units definition "belongs in the RAG knowledge layer." This is now resolved: the **numeric tables** stay purely in `toll_rate_bands` (structured, no RAG role), but the **Notes section** of the same PDF is now the 6th RAG corpus source (see Section 2). Same file, two different roles depending on which part of it.

---

## 9. What each RAG source contributes

### HbR

Useful for port operations, infrastructure, digitalization, logistics ecosystem and real operational context.

### LPI

Two files, two distinct contributions:

- `LPI.pdf` — the actual indicator data and benchmark narrative (connectivity, dwell time, reliability by region/income group), **including a ready-made Egypt example** directly relevant to this project's business context. This is the file that answers benchmarking questions.
- `LPI_Methodology.pdf` — explains how the indicators are computed. Useful for questions about data sources and definitions, not for answering "how does X compare to Y" questions.

Do not treat either file as a live ranking dataset — both are a point-in-time (2023–2024) methodology-driven report, not a continuously updated feed.

### Suez Canal Tolls PDF — Notes section

Useful for the deferred business rules from Section 7 that have no automated logic yet: the OBO/Combined-Carrier highest-rate rule, the inspection-refusal alternate-tonnage-basis rule, the Ballast Oil/Chemical Tanker mapping, and the Special Floating Units definition (yachts, dredgers, rigs, floating docks, fishing vessels, navy ships, tugboats, research vessels). Retrieval-only for now — these rules are not wired into the `invoices` generation logic, but an agent should still be able to explain them when asked.

### IMO MSC-MEPC Circular

Useful for marine casualty/incident reporting structure:

- ship particulars
- voyage data
- casualty analysis
- contributing factors
- weather/visibility
- accident events
- training
- error types
- equipment failures
- organizational factors

### USCG BOIR (24 real reports)

Useful for real incident narratives, causes, consequences, response/actions and operational lessons. Ingested as-is, tagged `source_type: real_regulatory_report`.

These real reports are the primary source of general maritime-safety/casualty knowledge, and also serve as the few-shot style/structure reference for the separate synthetic incident-report generator (Section 14), which produces incidents tied to this project's own vessels/ports/containers — something the real reports cannot do, since they describe actual historical ships and events. Tag those `source_type: synthetic_internal_incident` to keep the two distinguishable at retrieval time.

### FBL

Useful for multimodal bill-of-lading concepts:

- parties
- cargo
- freight
- dangerous goods
- liability
- control/title
- contractual clauses
- document structure

The FBL is a real template/reference. Synthetic FBLs can be generated later if needed.

---

## 10. Final Qdrant RAG architecture

Final vector store:

**Qdrant**

Not PostgreSQL + pgvector as the final design.

Conceptual pipeline:

```text
Documents
   ↓
Change Detection
   ↓
Parsing + Metadata Extraction
   ↓
Cleaning
   ↓
Chunking
   ↓
Embedding Model
   ↓
Qdrant
   +
PostgreSQL document metadata/lineage
   ↓
Authorization Filter
   ↓
Retrieval / Reranking
   ↓
Cited passages
   ↓
LLM
```

Qdrant owns vector search and retrieval payloads.

PostgreSQL remains the relational source of truth for structured business data and relational metadata/lineage.

---

## 11. RAG ingestion steps

Do not jump directly to embeddings.

1. Inventory corpus
2. Define document metadata
3. Extract text
4. Clean/normalize
5. Chunk
6. Choose embedding model
7. Create Qdrant locally with Docker
8. Create collection
9. Insert a small controlled subset
10. Test retrieval
11. Add metadata filtering
12. Connect filtering to RBAC
13. Scale ingestion
14. Add hybrid retrieval/reranking if evaluation shows it is needed

---

## 12. Chunk metadata

Minimum conceptual payload:

```json
{
  "document_id": "...",
  "document_version": "...",
  "document_type": "...",
  "source": "...",
  "department": "...",
  "sensitivity_level": 1,
  "page": 12,
  "chunk_id": "...",
  "effective_from": "...",
  "ingested_at": "..."
}
```

Possible additional fields:

- title
- section
- checksum
- language
- owner
- tags
- vessel references
- port references

Exact schema should be decided before ingestion.

**Design decision — sensitivity_level is numeric, not a named array.** An earlier draft of this project considered named levels (`public`/`internal`/`confidential`/`executive` as a list per role). The implemented design instead uses a single integer per role that acts as a ceiling: role N can read any chunk with `sensitivity_level <= N`. This is simpler and is the version actually running in PostgreSQL — treat it as final, not as a placeholder pending a richer scheme.

---

## 13. RBAC retrieval

Current levels:

```text
employee → 1
manager  → 2
ceo      → 3
```

Target flow:

```text
User
 ↓
Employee
 ↓
Role
 ↓
Allowed sensitivity
 ↓
Qdrant metadata filter
 ↓
Authorized chunks only
 ↓
Ranking
 ↓
LLM
```

Authorization must be part of retrieval, not an afterthought after retrieving sensitive chunks.

---

## 14. Synthetic data strategy

Synthetic data is not random variation for its own sake.

### Incidents

```text
USCG narratives + IMO schema
          ↓
realistic incident scenarios
```

Useful dimensions:

- incident type
- vessel type
- severity
- location
- cause
- weather
- human factors
- equipment
- response
- outcome

Synthetic incidents are optional. Real USCG reports are the primary incident corpus.

### FBL

```text
Real FBL template
      ↓
synthetic parties/cargo/routes
      ↓
synthetic FBL documents
```

### AIS

```text
AISHub AIS → vessel/type/status diversity
NOAA AIS   → movement behavior
                    ↓
             realistic synthetic AIS
```

### EDI

```text
IFTMIN D12A sample
        ↓
preserve EDIFACT structure
        ↓
generate realistic values
```

---

## 15. MongoDB phase

MongoDB remains the semi-structured layer.

Potential logical collections:

```text
ais_events
edi_messages
```

Exact schema must be designed after inspecting real samples for:

- field distributions
- nesting
- timestamps
- identifiers
- missingness
- duplicates

Do not create collections blindly.

---

## 16. Causal consistency

Later test consistency across:

```text
PostgreSQL
    ↕
AIS
    ↕
Incident data
    ↕
RAG evidence
```

Example contradiction:

```text
PostgreSQL:
vessel_status = At Port

AIS:
speed = 18 knots
mid-sea position
```

Flag as implausible.

Plausible example:

```text
PostgreSQL:
vessel_status = In Transit

AIS:
speed = 15 knots
```

The goal is business consistency, not perfect physical simulation.

---

## 17. Agent architecture

Approved MVP:

```text
Supervisor
    ↓
Analytics Agent
```

Supervisor:
- owns task state
- routes work
- combines evidence
- controls delegation

Analytics Agent:
- analyzes governed operational data
- interprets validated results

Possible future specialists:

- Power BI Specialist
- Knowledge/RAG Specialist
- Validator/Critic
- Visualization Specialist

Do not create many agents simply to make the system look advanced. Add specialists only when they improve accuracy, security isolation or maintainability.

---

## 18. Power BI

Power BI is an external analytics platform, not the RAG store.

Later integration can include:

- metadata service
- semantic-model schemas/measures
- constrained queries
- privileged refresh/write workflows
- shared business metric glossary

---

## 19. Security and guardrails

Later phases should include:

- authentication
- RBAC
- row/column-level controls where applicable
- read-only SQL by default
- allowlisted views
- query validation
- tool authorization
- PII classification/redaction
- audit logging
- prompt-injection defense
- output checks
- approval workflows for sensitive writes/exports

Retrieved documents must be treated as untrusted data, not as instructions.

---

## 20. Evaluation

Build a versioned golden-task/evaluation set.

### Data

- validity
- referential integrity
- causal consistency

### RAG

- retrieval precision
- relevant-context recall
- citation coverage
- grounded answers
- permission filtering

### Agents

- routing
- tool selection
- SQL correctness
- reasoning
- failure handling

### Security

- employee access tests
- manager access tests
- CEO access tests
- leakage tests

### System

- latency
- token usage
- cost
- regression over time

---

## 21. Observability

Eventually introduce a shared trace ID across:

```text
API → Supervisor → Agent → Tool → Retrieval → LLM
```

Capture:

- routing decisions
- tool parameters
- failures/retries
- retrieved chunks
- citations
- SQL execution
- latency
- token usage
- model cost
- guardrail decisions
- evaluation metadata

---

## 22. Deployment direction

Local development should eventually use Docker Compose for:

- API/application
- PostgreSQL/PostGIS
- MongoDB
- Qdrant
- observability dependencies

Do not jump to Kubernetes/microservices before the core system works.

---

## 23. Current status

```text
Planning & data understanding     ✅
Docker                            ✅
PostgreSQL/PostGIS                ✅
Ports                             ✅
Port connections                  ✅
Suez toll modeling                ✅
Departments                       ✅
Roles                             ✅
Employees                         ✅
Vessels                           ✅
Containers                        ✅
Invoices                          ✅

RAG corpus inventory              ← NEXT
Text extraction                   ⏳
Chunking                          ⏳
Embedding model                   ⏳
Qdrant setup                      ⏳
Qdrant ingestion                  ⏳
Retrieval                         ⏳
RBAC retrieval                    ⏳
MongoDB                            ⏳
AIS generation                    ⏳
EDI generation                    ⏳
FBL synthetic documents           ⏳
Incident scenarios                ⏳
Causal consistency                ⏳
Agents                            ⏳
Power BI                          ⏳
Evaluation                        ⏳
Observability                     ⏳
Final integration                 ⏳
```

---

## 24. Exact next-session starting point

**Start with RAG Corpus Inventory.**

Do not:
- rebuild PostgreSQL
- regenerate completed synthetic tables
- jump straight to embeddings
- create Qdrant collection before inspecting the corpus

First verify exactly which files exist among the 24 USCG reports (source: dco.uscg.mil Marine Casualty Reports page), plus the rest of the corpus.

For every RAG candidate, record:

```text
filename
extension
file size
page count
source
real/synthetic
document type
department
sensitivity level
version/date
```

Then proceed one step at a time:

```text
Inventory
→ Extraction
→ Metadata
→ Chunking
→ Embeddings
→ Qdrant
→ Retrieval
→ RBAC
→ Evaluation
```

---

## 25. Message to paste into the next ChatGPT session

> We are continuing my Ports & Logistics AI project from the Master Checkpoint. Do not restart or rebuild completed PostgreSQL work. Final architecture decision: PostgreSQL/PostGIS + MongoDB + Qdrant, with Qdrant as the dedicated vector database. My goal is learning and job readiness, so explain the concepts and let me execute commands myself. Continue strictly step-by-step.
>
> Completed: Docker/PostgreSQL/PostGIS, ports (837), port_connections (19,990), Suez toll modeling (177 toll bands, SDR only — no currency table), departments, roles, 100 employees, 500 vessels, 1,000 containers and 1,000 invoices.
>
> We are now beginning the RAG phase. Core corpus: HbR, LPI.pdf + LPI_Methodology.pdf (two separate files), IMO MSC-MEPC circular, 24 real USCG BOIR reports (from dco.uscg.mil, ingested as-is — general knowledge, not tied to our synthetic vessels), FBL Template, and the Notes section of the Suez Canal Tolls PDF (added to make the Section 7 deferred business rules retrievable). A separate synthetic incident-report generator is still planned on top of this, using the 24 real reports as few-shot grounding but referencing our own vessels/ports/containers. Before chunking/embeddings/Qdrant, start with RAG Corpus Inventory and confirm exactly which of the 24 USCG files are present on disk.
>
> Use the attached Master Checkpoint as the source of truth for project state.

---

## 26. Learning principle

For every new component, understand:

```text
Why do we need it?
Why this technology?
What problem does it solve?
What are the trade-offs?
What data belongs there?
How does it connect to other systems?
How do we validate it?
How would it change at production scale?
```

That reasoning is more important for job readiness than simply making a demo work.
