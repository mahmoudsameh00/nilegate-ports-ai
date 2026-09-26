# USCG Reports of Investigation (23) — Template-driven Ingestion, Chunking & IMO Coding Plan

**Status: IMPLEMENTED (2026-09-27)** — approved 2026-09-26 — the owner answered §4 on 2026-09-26 (one notebook; **OCR the image-only pages**; chunking chosen per content, no fixed rule; roles instead of names); the other §4 answers are adopted as proposed. Implementation details not fixed here are delegated to the implementing session, which records every decision and deviation in §6 (dated log).

**Planned notebook:** `Notebooks/USCG_ROI_chunking.ipynb` (one notebook for the 23 reports — §4.1, approved)
**Primary input:** `Data/raw/unstructured/us_coast_guard_reports/*_ROI_Redacted.pdf` (23 files, 580 pages, 98 MB; ADR-007)
**Companion source:** `Notebooks/IMO_MSC-MEPC_3_Circ_4_Rev_1_chunking.ipynb` and its field catalogue (`extracted/IMO_MSC-MEPC_3_Circ_4_Rev_1_extracted.json`, key `field_catalogue`, ADR-023)
**Reference notebooks:** IMO (rows by baseline, grids from cell borders, numbered-item blocks, balanced splits, coverage audit), HbR (summary dedup policy, errata, access per unit). Closed plans in `docs/archive/`.
**Governing decisions:** ADR-007, ADR-008, ADR-009, ADR-010/019, ADR-020, ADR-021, ADR-022, ADR-023, `docs/rbac_mapping.md` §4 (USCG = level 1 / Operations).


## Implementation record (2026-09-27)

**Status: IMPLEMENTED (2026-09-27).** `Notebooks/USCG_ROI_chunking.ipynb`: 86 cells, Phases 0–20 + Final Checkpoint,
nbconvert run 0 errors, 17 validation cells passed. The notebook's Final Checkpoint markdown is the authoritative
description of every step, its problems and their fixes.

**Results.** 23 reports / 580 pages (text 446, image-only 115 OCR'd with RapidOCR, OCR layer 19); 18,999 lines,
17,471 rows; 116 document parts, 297 vessel/vehicle fields, 41 persons (roles only), 204 caption units (all
`caption_only`); 93 notes (22 informative / 65 citation-only / 6 redacted), 44 superscripts restored; 3,170 paragraphs;
3,223 units (incl. 23 incident profiles); Executive Summary: 49 sentences trimmed, 2 units dropped; 0 cross-source
duplicates; **1,609 chunks** (median 664, max 2,000 characters; 71 whole short pieces below MIN), all level 1 /
Operations; corpus 619 + 1,609 = **2,228**; coverage 18,999 lines, **0 unaccounted**; 407 profile values traced.
Artifacts: `extracted/USCG_ROI_extracted.json`, `cleaned/USCG_ROI_logical_units.json`
(`{source, units, duplicate_audit, coverage_audit}`), `chunks/USCG_ROI_chunks.parquet`, OCR cache
`ocr_cache/USCG_ROI/` (134 files).

**Deviations from the plan (all recorded in §6).**
- Phase 12b added: incident profiles built before the save (Phase 13) and traced in Phase 20. Coded: 1.2.2, 1.1.2,
  ship particulars, 2.4.1–2.4.3 and three reviewed codes (1.2.6 location, 1.2.7 casualty event, 1.2.8 severity);
  "seriously injured" not coded (reports print "Injured" only); GOOD_GULF location left empty with its reason.
- Only the Executive Summary is trimmed within a report; the letters' restated recommendations (390 sentences) are
  kept and recorded in the duplicate audit.
- Phase 4 corrections made in Phases 5–6: 57 signature rows, SPIRIT List of Figures/Tables → metadata, OCR figure
  labels, one caption line, a "Copy:" line; `survivor_unspecified` outcome (Phase 4).
- Personal data: individual owners/operators of 7 reports written as roles in curated text (guarded by an assert
  that every other printed party is a company or a redacted name); a persons-table Name cell excluded.
- Figures: ADR-020 gate applied by rule (raster, no text-readable data), not reviewed against renders.

**Lasting decisions → ADRs:** ADR-024 (a source may be a corpus of same-template documents; refines ADR-008),
ADR-025 (OCR with RapidOCR: dependency, cache, provenance, readability gate), ADR-026 (personal data in public
reports: text as published, roles in curated text).

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

0. **Cost rule (owner):** never parse every PDF to learn the format. Learn it from seeded random samples and from the IMO template, fingerprint all reports cheaply, and look individually only at the abnormal ones.
1. **Parse by template, not by file.** The ROI template (§0) is written once as a reviewed spec; every report is first *fingerprinted* against it (cheap, text-only); conforming reports go through one template-driven parser; only the reports that deviate are inspected individually.
2. **OCR where there is no text (owner decision).** Image-only pages are OCR'd (RapidOCR, installed with uv), not skipped; OCR text is marked as such (provenance `ocr`), passes a readability gate, and is cached so a re-run does not OCR again.
3. **Chunking follows the content, not a fixed rule (owner decision).** Each section type gets the split that reads best on the samples (a paragraph, a numbered finding with its sub-items, a whole Determination of Cause, one vessel block…); `MAX_CHUNK_CHARS = 2000` stays a safety cap and chunks under 50 characters are still forbidden, but `MIN_CHUNK_CHARS` is a guideline, not a rule.
4. **Use the IMO circular as the coding vocabulary.** Each report gets an **IMO incident profile** coded with the IMO field catalogue — mechanically where the ROI prints the fact, by reviewed decision (with a quoted evidence sentence) where it is interpretation.

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
| 1b | **OCR** of every `image_only` page that carries text, and quality check of the two OCR layers (VICAR_602, MERRICK) | RapidOCR on the PyMuPDF page render (≥ 300 dpi): detected boxes → text lines in PDF coordinates (px × 72 / dpi), with the recognizer's confidence per line; per-page cache with engine/model versions, dpi and render settings; readability gate (share of dictionary words, mean word length); photos without text stay images (→ figure gate); a page that fails the gate after OCR is excluded with its reason, never silently; OCR text goes through the same template parser as native text |
| 2 | **Template spec** from the seeded sample | reviewed `ROI_TEMPLATE`: front-matter letters, sections 1–8 with title variants, numbering pattern, vessel labels, persons header, caption pattern, header/footer/letterhead patterns |
| 3 | **Template fingerprint of all 23** (text-only regex) | per report: sections found and order, numbering continuity, vessel labels, persons table, captions → `conformant` / `deviating (what)` / `image_only`; reviewed snapshot; **3b: individual inspection of the deviating reports only** |
| 4 | Template-driven structured extraction | letters, executive summary, vessel blocks, persons tables, figures (captions; photos `caption_only`, diagrams/charts through the ADR-020 gate), "Enclosures" lists |
| 5 | Notes / footnotes | policy as in the IMO/LPI notebooks |
| 6–8 | Body, numbered paragraphs, sections | paragraphs across pages; depth from the numbering; section title variants mapped to the canonical 8 sections |
| 9 | Units, errata, access, PII check | numbering slips recorded (BIG_STICK "5. Conclusions"); §4.6 |
| 10–12 | Dedup | within report: Executive Summary non-canonical (§4.4); across reports: boilerplate kept in context (§4.5); cross-source vs the 619 chunks |
| 13 | Save: ONE extracted (per-report layers + incident profiles), ONE cleaned file `{source, units, duplicate_audit, coverage_audit}` | |
| 14–15 | Chunking + validation | **best split per content, reviewed on the samples** (owner): chunk header = `USCG ROI <vessel> (MISLE <n>, <incident date>) — <section path>` so every chunk stands alone; candidates to decide on evidence: one chunk per vessel block and per persons table, 6.1 Determination of Cause whole (event + causal factors), a numbered finding with its sub-items, recommendations with the Commandant's action; the chosen split per section type and its reason are recorded in §6 and in the Final Checkpoint |
| 16–18 | Schema, save/reload, cross-source | expected corpus = 619 + USCG chunks |
| 19 | Coverage audit per report and for the corpus | 0 unaccounted; OCR lines verified against their chunks like native lines (disposition `in_chunks_ocr`); photo-only pages `page_excluded:photo`; a page that failed the OCR gate `ocr_unreadable` with its evidence |
| 20 | **IMO incident profiles** + validation | every printed value traced to its line; every reviewed code has an evidence sentence id; codes exist in the catalogue |
| Final | Final Checkpoint code + markdown | |

## 4. Decisions (owner, 2026-09-26)

1. **One notebook for the 23 reports — approved.** The ROI corpus is one source (ADR-008 refined: one notebook per *source*, a source may be a corpus of same-template documents): one extracted, one cleaned and one chunks file, `filename` per chunk. Record the refinement as an ADR.
2. **OCR — approved (owner: "do OCR").** The 4 image-only reports (H20_BELOW, PROWLER_ATTESSA_IV, QUEEN_OF_THE_WEST, UNA_MAS) and every image-only page that carries text in the other reports are OCR'd (Phase 1b). Engine (owner, 2026-09-26: "must install with uv"): **RapidOCR (`rapidocr` + `onnxruntime`, installed with uv — pure Python wheels, models bundled, no system install; owner decision 2026-09-26)**, added to `pyproject.toml` / `uv.lock` with pinned versions like the other dependencies. Tesseract is **not** used (it needs a system install). The implementing session first checks the engine on the image-only pages of the sample; if its quality fails the readability gate, it stops and asks before any other engine. Record the dependency and the OCR policy (cache, provenance, confidence, readability gate) as an ADR. The OCR cache is an artifact owned by this notebook. The two OCR-layer reports (VICAR_602, MERRICK) keep their layer if it passes the same gate, otherwise they are re-OCR'd.
3. **IMO incident profile** in the extracted file **and** one curated `incident_profile` chunk per report whose every value carries its evidence — adopted as proposed (`provenance = curated_from_report`, ADR-020 rule: only values printed in the report).
4. **Executive Summary non-canonical** (HbR policy, ADR-019): covered sentences trimmed, new ones kept — adopted as proposed.
5. **Boilerplate across reports** kept inside each report's chunks, never as standalone chunks — adopted as proposed.
6. **Roles instead of names — approved.** Incident profiles, chunk headers, titles and any curated text use roles ("the operator", "a deckhand", "the deceased passenger"), never personal names. Report text is kept as published (public redacted release, level 1 / Operations per rbac_mapping §4).
7. **Chunking — owner: "the best split, not a fixed rule".** See §1.3 and Phase 14.
8. **`version_date`** = date of the Commandant's action; incident date in the chunk header and the profile — adopted as proposed.
9. **Sample:** seed 42, 4 reports (VICAR_602, CUMBERLAND_II, BIG_STICK, KIM_LY), extended only when the Phase 3 fingerprint shows an unseen variant — adopted as proposed; add one image-only report to the sample for the OCR path.

## 5. Validation targets

- Inventory covers 23 files / 580 pages; every page has a text class; the image-only pages match §0; every OCR'd page has its cache entry and its readability result.
- Every report has a fingerprint row; every deviation is either handled by the parser or listed with its individual decision (Phase 3b).
- Every vessel block has its printed labels; every persons row is a unit; numbering is continuous per section (slips recorded).
- Every IMO code in a profile exists in the IMO field catalogue; every reviewed code has an evidence sentence id; printed values match their lines.
- Coverage: every text line of every report has a disposition; 0 unaccounted.

## 6. Implementation log

- 2026-09-26 — Plan approved by the owner (§4). Implementation delegated to a new session (the coding assistant in Cursor).
- 2026-09-26 — Owner: the OCR engine must install with uv → RapidOCR (`rapidocr` + `onnxruntime`) instead of Tesseract.
- 2026-09-26 — Implementation session started (execution plan approved). `rapidocr 3.9.2` / `onnxruntime 1.30.0` import in `.venv`; models (PP-OCRv6 det/rec small + mobile cls) ship inside the package → no download at run time. `pyproject.toml` declares them with `>=`; owner pins them with `uv add "rapidocr==3.9.2" "onnxruntime==1.30.0"`.
- 2026-09-26 — Decisions (delegated): `SOURCE_NAME = USCG_ROI` (artifacts `extracted/USCG_ROI_extracted.json`, `cleaned/USCG_ROI_logical_units.json`, `chunks/USCG_ROI_chunks.parquet`); `CHUNK_PREFIX = uscg`; `source = United States Coast Guard`; `report_id` = the vessel part of the file name, MISLE = its 7 digits. **OCR cache** = `Data/processed/rag/ocr_cache/USCG_ROI/<report>_p<NNN>.json` (one file per OCR'd page, keyed by PDF sha256 / page / dpi / engine + model versions; kept out of the extracted file so that file stays one readable JSON). OCR sample report = UNA_MAS (fewest pages of the four image-only bodies). The raw-layout export review aid of the IMO notebook (1.6) is not repeated: 23 files would give a very large scratch file and Phases 2–3 inspect the sample directly.
- 2026-09-26 — Phase 1 (reconnaissance correction): the "OCR layer" takes two forms — an invisible render-mode-3 layer (MERRICK p.7–19, Acrobat Paper Capture) and **visible Acrobat editable OCR text** in substitute fonts named `*…` over a full-page scan (the scanned letters VICAR_602 p.3/5, MERRICK p.4/6, CONCHRD p.3, TOO_SHORT p.4). VICAR_602 itself is native Word text (the Lexmark producer only concerns its scanned pages). QUEEN_OF_THE_WEST p.22 has an invisible layer of spaces only → `image_only`. Page classes: 446 `text`, 19 `ocr_layer` (4 reports), 115 `image_only` (19 reports).
- 2026-09-26 — Bug fixed in Phase 0 (0.5): `PROJECT_ROOT = CORPUS_DIR.parents[2]` pointed at `Data/` (the corpus is a folder, not a file as in the IMO notebook); the owner's first run created empty folders `Data/Data/processed/rag/...`, removed (empty, no file written). Now `parents[3]` + an assert that the root holds `pyproject.toml`.
- 2026-09-26 — Phase 1b (OCR) decisions, all measured on the OCR sample and then on all 134 pages:
  - RapidOCR settings: `text_score = 0` (the default 0.5 silently drops low-confidence lines); `max_side_len = 2000` kept (3400 was 40 % slower and not better). **Retry of weak lines:** a line < 0.95 is recognised again from its own crop of the 300-dpi render; the better reading is kept, the first one stays in the cache (UNA_MAS p.5: a 0.742 garbled line became the correct sentence at 0.996). **Engine quirk:** RapidOCR keeps the `use_det/use_cls/use_rec` flags of the previous call, so a rec-only retry switched detection off for every later page (first full run: 131 pages with 0 lines) — the flags are now passed on every call.
  - **No bare photo page:** all 115 `image_only` pages carry text (scanned letters and body pages, covers, pages with figures). RapidOCR also reads text *inside* figures (chart soundings, screen labels, personal names on a diagram), so figure regions are found in the page image: text boxes painted white, remaining ink split into connected regions typed `redaction` (solid black box), `table` (straight rules on white paper: density ≤ 0.25, straight ≥ 0.6, light fill ≤ 0.15 — the light-fill test added after a boxed Google-Earth map passed as a table) or `graphic`; graphic regions ≥ 100 × 50 pt are merged by their y-range into **figure bands** (one chart = 3 regions on UNA_MAS p.8). Lines in a band (not captions) are `figure_internal` (417 lines on the used pages). Every long figure-internal line and every questionable band was checked on renders (map title, capacity plate, screen header, diagram label; the large bands on letter pages are redaction boxes → now `redaction`, never a band).
  - **Gate** (body lines only): dictionary share ≥ 0.75 (dictionary = words seen ≥ 2× on native pages, no new dependency) and mean confidence ≥ 0.90. First threshold 0.80 → lowered to 0.75 on evidence: H20_BELOW p.15 is fully readable (confidence 0.994) but that report is scanned end to end, so its diving vocabulary is absent from the dictionary. All 153 readings pass; no page is `ocr_unreadable`.
  - **OCR layers kept:** the 19 layers pass the gate and agree 0.89–1.00 word by word with the independent RapidOCR reading.
  - **OCR noise:** readings < 0.80 of ≤ 2 characters are marks, not text (2: letterhead seal read as "3", signature stroke read as "V"; checked on renders).
  - **Dependency note (asked):** the region analysis uses `scipy.ndimage` (scipy 1.18.1, already installed as a dependency of scikit-learn, not declared in `pyproject.toml`) — owner asked whether to declare it (`uv add "scipy==1.18.1"`, no new install).

### 2026-09-26 — §6 log entry: status at session stop (Phases 0–3 in the notebook, Phase 4 in scratch)
**Phases done (in `Notebooks/USCG_ROI_chunking.ipynb`, 34 cells, last `nbconvert --execute` run: 0 errors)**
- Cells 0–14 (batch A): Phase 0 setup (`PROJECT_ROOT = CORPUS_DIR.parents[3]` + assert, SOURCE_NAME `USCG_ROI`, level 1 / Operations, MIN 300 / MAX 2000 / FRAGMENT 50, prefix `uscg`, per-file sha256, seed-42 sample VICAR_602 / CUMBERLAND_II / BIG_STICK / KIM_LY + OCR sample UNA_MAS) and Phase 1 inventory (`pages_df`, `text_class` text / ocr_layer / image_only).
- Cells 15–24 (B1, B2): Phase 1b OCR — RapidOCR 3.9.2 + onnxruntime 1.30.0, 300 dpi, retry below conf 0.95, pad 4, `text_score 0.0`, `max_side_len 2000`; cache `Data/processed/rag/ocr_cache/USCG_ROI/` (134 page files, keyed by sha256/page/dpi/versions); figure regions (redaction / table / graphic) and figure bands; readability gate dictionary share ≥ 0.75 and mean conf ≥ 0.90 (lowered from 0.80 on evidence: H20_BELOW p.15 diving vocabulary); OCR-layer check; `text_source` native 446 / ocr 115 / ocr_layer 19 pages. Gate passed — no stop needed.
- Cells 25–29 (C): Phase 2 — `clean_text` (native glyph shift +29, CUYAHOGA repairs, OCR control chars removed), `lines_df` (native 14224 / ocr 4085 / ocr_layer 690), `rows_df` with non-overlapping subrows and segments, `ROI_TEMPLATE`, `letter_of`, `section_of`.
- Cells 30–33 (C3): Phase 3 / 3b — fingerprint of all 23, 19 reviewed deviations with decisions, status conformant 12 / deviating 11, numbering slips BIG_STICK 6→"5", LA6893ER 5→"4", SPIRIT_OF_BOSTON 4→"3".

**Phase 4 (not yet in the notebook; scratch cell files `uscg_cells_D1/D2/D3.py`)**
- D1 row roles (22 roles; body 14043 …); D2 document parts, dates, `meta_df` (tested); D3 vessel/vehicle fields by horizontal rules and persons tables by header columns — **untested** after the last fixes.

**Decisions taken (implementation details delegated by the owner)**
- `scipy==1.18.1` and `nbconvert==7.17.1` were added **by me** with `uv add` under the autonomous-mode rule (correcting the earlier note "owner asked").
- version_date = the Commandant action date (the later one when there are two: QUEEN_OF_THE_WEST); incident date = most frequent date in the casualty titles; vessel label = first official name uppercased, PROWLER labelled "PROWLER / ATTESSA IV".
- SPIRIT_OF_BOSTON: the leading MEMORANDUM = `convening_memorandum`; its two Findings parts = canonical section 4.
- CUYAHOGA / LITTLE_G: report start anchored at "1. Preliminary Statement".
- Signature blocks excluded (names only, no retrieval value); an individual vessel owner gets a role label, never the name.
- KIM_LY incident date 2024-02-20; the executive-summary clause "On 19 February 2024," is an ADR-022 erratum; the Commandant title's "19" is a recorded metadata conflict.
- CONCHRD list of acronyms = one glossary unit; names printed inside the CUYAHOGA figure = figure_internal.
- Vessel tables: cells from drawn horizontal rules (native drawings / dark pixel runs on scans); persons tables: columns from the header segments; 'None'/'N/A' rows (CUYAHOGA) recorded as a statement, not a person.
- Planned for persons: reviewed keyword mapping class crew / passenger / other and outcome dead_or_missing / injured / uninjured; names never in curated text.

**Open issues**
- D3 vessel fixes (UNA_MAS label continuation, value-only cell merge, block_kind carry-over) and the persons parser are untested; D3 prints whole DataFrames → must become counts + `head()` (token discipline).
- Phase 4 remaining: persons class/outcome mapping, figures + captions (ADR-020 gate, photos caption_only), enclosures + TOC cross-check, Phase 4 validation snapshot; then append D1–D3 to the notebook and run nbconvert into a log checked with `nb_check.py`.
- Phases 5–20 + Final Checkpoint and the closing steps are not started.

### 2026-09-26 — §6 log entry (verified from files after context compaction)
- **Verified phases in the notebook** (34 cells, ids from the .ipynb): Phase 0 = cells 0–9 (`c0df49bb`…`277d7df4`), Phase 1 = 10–14 (`663afc78`…`4e168c8e`), Phase 1b = 15–24 (`4d4c3b7a`…`c7bea44c`), Phase 2 = 25–29 (`9df427c6`…`b1df9d60`), Phase 3/3b = 30–33 (`b9c0c7c7`…`e87288ce`). `run_nb.log` ends with nbconvert writing the notebook (no traceback in its tail). Phase 4+ is **not** in the notebook.
- **Verified scratch state:** cell files `uscg_cells_D1/D2/D3.py` hold Phase 4 draft code; `test_D.log` has no Traceback, but it predates the last D3 edits (persons parser, vessel fixes) → D3 remains untested. State pickles `state/uscg_state_B/C/D.pkl`, `uscg_lines.pkl`, `uscg_rows.pkl`; OCR cache 134 files.
- **Decisions:** as listed in the previous entry (same date); none added since.
- **Open issues:** same as the previous entry; the counts quoted there (row roles, parts, lines) come from earlier runs and are not re-verified in this session.

### 2026-09-26 — §6 log entry: Phase 4 in the notebook (cells 34–42, `af772690`…`5aca65be`), 0 errors, 6 ✅
- Results (reviewed snapshot, cell 42): 116 parts, 297 vessel/vehicle fields (0 unknown), 41 persons (crew 34 / passenger 5 / other 2), 204 caption units (all `caption_only`), 44 enclosure items (VICAR_602 Executive Summary listed but not in the release), 82 TOC entries all found. Notebook cells 27/28 were stale vs `uscg_cells_C.py` and were synced. Deviations: outcome `survivor_unspecified` added for the memorandum's survivor table; ADR-020 gate applied by rule (raster figures → `caption_only`), not reviewed against renders. Next: Phase 5 (notes) and 6–8.

### 2026-09-27 — §6 log entry: Phases 5–12 in scratch (`uscg_cells_E.py`, `uscg_cells_F.py`), Windows test OK
- Loop: `run_step.py` + portable state after Phase 4 (`uscg_stub_D.py`), local pre-tests in the assistant's sandbox.
- Results: 93 notes (22 informative / 65 citation-only / 6 redacted), 44 superscripts restored (ordinals, exponents, ®), 3170 paragraphs, 3200 units after dedup (49 summary sentences trimmed, 2 summary units dropped), 0 cross-source duplicates.
- Decisions (delegated details): paragraph rules (number / item / label / pitch 1.4× / visible last line; page breaks continue unless the last line ends the paragraph); inline headings and title-only sub-headings joined to the next paragraph; Phase 4 role corrections (57 signature rows, SPIRIT figure lists -> metadata); individual owners/operators in vessel tables written by role; letters' restated recommendations kept (recorded in the duplicate audit, not trimmed) — only the Executive Summary is non-canonical (§4.4).

### 2026-09-27 — §6 log entry: notebook complete (86 cells, Phases 0–20 + Final), nbconvert 0 errors
- Cell files E–J appended (via `run_step.py sync E`); Windows test chain and full run green. Results and deviations: implementation record at the top. Fixes found by the coverage audit and applied upstream: restored ordinals in figure captions, CUYAHOGA "None / N/A" persons row, QUEEN_OF_THE_WEST period of employment, 3 more individual parties (CUMBERLAND_II, GOOD_GULF, NC3250BW "Owner/Operator").

