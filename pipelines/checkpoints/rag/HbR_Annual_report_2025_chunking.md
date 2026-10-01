# Final Checkpoint — Port of Rotterdam Annual Report 2025 Chunking Pipeline

## What this notebook does

**Input:** `HbR_Annual_report_2025_highlights.pdf`, the *Annual report 2025 (highlights edition)* of the Port of Rotterdam Authority (85 landscape pages, two text columns).

**Goal:** cut the report into **chunks** that a RAG system can index and retrieve, **without dropping anything silently**, **without repeating what the report already says elsewhere**, and — new for this source — with an **access level per chunk**: the Port Authority's own financial results are level 3 / Finance, everything else level 1 / Operations.

**Why it is not simply "split the text every N characters":** chemical subscripts are separate PDF lines, bullets are vector drawings, the 21 tables are unnumbered and drawn with navy header bars, there are ESG boxes and milestone cards, raster and vector graphics, charts whose values are printed labels, full-width figures that cut a page into bands, summary chapters that repeat the thematic chapters, and three statements that the PDF itself contradicts.

The notebook works in **phases**. Each phase makes one kind of decision, validates it (asserts + a reviewed snapshot) and hands a clean result to the next:

`pages → structure → tables/boxes/graphics → notes → body lines → paragraphs → sections → units + access → dedup → chunks → schema → saved files → whole-PDF coverage`

**Vocabulary used below**

* **Page numbers** are PDF page indexes; the printed page number is the PDF index minus 1.
* **Unit** = one meaningful piece before chunking: a paragraph, a table row, an IRO box, a text box, a milestone card or a graphic.
* **Chunk** = a piece that is finally indexed. `content` is the single text field of a unit.

**Setup (Phase 0).** The notebook finds `Data/raw/unstructured/HbR_Annual_report_2025_highlights.pdf` by walking up from its own folder, fingerprints it (SHA-256) and defines the document metadata (`port_authority_annual_report`, source *Port of Rotterdam Authority*, version 2025). `sensitivity_level` and `department` are **not** document constants here: they are decided per unit in Phase 9.

---

## Phase 1 — Page inventory

Characters, words, lines, blocks, images, **image placements**, vector drawings and links per page. A layout export (without image bytes) is written to `Notebooks/_scratch/state/` (git-ignored) as a development aid; the notebook itself always reads the PDF.

## Phase 2 — Page classification

Every page gets one class and a reason, from signals (title size, contents title, credits title, word counts, the highlighted label of the navigation bar), never from hard-coded page numbers.

**Output.** `cover_image` (1, 85), `contents` (2), `chapter_divider` (5, 8, 21, 67, 81), `credits` (84, kept for retrieval), `content` (76 pages). The active navigation label gives every retrieval page its chapter, used later as a cross-check.

## Phase 3 — Structure reconnaissance

**Problems and how they were solved**

1. *Chemical subscripts are separate PDF lines* ("CO e" instead of "CO2e"): 28 subscripts are re-inserted into their host line at the right position.
2. *Heading level is carried by the font role*, not by size alone: 30pt chapter titles, ExtraBold 20pt section titles, bold "N.N.N" subsections, bold 10pt headings, bold 8.5pt subheadings, all-bold 8pt minor headings.
3. *Multi-line chapter titles* are compared letter by letter with all title lines of the page.
4. *"6.1 Key figures" has no title on its pages*: an implied heading at the top of p.82 (listed on the divider p.81).

**Output.** `section_map` with 240 typographic headings + 1 implied; it matches the tagged **PDF outline exactly** (same texts, same pages), the Contents and the divider pages.

## Phase 4 — Structured extraction

1. **Tables (21, 144 rows).** Found from their navy header rectangles, which also give the column boundaries. Cells are rebuilt at span level (wrapped text merged by line pitch), rows by vertical overlap; a reviewed `TABLE_SPECS` records titles, printed headers (asserted), merged value columns of the indented financial statements, and group labels. The table font is 7.25pt, which PyMuPDF reports as 7.3: `TABLE_FONT_SIZE` is taken from the data, not hard-coded. **Two source errata** are excluded with evidence: "Deepsea containers −1.5%" (its own values give +4.1%) and "Containers 2024 = 133,4" (truncated; p.13 prints 133,400).
2. **IRO boxes (11), text boxes (4), milestone cards (8)**: one self-contained unit each.
3. **Graphics.** 18 photos and 19 decorative icons carry no information. 15 graphics went through a **value gate** after reviewing their renders: 9 `full`, 6 `skip` (restated elsewhere, or a map whose content is in the prose). Chart values are mapped to their years / steps from the printed labels; descriptions of text-less graphics contain no numbers (ADR-020).

## Phase 5 — Notes

**Finding (proved, not assumed):** the report has no footnotes or endnotes — 0 superscript markers, no Notes / Sources heading; every small digit line is a chemical subscript or a chart label.

## Phase 6 — Body extraction and cleaning

**Principle.** Exclude what is known (navigation bar, page numbers, headings, subscripts, structured regions) and keep everything else.

**Problems and how they were solved:** bullets are **vector squares**, detected from the drawing on the line's baseline (65); chart legends and the org chart also contain small squares and are excluded; heading lines are tagged **per column**, because PyMuPDF placed a right-column body line of p.71 in the block of a left-column heading on the same baseline (found by the Phase 19 audit, see below).

**Output.** 2,019 clean body lines; pages without body text: 6, 7 (cards), 11, 23, 58 (graphics), 82 (financial statements).

## Phase 7 — Paragraph reconstruction

**Rules from measurements:** 11.5pt leading, paragraph gap ≈ 23pt, no first-line indent, hanging indent for bullets. **Reading order is band-aware** — `(page, band, column, y)` — because full-width graphics split a page into bands; otherwise the p.71 sentence running from the left into the right column above the figure would be cut. A paragraph continues across a column or page when the previous line did not end a sentence.

**Output.** 426 paragraphs; every line used exactly once, no character lost.

## Phase 8 — Section / subsection assignment

Paragraphs take the last heading before them in reading order. Tables and graphics are unnumbered and sit under their introducing heading, so they are assigned by **physical position**; every IRO box lands in its own ESG theme (asserted).

## Phase 9 — Units, errata and access control

602 units (426 paragraphs, 144 table rows, 11 IRO boxes, 9 figures, 8 milestones, 4 boxes).

* **Prose erratum:** p.70 "Our Executive Board consisted of three women and five men…" is removed — contradicted on p.70 itself, on p.73, in the Executive Board table and by the three signatories of the foreword.
* **Access control per unit:** a keyword pre-filter lists the 140 units that mention money or finance; each gets a reviewed decision. **37 units are level 3 / Finance** — the four 3.2.2 paragraphs on revenue, operating expenses, EBITDA / net result and gross investments, the gross-investments chart, and the 32 rows of the balance sheet and income statement. The other 103 candidates stay level 1 with one of ten recorded reasons (programme budgets, port-due discounts, governance thresholds, economic impact of the port, …).

## Phases 10–12 — Duplicate detection, decisions and QA

**Method.** Deterministic, item-level comparison (sentences for prose; for table rows all numbers contained, ≥ 3 distinct non-zero values, and a shared label word), within the report and against the cleaned units of the four other sources.

**Canonical policy.** The thematic chapters and the financial statements are canonical; the **Foreword**, **2025 at a glance** and the **key-figure tables of 6.1** are summaries.

* **Suppressed (9):** `tab_p83a` rows that repeat `tab_p13` (subtotals and totals).
* **Trimmed (1):** milestone card p.7 (4) loses the Cobouw sentence already in P200.
* **Kept contextual (8):** templated statements repeated between two canonical sections.
* **Cross-source:** no candidate.

**Output.** 593 units after dedup; no level-3 unit suppressed.

## Phase 13 — Saved artifacts

| Layer | File | Content |
|---|---|---|
| extracted | `extracted/HbR_Annual_report_2025_extracted.json` | page classes, section map, subscripts, tables (spec, meta, errata), regions, graphics (gate, elements, images, chart evidence), body lines, paragraphs, prose errata, access decisions |
| cleaned | `cleaned/HbR_Annual_report_2025_logical_units.json` | one file: `units` (with `sensitivity_level` / `department`) + `duplicate_audit` + `coverage_audit` |
| chunks | `chunks/HbR_Annual_report_2025_chunks.parquet` | 352 chunks, 16-column schema |

## Phases 14–15 — Chunking and validation

Paragraphs are never cut; short paragraphs of the same subsection **and the same access level** are grouped (bullets join their introduction); 2,000 characters is a safety cap. Consecutive rows of one table are grouped with the table title written once (the rows are short KPI rows); a table too long for one chunk is split into balanced parts (the balance sheet: 10 + 9 rows, not 18 + 1). IRO boxes, text boxes, cards and graphics are one chunk each. The credits page (6.2) is a **section block**: publisher, feedback and the two addresses are fragments on their own ("Port of Rotterdam Authority" alone was a 27-character chunk), so the section is one chunk with each piece labelled by its heading. No chunk is shorter than 50 characters (asserted). `chunk_id` = `hbr2025_<logical_unit>_chunk_<n>`.

**Result.** 352 chunks (298 paragraph, 22 table, 11 IRO box, 9 figure, 8 milestone, 4 box), 57–1,760 characters (median 552): **347 level 1 / Operations and 5 level 3 / Finance**. The 30 chunks under 300 characters are complete statements or one-row tables that are alone in their subsection (e.g. "We intend to formulate a target for chain responsibility." under *Objective*). No chunk mixes access levels, departments, sections or tables; every kept unit is preserved.

## Phases 16–18 — Schema, save/reload, cross-source

Same 16-column schema and validator as the other notebooks (ADR-009), with `sensitivity_level` / `department` taken from each chunk. The Parquet file is validated after reloading from disk and concatenated with the four other sources: 550 chunks, identical columns and dtypes, no `chunk_id` collision.

## Phase 19 — Whole-PDF coverage audit

Every one of the **4,151 text lines** of the PDF has exactly one disposition — in the chunks (verified against the chunks of its own unit, table or figure), heading / column-header metadata, merged subscript, suppressed or trimmed duplicate (with its canonical copy in the chunks), erratum (located physically, with evidence), chart internals, layout, or an excluded page class. **0 lines are unaccounted for.**

The first run of this audit found one real loss: a body line of p.71 ("The Supervisory Board oversees, monitors and advises the Executive Board on various matters:") had been tagged as a heading because it shared a PyMuPDF block and baseline with a heading in the other column. Phase 6 now tags heading lines per column and asserts that the tagged lines spell the heading; the line is back in its paragraph (P360), which shifted the later paragraph numbers by one.

## Status

Nothing is pending: no manual-review duplicate, no flagged unit, every access decision reviewed, and every line of the PDF accounted for.
