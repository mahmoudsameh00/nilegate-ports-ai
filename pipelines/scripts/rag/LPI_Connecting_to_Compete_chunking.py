"""Phase 0 — Setup & Configuration

Origin:  Converted from Notebooks/rag/LPI_Connecting_to_Compete_chunking.ipynb (archived in docs/archive/notebooks/).
         Refactored (ADR-036 D3), cleanup level (2026-10-01): the notebook's phases, code and validations are unchanged;
         cell markers, Jupyter display() and the conversion helpers became plain sections and print(); proven by
         Appended: title / text normalization appended as the last phase (ADR-041, owner decision 2026-10-02).
         `uv run python tools/nb_to_script.py check LPI_Connecting_to_Compete_chunking` (AST equal to the archived notebook).
Run:     uv run python tools/run.py pipelines/scripts/rag/LPI_Connecting_to_Compete_chunking.py  (from the project root)

Reads:   Data/raw/unstructured/LPI.pdf; Data/processed/rag/cleaned/LPI_Methodology_logical_units.json (dedup)
Writes:  Data/processed/rag/extracted|cleaned|chunks/ (the LPI Connecting to Compete files); review aids in Notebooks/_scratch/ (git-ignored)
Re-run:  safe: rewrites the same three artifacts; run after LPI_methodology_chunking
Final Checkpoint (what was done, problems, fixes): pipelines/checkpoints/rag/LPI_Connecting_to_Compete_chunking.md
"""

# %% Phase 0 — Setup & Configuration
# This phase initializes the environment and defines the source and pipeline configuration for the
# LPI Connecting to Compete 2025 ingestion pipeline.
#
# The purpose of this phase is to prepare the notebook for all downstream processing without
# performing any PDF extraction, page classification, structural parsing, duplicate detection,
# or chunking yet.
#
# The phase establishes:
#
# - Required Python libraries and runtime environment
# - Source PDF location
# - Project and output directories
# - Source/document metadata
# - Pipeline configuration
# - Source file fingerprinting for reproducibility
#
# No transformation of the PDF content is performed in this phase.

# =========================================================
# 0.1 Imports & Environment
# =========================================================

from pathlib import Path
import re
import json
import hashlib
import unicodedata
import difflib

import pandas as pd
import numpy as np
import pymupdf

print("Imports loaded successfully.")
print("pandas :", pd.__version__)
print("numpy  :", np.__version__)

# =========================================================
# 0.2 Locate the source PDF
# =========================================================

PDF_RELATIVE_PATH = Path("Data/raw/unstructured/LPI.pdf")

search_roots = [Path.cwd(), *Path.cwd().parents]

candidates = [
    root / PDF_RELATIVE_PATH
    for root in search_roots
]

PDF_PATH = next(
    (path for path in candidates if path.exists()),
    None,
)

if PDF_PATH is None:
    raise FileNotFoundError(
        "LPI Connecting to Compete 2025 PDF was not found.\n\n"
        "Looked in:\n"
        + "\n".join(f"  {path}" for path in candidates)
    )

print("PDF found successfully.")
print("PDF path :", PDF_PATH)

# =========================================================
# 0.3 Open the source PDF
# =========================================================

doc = pymupdf.open(PDF_PATH)

print("Document opened successfully.")
print("Document name :", PDF_PATH.name)
print("Total pages   :", len(doc))

# =========================================================
# 0.4 Inspect PDF metadata
# =========================================================

pdf_metadata = doc.metadata

print("PDF metadata:")
for key, value in pdf_metadata.items():
    print(f"{key:12}: {value}")

# =========================================================
# 0.5 Define project and output paths
# =========================================================

PROJECT_ROOT = PDF_PATH.parents[3]

PROCESSED_RAG_DIR = PROJECT_ROOT / "Data" / "processed" / "rag"

EXTRACTED_DIR = PROCESSED_RAG_DIR / "extracted"
CLEANED_DIR = PROCESSED_RAG_DIR / "cleaned"
CHUNKS_DIR = PROCESSED_RAG_DIR / "chunks"

for directory in (
    EXTRACTED_DIR,
    CLEANED_DIR,
    CHUNKS_DIR,
):
    directory.mkdir(parents=True, exist_ok=True)

print("Project root     :", PROJECT_ROOT)
print("Processed RAG    :", PROCESSED_RAG_DIR)
print("Extracted dir    :", EXTRACTED_DIR)
print("Cleaned dir      :", CLEANED_DIR)
print("Chunks dir       :", CHUNKS_DIR)

# =========================================================
# 0.6 Define source and pipeline configuration
# =========================================================

SOURCE_NAME = "LPI_Connecting_to_Compete"
SOURCE_FILE = PDF_PATH.name

DOCUMENT_TYPE = "lpi_connecting_to_compete_2025"
REAL_OR_SYNTHETIC = "real"

DEPARTMENT = "Operations"  # owner department; must exist in the departments table (ADR-006)
SENSITIVITY_LEVEL = 1
VERSION_DATE = "2025"

SOURCE_DESCRIPTION = (
    "Connecting to Compete 2025: "
    "Trade Logistics in the Global Economy — "
    "The New Logistics Performance Indicators 2.0"
)

MIN_CHUNK_CHARS = 300
MAX_CHUNK_CHARS = 2000

source_metadata = {
    "source_name": SOURCE_NAME,
    "source_file": SOURCE_FILE,
    "document_type": DOCUMENT_TYPE,
    "real_or_synthetic": REAL_OR_SYNTHETIC,
    "department": DEPARTMENT,
    "sensitivity_level": SENSITIVITY_LEVEL,
    "version_date": VERSION_DATE,
}

print("Source configuration:")
for key, value in source_metadata.items():
    print(f"{key:20}: {value}")

print("\nChunk configuration:")
print("MIN_CHUNK_CHARS :", MIN_CHUNK_CHARS)
print("MAX_CHUNK_CHARS :", MAX_CHUNK_CHARS)

# =========================================================
# 0.7 Source file fingerprint
# =========================================================

def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    sha256 = hashlib.sha256()

    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            sha256.update(chunk)

    return sha256.hexdigest()


SOURCE_SHA256 = sha256_file(PDF_PATH)
SOURCE_FILE_SIZE = PDF_PATH.stat().st_size

print("Source file fingerprint:")
print("File :", PDF_PATH.name)
print("Size :", SOURCE_FILE_SIZE, "bytes")
print("SHA256:", SOURCE_SHA256)

# =========================================================
# 0.8 Phase 0 validation
# =========================================================

assert PDF_PATH.exists(), "Source PDF does not exist."
assert len(doc) > 0, "PDF contains no pages."

assert SOURCE_NAME
assert SOURCE_FILE == PDF_PATH.name
assert DOCUMENT_TYPE == "lpi_connecting_to_compete_2025"
assert REAL_OR_SYNTHETIC == "real"
assert DEPARTMENT == "Operations"
assert SENSITIVITY_LEVEL in [1, 2, 3]
assert VERSION_DATE == "2025"

assert MIN_CHUNK_CHARS > 0
assert MAX_CHUNK_CHARS > MIN_CHUNK_CHARS

assert len(SOURCE_SHA256) == 64
assert SOURCE_FILE_SIZE > 0

print("✅ Phase 0 validation passed.")
print("Pages :", len(doc))
print("Source:", SOURCE_NAME)
print("SHA256:", SOURCE_SHA256)


# %% Phase 1 — Page Inventory
# This phase creates a raw page-level inventory of the source PDF.
#
# The purpose is to inspect the document page by page before applying any
# classification, structural parsing, table/figure extraction, cleaning,
# deduplication, or chunking logic.
#
# For each physical PDF page, the inventory records:
#
# - Page number
# - Character count
# - Word count
# - Line count
# - Text block count
# - Image, drawing and link counts
# - Page width and height
# - Raw extracted text
#
# Note: this report contains vector/drawing-heavy figures, so `image_count` alone
# must not be treated as figure detection; `drawing_count` is recorded as well.
#
# At this stage, the extracted text is preserved as-is. No normalization,
# cleaning, paragraph reconstruction, or content filtering is performed.
#
# The resulting page inventory will be used as the foundation for the next
# phase, where each page is classified according to its actual content and
# role in the document.

# =========================================================
# 1.1 Build page inventory
# =========================================================

page_records = []

for page_idx in range(len(doc)):
    page = doc[page_idx]
    text = page.get_text("text") or ""

    # text blocks only (block_type == 0); image blocks are counted separately
    text_blocks = [b for b in page.get_text("blocks") if b[6] == 0]

    page_records.append({
        "page_number": page_idx + 1,
        "char_count": len(text),
        "word_count": len(text.split()),
        "line_count": len(text.splitlines()),
        "text_block_count": len(text_blocks),
        "image_count": len(page.get_images(full=True)),
        "drawing_count": len(page.get_drawings()),
        "link_count": len(page.get_links()),
        "page_width": round(page.rect.width, 1),
        "page_height": round(page.rect.height, 1),
        "text": text,
    })

pages_df = pd.DataFrame(page_records)

print("Page inventory created successfully.")
print("Rows :", len(pages_df))
print("Columns:", list(pages_df.columns))

# =========================================================
# 1.2 Inventory statistics
# =========================================================

print("Page inventory statistics:\n")

print("Total pages :", len(pages_df))
print("Total chars :", pages_df["char_count"].sum())
print("Total words :", pages_df["word_count"].sum())
print("Total lines :", pages_df["line_count"].sum())

print("\nCharacter count:")
print(pages_df["char_count"].describe())

print("\nWord count:")
print(pages_df["word_count"].describe())

print("\nVisual / structural signals:")
print(pages_df[["text_block_count", "image_count", "drawing_count", "link_count"]].describe())

print("\nPage sizes (width x height):")
print(pages_df.groupby(["page_width", "page_height"]).size())

# =========================================================
# 1.3 Inventory preview (all pages)
# =========================================================

preview_df = pages_df.copy()

preview_df["text_preview"] = (
    preview_df["text"]
    .str.replace(r"\s+", " ", regex=True)
    .str.strip()
    .str[:250]
)

print(
    preview_df[
        ["page_number", "char_count", "word_count", "line_count",
         "text_block_count", "image_count", "drawing_count", "link_count",
         "text_preview"]
    ]
)

# =========================================================
# 1.4 Flag unusual pages (empty / very short / very long)
# =========================================================

special_pages_df = pages_df[
    (pages_df["char_count"] == 0) |
    (pages_df["char_count"] < 500) |
    (pages_df["char_count"] > 5000)
].copy()

print(
    special_pages_df[
        ["page_number", "char_count", "word_count", "line_count",
         "text_block_count", "image_count", "drawing_count"]
    ]
)

# =========================================================
# 1.5 Raw text inspection of selected pages
# =========================================================

inspection_pages = [1, 2, 3, 5, 6, 7, 8, 9, 10, 28, 29, 30]

for page_number in inspection_pages:
    row = pages_df.loc[pages_df["page_number"] == page_number].iloc[0]

    print("=" * 100)
    print(f"PAGE {page_number}")
    print(f"chars={row['char_count']} | words={row['word_count']} | lines={row['line_count']}")
    print("-" * 100)

    text_preview = row["text"].strip()

    if not text_preview:
        print("[EMPTY PAGE]")
    else:
        print(text_preview[:1200])

    print()

# =========================================================
# 1.6 Phase 1 validation
# =========================================================

expected_columns = [
    "page_number", "char_count", "word_count", "line_count",
    "text_block_count", "image_count", "drawing_count", "link_count",
    "page_width", "page_height", "text",
]

assert list(pages_df.columns) == expected_columns, "Unexpected inventory columns."
assert len(pages_df) == len(doc), "Inventory row count != PDF page count."
assert pages_df["page_number"].tolist() == list(range(1, len(doc) + 1)), "Page numbers not 1..N."
assert (pages_df["char_count"] == pages_df["text"].str.len()).all(), "char_count mismatch."

count_cols = expected_columns[1:8]
assert (pages_df[count_cols] >= 0).all().all(), "Negative counts found."
assert (pages_df[["page_width", "page_height"]] > 0).all().all(), "Invalid page size."

print("✅ Phase 1 validation passed.")
print("Pages          :", len(pages_df))
print("Empty pages    :", int((pages_df["char_count"] == 0).sum()))
print("Pages w/ images:", int((pages_df["image_count"] > 0).sum()))
print("Pages w/ drawings:", int((pages_df["drawing_count"] > 0).sum()))


# %% Phase 2 — Page Classification
# Each page receives a class label and a human-readable reason.
#
# - Non-retrieval: `cover_title`, `blank`, `legal`, `contents`, `acknowledgements`, `references`
# - Auxiliary (excluded from retrieval, still used downstream): `notes_auxiliary`
# - Retrieval: `content`
#
# Rules are derived from observed page signals (2.1), not from hard-coded page numbers.

# =========================================================
# 2.1 Page signals (inspection only — no decisions yet)
# =========================================================

NUMBER_LINE = re.compile(r"^(?:\d{1,3}|[ivxlc]{1,6})$", re.IGNORECASE)
LEGAL_PATTERN = re.compile(
    r"©|\bisbn\b|creative commons|rights and permissions|\bdoi\b",
    re.IGNORECASE,
)
HEADING_PATTERNS = {
    "contents": r"^contents$",
    "foreword": r"^foreword$",
    "acknowledgments": r"^acknowledge?ments$",
    "abbreviations": r"^abbreviations",
    "executive_summary": r"^executive summary$",
    "chapter": r"^chapter\s+\d+$",
    "notes": r"^notes$",
    "references": r"^references$",
}


def non_empty_lines(text: str) -> list[str]:
    return [
        unicodedata.normalize("NFKC", line).strip()
        for line in text.splitlines()
        if line.strip()
    ]


def heading_hits(lines: list[str], top_n: int = 5) -> list[str]:
    top = [line.lower() for line in lines[:top_n]]
    return [
        name for name, pattern in HEADING_PATTERNS.items()
        if any(re.match(pattern, line) for line in top)
    ]


signal_records = []

for row in pages_df.itertuples():
    lines = non_empty_lines(row.text)
    number_lines = sum(bool(NUMBER_LINE.match(line)) for line in lines)

    signal_records.append({
        "page_number": row.page_number,
        "word_count": row.word_count,
        "text_block_count": row.text_block_count,
        "image_count": row.image_count,
        "drawing_count": row.drawing_count,
        "is_blank": row.word_count == 0,
        "legal_marker": bool(LEGAL_PATTERN.search(row.text)),
        "number_line_ratio": round(number_lines / len(lines), 2) if lines else 0.0,
        "heading_hits": heading_hits(lines),
        "first_lines": " | ".join(lines[:3])[:120],
    })

signals_df = pd.DataFrame(signal_records)

with pd.option_context("display.max_rows", None, "display.max_colwidth", 120):
    print(signals_df)

# =========================================================
# 2.2 Inspect ambiguous pages (raw text)
# =========================================================

AMBIGUOUS_PAGES = [4, 5, 7, 8, 30]

for page_number in AMBIGUOUS_PAGES:
    lines = non_empty_lines(pages_df.loc[pages_df["page_number"] == page_number, "text"].iloc[0])
    print("=" * 100)
    print(f"PAGE {page_number} | lines={len(lines)}")
    print("-" * 100)
    print("\n".join(lines[:40]))
    if len(lines) > 40:
        print(f"... [{len(lines) - 40} more lines]")
    print()

# Page 28: locate where Notes end and References begin
lines_28 = non_empty_lines(pages_df.loc[pages_df["page_number"] == 28, "text"].iloc[0])
ref_idx = [i for i, line in enumerate(lines_28) if line.lower() == "references"]

print("=" * 100)
print(f"PAGE 28 | lines={len(lines_28)} | 'References' heading at line index: {ref_idx}")
print("-" * 100)
if ref_idx:
    start = max(ref_idx[0] - 5, 0)
    print("\n".join(f"{i:>3}: {lines_28[i]}" for i in range(start, min(ref_idx[0] + 6, len(lines_28)))))
else:
    print("No standalone 'References' line found. Last 15 lines:")
    print("\n".join(f"{i:>3}: {line}" for i, line in enumerate(lines_28) if i >= len(lines_28) - 15))

# =========================================================
# 2.3 Edge-heading detection and document region boundaries
# =========================================================
# Headings in this PDF can appear at the END of the extracted text
# (e.g. "Abbreviations" on p.7, "About this report" on p.8),
# so we scan the first 5 AND last 3 non-empty lines.

HEADING_PATTERNS["about_this_report"] = r"^about this report$"


def edge_heading_hits(lines: list[str], top_n: int = 5, bottom_n: int = 3) -> list[str]:
    edge = [line.lower() for line in lines[:top_n] + lines[-bottom_n:]]
    return sorted({
        name for name, pattern in HEADING_PATTERNS.items()
        if any(re.match(pattern, line) for line in edge)
    })


signals_df["edge_hits"] = pages_df["text"].map(lambda t: edge_heading_hits(non_empty_lines(t)))
signals_df["has_copyright"] = pages_df["text"].str.contains("©", regex=False)


def first_page_with(hit: str, after: int = 0) -> int | None:
    pages = signals_df.loc[
        signals_df["edge_hits"].apply(lambda hits: hit in hits)
        & (signals_df["page_number"] > after),
        "page_number",
    ]
    return int(pages.min()) if len(pages) else None


LAST_PAGE = len(doc)
FIRST_LEGAL_PAGE = int(signals_df.loc[signals_df["has_copyright"], "page_number"].min())
BODY_START = first_page_with("executive_summary")
NOTES_START = first_page_with("notes", after=BODY_START or 0)
REFERENCES_START = first_page_with("references", after=NOTES_START or 0)

print("Region boundaries:")
print("FIRST_LEGAL_PAGE :", FIRST_LEGAL_PAGE)
print("BODY_START       :", BODY_START)
print("NOTES_START      :", NOTES_START)
print("REFERENCES_START :", REFERENCES_START)
print("LAST_PAGE        :", LAST_PAGE)

with pd.option_context("display.max_rows", None):
    print(signals_df[["page_number", "word_count", "number_line_ratio", "has_copyright", "edge_hits"]])

# =========================================================
# 2.4 Page classification rules
# =========================================================
# Region-based classification: boundaries come from 2.3 (no hard-coded pages).
# Rule order matters: e.g. p.4 has both "contents" and "abbreviations" hits,
# so "contents" is checked first.

assert None not in (BODY_START, NOTES_START, REFERENCES_START), "A region boundary was not detected."
assert FIRST_LEGAL_PAGE < BODY_START < NOTES_START < REFERENCES_START <= LAST_PAGE

CONTENTS_RATIO_THRESHOLD = 0.25  # front matter only; body figure pages reach 0.28

RETRIEVAL_CLASSES = {"content", "back_cover"}
AUXILIARY_CLASSES = {"notes_auxiliary", "abbreviations"}
ALLOWED_CLASSES = {
    "cover_title", "blank", "legal", "contents", "acknowledgements",
    "abbreviations", "references", "notes_auxiliary", "content", "back_cover",
}


def classify_page(sig) -> tuple[str, str, str]:
    """Return (region, page_class, reason) for one row of signals_df."""
    p, hits = sig.page_number, sig.edge_hits

    if sig.word_count == 0:
        return "any", "blank", "No extractable text"

    if p == LAST_PAGE:
        return "back", "back_cover", "Last physical page; summary blurb, sent to dedup (Phase 10)"

    # ---------- front matter ----------
    if p < BODY_START:
        if sig.has_copyright:
            return "front", "legal", "Contains © notice"
        if p < FIRST_LEGAL_PAGE:
            return "front", "cover_title", "Before the legal page; title material only"
        if "contents" in hits or sig.number_line_ratio >= CONTENTS_RATIO_THRESHOLD:
            return "front", "contents", f"Contents heading or page-number ratio={sig.number_line_ratio}"
        if "acknowledgments" in hits:
            return "front", "acknowledgements", "Acknowledgements heading"
        if "abbreviations" in hits:
            return "front", "abbreviations", "Abbreviations heading; kept for definitions (Phase 4)"
        if "about_this_report" in hits:
            return "front", "content", "About this report: the report's own abstract"
        return "front", "unclassified", "Front-matter page matched no rule"

    # ---------- body ----------
    if p < NOTES_START:
        return "body", "content", "Between Executive summary and Notes"

    # ---------- back matter ----------
    if p < REFERENCES_START:
        return "back", "notes_auxiliary", "Endnote registry; used for note linking (Phase 5)"
    return "back", "references", "Bibliography; not needed for retrieval"


rows = [classify_page(sig) for sig in signals_df.itertuples()]

page_class_df = signals_df[["page_number", "word_count"]].copy()
page_class_df[["region", "page_class", "reason"]] = pd.DataFrame(rows, index=signals_df.index)
page_class_df["keep_for_retrieval"] = page_class_df["page_class"].isin(RETRIEVAL_CLASSES)
page_class_df["is_auxiliary"] = page_class_df["page_class"].isin(AUXILIARY_CLASSES)

with pd.option_context("display.max_rows", None, "display.max_colwidth", 80):
    print(page_class_df)

print("\nClass counts:")
print(page_class_df["page_class"].value_counts())

# =========================================================
# 2.5 Phase 2 validation
# =========================================================

# ---- completeness ----
assert len(page_class_df) == len(doc), "Not every page was classified."
assert page_class_df["page_number"].tolist() == list(range(1, len(doc) + 1))
assert page_class_df["page_class"].isin(ALLOWED_CLASSES).all(), "Unknown / unclassified page found."
assert page_class_df["reason"].str.strip().ne("").all(), "Every page needs a reason."

# ---- flag consistency ----
assert (page_class_df["keep_for_retrieval"] == page_class_df["page_class"].isin(RETRIEVAL_CLASSES)).all()
assert (page_class_df["is_auxiliary"] == page_class_df["page_class"].isin(AUXILIARY_CLASSES)).all()
assert not (page_class_df["keep_for_retrieval"] & page_class_df["is_auxiliary"]).any(), \
    "A page cannot be both retrieval and auxiliary."

# ---- structural rules ----
body_pages = page_class_df.loc[page_class_df["region"] == "body"]
assert (body_pages["page_class"] == "content").all(), "Non-content page inside the body region."
assert body_pages["page_number"].tolist() == list(range(BODY_START, NOTES_START)), "Body is not contiguous."

retrieval_pages = page_class_df.loc[page_class_df["keep_for_retrieval"]]
assert (retrieval_pages["word_count"] > 0).all(), "Retrieval page with no text."

notes_pages = page_class_df.loc[page_class_df["page_class"] == "notes_auxiliary", "page_number"]
ref_pages = page_class_df.loc[page_class_df["page_class"] == "references", "page_number"]
assert len(notes_pages) >= 1 and len(ref_pages) >= 1
assert notes_pages.max() < ref_pages.min(), "Notes must come before References."
assert not ref_pages.isin(retrieval_pages["page_number"]).any(), "References must not be retrieved."

back_cover = page_class_df.loc[page_class_df["page_class"] == "back_cover", "page_number"]
assert back_cover.tolist() == [LAST_PAGE], "back_cover must be exactly the last page."

# ---- reviewed snapshot (regression guard) ----
# Manually reviewed on 2026-09-24. If the rules change, this must still hold.
REVIEWED_CLASSES = {
    1: "cover_title", 2: "cover_title", 3: "legal", 4: "contents", 5: "contents",
    6: "acknowledgements", 7: "abbreviations", 8: "content", 9: "blank",
    **{p: "content" for p in range(10, 28)},
    28: "notes_auxiliary", 29: "references", 30: "back_cover",
}
actual = dict(zip(page_class_df["page_number"], page_class_df["page_class"]))
mismatches = {p: (REVIEWED_CLASSES[p], actual[p]) for p in REVIEWED_CLASSES if REVIEWED_CLASSES[p] != actual[p]}
assert not mismatches, f"Classification drifted from reviewed snapshot: {mismatches}"

# ---- summary ----
def pages_of(mask) -> list[int]:
    return page_class_df.loc[mask, "page_number"].tolist()

print("✅ Phase 2 validation passed.")
print("Retrieval pages :", pages_of(page_class_df["keep_for_retrieval"]))
print("Auxiliary pages :", pages_of(page_class_df["is_auxiliary"]))
print("Excluded pages  :", pages_of(~page_class_df["keep_for_retrieval"] & ~page_class_df["is_auxiliary"]))


# %% Phase 3 — Structure Reconnaissance
# Goal: build a confirmed `section_map` (headings, levels, physical positions) and a
# confirmed figure/table caption inventory. No content is extracted in this phase.
#
# The PDF outline is inspected but is **not** the source of truth; the hierarchy comes
# from visible headings (font/position) cross-checked against the Contents pages.

# =========================================================
# 3.1 Layout profile: line table, body font size, running headers
# =========================================================

RETRIEVAL_PAGES = page_class_df.loc[page_class_df["keep_for_retrieval"], "page_number"].tolist()

line_records = []

for page_idx in range(len(doc)):
    page_dict = doc[page_idx].get_text("dict")

    for block_no, block in enumerate(page_dict["blocks"]):
        if block.get("type") != 0:          # text blocks only
            continue

        for line_no, line in enumerate(block["lines"]):
            spans = [s for s in line["spans"] if s["text"].strip()]
            if not spans:
                continue

            text = "".join(s["text"] for s in line["spans"]).strip()
            main_span = max(spans, key=lambda s: len(s["text"].strip()))   # dominant span
            x0, y0, x1, y1 = line["bbox"]

            line_records.append({
                "page_number": page_idx + 1,
                "block_no": block_no,
                "line_no": line_no,
                "x0": round(x0, 1), "y0": round(y0, 1),
                "x1": round(x1, 1), "y1": round(y1, 1),
                "text": text,
                "n_chars": len(text),
                "size": round(main_span["size"], 1),
                "font": main_span["font"],
                "is_bold": bool(main_span["flags"] & 16) or "bold" in main_span["font"].lower(),
            })

lines_df = pd.DataFrame(line_records)
retr_lines = lines_df[lines_df["page_number"].isin(RETRIEVAL_PAGES)]

# ---- body font size = the size carrying the most characters ----
size_profile = (
    retr_lines.groupby("size")
    .agg(chars=("n_chars", "sum"), lines=("text", "size"), bold_share=("is_bold", "mean"))
    .sort_values("chars", ascending=False)
)
BODY_FONT_SIZE = float(size_profile.index[0])

# ---- running headers/footers = normalized lines repeated across pages ----
def repeat_key(text: str) -> str:
    key = re.sub(r"\d+", "#", text.lower())
    return "#" if re.fullmatch(r"[ivxlc]+", key) else key

repeated_df = (
    retr_lines.assign(key=retr_lines["text"].map(repeat_key))
    .groupby("key")
    .agg(pages=("page_number", "nunique"), y0_min=("y0", "min"), y1_max=("y1", "max"),
         size=("size", "first"), example=("text", "first"))
    .query("pages >= 3")
    .sort_values("pages", ascending=False)
)

print("Lines extracted     :", len(lines_df), "| on retrieval pages:", len(retr_lines))
print("Page size (w x h)   :", pages_df[["page_width", "page_height"]].drop_duplicates().values.tolist())
print("BODY_FONT_SIZE      :", BODY_FONT_SIZE)

print("\nFont-size profile (retrieval pages):")
print(size_profile.head(15))

print("\nRepeated lines (running header/footer candidates):")
with pd.option_context("display.max_colwidth", 90):
    print(repeated_df)

# =========================================================
# 3.2 Running header / footer zones
# =========================================================
# From 3.1: chapter running header ends at y1≈28.5; the "CHAPTER" opener label
# starts at y0≈36.5 (must stay in the body zone); report-title footer starts at y0≈756.

HEADER_MAX_Y1 = 32.0
FOOTER_MIN_Y0 = 750.0

PAGE_NUMBER_RE = r"\d{1,3}|[ivxlc]{1,6}"

lines_df["zone"] = np.select(
    [lines_df["y1"] <= HEADER_MAX_Y1, lines_df["y0"] >= FOOTER_MIN_Y0],
    ["header", "footer"],
    default="body",
)
lines_df["is_page_number"] = lines_df["text"].str.fullmatch(PAGE_NUMBER_RE, case=False)

retr_mask = lines_df["page_number"].isin(RETRIEVAL_PAGES)

# ---- 1) what lives in the header/footer zones? (should be running text + page numbers only)
zone_lines = lines_df[retr_mask & (lines_df["zone"] != "body")]
zone_summary = (
    zone_lines.assign(key=zone_lines["text"].map(repeat_key))
    .groupby(["zone", "key"])
    .agg(pages=("page_number", "nunique"), size=("size", "first"),
         y0_min=("y0", "min"), y1_max=("y1", "max"))
    .sort_values(["zone", "pages"], ascending=[True, False])
)
print("Header/footer zone contents (retrieval pages):")
with pd.option_context("display.max_colwidth", 90):
    print(zone_summary)

# ---- 2) where do standalone number lines sit? (page numbers vs chart values)
number_lines = lines_df[retr_mask & lines_df["is_page_number"]]
print("\nStandalone number lines by zone:")
print(
    number_lines.groupby(["zone", "size", "is_bold"])
    .agg(lines=("text", "size"), pages=("page_number", "nunique"),
         y0_min=("y0", "min"), y1_max=("y1", "max"))
)

# ---- 3) coverage: retrieval pages with no header/footer line at all
zone_pages = set(zone_lines["page_number"])
print("\nRetrieval pages with NO header/footer line:", sorted(set(RETRIEVAL_PAGES) - zone_pages))

# =========================================================
# 3.3 Figure / table caption inventory: expected (Contents) vs observed (pages)
# =========================================================

CAPTION_NUM = r"(\d{1,2}\.\d{1,2})"
NUM_START = re.compile(CAPTION_NUM + r"(?:\s|$)")
PRINTED_PAGE = re.compile(r"\d{1,3}")

# ---- printed page -> physical page offset (from footer page numbers) ----
footer_nums = lines_df[
    (lines_df["zone"] == "footer") & lines_df["text"].str.fullmatch(r"\d{1,3}")
]
offsets = (footer_nums["page_number"] - footer_nums["text"].astype(int)).unique()
assert len(offsets) == 1, f"Printed->physical offset is not constant: {offsets}"
PAGE_OFFSET = int(offsets[0])

# ---- 1) expected inventory parsed from the Contents pages ----
contents_pages = page_class_df.loc[page_class_df["page_class"] == "contents", "page_number"].tolist()
toc = lines_df[lines_df["page_number"].isin(contents_pages) & (lines_df["zone"] == "body")]["text"].str.strip().tolist()

expected_records, kind, i = [], None, 0
while i < len(toc):
    t = toc[i]
    if t.lower().startswith("figure"):
        kind = "figure"
    elif t.lower().startswith("table"):
        kind = "table"

    m = NUM_START.match(t)
    if kind and m:
        title_parts, j = [t[m.end():].strip()], i + 1
        while j < len(toc) and not PRINTED_PAGE.fullmatch(toc[j]) and not NUM_START.match(toc[j]):
            title_parts.append(toc[j])
            j += 1
        printed = int(toc[j]) if j < len(toc) and PRINTED_PAGE.fullmatch(toc[j]) else None
        expected_records.append({
            "kind": kind, "number": m.group(1),
            "toc_title": " ".join(p for p in title_parts if p),
            "printed_page": printed,
            "expected_page": printed + PAGE_OFFSET if printed else None,
        })
        i = j + 1
        continue
    i += 1

expected_df = pd.DataFrame(expected_records)

# ---- 2) observed caption labels on retrieval pages ----
LABEL_RE = re.compile(r"^(figure|table)\s*" + CAPTION_NUM + r"\b", re.IGNORECASE)
retr_body = lines_df[lines_df["page_number"].isin(RETRIEVAL_PAGES) & (lines_df["zone"] == "body")]

observed_records = []
for idx, r in retr_body.iterrows():
    m = LABEL_RE.match(r["text"])
    if not m:
        continue
    nxt = lines_df.loc[idx + 1: idx + 2]
    nxt = nxt[nxt["page_number"] == r["page_number"]]
    observed_records.append({
        "kind": m.group(1).lower(), "number": m.group(2),
        "page_number": r["page_number"], "y0": r["y0"],
        "size": r["size"], "is_bold": r["is_bold"],
        "label_style": r["size"] != BODY_FONT_SIZE,      # False = prose reference ("Figure 2.1 shows…")
        "text": r["text"][:60],
        "next_text": " | ".join(nxt["text"])[:100],
    })
observed_df = pd.DataFrame(observed_records)
labels_df = observed_df[observed_df["label_style"]]

# ---- 3) compare ----
obs_pages = labels_df.groupby(["kind", "number"])["page_number"].apply(sorted).rename("observed_pages")
comparison_df = expected_df.join(obs_pages, on=["kind", "number"])
comparison_df["status"] = [
    "missing" if not isinstance(pages, list)
    else ("ok" if exp in pages else "page_mismatch")
    for exp, pages in zip(comparison_df["expected_page"], comparison_df["observed_pages"])
]
unexpected = labels_df.merge(expected_df[["kind", "number"]], how="left", indicator=True).query("_merge == 'left_only'")

# ---- 4) loose candidates: caption-style lines mentioning Figure/Table that the strict regex missed ----
loose_df = retr_body[
    retr_body["text"].str.contains(r"\b(?:figure|table)\b", case=False)
    & (retr_body["size"] != BODY_FONT_SIZE)
    & ~retr_body["text"].str.match(LABEL_RE)
][["page_number", "y0", "size", "is_bold", "text"]]

print("PAGE_OFFSET (physical - printed):", PAGE_OFFSET)
print(f"Expected from Contents: {len(expected_df)} "
      f"(figures={int((expected_df['kind']=='figure').sum())}, tables={int((expected_df['kind']=='table').sum())})")

print("\n[A] Expected vs observed:")
with pd.option_context("display.max_colwidth", 70, "display.max_rows", None):
    print(comparison_df)

print("\n[B] Observed label-style captions not in Contents:")
print(unexpected.drop(columns="_merge"))

print("\n[C] All observed label lines (incl. prose references):")
with pd.option_context("display.max_colwidth", 100, "display.max_rows", None):
    print(observed_df)

print("\n[D] Loose Figure/Table lines missed by the strict pattern:")
with pd.option_context("display.max_colwidth", 100, "display.max_rows", None):
    print(loose_df)

# =========================================================
# 3.4 Heading candidates (font-role based)
# =========================================================
# Font profile showed that heading level is carried by the FONT, not size/bold flags:
#   EurostileLTStd-Bold >= 13pt -> title (60pt = decorative chapter number)
#   HelveticaNeueLTStd-Hv       -> section heading (Heavy weight, NOT flagged bold)
#   GaramondPremrPro-Bd + "N.N" -> run-in subsection (bold lead-in inside a paragraph)
# Bold Garamond without "N.N" = emphasis inside bullets, not a heading.

TITLE_FONT = "EurostileLTStd-Bold"
SECTION_FONT = "HelveticaNeueLTStd-Hv"
BODY_BOLD_FONT = "GaramondPremrPro-Bd"
CHAPTER_NUMBER_SIZE = 60.0
RUNIN_NUM_RE = re.compile(r"^\d\.\d\s")


def heading_role(r) -> str | None:
    if r.font == TITLE_FONT and r.size >= CHAPTER_NUMBER_SIZE:
        return "chapter_number"
    if r.font == TITLE_FONT and r.size > BODY_FONT_SIZE:
        return "title"
    if r.font == SECTION_FONT and r.size >= BODY_FONT_SIZE - 0.6:
        return "section"
    if r.font == SECTION_FONT:
        return "caption_title"          # 8pt Helvetica = figure/table title, not a heading
    if r.font == BODY_BOLD_FONT and RUNIN_NUM_RE.match(r.text):
        return "runin_subsection"
    return None


def is_bold_span(span) -> bool:
    return bool(span["flags"] & 16) or "bold" in span["font"].lower() or span["font"].endswith("-Bd")


def runin_bold_text(page_number: int, y0: float, x0: float) -> str | None:
    """Bold spans from the matched line onward (same block), stopping at the first regular span."""
    for block in doc[page_number - 1].get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for li, line in enumerate(block["lines"]):
            if abs(line["bbox"][1] - y0) < 0.15 and abs(line["bbox"][0] - x0) < 0.15:
                parts = []
                for next_line in block["lines"][li:]:
                    for span in next_line["spans"]:
                        if not span["text"].strip():
                            continue
                        if not is_bold_span(span):
                            return " ".join("".join(parts).split())
                        parts.append(span["text"])
                    parts.append(" ")
                return " ".join("".join(parts).split())
    return None


# ---- 1) tag candidate lines by role ----
roles = [heading_role(r) for r in retr_body.itertuples()]
cand_lines = retr_body.assign(role=roles).dropna(subset=["role"])

# ---- 2) merge wrapped titles/sections: consecutive lines, same page/block/role/font/size ----
groups = []
for r in cand_lines.itertuples():
    last = groups[-1] if groups else None
    if (r.role in ("title", "section", "caption_title") and last and last["role"] == r.role
            and last["page_number"] == r.page_number and last["block_no"] == r.block_no
            and last["size"] == r.size and last["font"] == r.font):
        last["text"] += " " + r.text
        last["y1"] = r.y1
        last["n_lines"] += 1
        continue

    text = r.text
    if r.role == "runin_subsection":
        text = runin_bold_text(r.page_number, r.y0, r.x0) or r.text

    groups.append({
        "page_number": r.page_number, "block_no": r.block_no, "role": r.role,
        "y0": r.y0, "y1": r.y1, "x0": r.x0,
        "size": r.size, "font": r.font, "n_lines": 1, "text": text,
    })

heading_cand_df = pd.DataFrame(groups)

print(f"Heading candidates: {len(heading_cand_df)}")
print(heading_cand_df["role"].value_counts().to_string())
with pd.option_context("display.max_colwidth", 110, "display.max_rows", None):
    print(heading_cand_df[["page_number", "y0", "x0", "role", "size", "n_lines", "text"]])

# =========================================================
# 3.5 PDF outline, Contents hierarchy (indentation), Chapter 3 "Areas"
# =========================================================

# ---- 1) internal PDF outline (inspected only; plan says it is NOT the source of truth)
outline = doc.get_toc(simple=True)
print(f"PDF outline entries: {len(outline)}")
for level, title, page in outline[:40]:
    print(f"{'  ' * (level - 1)}[{level}] p{page}: {title}")

# ---- 2) Contents section list with x0 (indentation = hierarchy level)
toc_df = lines_df[
    lines_df["page_number"].isin(contents_pages) & (lines_df["zone"] == "body")
].reset_index(drop=True)
fig_start = toc_df.index[toc_df["text"].str.strip().str.lower().str.startswith("figure")]
toc_sections = toc_df.loc[: (fig_start[0] - 1) if len(fig_start) else len(toc_df)]
toc_sections = toc_sections[~toc_sections["text"].str.strip().str.fullmatch(PAGE_NUMBER_RE, case=False)]

print("\nContents entries (page numbers dropped) with indentation:")
with pd.option_context("display.max_rows", None, "display.max_colwidth", 90):
    print(toc_sections[["page_number", "x0", "size", "font", "text"]])

# ---- 3) where are the Chapter 3 "Areas"?
ch3_page = int(heading_cand_df.loc[
    (heading_cand_df["role"] == "title") & heading_cand_df["text"].str.match(r"^3\s"), "page_number"
].iloc[0])
ch3_lines = lines_df[
    lines_df["page_number"].between(ch3_page, NOTES_START - 1) & (lines_df["zone"] == "body")
]
area_df = ch3_lines[
    ch3_lines["text"].str.contains(r"\barea\b", case=False) | (ch3_lines["size"] < BODY_FONT_SIZE - 0.6)
]
print(f"\nChapter 3 (pages {ch3_page}-{NOTES_START - 1}): 'Area' mentions + small-font (diagram) lines:")
with pd.option_context("display.max_rows", None, "display.max_colwidth", 100):
    print(area_df[["page_number", "y0", "x0", "size", "font", "is_bold", "text"]])

# =========================================================
# 3.6 Build section_map
# =========================================================
# Levels: 1 = title (front/chapter), 2 = section (Helvetica Hv 10pt),
#         3 = Chapter 3 "Area N:" (Helvetica Md 9.5pt), 4 = run-in "N.N" subsection.
# Reading order is column-aware: (page, column, y0).

AREA_FONT = "HelveticaNeueLTStd-Md"
AREA_RE = re.compile(r"^Area\s+\d+:", re.IGNORECASE)
BODY_FONT = "GaramondPremrPro"
COLUMN_MIN_OFFSET = 150.0   # right column starts ~198pt after the page's left text margin


def clean_heading(text: str) -> str:
    t = text.replace("\u00ad ", "")                             # soft hyphen + wrap space
    t = "".join(                                                # drop control/format chars (\x08, \u00ad, ZWSP…)
        ch for ch in t
        if ch in "\t\n" or not unicodedata.category(ch).startswith("C")
    )
    return " ".join(unicodedata.normalize("NFKC", t).split()).strip()


# ---- 1) Area headings: merge Helvetica-Md lines per block, keep "Area N:" groups ----
md_groups = (
    retr_body[retr_body["font"] == AREA_FONT]
    .groupby(["page_number", "block_no"])
    .agg(y0=("y0", "min"), x0=("x0", "min"), text=("text", " ".join))
    .reset_index()
)
area_rows = md_groups[md_groups["text"].str.match(AREA_RE)]
other_md = md_groups[~md_groups["text"].str.match(AREA_RE)]

# ---- 2) column detection: left margin of body text per page ----
page_left = retr_body[retr_body["font"] == BODY_FONT].groupby("page_number")["x0"].min()

def column_of(page_number: int, x0: float) -> int:
    return int(x0 >= page_left.get(page_number, 0.0) + COLUMN_MIN_OFFSET)

# ---- 3) assemble headings ----
chapter_no_by_page = (
    heading_cand_df[heading_cand_df["role"] == "chapter_number"]
    .set_index("page_number")["text"].to_dict()
)
LEVEL_BY_ROLE = {"title": 1, "section": 2, "runin_subsection": 4}

rows = []
for r in heading_cand_df[heading_cand_df["role"].isin(LEVEL_BY_ROLE)].itertuples():
    text = clean_heading(r.text)
    if r.role == "title":
        m = re.match(r"^(\d)\s+(.+)$", text)                   # "3 From indicators…"
        chapter_no = m.group(1) if m else chapter_no_by_page.get(r.page_number)
        if m:
            text = m.group(2)
        if chapter_no:
            text = f"Chapter {chapter_no}: {text}"
    elif r.role == "runin_subsection":
        text = text.rstrip(".")
    rows.append({"page_number": r.page_number, "y0": r.y0, "x0": r.x0,
                 "level": LEVEL_BY_ROLE[r.role], "role": r.role, "heading_text": text})

for r in md_groups.itertuples():
    rows.append({"page_number": r.page_number, "y0": r.y0, "x0": r.x0, "level": 3,
                 "role": "area" if AREA_RE.match(r.text) else "minor_heading",
                 "heading_text": clean_heading(r.text)})

section_map = pd.DataFrame(rows)
section_map["column"] = [column_of(p, x) for p, x in zip(section_map["page_number"], section_map["x0"])]
section_map = section_map.sort_values(["page_number", "column", "y0"]).reset_index(drop=True)

# ---- 4) walk in reading order to build the hierarchy path ----
stack, path_rows = {}, []
for r in section_map.itertuples():
    stack = {lvl: txt for lvl, txt in stack.items() if lvl < r.level}
    stack[r.level] = r.heading_text
    path_rows.append({f"l{lvl}": stack.get(lvl) for lvl in range(1, 5)})

section_map = pd.concat([section_map, pd.DataFrame(path_rows)], axis=1)
section_map["heading_norm"] = section_map["heading_text"].str.lower()
section_map["section"] = section_map["l1"]
section_map["subsection"] = section_map[["l2", "l3", "l4"]].apply(
    lambda s: " > ".join(v for v in s if isinstance(v, str)) or None, axis=1
)
section_map.insert(0, "heading_id", [f"h{i:02d}" for i in range(1, len(section_map) + 1)])

print(f"section_map: {len(section_map)} headings")
print(section_map["role"].value_counts().to_string())
print("\nPage left margins used for column detection:")
print(page_left.to_dict())

with pd.option_context("display.max_rows", None, "display.max_colwidth", 80):
    print(section_map[["heading_id", "page_number", "column", "y0", "level", "role",
                         "heading_text", "section", "subsection"]])

# =========================================================
# 3.7 Phase 3 validation
# =========================================================

# ---- A) section_map composition ----
EXPECTED_ROLE_COUNTS = {"title": 6, "section": 12, "area": 3, "minor_heading": 1, "runin_subsection": 9}
role_counts = section_map["role"].value_counts().to_dict()
assert role_counts == EXPECTED_ROLE_COUNTS, f"Role counts changed: {role_counts}"
assert section_map["heading_id"].is_unique
assert section_map["page_number"].isin(RETRIEVAL_PAGES).all(), "Heading found on a non-retrieval page."

# ---- B) every heading is physically at its recorded position ----
def heading_at_position(r) -> bool:
    key = re.sub(r"^Chapter \d: ", "", r.heading_text)[:8].lower()
    same_y = lines_df[(lines_df["page_number"] == r.page_number) & ((lines_df["y0"] - r.y0).abs() < 1.0)]
    return any(key in clean_heading(t).lower() for t in same_y["text"])

misplaced = [r.heading_id for r in section_map.itertuples() if not heading_at_position(r)]
assert not misplaced, f"Headings not found at their position: {misplaced}"

# ---- C) hierarchy sanity ----
assert (section_map["level"].diff().fillna(0) <= 1).all(), "A level was skipped going deeper."
assert section_map.loc[section_map["level"] > 1, "l1"].notna().all(), "Heading without a level-1 parent."

runins = section_map[section_map["role"] == "runin_subsection"]
run_nums = runins["heading_text"].str.extract(r"^(\d\.\d)")[0]
assert sorted(run_nums) == [f"{a}.{b}" for a in (1, 2, 3) for b in (1, 2, 3)], "Run-in numbering incomplete."
area_of_runin = runins["l3"].str.extract(r"^Area (\d+):")[0]
assert (area_of_runin == run_nums.str[0]).all(), "A run-in subsection sits under the wrong Area."

# ---- D) Contents cross-check: every Contents entry exists in section_map ----
SKIP_TOC = {"contents", "acknowledgements", "abbreviations", "notes", "references"}
toc_entries = [
    clean_heading(t) for t in toc_sections["text"]
    if not re.fullmatch(r"Chapter \d", t.strip()) and clean_heading(t).lower() not in SKIP_TOC
]
map_texts = set(section_map["heading_text"].str.replace(r"^Chapter \d: ", "", regex=True).str.lower())
toc_missing = [t for t in toc_entries if t.lower() not in map_texts]
assert not toc_missing, f"Contents entries missing from section_map: {toc_missing}"

# ---- E) confirmed caption inventory ----
assert len(comparison_df) == 12 and (comparison_df["status"] == "ok").all(), "Caption inventory not fully confirmed."
caption_inventory = (
    labels_df.merge(expected_df[["kind", "number", "toc_title"]], on=["kind", "number"])
    [["kind", "number", "page_number", "y0", "toc_title"]]
    .sort_values(["page_number", "y0"])
    .reset_index(drop=True)
)
assert not caption_inventory.duplicated(["kind", "number"]).any(), "Duplicate caption label."
assert caption_inventory["kind"].value_counts().to_dict() == {"figure": 10, "table": 2}

# ---- F) reviewed snapshot (regression guard) — reviewed 2026-09-24 ----
REVIEWED_HEADINGS = [
    (8, 1, "About this report"), (10, 1, "Executive summary"),
    (12, 1, "Chapter 1: Introducing the 2025 LPI 2.0"),
    (12, 2, "Why is logistics important"), (12, 2, "Conceptual framework of the LPI 2.0"),
    (13, 2, "The new indicators"), (13, 2, "Core indicators"),
    (14, 2, "Supplementary indicators"), (15, 3, "Data"),
    (17, 1, "Chapter 2: What the LPI 2.0 reveals"),
    (17, 2, "Connectivity"), (17, 2, "Time"),
    (20, 2, "The special situation of landlocked"), (20, 2, "Assessing supply chain reliability"),
    (22, 2, "Additional insights from supplementary"),
    (24, 1, "Chapter 3: From indicators to policy"),
    (24, 2, "A strategic framework for logistics"),
    (24, 3, "Area 1: Enhancing connectivity"),
    (24, 4, "1.1 Liberalizing markets"), (24, 4, "1.2 Developing hubs"),
    (24, 4, "1.3 Pursuing regional integration"),
    (25, 3, "Area 2: Reducing time and variability"),
    (25, 4, "2.1 Modernizing border management"), (25, 4, "2.2 Improving gateway efficiency"),
    (25, 4, "2.3 Enhancing supply chain traceability"),
    (26, 3, "Area 3: Strengthening the institutional"),
    (26, 4, "3.1 Leveraging public–private"), (26, 4, "3.2 Strengthening competition"),
    (26, 4, "3.3 Enhancing policy consistency"),
    (26, 2, "Using the LPI 2.0 to prioritize"),
    (30, 1, "What are the Logistics Performance"),
]
assert len(section_map) == len(REVIEWED_HEADINGS), "Heading count drifted from snapshot."
drift = [
    (r.heading_id, (r.page_number, r.level, r.heading_text), exp)
    for r, exp in zip(section_map.itertuples(), REVIEWED_HEADINGS)
    if (r.page_number, r.level) != exp[:2] or not r.heading_text.startswith(exp[2])
]
assert not drift, f"section_map drifted from reviewed snapshot: {drift}"

# ---- summary ----
print("✅ Phase 3 validation passed.")
print(f"Headings          : {len(section_map)}  {role_counts}")
print(f"Captions          : {len(caption_inventory)}  (figures=10, tables=2)")
print(f"PAGE_OFFSET       : {PAGE_OFFSET}")
print(f"Header/footer     : y1 <= {HEADER_MAX_Y1} / y0 >= {FOOTER_MIN_Y0}")
print(f"BODY_FONT_SIZE    : {BODY_FONT_SIZE}")


# %% Phase 4 — Structured Extraction
# Goal: convert the confirmed structured elements into semantic units, and record the
# physical region (page + bbox) of each one so body extraction (Phase 6) can exclude them.
#
# - **Tables (1.1, 1.2):** one `table_row` unit per logical row, preserving row and column
#   identity. Bullet-level splitting of Table 1.2 happens later, at chunking (Phase 14).
# - **Figures (2.1–2.10):** each figure goes through a **value gate** before reconstruction:
#   - `full` — deterministic text elements + a curated description reviewed against a render
#     (every number in the description must exist in the extracted text)
#   - `caption_only` — title, source and note only
#   - `skip` — not added to the corpus; the decision and reason are logged
#   
#   The region of every figure is recorded regardless of the gate decision.
# - **Abbreviations (page 7):** one `definitions` unit per abbreviation, so Phase 10 can
#   drop the ones already covered by the Methodology report.
#
# Figure renders are temporary review aids saved to `Notebooks/_scratch/figure_renders/`
# (git-ignored); they are not part of the corpus.
#
# Outputs: `table_units_df`, `figure_units_df`, `definition_units_df`, `structured_regions_df`.

# =========================================================
# 4.1 Table regions: inspect layout around each table (no decisions yet)
# =========================================================

SOURCE_NOTE_RE = re.compile(r"^(sources?|notes?)\s*:", re.IGNORECASE)

table_caps = caption_inventory[caption_inventory["kind"] == "table"]
table_pages = sorted(set(table_caps["page_number"]) | set(table_caps["page_number"] + 1))

# ---- 1) PyMuPDF's built-in table detector: does it see a grid? ----
print("find_tables() results:")
for p in table_pages:
    tabs = doc[p - 1].find_tables()
    print(f"  page {p}: {len(tabs.tables)} table(s)")
    for t in tabs.tables:
        print(f"     bbox={tuple(round(v, 1) for v in t.bbox)} rows={t.row_count} "
              f"cols={t.col_count} header={t.header.names}")

# ---- 2) layout from the first table caption to the end of the last candidate page ----
first_cap = table_caps.iloc[0]
view = lines_df[lines_df["page_number"].isin(table_pages) & (lines_df["zone"] == "body")].copy()
view = view[(view["page_number"] > first_cap["page_number"]) | (view["y0"] >= first_cap["y0"] - 1)]
view["column"] = [column_of(p, x) for p, x in zip(view["page_number"], view["x0"])]
view["flag"] = np.select(
    [view["text"].str.match(LABEL_RE), view["text"].str.match(SOURCE_NOTE_RE)],
    ["CAPTION", "SOURCE/NOTE"], default="",
)
view = view.sort_values(["page_number", "y0", "x0"])

is_prose = (view["font"] == BODY_FONT) & (view["size"] == BODY_FONT_SIZE)

print("\nProse lines (body font) — summarized per page/column:")
print(
    view[is_prose].groupby(["page_number", "column"])
    .agg(lines=("text", "size"), y0_min=("y0", "min"), y1_max=("y1", "max"))
)

print("\nNon-prose lines (tables, captions, headings, source/note):")
with pd.option_context("display.max_rows", None, "display.max_colwidth", 70):
    print(view[~is_prose][["page_number", "y0", "x0", "column", "size", "font", "flag", "text"]])

# =========================================================
# 4.2 Table extraction (find_tables inner grid) + normalization
# =========================================================
# find_tables() returns two tables per page:
#   outer frame (caption + grid + source) -> used as the structured REGION
#   inner grid  (Logistics mode | Connectivity indicators | Time indicators) -> CONTENT
# Each cell is a bullet list: "• Indicator name (units): Definition".

TABLE_HEADER = ["Logistics mode", "Connectivity indicators", "Time indicators"]


def clean_text(text: str) -> str:
    """Remove soft-hyphen line breaks and control/format chars; keep \\t and \\n."""
    t = (text or "").replace("\u00ad\n", "").replace("\u00ad ", "")
    t = "".join(ch for ch in t if ch in "\t\n" or not unicodedata.category(ch).startswith("C"))
    return unicodedata.normalize("NFKC", t)


def norm_ws(text: str) -> str:
    return " ".join(text.split())


def parse_bullets(cell: str) -> list[dict]:
    parts = [norm_ws(p) for p in clean_text(cell).split("•")]
    bullets = []
    for p in (p for p in parts if p):
        m = re.match(r"^(.+?):\s+(.+)$", p)          # split at the FIRST colon
        bullets.append({"indicator": m.group(1) if m else p,
                        "definition": m.group(2) if m else ""})
    return bullets


indicator_records, table_meta_records = [], []

for cap in table_caps.itertuples():
    tabs = doc[cap.page_number - 1].find_tables().tables

    inner = [t for t in tabs if [norm_ws(clean_text(h)) for h in t.header.names] == TABLE_HEADER]
    assert len(inner) == 1, f"Table {cap.number}: expected exactly one inner grid, found {len(inner)}"
    inner = inner[0]
    outer = [t for t in tabs if t is not inner and pymupdf.Rect(t.bbox).contains(pymupdf.Rect(inner.bbox))]
    region = pymupdf.Rect(outer[0].bbox if outer else inner.bbox)

    rows = inner.extract()
    body_rows = rows[1:] if [norm_ws(clean_text(c)) for c in rows[0]] == TABLE_HEADER else rows

    for row in body_rows:
        mode = norm_ws(clean_text(row[0]))
        for col_idx in (1, 2):
            for bullet_no, b in enumerate(parse_bullets(row[col_idx]), start=1):
                indicator_records.append({
                    "table_number": cap.number, "page_number": cap.page_number,
                    "logistics_mode": mode, "column": TABLE_HEADER[col_idx],
                    "bullet_no": bullet_no, **b,
                })

    page_lines = lines_df[lines_df["page_number"] == cap.page_number]
    in_region = page_lines["y0"].between(region.y0, region.y1)
    source_lines = page_lines[in_region & page_lines["text"].str.match(SOURCE_NOTE_RE)]
    title_rows = heading_cand_df[
        (heading_cand_df["role"] == "caption_title")
        & (heading_cand_df["page_number"] == cap.page_number)
        & ((heading_cand_df["y0"] - cap.y0).abs() < 1.0)
    ]

    table_meta_records.append({
        "table_number": cap.number, "page_number": cap.page_number,
        "title": clean_heading(title_rows["text"].iloc[0]) if len(title_rows) else None,
        "source_note": " ".join(clean_heading(t) for t in source_lines["text"]),
        "region_bbox": tuple(round(v, 1) for v in region),
        "outer_found": bool(outer), "n_body_rows": len(body_rows),
    })

indicator_df = pd.DataFrame(indicator_records)
table_meta_df = pd.DataFrame(table_meta_records)

print("Table metadata:")
with pd.option_context("display.max_colwidth", 70):
    print(table_meta_df)

print("\nIndicators per table / mode / column:")
print(indicator_df.groupby(["table_number", "logistics_mode", "column"]).size().rename("n").reset_index())

print("\nAll extracted indicators:")
with pd.option_context("display.max_rows", None, "display.max_colwidth", 75):
    print(indicator_df[["table_number", "logistics_mode", "column", "indicator", "definition"]])

# =========================================================
# 4.3 Table semantic units (one table_row unit per logistics mode)
# =========================================================
# Expected counts are stated in the report itself (p.8):
# "6 core indicators ... and 15 supplementary indicators".

EXPECTED_INDICATORS = {"1.1": 6, "1.2": 15}
EXPECTED_MODES = {"1.1": ["Maritime", "Aviation", "Postal"], "1.2": ["Maritime", "Postal"]}

meta = table_meta_df.set_index("table_number")
caption_y0 = caption_inventory.set_index(["kind", "number"])["y0"]

table_unit_records = []
for (tnum, mode), grp in indicator_df.groupby(["table_number", "logistics_mode"], sort=False):
    m = meta.loc[tnum]
    content_lines = [f"Table {tnum}: {m['title']}", f"Logistics mode: {mode}"]
    for col, col_grp in grp.groupby("column", sort=False):
        content_lines.append(f"{col}:")
        content_lines += [f"- {r.indicator}: {r.definition}" for r in col_grp.itertuples()]

    table_unit_records.append({
        "unit_id": f"table_{tnum}_{mode.lower()}",
        "unit_type": "table_row",
        "page_start": int(m["page_number"]),
        "page_end": int(m["page_number"]),
        "title": f"Table {tnum}: {m['title']} — {mode}",
        "content": "\n".join(content_lines),
        "table_number": tnum,
        "figure_number": None,
        "logistics_mode": mode,
        "indicators": grp[["column", "indicator", "definition"]].to_dict("records"),  # for Phase 14 bullet-level split
        "source_note": m["source_note"],
        "anchor_y0": float(caption_y0[("table", tnum)]),                                   # for Phase 8 section assignment
    })

table_units_df = pd.DataFrame(table_unit_records)

# ---- structured regions (Phase 6 will exclude these from body text) ----
table_regions_df = pd.DataFrame([
    {"region_id": f"region_table_{r.table_number}", "kind": "table", "ref": r.table_number,
     "page_number": r.page_number,
     "x0": r.region_bbox[0], "y0": r.region_bbox[1], "x1": r.region_bbox[2], "y1": r.region_bbox[3]}
    for r in table_meta_df.itertuples()
])

# ---- validation ----
assert indicator_df.groupby("table_number").size().to_dict() == EXPECTED_INDICATORS, "Indicator counts differ from p.8."
assert table_units_df.groupby("table_number", sort=False)["logistics_mode"].apply(list).to_dict() == EXPECTED_MODES
assert indicator_df["indicator"].str.len().gt(0).all() and indicator_df["definition"].str.len().gt(0).all()
assert table_units_df["unit_id"].is_unique

content_by_unit = table_units_df.set_index(["table_number", "logistics_mode"])["content"]
for r in indicator_df.itertuples():
    assert f"- {r.indicator}: {r.definition}" in content_by_unit[(r.table_number, r.logistics_mode)], \
        f"Indicator missing from its unit: {r.indicator}"

has_control = table_units_df["content"].map(
    lambda t: any(unicodedata.category(ch).startswith("C") and ch != "\n" for ch in t)
)
assert not has_control.any(), "Control characters left in table content."

# ---- summary ----
summary = table_units_df.assign(
    n_indicators=table_units_df["indicators"].map(len),
    char_count=table_units_df["content"].str.len(),
)[["unit_id", "title", "n_indicators", "char_count"]]

print("✅ Table units built.")
print(summary)
print(table_regions_df)

print("\nSample unit (table_1.1_maritime):\n")
print(table_units_df.loc[table_units_df["unit_id"] == "table_1.1_maritime", "content"].iloc[0])

# =========================================================
# 4.4 Figure regions, text elements, and retrieval-value signals
# =========================================================
# Region per figure: from its caption down to the end of its Source/Note block,
# using NON-prose lines only (so prose in the other column is never swallowed),
# then widened by vector drawings that sit inside that vertical band.

PROSE_FONTS = {BODY_FONT, BODY_BOLD_FONT, "GaramondPremrPro-It"}
VALUE_RE = re.compile(r"[-–−]?\d[\d,]*(?:\.\d+)?%?")
PANEL_RE = re.compile(r"^[a-h]\.\s+\S")
SOURCE_GAP = 12.0          # max vertical gap inside a Source/Note block
page_w = float(pages_df["page_width"].iloc[0])

def is_heading_line(df: pd.DataFrame) -> pd.Series:
    """Document headings (title / section / area-minor) — never part of a figure."""
    return (
        ((df["font"] == TITLE_FONT) & (df["size"] > BODY_FONT_SIZE))
        | ((df["font"] == SECTION_FONT) & (df["size"] >= BODY_FONT_SIZE - 0.6))
        | ((df["font"] == AREA_FONT) & (df["size"] >= 9.0))
    )

fig_caps = caption_inventory[caption_inventory["kind"] == "figure"].sort_values(["page_number", "y0"])
drawings_cache: dict[int, list] = {}
region_records, element_records = [], []

for cap in fig_caps.itertuples():
    p = cap.page_number
    page_lines = lines_df[(lines_df["page_number"] == p) & (lines_df["zone"] == "body")]
    later = fig_caps[(fig_caps["page_number"] == p) & (fig_caps["y0"] > cap.y0 + 1)]
    y_stop = later["y0"].min() if len(later) else FOOTER_MIN_Y0

    cand = page_lines[
        (page_lines["y0"] >= cap.y0 - 1) & (page_lines["y0"] < y_stop)
        & ~page_lines["font"].isin(PROSE_FONTS)
        & ~is_heading_line(page_lines)
        ].sort_values(["y0", "x0"])

    # ---- end of the figure = end of its Source/Note block ----
    src = cand[cand["text"].map(clean_heading).str.match(SOURCE_NOTE_RE)]
    has_source = len(src) > 0
    if has_source:
        tail = cand[cand["y0"] >= src["y0"].iloc[0]]
        end_y, prev_y1 = tail["y1"].iloc[0], tail["y1"].iloc[0]
        for r in tail.itertuples():
            if r.y0 - prev_y1 > SOURCE_GAP:
                break
            end_y, prev_y1 = max(end_y, r.y1), max(prev_y1, r.y1)
    else:
        end_y = cand["y1"].max()
    reg_lines = cand[cand["y0"] <= end_y]

    # ---- bbox from text, widened by drawings inside the band ----
    x0, x1 = reg_lines["x0"].min(), reg_lines["x1"].max()
    y0, y1 = reg_lines["y0"].min(), end_y
    if p not in drawings_cache:
        drawings_cache[p] = [d["rect"] for d in doc[p - 1].get_drawings()]
    for rect in drawings_cache[p]:
        if (rect.width < 0.95 * page_w and rect.y0 >= y0 - 2 and rect.y1 <= y1 + 2
                and rect.x1 > x0 and rect.x0 < x1):
            x0, x1 = min(x0, rect.x0), max(x1, rect.x1)

    prose_inside = page_lines[
        page_lines["font"].isin(PROSE_FONTS)
        & (page_lines["x1"] > x0) & (page_lines["x0"] < x1)
        & (page_lines["y1"] > y0) & (page_lines["y0"] < y1)
    ]

    region_records.append({
        "region_id": f"region_figure_{cap.number}", "kind": "figure", "ref": cap.number,
        "page_number": p, "x0": round(x0, 1), "y0": round(y0, 1), "x1": round(x1, 1), "y1": round(y1, 1),
        "n_lines": len(reg_lines), "has_source": has_source, "prose_lines_inside": len(prose_inside),
    })

    # ---- classify text elements ----
    current = None
    for r in reg_lines.itertuples():
        t = clean_heading(r.text)
        if LABEL_RE.match(t):
            role = "label"
        elif SOURCE_NOTE_RE.match(t):
            role = current = "note" if t.lower().startswith("note") else "source"
        elif current in ("source", "note"):
            role = current
        elif r.font == SECTION_FONT:
            role = "title"
        elif PANEL_RE.match(t):
            role = "panel_title"
        elif VALUE_RE.fullmatch(t):
            role = "value"
        else:
            role = "text"          # axis titles, legend items, category labels
        element_records.append({"figure_number": cap.number, "page_number": p, "y0": r.y0, "x0": r.x0,
                                "size": r.size, "font": r.font, "role": role, "text": t})

figure_regions_df = pd.DataFrame(region_records)

assert (figure_regions_df["prose_lines_inside"] == 0).all(), \
    f"Prose inside figure regions: {figure_regions_df.loc[figure_regions_df['prose_lines_inside'] > 0, 'ref'].tolist()}"

figure_elements_df = pd.DataFrame(element_records)

# ---- retrieval-value signals ----
prose_text = " ".join(
    clean_heading(t) for t in lines_df.loc[
        lines_df["page_number"].isin(RETRIEVAL_PAGES) & (lines_df["zone"] == "body")
        & lines_df["font"].isin(PROSE_FONTS), "text"
    ]
).lower()

def share_in_prose(items: list[str], numeric: bool) -> float | None:
    if not items:
        return None
    if numeric:
        hits = [bool(re.search(rf"(?<![\d.]){re.escape(v.lower())}(?!\d)", prose_text)) for v in items]
    else:
        hits = [v.lower() in prose_text for v in items]
    return round(sum(hits) / len(items), 2)

signal_rows = []
for fig, els in figure_elements_df.groupby("figure_number", sort=False):
    values = sorted({t for t in els.loc[els["role"] == "value", "text"] if len(re.sub(r"\D", "", t)) >= 2})
    labels = sorted({t for t in els.loc[els["role"] == "text", "text"] if len(t) >= 4})
    title = " ".join(els.loc[els["role"].isin(["label", "title"]), "text"])
    signal_rows.append({
        "figure": fig,
        "title": title[:80],
        "n_panels": int((els["role"] == "panel_title").sum()),
        "n_values": len(values),
        "n_labels": len(labels),
        "value_overlap": share_in_prose(values, numeric=True),
        "label_overlap": share_in_prose(labels, numeric=False),
        "prose_refs": len(re.findall(rf"\bfigure {re.escape(fig)}(?!\d)", prose_text)),
    })
figure_signals_df = pd.DataFrame(signal_rows)

print("Figure regions:")
print(figure_regions_df)

print("\nElement roles per figure:")
print(figure_elements_df.pivot_table(index="figure_number", columns="role", values="text",
                                       aggfunc="count", fill_value=0))

print("\nRetrieval-value signals:")
with pd.option_context("display.max_colwidth", 80):
    print(figure_signals_df)

# =========================================================
# 4.5 (prep) Render figure regions + element dumps for review
# =========================================================
# Temporary review aids for the value gate — NOT part of the corpus.
# Saved under Notebooks/_scratch/ (git-ignored); safe to delete after Phase 4.

REVIEW_DIR = PROJECT_ROOT / "Notebooks" / "_scratch" / "figure_renders"
REVIEW_DIR.mkdir(parents=True, exist_ok=True)

RENDER_ZOOM = 2.5     # ~180 dpi: small 6–7pt chart labels stay readable
PAD = 6               # small margin around the region

for r in figure_regions_df.itertuples():
    page = doc[r.page_number - 1]
    clip = pymupdf.Rect(r.x0 - PAD, r.y0 - PAD, r.x1 + PAD, r.y1 + PAD).intersect(page.rect)
    page.get_pixmap(matrix=pymupdf.Matrix(RENDER_ZOOM, RENDER_ZOOM), clip=clip) \
        .save(REVIEW_DIR / f"figure_{r.ref}.png")

    els = figure_elements_df[figure_elements_df["figure_number"] == r.ref]
    (REVIEW_DIR / f"figure_{r.ref}_elements.txt").write_text(
        "\n".join(f"{e.role:12}| y={e.y0:6.1f} x={e.x0:6.1f} | {e.text}" for e in els.itertuples()),
        encoding="utf-8",
    )

saved = sorted(p.name for p in REVIEW_DIR.iterdir())
print(f"Saved {len(saved)} files to {REVIEW_DIR.relative_to(PROJECT_ROOT)}:")
for name in saved:
    print("  ", name)

# =========================================================
# 4.5a Figure 2.10 — does the plotted data support its title?
# =========================================================
# The title says business-to-business (B2B) postal delivery times are LONGER than
# business-to-consumer (B2C); the prose on p.23 says the opposite. The scatter decides it:
# x = B2B median, y = B2C median (both log scales), black 45-degree line.
# A marker ABOVE the line means B2C is longer. Markers are vector drawings, so they are
# read from page.get_drawings(); axis positions come from the tick labels "1", "10", "100".

r210 = figure_regions_df.set_index("ref").loc["2.10"]
p210 = int(r210["page_number"])
in_fig = lines_df[(lines_df["page_number"] == p210)
                  & lines_df["x0"].between(r210["x0"] - 5, r210["x1"]) & lines_df["y0"].between(r210["y0"], r210["y1"])]

ticks = in_fig[in_fig["text"].isin(["1", "10", "100"])].copy()
ticks["xc"], ticks["yc"] = (ticks["x0"] + ticks["x1"]) / 2, (ticks["y0"] + ticks["y1"]) / 2
ticks["log_v"] = np.log10(ticks["text"].astype(int))
x_ticks = ticks[ticks["y0"] >= ticks["y0"].max() - 1]          # bottom row = x axis
y_ticks = ticks[ticks["y0"] < ticks["y0"].max() - 1]           # left column = y axis
assert len(x_ticks) == 3 and len(y_ticks) == 3, "Axis ticks not found."
bx, ax_ = np.polyfit(x_ticks["xc"], x_ticks["log_v"], 1)       # log10(B2B) = ax_ + bx * x
by, ay_ = np.polyfit(y_ticks["yc"], y_ticks["log_v"], 1)       # log10(B2C) = ay_ + by * y

legend = in_fig[in_fig["text"].isin(["High income", "Upper middle income", "Lower middle income", "Low income"])]
lx0, lx1 = legend["x0"].min() - 12, legend["x1"].max()
ly0, ly1 = legend["y0"].min() - 2, legend["y1"].max() + 2

centers = set()
for d in doc[p210 - 1].get_drawings():
    rect = d["rect"]
    if d.get("fill") is None or rect.width > 5 or rect.height > 5:
        continue
    cx, cy = (rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2
    inside = r210["x0"] < cx < r210["x1"] and r210["y0"] < cy < r210["y1"]
    in_legend = lx0 < cx < lx1 and ly0 < cy < ly1
    if inside and not in_legend:
        centers.add((round(cx * 2) / 2, round(cy * 2) / 2))

diff = np.array([(ay_ + by * cy) - (ax_ + bx * cx) for cx, cy in centers])   # log10(B2C) - log10(B2B)
FIG_2_10_EVIDENCE = {
    "markers": len(centers),
    "b2c_longer": int((diff > 0.02).sum()),
    "b2b_longer": int((diff < -0.02).sum()),
    "on_line": int((abs(diff) <= 0.02).sum()),
}
print("Figure 2.10 plotted data:", FIG_2_10_EVIDENCE, "(N = 173 printed; overlapping markers merge)")
assert FIG_2_10_EVIDENCE["markers"] >= 150, "Could not read the scatter markers."
assert FIG_2_10_EVIDENCE["b2c_longer"] > FIG_2_10_EVIDENCE["b2b_longer"], \
    "Evidence changed: re-review the Figure 2.10 decision."
print("-> The plotted data agree with the prose on p.23 (B2C longer), not with the figure title.")

# =========================================================
# 4.5 Figure value gate — reviewed decisions (2026-09-25)
# =========================================================
# Decided after reviewing renders + extracted elements + the chapter prose.
# Key finding: chart data values are vector graphics, not text. Extracted "values"
# are mostly axis ticks. The only data-bearing printed numbers are pie shares (2.3),
# regression fits / R² / N (2.2, 2.3, 2.7) and figure notes.
# Therefore "full" = qualitative description + printed numbers only (no visual estimates).

GATE_LEVELS = {"full", "caption_only", "skip"}

FIGURE_VALUE_DECISIONS = {
    "2.1":  {"decision": "full",
             "reason": "Prose gives only a general regional pattern ('depending on the mode'); the figure "
                       "shows the per-mode ranking (e.g. North America first in maritime and postal, "
                       "South Asia second in maritime) plus printed group sizes (n)."},
    "2.2":  {"decision": "full",
             "reason": "Printed R² (0.5 maritime, 0.67 postal) and the market-access definition in the note "
                       "(Harris 1954) are not in the prose."},
    "2.3":  {"decision": "full",
             "reason": "Printed shares by number of transshipments (51/37/11/2%) and the fitted line "
                       "(y = 17.75x + 21.73, R² = 0.459); prose only says 'about half'."},
    "2.4":  {"decision": "skip",
             "reason": "Fully covered by prose (dwell > two weeks, SSA/MENA, aviation about half); "
                       "no printed data values."},
    "2.5":  {"decision": "full",
             "reason": "Country-level pattern for 23 LLDCs is not in the prose (Niger and Mongolia longest; "
                       "port dwell dominates Mongolia, corridor time dominates Niger); note lists LLDCs without data."},
    "2.6":  {"decision": "caption_only",
             "reason": "Title states the finding; the note carries unique facts (Hamburg–Santos route, "
                       "3,806 voyages, 168 transshipped via Morocco, the Netherlands or Spain)."},
    "2.7":  {"decision": "full",
             "reason": "Printed slopes (imports y = 1.21x, N = 154; exports y = 0.89x, N = 149); "
                       "prose gives only the derived '36 percent higher'."},
    "2.8":  {"decision": "full",
             "reason": "Percentiles are already in prose (p.21), but the figure adds a distribution shape "
                       "not stated anywhere: a large mass at the 50+ day mark for Apapa and Algiers."},
    "2.9":  {"decision": "skip",
             "reason": "Fully covered by prose (turnaround < 2 days vs 2–6 days; turnaround shorter than "
                       "dwell time); no printed data values."},
    "2.10": {"decision": "skip",
             "reason": "The title contradicts both the prose (p.23) and the figure's own plotted data "
                       f"(4.5a: {FIG_2_10_EVIDENCE['b2c_longer']} economies above the 45-degree line = B2C longer, "
                       f"{FIG_2_10_EVIDENCE['b2b_longer']} below). Keeping the unit would put a misleading statement "
                       "in the corpus; the correct finding is already in the p.23 prose."},
}

figure_gate_df = (
    pd.DataFrame.from_dict(FIGURE_VALUE_DECISIONS, orient="index")
    .rename_axis("figure_number").reset_index()
    .merge(caption_inventory.loc[caption_inventory["kind"] == "figure", ["number", "page_number"]]
           .rename(columns={"number": "figure_number"}), on="figure_number", how="left")
)
if "flag" not in figure_gate_df:
    figure_gate_df["flag"] = None

# ---- validation ----
expected_figs = set(caption_inventory.loc[caption_inventory["kind"] == "figure", "number"])
assert set(FIGURE_VALUE_DECISIONS) == expected_figs, "Every confirmed figure needs exactly one gate decision."
assert figure_gate_df["decision"].isin(GATE_LEVELS).all(), "Unknown gate decision."
assert figure_gate_df["reason"].str.len().gt(20).all(), "Every decision needs a real reason."
assert set(figure_regions_df["ref"]) == expected_figs, "Every figure (including 'skip') must keep its region."

print("✅ Value gate recorded.")
print(figure_gate_df["decision"].value_counts().to_string())
with pd.option_context("display.max_colwidth", 110):
    print(figure_gate_df[["figure_number", "page_number", "decision", "flag", "reason"]])

# =========================================================
# 4.6 Figure reconstruction (units for 'full' and 'caption_only')
# =========================================================
# Unit content = title + panel titles + [curated description] + note + source.
# Curated descriptions were written from the renders and may only contain numbers
# that appear in the figure's own extracted text (validated below).
# Provenance: reviewed against renders on 2026-09-25.

FIGURE_DESCRIPTIONS = {
    "2.1": (
        "Six bar-chart panels compare the average number of direct partner economies in 2023 and 2024. "
        "Panels a–c group economies by region (maritime, aviation, business-to-business postal); panels d–f "
        "group them by income group. By region, North America has the highest average in maritime and postal "
        "connectivity, with South Asia second in maritime; in aviation, North America and Europe & Central Asia "
        "are close at the top, with East Asia & Pacific just behind. Sub-Saharan Africa and Latin America & "
        "Caribbean are the lowest regions in all three modes. By income group, connectivity rises steadily from "
        "low-income to high-income economies in all three modes. Between 2023 and 2024 most groups changed only "
        "slightly; the largest visible gain is aviation connectivity in Latin America & Caribbean, while South "
        "Asia's maritime connectivity declined. Group sizes: East Asia & Pacific (n = 29), Europe & Central Asia "
        "(n = 51), Latin America & Caribbean (n = 38), Middle East, North Africa, Afghanistan & Pakistan (n = 20), "
        "North America (n = 3), South Asia (n = 6), Sub-Saharan Africa (n = 40); low income (n = 17), middle "
        "income (n = 44), upper middle income (n = 49), high income (n = 75)."
    ),
    "2.2": (
        "Two scatter panels plot, for 2024, each economy's number of direct partner economies against its market "
        "access. Panel a (maritime partner economies) shows a positive correlation with R² = 0.5; panel b "
        "(business-to-business postal partner economies) shows a stronger positive correlation with R² = 0.67. "
        "Economies with lower market access are more remote from economic opportunities and tend to have fewer "
        "direct partners."
    ),
    "2.3": (
        "Panel a is a pie chart of container shipments in 2024 by number of transshipments: 0 transshipments 51%, "
        "1 transshipment 37%, 2 transshipments 11%, and 3 or more 2%. Panel b plots each economy's mean maritime "
        "lead time (days) against its mean number of transshipments; the fitted line y = 17.75x + 21.73 "
        "(R² = 0.459) implies about 17.75 additional days of lead time per additional transshipment."
    ),
    "2.5": (
        "Stacked bars show 2024 container import time (days) for landlocked developing countries, split into three "
        "components: dwell time at the port of arrival, corridor lead time from port exit to destination, and dwell "
        "time at destination. Niger and Mongolia have by far the longest total import times; Mongolia's total is "
        "dominated by dwell time at the port of arrival, whereas Niger's is dominated by corridor lead time. The "
        "Central African Republic and Chad follow, with sizable port-of-arrival dwell times. Armenia and Azerbaijan "
        "have the shortest totals. The mix of components varies widely: in Kazakhstan, the Kyrgyz Republic, South "
        "Sudan, Tajikistan and Uzbekistan most of the time is corridor lead time, while in Zimbabwe, Chad and "
        "Burkina Faso dwell time at destination is also substantial."
    ),
    "2.7": (
        "A scatter of economies' interquartile range of dwell time (days) against median dwell time (days) for "
        "2024, shown separately for import and export dwell time. Lines fitted through the origin show dispersion "
        "rising with the median: y = 1.21x for imports (N = 154) and y = 0.89x for exports (N = 149). At the same "
        "median dwell time, import dwell times are therefore more dispersed, and less predictable, than export "
        "dwell times."
    ),
    "2.8": (
        "Three histograms show the 2024 distribution of container import dwell time (days) at the port of Le Havre "
        "(France), the port of Apapa (Nigeria) and the port of Algiers (Algeria). At Le Havre most containers leave "
        "within the first few days and the distribution drops off sharply, with almost no containers beyond about "
        "20 days. At Apapa and Algiers the distributions peak much later and have long right tails, and both show a "
        "large spike at the 50-day mark, which aggregates all containers that stayed 50 days or more, indicating a "
        "substantial number of containers with extremely long dwell times at these two ports. The number of "
        "observations differs by port (frequency axes reach 20,000 for Le Havre, 1,500 for Apapa and 5,000 for "
        "Algiers)."
    ),
}

NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
PANEL_CONT_DY = (5.0, 10.0)   # panel-title continuation line sits 5–10pt below
PANEL_CONT_DX = 35.0


def numbers_in(text: str) -> set[str]:
    return {n.rstrip(",.") for n in NUMBER_RE.findall(text)}


def assemble_panels(els: pd.DataFrame) -> list[str]:
    panels = els[els["role"] == "panel_title"]
    texts = els[els["role"] == "text"]
    out = []
    for p in panels.itertuples():
        cont = texts[
            texts["y0"].sub(p.y0).between(*PANEL_CONT_DY)
            & texts["x0"].sub(p.x0).abs().le(PANEL_CONT_DX)
        ]
        if len(cont):
            nearest = cont.iloc[(cont["x0"] - p.x0).abs().argmin()]
            out.append(f"{p.text} {nearest['text']}")
        else:
            out.append(p.text)
    return out


figure_unit_records = []
for g in figure_gate_df.itertuples():
    if g.decision == "skip":
        continue
    num = g.figure_number
    els = figure_elements_df[figure_elements_df["figure_number"] == num].sort_values(["y0", "x0"])

    label_text = els.loc[els["role"] == "label", "text"].iloc[0]
    label_rest = label_text[LABEL_RE.match(label_text).end():].strip()      # 2.10: title starts on label line
    title = " ".join([label_rest] * bool(label_rest) + els.loc[els["role"] == "title", "text"].tolist())

    panels = assemble_panels(els)
    note = " ".join(els.loc[els["role"] == "note", "text"])
    source = " ".join(els.loc[els["role"] == "source", "text"])
    description = FIGURE_DESCRIPTIONS.get(num) if g.decision == "full" else None

    # printed sample sizes ("N = 173") are data, not axis ticks — keep them for caption_only units
    sample_sizes = [t for t in els.loc[els["role"] == "text", "text"] if re.fullmatch(r"N\s*=\s*[\d,]+", t)]

    parts = [f"Figure {num}: {title}"]
    if panels:
        parts.append("Panels: " + "; ".join(panels))
    if description:
        parts.append(description)
    if g.decision == "caption_only" and sample_sizes:
        parts.append(" ".join(sample_sizes) + ".")
    if note:
        parts.append(note)
    if source:
        parts.append(source)

    figure_unit_records.append({
        "unit_id": f"figure_{num}",
        "unit_type": "figure",
        "page_start": int(g.page_number), "page_end": int(g.page_number),
        "title": f"Figure {num}: {title}",
        "content": "\n".join(parts),
        "table_number": None,
        "figure_number": num,
        "gate_decision": g.decision,
        "description_provenance": "curated_from_render" if description else None,
        "flag": g.flag if isinstance(g.flag, str) else None,
        "anchor_y0": float(els.loc[els["role"] == "label", "y0"].iloc[0]),
    })

figure_units_df = pd.DataFrame(figure_unit_records)

# ---- validation ----
full_figs = set(figure_gate_df.loc[figure_gate_df["decision"] == "full", "figure_number"])
kept_figs = set(figure_gate_df.loc[figure_gate_df["decision"] != "skip", "figure_number"])

assert set(FIGURE_DESCRIPTIONS) == full_figs, "Descriptions must exist for exactly the 'full' figures."
assert set(figure_units_df["figure_number"]) == kept_figs, "Skipped figures must not produce units."
assert figure_units_df["unit_id"].is_unique

for num, desc in FIGURE_DESCRIPTIONS.items():
    fig_text = " ".join(figure_elements_df.loc[figure_elements_df["figure_number"] == num, "text"])
    unsupported = numbers_in(desc) - numbers_in(fig_text)
    assert not unsupported, f"Figure {num}: description numbers not found in extracted text: {unsupported}"

signal_panels = figure_signals_df.set_index("figure")["n_panels"]
for r in figure_units_df.itertuples():
    n_listed = r.content.split("\n")[1].count(";") + 1 if "\nPanels: " in r.content else 0
    assert n_listed == signal_panels[r.figure_number], f"Figure {r.figure_number}: panel count mismatch."

assert not figure_units_df["content"].map(
    lambda t: any(unicodedata.category(ch).startswith("C") and ch != "\n" for ch in t)
).any(), "Control characters in figure content."

for r in figure_units_df[figure_units_df["gate_decision"] == "caption_only"].itertuples():
    els = figure_elements_df[figure_elements_df["figure_number"] == r.figure_number]
    for t in els.loc[els["role"] == "text", "text"]:
        if re.fullmatch(r"N\s*=\s*[\d,]+", t):
            assert t in r.content, f"Figure {r.figure_number}: printed sample size '{t}' missing."

print("✅ Figure units built.")
print(figure_units_df.assign(char_count=figure_units_df["content"].str.len())
        [["unit_id", "gate_decision", "description_provenance", "flag", "char_count"]])

for r in figure_units_df.itertuples():
    print("\n" + "=" * 100)
    print(r.content)

# =========================================================
# 4.7 Abbreviations (page 7) -> one `definitions` unit per abbreviation
# =========================================================
# Layout: two columns — term (left) and expansion (right), one row per abbreviation.
# The "Abbreviations" heading is the LAST line of the page (observed in Phase 2).

ABBR_PAGE = int(page_class_df.loc[page_class_df["page_class"] == "abbreviations", "page_number"].iloc[0])
TERM_COL_WIDTH = 20.0

al = lines_df[(lines_df["page_number"] == ABBR_PAGE) & (lines_df["zone"] == "body")].copy()
al["text_c"] = al["text"].map(clean_heading)
al = al[
    ~al["text_c"].str.lower().eq("abbreviations")
    & ~al["text_c"].str.fullmatch(PAGE_NUMBER_RE, case=False)
].sort_values(["y0", "x0"])

term_x = al["x0"].min()
terms = al[al["x0"] < term_x + TERM_COL_WIDTH].reset_index(drop=True)
defs = al[al["x0"] >= term_x + TERM_COL_WIDTH]

definition_unit_records = []
for i, t in terms.iterrows():
    next_y = terms.loc[i + 1, "y0"] if i + 1 < len(terms) else np.inf
    expansion = " ".join(defs.loc[defs["y0"].between(t["y0"] - 2, next_y - 2, inclusive="left"), "text_c"])
    slug = re.sub(r"[^a-z0-9]+", "_", t["text_c"].lower()).strip("_")
    definition_unit_records.append({
        "unit_id": f"abbr_{slug}",
        "unit_type": "definitions",
        "page_start": ABBR_PAGE, "page_end": ABBR_PAGE,
        "title": f"Abbreviation: {t['text_c']}",
        "content": f"{t['text_c']}: {expansion}",
        "term": t["text_c"],
        "expansion": expansion,
        "table_number": None, "figure_number": None,
        "anchor_y0": float(t["y0"]),
    })

definition_units_df = pd.DataFrame(definition_unit_records)

# ---- validation (reviewed snapshot: page 7 lists 7 abbreviations) ----
EXPECTED_TERMS = ["B2B", "B2C", "LLDC", "LPI", "LPI 2.0", "PPP", "SMEs"]
assert definition_units_df["term"].tolist() == EXPECTED_TERMS, f"Terms drifted: {definition_units_df['term'].tolist()}"
assert definition_units_df["expansion"].str.len().gt(0).all(), "Abbreviation without expansion."
assert definition_units_df["unit_id"].is_unique
assert len(defs) == len(definition_units_df), "Some expansion lines were not attached to a term."

print("✅ Definition units built.")
with pd.option_context("display.max_colwidth", 90):
    print(definition_units_df[["unit_id", "term", "expansion", "content"]])

# =========================================================
# 4.8 Phase 4 QA — structured units + structured regions
# =========================================================

structured_units_df = pd.concat([table_units_df, figure_units_df, definition_units_df], ignore_index=True)
structured_regions_df = pd.concat(
    [table_regions_df, figure_regions_df[table_regions_df.columns]], ignore_index=True
)
page_h = float(pages_df["page_height"].iloc[0])

# ---- A) units ----
assert structured_units_df["unit_id"].is_unique, "Duplicate unit_id across structured units."
assert structured_units_df["content"].str.strip().ne("").all(), "Empty structured unit."
assert structured_units_df["unit_type"].value_counts().to_dict() == {"definitions": 7, "figure": 7, "table_row": 5}
assert not structured_units_df["content"].map(
    lambda t: any(unicodedata.category(ch).startswith("C") and ch != "\n" for ch in t)
).any(), "Control characters in structured content."

# ---- B) regions: every confirmed caption has exactly one region (incl. skipped figures) ----
cap_keys = set(zip(caption_inventory["kind"], caption_inventory["number"]))
reg_keys = list(zip(structured_regions_df["kind"], structured_regions_df["ref"]))
assert len(reg_keys) == len(set(reg_keys)), "A caption has more than one region."
assert set(reg_keys) == cap_keys, "Region set does not match the caption inventory."

assert (
    (structured_regions_df["x0"] >= 0) & (structured_regions_df["x1"] <= page_w)
    & (structured_regions_df["y0"] >= 0) & (structured_regions_df["y1"] <= page_h)
).all(), "Region outside the page."
assert structured_regions_df["page_number"].isin(RETRIEVAL_PAGES).all()

# ---- C) no prose inside any region (tables AND figures) ----
def prose_in_region(r) -> int:
    pl = lines_df[(lines_df["page_number"] == r.page_number) & lines_df["font"].isin(PROSE_FONTS)]
    return int(((pl["x1"] > r.x0) & (pl["x0"] < r.x1) & (pl["y1"] > r.y0) & (pl["y0"] < r.y1)).sum())

leaks = {r.region_id: n for r in structured_regions_df.itertuples() if (n := prose_in_region(r))}
assert not leaks, f"Prose lines inside structured regions: {leaks}"

# ---- D) regions on the same page must not overlap ----
for p, grp in structured_regions_df.groupby("page_number"):
    rects = [(r.region_id, pymupdf.Rect(r.x0, r.y0, r.x1, r.y1)) for r in grp.itertuples()]
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            assert not rects[i][1].intersects(rects[j][1]), f"Overlap on p{p}: {rects[i][0]} / {rects[j][0]}"

# ---- E) gate consistency + flags ----
skipped = set(figure_gate_df.loc[figure_gate_df["decision"] == "skip", "figure_number"])
assert not skipped & set(figure_units_df["figure_number"]), "A skipped figure produced a unit."
assert figure_units_df["flag"].isna().all(), "No figure unit may remain flagged."
assert figure_units_df.loc[figure_units_df["gate_decision"] == "full", "description_provenance"].notna().all()

# ---- F) reviewed snapshot (regression guard) — reviewed 2026-09-25 ----
REVIEWED_UNIT_IDS = [
    "table_1.1_maritime", "table_1.1_aviation", "table_1.1_postal", "table_1.2_maritime", "table_1.2_postal",
    "figure_2.1", "figure_2.2", "figure_2.3", "figure_2.5", "figure_2.6", "figure_2.7", "figure_2.8",
    "abbr_b2b", "abbr_b2c", "abbr_lldc", "abbr_lpi", "abbr_lpi_2_0", "abbr_ppp", "abbr_smes",
]
assert structured_units_df["unit_id"].tolist() == REVIEWED_UNIT_IDS, "Structured units drifted from snapshot."

# ---- summary ----
print("✅ Phase 4 validation passed.")
print("Structured units :", len(structured_units_df), structured_units_df["unit_type"].value_counts().to_dict())
print("Regions          :", len(structured_regions_df), structured_regions_df["kind"].value_counts().to_dict())
print("Figure gate      :", figure_gate_df["decision"].value_counts().to_dict())
print(structured_units_df.assign(char_count=structured_units_df["content"].str.len())
        .groupby("unit_type")["char_count"].describe()[["count", "min", "mean", "max"]])


# %% Phase 5 — Notes / Endnotes
# The report uses **endnotes** (a single Notes page) rather than page-local footnotes.
#
# - **5.1** Build the note registry (`note_no → text`) from the Notes page.
# - **5.2** Detect inline note markers in body prose at **span level**: a marker is a
#   digits-only span that is clearly smaller than body text (superscript), so ordinary
#   numbers, years and decimals in prose are never mistaken for markers.
# - **5.3** Auto-suggest a policy per note: `informative` (text will be appended to its
#   paragraph as `Note: …` in Phase 9) or `citation_only` (kept as metadata only).
# - **5.4** Manual review of all notes; corrections recorded in `NOTE_POLICY_OVERRIDES` with reasons.
# - **5.5** Validation: every note has one policy, every marker resolves, every note is referenced.
#
# Figure-level "Note:" lines are not endnotes; they were handled in Phase 4.

# =========================================================
# 5.1 Note registry from the Notes page
# =========================================================
# A note starts at a line holding ONLY its number (e.g. "31"), or "N text" on one line.
# A number line is accepted as a note start only if it is the NEXT expected number,
# so stray numbers inside note text can never open a new note.

NOTES_PAGE = NOTES_START

nl = lines_df[(lines_df["page_number"] == NOTES_PAGE) & (lines_df["zone"] == "body")].copy()
nl["text_c"] = nl["text"].map(clean_heading)
nl = nl[~nl["text_c"].str.lower().eq("notes")]

notes_left = nl["x0"].min()                                   # page 28 is not a retrieval page,
nl["column"] = (nl["x0"] >= notes_left + COLUMN_MIN_OFFSET).astype(int)   # so compute its own margin
nl = nl.sort_values(["column", "y0", "x0"])

note_records, orphans, current = [], [], None
for r in nl.itertuples():
    expected = current["note_no"] + 1 if current else 1
    m = re.fullmatch(r"(\d{1,2})(?:\s+(.*))?", r.text_c)
    if m and int(m.group(1)) == expected:
        current = {"note_no": expected, "column": r.column, "y0": r.y0, "raw_lines": []}
        if m.group(2):
            current["raw_lines"].append(m.group(2))
        note_records.append(current)
    elif current is None:
        orphans.append(r.text_c)
    else:
        current["raw_lines"].append(r.text)

for rec in note_records:
    rec["text"] = norm_ws(clean_text("\n".join(rec.pop("raw_lines"))).replace("\n", " "))

note_registry_df = pd.DataFrame(note_records)
note_registry_df["char_count"] = note_registry_df["text"].str.len()
note_text_map = dict(zip(note_registry_df["note_no"], note_registry_df["text"]))

# ---- validation ----
assert not orphans, f"Text found before note 1: {orphans[:5]}"
assert note_registry_df["note_no"].tolist() == list(range(1, len(note_registry_df) + 1)), "Note numbering gap."
assert len(note_registry_df) == 33, f"Expected 33 notes (last seen on p.28 is 33), got {len(note_registry_df)}"
assert note_registry_df["text"].str.len().gt(0).all(), "Empty note text."

print(f"✅ Note registry: {len(note_registry_df)} notes | columns on page: {sorted(nl['column'].unique())}")
with pd.option_context("display.max_rows", None, "display.max_colwidth", 110):
    print(note_registry_df[["note_no", "column", "char_count", "text"]])

# =========================================================
# 5.2 Note markers in body prose (span level)
# =========================================================
# A marker = digits-only span (optionally "13, 15" or "13–15") inside a PROSE line,
# that is superscript (flag bit 1) or clearly smaller than body text.
# Ordinary numbers in prose are body-size, so they are never matched.
# Structured regions are excluded. We scan every page BEFORE the Notes page
# (not only retrieval pages) so that no reference is silently missed.

MARKER_MAX_SIZE = BODY_FONT_SIZE * 0.8
MARKER_RE = re.compile(r"\d{1,2}(?:\s*[,–-]\s*\d{1,2})*")


def expand_marker(text: str) -> list[int]:
    nums = []
    for part in re.split(r"\s*,\s*", text):
        m = re.fullmatch(r"(\d{1,2})\s*[–-]\s*(\d{1,2})", part)
        nums += list(range(int(m.group(1)), int(m.group(2)) + 1)) if m else [int(part)]
    return nums


def in_structured_region(p: int, x0: float, y0: float, x1: float, y1: float) -> bool:
    rg = structured_regions_df[structured_regions_df["page_number"] == p]
    return bool(((rg["x0"] < x1) & (rg["x1"] > x0) & (rg["y0"] < y1) & (rg["y1"] > y0)).any())


page_class_of = page_class_df.set_index("page_number")["page_class"]
ref_records = []

for p in range(1, NOTES_START):
    for block in doc[p - 1].get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            spans = [s for s in line["spans"] if s["text"].strip()]
            if not spans:
                continue
            main = max(spans, key=lambda s: len(s["text"].strip()))
            if main["font"] not in PROSE_FONTS:
                continue
            for i, s in enumerate(spans):
                t = s["text"].strip()
                if not MARKER_RE.fullmatch(t):
                    continue
                if not (s["size"] <= MARKER_MAX_SIZE or s["flags"] & 1):
                    continue
                x0, y0, x1, y1 = s["bbox"]
                if in_structured_region(p, x0, y0, x1, y1):
                    continue
                ref_records.append({
                    "page_number": p,
                    "page_class": page_class_of[p],
                    "column": column_of(p, line["bbox"][0]),   # column of the LINE, not of the marker span
                    "y0": round(y0, 1), "x0": round(x0, 1),
                    "size": round(s["size"], 1),
                    "marker": t,
                    "note_nos": expand_marker(t),
                    "context": clean_heading(spans[i - 1]["text"])[-45:] if i > 0 else "(line start)",
                })

note_refs_df = pd.DataFrame(ref_records).sort_values(["page_number", "column", "y0", "x0"]).reset_index(drop=True)

# ---- diagnostics (hard checks come in 5.5) ----
all_refs = [n for nums in note_refs_df["note_nos"] for n in nums]
referenced = set(all_refs)
known = set(note_registry_df["note_no"])
first_seen = list(dict.fromkeys(all_refs))            # first occurrence, in reading order

print(f"Markers found        : {len(note_refs_df)}  (note references: {len(all_refs)})")
print(f"Marker sizes (pt)    : {sorted(note_refs_df['size'].unique())}")
print(f"Pages with markers   : {sorted(note_refs_df['page_number'].unique())}")
print(f"Non-retrieval pages  : {sorted(note_refs_df.loc[~note_refs_df['page_number'].isin(RETRIEVAL_PAGES), 'page_number'].unique())}")
print(f"Unknown note numbers : {sorted(referenced - known)}")
print(f"Never referenced     : {sorted(known - referenced)}")
print(f"Referenced >1 time   : {sorted(n for n in referenced if all_refs.count(n) > 1)}")
print(f"First-seen order ok  : {first_seen == sorted(first_seen)}")
if first_seen != sorted(first_seen):
    print("  first-seen order   :", first_seen)

with pd.option_context("display.max_rows", None, "display.max_colwidth", 60):
    print(note_refs_df[["page_number", "page_class", "column", "y0", "size", "marker", "context"]])

# =========================================================
# 5.3 Auto-suggested note policy (reviewed manually in 5.4)
# =========================================================
# citation_only : the note only points to a source (references, "see …", "According to …")
# informative   : the note adds explanatory content (it will be appended as "Note: …" in Phase 9)
# Rules are applied in order; the first match wins.

CITATION = r"[A-Z][A-Za-z’'\-\s,&]*?(?:\set al\.)?\s\d{4}[a-z]?"
PURE_CITATION_RE = re.compile(rf"^{CITATION}(?:;\s*{CITATION})*\.$")                    # "Arvis et al. 2013."
LEADING_CITATION_RE = re.compile(rf"^{CITATION}(?:;\s*{CITATION})*\.\s+\S")              # "Hummels 2001. Manufactures …"
ATTRIBUTION_RE = re.compile(r"^According to [^.]+\.$")                                   # "According to the UPU."
POINTER_RE = re.compile(r"^(?:See\s|For\s.+?,\s*see\s)", re.IGNORECASE)                  # "See …" / "For …, see …"
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def n_sentences(text: str) -> int:
    return len([s for s in SENTENCE_SPLIT_RE.split(text) if s.strip()])


def suggest_policy(text: str) -> tuple[str, str, str]:
    if PURE_CITATION_RE.match(text):
        return "citation_only", "pure_citation", "Only bibliographic reference(s)."
    if ATTRIBUTION_RE.match(text):
        return "citation_only", "attribution", "Only attributes a source ('According to …')."
    if POINTER_RE.match(text) and n_sentences(text) == 1:
        return "citation_only", "pointer", "Single-sentence pointer to a source or URL."
    if LEADING_CITATION_RE.match(text):
        return "informative", "citation_plus_text", "Reference followed by explanatory text."
    return "informative", "explanatory", "Adds explanatory content."


suggestions = note_registry_df["text"].map(suggest_policy)
note_registry_df["suggested_policy"] = suggestions.str[0]
note_registry_df["rule"] = suggestions.str[1]
note_registry_df["suggested_reason"] = suggestions.str[2]
note_registry_df["n_sentences"] = note_registry_df["text"].map(n_sentences)

print(note_registry_df["suggested_policy"].value_counts().to_string())
print()
print(note_registry_df.groupby(["suggested_policy", "rule"]).size().to_string())

with pd.option_context("display.max_rows", None, "display.max_colwidth", None):
    print(note_registry_df[["note_no", "suggested_policy", "rule", "n_sentences", "char_count", "text"]])

# =========================================================
# 5.4 Manual note review (reviewed 2026-09-25)
# =========================================================
# All 33 auto-suggestions were reviewed against the full note text and found correct.
# NOTE_POLICY_OVERRIDES records any change; NOTE_REVIEW_COMMENTS documents borderline
# notes that were deliberately kept as suggested.

NOTE_POLICIES = {"informative", "citation_only"}

NOTE_POLICY_OVERRIDES: dict[int, dict] = {
    # example: 24: {"policy": "citation_only", "reason": "Data-sharing meta-information; not useful for retrieval."},
}

NOTE_REVIEW_COMMENTS = {
    16: "Very short, but clarifies that aviation connectivity counts direct flights; meaningful once appended to its paragraph.",
    21: "Starts with 'It' and depends on context, which is guaranteed because informative notes are appended to the referencing paragraph.",
    24: "Data-sharing constraint (summary statistics only); kept because it answers data-granularity questions.",
    25: "Shipping line anonymized by agreement; kept because it answers 'which shipping line?' questions.",
    28: "Single pointer to lpi.worldbank.org; the referencing paragraph already states the finding.",
    30: "Starts with a URL pointer but continues with substantive content on FLOW and India's ULIP.",
}

# ---- validate overrides / comments ----
known_notes = set(note_registry_df["note_no"])
assert set(NOTE_POLICY_OVERRIDES) <= known_notes, "Override for an unknown note."
assert set(NOTE_REVIEW_COMMENTS) <= known_notes, "Comment for an unknown note."
for n, o in NOTE_POLICY_OVERRIDES.items():
    assert o["policy"] in NOTE_POLICIES and len(o.get("reason", "")) > 10, f"Note {n}: invalid override."

# ---- final policy ----
is_override = note_registry_df["note_no"].isin(NOTE_POLICY_OVERRIDES)
note_registry_df["policy"] = [
    NOTE_POLICY_OVERRIDES[n]["policy"] if n in NOTE_POLICY_OVERRIDES else s
    for n, s in zip(note_registry_df["note_no"], note_registry_df["suggested_policy"])
]
note_registry_df["policy_reason"] = [
    NOTE_POLICY_OVERRIDES[n]["reason"] if n in NOTE_POLICY_OVERRIDES else r
    for n, r in zip(note_registry_df["note_no"], note_registry_df["suggested_reason"])
]
note_registry_df["policy_source"] = np.where(is_override, "manual_override", "auto_reviewed")
note_registry_df["review_comment"] = note_registry_df["note_no"].map(NOTE_REVIEW_COMMENTS)

print("Final policy:", note_registry_df["policy"].value_counts().to_dict())
print("Overrides   :", len(NOTE_POLICY_OVERRIDES), "| Review comments:", len(NOTE_REVIEW_COMMENTS))

with pd.option_context("display.max_colwidth", 110):
    print(note_registry_df.loc[
        is_override | note_registry_df["review_comment"].notna(),
        ["note_no", "suggested_policy", "policy", "policy_source", "review_comment"],
    ])

# =========================================================
# 5.5 Phase 5 validation
# =========================================================

# ---- one row per (marker, note) — a marker like "13, 15" would give two rows ----
note_refs_long = (
    note_refs_df.explode("note_nos").rename(columns={"note_nos": "note_no"})
    .astype({"note_no": int})
    .merge(note_registry_df[["note_no", "policy"]], on="note_no", how="left")
    .reset_index(drop=True)
)

# ---- A) registry ----
assert note_registry_df["note_no"].tolist() == list(range(1, 34)), "Registry must hold notes 1..33."
assert note_registry_df["text"].str.strip().ne("").all(), "Empty note text."
assert note_registry_df["policy"].isin(NOTE_POLICIES).all(), "Every note needs exactly one valid policy."
assert note_registry_df["policy_reason"].str.len().gt(0).all(), "Every policy needs a reason."

# ---- B) references resolve, and every note is referenced ----
assert note_refs_long["policy"].notna().all(), "A marker points to an unknown note."
ref_counts = note_refs_long["note_no"].value_counts()
assert set(ref_counts.index) == set(note_registry_df["note_no"]), \
    f"Notes never referenced: {sorted(set(note_registry_df['note_no']) - set(ref_counts.index))}"

# ---- C) marker placement ----
assert note_refs_df["page_number"].isin(RETRIEVAL_PAGES).all(), "Marker on a non-retrieval page."
assert not any(
    in_structured_region(r.page_number, r.x0, r.y0, r.x0 + 1, r.y0 + 1) for r in note_refs_df.itertuples()
), "Marker inside a table/figure region."
first_seen = list(dict.fromkeys(note_refs_long["note_no"]))
assert first_seen == sorted(first_seen), "Markers are not in ascending reading order."

# ---- D) no informative note can be lost ----
informative_notes = set(note_registry_df.loc[note_registry_df["policy"] == "informative", "note_no"])
assert informative_notes <= set(note_refs_long["note_no"]), "An informative note has no marker to attach to."

# ---- E) reviewed snapshot (regression guard) — reviewed 2026-09-25 ----
REVIEWED_CITATION_ONLY = [2, 3, 4, 5, 7, 8, 9, 11, 14, 20, 27, 28, 31, 32, 33]
assert sorted(note_registry_df.loc[note_registry_df["policy"] == "citation_only", "note_no"]) == REVIEWED_CITATION_ONLY, \
    "Note policies drifted from the reviewed snapshot."
assert (ref_counts == 1).all(), "Snapshot: every note is referenced exactly once in this report."

# ---- summary ----
print("✅ Phase 5 validation passed.")
print(f"Notes            : {len(note_registry_df)}  {note_registry_df['policy'].value_counts().to_dict()}")
print(f"Markers          : {len(note_refs_df)} on pages {sorted(note_refs_df['page_number'].unique())}")
print(f"Policy source    : {note_registry_df['policy_source'].value_counts().to_dict()}")
print(f"Informative chars: {note_registry_df.loc[note_registry_df['policy'] == 'informative', 'char_count'].sum()} "
      f"(to be appended in Phase 9)")


# %% Phase 6 — Body Extraction + Cleaning
# Goal: extract only the body prose from retrieval pages, cleaned and with physical position,
# excluding everything already handled in Phases 3–5.
#
# Principle: **exclude what is known, keep everything else.** A line is body unless it is a
# header/footer, a document heading or decoration, or inside a structured (table/figure) region.
# Any unexpected font that survives is surfaced by the audit rather than silently dropped.
#
# - **6.1** Tag every line with its exclusion reason (or `body`)
# - **6.2** Cleaning rules (control chars, NBSP, non-breaking hyphen; line-break type recorded, not applied)
# - **6.3** Span-level body extraction: note-marker spans removed and recorded as `note_nos`
# - **6.4** Duplication check against structured units
# - **6.5** Body audit + validation
#
# Run-in subsection headings ("1.1 …") stay inside their line; Phase 7 decides how to treat them.

# =========================================================
# 6.1 Structural boundaries: tag every line on retrieval pages
# =========================================================
# Priority: header/footer > structured region > heading > title-font decoration > body

rl = lines_df[lines_df["page_number"].isin(RETRIEVAL_PAGES)].copy()

in_region = pd.Series(False, index=rl.index)
for r in structured_regions_df.itertuples():
    in_region |= (
        (rl["page_number"] == r.page_number)
        & (rl["x1"] > r.x0) & (rl["x0"] < r.x1) & (rl["y1"] > r.y0) & (rl["y0"] < r.y1)
    )

rl["reason"] = np.select(
    [
        rl["zone"] == "header",
        rl["zone"] == "footer",
        in_region,
        is_heading_line(rl),
        rl["font"] == TITLE_FONT,          # "CHAPTER" label and other title-font decoration
    ],
    ["header", "footer", "structured_region", "heading", "decoration"],
    default="body",
)

# ---- 1) counts per page and reason ----
print("Lines per page by reason:")
with pd.option_context("display.max_rows", None):
    print(rl.pivot_table(index="page_number", columns="reason", values="text",
                           aggfunc="count", fill_value=0))

# ---- 2) decoration lines (should be only 'CHAPTER' labels) ----
print("\nDecoration lines:")
print(rl.loc[rl["reason"] == "decoration", ["page_number", "y0", "x0", "size", "font", "text"]])

# ---- 3) every non-run-in heading of section_map must be excluded as 'heading' ----
missing_headings = []
for h in section_map[section_map["role"] != "runin_subsection"].itertuples():
    tagged = rl[(rl["page_number"] == h.page_number) & ((rl["y0"] - h.y0).abs() < 1.0)
                & (rl["reason"] == "heading")]
    if tagged.empty:
        missing_headings.append((h.heading_id, h.page_number, h.heading_text))
print("\nsection_map headings NOT tagged as heading:", missing_headings or "none")

# ---- 4) preview: fonts of the lines that will be treated as body ----
print("\nBody-line fonts (preview for 6.5):")
print(rl[rl["reason"] == "body"].groupby(["font", "size"]).agg(
    lines=("text", "size"), pages=("page_number", "nunique"), example=("text", "first")))

# =========================================================
# 6.2 Line cleaning rules (+ unit tests on real cases from this PDF)
# =========================================================
# Observed encodings in this PDF:
#   "shipment-\u00adlevel"  -> compound hyphen is followed by a soft hyphen (even mid-line)
#   "logis\u00ad" at EOL    -> soft hyphenation of a single word across lines
#   "low- and"             -> suspended hyphen: plain "-" followed by a space
#   "\x08"                 -> hidden control characters (seen in the Contents)
#   "•\t•\t There …"       -> Executive-summary bullet glyphs
# The line-break TYPE is recorded here and applied in Phase 7 when lines are joined.

SOFT_HYPHEN = "\u00ad"
BULLET_RE = re.compile(r"^[•\u2022\s]+")


def line_break_type(raw: str) -> str:
    """How this line should join the next one (applied in Phase 7)."""
    t = raw.rstrip(" \t")
    if t.endswith("-" + SOFT_HYPHEN) or t.endswith("\u2011" + SOFT_HYPHEN):
        return "hard"      # keep the hyphen, no space:  "shipment-" + "level"  -> "shipment-level"
    if t.endswith(SOFT_HYPHEN):
        return "soft"      # drop the hyphen, no space:  "logis" + "tics"        -> "logistics"
    return "none"          # join with a single space


def clean_line(raw: str) -> str:
    t = raw.replace("\u00a0", " ").replace("\u2011", "-").replace("\t", " ")
    t = "".join(ch for ch in t if not unicodedata.category(ch).startswith("C"))   # \x08, soft hyphen, ZWSP …
    t = unicodedata.normalize("NFKC", t)                                           # ligatures: "ﬁ" -> "fi"
    return " ".join(t.split())


def split_bullet(text: str) -> tuple[str, bool]:
    """Remove leading bullet glyphs; report whether the line starts a bullet item."""
    stripped = BULLET_RE.sub("", text)
    return stripped, stripped != text and text.lstrip().startswith(("•", "\u2022"))


# ---- unit tests (real cases) ----
assert clean_line("shipment-\u00adlevel, real-\u00adworld") == "shipment-level, real-world"
assert clean_line("Acknowledgements\x08") == "Acknowledgements"
assert clean_line("a\u00a0b  c") == "a b c"
assert clean_line("\ufb01rms") == "firms"
assert clean_line("public–private — 3.8 days (2024)") == "public–private — 3.8 days (2024)"   # dashes/numbers untouched

assert line_break_type("logis\u00ad") == "soft"
assert line_break_type("shipment-\u00ad") == "hard"
assert line_break_type("low- and middle-") == "none"
assert line_break_type("observed shipment data.") == "none"

assert split_bullet(clean_line("•\t•\t There are large gaps")) == ("There are large gaps", True)
assert split_bullet("Normal line") == ("Normal line", False)

print("✅ Cleaning rules defined and tested.")

# =========================================================
# 6.3 Body-line extraction at span level
# =========================================================
# For every line tagged 'body' in 6.1, rebuild its text from the PDF spans,
# REMOVING note-marker spans (same rule as 5.2) and recording them as note_nos.
# lines_df.block_no / line_no index into page.get_text("dict") exactly as built in 3.1.

dict_cache: dict[int, dict] = {}

def page_dict(p: int) -> dict:
    if p not in dict_cache:
        dict_cache[p] = doc[p - 1].get_text("dict")
    return dict_cache[p]


def is_marker_span(s: dict) -> bool:
    t = s["text"].strip()
    return bool(MARKER_RE.fullmatch(t)) and (s["size"] <= MARKER_MAX_SIZE or bool(s["flags"] & 1))


body_records, dropped_empty, orphan_bullets = [], [], []

for r in rl[rl["reason"] == "body"].itertuples():
    line = page_dict(r.page_number)["blocks"][r.block_no]["lines"][r.line_no]

    note_nos, raw_parts = [], []
    for s in line["spans"]:
        if s["text"].strip() and is_marker_span(s):
            note_nos += expand_marker(s["text"].strip())
        else:
            raw_parts.append(s["text"])
    raw = "".join(raw_parts)

    text, is_bullet = split_bullet(clean_line(raw))
    if not text:
        if is_bullet:      # bullet glyph on its own line -> attach to the text on the same baseline
            orphan_bullets.append((r.page_number, r.y0, r.x0))
        else:
            dropped_empty.append((r.page_number, r.y0, r.text))
        continue

    body_records.append({
        "line_uid": f"p{r.page_number}_b{r.block_no}_l{r.line_no}",
        "page_number": r.page_number, "block_no": r.block_no, "line_no": r.line_no,
        "column": column_of(r.page_number, r.x0),
        "x0": r.x0, "y0": r.y0, "x1": r.x1, "y1": r.y1,
        "font": r.font, "size": r.size, "is_bold": r.is_bold,
        "text": text,
        "raw_text": raw,
        "note_nos": note_nos,
        "line_break": line_break_type(raw),
        "is_bullet_start": is_bullet,
    })

body_lines_df = (
    pd.DataFrame(body_records)
    .sort_values(["page_number", "column", "y0", "x0"])
    .reset_index(drop=True)
)
excluded_lines_df = rl[rl["reason"] != "body"][
    ["page_number", "block_no", "line_no", "y0", "x0", "size", "font", "reason", "text"]
].reset_index(drop=True)

# ---- attach orphan bullet glyphs to the text line on the same baseline, to their right ----
unattached_bullets = []
for p, y, x in orphan_bullets:
    cand = body_lines_df[
        (body_lines_df["page_number"] == p)
        & ((body_lines_df["y0"] - y).abs() < 2.0)
        & (body_lines_df["x0"] > x)
    ]
    if cand.empty:
        unattached_bullets.append((p, y, x))
        continue
    body_lines_df.loc[(cand["x0"] - x).idxmin(), "is_bullet_start"] = True

assert not unattached_bullets, f"Bullet glyphs with no text line on their baseline: {unattached_bullets}"
print(f"Orphan bullet glyphs attached: {len(orphan_bullets)}")

# ---- summary ----
markers_removed = [n for nums in body_lines_df["note_nos"] for n in nums]
print(f"Body lines        : {len(body_lines_df)}  (dropped empty after cleaning: {len(dropped_empty)})")
print(f"Excluded lines    : {len(excluded_lines_df)}  {excluded_lines_df['reason'].value_counts().to_dict()}")
print(f"Markers removed   : {len(markers_removed)}  (notes {min(markers_removed)}–{max(markers_removed)})")
print(f"Line-break types  : {body_lines_df['line_break'].value_counts().to_dict()}")
print(f"Bullet starts     : {int(body_lines_df['is_bullet_start'].sum())}")
if dropped_empty:
    print("Dropped (empty)   :", dropped_empty[:10])
if orphan_bullets:
    print("Orphan bullets    :", orphan_bullets[:10])

sample = pd.concat([
    body_lines_df[body_lines_df["note_nos"].map(len) > 0].head(3),
    body_lines_df[body_lines_df["line_break"] == "soft"].head(3),
    body_lines_df[body_lines_df["line_break"] == "hard"].head(3),
    body_lines_df[body_lines_df["is_bullet_start"]].head(3),
])
print("\nSamples (markers / soft break / hard break / bullets):")
with pd.option_context("display.max_colwidth", 70):
    print(sample[["line_uid", "column", "note_nos", "line_break", "is_bullet_start", "raw_text", "text"]])

# =========================================================
# 6.4 Duplication check: body lines vs structured units
# =========================================================
# Structured content (captions, table cells, figure text, Source/Note lines) uses
# Helvetica; body prose uses Garamond (and Eurostile regular on the back cover).
# Prose may legitimately START with "figure 2.1)." — so caption leaks are detected
# by FONT, not by the label regex alone.

def norm_cmp(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", text.lower()).split())


# ---- 1) structural-font leak: any Helvetica line left in the body ----
helvetica_leaks = body_lines_df[body_lines_df["font"].str.startswith("HelveticaNeue")]

# ---- 2) Source/Note line leak ----
source_leaks = body_lines_df[body_lines_df["text"].str.match(SOURCE_NOTE_RE)]

# ---- 3) caption-label-looking lines (reported with font, for review) ----
label_like = body_lines_df[body_lines_df["text"].str.match(LABEL_RE)][["line_uid", "font", "size", "text"]]

# ---- 4) text overlap: long body lines found verbatim inside structured content ----
structured_norm = {r.unit_id: norm_cmp(r.content) for r in structured_units_df.itertuples()}
overlaps = []
for r in body_lines_df.itertuples():
    t = norm_cmp(r.text)
    if len(t) < 30:
        continue
    hits = [uid for uid, content in structured_norm.items() if t in content]
    if hits:
        overlaps.append({"line_uid": r.line_uid, "page_number": r.page_number, "units": hits, "text": r.text})
overlaps_df = pd.DataFrame(overlaps)

print(f"Helvetica lines in body        : {len(helvetica_leaks)}")
print(f"Source/Note lines in body      : {len(source_leaks)}")
print(f"Label-like lines (prose refs?) : {len(label_like)}")
print(f"Body lines found in structured : {len(overlaps_df)}")

if len(label_like):
    print(label_like)
if len(overlaps_df):
    with pd.option_context("display.max_colwidth", 80):
        print(overlaps_df)

assert helvetica_leaks.empty, f"Structured text leaked into body: {helvetica_leaks['line_uid'].tolist()}"
assert source_leaks.empty, f"Source/Note lines leaked into body: {source_leaks['line_uid'].tolist()}"
print("\n✅ No structured-element leakage into body text.")

# =========================================================
# 6.5 Body audit + Phase 6 validation
# =========================================================

ALLOWED_BODY_FONTS = {"GaramondPremrPro", "GaramondPremrPro-Bd", "GaramondPremrPro-It"}
BACK_COVER_FONT = "EurostileLTStd"

# ---- A) accounting: every 'body' line from 6.1 is kept or explicitly explained ----
n_body_tagged = int((rl["reason"] == "body").sum())
assert len(body_lines_df) + len(orphan_bullets) + len(dropped_empty) == n_body_tagged, "Body lines unaccounted for."
assert body_lines_df["line_uid"].is_unique

# ---- B) coverage: every retrieval page has body text ----
per_page = body_lines_df.groupby("page_number").agg(
    lines=("text", "size"), body_chars=("text", lambda s: s.str.len().sum())
)
per_page = per_page.join(pages_df.set_index("page_number")["char_count"].rename("page_chars"))
per_page["body_share"] = (per_page["body_chars"] / per_page["page_chars"]).round(2)
assert set(per_page.index) == set(RETRIEVAL_PAGES), \
    f"Retrieval pages without body text: {sorted(set(RETRIEVAL_PAGES) - set(per_page.index))}"

# ---- C) fonts ----
unexpected_fonts = body_lines_df[
    ~body_lines_df["font"].isin(ALLOWED_BODY_FONTS)
    & ~((body_lines_df["font"] == BACK_COVER_FONT) & (body_lines_df["page_number"] == LAST_PAGE))
]
assert unexpected_fonts.empty, f"Unexpected body fonts: {unexpected_fonts[['page_number', 'font']].drop_duplicates().values.tolist()}"

# ---- D) text hygiene ----
assert not body_lines_df["text"].map(lambda t: any(unicodedata.category(ch).startswith("C") for ch in t)).any(), \
    "Control/format characters left in body text."
assert not body_lines_df["text"].str.startswith("•").any(), "Bullet glyph left at line start."
assert not body_lines_df["text"].str.upper().str.startswith("CONNECTING TO COMPETE 2025 THE NEW").any(), \
    "Running footer leaked into body."
assert body_lines_df["line_break"].isin({"none", "soft", "hard"}).all()

# ---- E) note markers: removed from text, each note recorded exactly once ----
body_note_refs = sorted(n for nums in body_lines_df["note_nos"] for n in nums)
assert body_note_refs == list(range(1, 34)), "Body note references must be exactly notes 1..33, once each."

# ---- F) reviewed snapshot — body lines per page (reviewed 2026-09-25) ----
REVIEWED_BODY_LINES = {
    8: 32, 10: 80, 11: 60, 12: 75, 13: 64, 14: 39, 15: 96, 16: 22, 17: 74, 18: 22,
    19: 16, 20: 48, 21: 33, 22: 34, 23: 29, 24: 71, 25: 91, 26: 88, 27: 20, 30: 29,
}
assert per_page["lines"].to_dict() == REVIEWED_BODY_LINES, "Body lines per page drifted from snapshot."

# ---- summary ----
print("✅ Phase 6 validation passed.")
print(f"Body lines       : {len(body_lines_df)} on {len(per_page)} pages | chars: {per_page['body_chars'].sum()}")
print(f"Excluded lines   : {len(excluded_lines_df)}  {excluded_lines_df['reason'].value_counts().to_dict()}")
print(f"Bullet starts    : {int(body_lines_df['is_bullet_start'].sum())} | line breaks: "
      f"{body_lines_df['line_break'].value_counts().to_dict()}")
print("\nBody coverage per page (body_share = body chars / raw page chars):")
print(per_page)


# %% Phase 7 — Paragraph Reconstruction
# Goal: rebuild complete paragraphs from the Phase 6 body lines, in true reading order,
# including paragraphs that continue across columns, pages and figures.
#
# The rules are derived from measurements (7.1), not assumptions: 13.5pt leading, a 15pt
# first-line indent for new paragraphs, hanging indents for bullet items, 27–68pt gaps at headings.
# A paragraph continues whenever the previous line did not end a sentence — this is what joins
# text across a column break, a page break or a figure. Run-in subsections ("1.1 …") stay in the
# paragraph text and are also recorded as `runin_heading`.

# =========================================================
# 7.1 Layout profile: line spacing, first-line indent, column geometry
# =========================================================
# Measured on body_lines_df (Phase 6). These numbers drive the rules in 7.2.

COLUMN_PITCH = 198.0          # right column starts 198pt after the left one on every two-column page

rb = body_lines_df.sort_values(["page_number", "column", "y0", "x0"]).reset_index(drop=True)

# column left edge per (page, column): robust to columns whose lines are all indented
col_min = rb.groupby(["page_number", "column"])["x0"].min().unstack()
page_base = pd.concat([col_min[0], col_min.get(1, pd.Series(dtype=float)) - COLUMN_PITCH], axis=1).min(axis=1)
rb["col_left"] = [page_base[p] + COLUMN_PITCH * c for p, c in zip(rb["page_number"], rb["column"])]
rb["dx"] = (rb["x0"] - rb["col_left"]).round(1)
rb["dy"] = rb.groupby(["page_number", "column"])["y0"].diff().round(1)

LEADING = float(rb["dy"].mode().iloc[0])
INDENT = float(rb.loc[rb["dx"] > 5, "dx"].mode().iloc[0])

print(f"Normal leading (mode of dy) : {LEADING} pt")
print(f"First-line / hanging indent : {INDENT} pt")
print("\ndx distribution:", rb["dx"].value_counts().to_dict())
print("dy > 2 × leading (candidate breaks):", int((rb["dy"] > 2 * LEADING).sum()))

print("\nColumn geometry per page:")
print(rb.groupby(["page_number", "column"]).agg(
    lines=("text", "size"), left=("col_left", "first"), y0=("y0", "min"), y1=("y1", "max")
).unstack("column"))

# =========================================================
# 7.2 Paragraph boundary rules
# =========================================================
# Observed layout (7.1): leading 13.5pt; a new paragraph is signalled by a 15pt
# FIRST-LINE indent; bullet items use a HANGING indent (bullet line flush, the rest +15pt);
# headings leave a 27–68pt gap. Rules, evaluated between consecutive lines in reading order:
#
#   1. a section_map heading lies between the two lines      -> new paragraph ("heading")
#   2. the line starts a bullet item                         -> new paragraph ("bullet")
#   3. the line starts a run-in subsection ("1.1 …", bold)   -> new paragraph ("runin")
#   4. the previous line did NOT end a sentence, or ended
#      with a soft/hard hyphen break                         -> CONTINUE (across columns, pages, figures)
#   5. back cover: each text block is its own paragraph      -> new paragraph ("back_cover_block")
#   6. inside a bullet item, an indented line in the same
#      block is the item's next sentence                     -> CONTINUE
#   7. first-line indent                                     -> new paragraph ("indent")
#   8. vertical gap > 1.6 × leading in the same column       -> new paragraph ("gap")
#   9. otherwise                                             -> CONTINUE

SENTENCE_END_RE = re.compile(r"[.!?:;][”’\")\]]*$")
RUNIN_START_RE = re.compile(r"^\d\.\d\s")


def order_key(page, column, y0):
    return (int(page), int(column), float(y0))


heading_keys = sorted(
    order_key(h.page_number, h.column, h.y0)
    for h in section_map[section_map["role"] != "runin_subsection"].itertuples()
)


def heading_between(prev, cur) -> bool:
    k0 = order_key(prev.page_number, prev.column, prev.y0)
    k1 = order_key(cur.page_number, cur.column, cur.y0)
    return any(k0 < k < k1 for k in heading_keys)


def boundary(prev, cur, in_bullet: bool) -> str | None:
    """Return the reason a new paragraph starts at `cur`, or None to continue."""
    if prev is None:
        return "document_start"
    if heading_between(prev, cur):
        return "heading"
    if cur.is_bullet_start:
        return "bullet"
    if cur.is_bold and RUNIN_START_RE.match(cur.text):
        return "runin"
    if prev.line_break in ("soft", "hard") or not SENTENCE_END_RE.search(prev.text):
        return None
    if cur.page_number == LAST_PAGE and (prev.page_number != cur.page_number or prev.block_no != cur.block_no):
        return "back_cover_block"
    if in_bullet and cur.dx >= INDENT - 1 and (cur.page_number, cur.block_no) == (prev.page_number, prev.block_no):
        return None
    if cur.dx >= INDENT - 1:
        return "indent"
    same_col = (cur.page_number, cur.column) == (prev.page_number, prev.column)
    if same_col and cur.dy > 1.6 * LEADING:
        return "gap"
    return None


# ---- tag every line ----
reasons, in_bullet, prev = [], False, None
for cur in rb.itertuples():
    reason = boundary(prev, cur, in_bullet)
    reasons.append(reason)
    if reason is not None:
        in_bullet = reason == "bullet"
    prev = cur
rb["boundary"] = reasons
rb["para_no"] = rb["boundary"].notna().cumsum()

print("Paragraph starts by reason:", rb["boundary"].value_counts().to_dict())
print("Paragraphs:", int(rb["para_no"].max()))

# ---- every column / page transition: continued or broken, and why ----
prev_rows = rb.shift(1)
transition = (rb["page_number"] != prev_rows["page_number"]) | (rb["column"] != prev_rows["column"])
trans_df = pd.DataFrame({
    "from": prev_rows.loc[transition, "line_uid"],
    "to": rb.loc[transition, "line_uid"],
    "decision": rb.loc[transition, "boundary"].fillna("CONTINUE"),
    "prev_end": prev_rows.loc[transition, "text"].str[-35:],
    "next_start": rb.loc[transition, "text"].str[:35],
}).iloc[1:]
print("\nColumn / page transitions:")
with pd.option_context("display.max_rows", None, "display.max_colwidth", 40):
    print(trans_df)

# =========================================================
# 7.3 Reconstruct paragraphs
# =========================================================

SUSPENDED_HYPHEN_NEXT = {"and", "or", "to", "nor"}     # "low- and middle-income" keeps its space


def join_lines(lines: list) -> str:
    text = ""
    for i, ln in enumerate(lines):
        if i == 0:
            text = ln.text
            continue
        brk = lines[i - 1].line_break
        first_word = ln.text.split(" ", 1)[0].lower()
        if brk in ("soft", "hard"):
            text += ln.text                       # soft: "logis"+"tics"; hard: "shipment-"+"level"
        elif re.search(r"[A-Za-z]-$", text) and first_word not in SUSPENDED_HYPHEN_NEXT:
            text += ln.text                       # plain compound hyphen at EOL: "third-"+"party"
        else:
            text += " " + ln.text
    return " ".join(text.split())


RUNIN_HEADINGS = section_map.loc[section_map["role"] == "runin_subsection", "heading_text"].tolist()


paragraph_records = []
for para_no, grp in rb.groupby("para_no", sort=True):
    lines = list(grp.itertuples())
    first = lines[0]
    text = join_lines(lines)
    runin = None
    if first.boundary == "runin":
        runin = next((h for h in RUNIN_HEADINGS if text.startswith(h)), None)
    paragraph_records.append({
        "paragraph_id": f"P{para_no:03d}",
        "text": text,
        "page_start": int(grp["page_number"].min()),
        "page_end": int(grp["page_number"].max()),
        "first_page": int(first.page_number), "first_column": int(first.column), "first_y0": float(first.y0),
        "boundary_reason": first.boundary,
        "is_bullet": first.boundary == "bullet",
        "runin_heading": runin,
        "footnote_refs": [n for l in lines for n in l.note_nos],
        "n_lines": len(lines),
        "line_uids": [l.line_uid for l in lines],
    })

paragraphs_df = pd.DataFrame(paragraph_records)
paragraphs_df["char_count"] = paragraphs_df["text"].str.len()

print(f"Paragraphs: {len(paragraphs_df)} | spanning >1 page: {int((paragraphs_df['page_start'] != paragraphs_df['page_end']).sum())}")
print("Size (chars):", paragraphs_df["char_count"].describe()[["min", "50%", "max"]].to_dict())
with pd.option_context("display.max_rows", None, "display.max_colwidth", 90):
    print(paragraphs_df[["paragraph_id", "page_start", "page_end", "boundary_reason", "footnote_refs",
                           "char_count", "text"]].assign(text=paragraphs_df["text"].str[:90]))

# =========================================================
# 7.4 Paragraph validation
# =========================================================

# ---- A) every body line used exactly once, in order ----
used = [uid for uids in paragraphs_df["line_uids"] for uid in uids]
assert sorted(used) == sorted(body_lines_df["line_uid"]) and len(used) == len(set(used)), "Line coverage broken."

# ---- B) text preservation: joining can only remove soft-hyphen breaks and whitespace ----
def letters(t: str) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", t)
assert letters("".join(paragraphs_df["text"])) == letters("".join(rb["text"])), "Characters lost while joining."

# ---- C) note references preserved ----
assert sorted(n for refs in paragraphs_df["footnote_refs"] for n in refs) == list(range(1, 34))

# ---- D) no heading text survives as a standalone paragraph ----
heading_texts = set(section_map.loc[section_map["role"] != "runin_subsection", "heading_norm"])
assert not paragraphs_df["text"].str.lower().isin(heading_texts).any(), "A heading became a paragraph."

# ---- E) join artefacts ----
# (Python `re` via .map: pyarrow-backed .str methods do not support look-ahead)
BAD_HYPHEN_RE = re.compile(r"[A-Za-z]- (?!and\b|or\b|to\b|nor\b)[A-Za-z]")
bad_hyphen = paragraphs_df["text"].map(lambda t: bool(BAD_HYPHEN_RE.search(t)))
assert not bad_hyphen.any(), f"Broken hyphenation joins: {paragraphs_df.loc[bad_hyphen, 'paragraph_id'].tolist()}"
assert (paragraphs_df["runin_heading"].notna() == (paragraphs_df["boundary_reason"] == "runin")).all(), \
    "Every run-in paragraph must be matched to its section_map heading."
assert not paragraphs_df["text"].str.contains("\u00ad", regex=False).any(), "Soft hyphen left in text."

# ---- F) review flags (not errors) ----
starts_lower = paragraphs_df[paragraphs_df["text"].str.match(r"^[a-z]")]
no_end = paragraphs_df[~paragraphs_df["text"].str.contains(r"[.!?:][”’\")\]]*$", regex=True)]
print(f"Paragraphs starting lowercase : {len(starts_lower)}")
print(f"Paragraphs without an ending  : {len(no_end)}")
with pd.option_context("display.max_colwidth", 120):
    if len(starts_lower):
        print(starts_lower[["paragraph_id", "page_start", "boundary_reason", "text"]])
    if len(no_end):
        print(no_end[["paragraph_id", "page_start", "boundary_reason", "text"]].assign(text=no_end["text"].str[-120:]))

# ---- G) reviewed snapshot ----
REVIEWED_PARAGRAPH_STARTS = {"bullet": 44, "indent": 37, "heading": 20, "runin": 9,
                             "document_start": 1, "back_cover_block": 1}
assert paragraphs_df["boundary_reason"].value_counts().to_dict() == REVIEWED_PARAGRAPH_STARTS, \
    "Paragraph segmentation drifted from the reviewed snapshot."
assert len(paragraphs_df) == 112
print(f"\n✅ Phase 7 validation passed. Paragraphs: {len(paragraphs_df)} | "
      f"bullets: {int(paragraphs_df['is_bullet'].sum())} | run-ins: {int(paragraphs_df['runin_heading'].notna().sum())}")


# %% Phase 8 — Section / Subsection Assignment
# Every unit is assigned by **physical position**: the last heading that precedes it in reading
# order `(page, column, y0)`, so a page with several subsections is split correctly.
#
# Tables and figures are floats (placed at page tops or in the other column), so they are assigned
# to the section of the **first prose paragraph that references them** ("figure 2.1", "table 1.2"),
# with physical position only as a fallback. `subsection` is the full heading path below the chapter,
# e.g. `A strategic framework… > Area 1: … > 1.1 Liberalizing markets…`.

# =========================================================
# 8.1 Heading positions in reading order
# =========================================================
# Every unit is assigned to the LAST heading that precedes it in reading order
# (page, column, y0) — a physical assignment, so a page with several subsections
# is split correctly. Run-in subsections count as level-4 headings.

heading_seq = section_map.assign(
    key=[order_key(p, c, y) for p, c, y in zip(section_map["page_number"], section_map["column"], section_map["y0"])]
).sort_values("key").reset_index(drop=True)


def subsection_path(h) -> list[str]:
    return [v for v in (h["l2"], h["l3"], h["l4"]) if isinstance(v, str) and v]


def locate(page: int, column: int, y0: float) -> dict:
    """Section / subsection path of the last heading at or before this position."""
    k = order_key(page, column, y0)
    prior = heading_seq[heading_seq["key"].map(lambda hk: hk <= (k[0], k[1], k[2] + 0.5))]
    if prior.empty:
        return {"section": None, "subsection_path": [], "heading_id": None}
    h = prior.iloc[-1]
    return {"section": h["l1"], "subsection_path": subsection_path(h), "heading_id": h["heading_id"]}


print(f"Headings in reading order: {len(heading_seq)} (first: {heading_seq['heading_text'].iloc[0]!r})")

# =========================================================
# 8.2 Assign paragraph sections
# =========================================================
loc = paragraphs_df.apply(lambda r: locate(r["first_page"], r["first_column"], r["first_y0"]), axis=1)
paragraphs_df["section"] = loc.map(lambda d: d["section"])
paragraphs_df["subsection_path"] = loc.map(lambda d: d["subsection_path"])
paragraphs_df["heading_id"] = loc.map(lambda d: d["heading_id"])

# =========================================================
# 8.3 Assign structured-unit sections
# =========================================================
# Tables and figures are FLOATS: the layout places them at the top of a page or in
# the other column, so their physical position often falls under the previous
# heading (e.g. Figure 2.1 sits on p.18 after the "Time" heading, but belongs to
# "Connectivity"). They are therefore assigned to the section of the FIRST prose
# paragraph that references them ("(figure 2.1, panels a, b, c)", "table 1.2"),
# with the physical position as a fallback.

region_by_ref = structured_regions_df.set_index(["kind", "ref"])


def first_reference(kind: str, number: str):
    pat = re.compile(rf"\b{kind}s? {re.escape(number)}(?!\d)", re.IGNORECASE)
    hits = paragraphs_df[paragraphs_df["text"].map(lambda t: bool(pat.search(t)))]   # Python re (look-ahead)
    return None if hits.empty else hits.iloc[0]


def structured_location(u) -> dict:
    if u["unit_type"] == "definitions":
        return {"section": "Abbreviations", "subsection_path": [], "heading_id": None, "section_basis": "front_matter"}
    kind, ref = ("table", u["table_number"]) if u["unit_type"] == "table_row" else ("figure", u["figure_number"])
    ref_par = first_reference(kind, ref)
    if ref_par is not None:
        return {"section": ref_par["section"], "subsection_path": list(ref_par["subsection_path"]),
                "heading_id": ref_par["heading_id"], "section_basis": f"first_prose_reference:{ref_par['paragraph_id']}"}
    reg = region_by_ref.loc[(kind, ref)]
    d = locate(int(reg["page_number"]), column_of(int(reg["page_number"]), float(reg["x0"]) + 1), float(reg["y0"]))
    return {**d, "section_basis": "physical_position"}


sloc = structured_units_df.apply(structured_location, axis=1)
for key in ("section", "subsection_path", "heading_id", "section_basis"):
    structured_units_df[key] = sloc.map(lambda d, k=key: d[k])

# =========================================================
# 8.4 Validate assignment
# =========================================================
assert paragraphs_df["section"].notna().all(), "Paragraph without a section."
assert structured_units_df["section"].notna().all(), "Structured unit without a section."
tf = structured_units_df[structured_units_df["unit_type"].isin(["table_row", "figure"])]
assert tf["section_basis"].str.startswith("first_prose_reference").all(), \
    f"Tables/figures without a prose reference: {tf.loc[~tf['section_basis'].str.startswith('first_prose_reference'), 'unit_id'].tolist()}"

# a paragraph that starts right after a heading must be assigned to THAT heading
after_heading = paragraphs_df[paragraphs_df["boundary_reason"] == "heading"]
for r in after_heading.itertuples():
    h = heading_seq[heading_seq["heading_id"] == r.heading_id].iloc[0]
    assert h["page_number"] in (r.first_page, r.first_page - 1), f"{r.paragraph_id}: heading too far away."

# run-in paragraphs sit under their own run-in heading
for r in paragraphs_df[paragraphs_df["runin_heading"].notna()].itertuples():
    assert r.subsection_path and r.subsection_path[-1] == r.runin_heading, f"{r.paragraph_id}: run-in not assigned."

# sections appear in document order (no paragraph jumps back to an earlier chapter)
section_order = list(dict.fromkeys(heading_seq["l1"]))
seq = paragraphs_df["section"].map(section_order.index)
assert seq.is_monotonic_increasing, "Paragraph sections are not in document order."

summary = (paragraphs_df.assign(subsection=paragraphs_df["subsection_path"].map(" > ".join))
           .groupby(["section", "subsection"], sort=False).agg(paragraphs=("paragraph_id", "size"),
                                                                pages=("page_start", lambda s: sorted(set(s)))))
print("✅ Phase 8 validation passed.\n\nParagraphs per section / subsection:")
with pd.option_context("display.max_rows", None, "display.max_colwidth", 90):
    print(summary)
print("\nStructured units:")
print(structured_units_df.assign(subsection=structured_units_df["subsection_path"].map(" > ".join))
        [["unit_id", "section", "subsection", "section_basis"]])


# %% Phase 9 — Unified Logical Units
# One pre-chunking table with a single authoritative text field (`content`):
# paragraphs + table rows + figures + abbreviation definitions.
# The note policy from Phase 5 is applied here: informative notes are appended to the
# paragraph that references them as `Note: …`; citation-only notes stay in `footnote_refs` only.

# =========================================================
# 9.1 Combine paragraphs + tables + figures + definitions
# 9.2 Apply the note policy (informative -> "Note: …" appended; citation_only -> metadata only)
# =========================================================

note_policy = note_registry_df.set_index("note_no")["policy"].to_dict()
note_text = note_registry_df.set_index("note_no")["text"].to_dict()


def with_notes(text: str, refs: list[int]) -> str:
    notes = [f"Note: {note_text[n]}" for n in refs if note_policy[n] == "informative"]
    return text if not notes else f"{text} " + " ".join(notes)


unit_records = []
for r in paragraphs_df.itertuples():
    unit_records.append({
        "unit_id": r.paragraph_id,
        "unit_type": "paragraph",
        "logical_unit": f"paragraph_{int(r.paragraph_id[1:]):03d}",
        "title": None,
        "content": with_notes(r.text, list(r.footnote_refs)),
        "section": r.section,
        "subsection_path": list(r.subsection_path),
        "page_start": r.page_start, "page_end": r.page_end,
        "order_key": order_key(r.first_page, r.first_column, r.first_y0),
        "footnote_refs": list(r.footnote_refs),
        "table_number": None, "figure_number": None,
        "is_bullet": bool(r.is_bullet), "runin_heading": r.runin_heading,
        "provenance": "extracted",
        "flag": None,
    })

for r in structured_units_df.itertuples():
    if r.unit_type == "definitions":
        key = (7, 0, float(r.anchor_y0))
    else:
        kind, ref = ("table", r.table_number) if r.unit_type == "table_row" else ("figure", r.figure_number)
        reg = region_by_ref.loc[(kind, ref)]
        key = order_key(reg["page_number"], column_of(int(reg["page_number"]), float(reg["x0"]) + 1), reg["y0"])
    unit_records.append({
        "unit_id": r.unit_id,
        "unit_type": r.unit_type,
        "logical_unit": r.unit_id.replace(".", "_"),
        "title": r.title,
        "content": r.content,
        "section": r.section,
        "subsection_path": list(r.subsection_path),
        "page_start": int(r.page_start), "page_end": int(r.page_end),
        "order_key": key,
        "footnote_refs": [],
        "table_number": r.table_number, "figure_number": r.figure_number,
        "is_bullet": False, "runin_heading": None,
        "provenance": r.description_provenance if isinstance(r.description_provenance, str) else "extracted",
        "flag": r.flag if isinstance(r.flag, str) else None,
    })

units_df = pd.DataFrame(unit_records).sort_values("order_key", kind="stable").reset_index(drop=True)
units_df["subsection"] = units_df["subsection_path"].map(lambda p: " > ".join(p) if p else None)
units_df["char_count"] = units_df["content"].str.len()

# =========================================================
# 9.3 Validate units
# =========================================================
assert units_df["unit_id"].is_unique
assert units_df["content"].str.strip().ne("").all()
assert units_df["section"].notna().all()
assert units_df["unit_type"].value_counts().to_dict() == {"paragraph": 112, "figure": 7, "definitions": 7, "table_row": 5}

# every informative note appended exactly once; no citation-only note injected
all_content = "\n".join(units_df["content"])
for n, pol in note_policy.items():
    hits = all_content.count(f"Note: {note_text[n]}")
    assert hits == (1 if pol == "informative" else 0), f"Note {n} ({pol}) appears {hits} times."

print("✅ Unified logical units:", len(units_df), units_df["unit_type"].value_counts().to_dict())
print("Informative notes appended:", sum(p == "informative" for p in note_policy.values()),
      "| citation-only kept as metadata:", sum(p == "citation_only" for p in note_policy.values()))
print("Units > MAX_CHUNK_CHARS (to be split at chunking):",
      units_df.loc[units_df["char_count"] > MAX_CHUNK_CHARS, ["unit_id", "char_count"]].values.tolist())


# %% Phase 10 — Duplicate Detection (within-source and cross-source)
# Reference: `LPI_Methodology_logical_units.json` (the cleaned units of the Methodology report).
#
# Deterministic, no embeddings:
# 1. exact duplicates by normalized-text hash;
# 2. candidate blocking by unit family + TF-IDF character n-gram cosine (small structured families
#    are compared exhaustively);
# 3. **item-level** comparison — sentences for prose, indicator definitions for table rows, one line
#    per abbreviation — with `difflib` ratios. An item is *covered* when it is repeated (ratio ≥ 0.90)
#    or paraphrased (≥ 0.75) **without adding any new content word**.
#
# Relationships: `exact_duplicate`, `near_duplicate`, `contextual_duplicate`,
# `duplicate_candidate_review`, `unique`. The unit `content` is never modified in this phase.

# =========================================================
# 10.1 Comparison normalization, sentence splitting, content tokens
# =========================================================
# Comparison-only representations: the unit `content` itself is never modified here.

import difflib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

METHODOLOGY_UNITS_PATH = CLEANED_DIR / "LPI_Methodology_logical_units.json"

CANDIDATE_SIM = 0.50        # TF-IDF (char 3–5 grams) cosine to enter the detailed comparison
SENTENCE_MATCH = 0.90       # difflib ratio: sentence repeated (near-)verbatim
PARAPHRASE_MATCH = 0.75     # ratio for a rephrased sentence that adds NO new content words

SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z“\"(])")
STOPWORDS = set("""the a an of and or to in for on by with from as at is are be that this these those which its their it
into than more most such can may also both each other has have was were not but between over across while within through""".split())


def cmp_norm(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).replace("­", "").lower()
    t = re.sub(r"[‐‑–—]", "-", t)
    t = re.sub(r"[“”]", '"', t)
    t = re.sub(r"[‘’]", "'", t)
    return " ".join(t.split())


def sentences(text: str) -> list[str]:
    return [s for s in SENT_SPLIT_RE.split(text.replace("\n", " ")) if s.strip()]


def content_tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", cmp_norm(text))
            if (len(w) >= 3 or w.isdigit()) and w not in STOPWORDS}


def text_hash(text: str) -> str:
    return hashlib.sha256(cmp_norm(text).encode("utf-8")).hexdigest()[:16]


# ---- comparison items per unit: sentences for prose, indicator/term items for tables & definitions ----
def items_of_ours(u) -> list[str]:
    if u["unit_type"] == "table_row":
        su = structured_units_df.set_index("unit_id").loc[u["unit_id"]]
        return [f"{i['indicator']}: {i['definition']}" for i in su["indicators"]]
    if u["unit_type"] == "definitions":
        return [u["content"]]
    return sentences(u["content"])


def items_of_methodology(mu: dict) -> list[str]:
    if mu["unit_type"] == "table_row":
        out = []
        for line in mu["content"].split("\n")[1:]:                  # skip "Logistics mode: X"
            _, _, value = line.partition(": ")
            out += [p.strip() for p in value.split("•") if p.strip()]
        return out
    if mu["unit_type"] == "definitions":
        return [l for l in mu["content"].split("\n")[1:] if l.strip()]   # skip "Abbreviations"
    return sentences(mu["content"])


methodology_units = json.loads(METHODOLOGY_UNITS_PATH.read_text(encoding="utf-8"))
FAMILY = {"paragraph": "prose", "figure": "prose", "worked_example": "prose",
          "table_row": "table_row", "definitions": "definitions"}

print(f"Methodology reference units: {len(methodology_units)} "
      f"{pd.Series([u['unit_type'] for u in methodology_units]).value_counts().to_dict()}")

# =========================================================
# 10.2 Exact hash duplicates (within-source and cross-source)
# =========================================================
units_df["norm_hash"] = units_df["content"].map(text_hash)
meth_hash = {text_hash(u["content"]): u["unit_id"] for u in methodology_units}

within_exact = units_df[units_df.duplicated("norm_hash", keep=False)]
cross_exact = units_df[units_df["norm_hash"].isin(meth_hash)]
print(f"Exact within-source duplicates: {len(within_exact)} | exact cross-source duplicates: {len(cross_exact)}")

# =========================================================
# 10.3 Candidate blocking (same family + TF-IDF similarity)
# =========================================================
ours_texts = [cmp_norm(c) for c in units_df["content"]]
meth_texts = [cmp_norm(u["content"]) for u in methodology_units]
vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5)).fit(ours_texts + meth_texts)
V_ours, V_meth = vectorizer.transform(ours_texts), vectorizer.transform(meth_texts)
SIM_cross = cosine_similarity(V_ours, V_meth)
SIM_within = cosine_similarity(V_ours)
np.fill_diagonal(SIM_within, 0.0)

# Small structured families (table rows, definitions) are compared exhaustively: a short
# abbreviation line has a low TF-IDF score against a whole abbreviations table.
# Within-source pairs are compared in BOTH directions (A covered by B, and B covered by A).
EXHAUSTIVE_FAMILIES = {"table_row", "definitions"}

candidates = []
for i, u in units_df.iterrows():
    fam = FAMILY[u["unit_type"]]
    for j, mu in enumerate(methodology_units):
        if FAMILY[mu["unit_type"]] == fam and (fam in EXHAUSTIVE_FAMILIES or SIM_cross[i, j] >= CANDIDATE_SIM):
            candidates.append(("cross", i, j, float(SIM_cross[i, j])))
    for j in range(len(units_df)):
        if j != i and FAMILY[units_df.at[j, "unit_type"]] == fam and SIM_within[i, j] >= CANDIDATE_SIM:
            candidates.append(("within", i, j, float(SIM_within[i, j])))
print(f"Candidate pairs: {len(candidates)} "
      f"(cross={sum(c[0] == 'cross' for c in candidates)}, within={sum(c[0] == 'within' for c in candidates)})")

# =========================================================
# 10.4 Item-level near-duplicate comparison
# =========================================================
# An item (sentence / indicator / abbreviation) of unit A is COVERED by unit B if
#   - its best difflib ratio against B's items is >= SENTENCE_MATCH, or
#   - the ratio is >= PARAPHRASE_MATCH AND it adds no content word missing from B.
# Items that are not covered carry the unit's unique information.

def compare_items(a_items: list[str], b_items: list[str], b_text: str) -> list[dict]:
    b_norm = [cmp_norm(x) for x in b_items]
    b_tokens = content_tokens(b_text)
    out = []
    for item in a_items:
        n = cmp_norm(item)
        ratios = [difflib.SequenceMatcher(None, n, m).ratio() for m in b_norm] or [0.0]
        k = int(np.argmax(ratios))
        new_words = sorted(content_tokens(item) - b_tokens)
        covered = ratios[k] >= SENTENCE_MATCH or (ratios[k] >= PARAPHRASE_MATCH and not new_words)
        out.append({"item": item, "best_ratio": round(ratios[k], 3), "new_words": new_words, "covered": covered})
    return out


pair_records = []
for scope, i, j, sim in candidates:
    u = units_df.loc[i]
    if scope == "cross":
        mu = methodology_units[j]
        other_id, other_type, b_items, b_text = mu["unit_id"], mu["unit_type"], items_of_methodology(mu), mu["content"]
        other_source = "LPI_Methodology"
    else:
        v = units_df.loc[j]
        other_id, other_type, b_items, b_text = v["unit_id"], v["unit_type"], items_of_ours(v), v["content"]
        other_source = SOURCE_NAME
    items = compare_items(items_of_ours(u), b_items, b_text)
    pair_records.append({
        "scope": scope, "unit_id": u["unit_id"], "unit_type": u["unit_type"], "section": u["section"],
        "candidate_source": other_source, "candidate_unit_id": other_id, "candidate_type": other_type,
        "similarity_score": round(sim, 3),
        "exact": u["norm_hash"] == (text_hash(b_text)),
        "items_total": len(items), "items_covered": sum(x["covered"] for x in items),
        "uncovered_items": [x for x in items if not x["covered"]],
        "item_details": items,
    })
pairs_df = pd.DataFrame(pair_records)

# =========================================================
# 10.5 Cross-source + within-source comparison summary
# 10.6 Duplicate relationship classification
# =========================================================
# exact_duplicate            normalized content identical
# near_duplicate             every item covered (repeated or paraphrased without new content words)
# contextual_duplicate       same topic, but at least one item carries new information (< PARAPHRASE_MATCH
#                            or new content words)
# duplicate_candidate_review uncovered items exist but all are close paraphrases (>= PARAPHRASE_MATCH)
#                            that differ only by a few words -> kept, listed for manual review

def relationship(p) -> str:
    if p["exact"]:
        return "exact_duplicate"
    if p["items_covered"] == p["items_total"]:
        return "near_duplicate"
    if all(x["best_ratio"] >= PARAPHRASE_MATCH for x in p["uncovered_items"]):
        return "duplicate_candidate_review"
    return "contextual_duplicate"


pairs_df["relationship"] = pairs_df.apply(relationship, axis=1)
pairs_df["unique_information_flag"] = pairs_df["items_covered"] < pairs_df["items_total"]

print("\nRelationships:")
print(pairs_df.groupby(["scope", "relationship"]).size().rename("pairs"))
with pd.option_context("display.max_rows", None, "display.max_colwidth", 60):
    print(pairs_df[pairs_df["items_covered"] > 0].sort_values(["scope", "relationship", "unit_id"])[
        ["scope", "unit_id", "candidate_unit_id", "similarity_score", "items_covered", "items_total", "relationship"]])


# %% Phase 11 — Duplicate Decisions
# Canonical-source policy (plan §17), applied only when content is actually redundant:
# - **LPI Methodology is canonical** for indicator definitions, methodology and data construction:
#   table rows, abbreviations and Chapter 1 of this report.
# - **Connecting to Compete is canonical** for findings, figures and the policy framework
#   (About, Executive summary, Chapters 2–3): never suppressed cross-source.
# - The Methodology corpus is never modified; only units of this report can be suppressed.
# - Back cover (p.30): sentences repeating "About this report" are trimmed; new sentences kept.
# - Close paraphrases that cannot be decided automatically are **kept** as `manual_review`.
#
# Every decision, every candidate pair and every removed item is written to the duplicate audit.

# =========================================================
# 11.1 Canonical-source policy
# =========================================================
# Only units of THIS source can be suppressed; the Methodology corpus is never modified.
# Methodology is canonical for indicator definitions, methodology and data construction:
#   table rows, abbreviations, and Chapter 1 ("Introducing the 2025 LPI 2.0").
# Connecting to Compete is canonical for findings, figures and the policy framework
#   (About, Executive summary, Chapters 2–3): those units are never suppressed cross-source.
# Within this source, the back cover (p.30) restates "About this report": its repeated
# sentences are trimmed and only its new sentences are kept (decision recorded in 2.4).

METHODOLOGY_CANONICAL_SECTIONS = {"Chapter 1: Introducing the 2025 LPI 2.0"}

# Owner decision (2026-09-25): "remove everything that is repeated".
#  - contextual duplicates in Methodology-canonical sections: repeated sentences are TRIMMED,
#    only the sentences carrying new information are kept;
#  - the three duplicate_candidate_review units were reviewed: their only uncovered sentence is a
#    rewording of a Methodology sentence with no new fact -> suppressed.
TRIM_CONTEXTUAL_DUPLICATES = True
REVIEWED_DUPLICATE_DECISIONS = {
    "P021": "Only uncovered sentence rewords Methodology P009 ('observations collected throughout the year' "
            "= 'a full year of observed logistics activity'); no new fact.",
    "P025": "Only uncovered sentence equals Methodology P014 plus the mode names '(maritime, air, and postal)', "
            "which are stated in the same Methodology section; no new fact.",
    "P031": "Only uncovered sentence ('The fourth indicator measures…') equals Methodology P024 "
            "('Reference dwell time at port of arrival measures…'); no new fact.",
}


def methodology_is_canonical(u) -> bool:
    return u["unit_type"] in ("table_row", "definitions") or u["section"] in METHODOLOGY_CANONICAL_SECTIONS


def union_coverage(unit_id: str, scope: str, exclude_ids: set = frozenset()) -> tuple[list, list, list]:
    """Items of `unit_id` covered by ANY candidate in scope; returns (covered, uncovered, candidate_ids)."""
    ps = pairs_df[(pairs_df["unit_id"] == unit_id) & (pairs_df["scope"] == scope)
                  & ~pairs_df["candidate_unit_id"].isin(exclude_ids)]
    if ps.empty:
        return [], [], []
    n_items = ps.iloc[0]["items_total"]
    covered_by = {}
    for p in ps.itertuples():
        for k, it in enumerate(p.item_details):
            if it["covered"]:
                covered_by.setdefault(k, p.candidate_unit_id)
    items = ps.iloc[0]["item_details"]
    covered = [(items[k]["item"], covered_by[k]) for k in sorted(covered_by)]
    uncovered = [items[k] for k in range(n_items) if k not in covered_by]
    return covered, uncovered, sorted(set(covered_by.values()))

# =========================================================
# 11.2 Suppress true duplicates / 11.3 preserve contextual duplicates
# =========================================================
decisions = []
for u in units_df.to_dict("records"):
    uid = u["unit_id"]
    rec = {"unit_id": uid, "unit_type": u["unit_type"], "section": u["section"],
           "relationship": "unique", "action": "keep", "canonical_unit_ids": [], "canonical_source": None,
           "removed_items": [], "reason": "No candidate duplicate."}

    # ---- cross-source ----
    cov, unc, cands = union_coverage(uid, "cross")
    if cov or unc:
        best = pairs_df[(pairs_df["unit_id"] == uid) & (pairs_df["scope"] == "cross")]
        if not unc:
            rel = "exact_duplicate" if best["exact"].any() else "near_duplicate"
        elif all(x["best_ratio"] >= PARAPHRASE_MATCH for x in unc) and cov:
            rel = "duplicate_candidate_review"
        elif cov:
            rel = "contextual_duplicate"
        else:
            rel = "unique"
        rec["relationship"] = rel
        if rel in ("exact_duplicate", "near_duplicate") and methodology_is_canonical(u):
            rec.update(action="suppress_duplicate", canonical_unit_ids=cands, canonical_source="LPI_Methodology",
                       removed_items=[c[0] for c in cov],
                       reason="All items repeated in the Methodology report, which is canonical for this content.")
        elif rel in ("exact_duplicate", "near_duplicate"):
            rec.update(action="keep_canonical_here", canonical_unit_ids=[uid], canonical_source=SOURCE_NAME,
                       reason="Repeated in Methodology, but this report is canonical for findings / policy content.")
        elif rel == "duplicate_candidate_review" and uid in REVIEWED_DUPLICATE_DECISIONS:
            rec.update(action="suppress_duplicate", canonical_unit_ids=cands, canonical_source="LPI_Methodology",
                       removed_items=[c[0] for c in cov] + [x["item"] for x in unc],
                       reason="Manual review: " + REVIEWED_DUPLICATE_DECISIONS[uid])
        elif rel == "duplicate_candidate_review":
            rec.update(action="manual_review", canonical_unit_ids=cands, canonical_source="LPI_Methodology",
                       reason="Uncovered items are close paraphrases; kept (preservation-first) pending review: "
                              + " | ".join(f"{x['best_ratio']}: {x['item'][:70]}" for x in unc))
        elif rel == "contextual_duplicate" and TRIM_CONTEXTUAL_DUPLICATES and methodology_is_canonical(u):
            rec.update(action="trim_duplicate_sentences", canonical_unit_ids=cands, canonical_source="LPI_Methodology",
                       removed_items=[c[0] for c in cov],
                       reason=f"{len(cov)} sentence(s) repeated in Methodology trimmed; "
                              f"{len(unc)} sentence(s) with new information kept.")
        elif rel == "contextual_duplicate":
            rec.update(action="keep_contextual", canonical_unit_ids=cands, canonical_source="LPI_Methodology",
                       reason=f"{len(unc)} item(s) carry information not in Methodology.")

    # ---- within-source: back cover vs the rest of the report ----
    if u["page_start"] == LAST_PAGE and rec["action"] != "suppress_duplicate":
        back_cover_ids = set(units_df.loc[units_df["page_start"] == LAST_PAGE, "unit_id"])
        cov_w, unc_w, cands_w = union_coverage(uid, "within", exclude_ids=back_cover_ids)
        if cov_w and unc_w:
            rec.update(relationship="contextual_duplicate", action="trim_duplicate_sentences",
                       canonical_unit_ids=cands_w, canonical_source=SOURCE_NAME,
                       removed_items=[c[0] for c in cov_w],
                       reason=f"Back cover: {len(cov_w)} sentence(s) repeat {cands_w}; {len(unc_w)} new sentence(s) kept.")
        elif cov_w and not unc_w:
            rec.update(relationship="near_duplicate", action="suppress_duplicate", canonical_unit_ids=cands_w,
                       canonical_source=SOURCE_NAME, removed_items=[c[0] for c in cov_w],
                       reason="Back cover restates this report's own text.")
    decisions.append(rec)

decisions_df = pd.DataFrame(decisions)

# =========================================================
# 11.4 Duplicate audit (pair level + unit level)
# =========================================================
audit_pairs_df = pairs_df.assign(
    source_document=SOURCE_NAME,
    normalized_hash=pairs_df["unit_id"].map(units_df.set_index("unit_id")["norm_hash"]),
    length_ratio=[
        round(units_df.set_index("unit_id").at[p.unit_id, "char_count"]
              / max(1, len(next((m["content"] for m in methodology_units if m["unit_id"] == p.candidate_unit_id), "")
                         if p.scope == "cross" else units_df.set_index("unit_id").at[p.candidate_unit_id, "content"])), 2)
        for p in pairs_df.itertuples()
    ],
)[["source_document", "scope", "unit_id", "unit_type", "candidate_source", "candidate_unit_id", "candidate_type",
   "relationship", "similarity_score", "exact", "items_covered", "items_total", "unique_information_flag",
   "length_ratio", "normalized_hash", "uncovered_items"]]

# =========================================================
# 11.5 Post-dedup corpus
# =========================================================
def apply_decision(u, d):
    if d["action"] == "trim_duplicate_sentences":
        kept = [s for s in sentences(u["content"]) if s not in set(d["removed_items"])]
        return " ".join(kept)
    return u["content"]


dec_by_id = decisions_df.set_index("unit_id")
final_units_df = units_df[~units_df["unit_id"].map(dec_by_id["action"]).eq("suppress_duplicate")].copy()
final_units_df["content"] = [apply_decision(u, dec_by_id.loc[u["unit_id"]]) for u in final_units_df.to_dict("records")]
final_units_df["dedup_action"] = final_units_df["unit_id"].map(dec_by_id["action"])
final_units_df["char_count"] = final_units_df["content"].str.len()
final_units_df = final_units_df.reset_index(drop=True)

print("Unit-level decisions:")
print(decisions_df.groupby(["relationship", "action"]).size().rename("units"))
with pd.option_context("display.max_rows", None, "display.max_colwidth", 110):
    print(decisions_df[decisions_df["action"] != "keep"][["unit_id", "relationship", "action", "canonical_unit_ids", "reason"]])
print("\nTrimmed units — kept text:")
for r in final_units_df[final_units_df["dedup_action"] == "trim_duplicate_sentences"].itertuples():
    print(f"--- {r.unit_id}: {r.content}")
print(f"\nUnits: {len(units_df)} -> post-dedup: {len(final_units_df)}")


# %% Phase 12 — Final Logical-Unit QA
# Gate before chunking: every unit is kept or suppressed with a canonical mapping, every
# confirmed table/figure is accounted for, informative notes are not lost, no unit carrying
# unique information is suppressed, and the decisions match the reviewed snapshot.

# =========================================================
# 12.1 Content samples (deterministic)
# =========================================================
SAMPLE_IDS = ["P003", "P007", "P023", "P029", "P063", "P111", "figure_2.8", "table_1.2_postal", "abbr_ppp"]
for uid in SAMPLE_IDS:
    d = dec_by_id.loc[uid]
    u = final_units_df.set_index("unit_id").loc[uid] if uid in set(final_units_df["unit_id"]) else None
    print(f"--- {uid} | {d['relationship']} -> {d['action']}")
    print((u["content"][:400] + " …") if u is not None else f"(suppressed; canonical: {d['canonical_unit_ids']})")

# =========================================================
# 12.2 Coverage checks
# =========================================================
final_ids = set(final_units_df["unit_id"])
suppressed = decisions_df[decisions_df["action"] == "suppress_duplicate"]

# every unit is either kept or suppressed with a canonical mapping
assert set(units_df["unit_id"]) == final_ids | set(suppressed["unit_id"])
assert suppressed["canonical_unit_ids"].map(len).gt(0).all(), "Suppressed unit without canonical mapping."

# structured elements: every confirmed table/figure is kept, skipped by the gate, or suppressed as duplicate
for kind, num in zip(caption_inventory["kind"], caption_inventory["number"]):
    ids = units_df.loc[units_df[f"{kind}_number"] == num, "unit_id"]
    if kind == "figure" and num in set(figure_gate_df.loc[figure_gate_df["decision"] == "skip", "figure_number"]):
        assert ids.empty
        continue
    assert len(ids) >= 1, f"{kind} {num} has no unit."
    for uid in ids:
        assert uid in final_ids or uid in set(suppressed["unit_id"])

# kept figures appear exactly once; no caption leaked into paragraphs
assert final_units_df.loc[final_units_df["unit_type"] == "figure", "figure_number"].is_unique
assert not final_units_df.loc[final_units_df["unit_type"] == "paragraph", "content"].str.match(LABEL_RE).any()

# informative notes: present in a kept unit, or inside a suppressed unit whose items are all covered
kept_text = "\n".join(final_units_df["content"])
for n in note_registry_df.loc[note_registry_df["policy"] == "informative", "note_no"]:
    owner = units_df[units_df["footnote_refs"].map(lambda refs: n in refs)]["unit_id"].iloc[0]
    if f"Note: {note_text[n]}" in kept_text:
        continue
    d = dec_by_id.loc[owner]
    if d["action"] == "suppress_duplicate":
        continue
    # trimmed: every sentence of the note was matched in the canonical copy and removed as repeated
    assert d["action"] == "trim_duplicate_sentences" and \
        all(s in d["removed_items"] for s in sentences(f"Note: {note_text[n]}")), f"Informative note {n} lost."

# =========================================================
# 12.3 Duplicate suppression checks
# =========================================================
assert pairs_df["relationship"].notna().all()
meth_ids = {m["unit_id"] for m in methodology_units}
for d in suppressed.itertuples():
    if d.canonical_source != "LPI_Methodology":
        continue
    cov, unc, _ = union_coverage(d.unit_id, "cross")
    if d.unit_id in REVIEWED_DUPLICATE_DECISIONS:
        # reviewed: every uncovered item must at least be a close paraphrase
        assert all(x["best_ratio"] >= PARAPHRASE_MATCH for x in unc), f"{d.unit_id}: not a paraphrase."
    else:
        assert not unc, f"{d.unit_id} was suppressed although it carries unique information."
for d in decisions_df[decisions_df["action"] == "trim_duplicate_sentences"].itertuples():
    kept = final_units_df.set_index("unit_id").at[d.unit_id, "content"]
    assert kept and all(item not in kept for item in d.removed_items), f"{d.unit_id}: trim failed."
    pool = meth_ids if d.canonical_source == "LPI_Methodology" else final_ids
    assert set(d.canonical_unit_ids) <= pool, f"{d.unit_id}: canonical copy of trimmed sentences missing."

# reviewed snapshot (2026-09-25)
REVIEWED_SUPPRESSED = sorted(["abbr_b2b", "abbr_b2c", "abbr_lldc", "abbr_lpi", "abbr_lpi_2_0", "P020", "P021", "P023",
                              "P024", "P025", "P028", "P031", "P032", "table_1.1_maritime", "table_1.1_aviation",
                              "table_1.1_postal", "table_1.2_maritime", "table_1.2_postal"])
REVIEWED_TRIMMED = sorted(["P022", "P029", "P030", "P033", "P035", "P111", "P112"])
REVIEWED_MANUAL_REVIEW = []
assert sorted(decisions_df.loc[decisions_df["action"] == "trim_duplicate_sentences", "unit_id"]) == REVIEWED_TRIMMED
assert sorted(suppressed["unit_id"]) == REVIEWED_SUPPRESSED, "Suppression set drifted from the reviewed snapshot."
assert sorted(decisions_df.loc[decisions_df["action"] == "manual_review", "unit_id"]) == REVIEWED_MANUAL_REVIEW

print("\n✅ Final logical-unit QA passed.")
print(f"Units: {len(units_df)} -> kept {len(final_units_df)} | suppressed {len(suppressed)} | "
      f"trimmed {int((decisions_df['action'] == 'trim_duplicate_sentences').sum())} | "
      f"manual review pending {len(REVIEWED_MANUAL_REVIEW)}")
print(final_units_df["unit_type"].value_counts().rename("kept units"))


# %% Phase 13 — Save Extracted + Cleaned Artifacts
# One file per layer:
# - `extracted/…_extracted.json` — raw structured layer: page classes, section map, captions,
#   regions, tables, figure gate/elements, notes, markers, body lines, paragraphs
# - `cleaned/…_logical_units.json` — **the single cleaned file**: `source`, `units` (post-dedup units that
#   feed chunking) and `duplicate_audit` (thresholds, canonical policy, unit decisions, candidate pairs);
#   Phase 19 adds `coverage_audit` to the same file
#
# Each file is reloaded from disk and re-validated.

# =========================================================
# 13. Save extracted + cleaned artifacts, then reload and validate
# =========================================================

def to_records(df: pd.DataFrame) -> list[dict]:
    return json.loads(df.to_json(orient="records", force_ascii=False, default_handler=str))


EXTRACTED_PATH = EXTRACTED_DIR / f"{SOURCE_NAME}_extracted.json"
LOGICAL_UNITS_PATH = CLEANED_DIR / f"{SOURCE_NAME}_logical_units.json"   # the ONE cleaned file of this source

# earlier runs wrote the audits as separate files; the cleaned layer is now a single file
for legacy in (CLEANED_DIR / f"{SOURCE_NAME}_duplicate_audit.json", CLEANED_DIR / f"{SOURCE_NAME}_coverage_audit.json"):
    if legacy.exists():
        legacy.unlink()
        print("Removed legacy file:", legacy.name)

extracted_payload = {
    "source": {**source_metadata, "sha256": SOURCE_SHA256, "pages": int(len(pages_df))},
    "page_classification": to_records(page_class_df[["page_number", "page_class", "keep_for_retrieval",
                                                     "is_auxiliary", "reason"]]),
    "section_map": to_records(section_map[["heading_id", "page_number", "column", "y0", "level", "role",
                                           "heading_text", "section", "subsection"]]),
    "captions": to_records(caption_inventory),
    "structured_regions": to_records(structured_regions_df),
    "tables": to_records(structured_units_df[structured_units_df["unit_type"] == "table_row"]
                         [["unit_id", "table_number", "logistics_mode", "indicators", "source_note"]]),
    "figures": {"gate": to_records(figure_gate_df), "elements": to_records(figure_elements_df)},
    "notes": to_records(note_registry_df[["note_no", "text", "policy", "policy_reason", "policy_source",
                                          "review_comment"]]),
    "note_markers": to_records(note_refs_df[["page_number", "column", "y0", "marker", "note_nos"]]),
    "body_lines": to_records(body_lines_df[["line_uid", "page_number", "column", "y0", "text", "note_nos",
                                            "line_break", "is_bullet_start"]]),
    "paragraphs": to_records(paragraphs_df[["paragraph_id", "text", "page_start", "page_end", "boundary_reason",
                                            "is_bullet", "runin_heading", "footnote_refs", "line_uids"]]),
}
UNIT_FIELDS = ["unit_id", "unit_type", "logical_unit", "title", "content", "section", "subsection", "subsection_path",
               "page_start", "page_end", "table_number", "figure_number", "footnote_refs", "is_bullet",
               "runin_heading", "provenance", "flag", "dedup_action"]
duplicate_audit = {
    "thresholds": {"CANDIDATE_SIM": CANDIDATE_SIM, "SENTENCE_MATCH": SENTENCE_MATCH,
                   "PARAPHRASE_MATCH": PARAPHRASE_MATCH},
    "reference": str(METHODOLOGY_UNITS_PATH.name),
    "canonical_policy": {"LPI_Methodology": ["table_row", "definitions", *sorted(METHODOLOGY_CANONICAL_SECTIONS)],
                         SOURCE_NAME: "all other sections (findings, figures, policy framework)"},
    "unit_decisions": to_records(decisions_df),
    "pairs": to_records(audit_pairs_df),
}

EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)
EXTRACTED_PATH.write_text(json.dumps(extracted_payload, ensure_ascii=False, indent=1), encoding="utf-8")
# cleaned file = post-dedup units + the duplicate audit (the coverage audit is added in Phase 19)
cleaned_payload = {
    "source": {**source_metadata, "sha256": SOURCE_SHA256},
    "units": to_records(final_units_df[UNIT_FIELDS]),
    "duplicate_audit": duplicate_audit,
}
LOGICAL_UNITS_PATH.write_text(json.dumps(cleaned_payload, ensure_ascii=False, indent=1), encoding="utf-8")

# ---- reload + validate ----
re_extracted = json.loads(EXTRACTED_PATH.read_text(encoding="utf-8"))
re_cleaned = json.loads(LOGICAL_UNITS_PATH.read_text(encoding="utf-8"))
re_units, re_audit = re_cleaned["units"], re_cleaned["duplicate_audit"]

assert re_extracted["source"]["sha256"] == SOURCE_SHA256
assert len(re_extracted["paragraphs"]) == len(paragraphs_df) and len(re_extracted["notes"]) == 33
assert [u["unit_id"] for u in re_units] == final_units_df["unit_id"].tolist()
assert all(u["content"] == c for u, c in zip(re_units, final_units_df["content"]))
assert len(re_audit["unit_decisions"]) == len(units_df)

assert sorted(p.name for p in CLEANED_DIR.glob(f"{SOURCE_NAME}_*")) == [LOGICAL_UNITS_PATH.name], \
    "The cleaned layer of this source must be exactly one file."
for p in (EXTRACTED_PATH, LOGICAL_UNITS_PATH):
    print(f"Saved + reloaded: {p.name:55} {p.stat().st_size:>9,} bytes")


# %% Phase 14 — Semantic Chunking
# Same philosophy as `LPI_methodology_chunking.ipynb`: paragraphs are never split; adjacent
# paragraphs of the same section/subsection are grouped only while short (`MIN_CHUNK_CHARS`),
# so bullet items join their introductory sentence; `MAX_CHUNK_CHARS` is a safety cap, applied at
# sentence (or table-indicator) boundaries. Figures are one self-contained chunk each; the
# abbreviations that survive dedup form one chunk. Chunk IDs use the prefix `lpi2025_`.

# =========================================================
# 14.1 Chunking rules
# =========================================================
# Same philosophy as LPI_methodology_chunking.ipynb:
# - paragraphs: never split; adjacent paragraphs of the SAME section/subsection are grouped when
#   the group or the next paragraph is shorter than MIN_CHUNK_CHARS, up to MAX_CHUNK_CHARS
#   (bullet items therefore join their introductory sentence)
# - a unit longer than MAX_CHUNK_CHARS is split at sentence boundaries (safety cap only)
# - table rows: one chunk per logical row; a row over the cap is split per indicator,
#   each part repeating the table/row header
# - figures: one self-contained chunk each
# - abbreviations kept after dedup: one "abbreviations" chunk
# chunk_id prefix "lpi2025_" keeps IDs distinct from the Methodology corpus ("lpi_").

CHUNK_SEPARATOR = "\n\n"
CHUNK_PREFIX = "lpi2025"


def location(u) -> tuple:
    return (u["section"], u["subsection"])


def split_by_sentences(text: str, limit: int = MAX_CHUNK_CHARS) -> list[str]:
    parts, current = [], ""
    for s in sentences(text):
        if current and len(current) + 1 + len(s) > limit:
            parts.append(current)
            current = s
        else:
            current = f"{current} {s}".strip()
    return parts + ([current] if current else [])


def split_table_row(u) -> list[str]:
    if u["char_count"] <= MAX_CHUNK_CHARS:
        return [u["content"]]
    lines = u["content"].split("\n")
    header, parts, column = lines[:2], [], None
    for line in lines[2:]:
        if not line.startswith("- "):
            column = line
        else:
            parts.append("\n".join(header + [column, line]))
    return parts


def chunk_title(u) -> str:
    if isinstance(u["title"], str) and u["title"]:
        return u["title"]
    return u["subsection_path"][-1] if u["subsection_path"] else u["section"]


def make_chunk(units: list[dict], unit_type: str, logical_unit: str, part: int, text: str,
               title: str | None = None) -> dict:
    first = units[0]
    return {
        "page": int(min(u["page_start"] for u in units)),
        "unit_type": unit_type,
        "logical_unit": logical_unit,
        "chunk_id": f"{CHUNK_PREFIX}_{logical_unit}_chunk_{part}",
        "section": first["section"],
        "subsection_path": list(first["subsection_path"]),
        "title": title or chunk_title(first),
        "text": text,
        "source_unit_ids": [u["unit_id"] for u in units],
    }

# =========================================================
# 14.2 Build paragraph chunks
# =========================================================
unit_dicts = final_units_df.to_dict("records")
paragraph_units = [u for u in unit_dicts if u["unit_type"] == "paragraph"]

groups = []
for u in paragraph_units:
    if groups and location(groups[-1][-1]) == location(u):
        group_size = len(CHUNK_SEPARATOR.join(x["content"] for x in groups[-1]))
        merged_size = group_size + len(CHUNK_SEPARATOR) + u["char_count"]
        if merged_size <= MAX_CHUNK_CHARS and (group_size < MIN_CHUNK_CHARS or u["char_count"] < MIN_CHUNK_CHARS):
            groups[-1].append(u)
            continue
    groups.append([u])

chunk_records = []
for g in groups:
    name = g[0]["logical_unit"] if len(g) == 1 else f"{g[0]['logical_unit']}_{g[-1]['logical_unit'].split('_')[-1]}"
    text = CHUNK_SEPARATOR.join(x["content"] for x in g)
    pieces = [text] if len(text) <= MAX_CHUNK_CHARS else split_by_sentences(text)
    for part, piece in enumerate(pieces, start=1):
        chunk_records.append(make_chunk(g, "paragraph", name, part, piece))

# =========================================================
# 14.3 Build structured chunks
# =========================================================
for u in unit_dicts:
    if u["unit_type"] == "table_row":
        for part, piece in enumerate(split_table_row(u), start=1):
            chunk_records.append(make_chunk([u], "table_row", u["logical_unit"], part, piece))
    elif u["unit_type"] == "figure":
        pieces = [u["content"]] if u["char_count"] <= MAX_CHUNK_CHARS else split_by_sentences(u["content"])
        for part, piece in enumerate(pieces, start=1):
            chunk_records.append(make_chunk([u], "figure", u["logical_unit"], part, piece))

definition_units = [u for u in unit_dicts if u["unit_type"] == "definitions"]
if definition_units:
    chunk_records.append(make_chunk(definition_units, "definitions", "abbreviations", 1,
                                    "Abbreviations\n" + "\n".join(u["content"] for u in definition_units),
                                    title="Abbreviations"))

order_of = {uid: k for k, uid in enumerate(final_units_df["unit_id"])}
chunk_records.sort(key=lambda r: order_of[r["source_unit_ids"][0]])

print(f"Kept units: {len(unit_dicts)} -> chunks: {len(chunk_records)}")
print(pd.Series([r["unit_type"] for r in chunk_records]).value_counts().rename("chunks"))
print("\nParagraph chunks built from several units:")
print(pd.DataFrame([{"chunk_id": r["chunk_id"], "units": r["source_unit_ids"], "chars": len(r["text"])}
                      for r in chunk_records if len(r["source_unit_ids"]) > 1]))


# %% Phase 15 — Chunk Validation
# Size and ID checks, content preservation of every kept unit, no suppressed unit re-entering
# through grouping, and no chunk crossing a section/subsection boundary.

# =========================================================
# 15.1 Size checks
# =========================================================
chunk_sizes = pd.Series([len(r["text"]) for r in chunk_records])
assert (chunk_sizes > 0).all(), "Empty chunk."
assert (chunk_sizes <= MAX_CHUNK_CHARS).all(), "A chunk exceeds MAX_CHUNK_CHARS."
chunk_ids = [r["chunk_id"] for r in chunk_records]
assert len(chunk_ids) == len(set(chunk_ids)), "Duplicate chunk_id."

# =========================================================
# 15.2 Coverage checks
# =========================================================
texts_by_unit: dict[str, list[str]] = {}
for r in chunk_records:
    for uid in r["source_unit_ids"]:
        texts_by_unit.setdefault(uid, []).append(r["text"])
units_by_id = {u["unit_id"]: u for u in unit_dicts}

assert set(texts_by_unit) == set(units_by_id), "A kept unit is missing from the chunks."
for uid, u in units_by_id.items():
    joined = "\n".join(texts_by_unit[uid])
    pieces = [s for line in u["content"].split("\n") for s in (sentences(line) if u["unit_type"] != "table_row" else [line])]
    for piece in pieces:
        assert piece.strip() in joined, f"Content of {uid} not preserved: {piece[:60]!r}"

# no suppressed duplicate re-enters through grouping
suppressed_ids = set(suppressed["unit_id"])
assert not any(set(r["source_unit_ids"]) & suppressed_ids for r in chunk_records)

# =========================================================
# 15.3 Provenance checks
# =========================================================
for r in chunk_records:
    locs = {location(units_by_id[uid]) for uid in r["source_unit_ids"]}
    assert len(locs) == 1, f"{r['chunk_id']} crosses a section/subsection boundary."
    assert r["section"] and r["title"], f"{r['chunk_id']} lacks section/title."

print("✅ Chunk validation passed.")
print("Chunk size:", chunk_sizes.describe()[["count", "min", "50%", "mean", "max"]].round(0).to_dict())
print(f"Below MIN_CHUNK_CHARS: {int((chunk_sizes < MIN_CHUNK_CHARS).sum())} "
      "(isolated short units that have no same-section neighbour to merge with)")
print(pd.DataFrame([{"chunk_id": r["chunk_id"], "chars": len(r["text"]), "text": r["text"][:80]}
                      for r in sorted(chunk_records, key=lambda r: len(r["text"]))[:6]]))


# %% Phase 16 — Unified 16-Column Schema (ADR-009)
# Identical schema, dtypes and validation as the Methodology / FBL / Suez notebooks.
# `parent_chunk` = section, `sub_chunk` = subsection heading path (list), document metadata from Phase 0.
# Audit and dedup metadata stay in their own files, never in the chunk schema.

# =========================================================
# 16.1 Schema definition (identical to LPI_methodology / FBL / Suez notebooks — ADR-009)
# =========================================================
CHUNK_SCHEMA = {
    "page": "Int64", "unit_type": "string", "logical_unit": "string", "chunk_id": "string",
    "parent_chunk": "string", "sub_chunk": "object", "title": "string", "text": "string",
    "char_count": "Int64", "filename": "string", "source": "string", "real_or_synthetic": "string",
    "document_type": "string", "department": "string", "sensitivity_level": "Int64", "version_date": "string",
}
REQUIRED_CHUNK_FIELDS = ["unit_type", "logical_unit", "chunk_id", "text", "char_count", "filename", "source",
                         "real_or_synthetic", "document_type", "department", "sensitivity_level"]


def validate_chunk_schema(chunks_df: pd.DataFrame, label: str) -> None:
    has_sub = chunks_df["sub_chunk"].apply(lambda v: v is not None and not (isinstance(v, float) and np.isnan(v))
                                           and len(v) > 0)
    checks = {
        "columns_match_schema": list(chunks_df.columns) == list(CHUNK_SCHEMA),
        "dtypes_match_schema": chunks_df.dtypes.astype(str).equals(pd.Series(CHUNK_SCHEMA).astype(str)),
        "required_fields_complete": not chunks_df[REQUIRED_CHUNK_FIELDS].isna().any().any(),
        "chunk_id_unique": chunks_df["chunk_id"].is_unique,
        "text_non_empty": chunks_df["text"].str.strip().ne("").all(),
        "char_count_matches_text_length": (chunks_df["text"].str.len() == chunks_df["char_count"]).all(),
        "sensitivity_level_in_range": chunks_df["sensitivity_level"].isin([1, 2, 3]).all(),
        "sub_chunk_requires_parent_chunk": (~has_sub | chunks_df["parent_chunk"].notna()).all(),
    }
    print(f"--- Schema validation: {label} ---")
    for name, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    failed = [n for n, ok in checks.items() if not ok]
    assert not failed, f"{label}: failed checks -> {failed}"

# =========================================================
# 16.2 Metadata mapping
# =========================================================
chunk_metadata = {
    "filename": SOURCE_FILE,
    "source": "The World Bank",
    "real_or_synthetic": REAL_OR_SYNTHETIC,
    "document_type": DOCUMENT_TYPE,
    "department": DEPARTMENT,
    "sensitivity_level": SENSITIVITY_LEVEL,
    "version_date": VERSION_DATE,
}

chunks_df = pd.DataFrame([
    {
        "page": r["page"],
        "unit_type": r["unit_type"],
        "logical_unit": r["logical_unit"],
        "chunk_id": r["chunk_id"],
        "parent_chunk": r["section"],
        "sub_chunk": list(r["subsection_path"]) or None,
        "title": r["title"],
        "text": r["text"],
        "char_count": len(r["text"]),
        **chunk_metadata,
    }
    for r in chunk_records
])[list(CHUNK_SCHEMA)].astype(CHUNK_SCHEMA)

# =========================================================
# 16.3 Schema validation
# =========================================================
validate_chunk_schema(chunks_df, "LPI_Connecting_to_Compete chunks")
print(chunks_df[["page", "unit_type", "logical_unit", "chunk_id", "parent_chunk", "title", "char_count"]].head(10))
print(chunks_df[list(chunk_metadata)].drop_duplicates())


# %% Phase 17 — Save + Reload
# The Parquet file on disk — not the in-memory frame — is the artifact that must pass validation.

# =========================================================
# 17.1 Save Parquet / 17.2 Reload / 17.3 Revalidate
# =========================================================
CHUNKS_PATH = CHUNKS_DIR / f"{SOURCE_NAME}_chunks.parquet"
chunks_df.to_parquet(CHUNKS_PATH, index=False)

reloaded_df = pd.read_parquet(CHUNKS_PATH).astype(CHUNK_SCHEMA)
validate_chunk_schema(reloaded_df, "LPI_Connecting_to_Compete chunks (reloaded from disk)")

assert len(reloaded_df) == len(chunks_df)
assert reloaded_df["chunk_id"].tolist() == chunks_df["chunk_id"].tolist()
for col in [c for c in CHUNK_SCHEMA if c != "sub_chunk"]:
    assert reloaded_df[col].equals(chunks_df[col]), f"Column {col} changed on disk."
as_list = lambda v: None if v is None or (isinstance(v, float) and np.isnan(v)) else list(v)
assert reloaded_df["sub_chunk"].map(as_list).tolist() == chunks_df["sub_chunk"].map(as_list).tolist()

print(f"✅ Saved and revalidated: {CHUNKS_PATH.name} ({CHUNKS_PATH.stat().st_size:,} bytes, {len(reloaded_df)} chunks)")


# %% Phase 18 — Cross-Source Validation
# The new chunks must concatenate cleanly with the LPI Methodology, FBL and Suez chunks:
# same columns, same order, same dtypes, no `chunk_id` collision.

# =========================================================
# 18.1 Compare schemas / 18.2 dtypes / 18.3 chunk_id collisions / 18.4 concatenate
# =========================================================
other_chunk_paths = {
    "LPI_Methodology": CHUNKS_DIR / "LPI_Methodology_chunks.parquet",
    "FBL": CHUNKS_DIR / "FBL_template_chunks.parquet",
    "Suez": CHUNKS_DIR / "suez_notes_chunks.parquet",
}
loaded_chunks = {SOURCE_NAME: reloaded_df}
for label, path in other_chunk_paths.items():
    assert path.exists(), f"{label} chunks not found at {path}"
    loaded_chunks[label] = pd.read_parquet(path)

for label, frame in loaded_chunks.items():
    assert list(frame.columns) == list(reloaded_df.columns), f"{label}: columns differ."
    assert frame.dtypes.astype(str).equals(reloaded_df.dtypes.astype(str)), f"{label}: dtypes differ."

combined_chunks_df = pd.concat(loaded_chunks.values(), ignore_index=True)
assert combined_chunks_df["chunk_id"].is_unique, "chunk_id collision across sources."
assert combined_chunks_df["department"].isin(["Operations", "Finance"]).all()

print("===================================")
print("UNIFIED SCHEMA CROSS-SOURCE CHECK: PASSED")
print("===================================")
print(combined_chunks_df.groupby(["filename", "document_type"]).size().rename("chunks"))
print("Combined rows:", len(combined_chunks_df))


# %% Phase 19 — Whole-PDF Coverage Audit
# Proof that nothing was dropped silently. Every text line of all 30 pages receives exactly one
# disposition — `in_chunks`, `metadata` (headings), `suppressed_duplicate` (repeated in LPI Methodology),
# `trimmed_duplicate` (back cover), `note_metadata` (citation-only notes), `figure_internal` /
# `figure_skipped` (chart ticks, labels, gated figures), `layout_excluded`, or `page_excluded:<class>` —
# and every `in_chunks` claim is verified by text containment against the final chunks.
# The line-level result is added to the single cleaned file (`cleaned/…_logical_units.json`, key `coverage_audit`).

# =========================================================
# 19.1 Line-level disposition of the WHOLE PDF (all pages, every text line)
# =========================================================
# Goal: prove that nothing was dropped silently. Every text line of the PDF must end in
# exactly one of these dispositions, and every "in_chunks" claim is verified by text
# containment against the final chunk texts (letters/digits only, so hyphenation and
# whitespace differences cannot hide a loss).

def letters_only(t: str) -> str:
    return re.sub(r"[^0-9a-z]", "", unicodedata.normalize("NFKC", str(t)).replace("­", "").lower())


chunk_corpus = letters_only(" ".join(chunks_df["text"]))
suppressed_corpus = letters_only(" ".join(units_df.loc[units_df["unit_id"].isin(suppressed_ids), "content"]))
methodology_corpus = letters_only(" ".join(u["content"] for u in methodology_units))
trimmed_corpus = letters_only(" ".join(
    item for d in decisions_df[decisions_df["action"] == "trim_duplicate_sentences"].itertuples() for item in d.removed_items))
citation_corpus = letters_only(" ".join(note_registry_df.loc[note_registry_df["policy"] == "citation_only", "text"]))

line_to_paragraph = {uid: r.paragraph_id for r in paragraphs_df.itertuples() for uid in r.line_uids}
region_kind = {(r.kind, r.ref): r for r in structured_regions_df.itertuples()}
skipped_figs = set(figure_gate_df.loc[figure_gate_df["decision"] == "skip", "figure_number"])
reason_of = {(r.page_number, r.block_no, r.line_no): r.reason for r in rl.itertuples()}
body_uid_of = {(r.page_number, r.block_no, r.line_no): r.line_uid for r in body_lines_df.itertuples()}
page_class_map = page_class_df.set_index("page_number")["page_class"]


elem_role = {(r.page_number, r.y0, r.x0): r.role for r in figure_elements_df.itertuples()}
fig_chunk_text = {
    num: letters_only(" ".join(chunks_df.loc[chunks_df["logical_unit"] == f"figure_{num.replace('.', '_')}", "text"]))
    for num in figure_gate_df["figure_number"]
}
CAPTION_ROLES = {"label", "title", "panel_title", "source", "note"}


def region_of(p, x0, y0, x1, y1):
    for r in structured_regions_df.itertuples():
        if r.page_number == p and x1 > r.x0 and x0 < r.x1 and y1 > r.y0 and y0 < r.y1:
            return r
    return None


def disposition(r) -> tuple[str, str]:
    p, key, t = r.page_number, (r.page_number, r.block_no, r.line_no), letters_only(r.text)
    pclass = page_class_map[p]
    if not t:
        return "no_text", "bullet glyph / punctuation only"
    if r.zone in ("header", "footer"):
        return "layout_excluded", "running header/footer or page number"
    if pclass in ("cover_title", "legal", "contents", "acknowledgements", "references", "blank"):
        return f"page_excluded:{pclass}", "non-retrieval page (Phase 2)"
    if pclass == "abbreviations":
        if t == "abbreviations":
            return "metadata", "page heading"
        if t in chunk_corpus:
            return "in_chunks", "abbreviations chunk"
        if t in suppressed_corpus and t in methodology_corpus:
            return "suppressed_duplicate", "abbreviation already in LPI_Methodology (AB1)"
        return "UNACCOUNTED", ""
    if pclass == "notes_auxiliary":
        if t == "notes" or re.fullmatch(r"\d{1,2}", t):
            return "metadata", "Notes heading / note number"
        if t in chunk_corpus:
            return "in_chunks", "informative note appended to its paragraph"
        if t in citation_corpus:
            return "note_metadata", "citation-only note (kept as footnote_refs metadata)"
        if t in suppressed_corpus:
            return "suppressed_duplicate", "note of a paragraph suppressed as a Methodology duplicate (item-level match, Phase 10)"
        if t in trimmed_corpus:
            return "trimmed_duplicate", "note sentence repeated in Methodology, trimmed from its paragraph"
        return "UNACCOUNTED", ""
    reason = reason_of.get(key)
    if reason in ("header", "footer", "decoration"):
        return "layout_excluded", reason
    if reason == "heading":
        return "metadata", "heading -> parent_chunk / sub_chunk / title"
    if reason == "structured_region":
        reg = region_of(p, r.x0, r.y0, r.x1, r.y1)
        if reg.kind == "table":
            if t in chunk_corpus:
                return "in_chunks", f"table {reg.ref}"
            return ("suppressed_duplicate", f"table {reg.ref} identical to LPI_Methodology") \
                if t in methodology_corpus or t in suppressed_corpus else ("UNACCOUNTED", "")
        if reg.ref in skipped_figs:
            return "figure_skipped", f"figure {reg.ref}: value gate = skip (covered by prose)"
        role = elem_role.get((p, r.y0, r.x0))
        if role in CAPTION_ROLES:      # caption parts MUST be in this figure's own chunk
            return ("in_chunks", f"figure {reg.ref} ({role})") if t in fig_chunk_text[reg.ref] else ("UNACCOUNTED", role)
        if len(t) >= 12 and t in fig_chunk_text[reg.ref]:
            return "in_chunks", f"figure {reg.ref} ({role})"
        return "figure_internal", f"figure {reg.ref}: axis tick / category label / legend (described, not verbatim)"
    if reason == "body":
        uid = body_uid_of.get(key)
        if uid is None:
            return "no_text", "orphan bullet glyph"
        pid = line_to_paragraph[uid]
        act = dec_by_id.loc[pid, "action"]
        if act == "suppress_duplicate":
            return "suppressed_duplicate", f"{pid} repeated in LPI_Methodology {dec_by_id.loc[pid, 'canonical_unit_ids']}"
        body_text = letters_only(body_lines_df.set_index("line_uid").at[uid, "text"])
        if body_text in chunk_corpus:
            return "in_chunks", pid
        if act == "trim_duplicate_sentences":
            return "trimmed_duplicate", f"{pid}: sentence repeating {dec_by_id.loc[pid, 'canonical_source']} {dec_by_id.loc[pid, 'canonical_unit_ids']}"
        return "UNACCOUNTED", pid
    return "UNACCOUNTED", str(reason)


disp = lines_df.apply(disposition, axis=1)
coverage_df = lines_df[["page_number", "block_no", "line_no", "y0", "font", "text"]].assign(
    disposition=disp.str[0], detail=disp.str[1], chars=lines_df["text"].str.len())

# =========================================================
# 19.2 Coverage summary + assertions
# =========================================================
unaccounted = coverage_df[coverage_df["disposition"] == "UNACCOUNTED"]
print(f"Lines in PDF: {len(coverage_df)} | UNACCOUNTED: {len(unaccounted)}")
if len(unaccounted):
    print(unaccounted[["page_number", "text", "detail"]])
assert unaccounted.empty, "Some PDF lines are not accounted for."

# trimmed sentences: their canonical copy (matched item by item in Phase 10) is in the chunks
# (within-source) or in the Methodology units (cross-source)
chunked_units = {uid for r in chunk_records for uid in r["source_unit_ids"]}
for d in decisions_df[decisions_df["action"] == "trim_duplicate_sentences"].itertuples():
    pool = {m["unit_id"] for m in methodology_units} if d.canonical_source == "LPI_Methodology" else chunked_units
    assert set(d.canonical_unit_ids) <= pool, f"{d.unit_id}: canonical copy of trimmed sentences missing."

# suppressed units: EVERY item (sentence / indicator / abbreviation) was matched in the canonical source
units_by_uid = units_df.set_index("unit_id")
for d in suppressed.itertuples():
    u = units_by_uid.loc[d.unit_id].to_dict() | {"unit_id": d.unit_id}
    assert sorted(items_of_ours(u)) == sorted(d.removed_items), f"{d.unit_id}: not every item was matched."

summary = coverage_df.groupby("disposition").agg(lines=("text", "size"), chars=("chars", "sum"))
summary["share_chars"] = (summary["chars"] / summary["chars"].sum()).round(3)
print("\nWhere every line of the PDF went:")
print(summary.sort_values("chars", ascending=False))
print("\nPer page:")
with pd.option_context("display.max_rows", None):
    print(coverage_df.pivot_table(index="page_number", columns="disposition", values="text",
                                    aggfunc="count", fill_value=0))

# add the coverage audit to the single cleaned file, then reload and check
cleaned_payload = json.loads(LOGICAL_UNITS_PATH.read_text(encoding="utf-8"))
cleaned_payload["coverage_audit"] = {
    "summary": json.loads(summary.reset_index().to_json(orient="records")),
    "lines": to_records(coverage_df[["page_number", "block_no", "line_no", "disposition", "detail", "text"]]),
}
LOGICAL_UNITS_PATH.write_text(json.dumps(cleaned_payload, ensure_ascii=False, indent=1), encoding="utf-8")
re_cleaned = json.loads(LOGICAL_UNITS_PATH.read_text(encoding="utf-8"))
assert set(re_cleaned) == {"source", "units", "duplicate_audit", "coverage_audit"}
assert len(re_cleaned["coverage_audit"]["lines"]) == len(coverage_df)
assert len(re_cleaned["units"]) == len(final_units_df)
print(f"\n✅ Whole-PDF coverage audit passed. Added to: {LOGICAL_UNITS_PATH.name}")

# =========================================================
# Final Checkpoint
# =========================================================
print("=" * 70)
print("LPI CONNECTING TO COMPETE 2025 — INGESTION PIPELINE: FINAL CHECKPOINT")
print("=" * 70)
print(f"Source            : {SOURCE_FILE} | {len(pages_df)} pages | sha256 {SOURCE_SHA256[:16]}…")
print(f"Page classes      : {page_class_df['page_class'].value_counts().to_dict()}")
print(f"Retrieval pages   : {RETRIEVAL_PAGES}")
print(f"Headings          : {len(section_map)} {section_map['role'].value_counts().to_dict()}")
print(f"Captions          : {len(caption_inventory)} (tables 2, figures 10) | figure gate "
      f"{figure_gate_df['decision'].value_counts().to_dict()}")
print(f"Notes             : 33 {note_registry_df['policy'].value_counts().to_dict()}")
print(f"Body              : {len(body_lines_df)} lines -> {len(paragraphs_df)} paragraphs")
print(f"Logical units     : {len(units_df)} -> after dedup {len(final_units_df)} "
      f"(suppressed {len(suppressed)}, trimmed {int((decisions_df['action'] == 'trim_duplicate_sentences').sum())}, "
      f"manual review pending {int((decisions_df['action'] == 'manual_review').sum())})")
print(f"Chunks            : {len(reloaded_df)} {reloaded_df['unit_type'].value_counts().to_dict()} | "
      f"chars min/median/max = {reloaded_df['char_count'].min()}/{int(reloaded_df['char_count'].median())}/"
      f"{reloaded_df['char_count'].max()}")
print(f"Cross-source      : {len(combined_chunks_df)} chunks in the unified corpus, chunk_id unique")
print(f"Whole-PDF coverage: {len(coverage_df)} lines, 0 unaccounted")
assert final_units_df["flag"].isna().all(), "No unit may remain flagged."
print("\nPending manual review :", REVIEWED_MANUAL_REVIEW or "none")
print("Flagged units         : none")
print("\nArtifacts:")
for p in (EXTRACTED_PATH, LOGICAL_UNITS_PATH, CHUNKS_PATH):
    print(f"  {p.relative_to(PROJECT_ROOT)}")


# %% Final phase — Title / text normalization (ADR-041)
# One rule for the whole corpus: `title` is the chunk's location label, `text` the body only. The chunk file saved above is normalized in place by `pipelines/lib/chunks.py` (a leading heading line moves to `title`, a run-in heading is removed; lossless, idempotent, chunk ids and order unchanged), then checked against the contract and reloaded. The phases above validated the chunking itself, before this step.

import sys as _sys
from pathlib import Path as _Path

_root = next(p for p in [_Path.cwd(), *_Path.cwd().parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())
if str(_root) not in _sys.path:
    _sys.path.insert(0, str(_root))
from pipelines.lib import chunks as _chunk_contract

_kinds = _chunk_contract.normalize_chunk_file(_root / "Data" / "processed" / "rag" / "chunks" / "LPI_Connecting_to_Compete_chunks.parquet", {'heading_line': 8, 'run_in_heading': 9, 'unchanged': 52})
print(f"✅ Title / text normalization passed (ADR-041): {_kinds}")
