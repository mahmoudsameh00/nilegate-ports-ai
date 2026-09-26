# IMO MSC-MEPC.3/Circ.4/Rev.1 (casualty reporting) — Ingestion & Chunking Plan

> **Status: IMPLEMENTED (2026-09-26)** in `Notebooks/IMO_MSC-MEPC_3_Circ_4_Rev_1_chunking.ipynb` (approved 2026-09-26; the owner delegated the §3 decisions and the build to the assistant).
> The notebook's Final Checkpoint markdown is the authoritative description of what was built; §5 holds the §3 decisions and §6 the dated log. Deviations from this plan:
> - **Reconnaissance correction:** the circular is p.1–3; **p.4 is blank** (page class `blank`), the annex is p.5–31.
> - **Rows by baseline:** one printed row is several PyMuPDF lines (a justified line of p.14 even word by word) → 2,329 lines rebuilt into 1,311 rows. **Grids from the drawn cell borders** give the columns; 25 lines that PyMuPDF merged across a column rule (e.g. `.14 … & quantity Table 15`) are split again by their words.
> - **`*` footnote:** anchored on the heading "CASUALTY-RELATED MATTERS", not on a paragraph → its own `note` unit (the plan said "append to the paragraph").
> - **Option tables:** Table 12 has a third level; Tables 13–15 are fill-in forms (printed column headers, blank columns asserted); Table 12 `.8–.27` carried as *Normal service* on evidence (alphabetical continuation, next printed category *Sailing*) despite a p.20 border under `.16`; Table 22 `.17` prints no text → excluded (`empty_option_excluded`).
> - **Errata (ADR-022):** field 3.2.22 value type `Y/N/U` (contradicts its own drop-down description and footnote 2) excluded; the clause "and as much of the consequence data in appendix 3, as possible" of circular para. 7 excluded (para. 8 and the annex put consequences in Appendix 2) — first **clause-level** exclusion.
> - **Dedup:** the form repeats itself by design ("Other" ×11, "Unknown" ×18, repeated Appendix 3 fields) → field/option lines compared without their code, 55 exact repeats kept contextual, nothing suppressed; similar wording of two different values is `similar_wording_distinct_value`, never a duplicate. Cross-source (828 units): 2 candidates, none covered.
> - **Damage diagram:** gate `full` (plan proposed `caption_only`-style): curated description of printed labels only, no number.
> - **Result:** 31 pages, 2,329 lines, **0 unaccounted**; field catalogue 117 fields / 13 groups / 14 minimum fields, 30 option tables / 553 options, 56 cross-references resolved; 689 units; **69 chunks** (33 option tables, 14 field groups, 11 Appendix 4 parts, 9 paragraph chunks, 1 note, 1 figure), 144–1,801 chars, all level 1 / Operations; unified corpus **619 chunks**; nothing flagged or pending.

**Status (history): APPROVED (2026-09-26)** — the owner delegated the §3 questions; they are decided from the PDF evidence in §5 (decisions) and every later decision or deviation is logged in §6 (implementation log).

**Planned notebook:** `Notebooks/IMO_MSC-MEPC_3_Circ_4_Rev_1_chunking.ipynb`
**Primary input:** `Data/raw/unstructured/MSC-MEPC_3-Circ_4-Rev_1.pdf` — IMO circular *Casualty-related matters — Reports on marine casualties and incidents: Revised harmonized reporting procedures* (18 November 2014)
**Reference notebooks:** `Notebooks/HbR_Annual_report_2025_chunking.ipynb` (latest pipeline: errata, coverage audit, section blocks, balanced table splits) and `Notebooks/LPI_Connecting_to_Compete_chunking.ipynb` (footnote policy). Closed plans in `docs/archive/`.
**Governing decisions:** ADR-008, ADR-009, ADR-010/019 (dedup), ADR-020 (figures), ADR-021 (access per unit), ADR-022 (errata), `docs/rbac_mapping.md` §4 (IMO = level 1 / Operations).

---

## 0. Reconnaissance facts (quick `pdfinfo` / `pdftotext -layout` scan, 2026-09-26 — to be re-verified with PyMuPDF in Phases 1–3)

- 31 pages, **A4 portrait, single column**, Microsoft Word 2013, tagged PDF, **no outline**, 0.5 MB. Images only on p.1 (IMO letterhead) and p.10 (damage diagram).
- **Running header** on every page: `MSC-MEPC.3/Circ.4/Rev.1` + `Page N` (circular, p.1–4) or `Annex, page N` (annex, p.5–31). **Running footer**: the file path `I:\CIRC\MSC-MEPC\3\4-Rev-1.doc`. Both are layout.
- **Circular (p.1–4):** letterhead (IMO address, telephone), document symbol and date, title, 10 numbered paragraphs (sub-items `.1`, `.2`), a `*` footnote on p.1 (the joint MSC-MEPC circular series 1–7), then a **list of appendices and of the 30 field-value tables** (a contents list; must match the real headings).
- **Annex, Appendices 1–3 (p.5–9): field tables** — columns *Field number | Field description | Field value type*; groups such as *General*, *Generic casualty data*, *External environmental data* (App. 1), *1 Ship particulars … 4 Consequences* (App. 2), *For each "human erroneous action" / "equipment failure" / … accident event* (App. 3). An asterisk on the field number (`.1*`) marks the minimum fields for the first report (circular para. 7). Value types reference option tables ("See table 4"). Footnotes 1–3 define `Auto`, `Y/N/U`, `M/F/U`.
- **Appendix 4 (p.10–15): supplementary information** — conditional sections ("If 'breach of hull causing flooding' (Field at appendix 2.4.9) AND … – then complete following appendix 4 data") numbered 1–7 with form items (`2.1 Nature of damage:` …), nested "If so:" items, and a **damage diagram** (p.10: raster image + vector labels Lpp, d, h, X, Z…).
- **Appendix 5 (p.16–31): 30 field-value option tables** — coded options (`.1 Collision`), often two-level (category in the left column, sub-option on the right: `Collision — own ship not under way`), group sub-headings inside long tables (Table 23), tables continuing across pages; Table 1 holds only "As per GISIS nomenclatures".

## 1. Goal and design principles

Same guarantees as the HbR pipeline: semantic chunks in the 16-column schema; reviewed snapshots after every phase; nothing dropped silently (whole-PDF coverage audit, 0 unaccounted); errata excluded with evidence (ADR-022); nothing flagged or pending; Final Checkpoint code + markdown.

**Specific to this source:** it is a **reporting form**, not prose. Its value for the RAG is (a) *what must be reported about a marine casualty and when* (the circular text and the conditions of Appendix 4) and (b) *what each field means and which values it may take* (Appendices 1–3 + 5). The same field catalogue is also the planned schema for synthetic incidents (ARCHITECTURE §3), so the extracted file keeps a **machine-readable field catalogue** (appendix, group, field number, description, value type, minimum-field flag, option-table reference) — as a file only; no database change is part of this plan.

## 2. Phases (same numbering scheme as the reference notebooks)

| Phase | Content | IMO-specific points |
|---|---|---|
| 0 | Setup, paths, fingerprint, metadata | see §3.1 |
| 1 | Page inventory | images (logo, diagram) vs drawings (table rules) |
| 2 | Page classification | `circular` (p.1–4), `annex` (p.5–31); letterhead block; contents list on p.3–4 |
| 3 | Structure reconnaissance | headings by font/case: ANNEX, APPENDIX N, table titles, field groups, conditional sections; cross-check with the list of appendices/tables; numbered paragraphs and `.N` sub-items |
| 4 | Structured extraction | field tables (App. 1–3) → `field` rows; Appendix 4 conditional sections; option tables (App. 5) → `option` rows with category carried down; tables continued across pages joined; damage diagram through the value gate |
| 5 | Notes | `*` circular-series footnote; footnotes 1–3 (Auto, Y/N/U, M/F/U) — policy in §3.5 |
| 6 | Body extraction + cleaning | circular paragraphs; header/footer/path excluded |
| 7 | Paragraph reconstruction | numbered paragraphs with hanging `.N` items (items join their paragraph) |
| 8 | Section assignment | circular vs annex > appendix > group |
| 9 | Unified logical units + access | all level 1 / Operations (rbac_mapping); pre-filter kept only as a check |
| 10–12 | Dedup + decisions + QA | cross-source against the 550 existing chunks' units (little overlap expected); within-source: the p.3–4 table list vs the real table titles (contents → metadata, not a duplicate unit) |
| 13 | Save extracted (+ field catalogue) + ONE cleaned file | `{source, units, duplicate_audit, coverage_audit}` |
| 14–15 | Chunking + validation | §3.2–3.4; no chunk < 50 chars; balanced splits |
| 16–18 | Schema, save/reload, cross-source | expected corpus = 550 + IMO chunks |
| 19 | Whole-PDF coverage audit | 0 unaccounted lines; diagram labels = `figure_internal` |
| Final | Final Checkpoint code + markdown | |

## 3. Open questions for the owner (proposed answers)

1. **Metadata.** `document_type = imo_casualty_reporting_circular`, `source = International Maritime Organization (IMO)`, `version_date = 2014-11-18`, `SOURCE_NAME = IMO_MSC-MEPC_3_Circ_4_Rev_1`, chunk prefix `imo_mci_`, level 1 / Operations for every unit.
2. **Field tables (App. 1–3).** One unit per field (for dedup and audit), but **one chunk per field group** (e.g. *Appendix 2 > 4 Consequences*), with the column names and the group path written once at the top; a group longer than `MAX_CHUNK_CHARS` is split in balanced parts with the header repeated.
3. **Minimum fields and references.** Write the asterisk as text (`[minimum field for the first report]`) and resolve every "See table N" to "See table N (Casualty event)" — the table **name** only, never its options, so field and option chunks stay separate but self-explanatory.
4. **Option tables (App. 5).** One chunk per table ("Table 4 — Casualty event: .1 Collision — own ship not under way; …"), balanced split for long tables (Tables 4, 22, 23, 24) with the title repeated; tables continuing across pages are joined first. Table 1 ("As per GISIS nomenclatures") stays as one short chunk.
5. **Footnotes.** Footnotes 1–3 are informative definitions of value types → appended as "Note:" to every field chunk that uses `Auto`, `Y/N/U` or `M/F/U`. The `*` circular-series footnote is informative about IMO document numbering → appended to the paragraph that carries the marker.
6. **Appendix 4.** One unit per conditional section (trigger condition + its items, nested "If so:" items kept in order); chunk = the section, split in balanced parts if needed with the trigger repeated.
7. **Damage diagram (p.10).** Value gate (ADR-020): proposed `caption_only`-style unit that names the dimensions it illustrates (Lpp, B, D, d, h, X, Z, l — all printed in the figure), otherwise its labels are `figure_internal`.
8. **Letterhead and contents.** The IMO address/telephone letterhead is layout (excluded with reason); the document symbol and date are metadata. The p.3–4 list of appendices/tables is a contents list → metadata, cross-checked against the real headings.

## 4. Validation targets

- Every field of Appendices 1–3 appears once in the field catalogue and in exactly one chunk; field numbers are consecutive within each group (asserted); minimum-field flags match the asterisks.
- Every "See table N" resolves to one of the 30 tables; every table listed on p.3–4 exists with the same title.
- Every option of the 30 tables appears in exactly one chunk; two-level categories carried down correctly (reviewed snapshot per table: option count).
- Coverage audit: every line of the 31 pages has a disposition; 0 unaccounted.

## 5. Decisions on §3 (2026-09-26, delegated by the owner, evidence from the PDF)

Reconnaissance re-checked before the first cell (`pdftotext -layout`, page renders): **the circular text is on p.1–3 and p.4 is blank** (0 characters); the annex is p.5–31 ("Annex, page 1–27").

1. **Metadata — as proposed.** `document_type = imo_casualty_reporting_circular`, `source = International Maritime Organization (IMO)`, `version_date = 2014-11-18` (the date printed under the symbol on p.1), `SOURCE_NAME = IMO_MSC-MEPC_3_Circ_4_Rev_1`, chunk prefix `imo_mci`, level 1 / Operations for every unit (asserted per unit and per chunk).
2. **Field tables — as proposed.** One unit per field (catalogue, dedup, audit); one chunk per field group with the appendix/group path and the column names written once; balanced split with the header repeated when a group exceeds `MAX_CHUNK_CHARS`.
3. **Minimum fields and references — as proposed**, plus: three references are printed without "See" (`Table 13`, `Table 15`, `Table 14` for fields 2.4.13–2.4.15); they are resolved the same way. The printed value type is kept verbatim; the table name is added in parentheses.
4. **Option tables — as proposed**, plus: Table 12 has a **third level** (`.14 On passage` → Displacement / Non-displacement / Transitional mode); levels 2 and 3 are carried down like level 1. Table 14 is a **fill-in form** (IMDG class codes and four blank columns) → one chunk with its column names and class codes. The printed column headers of Tables 13 and 15 (`Dropdown list from MARPOL Annex 1, Appendix 1, applies to each item below`, `Quantity`) are kept as a table note. A carried-down category is taken only from the last printed category of the same table (across pages); a row that prints a category without a sub-option is a leaf and ends the carry.
5. **Footnotes — footnotes 1–3 as proposed** (appended as "Note:" to every field chunk whose value types use `Auto`, `Y/N/U` or `M/F/U`). **Deviation for the `*` footnote:** its marker sits on the heading `CASUALTY-RELATED MATTERS*`, not on a paragraph, so the footnote (the seven joint MSC-MEPC circular series) becomes its own unit in the circular section, titled with that heading.
6. **Appendix 4 — as proposed.** An item and its nested "If so:" / "If yes:" lines form one atomic block that is never split; the sub-headings of section 3 ("For ship in …") are repeated when a part continues under them. The "Direct Natural Resources Damages" table belongs to section 6.
7. **Damage diagram (p.10) — gate `full`**: one self-contained figure unit whose curated description names only the labels printed in the figure (verified against the extracted labels, ADR-020); every label line is `figure_internal` in the coverage audit.
8. **Letterhead and contents — as proposed**, plus: the `E` language marker and the two IMO images on p.1 are layout; p.4 is page class `blank`; the `***` and `____________` separators are punctuation only. The p.3 list of appendices and tables is metadata, cross-checked title by title against the real headings (differences are recorded, the heading wins).

## 6. Implementation log

- 2026-09-26 — Plan approved (delegated). Notebook built phase by phase; the environment used to write the cells cannot run the project's PyMuPDF, so Phase 1 exports the raw PyMuPDF layout to `Notebooks/_scratch/state/` and the later phases are tested against that export before the owner runs them.
- 2026-09-26 — Phases 2–9: page classes; rows by baseline; bold heading roles; p.3 list vs headings (1 difference: Table 13 "bunkers"/"Bunker", heading wins); grids from vertical rules; word-level split of 25 merged lines; field catalogue (117 fields); Appendix 4 (150 items, 139 atomic blocks, damages table with an unlabelled last group kept as "(no label printed)"); 30 option tables (553 options, carry-down incl. 3-level Table 12); figure gate `full`; 56 cross-references resolved; field erratum 3.2.22; footnote `*` as own unit; 10 paragraphs; prose erratum para. 7 (clause); empty option Table 22 `.17` excluded; access check: 4 finance-term option names reviewed, all level 1.
- 2026-09-26 — Phases 10–19: code-less comparison of field/option lines; 55 exact repeats `keep_contextual`, 0 suppressed/trimmed, 2 cross-source candidates (unique); single cleaned file with `coverage_audit`; structure-following chunks with repeated headers and balanced splits (App. 3 group 2, App. 4 sections 2–4, Tables 12, 22, 23); 13 chunks < 300 chars (whole short option tables + the one-field App. 3 group), none < 50; coverage 2,329 lines, 0 unaccounted. Re-run on the owner's machine gave the same numbers (artifacts 2026-09-26 10:59).
