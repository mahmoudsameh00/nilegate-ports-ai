"""Phase 0 — Setup & Configuration

Converted from Notebooks/rag/HbR_Annual_report_2025_chunking.ipynb (2026-10-01) by tools/nb_to_script.py: same cells, same order; `# %% cell N` = notebook cell N.
Run from the project root: uv run python tools/run.py pipelines/scripts/rag/HbR_Annual_report_2025_chunking.py

Reads:   Data/raw/unstructured/HbR_Annual_report_2025_highlights.pdf
Writes:  Data/processed/rag/extracted|cleaned|chunks/ (the HbR files); review aids in Notebooks/_scratch/ (git-ignored)
Re-run:  safe: rewrites the same three artifacts
Final Checkpoint (what was done, problems, fixes): pipelines/checkpoints/rag/HbR_Annual_report_2025_chunking.md
"""
from IPython.display import display  # outside Jupyter it prints the value (added by the conversion)

# %% [markdown] cell 0
# # Phase 0 — Setup & Configuration
#
# This phase initializes the environment and defines the source and pipeline configuration for the
# **Port of Rotterdam Authority — Annual Report 2025 (highlights)** ingestion pipeline
# (`HbR_Annual_report_2025_highlights.pdf`, 85 landscape pages).
#
# The purpose of this phase is to prepare the notebook for all downstream processing without
# performing any page classification, structural parsing, duplicate detection or chunking yet.
#
# The phase establishes:
#
# - Required Python libraries and runtime environment
# - Source PDF location and **one PDF access helper** (`page_dict`) used by every later phase, so every
#   phase sees exactly the same text blocks (image blocks are excluded: this PDF carries ~19 MB of photos)
# - Project and output directories
# - Source/document metadata. New in this source: **access control is decided per unit**, not per document —
#   the report mixes public narrative (level 1, Operations) with the Port Authority's own financial results
#   (level 3, Finance), as defined in `docs/rbac_mapping.md` §4
# - Pipeline configuration and the source file fingerprint
#
# No transformation of the PDF content is performed in this phase.

# %% cell 1
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
print("pymupdf:", pymupdf.__version__)

# %% cell 2
# =========================================================
# 0.2 Locate the source PDF
# =========================================================

PDF_RELATIVE_PATH = Path("Data/raw/unstructured/HbR_Annual_report_2025_highlights.pdf")

search_roots = [Path.cwd(), *Path.cwd().parents]
candidates = [root / PDF_RELATIVE_PATH for root in search_roots]
PDF_PATH = next((path for path in candidates if path.exists()), None)

if PDF_PATH is None:
    raise FileNotFoundError(
        "HbR annual report PDF was not found.\n\nLooked in:\n"
        + "\n".join(f"  {path}" for path in candidates)
    )

print("PDF found successfully.")
print("PDF path :", PDF_PATH)

# %% cell 3
# =========================================================
# 0.3 Open the source PDF + PDF access helpers
# =========================================================
# Every phase reads text through page_dict(), so block/line indexes are identical everywhere.
# TEXT_FLAGS = the default "dict" flags WITHOUT image bytes: this PDF embeds ~19 MB of photos,
# and image blocks are not text. Images are inventoried separately (get_image_info, Phase 1).

doc = pymupdf.open(PDF_PATH)

TEXT_FLAGS = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES

_dict_cache: dict[int, dict] = {}


def page_dict(p: int) -> dict:
    """get_text('dict') of physical page p (1-based), text blocks only, cached."""
    if p not in _dict_cache:
        _dict_cache[p] = doc[p - 1].get_text("dict", flags=TEXT_FLAGS)
    return _dict_cache[p]


print("Document opened successfully.")
print("Document name :", PDF_PATH.name)
print("Total pages   :", len(doc))
print("Image blocks in page_dict(3):", sum(b.get("type") == 1 for b in page_dict(3)["blocks"]))

# %% cell 4
# =========================================================
# 0.4 Inspect PDF metadata
# =========================================================

pdf_metadata = doc.metadata

print("PDF metadata:")
for key, value in pdf_metadata.items():
    print(f"{key:12}: {value}")

# %% cell 5
# =========================================================
# 0.5 Define project and output paths
# =========================================================

PROJECT_ROOT = PDF_PATH.parents[3]

PROCESSED_RAG_DIR = PROJECT_ROOT / "Data" / "processed" / "rag"
EXTRACTED_DIR = PROCESSED_RAG_DIR / "extracted"
CLEANED_DIR = PROCESSED_RAG_DIR / "cleaned"
CHUNKS_DIR = PROCESSED_RAG_DIR / "chunks"
SCRATCH_DIR = PROJECT_ROOT / "Notebooks" / "_scratch"      # git-ignored review aids only

for directory in (EXTRACTED_DIR, CLEANED_DIR, CHUNKS_DIR):
    directory.mkdir(parents=True, exist_ok=True)

print("Project root     :", PROJECT_ROOT)
print("Processed RAG    :", PROCESSED_RAG_DIR)
print("Extracted dir    :", EXTRACTED_DIR)
print("Cleaned dir      :", CLEANED_DIR)
print("Chunks dir       :", CHUNKS_DIR)
print("Scratch dir      :", SCRATCH_DIR)

# %% cell 6
# =========================================================
# 0.6 Define source and pipeline configuration
# =========================================================

SOURCE_NAME = "HbR_Annual_report_2025"
SOURCE_FILE = PDF_PATH.name
SOURCE_PUBLISHER = "Port of Rotterdam Authority"

DOCUMENT_TYPE = "port_authority_annual_report"
REAL_OR_SYNTHETIC = "real"
VERSION_DATE = "2025"

# Access control is decided PER UNIT (docs/rbac_mapping.md §4, ADR-006):
#   the Authority's own financial results / position  -> level 3, Finance
#   everything else (strategy, ESG, operations, governance narrative) -> level 1, Operations
DEFAULT_ACCESS = {"sensitivity_level": 1, "department": "Operations"}
FINANCIAL_ACCESS = {"sensitivity_level": 3, "department": "Finance"}
KNOWN_DEPARTMENTS = {"Operations", "Customs", "Finance", "HR", "IT"}   # rows of the departments table

SOURCE_DESCRIPTION = "Port of Rotterdam Authority — Annual report 2025 (highlights edition, English)"

MIN_CHUNK_CHARS = 300
MAX_CHUNK_CHARS = 2000
CHUNK_PREFIX = "hbr2025"

source_metadata = {
    "source_name": SOURCE_NAME,
    "source_file": SOURCE_FILE,
    "publisher": SOURCE_PUBLISHER,
    "document_type": DOCUMENT_TYPE,
    "real_or_synthetic": REAL_OR_SYNTHETIC,
    "version_date": VERSION_DATE,
    "access_policy": "per_unit",
    "default_access": DEFAULT_ACCESS,
    "financial_access": FINANCIAL_ACCESS,
}

print("Source configuration:")
for key, value in source_metadata.items():
    print(f"{key:20}: {value}")

print("\nChunk configuration:")
print("MIN_CHUNK_CHARS :", MIN_CHUNK_CHARS)
print("MAX_CHUNK_CHARS :", MAX_CHUNK_CHARS)
print("CHUNK_PREFIX    :", CHUNK_PREFIX)

# %% cell 7
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
print("File  :", PDF_PATH.name)
print("Size  :", f"{SOURCE_FILE_SIZE:,}", "bytes")
print("SHA256:", SOURCE_SHA256)

# %% cell 8
# =========================================================
# 0.8 Phase 0 validation
# =========================================================

assert PDF_PATH.exists(), "Source PDF does not exist."
assert len(doc) == 85, f"Expected 85 pages (reconnaissance), found {len(doc)}."

assert SOURCE_NAME and SOURCE_FILE == PDF_PATH.name
assert DOCUMENT_TYPE == "port_authority_annual_report"
assert REAL_OR_SYNTHETIC == "real"
assert VERSION_DATE == "2025"

for access in (DEFAULT_ACCESS, FINANCIAL_ACCESS):
    assert access["sensitivity_level"] in (1, 2, 3)
    assert access["department"] in KNOWN_DEPARTMENTS, "department must be a row of the departments table"
assert DEFAULT_ACCESS != FINANCIAL_ACCESS

assert 0 < MIN_CHUNK_CHARS < MAX_CHUNK_CHARS
assert len(SOURCE_SHA256) == 64 and SOURCE_FILE_SIZE > 0
assert not any(b.get("type") == 1 for p in (1, 3, 11) for b in page_dict(p)["blocks"]), \
    "page_dict must not contain image blocks."

print("✅ Phase 0 validation passed.")
print("Pages :", len(doc))
print("Source:", SOURCE_NAME)
print("SHA256:", SOURCE_SHA256)

# %% [markdown] cell 9
# # Phase 1 — Page Inventory
#
# This phase creates a raw page-level inventory of the source PDF, before any classification,
# structural parsing, table/figure extraction, cleaning, deduplication or chunking.
#
# For each physical page the inventory records character, word and line counts, text blocks,
# **image placements** (photos and raster infographics), **vector drawings** (charts, maps, box
# backgrounds, and text drawn as outlines), links, page size and the raw text.
#
# This report is a landscape, image-heavy layout: `image_count` counts image *objects* and
# `image_placements` counts where images are drawn; neither is treated as figure detection
# (Phase 4 decides what is a photo and what is a figure).
#
# **1.6 is a review aid**: it exports the raw PyMuPDF layout of all pages to `Notebooks/_scratch/state/`
# (git-ignored) so the layout can be inspected outside the project environment. The export is never read
# back by this notebook.

# %% cell 10
# =========================================================
# 1.1 Build page inventory
# =========================================================

page_records = []

for page_idx in range(len(doc)):
    page = doc[page_idx]
    p = page_idx + 1
    text = page.get_text("text") or ""

    page_records.append({
        "page_number": p,
        "char_count": len(text),
        "word_count": len(text.split()),
        "line_count": len(text.splitlines()),
        "text_block_count": len(page_dict(p)["blocks"]),
        "image_count": len(page.get_images(full=True)),
        "image_placements": len(page.get_image_info()),
        "drawing_count": len(page.get_drawings()),
        "link_count": len(page.get_links()),
        "page_width": round(page.rect.width, 1),
        "page_height": round(page.rect.height, 1),
        "text": text,
    })

pages_df = pd.DataFrame(page_records)

print("Page inventory created successfully.")
print("Rows   :", len(pages_df))
print("Columns:", list(pages_df.columns))

# %% cell 11
# =========================================================
# 1.2 Inventory statistics
# =========================================================

print("Total pages :", len(pages_df))
print("Total chars :", pages_df["char_count"].sum())
print("Total words :", pages_df["word_count"].sum())
print("Total lines :", pages_df["line_count"].sum())

print("\nWord count:")
print(pages_df["word_count"].describe())

print("\nVisual / structural signals:")
print(pages_df[["text_block_count", "image_count", "image_placements", "drawing_count", "link_count"]].describe())

print("\nPage sizes (width x height):")
print(pages_df.groupby(["page_width", "page_height"]).size())

# %% cell 12
# =========================================================
# 1.3 Inventory preview (all pages)
# =========================================================

preview_df = pages_df.copy()
preview_df["text_preview"] = (
    preview_df["text"].str.replace(r"\s+", " ", regex=True).str.strip().str[:160]
)

with pd.option_context("display.max_rows", None, "display.max_colwidth", 160):
    display(preview_df[["page_number", "word_count", "line_count", "text_block_count",
                        "image_count", "image_placements", "drawing_count", "link_count", "text_preview"]])

# %% cell 13
# =========================================================
# 1.4 Flag unusual pages (no text / very little text / images / many drawings)
# =========================================================
# The running navigation bar and the page number give every page ~20 words,
# so "very little text" means < 60 words here.

special_pages_df = pages_df[
    (pages_df["word_count"] < 60)
    | (pages_df["image_placements"] > 0)
    | (pages_df["drawing_count"] > 60)
].copy()

with pd.option_context("display.max_rows", None):
    display(special_pages_df[["page_number", "word_count", "text_block_count",
                              "image_count", "image_placements", "drawing_count"]])

# %% cell 14
# =========================================================
# 1.5 Raw text inspection of selected pages
# =========================================================

inspection_pages = [1, 2, 3, 5, 6, 11, 13, 23, 27, 33, 82, 83, 84, 85]

for page_number in inspection_pages:
    row = pages_df.loc[pages_df["page_number"] == page_number].iloc[0]
    print("=" * 100)
    print(f"PAGE {page_number} | words={row['word_count']} | lines={row['line_count']} | "
          f"images={row['image_placements']} | drawings={row['drawing_count']}")
    print("-" * 100)
    text_preview = row["text"].strip()
    print(text_preview[:900] if text_preview else "[NO TEXT]")
    print()

# %% cell 15
# =========================================================
# 1.6 Review aid: export the raw PyMuPDF layout to Notebooks/_scratch/state (git-ignored)
# =========================================================
# Not part of the pipeline and never read back by this notebook. It lets the layout
# (spans, fonts, bboxes, image placements, drawing rectangles) be inspected outside this
# environment. Image bytes are not exported.

STATE_DIR = SCRATCH_DIR / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)


def _r(values, nd=2):
    return [round(float(v), nd) for v in values]


def _clean_span(s: dict) -> dict:
    return {"text": s["text"], "font": s["font"], "size": round(s["size"], 2), "flags": s["flags"],
            "color": s["color"], "bbox": _r(s["bbox"]), "origin": _r(s["origin"])}


layout_export = {"source": {"file": SOURCE_FILE, "sha256": SOURCE_SHA256, "pymupdf": pymupdf.__version__},
                 "metadata": doc.metadata, "toc": doc.get_toc(simple=True), "pages": []}

for p in range(1, len(doc) + 1):
    page = doc[p - 1]
    d = page_dict(p)
    blocks = []
    for b in d["blocks"]:
        blocks.append({"type": b.get("type"), "bbox": _r(b["bbox"]),
                       "lines": [{"bbox": _r(l["bbox"]), "wmode": l["wmode"], "dir": _r(l["dir"], 3),
                                  "spans": [_clean_span(s) for s in l["spans"]]} for l in b.get("lines", [])]})
    drawings = [{"rect": _r(dr["rect"]), "fill": dr.get("fill"), "color": dr.get("color"),
                 "width": dr.get("width"), "type": dr.get("type"), "n_items": len(dr.get("items", []))}
                for dr in page.get_drawings()]
    layout_export["pages"].append({
        "page_number": p, "rect": _r(page.rect), "text": page.get_text("text"),
        "dict": {"width": d["width"], "height": d["height"], "blocks": blocks},
        "image_info": [{"bbox": _r(i["bbox"]), "width": i["width"], "height": i["height"],
                        "xref": i.get("xref")} for i in page.get_image_info(xrefs=True)],
        "images_full": [list(img[:2]) + [img[2], img[3]] for img in page.get_images(full=True)],
        "links": len(page.get_links()),
        "drawings": drawings,
    })

state_path = STATE_DIR / f"{SOURCE_NAME}_layout.json"
state_path.write_text(json.dumps(layout_export, ensure_ascii=False), encoding="utf-8")
print(f"Saved review aid: {state_path.relative_to(PROJECT_ROOT)} ({state_path.stat().st_size:,} bytes)")

# %% cell 16
# =========================================================
# 1.7 Phase 1 validation
# =========================================================

expected_columns = [
    "page_number", "char_count", "word_count", "line_count", "text_block_count",
    "image_count", "image_placements", "drawing_count", "link_count",
    "page_width", "page_height", "text",
]

assert list(pages_df.columns) == expected_columns, "Unexpected inventory columns."
assert len(pages_df) == len(doc), "Inventory row count != PDF page count."
assert pages_df["page_number"].tolist() == list(range(1, len(doc) + 1)), "Page numbers not 1..N."
assert (pages_df["char_count"] == pages_df["text"].str.len()).all(), "char_count mismatch."
assert (pages_df[expected_columns[1:9]] >= 0).all().all(), "Negative counts found."
assert (pages_df[["page_width", "page_height"]] > 0).all().all(), "Invalid page size."
assert pages_df[["page_width", "page_height"]].drop_duplicates().shape[0] == 1, "Mixed page sizes."
assert (pages_df["page_width"] > pages_df["page_height"]).all(), "Expected a landscape document."

print("✅ Phase 1 validation passed.")
print("Pages                 :", len(pages_df))
print("Pages without text    :", pages_df.loc[pages_df["word_count"] == 0, "page_number"].tolist())
print("Pages with images     :", int((pages_df["image_placements"] > 0).sum()))
print("Pages with >60 drawings:", pages_df.loc[pages_df["drawing_count"] > 60, "page_number"].tolist())

# %% [markdown] cell 17
# # Phase 2 — Page Classification
#
# Each page receives a class label and a human-readable reason. Rules are derived from observed page
# signals (2.1), never from hard-coded page numbers; a reviewed snapshot (2.4) guards the result.
#
# Layout facts that drive the rules (observed in Phase 1 and 2.1):
#
# - Every ordinary page carries a **navigation bar** (six chapter labels, y < 30pt); the label of the
#   current chapter is printed in a different colour, so each page "knows" its chapter.
# - **Chapter divider pages** (large 30pt title + a list of the chapter's sections) have no navigation bar.
# - The **Contents** page is titled "IN THIS REPORT"; the **covers** carry no text at all.
#
# Classes:
#
# - Non-retrieval: `cover_image`, `contents`, `chapter_divider` (their headings are still used as metadata in Phase 3)
# - Retrieval: `content`, `credits` (publisher / contact facts, kept as one unit — plan §3.4)

# %% cell 18
# =========================================================
# 2.1 Page signals (inspection only — no decisions yet)
# =========================================================
# Signals come from the same page_dict() spans every later phase uses.

NAV_LABELS = ["Foreword", "2025 at a glance", "Port of Rotterdam", "ESG Report",
              "Corporate governance and risk management", "Other information"]
NAV_MAX_Y1 = 30.0            # the navigation bar sits above y = 30pt on every ordinary page
TITLE_MIN_SIZE = 29.0        # chapter / contents titles are 30–31pt


def page_spans(p: int):
    for b in page_dict(p)["blocks"]:
        for l in b["lines"]:
            for s in l["spans"]:
                if s["text"].strip():
                    yield l, s


signal_records = []
for p in range(1, len(doc) + 1):
    spans = list(page_spans(p))
    nav = [(s["text"].strip(), s["color"]) for l, s in spans if l["bbox"][3] <= NAV_MAX_Y1]
    nav_colors = pd.Series([c for _, c in nav]).value_counts()
    # the active chapter label is the one printed in the minority colour
    active = [t for t, c in nav if len(nav_colors) == 2 and c == nav_colors.index[-1]]
    big_title = " ".join(s["text"].strip() for l, s in spans if s["size"] >= TITLE_MIN_SIZE)
    body_words = sum(len(s["text"].split()) for l, s in spans
                     if l["bbox"][3] > NAV_MAX_Y1 and not (s["font"] == "NLRTM-Medium" and l["bbox"][1] >= 445))

    signal_records.append({
        "page_number": p,
        "word_count": int(pages_df.loc[p - 1, "word_count"]),
        "body_words": body_words,
        "has_nav": [t for t, _ in nav] == NAV_LABELS,
        "active_nav": active[0] if len(active) == 1 else None,
        "big_title": big_title,
        "image_placements": int(pages_df.loc[p - 1, "image_placements"]),
        "drawing_count": int(pages_df.loc[p - 1, "drawing_count"]),
        "first_lines": " | ".join(s["text"].strip() for l, s in spans if l["bbox"][3] > NAV_MAX_Y1)[:110],
    })

signals_df = pd.DataFrame(signal_records)

with pd.option_context("display.max_rows", None, "display.max_colwidth", 110):
    display(signals_df)

print("\nNav bar present on", int(signals_df["has_nav"].sum()), "pages;",
      "active label found on", int(signals_df["active_nav"].notna().sum()))

# %% cell 19
# =========================================================
# 2.2 Inspect ambiguous pages (raw lines)
# =========================================================
# Pages with a big title, no nav bar, few body words, or a credits heading.

AMBIGUOUS = signals_df[
    (signals_df["big_title"] != "") | ~signals_df["has_nav"] | (signals_df["body_words"] < 40)
]["page_number"].tolist()

for p in AMBIGUOUS:
    lines = [" ".join(s["text"] for s in l["spans"]).strip()
             for b in page_dict(p)["blocks"] for l in b["lines"] if l["bbox"][3] > NAV_MAX_Y1]
    lines = [t for t in lines if t]
    print("=" * 100)
    print(f"PAGE {p} | body_words={signals_df.loc[p - 1, 'body_words']} | nav={signals_df.loc[p - 1, 'has_nav']} "
          f"| images={signals_df.loc[p - 1, 'image_placements']}")
    print("-" * 100)
    print("\n".join(lines[:25]) if lines else "[NO TEXT]")

# %% cell 20
# =========================================================
# 2.3 Page classification rules
# =========================================================
# Rule order matters: no text -> cover; big "IN THIS REPORT" title -> contents;
# big title without nav bar -> chapter divider; "6.2 CREDITS" title -> credits; else content.

RETRIEVAL_CLASSES = {"content", "credits"}
ALLOWED_CLASSES = {"cover_image", "contents", "chapter_divider", "content", "credits"}
CONTENTS_TITLE_RE = re.compile(r"^IN THIS\s+REPORT$", re.IGNORECASE)
CREDITS_RE = re.compile(r"^\d\.\d\s+CREDITS$")


def section_titles(p: int) -> list[str]:
    """ExtraBold 20pt section titles on a page (e.g. '6.2 CREDITS')."""
    return [s["text"].strip() for l, s in page_spans(p) if s["font"] == "NLRTM-ExtraBold" and 19 <= s["size"] <= 21]


def classify_page(sig) -> tuple[str, str]:
    if sig.word_count == 0:
        return "cover_image", "No extractable text (full-page image)"
    if CONTENTS_TITLE_RE.match(sig.big_title):
        return "contents", "30pt title 'IN THIS REPORT'"
    if sig.big_title and not sig.has_nav:
        return "chapter_divider", f"30pt chapter title without nav bar: '{sig.big_title}'"
    if any(CREDITS_RE.match(t) for t in section_titles(sig.page_number)):
        return "credits", "Section title '6.2 CREDITS': publisher/contact facts, kept (plan §3.4)"
    if sig.has_nav:
        return "content", f"Ordinary page (chapter: {sig.active_nav})"
    return "unclassified", "Matched no rule"


rows = [classify_page(sig) for sig in signals_df.itertuples()]
page_class_df = signals_df[["page_number", "word_count", "body_words", "active_nav"]].copy()
page_class_df[["page_class", "reason"]] = pd.DataFrame(rows, index=signals_df.index)
page_class_df["keep_for_retrieval"] = page_class_df["page_class"].isin(RETRIEVAL_CLASSES)

with pd.option_context("display.max_rows", None, "display.max_colwidth", 90):
    display(page_class_df)

print("\nClass counts:")
print(page_class_df["page_class"].value_counts())

# %% cell 21
# =========================================================
# 2.4 Phase 2 validation
# =========================================================

# ---- completeness ----
assert len(page_class_df) == len(doc), "Not every page was classified."
assert page_class_df["page_class"].isin(ALLOWED_CLASSES).all(), "Unknown / unclassified page found."
assert page_class_df["reason"].str.strip().ne("").all(), "Every page needs a reason."
assert (page_class_df["keep_for_retrieval"] == page_class_df["page_class"].isin(RETRIEVAL_CLASSES)).all()

# ---- structural rules ----
retrieval = page_class_df[page_class_df["keep_for_retrieval"]]
assert signals_df.loc[retrieval.index, "has_nav"].all(), "Every retrieval page must carry the nav bar."
assert retrieval["active_nav"].notna().all(), "Every retrieval page must have exactly one active chapter label."
assert set(retrieval["active_nav"]) == set(NAV_LABELS), "Every chapter must have at least one retrieval page."
active_order = [NAV_LABELS.index(a) for a in retrieval["active_nav"]]
assert active_order == sorted(active_order), "Active chapter labels must follow the document order."

dividers = page_class_df[page_class_df["page_class"] == "chapter_divider"]
for p in dividers["page_number"]:
    nxt = page_class_df.loc[p, "active_nav"]      # index p = physical page p + 1
    assert nxt is not None, f"Divider p{p} must be followed by a page of its chapter."

# ---- reviewed snapshot (regression guard) — reviewed 2026-09-25 ----
REVIEWED_CLASSES = {1: "cover_image", 2: "contents", 5: "chapter_divider", 8: "chapter_divider",
                    21: "chapter_divider", 67: "chapter_divider", 81: "chapter_divider",
                    84: "credits", 85: "cover_image"}
actual = dict(zip(page_class_df["page_number"], page_class_df["page_class"]))
expected = {p: REVIEWED_CLASSES.get(p, "content") for p in actual}
mismatches = {p: (expected[p], actual[p]) for p in actual if expected[p] != actual[p]}
assert not mismatches, f"Classification drifted from reviewed snapshot: {mismatches}"

RETRIEVAL_PAGES = page_class_df.loc[page_class_df["keep_for_retrieval"], "page_number"].tolist()
LAST_PAGE = len(doc)

print("✅ Phase 2 validation passed.")
print("Retrieval pages :", len(RETRIEVAL_PAGES), f"({RETRIEVAL_PAGES[0]}–{RETRIEVAL_PAGES[-1]}, minus dividers)")
print("Excluded pages  :", page_class_df.loc[~page_class_df["keep_for_retrieval"], ["page_number", "page_class"]]
      .values.tolist())
print("Pages per chapter (nav):", retrieval.groupby("active_nav", sort=False).size().to_dict())

# %% [markdown] cell 22
# # Phase 3 — Structure Reconnaissance
#
# Goal: build a confirmed `section_map` (headings, levels, physical positions) from the visible
# typography, cross-checked against three independent sources in the PDF itself:
#
# 1. the **Contents** page (p.2): chapter names and the ESG / governance section names;
# 2. the **chapter divider** pages: numbered section lists (`3.1`, `3.2.1`, …, `6.2`);
# 3. the **navigation bar**: the highlighted chapter label on every retrieval page.
#
# The PDF outline is inspected but is not the source of truth. No content is extracted in this phase.
#
# Layout facts measured here: running navigation bar above y = 30pt, page number (NLRTM-Medium 7.5pt)
# below y = 445pt, two text columns split at x = 420pt, body text NLRTM-Regular 8pt, tables and boxes 7.25pt.
# **Heading level is carried by font + size**: chapter titles 30pt, section titles ExtraBold 20pt,
# subsections numbered Bold 10pt (`4.2.1 …`), headings Bold 10pt, sub-headings Bold 8.5pt, minor/box
# headings: a whole line in Bold 8pt.

# %% cell 23
# =========================================================
# 3.1 Line table, zones, body font size
# =========================================================
# One row per text line of page_dict(). Lines whose spans are all blank are dropped
# (they carry no text). The dominant span (longest text) gives the line's font/size.

COLUMN_SPLIT_X = 420.0          # page width 841.9pt: left column x0≈42.5, right column x0≈432
FOOTER_MIN_Y0 = 445.0


def is_bold_span(s: dict) -> bool:
    return bool(s["flags"] & 16) or "Bold" in s["font"]


line_records = []
for p in range(1, len(doc) + 1):
    for block_no, block in enumerate(page_dict(p)["blocks"]):
        for line_no, line in enumerate(block["lines"]):
            spans = [s for s in line["spans"] if s["text"].strip()]
            if not spans:
                continue
            main = max(spans, key=lambda s: len(s["text"].strip()))
            x0, y0, x1, y1 = line["bbox"]
            line_records.append({
                "page_number": p, "block_no": block_no, "line_no": line_no,
                "x0": round(x0, 1), "y0": round(y0, 1), "x1": round(x1, 1), "y1": round(y1, 1),
                "text": "".join(s["text"] for s in line["spans"]).strip(),
                "size": round(main["size"], 1), "font": main["font"],
                "is_bold": is_bold_span(main),
                "all_bold": all(is_bold_span(s) for s in spans),
                "n_spans": len(spans),
                "color": main["color"],
            })

lines_df = pd.DataFrame(line_records)
lines_df["n_chars"] = lines_df["text"].str.len()
lines_df["column"] = (lines_df["x0"] >= COLUMN_SPLIT_X).astype(int)
lines_df["zone"] = np.select(
    [lines_df["y1"] <= NAV_MAX_Y1,
     (lines_df["font"] == "NLRTM-Medium") & (lines_df["y0"] >= FOOTER_MIN_Y0)],
    ["header", "footer"], default="body",
)
lines_df["page_class"] = lines_df["page_number"].map(page_class_df.set_index("page_number")["page_class"])

retr_lines = lines_df[lines_df["page_number"].isin(RETRIEVAL_PAGES) & (lines_df["zone"] == "body")]
size_profile = (
    retr_lines.groupby(["font", "size"])
    .agg(lines=("text", "size"), chars=("n_chars", "sum"), pages=("page_number", "nunique"),
         example=("text", "first"))
    .sort_values("chars", ascending=False)
)
BODY_FONT, BODY_FONT_SIZE = size_profile.index[0]

print("Lines extracted  :", len(lines_df), "| retrieval-page body lines:", len(retr_lines))
print("Zones            :", lines_df["zone"].value_counts().to_dict())
print("BODY_FONT / SIZE :", BODY_FONT, BODY_FONT_SIZE)
print("\nFont profile (retrieval pages, body zone):")
with pd.option_context("display.max_colwidth", 60, "display.max_rows", 60):
    display(size_profile)

# %% cell 24
# =========================================================
# 3.2 Header / footer zones and printed page numbers
# =========================================================

header = lines_df[lines_df["zone"] == "header"]
footer = lines_df[lines_df["zone"] == "footer"]

print("Header zone contents:", header["text"].value_counts().to_dict())
print("Footer zone contents are page numbers only:", footer["text"].str.fullmatch(r"\d{1,2}").all())

offsets = (footer["page_number"] - footer["text"].astype(int)).unique()
assert len(offsets) == 1, f"Printed->physical offset is not constant: {offsets}"
PAGE_OFFSET = int(offsets[0])

assert set(header["text"]) == set(NAV_LABELS), "Only nav labels may sit in the header zone."
assert footer["page_number"].nunique() == len(footer), "One page number per page."
assert lines_df.loc[(lines_df["zone"] == "body") & (lines_df["y0"] < NAV_MAX_Y1)].empty

print("PAGE_OFFSET (physical - printed):", PAGE_OFFSET)
print("Pages without a printed number   :",
      sorted(set(range(1, len(doc) + 1)) - set(footer["page_number"])))

# %% cell 25
# =========================================================
# 3.3 Chemical subscripts (CO2, NO2, PM10, PM2.5)
# =========================================================
# PyMuPDF returns a lowered subscript ("2" in CO2) as a SEPARATE line, often in another
# block at the end of the page, leaving a gap in its host line ("CO e emissions").
# A subscript = a digits-only body line, clearly smaller than body text, whose position
# falls inside exactly one host line that contains a host token (CO / NO / PM).
# It is re-inserted after its token: "CO e" -> "CO2e", "CO ," -> "CO2,", "(PM" + "10" -> "(PM10".
# The subscript line itself is then accounted for as merged (Phase 6 / Phase 19).

SUBSCRIPT_MAX_SIZE = 0.85 * BODY_FONT_SIZE
SUB_TEXT_RE = re.compile(r"^\d+(?:\.\d+)?$")
HOST_TOKEN_RE = re.compile(r"\b(?:CO|NO|PM)(?![A-Za-z0-9\u2082])")


def insert_subscripts(text: str, host_x1: float, subs: list[tuple[float, str]]) -> str:
    """subs = [(x0, digits)] of one host line; returns the text with the subscripts inserted."""
    tokens = list(HOST_TOKEN_RE.finditer(text))
    subs = sorted(subs)
    end_subs = [s for s in subs if s[0] >= host_x1 - 1.5]
    inner = [s for s in subs if s[0] < host_x1 - 1.5]
    assert len(end_subs) <= 1, f"Two subscripts at the end of {text!r}"
    if end_subs:
        assert tokens and tokens[-1].end() == len(text.rstrip()), f"End subscript without a final token: {text!r}"
        assign = list(zip(tokens[:-1], [d for _, d in inner])) + [(tokens[-1], end_subs[0][1])]
        assert len(inner) == len(tokens) - 1, f"Subscript/token count mismatch: {text!r}"
    else:
        assert len(inner) == len(tokens), f"Subscript/token count mismatch: {text!r} {subs}"
        assign = list(zip(tokens, [d for _, d in inner]))
    out, pos = "", 0
    for tok, digits in assign:
        out += text[pos:tok.end()] + digits
        pos = tok.end()
        if re.match(r" (?=[e,.;:)](?![a-z]))", text[pos:]):       # "CO e" / "CO ," / "(NO )"
            pos += 1
    return out + text[pos:]


# unit tests on real cases of this PDF
assert insert_subscripts("reduce CO e emissions. In col", 400, [(221.6, "2")]) == "reduce CO2e emissions. In col"
assert insert_subscripts("CO and CO e", 501.6, [(458.6, "2"), (493.1, "2")]) == "CO2 and CO2e"
assert insert_subscripts("other than CO , such as methane", 700, [(607.0, "2")]) == "other than CO2, such as methane"
assert insert_subscripts("dioxide (NO ) and particulate matter (PM", 674.5, [(566.3, "2"), (674.5, "10")]) \
    == "dioxide (NO2) and particulate matter (PM10"
assert insert_subscripts("to accelerate CO", 386.5, [(386.4, "2")]) == "to accelerate CO2"

body_mask = lines_df["zone"] == "body"
sub_cand = lines_df[body_mask & (lines_df["size"] <= SUBSCRIPT_MAX_SIZE) & (lines_df["size"] >= 5.5)
                    & lines_df["text"].str.match(SUB_TEXT_RE)]
host_of, orphan_subs = {}, []
for i, s in sub_cand.iterrows():
    hosts = lines_df[body_mask & (lines_df["page_number"] == s["page_number"]) & (lines_df["size"] > s["size"])
                     & (lines_df["y0"] <= s["y0"]) & (lines_df["y1"] >= s["y0"])
                     & (lines_df["x0"] - 1 <= s["x0"]) & (lines_df["x1"] + 1 >= s["x0"])]
    hosts = hosts[hosts["text"].str.contains(HOST_TOKEN_RE)]
    if len(hosts) == 1:
        host_of[i] = hosts.index[0]
    else:
        orphan_subs.append((s["page_number"], s["y0"], s["text"], len(hosts)))

lines_df["is_subscript"] = lines_df.index.isin(list(host_of))
lines_df["subscript_host"] = pd.Series(host_of, dtype="Int64").reindex(lines_df.index)
lines_df["text_merged"] = lines_df["text"]
for host, grp in pd.Series(host_of).groupby(pd.Series(host_of).values):
    h = lines_df.loc[host]
    subs = [(lines_df.at[i, "x0"], lines_df.at[i, "text"]) for i in grp.index]
    lines_df.at[host, "text_merged"] = insert_subscripts(h["text"], h["x1"], subs)

subscripts_df = lines_df[lines_df["is_subscript"]].assign(
    host_text=lambda d: d["subscript_host"].map(lambda h: lines_df.at[h, "text_merged"]))

print(f"Subscript lines: {len(subscripts_df)} on pages {sorted(subscripts_df['page_number'].unique().tolist())}")
print(f"Small digit lines NOT treated as subscripts (no host line with a token): {len(orphan_subs)} "
      f"on pages {sorted({o[0] for o in orphan_subs})} (chart values / axis ticks)")
with pd.option_context("display.max_colwidth", 100, "display.max_rows", None):
    display(subscripts_df[["page_number", "x0", "y0", "size", "text", "host_text"]])

# %% cell 26
# =========================================================
# 3.4 Chapters and numbered sections from the Contents page and the chapter dividers
# =========================================================
# Line order inside a PyMuPDF block is not reading order (the number "3.1" comes after
# "Profile and strategy"), so entries are rebuilt by row (same y) and x position.

NUM_RE = re.compile(r"^(\d(?:\.\d{1,2}){1,2})$")
CONTENTS_PAGE = int(page_class_df.loc[page_class_df["page_class"] == "contents", "page_number"].iloc[0])
DIVIDER_PAGES = page_class_df.loc[page_class_df["page_class"] == "chapter_divider", "page_number"].tolist()


def clean_heading(text: str) -> str:
    t = "".join(ch for ch in str(text) if not unicodedata.category(ch).startswith("C"))
    return " ".join(unicodedata.normalize("NFKC", t).split()).strip()


# ---- 1) Contents page: chapter names (Bold 12pt, wrapped lines merged per block) ----
toc = lines_df[(lines_df["page_number"] == CONTENTS_PAGE) & (lines_df["zone"] == "body")]
toc_chapters = (
    toc[(toc["size"] == 12.0) & ~toc["text"].str.fullmatch(r"\d{1,3}")]
    .sort_values(["block_no", "y0"]).groupby("block_no", sort=False)
    .agg(text=("text", " ".join), x0=("x0", "min"), y0=("y0", "min"))
)
toc_pages = toc[(toc["size"] == 12.0) & toc["text"].str.fullmatch(r"\d{1,3}")].groupby("block_no")["text"].first()
toc_chapters["printed_page"] = toc_chapters.index.map(toc_pages).astype(int)
toc_chapters["physical_page"] = toc_chapters["printed_page"] + PAGE_OFFSET
toc_chapters = toc_chapters.sort_values(["x0", "y0"]).reset_index(drop=True)
CHAPTERS = toc_chapters["text"].map(clean_heading).tolist()
toc_section_names = [clean_heading(t) for t in toc.loc[toc["size"] == BODY_FONT_SIZE, "text"]]

# ---- 2) Divider pages: numbered entries ----
div_records = []
for p in DIVIDER_PAGES:
    dl = lines_df[(lines_df["page_number"] == p) & (lines_df["zone"] == "body") & (lines_df["size"] < 29)]
    for y, row in dl.groupby(dl["y0"].round(0)):
        nums = row[row["text"].str.match(NUM_RE)]
        names = row[~row["text"].str.match(NUM_RE)]
        assert len(nums) == 1 and len(names) == 1, f"Divider p{p} row y={y}: {row['text'].tolist()}"
        div_records.append({"divider_page": p, "number": nums["text"].iloc[0],
                            "name": clean_heading(names["text"].iloc[0]), "y0": float(y)})
divider_entries = pd.DataFrame(div_records)
divider_entries["level"] = divider_entries["number"].str.count(r"\.") + 1     # 2 = N.N, 3 = N.N.N

# ---- 3) Chapter title of every divider (30pt) matched to a Contents chapter ----
div_titles = (
    lines_df[lines_df["page_number"].isin(DIVIDER_PAGES) & (lines_df["size"] >= TITLE_MIN_SIZE)]
    .sort_values(["page_number", "y0"]).groupby("page_number")["text"].apply(" ".join)
)
chapter_of_title = {t: next((c for c in CHAPTERS if c.upper() == clean_heading(t).upper()), None)
                    for t in div_titles}

print("Chapters from Contents:")
display(toc_chapters)
print("\nDivider titles -> chapter:", chapter_of_title)
print("\nNumbered divider entries:")
with pd.option_context("display.max_rows", None):
    display(divider_entries)

# %% cell 27
# =========================================================
# 3.5 Heading candidates (font-role based)
# =========================================================
#   size >= 29 (ExtraBold/Light)           -> chapter_title (content page p.3 "FOREWORD EXECUTIVE BOARD"
#                                             and the divider titles)
#   ExtraBold 20                           -> section_title   ("4.1 GENERAL INFORMATION ABOUT OUR REPORT")
#   Bold 10 + "N.N.N"                      -> subsection      ("4.2.1 Climate mitigation")
#   Bold 10                                -> heading         ("Policy", "Objectives", …)
#   Bold 8.5                               -> subheading
#   a whole line in Bold 8 (standalone)    -> minor_heading   (box titles, "Fleet renewal", …)
# Excluded on purpose: milestone card titles in "2025 at a glance" (Phase 4 units) and the
# reviewed exceptions below. Wrapped headings (same page/block/role) are merged.

SUBSECTION_RE = re.compile(r"^\d\.\d\.\d{1,2}\s")
NOT_A_HEADING = {
    (4, "The Executive Board"): "Signature line of the foreword (followed by the three names), not a heading.",
}


def heading_role(r) -> str | None:
    if r.page_class not in RETRIEVAL_CLASSES and r.page_class != "chapter_divider":
        return None
    if r.size >= TITLE_MIN_SIZE:
        return "chapter_title"
    if r.page_class == "chapter_divider":
        return None                                    # divider section lists are metadata (3.3)
    if (r.page_number, r.text) in NOT_A_HEADING:
        return None
    if r.font == "NLRTM-ExtraBold" and 19 <= r.size <= 21:
        return "section_title"
    if r.font == "NLRTM-Bold" and r.size == 10.0:
        return "subsection" if SUBSECTION_RE.match(r.text) else "heading"
    if r.font == "NLRTM-Bold" and r.size == 8.5:
        return "subheading"
    if r.font == "NLRTM-Bold" and r.size == BODY_FONT_SIZE and r.all_bold:
        if signals_df.loc[r.page_number - 1, "active_nav"] == "2025 at a glance":
            return None                                # milestone card titles (Phase 4)
        return "minor_heading"
    return None


cand = lines_df[(lines_df["zone"] == "body") & ~lines_df["is_subscript"]].copy()
cand["role"] = [heading_role(r) for r in cand.itertuples()]
cand = cand.dropna(subset=["role"]).sort_values(["page_number", "column", "y0", "x0"])

groups = []
for r in cand.itertuples():
    last = groups[-1] if groups else None
    if (last and last["role"] == r.role and last["page_number"] == r.page_number
            and last["block_no"] == r.block_no and r.y0 - last["y1"] < 12):
        last["text"] += " " + r.text_merged
        last["y1"] = r.y1
        last["n_lines"] += 1
        continue
    groups.append({"page_number": r.page_number, "block_no": r.block_no, "column": r.column,
                   "y0": r.y0, "y1": r.y1, "x0": r.x0, "role": r.role,
                   "font": r.font, "size": r.size, "n_lines": 1, "text": r.text_merged})

heading_cand_df = pd.DataFrame(groups)

print(f"Heading candidates: {len(heading_cand_df)}")
print(heading_cand_df["role"].value_counts().to_string())
print("\nMulti-line headings:")
display(heading_cand_df[heading_cand_df["n_lines"] > 1][["page_number", "role", "n_lines", "text"]])
print("\nNon-heading lines deliberately excluded:", NOT_A_HEADING)

# %% cell 28
# =========================================================
# 3.6 Build section_map (levels, names, reading order, hierarchy path)
# =========================================================
# Levels: 1 chapter, 2 numbered section (N.N), 3 numbered subsection (N.N.N),
#         4 heading (Bold 10), 5 sub-heading (Bold 8.5), 6 minor/box heading (Bold 8).
# Chapter and section NAMES come from the Contents / divider entries (title case), matched
# by text or number; the on-page titles are upper case. Reading order: (page, column, y0).
# "6.1 Key figures" has no title on its page (p.82 starts directly with "Balance sheet"):
# it is inserted as an IMPLIED heading at the top of the first page of that section (reviewed).

LEVEL_BY_ROLE = {"chapter_title": 1, "section_title": 2, "subsection": 3, "heading": 4,
                 "subheading": 5, "minor_heading": 6}
SECTION_NAME = dict(zip(divider_entries["number"], divider_entries["name"]))
IMPLIED_SECTIONS = {"6.1": {"page_number": 82, "reason": "Listed on divider p.81; p.82–83 hold the key "
                                                        "figures but print no section title."}}


def order_key(page, column, y0):
    return (int(page), int(column), float(y0))


rows = []
for h in heading_cand_df.itertuples():
    text = clean_heading(h.text)
    if h.role == "chapter_title":
        name = next((c for c in CHAPTERS if c.upper() == text.upper()), None)
        assert name, f"Chapter title not in Contents: {text!r}"
        text = name
    elif h.role == "section_title":
        num = text.split()[0]
        assert num in SECTION_NAME, f"Section {num} not listed on any divider."
        assert SECTION_NAME[num].upper() == text[len(num):].strip().upper(), f"Section title mismatch: {text!r}"
        text = f"{num} {SECTION_NAME[num]}"
    rows.append({"page_number": h.page_number, "column": h.column, "y0": h.y0, "x0": h.x0,
                 "level": LEVEL_BY_ROLE[h.role], "role": h.role, "heading_text": text, "basis": "typography"})

for num, spec in IMPLIED_SECTIONS.items():
    rows.append({"page_number": spec["page_number"], "column": 0, "y0": 0.0, "x0": 0.0, "level": 2,
                 "role": "implied_section", "heading_text": f"{num} {SECTION_NAME[num]}",
                 "basis": "implied: " + spec["reason"]})

section_map = pd.DataFrame(rows)
section_map["key"] = [order_key(p, c, y) for p, c, y in zip(section_map["page_number"],
                                                              section_map["column"], section_map["y0"])]
section_map = section_map.sort_values("key").reset_index(drop=True)

# ---- walk in reading order: hierarchy path ----
stack, path_rows = {}, []
for r in section_map.itertuples():
    stack = {lvl: txt for lvl, txt in stack.items() if lvl < r.level}
    stack[r.level] = r.heading_text
    path_rows.append({f"l{lvl}": stack.get(lvl) for lvl in range(1, 7)})
section_map = pd.concat([section_map, pd.DataFrame(path_rows)], axis=1)
section_map["section"] = section_map["l1"]
section_map["subsection_path"] = section_map[[f"l{i}" for i in range(2, 7)]].apply(
    lambda s: [v for v in s if isinstance(v, str)], axis=1)
section_map["subsection"] = section_map["subsection_path"].map(lambda p: " > ".join(p) or None)
section_map["heading_norm"] = section_map["heading_text"].str.lower()
section_map.insert(0, "heading_id", [f"h{i:03d}" for i in range(1, len(section_map) + 1)])

print(f"section_map: {len(section_map)} headings", section_map["role"].value_counts().to_dict())
with pd.option_context("display.max_rows", None, "display.max_colwidth", 70):
    display(section_map[["heading_id", "page_number", "column", "y0", "level", "role", "heading_text", "subsection"]])

# %% cell 29
# =========================================================
# 3.7 PDF outline (inspected; used as an independent cross-check in 3.8)
# =========================================================

outline = doc.get_toc(simple=True)
print(f"PDF outline entries: {len(outline)}")
for level, title, page in outline[:60]:
    print(f"{'  ' * (level - 1)}[{level}] p{page}: {title}")

# %% cell 30
# =========================================================
# 3.8 Phase 3 validation
# =========================================================

# ---- A) Contents: six chapters, in order, pointing to their divider/first page ----
assert CHAPTERS == ["Foreword Executive Board", "2025 at a glance", "The Port of Rotterdam Authority",
                    "ESG report", "Corporate governance and risk management", "Other information"], CHAPTERS
assert toc_chapters["physical_page"].tolist() == [3, *DIVIDER_PAGES], "Contents page numbers do not match."
assert all(chapter_of_title.values()), "A divider title matches no Contents chapter."

# ---- B) every numbered divider entry is a heading of the section_map ----
map_numbers = set(section_map["heading_text"].str.extract(r"^(\d\.\d(?:\.\d{1,2})?)\s")[0].dropna())
assert set(divider_entries["number"]) == map_numbers, \
    f"Divider vs section_map: {set(divider_entries['number']) ^ map_numbers}"
for num, name in SECTION_NAME.items():
    assert (section_map["heading_text"].str.lower() == f"{num} {name}".lower()).sum() == 1, f"{num} {name}"

# ---- C) every Contents sub-entry (section / ESG theme name) exists in the section_map ----
names_in_map = set(section_map["heading_text"].str.replace(r"^\d(\.\d{1,2}){1,2}\s", "", regex=True).str.lower())
missing = [n for n in toc_section_names if n.lower() not in names_in_map]
assert not missing, f"Contents entries missing from section_map: {missing}"

# ---- D) nav bar cross-check: the chapter in force at the END of each retrieval page
#         is the chapter highlighted in that page's navigation bar ----
NAV_TO_CHAPTER = dict(zip(NAV_LABELS, CHAPTERS))
nav_mismatch = []
for p in RETRIEVAL_PAGES:
    prior = section_map[section_map["key"].map(lambda k: k <= (p, 1, 1e9))]
    chapter = prior["l1"].iloc[-1]
    if chapter != NAV_TO_CHAPTER[signals_df.loc[p - 1, "active_nav"]]:
        nav_mismatch.append((p, chapter, signals_df.loc[p - 1, "active_nav"]))
assert not nav_mismatch, f"Chapter differs from the nav bar: {nav_mismatch}"

# ---- E) hierarchy sanity ----
assert section_map["heading_id"].is_unique
assert section_map.loc[section_map["level"] > 1, "l1"].notna().all(), "Heading without a chapter."
sub = section_map[section_map["level"] == 3]
assert (sub["heading_text"].str[:3] == sub["l2"].str[:3]).all(), "A N.N.N subsection sits under the wrong N.N section."
assert section_map["page_number"].isin(RETRIEVAL_PAGES + DIVIDER_PAGES).all()

# ---- F) every heading is physically at its recorded position ----
def letters_key(t: str) -> str:
    return re.sub(r"[^a-z]", "", clean_heading(t).lower())


def heading_at_position(r) -> bool:
    page_lines = lines_df[lines_df["page_number"] == r.page_number]
    if r.role == "implied_section":
        return True
    if r.role == "chapter_title":                  # multi-line, mixed fonts: compare the whole title
        return letters_key(" ".join(page_lines.loc[page_lines["size"] >= TITLE_MIN_SIZE, "text"])) \
            == letters_key(r.heading_text)
    same = page_lines[(page_lines["y0"] - r.y0).abs() < 1.0]
    words = re.findall(r"[a-z]{3,}", r.heading_text.lower())[:2]
    return any(all(w in clean_heading(t).lower() for w in words) for t in same["text"])


misplaced = [r.heading_id for r in section_map.itertuples() if not heading_at_position(r)]
assert not misplaced, f"Headings not found at their position: {misplaced}"

# ---- G) independent cross-check with the PDF outline (tagged PDF, 241 entries) ----
#      same heading texts on the same pages (letters only: the outline drops some spaces),
#      except the outline's Contents entry (p.2) and the implied 6.1 heading.
outline_keys = sorted((letters_key(t), p) for _, t, p in outline if p != CONTENTS_PAGE)
map_keys = sorted((letters_key(t), p) for t, p, role in
                  zip(section_map["heading_text"], section_map["page_number"], section_map["role"])
                  if role != "implied_section")
only_outline = sorted(set(outline_keys) - set(map_keys))
only_map = sorted(set(map_keys) - set(outline_keys))
print("Outline-only headings :", only_outline)
print("Map-only headings     :", only_map)
assert outline_keys == map_keys, "section_map and PDF outline disagree."

# ---- H) reviewed snapshot (regression guard) — reviewed 2026-09-25 ----
REVIEWED_ROLE_COUNTS = {"heading": 102, "subheading": 88, "minor_heading": 19, "subsection": 15,
                        "section_title": 10, "chapter_title": 6, "implied_section": 1}
role_counts = section_map["role"].value_counts().to_dict()
assert role_counts == REVIEWED_ROLE_COUNTS, f"Role counts changed: {role_counts}"

print("✅ Phase 3 validation passed.")
print(f"Headings        : {len(section_map)}  {role_counts}")
print(f"Chapters        : {CHAPTERS}")
print(f"Numbered entries: {len(divider_entries)} (all found)")
print(f"PAGE_OFFSET     : {PAGE_OFFSET} | zones: header y1 <= {NAV_MAX_Y1}, footer y0 >= {FOOTER_MIN_Y0}")
print(f"BODY font       : {BODY_FONT} {BODY_FONT_SIZE}pt")

# %% [markdown] cell 31
# # Phase 4 — Structured Extraction
#
# Goal: turn every structured element into semantic units, and record the physical region (page + bbox)
# of each one so body extraction (Phase 6) can exclude it. The report has **no figure or table numbers**,
# so ids are page-based (`tab_p13`, `fig_p33a`, …).
#
# Structured elements found in this PDF (4.1):
#
# - **Tables (21)** — every table has a dark-navy header row drawn as filled rectangles; those rectangles give
#   the table's extent and its column boundaries. Cells are rebuilt at **span level** (a PyMuPDF span is one
#   table cell), wrapped cell text is merged by line pitch (10pt inside a cell, ≥ 12pt between rows) and rows
#   by vertical overlap, so multi-line labels and vertically centred values stay together. One `table_row`
#   unit per logical row; each row repeats its table title and column names, so it is self-contained.
#   Titles, column names and a few layout quirks are fixed in a reviewed spec (4.3) that is checked against
#   the printed header text.
# - **Impacts, risks and opportunities boxes (11)** — one per ESG theme (`iro_box` units).
# - **Text boxes (4)** — 7.25pt "spotlight" boxes with a bold title (`box` units).
# - **Milestone cards (8)** — the four-column "2025 at a glance" pages (`milestone` units).
# - **Graphics** — photos, raster infographics, vector graphics whose text is drawn as outlines, and three
#   charts with real text. Every graphic passes the ADR-020 value gate (`full`, `caption_only`, `skip`) after
#   review of its render; curated descriptions may contain **only numbers printed in the graphic's own
#   extracted text** — so graphics without extractable text get number-free descriptions.
#
# Renders are temporary review aids in `Notebooks/_scratch/figure_renders/` (git-ignored).

# %% cell 32
# =========================================================
# 4.1 Span table, text helpers, structured-element reconnaissance
# =========================================================

def clean_line(raw: str) -> str:
    """NBSP/non-breaking hyphen -> plain, drop control/format chars (incl. soft hyphen), NFKC (CO₂ -> CO2)."""
    t = str(raw).replace(" ", " ").replace("‑", "-").replace("\t", " ")
    t = "".join(ch for ch in t if not unicodedata.category(ch).startswith("C"))
    return " ".join(unicodedata.normalize("NFKC", t).split())


SUSPENDED_HYPHEN_NEXT = {"and", "or", "to", "nor"}


def join_wrapped(parts: list[str]) -> str:
    """Join wrapped lines: a line-final compound hyphen is kept without a space ('deep-' + 'draught'),
    a suspended hyphen keeps its space ('land- and water-based')."""
    text = ""
    for part in (clean_line(p) for p in parts):
        if not part:
            continue
        if text and re.search(r"[A-Za-z]-$", text) and part.split(" ", 1)[0].lower() not in SUSPENDED_HYPHEN_NEXT:
            text += part
        else:
            text = f"{text} {part}".strip()
    return text


assert join_wrapped(["the world's largest deep-", "draught vessels."]) == "the world's largest deep-draught vessels."
assert join_wrapped(["land- and water-based", "nature"]) == "land- and water-based nature"
assert clean_line("CO₂e emissions­") == "CO2e emissions"

# ---- span table (one row per non-blank span of the body zone) ----
line_zone = lines_df.set_index(["page_number", "block_no", "line_no"])["zone"]
line_is_sub = lines_df.set_index(["page_number", "block_no", "line_no"])["is_subscript"]
span_records = []
for p in RETRIEVAL_PAGES:
    for bi, block in enumerate(page_dict(p)["blocks"]):
        for li, line in enumerate(block["lines"]):
            key = (p, bi, li)
            if key not in line_zone.index or line_zone[key] != "body" or line_is_sub[key]:
                continue
            for si, s in enumerate(line["spans"]):
                if not s["text"].strip():
                    continue
                x0, y0, x1, y1 = s["bbox"]
                span_records.append({"page_number": p, "block_no": bi, "line_no": li, "span_no": si,
                                     "x0": round(x0, 1), "y0": round(y0, 1), "x1": round(x1, 1), "y1": round(y1, 1),
                                     "text": s["text"], "font": s["font"], "size": round(s["size"], 1),
                                     "is_bold": is_bold_span(s)})
spans_df = pd.DataFrame(span_records)

# ---- navy header bands (tables and IRO boxes) ----
NAVY = (0.0, 0.12, 0.29)


def is_navy(fill) -> bool:
    return fill is not None and len(fill) == 3 and all(abs(a - b) < 0.02 for a, b in zip(fill, NAVY))


drawings_cache: dict[int, list] = {}


def page_drawings(p: int) -> list:
    if p not in drawings_cache:
        drawings_cache[p] = doc[p - 1].get_drawings()
    return drawings_cache[p]


band_records = []
for p in RETRIEVAL_PAGES:
    rects = sorted((tuple(round(v, 1) for v in d["rect"]) for d in page_drawings(p)
                    if is_navy(d.get("fill")) and d["rect"].height >= 6 and d["rect"].width >= 20
                    and NAV_MAX_Y1 < d["rect"].y0 < FOOTER_MIN_Y0), key=lambda r: (r[1], r[0]))
    bands: list[list] = []
    for r in rects:                                   # connected components of touching rectangles
        hit = [b for b in bands if any(r[0] <= q[2] + 1 and q[0] <= r[2] + 1 and r[1] <= q[3] + 1 and q[1] <= r[3] + 1
                                       for q in b)]
        merged = [r] + [q for b in hit for q in b]
        bands = [b for b in bands if b not in hit] + [merged]
    for b in bands:
        bottom_row_y = max(q[1] for q in b)
        cols = sorted({(q[0], q[2]) for q in b if abs(q[1] - bottom_row_y) < 1})
        bx0, by0, bx1, by1 = min(q[0] for q in b), min(q[1] for q in b), max(q[2] for q in b), max(q[3] for q in b)
        inside = spans_df[(spans_df["page_number"] == p) & (spans_df["y0"] >= by0 - 1) & (spans_df["y1"] <= by1 + 1)
                          & (spans_df["x0"] >= bx0 - 1) & (spans_df["x1"] <= bx1 + 1)]
        band_records.append({"page_number": p, "x0": bx0, "y0": by0, "x1": bx1, "y1": by1, "n_cols": len(cols),
                             "cols": cols, "column": int(bx0 >= COLUMN_SPLIT_X),
                             "text": " | ".join(inside.sort_values(["y0", "x0"])["text"].str.strip())})

bands_df = pd.DataFrame(band_records).sort_values(["page_number", "column", "y0"]).reset_index(drop=True)


focal_lines = lines_df[lines_df["text"].str.startswith("Focal point:")]


def band_kind(r) -> str:
    focal = focal_lines[(focal_lines["page_number"] == r.page_number) & (focal_lines["y0"] >= r.y0 - 15)
                        & (focal_lines["y0"] <= r.y1) & ((focal_lines["x0"] - r.x0).abs() < 10)]
    if r.n_cols == 2 and len(focal) == 1:
        return "iro_box"
    if r.n_cols >= 2:
        return "table"
    return "chart_background"


bands_df["kind"] = [band_kind(r) for r in bands_df.itertuples()]
iro_starts = focal_lines[focal_lines["page_number"].isin(RETRIEVAL_PAGES)]

print(f"Spans (body zone, retrieval pages): {len(spans_df)}")
print("Header bands by kind:", bands_df["kind"].value_counts().to_dict())
print("'Focal point:' lines :", len(iro_starts), "on pages", iro_starts["page_number"].tolist())
with pd.option_context("display.max_rows", None, "display.max_colwidth", 90):
    display(bands_df[["page_number", "column", "x0", "y0", "x1", "y1", "n_cols", "kind", "text"]])

# %% cell 33
# =========================================================
# 4.2 Generic table grid extraction (span level)
# =========================================================
# Extent : from the header band down, 7.25pt lines inside the band's x-range, until a vertical
#          gap >= 14pt, the next header band, or a non-table font.
# Columns: header rectangles of the band's bottom row (reviewed overrides in 4.3 where the
#          printed layout indents subtotals into their own column).
# Cells  : spans of one column merged top-down while the line pitch is <= 11.2pt (wrapped text).
# Rows   : cells of the non-group columns merged when they overlap vertically (centred values).
# Notes  : a span that starts in the first column and runs across most of the table is a note row.

# table / box font size, taken from the data (7.25pt in the PDF; rounds to 7.3 with PyMuPDF's float sizes)
TABLE_FONT_SIZE = float(lines_df.loc[lines_df["text"].str.startswith("Focal point:"), "size"].mode().iloc[0])
assert 7.0 < TABLE_FONT_SIZE < 7.5, TABLE_FONT_SIZE
CELL_PITCH = 11.2
TABLE_GAP = 14.0

table_bands = bands_df[bands_df["kind"] == "table"].reset_index(drop=True)


def table_extent(band, next_band_y0: float) -> pd.DataFrame:
    cand = lines_df[(lines_df["page_number"] == band.page_number) & (lines_df["zone"] == "body")
                    & ~lines_df["is_subscript"] & (lines_df["y0"] >= band.y1 - 1) & (lines_df["y0"] < next_band_y0)
                    & (lines_df["x0"] >= band.x0 - 3) & (lines_df["x1"] <= band.x1 + 3)].sort_values("y0")
    keep, prev_y1 = [], band.y1
    for i, r in cand.iterrows():
        if r["size"] != TABLE_FONT_SIZE or r["y0"] - prev_y1 >= TABLE_GAP:
            break
        keep.append(i)
        prev_y1 = max(prev_y1, r["y1"])
    return cand.loc[keep]


def header_by_column(band, cols) -> list[str]:
    hs = spans_df[(spans_df["page_number"] == band.page_number) & (spans_df["y0"] >= band.y0 - 1)
                  & (spans_df["y1"] <= band.y1 + 1) & (spans_df["x0"] >= band.x0 - 1) & (spans_df["x1"] <= band.x1 + 1)]
    out = []
    for cx0, cx1 in cols:
        c = hs[(hs["x0"] >= cx0 - 2) & (hs["x0"] < cx1 - 1)].sort_values(["y0", "x0"])
        out.append(clean_line(" ".join(c["text"])))
    return out


def column_of_span(x0: float, cols) -> int:
    for i, (cx0, cx1) in enumerate(cols):
        if cx0 - 2 <= x0 < cx1 - 1:
            return i
    return -1


def build_grid(band, ext_lines: pd.DataFrame, cols, group_col: bool) -> dict:
    keys = set(zip(ext_lines["page_number"], ext_lines["block_no"], ext_lines["line_no"]))
    sp = spans_df[[k in keys for k in zip(spans_df["page_number"], spans_df["block_no"], spans_df["line_no"])]].copy()
    sp["col"] = [column_of_span(x, cols) for x in sp["x0"]]
    assert (sp["col"] >= 0).all(), f"p{band.page_number}: span outside the columns"
    # a note starts with a first-column span that runs across the column boundary; the wrapped
    # lines directly below it (alone on their row) belong to the same note
    sp["is_note"] = (sp["col"] == 0) & (sp["x1"] > cols[0][1] + 5)
    for _ in range(3):
        last_note_y = sp.loc[sp["is_note"], "y0"]
        for i, r in sp[~sp["is_note"] & (sp["col"] == 0)].iterrows():
            alone = (sp["y0"] - r["y0"]).abs().lt(2).sum() == 1
            if alone and ((r["y0"] - last_note_y).between(0.5, CELL_PITCH)).any():
                sp.at[i, "is_note"] = True
    notes = join_wrapped(sp[sp["is_note"]].sort_values("y0")["text"].tolist())
    sp = sp[~sp["is_note"]].sort_values(["col", "y0", "x0"])

    # cells: merge wrapped spans of one column
    cells = []
    for col, g in sp.groupby("col"):
        cur = None
        for r in g.itertuples():
            if cur and (r.y0 - cur["y_last"] <= CELL_PITCH):
                cur["parts"].append(r.text); cur["y_last"] = r.y0; cur["y1"] = max(cur["y1"], r.y1)
                cur["bold"] = cur["bold"] and r.is_bold
            else:
                cur = {"col": col, "y0": r.y0, "y1": r.y1, "y_last": r.y0, "parts": [r.text], "bold": r.is_bold}
                cells.append(cur)
    for c in cells:
        c["text"] = join_wrapped(c["parts"])

    # rows: vertical overlap of non-group cells
    body_cells = sorted([c for c in cells if not (group_col and c["col"] == 0)], key=lambda c: c["y0"])
    rows = []
    for c in body_cells:
        if rows and c["y0"] < rows[-1]["y1"] - 1:
            rows[-1]["cells"].append(c); rows[-1]["y1"] = max(rows[-1]["y1"], c["y1"])
        else:
            rows.append({"y0": c["y0"], "y1": c["y1"], "cells": [c]})
    groups = sorted([c for c in cells if group_col and c["col"] == 0], key=lambda c: c["y0"])
    for r in rows:
        prior = [g for g in groups if g["y0"] <= r["y1"]]
        r["group"] = prior[-1]["text"] if prior else None
    first_value_col = 1 + int(group_col)
    grid = []
    for r in rows:
        by_col = {}
        for c in sorted(r["cells"], key=lambda c: c["y0"]):
            by_col[c["col"]] = join_wrapped([by_col.get(c["col"], ""), c["text"]]) if c["col"] in by_col else c["text"]
        label_col = int(group_col)
        grid.append({"y0": r["y0"], "group": r["group"], "label": by_col.get(label_col),
                     "label_bold": any(c["bold"] for c in r["cells"] if c["col"] == label_col),
                     "values": [by_col.get(i) for i in range(first_value_col, len(cols))]})
    return {"notes": notes, "rows": grid, "n_spans": len(sp) + int(bool(notes))}


raw_tables = []
for i, band in enumerate(table_bands.itertuples()):
    same_col = table_bands[(table_bands["page_number"] == band.page_number) & (table_bands["column"] == band.column)
                           & (table_bands["y0"] > band.y0)]
    ext = table_extent(band, same_col["y0"].min() if len(same_col) else FOOTER_MIN_Y0)
    raw_tables.append({"table_id": f"tab_p{band.page_number}" + ("" if len(table_bands[table_bands["page_number"] == band.page_number]) == 1
                                                              else "abcd"[list(table_bands[table_bands["page_number"] == band.page_number].index).index(i)]),
                       "page_number": band.page_number, "band": band, "ext": ext,
                       "header_cols": header_by_column(band, band.cols)})

print(f"Tables detected: {len(raw_tables)}")
for t in raw_tables:
    b = t["band"]
    print(f"  {t['table_id']:8} p{b.page_number} col{b.column} y{b.y0:.0f}-{t['ext']['y1'].max():.0f} "
          f"cols={b.n_cols} lines={len(t['ext'])} | header: {t['header_cols']}")

# %% cell 34
# =========================================================
# 4.3 Table spec (reviewed 2026-09-25) + table_row units
# =========================================================
# header   : the printed header per column, exactly as detected in 4.2 (asserted)
# names    : column names used in the unit text (clarified only where the printed header is empty,
#            split over lines, or an unlabeled indicator column)
# title    : descriptive title built from the table's heading / introducing sentence (tables are unnumbered)
# group_col: first column holds group labels that span several rows (carried down)
# merge    : printed layout puts subtotals in their own column; logical value columns = merged physical ones
# unlabeled: label for rows that print values but no label
# Label-only rows (no values) are group labels: bold -> level 1, regular -> level 2; a subtotal row closes
# the level-2 group. Source errors are handled in TABLE_ERRATA (cell excluded, evidence recorded).

TABLE_SPECS = {
    "tab_p12": {"title": "Headcount of the Port of Rotterdam Authority by contract type and gender (as per 31-12-2025)",
                "header": ["Headcount", "Male", "Female", "X", "Total"],
                "names": ["Contract type", "Male", "Female", "X", "Total"]},
    "tab_p13": {"title": "Throughput in the port of Rotterdam by cargo type, 2025 vs 2024 (gross weight x 1,000 tonnes)",
                "header": ["(Gross weight x 1,000 tonnes)", "2025", "2024", "Difference (number)", "Difference (%)"],
                "names": ["Cargo type", "2025", "2024", "Difference (number)", "Difference (%)"]},
    "tab_p16": {"title": "Reputation survey 2025: scores of the Rotterdam port among local residents and the Dutch public",
                "header": ["Rotterdam port", "", "2025", "2023"], "names": ["Respondents", "Indicator", "2025", "2023"]},
    "tab_p17": {"title": "Reputation survey 2025: scores of the Port of Rotterdam Authority among local residents and the Dutch public",
                "header": ["Port of Rotterdam Authority", "", "2025", "2023"], "names": ["Respondents", "Indicator", "2025", "2023"]},
    "tab_p25": {"title": "Double materiality analysis: changes in the material themes from 2024 to 2025",
                "header": ["Changes to material themes", "Material themes 2025", "Material themes 2024"],
                "names": ["Category", "Material theme 2025", "Material themes 2024"], "group_col": True},
    "tab_p28a": {"title": "CO2e reduction objectives for scope 1, 2 and 3 emissions of the Port of Rotterdam Authority",
                 "header": ["Activity", "Objectives"], "names": ["Activity", "Objective"]},
    "tab_p28b": {"title": "CO2e reduction objectives beyond the value chain (clients' suppliers and consumers)",
                 "header": ["Activity", "Objectives"], "names": ["Activity", "Objective"]},
    "tab_p32": {"title": "Energy consumption of the Port of Rotterdam Authority by energy source (MWh)",
                "header": ["Energy sources", "Renewable energy consumption in MWh", "Fossil energy consumption in MWh",
                           "Total energy consumption in MWh"],
                "names": ["Energy source", "Renewable energy consumption in MWh", "Fossil energy consumption in MWh",
                          "Total energy consumption in MWh"]},
    "tab_p38": {"title": "Climate adaptation results: quality of port infrastructure sub-KPIs (scores)",
                "header": ["(Critical) Performance Indicators", "Achieved 2025", "Achieved 2024", "Achieved 2023", "Achieved 2022"],
                "names": ["Indicator", "Achieved 2025", "Achieved 2024", "Achieved 2023", "Achieved 2022"]},
    "tab_p40": {"title": "Air quality results: air pollutant emissions in the port and industrial complex (tonnes)",
                "header": ["(Critical) Performance Indicators", "Achieved 2023", "Achieved 2022", "Achieved 2021",
                           "Achieved 2020", "Achieved 2019"],
                "names": ["Indicator", "Achieved 2023", "Achieved 2022", "Achieved 2021", "Achieved 2020", "Achieved 2019"]},
    "tab_p54": {"title": "Occupational safety results: injury frequency rates at Port Authority locations",
                "header": ["(Critical) Performance Indicators", "Objective 2025", "Achieved 2025", "Achieved 2024", "Achieved 2023"],
                "names": ["Indicator", "Objective 2025", "Achieved 2025", "Achieved 2024", "Achieved 2023"]},
    "tab_p55": {"title": "Occupational safety: other performance indicators (PoR employees and outsourced work)",
                "header": ["Other Performance Indicators", "", "Achieved 2025", "Achieved 2024", "Achieved 2023"],
                "names": ["Group", "Indicator", "Achieved 2025", "Achieved 2024", "Achieved 2023"], "group_col": True},
    "tab_p62": {"title": "Subversive crime results: stakeholder appreciation score for the Port Authority's role",
                "header": ["(Critical) Performance Indicators", "Achieved 2025", "Achieved 2024", "Achieved 2023", "Achieved 2022"],
                "names": ["Indicator", "Achieved 2025", "Achieved 2024", "Achieved 2023", "Achieved 2022"]},
    "tab_p64": {"title": "Nautical safety results: major nautical incidents",
                "header": ["(Critical) Performance Indicators", "Objective 2025", "Achieved 2025", "Achieved 2024",
                           "Achieved 2023", "Achieved 2022"],
                "names": ["Indicator", "Objective 2025", "Achieved 2025", "Achieved 2024", "Achieved 2023", "Achieved 2022"]},
    "tab_p66": {"title": "Digital and physical resilience results: incidents in vital systems",
                "header": ["(Critical) Performance Indicators", "Objective 2025", "Achieved 2025", "Achieved 2024",
                           "Achieved 2023", "Achieved 2022"],
                "names": ["Indicator", "Objective 2025", "Achieved 2025", "Achieved 2024", "Achieved 2023", "Achieved 2022"]},
    "tab_p73a": {"title": "Members of the Supervisory Board: term, appointment date and final year of current term",
                 "header": ["Name", "Term", "Appointment", "Final year of current term"],
                 "names": ["Name", "Term", "Appointment", "Final year of current term"]},
    "tab_p73b": {"title": "Members of the Executive Board: term, appointment date and final year of current term",
                 "header": ["Name", "Term", "Appointment", "Final year of current term"],
                 "names": ["Name", "Term", "Appointment", "Final year of current term"],
                 "unlabeled": "Member (name not printed in the report)"},
    "tab_p82a": {"title": "Balance sheet of the Port of Rotterdam Authority (before result appropriation, x EUR 1,000)",
                 "header": ["Balance sheet (Before result appropriation x € 1.000)", "31. December 2025", "",
                            "31. December 2024", ""],
                 "names": ["Item", "31 December 2025", "31 December 2024"], "merge": [[0, 1], [2, 3]],
                 "unlabeled": "subtotal"},
    "tab_p82b": {"title": "Income statement (profit and loss account) of the Port of Rotterdam Authority (x EUR 1,000)",
                 "header": ["Profit and loss account (Amounts x € 1000)", "", "2025", "", "2024"],
                 "names": ["Item", "2025", "2024"], "merge": [[0, 1], [2, 3]]},
    "tab_p83a": {"title": "Key figures: throughput in the port of Rotterdam by cargo segment, 2025 vs 2024 (gross weight x 1,000 tonnes)",
                 "header": ["Throughput (Gross weight x 1,000 tonnes)", "2025", "2024", "Difference (number)", "Difference (%)"],
                 "names": ["Cargo segment", "2025", "2024", "Difference (number)", "Difference (%)"]},
    "tab_p83b": {"title": "Key figures of the port of Rotterdam and the Port Authority, 2021–2025",
                 "header": ["Keyfigures", "Unit", "2025", "2024", "2023", "2022", "2021"],
                 "names": ["Key figure", "Unit", "2025", "2024", "2023", "2022", "2021"]},
}

# Source errors found while reviewing the tables (evidence from the PDF itself); the cell is excluded.
TABLE_ERRATA = {
    ("tab_p83a", "Deepsea containers", "Difference (%)"): (
        "Printed '-1.5%' contradicts the row's own values (90,294 vs 86,701, difference +3,593 = +4.1%); "
        "'-1.5%' repeats the liquid-bulk subtotal. Cell excluded, the correct figures stay in the row."),
    ("tab_p83a", "Containers", "2024"): (
        "Printed '133,4' is truncated: the same row on p.13 prints 133,400, consistent with 133,167 and -232. "
        "Cell excluded (the complete row is kept in tab_p13)."),
}

detected_ids = [t["table_id"] for t in raw_tables]
assert detected_ids == list(TABLE_SPECS), f"Detected tables differ from the spec: {set(detected_ids) ^ set(TABLE_SPECS)}"


def format_value_row(label_path: str, names: list[str], values: list, table_id: str, errata_used: list) -> str:
    parts = []
    for name, value in zip(names, values):
        if value is None or not str(value).strip():
            continue
        key = (table_id, label_path.split(" > ")[-1], name)
        if key in TABLE_ERRATA:
            errata_used.append(key)
            continue
        parts.append(f"{name}: {value}")
    return f"{label_path} — " + "; ".join(parts) if parts else label_path


table_unit_records, table_meta_records, table_region_records, errata_used = [], [], [], []
for t in raw_tables:
    spec, band = TABLE_SPECS[t["table_id"]], t["band"]
    assert t["header_cols"] == spec["header"], f"{t['table_id']}: printed header {t['header_cols']}"
    grid = build_grid(band, t["ext"], band.cols, spec.get("group_col", False))
    names = spec["names"]
    first_value = 1 + int(spec.get("group_col", False))
    value_names = names[first_value:]
    lvl1 = lvl2 = None
    rows_out = []
    for r in grid["rows"]:
        values = r["values"]
        if "merge" in spec:
            values = [next((values[i] for i in grp if values[i]), None) for grp in spec["merge"]]
        has_values = any(v for v in values)
        if r["label"] and not has_values:                      # group label row
            if r["label_bold"]:
                lvl1, lvl2 = r["label"].rstrip(":"), None
            else:
                lvl2 = r["label"].rstrip(":")
            continue
        label = r["label"]
        if label is None:
            unl = spec.get("unlabeled")
            assert unl, f"{t['table_id']}: row without label at y={r['y0']}"
            label = f"Subtotal {lvl2 or lvl1}" if unl == "subtotal" else unl
        path = [x for x in (r["group"], lvl1, lvl2, label) if x]
        label_path = " > ".join(dict.fromkeys(path))
        rows_out.append({"label_path": label_path, "label": label, "values": values, "y0": r["y0"]})
        if label.startswith("Subtotal"):
            lvl2 = None

    header_line = f"Table: {spec['title']}"
    note_line = f"Note: {grid['notes']}" if grid["notes"] else None
    for k, row in enumerate(rows_out, start=1):
        row_text = format_value_row(row["label_path"], value_names, row["values"], t["table_id"], errata_used)
        table_unit_records.append({
            "unit_id": f"{t['table_id']}_r{k:02d}", "unit_type": "table_row",
            "page_start": band.page_number, "page_end": band.page_number,
            "title": f"{spec['title']} — {row['label']}",
            "content": "\n".join(x for x in (header_line, note_line, row_text) if x),
            "row_text": row_text, "table_header_text": "\n".join(x for x in (header_line, note_line) if x),
            "table_id": t["table_id"], "figure_id": None, "row_label": row["label"],
            "anchor_y0": float(band.y0), "anchor_column": int(band.column),
        })
    ext = t["ext"]
    table_meta_records.append({"table_id": t["table_id"], "page_number": band.page_number, "title": spec["title"],
                               "columns": names, "n_rows": len(rows_out), "note": grid["notes"] or None})
    table_region_records.append({"region_id": f"region_{t['table_id']}", "kind": "table", "ref": t["table_id"],
                                 "page_number": band.page_number, "x0": band.x0, "y0": band.y0,
                                 "x1": max(band.x1, ext["x1"].max()), "y1": max(band.y1, ext["y1"].max())})

table_units_df = pd.DataFrame(table_unit_records)
table_meta_df = pd.DataFrame(table_meta_records)
table_regions_df = pd.DataFrame(table_region_records)

# ---- validation ----
REVIEWED_ROWS = {"tab_p12": 4, "tab_p13": 9, "tab_p16": 4, "tab_p17": 4, "tab_p25": 11, "tab_p28a": 7, "tab_p28b": 2,
                 "tab_p32": 9, "tab_p38": 5, "tab_p40": 3, "tab_p54": 2, "tab_p55": 3, "tab_p62": 1, "tab_p64": 1,
                 "tab_p66": 1, "tab_p73a": 6, "tab_p73b": 4, "tab_p82a": 19, "tab_p82b": 13, "tab_p83a": 23, "tab_p83b": 13}
assert table_meta_df.set_index("table_id")["n_rows"].to_dict() == REVIEWED_ROWS, table_meta_df.set_index("table_id")["n_rows"].to_dict()
assert sorted(errata_used) == sorted(TABLE_ERRATA), f"Errata not applied exactly once: {errata_used}"
assert table_units_df["unit_id"].is_unique
assert not table_units_df["content"].map(lambda s: any(unicodedata.category(ch).startswith("C") and ch != "\n" for ch in s)).any()

# every printed span of every table is in its units (header, notes, labels, values), except the errata cells
for t in raw_tables:
    unit_text = " ".join(table_units_df.loc[table_units_df["table_id"] == t["table_id"], "content"]) + " " + \
        " ".join(TABLE_SPECS[t["table_id"]]["header"])
    keys = set(zip(t["ext"]["page_number"], t["ext"]["block_no"], t["ext"]["line_no"]))
    sp = spans_df[[k in keys for k in zip(spans_df["page_number"], spans_df["block_no"], spans_df["line_no"])]]
    errata_values = {"-1.5%": "tab_p83a", "133,4": "tab_p83a"}
    missing = [s for s in sp["text"].map(clean_line) if s not in unit_text and errata_values.get(s) != t["table_id"]]
    group_labels = [m for m in missing if m.rstrip(":") in unit_text]
    missing = [m for m in missing if m not in group_labels]
    assert not missing, f"{t['table_id']}: printed text missing from its units: {missing}"

print(f"✅ Table units built: {len(table_units_df)} rows from {len(table_meta_df)} tables")
print("Errata applied:", len(errata_used))
with pd.option_context("display.max_colwidth", 110, "display.max_rows", None):
    display(table_meta_df[["table_id", "page_number", "n_rows", "title", "note"]])
for uid in ["tab_p13_r01", "tab_p25_r08", "tab_p55_r03", "tab_p82a_r04", "tab_p83a_r13", "tab_p73b_r02", "tab_p40_r01"]:
    print("\n---", uid)
    print(table_units_df.set_index("unit_id").at[uid, "content"])

# %% cell 35
# =========================================================
# 4.4 Impacts, risks and opportunities (IRO) boxes -> one `iro_box` unit per ESG theme
# =========================================================
# Layout (reviewed on the 11 boxes): a 7.25pt two-column box that starts with "Focal point:".
#   left column : "Focal point:", then the theme label (may wrap: "Digital and physical / resilience")
#   right column: the focal point, then the theme definition (bold), then the impact description
#                 (regular; paragraphs separated by a pitch > 11.2pt)
# Lines (not spans) are used so the CO2 subscripts merged in Phase 3 are kept.

iro_bands = bands_df[bands_df["kind"] == "iro_box"]
host_lines = set(lines_df["subscript_host"].dropna().astype(int))
iro_unit_records, iro_region_records = [], []

for f in focal_lines[focal_lines["page_number"].isin(RETRIEVAL_PAGES)].sort_values("page_number").itertuples():
    band = iro_bands[(iro_bands["page_number"] == f.page_number) & (iro_bands["y0"] >= f.y0 - 15)].iloc[0]
    split_x = band["cols"][1][0]
    cand = lines_df[(lines_df["page_number"] == f.page_number) & (lines_df["zone"] == "body") & ~lines_df["is_subscript"]
                    & (lines_df["y0"] >= f.y0 - 0.5) & (lines_df["x0"] >= band["x0"] - 3)
                    & (lines_df["x1"] <= band["x1"] + 3)].sort_values(["y0", "x0"])
    box, prev_y1 = [], f.y0
    for i, r in cand.iterrows():
        if r["size"] != TABLE_FONT_SIZE or r["y0"] - prev_y1 >= TABLE_GAP:
            break
        box.append(i)
        prev_y1 = max(prev_y1, r["y1"])
    bl = lines_df.loc[box]
    left, right = bl[bl["x0"] < split_x - 2], bl[bl["x0"] >= split_x - 2]
    focal_value = right[(right["y0"] - f.y0).abs() < 1]["text_merged"].iloc[0]
    theme = join_wrapped(left[left["y0"] > f.y0 + 1]["text_merged"].tolist()).rstrip(":")
    rest = right[right["y0"] > f.y0 + 1]
    definition = join_wrapped(rest[rest["is_bold"]]["text_merged"].tolist())
    desc_lines = rest[~rest["is_bold"]]
    paragraphs, cur, last_y = [], [], None
    for r in desc_lines.itertuples():
        if last_y is not None and r.y0 - last_y > CELL_PITCH:
            paragraphs.append(join_wrapped(cur)); cur = []
        cur.append(r.text_merged); last_y = r.y0
    paragraphs.append(join_wrapped(cur))
    content = "\n".join([f"Impacts, risks and opportunities — {theme}", f"Focal point: {focal_value}",
                         f"{theme}: {definition}", *paragraphs])
    uid = f"iro_p{f.page_number}"
    iro_unit_records.append({"unit_id": uid, "unit_type": "iro_box", "page_start": f.page_number,
                             "page_end": f.page_number, "title": f"Impacts, risks and opportunities: {theme}",
                             "content": content, "table_id": None, "figure_id": None, "row_label": theme,
                             "anchor_y0": float(f.y0), "anchor_column": 0, "n_lines": len(bl)})
    iro_region_records.append({"region_id": f"region_{uid}", "kind": "iro_box", "ref": uid, "page_number": f.page_number,
                               "x0": min(band["x0"], bl["x0"].min()), "y0": min(band["y0"], bl["y0"].min()),
                               "x1": max(band["x1"], bl["x1"].max()), "y1": max(band["y1"], bl["y1"].max())})

iro_units_df = pd.DataFrame(iro_unit_records)
iro_regions_df = pd.DataFrame(iro_region_records)

# ---- validation ----
REVIEWED_IRO_THEMES = ["Climate mitigation", "Climate adaptation", "Air pollution", "Soil contamination", "Water pollution",
                       "Nature & biodiversity", "Occupational safety", "Chain responsibility", "Subversive crime",
                       "Nautical safety", "Digital and physical resilience"]
assert iro_units_df["row_label"].tolist() == REVIEWED_IRO_THEMES, iro_units_df["row_label"].tolist()
assert len(iro_units_df) == len(iro_bands), "Every IRO header band must give exactly one box."
for r in iro_units_df.itertuples():
    lines = lines_df[(lines_df["page_number"] == r.page_start)]
    reg = iro_regions_df.set_index("ref").loc[r.unit_id]
    inside = lines[(lines["x0"] >= reg["x0"] - 3) & (lines["x1"] <= reg["x1"] + 3) & (lines["y0"] >= reg["y0"] - 1)
                   & (lines["y1"] <= reg["y1"] + 1) & ~lines["is_subscript"]]
    letters = lambda s: re.sub(r"[^0-9a-z]", "", s.lower())
    missing = [t for t in inside["text_merged"] if letters(t) not in letters(r.content)]
    assert not missing, f"{r.unit_id}: lines missing from the unit: {missing}"
    assert (inside["size"] == TABLE_FONT_SIZE).all(), f"{r.unit_id}: non-box font inside the box region"

print(f"✅ IRO boxes: {len(iro_units_df)}")
print(iro_units_df.set_index("unit_id").at["iro_p27", "content"])
print()
print(iro_units_df.set_index("unit_id").at["iro_p65", "content"])

# %% cell 36
# =========================================================
# 4.5 Text boxes ("spotlight" boxes, 7.25pt prose with a bold title) -> `box` units
# =========================================================
# Every 7.25pt line of a retrieval page that is not in a table or an IRO box, grouped by page,
# column and vertical proximity. Reviewed: exactly four such boxes, each opening with a bold title.

def in_regions(df: pd.DataFrame, regions: pd.DataFrame) -> pd.Series:
    mask = pd.Series(False, index=df.index)
    for r in regions.itertuples():
        mask |= ((df["page_number"] == r.page_number) & (df["x1"] > r.x0 + 1) & (df["x0"] < r.x1 - 1)
                 & (df["y1"] > r.y0 + 1) & (df["y0"] < r.y1 - 1))
    return mask


small = lines_df[lines_df["page_number"].isin(RETRIEVAL_PAGES) & (lines_df["zone"] == "body")
                 & (lines_df["size"] == TABLE_FONT_SIZE) & ~lines_df["is_subscript"]]
small = small[~in_regions(small, pd.concat([table_regions_df, iro_regions_df]))].sort_values(["page_number", "column", "y0"])

box_groups = []
for i, r in small.iterrows():
    g = box_groups[-1] if box_groups else None
    if g and g["page_number"] == r["page_number"] and g["column"] == r["column"] and r["y0"] - g["y1"] < TABLE_GAP:
        g["idx"].append(i); g["y1"] = max(g["y1"], r["y1"])
    else:
        box_groups.append({"page_number": r["page_number"], "column": r["column"], "y1": r["y1"], "idx": [i]})

box_unit_records, box_region_records = [], []
for g in box_groups:
    bl = lines_df.loc[g["idx"]].sort_values("y0")
    title = join_wrapped(bl[bl["is_bold"]]["text_merged"].tolist())
    body = bl[~bl["is_bold"]]
    assert bl.iloc[0]["is_bold"] and len(body), f"p{g['page_number']}: a 7.25pt text group without a bold title"
    paragraphs, cur, last_y = [], [], None
    for r in body.itertuples():
        if last_y is not None and r.y0 - last_y > CELL_PITCH:
            paragraphs.append(join_wrapped(cur)); cur = []
        cur.append(r.text_merged); last_y = r.y0
    paragraphs.append(join_wrapped(cur))
    uid = f"box_p{g['page_number']}"
    box_unit_records.append({"unit_id": uid, "unit_type": "box", "page_start": g["page_number"], "page_end": g["page_number"],
                             "title": title, "content": "\n".join([title, *paragraphs]), "table_id": None, "figure_id": None,
                             "row_label": None, "anchor_y0": float(bl["y0"].min()), "anchor_column": int(g["column"])})
    box_region_records.append({"region_id": f"region_{uid}", "kind": "box", "ref": uid, "page_number": g["page_number"],
                               "x0": bl["x0"].min(), "y0": bl["y0"].min(), "x1": bl["x1"].max(), "y1": bl["y1"].max()})

box_units_df = pd.DataFrame(box_unit_records)
box_regions_df = pd.DataFrame(box_region_records)

REVIEWED_BOXES = {"box_p28": "Shore power strategy 2025-2035 in the spotlight",
                  "box_p30": "Rotterdam Shore Power takes the next step in the realisation of shore power",
                  "box_p31": "Carbonbid stimulates CO2e reduction in the port area",
                  "box_p50": "Nature vision in the spotlight"}
assert dict(zip(box_units_df["unit_id"], box_units_df["title"])) == REVIEWED_BOXES, box_units_df[["unit_id", "title"]]

print(f"✅ Text boxes: {len(box_units_df)}")
for r in box_units_df.itertuples():
    print(f"\n--- {r.unit_id} ({len(r.content)} chars)\n{r.content[:400]} …")

# %% cell 37
# =========================================================
# 4.6 Milestone cards ("2.1 Milestones 2025", four columns per page) -> `milestone` units
# =========================================================
# Each card = photo + bold title (Bold 8pt, may wrap) + text, in one of four column bands whose
# x-extent is given by the card photos (image placements). Titles were excluded from the headings in 3.5.

MILESTONE_PAGES = signals_df.loc[signals_df["active_nav"] == "2025 at a glance", "page_number"].tolist()
milestone_unit_records, milestone_region_records = [], []

for p in MILESTONE_PAGES:
    photos = sorted(tuple(i["bbox"]) for i in doc[p - 1].get_image_info())
    pl = lines_df[(lines_df["page_number"] == p) & (lines_df["zone"] == "body") & (lines_df["size"] == BODY_FONT_SIZE)
                  & ~lines_df["is_subscript"]]
    for k, ph in enumerate(photos, start=1):
        cl = pl[(pl["x0"] >= ph[0] - 2) & (pl["x0"] < ph[2]) & (pl["y0"] > ph[3])].sort_values("y0")
        title = join_wrapped(cl[cl["all_bold"]]["text_merged"].tolist())
        body = join_wrapped(cl[~cl["all_bold"]]["text_merged"].tolist())
        uid = f"milestone_p{p}_{k}"
        milestone_unit_records.append({"unit_id": uid, "unit_type": "milestone", "page_start": p, "page_end": p,
                                       "title": f"Milestone 2025: {title}", "content": f"Milestone 2025: {title}\n{body}",
                                       "table_id": None, "figure_id": None, "row_label": title,
                                       "anchor_y0": float(cl["y0"].min()), "anchor_column": 0, "n_lines": len(cl)})
        milestone_region_records.append({"region_id": f"region_{uid}", "kind": "milestone", "ref": uid, "page_number": p,
                                         "x0": ph[0], "y0": ph[1], "x1": max(ph[2], cl["x1"].max()), "y1": cl["y1"].max()})

milestone_units_df = pd.DataFrame(milestone_unit_records)
milestone_regions_df = pd.DataFrame(milestone_region_records)

# ---- validation ----
card_lines = sum(milestone_units_df["n_lines"])
page_card_lines = lines_df[lines_df["page_number"].isin(MILESTONE_PAGES) & (lines_df["zone"] == "body")
                           & (lines_df["size"] == BODY_FONT_SIZE)]
assert card_lines == len(page_card_lines), "Every 8pt line of the milestone pages must belong to one card."
REVIEWED_MILESTONES = ["Port of Rotterdam Authority partner of Jeugdeducatiefonds", "Opening of Portlantis",
                       "Shore power installations in the port of Rotterdam",
                       "Together towards a competitive, sustainable and resilient port in 2050",
                       "Start construction of Maasvlakte Zuid railway yard", "The Port of Rotterdam Authority presents the new Nature Vision",
                       "The Port of Rotterdam Authority continues to invest in the surroundings",
                       "Most sustainable client in construction"]
assert milestone_units_df["row_label"].tolist() == REVIEWED_MILESTONES, milestone_units_df["row_label"].tolist()

print(f"✅ Milestone cards: {len(milestone_units_df)}")
with pd.option_context("display.max_colwidth", 140):
    display(milestone_units_df[["unit_id", "n_lines", "content"]])

# %% cell 38
# =========================================================
# 4.7 Graphics inventory, regions and text elements
# =========================================================
# Three kinds of evidence, all checked for completeness:
#   a) image placements >= 1,000 pt² on retrieval pages (photos and raster infographics);
#      smaller placements are decorative icons (IRO boxes, org chart) — listed, not units;
#   b) dense vector drawings (>= 60 drawing objects in one page column outside tables/boxes):
#      maps and diagrams whose text is drawn as outlines (no extractable text);
#   c) chart text: body lines smaller than 7pt that are not subscripts (plus the 8.3pt chart title).
# GRAPHICS gives each graphic an id, kind and search window (reviewed against renders); the exact
# region is computed from the evidence inside the window.

GRAPHICS = {
    "fig_p11": {"page": 11, "kind": "raster_infographic", "window": (40, 100, 750, 445)},
    "fig_p13": {"page": 13, "kind": "text_chart", "window": (40, 50, 415, 310)},
    "fig_p15": {"page": 15, "kind": "vector_graphic", "window": (40, 225, 420, 445)},
    "fig_p19": {"page": 19, "kind": "vector_graphic", "window": (40, 285, 420, 400)},
    "fig_p23": {"page": 23, "kind": "raster_infographic", "window": (40, 50, 800, 425)},
    "fig_p26": {"page": 26, "kind": "vector_graphic", "window": (415, 50, 800, 262)},
    "fig_p33a": {"page": 33, "kind": "text_chart", "window": (40, 50, 415, 310)},
    "fig_p33b": {"page": 33, "kind": "text_chart", "window": (440, 140, 800, 360)},
    "fig_p45": {"page": 45, "kind": "raster_infographic", "window": (40, 50, 415, 295)},
    "fig_p47": {"page": 47, "kind": "raster_infographic", "window": (430, 50, 802, 295)},
    "fig_p49a": {"page": 49, "kind": "raster_infographic", "window": (40, 50, 415, 380)},
    "fig_p49b": {"page": 49, "kind": "raster_infographic", "window": (430, 190, 802, 400)},
    "fig_p58": {"page": 58, "kind": "raster_infographic", "window": (40, 60, 530, 322), "caption_y": (310, 322)},
    "fig_p69": {"page": 69, "kind": "vector_graphic", "window": (40, 60, 615, 395)},
    "fig_p71": {"page": 71, "kind": "raster_infographic", "window": (40, 165, 802, 415)},
}
REVIEWED_PHOTO_PAGES = [3, 6, 6, 6, 6, 7, 7, 7, 7, 10, 38, 41, 43, 46, 51, 55, 63, 75]
MIN_IMAGE_AREA = 1000.0
DENSE_DRAWINGS = 60

structured_so_far = pd.concat([table_regions_df, iro_regions_df, box_regions_df, milestone_regions_df], ignore_index=True)


def inside(bbox, window, tol=2.0) -> bool:
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    return window[0] - tol <= cx <= window[2] + tol and window[1] - tol <= cy <= window[3] + tol


def clip(b):
    return (max(b[0], 0.0), max(b[1], 0.0), min(b[2], float(pages_df["page_width"].iloc[0])),
            min(b[3], float(pages_df["page_height"].iloc[0])))


# ---- a) image placements ----
img_records = []
for p in RETRIEVAL_PAGES:
    for k, info in enumerate(doc[p - 1].get_image_info(), start=1):
        b = clip(tuple(info["bbox"]))
        area = (b[2] - b[0]) * (b[3] - b[1])
        gid = next((g for g, s in GRAPHICS.items() if s["page"] == p and s["kind"] == "raster_infographic"
                    and inside(b, s["window"])), None)
        kind = "raster_infographic" if gid else ("photo" if area >= MIN_IMAGE_AREA else "decorative_icon")
        img_records.append({"page_number": p, "image_no": k, "x0": b[0], "y0": b[1], "x1": b[2], "y1": b[3],
                            "area": round(area), "kind": kind, "graphic_id": gid})
images_df = pd.DataFrame(img_records)

# ---- b) dense vector drawings outside tables / boxes / cards ----
def outside_structured(p, r) -> bool:
    rg = structured_so_far[structured_so_far["page_number"] == p]
    cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
    return not ((rg["x0"] - 2 <= cx) & (cx <= rg["x1"] + 2) & (rg["y0"] - 2 <= cy) & (cy <= rg["y1"] + 2)).any()


draw_records = []
for p in RETRIEVAL_PAGES:
    for d in page_drawings(p):
        r = d["rect"]
        if r.y1 <= NAV_MAX_Y1 + 2 or r.y0 >= FOOTER_MIN_Y0 or not outside_structured(p, r):
            continue
        draw_records.append({"page_number": p, "column": int(r.x0 >= COLUMN_SPLIT_X),
                             "x0": r.x0, "y0": r.y0, "x1": r.x1, "y1": r.y1})
drawings_df = pd.DataFrame(draw_records)
dense = drawings_df.groupby(["page_number", "column"]).size().rename("n").reset_index()
dense = dense[dense["n"] >= DENSE_DRAWINGS]

# ---- c) chart text elements ----
chart_lines = lines_df[lines_df["page_number"].isin(RETRIEVAL_PAGES) & (lines_df["zone"] == "body")
                       & ~lines_df["is_subscript"] & ((lines_df["size"] < 7.0) | lines_df["font"].eq("Arimo-Bold")
                                                      | ((lines_df["size"] == 8.3)))]

# ---- regions ----
figure_region_records, element_records = [], []
for gid, s in GRAPHICS.items():
    p, w = s["page"], s["window"]
    boxes = []
    if s["kind"] == "raster_infographic":
        boxes += [(r.x0, r.y0, r.x1, r.y1) for r in images_df[images_df["graphic_id"] == gid].itertuples()]
    dr = drawings_df[(drawings_df["page_number"] == p)]
    boxes += [(r.x0, r.y0, r.x1, r.y1) for r in dr.itertuples()          # drawings fully inside the window
              if w[0] - 2 <= r.x0 and r.x1 <= w[2] + 2 and w[1] - 2 <= r.y0 and r.y1 <= w[3] + 2
              and s["kind"] in ("vector_graphic", "text_chart")]
    els = chart_lines[(chart_lines["page_number"] == p)]
    els = els[[inside((a, b, c, d), w) for a, b, c, d in zip(els["x0"], els["y0"], els["x1"], els["y1"])]]
    boxes += [(r.x0, r.y0, r.x1, r.y1) for r in els.itertuples()]
    if "caption_y" in s:
        cap = lines_df[(lines_df["page_number"] == p) & lines_df["y0"].between(*s["caption_y"])]
        boxes += [(r.x0, r.y0, r.x1, r.y1) for r in cap.itertuples()]
        els = pd.concat([els, cap])
    assert boxes, f"{gid}: no evidence found in its window"
    x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    figure_region_records.append({"region_id": f"region_{gid}", "kind": "figure", "ref": gid, "page_number": p,
                                  "x0": round(x0, 1), "y0": round(y0, 1), "x1": round(x1, 1), "y1": round(y1, 1),
                                  "graphic_kind": s["kind"], "n_text_lines": len(els)})
    for r in els.itertuples():
        element_records.append({"figure_id": gid, "page_number": p, "block_no": r.block_no, "line_no": r.line_no,
                                "x0": r.x0, "y0": r.y0, "x1": r.x1, "size": r.size, "font": r.font,
                                "is_bold": r.is_bold, "text": clean_line(r.text_merged)})
figure_regions_df = pd.DataFrame(figure_region_records)
figure_elements_df = pd.DataFrame(element_records)

# ---- completeness ----
photos = images_df[images_df["kind"] == "photo"]
assert sorted(photos["page_number"]) == REVIEWED_PHOTO_PAGES, f"Photo inventory changed: {sorted(photos['page_number'])}"
assert set(images_df.loc[images_df["kind"] == "raster_infographic", "graphic_id"]) == \
    {g for g, s in GRAPHICS.items() if s["kind"] == "raster_infographic"}, "A raster infographic has no image."
for r in dense.itertuples():
    covered = [g for g, s in GRAPHICS.items() if s["page"] == r.page_number and s["kind"] in ("vector_graphic", "text_chart")]
    assert covered, f"Dense drawings on p{r.page_number} col{r.column} are not covered by GRAPHICS."
element_keys = set(zip(figure_elements_df["page_number"], figure_elements_df["block_no"], figure_elements_df["line_no"]))
assert set(zip(chart_lines["page_number"], chart_lines["block_no"], chart_lines["line_no"])) <= element_keys, \
    "A chart text line is not inside any graphic window."

print("Image placements:", images_df["kind"].value_counts().to_dict())
print("Dense vector drawings (page, column, n):", dense.values.tolist())
print("Chart text lines:", len(chart_lines))
display(figure_regions_df)

# %% cell 39
# =========================================================
# 4.8 (prep) Render graphic regions + element dumps for review
# =========================================================
# Temporary review aids for the value gate — NOT part of the corpus (Notebooks/_scratch is git-ignored).

REVIEW_DIR = SCRATCH_DIR / "figure_renders"
REVIEW_DIR.mkdir(parents=True, exist_ok=True)
RENDER_ZOOM, PAD = 2.5, 6

for r in figure_regions_df.itertuples():
    page = doc[r.page_number - 1]
    clip_rect = pymupdf.Rect(r.x0 - PAD, r.y0 - PAD, r.x1 + PAD, r.y1 + PAD).intersect(page.rect)
    page.get_pixmap(matrix=pymupdf.Matrix(RENDER_ZOOM, RENDER_ZOOM), clip=clip_rect).save(REVIEW_DIR / f"{SOURCE_NAME}_{r.ref}.png")
    els = figure_elements_df[figure_elements_df["figure_id"] == r.ref]
    (REVIEW_DIR / f"{SOURCE_NAME}_{r.ref}_elements.txt").write_text(
        "\n".join(f"y={e.y0:6.1f} x={e.x0:6.1f} size={e.size:4.1f} | {e.text}" for e in els.itertuples()), encoding="utf-8")

saved = sorted(p.name for p in REVIEW_DIR.glob(f"{SOURCE_NAME}_*"))
print(f"Saved {len(saved)} review files to {REVIEW_DIR.relative_to(PROJECT_ROOT)}")

# %% cell 40
# =========================================================
# 4.9 Chart evidence: which printed number belongs to which year / step?
# =========================================================
# The bar values are vector drawings; the only data are the printed labels. A label belongs to the
# category whose axis label has the nearest x-centre. p.33 prints every chart label twice (a Dutch and
# an English text layer: "31,3" and "31.3"); decimal commas are normalised before comparing.

def num_value(t: str):
    t = t.replace(" ", "").replace("−", "-")
    t = re.sub(r"^(-?\d+),(\d)$", r"\1.\2", t)          # decimal comma "9,6" -> "9.6"
    try:
        return float(t)
    except ValueError:
        return None


def nearest_label_map(els: pd.DataFrame, cats: pd.DataFrame, values: pd.DataFrame, max_dx: float = 9.0) -> dict:
    out = {}
    cx = (cats["x0"] + cats["x1"]) / 2
    for v in values.itertuples():
        vx = (v.x0 + v.x1) / 2
        k = (cx - vx).abs().idxmin()
        if abs(cx[k] - vx) <= max_dx:
            out.setdefault(cats.at[k, "text"], set()).add(num_value(v.text))
    return out


# ---- fig_p13: totals (bold labels) per year ----
e13 = figure_elements_df[figure_elements_df["figure_id"] == "fig_p13"]
years13 = e13[e13["text"].str.fullmatch(r"20\d\d")]
totals13 = e13[e13["is_bold"] & e13["text"].str.fullmatch(r"\d+\.\d")]
FIG_P13_TOTALS = {y: sorted(v) for y, v in nearest_label_map(e13, years13, totals13).items()}

# ---- fig_p33a: totals (largest-font labels) per year ----
e33a = figure_elements_df[figure_elements_df["figure_id"] == "fig_p33a"]
years33 = e33a[e33a["text"].str.fullmatch(r"20\d\d")].drop_duplicates("text")
tot_size = e33a.loc[e33a["text"].map(num_value).notna() & ~e33a["text"].str.fullmatch(r"20\d\d"), "size"].max()
totals33 = e33a[(e33a["size"] >= tot_size - 0.2) & e33a["text"].map(num_value).notna()
                & ~e33a["text"].str.fullmatch(r"20\d\d")]
FIG_P33A_TOTALS = {y: sorted(v) for y, v in nearest_label_map(e33a, years33, totals33).items()}

# ---- fig_p33b: waterfall step labels ----
e33b = figure_elements_df[figure_elements_df["figure_id"] == "fig_p33b"]
steps = e33b[e33b["y0"] > 330].copy()                                   # category labels under the bars
vals = e33b[(e33b["y0"] < 330) & e33b["text"].map(lambda t: num_value(t) is not None) & (e33b["size"] >= 4.0)]
FIG_P33B_STEPS = {}
for v in vals.itertuples():
    vx = (v.x0 + v.x1) / 2
    near = steps.assign(d=((steps["x0"] + steps["x1"]) / 2 - vx).abs()).sort_values("d")
    label_x = near.iloc[0]["x0"]
    label = " ".join(steps[(steps["x0"] - label_x).abs() < 14].sort_values(["x0", "y0"])["text"])
    FIG_P33B_STEPS[label] = num_value(v.text)

print("fig_p13  totals by year :", FIG_P13_TOTALS)
print("fig_p33a totals by year :", FIG_P33A_TOTALS)
print("fig_p33b steps          :", FIG_P33B_STEPS)

assert FIG_P13_TOTALS == {"2021": [226.3], "2022": [257.0], "2023": [295.4], "2024": [320.6], "2025": [291.4]}
assert FIG_P33A_TOTALS == {"2016": [31.3], "2017": [29.1], "2018": [27.0], "2019": [26.0], "2020": [23.1],
                           "2021": [24.2], "2022": [23.2], "2023": [20.8], "2024": [19.1]}
assert FIG_P33B_STEPS == {"2024": 19.1, "Capture CO2": -3.5, "Coalpower plant ban": -3.3, "Closing industry": -0.3,
                          "Biofuels": -0.2, "Efficiency": -0.9, "Electrificati on": -0.2, "Green hydrogen": -0.2,
                          "Other": 0.5, "2030": 11.1}
assert abs(19.1 + sum(v for k, v in FIG_P33B_STEPS.items() if k not in ("2024", "2030")) - 11.1) <= 0.15, \
    "Waterfall steps must add up (within rounding) from 2024 to 2030."
assert FIG_P13_TOTALS["2025"] == [291.4], "Chart total must equal the prose (gross investments EUR 291.4 million)."

# %% cell 41
# =========================================================
# 4.10 Value gate — reviewed decisions (2026-09-25)
# =========================================================
# Reviewed against the renders (4.8), the element dumps and the surrounding prose.
# Photos are skipped as a class (inventory in 4.7). Graphics WITHOUT extractable text can only get
# number-free descriptions (ADR-020), so a graphic whose value lies in its numbers is skipped.

GATE_LEVELS = {"full", "caption_only", "skip"}
PHOTO_REASON = "Photograph; carries no retrievable information."

FIGURE_VALUE_DECISIONS = {
    "fig_p11": {"decision": "skip", "reason": (
        "Value creation model, raster (no extractable text). Everything it shows is reported elsewhere in text or "
        "tables: headcount and share of women (3.2.1, tab_p12, key figures), equity and debt (balance sheet tab_p82a), "
        "gross investments (3.2.2, fig_p13), the KPI results of the ESG themes (result tables), core values and "
        "focal points (3.1), stakeholder groups (3.2.4) and the SDGs (3.2.4 prose).")},
    "fig_p13": {"decision": "full", "reason": (
        "Five-year series of gross investments (2021–2025) and the category breakdown are not in the prose, which "
        "gives only the 2025 total; totals are printed labels (4.9).")},
    "fig_p15": {"decision": "skip", "reason": (
        "Port profile map with key statistics drawn as vector outlines (no extractable text). Its value is in its "
        "numbers, which ADR-020 does not allow in a description; the maximum depth is stated in the prose (Water).")},
    "fig_p19": {"decision": "skip", "reason": (
        "SDG icons with names drawn as outlines; the adjacent prose names the same SDGs (3, 7, 8, 9, 13) and explains "
        "how the Port Authority contributes to each.")},
    "fig_p23": {"decision": "full", "reason": (
        "Only source for who the partners in the value chain are (suppliers' partners, suppliers, the Port "
        "Authority's own activities, customers, customers' partners) and how influence varies along the chain.")},
    "fig_p26": {"decision": "full", "reason": (
        "The materiality matrix is the outcome of the double materiality analysis; the prose explains the axes but "
        "does not list which theme falls in which quadrant.")},
    "fig_p33a": {"decision": "full", "reason": (
        "Nine-year emission series of the port and industrial complex (printed totals 2016–2024, 4.9) and its sector "
        "breakdown; the prose refers to the chart without giving the series.")},
    "fig_p33b": {"decision": "full", "reason": (
        "Outlook 2024 -> 2030 with the printed effect of each reduction measure and the 9.6 Mton target (4.9); the "
        "prose gives only the target and says reaching it is increasingly unlikely.")},
    "fig_p45": {"decision": "skip", "reason": (
        "Raster map of the water bodies assessed under the Water Framework Directive: location information only; "
        "the relevant water bodies (Nieuwe Waterweg, Nieuwe Maas) are named in the prose.")},
    "fig_p47": {"decision": "skip", "reason": (
        "Raster map of the Natura 2000 areas around the port with the 25 km zone; the prose lists every "
        "nitrogen-sensitive Natura 2000 site in the zone and states the 25 km rule.")},
    "fig_p49a": {"decision": "full", "reason": (
        "The Nature Vision's three themes with their planned actions and the implementation programme; the prose "
        "names the three pillars but not the actions.")},
    "fig_p49b": {"decision": "skip", "reason": (
        "Raster map of the Nature Vision landscapes and zones; the text box next to it (p.49) describes the seven "
        "landscapes and two zones.")},
    "fig_p58": {"decision": "full", "reason": (
        "Explains the Port Authority's core tasks and how its influence decreases along upstream and downstream "
        "cargo chains; the prose only introduces the figure. Its printed caption is kept.")},
    "fig_p69": {"decision": "full", "reason": (
        "Organisational chart: which departments report to the CEO, CFO and COO; not listed anywhere in the text.")},
    "fig_p71": {"decision": "full", "reason": (
        "How responsibility for the climate goals is divided between the CFO, CEO and COO departments; the prose only "
        "introduces the figure.")},
}

figure_gate_df = (
    pd.DataFrame.from_dict(FIGURE_VALUE_DECISIONS, orient="index").rename_axis("figure_id").reset_index()
    .merge(figure_regions_df[["ref", "page_number", "graphic_kind", "n_text_lines"]].rename(columns={"ref": "figure_id"}),
           on="figure_id", how="left")
)
figure_gate_df["flag"] = None
photo_gate_df = images_df[images_df["kind"] == "photo"].assign(decision="skip", reason=PHOTO_REASON)

# ---- validation ----
assert set(FIGURE_VALUE_DECISIONS) == set(GRAPHICS), "Every graphic needs exactly one gate decision."
assert figure_gate_df["decision"].isin(GATE_LEVELS).all()
assert figure_gate_df["reason"].str.len().gt(40).all(), "Every decision needs a real reason."
assert set(figure_regions_df["ref"]) == set(GRAPHICS), "Every graphic (including 'skip') keeps its region."

print("✅ Value gate recorded:", figure_gate_df["decision"].value_counts().to_dict(),
      f"| photos skipped: {len(photo_gate_df)} | decorative icons: {int((images_df['kind'] == 'decorative_icon').sum())}")
with pd.option_context("display.max_colwidth", 120):
    display(figure_gate_df[["figure_id", "page_number", "graphic_kind", "decision", "reason"]])

# %% cell 42
# =========================================================
# 4.11 Figure units (curated descriptions, reviewed against the renders on 2026-09-25)
# =========================================================
# Numbers in a description must appear in the graphic's OWN extracted text (4.7 elements; decimal commas
# normalised). Graphics without extractable text therefore have number-free descriptions.

FIGURE_TITLES = {
    "fig_p13": "Gross investments (in mln euro), 2021–2025",
    "fig_p23": "Partners in our value chain",
    "fig_p26": "Outcome of the double materiality analysis (materiality matrix)",
    "fig_p33a": "Emissions in the port and industry complex (in Mton CO2-equivalents), 2016–2024",
    "fig_p33b": "Outlook emissions in the port and industrial complex (in Mton CO2), 2024–2030",
    "fig_p49a": "Nature Vision: themes, planned actions and implementation programme",
    "fig_p58": "Linked to cargo flows in value chain",
    "fig_p69": "Organisational chart of the Port of Rotterdam Authority",
    "fig_p71": "Division of responsibilities for the climate goals within the Executive Board",
}

FIGURE_DESCRIPTIONS = {
    "fig_p13": (
        "Stacked bar chart of the Port of Rotterdam Authority's gross investments in million euro per year, broken "
        "down into assets, public infrastructure, customer-specific infrastructure, participating interests and "
        "technical advice. Total gross investments: 2021: 226.3; 2022: 257.0; 2023: 295.4; 2024: 320.6; "
        "2025: 291.4. Investments rose every year from 2021 to a peak in 2024 and were lower in 2025."),
    "fig_p23": (
        "Infographic of the value chain of the Port of Rotterdam Authority, from upstream (suppliers) to downstream "
        "(customers). Partners of suppliers: fuels and raw materials; seconded staff. Suppliers: consultancy, research "
        "and engineering services; technological and facility services; product suppliers; construction, maintenance "
        "and repair services. The Port of Rotterdam Authority itself: exploitation of port areas; the promotion of the "
        "safe and smooth handling of shipping; consultancy services; investments. Customers: logistics, industry, "
        "energy, vessels. Partners of customers: road haulage companies, freight forwarders, nautical service "
        "providers (boatmen, pilots, tugs), logistical service providers. A bar labelled 'our influence' shows that "
        "the Port Authority's influence is greatest at its own position in the chain and decreases towards both ends."),
    "fig_p26": (
        "Double materiality matrix, the final result of the double materiality analysis validated by the management "
        "team. The vertical axis is the impact of the Port of Rotterdam Authority on people and the environment, the "
        "horizontal axis the financial impact on the Port Authority. Impact materiality: water pollution, occupational "
        "safety, chain responsibility, nautical safety, subversive crime. Double materiality (material for both impact "
        "and financial impact): climate mitigation, air pollution, soil contamination, nature and biodiversity, "
        "digital and physical resilience. Financial materiality: climate adaptation. Non-material: circularity, "
        "balanced and inclusive labour market, noise and odour nuisance, honest company operations, communities in "
        "the chain, diversity and inclusion."),
    "fig_p33a": (
        "Stacked bar chart of greenhouse gas emissions in the port and industrial complex in megatonnes of "
        "CO2-equivalents, broken down into oil refineries, chemical industry, coal-fired power stations, natural gas "
        "power plants, other sectors and other greenhouse gas emissions, with reference lines for the emissions in "
        "1990 and the target in 2030 (-55% vs. 1990). Total emissions: 2016: 31.3; 2017: 29.1; 2018: 27.0; "
        "2019: 26.0; 2020: 23.1; 2021: 24.2; 2022: 23.2; 2023: 20.8; 2024: 19.1. Emissions fell in every year except "
        "2021, when they rose again after 2020."),
    "fig_p33b": (
        "Waterfall chart of the expected emissions of the port and industrial complex from 19.1 Mton in 2024 to "
        "11.1 Mton in 2030, with the expected effect of each measure: CO2 capture -3.5; coal power plant ban -3.3; "
        "closing industry -0.3; biofuels -0.2; efficiency -0.9; electrification -0.2; green hydrogen -0.2; other +0.5. "
        "The 2030 target of 9.6 Mton is drawn as a line below the 2030 forecast, so the forecast does not reach "
        "the target."),
    "fig_p49a": (
        "Infographic of the Nature Vision ('Together with stakeholders, we are strengthening nature and biodiversity "
        "in and around the port'): three themes, what the Port Authority plans to do for each, and an implementation "
        "programme describing how it will be done. Room for nature: nature in the port is preserved and protected as "
        "much as possible; opportunities for nature and biodiversity are actively sought and exploited; management "
        "and development are carried out in a nature-inclusive manner; nature in the port is connected to (nature in) "
        "the surrounding area. Reducing pressure factors and improving basic conditions for nature: pressure factors "
        "such as litter and disturbance from recreation, light and noise are being addressed to improve nature; a "
        "well-functioning soil system and good water quality are promoted. Nature and biodiversity are becoming an "
        "integral part of the organisation and its processes: a nature-inclusive way of working becomes part of the "
        "culture of the Port of Rotterdam Authority, suppliers and customers; knowledge is further developed, "
        "effectively deployed and transferred; cooperation with the surrounding area, based on mutual interests; "
        "active communication."),
    "fig_p58": (
        "Infographic of the cargo-flow value chains the Port of Rotterdam Authority is linked to. Core tasks: the "
        "promotion of the safe and smooth handling of all shipping, and the development, management and operation of "
        "the port and industrial area in Rotterdam. Upstream of the Port Authority are its suppliers and the partners "
        "of suppliers. In the port industrial complex (shipping and landlease customers) cargo passes through "
        "transport, storage and transhipment, and production and processing. Upstream of the customers are "
        "production, transport, raw material and extraction; downstream are transport, distribution, consumer and "
        "end of life. Our influence: the Port Authority is linked to the upstream and downstream value chains of its "
        "customers and has influence on multiple levels; its influence is strongest with its contractual relationships "
        "(suppliers and customers) and weaker with their relationships, and becomes more indirect for the activities "
        "of companies it does not directly do business with."),
    "fig_p69": (
        "Organisational chart. The Supervisory Board and the Shareholders are shown above the Executive Board, which "
        "consists of the President and Chief Executive Officer (Boudewijn Siemons, CEO), the Chief Financial Officer "
        "(Vivienne de Leeuw, CFO) and the Chief Operating Officer (Berte Simons, COO). Departments under the CEO: "
        "Strategie & Portfolio, Commerce, Digital Port Performance, Corporate Legal, Human Resources, Communications & "
        "External Affairs, Internal Audit. Under the CFO: Finance, Procurement, Information & Digital Technology, "
        "Innovation, Service Center Facility. Under the COO: Port Development, Digital Port Lifecycle, Asset "
        "Management, Safety, Environmental Management. The Harbour Master Division is linked to the COO's line and to "
        "the Dutch Government and the Municipality of Rotterdam."),
    "fig_p71": (
        "Figure showing how responsibility for achieving the climate goals is divided within the Executive Board "
        "(shown below the Supervisory Board and the Shareholders). Chief Financial Officer: the approach to achieving "
        "the Port Authority's own emission reduction targets is partly assigned to the Facilities Department, which "
        "falls under the CFO; the departments of Innovation, Finance, and Information & Digital Technology, also under "
        "the CFO, provide essential input for various projects within the energy transition. Chief Executive Officer: "
        "the approach to achieving the emission reduction targets in the port is largely assigned to departments under "
        "the CEO; these commercial departments are involved in the initial and development phases of energy "
        "transition projects and actively seek collaboration across the value chain. Chief Operations Officer (the "
        "(State) Harbour Master is shown under the COO): the implementation of infrastructure and transition projects "
        "falls under the COO, and achieving the Port Authority's emission reduction targets is also largely assigned "
        "to the Port Development and Asset Management departments under the COO."),
}

NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def numbers_in(text: str) -> set[str]:
    out = set()
    for n in NUMBER_RE.findall(text):
        n = n.rstrip(",.")
        n = re.sub(r"^(\d+),(\d)$", r"\1.\2", n)          # decimal comma
        out.add(n)
    return out


figure_unit_records = []
for g in figure_gate_df.itertuples():
    if g.decision == "skip":
        continue
    els = figure_elements_df[figure_elements_df["figure_id"] == g.figure_id]
    caption = " ".join(els.loc[els["size"] == 7.5, "text"]) if g.figure_id == "fig_p58" else ""
    parts = [f"Figure: {FIGURE_TITLES[g.figure_id]}", FIGURE_DESCRIPTIONS[g.figure_id]] + ([caption] if caption else [])
    reg = figure_regions_df.set_index("ref").loc[g.figure_id]
    figure_unit_records.append({
        "unit_id": g.figure_id, "unit_type": "figure", "page_start": int(g.page_number), "page_end": int(g.page_number),
        "title": f"Figure: {FIGURE_TITLES[g.figure_id]}", "content": "\n".join(parts), "table_id": None,
        "figure_id": g.figure_id, "row_label": None, "gate_decision": g.decision,
        "description_provenance": "curated_from_render", "flag": None,
        "anchor_y0": float(reg["y0"]), "anchor_column": int((reg["x0"] + reg["x1"]) / 2 >= COLUMN_SPLIT_X),
    })
figure_units_df = pd.DataFrame(figure_unit_records)

# ---- validation (ADR-020) ----
full_figs = set(figure_gate_df.loc[figure_gate_df["decision"] == "full", "figure_id"])
assert set(FIGURE_DESCRIPTIONS) == full_figs == set(FIGURE_TITLES), "Descriptions/titles exactly for the 'full' figures."
for fid in full_figs:
    own_text = " ".join(figure_elements_df.loc[figure_elements_df["figure_id"] == fid, "text"])
    unsupported = numbers_in(FIGURE_TITLES[fid] + " " + FIGURE_DESCRIPTIONS[fid]) - numbers_in(own_text)
    assert not unsupported, f"{fid}: numbers not printed in the graphic's own text: {unsupported}"
assert not figure_units_df["content"].map(lambda s: any(unicodedata.category(c).startswith("C") and c != "\n" for c in s)).any()

print(f"✅ Figure units built: {len(figure_units_df)} (all 'full'; skipped: "
      f"{sorted(set(GRAPHICS) - full_figs)} + {len(photo_gate_df)} photos)")
for r in figure_units_df.itertuples():
    print("\n" + "=" * 100 + f"\n{r.unit_id} ({len(r.content)} chars)\n{r.content}")

# %% cell 43
# =========================================================
# 4.12 Phase 4 QA — structured units + structured regions
# =========================================================

UNIT_COLS = ["unit_id", "unit_type", "page_start", "page_end", "title", "content", "table_id", "figure_id",
             "row_label", "anchor_y0", "anchor_column"]
structured_units_df = pd.concat([table_units_df[UNIT_COLS + ["row_text", "table_header_text"]], iro_units_df[UNIT_COLS],
                                 box_units_df[UNIT_COLS], milestone_units_df[UNIT_COLS],
                                 figure_units_df[UNIT_COLS + ["gate_decision", "description_provenance", "flag"]]],
                                ignore_index=True)
REGION_COLS = ["region_id", "kind", "ref", "page_number", "x0", "y0", "x1", "y1"]
structured_regions_df = pd.concat([table_regions_df, iro_regions_df, box_regions_df, milestone_regions_df,
                                   figure_regions_df[REGION_COLS]], ignore_index=True)[REGION_COLS]
page_w, page_h = float(pages_df["page_width"].iloc[0]), float(pages_df["page_height"].iloc[0])
structured_regions_df[["x0", "y0"]] = structured_regions_df[["x0", "y0"]].clip(lower=0)
structured_regions_df["x1"] = structured_regions_df["x1"].clip(upper=page_w)
structured_regions_df["y1"] = structured_regions_df["y1"].clip(upper=page_h)

# ---- A) units ----
assert structured_units_df["unit_id"].is_unique
assert structured_units_df["content"].str.strip().ne("").all()
assert structured_units_df["unit_type"].value_counts().to_dict() == \
    {"table_row": 144, "iro_box": 11, "figure": 9, "milestone": 8, "box": 4}, structured_units_df["unit_type"].value_counts().to_dict()

# ---- B) regions: one per element, inside retrieval pages ----
assert structured_regions_df["region_id"].is_unique
assert structured_regions_df["page_number"].isin(RETRIEVAL_PAGES).all()

# ---- C) no 8pt prose inside any region (except the milestone cards, which ARE 8pt text) ----
prose = lines_df[(lines_df["zone"] == "body") & (lines_df["size"] == BODY_FONT_SIZE) & ~lines_df["is_subscript"]]
leaks = {}
for r in structured_regions_df[structured_regions_df["kind"] != "milestone"].itertuples():
    pl = prose[(prose["page_number"] == r.page_number) & (prose["x1"] > r.x0 + 1) & (prose["x0"] < r.x1 - 1)
               & (prose["y1"] > r.y0 + 1) & (prose["y0"] < r.y1 - 1)]
    if len(pl):
        leaks[r.region_id] = pl["text"].str[:40].tolist()
assert not leaks, f"Prose lines inside structured regions: {leaks}"

# ---- D) regions on the same page must not overlap ----
for p, grp in structured_regions_df.groupby("page_number"):
    rects = list(grp.itertuples())
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            a, b = rects[i], rects[j]
            overlap = a.x0 < b.x1 - 1 and b.x0 < a.x1 - 1 and a.y0 < b.y1 - 1 and b.y0 < a.y1 - 1
            assert not overlap, f"Overlap on p{p}: {a.region_id} / {b.region_id}"

# ---- E) every 7.25pt line of a retrieval page belongs to a table, an IRO box or a text box ----
tbl_font = lines_df[lines_df["page_number"].isin(RETRIEVAL_PAGES) & (lines_df["zone"] == "body")
                    & (lines_df["size"] == TABLE_FONT_SIZE) & ~lines_df["is_subscript"]]
orphans = tbl_font[~in_regions(tbl_font, structured_regions_df[structured_regions_df["kind"].isin(["table", "iro_box", "box"])])]
assert orphans.empty, f"7.25pt lines outside tables/boxes: {orphans[['page_number', 'text']].values.tolist()[:5]}"

# ---- F) gate consistency ----
assert figure_units_df["flag"].isna().all(), "No figure unit may remain flagged."
assert set(figure_units_df["unit_id"]) == set(figure_gate_df.loc[figure_gate_df["decision"] != "skip", "figure_id"])

print("✅ Phase 4 validation passed.")
print("Structured units :", len(structured_units_df), structured_units_df["unit_type"].value_counts().to_dict())
print("Regions          :", len(structured_regions_df), structured_regions_df["kind"].value_counts().to_dict())
print("Figure gate      :", figure_gate_df["decision"].value_counts().to_dict(), "| photos skipped:", len(photo_gate_df))
display(structured_units_df.assign(chars=structured_units_df["content"].str.len())
        .groupby("unit_type")["chars"].describe()[["count", "min", "mean", "max"]])

# %% [markdown] cell 44
# # Phase 5 — Notes / Footnotes
#
# The reference pipeline links endnote markers to a notes registry. **This report has no footnotes or endnotes**:
# there is no Notes page, and the only small digit spans next to prose are the chemical subscripts
# (CO2, NO2, PM10, PM2.5) already re-inserted in Phase 3.
#
# This phase proves that claim instead of assuming it:
#
# - **5.1** scan every prose line (8pt body text and the 7.25pt boxes) for superscript-style spans
#   (digits only, smaller than the line's text or flagged superscript) and for "Notes" / "Sources" headings;
# - **5.2** validation: zero note markers, zero note registry entries, every small digit line accounted for
#   (subscript or chart label).

# %% cell 45
# =========================================================
# 5.1 Note-marker scan (span level)
# =========================================================

MARKER_RE = re.compile(r"\d{1,2}(?:\s*[,–-]\s*\d{1,2})*")
NOTE_HEADING_RE = re.compile(r"^(notes?|endnotes|footnotes|sources?)$", re.IGNORECASE)

marker_records = []
for p in RETRIEVAL_PAGES:
    for bi, block in enumerate(page_dict(p)["blocks"]):
        for li, line in enumerate(block["lines"]):
            spans = [s for s in line["spans"] if s["text"].strip()]
            if len(spans) < 2:
                continue
            main = max(spans, key=lambda s: len(s["text"].strip()))
            if main["size"] < TABLE_FONT_SIZE - 0.2:
                continue
            for s in spans:
                t = s["text"].strip()
                if MARKER_RE.fullmatch(t) and (s["size"] < main["size"] - 0.5 or s["flags"] & 1):
                    marker_records.append({"page_number": p, "block_no": bi, "line_no": li, "marker": t,
                                           "size": round(s["size"], 1), "context": main["text"][:60]})
note_markers_df = pd.DataFrame(marker_records, columns=["page_number", "block_no", "line_no", "marker", "size", "context"])

note_headings = lines_df[lines_df["page_number"].isin(RETRIEVAL_PAGES)
                         & lines_df["text"].str.strip().str.match(NOTE_HEADING_RE)]

# small digit-only lines (separate PyMuPDF lines) and how they are accounted for
small_digits = lines_df[lines_df["page_number"].isin(RETRIEVAL_PAGES) & (lines_df["zone"] == "body")
                        & (lines_df["size"] < BODY_FONT_SIZE - 0.5) & (lines_df["size"] != TABLE_FONT_SIZE)
                        & lines_df["text"].str.fullmatch(r"[\d.,\-–]+")]
element_keys = set(zip(figure_elements_df["page_number"], figure_elements_df["block_no"], figure_elements_df["line_no"]))
small_digits = small_digits.assign(
    accounted_as=np.where(small_digits["is_subscript"], "chemical_subscript",
                          np.where([k in element_keys for k in zip(small_digits["page_number"], small_digits["block_no"],
                                                                   small_digits["line_no"])], "chart_label", "UNACCOUNTED")))

print(f"Superscript-style marker spans inside prose lines: {len(note_markers_df)}")
print(f"'Notes' / 'Sources' headings on retrieval pages    : {len(note_headings)}")
print("Small digit-only lines by explanation:", small_digits["accounted_as"].value_counts().to_dict())

# %% cell 46
# =========================================================
# 5.2 Phase 5 validation
# =========================================================

note_registry_df = pd.DataFrame(columns=["note_no", "text", "policy"])     # empty by evidence (5.1)

assert note_markers_df.empty, f"Unexpected note markers: {note_markers_df.values.tolist()}"
assert note_headings.empty, f"Unexpected notes headings: {note_headings['text'].tolist()}"
assert (small_digits["accounted_as"] != "UNACCOUNTED").all(), \
    small_digits.loc[small_digits["accounted_as"] == "UNACCOUNTED", ["page_number", "text"]].values.tolist()
assert int((small_digits["accounted_as"] == "chemical_subscript").sum()) == int(lines_df["is_subscript"].sum()) == 28

print("✅ Phase 5 validation passed: no footnotes/endnotes in this report.")
print(f"Chemical subscripts: 28 (merged in Phase 3) | chart labels: "
      f"{int((small_digits['accounted_as'] == 'chart_label').sum())} (Phase 4 figure elements)")

# %% [markdown] cell 47
# # Phase 6 — Body Extraction + Cleaning
#
# Goal: extract only the body prose of the retrieval pages, cleaned and with physical position,
# excluding everything handled in Phases 3–5.
#
# Principle: **exclude what is known, keep everything else.** A line is body unless it is in the
# navigation bar or page-number zone, a heading of the `section_map`, a chemical subscript (already merged
# into its host line), or inside a structured region (table, IRO box, text box, milestone card, graphic).
# Unexpected fonts that survive are surfaced by the audit (6.5), not silently dropped.
#
# - **6.1** tag every line of the retrieval pages with its reason
# - **6.2** cleaning (shared `clean_line` from 4.1) and **bullet detection**: bullets in this PDF are not text
#   glyphs but small navy squares drawn as vectors, so a bullet item is recognised from the drawing on its baseline
# - **6.3** body-line extraction (subscript-merged text) with line-break type
# - **6.4** duplication check against structured units
# - **6.5** body audit + validation

# %% cell 48
# =========================================================
# 6.1 Structural boundaries: tag every line on retrieval pages
# =========================================================
# Priority: header/footer > subscript (merged) > structured region > heading > body

rl = lines_df[lines_df["page_number"].isin(RETRIEVAL_PAGES)].copy()

heading_line_keys = set()
for h in heading_cand_df.itertuples():          # every physical line of every (possibly wrapped) heading
    # same block AND same column: PyMuPDF can put a right-column body line in the heading's block when it
    # sits on the same baseline (p.71, found by the Phase 19 coverage audit)
    hl = lines_df[(lines_df["page_number"] == h.page_number) & (lines_df["block_no"] == h.block_no)
                  & (lines_df["column"] == h.column)
                  & (lines_df["y0"] >= h.y0 - 0.5) & (lines_df["y1"] <= h.y1 + 0.5) & ~lines_df["is_subscript"]]
    assert letters_key(" ".join(hl.sort_values("y0")["text"])) == letters_key(h.text), \
        f"p{h.page_number}: heading lines {hl['text'].tolist()} differ from the heading {h.text!r}"
    heading_line_keys |= set(zip(hl["page_number"], hl["block_no"], hl["line_no"]))
rl_keys = list(zip(rl["page_number"], rl["block_no"], rl["line_no"]))

rl["reason"] = np.select(
    [rl["zone"] == "header", rl["zone"] == "footer", rl["is_subscript"],
     in_regions(rl, structured_regions_df), pd.Series([k in heading_line_keys for k in rl_keys], index=rl.index)],
    ["header", "footer", "subscript", "structured_region", "heading"],
    default="body",
)

print("Lines by reason:", rl["reason"].value_counts().to_dict())
print("\nsection_map headings (typographic) vs lines tagged 'heading':",
      int((section_map["role"] != "implied_section").sum()), "headings /", int((rl["reason"] == "heading").sum()), "lines")
print("\nBody-line fonts (preview for 6.5):")
display(rl[rl["reason"] == "body"].groupby(["font", "size"]).agg(
    lines=("text", "size"), pages=("page_number", "nunique"), example=("text", "first")))

# %% cell 49
# =========================================================
# 6.2 Bullet detection (vector bullets) + line-break rules
# =========================================================
# A bullet = a small navy filled square (<= 4pt) whose centre lies on a text line's baseline band,
# just left of the line (gap < 9pt). Bullet items are hanging-indented: continuation lines start at
# the same x as the item text, without a bullet.

def outside_structured_region(p, r) -> bool:
    """Chart legends and the outlined text of the org chart also contain small navy squares."""
    rg = structured_regions_df[structured_regions_df["page_number"] == p]
    return not ((rg["x0"] <= r.x0) & (r.x1 <= rg["x1"]) & (rg["y0"] <= r.y0) & (r.y1 <= rg["y1"])).any()


bullet_records = []
for p in RETRIEVAL_PAGES:
    for d in page_drawings(p):
        r = d["rect"]
        if is_navy(d.get("fill")) and r.width <= 4 and r.height <= 4 and NAV_MAX_Y1 < r.y0 < FOOTER_MIN_Y0 \
                and outside_structured_region(p, r):
            bullet_records.append({"page_number": p, "bx0": r.x0, "bx1": r.x1, "by": (r.y0 + r.y1) / 2})
bullets_df = pd.DataFrame(bullet_records)


def line_break_type(text: str) -> str:
    """How this line joins the next one (applied in Phase 7)."""
    t = text.rstrip()
    if re.search(r"[A-Za-z]-$", t):
        return "hyphen"       # compound hyphen at line end: joined without a space unless suspended ("land- and")
    return "none"             # join with a single space


assert line_break_type("the world's largest deep-") == "hyphen"
assert line_break_type("low river levels.") == "none"
assert line_break_type("(PM2.5 and PM10) -") == "none"

print(f"Vector bullets found: {len(bullets_df)} on {bullets_df['page_number'].nunique()} pages")

# %% cell 50
# =========================================================
# 6.3 Body-line extraction
# =========================================================

body_records, dropped_empty = [], []
for r in rl[rl["reason"] == "body"].itertuples():
    text = clean_line(r.text_merged)
    if not text:
        dropped_empty.append((r.page_number, r.y0, r.text))
        continue
    bl = bullets_df[(bullets_df["page_number"] == r.page_number) & (bullets_df["by"] >= r.y0) & (bullets_df["by"] <= r.y1)
                    & (bullets_df["bx1"] <= r.x0) & (r.x0 - bullets_df["bx1"] < 9)]
    body_records.append({
        "line_uid": f"p{r.page_number}_b{r.block_no}_l{r.line_no}",
        "page_number": r.page_number, "block_no": r.block_no, "line_no": r.line_no,
        "column": r.column, "x0": r.x0, "y0": r.y0, "x1": r.x1, "y1": r.y1,
        "font": r.font, "size": r.size, "is_bold": r.is_bold, "all_bold": r.all_bold,
        "text": text, "raw_text": r.text, "has_subscript": text != clean_line(r.text),
        "line_break": line_break_type(text), "is_bullet_start": len(bl) > 0,
    })

body_lines_df = pd.DataFrame(body_records).sort_values(["page_number", "column", "y0", "x0"]).reset_index(drop=True)
excluded_lines_df = rl[rl["reason"] != "body"][["page_number", "block_no", "line_no", "y0", "x0", "size", "font",
                                               "reason", "text"]].reset_index(drop=True)

used_bullets = 0
for b in bullets_df.itertuples():
    hit = body_lines_df[(body_lines_df["page_number"] == b.page_number) & (body_lines_df["y0"] <= b.by)
                        & (body_lines_df["y1"] >= b.by) & (body_lines_df["x0"] >= b.bx1) & (body_lines_df["x0"] - b.bx1 < 9)]
    used_bullets += len(hit) > 0

print(f"Body lines        : {len(body_lines_df)}  (dropped empty after cleaning: {len(dropped_empty)})")
print(f"Excluded lines    : {len(excluded_lines_df)}  {excluded_lines_df['reason'].value_counts().to_dict()}")
print(f"Line-break types  : {body_lines_df['line_break'].value_counts().to_dict()}")
print(f"Bullet starts     : {int(body_lines_df['is_bullet_start'].sum())} | vector bullets on a body line: "
      f"{used_bullets} of {len(bullets_df)}")
print(f"Lines with a merged subscript: {int(body_lines_df['has_subscript'].sum())}")
with pd.option_context("display.max_colwidth", 90):
    display(body_lines_df[body_lines_df["is_bullet_start"]].head(6)[["line_uid", "x0", "text"]])

# %% cell 51
# =========================================================
# 6.4 Duplication check: body lines vs structured units
# =========================================================

def norm_cmp(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", text.lower()).split())


table_font_leaks = body_lines_df[(body_lines_df["size"] - TABLE_FONT_SIZE).abs() < 0.1]
structured_norm = {r.unit_id: norm_cmp(r.content) for r in structured_units_df.itertuples()}
overlaps = []
for r in body_lines_df.itertuples():
    t = norm_cmp(r.text)
    if len(t) < 30:
        continue
    hits = [uid for uid, content in structured_norm.items() if t in content]
    if hits:
        overlaps.append({"line_uid": r.line_uid, "units": hits, "text": r.text})
overlaps_df = pd.DataFrame(overlaps, columns=["line_uid", "units", "text"])

# physical exclusivity: no body line is a line used by a structured unit
structured_line_keys = set(zip(rl.loc[rl["reason"] == "structured_region", "page_number"],
                               rl.loc[rl["reason"] == "structured_region", "block_no"],
                               rl.loc[rl["reason"] == "structured_region", "line_no"]))
body_keys = set(zip(body_lines_df["page_number"], body_lines_df["block_no"], body_lines_df["line_no"]))

print(f"Table-font (7.25pt) lines left in body : {len(table_font_leaks)}")
print(f"Body lines that are also structured lines: {len(body_keys & structured_line_keys)}")
print(f"Body lines whose text also occurs in a structured unit (textual repeats): {len(overlaps_df)}")
with pd.option_context("display.max_colwidth", 90):
    display(overlaps_df)
assert table_font_leaks.empty, "Structured text leaked into body."
assert not (body_keys & structured_line_keys), "A physical line is both body and structured."
# reviewed 2026-09-25: the repeats are legitimate — the purpose quote also appears in a milestone card,
# a table title and a figure description reuse the words of the introducing sentence / pillar list.
REVIEWED_TEXT_REPEATS = {"p9_b2_l1": ["milestone_p6_1"], "p48_b10_l1": ["fig_p49a"]}
repeats = {r.line_uid: [u for u in r.units if not u.startswith("tab_p25")] for r in overlaps_df.itertuples()}
repeats = {k: v for k, v in repeats.items() if v}
assert repeats == REVIEWED_TEXT_REPEATS, f"Textual repeats changed: {repeats}"
assert set(overlaps_df["line_uid"]) - set(REVIEWED_TEXT_REPEATS) <= {"p25_b9_l3"}, "Unexpected textual repeat."
print("✅ No structured-element leakage into body text.")

# %% cell 52
# =========================================================
# 6.5 Body audit + Phase 6 validation
# =========================================================

ALLOWED_BODY = {("NLRTM-Regular", BODY_FONT_SIZE), ("NLRTM-Bold", BODY_FONT_SIZE), ("NLRTM-RegularItalic", BODY_FONT_SIZE)}

# ---- A) accounting ----
n_body_tagged = int((rl["reason"] == "body").sum())
assert len(body_lines_df) + len(dropped_empty) == n_body_tagged, "Body lines unaccounted for."
assert body_lines_df["line_uid"].is_unique

# ---- B) fonts ----
unexpected = body_lines_df[[(f, s) not in ALLOWED_BODY for f, s in zip(body_lines_df["font"], body_lines_df["size"])]]
assert unexpected.empty, f"Unexpected body fonts: {unexpected[['page_number', 'font', 'size', 'text']].values.tolist()[:10]}"

# ---- C) hygiene ----
assert not body_lines_df["text"].map(lambda t: any(unicodedata.category(ch).startswith("C") for ch in t)).any()
assert not body_lines_df["text"].str.upper().isin([l.upper() for l in NAV_LABELS]).any(), "Nav label leaked."
assert not body_lines_df["text"].str.contains(HOST_TOKEN_RE.pattern + r"\s+e\b", regex=True).any(), "Unmerged 'CO e'."

# ---- D) pages: every retrieval page has body text, except pages that hold only graphics / tables ----
per_page = body_lines_df.groupby("page_number").agg(lines=("text", "size"), chars=("text", lambda s: s.str.len().sum()))
no_body = sorted(set(RETRIEVAL_PAGES) - set(per_page.index))
REVIEWED_NO_BODY_PAGES = [6, 7, 11, 23, 58, 82]   # milestone cards, value creation model, value chain, cargo-flow figure, financial statements
assert no_body == REVIEWED_NO_BODY_PAGES, f"Pages without body text: {no_body}"

# ---- E) every heading on a retrieval page is tagged; every bullet drawing sits on a body line ----
for h in section_map[(section_map["role"] != "implied_section") & section_map["page_number"].isin(RETRIEVAL_PAGES)].itertuples():
    tagged = rl[(rl["page_number"] == h.page_number) & ((rl["y0"] - h.y0).abs() < 1.0) & (rl["reason"] == "heading")]
    assert len(tagged), f"Heading not excluded from body: {h.heading_id} {h.heading_text}"
assert used_bullets == len(bullets_df), "A vector bullet has no body line on its baseline."

# ---- F) reviewed snapshot ----
REVIEWED_BODY_LINE_COUNT = 2019     # 2018 + the p.71 line recovered from the heading block (see 6.1)
if REVIEWED_BODY_LINE_COUNT is not None:
    assert len(body_lines_df) == REVIEWED_BODY_LINE_COUNT

print("✅ Phase 6 validation passed.")
print(f"Body lines : {len(body_lines_df)} on {len(per_page)} pages | chars: {per_page['chars'].sum()}")
print(f"Excluded   : {excluded_lines_df['reason'].value_counts().to_dict()}")
print(f"Bullets    : {int(body_lines_df['is_bullet_start'].sum())} | hyphen breaks: "
      f"{int((body_lines_df['line_break'] == 'hyphen').sum())}")

# %% [markdown] cell 53
# # Phase 7 — Paragraph Reconstruction
#
# Goal: rebuild complete paragraphs from the Phase 6 body lines, in true reading order, including
# paragraphs that continue across a column or a page.
#
# **Reading order is band-aware**: a graphic that spans both columns (p.11, 23, 69, 71) splits its page into
# horizontal bands, and the columns are read band by band: `(page, band, column, y)`. Without this, the p.71
# sentence that runs from the left column into the right column *above* the full-width figure would be cut.
#
# The rules come from measurements (7.1), not assumptions: **11.5pt leading**, paragraphs separated by an
# empty line (**≈ 23pt**), headings by ≥ 34pt, **no first-line indent**. Bullet items are recognised by their
# vector bullet (Phase 6) and use a hanging indent. A paragraph continues across a column or page break
# whenever the previous line did not end a sentence; a heading or a structured element (table, box, graphic)
# between two lines always ends the paragraph.

# %% cell 54
# =========================================================
# 7.1 Layout profile: leading, paragraph gap, indents
# =========================================================

FULL_WIDTH = structured_regions_df[(structured_regions_df["x0"] < COLUMN_SPLIT_X - 40)
                                  & (structured_regions_df["x1"] > COLUMN_SPLIT_X + 40)]


def band_of(page: int, y0: float) -> int:
    fw = FULL_WIDTH[FULL_WIDTH["page_number"] == page]
    return int((fw["y1"] <= y0 + 1).sum())


def reading_key(page: int, column: int, y0: float) -> tuple:
    return (int(page), band_of(page, y0), int(column), float(y0))


print("Full-width regions (band separators):", FULL_WIDTH[["page_number", "ref", "y0", "y1"]].values.tolist())

rb = body_lines_df.copy()
rb["band"] = [band_of(p, y) for p, y in zip(rb["page_number"], rb["y0"])]
rb["rkey"] = [reading_key(p, c, y) for p, c, y in zip(rb["page_number"], rb["column"], rb["y0"])]
rb = rb.sort_values(["rkey", "x0"]).reset_index(drop=True)
rb["col_left"] = rb.groupby(["page_number", "column"])["x0"].transform("min")
rb["dx"] = (rb["x0"] - rb["col_left"]).round(1)
rb["dy"] = rb.groupby(["page_number", "band", "column"])["y0"].diff().round(1)

section_map["rkey"] = [reading_key(p, c, y) for p, c, y in zip(section_map["page_number"], section_map["column"], section_map["y0"])]


LEADING = float(rb["dy"].mode().iloc[0])
PARA_GAP = float(rb.loc[rb["dy"].between(1.5 * LEADING, 2.5 * LEADING), "dy"].median())

print(f"Leading (mode of dy)          : {LEADING} pt")
print(f"Paragraph gap (median 1.5–2.5x): {PARA_GAP} pt")
print("dy distribution (top):", rb["dy"].value_counts().head(8).to_dict())
print("dx distribution (top):", rb["dx"].value_counts().head(8).to_dict())
print("dx of bullet lines    :", rb.loc[rb["is_bullet_start"], "dx"].value_counts().to_dict())

# %% cell 55
# =========================================================
# 7.2 Paragraph boundary rules
# =========================================================
#   1. a section_map heading lies between the two lines (reading order)   -> new paragraph ("heading")
#   2. a structured region (table, box, card, graphic) lies between them   -> new paragraph ("structured")
#   3. the line starts a bullet item                                        -> new paragraph ("bullet")
#   4. the previous line ends with a hyphen, or does not end a sentence     -> CONTINUE (also across
#                                                                              columns and pages)
#   5. vertical gap > 1.6 x leading in the same column                       -> new paragraph ("gap")
#   6. new column or page after a finished sentence                          -> new paragraph ("column_start")
#   7. otherwise                                                             -> CONTINUE

SENTENCE_END_RE = re.compile(r"[.!?:;][”’\")\]]*$")

heading_keys = sorted(section_map["rkey"])
region_keys = sorted(
    (r.page_number, band_of(r.page_number, r.y0),
     2 if r.region_id in set(FULL_WIDTH["region_id"]) else int((r.x0 + r.x1) / 2 >= COLUMN_SPLIT_X), r.y0)
    for r in structured_regions_df.itertuples())


def between(keys, k0, k1) -> bool:
    return any(k0 < k < k1 for k in keys)


def boundary(prev, cur) -> str | None:
    if prev is None:
        return "document_start"
    k0, k1 = prev.rkey, cur.rkey
    if between(heading_keys, k0, k1):
        return "heading"
    if between(region_keys, k0, k1):
        return "structured"
    if cur.is_bullet_start:
        return "bullet"
    if prev.line_break == "hyphen" or not SENTENCE_END_RE.search(prev.text):
        return None
    same_col = (cur.page_number, cur.band, cur.column) == (prev.page_number, prev.band, prev.column)
    if same_col and cur.dy > 1.6 * LEADING:
        return "gap"
    if not same_col:
        return "column_start"
    return None


reasons, prev = [], None
for cur in rb.itertuples():
    reasons.append(boundary(prev, cur))
    prev = cur
rb["boundary"] = reasons
rb["para_no"] = rb["boundary"].notna().cumsum()

print("Paragraph starts by reason:", rb["boundary"].value_counts().to_dict())
print("Paragraphs:", int(rb["para_no"].max()))

# every column / page transition: continued or broken, and why
prev_rows = rb.shift(1)
transition = ((rb["page_number"] != prev_rows["page_number"]) | (rb["column"] != prev_rows["column"])
              | (rb["band"] != prev_rows["band"]))
trans_df = pd.DataFrame({
    "from": prev_rows.loc[transition, "line_uid"], "to": rb.loc[transition, "line_uid"],
    "decision": rb.loc[transition, "boundary"].fillna("CONTINUE"),
    "prev_end": prev_rows.loc[transition, "text"].str[-40:], "next_start": rb.loc[transition, "text"].str[:40],
}).iloc[1:]
print("\nColumn / page transitions that CONTINUE a paragraph:")
with pd.option_context("display.max_rows", None, "display.max_colwidth", 45):
    display(trans_df[trans_df["decision"] == "CONTINUE"])

# %% cell 56
# =========================================================
# 7.3 Reconstruct paragraphs
# =========================================================

def join_lines(lines: list) -> str:
    return join_wrapped([ln.text for ln in lines])


paragraph_records = []
for para_no, grp in rb.groupby("para_no", sort=True):
    lines = list(grp.itertuples())
    first = lines[0]
    paragraph_records.append({
        "paragraph_id": f"P{para_no:03d}",
        "text": join_lines(lines),
        "page_start": int(grp["page_number"].min()), "page_end": int(grp["page_number"].max()),
        "first_page": int(first.page_number), "first_column": int(first.column), "first_y0": float(first.y0),
        "first_rkey": first.rkey,
        "boundary_reason": first.boundary,
        "is_bullet": bool(first.is_bullet_start),
        "n_lines": len(lines),
        "line_uids": [l.line_uid for l in lines],
    })

paragraphs_df = pd.DataFrame(paragraph_records)
paragraphs_df["char_count"] = paragraphs_df["text"].str.len()

print(f"Paragraphs: {len(paragraphs_df)} | spanning >1 page: "
      f"{int((paragraphs_df['page_start'] != paragraphs_df['page_end']).sum())}")
print("Size (chars):", paragraphs_df["char_count"].describe()[["min", "50%", "max"]].to_dict())
with pd.option_context("display.max_rows", 40, "display.max_colwidth", 90):
    display(paragraphs_df[["paragraph_id", "page_start", "page_end", "boundary_reason", "char_count", "text"]]
            .assign(text=paragraphs_df["text"].str[:90]))

# %% cell 57
# =========================================================
# 7.4 Paragraph validation
# =========================================================

# ---- A) every body line used exactly once ----
used = [uid for uids in paragraphs_df["line_uids"] for uid in uids]
assert sorted(used) == sorted(body_lines_df["line_uid"]) and len(used) == len(set(used)), "Line coverage broken."

# ---- B) text preservation: joining only changes whitespace ----
def letters(t: str) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", t)


assert letters("".join(paragraphs_df["text"])) == letters("".join(rb["text"])), "Characters lost while joining."

# ---- C) no heading text survives as a standalone paragraph ----
assert not paragraphs_df["text"].str.lower().isin(set(section_map["heading_norm"])).any(), "A heading became a paragraph."

# ---- D) join artefacts ----
BAD_HYPHEN_RE = re.compile(r"[A-Za-z]- (?!and\b|or\b|to\b|nor\b)[a-z]")
bad = paragraphs_df["text"].map(lambda t: bool(BAD_HYPHEN_RE.search(t)))
assert not bad.any(), f"Broken hyphen joins: {paragraphs_df.loc[bad, ['paragraph_id', 'text']].values.tolist()}"

# ---- E) review flags: lowercase starts / no sentence end (each reviewed below) ----
starts_lower = paragraphs_df[paragraphs_df["text"].str.match(r"^[a-z]")]
no_end = paragraphs_df[~paragraphs_df["text"].map(lambda t: bool(SENTENCE_END_RE.search(t)))]
print(f"Paragraphs starting lowercase : {len(starts_lower)}")
print(f"Paragraphs without an ending  : {len(no_end)}")
with pd.option_context("display.max_colwidth", 130, "display.max_rows", None):
    if len(starts_lower):
        display(starts_lower[["paragraph_id", "page_start", "boundary_reason", "text"]])
    if len(no_end):
        display(no_end[["paragraph_id", "page_start", "boundary_reason", "text"]].assign(text=no_end["text"].str[-110:]))

# Reviewed 2026-09-25: all are list items (bullets continue an introducing sentence ending in ':'),
# the foreword signature, and the address lines of the credits page — no broken paragraph.
REVIEWED_LOWER_START = {"P245": "quality relative to reference,", "P246": "species diversity and absence,",
                        "P247": "connections between habitats.", "P250": "space for nature,",
                        "P251": "reducing pressure factors and ", "P252": "integrating nature into the or"}
REVIEWED_NO_END = {"P006": "enne de Leeuw and Berte Simons", "P101": "y, with more transition risks)",
                   "P231": "Solleveld & Kapittelduinen", "P232": "Westduinpark & Wapendal",
                   "P233": " Berkheide (only southern tip)", "P234": "Voornes Duin",
                   "P235": "Duinen van Goeree & Kwade Hoek", "P236": "errestrial parts are relevant)",
                   "P237": "Krammer-Volkerak", "P245": "quality relative to reference,",
                   "P246": "species diversity and absence,", "P250": "space for nature,",
                   "P251": "nd improving basic conditions,", "P278": " (expansion of safety support)",
                   "P279": "d the prevention of recurrence", "P280": "nts in the contract provisions",
                   "P423": "Port of Rotterdam Authority", "P425": " AP Rotterdam Port Number 1247",
                   "P426": "010 W: www.portofrotterdam.com"}
assert dict(zip(starts_lower["paragraph_id"], starts_lower["text"].str[:30])) == REVIEWED_LOWER_START
assert dict(zip(no_end["paragraph_id"], no_end["text"].str[-30:])) == REVIEWED_NO_END
lower_or_open = set(REVIEWED_LOWER_START) | set(REVIEWED_NO_END)
assert paragraphs_df.set_index("paragraph_id").loc[sorted(lower_or_open - {"P006", "P423", "P425", "P426"}), "is_bullet"].all(), \
    "Only bullet items may start in lowercase or end without punctuation (besides signature/address lines)."

# ---- F) reviewed snapshot ----
REVIEWED_PARAGRAPH_STARTS = {"heading": 205, "gap": 120, "bullet": 62, "column_start": 27, "structured": 11,
                             "document_start": 1}
assert paragraphs_df["boundary_reason"].value_counts().to_dict() == REVIEWED_PARAGRAPH_STARTS
assert len(paragraphs_df) == 426

print(f"\n✅ Phase 7 validation passed. Paragraphs: {len(paragraphs_df)} "
      f"{paragraphs_df['boundary_reason'].value_counts().to_dict()}")

# %% [markdown] cell 58
# # Phase 8 — Section / Subsection Assignment
#
# Every unit is assigned by **physical position**: the last heading that precedes it in the band-aware
# reading order `(page, band, column, y)` of Phase 7. Unlike the LPI reports, tables and graphics here are
# unnumbered and never referenced by number, and they sit where they belong (right under the heading or
# sentence that introduces them), so their own position is used; a full-width graphic is read after both
# columns of the band above it. `subsection` is the full heading path below the chapter, e.g.
# `4.2 Double Materiality Analysis > 4.2.1 Climate mitigation > Activities > Reducing greenhouse gas … > Fleet renewal`.

# %% cell 59
# =========================================================
# 8.1 Heading positions in reading order + locate()
# =========================================================

FULL_WIDTH_IDS = set(FULL_WIDTH["region_id"])
heading_seq = section_map.sort_values("rkey").reset_index(drop=True)
heading_rkeys = heading_seq["rkey"].tolist()


def locate(rkey: tuple) -> dict:
    """Chapter / subsection path of the last heading at or before this reading position."""
    k = rkey[:3] + (rkey[3] + 0.5,)
    idx = max((i for i, hk in enumerate(heading_rkeys) if hk <= k), default=None)
    if idx is None:
        return {"section": None, "subsection_path": [], "heading_id": None}
    h = heading_seq.iloc[idx]
    return {"section": h["l1"], "subsection_path": list(h["subsection_path"]), "heading_id": h["heading_id"]}


def region_rkey(region_id: str) -> tuple:
    r = structured_regions_df.set_index("region_id").loc[region_id]
    col = 2 if region_id in FULL_WIDTH_IDS else int((r["x0"] + r["x1"]) / 2 >= COLUMN_SPLIT_X)
    return (int(r["page_number"]), band_of(int(r["page_number"]), float(r["y0"])), col, float(r["y0"]))


print(f"Headings in reading order: {len(heading_seq)} | first: {heading_seq['heading_text'].iloc[0]!r}")

# %% cell 60
# =========================================================
# 8.2 Assign paragraph sections
# =========================================================
loc = paragraphs_df["first_rkey"].map(locate)
paragraphs_df["section"] = loc.map(lambda d: d["section"])
paragraphs_df["subsection_path"] = loc.map(lambda d: d["subsection_path"])
paragraphs_df["heading_id"] = loc.map(lambda d: d["heading_id"])

# %% cell 61
# =========================================================
# 8.3 Assign structured-unit sections (physical position of the element's region)
# =========================================================
REGION_OF_UNIT = {}
for u in structured_units_df.itertuples():
    ref = u.table_id if u.unit_type == "table_row" else u.unit_id
    REGION_OF_UNIT[u.unit_id] = f"region_{ref}"

structured_units_df["rkey"] = structured_units_df["unit_id"].map(lambda uid: region_rkey(REGION_OF_UNIT[uid]))
sloc = structured_units_df["rkey"].map(locate)
for key in ("section", "subsection_path", "heading_id"):
    structured_units_df[key] = sloc.map(lambda d, k=key: d[k])
structured_units_df["section_basis"] = "physical_position"

# %% cell 62
# =========================================================
# 8.4 Validate assignment
# =========================================================
assert paragraphs_df["section"].notna().all(), "Paragraph without a section."
assert structured_units_df["section"].notna().all(), "Structured unit without a section."

# a paragraph that starts right after a heading is assigned to THAT heading (same or previous page)
for r in paragraphs_df[paragraphs_df["boundary_reason"] == "heading"].itertuples():
    h = heading_seq[heading_seq["heading_id"] == r.heading_id].iloc[0]
    assert h["page_number"] in (r.first_page, r.first_page - 1), f"{r.paragraph_id}: heading too far away."

# chapters appear in document order
chapter_order = CHAPTERS
seq = pd.concat([paragraphs_df[["first_rkey", "section"]].rename(columns={"first_rkey": "rkey"}),
                 structured_units_df[["rkey", "section"]]]).sort_values("rkey")["section"].map(chapter_order.index)
assert seq.is_monotonic_increasing, "Units are not in chapter order."

# every IRO box sits in its own ESG theme subsection; milestones in 2.1; financial statements in 6.1
iro_paths = structured_units_df.loc[structured_units_df["unit_type"] == "iro_box", "subsection_path"]
assert all(p[1].startswith("4.2.") for p in iro_paths), "IRO box outside its 4.2.x theme."
iro_theme_numbers = [p[1].split()[0] for p in iro_paths]
assert iro_theme_numbers == [f"4.2.{i}" for i in range(1, 12)], iro_theme_numbers
assert structured_units_df.loc[structured_units_df["unit_type"] == "milestone", "subsection_path"].map(
    lambda p: p[0] == "2.1 Milestones 2025").all()
fin = structured_units_df[structured_units_df["table_id"].isin(["tab_p82a", "tab_p82b"])]
assert fin["subsection_path"].map(lambda p: p[0] == "6.1 Key figures").all()

summary = (paragraphs_df.assign(subsection=paragraphs_df["subsection_path"].map(" > ".join))
           .groupby(["section", "subsection"], sort=False).agg(paragraphs=("paragraph_id", "size")))
print("✅ Phase 8 validation passed.")
print(f"Paragraph locations: {len(summary)} distinct section/subsection paths")
with pd.option_context("display.max_rows", 60, "display.max_colwidth", 110):
    display(structured_units_df.assign(subsection=structured_units_df["subsection_path"].map(" > ".join))
            .drop_duplicates("subsection")[["unit_id", "unit_type", "section", "subsection"]])

# %% [markdown] cell 63
# # Phase 9 — Unified Logical Units + per-unit access control
#
# One pre-chunking table with a single authoritative text field (`content`): paragraphs + table rows +
# IRO boxes + text boxes + milestone cards + figures.
#
# - **9.1** combine the units in reading order.
# - **9.2** source errata in prose: a sentence the PDF itself contradicts is excluded with its evidence
#   (same policy as the table errata of 4.3).
# - **9.3** **access control per unit** (plan §3.1, `docs/rbac_mapping.md` §4): a keyword pre-filter lists every
#   unit that mentions money or finance; each candidate gets a reviewed decision and reason. Level 3 / Finance =
#   the Port of Rotterdam Authority's **own financial results and position**; everything else is
#   level 1 / Operations.
# - **9.4** validation.

# %% cell 64
# =========================================================
# 9.1 Combine paragraphs + structured units (reading order)
# =========================================================

unit_records = []
for r in paragraphs_df.itertuples():
    unit_records.append({
        "unit_id": r.paragraph_id, "unit_type": "paragraph",
        "logical_unit": f"paragraph_{int(r.paragraph_id[1:]):03d}", "title": None, "content": r.text,
        "section": r.section, "subsection_path": list(r.subsection_path),
        "page_start": r.page_start, "page_end": r.page_end, "order_key": r.first_rkey,
        "table_id": None, "figure_id": None, "is_bullet": bool(r.is_bullet),
        "provenance": "extracted", "flag": None,
    })
for r in structured_units_df.itertuples():
    unit_records.append({
        "unit_id": r.unit_id, "unit_type": r.unit_type, "logical_unit": r.unit_id.replace(".", "_"),
        "title": r.title, "content": r.content, "section": r.section, "subsection_path": list(r.subsection_path),
        "page_start": int(r.page_start), "page_end": int(r.page_end), "order_key": r.rkey,
        "table_id": r.table_id if isinstance(r.table_id, str) else None,
        "figure_id": r.figure_id if isinstance(r.figure_id, str) else None, "is_bullet": False,
        "provenance": r.description_provenance if isinstance(r.description_provenance, str) else "extracted",
        "flag": r.flag if isinstance(r.flag, str) else None,
    })

units_df = pd.DataFrame(unit_records)
units_df["sort_row"] = units_df["unit_id"].str.extract(r"_r(\d+)$")[0].fillna(0).astype(int)
units_df = units_df.sort_values(["order_key", "sort_row"], kind="stable").drop(columns="sort_row").reset_index(drop=True)
row_meta = structured_units_df.set_index("unit_id")[["row_text", "table_header_text"]]
units_df = units_df.join(row_meta, on="unit_id")
units_df["subsection"] = units_df["subsection_path"].map(lambda p: " > ".join(p) if p else None)

print("Units:", len(units_df), units_df["unit_type"].value_counts().to_dict())

# %% cell 65
# =========================================================
# 9.2 Source errata in prose (reviewed 2026-09-25)
# =========================================================
# p.70 "Male-female ratio": "Our Executive Board consisted of three women and five men and here, too, we are
# aiming for more proportional staffing." contradicts the next sentence ("Our Executive Board consists of two
# women and one man"), p.73 ("the Executive Board consists of two women and one man"; "Executive Board …
# (three members)"), the Executive Board table on p.73 and the three signatories of the foreword (p.4).
# The eight-person figure matches no board in the report; the sentence is excluded, the rest of the
# paragraph is kept.

PROSE_ERRATA = [
    {"match": "Our Executive Board consisted of three women and five men and here, too, we are aiming for more "
              "proportional staffing.",
     "evidence": "Contradicted on the same page and on p.73 (Executive Board = three members: two women, one man; "
                 "tab_p73b) and by the three signatories on p.4."},
]

errata_log = []
for e in PROSE_ERRATA:
    hits = units_df[units_df["content"].str.contains(e["match"], regex=False)]
    assert len(hits) == 1, f"Erratum must match exactly one unit: {e['match'][:50]}"
    i = hits.index[0]
    units_df.at[i, "content"] = " ".join(units_df.at[i, "content"].replace(e["match"], "").split())
    errata_log.append({"unit_id": units_df.at[i, "unit_id"], "removed": e["match"], "evidence": e["evidence"]})
errata_df = pd.DataFrame(errata_log)
display(errata_df)
print(units_df.set_index("unit_id").at[errata_df["unit_id"].iloc[0], "content"])

# %% cell 66
# =========================================================
# 9.3 Access control per unit (sensitivity_level / department) — reviewed 2026-09-25
# =========================================================
# Rule (plan §3.1, rbac_mapping.md §4): level 3 / Finance = the Port of Rotterdam Authority's OWN financial
# results and financial position (financial statements, revenue, operating expenses, EBITDA / net result,
# gross investments). Everything else is level 1 / Operations.
# The pre-filter lists every unit that mentions money or finance; every candidate is assigned below to
# exactly one reviewed decision (asserted), so no unit is classified by the keyword alone.

FIN_RE = re.compile(
    r"€|\beuros?\b|\brevenues?\b|\bEBITDA\b|\bearnings\b|\bnet result\b|\bresult after taxation\b|\bprofit\b"
    r"|\bbalance sheet\b|\bequity\b|\bdebts?\b|\binvest(?:ment|ments|ed|ing)?\b|\bfinancial\b|\bfinanc(?:e|ing)\b"
    r"|\bdividend\b|\bincome\b|\bexpenses?\b|\bcosts?\b|\bbudgets?\b|\bport dues\b|\bseaport dues\b", re.IGNORECASE)

FINANCIAL_UNITS = {
    "P030": "Revenue of the Port Authority (EUR 940.4 million, +6.6%) and its drivers.",
    "P031": "Operating expenses of the Port Authority (EUR 356.8 million, +12%) and their drivers.",
    "P032": "EBITDA (EUR 340.9 million) and net result (EUR 266.0 million) of the Port Authority.",
    "P033": "Gross investments of the Port Authority (EUR 291.4 million) and its largest investments.",
    "fig_p13": "Five-year series of the Port Authority's gross investments (million euro).",
    **{f"tab_p82a_r{i:02d}": "Balance sheet of the Port Authority (financial statements)." for i in range(1, 20)},
    **{f"tab_p82b_r{i:02d}": "Income statement of the Port Authority (financial statements)." for i in range(1, 14)},
}

LEVEL1_REASONS = {
    "investing_qualitative": ("Investing / investment climate mentioned as an activity or condition, without any "
                              "figure of the Port Authority's own results.",
                              ["P002", "P004", "P026", "P057", "P063", "P069", "P071", "P079", "P082", "P088", "P091",
                               "P093", "P135", "P151", "box_p30", "P156", "P157", "P158", "P159", "P163", "P166",
                               "P167", "P170", "P172", "P183", "P184", "P203", "P216", "P219", "P226", "P291", "P318",
                               "P336", "P384", "fig_p23"]),
    "qualitative_result": ("Foreword: the financial result is mentioned qualitatively ('stable'), no figures; the "
                           "figures themselves are in 3.2.2 and 6.1 (level 3).", ["P003"]),
    "programme_amounts": ("Amounts of community funds, sponsorships, programme budgets, State subsidies or port-due "
                          "discounts: published ESG / community narrative, not a financial statement item.",
                          ["milestone_p6_1", "milestone_p7_3", "P056", "P068", "P130", "P148", "box_p31"]),
    "materiality_qualitative": ("'Financial materiality' / financial impact as a concept of the double materiality "
                                "analysis or an ESG impact box; qualitative, no figures.",
                                ["P114", "P120", "fig_p26", "P122", "iro_p27", "iro_p35", "iro_p48", "iro_p65",
                                 "P169", "P205"]),
    "governance": ("Governance: shareholders, approval thresholds, board and committee duties, organisation chart; "
                   "no financial results.", ["P340", "P346", "P357", "fig_p69", "fig_p71", "P364", "P368", "P377",
                                             "P387"]),
    "risk_and_reporting_process": ("Risk management and reporting processes (financial risks, financial reporting, "
                                   "planning & control) described qualitatively, without figures.",
                                   ["P103", "P390", "P392", "P393", "P398", "P399", "P402", "P404", "P405", "P406",
                                    "P407", "P409", "P411", "P413", "P414", "P415", "P417", "P422"]),
    "economic_impact": ("Economic significance of the port (added value, GDP share, jobs; Havenmonitor), not the "
                        "Port Authority's own finances.", ["P001", "P092", "tab_p83b_r01"]),
    "esg_kpi_ratio": ("Energy consumption table with its energy-intensity note (MWh per million euros of revenue): an "
                      "ESG KPI that discloses no financial statement item.",
                      [f"tab_p32_r{i:02d}" for i in range(1, 10)]),
    "costs_qualitative": ("Costs mentioned qualitatively in operational or ESG narrative (lower costs, cost of "
                          "damage, operational safety costs, financial well-being of employees).",
                          ["P041", "P042", "P177", "P188", "P262", "P267", "P283"]),
    "scenarios": ("Scenario narratives and business-model outlook ('financial prosperity', 'revenues will remain "
                  "stable'); no figures.", ["P096", "P097", "P098", "P102"]),
}

candidates = set(units_df.loc[units_df["content"].str.contains(FIN_RE), "unit_id"])
level1_ids = [u for _, ids in LEVEL1_REASONS.values() for u in ids]
assert len(level1_ids) == len(set(level1_ids)), "A unit is listed under two level-1 reasons."
assert not set(level1_ids) & set(FINANCIAL_UNITS), "A unit is both financial and level 1."
assert candidates == set(level1_ids) | set(FINANCIAL_UNITS), \
    f"Unreviewed candidates: {sorted(candidates - set(level1_ids) - set(FINANCIAL_UNITS))} | " \
    f"not candidates: {sorted(set(level1_ids) | set(FINANCIAL_UNITS) - candidates)}"

reason_of_unit = {u: (code, text) for code, (text, ids) in LEVEL1_REASONS.items() for u in ids}
access_records = []
for r in units_df.itertuples():
    if r.unit_id in FINANCIAL_UNITS:
        access, code, reason = FINANCIAL_ACCESS, "own_financials", FINANCIAL_UNITS[r.unit_id]
    elif r.unit_id in reason_of_unit:
        access, (code, reason) = DEFAULT_ACCESS, reason_of_unit[r.unit_id]
    else:
        access, code, reason = DEFAULT_ACCESS, "no_financial_content", "No money or finance mentioned (pre-filter)."
    access_records.append({"unit_id": r.unit_id, "sensitivity_level": access["sensitivity_level"],
                           "department": access["department"], "access_code": code, "access_reason": reason,
                           "fin_keywords": sorted({m.lower() for m in FIN_RE.findall(r.content)})})
access_df = pd.DataFrame(access_records)
units_df = units_df.merge(access_df[["unit_id", "sensitivity_level", "department", "access_code"]], on="unit_id")

print("Candidates reviewed:", len(candidates), "| level 3 / Finance:", len(FINANCIAL_UNITS))
display(access_df.groupby(["sensitivity_level", "department", "access_code"]).size().rename("units"))
with pd.option_context("display.max_colwidth", 100):
    display(units_df.loc[units_df["sensitivity_level"] == 3, ["unit_id", "unit_type", "page_start", "subsection"]]
            .drop_duplicates("subsection"))

# %% cell 67
# =========================================================
# 9.4 Validate units
# =========================================================
assert units_df["unit_id"].is_unique
assert units_df["content"].str.strip().ne("").all()
assert units_df["section"].notna().all()
assert units_df["unit_type"].value_counts().to_dict() == \
    {"paragraph": 426, "table_row": 144, "iro_box": 11, "figure": 9, "milestone": 8, "box": 4}
assert units_df["sensitivity_level"].isin([1, 3]).all()
assert units_df["department"].isin(KNOWN_DEPARTMENTS).all()
assert (units_df.loc[units_df["sensitivity_level"] == 3, "department"] == "Finance").all()
assert (units_df.loc[units_df["sensitivity_level"] == 1, "department"] == "Operations").all()
assert units_df["flag"].isna().all(), "No unit may remain flagged."

# every financial-statement figure and every 3.2.2 financial paragraph is level 3; nothing else is
lvl3 = set(units_df.loc[units_df["sensitivity_level"] == 3, "unit_id"])
assert lvl3 == set(FINANCIAL_UNITS)
assert units_df.loc[units_df["unit_id"].isin(["P030", "P031", "P032", "P033"]), "subsection_path"].map(
    lambda p: p[-1] == "3.2.2 Throughput and financials").all()

# errata applied once, and the removed sentence is gone
assert len(errata_df) == len(PROSE_ERRATA)
assert not units_df["content"].str.contains("three women and five men", regex=False).any()

print("✅ Unified logical units:", len(units_df), units_df["unit_type"].value_counts().to_dict())
print("Access:", units_df.groupby(["sensitivity_level", "department"]).size().to_dict())
print("Units > MAX_CHUNK_CHARS (to be split at chunking):",
      units_df.loc[units_df["content"].str.len() > MAX_CHUNK_CHARS, "unit_id"].tolist())

# %% [markdown] cell 68
# # Phase 10 — Duplicate Detection (within-source and cross-source)
#
# Deterministic, no embeddings (ADR-010 / ADR-019):
#
# 1. exact duplicates by normalized-text hash;
# 2. candidate blocking by unit family + TF-IDF character n-gram cosine (prose), or number signatures (table rows);
# 3. **item-level** comparison — sentences for prose, the row (label + numbers) for table rows — with `difflib`
#    ratios. A sentence is *covered* when it is repeated (ratio ≥ 0.90) or paraphrased (≥ 0.75) **without adding
#    any new content word**. A table row is covered by another row when all its numbers (decimal commas
#    normalized) appear in that row and the labels share a content word.
#
# **Within-source** is the main case here: the report summarises itself in the Foreword, in "2025 at a glance"
# (milestones) and in the key-figure tables of 6.1. **Cross-source** is checked against every cleaned unit of the
# four existing sources (LPI Methodology, LPI Connecting to Compete, FBL, Suez Notes); no overlap is expected.
# The unit `content` is never modified in this phase.

# %% cell 69
# =========================================================
# 10.1 Comparison normalization, sentences, content tokens, number signatures
# =========================================================
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

CANDIDATE_SIM = 0.50        # TF-IDF (char 3–5 grams) cosine to enter the detailed comparison
SENTENCE_MATCH = 0.90       # difflib ratio: sentence repeated (near-)verbatim
PARAPHRASE_MATCH = 0.75     # ratio for a rephrased sentence that adds NO new content words

SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z‘“\"(])")
STOPWORDS = set("""the a an of and or to in for on by with from as at is are be that this these those which its their it
into than more most such can may also both each other has have was were not but between over across while within through
our we us port rotterdam authority""".split())


def cmp_norm(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).replace("­", "").lower()
    t = re.sub(r"[‐‑–—−]", "-", t)
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


def number_signature(text: str) -> list[float]:
    """Numbers of a table row's VALUES (column names excluded), decimal commas normalised ('-6,5%' == '-6.5%'),
    thousands commas removed, year-like tokens (1900–2099 printed without a comma) dropped."""
    if " — " in text:
        text = "; ".join(part.split(": ", 1)[-1] for part in text.split(" — ", 1)[1].split("; "))
    out = []
    for n in re.findall(r"-?\d[\d.,]*", text):
        n = n.rstrip(".,")
        if re.fullmatch(r"(19|20)\d\d", n):
            continue
        if re.fullmatch(r"-?\d+,\d", n):                     # decimal comma
            n = n.replace(",", ".")
        n = n.replace(",", "")
        try:
            out.append(float(n))
        except ValueError:
            pass
    return out


assert number_signature("Dry bulk cargo — 2025: 66,562; Difference (%): -6,5%") == [66562.0, -6.5]
assert number_signature("X — Objective: -20% in 2030 compared to 2019") == [-20.0]
assert sentences("It rose. Then it fell. ‘Quoted’ start.") == ["It rose.", "Then it fell.", "‘Quoted’ start."]

FAMILY = {"paragraph": "prose", "box": "prose", "iro_box": "prose", "milestone": "prose", "figure": "prose",
          "worked_example": "prose", "definitions": "definitions", "table_row": "table_row"}


def items_of(u: dict) -> list[str]:
    if u["unit_type"] == "table_row":
        return [u["row_text"]]
    return sentences(u["content"])


print("Thresholds:", {"CANDIDATE_SIM": CANDIDATE_SIM, "SENTENCE_MATCH": SENTENCE_MATCH, "PARAPHRASE_MATCH": PARAPHRASE_MATCH})

# %% cell 70
# =========================================================
# 10.2 Reference corpus: cleaned units of the existing sources
# =========================================================
# Older cleaned files store a plain list of units; LPI Connecting to Compete stores {source, units, …};
# the FBL units use `text`; the Suez Notes are a plain text file (one note per "-" item).

def load_reference_units() -> list[dict]:
    refs = []
    meth = json.loads((CLEANED_DIR / "LPI_Methodology_logical_units.json").read_text(encoding="utf-8"))
    refs += [{"source": "LPI_Methodology", "unit_id": u["unit_id"], "unit_type": u["unit_type"], "content": u["content"]}
             for u in meth]
    c2c = json.loads((CLEANED_DIR / "LPI_Connecting_to_Compete_logical_units.json").read_text(encoding="utf-8"))
    refs += [{"source": "LPI_Connecting_to_Compete", "unit_id": u["unit_id"], "unit_type": u["unit_type"],
              "content": u["content"]} for u in c2c["units"]]
    fbl = json.loads((CLEANED_DIR / "FBL_template_logical_units.json").read_text(encoding="utf-8"))
    refs += [{"source": "FBL_template", "unit_id": u["logical_unit"], "unit_type": "paragraph", "content": u["text"]}
             for u in fbl]
    suez = (CLEANED_DIR / "suez_notes_cleaned.txt").read_text(encoding="utf-8")
    notes = [n.strip() for n in re.split(r"\n-\s*\n?", suez) if n.strip() and not n.strip().lower().startswith("notes")]
    refs += [{"source": "Suez_Notes", "unit_id": f"suez_note_{i}", "unit_type": "paragraph", "content": n}
             for i, n in enumerate(notes, start=1)]
    return refs


reference_units = load_reference_units()
print("Reference units:", pd.Series([r["source"] for r in reference_units]).value_counts().to_dict())

# %% cell 71
# =========================================================
# 10.3 Exact hash duplicates + candidate blocking
# =========================================================
units_df["norm_hash"] = units_df["content"].map(text_hash)
ref_hash = {text_hash(r["content"]): (r["source"], r["unit_id"]) for r in reference_units}

within_exact = units_df[units_df.duplicated("norm_hash", keep=False)]
cross_exact = units_df[units_df["norm_hash"].isin(ref_hash)]
print(f"Exact within-source duplicates: {len(within_exact)} | exact cross-source duplicates: {len(cross_exact)}")

unit_dicts_all = units_df.to_dict("records")
ours = [cmp_norm(u["content"] if u["unit_type"] != "table_row" else u["row_text"]) for u in unit_dicts_all]
refs = [cmp_norm(r["content"]) for r in reference_units]
vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5)).fit(ours + refs)
V_ours, V_refs = vectorizer.transform(ours), vectorizer.transform(refs)
SIM_cross = cosine_similarity(V_ours, V_refs)
SIM_within = cosine_similarity(V_ours)
np.fill_diagonal(SIM_within, 0.0)

sigs = [number_signature(u["row_text"]) if u["unit_type"] == "table_row" else [] for u in unit_dicts_all]

candidates = []
for i, u in enumerate(unit_dicts_all):
    fam = FAMILY[u["unit_type"]]
    for j, r in enumerate(reference_units):
        if FAMILY.get(r["unit_type"], "prose") == fam and SIM_cross[i, j] >= CANDIDATE_SIM:
            candidates.append(("cross", i, j, float(SIM_cross[i, j])))
    for j, v in enumerate(unit_dicts_all):
        if j == i or FAMILY[v["unit_type"]] != fam:
            continue
        if fam == "table_row":
            # all numbers of row i appear in row j; at least 3 distinct non-zero values (years excluded), so
            # rows of zeros / identical scores or accounting identities (total assets = total liabilities) do not match
            a, b = sigs[i], sigs[j]
            if len({x for x in a if x != 0}) >= 3 and all(a.count(x) <= b.count(x) for x in set(a)):
                candidates.append(("within", i, j, float(SIM_within[i, j])))
        elif SIM_within[i, j] >= CANDIDATE_SIM:
            candidates.append(("within", i, j, float(SIM_within[i, j])))
print(f"Candidate pairs: {len(candidates)} (cross={sum(c[0] == 'cross' for c in candidates)}, "
      f"within={sum(c[0] == 'within' for c in candidates)})")

# %% cell 72
# =========================================================
# 10.4 Item-level comparison
# =========================================================

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


def label_words(row_text: str) -> set[str]:
    return content_tokens(re.split(r" — ", row_text)[0])


pair_records = []
for scope, i, j, sim in candidates:
    u = unit_dicts_all[i]
    if scope == "cross":
        r = reference_units[j]
        other = {"source": r["source"], "unit_id": r["unit_id"], "unit_type": r["unit_type"]}
        items = compare_items(items_of(u), sentences(r["content"]), r["content"])
        exact = u["norm_hash"] == text_hash(r["content"])
    else:
        v = unit_dicts_all[j]
        other = {"source": SOURCE_NAME, "unit_id": v["unit_id"], "unit_type": v["unit_type"]}
        exact = u["norm_hash"] == v["norm_hash"]
        if u["unit_type"] == "table_row":          # number signature already matched; labels must share a word
            shared = label_words(u["row_text"]) & label_words(v["row_text"])
            items = [{"item": u["row_text"], "best_ratio": 1.0 if shared else 0.0,
                      "new_words": [] if shared else sorted(label_words(u["row_text"])), "covered": bool(shared)}]
        else:
            items = compare_items(items_of(u), items_of(v), v["content"])
    pair_records.append({
        "scope": scope, "unit_id": u["unit_id"], "unit_type": u["unit_type"], "section": u["section"],
        "candidate_source": other["source"], "candidate_unit_id": other["unit_id"], "candidate_type": other["unit_type"],
        "similarity_score": round(sim, 3), "exact": bool(exact),
        "items_total": len(items), "items_covered": sum(x["covered"] for x in items),
        "uncovered_items": [x for x in items if not x["covered"]], "item_details": items,
    })
pairs_df = pd.DataFrame(pair_records)


def relationship(p) -> str:
    if p["exact"]:
        return "exact_duplicate"
    if p["items_covered"] == p["items_total"]:
        return "near_duplicate"
    if p["items_covered"] and all(x["best_ratio"] >= PARAPHRASE_MATCH for x in p["uncovered_items"]):
        return "duplicate_candidate_review"
    if p["items_covered"]:
        return "contextual_duplicate"
    return "unique"


pairs_df["relationship"] = pairs_df.apply(relationship, axis=1)
pairs_df["unique_information_flag"] = pairs_df["items_covered"] < pairs_df["items_total"]

print("Relationships:")
display(pairs_df.groupby(["scope", "relationship"]).size().rename("pairs"))
with pd.option_context("display.max_rows", None, "display.max_colwidth", 60):
    display(pairs_df[pairs_df["items_covered"] > 0].sort_values(["scope", "unit_id"])[
        ["scope", "unit_id", "candidate_unit_id", "similarity_score", "items_covered", "items_total", "relationship"]])

# %% [markdown] cell 73
# # Phase 11 — Duplicate Decisions
#
# Canonical-source policy (ADR-019 applied within one document):
#
# - The **thematic chapters** (3 The Port of Rotterdam Authority, 4 ESG report, 5 Governance, and the financial
#   statements of 6.1) are canonical: their units are never suppressed or trimmed.
# - The **summary parts** — the Foreword, "2025 at a glance" (milestones) and the key-figure tables of 6.1
#   (`tab_p83a`, `tab_p83b`) — are non-canonical: a summary unit fully covered by a canonical unit is suppressed;
#   a summary unit that repeats some canonical sentences keeps only its new sentences.
# - A repeat **between two canonical units** is kept (`keep_contextual`): here those are templated statements that
#   each belong to their own subsection (e.g. the assurance-level sentence of each risk category, the SEI
#   definition in Policy and in Results); trimming one would take a fact away from its section.
# - Cross-source: nothing to decide (10.3 found no candidate against the other four sources).
#
# Every decision, every candidate pair and every removed item goes into the duplicate audit.

# %% cell 74
# =========================================================
# 11.1 Canonical policy
# =========================================================
SUMMARY_CHAPTERS = {"Foreword Executive Board", "2025 at a glance"}
SUMMARY_TABLES = {"tab_p83a", "tab_p83b"}


def is_summary(u) -> bool:
    return u["section"] in SUMMARY_CHAPTERS or u.get("table_id") in SUMMARY_TABLES


units_df["is_summary"] = [is_summary(u) for u in units_df.to_dict("records")]
print("Summary (non-canonical) units:", int(units_df["is_summary"].sum()),
      units_df[units_df["is_summary"]].groupby("unit_type").size().to_dict())


def union_coverage(unit_id: str, canonical_only: bool) -> tuple[list, list, list]:
    """Items of unit_id covered by any within-source candidate (optionally canonical candidates only)."""
    ps = pairs_df[(pairs_df["unit_id"] == unit_id) & (pairs_df["scope"] == "within")]
    if canonical_only:
        ps = ps[~ps["candidate_unit_id"].map(units_df.set_index("unit_id")["is_summary"])]
    if ps.empty:
        return [], [], []
    items = ps.iloc[0]["item_details"]
    covered_by = {}
    for p in ps.itertuples():
        for k, it in enumerate(p.item_details):
            if it["covered"]:
                covered_by.setdefault(k, p.candidate_unit_id)
    covered = [(items[k]["item"], covered_by[k]) for k in sorted(covered_by)]
    uncovered = [items[k] for k in range(len(items)) if k not in covered_by]
    return covered, uncovered, sorted(set(covered_by.values()))

# %% cell 75
# =========================================================
# 11.2 Unit decisions
# =========================================================
decisions = []
for u in units_df.to_dict("records"):
    uid = u["unit_id"]
    rec = {"unit_id": uid, "unit_type": u["unit_type"], "section": u["section"], "is_summary": u["is_summary"],
           "relationship": "unique", "action": "keep", "canonical_unit_ids": [], "canonical_source": None,
           "removed_items": [], "reason": "No candidate duplicate."}
    has_pairs = not pairs_df[(pairs_df["unit_id"] == uid) & (pairs_df["scope"] == "within")].empty
    if u["is_summary"]:
        cov, unc, cands = union_coverage(uid, canonical_only=True)
        if cov and not unc:
            rec.update(relationship="near_duplicate", action="suppress_duplicate", canonical_unit_ids=cands,
                       canonical_source=SOURCE_NAME, removed_items=[c[0] for c in cov],
                       reason="Summary unit fully covered by the canonical chapter text/table.")
        elif cov:
            rec.update(relationship="contextual_duplicate", action="trim_duplicate_sentences", canonical_unit_ids=cands,
                       canonical_source=SOURCE_NAME, removed_items=[c[0] for c in cov],
                       reason=f"Summary unit: {len(cov)} item(s) repeated in {cands} trimmed; {len(unc)} new item(s) kept.")
    elif has_pairs:
        cov, unc, cands = union_coverage(uid, canonical_only=True)
        if cov:
            rec.update(relationship="contextual_duplicate", action="keep_contextual", canonical_unit_ids=[uid],
                       canonical_source=SOURCE_NAME,
                       reason=f"Canonical unit; {len(cov)} item(s) also stated in {cands}, kept because each occurrence "
                              "belongs to its own subsection.")
    decisions.append(rec)
decisions_df = pd.DataFrame(decisions)

audit_pairs_df = pairs_df.assign(
    source_document=SOURCE_NAME,
    normalized_hash=pairs_df["unit_id"].map(units_df.set_index("unit_id")["norm_hash"]),
)[["source_document", "scope", "unit_id", "unit_type", "candidate_source", "candidate_unit_id", "candidate_type",
   "relationship", "similarity_score", "exact", "items_covered", "items_total", "unique_information_flag",
   "normalized_hash", "uncovered_items"]]

print("Unit-level decisions:")
display(decisions_df.groupby(["relationship", "action"]).size().rename("units"))
with pd.option_context("display.max_rows", None, "display.max_colwidth", 110):
    display(decisions_df[decisions_df["action"] != "keep"][["unit_id", "relationship", "action", "canonical_unit_ids", "reason"]])

# %% cell 76
# =========================================================
# 11.3 Post-dedup corpus
# =========================================================
def apply_decision(u, d):
    if d["action"] == "trim_duplicate_sentences":
        removed = set(d["removed_items"])
        head, *body = u["content"].split("\n", 1) if u["unit_type"] == "milestone" else ("", u["content"])
        kept = " ".join(s for s in sentences(" ".join(body) if isinstance(body, list) else body) if s not in removed)
        return f"{head}\n{kept}" if head else kept
    return u["content"]


dec_by_id = decisions_df.set_index("unit_id")
final_units_df = units_df[~units_df["unit_id"].map(dec_by_id["action"]).eq("suppress_duplicate")].copy()
final_units_df["content"] = [apply_decision(u, dec_by_id.loc[u["unit_id"]]) for u in final_units_df.to_dict("records")]
final_units_df["dedup_action"] = final_units_df["unit_id"].map(dec_by_id["action"])
final_units_df["char_count"] = final_units_df["content"].str.len()
final_units_df = final_units_df.reset_index(drop=True)

for r in final_units_df[final_units_df["dedup_action"] == "trim_duplicate_sentences"].itertuples():
    print(f"--- {r.unit_id} (trimmed):\n{r.content}")
print(f"\nUnits: {len(units_df)} -> post-dedup: {len(final_units_df)}")

# %% [markdown] cell 77
# # Phase 12 — Final Logical-Unit QA
#
# Gate before chunking: every unit is kept or suppressed with a canonical mapping, every table and every kept
# graphic is still represented, trims removed only repeated items, access levels are intact, and the decisions
# match the reviewed snapshot.

# %% cell 78
# =========================================================
# 12.1 Coverage and suppression checks
# =========================================================
final_ids = set(final_units_df["unit_id"])
suppressed = decisions_df[decisions_df["action"] == "suppress_duplicate"]
trimmed = decisions_df[decisions_df["action"] == "trim_duplicate_sentences"]

assert set(units_df["unit_id"]) == final_ids | set(suppressed["unit_id"])
assert suppressed["canonical_unit_ids"].map(len).gt(0).all(), "Suppressed unit without canonical mapping."
assert set(suppressed["canonical_unit_ids"].explode()) <= final_ids, "A canonical copy was itself suppressed."
assert (~decisions_df.loc[decisions_df["action"].isin(["suppress_duplicate", "trim_duplicate_sentences"]), "unit_id"]
        .map(units_df.set_index("unit_id")["is_summary"])).sum() == 0, "Only summary units may be suppressed/trimmed."

# every table still has rows; every kept graphic is kept
for tid in TABLE_SPECS:
    assert final_units_df["table_id"].eq(tid).any(), f"{tid} lost all its rows."
assert set(final_units_df.loc[final_units_df["unit_type"] == "figure", "unit_id"]) == set(figure_units_df["unit_id"])

# trims removed only covered items and left text behind
for d in trimmed.itertuples():
    kept = final_units_df.set_index("unit_id").at[d.unit_id, "content"]
    assert kept.strip() and all(item not in kept for item in d.removed_items), f"{d.unit_id}: trim failed."

# access levels unchanged; level-3 units never suppressed
assert set(FINANCIAL_UNITS) <= final_ids, "A level-3 unit was suppressed."

# ---- reviewed snapshot (2026-09-26) ----
REVIEWED_SUPPRESSED = sorted(["tab_p83a_r06", "tab_p83a_r11", "tab_p83a_r12", "tab_p83a_r16", "tab_p83a_r19",
                              "tab_p83a_r20", "tab_p83a_r21", "tab_p83a_r22", "tab_p83a_r23"])
REVIEWED_TRIMMED = ["milestone_p7_4"]
REVIEWED_KEEP_CONTEXTUAL = sorted(["P007", "P017", "P297", "P323", "P329", "P414", "P418", "P421"])
REVIEWED_MANUAL_REVIEW = []
assert sorted(suppressed["unit_id"]) == REVIEWED_SUPPRESSED, sorted(suppressed["unit_id"])
assert sorted(trimmed["unit_id"]) == REVIEWED_TRIMMED, sorted(trimmed["unit_id"])
assert sorted(decisions_df.loc[decisions_df["action"] == "keep_contextual", "unit_id"]) == REVIEWED_KEEP_CONTEXTUAL, \
    sorted(decisions_df.loc[decisions_df["action"] == "keep_contextual", "unit_id"])
assert "manual_review" not in set(decisions_df["action"])
assert not pairs_df["scope"].eq("cross").any(), "Cross-source candidates appeared: review them."

print("✅ Final logical-unit QA passed.")
print(f"Units: {len(units_df)} -> kept {len(final_units_df)} | suppressed {len(suppressed)} | trimmed {len(trimmed)} | "
      f"kept contextual {len(REVIEWED_KEEP_CONTEXTUAL)} | manual review pending 0")
display(final_units_df.groupby(["unit_type", "sensitivity_level"]).size().rename("kept units"))

# %% [markdown] cell 79
# # Phase 13 — Save Extracted + Cleaned Artifacts
#
# One file per layer:
# - `extracted/HbR_Annual_report_2025_extracted.json` — raw structured layer: page classes, section map,
#   subscripts, tables (spec + meta), structured regions, graphics (gate, elements, photos), bullets, body lines,
#   paragraphs, errata, access decisions
# - `cleaned/HbR_Annual_report_2025_logical_units.json` — **the single cleaned file**: `source`, `units` (post-dedup
#   units with their `sensitivity_level` / `department`) and `duplicate_audit`; Phase 19 adds `coverage_audit`
#
# Each file is reloaded from disk and re-validated.

# %% cell 80
# =========================================================
# 13. Save extracted + cleaned artifacts, then reload and validate
# =========================================================

def to_records(df: pd.DataFrame) -> list[dict]:
    return json.loads(df.to_json(orient="records", force_ascii=False, default_handler=str))


EXTRACTED_PATH = EXTRACTED_DIR / f"{SOURCE_NAME}_extracted.json"
LOGICAL_UNITS_PATH = CLEANED_DIR / f"{SOURCE_NAME}_logical_units.json"     # the ONE cleaned file of this source

extracted_payload = {
    "source": {**source_metadata, "sha256": SOURCE_SHA256, "pages": int(len(pages_df))},
    "page_classification": to_records(page_class_df[["page_number", "page_class", "keep_for_retrieval", "active_nav",
                                                     "reason"]]),
    "section_map": to_records(section_map[["heading_id", "page_number", "column", "y0", "level", "role",
                                           "heading_text", "section", "subsection", "basis"]]),
    "subscripts": to_records(subscripts_df[["page_number", "x0", "y0", "text", "host_text"]]),
    "tables": {"spec": {k: {**v} for k, v in TABLE_SPECS.items()}, "meta": to_records(table_meta_df),
               "errata": [{"table_id": k[0], "row": k[1], "column": k[2], "evidence": v} for k, v in TABLE_ERRATA.items()]},
    "structured_regions": to_records(structured_regions_df),
    "graphics": {"gate": to_records(figure_gate_df), "elements": to_records(figure_elements_df),
                 "images": to_records(images_df), "chart_evidence": {
                     "fig_p13": FIG_P13_TOTALS, "fig_p33a": FIG_P33A_TOTALS, "fig_p33b": FIG_P33B_STEPS}},
    "notes": {"registry": [], "markers": [], "finding": "No footnotes or endnotes (Phase 5)."},
    "body_lines": to_records(body_lines_df[["line_uid", "page_number", "column", "y0", "text", "line_break",
                                            "is_bullet_start"]]),
    "paragraphs": to_records(paragraphs_df[["paragraph_id", "text", "page_start", "page_end", "boundary_reason",
                                            "is_bullet", "line_uids"]]),
    "prose_errata": to_records(errata_df),
    "access_decisions": to_records(access_df),
}
UNIT_FIELDS = ["unit_id", "unit_type", "logical_unit", "title", "content", "section", "subsection", "subsection_path",
               "page_start", "page_end", "table_id", "figure_id", "is_bullet", "provenance", "flag", "dedup_action",
               "sensitivity_level", "department"]
duplicate_audit = {
    "thresholds": {"CANDIDATE_SIM": CANDIDATE_SIM, "SENTENCE_MATCH": SENTENCE_MATCH, "PARAPHRASE_MATCH": PARAPHRASE_MATCH,
                   "table_rows": "all numbers contained + >= 3 distinct non-zero values + shared label word"},
    "reference": sorted({r["source"] for r in reference_units}),
    "canonical_policy": {"summary (non-canonical)": sorted(SUMMARY_CHAPTERS) + sorted(SUMMARY_TABLES),
                         SOURCE_NAME: "thematic chapters 3–5 and the financial statements of 6.1"},
    "unit_decisions": to_records(decisions_df),
    "pairs": to_records(audit_pairs_df),
}

EXTRACTED_PATH.write_text(json.dumps(extracted_payload, ensure_ascii=False, indent=1), encoding="utf-8")
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
assert len(re_extracted["paragraphs"]) == len(paragraphs_df)
assert [u["unit_id"] for u in re_units] == final_units_df["unit_id"].tolist()
assert all(u["content"] == c for u, c in zip(re_units, final_units_df["content"]))
assert [u["sensitivity_level"] for u in re_units] == final_units_df["sensitivity_level"].tolist()
assert len(re_audit["unit_decisions"]) == len(units_df)
assert sorted(p.name for p in CLEANED_DIR.glob(f"{SOURCE_NAME}_*")) == [LOGICAL_UNITS_PATH.name], \
    "The cleaned layer of this source must be exactly one file."
for p in (EXTRACTED_PATH, LOGICAL_UNITS_PATH):
    print(f"Saved + reloaded: {p.name:50} {p.stat().st_size:>10,} bytes")

# %% [markdown] cell 81
# # Phase 14 — Semantic Chunking
#
# Same philosophy as the other notebooks, plus one new rule for access control:
#
# - **Paragraphs** are never split; adjacent paragraphs of the same section/subsection are grouped while short
#   (`MIN_CHUNK_CHARS`), up to `MAX_CHUNK_CHARS` (a safety cap), so bullet items join their introduction.
# - **Table rows** (deviation from the LPI notebooks): the rows here are short KPI rows (median ≈ 200 chars), so
#   consecutive rows of the **same table** are grouped into one chunk up to `MAX_CHUNK_CHARS`, with the table title
#   (and note) written once at the top. A row is never split; a chunk never mixes tables.
# - **IRO boxes, text boxes, milestone cards and figures**: one self-contained chunk each.
# - **Section blocks**: a section made only of short paragraphs separated by minor headings has no piece that
#   stands alone (6.2 Credits: "Port of Rotterdam Authority", a postal address, …). The whole section becomes
#   **one** chunk, each piece labelled with its heading (`Contact > Office address: …`).
# - **Balanced table splits**: when a table does not fit in one chunk, its rows are split into the fewest
#   chunks that fit, with (almost) equal row counts — never a large chunk plus a one-row remainder.
# - No chunk is a fragment: every chunk has at least `FRAGMENT_MIN_CHARS` (50) characters (15.1).
# - **A chunk never mixes access levels or departments** — the grouping key includes `sensitivity_level` and
#   `department`, and 15.3 asserts it.
#
# `chunk_id` = `hbr2025_<logical_unit>_chunk_<n>`.

# %% cell 82
# =========================================================
# 14.1 Chunking rules
# =========================================================
CHUNK_SEPARATOR = "\n\n"


def location(u) -> tuple:
    return (u["section"], u["subsection"], int(u["sensitivity_level"]), u["department"])


def split_by_sentences(text: str, limit: int = MAX_CHUNK_CHARS) -> list[str]:
    parts, current = [], ""
    for s in sentences(text):
        if current and len(current) + 1 + len(s) > limit:
            parts.append(current)
            current = s
        else:
            current = f"{current} {s}".strip()
    return parts + ([current] if current else [])


def chunk_title(u) -> str:
    if isinstance(u["title"], str) and u["title"]:
        return u["title"]
    return u["subsection_path"][-1] if u["subsection_path"] else u["section"]


def make_chunk(units: list[dict], unit_type: str, logical_unit: str, part: int, text: str,
               title: str | None = None) -> dict:
    first = units[0]
    return {
        "page": int(min(u["page_start"] for u in units)),
        "unit_type": unit_type, "logical_unit": logical_unit,
        "chunk_id": f"{CHUNK_PREFIX}_{logical_unit}_chunk_{part}",
        "section": first["section"], "subsection_path": list(first["subsection_path"]),
        "title": title or chunk_title(first), "text": text,
        "sensitivity_level": int(first["sensitivity_level"]), "department": first["department"],
        "source_unit_ids": [u["unit_id"] for u in units],
    }

# %% cell 83
# =========================================================
# 14.2 Paragraph chunks
# =========================================================
unit_dicts = final_units_df.to_dict("records")

# Section blocks: every unit of the section is a short paragraph and they sit under different minor headings
block_members: dict[tuple, list] = {}
for u in unit_dicts:
    if u["subsection_path"]:
        block_members.setdefault((u["section"], u["subsection_path"][0], int(u["sensitivity_level"]), u["department"]), []).append(u)
SECTION_BLOCKS = {k: us for k, us in block_members.items()
                  if len(us) > 1 and all(u["unit_type"] == "paragraph" and u["char_count"] < MIN_CHUNK_CHARS for u in us)
                  and len({tuple(u["subsection_path"]) for u in us}) > 1
                  and sum(u["char_count"] for u in us) <= MAX_CHUNK_CHARS}
assert [k[:2] for k in SECTION_BLOCKS] == [("Other information", "6.2 Credits")], list(SECTION_BLOCKS)   # reviewed
block_unit_ids = {u["unit_id"] for us in SECTION_BLOCKS.values() for u in us}
BLOCK_LABELS = []

paragraph_units = [u for u in unit_dicts if u["unit_type"] == "paragraph" and u["unit_id"] not in block_unit_ids]

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

for (section, heading, _, _), us in SECTION_BLOCKS.items():
    labels = [" > ".join(u["subsection_path"][1:]) for u in us]
    BLOCK_LABELS += labels
    text = CHUNK_SEPARATOR.join(f"{label}: {u['content']}" for label, u in zip(labels, us))
    name = "section_" + re.sub(r"[^a-z0-9]+", "_", heading.lower()).strip("_")
    rec = make_chunk(us, "paragraph", name, 1, text, title=heading)
    rec["subsection_path"], rec["section_block"] = [heading], True
    chunk_records.append(rec)
    print(f"Section block {heading!r}: {len(us)} short units -> {rec['chunk_id']} ({len(text)} chars)\n{text}\n")

print(f"Paragraph units: {len(paragraph_units) + len(block_unit_ids)} -> paragraph chunks: {len(chunk_records)}")

# %% cell 84
# =========================================================
# 14.3 Structured chunks (table groups, boxes, cards, figures)
# =========================================================
# Table rows: consecutive kept rows of the same table (same access) form a run; a run that does not fit in
# one chunk is split into the fewest parts that fit, with equal row counts (no one-row remainder).
def table_chunk_size(rows: list) -> int:
    return len(rows[0]["table_header_text"]) + sum(len(x["row_text"]) + 1 for x in rows)


table_runs = []
for u in (u for u in unit_dicts if u["unit_type"] == "table_row"):
    g = table_runs[-1] if table_runs else None
    if g and g[-1]["table_id"] == u["table_id"] and location(g[-1])[2:] == location(u)[2:]:
        g.append(u)
    else:
        table_runs.append([u])

table_groups = []
for run in table_runs:
    k = 1
    while True:
        parts = [list(p) for p in np.array_split(np.array(run, dtype=object), k)]
        if all(table_chunk_size(p) <= MAX_CHUNK_CHARS for p in parts):
            break
        k += 1
    table_groups += parts
    if k > 1:
        print(f"{run[0]['table_id']}: {len(run)} rows -> {k} balanced chunks of {[len(p) for p in parts]} rows")

for g in table_groups:
    text = g[0]["table_header_text"] + "\n" + "\n".join(x["row_text"] for x in g)
    rows = [x["unit_id"].rsplit("_", 1)[1] for x in g]
    name = f"{g[0]['table_id']}_{rows[0]}" + (f"_{rows[-1]}" if len(g) > 1 else "")
    title = TABLE_SPECS[g[0]["table_id"]]["title"]
    chunk_records.append(make_chunk(g, "table_row", name, 1, text, title=title))

for u in unit_dicts:
    if u["unit_type"] in ("iro_box", "box", "milestone", "figure"):
        pieces = [u["content"]] if u["char_count"] <= MAX_CHUNK_CHARS else split_by_sentences(u["content"])
        for part, piece in enumerate(pieces, start=1):
            chunk_records.append(make_chunk([u], u["unit_type"], u["logical_unit"], part, piece))

order_of = {uid: k for k, uid in enumerate(final_units_df["unit_id"])}
chunk_records.sort(key=lambda r: order_of[r["source_unit_ids"][0]])

print(f"Kept units: {len(unit_dicts)} -> chunks: {len(chunk_records)}")
display(pd.Series([r["unit_type"] for r in chunk_records]).value_counts().rename("chunks"))
print("\nTable chunks:")
display(pd.DataFrame([{"chunk_id": r["chunk_id"], "rows": len(r["source_unit_ids"]), "chars": len(r["text"]),
                       "level": r["sensitivity_level"]} for r in chunk_records if r["unit_type"] == "table_row"]))

# %% [markdown] cell 85
# # Phase 15 — Chunk Validation
#
# Size and ID checks, content preservation of every kept unit, no suppressed unit re-entering, no chunk crossing a
# section/subsection boundary, and **no chunk mixing access levels or departments**.

# %% cell 86
# =========================================================
# 15.1 Size checks
# =========================================================
chunk_sizes = pd.Series([len(r["text"]) for r in chunk_records])
assert (chunk_sizes > 0).all(), "Empty chunk."
assert (chunk_sizes <= MAX_CHUNK_CHARS).all(), "A chunk exceeds MAX_CHUNK_CHARS."
FRAGMENT_MIN_CHARS = 50        # below this a chunk is a fragment (a name, an address line) with no standalone meaning
assert (chunk_sizes >= FRAGMENT_MIN_CHARS).all(), \
    [(r["chunk_id"], r["text"]) for r in chunk_records if len(r["text"]) < FRAGMENT_MIN_CHARS]
chunk_ids = [r["chunk_id"] for r in chunk_records]
assert len(chunk_ids) == len(set(chunk_ids)), "Duplicate chunk_id."

# %% cell 87
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
    pieces = [u["row_text"]] if u["unit_type"] == "table_row" else \
        [s for line in u["content"].split("\n") for s in sentences(line)]
    for piece in pieces:
        assert piece.strip() in joined, f"Content of {uid} not preserved: {piece[:60]!r}"

suppressed_ids = set(suppressed["unit_id"])
assert not any(set(r["source_unit_ids"]) & suppressed_ids for r in chunk_records), "A suppressed unit re-entered."

# %% cell 88
# =========================================================
# 15.3 Provenance + access checks
# =========================================================
for r in chunk_records:
    locs = {location(units_by_id[uid])[:2] for uid in r["source_unit_ids"]} if not r.get("section_block") else \
        {(units_by_id[uid]["section"], units_by_id[uid]["subsection_path"][0]) for uid in r["source_unit_ids"]}
    access = {location(units_by_id[uid])[2:] for uid in r["source_unit_ids"]}
    assert len(locs) == 1, f"{r['chunk_id']} crosses a section/subsection boundary."
    assert len(access) == 1, f"{r['chunk_id']} mixes access levels / departments."
    assert (r["sensitivity_level"], r["department"]) == next(iter(access))
    assert r["section"] and r["title"], f"{r['chunk_id']} lacks section/title."
    if r["unit_type"] == "table_row":
        assert len({units_by_id[uid]["table_id"] for uid in r["source_unit_ids"]}) == 1, f"{r['chunk_id']} mixes tables."

lvl3_chunks = [r for r in chunk_records if r["sensitivity_level"] == 3]
assert {uid for r in lvl3_chunks for uid in r["source_unit_ids"]} == set(FINANCIAL_UNITS), "Level-3 units and chunks differ."

print("✅ Chunk validation passed.")
print("Chunk size:", chunk_sizes.describe()[["count", "min", "50%", "mean", "max"]].round(0).to_dict())
print(f"Below MIN_CHUNK_CHARS: {int((chunk_sizes < MIN_CHUNK_CHARS).sum())} "
      "(complete short statements or one-row tables alone in their subsection; none below FRAGMENT_MIN_CHARS)")
print(f"Level-3 / Finance chunks: {len(lvl3_chunks)} {[r['chunk_id'] for r in lvl3_chunks]}")
display(pd.DataFrame([{"chunk_id": r["chunk_id"], "chars": len(r["text"]), "text": r["text"][:80]}
                      for r in sorted(chunk_records, key=lambda r: len(r["text"]))[:8]]))

# %% [markdown] cell 89
# # Phase 16 — Unified 16-Column Schema (ADR-009)
#
# Identical schema, dtypes and validator as the other notebooks. `parent_chunk` = chapter, `sub_chunk` = subsection
# heading path (list), document metadata from Phase 0 — except `sensitivity_level` and `department`, which come
# **from each chunk** (Phase 9 decision per unit). Audit and dedup metadata stay in their own files.

# %% cell 90
# =========================================================
# 16.1 Schema definition (identical to the other notebooks — ADR-009)
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

# %% cell 91
# =========================================================
# 16.2 Metadata mapping (document metadata + per-chunk access)
# =========================================================
chunk_metadata = {
    "filename": SOURCE_FILE,
    "source": SOURCE_PUBLISHER,
    "real_or_synthetic": REAL_OR_SYNTHETIC,
    "document_type": DOCUMENT_TYPE,
    "version_date": VERSION_DATE,
}

chunks_df = pd.DataFrame([
    {
        "page": r["page"], "unit_type": r["unit_type"], "logical_unit": r["logical_unit"], "chunk_id": r["chunk_id"],
        "parent_chunk": r["section"], "sub_chunk": list(r["subsection_path"]) or None, "title": r["title"],
        "text": r["text"], "char_count": len(r["text"]),
        "department": r["department"], "sensitivity_level": r["sensitivity_level"],
        **chunk_metadata,
    }
    for r in chunk_records
])[list(CHUNK_SCHEMA)].astype(CHUNK_SCHEMA)

# %% cell 92
# =========================================================
# 16.3 Schema validation
# =========================================================
validate_chunk_schema(chunks_df, f"{SOURCE_NAME} chunks")
assert chunks_df["department"].isin(KNOWN_DEPARTMENTS).all()
assert set(zip(chunks_df["sensitivity_level"], chunks_df["department"])) == {(1, "Operations"), (3, "Finance")}
display(chunks_df[["page", "unit_type", "logical_unit", "chunk_id", "parent_chunk", "title", "char_count",
                   "sensitivity_level", "department"]].head(10))
display(chunks_df.groupby(["sensitivity_level", "department"]).size().rename("chunks"))
display(chunks_df[list(chunk_metadata)].drop_duplicates())

# %% [markdown] cell 93
# # Phase 17 — Save + Reload
#
# The Parquet file on disk — not the in-memory frame — is the artifact that must pass validation.

# %% cell 94
# =========================================================
# 17.1 Save Parquet / 17.2 Reload / 17.3 Revalidate
# =========================================================
CHUNKS_PATH = CHUNKS_DIR / f"{SOURCE_NAME}_chunks.parquet"
chunks_df.to_parquet(CHUNKS_PATH, index=False)

reloaded_df = pd.read_parquet(CHUNKS_PATH).astype(CHUNK_SCHEMA)
validate_chunk_schema(reloaded_df, f"{SOURCE_NAME} chunks (reloaded from disk)")

assert len(reloaded_df) == len(chunks_df)
assert reloaded_df["chunk_id"].tolist() == chunks_df["chunk_id"].tolist()
for col in [c for c in CHUNK_SCHEMA if c != "sub_chunk"]:
    assert reloaded_df[col].equals(chunks_df[col]), f"Column {col} changed on disk."
as_list = lambda v: None if v is None or (isinstance(v, float) and np.isnan(v)) else list(v)
assert reloaded_df["sub_chunk"].map(as_list).tolist() == chunks_df["sub_chunk"].map(as_list).tolist()

print(f"✅ Saved and revalidated: {CHUNKS_PATH.name} ({CHUNKS_PATH.stat().st_size:,} bytes, {len(reloaded_df)} chunks)")

# %% [markdown] cell 95
# # Phase 18 — Cross-Source Validation
#
# The new chunks must concatenate cleanly with the four existing chunk files (FBL, LPI Methodology, Suez Notes,
# LPI Connecting to Compete): same columns, same order, same dtypes, no `chunk_id` collision. This source is the
# first with level-3 chunks, so the corpus-level access profile is printed as well.

# %% cell 96
# =========================================================
# 18.1 Compare schemas / 18.2 dtypes / 18.3 chunk_id collisions / 18.4 concatenate
# =========================================================
other_chunk_paths = {
    "FBL": CHUNKS_DIR / "FBL_template_chunks.parquet",
    "LPI_Methodology": CHUNKS_DIR / "LPI_Methodology_chunks.parquet",
    "Suez": CHUNKS_DIR / "suez_notes_chunks.parquet",
    "LPI_Connecting_to_Compete": CHUNKS_DIR / "LPI_Connecting_to_Compete_chunks.parquet",
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
assert len(combined_chunks_df) == 198 + len(reloaded_df), "The existing corpus is expected to hold 198 chunks."

print("===================================")
print("UNIFIED SCHEMA CROSS-SOURCE CHECK: PASSED")
print("===================================")
display(combined_chunks_df.groupby(["filename", "document_type"]).size().rename("chunks"))
display(combined_chunks_df.groupby(["sensitivity_level", "department"]).size().rename("chunks"))
print("Combined rows:", len(combined_chunks_df))

# %% [markdown] cell 97
# # Phase 19 — Whole-PDF Coverage Audit
#
# Proof that nothing was dropped silently. **Every text line of all 85 pages** receives exactly one disposition:
#
# | Disposition | Meaning |
# |---|---|
# | `in_chunks` | the line's text is in the final chunks — verified by containment in the chunks of **its own unit / table / figure** |
# | `metadata` | headings (→ `parent_chunk` / `sub_chunk` / `title`, verified) and printed table column headers (→ column names of the row text) |
# | `merged_subscript` | chemical subscript re-inserted into its host line (Phase 3) |
# | `suppressed_duplicate` | a cell of a `tab_p83a` row suppressed in Phase 11; its canonical `tab_p13` row is in the chunks |
# | `trimmed_duplicate` | the milestone sentence trimmed in Phase 11; its canonical paragraph is in the chunks |
# | `erratum_excluded` | the two table cells (4.3) and the prose sentence (9.2) excluded as source errors, with evidence |
# | `figure_internal` | tick values, category and data labels of the three text charts (described by the figure unit) |
# | `layout_excluded` | navigation bar and page numbers |
# | `page_excluded:<class>` | cover, contents and chapter-divider pages (Phase 2) |
# | `no_text` | punctuation only |
#
# Errata cells and suppressed rows are located **physically** (same row as their printed label), not by text, because
# `-1.5%` also appears legitimately in another row. The line-level result is added to the single cleaned file
# (`cleaned/…_logical_units.json`, key `coverage_audit`).

# %% cell 98
# =========================================================
# 19.1 Lookups: chunk text per unit / table / figure, removed items, physical table rows
# =========================================================

def letters_only(t: str) -> str:
    return re.sub(r"[^0-9a-z]", "", unicodedata.normalize("NFKC", str(t)).replace("­", "").lower())


chunk_corpus = letters_only(" ".join(chunks_df["text"]))
chunk_letters_of_unit: dict[str, str] = {}
for r in chunk_records:
    for uid in r["source_unit_ids"]:
        chunk_letters_of_unit[uid] = chunk_letters_of_unit.get(uid, "") + " " + letters_only(r["text"])
table_chunk_letters = {tid: letters_only(" ".join(r["text"] for r in chunk_records if r["unit_type"] == "table_row"
                                                  and units_by_id[r["source_unit_ids"][0]]["table_id"] == tid))
                       for tid in TABLE_SPECS}
metadata_corpus = letters_only(" ".join(
    [*chunks_df["parent_chunk"].dropna(), *chunks_df["title"].dropna(),
     *[h for path in chunks_df["sub_chunk"].dropna() for h in path], *BLOCK_LABELS]))   # + labels inside section blocks

# items removed on purpose (each with its reason), as letters
REMOVED = {}
for d in trimmed.itertuples():
    for item in d.removed_items:
        REMOVED.setdefault(d.unit_id, []).append(("trimmed_duplicate", letters_only(item),
                                                  f"repeated in canonical {d.canonical_unit_ids}"))
for e in errata_df.itertuples():
    REMOVED.setdefault(e.unit_id, []).append(("erratum_excluded", letters_only(e.removed), f"source erratum (9.2): {e.evidence}"))


def claim(t: str, kept: str, removed: list) -> tuple[str, str] | None:
    """A line is in the chunks, inside a removed item, or split between a kept part and a removed item."""
    if t in kept:
        return "in_chunks", ""
    for kind, item, why in removed:
        if t in item:
            return kind, why
        for k in range(1, len(t)):
            if (t[:k] in kept and item.startswith(t[k:])) or (item.endswith(t[:k]) and t[k:] in kept):
                return kind, f"line partly kept; removed part: {why}"
    return None


# regions of every structured line, and the physical rows of every table
region_of_line = {}
for r in rl[rl["reason"] == "structured_region"].itertuples():
    rg = structured_regions_df[(structured_regions_df["page_number"] == r.page_number)
                               & (structured_regions_df["x0"] - 1 <= r.x0) & (r.x1 <= structured_regions_df["x1"] + 1)
                               & (structured_regions_df["y0"] - 1 <= r.y0) & (r.y1 <= structured_regions_df["y1"] + 1)]
    assert len(rg) == 1, f"p{r.page_number} y{r.y0}: line in {len(rg)} regions"
    region_of_line[(r.page_number, r.block_no, r.line_no)] = (rg["kind"].iloc[0], rg["ref"].iloc[0])

table_lines = rl[[region_of_line.get((p, b, l), ("", ""))[0] == "table"
                  for p, b, l in zip(rl["page_number"], rl["block_no"], rl["line_no"])]].copy()
table_lines["table_id"] = [region_of_line[(p, b, l)][1] for p, b, l in
                           zip(table_lines["page_number"], table_lines["block_no"], table_lines["line_no"])]
table_lines["cell"] = table_lines["text"].map(clean_line)
band_of_table = {t["table_id"]: t["band"] for t in raw_tables}
table_lines["in_header_band"] = [band_of_table[t].y0 - 1 <= y0 and y1 <= band_of_table[t].y1 + 1
                                 for t, y0, y1 in zip(table_lines["table_id"], table_lines["y0"], table_lines["y1"])]


def physical_row(table_id: str, label: str) -> pd.DataFrame:
    """All cells printed on the same row as the (unique) label cell."""
    tl = table_lines[(table_lines["table_id"] == table_id) & ~table_lines["in_header_band"]]
    lab = tl[tl["cell"] == label]
    assert len(lab) == 1, f"{table_id}: label {label!r} printed {len(lab)} times"
    return tl[(tl["y0"] - lab["y0"].iloc[0]).abs() < 2]


line_key = lambda df: set(zip(df["page_number"], df["block_no"], df["line_no"]))

ERRATUM_CELLS = {}          # line key -> evidence
for (tid, label, column), evidence in TABLE_ERRATA.items():
    row = physical_row(tid, label)
    cols = band_of_table[tid].cols
    idx = TABLE_SPECS[tid]["names"].index(column)
    cell = row[[column_of_span(x, cols) == idx for x in row["x0"]]]
    assert len(cell) == 1, f"Erratum cell {tid}/{label}/{column} not found"
    ERRATUM_CELLS[next(iter(line_key(cell)))] = f"{tid} '{label}' / {column} = {cell['cell'].iloc[0]!r}: {evidence}"

SUPPRESSED_CELLS = {}       # line key -> (unit_id, canonical ids)
tu = table_units_df.set_index("unit_id")
for d in suppressed.itertuples():
    row = physical_row(tu.at[d.unit_id, "table_id"], tu.at[d.unit_id, "row_label"])
    row_letters = letters_only(tu.at[d.unit_id, "row_text"])
    for r in row.itertuples():
        assert letters_only(r.cell) in row_letters or (r.page_number, r.block_no, r.line_no) in ERRATUM_CELLS, \
            f"{d.unit_id}: printed cell {r.cell!r} not in the suppressed row"
        SUPPRESSED_CELLS[(r.page_number, r.block_no, r.line_no)] = (d.unit_id, d.canonical_unit_ids)

print(f"Chunk corpus: {len(chunk_corpus):,} letters | erratum cells located: {len(ERRATUM_CELLS)} | "
      f"cells of suppressed rows: {len(SUPPRESSED_CELLS)} | units with removed items: {sorted(REMOVED)}")

# %% cell 99
# =========================================================
# 19.2 Line-level disposition of the WHOLE PDF (all pages, every text line)
# =========================================================
reason_of = {(r.page_number, r.block_no, r.line_no): r.reason for r in rl.itertuples()}
body_uid_of = {(r.page_number, r.block_no, r.line_no): r.line_uid for r in body_lines_df.itertuples()}
body_text_of = body_lines_df.set_index("line_uid")["text"]
line_to_paragraph = {uid: r.paragraph_id for r in paragraphs_df.itertuples() for uid in r.line_uids}
unit_of_region = {"iro_box": "iro_box", "box": "box", "milestone": "milestone", "figure": "figure"}
header_letters = {tid: letters_only(" ".join(spec["header"])) for tid, spec in TABLE_SPECS.items()}
SKIPPED_FIGURES = set(figure_gate_df.loc[figure_gate_df["decision"] == "skip", "figure_id"])


def disposition(r) -> tuple[str, str]:
    key, pclass = (r.page_number, r.block_no, r.line_no), r.page_class
    t = letters_only(r.text_merged if isinstance(r.text_merged, str) else r.text)
    if not letters_only(r.text):
        return "no_text", f"punctuation only: {r.text.strip()!r} (table placeholder dash, unit symbol)"
    if pclass not in RETRIEVAL_CLASSES:
        return f"page_excluded:{pclass}", "non-retrieval page (Phase 2)"
    reason = reason_of[key]
    if reason in ("header", "footer"):
        return "layout_excluded", "navigation bar / page number"
    if reason == "subscript":
        return "merged_subscript", f"re-inserted into its host line: {r.subscript_host}"
    if reason == "heading":
        return ("metadata", "heading -> parent_chunk / sub_chunk / title") if t in metadata_corpus \
            else ("UNACCOUNTED", "heading not in chunk metadata")
    if reason == "structured_region":
        kind, ref = region_of_line[key]
        if kind == "table":
            if key in ERRATUM_CELLS:
                return "erratum_excluded", ERRATUM_CELLS[key]
            if key in SUPPRESSED_CELLS:
                uid, canon = SUPPRESSED_CELLS[key]
                return "suppressed_duplicate", f"{uid} repeats {canon}"
            if band_of_table[ref].y0 - 1 <= r.y0 and r.y1 <= band_of_table[ref].y1 + 1:
                return ("metadata", f"{ref}: printed column header -> column names") if t in header_letters[ref] \
                    else ("UNACCOUNTED", f"{ref} header")
            return ("in_chunks", ref) if t in table_chunk_letters[ref] else ("UNACCOUNTED", ref)
        if kind == "figure":
            if ref in SKIPPED_FIGURES:
                return "UNACCOUNTED", f"{ref}: text inside a skipped graphic"
            kept = chunk_letters_of_unit[ref]
            if len(t) >= 12 and t in kept:
                return "in_chunks", f"{ref} (title / caption / label)"
            return "figure_internal", f"{ref}: tick / category / data label of the chart (described by the figure unit)"
        c = claim(t, chunk_letters_of_unit.get(ref, ""), REMOVED.get(ref, []))
        return (c[0], c[1] or ref) if c else ("UNACCOUNTED", ref)
    if reason == "body":
        uid = body_uid_of.get(key)
        if uid is None:
            return "no_text", "empty after cleaning"
        pid = line_to_paragraph[uid]
        c = claim(letters_only(body_text_of[uid]), chunk_letters_of_unit.get(pid, ""), REMOVED.get(pid, []))
        return (c[0], c[1] or pid) if c else ("UNACCOUNTED", pid)
    return "UNACCOUNTED", str(reason)


disp = lines_df.apply(disposition, axis=1)
coverage_df = lines_df[["page_number", "block_no", "line_no", "y0", "font", "text"]].assign(
    disposition=disp.str[0], detail=disp.str[1], chars=lines_df["text"].str.len())
print(f"Lines in PDF: {len(coverage_df)} on {coverage_df['page_number'].nunique()} pages")
print(coverage_df["disposition"].value_counts().to_dict())

# %% cell 100
# =========================================================
# 19.3 Coverage summary + assertions + coverage_audit in the cleaned file
# =========================================================
unaccounted = coverage_df[coverage_df["disposition"] == "UNACCOUNTED"]
print(f"UNACCOUNTED lines: {len(unaccounted)}")
if len(unaccounted):
    with pd.option_context("display.max_rows", None, "display.max_colwidth", 80):
        display(unaccounted[["page_number", "y0", "text", "detail"]])
assert unaccounted.empty, "Some PDF lines are not accounted for."
assert len(coverage_df) == len(lines_df)
TEXTLESS_PAGES = sorted(set(pages_df["page_number"]) - set(coverage_df["page_number"]))
assert TEXTLESS_PAGES == [1, 85], TEXTLESS_PAGES          # front and back cover: image only, no text layer

# every removed item was removed on purpose and its canonical copy / evidence exists
chunked_units = {uid for r in chunk_records for uid in r["source_unit_ids"]}
for d in pd.concat([suppressed, trimmed]).itertuples():
    assert set(d.canonical_unit_ids) <= chunked_units, f"{d.unit_id}: canonical copy missing from the chunks."
for d in suppressed.itertuples():
    u = units_df.set_index("unit_id").loc[d.unit_id].to_dict()
    assert sorted(items_of(u)) == sorted(d.removed_items), f"{d.unit_id}: not every item was matched."
assert (coverage_df["disposition"] == "erratum_excluded").sum() >= len(TABLE_ERRATA) + len(PROSE_ERRATA)
assert set(coverage_df.loc[coverage_df["disposition"] == "suppressed_duplicate", "detail"].str.split(" ").str[0]) \
    == set(suppressed["unit_id"])

# the one kept caption of a raster figure (fig_p58) is in its chunk; no text in a skipped graphic
fig_lines = coverage_df[coverage_df["detail"].str.startswith("fig_p58")]
assert (fig_lines["disposition"] == "in_chunks").all() and len(fig_lines) == 1
# every line of the level-3 units is in a level-3 chunk (access control did not lose text)
lvl3_letters = letters_only(" ".join(r["text"] for r in chunk_records if r["sensitivity_level"] == 3))
for pid in ["P030", "P031", "P032", "P033"]:
    for uid in paragraphs_df.set_index("paragraph_id").at[pid, "line_uids"]:
        assert letters_only(body_text_of[uid]) in lvl3_letters, f"{pid}: line {uid} not in a level-3 chunk."

summary = coverage_df.groupby("disposition").agg(lines=("text", "size"), chars=("chars", "sum"))
summary["share_chars"] = (summary["chars"] / summary["chars"].sum()).round(3)
print("\nWhere every line of the PDF went:")
display(summary.sort_values("chars", ascending=False))
print("\nRemoved on purpose (every one with its reason):")
with pd.option_context("display.max_colwidth", 120, "display.max_rows", None):
    display(coverage_df[coverage_df["disposition"].isin(["erratum_excluded", "trimmed_duplicate", "suppressed_duplicate"])]
            [["page_number", "disposition", "text", "detail"]].assign(detail=lambda d: d["detail"].str[:90]))
print("\nPer page (lines):")
with pd.option_context("display.max_rows", None, "display.max_columns", None):
    display(coverage_df.pivot_table(index="page_number", columns="disposition", values="text",
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
assert sorted(p.name for p in CLEANED_DIR.glob(f"{SOURCE_NAME}_*")) == [LOGICAL_UNITS_PATH.name]
print(f"\n✅ Whole-PDF coverage audit passed: {len(coverage_df)} lines, 0 unaccounted. Added to: {LOGICAL_UNITS_PATH.name}")

# %% cell 101
# =========================================================
# Final Checkpoint
# =========================================================
print("=" * 78)
print("PORT OF ROTTERDAM ANNUAL REPORT 2025 (HIGHLIGHTS) — INGESTION PIPELINE: FINAL CHECKPOINT")
print("=" * 78)
print(f"Source            : {SOURCE_FILE} | {len(pages_df)} pages | sha256 {SOURCE_SHA256[:16]}…")
print(f"Page classes      : {page_class_df['page_class'].value_counts().to_dict()}")
print(f"Retrieval pages   : {len(RETRIEVAL_PAGES)} (p.{RETRIEVAL_PAGES[0]}–{RETRIEVAL_PAGES[-1]} without dividers)")
print(f"Headings          : {len(section_map)} {section_map['role'].value_counts().to_dict()}")
print(f"Subscripts        : {int(lines_df['is_subscript'].sum())} re-inserted (CO2, NO2, PM10, PM2.5) | footnotes: none")
print(f"Tables            : {len(table_meta_df)} -> {len(table_units_df)} rows | table errata {len(TABLE_ERRATA)}, "
      f"prose errata {len(PROSE_ERRATA)}")
print(f"Boxes / cards     : {len(iro_units_df)} IRO boxes, {len(box_units_df)} text boxes, {len(milestone_units_df)} milestone cards")
print(f"Graphics          : gate {figure_gate_df['decision'].value_counts().to_dict()} | "
      f"images {images_df['kind'].value_counts().to_dict()}")
print(f"Body              : {len(body_lines_df)} lines ({len(bullets_df)} vector bullets) -> {len(paragraphs_df)} paragraphs")
print(f"Logical units     : {len(units_df)} -> after dedup {len(final_units_df)} "
      f"(suppressed {len(suppressed)}, trimmed {len(trimmed)}, kept contextual {len(REVIEWED_KEEP_CONTEXTUAL)}, "
      f"manual review pending {int((decisions_df['action'] == 'manual_review').sum())})")
print(f"Access control    : {int(access_df['access_code'].ne('no_financial_content').sum())} finance candidates reviewed -> "
      f"{units_df.groupby(['sensitivity_level', 'department']).size().to_dict()} units")
print(f"Chunks            : {len(reloaded_df)} {reloaded_df['unit_type'].value_counts().to_dict()} | "
      f"chars min/median/max = {reloaded_df['char_count'].min()}/{int(reloaded_df['char_count'].median())}/"
      f"{reloaded_df['char_count'].max()}")
print(f"Chunk access      : {reloaded_df.groupby(['sensitivity_level', 'department']).size().to_dict()}")
print(f"Cross-source      : {len(combined_chunks_df)} chunks in the unified corpus, chunk_id unique")
print(f"Whole-PDF coverage: {len(coverage_df)} lines, "
      f"{int((coverage_df['disposition'] == 'UNACCOUNTED').sum())} unaccounted")

assert final_units_df["flag"].isna().all(), "No unit may remain flagged."
assert "manual_review" not in set(decisions_df["action"])
assert (coverage_df["disposition"] != "UNACCOUNTED").all()
print("\nPending manual review :", REVIEWED_MANUAL_REVIEW or "none")
print("Flagged units         : none")
print("\nArtifacts:")
for p in (EXTRACTED_PATH, LOGICAL_UNITS_PATH, CHUNKS_PATH):
    print(f"  {p.relative_to(PROJECT_ROOT)}  ({p.stat().st_size:,} bytes)")

# %% [markdown] cell 102
# Final Checkpoint: see pipelines/checkpoints/rag/HbR_Annual_report_2025_chunking.md
