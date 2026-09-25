# LPI Connecting to Compete 2025 — Ingestion & Chunking Pipeline Plan

**Planned notebook:** `LPI_Connecting_to_Compete_2025_chunking.ipynb` (implemented as `LPI_Connecting_to_Compete_chunking.ipynb`)

**Reference notebook:** `LPI_methodology_chunking.ipynb`

**Primary input:** `LPI.pdf` — *Connecting to Compete 2025: Trade Logistics in the Global Economy — The New Logistics Performance Indicators 2.0*

**Reference input for cross-document duplicate detection:** `LPI_Methodology.pdf` / the cleaned logical-units artifact produced by the existing methodology pipeline.

> **Status: IMPLEMENTED (2026-09-25)** in `Notebooks/LPI_Connecting_to_Compete_chunking.ipynb`.
> The notebook's Final Checkpoint markdown is the authoritative description of what was built. Deviations from this plan:
> - **Numbering:** Phase 0 setup, 1 inventory, 2 classification, 3 structure (3.1–3.7), 4 structured extraction (4.1–4.8), 5 notes (5.1–5.5), 6 body, 7 paragraphs, 8 sections, 9 units, 10–12 dedup + QA, 13 save, 14–15 chunking, 16–18 schema/save/cross-source, **19 whole-PDF coverage audit (new)**.
> - **Page classes added:** `abbreviations` (p.7, auxiliary) and `back_cover` (p.30, retrieval, sent to dedup).
> - **Structure:** the PDF outline is unusable; headings come from fonts. "Core/Supplementary indicators" are level 2; "Data" and the three "Area N" headings are level 3; run-ins "1.1…3.3" are level 4. Tables/figures take the section of their first prose reference (they are floats).
> - **Figures:** a retrieval-value gate (6 full, 2 caption_only, 2 skip) with number-checked curated descriptions (ADR-020).
> - **Notes:** added step 5.4, manual review of all 33 notes (18 informative, 15 citation-only).
> - **Dedup:** item-level matching and canonical-source policy (ADR-019); owner decision to remove everything repeated: 18 units suppressed (both tables, 5 abbreviations, 8 Chapter 1 paragraphs), 7 trimmed; no manual-review item left.
> - **Artifacts:** `LPI_Connecting_to_Compete_{extracted.json, logical_units.json, chunks.parquet}`; the cleaned layer is ONE file holding units, duplicate audit and coverage audit; `chunk_id` prefix `lpi2025_`.
> - **Result:** 70 chunks; cross-source corpus 199 chunks; 2,189 PDF lines, 0 unaccounted.

---

## 0. Purpose and design goals

This notebook will ingest the **Connecting to Compete 2025** LPI report into the same governed RAG ingestion architecture already used for the LPI Methodology report, while adapting the extraction layer to the new PDF's structure.

The notebook must produce a corpus that is:

1. **Semantically chunked** — chunk boundaries follow meaning and document structure, not arbitrary character windows.
2. **Structure-aware** — tables, figures, headings, notes, and prose are represented correctly.
3. **Deduplicated before chunking** — repeated content is detected at the logical-unit level before chunks are built.
4. **Cross-source aware** — repeated material between the Methodology report and Connecting to Compete is detected without deleting contextual information that is genuinely different.
5. **Auditable** — every extraction, classification, duplicate decision, and filtering decision can be inspected.
6. **Schema-compatible** — final chunks use the same unified 16-column schema as LPI/FBL/Suez.
7. **Deterministic where possible** — avoid unnecessary model/embedding calls in the core ingestion path.
8. **Preservation-first** — extraction should not lose meaningful information merely because it resembles content already present in another source.

---

# 1. Source understanding and document roles

## 1.1 What the new PDF contributes

The new report is primarily a **results, analysis, benchmarking, and policy** document.

Its main content areas are:

- Executive Summary
- Chapter 1 — Introducing the 2025 LPI 2.0
- Chapter 2 — What the LPI 2.0 reveals about logistics performance
- Chapter 3 — From indicators to policy interventions
- Notes
- References

The report contains two core tables and ten analytical figures in addition to prose.

## 1.2 What the old Methodology PDF contributes

The Methodology report is primarily a **definitions, construction, data-source, methodology, and user-guide** document.

It contains overlapping descriptions of:

- LPI 2.0 conceptual framework
- connectivity and time
- maritime / aviation / postal modes
- six core indicators
- supplementary indicators
- data sources
- methodology
- indicator definitions

## 1.3 Source-role principle

The two reports may describe the same concept but serve different purposes.

Therefore:

> **Same topic does not automatically mean duplicate data.**

Example:

- Methodology: what an indicator means, how it is defined, or how it is constructed.
- Connecting to Compete: what the observed 2023–2024 results show about that indicator.

Both pieces may be required by RAG and must remain available when they contain distinct information.

---

# 2. Core pipeline architecture

The new notebook should follow this overall flow:

```text
PDF
 │
 ├── 0. Setup / configuration
 │
 ├── 1. Page inventory
 │
 ├── 2. Page classification
 │
 ├── 3. Structure reconnaissance
 │      ├── headings
 │      ├── section boundaries
 │      ├── table candidates
 │      └── figure candidates
 │
 ├── 4. Structured extraction
 │      ├── tables
 │      ├── figures
 │      └── abbreviations
 │
 ├── 5. Notes / endnotes extraction
 │
 ├── 6. Body extraction + cleaning
 │
 ├── 7. Paragraph reconstruction
 │
 ├── 8. Section/subsection assignment
 │
 ├── 9. Unified logical units
 │
 ├── 10. CROSS-SOURCE + WITHIN-SOURCE DUPLICATE DETECTION   <-- new major stage
 │        ├── exact duplicate
 │        ├── near duplicate
 │        ├── contextual duplicate
 │        └── unique
 │
 ├── 11. Duplicate decision / corpus filtering
 │
 ├── 12. Final logical-unit QA
 │
 ├── 13. Save extracted + cleaned artifacts
 │
 ├── 14. Semantic chunking
 │
 ├── 15. Chunk validation
 │
 ├── 16. Unified 16-column schema
 │
 ├── 17. Save / reload / schema validation
 │
 └── 18. Cross-source compatibility validation
```

The major architectural change compared with the old notebook is that **duplicate detection is inserted after logical units are complete and before chunking**.

---

# 3. Step 0 — Setup and configuration

## Goal

Create the same stable environment pattern used by the existing notebook, but configure it for Connecting to Compete 2025.

## Inputs

- `LPI.pdf`
- optional reference logical-units file from the Methodology pipeline
- optional reference chunks from the Methodology pipeline, only for final compatibility checks

## Configuration to define

```python
PDF_RELATIVE_PATH
PDF_PATH
REFERENCE_METHODLOGY_UNITS_PATH
PROCESSED_RAG_DIR
EXTRACTED_DIR
CLEANED_DIR
CHUNKS_DIR

MAX_CHUNK_CHARS = 2000
MIN_CHUNK_CHARS = 300
```

The exact chunk-size constants are inherited from the existing pipeline and should remain configurable.

## New configuration

```python
DUPLICATE_EXACT_MODE = "normalized_hash"
DUPLICATE_NEAR_SIMILARITY_THRESHOLD = <to be calibrated>
DUPLICATE_REVIEW_THRESHOLD = <to be calibrated>
```

Do not freeze near-duplicate thresholds until the first duplicate audit has been inspected.

---

# 4. Step 1 — Page inventory

## Goal

Build the basic page-level inventory before making extraction decisions.

## Required fields

At minimum:

- `page_number`
- `char_count`
- `word_count`
- `text`
- `image_count`
- `drawing_count`
- `link_count`

Also inspect:

- page dimensions
- text block count
- possible two-column layout
- visual/drawing density

## QA

Display the complete page inventory so abnormal pages are visible before classification.

Important: this report contains vector/drawing-heavy figures, so **image count alone must not be treated as figure detection**.

---

# 5. Step 2 — Page classification

## Goal

Decide which pages belong to the main retrieval corpus.

Classification should include both a label and a reason.

## Proposed initial classes

### Non-retrieval

- `cover_title`
- `blank`
- `legal`
- `contents`
- `acknowledgements`
- `references`
- `notes_auxiliary` (not normal retrieval units, but used by the notes-linking system)

### Retrieval

- `content`

## Important rule

A page can be excluded from the **main retrieval body** while still being used as an auxiliary source.

Example:

- Notes page → not normal chunk content, but still needed to resolve informative notes.

## QA

Display:

- page number
- word count
- classification
- keep/exclude flag
- reason

Do not proceed until all pages are explainable.

---

# 6. Step 3 — Structure reconnaissance

This step replaces the assumption that the new PDF will have the exact same internal structure as the Methodology report.

## 6.1 Inspect visible headings

Identify:

- chapter headings
- major section headings
- subsection headings
- numbered policy subsections in Chapter 3

Expected important hierarchy includes:

```text
Executive summary

Chapter 1
  Introducing the 2025 LPI 2.0
    Why is logistics important for trade and development?
    Conceptual framework ...
    The new indicators
      Core indicators
      Supplementary indicators
      Data

Chapter 2
  What the LPI 2.0 reveals about logistics performance
    Connectivity
    Time
    The special situation of landlocked developing countries
    Assessing supply chain reliability using the dispersion of delays
    Additional insights from supplementary indicators

Chapter 3
  From indicators to policy interventions
    A strategic framework for logistics performance
      Area 1 ...
        1.1 ...
        1.2 ...
        1.3 ...
      Area 2 ...
        2.1 ...
        2.2 ...
        2.3 ...
      Area 3 ...
        3.1 ...
        3.2 ...
        3.3 ...
    Using the LPI 2.0 to prioritize and tailor reforms
```

This is a structural plan, not a claim that every visible heading will be represented exactly this way in the final `section_map`; the actual PDF must determine the final map.

## 6.2 Inspect PDF outline

Attempt to use the internal PDF outline/bookmarks, but **do not treat it as the source of truth**.

The new PDF has been observed to expose non-semantic/internal outline identifiers. Therefore the reliable hierarchy must come from the visible headings + Contents + page positions.

## 6.3 Build `section_map`

Each map entry should contain at least:

- `section`
- `subsection`
- `start_page`
- `level`
- normalized heading text

## QA

Validate every mapped heading against its actual page location.

---

# 7. Step 4 — Detect tables and figures

## Goal

Create a confirmed inventory of structured elements before extracting body prose.

## Tables expected

The report contains:

- Table 1.1 — six core indicators
- Table 1.2 — supplementary indicators

The table content overlaps strongly with the Methodology report.

That overlap is expected and will be handled **after unit extraction**, not by deleting these tables prematurely.

## Figures expected

The report contains Figures 2.1–2.10.

Do not infer figure number solely from flattened text because figure labels can be distorted during extraction (especially two-digit figure numbers such as Figure 2.10).

## Detection strategy

Use multiple signals:

1. caption candidates
2. caption position
3. page location
4. drawing/visual density
5. neighboring structured text
6. rendered-page inspection when extraction is ambiguous

## QA

Produce a caption inventory such as:

| content_type | number | page | caption | confidence |
|---|---:|---:|---|---|
| table | 1 | ... | ... | ... |
| table | 2 | ... | ... | ... |
| figure | 2.1 | ... | ... | ... |
| figure | 2.2 | ... | ... | ... |
| ... | ... | ... | ... | ... |

No structured extraction should happen from unverified caption candidates.

---

# 8. Step 5 — Extract tables

## Goal

Represent tables as semantic units instead of flattened text.

## Table strategy

### Table 1.1

Each logical row becomes a `table_row` unit.

Expected semantic organization:

```text
Maritime
  connectivity definition
  time definition

Aviation
  connectivity definition
  time definition

Postal
  connectivity definition
  time definition
```

### Table 1.2

This table contains many indicator definitions in bullet lists.

The raw table row may be large, so the generic rule should be:

- extract row
- normalize cells
- preserve row identity
- preserve column identity
- later split bullet-level indicator definitions into individual retrieval chunks

The extraction stage should still produce a coherent logical `table_row` unit rather than prematurely creating chunks.

## Cleaning

Normalize:

- soft hyphens
- line breaks
- duplicated whitespace
- broken bullet symbols
- cell formatting artifacts

Do not delete semantic content.

## QA

Display every extracted table row before proceeding.

---

# 9. Step 6 — Extract figures

## Goal

Convert analytical figures into self-contained descriptive RAG units.

## Important principle

A figure is not just its caption.

If the visual communicates:

- categories
- relationships
- trends
- numerical labels
- chart values
- axes
- comparisons
- source/note

those elements should be represented in the figure unit as accurately as the PDF allows.

## Extraction strategy

For each figure:

1. locate the figure page
2. identify the caption
3. inspect raw text blocks
4. inspect rendered page image when necessary
5. reconstruct chart/table relationships
6. separate `Source:` and `Note:` from the descriptive content when appropriate
7. create one coherent figure unit

## Special handling

Figure 2.10 must be validated visually because the text extractor can confuse `2.10` with flattened token fragments.

## QA

One complete sample per figure, with:

- figure number
- title
- page
- reconstructed content
- source
- note

---

# 10. Step 7 — Notes / endnotes extraction

This is a major change from the Methodology notebook.

## Goal

Treat the Notes page as an **endnote registry** rather than assuming page-local footnotes.

## Build

```python
note_text_map = {
    1: "...",
    2: "...",
    ...
}
```

## Inline references

Detect numeric note markers in body content and attach them to the paragraph as metadata:

```text
footnote_refs = [13, 15]
```

Use a robust context rule so normal numbers, dates, decimals, or values are not mistaken for note markers.

## Notes policy

Classify each note as:

- `informative`
- `citation_only`

### Informative note

Append its useful text to the paragraph content as:

```text
Note: ...
```

### Citation-only note

Keep only the note reference in metadata; do not duplicate the citation inside the retrieval text.

This is the same conceptual policy used in the existing Methodology notebook, adapted from page-local footnotes to endnotes.

## QA

Every note should have exactly one policy decision.

Every referenced note should resolve.

No citation-only note should be injected into `content`.

No informative note should be lost.

---

# 11. Step 8 — Body extraction and cleaning

## Goal

Extract only the prose not already represented by tables and figures.

## Remove from body stream

- running headers
- page numbers
- confirmed table regions
- confirmed figure regions
- figure/table captions
- source lines
- note lines belonging to structured elements
- obvious decorative text

## Cleaning rules

Normalize:

- soft hyphen artifacts
- non-breaking hyphens
- zero-width characters
- whitespace
- line-wrap artifacts

Preserve:

- punctuation
- numbers
- dates
- units
- named entities
- policy terminology
- indicator names

## Body audit

For every retrieval page:

- confirm useful body text exists where expected
- confirm no table/figure duplicate leaked into body
- confirm no caption duplicated into body
- confirm no source/note line leaked into prose

---

# 12. Step 9 — Paragraph reconstruction

Reuse the proven logic from the Methodology pipeline, but validate it against the new document.

## Rules

1. remove validated structural headings from the paragraph stream
2. preserve those headings separately for auditing
3. detect one- vs two-column pages
4. read columns in actual document reading order
5. merge blocks that are fragments of the same paragraph
6. allow continuation across columns and page boundaries
7. allow continuation when a block ends mid-sentence and the next starts with a proper noun/capitalized continuation
8. preserve note references

## Output

`paragraphs_df` with at least:

- `paragraph_id`
- `text`
- `page_start`
- `page_end`
- `footnote_refs`
- location metadata needed for section assignment

## QA

Check:

- no structural heading remains as prose
- no paragraph begins/ends in an obviously broken way
- all retrieval pages have expected prose coverage
- multi-column transitions are correct

---

# 13. Step 10 — Section/subsection assignment

## Goal

Assign every paragraph and every structured unit to the correct document hierarchy.

## Strategy

Use **physical location + validated heading positions**.

Do not simply assign a whole page to one heading because a page can contain multiple subsection transitions.

## Required fields

For every unit:

- `section`
- `subsection`

## QA

Especially inspect pages containing multiple subsections or chapter transitions.

---

# 14. Step 11 — Build the unified logical-units layer

## Goal

Create one pre-chunking table containing all meaningful semantic units.

## Unit types

Initial expected set:

- `paragraph`
- `table_row`
- `figure`
- `definitions` (only if an abbreviation/definition table is present and useful)

`worked_example` should only be added if the new PDF actually contains a genuine worked-example structure that deserves that unit type.

## Unified unit concept

Each unit contains one authoritative text field:

```text
content
```

Do **not** create a redundant `rag_text` copy.

## Suggested internal unit fields

- `unit_id`
- `unit_type`
- `page_start`
- `page_end`
- `section`
- `subsection`
- `title`
- `content`
- `footnote_refs`
- `table_number`
- `figure_number`
- location/audit metadata as needed

The internal unit table may contain more fields than the final 16-column chunk schema.

---

# 15. Step 12 — Duplicate detection (NEW major stage)

This stage happens **before chunking**.

It has two scopes:

```text
A. Within-document duplicates
B. Cross-document duplicates
```

## 15.1 Normalization for duplicate comparison

Create a comparison-only normalized representation.

Example transformations:

- Unicode normalization
- lowercase
- normalize whitespace
- normalize soft hyphens
- normalize punctuation variants where safe
- collapse repeated spaces

Do not modify the actual `content` field.

## 15.2 Exact duplicate detection

Compute a deterministic hash of normalized text.

```text
normalized_text
     ↓
SHA-256 / stable hash
     ↓
exact duplicate groups
```

Use this for:

- repeated extraction fragments
- repeated front/back matter
- repeated paragraphs inside the same PDF
- exact cross-source repetitions

## 15.3 Near-duplicate detection

For candidate pairs that are not exact matches, compare using a deterministic lexical method.

Preferred first implementation:

- TF-IDF character n-grams or word n-grams
- cosine similarity
- optional `rapidfuzz` score as a secondary audit signal

This avoids making embeddings a dependency of the ingestion/dedup core.

## 15.4 Candidate generation

Do not compare every unit with every other unit blindly.

Create blocking keys such as:

- `unit_type`
- section family
- normalized first terms / title
- approximate length bucket

This keeps the comparison interpretable and scalable.

---

# 16. Duplicate decision model

The duplicate detector must not simply say `duplicate=True/False`.

Each candidate should receive a relationship class.

## Relationship classes

### `unique`

The unit contains information not otherwise represented.

→ Keep.

### `exact_duplicate`

The normalized content is identical.

Typical action:

- within same document → keep one canonical occurrence and record the duplicate occurrence
- across Methodology vs Connecting to Compete → suppress redundant copy when the exact content adds no new context, while preserving the source mapping in the audit table

### `near_duplicate`

Very similar wording, but not byte-for-byte identical.

→ Requires rule-based decision or review.

### `contextual_duplicate`

Same concept, but one unit adds materially different information.

Examples:

- methodology definition vs empirical finding
- general definition vs country-specific result
- indicator meaning vs policy implication

→ Keep both.

### `duplicate_candidate_review`

Similarity is high enough to inspect but the automated evidence is insufficient.

→ Keep pending manual review rather than deleting information.

---

# 17. Canonical-source policy for cross-document duplicates

Use source role, not arbitrary first-seen order, to choose the canonical copy when a true duplicate must be suppressed.

## Methodology report is canonical for

- indicator definitions
- methodological definitions
- data construction descriptions
- data-source methodology
- formal indicator meaning

## Connecting to Compete is canonical for

- 2023–2024 findings
- cross-region comparisons
- empirical patterns
- figures 2.1–2.10
- policy intervention framework
- interpretation of observed performance patterns

This policy is only applied when the content is actually redundant.

A new analytical statement must never be removed merely because it discusses the same concept as an old definition.

---

# 18. Duplicate audit table

Create a dedicated audit dataframe, separate from the final chunk schema.

Suggested columns:

```text
source_document
unit_id
candidate_unit_id
unit_type
relationship
similarity_score
normalized_hash
candidate_hash
same_section_family
same_title_family
length_ratio
unique_information_flag
action
canonical_unit_id
reason
```

Possible `action` values:

- `keep`
- `suppress_duplicate`
- `keep_contextual`
- `manual_review`

This audit layer is essential because the final 16-column schema should not be expanded just to carry ingestion-control metadata.

---

# 19. Duplicate decision logic

Recommended decision order:

```text
1. Exact normalized hash?
       │
       ├── YES → exact_duplicate
       │
       └── NO
            │
2. High lexical similarity candidate?
       │
       ├── NO → unique
       │
       └── YES
            │
3. Does the candidate contain materially new information?
       │
       ├── YES → contextual_duplicate → KEEP
       │
       └── NO → near/exact semantic duplicate → SUPPRESS one copy
```

The "materially new information" check must consider:

- new statistics
- new dates/years
- new countries/regions
- new indicator values
- new causal/interpretive statements
- new policy actions
- new methodological detail
- new figure/chart evidence

If unique information is present, keep the unit.

---

# 20. Why dedup happens before chunking

Logical units are the correct granularity for deduplication because they preserve semantic boundaries.

If dedup happens after chunking:

- one paragraph may already have been merged with another
- table definitions may be split into different chunks
- figure descriptions may be duplicated partially
- provenance becomes harder to reason about
- the duplicate detector sees chunk fragments instead of source meaning

Therefore:

```text
raw extraction
→ clean units
→ dedup
→ chunk
```

is the required order.

---

# 21. Step 13 — Final logical-unit QA before chunking

Before chunking, run a strict checkpoint.

## Required checks

### Structure

- all units have valid `unit_type`
- all retrieval units have a section
- all units have non-empty content
- no structural heading is standalone unless intentionally represented

### Tables

- every confirmed table is represented
- no table row is duplicated in body prose
- no row loses a column
- bullet structure is preserved

### Figures

- every confirmed figure is represented exactly once
- no confirmed figure is duplicated in body prose
- title/source/note handling is valid

### Notes

- every referenced note resolves
- informative notes are retained
- citation-only notes are not redundantly injected

### Duplicate layer

- every duplicate candidate has a decision
- every suppressed unit has a canonical mapping
- no `unique_information_flag=True` unit is accidentally suppressed

---

# 22. Step 14 — Save extraction and cleaned artifacts

Follow the existing persistence pattern:

```text
processed/rag/
├── extracted/
├── cleaned/
└── chunks/
```

## Extracted artifact

Save the raw structured extraction layer:

- body blocks
- notes/endnotes
- tables
- figures
- captions

## Cleaned artifact

Save the final logical-unit corpus **after duplicate decisions**.

Also save the duplicate audit as a separate artifact, for example:

```text
LPI_Connecting_to_Compete_2025_duplicate_audit.json
```

The cleaned artifact should contain the units that are actually eligible for chunk construction.

---

# 23. Step 15 — Semantic chunking

Reuse the proven chunking philosophy from `LPI_methodology_chunking.ipynb`.

## Paragraphs

- preserve complete paragraphs where possible
- short paragraphs under `MIN_CHUNK_CHARS` may be grouped with neighboring paragraphs
- grouping must stay inside the same section/subsection
- a minor heading may attach to the following paragraph rather than becoming a standalone retrieval chunk

## Tables

- one logical row is the starting unit
- bullet-level indicator definitions can become separate chunks
- preserve table identity and column label in the chunk text

## Figures

- one coherent figure description per chunk
- do not split a figure into arbitrary character fragments

## Maximum size

```text
MAX_CHUNK_CHARS = 2000
```

This remains a **safety cap**, not a chunk-size target.

If a semantic unit genuinely exceeds the cap, split at a meaningful structural boundary rather than slicing arbitrary characters.

---

# 24. Step 16 — Chunk validation

Validate at least:

1. no empty chunks
2. no duplicate `chunk_id`
3. `char_count == len(text)`
4. all chunks ≤ maximum size
5. every logical unit is represented exactly once or according to an explicit structured-splitting rule
6. no chunk crosses section/subsection boundaries
7. no minor heading remains as an unintended standalone chunk
8. all structured units that survived dedup are represented
9. source-unit provenance is complete
10. no suppressed duplicate reappears through a merge operation

Also generate:

- chunks by type
- chunk size distribution
- multi-unit paragraph chunks
- multi-part table rows
- duplicate audit summary

---

# 25. Step 17 — Unified 16-column schema

The final chunk dataframe must remain compatible with the existing cross-source corpus.

Required final schema:

```text
page
unit_type
logical_unit
chunk_id
parent_chunk
sub_chunk
title
text
char_count
filename
source
real_or_synthetic
document_type
department
sensitivity_level
version_date
```

## Important

Do not add duplicate-audit fields to this final retrieval schema.

Keep ingestion/audit metadata in separate dataframes/files.

## Metadata mapping

Configure the document metadata explicitly for Connecting to Compete 2025 rather than inheriting the Methodology report's `document_type` blindly.

The exact final values should be decided in the notebook after confirming the source filename/title and project naming conventions.

---

# 26. Step 18 — Save, reload, and validate

Persist the final chunks to Parquet.

Then:

1. reload from disk
2. validate schema
3. validate dtypes
4. validate row count
5. validate `chunk_id` uniqueness
6. compare in-memory vs reloaded data

The saved file, not only the in-memory dataframe, is the final artifact that must pass validation.

---

# 27. Cross-source compatibility validation

After reload, compare the new LPI chunks against:

- existing LPI Methodology chunks
- FBL chunks
- Suez chunks

Validate:

- identical column names
- identical column order
- compatible dtypes
- no chunk-ID collision
- successful concatenation

Final conceptual check:

```text
LPI Methodology chunks
        +
Connecting to Compete chunks
        +
FBL chunks
        +
Suez chunks
        ↓
Unified RAG corpus
```

---

# 28. Final QA / manual review gate

Before considering the notebook finished, manually review a deterministic sample covering:

- normal paragraph
- short paragraph merged with neighbor
- table row
- table bullet-level indicator definition
- figure
- notes-attached paragraph
- citation-only note paragraph
- exact duplicate that was suppressed
- contextual duplicate that was retained
- unique analytical finding
- policy subsection chunk

The goal is to prove that the duplicate stage is **removing redundancy, not information**.

---

# 29. Expected artifact set

At completion, the notebook should produce something close to:

```text
processed/rag/
├── extracted/
│   └── LPI_Connecting_to_Compete_2025_extracted.json
│
├── cleaned/
│   ├── LPI_Connecting_to_Compete_2025_logical_units.json
│   └── LPI_Connecting_to_Compete_2025_duplicate_audit.json
│
└── chunks/
    └── LPI_Connecting_to_Compete_2025_chunks.parquet
```

Exact naming may follow the existing project convention once paths are confirmed.

---

# 30. Notebook section map — the actual build order

The notebook should be written in this exact stepwise order so every stage can be run, inspected, and validated independently:

```text
# 0. Setup

# 1. Page Inventory
## 1.1 Build page inventory
## 1.2 Inspect inventory

# 2. Page Classification
## 2.1 Define classification rules
## 2.2 Validate classification

# 3. Structure Reconnaissance
## 3.1 Detect candidate figures/tables
## 3.2 Detect heading candidates
## 3.3 Inspect PDF outline
## 3.4 Build section map
## 3.5 Validate section map

# 4. Structured Extraction
## 4.1 Table extraction
## 4.2 Table normalization
## 4.3 Table semantic units
## 4.4 Figure extraction
## 4.5 Figure reconstruction
## 4.6 Structured-unit QA

# 5. Notes / Endnotes
## 5.1 Extract note registry
## 5.2 Detect note references
## 5.3 Build note policy table
## 5.4 Validate note coverage

# 6. Body Text
## 6.1 Structural boundaries
## 6.2 Cleaning
## 6.3 Body-block extraction
## 6.4 Remove structured-unit duplication
## 6.5 Body audit

# 7. Paragraph Reconstruction
## 7.1 Remove structural headings
## 7.2 Detect reading order
## 7.3 Reconstruct paragraphs
## 7.4 Validate paragraphs

# 8. Section Assignment
## 8.1 Locate headings physically
## 8.2 Assign paragraph sections
## 8.3 Assign structured-unit sections
## 8.4 Validate assignment

# 9. Unified Logical Units
## 9.1 Combine paragraphs + tables + figures + definitions
## 9.2 Apply note policy
## 9.3 Validate units

# 10. Duplicate Detection
## 10.1 Normalize comparison text
## 10.2 Exact hash duplicates
## 10.3 Candidate blocking
## 10.4 Near-duplicate similarity
## 10.5 Cross-source comparison
## 10.6 Duplicate relationship classification

# 11. Duplicate Decisions
## 11.1 Apply canonical-source policy
## 11.2 Suppress true duplicates
## 11.3 Preserve contextual duplicates
## 11.4 Produce duplicate audit
## 11.5 Validate post-dedup corpus

# 12. Final Unit QA
## 12.1 Content samples
## 12.2 Coverage checks
## 12.3 Duplicate suppression checks

# 13. Save Extracted + Cleaned Artifacts

# 14. Chunking
## 14.1 Chunking rules
## 14.2 Build paragraph chunks
## 14.3 Build structured chunks

# 15. Chunk Validation
## 15.1 Size checks
## 15.2 Coverage checks
## 15.3 Provenance checks

# 16. Unified Chunk Schema
## 16.1 Schema definition
## 16.2 Metadata mapping
## 16.3 Schema validation

# 17. Save + Reload
## 17.1 Save Parquet
## 17.2 Reload
## 17.3 Revalidate

# 18. Cross-Source Validation
## 18.1 Compare schemas
## 18.2 Check dtypes
## 18.3 Check chunk ID collisions
## 18.4 Concatenate corpus

# Final Checkpoint
```

---

# 31. What we explicitly will NOT do

## No blind copying of the old pipeline

Reuse architecture and proven helpers, but adapt extraction rules to this PDF.

## No aggressive cross-document deletion

A repeated concept is not automatically duplicate knowledge.

## No dedup after chunking

Dedup belongs before chunk construction.

## No arbitrary character slicing

Semantic boundaries come first.

## No redundant `content` / `rag_text` pair

One authoritative retrieval text field is enough.

## No dependence on images alone for figure detection

This PDF contains vector/drawing-heavy visual content.

## No automatic deletion when similarity is uncertain

Uncertain cases become `manual_review` and remain preserved.

---

# 32. Critical implementation philosophy

The pipeline has three different notions that must never be conflated:

```text
EXTRACTION
    "What is physically present in the PDF?"

STRUCTURING
    "What are the semantic units and document hierarchy?"

DEDUPLICATION
    "Which units are genuinely redundant, and which only discuss the same concept?"

CHUNKING
    "What is the smallest self-contained retrieval unit?"
```

The correct order is therefore:

```text
PDF
 ↓
Extraction
 ↓
Cleaning
 ↓
Structure
 ↓
Logical Units
 ↓
Deduplication
 ↓
Chunks
 ↓
Unified Schema
 ↓
Validation
```

---

# 33. First implementation milestone

Do **not** start coding the entire notebook at once.

The first working milestone should stop after:

```text
Step 0 → Step 3
```

and produce:

- page inventory
- page classification
- confirmed headings
- confirmed table/figure inventory

Only after those are inspected should structured extraction begin.

The second milestone should stop after:

```text
Step 4 → Step 9
```

and produce a clean, section-aware logical-unit corpus.

The third milestone is:

```text
Step 10 → Step 12
```

and is the new duplicate-detection / duplicate-decision gate.

Only when that gate passes should we move to chunking.

---

# 34. Final mental model

The complete project should eventually behave like this:

```text
                    ┌───────────────────────────────┐
                    │      PDF: Connecting to       │
                    │         Compete 2025         │
                    └───────────────┬───────────────┘
                                    │
                              Extraction
                                    │
                    ┌───────────────▼───────────────┐
                    │   Clean semantic units        │
                    │ paragraphs / tables / figures │
                    │            / notes            │
                    └───────────────┬───────────────┘
                                    │
                             Structure map
                                    │
                    ┌───────────────▼───────────────┐
                    │ Unified logical-unit layer    │
                    └───────────────┬───────────────┘
                                    │
                          Duplicate detection
                       ┌────────────┴────────────┐
                       │                         │
                 Methodology source      Connecting source
                       │                         │
                       └────────────┬────────────┘
                                    │
                       duplicate relationship
                       ┌────────────┼──────────────┐
                       │            │              │
                    unique     contextual      true duplicate
                       │            │              │
                       │            │          suppress one
                       └────────────┴──────────────┘
                                    │
                              Final units
                                    │
                                Chunking
                                    │
                           Unified 16-column schema
                                    │
                              Parquet output
                                    │
                          Cross-source validation
                                    │
                       ┌────────────┬────────────┐
                       │            │            │
                     LPI          FBL          Suez
                       └────────────┴────────────┘
                                    │
                           Unified RAG corpus
```

---

# 35. Reference to the existing pipeline

The existing Methodology notebook remains the architectural reference for:

- page classification
- structure discovery
- table extraction
- figure handling
- body extraction
- paragraph reconstruction
- footnote policy
- unified logical units
- semantic chunking
- schema validation
- Parquet persistence
- cross-source schema checking

The Connecting to Compete notebook adds/adapts:

- document-specific section mapping
- vector-figure inspection/reconstruction
- endnote registry rather than page-local footnotes
- new figure/table structure
- **pre-chunk duplicate detection**
- **cross-document duplicate policy**
- duplicate audit artifacts

This plan is the governing reference while implementing `LPI_Connecting_to_Compete_2025_chunking.ipynb`.
