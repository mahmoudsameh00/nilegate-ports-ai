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
| `audit_log` (planned, API phase) | 3 | IT | security audit trail, CEO only |

## 3. Semi-structured (MongoDB, planned)

| Collection | Level | Owner department |
|---|---:|---|
| `ais_events` | 1 | Operations |
| `edi_messages` | 1 | Operations (can move to 2 later if commercial values must be restricted) |

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
| HbR financial statements (balance sheet, income statement) | **3** | Finance |

HbR is deliberately treated as "our internal report" so the corpus contains one document with sections at different levels. Sensitivity is stored per chunk.

## 5. Synthetic company documents (planned)

| Source | Level | Owner department | Why |
|---|---:|---|---|
| Synthetic incident reports (linked to our vessels) | 2 | Operations | internal operational incidents |
| Synthetic bills of lading (customer names, commercial terms) | 2 | Operations | commercially sensitive |

## 6. Open points

- Employees have no active/inactive status; the column is dropped (ADR-017).
- Exception cases (temporary permissions, conflicting duties) from the early design are not modelled.
