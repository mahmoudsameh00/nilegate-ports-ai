# Final Checkpoint — LPI Connecting to Compete 2025 Chunking Pipeline

## What this notebook does

**Input:** `LPI.pdf`, the World Bank report *Connecting to Compete 2025: Trade Logistics in the Global Economy — The New Logistics Performance Indicators 2.0* (30 PDF pages).

**Goal:** cut the report into **chunks**, small self-contained pieces of text that a RAG system can index and retrieve, **without dropping anything silently** and **without repeating what the LPI Methodology corpus already contains**.

**Why it is not simply "split the text every N characters":** the PDF has two text columns, floating figures and tables, vector charts whose values are drawings (not text), endnotes on a separate page, hidden control characters, and several passages copied from the Methodology report.

The notebook works in **phases**. Each phase makes one kind of decision, validates it (asserts + a reviewed snapshot) and hands a clean result to the next:

`pages → structure → tables/figures → notes → body lines → paragraphs → sections → units → dedup → chunks → schema → saved files → whole-PDF coverage`

**Vocabulary used below**

* **Page numbers** are PDF page indexes. The printed page number is the PDF index minus 9 (the Executive summary is printed page 1 and PDF page 10).
* **Unit** = one meaningful piece before chunking: a paragraph, a table row, a figure or an abbreviation.
* **Chunk** = a piece that is finally indexed. `content` is the single text field of a unit.

**Setup (Phase 0).** The notebook finds `Data/raw/unstructured/LPI.pdf` by walking up from its own folder, fingerprints it (SHA-256) and defines the document metadata (`lpi_connecting_to_compete_2025`, Operations, level 1, version 2025).

---

## Phase 1 — Page inventory

**What it does.** Records, for every page, character/word/line counts, text blocks, images, **vector drawings**, links and page size.

**Problem.** The charts are vector drawings, so `image_count` is 0 on every figure page. `drawing_count` is recorded as well and is never replaced by image counts.

## Phase 2 — Page classification

**What it does.** Gives every page one class and a reason, using detected region boundaries (Executive summary → Notes → References), never hard-coded page numbers.

**Problems and how they were solved**

1. *Headings sit at the END of the extracted text* ("Abbreviations" on p.7, "About this report" on p.8), so headings are searched in the first 5 **and** last 3 lines.
2. *"doi" in references looked like a legal page.* The legal rule uses the © sign only.
3. *Pages that fit no planned class:* the abbreviations page (`abbreviations`, auxiliary) and the back cover (`back_cover`, kept for retrieval and sent to dedup).

**Output.** 20 retrieval pages (8, 10–27, 30); auxiliary pages 7 (abbreviations) and 28 (notes); excluded: cover, legal, contents, acknowledgements, blank, references.

## Phase 3 — Structure reconnaissance

**Problems and how they were solved**

1. *The PDF outline is useless* (internal ids such as `_Int_Gh1S7VvD`). The hierarchy comes from fonts, positions and the Contents.
2. *Heading level is carried by the font, not size or bold flags:* Eurostile Bold = titles, Helvetica Heavy 10pt = sections (not flagged bold), Helvetica Medium 9.5pt = "Area N" and "Data", bold Garamond with "N.N" = run-in subsections. Helvetica Heavy 8pt is a figure/table title, not a heading.
3. *Two-column reading order:* headings are ordered by (page, column, y), with the column measured from each page's own left margin.
4. *Hidden `\x08` characters* in the Contents made titles look truncated; all Unicode control/format characters are removed.

**Output.** `section_map` (31 headings: 6 titles, 12 sections, 3 areas + "Data", 9 run-ins) and `caption_inventory` (Tables 1.1–1.2, Figures 2.1–2.10), both checked against the Contents.

## Phase 4 — Structured extraction

1. **Tables.** `find_tables()` returns an outer frame (used as the region) and the inner grid (used as content). Each row is one `table_row` unit; the counts match the report itself (6 core + 15 supplementary indicators).
2. **Figures.** A section heading next to Figure 2.7 widened its region into the prose column; heading lines are now excluded and an assert guarantees no prose inside any region. Chart values are drawings, so each figure went through a **value gate** after reviewing its render: 6 `full` (curated description; every number must exist in the figure's extracted text), 1 `caption_only`, 3 `skip`. Figures 2.4 and 2.9 are fully covered by the prose. **Figure 2.10's title contradicts the prose on p.23**; step 4.5a reads the scatter markers from the vector drawings and shows that the figure's own data agree with the prose (most economies lie above the 45-degree line: B2C slower than B2B), so the misleading figure is skipped and the correct statement stays in the prose.
3. **Abbreviations.** One `definitions` unit per abbreviation (7), so duplicates can be removed one by one.

## Phase 5 — Notes / endnotes

**What it does.** Builds the registry of the 33 endnotes on p.28 and finds the 33 superscript markers at span level (6.9pt), so normal numbers, years and decimals are never mistaken for markers.

**Problem.** A marker at the end of a long left-column line was assigned to the right column; the column is now taken from the start of the line.

**Decision.** 18 notes are `informative` (appended as `Note: …`), 15 are `citation_only` (kept in `footnote_refs`); all 33 were reviewed by hand, with comments on the borderline ones.

## Phase 6 — Body extraction and cleaning

**Principle.** Exclude what is known (header/footer, headings, decoration, table/figure regions) and keep everything else, so unexpected content is surfaced by the audit instead of lost.

**Problems and how they were solved:** note markers are removed at span level; line-break type is recorded (`soft`, `hard`, `none`) instead of guessed later; bullet glyphs printed on their own line are attached to the text on the same baseline; the back cover's Eurostile text is kept (a Garamond whitelist would have dropped it).

**Output.** 1,023 clean body lines on the 20 retrieval pages.

## Phase 7 — Paragraph reconstruction

**Rules from measurements:** 13.5pt leading, 15pt first-line indent for new paragraphs, hanging indent for bullets. A paragraph continues across a column, a page or a figure whenever the previous line did not end a sentence.

**Problem.** Three compound words broke at a plain hyphen ("third-party", "just-in-time", "investment-friendly"); they are joined without a space, while suspended hyphens ("low- and middle-income") keep theirs.

**Output.** 112 paragraphs (44 bullet items, 9 run-in subsections); every line used exactly once, no character lost.

## Phase 8 — Section / subsection assignment

Paragraphs take the last heading before them in reading order. **Tables and figures are floats**, so they take the section of the first paragraph that references them (Figure 2.1 → Connectivity, Table 1.2 → Supplementary indicators). `subsection` is the full path, e.g. `A strategic framework… > Area 1: … > 1.1 Liberalizing markets…`.

## Phase 9 — Unified logical units

131 units (112 paragraphs, 5 table rows, 7 figures, 7 abbreviations), with the note policy applied.

## Phases 10–12 — Duplicate detection, decisions and QA

**Method.** Deterministic, item-level comparison with the cleaned Methodology units: sentences for prose, indicator definitions for table rows, one line per abbreviation. An item is a duplicate when repeated (ratio ≥ 0.90) or paraphrased (≥ 0.75) without any new content word.

**Canonical policy.** Methodology is canonical for indicator definitions, methodology and data construction (table rows, abbreviations, Chapter 1); this report is canonical for findings, figures and the policy framework. The Methodology corpus is never modified.

**Decisions (owner instruction: remove everything that is repeated).**
* **Suppressed (18):** both tables (identical to Methodology Tables 1–2), 5 abbreviations (B2B, B2C, LLDC, LPI, LPI 2.0), and 8 Chapter 1 paragraphs (P020, P021, P023, P024, P025, P028, P031, P032); P021/P025/P031 after manual review (their only unmatched sentence is a rewording).
* **Trimmed (7):** P022, P029, P030, P033, P035 keep only their sentences with new information; the back cover (P111, P112) keeps only what "About this report" does not already say.
* **Kept:** everything else; PPP and SMEs are the only new abbreviations.

**Output.** 113 units after dedup.

## Phase 13 — Saved artifacts

| Layer | File | Content |
|---|---|---|
| extracted | `extracted/LPI_Connecting_to_Compete_extracted.json` | page classes, section map, captions, regions, tables, figure gate/elements, notes, markers, body lines, paragraphs |
| cleaned | `cleaned/LPI_Connecting_to_Compete_logical_units.json` | one file: `units` + `duplicate_audit` + `coverage_audit` |
| chunks | `chunks/LPI_Connecting_to_Compete_chunks.parquet` | 69 chunks, 16-column schema |

## Phases 14–15 — Chunking and validation

Paragraphs are never cut; short paragraphs of the same subsection are grouped (bullets join their introduction); 2,000 characters is a safety cap only; figures are one chunk each; the two new abbreviations form one chunk. `chunk_id` = `lpi2025_<logical_unit>_chunk_<n>`, distinct from the Methodology's `lpi_`.

**Result.** 69 chunks (61 paragraph, 7 figure, 1 definitions), 80–1,990 characters (median 657); every kept unit preserved, no suppressed unit re-entering, no chunk crossing a section.

## Phases 16–18 — Schema, save/reload, cross-source

Same 16-column schema and validator as the Methodology, FBL and Suez notebooks (ADR-009). The Parquet file is validated after reloading from disk, then concatenated with the other three sources: 198 chunks, identical columns and dtypes, no `chunk_id` collision.

## Phase 19 — Whole-PDF coverage audit

Every one of the **2,189 text lines of the 30 pages** has exactly one disposition — in the chunks, heading metadata, suppressed or trimmed duplicate (with its canonical copy), citation-only note metadata, figure internals / skipped figure, layout, or an excluded page class — and every "in chunks" claim is verified against the final chunk texts. **0 lines are unaccounted for.**

## Status

Nothing is pending: no manual-review duplicate, no flagged unit, and every line of the PDF is accounted for.

## Addendum 2026-10-02 — Title / text normalization (ADR-041)

A last phase (appended to the script, proven by `tools/nb_to_script.py check`) normalizes the saved chunk file in
place with `pipelines/lib/chunks.py`: a leading heading moves from `text` to `title` (`title` = the location label,
`text` = the body only). Lossless, idempotent; chunk ids, order and count unchanged. Reviewed counts: heading_line 8, run_in_heading 9, unchanged 52.
Where this narrative says a header, path or caption is at the start of every chunk, it is now the chunk's `title`.
