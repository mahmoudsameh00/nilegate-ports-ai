# Final Checkpoint — FBL Chunking Pipeline

## What this notebook does

**Input:** `FBL_template.pdf`, the FIATA Negotiable Multimodal Transport Bill of Lading template (3 PDF pages).

**Goal:** cut the document into **chunks**, small self-contained pieces of text that a RAG (retrieval-augmented generation) system can index and retrieve to answer questions.

**Why it is not simply "split the text every N characters":** page 1 is a form, not prose; page 2 packs a Definitions block and 19 numbered clauses (several of them with subclauses) into two columns; page 3 is explanatory text with its own internal sections. A naive extraction would flatten the form fields into noise, lose the clause/subclause boundaries, and cut a legal clause in the middle of a sentence.

So the notebook works in **steps**. Each numbered section is one step. A step makes one kind of decision, checks it, and hands a clean result to the next step:

`classification → reconstructed text → logical units → chunks → unified schema → saved files`

**Vocabulary used below**

* **Logical unit** = one meaningful piece of the document before chunking: the form, the Definitions block, one clause, or one explanatory section. Section 3 produces logical units.
* **Chunk** = a piece that is finally indexed for retrieval. Section 4 builds chunks from logical units; most units become exactly one chunk, and the three oversized clauses become three chunks each.
* `text` = the single text field of a unit or chunk. There is no second copy of the text.

**Setup.** `PROJECT_ROOT` is found by walking up from the notebook's folder until `Data/raw/unstructured/FBL_template.pdf` exists, with the original machine's project folder kept only as a last-resort fallback — the same pattern the LPI notebook uses. The input PDF and every output path (`PROCESSED_RAG_DIR`) are built from it, so the notebook does not depend on one machine's directory layout.

---

## Step 1 — Document classification

**What it does.** Records the document-level metadata used for retrieval filtering and RBAC: source, real-vs-synthetic, document type, department, sensitivity level, version date, and ingestion scope.

**Result.** `FBL_template.pdf` is a real FIATA template (not project-synthetic data), Operations department, sensitivity level 1, and the **full document** is in scope — unlike the Suez Canal Notes document, where only one section of one page is retrieval-worthy.

## Step 2 — Content extraction and reconstruction

**What it does.** Loads the PDF with PyMuPDF and reconstructs clean, page-aware text from each page's actual block coordinates.

**Problems and how they were solved**

1. *Page 1 is a form, not a text stream.* Its fields (consignor, ports, cargo description, declared value, …) are reconstructed from block coordinates rather than reading order, so the field grouping survives.
2. *Page 2's numbered clause headers are split across lines* (`1.` on one line, `Applicability` on the next). These are rejoined before the clause parser in Step 3 ever sees the text.
3. *Page 3 mixes a checklist with regular paragraphs in two columns.* The checklist items (numbered requirements with their explanatory text beside them) are matched by vertical position so a requirement and its explanation stay together.
4. *Repeated artifacts* — the FIATA copyright line, the "Seite N" page marker, "FIATA FBL black_pantone" — are filtered out wherever they recur.

**Output.** `fbl_text`, the full reconstructed document, still tagged by page (`========== PAGE N ==========`) so Step 3 can split on page boundaries. Line wrapping is still the PDF's; it is normalized per logical unit in Step 3.1.

## Step 3 — Structure-aware logical unit extraction

**What it does.** Splits `fbl_text` into 25 logical units along the document's own structure: the form (page 1), the Definitions block and Clauses 1–19 (page 2), and four explanatory sections — overview, liability limits, issuing requirements, liability insurance (page 3).

**Problems and how they were solved**

1. *Clause 19 carries an ICC footer note glued to its text.* The footer ("The ICC logo denotes that this document …") is detected and stripped so it does not read as clause content.
2. *The parser validates its own result*: it raises immediately if Clauses 1–19 are not found in that exact order, rather than silently returning a partial or misordered list.
3. **3.1 Normalizing the unit text.** Page 2 prints the Definitions and Clauses 1–19 in narrow columns, so almost every sentence was broken across several lines, while the page-3 sections were already single paragraphs. Those wraps are re-joined; every structural break is kept (clause heading, each subclause `6.1.`, each list item `a)`, each definition `–`, each new paragraph), and one stray column-break blank line in Clause 8 is dropped. The form keeps one field label per line, with only its three wrapped sentences re-joined. Two small defects are also removed: a fragment duplicated on the form's title line (*"Multimodal Transport Documents (ICC Publication 481)."*, caused by overlapping PDF blocks) and trailing spaces on ten lines. The cell asserts that every non-form unit keeps exactly the same words in the same order, so this step changes layout only, not wording (25 709 → 25 644 characters; the only words removed are the 6 duplicated ones).
4. **3.2 Identifying large logical units.** Three clauses exceed the 2000-character chunk-size guard: Clause 6 (3131 chars), Clause 8 (3569 chars), Clause 13 (2529 chars). Their subclause boundaries (`6.1`, `6.2`, …) are located so Step 4 can split them without cutting mid-sentence.

**Output.** `fbl_units`, 25 normalized logical units, one row each (`page`, `unit_type`, `logical_unit`, `clause_number`, `title`, `text`).

## Step 4 — Structure-aware chunking

**Principle.** Chunk boundaries follow the document's own clause/subclause structure, not a fixed size target. A unit at or under 2000 characters becomes one chunk unchanged.

**Rule for the three oversized clauses.** Each is split into three chunks along a predefined grouping of its subclauses (for example, Clause 6 → subclauses 1–4, then 5, then 6). The parent clause heading is repeated at the top of every resulting chunk, so each chunk still reads as "Clause 6, sub-point X" when retrieved on its own, without needing the sibling chunks for context.

**Validation (4.1).** No chunk exceeds 2000 characters or is empty; no `chunk_id` is duplicated; every subclause of Clauses 6, 8 and 13 is confirmed present in its assigned chunk; chunk sizes range from 101 to 1609 characters. The split chunks add 223 characters versus the unit text (25 644 → 25 867): the clause heading repeated at the top of each extra chunk, plus the blank line placed between subclauses — an intentional, checked trade-off for chunk-level readability, not data loss.

**Output.** 31 final chunks (22 logical units that needed no split, plus 3 chunks each for Clauses 6, 8 and 13).

## Step 5 — Unified chunk schema

**Why.** The Suez Canal Notes and LPI Methodology documents use the same 16-column chunk schema, so the same one is used here and all three documents can live in a single retrieval table.

**5.1–5.2.** `CHUNK_SCHEMA`, `normalize_chunk_schema` and `validate_chunk_schema` are defined locally (identical to the Suez Canal Notes and LPI notebooks) so this notebook does not depend on the others having run first. FBL's document-level metadata (source `FIATA`, `bill_of_lading_template`, Operations, sensitivity 1) is read directly from the Step 1 classification table and attached to every chunk, so chunk metadata can never drift from the corpus-wide classification; and `parent_chunk` / `sub_chunk` carry the clause and subclause numbers using field names generic enough for other resource types to reuse.

**5.3 Validation.** All eight schema checks pass: columns and dtypes match the canonical schema, every required field is populated, `chunk_id` values are unique, no chunk is empty, `char_count` matches the text length, `sensitivity_level` is a valid RBAC level, and `sub_chunk` is only set where `parent_chunk` is also set.

**5.4 Schema generality check.** A synthetic, non-PDF probe (one audio-transcript turn, with no page, parent/sub-chunk, or title) confirms the schema's structural fields are genuinely optional, not accidentally shaped around PDF documents.

## Step 6 — Save the chunks and verify

**What it does.** Saves all three layers of the flow — the reconstructed text (as extracted), the normalized logical units, and the final chunks — under `Data/processed/rag/{extracted, cleaned, chunks}` (created if missing) as `FBL_template_reconstructed.txt`, `FBL_template_logical_units.json`, and `FBL_template_chunks.parquet`. It then reloads the parquet file from disk and re-runs the schema validator against it, confirming the file that was actually written — not just the in-memory table — satisfies the canonical schema.

---

## Scope note

Cross-checking this document's chunks against the Suez Canal Notes and LPI chunks (same columns, same dtypes, no colliding `chunk_id`) is not repeated in this notebook — it is exercised once, at the project's integration point, in the LPI notebook's own Step 12.

## Addendum 2026-10-02 — Title / text normalization (ADR-041)

A last phase (appended to the script, proven by `tools/nb_to_script.py check`) normalizes the saved chunk file in
place with `pipelines/lib/chunks.py`: a leading heading moves from `text` to `title` (`title` = the location label,
`text` = the body only). Lossless, idempotent; chunk ids, order and count unchanged. Reviewed counts: heading_line 26, unchanged 5.
Where this narrative says a header, path or caption is at the start of every chunk, it is now the chunk's `title`.
