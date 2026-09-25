# HbR Annual Report 2025 (highlights) — Ingestion & Chunking Plan

**Status: PROPOSED (2026-09-25) — needs the owner's approval before any notebook work.**

**Planned notebook:** `Notebooks/HbR_Annual_report_2025_chunking.ipynb`
**Primary input:** `Data/raw/unstructured/HbR_Annual_report_2025_highlights.pdf` (Port of Rotterdam Authority, *Jaarverslag 2025*, English text)
**Reference notebook:** `Notebooks/LPI_Connecting_to_Compete_chunking.ipynb` (most complete pipeline; closed plan in `docs/archive/2026-09-25_LPI_Connecting_to_Compete_2025_chunking_plan.md`)
**Governing decisions:** ADR-006 (RBAC), ADR-008, ADR-009, ADR-010/019 (dedup), ADR-020 (figures), `docs/rbac_mapping.md` §4.

---

## 0. Reconnaissance facts (quick pdfplumber scan, 2026-09-25 — to be re-verified with PyMuPDF in Phase 1)

- 85 pages, **landscape** (841.9 × 473.4 pt), 19.6 MB (many photos). Tagged PDF produced by PDFreactor.
- Fonts: one family (`NLRTM-Regular/Bold/Light`); body text ≈ 8pt, section titles ≈ 30pt Light, sub-headings ≈ 10–12pt Bold.
- A **navigation bar is repeated at the top of every page** ("Foreword · 2025 at a glance · Port of Rotterdam · ESG Report · Corporate governance and risk management · Other information") → running header to exclude.
- Chapter divider pages with little text: p.5 (2025 at a glance), p.8 (The Port of Rotterdam Authority), p.21 (ESG report), p.67 (Corporate governance and risk management), p.81 (Other information); p.1 and p.85 are image-only covers.
- Visible structure: p.2 contents; p.3–4 Foreword (Executive Board); 2.1 Milestones 2025; 3.1 Profile and strategy, 3.2 How we create value, 3.3 Scenarios provide direction; 4.1 General information about our report, 4.2 Double materiality analysis, then ESG topics (climate mitigation/adaptation, air, soil, water, nature, occupational safety, value chain, subversive crime, nautical safety, digital and physical resilience); 5.1 Governance and diversity, 5.2 Due diligence statement, 5.3 Risk management; 6.1 Key figures (p.82–83, many small tables), 6.2 Credits (p.84).
- Tables are frequent (KPI/ESG tables on ~35 pages; up to 8 on p.82). Throughput and financial figures appear in several places.
- Unlike the LPI reports, this is a multi-column **landscape** layout; column geometry must be measured, not assumed.

## 1. Goal and design principles

Same guarantees as the LPI Connecting to Compete pipeline:
semantic chunks in the 16-column schema; tables as row units; figures through the value gate (ADR-020);
notes handled by policy; dedup before chunking (ADR-010/019; no cross-source overlap is expected, so mainly within-document repetition such as "at a glance" vs chapter text);
reviewed snapshots after every stage; a **whole-PDF coverage audit** (every line accounted for); Final Checkpoint code + markdown.

**New in this source — per-chunk access control:** the report mixes public narrative (level 1, Operations) with financial content that `docs/rbac_mapping.md` classifies as **level 3, Finance**. `sensitivity_level` and `department` are therefore decided **per unit**, not per document.

## 2. Phases (same numbering scheme as the reference notebook)

| Phase | Content | HbR-specific points |
|---|---|---|
| 0 | Setup, paths, fingerprint, metadata | `document_type = port_authority_annual_report` (proposed), `version_date = 2025`, `source = Port of Rotterdam Authority` |
| 1 | Page inventory | drawings vs images (photos ≠ figures) |
| 2 | Page classification | cover, contents, chapter dividers, credits; decide whether divider pages carry retrievable text |
| 3 | Structure reconnaissance | navigation-bar zone; landscape column geometry; heading levels by font; numbered sections (2.1 … 6.2) cross-checked with the contents page |
| 4 | Structured extraction | KPI/ESG/financial tables → `table_row` units; each table gets a **sensitivity decision** (4.x); charts/infographics → value gate |
| 5 | Notes | detect footnotes/endnotes if any (not yet confirmed) |
| 6 | Body extraction + cleaning | exclude-what-is-known approach; control characters; hyphenation |
| 7 | Paragraph reconstruction | measured leading/indent; continuation across columns and pages |
| 8 | Section assignment | physical position; floats by first reference |
| 9 | Unified logical units | + per-unit `sensitivity_level` / `department` |
| 10–12 | Dedup + decisions + QA | within-document ("at a glance" and Key figures repeating chapter numbers); cross-source check against existing units kept for safety |
| 13 | Save extracted + ONE cleaned file | `{source, units, duplicate_audit, coverage_audit}` |
| 14–15 | Chunking + validation | chunks never mix sensitivity levels or departments |
| 16–18 | Schema, save/reload, cross-source | `chunk_id` prefix proposed: `hbr2025_` |
| 19 | Whole-PDF coverage audit | 0 unaccounted lines |
| Final | Final Checkpoint code + markdown | |

## 3. Decisions needed from the owner before approval

1. **Sensitivity rule.** Only the full financial statements are level 3 in `rbac_mapping.md`, and this "highlights" edition may not contain them. Proposed: tables/paragraphs with financial results (revenue, EBITDA, net result, balance-sheet items, investments in EUR) → level 3 / Finance; operational KPIs (throughput, safety, ESG) → level 1 / Operations. Confirm, or name the pages/tables.
2. **`document_type` value** (`port_authority_annual_report` proposed) and chunk prefix `hbr2025_`.
3. **Photos and infographics:** photos are skipped; infographics go through the value gate (render review), as in ADR-020.
4. **Credits page (p.84) and chapter dividers:** excluded from retrieval unless they carry facts.

## 4. Milestones

1. Phases 0–3 (inventory, classification, structure) → review.
2. Phases 4–9 (units with per-unit sensitivity) → review.
3. Phases 10–19 + Final Checkpoint → Run All, then close this plan (lifecycle in the project rules).
