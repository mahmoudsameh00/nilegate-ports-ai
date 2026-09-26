# USCG Reports of Investigation (23) — Template-driven Ingestion, Chunking & IMO Coding Plan

**Status: PROPOSED (2026-09-26)** — review §4 and approve before any notebook work.

**Planned notebook:** `Notebooks/USCG_ROI_chunking.ipynb` (one notebook for the 23 reports — §4.1)
**Primary input:** `Data/raw/unstructured/us_coast_guard_reports/*_ROI_Redacted.pdf` (23 files, 580 pages, 98 MB; ADR-007)
**Companion source:** `Notebooks/IMO_MSC-MEPC_3_Circ_4_Rev_1_chunking.ipynb` and its field catalogue (`extracted/IMO_MSC-MEPC_3_Circ_4_Rev_1_extracted.json`, key `field_catalogue`, ADR-023)
**Reference notebooks:** IMO (rows by baseline, grids from cell borders, numbered-item blocks, balanced splits, coverage audit), HbR (summary dedup policy, errata, access per unit). Closed plans in `docs/archive/`.
**Governing decisions:** ADR-007, ADR-008, ADR-009, ADR-010/019, ADR-020, ADR-021, ADR-022, ADR-023, `docs/rbac_mapping.md` §4 (USCG = level 1 / Operations).

---

## 0. Reconnaissance (2026-09-26) — cheap, without parsing every report

**Principle (owner's request):** no per-file parsing to learn the format. Two cheap passes only:

1. **Inventory of all 23** (`pdfinfo`, per-page text length from `pdftotext`, `pdfimages -list` — metadata, no layout parsing);
2. **Template reading on a seeded random sample** (`random.seed(42)` over the sorted file list → VICAR_602, CUMBERLAND_II, BIG_STICK, KIM_LY) plus a look at the first pages of two image-only reports.

**Inventory facts**

- 11–97 pages per report (SPIRIT_OF_BOSTON 97, CAROL_ANN 51, CONCHRD 45; most 13–23). Producers: Word → PDF (PDFMaker/Distiller), "Microsoft", a Lexmark scan (VICAR_602) and an Acrobat "Paper Capture" OCR (MERRICK).
- **Text layer classes:**
  - 19 reports with a text layer (VICAR_602 and MERRICK through an OCR layer → quality check needed);
  - **4 reports whose body is image-only**: H20_BELOW (p.4–16 no text), PROWLER_ATTESSA_IV (p.4–22), QUEEN_OF_THE_WEST (p.5–23), UNA_MAS (p.5–14). Only the Commandant / endorsement letters have text.
- Image-only pages inside text reports (photos, enclosures, charts): e.g. CUYAHOGA 6 pages, LITTLE_G 8, WAYMON_BOYD 7, LADY_ELLEN 5, SPIRIT_OF_BOSTON 4. The cover (p.1) is often an image.

**The common ROI template (identical in the 4 samples)**

| Part | Content | Parsing hint |
|---|---|---|
| Cover | "Report of the Investigation into …", MISLE Activity Number | often image; the MISLE number is also in the file name |
| Front matter (letters) | **ACTION BY THE COMMANDANT** (+ ACTION ON RECOMMENDATIONS), **ENDORSEMENT BY THE COMMANDER** (district, + ENDORSEMENT ON RECOMMENDATIONS), **ENDORSEMENT BY THE OFFICER IN CHARGE, MARINE INSPECTION** (+ COMMENTS ON THE REPORT), **EXECUTIVE SUMMARY** | each letter = letterhead + file/date block + casualty title + centred bold heading + text + signature + "Enclosures:" list |
| 1 Preliminary Statement | 1.1–1.4 standard statements (authority, parties in interest, lead agency, time zone) | numbered paragraphs |
| 2 Vessel(s) Involved | one key–value block per vessel/craft: Official Name, Identification Number, Flag, Vessel Class/Type/Sub-Type, Build Year, Gross Tonnage, Length, Beam/Width, Draft/Depth, Main/Primary Propulsion, Owner, Operator (11–12 labels) | label column + value column; title variants "Vessels and Motor Vehicle Involved", "Craft Involved" |
| 3 Deceased, Missing, and/or Injured Persons | table: Relationship to Vessel · Sex · Age · Status | title variant "Record of Deceased, Missing, and Injured" |
| 4 Findings of Fact | 4.1 The Incident (4.1.1 …), 4.2 Additional/Supporting Information | numbered paragraphs, figures "Figure N: …" (3–12 per report) |
| 5 Analysis | 5.N titled paragraphs | |
| 6 Conclusions | **6.1 Determination of Cause**: "The initiating event … Causal factors …" (6.1.1.1 …); 6.2–6.7 standard findings (violations by credentialed mariners / USCG personnel, civil penalty, criminal acts, need for new law, unsafe non-causal conditions) | |
| 7 Actions Taken Since the Incident | | |
| 8 Recommendations | 8.1 Safety, 8.2 Administrative | the Commandant's "Action on recommendations" answers them |

Observed anomalies already: BIG_STICK prints the heading "**5.** Conclusions" above paragraphs 6.1–6.7 (numbering slip); redactions leave blanks (e-mail, owner); some redacted reports still print private names (operator of BIG_STICK).

## 1. Goal and design principles

Same guarantees as the other notebooks (16-column schema, reviewed snapshots, errata with evidence, nothing flagged or pending, whole-corpus coverage audit, Final Checkpoint), plus two new ones:

1. **Parse by template, not by file.** The ROI template (§0) is written once as a reviewed spec; every report is first *fingerprinted* against it (cheap, text-only); conforming reports go through one template-driven parser; only the reports that deviate are inspected individually.
2. **Use the IMO circular as the coding vocabulary.** Each report gets an **IMO incident profile** coded with the IMO field catalogue — mechanically where the ROI prints the fact, by reviewed decision (with a quoted evidence sentence) where it is interpretation.

## 2. What the IMO work gives this task

| IMO asset | Use for the USCG reports |
|---|---|
| Rows by baseline, superscript/subscript handling (IMO Phase 3) | same Word-generated layout: paragraph numbers and text on one baseline, footnote markers |
| Grids from drawn cell borders + word-level split (4.1) | Section 2 key–value blocks and Section 3 persons tables |
| Numbered items and atomic blocks (Appendix 4, 4.3) | ROI paragraph numbering 4.1.1 / 6.1.1.1 (depth = number of dots), "Causal factors … were:" lists kept with their event |
| Balanced splits with repeated header (14.1) | long Findings / Analysis subsections |
| Errata (ADR-022), coverage audit (Phase 19) | per report and for the corpus |
| **Field catalogue** (ADR-023) | coding vocabulary of the incident profiles (below) |

**IMO incident profile (one per report)**

| ROI source | IMO fields | Method |
|---|---|---|
| Section 2 vessel block | App. 2 group 1 Ship particulars: name (2.1.2), identification number (2.1.1 IMO number / O.N.), flag (2.1.5), type of ship (2.1.6), gross tonnage (2.1.7), length overall (2.1.8), registered owner (2.1.10), year of build (2.1.12), propulsion (2.1.16) | **printed** — label → field, value copied |
| Section 3 persons table | App. 2 group 4 Consequences (2.4.1–2.4.6 dead/missing/injured crew, passengers, others); App. 3 subject age (3.2.1) and gender (3.2.2) | **printed** — counted from the rows |
| Title / Executive summary / 4.1 | App. 1 generic casualty data: date (1.2.2), location (1.2.6, Table 3) | date printed; location **reviewed** with its sentence |
| 6.1 Determination of Cause | casualty event (2.3.1 / 1.2.7, Table 4), accident event (3.1.1, Table 16), error type and contributing factors (Tables 19–25) | **reviewed** decision per report, evidence sentence id required |
| — | casualty severity (Table 5) | **not coded**: the circular does not define the severity classes, so no evidence in the corpus supports a classification |

Uses: (1) retrieval can answer "which reports were a fall overboard / a collision / fatigue-related?" with evidence; (2) the synthetic incidents (ADR-007) get real, IMO-coded examples to imitate; (3) a later Analytics Agent can count incidents by IMO category. The profile is stored in the extracted file (ADR-023 pattern) and, if approved (§4.3), as one curated chunk per report.

## 3. Phases (same numbering scheme as the reference notebooks)

| Phase | Content | Notes |
|---|---|---|
| 0 | Setup: corpus list, per-file SHA-256, metadata, access | `document_type = uscg_report_of_investigation`, `source = United States Coast Guard`, level 1 / Operations (rbac_mapping §4); `filename` per chunk |
| 1 | **Corpus inventory** (all 23, cheap) | pages, text chars per page, images, producer, page size; page text classes `text` / `ocr_layer` / `image_only` |
| 2 | **Template spec** from the seeded sample | reviewed `ROI_TEMPLATE`: front-matter letters, sections 1–8 with title variants, numbering pattern, vessel labels, persons header, caption pattern, header/footer/letterhead patterns |
| 3 | **Template fingerprint of all 23** (text-only regex) | per report: sections found and order, numbering continuity, vessel labels, persons table, captions → `conformant` / `deviating (what)` / `image_only`; reviewed snapshot; **3b: individual inspection of the deviating reports only** |
| 4 | Template-driven structured extraction | letters, executive summary, vessel blocks, persons tables, figures (captions; photos `caption_only`, diagrams/charts through the ADR-020 gate), "Enclosures" lists |
| 5 | Notes / footnotes | policy as in the IMO/LPI notebooks |
| 6–8 | Body, numbered paragraphs, sections | paragraphs across pages; depth from the numbering; section title variants mapped to the canonical 8 sections |
| 9 | Units, errata, access, PII check | numbering slips recorded (BIG_STICK "5. Conclusions"); §4.6 |
| 10–12 | Dedup | within report: Executive Summary non-canonical (§4.4); across reports: boilerplate kept in context (§4.5); cross-source vs the 619 chunks |
| 13 | Save: ONE extracted (per-report layers + incident profiles), ONE cleaned file `{source, units, duplicate_audit, coverage_audit}` | |
| 14–15 | Chunking + validation | chunk header = `USCG ROI <vessel> (MISLE <n>, <incident date>) — <section path>` so every chunk stands alone; one chunk per vessel block and per persons table; 6.1 Determination of Cause kept whole (event + causal factors); recommendations with the Commandant's action |
| 16–18 | Schema, save/reload, cross-source | expected corpus = 619 + USCG chunks |
| 19 | Coverage audit per report and for the corpus | 0 unaccounted; image-only pages `page_excluded:image_only` (§4.2) |
| 20 | **IMO incident profiles** + validation | every printed value traced to its line; every reviewed code has an evidence sentence id; codes exist in the catalogue |
| Final | Final Checkpoint code + markdown | |

## 4. Open questions for the owner (proposed answers)

1. **One notebook for the 23 reports.** They share one template, so ADR-008 ("one notebook per source") is read as *the ROI corpus is one source*. Proposed: yes — one notebook, one extracted, one cleaned and one chunks file, `filename` per chunk (records a refinement of ADR-008).
2. **The 4 image-only reports** (H20_BELOW, PROWLER_ATTESSA_IV, QUEEN_OF_THE_WEST, UNA_MAS). (a) OCR now — needs Tesseract installed on Windows + PyMuPDF OCR (new system dependency, an ADR); (b) **ingest their text front matter now, record the image-only pages as `page_excluded:image_only`, and plan OCR as a separate task** — proposed (b). The two OCR-layer reports (VICAR_602, MERRICK) are kept if they pass an OCR-quality check (share of dictionary words per page).
3. **IMO incident profile**: stored in the extracted file (proposed yes) **and** as one curated `incident_profile` chunk per report whose every value carries its evidence (proposed yes; `provenance = curated_from_report`, ADR-020 rule: only values printed in the report).
4. **Executive Summary** = a summary of its own report → non-canonical (HbR policy, ADR-019): sentences fully covered by Findings/Analysis/Conclusions are trimmed, new ones kept. Proposed yes.
5. **Boilerplate across reports** (endorsement approvals, 1.1–1.4 preliminary statements, the 6.2–6.6 "no violations identified" findings): the same sentences in 23 reports would crowd retrieval. Proposed: kept **inside their report's chunks** (they are facts about that casualty) but never as standalone chunks; the standard preliminary statements (1.1–1.4) are merged with the report's first section chunk.
6. **Personal names.** The reports are public, redacted releases (rbac_mapping §4: level 1) but some still print names of private persons (operators, deceased). Proposed: keep level 1 as mapped, keep the text as published, and **use roles, not names, in the incident profiles and chunk headers**.
7. **`version_date`** = the date of the Commandant's action (final approval, printed in the first letter); the incident date goes into the chunk header and the profile. Proposed yes.
8. **Sample size.** Seed 42, 4 reports; the sample is extended only if the Phase 3 fingerprint shows a variant not seen in it. Proposed yes.

## 5. Validation targets

- Inventory covers 23 files / 580 pages; every page has a text class; the image-only pages match §0.
- Every report has a fingerprint row; every deviation is either handled by the parser or listed with its individual decision (Phase 3b).
- Every vessel block has its printed labels; every persons row is a unit; numbering is continuous per section (slips recorded).
- Every IMO code in a profile exists in the IMO field catalogue; every reviewed code has an evidence sentence id; printed values match their lines.
- Coverage: every text line of every report has a disposition; 0 unaccounted.
