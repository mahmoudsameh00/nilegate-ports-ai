# Final Checkpoint — USCG Reports of Investigation (ROI) Chunking Pipeline

## What this notebook does

**Input:** the 23 United States Coast Guard Reports of Investigation in
`Data/raw/unstructured/us_coast_guard_reports/` (580 pages; public, redacted releases written on one shared ROI
template). **Goal:** cut them into self-contained chunks for the RAG corpus **without dropping anything silently**,
and give every report an **IMO incident profile** coded with the field catalogue of the IMO circular
MSC-MEPC.3/Circ.4/Rev.1 (ADR-023). The 23 reports are **one source**: one extracted, one cleaned and one chunks file,
`filename` per chunk (plan §4.1).

**Why not "split every N characters":** 115 pages are scans (4 reports are scanned end to end), 19 pages carry an
old OCR layer, the letters and the report repeat each other, the reports print notes, tables, figures with text
inside them, signatures with names, and their numbering has slips. Meaning lives in the template: a finding is read
with its sub-items, a recommendation with the Commandant's action on it.

`pages → OCR → lines/rows + template → fingerprint → structure (parts, tables, persons, figures) → notes →
paragraphs → numbering → sections → units + errata + access → dedup → incident profiles → saved files → chunks →
schema/save/cross-source → coverage of every line → profile trace`

**Vocabulary.** *Line* = one PyMuPDF line or one OCR line; *row* = the lines of one page on one baseline; *unit* =
one meaningful piece before chunking (paragraph, table, glossary, note, profile); *chunk* = what is
indexed. Every chunk starts with the header `USCG ROI <vessel> (MISLE <n>, <incident date>) — <section path>`.

---

## Phase 0 — Setup
Corpus list, one SHA-256 per file, source metadata (level 1 / Operations, `docs/rbac_mapping.md` §4), the seeded
sample (seed 42 → VICAR_602, CUMBERLAND_II, BIG_STICK, KIM_LY; UNA_MAS for the OCR path), MIN 300 / MAX 2000 /
fragment 50 characters, prefix `uscg`. **Problem:** the owner's cost rule — the format must not be learned by
parsing every PDF. **Fix:** learn it from the sample, write it once as a template, fingerprint the rest cheaply.

## Phase 1 — Inventory
Per page: characters, words, image cover, invisible / star-font characters → `text` 446, `image_only` 115,
`ocr_layer` 19. **Problem:** a page can look empty yet hold an invisible OCR layer (VICAR_602, MERRICK), or hold text
in a decorative font. **Fix:** classes from visible characters and image cover, reviewed page lists asserted.

## Phase 1b — OCR (RapidOCR, installed with uv)
300-dpi renders, RapidOCR lines converted to PDF coordinates with their confidence, a per-page cache (134 files) with
engine versions and settings, retry of weak lines on their own crop, a readability gate, and the two OCR layers
re-checked. **Problems:** the default score threshold silently dropped low-confidence lines; OCR also reads the text
*inside* photos, charts and screens (soundings, labels, even names on a diagram); seal marks read as letters.
**Fixes:** keep every line with its confidence and let the gate decide; find figure regions in the page image
(text masked out) and flag the lines inside them `figure_internal`; short weak marks become `ocr_noise`.

## Phase 2 — Lines, rows, template
One line table (18,999 lines) and one row table (rows by baseline, segments in x order), and the reviewed
`ROI_TEMPLATE` (letters, sections 1–8 with their title variants, numbering, vessel labels, persons header, captions,
furniture). **Problems:** a glyph shift in one report's fonts, control characters in OCR text, a label and its value
printed as separate lines. **Fixes:** reviewed character repairs; rows rebuilt by baseline.

## Phase 3 — Fingerprint + 3b
Every report compared with the template (text only): 12 conformant, 11 deviating with 19 reviewed deviations
(e.g. SPIRIT_OF_BOSTON's convening memorandum and two Findings parts; numbering slips BIG_STICK 6 → "5",
LA6893ER 5 → "4", SPIRIT 4 → "3"). Each deviation has a recorded decision; the list is asserted.

## Phase 4 — Structured extraction
One role per row (22 roles), 116 document parts with dates (`version_date` = the Commandant's action), 297 vessel /
vehicle fields from drawn rules, 41 persons (roles, class, outcome), 204 caption units (all `caption_only` under
ADR-020: raster images, no text-readable data), 44 enclosure items and 82 TOC entries cross-checked.
**Problems:** missing table rules silently dropped name rows; OCR "Figure l."; in-text references that look like
captions. **Fixes:** tables closed at top/bottom + "no row outside a cell" assert; reviewed caption patterns.

## Phase 5 — Notes and superscripts
93 notes in 5 reports (H20_BELOW's four from OCR), every marker resolved, every note cited once; policies reviewed:
22 informative (appended as `Note: …`), 65 citation-only (evidence exhibits, transcripts → metadata), 6 "Redacted".
**Problems found:** not every superscript is a note — ordinal suffixes ("the 1ˢᵗ Officer" read "the 1 Officer",
"E 9ᵗʰ St."), an exponent ("in²"), trademark signs ("SternoDon" instead of "Sterno®, Don®"); a note label printed
twice (SPIRIT p.62 "54" for note 55) with the continuation of note 54 printed below it; SPIRIT's List of Figures /
Tables taken for footnotes; OCR note numbers glued to words ("water1."). **Fixes:** 44 superscripts restored at
reviewed positions (row, line and caption), a reviewed label slip and continuation, the lists moved to metadata and
cross-checked against the captions, OCR references removed from the word and recorded.

## Phases 6–8 — Body, numbering, sections
3,170 paragraphs: new paragraph at a printed number, list item, letter label, context change, a baseline step
> 1.4 × the report's pitch, or a visible last line; across a page or a figure the paragraph continues unless its last
line ended it. Depth from the printed number; 202 title-only sub-headings and 25 inline headings head the paragraph
after them; every paragraph gets part → sub-part → canonical section → sub-heading path. **Problems:** 57 signature
rows (names, ranks, offices) and a "Copy:" line had reached the body; OCR numbers with spaces ("4 .1. 8."); wrapped
cross-references ("…discussed in / 4.2.19.") and decimals ("5.90 hours") at a line start; a number printed alone on
its row; a quoted university guideline numbered "3.1.1…3.2.16" inside 4.4.3.3; eight numbering errors printed in
the source. **Fixes:** role corrections recorded; atomic number patterns; lone numbers accepted only after a finished
line; the quoted list as items; the eight exceptions reviewed and kept as printed.

## Phase 9 — Units, errata, access, personal data
2,998 units (paragraphs, notes, vessel blocks, persons, glossaries; the 204 figure captions stay metadata: raster
photos the system cannot show, whose few facts the report text already prints). Errata (ADR-022): KIM_LY's summary
clause "On 19 February 2024," contradicts the report's own dates → excluded, never corrected; numbering slips kept
as printed and recorded. Access (ADR-021): 60 money-term candidates reviewed → all level 1 / Operations (facts of a
public federal report). Personal data (plan §4.6): report text as published; in curated text, individual owners /
operators of 7 reports are written as roles (every other printed party is a company or a redacted name — asserted),
signer names never appear, persons units keep roles only (QUEEN_OF_THE_WEST's Name cell excluded).

## Phases 10–12 — Dedup
Within a report the Executive Summary is non-canonical (plan §4.4): 49 sentences the report already prints were
trimmed and 2 summary units dropped (coverage test: ≥ 85 % of content words and every number in one report sentence).
The letters' restatements of the recommendations (390 sentences) were **kept** and recorded: each letter is its own
decision document and the recommendation beside its action is the answerable unit. Template boilerplate across
reports (39 sentences) stays in context (plan §4.5). Across sources: 0 sentences already in the 619 chunks.

## Phase 12b — IMO incident profiles
23 profiles, 407 values: printed values (date, ship particulars), counts of printed rows (ships, dead or missing
crew / passengers / others), and 68 reviewed codes (location, overall casualty event, severity) each with its
evidence sentence. **Deliberately not coded:** "seriously injured" (the reports print "Injured" only) and one location
the text does not establish (GOOD_GULF). CUMBERLAND_II's car driver counts as "other", not crew.

## Phase 13 — Saved files
`extracted/USCG_ROI_extracted.json` (per-report layers + incident profiles with evidence + corpus-level superscripts,
role corrections, errata, access decisions) and `cleaned/USCG_ROI_logical_units.json`
(`{source, units, duplicate_audit, coverage_audit}`), both reloaded and re-validated.

## Phases 14–15 — Chunking (the best split per content)
1,544 chunks: one per vessel table, persons table, glossary, note and incident profile; a numbered finding with its
sub-items; 6.1 Determination of Cause whole when it fits (16 reports; longer ones split balanced); a recommendation
with its action / endorsement; prose grouped while short. Short
groups are joined in reading order inside one section; long ones are split into the fewest balanced parts at unit,
then sentence boundaries (209 parts). 40 chunks stay below 300 characters because they are whole: a one-line
section ("7.1. There have been no actions taken since the incident.") or a short table — a chunk never crosses a
section. Median 672, maximum 2,000 characters, header on every chunk.

## Phases 16–18 — Schema, save, cross-source
16-column schema with the corpus dtypes, `chunks/USCG_ROI_chunks.parquet` saved, reloaded and compared cell by cell;
corpus = 619 + 1,544 = 2,163 chunks, `chunk_id` unique.

## Phase 19 — Coverage of every line
18,999 lines, each with one disposition, **0 unaccounted**: 14,540 in their own unit's chunks (3,127 of them OCR
lines), the rest metadata (incl. the figure captions), layout, signatures, figure-internal text, trimmed summary lines, the erratum, role-replaced
party cells, one excluded Name cell and the redacted notes. **Problems caught here and fixed upstream:** captions
whose restored ordinals were missing (extracted figure list), a unit split over two chunks, the CUYAHOGA "None / N/A"
table, QUEEN_OF_THE_WEST's "Period of Employment" column, and three individual owners in "Owner/Operator" cells
that the first party list had missed.

## Phase 20 — Profile trace
All 407 profile values traced: printed values to their lines, counts recomputed from the persons rows (= the 26 dead
or missing of Phase 4), each code to an existing evidence sentence and an option of the IMO catalogue.

## Decisions on the last open points (closed 2026-09-27)
- The letters' restated recommendations are **kept** (recorded in the duplicate audit): each letter is a decision
  document, and the recommendation beside its action is the answerable unit (ADR-019 extension).
- The 35 `diagram_or_chart` figures are raster images: their values cannot be checked against printed text, so they
  are `caption_only` by rule; render reviews apply to vector figures (ADR-020 extension).
- IMO codes cover only what the reports print or state explicitly (location, casualty event, severity); ship
  operation, accident events and contributing factors need an investigator's interpretation and are not coded
  (ADR-023 extension).
