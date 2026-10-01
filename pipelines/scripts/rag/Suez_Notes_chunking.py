"""Suez Canal Transit Dues — Notes Logical-Unit Chunking Pipeline

Origin:  Converted from Notebooks/rag/Suez_Notes_chunking.ipynb (archived in docs/archive/notebooks/).
         Refactored (ADR-036 D3), cleanup level (2026-10-01): the notebook's phases, code and validations are unchanged;
         cell markers, Jupyter display() and the conversion helpers became plain sections and print(); proven by
         `uv run python tools/nb_to_script.py check Suez_Notes_chunking` (AST equal to the archived notebook).
Run:     uv run python tools/run.py pipelines/scripts/rag/Suez_Notes_chunking.py  (from the project root)

Reads:   Data/raw/unstructured/Transit_Dues_Rates.pdf
Writes:  Data/processed/rag/extracted|cleaned|chunks/ (the Suez Notes files)
Re-run:  safe: rewrites the same three artifacts
Final Checkpoint (what was done, problems, fixes): pipelines/checkpoints/rag/Suez_Notes_chunking.md
"""

# %% Suez Canal Transit Dues — Notes Logical-Unit Chunking Pipeline
# This notebook is the Suez Canal Notes half of the Ports & Logistics AI RAG chunking pipeline. It was split out of a combined FBL + Suez Canal notebook so each resource has its own self-contained, checkpointed pipeline — the FBL Bill of Lading is processed the same way in the sibling notebook `FBL_logical_unit_chunking.ipynb`. Both notebooks are organized like the LPI Methodology chunking notebook: classify → extract → build structure-aware logical units → chunk → validate against the shared schema → save → checkpoint.
#
# **Document:** `Transit_Dues_Rates.pdf` — the Suez Canal Authority's transit-dues tariff document (4 PDF pages). Only page 4's "Notes" section is in scope for retrieval; the numeric rate tables stay in PostgreSQL as structured data.
#
# **Why simple page-by-page extraction is not enough:** the Notes section is a flat list of bullet rules — rate exceptions, a definition, inspection-refusal consequences, accepted currencies — of very different lengths and subjects. Splitting by character count would cut a rule in half or glue unrelated rules together; one chunk per bullet would produce several chunks too short to stand on their own.
#
# So the notebook works in **steps**, each one making one kind of decision and handing a clean result to the next:
#
# `classification → raw page text → isolated Notes text → cleaned text → logical units → semantic groups → chunks → unified schema → saved files`


# %% 1. Document Classification
# Every document in the RAG corpus is classified before extraction, using the same fields as the FBL and LPI Methodology documents: `source`, `real_or_synthetic`, `document_type`, `department`, `sensitivity_level`, `version_date`, and `ingestion_scope`.
#
# `Transit_Dues_Rates.pdf` is a real Suez Canal Authority tariff schedule. Unlike FBL, it has a **narrow ingestion scope**: the numeric transit-dues tables stay in PostgreSQL as structured operational data, and only the "Notes" section on page 4 — the qualitative rules that don't fit a rate table (special-vessel definitions, accepted payment currencies, inspection-refusal consequences, …) — is relevant for retrieval (`ingestion_scope: notes_only`).

import pandas as pd

suez_classification = pd.DataFrame([{
    "filename": "Transit_Dues_Rates.pdf",
    "source": "Suez Canal Authority",
    "real_or_synthetic": "real",
    "document_type": "suez_transit_dues_schedule",
    "department": "Finance",
    "sensitivity_level": 1,
    "version_date": "2023-01-01",
    "ingestion_scope": "notes_only",
}])

print(suez_classification.to_string(index=False))


# %% 2. Load the Document
# Import the required libraries and resolve the project root, the input path for the Suez Canal Transit Dues document, and the output folder. We will process only page 4, which contains the "Notes" section.

import re
import pandas as pd
from pathlib import Path

# Locate the project root by walking up from the notebook's folder until the
# Suez PDF is found (same pattern as the FBL and LPI notebooks), so the
# notebook does not depend on one machine's absolute path.
PDF_RELATIVE_PATH = Path("Data/raw/unstructured/Transit_Dues_Rates.pdf")

search_roots = [Path.cwd(), *Path.cwd().parents]

PROJECT_ROOT = next(
    (root for root in search_roots if (root / PDF_RELATIVE_PATH).exists()),
    None,
)
if PROJECT_ROOT is None:
    raise FileNotFoundError(f"{PDF_RELATIVE_PATH} not found above {Path.cwd()}")

# Input PDF and output folder
pdf_path = PROJECT_ROOT / PDF_RELATIVE_PATH
PROCESSED_RAG_DIR = PROJECT_ROOT / "Data" / "processed" / "rag"

print("PDF exists:", pdf_path.exists())


# %% 3. Extract the Notes Section
# The Suez PDF contains four pages, but only page 4 is relevant for this source. We intentionally exclude the vessel-rate tables and extract only the section starting from "Notes:". No semantic rewriting is performed at this stage.

import fitz  # PyMuPDF

doc = fitz.open(pdf_path)

print(f"Number of pages: {len(doc)}")

# Page 4 = index 3
page_4_text = doc[3].get_text("text")

print(page_4_text)

extracted_path = PROCESSED_RAG_DIR / "extracted" / "suez_notes_extracted.txt"

extracted_path.parent.mkdir(parents=True, exist_ok=True)

extracted_path.write_text(
    page_4_text,
    encoding="utf-8"
)

print("Extracted text saved to:")
print(extracted_path)


# %% 4. Isolate the Notes Section
# Locate the "Notes:" heading and discard everything before it. This guarantees that the rate tables from page 4 are not accidentally included in the Suez Notes chunks.

notes_start = page_4_text.find("Notes:")

if notes_start == -1:
    raise ValueError("Could not find 'Notes:' in Page 4.")

notes_text = page_4_text[notes_start:].strip()

print(notes_text)


# %% 5. Clean the Notes Text
# The cleaning here is intentionally conservative. We only normalize excessive whitespace, line breaks caused by PDF extraction, and spacing around the text. We do NOT rewrite the regulatory content or change terminology.

def clean_pdf_text(text):
    # Normalize line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Remove excessive spaces
    text = re.sub(r"[ \t]+", " ", text)

    # Remove excessive blank lines
    text = re.sub(r"\n\s*\n+", "\n\n", text)

    return text.strip()


clean_notes_text = clean_pdf_text(notes_text)

print(clean_notes_text)


# %% 6. Save the Cleaned Text
# Persist the cleaned Notes text to disk before structural parsing begins, so this intermediate result can be inspected or reused independently of the chunking logic below.

cleaned_path = PROCESSED_RAG_DIR / "cleaned" / "suez_notes_cleaned.txt"

cleaned_path.parent.mkdir(parents=True, exist_ok=True)

cleaned_path.write_text(
    clean_notes_text,
    encoding="utf-8"
)

print("Cleaned text saved to:")
print(cleaned_path)


# %% 7. Structure-Aware Logical Unit Detection
# Instead of relying only on the extracted text, use the PDF's text-block structure to preserve natural logical boundaries. The pipeline should:
#
# 1. Extract text blocks with their layout information.
# 2. Detect bullet/number markers.
# 3. Keep wrapped lines belonging to the same item together.
# 4. Preserve nested items such as a./b. inside their parent rule.
# 5. Avoid splitting list continuations into independent logical units.
#
# No source-specific phrases are hardcoded.

import fitz
import re

doc = fitz.open(pdf_path)
page = doc[3]

blocks = page.get_text("blocks")

print("Detected blocks:", len(blocks))

for i, block in enumerate(blocks):
    x0, y0, x1, y1, text, block_no, block_type = block[:7]

    print(f"\n--- Block {i} ---")
    print(f"y={y0:.2f} → {y1:.2f}")
    print(repr(text))


# %% 8. Extract and Reconstruct Logical Units from PDF Layout
# Use PDF text blocks as the structural source of truth, then reconstruct top-level logical units from them.


# %% 8.1 Extract Note Blocks
# A logical unit starts when a block contains a bullet marker (`-`) and continues across subsequent lines/blocks until the next top-level bullet marker.
#
# Nested markers such as `a.` and `b.` remain part of their parent unit. This approach is source-agnostic and preserves the original source text.

def extract_note_blocks(page):
    """
    Extract text blocks belonging to the Notes section.

    Blocks are ordered by their vertical position on the page.
    """

    blocks = page.get_text("blocks")

    note_blocks = []

    for block in blocks:
        x0, y0, x1, y1, text, block_no, block_type = block[:7]

        text = text.strip()

        if not text:
            continue

        # Start collecting once Notes: appears
        if "Notes:" in text:
            note_blocks.append(text[text.find("Notes:"):].strip())
            continue

        if note_blocks:
            note_blocks.append(text)

    return note_blocks


note_blocks = extract_note_blocks(page)

print("Detected note blocks:", len(note_blocks))

for i, block in enumerate(note_blocks, 1):
    print(f"\n--- Note Block {i} ---")
    print(block)


# %% 8.2 Reconstruct Top-Level Logical Units
# Reconstruct logical units from the extracted PDF blocks. The parser detects top-level bullet markers while preserving continuations across lines and blocks.
#
# Nested items such as `a.` and `b.` are not treated as separate logical units.

def reconstruct_logical_units(note_blocks):
    """
    Reconstruct top-level logical units from PDF blocks.

    A top-level '-' starts a new logical unit.
    Nested markers such as 'a.' and 'b.' remain inside
    the current logical unit.

    No source-specific content is used.
    """

    # Combine blocks while preserving their textual order
    full_text = "\n".join(note_blocks)

    # Normalize line endings
    full_text = full_text.replace("\r\n", "\n").replace("\r", "\n")

    # Normalize spaces but keep newlines temporarily
    full_text = re.sub(r"[ \t]+", " ", full_text)

    lines = [
        line.strip()
        for line in full_text.splitlines()
        if line.strip()
    ]

    units = []
    current = None

    for line in lines:

        # Ignore Notes heading
        if line.lower() == "notes:":
            continue

        # Top-level bullet
        is_top_level_bullet = re.match(r"^-\s*$", line) or re.match(
            r"^-\s+",
            line
        )

        if is_top_level_bullet:

            # Save previous unit
            if current is not None:
                units.append({
                    "text": " ".join(current).strip()
                })

            # Remove bullet marker
            content = re.sub(r"^-\s*", "", line).strip()

            current = []

            if content:
                current.append(content)

        else:
            # Continuation of current unit
            if current is not None:
                current.append(line)

    # Save final unit
    if current is not None:
        units.append({
            "text": " ".join(current).strip()
        })

    return units


logical_units = reconstruct_logical_units(note_blocks)

print("Detected logical units:", len(logical_units))

for i, unit in enumerate(logical_units, 1):
    print(f"\n--- Logical Unit {i} ---")
    print(unit["text"])


# %% 9. Semantic Grouping of Logical Units
# Group adjacent logical units when they are semantically related and the resulting chunk remains within the configured size limit. Logical units are never split internally.
#
# The algorithm therefore preserves structural boundaries while allowing related units to form larger retrieval chunks. No source-specific content or rules are hardcoded.

# %pip install -q scikit-learn

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def semantic_group_units(
    units,
    max_chars=1800,
    similarity_threshold=0.10
):
    """
    Group adjacent logical units.

    Rules:
    - Never split a logical unit.
    - Only adjacent units can be grouped.
    - Do not exceed max_chars.
    - Use semantic similarity to decide whether adjacent
      units belong together.
    """

    if not units:
        return []

    texts = [unit["text"] for unit in units]

    # TF-IDF is used only for measuring similarity between
    # already detected logical units.
    vectorizer = TfidfVectorizer(
        ngram_range=(1, 2),
        lowercase=True
    )

    vectors = vectorizer.fit_transform(texts)

    grouped = []
    current_group = [units[0]]

    for i in range(1, len(units)):

        current_text = "\n\n".join(
            unit["text"] for unit in current_group
        )

        next_text = units[i]["text"]

        candidate_text = (
            current_text
            + "\n\n"
            + next_text
        )

        similarity = cosine_similarity(
            vectors[i - 1],
            vectors[i]
        )[0][0]

        exceeds_size = len(candidate_text) > max_chars
        weak_similarity = similarity < similarity_threshold

        if exceeds_size or weak_similarity:

            grouped.append(current_group)

            current_group = [units[i]]

        else:
            current_group.append(units[i])

    grouped.append(current_group)

    return grouped

semantic_groups = semantic_group_units(
    logical_units,
    max_chars=1800,
    similarity_threshold=0.10
)

print("Final semantic groups:", len(semantic_groups))

for i, group in enumerate(semantic_groups, 1):

    text = "\n\n".join(
        unit["text"] for unit in group
    )

    print(f"\n--- Semantic Group {i} ---")
    print("Units:", len(group))
    print("Characters:", len(text))
    print(text)


# %% 10. Unified Chunk Schema
# The Suez Notes chunks are mapped onto the same 16-column chunk schema used for the FBL and LPI Methodology chunks, so all three resource types can live in one retrieval table.


# %% 10.1 Schema Definition and Validator
# `CHUNK_SCHEMA` and its two helpers (`normalize_chunk_schema`, `validate_chunk_schema`) are the same code used in the FBL and LPI notebooks. In the original combined notebook this pipeline relied on the FBL section's definitions having already run earlier in the same kernel; defining them here makes this notebook runnable on its own.

# =========================================================
# Canonical flexible chunk schema
# =========================================================
# Structural fields (page, parent_chunk, sub_chunk, title) are nullable
# when a resource does not have pages, a parent/sub-chunk relationship,
# or a natural title. parent_chunk / sub_chunk are intentionally generic:
# for FBL they hold a clause number and its subclause numbers, but another
# resource type could use section IDs, heading paths, or list positions
# instead. This keeps one retrieval schema across resource types without
# changing chunk text.
CHUNK_SCHEMA = {
    "page": "Int64",
    "unit_type": "string",
    "logical_unit": "string",
    "chunk_id": "string",
    "parent_chunk": "string",
    "sub_chunk": "object",
    "title": "string",
    "text": "string",
    "char_count": "Int64",
    "filename": "string",
    "source": "string",
    "real_or_synthetic": "string",
    "document_type": "string",
    "department": "string",
    "sensitivity_level": "Int64",
    "version_date": "string",
}

REQUIRED_CHUNK_FIELDS = [
    "unit_type", "logical_unit", "chunk_id", "text",
    "char_count", "filename", "source", "real_or_synthetic",
    "document_type", "department", "sensitivity_level",
]

OPTIONAL_CHUNK_DEFAULTS = {
    "page": pd.NA,
    "parent_chunk": pd.NA,
    "sub_chunk": None,
    "title": pd.NA,
    "version_date": pd.NA,
}


def normalize_chunk_schema(chunks_df):
    """Validate, order, and normalize nullable types without altering chunk values."""

    expected_columns = list(CHUNK_SCHEMA)
    missing_columns = [
        column for column in REQUIRED_CHUNK_FIELDS
        if column not in chunks_df.columns
    ]
    unexpected_columns = [
        column for column in chunks_df.columns
        if column not in CHUNK_SCHEMA
    ]

    if missing_columns or unexpected_columns:
        raise ValueError(
            f"Schema mismatch. Missing: {missing_columns}; "
            f"Unexpected: {unexpected_columns}"
        )

    normalized = chunks_df.copy()

    for column, default_value in OPTIONAL_CHUNK_DEFAULTS.items():
        if column not in normalized.columns:
            normalized[column] = default_value

    return normalized.loc[:, expected_columns].astype(CHUNK_SCHEMA)


def validate_chunk_schema(chunks_df, label):
    """
    Run the canonical schema and content checks on a chunks DataFrame.

    Checks:
    - columns match CHUNK_SCHEMA, in order
    - dtypes match CHUNK_SCHEMA
    - every required field (REQUIRED_CHUNK_FIELDS) is fully populated
    - chunk_id values are unique
    - text is non-empty and char_count matches the text length
    - sensitivity_level is a valid RBAC level (1, 2, or 3)
    - sub_chunk is only populated when parent_chunk is also populated

    Prints a PASS/FAIL report for every check, then raises an
    AssertionError naming the failed checks if any check failed.
    Returns the dict of individual check results otherwise.
    """

    expected_columns = list(CHUNK_SCHEMA)
    expected_dtypes = pd.Series(CHUNK_SCHEMA).astype(str)

    has_sub_chunk = chunks_df["sub_chunk"].apply(
        lambda value: isinstance(value, (list, tuple)) and len(value) > 0
    )
    has_parent_chunk = chunks_df["parent_chunk"].notna()

    checks = {
        "columns_match_schema": list(chunks_df.columns) == expected_columns,
        "dtypes_match_schema": chunks_df.dtypes.astype(str).equals(expected_dtypes),
        "required_fields_complete": not chunks_df[REQUIRED_CHUNK_FIELDS].isna().any().any(),
        "chunk_id_unique": chunks_df["chunk_id"].is_unique,
        "text_non_empty": chunks_df["text"].str.strip().ne("").all(),
        "char_count_matches_text_length": (
            chunks_df["text"].str.len() == chunks_df["char_count"]
        ).all(),
        "sensitivity_level_in_range": chunks_df["sensitivity_level"].isin([1, 2, 3]).all(),
        "sub_chunk_requires_parent_chunk": (~has_sub_chunk | has_parent_chunk).all(),
    }

    failed = [name for name, passed in checks.items() if not passed]

    print(f"--- Schema validation: {label} ---")
    for name, passed in checks.items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")

    if failed:
        raise AssertionError(f"{label}: failed checks -> {failed}")

    print(f"{label}: all checks passed ({len(chunks_df)} chunks)\n")
    return checks


# %% 10.2 Build the Chunk DataFrame
# Convert the semantic groups into final chunks using the common project-wide schema. Document-level metadata is read directly from the Section 1 classification table, so chunk metadata always matches the corpus-wide classification. The source text remains unchanged.
#
# Source and RBAC metadata are stored for validation and retrieval filtering, not as part of the generated answer — the same applies to every identifying field (including `filename` and `chunk_id`): none of them should be echoed verbatim into a user-facing answer unless the design explicitly calls for citing sources.

def build_chunk_dataframe(
    semantic_groups,
    page,
    filename,
    source,
    real_or_synthetic,
    document_type,
    department,
    sensitivity_level,
    version_date=None,
    chunk_descriptors=None
):
    """
    Build final chunks using the unified project schema.

    Source-specific values and optional descriptors are metadata.
    The chunk text itself remains source-faithful.
    """

    if (
        chunk_descriptors is not None
        and len(chunk_descriptors) != len(semantic_groups)
    ):
        raise ValueError(
            "Each semantic group needs one chunk descriptor."
        )

    rows = []

    for idx, group in enumerate(semantic_groups, start=1):

        descriptor = (
            chunk_descriptors[idx - 1]
            if chunk_descriptors is not None
            else {}
        )

        text = "\n\n".join(
            unit["text"]
            for unit in group
        ).strip()

        rows.append({
            "page": page,
            "unit_type": "note",
            "logical_unit": descriptor.get(
                "logical_unit", f"notes_group_{idx}"
            ),
            "chunk_id": descriptor.get(
                "chunk_id", f"suez_notes_chunk_{idx}"
            ),

            # Explicit nullable values. The Notes section has no
            # parent/sub-chunk hierarchy, so both stay empty.
            "parent_chunk": pd.NA,
            "sub_chunk": None,
            "title": descriptor.get("title", pd.NA),

            "text": text,
            "char_count": len(text),

            # Metadata
            "filename": filename,
            "source": source,
            "real_or_synthetic": real_or_synthetic,
            "document_type": document_type,
            "department": department,
            "sensitivity_level": sensitivity_level,
            "version_date": version_date
        })

    # Apply the same schema used for FBL. This only standardizes
    # field order and nullable types; it does not rewrite chunk data.
    return normalize_chunk_schema(pd.DataFrame(rows))

# Descriptive metadata improves standalone retrieval without changing text.
suez_chunk_descriptors = [
    {
        "logical_unit": "ballast_and_combined_carrier_rate_rules",
        "chunk_id": "suez_notes_ballast_combined_carrier_rates",
        "title": "Ballast and Combined Carrier Transit-Dues Rules",
    },
    {
        "logical_unit": "inspection_refusal_dues_and_additional_charges",
        "chunk_id": "suez_notes_inspection_refusal_dues",
        "title": "Transit Inspection Refusal, Dues, and Additional Charges",
    },
    {
        "logical_unit": "special_floating_units_definition",
        "chunk_id": "suez_notes_special_floating_units",
        "title": "Definition of Special Floating Units",
    },
    {
        "logical_unit": "transit_conditions_and_accepted_payment_currencies",
        "chunk_id": "suez_notes_transit_conditions_payment_currencies",
        "title": "Transit Conditions and Accepted Payment Currencies",
    },
]

# Document-level metadata is taken from the Section 1 classification table,
# so the chunks always carry the corpus-wide classification values.
suez_document = suez_classification.iloc[0]

suez_chunks_df = build_chunk_dataframe(
    semantic_groups=semantic_groups,
    page=4,
    filename=suez_document["filename"],
    source=suez_document["source"],
    real_or_synthetic=suez_document["real_or_synthetic"],
    document_type=suez_document["document_type"],
    department=suez_document["department"],
    sensitivity_level=int(suez_document["sensitivity_level"]),
    version_date=suez_document["version_date"],
    chunk_descriptors=suez_chunk_descriptors
)

print(suez_chunks_df)


# %% 11. Validate the Unified Chunk Schema
# Run the same shared validator used for the FBL chunks — this is the Suez_chunk test — to confirm this dataset follows the identical schema used across the project.
#
# Validation includes:
#
# - required columns
# - missing values
# - chunk IDs
# - character counts
# - sensitivity levels
# - source metadata

validate_chunk_schema(suez_chunks_df, "Suez_chunks")

print("Rows:", len(suez_chunks_df))
print("Columns:", len(suez_chunks_df.columns))


# %% 12. Save the Chunks and Verify
# Persist the final Suez Notes chunks so they can be combined with the FBL and LPI chunks into the unified RAG chunks table, then reload them from disk and re-verify.


# %% 12.1 Save Suez Chunks
# Persist the final Suez Notes chunks so they can be combined with the FBL chunks (and any future resource) into the unified RAG chunks table.

chunks_path = PROCESSED_RAG_DIR / "chunks" / "suez_notes_chunks.parquet"

chunks_path.parent.mkdir(parents=True, exist_ok=True)

suez_chunks_df.to_parquet(
    chunks_path,
    index=False
)

print("Final chunks saved to:")
print(chunks_path)

print("Final chunks:", len(suez_chunks_df))


# %% 12.2 Reload and Verify Saved Suez Chunks
# Reload the chunks that were just written to disk and re-run the shared schema validator against them — the same reload-and-verify pattern used in the FBL and LPI notebooks. This confirms the parquet file on disk — not just the in-memory DataFrame — satisfies the canonical schema.

chunks_path = PROCESSED_RAG_DIR / "chunks" / "suez_notes_chunks.parquet"

suez_df = pd.read_parquet(chunks_path)

validate_chunk_schema(suez_df, "Suez_chunks (reloaded)")

print("Suez shape:", suez_df.shape)


# %% Note — Source Attribution in Generated Answers
# The schema deliberately links every chunk to its source in metadata (`source`, `filename`, `chunk_id`) for retrieval filtering and RBAC — that part is settled and should stay as-is.
#
# Separately, some chunk **text** itself names the issuing body (e.g. the Suez Notes chunk that quotes "Suez Canal Authority's rules and regulations"). That text must stay verbatim — rewriting or scrubbing a regulatory source's own wording would misrepresent it and is a compliance risk, not a cleanup task.
#
# If a generic, non-attributing answer is a product requirement, it belongs in the retrieval/generation layer, not in this chunking pipeline:
#
# - Do not forward raw `chunk_id` or `filename` values into the LLM's context — they are retrieval/RBAC metadata, not answer content.
# - Add an explicit instruction in the generation system prompt telling the model to describe the regulation generically (e.g. "canal transit regulations") unless the user asks which authority issued it.
# - If specific answers must never name the source even when asked, that is a prompt/business-logic decision to make deliberately, not a side effect of chunk cleaning.
