# IMO MSC-MEPC.3/Circ.4/Rev.1 (casualty reporting) — Ingestion & Chunking Plan

**Status: PROPOSED (2026-09-26)** — review §3 and approve before any notebook work.

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
