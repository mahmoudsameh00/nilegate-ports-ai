# RBAC mapping

Decision record: ADR-006 in `docs/decisions.md`. Status: **the rule is decided; nothing enforces it yet** (retrieval and API are not built).

## 1. Access rule

Every protected resource (a table, a document or a chunk) has two attributes:

- `sensitivity_level` ∈ {1, 2, 3}
- an owner `department` (must be a row in the `departments` table)

Every employee has a role (`roles.allowed_sensitivity_level`: employee = 1, manager = 2, ceo = 3) and a department.

```text
allowed(user, resource) =
       resource.sensitivity_level <= user.role.allowed_sensitivity_level      -- role ceiling
   OR (resource.department_id = user.department_id                           -- department grant
       AND resource.sensitivity_level <= 2)                                  -- level 3 stays role-only (CEO)
```

- Level 1: everyone.
- Level 2: managers and CEO, plus **any employee of the owner department** (e.g. Finance employees can read `invoices`).
- Level 3: CEO only. The department grant never unlocks level 3.
- Authorization is applied **inside** retrieval (a Qdrant payload filter or a SQL predicate), never after results are fetched.

Qdrant filter (conceptual): `sensitivity_level <= role_level OR (department == user_department AND sensitivity_level <= 2)`.

## 2. Structured tables (PostgreSQL)

| Table | Level | Owner department | Note |
|---|---:|---|---|
| `ports` | 1 | Operations | geographic reference |
| `port_connections` | 1 | Operations | aggregated flow statistics |
| `toll_rate_bands` | 1 | Finance | published tariff |
| `departments` | 1 | HR | organisational structure |
| `vessels` | 1 | Operations | daily operational data |
| `containers` | 1 | Operations | operational shipment data |
| `documents` | 1 | IT | RAG document registry |
| `roles` | 2 | IT | defines the permission system |
| `employees` | 2 | HR | contains PII (names, emails). HR employees get access through their department |
| `invoices` | 2 | Finance | financial data. Finance employees get access through their department |
| `customers` | 2 | Finance | commercial terms and credit rating of the billed companies (migration 012, Agents plan §4a R8) |
| `payments` | 2 | Finance | payments received per invoice (migration 012) |
| `budget_weekly` | 2 | Finance | weekly budget 2025 per vessel category (migration 012) |
| `finance_test.*` | 2 | Finance | evaluation copy with planted errors (migration 012); the answer key is outside the database |
| `vessels.customer_id` | 1 | Operations | an id only (the vessels table stays level 1); the customer's details are level 2 |
| `audit_log` (planned, API phase) | 3 | IT | security audit trail, CEO only |

## 3. Semi-structured (MongoDB, implemented 2026-09-27)

| Collection | Level | Owner department |
|---|---:|---|
| `ais_positions` (time-series; real + synthetic fixes) | 1 | Operations |
| `ais_vessels` (static / voyage data per MMSI) | 1 | Operations |
| `edi_messages` | 1 | Operations (synthetic IFTMIN carries no amounts; can move to 2 later if commercial values must be restricted) |

Every document carries `sensitivity_level` and `department` (as the chunks do), so the rule in §1 can be applied as a query predicate. Names replace the earlier `ais_events` (ADR-029). `edi_messages.keys.invoice_number` is a reference to a level-2 / Finance invoice, not its content (no amounts, D14), so the collection stays level 1; reading the invoice itself still needs level 2 or the Finance department. Implemented 2026-09-27: every document of the three collections carries level 1 / Operations (validated by the loader's schema audit).

## 4. Documents (RAG corpus)

External, publicly published sources are level 1. Their owner department is the NileGate department that would use them.

| Document | Level | Owner department |
|---|---:|---|
| `LPI.pdf`, `LPI_Methodology.pdf` (World Bank) | 1 | Operations |
| `MSC-MEPC_3-Circ_4-Rev_1.pdf` (IMO) | 1 | Operations |
| USCG ROI reports ×23 | 1 | Operations |
| `FBL_template.pdf` (FIATA) | 1 | Operations |
| `Transit_Dues_Rates.pdf`, Notes section only (Suez Canal Authority) | 1 | Finance |
| `HbR_Annual_report_2025_highlights.pdf`: strategy, ESG, narrative | 1 | Operations |
| HbR: the Port Authority's own financial results and position — balance sheet and income statement (p.82), the 3.2.2 paragraphs on revenue, operating expenses, EBITDA / net result and gross investments, and the gross-investments chart (p.13) | **3** | Finance |

HbR is deliberately treated as "our internal report" so the corpus contains one document with sections at different levels. Sensitivity is stored per chunk. Implemented 2026-09-26 (ADR-021): every unit that mentions money or finance was reviewed; 37 units / 5 chunks are level 3, all others level 1, and no chunk mixes levels.

## 5. Synthetic company documents (planned)

| Source | Level | Owner department | Why |
|---|---:|---|---|
| Synthetic incident reports (linked to our vessels) | 2 | Operations | internal operational incidents |
| Synthetic bills of lading (customer names, commercial terms) | 2 | Operations | commercially sensitive |

## 6. Open points

- Employees have no active/inactive status; the column is dropped (ADR-017).
- Exception cases (temporary permissions, conflicting duties) from the early design are not modelled.
