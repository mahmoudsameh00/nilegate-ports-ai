# HbR Annual Report 2025 (highlights) — Ingestion & Chunking Plan

> **Status: IMPLEMENTED (2026-09-26)** in `Notebooks/HbR_Annual_report_2025_chunking.ipynb` (approved 2026-09-25; the owner delegated the §3 decisions and the build to the assistant).
> The notebook's Final Checkpoint markdown is the authoritative description of what was built; §5 below is the dated log. Deviations from this plan:
> - **Structure:** chemical subscripts (CO2, NO2, PM10, PM2.5) are separate PDF lines → 28 re-inserted into their host lines; "6.1 Key figures" gets an implied heading; the section map (240 + 1 implied) matches the tagged PDF outline exactly. No footnotes/endnotes (proved in Phase 5).
> - **New unit types:** `iro_box` (11), `box` (4), `milestone` (8) besides `paragraph`, `table_row`, `figure`. Tables and figures are unnumbered → page-based ids. Bullets are vector squares. Reading order is band-aware `(page, band, column, y)`.
> - **Source errata (new policy, ADR-022):** two table cells of p.83 and one prose sentence of p.70 excluded with evidence.
> - **Access control (ADR-021):** 140 finance candidates reviewed → 37 units level 3 / Finance (3.2.2 revenue/costs/EBITDA/result/investments paragraphs, the gross-investments chart, the balance sheet and income statement); everything else level 1 / Operations; no chunk mixes levels.
> - **Dedup:** within-source summary policy (ADR-019 extended): Foreword, "2025 at a glance" and the 6.1 key-figure tables are non-canonical → 9 `tab_p83a` rows suppressed, 1 milestone trimmed, 8 canonical repeats kept; no cross-source candidate.
> - **Chunking:** consecutive rows of one table grouped (header once), balanced split when a table does not fit; 6.2 Credits is one "section block" chunk; no chunk under 50 characters.
> - **Coverage audit bug found and fixed:** a right-column body line on p.71 had been tagged as a heading (same PyMuPDF block and baseline as a left-column heading); heading lines are now matched per column and checked against the heading text.
> - **Result:** 85 pages, 4,151 lines, 0 unaccounted; 2,019 body lines → 426 paragraphs; 602 units → 593 after dedup; **352 chunks** (347 level 1 / Operations, 5 level 3 / Finance), 57–1,760 chars; unified corpus **550 chunks**; nothing flagged or pending.

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

## 3. Decisions (taken 2026-09-25 from the PDF evidence and the docs; owner delegated)

1. **Sensitivity rule (per unit, reviewed).** Level 3 / Finance = the Port of Rotterdam Authority's **own financial results and financial position**: the financial statements (p.82 balance sheet and income statement), the "3.2.2 Throughput and financials" paragraphs on revenue, operating expenses, EBITDA / net result and gross investments, and the gross-investments chart (p.13). Everything else is level 1 / Operations (`rbac_mapping.md` §4), including ESG and operational KPIs, throughput, programme budgets, sponsorships, port-due discounts, governance approval thresholds and the port's economic impact (Havenmonitor). A keyword pre-filter (€, euro, revenue, result, investment, balance, equity, debt, EBITDA, financial…) lists every candidate unit; each candidate gets a recorded decision and reason. Chunks never mix levels or departments.
2. **Metadata.** `document_type = port_authority_annual_report`, `source = Port of Rotterdam Authority`, `version_date = 2025`, `SOURCE_NAME = HbR_Annual_report_2025`, chunk prefix `hbr2025_`.
3. **Photos and graphics.** Photos are inventoried and skipped with a reason. Every graphic (vector chart or infographic) goes through the ADR-020 value gate. Most infographics in this PDF have **no extractable text** (raster images, or text drawn as vector outlines); their curated descriptions therefore contain **no numbers at all** (ADR-020: only numbers printed in the figure's own extracted text).
4. **Divider and credits pages.** Contents (p.2) and chapter dividers (p.5, 8, 21, 67, 81) are excluded; their headings are metadata (chapter/section names, cross-checked with the section map). Credits (p.84) carry facts (publisher, contact, address) and are kept as one small unit.
5. **Unnumbered tables and figures.** The report has no figure/table numbers; ids are page-based (`tab_p13`, `fig_p33a`, …).
6. **Source errors.** Where the PDF contradicts itself, the evidence decides; a wrong sentence or table cell is excluded with its evidence recorded (nothing stays flagged).

## 4. Milestones

1. Phases 0–3 (inventory, classification, structure) → review.
2. Phases 4–9 (units with per-unit sensitivity) → review.
3. Phases 10–19 + Final Checkpoint → Run All, then close this plan (lifecycle in the project rules).

## 5. Implementation log (decisions and deviations recorded while building)

- 2026-09-25 — Status set to APPROVED. Development aid: Phase 1 exports the PyMuPDF layout (`get_text("dict")` without image bytes, image placements, drawing rectangles) to `Notebooks/_scratch/state/` (git-ignored) so the pipeline can be checked outside the Windows `.venv`; the notebook itself always reads the PDF.
- 2026-09-25 — Phase 2: page classes `cover_image` (1, 85), `contents` (2), `chapter_divider` (5, 8, 21, 67, 81), `credits` (84, kept), `content` (76 pages). The highlighted nav-bar label gives every retrieval page its chapter (used as a cross-check in Phase 3).
- 2026-09-25 — Phase 3 (deviation from the reference): **chemical subscripts** (CO2, NO2, PM10, PM2.5) are separate PyMuPDF lines; 28 are re-inserted into their host line ("CO e" → "CO2e"). "6.1 Key figures" has no title on its pages → an **implied heading** at the top of p.82 (listed on divider p.81). Heading levels 1–6 by font role; the section map (240 typographic headings + 1 implied) matches the tagged PDF outline **exactly** (same texts, same pages), in addition to the Contents and divider cross-checks.
- 2026-09-25 — Phase 4: **21 tables** found from their navy header rectangles (which also give the column boundaries); cells rebuilt at span level, wrapped cells merged by line pitch (≤ 11.2pt), rows by vertical overlap; reviewed `TABLE_SPECS` (titles, printed headers asserted, merged value columns for the indented financial statements, group labels). 144 `table_row` units. **Source errata** (cell excluded, evidence recorded): p.83 "Deepsea containers −1.5%" (its own values give +4.1%) and p.83 "Containers 2024 = 133,4" (truncated; p.13 prints 133,400).
- 2026-09-25 — Phase 4: new unit types (deviation, string values in `unit_type`): `iro_box` (11 impacts/risks/opportunities boxes), `box` (4 bold-titled 7.2pt text boxes), `milestone` (8 cards). Graphics: 18 photos + 19 decorative icons skipped; 15 graphics through the value gate → 9 `full`, 6 `skip` (fig_p11 value-creation model restates reported KPIs; fig_p15 port profile — its numbers are outlined text, not allowed by ADR-020; fig_p19 SDG icons, fig_p45/p47/p49b maps covered by prose). Chart values mapped to years/steps from printed labels (4.9); descriptions of text-less graphics carry no numbers.
- 2026-09-26 — Fix: the table/box font is 7.25pt, which PyMuPDF rounds to 7.3 (my layout export rounded it to 7.2); `TABLE_FONT_SIZE` is now taken from the data (the 'Focal point:' lines) instead of being hard-coded.
- 2026-09-26 — Phase 5: **no footnotes/endnotes** (proved: 0 superscript markers, no Notes/Sources heading; the 211 small digit lines are 28 chemical subscripts + 183 chart labels).
- 2026-09-26 — Phase 6: bullets are **vector squares**, not glyphs → bullet items detected from the drawing on the line's baseline (65). 2,018 body lines; pages without body text (reviewed): 6, 7 (cards), 11, 23, 58 (graphics), 82 (financial statements).
- 2026-09-26 — Phase 7 (deviation): **band-aware reading order** `(page, band, column, y)` — full-width graphics (p.11, 23, 58, 69, 71) split a page into bands; without it the p.71 sentence running from the left into the right column above the figure was cut. 425 paragraphs (leading 11.5pt, paragraph gap ≈ 23pt, no first-line indent).
- 2026-09-26 — Phase 8: tables/graphics are assigned by physical position (they are unnumbered and sit under their introducing heading); every IRO box lands in its own 4.2.x theme (asserted).
- 2026-09-26 — Phase 9: prose erratum — p.70 "Our Executive Board consisted of three women and five men…" removed (contradicted on p.70, p.73 and by the three signatories on p.4). **Access control**: 140 units matched the finance pre-filter; each is assigned to a reviewed decision → **37 level 3 / Finance** (4 paragraphs of 3.2.2 on revenue, operating expenses, EBITDA/net result and gross investments; the gross-investments chart; 19 balance-sheet + 13 income-statement rows); the other 103 candidates are level 1 with one of ten recorded reasons (e.g. programme budgets, port-due discounts, governance thresholds, economic impact of the port, energy-intensity KPI). 601 units in total.
- 2026-09-26 — Phase 10: deterministic item-level comparison (ADR-010/019), within the report and against the cleaned units of the four other sources. Table rows match only when all numbers of the row's values are contained (decimal commas normalised, years dropped), with >= 3 distinct non-zero values and a shared label word — otherwise identical zero rows and accounting identities matched. No cross-source candidate.
- 2026-09-26 — Phase 11 (ADR-019 applied within one document): the Foreword, "2025 at a glance" and the key-figure tables of 6.1 (`tab_p83a`, `tab_p83b`) are **summary (non-canonical)**; the thematic chapters and the financial statements are canonical. Result: 9 `tab_p83a` rows suppressed (repeat `tab_p13`), milestone p.7 (4) trimmed (Cobouw sentence = P200), 8 canonical-canonical repeats kept as `keep_contextual`. No level-3 unit suppressed.
- 2026-09-26 — Phase 13: one extracted file and ONE cleaned file (`units` with `sensitivity_level`/`department`, `duplicate_audit`, `coverage_audit` added in Phase 19).
- 2026-09-26 — Phase 14 (deviation from the LPI notebooks): consecutive rows of the **same table** are grouped into one chunk (header written once, <= MAX_CHUNK_CHARS) because the rows are short KPI rows; the chunk grouping key includes `sensitivity_level` and `department`, so **no chunk mixes access levels** (asserted in 15.3). 355 chunks: 350 level 1 / Operations, 5 level 3 / Finance.
- 2026-09-26 — Phase 16–18: 16-column schema unchanged (ADR-009); `sensitivity_level`/`department` filled per chunk. Cross-source: 198 + 355 = 553 chunks, no `chunk_id` collision; this is the first source with level-3 chunks.
- 2026-09-26 — Phase 19 found one silent loss: a right-column body line on p.71 ("The Supervisory Board oversees, monitors and advises the Executive Board on various matters:") shared a PyMuPDF block and baseline with a left-column heading and was tagged as heading. **Fix in 6.1:** heading lines are matched per column, and an assert checks that the tagged lines spell the heading. Effects: 2,019 body lines, 426 paragraphs (P360 is the recovered sentence; later paragraph ids shift by one, reviewed lists in 7.4/9.3/12.1 updated), 602 units, 593 after dedup; chunk count unchanged (355).
- 2026-09-26 — Phase 19: errata cells and suppressed rows are located **physically** (same printed row as their label), because '-1.5%' also appears in a correct row. 4,151 lines: 0 unaccounted.
- 2026-09-26 — Chunk-level cleanup (owner request, before closing the notebook): (1) **section blocks** — a section made only of short paragraphs under different minor headings becomes one chunk, each piece labelled with its heading; the rule is generic and matches only 6.2 Credits (asserted), whose four pieces were fragments on their own (the 27-char chunk "Port of Rotterdam Authority"); (2) **balanced table splits** — a table run too long for one chunk is split into the fewest parts that fit with equal row counts (balance sheet 10 + 9 rows instead of 18 + 1); (3) 15.1 asserts no chunk under `FRAGMENT_MIN_CHARS` = 50. Result: 352 chunks (347 level 1, 5 level 3), 57–1,760 chars; corpus 550. The remaining short chunks (< 300) are complete statements or one-row tables alone in their subsection and are kept.
