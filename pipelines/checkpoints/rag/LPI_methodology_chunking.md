# Final Checkpoint — LPI Chunking Pipeline

## What this notebook does

**Input:** `LPI_Methodology.pdf`, the World Bank report *The New Logistics Performance Indicators 2.0 (LPI 2.0): Methodology and User Guide* (32 PDF pages).

**Goal:** cut the document into **chunks**, small self-contained pieces of text that a RAG (retrieval-augmented generation) system can index and retrieve to answer questions.

**Why it is not simply "split the text every N characters":** the PDF has two text columns per page, tables, diagrams, footnotes, and a running header on every page. A naive extraction mixes the two columns, repeats the header, flattens tables and diagrams into meaningless word lists, and cuts sentences in the wrong places.

So the notebook works in **steps**. Each numbered section is one step. A step makes one kind of decision, checks it, and hands a clean result to the next step:

`pages → structure → tables/figures → body text → paragraphs → footnotes → units → chunks → schema → saved files`

**Vocabulary used below**

* **Page numbers** are PDF page indexes, not printed numbers. The printed page number is the PDF index minus 8 (the Executive summary is printed page 1 and PDF page 9).
* **Unit** = one meaningful piece of the document before chunking: a paragraph, a table row, a figure, or the abbreviations table. Steps 1–8 produce units.
* **Chunk** = a piece that is finally indexed for retrieval. Step 10 builds chunks from units.
* `content` = the single text field of a unit. There is no second copy of the text.

**Setup (first cell).** The notebook finds the PDF by walking up from its own folder until it finds `Data/raw/unstructured/LPI_Methodology.pdf`, so it does not depend on one machine's absolute path. All saved files go to `processed/rag/{extracted, cleaned, chunks}` next to `Data/raw`.

---

## Step 1 — Page classification

**What it does.** Decides, page by page, whether a page can help answer questions, and stores the reason for every decision.

**Problems and how they were solved**

1. Cover, title, legal/copyright, contents, acknowledgements and references pages would pollute the corpus with text that answers nothing (for example, a contents page that lists every figure title). They are excluded from retrieval, not deleted from the PDF.
2. The abbreviations table shares page 7 with the acknowledgements, so excluding that page loses useful content. This is fixed separately in Step 3.3.

**Output.** `content_pages_df`: the retrieval pages (PDF pages 8–30).

## Step 2 — Content extraction and structure inspection

**What it does.** Finds out what each retrieval page contains (figures, tables, headings) before anything is extracted.

**Problems and how they were solved**

1. *Images are not figures.* The PDF is full of decorative photos, logos and graphics, so the image count says nothing. Real figures and tables are found through their captions (`Figure N …`, `Table N …`).
2. *A body sentence can look like a caption.* "Figure 5 presents the example of a shipment from…" was detected as a caption. Captions must match `Figure N <Title starting with a capital letter>`.
3. *Every unit needs a section and subsection.* Guessing headings from font or case is unreliable, so the PDF's own outline (bookmarks) provides the hierarchy.
4. *Bookmarks can point to the wrong page*, and some headings wrap across lines or use different characters. Each outline entry is checked against the real page text, and the unresolved ones are inspected one by one.
5. *The Abstract (page 8) was missing from the section map*, so its content would have had no section. It was added.

**Output.** `captions_df` (confirmed figure/table captions) and `section_map` (section, subsection, start page, level).

## Step 3 — Structured content: tables, figures, abbreviations

**Why separate.** A table or diagram turned into a plain line of text is unreadable, so these elements are extracted on their own.

**3.1 Tables.** Tables are read with PyMuPDF's table finder. Cell text contained soft hyphens, line breaks and leading bullet symbols, which are normalized. Each table **row** becomes one unit whose content is one `Column: value` line per column. Table 1 has 3 rows, Table 2 has 2 rows (Maritime, Postal), Table 3 has 5 rows, each with 3 columns.

**3.2 Figures.** The PDF stores a diagram only as scattered text labels: the arrows and relationships are lost. Figure 1's labels are split across lines, Figure 6's formula comes out as fragments, and Figure 5 is a table whose brackets link events to results. Each figure was therefore **reconstructed by hand** into descriptive text that follows the visual relationships, keeping its caption title, source and note. Figures 1–4 and 6 are `figure` units. Figure 5 is a `worked_example` unit because it walks through one real container voyage. Figures 7 and 8 (the Egypt example) are deliberately not extracted.

**3.3 Abbreviations.** The table on page 7 (LLDC, B2B, UPU, …) answers "what does X stand for" questions. Its rows are read from the PDF word positions: a row is split into abbreviation and meaning at the first wide horizontal gap. The table becomes one `definitions` unit. The acknowledgements on the same page stay excluded.

**Output.** `table_units`, `figure_1_unit … figure_6_unit`, `abbreviations_unit`.

## Step 4 — Body text extraction and cleaning

**What it does.** Extracts the text that is not already a table or figure.

**Problems and how they were solved**

1. *Running header and page number on every page.* Removed using their position at the top of the page.
2. *Table and figure text would be indexed twice.* Table/figure regions, their captions and the `Source:` / `Note:` lines are removed from the body.
3. *Soft hyphens split words* (`mea­ sures`, `indi­ cators`). Soft hyphens, non-breaking hyphens and zero-width spaces are cleaned, with unit tests on real strings.
4. *Footnotes break the reading order.* A footnote block sits between the two columns, and its marker is glued to the sentence (`port vicinity.13 Turnaround…`). A block counts as a footnote only if it starts with `N.` **and** the marker `N` appears in another block of the same page. The marker is removed from the sentence and kept as `footnote_refs`. Times such as `12:14 a.m.` are not treated as markers.
5. *One sentence was kept twice.* "The elapsed time between EMD and EMH/EMI…" is a callout of Figure 3 but was also left in the body. Body blocks whose whole text already appears inside a structured unit are dropped, and every dropped block is listed.
6. *Audits* check that every page still has text and that no caption, `Source:` / `Note:` line or hyphen artifact leaked into the body.

**Output.** `body_blocks_df` (cleaned body blocks) and `footnotes_df`.

## Step 5 — Paragraph reconstruction

**What it does.** Rebuilds real paragraphs from the body blocks.

**Problems and how they were solved**

1. *Two-column pages.* The PDF lists blocks in a mixed order, so the left column is read top to bottom, then the right column.
2. *A paragraph continues across columns and pages.* The export dwell-time sentence on page 15 continues in the right column. Two blocks are merged when the first does not end a sentence and the second clearly continues it (lowercase start or a closing bracket).
3. *Headings are not paragraph text.* The headings listed in `section_map` are removed and kept separately in `heading_blocks_df`.
4. *A sentence cut before a proper noun was not merged.* "…a shipment from" on page 16 continues with "Surabaya (Indonesia) to Bamako (Mali)…" on page 17, but the rule required a lowercase start. A long block that stops mid-sentence now continues even when the next block starts with a capital letter.
5. *Minor headings that are not in `section_map`* (*Core indicators*, *Supplementary indicators*) remain paragraphs. They are handled in Step 10.

**Validation (5.1).** Headings are removed; the page-15 sentence is one paragraph; the export dwell-time paragraph and the turnaround-time paragraph stay separate; footnote 13 stays linked to its paragraph; every retrieval page has paragraphs.

**Output.** `paragraphs_df` (`paragraph_id`, text, page range, `footnote_refs`).

## Step 6 — Footnote decision

**The question.** Should footnote text be part of what is retrieved? Some footnotes carry facts (footnote 13 explains what ship turnaround time measures). Others are only citations (footnote 5 is `Arvis et al. 2026.`).

**The rule.** Informative footnotes are appended to the citing paragraph as `Note: …`. Citation-only footnotes stay in `footnote_refs` and are not copied into the text. The rule looks at the shape of the footnote text, never at its number.

**Problem found.** The citation-only test matched any sentence that ended with a year, so footnote 16 ("…this rule began being phased out in August 2025.") was dropped even though it is informative. The test now accepts only short author–year strings. Checked against all 24 footnotes of the PDF: 6 are citation-only (1, 2, 5, 12, 22, 24) and 18 are informative. The rule is applied in step 7.5.

## Step 7 — Unified units table

**What it does.** Combines everything into `units_df`, the single list of units in reading order, each with its section and subsection.

**Sub-steps and problems**

* **7.1–7.3 Section per paragraph.** Several subsections share one page (PDF pages 21, 26 and 29), so the start page of a section is not enough. Each heading is matched to its **position on the page**, and a paragraph belongs to the last heading before it in reading order.
* **7.4 Section per table/figure.** Tables and figures use the position of their caption.
* **7.5 Footnote policy** from Step 6 is applied to the whole corpus.
* **7.6 Build `units_df`.** Problem found: the whitespace cleaning collapsed the line breaks of table rows, so the `Column: value` structure was lost. Line breaks are now preserved. The abbreviations unit is added here.
* **7.7 Validation.** Every unit has content and a section; unit counts match the sources; the section counts are shown.
* **7.8–7.9 Diagnostics.** Final counts and a paragraph preview.

**Output.** `units_df` with `unit_type` (`paragraph`, `table_row`, `figure`, `worked_example`, `definitions`), `logical_unit`, `content`, `section`, `subsection`, `page_start`, `page_end`, table/figure numbers and `footnote_refs`.

## Step 8 — Content samples

**What it does.** Prints one complete sample of every unit type, and then the full content of the units, so the result can be reviewed by eye before chunking. Nothing is changed here.

## Step 9 — Save the extracted and cleaned artifacts

**What it does.** Persists the first two layers of the flow *extracted → cleaned → chunks* under `processed/rag/`:

| Layer | File | Content |
|---|---|---|
| extracted | `extracted/LPI_Methodology_extracted.json` | body blocks, footnotes, structured units (including abbreviations) |
| cleaned | `cleaned/LPI_Methodology_logical_units.json` | `units_df` |

Later stages can reuse them without repeating the extraction.

## Step 10 — Chunking

**Principle.** Chunk boundaries follow the meaning of the content, not a size target. A chunk is the smallest piece of text that answers a question on its own.

**Rules**

* **Paragraphs** stay whole and are never cut. Groups never cross a section or subsection.
* **Table rows** are one chunk each. **Figures**, the **worked example** and the **abbreviations table** are one chunk each.
* A **2000-character** cap (about 450 tokens) guards against oversized chunks. It is a safety limit, not a target, and it is one constant (with the 300-character minimum) in step 10.1, to be tuned when the embedding model is chosen.

**Problems and how they were solved**

1. *Minor headings became chunks of 15 and 24 characters.* A heading without punctuation is attached to the paragraph that follows it.
2. *Very short paragraphs have no context on their own.* "Indicators and statistical measures derived from this data source: …" never names the data source. A paragraph under 300 characters is grouped with its neighbor inside the same subsection.
3. *One table row held 13 indicator definitions.* The Maritime row of Table 2 is about 2300 characters, and its two cells are bulleted lists. A question about one indicator should retrieve that indicator, so each bullet becomes its own chunk, prefixed with the row identifier and the column label. The rule depends on the table structure, not on size, so the Postal row of Table 2 is treated the same way. Rows of Tables 1 and 3 hold one record each and stay whole.

**Validation (10.3).** No chunk exceeds the cap or is empty; every `chunk_id` is unique; every line and bullet of every unit appears in the chunks that carry it; table rows keep one line per column; no chunk crosses a section or subsection; no heading is left alone.

## Step 11 — Unified chunk schema

**Why.** The FBL and Suez documents already use one 16-column chunk schema. Using the same one for the LPI lets all documents live in a single table.

**Mapping.** `parent_chunk` is the section. `sub_chunk` is `[subsection]` when there is one. `logical_unit` is a readable unit name such as `table_2_row_01`, and `chunk_id` is `lpi_<logical_unit>_chunk_<n>`. `title` is the table or figure caption title, otherwise the subsection or section. `text` is the unit content, unchanged. `filename`, `source`, `real_or_synthetic`, `document_type`, `department`, `sensitivity_level` and `version_date` are document-level values. `source`, `version_date` and `sensitivity_level` come from the PDF (`© 2026 The World Bank`, `Public Disclosure Authorized`).

**Problems and decisions**

1. The schema is fixed at 16 columns, so `page_end`, table/figure numbers and `footnote_refs` have no column. Table and figure numbers are encoded in `logical_unit`, informative footnotes are inside `text`, and everything else stays in the cleaned file.
2. The `lpi_` prefix on `chunk_id` prevents collisions with FBL and Suez when the tables are combined.
3. The schema and its validator are the same code as in the FBL/Suez notebook.
4. `page` is kept for the developer only; responses do not expose page numbers.

## Step 12 — Save the chunks and verify

**What it does.** Saves `processed/rag/chunks/LPI_Methodology_chunks.parquet`, reloads it from disk, and runs the schema validator on what was actually written. Then it compares the LPI chunks with the saved FBL and Suez chunks: the columns and dtypes must be identical and no `chunk_id` may collide when the three tables are concatenated. If the FBL or Suez files are not found, that comparison is skipped with a message.

---

## Addendum 2026-10-02 — Title / text normalization (ADR-041)

A last phase (appended to the script, proven by `tools/nb_to_script.py check`) normalizes the saved chunk file in
place with `pipelines/lib/chunks.py`: a leading heading moves from `text` to `title` (`title` = the location label,
`text` = the body only). Lossless, idempotent; chunk ids, order and count unchanged. Reviewed counts: heading_line 1, run_in_heading 1, unchanged 92.
Where this narrative says a header, path or caption is at the start of every chunk, it is now the chunk's `title`.
