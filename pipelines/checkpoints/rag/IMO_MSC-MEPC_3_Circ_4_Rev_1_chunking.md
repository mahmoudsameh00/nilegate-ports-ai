# Final Checkpoint — IMO MSC-MEPC.3/Circ.4/Rev.1 (Casualty Reporting) Chunking Pipeline

## What this notebook does

**Input:** `MSC-MEPC_3-Circ_4-Rev_1.pdf`, the IMO circular *Casualty-related matters. Reports on marine casualties and incidents — Revised harmonized reporting procedures* (18 November 2014; 31 A4 pages, Word 2013 export).

**Goal:** cut the circular into **chunks** that a RAG system can index and retrieve, **without dropping anything silently**, and keep a **machine-readable field catalogue** of the reporting form (the planned schema source for synthetic incidents — a file only, no database change).

**Why it is not simply "split the text every N characters":** the document is a **reporting form**. After a 10-paragraph circular come 117 fields in 13 groups (Appendices 1–3), 7 conditional supplementary sections with a damage diagram (Appendix 4) and 30 option tables with 553 coded options (Appendix 5). Meaning lives in the *structure*: a field is only meaningful with its group and value type, an option only with its table and its (often unprinted, carried-down) category, an Appendix 4 item only with its condition. PyMuPDF also cuts one printed row into several lines, splits a justified line word by word, and once merges text across a table column rule.

The notebook works in **phases**. Each phase makes one kind of decision, validates it (asserts + a reviewed snapshot) and hands a clean result to the next:

`pages → rows + headings → fields / Appendix 4 / option tables / figure → notes → circular body → paragraphs → sections → units + errata + access → dedup → chunks → schema → saved files → whole-PDF coverage`

**Vocabulary**

* **Line** = one PyMuPDF line; **row** = the lines of one page that share a baseline (one printed row).
* **Unit** = one meaningful piece before chunking: a paragraph, the footnote, a field, an Appendix 4 section, the figure, an option. `content` is the unit's single text field.
* **Chunk** = what is finally indexed (16-column schema, ADR-009).

**Setup (Phase 0).** The PDF is found by walking up from the notebook folder and fingerprinted (SHA-256). Metadata: `imo_casualty_reporting_circular`, source *International Maritime Organization (IMO)*, `version_date = 2014-11-18` (the printed date, asserted in 3.6), **level 1 / Operations** for every unit (`docs/rbac_mapping.md` §4, asserted per unit and per chunk). The plan's §3 questions were delegated and decided from the PDF (plan §5); every deviation is in the plan's implementation log.

---

## Phase 1 — Page inventory

Characters, words, blocks, images, drawings and links per page. **p.4 has no text at all**; images only on p.1 (IMO logo, "IMO Conventions" badge) and p.10 (the two raster parts of the damage diagram); the annex pages carry 200–700 drawings each — the cell borders of the tables. A raw layout export (spans, words, drawings) is written to `Notebooks/_scratch/state/` as a development aid; the notebook itself always reads the PDF.

## Phase 2 — Page classification

From signals, not page numbers: the running page label (`Page N` / `Annex, page N`), the IMO letterhead and the `APPENDIX N` headings in force. **Output:** `circular` (1–3), `blank` (4), `annex_fields` (5–9), `annex_supplementary` (10–15), `annex_option_tables` (16–31); annex page labels run 1–27 (physical = printed + 4). *Reconnaissance correction:* the plan assumed the circular ran to p.4 — it ends on p.3.

## Phase 3 — Structure reconnaissance

**Problems and how they were solved**

1. *One printed row = several PyMuPDF lines* (paragraph number and text, field code / description / value type; a justified line of p.14 split word by word) → rows are rebuilt by **baseline** (2,329 lines → 1,311 rows); a row's segments never overlap horizontally (asserted).
2. *Small caps* (`A` + `PPENDIX`) → a line's text is the concatenation of its spans.
3. *Superscripts vs subscripts* → the four superscript footnote markers (`*`, `1`, `2`, `3`, PyMuPDF flag bit 0) are removed from the text and kept as markers; inline subscripts (`Lpp`, `l1`, `CO2`) stay in their word.
4. *Zones* → running header, footer (the Word file path), letterhead, footnote area, diagram labels (Times New Roman).
5. *Heading roles* come from **bold rows** (the Appendix 4 section numbers are printed in regular weight before a bold condition — handled): title block, list of appendices, `ANNEX` + title, `APPENDIX N` + title, the 7 Appendix 4 conditions, `Table N` + title (30 each), the first table's column header.

**Cross-check with the document's own list (p.3):** 30 entries identical; 4 where the heading adds a qualifier; **1 difference** — Table 13 is listed as "Oil cargo/**bunkers** type & quantity" but headed "Oil cargo/**Bunker** type & quantity": the printed heading wins, the list is metadata.

## Phase 4 — Structured extraction

1. **Grids from the drawn borders (4.1).** Every table border is a thin filled rectangle; the vertical rules that cross a row give its column boundaries — robust to wrapped cells and merged category cells.
2. **A line merged across a column rule** — `.14 Ship pollution – … & quantity Table 15` — would have put the value type into the description. It is split again with its **words** (PyMuPDF words and lines were first proven identical, same block/line numbering). 25 such lines (mostly `.10 Registered shipowner`-style code+description merges).
3. **Field catalogue (4.2):** 117 fields in 13 groups (e.g. App. 3 "human erroneous action": 30), field numbers consecutive per group, **14 minimum fields** (asterisks — only in Appendices 1 and 2, as circular para. 7 says), footnote refs on 2.1.1 / 2.2.2 / 3.2.2, 41 option-table references (three printed without "See").
4. **Appendix 4 (4.3):** 7 conditions, 150 numbered items, 10 "If so:/If yes:" markers (they bind the item before to the item after — 139 **atomic blocks**), 2 sub-headings ("For ship in …"), 1 parenthesised note, and section 6's *Direct Natural Resources Damages* table (18 rows; its last group prints no label).
5. **Option tables (4.4):** 553 options in 30 tables — 21 lists, 6 hierarchical (Tables 4, 12, 18, 25, 26, 27), 3 fill-in forms (13, 14, 15: printed column headers, blank fill-in columns asserted); groups in Tables 22 (10) and 23 (11); Table 1 is a note only. **Carry-down:** an empty category cell continues the last printed category of the same table, also across pages; a category printed without a sub-option is a leaf. Table 12 has a third level (On passage → three modes). *Evidence decision:* p.20 draws a border under `.16` in Table 12's category column, but `.8–.27` continue the alphabetical list of *Normal service* and the next printed category is *Sailing* at `.28` → carried as Normal service (asserted).
6. **Damage diagram (4.5):** gate **full** (ADR-020) — it defines the symbols of the section 2 damage items; the curated description names only printed labels and contains no number.
7. **Cross-references (4.6):** every "See table N" resolves; every "Field at appendix X.Y.Z" of the Appendix 4 conditions resolves to a field whose name (or option value) matches the quoted words; every table is referenced by at least one field.
8. **Field erratum (4.7, ADR-022):** field 3.2.22 describes a drop-down of four watchkeeping patterns but prints the value type `Y/N/U`, which footnote 2 defines as Yes/No/Unknown → the value-type cell is excluded (description kept). Field 3.2.23 prints no value type at all (recorded as such).

## Phase 5 — Notes

Four footnotes, each with its marker: the `*` note (the seven joint MSC-MEPC circular series) is anchored on the **heading** "CASUALTY-RELATED MATTERS", not on a paragraph → its own unit (deviation from the plan, logged). Footnotes 1–3 define `Auto`, `Y/N/U`, `M/F/U` → appended as "Note:" to every field chunk that uses the token.

## Phases 6–8 — Circular body, paragraphs, sections

Excluded with a reason: header, footer, letterhead, symbol and date, title block, footnotes, the p.3 list. The 70 body rows become **10 numbered paragraphs** (sub-items `.1–.2` of para. 2 and `.1–.5` of para. 8 kept one per line); every row used once, no character lost, no hyphenation to repair. Sections: the circular, and `Annex — Appendix N: <title>` with the field group / `Section N` / `Table N — <title>` below.

## Phase 9 — Units, errata and access

689 units: 552 options, 117 fields, 10 paragraphs, 7 Appendix 4 sections, 1 note, 1 figure, 1 table note.

* **Prose erratum (ADR-022):** paragraph 7 says to complete "…the asterisked fields in appendices 1 and 2 *and as much of the consequence data in appendix 3, as possible*". Paragraph 8 (.2/.3) and the annex put the consequence data in **Appendix 2** (group 4 Consequences); Appendix 3 has no consequence field. The contradicting clause is excluded; the minimum-field rule is kept.
* **Empty option:** Table 22 `.17` prints no text → excluded with its reason.
* **Access:** all level 1 / Operations; the ADR-021 keyword pre-filter found 4 option names (Economic conditions, Market change, …) — each reviewed: form option names, level 1.

## Phases 10–12 — Duplicate detection, decisions and QA

Item-level, deterministic (ADR-010/019). The form repeats itself **by design**: "Other" closes 11 tables, "Unknown" 18, "Description of accidental event" is a field in 5 Appendix 3 groups. Field and option lines are compared **without their code**; within the document only exact repeats count (similar wording such as "last 24 hours" / "last 7 days" is a *different value*). **Every unit is canonical** (there is no summary part): 55 exact repeats are **kept contextual**, nothing is suppressed or trimmed. Cross-source (828 units of the five other sources): 2 candidates, no covered item.

## Phase 13 — Saved artifacts

| Layer | File | Content |
|---|---|---|
| extracted | `extracted/IMO_MSC-MEPC_3_Circ_4_Rev_1_extracted.json` | page classes, section map, contents check, subscripts, split lines, footnotes, paragraphs, **field catalogue** (groups, fields, value-type notes, 30 option tables with their options, references), Appendix 4 (conditions + field refs, items, damages table), figure gate, errata, excluded items, access decisions |
| cleaned | `cleaned/IMO_MSC-MEPC_3_Circ_4_Rev_1_logical_units.json` | one file: `units` + `duplicate_audit` + `coverage_audit` |
| chunks | `chunks/IMO_MSC-MEPC_3_Circ_4_Rev_1_chunks.parquet` | 69 chunks, 16-column schema |

## Phases 14–15 — Chunking and validation

The chunk follows the form: circular paragraphs grouped while short (9 + 10), the note, **one chunk per field group** (column names and group path at the top, footnote notes when used), **one per Appendix 4 section** (the condition at the top), the figure, **one per option table** (title, note or printed columns at the top). Every chunk names its document part, so it stands alone. Long ones are split in **balanced parts** with the header repeated: App. 3 "human erroneous action" (2 parts), Appendix 4 sections 2, 3 (3 parts) and 4, Tables 12, 22 and 23 — part sizes within a few percent of each other; an option group or an Appendix 4 sub-heading that runs into a new part is repeated "(continued)". Field lines, option lines and atomic Appendix 4 blocks are never cut.

**Result.** 69 chunks (33 option tables, 14 field groups, 11 Appendix 4 parts, 9 paragraph chunks, 1 note, 1 figure), 144–1,801 characters (median 649), all level 1 / Operations. The 13 chunks under 300 characters are whole short option tables (e.g. Table 8 Natural light) and the one-field group "For each casualty event" — complete units; none under 50 characters.

## Phases 16–18 — Schema, save/reload, cross-source

Same 16-column schema and validator as the other notebooks; the Parquet file is validated after reloading from disk and concatenated with the five other sources: **619 chunks**, identical columns and dtypes, no `chunk_id` collision (prefix `imo_mci_`).

## Phase 19 — Whole-PDF coverage audit

Every one of the **2,329 text lines** has exactly one disposition: in the chunks (verified against the chunks of its own unit; bare codes as separate tokens; merged lines cell by cell), metadata (title, symbol/date, annex title, the p.3 list, footnote labels), erratum (the `Y/N/U` cell, located in its row, and the paragraph 7 line), the empty option, diagram labels, layout or punctuation. **0 lines are unaccounted for.**

## Status

Nothing is pending: no manual-review duplicate, no flagged unit, every doubt resolved with evidence from the PDF or excluded with a recorded reason, every line of the PDF accounted for.
