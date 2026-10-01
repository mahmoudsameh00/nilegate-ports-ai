"""Phase 0 — Setup & Configuration

Converted from Notebooks/rag/IMO_MSC-MEPC_3_Circ_4_Rev_1_chunking.ipynb (2026-10-01) by tools/nb_to_script.py: same cells, same order; `# %% cell N` = notebook cell N.
Run from the project root: uv run python tools/run.py pipelines/scripts/rag/IMO_MSC-MEPC_3_Circ_4_Rev_1_chunking.py

Reads:   Data/raw/unstructured/MSC-MEPC_3-Circ_4-Rev_1.pdf
Writes:  Data/processed/rag/extracted|cleaned|chunks/ (the IMO circular files, incl. the field catalogue); review aids in Notebooks/_scratch/ (git-ignored)
Re-run:  safe: rewrites the same three artifacts
Final Checkpoint (what was done, problems, fixes): pipelines/checkpoints/rag/IMO_MSC-MEPC_3_Circ_4_Rev_1_chunking.md
"""
from IPython.display import display  # outside Jupyter it prints the value (added by the conversion)

# %% [markdown] cell 0
# # Phase 0 — Setup & Configuration
#
# This phase initializes the environment and defines the source and pipeline configuration for the
# **IMO circular MSC-MEPC.3/Circ.4/Rev.1** — *Casualty-related matters. Reports on marine casualties and incidents:
# Revised harmonized reporting procedures* (18 November 2014, `MSC-MEPC_3-Circ_4-Rev_1.pdf`, 31 A4 portrait pages).
#
# The document is a **reporting form**, not prose: a 10-paragraph circular (what must be reported, when and how),
# then an annex with the field tables of Appendices 1–3, the conditional supplementary sections of Appendix 4 and
# the 30 field-value option tables of Appendix 5. Its RAG value is (a) *what must be reported about a marine
# casualty and when* and (b) *what each field means and which values it may take*. The field list is also the
# planned schema for synthetic incidents, so the extracted file keeps a machine-readable **field catalogue**
# (a file only — no database change).
#
# The phase establishes:
#
# - Required Python libraries and **one PDF access helper** (`page_dict`) used by every later phase, so every
#   phase sees exactly the same text blocks
# - Project and output directories
# - Source/document metadata. Access control: this is an external, public document → **level 1 / Operations for
#   every unit** (`docs/rbac_mapping.md` §4); the value is still asserted per unit (Phase 9) and per chunk (Phase 15)
# - Pipeline configuration and the source file fingerprint
#
# Plan: `docs/plans/MSC-MEPC_3-Circ_4-Rev_1_chunking_plan.md` (§5 decisions, §6 implementation log).

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

PDF_RELATIVE_PATH = Path("Data/raw/unstructured/MSC-MEPC_3-Circ_4-Rev_1.pdf")

search_roots = [Path.cwd(), *Path.cwd().parents]
candidates = [root / PDF_RELATIVE_PATH for root in search_roots]
PDF_PATH = next((path for path in candidates if path.exists()), None)

if PDF_PATH is None:
    raise FileNotFoundError(
        "IMO circular PDF was not found.\n\nLooked in:\n"
        + "\n".join(f"  {path}" for path in candidates)
    )

print("PDF found successfully.")
print("PDF path :", PDF_PATH)

# %% cell 3
# =========================================================
# 0.3 Open the source PDF + PDF access helpers
# =========================================================
# Every phase reads text through page_dict(), so block/line indexes are identical everywhere.
# TEXT_FLAGS = the default "dict" flags WITHOUT image bytes (images are inventoried separately in Phase 1).

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
print("Image blocks in page_dict(1):", sum(b.get("type") == 1 for b in page_dict(1)["blocks"]))

# %% cell 4
# =========================================================
# 0.4 Inspect PDF metadata
# =========================================================
# The embedded metadata comes from the Word template ("Session", author = the typist) and is NOT the
# document title; the title, symbol and date are read from page 1 (Phase 3) and fixed in 0.6.

pdf_metadata = doc.metadata

print("PDF metadata:")
for key, value in pdf_metadata.items():
    print(f"{key:12}: {value}")
print("Outline (TOC) entries:", len(doc.get_toc()))

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

SOURCE_NAME = "IMO_MSC-MEPC_3_Circ_4_Rev_1"
SOURCE_FILE = PDF_PATH.name
SOURCE_PUBLISHER = "International Maritime Organization (IMO)"

DOCUMENT_SYMBOL = "MSC-MEPC.3/Circ.4/Rev.1"
DOCUMENT_TYPE = "imo_casualty_reporting_circular"
REAL_OR_SYNTHETIC = "real"
VERSION_DATE = "2014-11-18"            # printed under the symbol on p.1 ("18 November 2014"), asserted in Phase 3

# External, publicly published source -> level 1 for everyone, owner = Operations (docs/rbac_mapping.md §4).
DOCUMENT_ACCESS = {"sensitivity_level": 1, "department": "Operations"}
KNOWN_DEPARTMENTS = {"Operations", "Customs", "Finance", "HR", "IT"}   # rows of the departments table

SOURCE_DESCRIPTION = ("IMO MSC-MEPC.3/Circ.4/Rev.1 — Casualty-related matters. Reports on marine casualties "
                      "and incidents: revised harmonized reporting procedures (18 November 2014)")

MIN_CHUNK_CHARS = 300
MAX_CHUNK_CHARS = 2000
FRAGMENT_MIN_CHARS = 50                # below this a chunk is a fragment with no standalone meaning
CHUNK_PREFIX = "imo_mci"

source_metadata = {
    "source_name": SOURCE_NAME,
    "source_file": SOURCE_FILE,
    "publisher": SOURCE_PUBLISHER,
    "document_symbol": DOCUMENT_SYMBOL,
    "document_type": DOCUMENT_TYPE,
    "real_or_synthetic": REAL_OR_SYNTHETIC,
    "version_date": VERSION_DATE,
    "access_policy": "document_level_asserted_per_unit",
    "access": DOCUMENT_ACCESS,
    "description": SOURCE_DESCRIPTION,
}

print("Source configuration:")
for key, value in source_metadata.items():
    print(f"{key:20}: {value}")

print("\nChunk configuration:")
print("MIN_CHUNK_CHARS    :", MIN_CHUNK_CHARS)
print("MAX_CHUNK_CHARS    :", MAX_CHUNK_CHARS)
print("FRAGMENT_MIN_CHARS :", FRAGMENT_MIN_CHARS)
print("CHUNK_PREFIX       :", CHUNK_PREFIX)

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
assert len(doc) == 31, f"Expected 31 pages (reconnaissance), found {len(doc)}."

assert SOURCE_NAME and SOURCE_FILE == PDF_PATH.name
assert DOCUMENT_TYPE == "imo_casualty_reporting_circular"
assert REAL_OR_SYNTHETIC == "real"
assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", VERSION_DATE)

assert DOCUMENT_ACCESS == {"sensitivity_level": 1, "department": "Operations"}, "rbac_mapping §4: IMO = level 1 / Operations"
assert DOCUMENT_ACCESS["department"] in KNOWN_DEPARTMENTS, "department must be a row of the departments table"

assert 0 < FRAGMENT_MIN_CHARS < MIN_CHUNK_CHARS < MAX_CHUNK_CHARS
assert len(SOURCE_SHA256) == 64 and SOURCE_FILE_SIZE > 0
assert not any(b.get("type") == 1 for p in (1, 10) for b in page_dict(p)["blocks"]), \
    "page_dict must not contain image blocks."

print("✅ Phase 0 validation passed.")
print("Pages :", len(doc))
print("Source:", SOURCE_NAME)
print("SHA256:", SOURCE_SHA256)

# %% [markdown] cell 9
# # Phase 1 — Page Inventory
#
# This phase creates a raw page-level inventory of the source PDF, before any classification, structural parsing,
# table extraction, cleaning, deduplication or chunking.
#
# For each physical page the inventory records character, word and line counts, text blocks, **image placements**,
# **vector drawings** (here: the cell borders of the annex tables, drawn as thin filled rectangles, and the damage
# diagram), links, page size and the raw text.
#
# Reconnaissance expectations (checked here, decided in Phase 2): A4 portrait single column; images only on p.1
# (IMO letterhead logo, "IMO Conventions" badge) and p.10 (damage diagram); p.4 has no text at all.
#
# **1.6 is a review aid**: it exports the raw PyMuPDF layout of all pages (spans, words, drawings, image placements)
# to `Notebooks/_scratch/state/` (git-ignored) so the layout can be inspected outside the project environment.
# The export is never read back by this notebook.

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
# 1.4 Flag unusual pages (no text / very little text / images)
# =========================================================
# Running header ("MSC-MEPC.3/Circ.4/Rev.1" + page label) and footer (file path) give every text page ~6 words.

special_pages_df = pages_df[
    (pages_df["word_count"] < 60)
    | (pages_df["image_placements"] > 0)
].copy()

with pd.option_context("display.max_rows", None):
    display(special_pages_df[["page_number", "word_count", "text_block_count",
                              "image_count", "image_placements", "drawing_count"]])

# %% cell 14
# =========================================================
# 1.5 Raw text inspection of selected pages
# =========================================================
# p.1 letterhead + title, p.3 list of appendices/tables, p.5 first field table, p.10 damage diagram,
# p.14 Direct Natural Resources Damages table, p.17 two-level option table, p.20 three-level table 12.

inspection_pages = [1, 3, 4, 5, 10, 14, 17, 20, 31]

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
# (spans, words, fonts, bboxes, image placements, drawing paths) be inspected outside this
# environment. Image bytes are not exported.

STATE_DIR = SCRATCH_DIR / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)


def _r(values, nd=2):
    return [round(float(v), nd) for v in values]


def _clean_span(s: dict) -> dict:
    return {"text": s["text"], "font": s["font"], "size": round(s["size"], 2), "flags": s["flags"],
            "color": s["color"], "bbox": _r(s["bbox"]), "origin": _r(s["origin"])}


def _item(it) -> list:
    out = [it[0]]
    for v in it[1:]:
        if hasattr(v, "x0"):                   # Rect
            out.append(["rect", *_r((v.x0, v.y0, v.x1, v.y1))])
        elif hasattr(v, "ul"):                 # Quad
            out.append(["quad", *[_r((q.x, q.y)) for q in (v.ul, v.ur, v.ll, v.lr)]])
        elif hasattr(v, "x"):                  # Point
            out.append(["point", *_r((v.x, v.y))])
        else:
            out.append(v)
    return out


layout_export = {"source": {"file": SOURCE_FILE, "sha256": SOURCE_SHA256, "pymupdf": pymupdf.__version__},
                 "metadata": doc.metadata, "toc": doc.get_toc(simple=True), "pages": []}

for p in range(1, len(doc) + 1):
    page = doc[p - 1]
    d = page_dict(p)
    blocks = []
    for b in d["blocks"]:
        blocks.append({"number": b.get("number"), "type": b.get("type"), "bbox": _r(b["bbox"]),
                       "lines": [{"bbox": _r(l["bbox"]), "wmode": l["wmode"], "dir": _r(l["dir"], 3),
                                  "spans": [_clean_span(s) for s in l["spans"]]} for l in b.get("lines", [])]})
    drawings = [{"rect": _r(dr["rect"]), "fill": dr.get("fill"), "color": dr.get("color"),
                 "width": dr.get("width"), "type": dr.get("type"), "closePath": dr.get("closePath"),
                 "fill_opacity": dr.get("fill_opacity"), "stroke_opacity": dr.get("stroke_opacity"),
                 "items": [_item(it) for it in dr.get("items", [])]}
                for dr in page.get_drawings()]
    layout_export["pages"].append({
        "page_number": p, "rect": _r(page.rect), "text": page.get_text("text"),
        "words": [[*_r(w[:4]), w[4], *w[5:8]] for w in page.get_text("words")],
        "dict": {"width": d["width"], "height": d["height"], "blocks": blocks},
        "image_info": [{"number": i.get("number"), "bbox": _r(i["bbox"]), "width": i["width"],
                        "height": i["height"], "xref": i.get("xref")} for i in page.get_image_info(xrefs=True)],
        "images_full": [[img[0], img[1], img[2], img[3], img[7]] for img in page.get_images(full=True)],
        "links": [{"kind": l.get("kind"), "from": _r(l["from"]), "uri": l.get("uri")} for l in page.get_links()],
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
assert (pages_df["page_width"] < pages_df["page_height"]).all(), "Expected a portrait document."

# ---- reviewed snapshot (2026-09-26) ----
assert pages_df.loc[pages_df["word_count"] == 0, "page_number"].tolist() == [4], "Only p.4 is expected without text."
assert pages_df.loc[pages_df["image_placements"] > 0, "page_number"].tolist() == [1, 10], "Images expected on p.1 and p.10 only."

print("✅ Phase 1 validation passed.")
print("Pages                 :", len(pages_df))
print("Pages without text    :", pages_df.loc[pages_df["word_count"] == 0, "page_number"].tolist())
print("Pages with images     :", pages_df.loc[pages_df["image_placements"] > 0, "page_number"].tolist())
print("Drawings per page     :", pages_df.set_index("page_number")["drawing_count"].to_dict())

# %% [markdown] cell 17
# # Phase 2 — Page Classification
#
# Each page receives a class label and a human-readable reason, from observed signals (2.1), never from hard-coded
# page numbers; a reviewed snapshot (2.3) guards the result.
#
# Layout facts that drive the rules:
#
# - Every text page carries a **running header**: the symbol `MSC-MEPC.3/Circ.4/Rev.1` and a page label —
#   `Page N` in the circular, `Annex, page N` in the annex (p.1 has the IMO letterhead instead).
# - The annex is divided by centred bold headings `APPENDIX 1` … `APPENDIX 5`; a page belongs to the appendix
#   in force at its first body line (an appendix always starts at the top of a page here).
# - Reconnaissance correction: the circular text ends on p.3 and **p.4 is blank** (no text layer at all).
#
# Classes (all text classes are retrieval classes; `blank` has nothing to retrieve):
# `circular` · `annex_fields` (Appendices 1–3: field tables) · `annex_supplementary` (Appendix 4) ·
# `annex_option_tables` (Appendix 5) · `blank`.

# %% cell 18
# =========================================================
# 2.1 Page signals (inspection only — no decisions yet)
# =========================================================
# Signals come from the same page_dict() spans every later phase uses.

HEADER_MAX_Y1 = 70.0                   # symbol + page label sit above y = 70pt on every page
PAGE_LABEL_RE = re.compile(r"^(?:Annex, page|Page)\s+(\d+)$")
APPENDIX_RE = re.compile(r"^APPENDIX\s+(\d)$")


def page_lines(p: int):
    """(line, joined text) for every non-blank line of page p."""
    for b in page_dict(p)["blocks"]:
        for l in b["lines"]:
            t = "".join(s["text"] for s in l["spans"]).strip()
            if t:
                yield l, t


signal_records = []
for p in range(1, len(doc) + 1):
    lines = list(page_lines(p))
    header = [t for l, t in lines if l["bbox"][3] <= HEADER_MAX_Y1]
    label = next((t for t in header if PAGE_LABEL_RE.match(t)), None)
    appendices = [int(APPENDIX_RE.match(t).group(1)) for l, t in lines if APPENDIX_RE.match(t)]
    signal_records.append({
        "page_number": p,
        "word_count": int(pages_df.loc[p - 1, "word_count"]),
        "header_symbol": DOCUMENT_SYMBOL in header,
        "page_label": label,
        "in_annex": bool(label and label.startswith("Annex")),
        "printed_number": int(PAGE_LABEL_RE.match(label).group(1)) if label else None,
        "appendix_headings": appendices,
        "letterhead": any("ALBERT EMBANKMENT" in t for l, t in lines),
        "first_lines": " | ".join(t for l, t in lines if l["bbox"][3] > HEADER_MAX_Y1)[:110],
    })

signals_df = pd.DataFrame(signal_records)

# appendix in force = last APPENDIX heading on this or an earlier page
current, in_force = None, []
for heads in signals_df["appendix_headings"]:
    current = heads[0] if heads else current
    in_force.append(current)
signals_df["appendix"] = pd.array(in_force, dtype="Int64")

with pd.option_context("display.max_rows", None, "display.max_colwidth", 110):
    display(signals_df)

# %% cell 19
# =========================================================
# 2.2 Page classification rules
# =========================================================
# Rule order: no text -> blank; letterhead or "Page N" label -> circular; annex label -> class by appendix.

RETRIEVAL_CLASSES = {"circular", "annex_fields", "annex_supplementary", "annex_option_tables"}
ALLOWED_CLASSES = RETRIEVAL_CLASSES | {"blank"}
APPENDIX_CLASS = {1: "annex_fields", 2: "annex_fields", 3: "annex_fields", 4: "annex_supplementary",
                  5: "annex_option_tables"}


def classify_page(sig) -> tuple[str, str]:
    if sig.word_count == 0:
        return "blank", "No text layer (empty page after the circular)"
    if sig.letterhead or (sig.page_label and not sig.in_annex):
        return "circular", f"Circular text ({'IMO letterhead' if sig.letterhead else sig.page_label})"
    if sig.in_annex and pd.notna(sig.appendix):
        return APPENDIX_CLASS[int(sig.appendix)], f"{sig.page_label}, appendix {sig.appendix} in force"
    return "unclassified", "Matched no rule"


rows = [classify_page(sig) for sig in signals_df.itertuples()]
page_class_df = signals_df[["page_number", "word_count", "page_label", "appendix"]].copy()
page_class_df[["page_class", "reason"]] = pd.DataFrame(rows, index=signals_df.index)
page_class_df["keep_for_retrieval"] = page_class_df["page_class"].isin(RETRIEVAL_CLASSES)

with pd.option_context("display.max_rows", None, "display.max_colwidth", 90):
    display(page_class_df)

print("\nClass counts:")
print(page_class_df["page_class"].value_counts())

# %% cell 20
# =========================================================
# 2.3 Phase 2 validation
# =========================================================

# ---- completeness ----
assert len(page_class_df) == len(doc), "Not every page was classified."
assert page_class_df["page_class"].isin(ALLOWED_CLASSES).all(), "Unknown / unclassified page found."
assert page_class_df["reason"].str.strip().ne("").all(), "Every page needs a reason."

# ---- structural rules ----
text_pages = signals_df[signals_df["word_count"] > 0]
assert text_pages.loc[~text_pages["letterhead"], "header_symbol"].all(), "Every page after p.1 must carry the running symbol."
assert signals_df["letterhead"].sum() == 1 and signals_df.loc[0, "letterhead"], "Only p.1 carries the IMO letterhead."
assert text_pages.loc[~text_pages["letterhead"], "page_label"].notna().all(), "Every page after p.1 needs a page label."
annex = signals_df[signals_df["in_annex"]]
assert annex["printed_number"].tolist() == list(range(1, len(annex) + 1)), "Annex page labels must run 1..N."
assert (annex["page_number"] - annex["printed_number"]).nunique() == 1
ANNEX_OFFSET = int((annex["page_number"] - annex["printed_number"]).iloc[0])     # physical = printed + offset
heads = [a for h in signals_df["appendix_headings"] for a in h]
assert heads == [1, 2, 3, 4, 5], f"APPENDIX headings out of order: {heads}"
assert signals_df["appendix"].dropna().is_monotonic_increasing

# ---- reviewed snapshot (regression guard) — reviewed 2026-09-26 ----
REVIEWED_CLASSES = {**{p: "circular" for p in (1, 2, 3)}, 4: "blank",
                    **{p: "annex_fields" for p in range(5, 10)},
                    **{p: "annex_supplementary" for p in range(10, 16)},
                    **{p: "annex_option_tables" for p in range(16, 32)}}
actual = dict(zip(page_class_df["page_number"], page_class_df["page_class"]))
mismatches = {p: (REVIEWED_CLASSES[p], actual[p]) for p in actual if REVIEWED_CLASSES[p] != actual[p]}
assert not mismatches, f"Classification drifted from reviewed snapshot: {mismatches}"
assert ANNEX_OFFSET == 4

RETRIEVAL_PAGES = page_class_df.loc[page_class_df["keep_for_retrieval"], "page_number"].tolist()

print("✅ Phase 2 validation passed.")
print("Retrieval pages :", len(RETRIEVAL_PAGES), "| excluded:",
      page_class_df.loc[~page_class_df["keep_for_retrieval"], ["page_number", "page_class"]].values.tolist())
print("Annex offset    : physical page = 'Annex, page N' +", ANNEX_OFFSET)
print("Pages per class :", page_class_df.groupby("page_class", sort=False)["page_number"].agg(lambda s: f"{s.min()}–{s.max()}").to_dict())

# %% [markdown] cell 21
# # Phase 3 — Structure Reconnaissance
#
# Goal: one **line table** and one **row table** that every later phase uses, the page zones, and a confirmed
# `section_map` of the bold headings, cross-checked against the document's own list of appendices and tables (p.3).
# No content is extracted in this phase.
#
# Layout facts measured here (Word 2013 export, A4 portrait):
#
# - Body text Arial 11.04pt; footnotes and the letterhead Arial 9pt; small caps are written as a large first letter
#   plus 9pt capitals (`A` + `PPENDIX` → `APPENDIX`), so a line's text is the **concatenation of its spans**.
# - **One printed row = several PyMuPDF lines.** A paragraph number, a field number, a description and a value
#   type sit on the same baseline but are separate lines; a justified line of p.14 is even split word by word.
#   Rows are therefore rebuilt by **baseline** (3.4), and a row's text is its segments in x order.
# - **Superscript** spans (flag bit 0, 6.96pt) are footnote markers (`*`, `1`, `2`, `3`) and are removed from the
#   text and kept as markers (3.3); **subscripts** (`L`+`pp`, `l`+`1`) are inline spans and stay in their words.
# - Zones: running header (y < 70pt), footer = the Word file path, IMO letterhead (p.1, above the symbol),
#   footnote area (9pt lines below y = 600pt), the p.3 list of appendices/tables, and the damage diagram
#   labels (Times New Roman, p.10).
# - Heading roles are carried by **bold** rows: the p.1 title block, `LIST OF APPENDICES`, `ANNEX` and the annex
#   title, `APPENDIX N` + its title, the conditions of the Appendix 4 sections (`N If …`), the Appendix 4 table
#   title, and `Table N` + title in Appendix 5. The column headers of the first field table are bold too.

# %% cell 22
# =========================================================
# 3.1 Line table: one row per non-blank PyMuPDF line (superscripts split off as markers)
# =========================================================
# Lines whose spans are all blank are dropped (they carry no text). The dominant span (longest text) gives
# the line's font/size/baseline. A span is a superscript when PyMuPDF sets flag bit 0 (superscript) and it is
# smaller than body text: it is removed from `text` and kept in `markers` (footnote references, Phase 5).

BODY_SIZE = 11.04
FOOTER_TEXT = r"I:\CIRC\MSC-MEPC\3\4-Rev-1.doc"


def is_bold_span(s: dict) -> bool:
    return bool(s["flags"] & 16) or "Bold" in s["font"]


def is_superscript(s: dict) -> bool:
    return bool(s["flags"] & 1) and s["size"] < 0.8 * BODY_SIZE


# Words (get_text("words")) carry the same block/line numbers as page_dict(); they are kept per line so that
# a line that PyMuPDF merged across a table column rule can be split again (4.1).
line_words: dict[tuple[int, int, int], list[tuple[float, float, str]]] = {}
for p in range(1, len(doc) + 1):
    for w in doc[p - 1].get_text("words"):
        line_words.setdefault((p, w[5], w[6]), []).append((round(w[0], 1), round(w[2], 1), w[4]))

line_records = []
for p in range(1, len(doc) + 1):
    for block_no, block in enumerate(page_dict(p)["blocks"]):
        assert block.get("number", block_no) == block_no
        for line_no, line in enumerate(block["lines"]):
            spans = [s for s in line["spans"] if s["text"].strip()]
            if not spans:
                continue
            main = max(spans, key=lambda s: len(s["text"].strip()))
            x0, y0, x1, y1 = line["bbox"]
            line_records.append({
                "page_number": p, "block_no": block_no, "line_no": line_no,
                "x0": round(x0, 1), "y0": round(y0, 1), "x1": round(x1, 1), "y1": round(y1, 1),
                "baseline": round(main["origin"][1], 1),
                "raw_text": "".join(s["text"] for s in line["spans"]).strip(),
                "text": "".join(s["text"] for s in line["spans"] if not is_superscript(s)).strip(),
                "markers": [s["text"].strip() for s in line["spans"] if is_superscript(s) and s["text"].strip()],
                "size": round(main["size"], 2), "font": main["font"],
                "all_bold": all(is_bold_span(s) for s in spans if not is_superscript(s)),
                "n_spans": len(spans),
            })

lines_df = pd.DataFrame(line_records)
# words and lines must agree exactly (same block/line numbering, same text)
for r in lines_df.itertuples():
    assert " ".join(w[2] for w in line_words[(r.page_number, r.block_no, r.line_no)]) == " ".join(r.raw_text.split()), \
        f"p{r.page_number}: words and line text differ: {r.raw_text!r}"
lines_df["n_chars"] = lines_df["text"].str.len()
lines_df["page_class"] = lines_df["page_number"].map(page_class_df.set_index("page_number")["page_class"])

font_profile = (lines_df.groupby(["font", "size"])
                .agg(lines=("text", "size"), chars=("n_chars", "sum"), pages=("page_number", "nunique"),
                     example=("text", "first"))
                .sort_values("chars", ascending=False))
assert font_profile.index[0] == ("Arial", BODY_SIZE), "Body text is expected in Arial 11.04pt."

print("Lines extracted :", len(lines_df), "on", lines_df["page_number"].nunique(), "pages")
print("Lines with superscript markers:", int(lines_df["markers"].map(len).gt(0).sum()))
with pd.option_context("display.max_colwidth", 60, "display.max_rows", 60):
    display(font_profile)

# %% cell 23
# =========================================================
# 3.2 Zones: running header, footer, letterhead, footnote area, figure labels
# =========================================================
FOOTNOTE_MIN_Y0 = 600.0            # footnotes sit at the bottom of p.1, p.6 and p.8
FOOTNOTE_MAX_SIZE = 9.5

symbol_line = lines_df[(lines_df["page_number"] == 1) & (lines_df["text"] == DOCUMENT_SYMBOL)]
assert len(symbol_line) == 1, "The symbol is printed once on p.1."
LETTERHEAD_MAX_Y1 = float(symbol_line["y0"].iloc[0])


def zone_of(r) -> str:
    if r.y1 <= HEADER_MAX_Y1:
        return "header"
    if r.text == FOOTER_TEXT:
        return "footer"
    if r.font.startswith("Times"):
        return "figure_label"
    if r.page_number == 1 and r.y1 <= LETTERHEAD_MAX_Y1:
        return "letterhead"
    if r.size <= FOOTNOTE_MAX_SIZE and r.y0 >= FOOTNOTE_MIN_Y0:
        return "footnote"
    return "body"


lines_df["zone"] = [zone_of(r) for r in lines_df.itertuples()]

header = lines_df[lines_df["zone"] == "header"]
print("Zones:", lines_df["zone"].value_counts().to_dict())
print("Header texts:", sorted(set(header["text"]) - {DOCUMENT_SYMBOL})[:6], "…")
print("Letterhead  :", lines_df.loc[lines_df["zone"] == "letterhead", "text"].tolist())
print("Footnote lines per page:", lines_df[lines_df["zone"] == "footnote"].groupby("page_number").size().to_dict())
print("Figure-label lines per page:", lines_df[lines_df["zone"] == "figure_label"].groupby("page_number").size().to_dict())

# every header line is the symbol or a page label; one footer per text page
assert header["text"].map(lambda t: t == DOCUMENT_SYMBOL or bool(PAGE_LABEL_RE.match(t))).all()
footer = lines_df[lines_df["zone"] == "footer"]
assert sorted(footer["page_number"]) == [p for p in range(1, len(doc) + 1) if p != 4], "One footer per text page."
assert set(lines_df.loc[lines_df["zone"] == "figure_label", "page_number"]) == {10}
assert set(lines_df.loc[lines_df["zone"] == "footnote", "page_number"]) == {1, 6, 8}

# %% cell 24
# =========================================================
# 3.3 Superscript markers and inline subscripts
# =========================================================
# Superscripts were split off in 3.1. Subscripts are inline spans (smaller, baseline lowered) that belong to
# their word: "L" + "pp" -> "Lpp", "damage l" + "1" -> "damage l1". They are listed here for the record only;
# the line text already contains them in the right place.

marker_df = lines_df[lines_df["markers"].map(len) > 0][["page_number", "zone", "baseline", "raw_text", "text", "markers"]]
print("Superscript markers:")
display(marker_df)

sub_records = []
for p in range(1, len(doc) + 1):
    for b in page_dict(p)["blocks"]:
        for l in b["lines"]:
            spans = [s for s in l["spans"] if s["text"].strip()]
            for k, s in enumerate(spans):
                if k > 0 and not is_superscript(s) and s["size"] < 0.8 * spans[k - 1]["size"] \
                        and s["origin"][1] > spans[k - 1]["origin"][1] + 0.5:
                    sub_records.append({"page_number": p, "font": s["font"], "host": spans[k - 1]["text"].strip()[-12:],
                                        "subscript": s["text"].strip(),
                                        "line": "".join(x["text"] for x in l["spans"]).strip()[:70]})
subscripts_df = pd.DataFrame(sub_records)
print("Inline subscripts (kept inside their words):")
display(subscripts_df)

# ---- reviewed snapshot (2026-09-26) ----
assert sorted(sum(marker_df["markers"], [])) == ["*", "1", "2", "3"], sorted(sum(marker_df["markers"], []))
assert set(marker_df["page_number"]) == {1, 6, 8}
assert sorted(subscripts_df["page_number"].unique()) == [10, 11, 13]       # Lpp, l1/h1/d1, suffix "1", CO2

# %% cell 25
# =========================================================
# 3.4 Rows: segments that share a baseline, in x order
# =========================================================
# One printed row = the lines of one page and zone whose baselines are within ROW_TOL of each other.
# The row text joins its segments with one space (a justified line split word by word becomes one row again).

ROW_TOL = 2.0

row_records, row_of_line = [], {}
for (p, zone), grp in lines_df.groupby(["page_number", "zone"], sort=True):
    grp = grp.sort_values(["baseline", "x0"])
    current, last_base = [], None
    rows_here = []
    for i, r in grp.iterrows():
        if current and r["baseline"] - last_base > ROW_TOL:
            rows_here.append(current)
            current = []
        current.append(i)
        last_base = r["baseline"] if len(current) == 1 else last_base
    if current:
        rows_here.append(current)
    for members in rows_here:
        seg = lines_df.loc[members].sort_values("x0")
        row_id = f"p{p:02d}_{zone}_{len(row_records):04d}"
        row_records.append({
            "row_id": row_id, "page_number": p, "zone": zone,
            "baseline": float(seg["baseline"].min()), "y0": float(seg["y0"].min()), "y1": float(seg["y1"].max()),
            "x0": float(seg["x0"].min()), "x1": float(seg["x1"].max()),
            "text": " ".join(" ".join(t.split()) for t in seg["text"] if t),
            "segments": [(float(x), " ".join(t.split())) for x, t in zip(seg["x0"], seg["text"]) if t],
            "markers": [m for ms in seg["markers"] for m in ms],
            # bold row: every segment bold, except a leading bare number (the Appendix 4 section numbers
            # "2" … "7" are printed in regular weight before a bold condition)
            "all_bold": bool(seg["all_bold"].all() or (len(seg) > 1 and re.fullmatch(r"\d", seg["text"].iloc[0])
                                                        and seg["all_bold"].iloc[1:].all())),
            "line_idx": list(seg.index),
        })
        for i in members:
            row_of_line[i] = row_id

rows_df = pd.DataFrame(row_records).sort_values(["page_number", "y0", "x0"]).reset_index(drop=True)
lines_df["row_id"] = lines_df.index.map(row_of_line)

multi = rows_df[rows_df["segments"].map(len) > 1]
print(f"Rows: {len(rows_df)} from {len(lines_df)} lines | rows with several segments: {len(multi)}")
print("Example (p.14, justified line split word by word):")
print(rows_df[(rows_df["page_number"] == 14) & rows_df["text"].str.startswith("5.6")][["text", "segments"]].iloc[0].to_dict())
assert lines_df["row_id"].notna().all()
# no row may join two lines that overlap horizontally (that would be two printed rows)
for r in multi.itertuples():
    xs = sorted(lines_df.loc[r.line_idx, ["x0", "x1"]].itertuples(index=False))
    assert all(a.x1 <= b.x0 + 0.5 for a, b in zip(xs, xs[1:])), f"Overlapping segments in one row: {r.text!r}"

# %% cell 26
# =========================================================
# 3.5 Bold heading blocks -> section_map (roles from text patterns, positions from the rows)
# =========================================================
# Consecutive bold rows of one page (gap <= HEADING_JOIN) form one heading block (multi-line titles and the
# multi-line conditions of Appendix 4). Every block must receive exactly one role.

HEADING_JOIN = 13.5                   # one line pitch (12.7pt) + tolerance; blank lines give >= 25pt
TABLE_LABEL_RE = re.compile(r"^Table\s+(\d{1,2})$")
A4_SECTION_RE = re.compile(r"^(\d)\s+If\b")

body_rows = rows_df[rows_df["zone"] == "body"]
blocks = []
for p, grp in body_rows[body_rows["all_bold"]].groupby("page_number"):
    for r in grp.sort_values("y0").itertuples():
        if blocks and blocks[-1]["page_number"] == p and r.y0 - blocks[-1]["y1_last"] <= HEADING_JOIN:
            b = blocks[-1]
            b["rows"].append(r.row_id); b["texts"].append(r.text); b["y1_last"] = r.y0
        else:
            blocks.append({"page_number": p, "y0": r.y0, "x0": r.x0, "rows": [r.row_id], "texts": [r.text],
                           "y1_last": r.y0})

roles, prev = [], None
for b in blocks:
    text = " ".join(b["texts"])
    if b["page_number"] == 1:
        role = "document_title"
    elif text == "LIST OF APPENDICES":
        role = "contents_title"
    elif text == "ANNEX":
        role = "annex"
    elif prev == "annex":
        role = "annex_title"
    elif APPENDIX_RE.match(text):
        role = "appendix"
    elif prev == "appendix":
        role = "appendix_title"
    elif A4_SECTION_RE.match(text):
        role = "a4_section"
    elif TABLE_LABEL_RE.match(text):
        role = "table_label"
    elif prev == "table_label":
        role = "table_title"
    elif text.startswith("Field Field description"):
        role = "column_header"
    elif text == "Direct Natural Resources Damages":
        role = "a4_table_title"
    else:
        role = "UNKNOWN"
    b.update(text=text, role=role)
    prev = role

section_map = pd.DataFrame(blocks)[["page_number", "y0", "x0", "role", "text", "rows"]]
section_map.insert(0, "heading_id", [f"H{k:03d}" for k in range(1, len(section_map) + 1)])

# document structure carried down in reading order: appendix, a4 section, table
appendix, a4_sec, table_no = None, None, None
struct = []
for h in section_map.itertuples():
    if h.role == "appendix":
        appendix, a4_sec, table_no = int(APPENDIX_RE.match(h.text).group(1)), None, None
    elif h.role == "a4_section":
        a4_sec = int(A4_SECTION_RE.match(h.text).group(1))
    elif h.role == "table_label":
        table_no = int(TABLE_LABEL_RE.match(h.text).group(1))
    struct.append((appendix, a4_sec, table_no))
section_map[["appendix", "a4_section", "table_no"]] = pd.DataFrame(struct, index=section_map.index).astype("Int64")

with pd.option_context("display.max_rows", None, "display.max_colwidth", 110):
    display(section_map.drop(columns="rows"))
print(section_map["role"].value_counts().to_dict())
assert (section_map["role"] != "UNKNOWN").all(), section_map[section_map["role"] == "UNKNOWN"]

# %% cell 27
# =========================================================
# 3.6 Title block, symbol/date, and the p.3 list of appendices/tables vs the real headings
# =========================================================

def letters_only(t: str) -> str:
    return re.sub(r"[^0-9a-z]", "", unicodedata.normalize("NFKC", str(t)).lower())


# ---- title, symbol, date (p.1) ----
TITLE_BLOCKS = section_map.loc[section_map["role"] == "document_title", "text"].tolist()
DOCUMENT_TITLE = " — ".join(TITLE_BLOCKS)
date_row = rows_df[(rows_df["page_number"] == 1) & rows_df["text"].str.fullmatch(r"\d{1,2} \w+ \d{4}")]
assert len(date_row) == 1
PRINTED_DATE = date_row["text"].iloc[0]
assert pd.to_datetime(PRINTED_DATE, format="%d %B %Y").strftime("%Y-%m-%d") == VERSION_DATE, "VERSION_DATE must be the printed date."
TITLE_MARKER_ROW = rows_df[(rows_df["page_number"] == 1) & (rows_df["markers"].map(lambda m: "*" in m))]
assert len(TITLE_MARKER_ROW) == 1 and TITLE_MARKER_ROW["text"].iloc[0] == "CASUALTY-RELATED MATTERS"
print("Title :", DOCUMENT_TITLE)
print("Date  :", PRINTED_DATE, "->", VERSION_DATE, "| '*' footnote marker on:", TITLE_MARKER_ROW["text"].iloc[0])

# ---- the contents list (p.3): from 'LIST OF APPENDICES' to the '***' separator ----
c_start = section_map.loc[section_map["role"] == "contents_title"].iloc[0]
c_end = rows_df[(rows_df["page_number"] == c_start.page_number) & (rows_df["text"] == "***")]
assert len(c_end) == 1
CONTENTS_ROWS = rows_df[(rows_df["page_number"] == c_start.page_number) & (rows_df["y0"] >= c_start.y0)
                        & (rows_df["y0"] <= c_end["y0"].iloc[0])]
contents_app, contents_tab, current = {}, {}, None
for r in CONTENTS_ROWS.itertuples():
    if m := re.match(r"^APPENDIX\s+(\d):\s*(.*)$", r.text):
        current = int(m.group(1)); contents_app[current] = m.group(2)
    elif m := re.match(r"^Table\s+(\d+):\s*(.*)$", r.text):
        current = None; contents_tab[int(m.group(1))] = m.group(2).strip()
    elif current and r.text not in ("LIST OF APPENDICES", "***"):
        contents_app[current] += " " + r.text                       # continuation of an appendix entry
assert sorted(contents_app) == [1, 2, 3, 4, 5] and sorted(contents_tab) == list(range(1, 31))

heading_app = {int(a): t for a, t in section_map.loc[section_map["role"] == "appendix_title", ["appendix", "text"]].values}
heading_tab = {int(n): t for n, t in section_map.loc[section_map["role"] == "table_title", ["table_no", "text"]].values}
assert sorted(heading_tab) == list(range(1, 31)), "Every table 1..30 needs exactly one printed title."


def contents_match(listed: str, printed: str) -> str:
    a, b = letters_only(listed), letters_only(printed)
    if a == b:
        return "identical"
    head = letters_only(re.split(r"[,(]", listed)[0])
    if b.startswith(a) or b.startswith(head) and head:
        return "heading adds a qualifier"
    return "differs"


contents_check = pd.DataFrame(
    [{"entry": f"Appendix {n}", "listed_p3": contents_app[n], "printed_heading": heading_app[n],
      "match": contents_match(contents_app[n], heading_app[n])} for n in sorted(contents_app)]
    + [{"entry": f"Table {n}", "listed_p3": contents_tab[n], "printed_heading": heading_tab[n],
        "match": contents_match(contents_tab[n], heading_tab[n])} for n in sorted(contents_tab)])
with pd.option_context("display.max_rows", None, "display.max_colwidth", 90):
    display(contents_check[contents_check["match"] != "identical"])
print("Contents entries:", contents_check["match"].value_counts().to_dict())

# %% cell 28
# =========================================================
# 3.7 Phase 3 validation
# =========================================================
roles = section_map["role"].value_counts().to_dict()
assert roles.get("appendix") == 5 and roles.get("appendix_title") == 5
assert roles.get("table_label") == 30 and roles.get("table_title") == 30
assert sorted(section_map.loc[section_map["role"] == "a4_section", "a4_section"].tolist()) == [1, 2, 3, 4, 5, 6, 7]
assert section_map.loc[section_map["role"] == "table_label", "table_no"].tolist() == list(range(1, 31)), "Tables out of order."
assert (section_map.loc[section_map["role"].isin(["table_label", "table_title"]), "appendix"] == 5).all()
assert (section_map.loc[section_map["role"].isin(["a4_section", "a4_table_title"]), "appendix"] == 4).all()

# ---- reviewed snapshot (2026-09-26): differences between the p.3 list and the printed headings ----
# the printed heading is canonical; the p.3 list is metadata only (plan §5.8)
REVIEWED_CONTENTS_DIFFS = {
    "Appendix 2": "heading adds a qualifier",     # 'relating to each ship involved in a marine casualty…' vs '(relating to each ship involved)'
    "Appendix 3": "heading adds a qualifier",
    "Appendix 4": "heading adds a qualifier",     # p.3 adds ', required in particular circumstances …'
    "Table 13": "differs",                        # p.3 'Oil cargo/bunkers type & quantity' vs heading 'Oil cargo/Bunker type & quantity'
    "Table 20": "heading adds a qualifier",       # heading adds '(select all that applies)'
}
actual_diffs = dict(contents_check.loc[contents_check["match"] != "identical", ["entry", "match"]].values)
assert actual_diffs == REVIEWED_CONTENTS_DIFFS, actual_diffs

print("✅ Phase 3 validation passed.")
print("Rows:", len(rows_df), "| bold heading blocks:", len(section_map), roles)
print("Appendix titles:", heading_app)

# %% [markdown] cell 29
# # Phase 4 — Structured Extraction
#
# The annex is a set of forms. Every table is drawn with thin filled rectangles (cell borders), so the **vertical
# rules give the column boundaries of each printed row** (4.1): a text segment belongs to the column between the
# two rules around its left edge. Rows are anchored on the **code** in the first column (`.1`, `.1*`, `2.20.1`);
# a row without a code is the wrapped continuation of the previous one (or a heading, when it lies outside the grid).
#
# | Step | Content | Output |
# |---|---|---|
# | 4.1 | grid of every page (vertical rules) | `grid_at(page, y)` |
# | 4.2 | Appendices 1–3: field tables → **field catalogue** (group, number, minimum flag, description, value type, footnote refs, option-table refs) | `fields_df` |
# | 4.3 | Appendix 4: conditional sections → conditions, numbered items, "If so:" markers, sub-headings, note, and the *Direct Natural Resources Damages* table | `a4_sections`, `a4_items_df` |
# | 4.4 | Appendix 5: the 30 option tables → options with their levels carried down (§5.4), groups, printed column headers | `options_df`, `option_tables` |
# | 4.5 | Damage diagram (p.10): value gate (ADR-020) | `figure_gate_df` |
# | 4.6 | Cross-references: every "See table N" → a table; every "Field at appendix X.Y.Z" → a field with the quoted name | `references_df` |
# | 4.7 | Source errata (ADR-022): the contradicting value-type cell of field 3.x.22 | `FIELD_ERRATA` |
# | 4.8 | Phase 4 validation + reviewed snapshot | |
#
# **Carry-down rule (tables with categories).** A row whose category cell is empty continues the last printed
# category of the same table (also across pages); a row that prints a category without a sub-option is a leaf and
# ends the carry. Table 12 has a third level (`On passage` → three modes) handled the same way.

# %% cell 30
# =========================================================
# 4.1 Table grids from the drawn cell borders
# =========================================================
# Every border is a filled rectangle ('re' item). A vertical rule is < 1.5pt wide and > 2pt high.
# grid_at(p, y) = the x positions of the vertical rules that cross height y on page p (merged within 3pt).

import bisect

vrules: dict[int, list[tuple[float, float, float]]] = {}
for p in range(1, len(doc) + 1):
    if p == 10:
        continue                                   # p.10: the damage diagram's vector drawing, no table
    for d in doc[p - 1].get_drawings():
        r = d["rect"]
        if r.width < 1.5 and r.height > 2:
            vrules.setdefault(p, []).append(((r.x0 + r.x1) / 2, r.y0, r.y1))


def grid_at(p: int, y: float) -> list[float]:
    xs = sorted(x for x, y0, y1 in vrules.get(p, []) if y0 - 1 <= y <= y1 + 1)
    merged = []
    for x in xs:
        if not merged or x - merged[-1] > 3:
            merged.append(x)
    return merged


def column_of(bounds: list[float], x0: float) -> int | None:
    """Column index (0 = first column) of a segment starting at x0, None outside the grid."""
    if len(bounds) < 2 or not (bounds[0] - 2 <= x0 <= bounds[-1]):
        return None
    return bisect.bisect_right(bounds, x0 + 1) - 1


def row_cells(r) -> dict[int, str] | None:
    """{column: text} of a row, None when the row is outside any grid. A line that PyMuPDF merged across a
    column rule (".14 Ship pollution – … & quantity Table 15") is split again by its words."""
    bounds = grid_at(r.page_number, r.baseline - 3)
    if len(bounds) < 2:
        return None
    cells: dict[int, list[tuple[float, str]]] = {}
    for i in r.line_idx:
        ln = lines_df.loc[i]
        if not ln["text"]:
            continue
        c0, c1 = column_of(bounds, ln["x0"]), column_of(bounds, ln["x1"] - 2)
        assert c0 is not None, f"p{r.page_number}: {ln['text']!r} at x={ln['x0']} outside the grid {bounds}"
        if c0 == c1 or c1 is None and ln["x1"] <= bounds[-1] + 40:
            cells.setdefault(c0, []).append((ln["x0"], ln["text"]))
            continue
        assert not ln["markers"], f"Cannot split a line with a superscript marker: {ln['text']!r}"
        for wx0, wx1, wt in line_words[(r.page_number, ln["block_no"], ln["line_no"])]:
            cells.setdefault(column_of(bounds, wx0), []).append((wx0, wt))
        SPLIT_LINES.add((r.page_number, int(ln["block_no"]), int(ln["line_no"]), ln["text"]))
    return {c: " ".join(t for _, t in sorted(ts)) for c, ts in cells.items()}


SPLIT_LINES = set()        # (page, block_no, line_no, text) of every line split at a column rule
rows_df["grid"] = [tuple(round(x) for x in grid_at(r.page_number, r.baseline - 3)) for r in rows_df.itertuples()]
rows_df["in_grid"] = rows_df["grid"].map(len) >= 2

grid_profile = (rows_df[rows_df["zone"] == "body"].groupby(["page_number", "grid"]).size().rename("rows").reset_index())
with pd.option_context("display.max_rows", None):
    display(grid_profile[grid_profile["grid"].map(len) > 0])
print("Body rows inside a grid:", int((rows_df["in_grid"] & (rows_df["zone"] == "body")).sum()),
      "| pages with grids:", sorted(vrules))

# %% cell 31
# =========================================================
# 4.2 Appendices 1–3: field tables -> field catalogue
# =========================================================
# Reading order = (page, y). Outside the grid: a group heading ("General", "1 Ship particulars",
# 'For each "equipment failure" accidental event'). Inside the grid: a row with a code in column 0 starts a
# field; a row without a code continues the previous field (wrapped description or value type).
# Word sometimes merges the code and the description into one segment (".10 Registered shipowner"): split.

CODE_RE = re.compile(r"^\.(\d+)(\*?)(?:\s+(.*))?$")
TABLE_REF_RE = re.compile(r"(?:See\s+)?[Tt]able\s+(\d{1,2})")
GROUP_NO_RE = re.compile(r"^(\d)\s+(\S.*)$")
HEADING_ROWS = {rid for rids in section_map["rows"] for rid in rids}

field_pages = page_class_df.loc[page_class_df["page_class"] == "annex_fields", "page_number"].tolist()
frows = rows_df[(rows_df["zone"] == "body") & rows_df["page_number"].isin(field_pages)].sort_values(["page_number", "y0"])
page_app = page_class_df.set_index("page_number")["appendix"]

fields, groups, row_role = [], [], {}
current_app, current_group = None, None
for r in frows.itertuples():
    if r.row_id in HEADING_ROWS:
        h = section_map[section_map["rows"].map(lambda ids: r.row_id in ids)].iloc[0]
        row_role[r.row_id] = h.role
        if h.role == "appendix":
            current_app, current_group = int(h.appendix), None
        continue
    if not r.in_grid:
        m = GROUP_NO_RE.match(r.text)
        groups.append({"appendix": current_app, "group": sum(g["appendix"] == current_app for g in groups) + 1,
                       "group_number_printed": m.group(1) if m else None,
                       "group_title": m.group(2) if m else r.text, "page_number": r.page_number, "row_id": r.row_id})
        current_group = groups[-1]
        row_role[r.row_id] = "field_group"
        continue
    cells = row_cells(r)
    m = CODE_RE.match(cells.get(0, ""))
    if m:
        assert not (m.group(3) and cells.get(1)), f"Code merged with text AND a description cell: {r.text!r}"
        assert current_group and current_group["appendix"] == current_app, f"Field outside a group: {r.text!r}"
        fields.append({
            "appendix": current_app, "group": current_group["group"],
            "group_number_printed": current_group["group_number_printed"], "group_title": current_group["group_title"],
            "field_no": int(m.group(1)), "code_printed": f".{m.group(1)}{m.group(2)}", "minimum": m.group(2) == "*",
            "description": (m.group(3) or cells.get(1, "")).strip(), "value_type": cells.get(2, "").strip(),
            "value_markers": list(r.markers), "page_number": r.page_number, "row_ids": [r.row_id],
        })
        row_role[r.row_id] = "field"
    else:
        assert 0 not in cells, f"Unexpected text in the code column: {r.text!r}"
        f = fields[-1]
        f["description"] = f"{f['description']} {cells.get(1, '')}".strip()
        f["value_type"] = f"{f['value_type']} {cells.get(2, '')}".strip()
        f["value_markers"] += list(r.markers)
        f["row_ids"].append(r.row_id)
        row_role[r.row_id] = "field_continuation"

fields_df = pd.DataFrame(fields)
groups_df = pd.DataFrame(groups)
fields_df.insert(0, "field_id", [f"{a}.{g}.{n}" for a, g, n in fields_df[["appendix", "group", "field_no"]].values])
fields_df["value_type"] = pd.Series([v or None for v in fields_df["value_type"]], dtype="object")
fields_df["table_refs"] = [[int(x) for x in TABLE_REF_RE.findall(v)] if v else [] for v in fields_df["value_type"]]
fields_df["multi_choice"] = [bool(v) and "(multi-choice)" in v for v in fields_df["value_type"]]

print(f"Fields: {len(fields_df)} in {len(groups_df)} groups")
print("Lines split at a column rule:", sorted((p, t) for p, _, _, t in SPLIT_LINES))
display(groups_df.assign(fields=[int(((fields_df["appendix"] == a) & (fields_df["group"] == g)).sum())
                                 for a, g in groups_df[["appendix", "group"]].values]).drop(columns="row_id"))
with pd.option_context("display.max_rows", None, "display.max_colwidth", 75):
    display(fields_df[["field_id", "code_printed", "description", "value_type", "value_markers", "table_refs"]])

# %% cell 32
# =========================================================
# 4.3 Appendix 4: conditional sections -> conditions, items, markers, sub-headings, note, damages table
# =========================================================
# Outside the grid, every body row of Appendix 4 is one of:
#   item          '2.20' + text (numbered at x = 70.9pt, text at 113.5pt)
#   continuation  text only at x >= 110pt (wrapped item text)
#   if_marker     'If so:' / 'If yes:' (binds the item before it to the item(s) after it)
#   subline       unnumbered text at x = 70.9pt right after an if_marker ('Lost goods floated or sank:')
#   subheading    'For ship in … condition …:' (section 3)
#   note          '(It is desirable to attach a sketch …)' — a parenthesised note, possibly several lines
# Inside the grid (p.14): the "Direct Natural Resources Damages" table of section 6 (group labels + options).

ITEM_RE = re.compile(r"^(\d+(?:\.\d+)+)$")
IF_MARKER_RE = re.compile(r"^If (?:so|yes):$")
A4_PAGES = page_class_df.loc[page_class_df["page_class"] == "annex_supplementary", "page_number"].tolist()

a4_rows = rows_df[(rows_df["zone"] == "body") & rows_df["page_number"].isin(A4_PAGES)].sort_values(["page_number", "y0"])
a4_sections: dict[int, dict] = {}
a4_items, dnr_rows = [], []
section, prev_kind = None, None
for r in a4_rows.itertuples():
    if r.row_id in HEADING_ROWS:
        h = section_map[section_map["rows"].map(lambda ids: r.row_id in ids)].iloc[0]
        row_role[r.row_id] = h.role
        if h.role == "a4_section" and h.a4_section not in a4_sections:
            section = int(h.a4_section)
            a4_sections[section] = {"section": section, "condition": A4_SECTION_RE.sub("", h.text, count=1).strip(),
                                    "condition_raw": h.text, "page_number": h.page_number, "heading_id": h.heading_id}
        prev_kind = h.role
        continue
    assert section is not None, f"Appendix 4 row before the first section: {r.text!r}"
    if r.in_grid:                                             # the damages table of section 6
        cells = row_cells(r)
        dnr_rows.append({"section": section, "row_id": r.row_id, "page_number": r.page_number,
                         "code": cells.get(0, "") if CODE_RE.match(cells.get(0, "")) else None,
                         "label": None if CODE_RE.match(cells.get(0, "")) else cells.get(0, ""),
                         "text": cells.get(1, "")})
        row_role[r.row_id] = "a4_table_row"
        prev_kind = "a4_table_row"
        continue
    first_x, first_t = r.segments[0]
    if ITEM_RE.match(first_t) and first_x < 100:
        kind, number, text = "item", first_t, " ".join(t for _, t in r.segments[1:])
    elif IF_MARKER_RE.match(r.text):
        kind, number, text = "if_marker", None, r.text
    elif r.text.startswith("For ship in"):
        kind, number, text = "subheading", None, r.text
    elif first_x < 100 and (r.text.startswith("(") or (prev_kind == "note" and not a4_items[-1]["text"].endswith(")"))):
        kind, number, text = "note", None, r.text
    elif first_x >= 110:
        kind, number, text = "continuation", None, r.text
    elif prev_kind in ("if_marker", "subline") and first_x < 100:
        kind, number, text = "subline", None, r.text
    else:
        raise AssertionError(f"Unclassified Appendix 4 row p{r.page_number}: {r.text!r}")

    if kind == "continuation":
        a4_items[-1]["text"] += " " + text
        a4_items[-1]["row_ids"].append(r.row_id)
        row_role[r.row_id] = "a4_continuation"
        continue
    if kind == "note" and prev_kind == "note":
        a4_items[-1]["text"] += " " + text
        a4_items[-1]["row_ids"].append(r.row_id)
        row_role[r.row_id] = "a4_note"
        continue
    a4_items.append({"section": section, "kind": kind, "item_no": number, "text": text,
                     "page_number": r.page_number, "row_ids": [r.row_id]})
    row_role[r.row_id] = f"a4_{kind}"
    prev_kind = kind

a4_items_df = pd.DataFrame(a4_items)
a4_items_df.insert(0, "a4_item_id", [f"a4_{k:03d}" for k in range(1, len(a4_items_df) + 1)])
dnr_df = pd.DataFrame(dnr_rows)

# ---- atomic blocks: an item + its nested items / markers / sublines; "If so:" joins the next item ----
block_ids, block, prev = [], 0, None
for it in a4_items_df.itertuples():
    joins = prev is not None and prev.section == it.section and (
        it.kind in ("if_marker", "subline")
        or (it.kind == "item" and (it.item_no.count(".") >= 2 or prev.kind == "if_marker")))
    block = block if joins else block + 1
    block_ids.append(block)
    prev = it
a4_items_df["block"] = block_ids

print("Sections:", {k: v["condition"][:70] + "…" for k, v in a4_sections.items()})
print("Item kinds:", a4_items_df["kind"].value_counts().to_dict(), "| atomic blocks:", a4_items_df["block"].nunique())
print("\nItems per section:", a4_items_df[a4_items_df["kind"] == "item"].groupby("section").size().to_dict())
with pd.option_context("display.max_rows", None, "display.max_colwidth", 100):
    display(a4_items_df[a4_items_df["kind"] != "item"][["a4_item_id", "section", "kind", "text", "block"]])
    display(dnr_df)

# %% cell 33
# =========================================================
# 4.4 Appendix 5: the 30 field-value option tables -> options (levels carried down), groups, headers
# =========================================================
# Rows are read in order (page, y) from each "Table N" heading to the next one, so a table continued on the
# next page keeps collecting rows. Inside the grid: a code in column 0 (".1", ".4.1") starts an option; a row
# without a code is a printed column header (before the first option) or the wrapped continuation of the
# previous option. Outside the grid: a group heading (Tables 22, 23) or a table note (Table 1).
# Levels (columns 1..k) are carried down within a table (§5.4); a table with a printed column header is a
# fill-in FORM: the option text is in column 1 (Table 14: the code itself = IMDG class) and the other columns
# are blank by design (asserted).

OPT_CODE_RE = re.compile(r"^\.(\d+(?:\.\d+)?)$")
OT_PAGES = page_class_df.loc[page_class_df["page_class"] == "annex_option_tables", "page_number"].tolist()
ot_rows = rows_df[(rows_df["zone"] == "body") & rows_df["page_number"].isin(OT_PAGES)].sort_values(["page_number", "y0"])

option_tables: dict[int, dict] = {}
options, table_no, group = [], None, None
for r in ot_rows.itertuples():
    if r.row_id in HEADING_ROWS:
        h = section_map[section_map["rows"].map(lambda ids: r.row_id in ids)].iloc[0]
        row_role[r.row_id] = h.role
        if h.role == "table_label":
            table_no, group = int(h.table_no), None
            option_tables[table_no] = {"table_no": table_no, "title": heading_tab[table_no], "page_start": r.page_number,
                                       "note": None, "header_cells": {}, "groups": [], "levels": 1,
                                       "heading_rows": [r.row_id]}
        elif h.role == "table_title":
            option_tables[table_no]["heading_rows"].append(r.row_id)
        continue
    t = option_tables[table_no]
    has_options = any(o["table_no"] == table_no for o in options)
    if not r.in_grid:                                     # group heading (or, in a table without options, a note)
        group = r.text; t["groups"].append((group, r.row_id)); row_role[r.row_id] = "option_group"
        continue
    cells = row_cells(r)
    t["levels"] = max(t["levels"], len(grid_at(r.page_number, r.baseline - 3)) - 2)
    m = OPT_CODE_RE.match(cells.get(0, ""))
    if m:
        options.append({"table_no": table_no, "code": f".{m.group(1)}", "group": group,
                        "cells": {c: v for c, v in cells.items() if c > 0}, "page_number": r.page_number,
                        "row_ids": [r.row_id]})
        row_role[r.row_id] = "option"
    elif not has_options:
        for c, v in cells.items():
            t["header_cells"][c] = f"{t['header_cells'].get(c, '')} {v}".strip()
        row_role[r.row_id] = "table_header"
    else:
        o = options[-1]
        assert o["table_no"] == table_no
        for c, v in cells.items():
            assert c > 0, f"Table {table_no}: continuation text in the code column: {r.text!r}"
            o["cells"][c] = f"{o['cells'].get(c, '')} {v}".strip()
        o["row_ids"].append(r.row_id)
        row_role[r.row_id] = "option_continuation"

# a table without any option row carries a note, not a group (Table 1: "As per GISIS nomenclatures")
for tno, t in option_tables.items():
    if not any(o["table_no"] == tno for o in options) and t["groups"]:
        (t["note"], rid), = t["groups"]
        t["groups"] = []
        row_role[rid] = "table_note"
    t["groups"] = [g for g, _ in t["groups"]]

# ---- levels, carry-down, form tables ----
option_records = []
for tno, t in option_tables.items():
    t["kind"] = "form" if t["header_cells"] else ("hierarchical" if t["levels"] > 1 else "list")
    t["header"] = [t["header_cells"][c] for c in sorted(t["header_cells"])]
    active = [None, None, None]                     # last printed category at level 1 / level 2
    for o in (o for o in options if o["table_no"] == tno):
        rec = {"table_no": tno, "code": o["code"], "group": o["group"], "page_number": o["page_number"],
               "row_ids": o["row_ids"], "level_1": "", "level_2": "", "level_3": "", "carried": [], "empty": False,
               "form_blank_columns": []}
        if t["kind"] == "form":
            label_col = 1 if tno != 14 else None
            rec["level_1"] = o["cells"].get(1, "") if label_col else ""
            others = {c: v for c, v in o["cells"].items() if c != label_col and v}
            assert not others, f"Table {tno} {o['code']}: text in a fill-in column {others}"
        else:
            lv = [o["cells"].get(c, "") for c in range(1, 4)]
            for k in range(3):
                if lv[k]:
                    active[k] = lv[k] if any(lv[k + 1:]) else None      # a leaf ends the carry at its level
                    for j in range(k + 1, 3):
                        active[j] = None if not lv[j] else active[j]
                    break
            first = next((k for k in range(3) if lv[k]), None)
            if first is None:
                rec["empty"] = True
            else:
                for k in range(first):
                    assert active[k] is not None, f"Table {tno} {o['code']}: nothing to carry at level {k + 1}"
                    lv[k] = active[k]; rec["carried"].append(k + 1)
            rec["level_1"], rec["level_2"], rec["level_3"] = lv
        option_records.append(rec)

options_df = pd.DataFrame(option_records)
options_df.insert(0, "option_id", [f"t{t:02d}_{c.strip('.').replace('.', '_')}" for t, c in options_df[["table_no", "code"]].values])
options_df["label"] = [" — ".join(x for x in (a, b, c) if x) for a, b, c in options_df[["level_1", "level_2", "level_3"]].values]
option_tables_df = pd.DataFrame([{k: v for k, v in t.items() if k != "header_cells"} for t in option_tables.values()])
option_tables_df["options"] = option_tables_df["table_no"].map(options_df.groupby("table_no").size()).fillna(0).astype(int)

print(f"Option tables: {len(option_tables_df)} | options: {len(options_df)} | empty options: {int(options_df['empty'].sum())} "
      f"| carried rows: {int(options_df['carried'].map(len).gt(0).sum())}")
with pd.option_context("display.max_rows", None, "display.max_colwidth", 70):
    display(option_tables_df[["table_no", "title", "kind", "levels", "options", "note", "header", "groups"]])
    display(options_df[options_df["table_no"].isin([4, 12, 14, 22]) | options_df["empty"]][["option_id", "group", "label", "carried", "empty"]])

# %% cell 34
# =========================================================
# 4.5 Damage diagram (p.10): region, labels, value gate (ADR-020)
# =========================================================
# The only graphic of the document (the p.1 images are the IMO logo and the "IMO Conventions" badge: layout).
# It is two raster sketches plus vector arrows and Times New Roman labels, printed without a caption between
# items 2.5 and 2.6 of Appendix 4, section 2. Gate decision after reviewing the render
# (Notebooks/_scratch/figure_renders/): FULL — it defines the damage dimensions that section 2 asks for.
# The curated description names only what is drawn and labelled, and contains no number (ADR-020: the figure
# prints none — the appendix/section numbers go to the chunk title, not into the description).

images_df = pd.DataFrame([{"page_number": p, "bbox": tuple(round(v, 1) for v in i["bbox"]), "xref": i.get("xref"),
                           "width": i["width"], "height": i["height"]}
                          for p in (1, 10) for i in doc[p - 1].get_image_info(xrefs=True)])
images_df["kind"] = ["layout_logo" if p == 1 else "figure_part" for p in images_df["page_number"]]

fig_lines = lines_df[lines_df["zone"] == "figure_label"]
fig_boxes = [b for b in images_df.loc[images_df["page_number"] == 10, "bbox"]] + \
            list(fig_lines[["x0", "y0", "x1", "y1"]].itertuples(index=False, name=None))
FIGURE_REGION = (10, min(b[0] for b in fig_boxes), min(b[1] for b in fig_boxes),
                 max(b[2] for b in fig_boxes), max(b[3] for b in fig_boxes))
FIGURE_LABELS = fig_lines["text"].tolist()

render_dir = SCRATCH_DIR / "figure_renders"
render_dir.mkdir(parents=True, exist_ok=True)
doc[9].get_pixmap(dpi=150, clip=pymupdf.Rect(*FIGURE_REGION[1:])).save(render_dir / "imo_fig_p10_damage_diagram.png")

FIGURE_DESCRIPTION = (
    "Damage diagram of the supplementary information on a breach of hull causing flooding (printed without a caption "
    "after the item \"Draught before damage\"). "
    "Two sketches mark the damage dimensions asked for in this section. The \"Ship bottom\" sketch shows a bottom "
    "damage with its length l, its height h, the penetration d and the distance X to the centre of the damage. "
    "The \"Ship side\" sketch shows the bulkhead- or freeboard deck, the moulded depth D, the draught after damage dd, "
    "a side damage with its length l, height h and penetration d, the distance z from the base line to the lower "
    "point of the damage, the distance X, the length between perpendiculars Lpp and the forward perpendicular FP; "
    "the part of the damage above the deck is marked with subscripted labels.")

figure_gate_df = pd.DataFrame([{
    "figure_id": "fig_p10_damage", "page_number": 10, "region": FIGURE_REGION[1:], "decision": "full",
    "caption": None, "provenance": "curated_from_render", "labels": FIGURE_LABELS, "description": FIGURE_DESCRIPTION,
    "reason": "Defines the symbols of the damage items of Appendix 4, section 2 (Lpp, D, dd, d, h, l, X, z).",
}])

# ADR-020: only numbers printed in the figure (none) + every named label really is printed
assert not re.search(r"\d", " ".join(FIGURE_LABELS)) and not re.search(r"\d", FIGURE_DESCRIPTION)
printed = letters_only(" ".join(FIGURE_LABELS).replace("I", "l"))
for label in ["Ship bottom", "Ship side", "freeboard deck", "Lpp", "FP", "dd"]:
    assert letters_only(label) in printed and label.lower() in FIGURE_DESCRIPTION.lower(), label
assert all(FIGURE_REGION[2] - 1 <= y <= FIGURE_REGION[4] + 1 for y in fig_lines["y0"])

print("Images:"); display(images_df)
print("Figure region (p.10):", tuple(round(v, 1) for v in FIGURE_REGION[1:]))
print("Printed labels:", FIGURE_LABELS)
print("Render:", (render_dir / "imo_fig_p10_damage_diagram.png").relative_to(PROJECT_ROOT))

# %% cell 35
# =========================================================
# 4.6 Cross-references: option tables named by the fields, fields named by the Appendix 4 conditions
# =========================================================
TABLE_TITLE = {int(t): s for t, s in option_tables_df[["table_no", "title"]].values}
assert set(TABLE_TITLE) == set(range(1, 31))

ref_records = []
for f in fields_df.itertuples():
    for t in f.table_refs:
        ref_records.append({"kind": "field -> option table", "from": f.field_id, "to": f"Table {t}",
                            "resolved": t in TABLE_TITLE, "check": TABLE_TITLE.get(t)})

FIELD_REF_RE = re.compile(r'"([^"]+)"[^"]*?\((?:Field at appendix |Field )?(\d\.\d\.\d+)\)')
words = lambda s: set(re.findall(r"[a-z0-9]+", s.lower()))
fields_by_id = fields_df.set_index("field_id")
for sec, s in a4_sections.items():
    refs = FIELD_REF_RE.findall(s["condition"])
    s["field_refs"] = [fid for _, fid in refs]
    for quoted, fid in refs:
        ok = fid in fields_by_id.index
        target = ""
        if ok:
            f = fields_by_id.loc[fid]
            vocab = words(f["description"])
            for t in f["table_refs"]:                              # a quoted value of the field's option table
                vocab |= words(" ".join(options_df.loc[options_df["table_no"] == t, "label"]))
            ok = words(quoted) <= vocab
            target = f["description"]
        ref_records.append({"kind": "appendix 4 condition -> field", "from": f"A4 section {sec}", "to": fid,
                            "resolved": ok, "check": f'"{quoted}" ~ {target}'})
references_df = pd.DataFrame(ref_records)

referenced_tables = {int(t[6:]) for t in references_df.loc[references_df["kind"] == "field -> option table", "to"]}
UNREFERENCED_TABLES = sorted(set(TABLE_TITLE) - referenced_tables)

with pd.option_context("display.max_rows", None, "display.max_colwidth", 100):
    display(references_df[references_df["kind"] != "field -> option table"])
print("Field -> table references:", int((references_df["kind"] == "field -> option table").sum()),
      "| tables never referenced by a field:", UNREFERENCED_TABLES)
assert references_df["resolved"].all(), references_df[~references_df["resolved"]]

# %% cell 36
# =========================================================
# 4.7 Source errata in the field tables (ADR-022) — excluded, never corrected
# =========================================================
# Field 3.2.22 (Appendix 3, "human erroneous action"): the description defines a drop-down list of four
# watchkeeping patterns, but the value-type cell prints "Y/N/U" — which footnote 2 of the same annex defines as
# Yes/No/Unknown and which cannot hold any of the four patterns. The row contradicts itself: the value-type cell
# is excluded (the description, which carries the four options, is kept).

FIELD_ERRATA = {
    "3.2.22": {"column": "value_type", "printed": "Y/N/U",
               "evidence": "description = 'drop down list: 4 on/8 off, or 6 on/6 off, or 12 on/12 off, or Other'; "
                           "footnote 2 (Annex p.2) defines Y/N/U as Yes/No/Unknown, which cannot express these options"},
}

fields_df["value_type_printed"] = fields_df["value_type"]
fields_df["value_type_excluded"] = None
for fid, e in FIELD_ERRATA.items():
    k = fields_df.index[fields_df["field_id"] == fid]
    assert len(k) == 1 and fields_df.at[k[0], "value_type"] == e["printed"], f"Erratum {fid} not found as printed."
    fields_df.at[k[0], "value_type_excluded"] = e["printed"]
    fields_df.at[k[0], "value_type"] = None
    assert "drop down list" in fields_df.at[k[0], "description"]
applied = fields_df["value_type_excluded"].notna().sum()
assert applied == len(FIELD_ERRATA), "Every erratum is applied exactly once."

no_value = fields_df[fields_df["value_type"].isna()][["field_id", "description", "value_type_printed", "value_type_excluded"]]
print("Fields without a value type after errata:")
display(no_value)
assert no_value["field_id"].tolist() == ["3.2.22", "3.2.23"], "3.2.23 prints no value type at all (reviewed)."

# %% cell 37
# =========================================================
# 4.8 Phase 4 validation (structure + reviewed snapshot 2026-09-26)
# =========================================================
# ---- field catalogue ----
for (a, g), grp in fields_df.groupby(["appendix", "group"]):
    assert grp["field_no"].tolist() == list(range(1, len(grp) + 1)), f"Field numbers not consecutive in {a}.{g}"
assert fields_df["description"].str.len().gt(0).all()
REVIEWED_FIELDS_PER_GROUP = {(1, 1): 6, (1, 2): 8, (1, 3): 6, (2, 1): 19, (2, 2): 5, (2, 3): 11, (2, 4): 15,
                             (3, 1): 1, (3, 2): 30, (3, 3): 6, (3, 4): 3, (3, 5): 2, (3, 6): 5}
assert fields_df.groupby(["appendix", "group"]).size().to_dict() == REVIEWED_FIELDS_PER_GROUP
MINIMUM_FIELDS = fields_df.loc[fields_df["minimum"], "field_id"].tolist()
assert MINIMUM_FIELDS == ["1.1.1", "1.1.2", "1.2.2", "1.2.3", "1.2.4", "1.2.5", "1.2.6", "1.2.7", "1.2.8",
                          "2.1.1", "2.1.2", "2.1.5", "2.1.6", "2.3.2"], MINIMUM_FIELDS
assert not fields_df.loc[fields_df["appendix"] == 3, "minimum"].any(), "Circular para. 7: asterisks only in appendices 1 and 2."
assert dict(zip(fields_df.loc[fields_df["value_markers"].map(len) > 0, "field_id"],
                fields_df.loc[fields_df["value_markers"].map(len) > 0, "value_markers"])) == \
    {"2.1.1": ["1"], "2.2.2": ["2"], "3.2.2": ["3"]}, "Footnote markers 1–3 sit on these value types."

# ---- Appendix 4 ----
assert sorted(a4_sections) == [1, 2, 3, 4, 5, 6, 7]
items = a4_items_df[a4_items_df["kind"] == "item"]
assert items.groupby("section").size().to_dict() == {1: 7, 2: 33, 3: 63, 4: 19, 5: 6, 7: 22}
for sec, grp in items.groupby("section"):
    top = [int(n.split(".")[1]) for n in grp["item_no"] if n.count(".") == 1]
    assert top == list(range(1, len(top) + 1)), f"A4 section {sec}: top-level items not consecutive"
    assert all(n.startswith(f"{sec}.") for n in grp["item_no"])
assert (dnr_df["section"] == 6).all() and len(dnr_df) == 18

# ---- option tables ----
REVIEWED_OPTIONS = {1: 0, 2: 13, 3: 14, 4: 34, 5: 3, 6: 11, 7: 14, 8: 4, 9: 6, 10: 6, 11: 3, 12: 58, 13: 10, 14: 13,
                    15: 6, 16: 6, 17: 18, 18: 33, 19: 4, 20: 11, 21: 3, 22: 60, 23: 77, 24: 40, 25: 37, 26: 13,
                    27: 16, 28: 22, 29: 11, 30: 7}
assert option_tables_df.set_index("table_no")["options"].to_dict() == REVIEWED_OPTIONS
for tno, grp in options_df.groupby("table_no"):
    if tno != 14:
        assert grp["code"].tolist() == [f".{k}" for k in range(1, len(grp) + 1)], f"Table {tno}: codes not consecutive"
assert options_df.loc[options_df["table_no"] == 14, "code"].tolist() == \
    [".1", ".2", ".3", ".4.1", ".4.2", ".4.3", ".5.1", ".5.2", ".6.1", ".6.2", ".7", ".8", ".9"]
assert option_tables_df.set_index("table_no")["kind"].to_dict() == {
    **{t: "list" for t in REVIEWED_OPTIONS}, 1: "list", 4: "hierarchical", 12: "hierarchical", 18: "hierarchical",
    25: "hierarchical", 26: "hierarchical", 27: "hierarchical", 13: "form", 14: "form", 15: "form"}
assert options_df.loc[options_df["empty"], "option_id"].tolist() == ["t22_17"], "Only Table 22 .17 prints no text."
assert option_tables_df.set_index("table_no").at[1, "note"] == "As per GISIS nomenclatures"
assert [len(g) for g in option_tables_df.set_index("table_no").loc[[22, 23], "groups"]] == [10, 11]
assert options_df.loc[options_df["table_no"].isin([22, 23]), "group"].notna().all()
# Table 12 (§5.4, evidence): .8–.27 carry "Normal service" — the printed sub-options continue its alphabetical
# list (Alongside … Embarking, Loading … Water ballast exchange) with On passage (.14–.16) as the only
# three-level entry; the next printed category is "Sailing" at .28. (p.20 draws a border under .16 in the
# category column, but prints no other category.)
t12 = options_df[options_df["table_no"] == 12].set_index("code")
assert (t12.loc[[f".{k}" for k in range(7, 28)], "level_1"] == "Normal service").all()
assert t12.loc[[".14", ".15", ".16"], "level_2"].eq("On passage").all()

# ---- every annex body row has exactly one role ----
annex_rows = rows_df[(rows_df["zone"] == "body") & rows_df["page_number"].isin(field_pages + A4_PAGES + OT_PAGES)]
unassigned = annex_rows[~annex_rows["row_id"].isin(row_role)]
assert unassigned.empty, unassigned[["page_number", "text"]]

print("✅ Phase 4 validation passed.")
print(f"Fields: {len(fields_df)} in {len(groups_df)} groups ({len(MINIMUM_FIELDS)} minimum fields) | "
      f"A4: {len(a4_sections)} sections, {len(items)} items, {a4_items_df['block'].nunique()} blocks, "
      f"damages table {len(dnr_df)} rows | options: {len(options_df)} in 30 tables | figure gate: full 1")
print("Annex row roles:", pd.Series(row_role).value_counts().to_dict())

# %% [markdown] cell 38
# # Phase 5 — Notes / Footnotes
#
# The document has **four footnotes**, each anchored by a superscript marker found in 3.3:
#
# | Marker | Page | Anchored on | Content | Policy (plan §5.5) |
# |---|---|---|---|---|
# | `*` | 1 | the heading `CASUALTY-RELATED MATTERS*` | the seven joint MSC-MEPC circular series | **own unit** in the circular section (the marker is on a heading, not on a paragraph — deviation from the proposed "append to the paragraph") |
# | `1` | 6 (Annex p.2) | value type `Number/Auto` of field 2.1.1 | `"Auto" means "automatically populated".` | informative definition → appended as "Note:" to **every field chunk** whose value types use `Auto` |
# | `2` | 6 | value type `Y/N/U` of field 2.2.2 | `Y/N/U means Yes/No/Unknown.` | same, for `Y/N/U` |
# | `3` | 8 (Annex p.4) | value type `M/F/U` of field 3.2.2 | `M/F/U means Male/Female/Unknown.` | same, for `M/F/U` |
#
# Each footnote is assembled from its footnote-zone rows (label row + text rows; the `*` note keeps its numbered
# list one item per line). The footnote label lines are metadata (the note text itself is what is indexed).

# %% cell 39
# =========================================================
# 5.1 Footnote registry
# =========================================================
FOOTNOTE_LABEL_RE = re.compile(r"^(\*|\d)$")

fn_rows = rows_df[rows_df["zone"] == "footnote"].sort_values(["page_number", "y0"])
notes, current = [], None
for r in fn_rows.itertuples():
    if FOOTNOTE_LABEL_RE.match(r.text) and r.x0 < 80:
        current = {"marker": r.text, "page_number": r.page_number, "label_row": r.row_id, "rows": [], "lines": []}
        notes.append(current)
        continue
    assert current is not None and current["page_number"] == r.page_number, f"Footnote text without label: {r.text!r}"
    current["rows"].append(r.row_id)
    if len(r.segments) > 1 and re.fullmatch(r"\d", r.segments[0][1]):       # numbered list item of the '*' note
        current["lines"].append(f"{r.segments[0][1]} {' '.join(t for _, t in r.segments[1:])}")
    elif current["lines"] and r.x0 > 140:                                    # wrapped list item
        current["lines"][-1] += " " + r.text
    elif current["lines"] and not re.match(r"^\d ", current["lines"][-1]):
        current["lines"][-1] += " " + r.text                                  # wrapped sentence
    else:
        current["lines"].append(r.text)

note_registry_df = pd.DataFrame(notes)
note_registry_df["text"] = note_registry_df["lines"].map("\n".join)

# anchors: the superscript markers of 3.3
anchor = {m: (r.page_number, r.text) for r in marker_df.itertuples() for m in r.markers}
note_registry_df["anchor_text"] = note_registry_df["marker"].map(lambda m: anchor[m][1])
note_registry_df["anchor_page"] = note_registry_df["marker"].map(lambda m: anchor[m][0])
VALUE_TYPE_NOTES = {"1": "Auto", "2": "Y/N/U", "3": "M/F/U"}         # footnote -> value-type token it defines
note_registry_df["policy"] = note_registry_df["marker"].map(
    lambda m: "own_unit" if m == "*" else f"append_to_field_chunks_using:{VALUE_TYPE_NOTES[m]}")

with pd.option_context("display.max_colwidth", 120):
    display(note_registry_df[["marker", "page_number", "anchor_text", "policy", "text"]])
print(note_registry_df.loc[note_registry_df["marker"] == "*", "text"].iloc[0])

# %% cell 40
# =========================================================
# 5.2 Phase 5 validation
# =========================================================
assert note_registry_df["marker"].tolist() == ["*", "1", "2", "3"], "One footnote per marker, in page order."
assert (note_registry_df["page_number"] == note_registry_df["anchor_page"]).all(), "A footnote sits on its marker's page."
for m, token in VALUE_TYPE_NOTES.items():
    txt = note_registry_df.set_index("marker").at[m, "text"]
    assert txt.startswith(token) or txt.startswith(f'"{token}"'), f"Footnote {m} must define {token}: {txt!r}"
star = note_registry_df.set_index("marker").at["*", "text"].split("\n")
assert len(star) == 8 and [l.split(" ")[0] for l in star[1:]] == [str(k) for k in range(1, 8)], star
assert star[3].startswith("3 Casualty-related matters, as MSC-MEPC.3/Circ"), "Series 3 = this circular's series."
used_rows = set(note_registry_df["label_row"]) | {rid for rs in note_registry_df["rows"] for rid in rs}
assert used_rows == set(fn_rows["row_id"]), "Every footnote-zone row belongs to one footnote."

print("✅ Phase 5 validation passed.")
print("Footnotes:", dict(zip(note_registry_df["marker"], note_registry_df["policy"])))

# %% [markdown] cell 41
# # Phase 6 — Body Extraction + Cleaning (circular, p.1–3)
#
# The annex was extracted structurally in Phase 4; the only running prose is the circular. Its body rows are what is
# left after excluding what is known: running header and footer (Phase 3 zones), the IMO letterhead, the symbol and
# date (metadata), the title block (metadata → chunk title), the footnote area (Phase 5) and the p.3 list of
# appendices/tables (metadata, cross-checked in 3.6). Every excluded circular row gets a recorded reason.

# %% cell 42
# =========================================================
# 6.1 Circular rows: body vs excluded (with a reason)
# =========================================================
CIRCULAR_PAGES = page_class_df.loc[page_class_df["page_class"] == "circular", "page_number"].tolist()
contents_ids = set(CONTENTS_ROWS["row_id"])
title_ids = {rid for rids in section_map.loc[section_map["role"] == "document_title", "rows"] for rid in rids}

circ_rows = rows_df[rows_df["page_number"].isin(CIRCULAR_PAGES)].sort_values(["page_number", "y0"]).copy()


def circular_role(r) -> str:
    if r.zone != "body":
        return r.zone                                      # header / footer / letterhead / footnote
    if r.row_id in title_ids:
        return "title"
    if r.row_id in contents_ids:
        return "contents"
    if r.page_number == 1 and r.text in (DOCUMENT_SYMBOL, PRINTED_DATE):
        return "symbol_date"
    return "body"


circ_rows["role"] = [circular_role(r) for r in circ_rows.itertuples()]
for r in circ_rows.itertuples():
    row_role.setdefault(r.row_id, f"circular_{r.role}")
body_rows_df = circ_rows[circ_rows["role"] == "body"].copy()

print("Circular rows by role:", circ_rows["role"].value_counts().to_dict())
print("Body rows per page:", body_rows_df.groupby("page_number").size().to_dict())

# %% cell 43
# =========================================================
# 6.2 Phase 6 validation
# =========================================================
assert set(circ_rows["role"]) == {"header", "footer", "letterhead", "footnote", "title", "contents", "symbol_date", "body"}
assert circ_rows.loc[circ_rows["role"] == "symbol_date", "text"].tolist() == [DOCUMENT_SYMBOL, PRINTED_DATE]
assert body_rows_df["text"].str.strip().ne("").all()
assert not body_rows_df["text"].str.contains(re.escape(FOOTER_TEXT)).any()
# the body starts with paragraph 1 and ends with paragraph 10
assert body_rows_df["segments"].iloc[0][0][1] == "1" and body_rows_df["segments"].iloc[-1][0][1] == "10"
print("✅ Phase 6 validation passed.")
print("Circular body rows:", len(body_rows_df), "| excluded circular rows:", int((circ_rows["role"] != "body").sum()))

# %% [markdown] cell 44
# # Phase 7 — Paragraph Reconstruction (circular)
#
# Rules from the layout: a numbered paragraph starts with its number at x = 70.9pt and its first line of text at
# x = 113.5pt; continuation lines start at x = 70.9pt; **sub-items** (`.1`, `.2`, …) start at x = 113.5pt with their
# text at x = 156pt and continue at 156pt. Sub-items belong to their paragraph (paragraph 2: `.1`–`.2`, paragraph 8:
# `.1`–`.5`) and keep one line each. Lines are joined with one space (Word breaks lines at spaces; no hyphenation
# occurs in this document — asserted).

# %% cell 45
# =========================================================
# 7.1 Numbered paragraphs + sub-items
# =========================================================
PARA_NO_RE = re.compile(r"^\d{1,2}$")
SUBITEM_RE = re.compile(r"^\.\d$")

paragraphs, current = [], None
for r in body_rows_df.itertuples():
    first_x, first_t = r.segments[0]
    rest = " ".join(t for _, t in r.segments[1:])
    if PARA_NO_RE.match(first_t) and first_x < 90 and rest:
        current = {"paragraph_no": int(first_t), "lines": [rest], "page_start": r.page_number,
                   "page_end": r.page_number, "row_ids": [r.row_id]}
        paragraphs.append(current)
        continue
    assert current is not None, f"Body text before paragraph 1: {r.text!r}"
    if SUBITEM_RE.match(first_t) and 100 < first_x < 130:
        current["lines"].append(f"{first_t} {rest}")
    else:
        current["lines"][-1] += " " + r.text
    current["page_end"] = r.page_number
    current["row_ids"].append(r.row_id)

paragraphs_df = pd.DataFrame(paragraphs)
paragraphs_df["lines"] = paragraphs_df["lines"].map(lambda ls: [" ".join(l.split()) for l in ls])   # justified double spaces
paragraphs_df["paragraph_id"] = paragraphs_df["paragraph_no"].map(lambda n: f"para_{n:02d}")
paragraphs_df["text"] = [f"{n} " + "\n".join(ls) for n, ls in paragraphs_df[["paragraph_no", "lines"]].values]
paragraphs_df["sub_items"] = paragraphs_df["lines"].map(lambda ls: len(ls) - 1)
paragraphs_df["char_count"] = paragraphs_df["text"].str.len()

with pd.option_context("display.max_colwidth", 140):
    display(paragraphs_df[["paragraph_id", "page_start", "page_end", "sub_items", "char_count", "text"]])

# %% cell 46
# =========================================================
# 7.2 Phase 7 validation
# =========================================================
assert paragraphs_df["paragraph_no"].tolist() == list(range(1, 11)), "Paragraphs 1–10, in order."
assert dict(zip(paragraphs_df["paragraph_no"], paragraphs_df["sub_items"])) == {**{k: 0 for k in range(1, 11)}, 2: 2, 8: 5}
used = [rid for rs in paragraphs_df["row_ids"] for rid in rs]
assert sorted(used) == sorted(body_rows_df["row_id"]) and len(used) == len(set(used)), "Every body row used exactly once."
assert letters_only(" ".join(paragraphs_df["text"])) == letters_only(" ".join(body_rows_df["text"])), "No character lost."
assert not any(re.search(r"[A-Za-z]-$", t) for t in body_rows_df["text"]), "No hyphenated line break to repair."
print("✅ Phase 7 validation passed.")
print("Paragraphs:", len(paragraphs_df), "| characters:", int(paragraphs_df["char_count"].sum()))

# %% [markdown] cell 47
# # Phase 8 — Section / Subsection Assignment
#
# Every piece of content gets its place in the document hierarchy, which becomes `parent_chunk` (the section) and
# `sub_chunk` (the path below it) of its chunks:
#
# | Content | `parent_chunk` | `sub_chunk` |
# |---|---|---|
# | circular paragraphs 1–10 | `MSC-MEPC.3/Circ.4/Rev.1 — Circular` | — |
# | `*` footnote | same | `Footnote to "Casualty-related matters"` |
# | fields (Appendices 1–3) | `Annex — Appendix N: <title>` | the field group (`1 Ship particulars`, `General`, `For each … event`) |
# | Appendix 4 sections | `Annex — Appendix 4: Supplementary information` | `Section N` (+ `Damage diagram` for the figure) |
# | option tables | `Annex — Appendix 5: Field value option tables` | `Table N — <title>` |
#
# Headings are printed in capitals; they are written in sentence case in the metadata (letters unchanged, verified
# case-insensitively in Phase 19).

# %% cell 48
# =========================================================
# 8.1 Section names and paths
# =========================================================
def sentence_case(t: str) -> str:
    """'FACTUAL INFORMATION (relating to each ship involved)' -> 'Factual information (relating to each ship involved)'."""
    return t[:1].upper() + t[1:].lower() if t[:1].isalpha() else t


CIRCULAR_SECTION = f"{DOCUMENT_SYMBOL} — Circular"
DISPLAY_TITLE = (f"{sentence_case(TITLE_BLOCKS[0].split(' REPORTS ')[0])}. "
                 f"{sentence_case('REPORTS ' + TITLE_BLOCKS[0].split(' REPORTS ', 1)[1])} — {TITLE_BLOCKS[1]}")
APPENDIX_SECTION = {a: f"Annex — Appendix {a}: {sentence_case(t)}" for a, t in heading_app.items()}
ANNEX_TITLE = section_map.loc[section_map["role"] == "annex_title", "text"].iloc[0]
assert letters_only(ANNEX_TITLE) == letters_only(TITLE_BLOCKS[1]), "The annex title repeats the circular's subtitle."

groups_df["group_label"] = [f"{n} {t}" if isinstance(n, str) else t
                            for n, t in groups_df[["group_number_printed", "group_title"]].values]
group_label = {(a, g): lab for a, g, lab in groups_df[["appendix", "group", "group_label"]].values}
fields_df["section"] = fields_df["appendix"].map(APPENDIX_SECTION)
fields_df["subsection_path"] = [[group_label[(a, g)]] for a, g in fields_df[["appendix", "group"]].values]
options_df["section"] = APPENDIX_SECTION[5]
options_df["subsection_path"] = options_df["table_no"].map(lambda t: [f"Table {t} — {TABLE_TITLE[t]}"])
paragraphs_df["section"] = CIRCULAR_SECTION

print("Document title :", DISPLAY_TITLE)
print("Sections       :", [CIRCULAR_SECTION, *APPENDIX_SECTION.values()])
display(groups_df[["appendix", "group", "group_label", "page_number"]])

# %% cell 49
# =========================================================
# 8.2 Phase 8 validation
# =========================================================
assert DISPLAY_TITLE.startswith("Casualty-related matters. Reports on marine casualties and incidents — Revised")
assert fields_df["subsection_path"].map(len).eq(1).all() and options_df["subsection_path"].map(len).eq(1).all()
assert fields_df.groupby("section")["appendix"].nunique().eq(1).all()
assert set(fields_df["appendix"]) == {1, 2, 3} and set(a4_items_df["section"]) | {6} == set(range(1, 8))
for sec, grp in fields_df.groupby(["appendix", "group"]):
    assert grp["page_number"].is_monotonic_increasing, f"Group {sec} is not in reading order."
print("✅ Phase 8 validation passed.")
print(fields_df.groupby("section").size().to_dict(), "| option tables:", options_df["table_no"].nunique())

# %% [markdown] cell 50
# # Phase 9 — Unified Logical Units, errata and access
#
# One unit per meaningful piece (plan §5):
#
# | unit_type | Source | Unit |
# |---|---|---|
# | `paragraph` | circular | one numbered paragraph with its sub-items |
# | `note` | circular footnote `*` | the circular-series note |
# | `field` | Appendices 1–3 | one field: `.N[*] description — value type: … (See table N (title))` |
# | `a4_section` | Appendix 4 | one conditional section: its condition + atomic item blocks (section 6 includes its damages table) |
# | `figure` | Appendix 4, p.10 | the damage diagram (gate `full`, curated description) |
# | `option` | Appendix 5 | one option: `.N category — sub-option` (levels carried down) |
# | `option_table_note` | Appendix 5, Table 1 | "As per GISIS nomenclatures" (the table has no options) |
#
# **Prose erratum (ADR-022).** Paragraph 7 ends "…completing all the asterisked fields in appendices 1 and 2 *and as much
# of the consequence data in appendix 3, as possible*." The same circular (para. 8 .2/.3) and the annex itself put the
# consequence data in **Appendix 2** (group *4 Consequences*, fields 2.4.1–2.4.15), while Appendix 3 holds casualty
# analysis data (accident events, contributing factors) and has no consequence field. The contradicting clause is
# excluded (never corrected); the rest of the sentence — the rule on the asterisked minimum fields — is kept.
#
# **Empty option.** Table 22 prints the code `.17` with no text in its row (between `.16 Inappropriate peer pressure`
# and the *Manning* group). There is nothing to retrieve: excluded with its reason, visible in the coverage audit.
#
# **Access (rbac_mapping §4).** Every unit is level 1 / Operations. The keyword pre-filter of ADR-021 is kept as a
# check: every unit that mentions money or finance terms gets a reviewed decision with a reason code.

# %% cell 51
# =========================================================
# 9.1 Rendering rules (one line per field / option, table names resolved)
# =========================================================
MINIMUM_SUFFIX = " (minimum field for the first report)"
FIELD_COLUMNS = "Field number | Field description | Field value type"          # the printed column headers (p.5)
NOTE_TEXT = {m: t for m, t in note_registry_df[["marker", "text"]].values}
VALUE_TOKEN_RE = {"1": re.compile(r"\bAuto\b"), "2": re.compile(r"\bY/N/U\b"), "3": re.compile(r"\bM/F/U\b")}


def resolve_tables(value: str) -> str:
    """'See table 13 (multi-choice)' -> 'See table 13 (Oil cargo/Bunker type & quantity) (multi-choice)'."""
    return TABLE_REF_RE.sub(lambda m: f"{m.group(0)} ({TABLE_TITLE[int(m.group(1))]})", value)


def field_line(f) -> str:
    line = f"{f['code_printed']} {f['description']}"
    if f["value_type"]:
        line += f" — value type: {resolve_tables(f['value_type'])}"
    return line + (MINIMUM_SUFFIX if f["minimum"] else "")


def field_notes(value_types) -> list[str]:
    """'Note: …' lines for the footnotes 1–3 whose token appears in these value types (plan §5.5)."""
    vt = " ".join(v for v in value_types if v)
    return [f"Note: {NOTE_TEXT[m]}" for m, rx in VALUE_TOKEN_RE.items() if rx.search(vt)]


def option_line(o) -> str:
    return f"{o['code']} {o['label']}".strip()


def a4_item_line(it) -> str:
    return f"{it['item_no']} {it['text']}" if it["kind"] == "item" else it["text"]


def dnr_lines(section: int) -> list[str]:
    """The 'Direct Natural Resources Damages' table of section 6, one line per printed group."""
    out, label, opts = [], None, []

    def flush():
        if label is not None or opts:
            head = label if label is not None else "(no label printed)"
            out.append(f"{head} " + "; ".join(opts) if opts else head)

    for r in dnr_df[dnr_df["section"] == section].itertuples():
        if isinstance(r.label, str) and r.label:      # a printed group label starts a group
            flush(); label, opts = r.label, []
        elif r.code == ".1" and opts:                 # numbering restarts without a label: a new, untitled group
            flush(); label, opts = None, [f"{r.code} {r.text}"]
        else:
            opts.append(f"{r.code} {r.text}")
    flush()
    return out


fields_by_id = fields_df.set_index("field_id")
print(field_line(fields_by_id.loc["2.1.1"]))
print(field_line(fields_by_id.loc["2.4.14"]))
print(field_line(fields_by_id.loc["3.2.22"]))
print(field_notes(fields_df.loc[fields_df["appendix"] == 2, "value_type"]))
print(dnr_lines(6))

# %% cell 52
# =========================================================
# 9.2 Units (+ prose erratum, empty option)
# =========================================================
PROSE_ERRATA = [{
    "unit_id": "para_07",
    "removed": " and as much of the consequence data in appendix 3, as possible",
    "evidence": ("Circular para. 8 .2: Appendix 2 requires '… casualty data and consequences'; para. 8 .3: Appendix 3 "
                 "requires casualty analysis data (accidental events and contributing factors); the consequence fields are "
                 "Appendix 2, group '4 Consequences' (2.4.1–2.4.15, Annex p.3). Appendix 3 has no consequence field."),
}]
EXCLUDED_ITEMS = [{"kind": "empty_option", "ref": oid, "page_number": int(p), "reason": "code printed without any text in its row"}
                  for oid, p in options_df.loc[options_df["empty"], ["option_id", "page_number"]].values]

units = []


def add_unit(**u):
    units.append({"title": None, "subsection_path": [], "table_no": None, "figure_id": None, "field_id": None,
                  "option_id": None, "group_key": None, "blocks": None, "block_context": None, "provenance": "extracted",
                  "flag": None, **DOCUMENT_ACCESS, **u})


for p in paragraphs_df.itertuples():
    text = p.text
    for e in (e for e in PROSE_ERRATA if e["unit_id"] == p.paragraph_id):
        assert text.count(e["removed"]) == 1, f"Erratum text of {p.paragraph_id} not found exactly once."
        text = text.replace(e["removed"], "")
    add_unit(unit_id=p.paragraph_id, unit_type="paragraph", logical_unit=p.paragraph_id, content=text,
             section=CIRCULAR_SECTION, page_start=p.page_start, page_end=p.page_end, group_key=("circular",))

star = note_registry_df.set_index("marker").loc["*"]
add_unit(unit_id="note_star", unit_type="note", logical_unit="note_circular_series",
         content=f"Note to the heading \"Casualty-related matters\": {star['text']}", section=CIRCULAR_SECTION,
         subsection_path=['Footnote to "Casualty-related matters"'], title="Joint MSC-MEPC circular series",
         page_start=int(star["page_number"]), page_end=int(star["page_number"]), group_key=("note",))

for f in fields_df.to_dict("records"):
    add_unit(unit_id=f"field_{f['field_id'].replace('.', '_')}", unit_type="field",
             logical_unit=f"app{f['appendix']}_g{f['group']}", content=field_line(f), section=f["section"],
             subsection_path=f["subsection_path"], field_id=f["field_id"], page_start=f["page_number"],
             page_end=f["page_number"], group_key=("field", f["appendix"], f["group"]),
             title=f"Appendix {f['appendix']} > {f['subsection_path'][0]}")

for sec, s in a4_sections.items():
    items = a4_items_df[a4_items_df["section"] == sec]
    blocks, context, current_ctx = [], [], None
    for b, grp in items.groupby("block", sort=True):
        recs = grp.to_dict("records")
        if recs[0]["kind"] == "subheading":
            current_ctx = recs[0]["text"]
        blocks.append("\n".join(a4_item_line(it) for it in recs))
        context.append(current_ctx if recs[0]["kind"] != "subheading" else None)
    if sec in set(dnr_df["section"]):
        blocks.append("Direct Natural Resources Damages:\n" + "\n".join(dnr_lines(sec)))
        context.append(None)
    header = f"Section {sec} — If {s['condition']}"
    pages = items["page_number"].tolist() + dnr_df.loc[dnr_df["section"] == sec, "page_number"].tolist() + [s["page_number"]]
    add_unit(unit_id=f"a4_section_{sec}", unit_type="a4_section", logical_unit=f"app4_s{sec}",
             content=header + "\n" + "\n".join(blocks), section=APPENDIX_SECTION[4], subsection_path=[f"Section {sec}"],
             title=f"Appendix 4 > Section {sec}", page_start=min(pages), page_end=max(pages),
             group_key=("a4", sec), blocks=blocks, block_context=context)

g = figure_gate_df.iloc[0]
add_unit(unit_id=g["figure_id"], unit_type="figure", logical_unit=g["figure_id"],
         content=g["description"], section=APPENDIX_SECTION[4], subsection_path=["Section 2", "Damage diagram"],
         title="Appendix 4 > Section 2 > Damage diagram", figure_id=g["figure_id"], page_start=10, page_end=10,
         provenance=g["provenance"], group_key=("figure",))

t1 = option_tables_df.set_index("table_no").loc[1]
add_unit(unit_id="table_01_note", unit_type="option_table_note", logical_unit="table_01", content=t1["note"],
         section=APPENDIX_SECTION[5], subsection_path=[f"Table 1 — {TABLE_TITLE[1]}"], table_no=1,
         title=f"Table 1 — {TABLE_TITLE[1]}", page_start=int(t1["page_start"]), page_end=int(t1["page_start"]),
         group_key=("options", 1))

for o in options_df[~options_df["empty"]].to_dict("records"):
    add_unit(unit_id=f"option_{o['option_id']}", unit_type="option", logical_unit=f"table_{o['table_no']:02d}",
             content=option_line(o), section=o["section"], subsection_path=o["subsection_path"],
             table_no=o["table_no"], option_id=o["option_id"], page_start=o["page_number"], page_end=o["page_number"],
             group_key=("options", o["table_no"]), title=f"Table {o['table_no']} — {TABLE_TITLE[o['table_no']]}")

units_df = pd.DataFrame(units)
units_df["table_no"] = units_df["table_no"].astype("Int64")
units_df["subsection"] = units_df["subsection_path"].map(lambda p: p[0] if p else None)
units_df["char_count"] = units_df["content"].str.len()
errata_df = pd.DataFrame(PROSE_ERRATA)
excluded_df = pd.DataFrame(EXCLUDED_ITEMS)

print("Units:", len(units_df), units_df["unit_type"].value_counts().to_dict())
print("\nPara 7 after the erratum:\n", units_df.set_index("unit_id").at["para_07", "content"])
print("\nSection 6:\n", units_df.set_index("unit_id").at["a4_section_6", "content"])
print("\nExcluded:", EXCLUDED_ITEMS)

# %% cell 53
# =========================================================
# 9.3 Access control check (rbac_mapping §4 / ADR-021 pre-filter)
# =========================================================
FINANCE_RE = re.compile(r"\b(?:financ\w*|revenue|cost\w*|budget\w*|profit\w*|econom\w*|price\w*|fees?|salar\w*|"
                        r"invoice\w*|payment\w*|tariff\w*|market\w*|SDR|EUR|USD)\b", re.IGNORECASE)
units_df["finance_terms"] = units_df["content"].map(lambda t: sorted({m.lower() for m in FINANCE_RE.findall(t)}))
candidates = units_df[units_df["finance_terms"].map(len) > 0]

# reviewed decisions (2026-09-26): all candidates are names of options in a public IMO reporting form
REVIEWED_ACCESS = {
    "option_t23_1": "form_option_name",     # 'Economic conditions' (management contributing factor)
    "option_t23_2": "form_option_name",     # 'Market change'
    "option_t23_16": "form_option_name",    # 'Cross-pressure from schedule and economy'
    "option_t23_18": "form_option_name",    # 'Pressure to keep schedule and costs'
}
access_df = candidates[["unit_id", "unit_type", "finance_terms", "content"]].assign(
    access_code=candidates["unit_id"].map(REVIEWED_ACCESS), sensitivity_level=1, department="Operations")
with pd.option_context("display.max_colwidth", 90):
    display(access_df)
assert set(candidates["unit_id"]) == set(REVIEWED_ACCESS), sorted(candidates["unit_id"])

# %% cell 54
# =========================================================
# 9.4 Phase 9 validation
# =========================================================
assert units_df["unit_id"].is_unique
assert units_df["content"].str.strip().ne("").all()
assert (units_df["sensitivity_level"] == 1).all() and (units_df["department"] == "Operations").all(), "rbac_mapping §4"
assert units_df["department"].isin(KNOWN_DEPARTMENTS).all()
assert units_df["flag"].isna().all(), "No unit may stay flagged."
REVIEWED_UNITS = {"option": 552, "field": 117, "paragraph": 10, "a4_section": 7, "note": 1, "figure": 1,
                  "option_table_note": 1}
assert units_df["unit_type"].value_counts().to_dict() == REVIEWED_UNITS
# every field / non-empty option / A4 item is represented once
assert sorted(units_df["field_id"].dropna()) == sorted(fields_df["field_id"])
assert sorted(units_df["option_id"].dropna()) == sorted(options_df.loc[~options_df["empty"], "option_id"])
a4_text = "\n".join(units_df.loc[units_df["unit_type"] == "a4_section", "content"])
for it in a4_items_df.itertuples():
    assert a4_item_line(it._asdict()) in a4_text, f"A4 item lost: {it.item_no} {it.text[:40]}"
# errata applied exactly once, never corrected
para7 = units_df.set_index("unit_id").at["para_07", "content"]
assert PROSE_ERRATA[0]["removed"].strip() not in para7 and para7.endswith("asterisked fields in appendices 1 and 2.")
assert "value type" not in units_df.set_index("field_id").at["3.2.22", "content"]
assert len(excluded_df) == 1 and excluded_df["ref"].tolist() == ["t22_17"]
print("✅ Phase 9 validation passed.")
print("Units:", REVIEWED_UNITS, "| access: all level 1 / Operations | errata: prose 1, field 1 | excluded empty option: 1")

# %% [markdown] cell 55
# # Phase 10 — Duplicate Detection (within-source and cross-source)
#
# Deterministic, no embeddings (ADR-010 / ADR-019), same thresholds as the HbR notebook:
#
# 1. exact duplicates by normalized-text hash;
# 2. candidate blocking by unit family + TF-IDF character n-gram cosine (≥ 0.50);
# 3. **item-level** comparison with `difflib`: an item is *covered* when it is repeated (ratio ≥ 0.90) or paraphrased
#    (≥ 0.75) **without any new content word**. Items: sentences for paragraphs and notes, one line per item block for
#    the Appendix 4 sections, the field line / option line itself for fields and options.
#
# **Within-source** the document repeats itself **by design**: the same option labels close many tables ("Other",
# "Unknown"), the same fields appear in several Appendix 3 groups ("Description of accidental event", "Operational
# contributing factors — See table 22"), and Appendix 4 sections 2 and 3 ask for the same ship dimensions (Lpp, B, D),
# section 3 even twice (fully loaded condition / condition at time of loss). Field and option lines are therefore
# compared **without their code** (`.25 Description …` vs `.4 Description …`). **Cross-source** is checked against every
# cleaned unit of the five existing sources (LPI Methodology, LPI Connecting to Compete, FBL, Suez Notes, HbR).
# Two different field or option lines with similar wording ("hours of rest in last 24 hours" / "… in last 7 days",
# "Fails to open" / "Fails open") are recorded as `similar_wording_distinct_value`: they are different values of the
# form, never duplicates. The unit `content` is never modified in this phase.

# %% cell 56
# =========================================================
# 10.1 Comparison normalization, items, content tokens
# =========================================================
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

CANDIDATE_SIM = 0.50        # TF-IDF (char 3–5 grams) cosine to enter the detailed comparison
SENTENCE_MATCH = 0.90       # difflib ratio: item repeated (near-)verbatim
PARAPHRASE_MATCH = 0.75     # ratio for a rephrased item that adds NO new content word

SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z‘“\"(])")
STOPWORDS = set("""the a an of and or to in for on by with from as at is are be that this these those which its their it
into than more most such can may also both each other has have was were not but between over across while within through
see table value type field""".split())
LEADING_CODE_RE = re.compile(r"^\.\d+(?:\.\d+)?\*?\s+")


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


FAMILY = {"paragraph": "prose", "note": "prose", "figure": "prose", "option_table_note": "prose",
          "a4_section": "form_items", "field": "form_line", "option": "form_line"}


def items_of(u: dict) -> list[str]:
    if u["unit_type"] in ("field", "option"):
        return [LEADING_CODE_RE.sub("", u["content"])]          # compared without its code
    if u["unit_type"] == "a4_section":
        return [l for l in u["content"].split("\n")[1:] if l.strip()]   # one line per item (header excluded)
    return sentences(u["content"])


def compare_text(u: dict) -> str:
    return " ".join(items_of(u))


assert items_of({"unit_type": "field", "content": ".25 Description of accidental event — value type: Text"}) == \
    ["Description of accidental event — value type: Text"]
assert LEADING_CODE_RE.sub("", ".4.1 x") == "x" and LEADING_CODE_RE.sub("", ".1* IMO number") == "IMO number"
print("Thresholds:", {"CANDIDATE_SIM": CANDIDATE_SIM, "SENTENCE_MATCH": SENTENCE_MATCH, "PARAPHRASE_MATCH": PARAPHRASE_MATCH})

# %% cell 57
# =========================================================
# 10.2 Reference corpus: cleaned units of the five existing sources
# =========================================================
# Older cleaned files store a plain list of units; LPI Connecting to Compete and HbR store {source, units, …};
# the FBL units use `text`; the Suez Notes are a plain text file (one note per "-" item).

def load_reference_units() -> list[dict]:
    refs = []
    meth = json.loads((CLEANED_DIR / "LPI_Methodology_logical_units.json").read_text(encoding="utf-8"))
    refs += [{"source": "LPI_Methodology", "unit_id": u["unit_id"], "unit_type": u["unit_type"], "content": u["content"]}
             for u in meth]
    for name in ("LPI_Connecting_to_Compete", "HbR_Annual_report_2025"):
        data = json.loads((CLEANED_DIR / f"{name}_logical_units.json").read_text(encoding="utf-8"))
        refs += [{"source": name, "unit_id": u["unit_id"], "unit_type": u["unit_type"], "content": u["content"]}
                 for u in data["units"]]
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
assert {r["source"] for r in reference_units} == {"LPI_Methodology", "LPI_Connecting_to_Compete", "HbR_Annual_report_2025",
                                                  "FBL_template", "Suez_Notes"}

# %% cell 58
# =========================================================
# 10.3 Exact hash duplicates + candidate blocking
# =========================================================
units_df["norm_hash"] = [text_hash(compare_text(u)) for u in units_df.to_dict("records")]
unit_dicts_all = units_df.to_dict("records")
ref_hash = {text_hash(r["content"]): (r["source"], r["unit_id"]) for r in reference_units}

within_exact = units_df[units_df.duplicated("norm_hash", keep=False)]
cross_exact = units_df[units_df["norm_hash"].isin(ref_hash)]
print(f"Exact within-source repeats (code ignored): {len(within_exact)} units in "
      f"{within_exact['norm_hash'].nunique()} groups | exact cross-source duplicates: {len(cross_exact)}")

ours = [cmp_norm(compare_text(u)) for u in unit_dicts_all]
refs = [cmp_norm(r["content"]) for r in reference_units]
vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5)).fit(ours + refs)
V_ours, V_refs = vectorizer.transform(ours), vectorizer.transform(refs)
SIM_cross = cosine_similarity(V_ours, V_refs)
SIM_within = cosine_similarity(V_ours)
np.fill_diagonal(SIM_within, 0.0)

candidates = []
for i, u in enumerate(unit_dicts_all):
    fam = FAMILY[u["unit_type"]]
    for j in np.nonzero(SIM_cross[i] >= CANDIDATE_SIM)[0]:
        candidates.append(("cross", i, int(j), float(SIM_cross[i, j])))
    for j in np.nonzero(SIM_within[i] >= CANDIDATE_SIM)[0]:
        if FAMILY[unit_dicts_all[j]["unit_type"]] == fam:
            candidates.append(("within", i, int(j), float(SIM_within[i, j])))
print(f"Candidate pairs: {len(candidates)} (cross={sum(c[0] == 'cross' for c in candidates)}, "
      f"within={sum(c[0] == 'within' for c in candidates)})")

# %% cell 59
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
        items = compare_items(items_of(u), items_of(v), compare_text(v))
        exact = u["norm_hash"] == v["norm_hash"]
    pair_records.append({
        "scope": scope, "unit_id": u["unit_id"], "unit_type": u["unit_type"], "section": u["section"],
        "candidate_source": other["source"], "candidate_unit_id": other["unit_id"], "candidate_type": other["unit_type"],
        "similarity_score": round(sim, 3), "exact": bool(exact),
        "items_total": len(items), "items_covered": sum(x["covered"] for x in items),
        "uncovered_items": [x for x in items if not x["covered"]], "item_details": items,
    })
pairs_df = pd.DataFrame(pair_records, columns=["scope", "unit_id", "unit_type", "section", "candidate_source",
                                               "candidate_unit_id", "candidate_type", "similarity_score", "exact",
                                               "items_total", "items_covered", "uncovered_items", "item_details"])


def relationship(p) -> str:
    if p["exact"]:
        return "exact_duplicate"
    if p["scope"] == "within" and FAMILY[p["unit_type"]] == "form_line":
        # two different field / option lines with similar wording ("hours of rest in last 24 hours" vs "… 7 days",
        # "Fails to open" vs "Fails open"): different values of the form, never duplicates
        return "similar_wording_distinct_value"
    if p["items_covered"] == p["items_total"]:
        return "near_duplicate"
    if p["items_covered"]:
        return "contextual_duplicate"
    return "unique"


pairs_df["relationship"] = pairs_df.apply(relationship, axis=1) if len(pairs_df) else []
pairs_df["unique_information_flag"] = pairs_df["items_covered"] < pairs_df["items_total"]

print("Relationships:")
display(pairs_df.groupby(["scope", "unit_type", "relationship"]).size().rename("pairs"))
print("Cross-source candidates:")
with pd.option_context("display.max_rows", None, "display.max_colwidth", 70):
    display(pairs_df[pairs_df["scope"] == "cross"][["unit_id", "candidate_source", "candidate_unit_id",
                                                     "similarity_score", "items_covered", "items_total", "relationship"]])

# %% [markdown] cell 60
# # Phase 11 — Duplicate Decisions
#
# Canonical-source policy (ADR-019), applied to a reporting form:
#
# - **Every unit of this circular is canonical.** Unlike the HbR report there is no summary part: the only
#   restatement is the p.3 list of appendices/tables, which is metadata (3.6), not a unit.
# - A repeat **within the document** is kept (`keep_contextual`): the same option label closing different tables
#   ("Other", "Unknown", "None"), the same field in different Appendix 3 event groups, and the same ship dimensions in
#   different Appendix 4 conditions each **mean something only in their own table / group / condition** — removing one
#   would remove a value from a table or a field from a form.
# - Cross-source: a candidate is acted on only when its items are covered (none are: see 10.4).
#
# Every decision, every candidate pair and every removed item (none) goes into the duplicate audit.

# %% cell 61
# =========================================================
# 11.1 Unit decisions
# =========================================================
decisions = []
for u in unit_dicts_all:
    uid = u["unit_id"]
    rec = {"unit_id": uid, "unit_type": u["unit_type"], "section": u["section"], "relationship": "unique",
           "action": "keep", "canonical_unit_ids": [], "canonical_source": None, "removed_items": [],
           "reason": "No candidate duplicate."}
    ps = pairs_df[pairs_df["unit_id"] == uid]
    within = ps[(ps["scope"] == "within") & (ps["items_covered"] > 0)
                & (ps["relationship"] != "similar_wording_distinct_value")]
    cross = ps[(ps["scope"] == "cross") & (ps["items_covered"] > 0)]
    assert cross.empty, f"{uid}: covered cross-source items need a decision: {cross[['candidate_unit_id']].values}"
    if not within.empty:
        others = sorted(within["candidate_unit_id"])
        rec.update(relationship="exact_duplicate" if within["exact"].any() else "near_duplicate",
                   action="keep_contextual", canonical_unit_ids=[uid], canonical_source=SOURCE_NAME,
                   reason=f"Repeated by design in {len(others)} other unit(s) of the form (e.g. {others[0]}); "
                          "each occurrence belongs to its own table / field group / condition.")
    elif not ps.empty:
        rec["reason"] = f"{len(ps)} candidate pair(s), no covered item."
    decisions.append(rec)
decisions_df = pd.DataFrame(decisions)

audit_pairs_df = pairs_df.assign(
    source_document=SOURCE_NAME,
    normalized_hash=pairs_df["unit_id"].map(units_df.set_index("unit_id")["norm_hash"]),
)[["source_document", "scope", "unit_id", "unit_type", "candidate_source", "candidate_unit_id", "candidate_type",
   "relationship", "similarity_score", "exact", "items_covered", "items_total", "unique_information_flag",
   "normalized_hash", "uncovered_items"]]

print("Unit-level decisions:")
display(decisions_df.groupby(["unit_type", "relationship", "action"]).size().rename("units"))
examples = within_exact.groupby("norm_hash")["content"].agg(lambda s: f"{len(s)}× {LEADING_CODE_RE.sub('', s.iloc[0])[:70]}")
print("Exact repeats (code ignored):")
for e in examples.sort_values(): print("  ", e)

# %% cell 62
# =========================================================
# 11.2 Post-dedup corpus
# =========================================================
# Nothing is suppressed or trimmed; the frame is copied so that later phases work on the post-dedup units.
dec_by_id = decisions_df.set_index("unit_id")
final_units_df = units_df[~units_df["unit_id"].map(dec_by_id["action"]).isin(["suppress_duplicate"])].copy()
final_units_df["dedup_action"] = final_units_df["unit_id"].map(dec_by_id["action"])
final_units_df = final_units_df.reset_index(drop=True)
print(f"Units: {len(units_df)} -> post-dedup: {len(final_units_df)}")

# %% [markdown] cell 63
# # Phase 12 — Final Logical-Unit QA
#
# Gate before chunking: every unit kept, every field / option / Appendix 4 item still represented, access levels
# intact, nothing flagged or pending, and the decisions match the reviewed snapshot.

# %% cell 64
# =========================================================
# 12.1 Coverage, access and decision checks + reviewed snapshot
# =========================================================
suppressed = decisions_df[decisions_df["action"] == "suppress_duplicate"]
trimmed = decisions_df[decisions_df["action"] == "trim_duplicate_sentences"]
kept_contextual = decisions_df[decisions_df["action"] == "keep_contextual"]

assert set(final_units_df["unit_id"]) == set(units_df["unit_id"]), "No unit may be lost."
assert suppressed.empty and trimmed.empty, "A form repeats itself by design: nothing is suppressed or trimmed."
assert "manual_review" not in set(decisions_df["action"])
assert (final_units_df["sensitivity_level"] == 1).all() and (final_units_df["department"] == "Operations").all()
assert final_units_df["flag"].isna().all()
assert not pairs_df.loc[pairs_df["scope"] == "cross", "items_covered"].any(), "No cross-source item is covered."

# ---- reviewed snapshot (2026-09-26) ----
REVIEWED_KEEP_CONTEXTUAL = {"field": 11, "option": 44}      # the 12 exact-repeat groups of 11.1
REVIEWED_CROSS_CANDIDATES = sorted([("option_t23_76", "P377"), ("option_t24_2", "suez_note_4")])
REVIEWED_MANUAL_REVIEW = []
assert kept_contextual.groupby("unit_type").size().to_dict() == REVIEWED_KEEP_CONTEXTUAL, \
    kept_contextual.groupby("unit_type").size().to_dict()
assert sorted(map(tuple, pairs_df.loc[pairs_df["scope"] == "cross", ["unit_id", "candidate_unit_id"]].values)) \
    == REVIEWED_CROSS_CANDIDATES

print("✅ Final logical-unit QA passed.")
print(f"Units: {len(units_df)} -> kept {len(final_units_df)} | suppressed 0 | trimmed 0 | "
      f"kept contextual {len(kept_contextual)} {REVIEWED_KEEP_CONTEXTUAL} | cross-source candidates "
      f"{len(REVIEWED_CROSS_CANDIDATES)} (unique) | manual review pending 0")
display(final_units_df.groupby("unit_type").size().rename("kept units"))

# %% [markdown] cell 65
# # Phase 13 — Save Extracted + Cleaned Artifacts
#
# One file per layer:
# - `extracted/IMO_MSC-MEPC_3_Circ_4_Rev_1_extracted.json` — raw structured layer: page classes, section map, contents
#   cross-check, subscripts, footnotes, circular paragraphs, **the machine-readable field catalogue** (groups, fields
#   with minimum flag / value type / footnote refs / option-table refs, the 30 option tables with their options and
#   levels, and the cross-reference checks), Appendix 4 (conditions with their field references, items, blocks, the
#   damages table), the figure gate, errata, excluded items and access decisions
# - `cleaned/IMO_MSC-MEPC_3_Circ_4_Rev_1_logical_units.json` — **the single cleaned file**: `source`, `units` and
#   `duplicate_audit`; Phase 19 adds `coverage_audit`
#
# The field catalogue is the planned schema source for synthetic incidents (ARCHITECTURE §3): it is a file only, no
# database change. Each file is reloaded from disk and re-validated.

# %% cell 66
# =========================================================
# 13. Save extracted + cleaned artifacts, then reload and validate
# =========================================================
def to_records(df: pd.DataFrame) -> list[dict]:
    return json.loads(df.to_json(orient="records", force_ascii=False, default_handler=str))


def json_default(o):
    """numpy scalars (np.int64 …) -> Python scalars."""
    return o.item() if hasattr(o, "item") else str(o)


EXTRACTED_PATH = EXTRACTED_DIR / f"{SOURCE_NAME}_extracted.json"
LOGICAL_UNITS_PATH = CLEANED_DIR / f"{SOURCE_NAME}_logical_units.json"     # the ONE cleaned file of this source

field_catalogue = {
    "description": "Machine-readable field catalogue of MSC-MEPC.3/Circ.4/Rev.1 (Appendices 1–3 fields, Appendix 5 "
                   "option tables). field_id = appendix.group.field (group = order within the appendix; for "
                   "Appendix 2 it equals the printed group number, so '2.4.9' is the printed reference).",
    "groups": to_records(groups_df[["appendix", "group", "group_number_printed", "group_title", "group_label", "page_number"]]),
    "fields": to_records(fields_df.assign(
        footnote_refs=fields_df["value_markers"],
        table_titles=fields_df["table_refs"].map(lambda ts: [TABLE_TITLE[t] for t in ts]),
        group_label=fields_df["subsection_path"].str[0],
    )[["field_id", "appendix", "group", "group_label", "field_no", "code_printed", "minimum", "description",
       "value_type", "value_type_printed", "value_type_excluded", "footnote_refs", "table_refs", "table_titles",
       "multi_choice", "page_number"]]),
    "value_type_notes": {VALUE_TYPE_NOTES[m]: NOTE_TEXT[m] for m in VALUE_TYPE_NOTES},
    "option_tables": [
        {**{k: t[k] for k in ("table_no", "title", "kind", "levels", "note", "header", "groups", "page_start")},
         "options": to_records(options_df.loc[options_df["table_no"] == t["table_no"],
                                              ["option_id", "code", "group", "level_1", "level_2", "level_3", "label",
                                               "carried", "empty", "page_number"]])}
        for t in option_tables_df.to_dict("records")],
    "references": to_records(references_df),
}
extracted_payload = {
    "source": {**source_metadata, "sha256": SOURCE_SHA256, "pages": int(len(pages_df)), "title": DISPLAY_TITLE,
               "printed_date": PRINTED_DATE},
    "page_classification": to_records(page_class_df[["page_number", "page_class", "keep_for_retrieval", "reason"]]),
    "section_map": to_records(section_map.drop(columns=["rows"])),
    "contents_check": to_records(contents_check),
    "subscripts": to_records(subscripts_df),
    "split_lines": [list(x) for x in sorted(SPLIT_LINES)],
    "notes": to_records(note_registry_df[["marker", "page_number", "anchor_text", "policy", "text"]]),
    "paragraphs": to_records(paragraphs_df[["paragraph_id", "paragraph_no", "page_start", "page_end", "sub_items", "text"]]),
    "field_catalogue": field_catalogue,
    "appendix_4": {
        "sections": [{k: v for k, v in s.items()} for s in a4_sections.values()],
        "items": to_records(a4_items_df.drop(columns=["row_ids"])),
        "damages_table": to_records(dnr_df.drop(columns=["row_id"])),
    },
    "graphics": {"gate": to_records(figure_gate_df), "images": to_records(images_df)},
    "errata": {"field": [{"field_id": k, **v} for k, v in FIELD_ERRATA.items()], "prose": to_records(errata_df)},
    "excluded_items": to_records(excluded_df),
    "access_decisions": to_records(access_df),
}
UNIT_FIELDS = ["unit_id", "unit_type", "logical_unit", "title", "content", "section", "subsection", "subsection_path",
               "page_start", "page_end", "table_no", "figure_id", "field_id", "option_id", "provenance", "flag",
               "dedup_action", "sensitivity_level", "department"]
duplicate_audit = {
    "thresholds": {"CANDIDATE_SIM": CANDIDATE_SIM, "SENTENCE_MATCH": SENTENCE_MATCH, "PARAPHRASE_MATCH": PARAPHRASE_MATCH,
                   "form_lines": "field / option lines compared without their code; within-source only exact repeats count"},
    "reference": sorted({r["source"] for r in reference_units}),
    "canonical_policy": {SOURCE_NAME: "every unit canonical (no summary part); the p.3 list of appendices/tables is metadata"},
    "unit_decisions": to_records(decisions_df),
    "pairs": to_records(audit_pairs_df[audit_pairs_df["relationship"] != "similar_wording_distinct_value"]),
    "pair_counts": pairs_df.groupby(["scope", "relationship"]).size().rename("pairs").reset_index().to_dict("records"),
}

EXTRACTED_PATH.write_text(json.dumps(extracted_payload, ensure_ascii=False, indent=1, default=json_default), encoding="utf-8")
cleaned_payload = {
    "source": {**source_metadata, "sha256": SOURCE_SHA256},
    "units": to_records(final_units_df[UNIT_FIELDS]),
    "duplicate_audit": duplicate_audit,
}
LOGICAL_UNITS_PATH.write_text(json.dumps(cleaned_payload, ensure_ascii=False, indent=1, default=json_default), encoding="utf-8")

# ---- reload + validate ----
re_extracted = json.loads(EXTRACTED_PATH.read_text(encoding="utf-8"))
re_cleaned = json.loads(LOGICAL_UNITS_PATH.read_text(encoding="utf-8"))
re_units, re_audit = re_cleaned["units"], re_cleaned["duplicate_audit"]
fc = re_extracted["field_catalogue"]

assert re_extracted["source"]["sha256"] == SOURCE_SHA256
assert len(fc["fields"]) == len(fields_df) == 117 and len(fc["option_tables"]) == 30
assert sum(len(t["options"]) for t in fc["option_tables"]) == len(options_df)
assert {f["field_id"] for f in fc["fields"] if f["minimum"]} == set(MINIMUM_FIELDS)
assert all(t in range(1, 31) for f in fc["fields"] for t in f["table_refs"])
assert len(re_extracted["paragraphs"]) == 10 and len(re_extracted["appendix_4"]["sections"]) == 7
assert [u["unit_id"] for u in re_units] == final_units_df["unit_id"].tolist()
assert all(u["content"] == c for u, c in zip(re_units, final_units_df["content"]))
assert all(u["sensitivity_level"] == 1 and u["department"] == "Operations" for u in re_units)
assert len(re_audit["unit_decisions"]) == len(units_df)
assert sorted(p.name for p in CLEANED_DIR.glob(f"{SOURCE_NAME}_*")) == [LOGICAL_UNITS_PATH.name], \
    "The cleaned layer of this source must be exactly one file."
for p in (EXTRACTED_PATH, LOGICAL_UNITS_PATH):
    print(f"Saved + reloaded: {p.name:50} {p.stat().st_size:>10,} bytes")
print("Field catalogue:", len(fc["fields"]), "fields |", len(fc["option_tables"]), "option tables |",
      sum(len(t["options"]) for t in fc["option_tables"]), "options |", len(fc["references"]), "references")

# %% [markdown] cell 67
# # Phase 14 — Semantic Chunking
#
# The chunk follows the **structure of the form**, and every chunk is self-contained (it names the document part it
# comes from):
#
# | Chunk type | One chunk = | Header written at the top of **every** part |
# |---|---|---|
# | `paragraph` | circular paragraphs, grouped while short (`MIN_CHUNK_CHARS`), never split | — (title = document title) |
# | `note` | the `*` footnote (joint MSC-MEPC circular series) | — |
# | `field_group` | one field group of Appendices 1–3, one line per field | `… Appendix N: <title> > <group>` + the printed column names; footnotes 1–3 as `Note:` when the part uses `Auto` / `Y/N/U` / `M/F/U` |
# | `a4_section` | one conditional section of Appendix 4 | `… Appendix 4: … > Section N` + its condition; a part that continues under a "For ship in …" sub-heading repeats it `(continued)` |
# | `figure` | the damage diagram | `… Appendix 4 … > Section 2 > Damage diagram` |
# | `option_table` | one option table of Appendix 5, one line per option | `… Appendix 5: … > Table N — <title>` (+ note / printed columns); a part that continues a group repeats `<group> (continued):` |
#
# **Balanced splits.** A group, section or table longer than `MAX_CHUNK_CHARS` is split into the **fewest parts that
# fit**, cut where the running size crosses equal fractions of the total — so the parts have (almost) the same size and
# there is never a large part plus a small remainder. An atomic Appendix 4 block (an item with its "If so:" follow-up)
# and a field / option line are never cut. No chunk mixes sections, groups, tables or access levels; no chunk is a
# fragment (< `FRAGMENT_MIN_CHARS`). `chunk_id` = `imo_mci_<logical_unit>_chunk_<part>`.

# %% cell 68
# =========================================================
# 14.1 Chunking rules
# =========================================================
CHUNK_SEPARATOR = "\n\n"
DOC_PREFIX = f"IMO {DOCUMENT_SYMBOL}, annex —"


def annex_header(section: str, path: list[str]) -> str:
    return f"{DOC_PREFIX} {section.replace('Annex — ', '')} > " + " > ".join(path)


def balanced_parts(pieces: list[str], fixed: int, sep: int = 1, limit: int = MAX_CHUNK_CHARS) -> list[list[int]]:
    """Split piece indexes into the fewest contiguous parts that fit `limit` (fixed = header/notes budget),
    cutting where the running size crosses k equal fractions of the total."""
    sizes = [len(p) + sep for p in pieces]
    total = sum(sizes)
    for k in range(1, len(pieces) + 1):
        bounds, acc, cut = [], 0, 1
        for i, s in enumerate(sizes):
            if cut < k and acc + s / 2 > total * cut / k and i > (bounds[-1] if bounds else 0):
                bounds.append(i); cut += 1
            acc += s
        parts = [list(range(a, b)) for a, b in zip([0, *bounds], [*bounds, len(pieces)])]
        if all(fixed + sum(sizes[i] for i in p) <= limit for p in parts):
            return parts
    raise AssertionError("A single piece does not fit in MAX_CHUNK_CHARS.")


def part_title(title: str, k: int, n: int) -> str:
    return title if n == 1 else f"{title} (part {k} of {n})"


def make_chunk(units: list[dict], unit_type: str, logical_unit: str, part: int, text: str, title: str) -> dict:
    first = units[0]
    return {
        "page": int(min(u["page_start"] for u in units)),
        "unit_type": unit_type, "logical_unit": logical_unit,
        "chunk_id": f"{CHUNK_PREFIX}_{logical_unit}_chunk_{part}",
        "section": first["section"], "subsection_path": list(first["subsection_path"]),
        "title": title, "text": text,
        "sensitivity_level": int(first["sensitivity_level"]), "department": first["department"],
        "source_unit_ids": [u["unit_id"] for u in units],
    }


assert balanced_parts(["a" * 10] * 10, fixed=0, sep=0, limit=50) == [[0, 1, 2, 3, 4], [5, 6, 7, 8, 9]]
assert [len(p) for p in balanced_parts(["a" * 10] * 11, fixed=0, sep=0, limit=50)] == [4, 3, 4] or \
       [len(p) for p in balanced_parts(["a" * 10] * 11, fixed=0, sep=0, limit=50)] == [4, 4, 3]
print("Chunk rules ready. DOC_PREFIX:", DOC_PREFIX)

# %% cell 69
# =========================================================
# 14.2 Circular chunks (paragraphs + footnote)
# =========================================================
unit_dicts = final_units_df.to_dict("records")
chunk_records = []

paragraph_units = [u for u in unit_dicts if u["unit_type"] == "paragraph"]
groups = []
for u in paragraph_units:
    if groups:
        size = len(CHUNK_SEPARATOR.join(x["content"] for x in groups[-1]))
        if size + len(CHUNK_SEPARATOR) + u["char_count"] <= MAX_CHUNK_CHARS and \
                (size < MIN_CHUNK_CHARS or u["char_count"] < MIN_CHUNK_CHARS):
            groups[-1].append(u)
            continue
    groups.append([u])
for g in groups:
    name = g[0]["logical_unit"] if len(g) == 1 else f"{g[0]['logical_unit']}_{g[-1]['logical_unit'].split('_')[-1]}"
    text = CHUNK_SEPARATOR.join(x["content"] for x in g)
    assert len(text) <= MAX_CHUNK_CHARS, "A circular paragraph never needs a split here."
    chunk_records.append(make_chunk(g, "paragraph", name, 1, text, title=DISPLAY_TITLE))

note = next(u for u in unit_dicts if u["unit_type"] == "note")
chunk_records.append(make_chunk([note], "note", note["logical_unit"], 1, note["content"], title=note["title"]))

print("Paragraph groups:", [[u["unit_id"] for u in g] for g in groups])
print(f"Circular chunks: {len(chunk_records)}")

# %% cell 70
# =========================================================
# 14.3 Field-group chunks (Appendices 1–3)
# =========================================================
field_units = [u for u in unit_dicts if u["unit_type"] == "field"]
vt_of = fields_df.set_index("field_id")["value_type"]
FIELD_HEADERS = {}
for (a, g), us in pd.DataFrame(field_units).groupby(
        [pd.Series([u["field_id"].split(".")[0] for u in field_units]), pd.Series([u["field_id"].split(".")[1] for u in field_units])],
        sort=False):
    us = us.to_dict("records")
    header = annex_header(us[0]["section"], us[0]["subsection_path"]) + "\n" + FIELD_COLUMNS
    lines = [u["content"] for u in us]
    worst_notes = len("\n".join(field_notes(vt_of[[u["field_id"] for u in us]])))
    parts = balanced_parts(lines, fixed=len(header) + 20 + worst_notes + 1)
    for k, idx in enumerate(parts, start=1):
        part_units = [us[i] for i in idx]
        notes = field_notes(vt_of[[u["field_id"] for u in part_units]])
        head = header if len(parts) == 1 else header.replace("\n", f" (part {k} of {len(parts)})\n", 1)
        text = head + "\n" + "\n".join(u["content"] for u in part_units) + ("\n" + "\n".join(notes) if notes else "")
        name = us[0]["logical_unit"]
        chunk_records.append(make_chunk(part_units, "field_group", name, k, text,
                                        title=part_title(us[0]["title"], k, len(parts))))
        FIELD_HEADERS[name] = header
    if len(parts) > 1:
        print(f"{us[0]['logical_unit']}: {len(us)} fields -> {len(parts)} balanced parts of {[len(p) for p in parts]} fields")

print("Field-group chunks:", sum(r["unit_type"] == "field_group" for r in chunk_records))

# %% cell 71
# =========================================================
# 14.4 Appendix 4 section chunks + the damage diagram
# =========================================================
for u in (u for u in unit_dicts if u["unit_type"] == "a4_section"):
    header = annex_header(u["section"], u["subsection_path"]) + "\n" + u["content"].split("\n", 1)[0]
    blocks, ctx = u["blocks"], u["block_context"]
    parts = balanced_parts(blocks, fixed=len(header) + 20 + max(len(c or "") + 13 for c in ctx) + 1)
    for k, idx in enumerate(parts, start=1):
        head = header if len(parts) == 1 else header.replace("\n", f" (part {k} of {len(parts)})\n", 1)
        body = [blocks[i] for i in idx]
        if k > 1 and ctx[idx[0]]:                                   # the part continues under a sub-heading
            body.insert(0, f"{ctx[idx[0]]} (continued)")
        chunk_records.append(make_chunk([u], "a4_section", u["logical_unit"], k, head + "\n" + "\n".join(body),
                                        title=part_title(u["title"], k, len(parts))))
    if len(parts) > 1:
        sizes = [sum(len(blocks[i]) + 1 for i in p) for p in parts]
        print(f"{u['unit_id']}: {len(blocks)} blocks -> {len(parts)} balanced parts of {sizes} chars")

fig = next(u for u in unit_dicts if u["unit_type"] == "figure")
chunk_records.append(make_chunk([fig], "figure", fig["logical_unit"], 1,
                                annex_header(fig["section"], fig["subsection_path"]) + "\n" + fig["content"],
                                title=fig["title"]))
print("Appendix 4 chunks:", sum(r["unit_type"] in ("a4_section", "figure") for r in chunk_records))

# %% cell 72
# =========================================================
# 14.5 Option-table chunks (Appendix 5)
# =========================================================
ot = option_tables_df.set_index("table_no")
BLANK_COLUMNS = {13: ["Quantity"], 14: ot.at[14, "header"][1:], 15: ["Quantity"]}
for tno in range(1, 31):
    us = [u for u in unit_dicts if u["unit_type"] in ("option", "option_table_note") and u["table_no"] == tno]
    t = ot.loc[tno]
    header = annex_header(us[0]["section"], us[0]["subsection_path"])
    extra = []
    if t["kind"] == "form":
        extra.append("Columns: " + " | ".join(t["header"]))
        extra.append("Blank fill-in column(s): " + ", ".join(BLANK_COLUMNS[tno]))
    header = "\n".join([header, *extra])
    if us[0]["unit_type"] == "option_table_note":               # Table 1: a note, no options
        chunk_records.append(make_chunk(us, "option_table", us[0]["logical_unit"], 1,
                                        header + "\n" + us[0]["content"], title=us[0]["title"]))
        continue
    opt = options_df.set_index("option_id")
    groups_of = [opt.at[u["option_id"], "group"] for u in us]
    lines = [u["content"] for u in us]
    parts = balanced_parts(lines, fixed=len(header) + 20 + 2 * max(len(str(g)) + 14 for g in groups_of))
    for k, idx in enumerate(parts, start=1):
        head = header if len(parts) == 1 else header.replace(
            header.split("\n")[0], header.split("\n")[0] + f" (part {k} of {len(parts)})", 1)
        body, last = [], None
        for i in idx:
            g = groups_of[i]
            if isinstance(g, str) and g != last:
                body.append(f"{g}:" if (i == 0 or groups_of[i - 1] != g) else f"{g} (continued):")
            last = g
            body.append(lines[i])
        chunk_records.append(make_chunk([us[i] for i in idx], "option_table", us[0]["logical_unit"], k,
                                        head + "\n" + "\n".join(body), title=part_title(us[0]["title"], k, len(parts))))
    if len(parts) > 1:
        print(f"Table {tno}: {len(us)} options -> {len(parts)} balanced parts of {[len(p) for p in parts]} options")

order_key = {"paragraph": 0, "note": 1, "field_group": 2, "a4_section": 3, "figure": 3, "option_table": 4}
chunk_records.sort(key=lambda r: (order_key[r["unit_type"]], r["page"], r["chunk_id"].rsplit("_", 1)[0],
                                  int(r["chunk_id"].rsplit("_", 1)[1])))
print(f"Kept units: {len(unit_dicts)} -> chunks: {len(chunk_records)}")
display(pd.Series([r["unit_type"] for r in chunk_records]).value_counts().rename("chunks"))
print("\nExample (Table 22, part 2):\n" + next(r["text"] for r in chunk_records if r["chunk_id"] == f"{CHUNK_PREFIX}_table_22_chunk_2")[:700])

# %% [markdown] cell 73
# # Phase 15 — Chunk Validation
#
# Size and ID checks (no fragment, nothing above the cap), content preservation of every unit (every field line,
# option line, Appendix 4 block, paragraph and note is in the chunks of its own unit), the header repeated in every
# part, balanced parts, no chunk crossing a section / group / table boundary, and no chunk mixing access levels.

# %% cell 74
# =========================================================
# 15.1 Size checks
# =========================================================
chunk_sizes = pd.Series([len(r["text"]) for r in chunk_records])
assert (chunk_sizes > 0).all(), "Empty chunk."
assert (chunk_sizes <= MAX_CHUNK_CHARS).all(), "A chunk exceeds MAX_CHUNK_CHARS."
assert (chunk_sizes >= FRAGMENT_MIN_CHARS).all(), \
    [(r["chunk_id"], r["text"]) for r in chunk_records if len(r["text"]) < FRAGMENT_MIN_CHARS]
chunk_ids = [r["chunk_id"] for r in chunk_records]
assert len(chunk_ids) == len(set(chunk_ids)), "Duplicate chunk_id."

# %% cell 75
# =========================================================
# 15.2 Content preservation + repeated headers + balanced parts
# =========================================================
texts_by_unit: dict[str, list[str]] = {}
for r in chunk_records:
    for uid in r["source_unit_ids"]:
        texts_by_unit.setdefault(uid, []).append(r["text"])
units_by_id = {u["unit_id"]: u for u in unit_dicts}

assert set(texts_by_unit) == set(units_by_id), "A kept unit is missing from the chunks."
for uid, u in units_by_id.items():
    joined = "\n".join(texts_by_unit[uid])
    pieces = u["blocks"] + [u["content"].split("\n", 1)[0]] if u["unit_type"] == "a4_section" else [u["content"]]
    for piece in pieces:
        assert piece in joined, f"Content of {uid} not preserved: {piece[:60]!r}"
    if u["unit_type"] == "field":                                     # a field is never cut between two chunks
        assert sum(u["content"] in t for t in texts_by_unit[uid]) == 1

by_lu: dict[str, list[dict]] = {}
for r in chunk_records:
    by_lu.setdefault(r["logical_unit"], []).append(r)
SPLIT_UNITS = {}
for lu, rs in by_lu.items():
    if len(rs) == 1:
        continue
    first_lines = {r["text"].split("\n")[0].rsplit(" (part ", 1)[0] for r in rs}
    assert len(first_lines) == 1, f"{lu}: the header is not repeated identically in every part."
    if rs[0]["unit_type"] in ("a4_section", "field_group") or (rs[0]["unit_type"] == "option_table"
                                                               and "Columns:" in rs[0]["text"]):
        second = {r["text"].split("\n")[1] for r in rs}
        assert len(second) == 1, f"{lu}: condition / column line not repeated."
    sizes = [len(r["text"]) for r in rs]
    assert max(sizes) / min(sizes) < 1.6, f"{lu}: unbalanced parts {sizes}"
    SPLIT_UNITS[lu] = sizes

# (continued) labels: every option group and every Appendix 4 sub-heading that runs into a new part is repeated
for lu, rs in by_lu.items():
    for r in rs[1:]:
        second_line = r["text"].split("\n")[2 if r["unit_type"] == "a4_section" else 1]
        if r["unit_type"] == "a4_section" and "(continued)" in second_line:
            assert second_line.startswith("For ship in")
print("Split logical units (part sizes):", SPLIT_UNITS)

# %% cell 76
# =========================================================
# 15.3 Provenance + access checks
# =========================================================
for r in chunk_records:
    us = [units_by_id[uid] for uid in r["source_unit_ids"]]
    assert len({u["section"] for u in us}) == 1, f"{r['chunk_id']} crosses a section."
    assert len({tuple(u["subsection_path"]) for u in us}) == 1, f"{r['chunk_id']} crosses a group / table."
    assert len({(u["sensitivity_level"], u["department"]) for u in us}) == 1, f"{r['chunk_id']} mixes access."
    assert (r["sensitivity_level"], r["department"]) == (1, "Operations"), "rbac_mapping §4"
    assert r["section"] and r["title"], f"{r['chunk_id']} lacks section/title."
    if r["unit_type"] == "option_table":
        assert len({u["table_no"] for u in us}) == 1, f"{r['chunk_id']} mixes tables."

# ---- reviewed snapshot (2026-09-26) ----
REVIEWED_CHUNKS = {"option_table": 33, "field_group": 14, "a4_section": 11, "paragraph": 9, "note": 1, "figure": 1}
assert pd.Series([r["unit_type"] for r in chunk_records]).value_counts().to_dict() == REVIEWED_CHUNKS
assert SPLIT_UNITS.keys() == {"app3_g2", "app4_s2", "app4_s3", "app4_s4", "table_12", "table_22", "table_23"}

SHORT_CHUNKS = [r["chunk_id"] for r in chunk_records if len(r["text"]) < MIN_CHUNK_CHARS]
# short = a whole short option table, or the one-field group 'For each casualty event' (App. 3): complete units
assert all(c.startswith(f"{CHUNK_PREFIX}_table_") for c in SHORT_CHUNKS if c != f"{CHUNK_PREFIX}_app3_g1_chunk_1"), SHORT_CHUNKS
print("✅ Chunk validation passed.")
print("Chunk size:", chunk_sizes.describe()[["count", "min", "50%", "mean", "max"]].round(0).to_dict())
print(f"Below MIN_CHUNK_CHARS: {int((chunk_sizes < MIN_CHUNK_CHARS).sum())} "
      "(whole short option tables and the one-field group of App. 3 — a chunk never mixes tables or groups; "
      "none below FRAGMENT_MIN_CHARS)")
display(pd.DataFrame([{"chunk_id": r["chunk_id"], "chars": len(r["text"]), "text": r["text"].split("\n")[-1][:60]}
                      for r in sorted(chunk_records, key=lambda r: len(r["text"]))[:8]]))

# %% [markdown] cell 77
# # Phase 16 — Unified 16-Column Schema (ADR-009)
#
# Identical schema, dtypes and validator as the other notebooks. `parent_chunk` = the section (circular or
# `Annex — Appendix N: …`), `sub_chunk` = the path below it (field group, `Section N`, `Table N — …`), document metadata
# from Phase 0; `sensitivity_level` / `department` are taken from each chunk (all 1 / Operations here, asserted).
# Audit and dedup metadata stay in their own files.

# %% cell 78
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

# %% cell 79
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

# %% cell 80
# =========================================================
# 16.3 Schema validation
# =========================================================
validate_chunk_schema(chunks_df, f"{SOURCE_NAME} chunks")
assert chunks_df["department"].isin(KNOWN_DEPARTMENTS).all()
assert set(zip(chunks_df["sensitivity_level"], chunks_df["department"])) == {(1, "Operations")}
display(chunks_df[["page", "unit_type", "logical_unit", "chunk_id", "parent_chunk", "title", "char_count"]].head(12))
display(chunks_df.groupby(["parent_chunk"]).size().rename("chunks"))
display(chunks_df[list(chunk_metadata)].drop_duplicates())

# %% [markdown] cell 81
# # Phase 17 — Save + Reload
#
# The Parquet file on disk — not the in-memory frame — is the artifact that must pass validation.

# %% cell 82
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

# %% [markdown] cell 83
# # Phase 18 — Cross-Source Validation
#
# The new chunks must concatenate cleanly with the five existing chunk files (FBL, LPI Methodology, Suez Notes,
# LPI Connecting to Compete, HbR annual report): same columns, same order, same dtypes, no `chunk_id` collision.
# The existing corpus holds 550 chunks.

# %% cell 84
# =========================================================
# 18.1 Compare schemas / 18.2 dtypes / 18.3 chunk_id collisions / 18.4 concatenate
# =========================================================
EXISTING_CORPUS_CHUNKS = 550
other_chunk_paths = {
    "FBL": CHUNKS_DIR / "FBL_template_chunks.parquet",
    "LPI_Methodology": CHUNKS_DIR / "LPI_Methodology_chunks.parquet",
    "Suez": CHUNKS_DIR / "suez_notes_chunks.parquet",
    "LPI_Connecting_to_Compete": CHUNKS_DIR / "LPI_Connecting_to_Compete_chunks.parquet",
    "HbR_Annual_report_2025": CHUNKS_DIR / "HbR_Annual_report_2025_chunks.parquet",
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
assert combined_chunks_df["department"].isin(KNOWN_DEPARTMENTS).all()
assert len(combined_chunks_df) == EXISTING_CORPUS_CHUNKS + len(reloaded_df), \
    f"The existing corpus is expected to hold {EXISTING_CORPUS_CHUNKS} chunks."
assert not combined_chunks_df.loc[combined_chunks_df["filename"] != SOURCE_FILE, "chunk_id"].str.startswith(CHUNK_PREFIX).any()

print("===================================")
print("UNIFIED SCHEMA CROSS-SOURCE CHECK: PASSED")
print("===================================")
display(combined_chunks_df.groupby(["filename", "document_type"]).size().rename("chunks"))
display(combined_chunks_df.groupby(["sensitivity_level", "department"]).size().rename("chunks"))
print("Combined rows:", len(combined_chunks_df))

# %% [markdown] cell 85
# # Phase 19 — Whole-PDF Coverage Audit
#
# Proof that nothing was dropped silently. **Every text line of all 31 pages** (every PyMuPDF line of 3.1) receives
# exactly one disposition:
#
# | Disposition | Meaning |
# |---|---|
# | `in_chunks` | the line's text is in the final chunks — verified against the chunks of **its own unit** (paragraph, field, field group, Appendix 4 section, option, option table); a bare code line (`.12`, `2.20`, a paragraph or group number) must appear as a separate token in those chunks; a line PyMuPDF merged across a column rule is checked cell by cell |
# | `metadata` | the p.1 title block and the annex title (→ `title` / `parent_chunk`), symbol and date (→ source metadata / `version_date`, asserted in 3.6), the p.3 list of appendices and tables (cross-checked in 3.6), footnote labels |
# | `erratum_excluded` | the value-type cell `Y/N/U` of field 3.2.22 (located physically in its row) and the clause of paragraph 7 (ADR-022) |
# | `empty_option_excluded` | the code `.17` of Table 22, printed without text |
# | `figure_internal` | the damage-diagram labels (described by the figure chunk) |
# | `layout_excluded` | running header, footer file path, IMO letterhead |
# | `no_text` | punctuation only (`***`, `____________`) |
#
# The line-level result is added to the single cleaned file (key `coverage_audit`).

# %% cell 86
# =========================================================
# 19.1 Owners: which unit(s) each printed row belongs to, and the chunk text of every unit
# =========================================================
chunk_text_of_unit: dict[str, str] = {}
for r in chunk_records:
    for uid in r["source_unit_ids"]:
        chunk_text_of_unit[uid] = chunk_text_of_unit.get(uid, "") + "\n" + r["text"]
metadata_corpus = letters_only(" ".join([*chunks_df["parent_chunk"].dropna(), *chunks_df["title"].dropna(),
                                         *[h for path in chunks_df["sub_chunk"].dropna() for h in path]]))

fu = final_units_df.set_index("unit_id")
units_of_section = fu.groupby("section").groups
units_of_table = {int(t): list(g) for t, g in fu[fu["table_no"].notna()].groupby("table_no").groups.items()}
field_unit = lambda fid: f"field_{fid.replace('.', '_')}"

owners: dict[str, set[str]] = {}
def own(row_ids, unit_ids):
    for rid in row_ids:
        owners.setdefault(rid, set()).update(unit_ids)

for p in paragraphs_df.itertuples():
    own(p.row_ids, {p.paragraph_id})
own(note_registry_df.set_index("marker").at["*", "rows"], {"note_star"})
for f in fields_df.itertuples():
    own(f.row_ids, {field_unit(f.field_id)})
for g in groups_df.itertuples():
    own([g.row_id], {field_unit(fid) for fid in fields_df.loc[(fields_df["appendix"] == g.appendix)
                                                              & (fields_df["group"] == g.group), "field_id"]})
for it in a4_items_df.itertuples():
    own(it.row_ids, {f"a4_section_{it.section}"})
own(dnr_df["row_id"], {"a4_section_6"})
for o in options_df[~options_df["empty"]].itertuples():
    own(o.row_ids, {f"option_{o.option_id}"})

# heading rows and table-level rows: owners by position
table_heads = section_map[section_map["role"] == "table_label"][["page_number", "y0", "table_no"]].values.tolist()
def table_at(page: int, y0: float) -> int:
    return int([t for p, y, t in table_heads if (p, y) <= (page, y0)][-1])

for h in section_map.itertuples():
    if h.role in ("appendix", "appendix_title"):
        own(h.rows, set(units_of_section[APPENDIX_SECTION[int(h.appendix)]]))
    elif h.role == "column_header":
        own(h.rows, {field_unit(fid) for fid in fields_df.loc[fields_df["appendix"] == 1, "field_id"]})
    elif h.role == "a4_section":
        own(h.rows, {f"a4_section_{int(h.a4_section)}"})
    elif h.role == "a4_table_title":
        own(h.rows, {"a4_section_6"})
    elif h.role in ("table_label", "table_title"):
        own(h.rows, set(units_of_table[int(h.table_no)]))
for r in rows_df[rows_df["row_id"].map(row_role).isin(["option_group", "table_header", "table_note"])].itertuples():
    own([r.row_id], set(units_of_table[table_at(r.page_number, r.y0)]))

# field-footnote rows (p.6, p.8) are owned by every field unit whose chunk carries that note
for n in note_registry_df[note_registry_df["marker"] != "*"].itertuples():
    note_line = f"Note: {n.text}"
    own(n.rows, {uid for uid, txt in chunk_text_of_unit.items() if note_line in txt})

# physically located removals
ERRATUM_LINES = {}
for fid, e in FIELD_ERRATA.items():
    rid = fields_df.set_index("field_id").at[fid, "row_ids"]
    cand = lines_df[lines_df["row_id"].isin(rid) & (lines_df["text"] == e["printed"])]
    assert len(cand) == 1, f"Erratum cell of {fid} not found physically."
    ERRATUM_LINES[cand.index[0]] = f"field {fid} value type {e['printed']!r}: {e['evidence']}"
EMPTY_LINES = {}
for o in options_df[options_df["empty"]].itertuples():
    cand = lines_df[lines_df["row_id"].isin(o.row_ids)]
    assert cand["text"].tolist() == [o.code]
    EMPTY_LINES[cand.index[0]] = f"Table {o.table_no} {o.code}: code printed without text (9.2)"
REMOVED = {e["unit_id"]: [("erratum_excluded", letters_only(e["removed"]), f"source erratum (9.2): {e['evidence']}")]
           for e in PROSE_ERRATA}
split_keys = {(p, b, l) for p, b, l, _ in SPLIT_LINES}

print(f"Rows with owners: {len(owners)} | erratum cells: {len(ERRATUM_LINES)} | empty option lines: {len(EMPTY_LINES)} "
      f"| split lines: {len(split_keys)}")

# %% cell 87
# =========================================================
# 19.2 Line-level disposition of the WHOLE PDF (all pages, every text line)
# =========================================================
CODE_ONLY_RE = re.compile(r"^\.?\d+(?:\.\d+)*\*?$")
METADATA_ROLES = {"circular_title": "title block -> chunk title", "annex": "'ANNEX' -> parent_chunk",
                  "annex_title": "annex title (= circular subtitle) -> chunk title",
                  "circular_contents": "p.3 list of appendices/tables (cross-checked against the headings, 3.6)"}


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


def disposition(i, r) -> tuple[str, str]:
    t = letters_only(r.text)
    if not t:
        return "no_text", f"punctuation only: {r.text!r}"
    if r.zone in ("header", "footer", "letterhead"):
        return "layout_excluded", r.zone
    if r.zone == "figure_label":
        return "figure_internal", "fig_p10_damage: label of the damage diagram (described by the figure chunk)"
    role = row_role.get(r.row_id)
    if r.zone == "footnote" and r.row_id in set(note_registry_df["label_row"]):
        return "metadata", "footnote label (the note text is indexed)"
    if role in METADATA_ROLES:
        ok = t in metadata_corpus or role == "circular_contents"
        return ("metadata", METADATA_ROLES[role]) if ok else ("UNACCOUNTED", f"{role} not in chunk metadata")
    if role == "circular_symbol_date":
        ok = r.text == DOCUMENT_SYMBOL and t in metadata_corpus or r.text == PRINTED_DATE
        return ("metadata", "symbol -> parent_chunk; date -> version_date (3.6)") if ok else ("UNACCOUNTED", role)
    if i in ERRATUM_LINES:
        return "erratum_excluded", ERRATUM_LINES[i]
    if i in EMPTY_LINES:
        return "empty_option_excluded", EMPTY_LINES[i]
    uids = owners.get(r.row_id)
    if not uids:
        return "UNACCOUNTED", f"row without owner (role {role})"
    raw = "\n".join(chunk_text_of_unit[u] for u in sorted(uids))
    kept = letters_only(raw)
    if (r.page_number, r.block_no, r.line_no) in split_keys:            # merged across a column rule: cell by cell
        bounds = grid_at(r.page_number, r.baseline - 3)
        cells = {}
        for wx0, _, wt in line_words[(r.page_number, r.block_no, r.line_no)]:
            cells.setdefault(column_of(bounds, wx0), []).append(wt)
        ok = all((" ".join(ws) + " " in raw) if CODE_ONLY_RE.match(" ".join(ws)) else letters_only(" ".join(ws)) in kept
                 for ws in cells.values())
        return ("in_chunks", f"{sorted(uids)[0]} (split at a column rule, checked per cell)") if ok \
            else ("UNACCOUNTED", "split line not found")
    if CODE_ONLY_RE.match(r.text):
        found = re.search(rf"(?:^|[\s>;]){re.escape(r.text)}(?:\s|$)", raw)
        return ("in_chunks", f"{sorted(uids)[0]} (code)") if found \
            else ("UNACCOUNTED", f"code {r.text} not found as a separate token in its chunks")
    removed = [x for u in uids for x in REMOVED.get(u, [])]
    c = claim(t, kept, removed)
    return (c[0], c[1] or sorted(uids)[0]) if c else ("UNACCOUNTED", f"not in the chunks of {sorted(uids)[:3]}")


disp = [disposition(i, r) for i, r in zip(lines_df.index, lines_df.itertuples())]
coverage_df = lines_df[["page_number", "block_no", "line_no", "y0", "zone", "text"]].assign(
    disposition=[d[0] for d in disp], detail=[d[1] for d in disp], chars=lines_df["text"].str.len())
print(f"Lines in PDF: {len(coverage_df)} on {coverage_df['page_number'].nunique()} pages")
print(coverage_df["disposition"].value_counts().to_dict())

# %% cell 88
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
assert TEXTLESS_PAGES == [4], TEXTLESS_PAGES

# every removal is on purpose and located once; the figure labels belong to a kept figure chunk
d = coverage_df["disposition"].value_counts().to_dict()
assert d.get("erratum_excluded", 0) >= 2 and d.get("empty_option_excluded") == 1
assert d.get("figure_internal") == len(FIGURE_LABELS) and any(r["unit_type"] == "figure" for r in chunk_records)
erratum_texts = coverage_df.loc[coverage_df["disposition"] == "erratum_excluded", "text"].tolist()
assert "Y/N/U" in erratum_texts and any("consequence data in appendix 3" in t for t in erratum_texts)
# every body line of an annex page and of the circular went to the chunks, except the declared removals
body = coverage_df[(coverage_df["zone"] == "body") & ~coverage_df["text"].map(letters_only).eq("")]
assert set(body["disposition"]) <= {"in_chunks", "metadata", "erratum_excluded", "empty_option_excluded"}

summary = coverage_df.groupby("disposition").agg(lines=("text", "size"), chars=("chars", "sum"))
summary["share_chars"] = (summary["chars"] / summary["chars"].sum()).round(3)
print("\nWhere every line of the PDF went:")
display(summary.sort_values("chars", ascending=False))
print("\nRemoved on purpose (every one with its reason):")
with pd.option_context("display.max_colwidth", 120, "display.max_rows", None):
    display(coverage_df[coverage_df["disposition"].isin(["erratum_excluded", "empty_option_excluded"])]
            [["page_number", "disposition", "text", "detail"]].assign(detail=lambda x: x["detail"].str[:100]))
print("\nPer page (lines):")
with pd.option_context("display.max_rows", None, "display.max_columns", None):
    display(coverage_df.pivot_table(index="page_number", columns="disposition", values="text",
                                    aggfunc="count", fill_value=0))

# add the coverage audit to the single cleaned file, then reload and check
cleaned_payload = json.loads(LOGICAL_UNITS_PATH.read_text(encoding="utf-8"))
cleaned_payload["coverage_audit"] = {
    "summary": json.loads(summary.reset_index().to_json(orient="records")),
    "lines": to_records(coverage_df[["page_number", "block_no", "line_no", "zone", "disposition", "detail", "text"]]),
}
LOGICAL_UNITS_PATH.write_text(json.dumps(cleaned_payload, ensure_ascii=False, indent=1, default=json_default),
                              encoding="utf-8")
re_cleaned = json.loads(LOGICAL_UNITS_PATH.read_text(encoding="utf-8"))
assert set(re_cleaned) == {"source", "units", "duplicate_audit", "coverage_audit"}
assert len(re_cleaned["coverage_audit"]["lines"]) == len(coverage_df)
assert len(re_cleaned["units"]) == len(final_units_df)
assert sorted(p.name for p in CLEANED_DIR.glob(f"{SOURCE_NAME}_*")) == [LOGICAL_UNITS_PATH.name]
print(f"\n✅ Whole-PDF coverage audit passed: {len(coverage_df)} lines, 0 unaccounted. Added to: {LOGICAL_UNITS_PATH.name}")

# %% cell 89
# =========================================================
# Final Checkpoint
# =========================================================
print("=" * 78)
print("IMO MSC-MEPC.3/Circ.4/Rev.1 (CASUALTY REPORTING) — INGESTION PIPELINE: FINAL CHECKPOINT")
print("=" * 78)
print(f"Source            : {SOURCE_FILE} | {len(pages_df)} pages | sha256 {SOURCE_SHA256[:16]}… | {PRINTED_DATE}")
print(f"Page classes      : {page_class_df['page_class'].value_counts().to_dict()}")
print(f"Lines / rows      : {len(lines_df)} PyMuPDF lines -> {len(rows_df)} printed rows (baseline) | "
      f"{len(SPLIT_LINES)} lines split at a column rule")
print(f"Headings          : {len(section_map)} {section_map['role'].value_counts().to_dict()}")
print(f"Contents (p.3)    : {contents_check['match'].value_counts().to_dict()}")
print(f"Field catalogue   : {len(fields_df)} fields in {len(groups_df)} groups, {len(MINIMUM_FIELDS)} minimum fields, "
      f"{int(fields_df['table_refs'].map(len).sum())} option-table references")
print(f"Appendix 4        : {len(a4_sections)} sections, {int((a4_items_df['kind'] == 'item').sum())} items, "
      f"{a4_items_df['block'].nunique()} atomic blocks, damages table {len(dnr_df)} rows")
print(f"Option tables     : {len(option_tables_df)} tables, {len(options_df)} options "
      f"({int(options_df['carried'].map(len).gt(0).sum())} with a carried category), "
      f"kinds {option_tables_df['kind'].value_counts().to_dict()}")
print(f"Cross-references  : {len(references_df)} resolved (fields -> tables, Appendix 4 conditions -> fields)")
print(f"Footnotes         : {dict(zip(note_registry_df['marker'], note_registry_df['policy']))}")
print(f"Figure gate       : {figure_gate_df['decision'].value_counts().to_dict()} | images {images_df['kind'].value_counts().to_dict()}")
print(f"Errata (ADR-022)  : field {list(FIELD_ERRATA)} + prose {[e['unit_id'] for e in PROSE_ERRATA]} | "
      f"excluded empty option {excluded_df['ref'].tolist()}")
print(f"Logical units     : {len(units_df)} {units_df['unit_type'].value_counts().to_dict()}")
print(f"Dedup             : suppressed {len(suppressed)}, trimmed {len(trimmed)}, kept contextual {len(kept_contextual)}, "
      f"cross-source candidates {int((pairs_df['scope'] == 'cross').sum())} (none covered), "
      f"manual review pending {int((decisions_df['action'] == 'manual_review').sum())}")
print(f"Access            : {units_df.groupby(['sensitivity_level', 'department']).size().to_dict()} units | "
      f"finance-term candidates reviewed {len(access_df)}")
print(f"Chunks            : {len(reloaded_df)} {reloaded_df['unit_type'].value_counts().to_dict()} | "
      f"chars min/median/max = {reloaded_df['char_count'].min()}/{int(reloaded_df['char_count'].median())}/"
      f"{reloaded_df['char_count'].max()} | split: {SPLIT_UNITS}")
print(f"Chunk access      : {reloaded_df.groupby(['sensitivity_level', 'department']).size().to_dict()}")
print(f"Cross-source      : {len(combined_chunks_df)} chunks in the unified corpus, chunk_id unique")
print(f"Whole-PDF coverage: {len(coverage_df)} lines, {int((coverage_df['disposition'] == 'UNACCOUNTED').sum())} unaccounted "
      f"{coverage_df['disposition'].value_counts().to_dict()}")

assert final_units_df["flag"].isna().all(), "No unit may remain flagged."
assert "manual_review" not in set(decisions_df["action"])
assert (coverage_df["disposition"] != "UNACCOUNTED").all()
assert (reloaded_df["sensitivity_level"] == 1).all() and (reloaded_df["department"] == "Operations").all()
print("\nPending manual review :", REVIEWED_MANUAL_REVIEW or "none")
print("Flagged units         : none")
print("\nArtifacts:")
for p in (EXTRACTED_PATH, LOGICAL_UNITS_PATH, CHUNKS_PATH):
    print(f"  {p.relative_to(PROJECT_ROOT)}  ({p.stat().st_size:,} bytes)")

# %% [markdown] cell 90
# Final Checkpoint: see pipelines/checkpoints/rag/IMO_MSC-MEPC_3_Circ_4_Rev_1_chunking.md
