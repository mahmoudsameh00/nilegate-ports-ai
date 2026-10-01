"""Phase 0 — Setup & Configuration

Converted from Notebooks/rag/USCG_ROI_chunking.ipynb (2026-10-01) by tools/nb_to_script.py: same cells, same order; `# %% cell N` = notebook cell N.
Run from the project root: uv run python tools/run.py pipelines/scripts/rag/USCG_ROI_chunking.py

Reads:   Data/raw/unstructured/us_coast_guard_reports/*.pdf (23); Data/processed/rag/extracted/ (the IMO field catalogue)
Writes:  Data/processed/rag/extracted|cleaned|chunks/ (the USCG ROI files); Data/processed/rag/ocr_cache/USCG_ROI/ (one JSON per OCR'd page, reused when present); review aids in Notebooks/_scratch/ (git-ignored)
Re-run:  safe: rewrites the same artifacts; OCR runs only for pages missing from the cache
Final Checkpoint (what was done, problems, fixes): pipelines/checkpoints/rag/USCG_ROI_chunking.md
"""
from IPython.display import display  # outside Jupyter it prints the value (added by the conversion)

# %% [markdown] cell 0
# # Phase 0 — Setup & Configuration
#
# This notebook ingests the **23 United States Coast Guard Reports of Investigation (ROI)** in
# `Data/raw/unstructured/us_coast_guard_reports/` (`<VESSEL>_<MISLE>_ROI_Redacted.pdf`, 580 pages) as **one source**:
# a corpus of documents written on the same ROI template (plan §4.1 — one notebook, one extracted, one cleaned and one
# chunks file, `filename` per chunk).
#
# Their RAG value is (a) real marine-casualty narratives — what happened, why, and what the Coast Guard recommended — and
# (b) an **IMO incident profile per report**, coded with the field catalogue of the IMO circular MSC-MEPC.3/Circ.4/Rev.1
# (ADR-023), so later consumers can count or filter incidents by IMO category.
#
# How the corpus is processed (plan §1, owner's cost rule): the format is **never learned by parsing every PDF**. It is
# learned from a **seeded random sample** (seed 42 → VICAR_602, CUMBERLAND_II, BIG_STICK, KIM_LY) plus one image-only
# report for the OCR path, written once as a reviewed template, then every report is **fingerprinted** cheaply against
# it; one template-driven parser handles the conforming reports, and only the deviating ones are inspected individually.
#
# The phase establishes:
#
# - libraries and **one PDF access helper** (`page_dict(report, page)`) used by every later phase
# - project / output directories, including the **OCR cache** owned by this notebook (`Data/processed/rag/ocr_cache/USCG_ROI/`)
# - source metadata. Access: public, redacted federal reports → **level 1 / Operations for every unit** (`docs/rbac_mapping.md` §4),
#   asserted per unit (Phase 9) and per chunk (Phase 15)
# - the corpus file list with one SHA-256 fingerprint per file, and the seeded sample
#
# Plan: `docs/plans/USCG_ROI_chunking_plan.md` (§4 decisions, §6 implementation log).

# %% cell 1
# =========================================================
# 0.1 Imports & Environment
# =========================================================

from pathlib import Path
from collections import Counter
import re
import json
import random
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
# 0.2 Locate the corpus folder and list the reports
# =========================================================
# File name = <VESSEL>_<MISLE activity number (7 digits)>_ROI_Redacted.pdf. report_id = the vessel part.

CORPUS_RELATIVE_PATH = Path("Data/raw/unstructured/us_coast_guard_reports")
FILE_RE = re.compile(r"^(?P<report_id>.+)_(?P<misle>\d{7})_ROI_Redacted\.pdf$")

search_roots = [Path.cwd(), *Path.cwd().parents]
candidates = [root / CORPUS_RELATIVE_PATH for root in search_roots]
CORPUS_DIR = next((path for path in candidates if path.is_dir()), None)
if CORPUS_DIR is None:
    raise FileNotFoundError("USCG corpus folder not found.\n\nLooked in:\n" + "\n".join(f"  {p}" for p in candidates))

CORPUS_FILES = sorted(p.name for p in CORPUS_DIR.glob("*.pdf"))
bad_names = [f for f in CORPUS_FILES if not FILE_RE.match(f)]
assert not bad_names, f"Unexpected file names: {bad_names}"

reports_df = pd.DataFrame([{**FILE_RE.match(f).groupdict(), "filename": f} for f in CORPUS_FILES])
REPORT_IDS = reports_df["report_id"].tolist()
FILE_OF = dict(zip(reports_df["report_id"], reports_df["filename"]))
MISLE_OF_FILE = dict(zip(reports_df["report_id"], reports_df["misle"]))

print("Corpus folder:", CORPUS_DIR)
print("Reports      :", len(REPORT_IDS))
print(reports_df.to_string(index=False))

# %% cell 3
# =========================================================
# 0.3 Open the PDFs + PDF access helpers
# =========================================================
# Every phase reads native text through page_dict(), so block/line indexes are identical everywhere.
# TEXT_FLAGS = the default "dict" flags WITHOUT image bytes (images are inventoried separately in Phase 1).

TEXT_FLAGS = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES

docs: dict[str, pymupdf.Document] = {rid: pymupdf.open(CORPUS_DIR / FILE_OF[rid]) for rid in REPORT_IDS}
_dict_cache: dict[tuple[str, int], dict] = {}


def page_dict(report_id: str, p: int) -> dict:
    """get_text('dict') of physical page p (1-based) of one report, text blocks only, cached."""
    key = (report_id, p)
    if key not in _dict_cache:
        _dict_cache[key] = docs[report_id][p - 1].get_text("dict", flags=TEXT_FLAGS)
    return _dict_cache[key]


print("Documents opened:", len(docs))
print("Pages per report:", {rid: len(d) for rid, d in docs.items()})

# %% cell 4
# =========================================================
# 0.4 Inspect PDF metadata (producer tells how each file was made)
# =========================================================
# Word -> PDF (Distiller / PDFMaker / "Microsoft: Print To PDF"), a scanner (Lexmark), Acrobat "Paper Capture" (OCR).
# The embedded title/author are not used: title, vessel and dates are read from the reports themselves (Phase 4).

metadata_df = pd.DataFrame([
    {"report_id": rid, "pages": len(d), "producer": d.metadata.get("producer", ""),
     "creator": d.metadata.get("creator", ""), "toc_entries": len(d.get_toc())}
    for rid, d in docs.items()
])
with pd.option_context("display.max_colwidth", 50):
    display(metadata_df)

# %% cell 5
# =========================================================
# 0.5 Define project and output paths
# =========================================================

PROJECT_ROOT = CORPUS_DIR.parents[3]                          # <root>/Data/raw/unstructured/us_coast_guard_reports
assert (PROJECT_ROOT / "pyproject.toml").is_file(), f"Project root not found: {PROJECT_ROOT}"

PROCESSED_RAG_DIR = PROJECT_ROOT / "Data" / "processed" / "rag"
EXTRACTED_DIR = PROCESSED_RAG_DIR / "extracted"
CLEANED_DIR = PROCESSED_RAG_DIR / "cleaned"
CHUNKS_DIR = PROCESSED_RAG_DIR / "chunks"
OCR_CACHE_DIR = PROCESSED_RAG_DIR / "ocr_cache" / "USCG_ROI"   # owned by this notebook: one JSON per OCR'd page
SCRATCH_DIR = PROJECT_ROOT / "Notebooks" / "_scratch"          # git-ignored review aids only

for directory in (EXTRACTED_DIR, CLEANED_DIR, CHUNKS_DIR, OCR_CACHE_DIR):
    directory.mkdir(parents=True, exist_ok=True)

print("Project root  :", PROJECT_ROOT)
print("Extracted dir :", EXTRACTED_DIR)
print("Cleaned dir   :", CLEANED_DIR)
print("Chunks dir    :", CHUNKS_DIR)
print("OCR cache dir :", OCR_CACHE_DIR)
print("Scratch dir   :", SCRATCH_DIR)

# %% cell 6
# =========================================================
# 0.6 Define source and pipeline configuration
# =========================================================

SOURCE_NAME = "USCG_ROI"
SOURCE_PUBLISHER = "United States Coast Guard"
DOCUMENT_TYPE = "uscg_report_of_investigation"
REAL_OR_SYNTHETIC = "real"
# version_date is per report = date of the Commandant's action (plan §4.8), read in Phase 4.

# External, publicly released (redacted) reports -> level 1 for everyone, owner = Operations (docs/rbac_mapping.md §4).
DOCUMENT_ACCESS = {"sensitivity_level": 1, "department": "Operations"}
KNOWN_DEPARTMENTS = {"Operations", "Customs", "Finance", "HR", "IT"}   # rows of the departments table

SOURCE_DESCRIPTION = ("United States Coast Guard Reports of Investigation (ROI) into 23 marine casualties — "
                      "public redacted releases written on one shared ROI template")

MIN_CHUNK_CHARS = 300                  # a guideline here, not a rule (plan §1.3): the split follows the content
MAX_CHUNK_CHARS = 2000                 # safety cap
FRAGMENT_MIN_CHARS = 50                # below this a chunk is a fragment with no standalone meaning (forbidden)
CHUNK_PREFIX = "uscg"

source_metadata = {
    "source_name": SOURCE_NAME,
    "publisher": SOURCE_PUBLISHER,
    "document_type": DOCUMENT_TYPE,
    "real_or_synthetic": REAL_OR_SYNTHETIC,
    "files": len(REPORT_IDS),
    "access_policy": "document_level_asserted_per_unit",
    "access": DOCUMENT_ACCESS,
    "description": SOURCE_DESCRIPTION,
}

print("Source configuration:")
for key, value in source_metadata.items():
    print(f"{key:20}: {value}")
print("\nChunk configuration:")
print("MIN_CHUNK_CHARS    :", MIN_CHUNK_CHARS, "(guideline)")
print("MAX_CHUNK_CHARS    :", MAX_CHUNK_CHARS, "(safety cap)")
print("FRAGMENT_MIN_CHARS :", FRAGMENT_MIN_CHARS)
print("CHUNK_PREFIX       :", CHUNK_PREFIX)

# %% cell 7
# =========================================================
# 0.7 Source file fingerprints (one SHA-256 per report)
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


reports_df["sha256"] = reports_df["filename"].map(lambda f: sha256_file(CORPUS_DIR / f))
reports_df["file_size"] = reports_df["filename"].map(lambda f: (CORPUS_DIR / f).stat().st_size)
reports_df["pages"] = reports_df["report_id"].map(lambda rid: len(docs[rid]))
SHA_OF = dict(zip(reports_df["report_id"], reports_df["sha256"]))

display(reports_df[["report_id", "misle", "pages", "file_size", "sha256"]])
print(f"Total: {reports_df['pages'].sum()} pages, {reports_df['file_size'].sum():,} bytes")

# %% cell 8
# =========================================================
# 0.8 Seeded random sample (the template is learned from these reports only)
# =========================================================
# random.sample over the sorted file list with seed 42 (plan §0/§4.9). One image-only report is added for the OCR
# path: the one with the fewest pages among the four image-only bodies (plan §0), chosen by page count — UNA_MAS.

random.seed(42)
SAMPLE_FILES = random.sample(CORPUS_FILES, 4)
SAMPLE_REPORTS = [FILE_RE.match(f).group("report_id") for f in SAMPLE_FILES]

IMAGE_ONLY_BODY_REPORTS = ["H20_BELOW", "PROWLER_ATTESSA_IV", "QUEEN_OF_THE_WEST", "UNA_MAS"]   # plan §0, checked in Phase 1
OCR_SAMPLE_REPORT = min(IMAGE_ONLY_BODY_REPORTS, key=lambda rid: len(docs[rid]))

print("Seeded sample (seed 42):", SAMPLE_REPORTS)
print("OCR sample report      :", OCR_SAMPLE_REPORT, f"({len(docs[OCR_SAMPLE_REPORT])} pages)")

# %% cell 9
# =========================================================
# 0.9 Phase 0 validation
# =========================================================

assert len(REPORT_IDS) == 23, f"ADR-007: 23 reports expected, found {len(REPORT_IDS)}."
assert reports_df["report_id"].is_unique and reports_df["misle"].is_unique
assert reports_df["pages"].sum() == 580, "Reconnaissance (plan §0): 580 pages."
assert reports_df["sha256"].str.len().eq(64).all() and reports_df["sha256"].is_unique
assert (reports_df["file_size"] > 0).all()

assert DOCUMENT_TYPE == "uscg_report_of_investigation" and REAL_OR_SYNTHETIC == "real"
assert DOCUMENT_ACCESS == {"sensitivity_level": 1, "department": "Operations"}, "rbac_mapping §4: USCG = level 1 / Operations"
assert DOCUMENT_ACCESS["department"] in KNOWN_DEPARTMENTS
assert 0 < FRAGMENT_MIN_CHARS < MIN_CHUNK_CHARS < MAX_CHUNK_CHARS

# ---- reviewed snapshot (2026-09-26) ----
assert SAMPLE_REPORTS == ["VICAR_602", "CUMBERLAND_II", "BIG_STICK", "KIM_LY"], SAMPLE_REPORTS
assert OCR_SAMPLE_REPORT == "UNA_MAS"
assert not any(b.get("type") == 1 for b in page_dict("BIG_STICK", 2)["blocks"]), "page_dict must not contain image blocks."

print("✅ Phase 0 validation passed.")
print("Reports:", len(REPORT_IDS), "| pages:", int(reports_df["pages"].sum()), "| sample:", SAMPLE_REPORTS, "+", OCR_SAMPLE_REPORT)

# %% [markdown] cell 10
# # Phase 1 — Corpus Inventory (all 23 reports, cheap)
#
# One row per physical page of every report, from cheap PyMuPDF calls only (no layout parsing): characters and words
# of the text layer, image placements and the share of the page covered by the largest image, and a **text trace**
# summary — how many characters are drawn invisibly (render mode 3, the classic OCR layer) and how many use Acrobat's
# OCR-substitute fonts (names starting with `*`, e.g. `*Minion Pro-Bold-7757`, written by Acrobat when a scanned page
# is converted to editable text).
#
# Each page then receives a **text class**:
#
# | Class | Rule | What happens next |
# |---|---|---|
# | `text` | a native text layer, not lying over a full-page scan | parsed directly |
# | `ocr_layer` | text lying over a full-page image (invisible mode-3 layer, or Acrobat editable OCR text) | readability gate (Phase 1b): kept if it passes, re-OCR'd otherwise |
# | `image_only` | fewer than 20 visible characters | OCR'd with RapidOCR (Phase 1b); a page with no text boxes is a photo / graphic |
#
# Reconnaissance correction (measured here): VICAR_602 is mostly native Word text — only its two scanned letters
# (p.3, p.5) carry Acrobat OCR text; the same kind of scanned letter appears in MERRICK (p.4, p.6), CONCHRD (p.3) and
# TOO_SHORT (p.4). MERRICK's body (p.7–19) is an invisible Paper-Capture layer. QUEEN_OF_THE_WEST p.22 has an
# invisible layer made only of spaces → `image_only`.

# %% cell 11
# =========================================================
# 1.1 Build the page inventory of all reports
# =========================================================
MIN_TEXT_CHARS = 20            # below this a page has no usable text layer
FULL_PAGE_IMAGE = 0.90         # an image covering >= 90 % of the page = a scanned page

page_records = []
for rid in REPORT_IDS:
    doc = docs[rid]
    for page in doc:
        p = page.number + 1
        text = page.get_text("text") or ""
        stripped = text.strip()
        area = page.rect.width * page.rect.height
        infos = page.get_image_info()
        cover = max([(i["bbox"][2] - i["bbox"][0]) * (i["bbox"][3] - i["bbox"][1]) / area for i in infos] or [0.0])
        invisible = star_font = visible = 0
        for tr in page.get_texttrace():
            n = sum(1 for c in tr["chars"] if chr(c[0]).strip())      # non-blank characters only
            if tr["type"] == 3:
                invisible += n
            else:
                visible += n
                if tr["font"].startswith("*"):
                    star_font += n
        page_records.append({
            "report_id": rid, "page_number": p,
            "char_count": len(stripped), "word_count": len(stripped.split()),
            "image_placements": len(infos), "max_image_cover": round(min(cover, 1.0), 3),
            "visible_chars": visible, "invisible_chars": invisible, "star_font_chars": star_font,
            "page_width": round(page.rect.width, 1), "page_height": round(page.rect.height, 1),
            "text": text,
        })

pages_df = pd.DataFrame(page_records)
print("Page inventory created:", len(pages_df), "pages of", pages_df["report_id"].nunique(), "reports")
print("Columns:", list(pages_df.columns))

# %% cell 12
# =========================================================
# 1.2 Page text classes
# =========================================================

def text_class(r) -> tuple[str, str]:
    if r.char_count < MIN_TEXT_CHARS:
        why = "no text layer" if r.invisible_chars == 0 else "invisible layer without words (blank characters only)"
        return "image_only", f"{r.char_count} visible chars; {why}"
    if r.max_image_cover >= FULL_PAGE_IMAGE:
        kind = "invisible mode-3 OCR layer" if r.invisible_chars > r.visible_chars else "Acrobat editable OCR text (*fonts)"
        return "ocr_layer", f"text over a full-page scan ({kind})"
    return "text", "native text layer"


cls = [text_class(r) for r in pages_df.itertuples()]
pages_df["text_class"] = [c[0] for c in cls]
pages_df["class_reason"] = [c[1] for c in cls]

summary_df = (pages_df.pivot_table(index="report_id", columns="text_class", values="page_number", aggfunc="count",
                                   fill_value=0)
              .reindex(columns=["text", "ocr_layer", "image_only"], fill_value=0))
summary_df["pages"] = summary_df.sum(axis=1)
summary_df["image_only_pages"] = pages_df[pages_df["text_class"] == "image_only"].groupby("report_id")["page_number"].agg(list)
summary_df["ocr_layer_pages"] = pages_df[pages_df["text_class"] == "ocr_layer"].groupby("report_id")["page_number"].agg(list)
with pd.option_context("display.max_rows", None, "display.max_colwidth", 80):
    display(summary_df)
print("Class counts:", pages_df["text_class"].value_counts().to_dict())

# %% cell 13
# =========================================================
# 1.3 Inventory statistics + the OCR-layer pages
# =========================================================
print("Page sizes (width x height):")
print(pages_df.groupby(["page_width", "page_height"]).size().to_string())
print("\nCharacters per class:")
print(pages_df.groupby("text_class")[["char_count", "word_count"]].sum().to_string())

ocr_layer_df = pages_df[pages_df["text_class"] == "ocr_layer"]
with pd.option_context("display.max_rows", None, "display.max_colwidth", 70):
    display(ocr_layer_df[["report_id", "page_number", "char_count", "visible_chars", "invisible_chars",
                          "star_font_chars", "max_image_cover", "class_reason"]])

# %% cell 14
# =========================================================
# 1.4 Phase 1 validation
# =========================================================
assert len(pages_df) == 580 and pages_df.groupby("report_id").size().to_dict() == reports_df.set_index("report_id")["pages"].to_dict()
for rid, grp in pages_df.groupby("report_id"):
    assert grp["page_number"].tolist() == list(range(1, len(docs[rid]) + 1)), f"{rid}: page numbers not 1..N"
assert pages_df["text_class"].isin({"text", "ocr_layer", "image_only"}).all()
assert pages_df["class_reason"].str.len().gt(0).all()
# a scanned page with text must be recognisably OCR text (invisible layer or Acrobat *fonts), never a native layer
ol = pages_df[pages_df["text_class"] == "ocr_layer"]
assert ((ol["invisible_chars"] > ol["visible_chars"]) | (ol["star_font_chars"] > 0.5 * ol["visible_chars"])).all()

# ---- reviewed snapshot (2026-09-26): image-only and OCR-layer pages per report ----
REVIEWED_IMAGE_ONLY = {
    "CONCHRD": [4], "CUMBERLAND_II": [1, 4], "CUYAHOGA": [1, 4, 5, 11, 20, 21], "GENERAL_MACARTHUR": [3, 4],
    "GOOD_GULF": [8], "H20_BELOW": [1, *range(4, 17)], "KIM_LY": [4, 5, 6, 7], "LADY_ELLEN": [5, 6, 7, 8, 9],
    "LITTLE_G": [4, 5, 7, 9, 10, 11, 13, 15], "MERRICK": [5], "NC3250BW": [3],
    "PROWLER_ATTESSA_IV": [1, *range(4, 23)], "QUEEN_OF_THE_WEST": [1, *range(5, 24)],
    "SPIRIT_OF_BOSTON": [6, 7, 8, 9], "TOO_SHORT": [3], "UNA_MAS": [1, *range(5, 15)], "VICAR_602": [1, 4],
    "WAYMON_BOYD": [4, 5, 6, 7, 8, 9, 10], "WILDERNESS_I": [8, 9, 10, 11, 13],
}
REVIEWED_OCR_LAYER = {"CONCHRD": [3], "MERRICK": [4, 6, *range(7, 20)], "TOO_SHORT": [4], "VICAR_602": [3, 5]}

actual_io = pages_df[pages_df["text_class"] == "image_only"].groupby("report_id")["page_number"].agg(list).to_dict()
actual_ol = ol.groupby("report_id")["page_number"].agg(list).to_dict()
assert actual_io == REVIEWED_IMAGE_ONLY, {k: v for k, v in actual_io.items() if REVIEWED_IMAGE_ONLY.get(k) != v}
assert actual_ol == REVIEWED_OCR_LAYER, actual_ol
# plan §0: the four image-only bodies
for rid in IMAGE_ONLY_BODY_REPORTS:
    assert summary_df.at[rid, "image_only"] >= 0.6 * summary_df.at[rid, "pages"], rid

print("✅ Phase 1 validation passed.")
print("Pages:", len(pages_df), "| classes:", pages_df["text_class"].value_counts().to_dict())
print("Image-only pages:", sum(map(len, REVIEWED_IMAGE_ONLY.values())), "in", len(REVIEWED_IMAGE_ONLY), "reports")
print("OCR-layer pages :", sum(map(len, REVIEWED_OCR_LAYER.values())), "in", len(REVIEWED_OCR_LAYER), "reports")

# %% [markdown] cell 15
# # Phase 1b — OCR of the pages without a usable text layer (RapidOCR)
#
# Owner decision (plan §4.2): image-only pages are **OCR'd, not skipped**, with RapidOCR (`rapidocr` + `onnxruntime`,
# installed with uv, models bundled in the package — no system install, no download).
#
# **Method**
#
# 1. Render the page with PyMuPDF at **300 dpi** (RGB, no alpha).
# 2. RapidOCR detects text-line boxes and recognises each line. Two settings are changed from the defaults, both on
#    evidence from UNA_MAS p.5 (the OCR sample):
#    - `text_score = 0` — the default (0.5) **silently drops** every line below 0.5 confidence; here every line is kept
#      with its confidence and the readability gate decides;
#    - `max_side_len = 2000` (default) is kept: 3400 was 40 % slower and not better (each setting garbled a different
#      long line).
# 3. **Retry of weak lines:** a line whose confidence is below `OCR_RETRY_CONF` is recognised again from its own crop
#    of the full-resolution render (recognition only). On UNA_MAS p.5 the line
#    "ve - sn r s o s t s es" (0.742) becomes "vessel capsized, turning over port side first and began floating upside
#    down. C-1 was thrown into" (0.996). The better reading is kept; the first one stays in the cache as evidence.
# 4. Boxes are converted to **PDF coordinates** (pixels × 72 / dpi) so OCR lines go through the same row / zone / template
#    logic as native lines; each line keeps its **confidence** and the provenance `ocr`.
# 5. **Cache** (artifact of this notebook): one JSON per page in `Data/processed/rag/ocr_cache/USCG_ROI/`, with a key
#    (file sha256, page, dpi, engine settings, rapidocr / onnxruntime versions, model file hashes). A cache file whose key
#    differs is stale and is recomputed, so a re-run never OCRs again unless something changed.
#
# All `image_only` pages are OCR'd (a photo is only known to be a photo once OCR finds no text on it), and the 19
# `ocr_layer` pages too, so that their existing layer can be compared with an independent reading (1b.4).

# %% cell 16
# =========================================================
# 1b.1 OCR engine, settings and cache key
# =========================================================
import importlib.metadata as importlib_metadata
import logging
from rapidocr import RapidOCR

logging.getLogger("RapidOCR").setLevel(logging.CRITICAL)

OCR_DPI = 300
OCR_MAX_SIDE_LEN = 2000
OCR_RETRY_CONF = 0.95          # lines below this are recognised again from their full-resolution crop
OCR_CROP_PAD = 4               # pixels around a line crop
OCR_PARAMS = {"Global.text_score": 0.0, "Global.max_side_len": OCR_MAX_SIDE_LEN, "Global.log_level": "critical"}

ocr_engine = RapidOCR(params=OCR_PARAMS)
_model_dir = Path(ocr_engine.cfg.Global.model_root_dir)
OCR_ENGINE_INFO = {
    "rapidocr": importlib_metadata.version("rapidocr"),
    "onnxruntime": importlib_metadata.version("onnxruntime"),
    "det": f"{ocr_engine.cfg.Det.ocr_version.value} {ocr_engine.cfg.Det.model_type.value}",
    "cls": f"{ocr_engine.cfg.Cls.ocr_version.value} {ocr_engine.cfg.Cls.model_type.value}",
    "rec": f"{ocr_engine.cfg.Rec.ocr_version.value} {ocr_engine.cfg.Rec.model_type.value}",
    "model_files": {p.name: sha256_file(p)[:16] for p in sorted(_model_dir.glob("*.onnx"))},
}
OCR_SETTINGS = {"dpi": OCR_DPI, "colorspace": "RGB", "alpha": False, "params": OCR_PARAMS,
                "retry_conf": OCR_RETRY_CONF, "crop_pad": OCR_CROP_PAD}


def ocr_cache_key(rid: str, p: int) -> dict:
    return {"report_id": rid, "filename": FILE_OF[rid], "sha256": SHA_OF[rid], "page_number": p,
            "settings": OCR_SETTINGS, "engine": OCR_ENGINE_INFO}


def ocr_cache_path(rid: str, p: int) -> Path:
    return OCR_CACHE_DIR / f"{rid}_p{p:03d}.json"


print(json.dumps({"settings": OCR_SETTINGS, "engine": OCR_ENGINE_INFO}, indent=1))

# %% cell 17
# =========================================================
# 1b.2 OCR one page (render -> detect + recognise -> retry weak lines -> PDF coordinates), cached
# =========================================================

def _render(rid: str, p: int) -> np.ndarray:
    pix = docs[rid][p - 1].get_pixmap(dpi=OCR_DPI, colorspace=pymupdf.csRGB, alpha=False)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)


def _run_ocr(rid: str, p: int) -> dict:
    img = _render(rid, p)
    # the three flags are passed on EVERY call: RapidOCR keeps the flags of the previous call, so a rec-only retry
    # (1b.2, weak lines) would otherwise switch detection off for all later pages
    res = ocr_engine(img, use_det=True, use_cls=True, use_rec=True)
    scale = 72 / OCR_DPI
    lines = []
    # a page where detection finds no text box returns an output without boxes -> no lines (a photo / blank scan)
    boxes = getattr(res, "boxes", None)
    boxes = [] if boxes is None else boxes
    for box, text, conf in zip(boxes, getattr(res, "txts", None) or [], getattr(res, "scores", None) or []):
        b = np.asarray(box, dtype=float)
        px0, py0, px1, py1 = b[:, 0].min(), b[:, 1].min(), b[:, 0].max(), b[:, 1].max()
        line = {"bbox": [round(v * scale, 1) for v in (px0, py0, px1, py1)], "text": text, "conf": round(float(conf), 4),
                "retry": None}
        if conf < OCR_RETRY_CONF:
            y0, y1 = max(0, int(py0) - OCR_CROP_PAD), int(py1) + OCR_CROP_PAD
            x0, x1 = max(0, int(px0) - OCR_CROP_PAD), int(px1) + OCR_CROP_PAD
            rr = ocr_engine(np.ascontiguousarray(img[y0:y1, x0:x1]), use_det=False, use_cls=False, use_rec=True)
            if rr.txts:
                r_text, r_conf = rr.txts[0], float(rr.scores[0])
                line["retry"] = {"text": r_text, "conf": round(r_conf, 4), "first_text": text, "first_conf": line["conf"],
                                 "kept": "retry" if r_conf > conf else "first"}
                if r_conf > conf:
                    line["text"], line["conf"] = r_text, round(r_conf, 4)
        lines.append(line)
    lines.sort(key=lambda l: (l["bbox"][1], l["bbox"][0]))
    return {"image_px": [int(img.shape[1]), int(img.shape[0])], "lines": lines}


def ocr_page(rid: str, p: int) -> tuple[dict, str]:
    """OCR result of one page and where it came from ('cache' or 'ocr')."""
    path, key = ocr_cache_path(rid, p), ocr_cache_key(rid, p)
    if path.exists():
        cached = json.loads(path.read_text(encoding="utf-8"))
        if cached.get("key") == key:
            return cached, "cache"
    result = {"key": key, **_run_ocr(rid, p)}
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result, "ocr"


print("OCR helpers ready. Cache:", OCR_CACHE_DIR.relative_to(PROJECT_ROOT))

# %% cell 18
# =========================================================
# 1b.3 OCR every image_only and ocr_layer page (first run ~15 min; later runs read the cache)
# =========================================================
import time

OCR_TARGETS = pages_df.loc[pages_df["text_class"].isin(["image_only", "ocr_layer"]), ["report_id", "page_number",
                                                                                       "text_class"]]
ocr_results: dict[tuple[str, int], dict] = {}
ocr_origin = Counter()
t_start = time.time()
for k, r in enumerate(OCR_TARGETS.itertuples(), start=1):
    ocr_results[(r.report_id, r.page_number)], origin = ocr_page(r.report_id, r.page_number)
    ocr_origin[origin] += 1
    if origin == "ocr" and k % 10 == 0:
        print(f"  {k}/{len(OCR_TARGETS)} pages ({time.time() - t_start:.0f}s)")
print(f"OCR pages: {len(ocr_results)} | from cache: {ocr_origin['cache']} | newly OCR'd: {ocr_origin['ocr']} "
      f"| {time.time() - t_start:.0f}s")

# %% [markdown] cell 19
# ### 1b.4–1b.7 Figures inside scanned pages, readability gate, OCR-layer check
#
# **Measured on the OCR output (1b.3):** none of the 115 `image_only` pages is a bare photo — every one carries text:
# scanned letters, scanned body pages, cover pages, and body pages that contain a **figure** (photo, nautical chart,
# dive-computer screen). RapidOCR also reads the text *inside* those figures: chart soundings ("28 | 36 | 36 | 35",
# 241 lines on MERRICK p.8), screen labels, and even personal names written on a diagram (CUYAHOGA p.20–21).
# That text is part of the image, not of the report's prose, so it must never reach the body text.
#
# **Figure regions on a scanned page (1b.4).** A scanned page has no image placements to tell where a figure is, so
# the regions are found in the page image itself: the page is rendered in grey, **every text box is masked out**, and
# what ink remains is graphics (photos, chart lines, drawn table borders, the letterhead seal, signatures, redaction
# boxes). The ink is dilated and split into connected regions; a region of at least 60 × 40 pt is kept and typed:
#
# - `redaction` — a solid black box (mean grey ≤ 10, all ink on straight runs): the FOIA redactions over signatures;
# - `table` — thin straight rules **on white paper**: ink density ≤ 0.25, ≥ 60 % of the ink on long horizontal / vertical
#   runs, and ≤ 15 % light fill once the text is painted white (the vessel particulars and persons tables). The light-fill
#   test was added after a Google-Earth map with boxed callouts (WILDERNESS_I p.9) passed the first two tests;
# - `graphic` — everything else (photos: dense ink; charts and maps: sparse, curved ink or a light background fill).
#
# **Figure bands.** A Word figure is a block across the text column, and one chart can come out as several ink regions
# side by side (UNA_MAS p.8: three regions, 55 soundings between them). Graphic regions of at least 100 × 50 pt are
# therefore merged by their vertical extent into **bands**; every line whose centre lies in a band is
# `figure_internal` (never chunked; the figure is represented by its caption, ADR-020), except a caption line
# (`Figure N …`). Smaller regions (the letterhead seal, a signature scribble) and tables / redactions never make a band.
# The same test is applied to the lines of the OCR-layer pages.
#
# **Readability gate (1b.5)** — per page, on the **body lines only** (figure-internal lines excluded):
# share of dictionary words (words of ≥ 2 letters; dictionary = every word seen at least twice on the 446 native-text
# pages of the corpus — no new dependency) ≥ 0.75, and mean recognition confidence ≥ 0.90 (RapidOCR pages). The share
# threshold sits below the lowest page reviewed as fully readable: H20_BELOW p.15 (0.781, confidence 0.994) — that
# report is scanned end to end, so its diving vocabulary (rebreather, counter-lung…) is absent from the native pages.
# A page that fails would be `ocr_unreadable`, with its measures as evidence, never silently (none fails).
#
# **OCR layers (1b.6).** The 19 `ocr_layer` pages keep their existing layer if it passes the same gate (plan §4.2); the
# independent RapidOCR reading is compared word by word and kept as evidence (agreement 0.89–1.00: the layers are as
# good as RapidOCR).
#
# **OCR noise (1b.7).** A reading below 0.80 confidence of at most two characters is a mark, not text (reviewed on the
# renders: the letterhead seal read as "3", a signature pen stroke read as "V"); it is recorded as `ocr_noise`.

# %% cell 20
# =========================================================
# 1b.4 Graphic regions of the scanned pages (text masked out) -> figure-internal lines
# =========================================================
from scipy import ndimage

GRAPHIC_DPI = 100
GRAPHIC_MIN_W, GRAPHIC_MIN_H, GRAPHIC_MIN_INK = 60, 40, 300     # pt, pt, pixels
TABLE_MAX_DENSITY, TABLE_MIN_STRAIGHT, TABLE_MAX_LIGHT = 0.25, 0.60, 0.15
REDACTION_MAX_GREY, REDACTION_MIN_STRAIGHT = 10, 0.98
CAPTION_RE = re.compile(r"^Fig(?:ure|\.)?\s*\d+", re.IGNORECASE)
_H_RUN, _V_RUN = np.ones((1, 40), bool), np.ones((40, 1), bool)


def graphic_regions(rid: str, p: int, boxes: list[list[float]]) -> list[dict]:
    """Regions of non-text ink on page p (boxes = text boxes in PDF points, masked out before the analysis)."""
    s = GRAPHIC_DPI / 72
    pix = docs[rid][p - 1].get_pixmap(dpi=GRAPHIC_DPI, colorspace=pymupdf.csGRAY)
    grey = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).copy()
    for x0, y0, x1, y1 in boxes:                     # text boxes are painted white: only graphics remain
        grey[max(0, int(y0 * s) - 2):int(y1 * s) + 3, max(0, int(x0 * s) - 2):int(x1 * s) + 3] = 255
    ink = grey < 200
    straight = ndimage.binary_opening(ink, _H_RUN) | ndimage.binary_opening(ink, _V_RUN)
    lab, _ = ndimage.label(ndimage.binary_dilation(ink, iterations=4))
    regions = []
    for k, sl in enumerate(ndimage.find_objects(lab), start=1):
        mask = ink[sl] & (lab[sl] == k)
        n_ink = int(mask.sum())
        w, h = (sl[1].stop - sl[1].start) / s, (sl[0].stop - sl[0].start) / s
        if w < GRAPHIC_MIN_W or h < GRAPHIC_MIN_H or n_ink < GRAPHIC_MIN_INK:
            continue
        density = n_ink / mask.size
        straight_share = float((straight[sl] & mask).sum() / n_ink)
        mean_grey = float(grey[sl][mask].mean())
        box = grey[sl]
        light_share = float(((box >= 150) & (box < 235)).mean())      # light fill (map / photo background), text excluded
        if mean_grey <= REDACTION_MAX_GREY and straight_share >= REDACTION_MIN_STRAIGHT:
            kind = "redaction"          # a solid black box (FOIA redaction, e.g. over a signature): not a figure
        elif density <= TABLE_MAX_DENSITY and straight_share >= TABLE_MIN_STRAIGHT and light_share <= TABLE_MAX_LIGHT:
            kind = "table"              # thin straight rules on white paper
        else:
            kind = "graphic"
        regions.append({"bbox": [round(sl[1].start / s, 1), round(sl[0].start / s, 1), round(sl[1].stop / s, 1),
                                 round(sl[0].stop / s, 1)],
                        "kind": kind, "density": round(density, 3), "straight_share": round(straight_share, 3),
                        "mean_grey": round(mean_grey, 1), "light_share": round(light_share, 3)})
    return regions


BAND_MIN_W, BAND_MIN_H, BAND_JOIN_GAP = 100, 50, 12      # pt


def figure_bands(regions: list[dict]) -> list[tuple[float, float]]:
    """Vertical bands occupied by figures: a Word figure is a block across the text column, and one chart can come
    out as several ink regions side by side (UNA_MAS p.8), so large graphic regions are merged by their y-range.
    Small regions (the letterhead seal, a signature scribble) never make a band."""
    spans = sorted((r["bbox"][1], r["bbox"][3]) for r in regions if r["kind"] == "graphic"
                   and r["bbox"][2] - r["bbox"][0] >= BAND_MIN_W and r["bbox"][3] - r["bbox"][1] >= BAND_MIN_H)
    bands = []
    for y0, y1 in spans:
        if bands and y0 <= bands[-1][1] + BAND_JOIN_GAP:
            bands[-1] = (bands[-1][0], max(bands[-1][1], y1))
        else:
            bands.append((y0, y1))
    return bands


def in_band(bbox, bands) -> bool:
    cy = (bbox[1] + bbox[3]) / 2
    return any(y0 <= cy <= y1 for y0, y1 in bands)


def layer_lines(rid: str, p: int) -> list[dict]:
    """Lines of an existing (OCR) text layer, in the same shape as the RapidOCR lines."""
    out = []
    for b in page_dict(rid, p)["blocks"]:
        for l in b["lines"]:
            t = "".join(s["text"] for s in l["spans"]).strip()
            if t:
                out.append({"bbox": [round(v, 1) for v in l["bbox"]], "text": t, "conf": None, "retry": None})
    return out


scan_records, graphic_records, band_records = [], [], []
for (rid, p), res in ocr_results.items():
    tclass = pages_df.loc[(pages_df["report_id"] == rid) & (pages_df["page_number"] == p), "text_class"].iloc[0]
    for source, lines in (("rapidocr", res["lines"]), ("layer", layer_lines(rid, p) if tclass == "ocr_layer" else None)):
        if lines is None:
            continue
        regions = graphic_regions(rid, p, [l["bbox"] for l in lines])
        bands = figure_bands(regions)
        for r in regions:
            graphic_records.append({"report_id": rid, "page_number": p, "source": source, **r})
        for b in bands:
            band_records.append({"report_id": rid, "page_number": p, "source": source, "y0": b[0], "y1": b[1]})
        for i, l in enumerate(lines):
            fig = in_band(l["bbox"], bands) and not CAPTION_RE.match(l["text"])
            scan_records.append({"report_id": rid, "page_number": p, "text_class": tclass, "source": source,
                                 "line_no": i, "bbox": l["bbox"], "text": l["text"], "conf": l["conf"],
                                 "retried": l["retry"] is not None, "figure_internal": fig})

scan_lines_df = pd.DataFrame(scan_records)
graphics_df = pd.DataFrame(graphic_records)
figure_bands_df = pd.DataFrame(band_records)
print("Scanned-page lines:", len(scan_lines_df), scan_lines_df.groupby("source").size().to_dict())
print("Figure-internal lines:", scan_lines_df.groupby("source")["figure_internal"].sum().to_dict())
print("Graphic regions:", graphics_df.groupby(["source", "kind"]).size().to_dict())
fig_pages = scan_lines_df[scan_lines_df["figure_internal"]].groupby(["report_id", "page_number", "source"]).size()
with pd.option_context("display.max_rows", None):
    display(fig_pages.rename("figure_internal_lines"))

# %% cell 21
# =========================================================
# 1b.5 Readability gate (body lines only)
# =========================================================
GATE_MIN_DICT_SHARE = 0.75       # below the lowest page reviewed as fully readable (H20_BELOW p.15: 0.781, diving terms)
GATE_MIN_MEAN_CONF = 0.90
WORD_RE = re.compile(r"[A-Za-z]+")

_vocab_counts = Counter(w.lower() for t in pages_df.loc[pages_df["text_class"] == "text", "text"] for w in WORD_RE.findall(t))
OCR_VOCAB = {w for w, n in _vocab_counts.items() if n >= 2 and len(w) >= 2}


def gate_measures(lines: pd.DataFrame) -> dict:
    words = [w.lower() for t in lines["text"] for w in WORD_RE.findall(t) if len(w) >= 2]
    confs = lines["conf"].dropna()
    return {"body_lines": len(lines), "words": len(words),
            "dict_share": round(float(np.mean([w in OCR_VOCAB for w in words])), 3) if words else 0.0,
            "mean_word_len": round(float(np.mean([len(w) for w in words])), 2) if words else 0.0,
            "mean_conf": round(float(confs.mean()), 4) if len(confs) else None}


gate_records = []
for (rid, p, source), grp in scan_lines_df.groupby(["report_id", "page_number", "source"]):
    m = gate_measures(grp[~grp["figure_internal"]])
    passed = m["dict_share"] >= GATE_MIN_DICT_SHARE and (m["mean_conf"] is None or m["mean_conf"] >= GATE_MIN_MEAN_CONF)
    gate_records.append({"report_id": rid, "page_number": p, "source": source,
                         "text_class": grp["text_class"].iloc[0], **m,
                         "figure_internal_lines": int(grp["figure_internal"].sum()), "gate": "pass" if passed else "fail"})
gate_df = pd.DataFrame(gate_records)

print("Dictionary:", len(OCR_VOCAB), "words | thresholds: dict_share >=", GATE_MIN_DICT_SHARE, "| mean_conf >=", GATE_MIN_MEAN_CONF)
print("Gate:", gate_df.groupby(["source", "gate"]).size().to_dict())
with pd.option_context("display.max_rows", None):
    display(gate_df.sort_values("dict_share").head(12))

# %% cell 22
# =========================================================
# 1b.6 OCR layers: gate + word agreement with the independent RapidOCR reading
# =========================================================

def word_agreement(a: str, b: str) -> float:
    wa, wb = WORD_RE.findall(a.lower()), WORD_RE.findall(b.lower())
    return round(difflib.SequenceMatcher(None, wa, wb, autojunk=False).ratio(), 3)


layer_check = []
for (rid, p), grp in scan_lines_df[scan_lines_df["text_class"] == "ocr_layer"].groupby(["report_id", "page_number"]):
    body = grp[~grp["figure_internal"]]
    txt = {s: "\n".join(body.loc[body["source"] == s, "text"]) for s in ("layer", "rapidocr")}
    g = gate_df.set_index(["report_id", "page_number", "source"])
    layer_check.append({"report_id": rid, "page_number": p,
                        "layer_dict_share": g.at[(rid, p, "layer"), "dict_share"],
                        "rapidocr_dict_share": g.at[(rid, p, "rapidocr"), "dict_share"],
                        "word_agreement": word_agreement(txt["layer"], txt["rapidocr"]),
                        "layer_gate": g.at[(rid, p, "layer"), "gate"]})
layer_check_df = pd.DataFrame(layer_check)
layer_check_df["decision"] = np.where(layer_check_df["layer_gate"] == "pass", "keep_layer", "re_ocr")
display(layer_check_df)

# %% cell 23
# =========================================================
# 1b.7 Text source of every page + weak OCR lines
# =========================================================
# text source per page: native layer (text), existing OCR layer (ocr_layer, gate passed) or RapidOCR (image_only)
source_of = {}
for r in pages_df.itertuples():
    if r.text_class == "text":
        source_of[(r.report_id, r.page_number)] = "native"
    elif r.text_class == "ocr_layer":
        keep = layer_check_df.set_index(["report_id", "page_number"]).at[(r.report_id, r.page_number), "decision"] == "keep_layer"
        source_of[(r.report_id, r.page_number)] = "ocr_layer" if keep else "ocr"
    else:
        source_of[(r.report_id, r.page_number)] = "ocr"
pages_df["text_source"] = [source_of[(r.report_id, r.page_number)] for r in pages_df.itertuples()]

# the lines that are actually used as page text: RapidOCR on image_only pages, the kept layer on ocr_layer pages
scan_lines_df["used"] = (((scan_lines_df["source"] == "rapidocr") & (scan_lines_df["text_class"] == "image_only"))
                         | ((scan_lines_df["source"] == "layer") & (scan_lines_df["text_class"] == "ocr_layer")))

# OCR noise: a weak reading (< 0.80 after the retry) of at most two characters is a mark, not text
# (reviewed on the renders: a misread of the letterhead seal, a pen stroke of a signature)
OCR_NOISE_MAX_CONF, OCR_NOISE_MAX_CHARS = 0.80, 2
scan_lines_df["ocr_noise"] = (scan_lines_df["conf"].fillna(1.0) < OCR_NOISE_MAX_CONF) \
    & (scan_lines_df["text"].str.replace(" ", "").str.len() <= OCR_NOISE_MAX_CHARS) & ~scan_lines_df["figure_internal"]

used = scan_lines_df[scan_lines_df["used"]]
weak = used[(used["conf"] < OCR_NOISE_MAX_CONF) & ~used["figure_internal"]]
print("Text source per page:", pages_df["text_source"].value_counts().to_dict())
print(f"Used scanned-page lines: {len(used)} | figure-internal {int(used['figure_internal'].sum())} "
      f"| OCR noise {int(used['ocr_noise'].sum())} | weak body lines (< {OCR_NOISE_MAX_CONF}) {len(weak)}")
with pd.option_context("display.max_rows", None, "display.max_colwidth", 90):
    display(weak[["report_id", "page_number", "line_no", "conf", "ocr_noise", "text"]])
    print("Figure-internal lines of >= 6 words (reviewed on the renders):")
    display(used[used["figure_internal"] & used["text"].str.split().str.len().ge(6)][["report_id", "page_number", "text"]])

# %% cell 24
# =========================================================
# 1b.8 Phase 1b validation
# =========================================================
# ---- cache: one entry per OCR'd page, current key, every line with a confidence ----
assert len(ocr_results) == len(OCR_TARGETS) == 134
for (rid, p), res in ocr_results.items():
    assert res["key"] == ocr_cache_key(rid, p) and ocr_cache_path(rid, p).is_file(), (rid, p)
    assert all(0.0 <= l["conf"] <= 1.0 for l in res["lines"]), (rid, p)
assert sorted(f.name for f in OCR_CACHE_DIR.glob("*.json")) == sorted(ocr_cache_path(r, p).name for r, p in ocr_results)
# ---- the retry of weak lines works (evidence of 1b.0: UNA_MAS p.5) ----
una5 = [l for l in ocr_results[("UNA_MAS", 5)]["lines"] if l["retry"] and l["retry"]["kept"] == "retry"]
assert any(l["text"].startswith("vessel capsized, turning over port side first") for l in una5)

# ---- gate: every page used as text passes; every OCR layer is kept ----
assert (gate_df["gate"] == "pass").all(), gate_df[gate_df["gate"] == "fail"]
assert (layer_check_df["decision"] == "keep_layer").all() and len(layer_check_df) == 19
assert pages_df["text_source"].value_counts().to_dict() == {"native": 446, "ocr": 115, "ocr_layer": 19}
every_scanned_page_has_text = used.groupby(["report_id", "page_number"]).size()
assert len(every_scanned_page_has_text) == 134, "Every image_only / ocr_layer page carries text (no bare photo page)."

# ---- reviewed snapshot (2026-09-26) ----
REVIEWED_MIN_DICT_PAGE = ("H20_BELOW", 15, "rapidocr")          # 0.781: readable; diving terms absent from native pages
lowest = gate_df.sort_values("dict_share").iloc[0]
assert (lowest["report_id"], lowest["page_number"], lowest["source"]) == REVIEWED_MIN_DICT_PAGE
REVIEWED_OCR_NOISE = {("H20_BELOW", 6, "3"), ("H20_BELOW", 16, "V")}   # letterhead-seal misread; signature pen stroke
assert set(map(tuple, used.loc[used["ocr_noise"], ["report_id", "page_number", "text"]].values)) == REVIEWED_OCR_NOISE
assert weak["ocr_noise"].all(), "Every weak body line is reviewed OCR noise."
REVIEWED_LONG_FIGURE_LINES = {        # text printed inside figures (checked on the renders, 2026-09-26)
    ("H20_BELOW", 12): 1,             # dive-computer screen header
    ("MERRICK", 16): 1,               # map title 'CT Department of Agriculture Bureau of Aquaculture' (layer)
    ("QUEEN_OF_THE_WEST", 13): 1,     # label on the damage diagram
    ("UNA_MAS", 10): 8,               # capacity plate in the photo
}
long_fig = used[used["figure_internal"] & used["text"].str.split().str.len().ge(6)].groupby(["report_id", "page_number"]).size()
assert long_fig.to_dict() == REVIEWED_LONG_FIGURE_LINES, long_fig.to_dict()
REVIEWED_FIGURE_INTERNAL = 417
assert int(used["figure_internal"].sum()) == REVIEWED_FIGURE_INTERNAL, int(used["figure_internal"].sum())


print("✅ Phase 1b validation passed.")
print(f"OCR'd pages: {len(ocr_results)} (cache) | text source: {pages_df['text_source'].value_counts().to_dict()}")
print(f"Gate: all {len(gate_df)} page readings pass | lowest dict share {lowest['dict_share']} ({REVIEWED_MIN_DICT_PAGE[0]} p.{REVIEWED_MIN_DICT_PAGE[1]})")
print(f"Scanned lines used: {len(used)} | figure-internal {int(used['figure_internal'].sum())} | OCR noise {int(used['ocr_noise'].sum())}")

# %% [markdown] cell 25
# # Phase 2 — Line and row tables + ROI template spec (learned from the sample)
#
# **One line table for the whole corpus (2.1).** Every text line of every page, whatever its source, in one shape:
# native lines come from `page_dict()` (superscript footnote markers split off, as in the IMO notebook), scanned pages
# contribute the lines chosen in Phase 1b (RapidOCR on `image_only` pages, the kept layer on `ocr_layer` pages) with their
# confidence, `figure_internal` and `ocr_noise` flags. `provenance` ∈ {`native`, `ocr_layer`, `ocr`} stays on every line
# so OCR text can always be told apart (plan §4.2).
#
# **Rows by baseline (2.2).** One printed row = the lines of one page whose baselines agree (native: ±2.5 pt; OCR: box
# bottoms within max(3 pt, 35 % of the box height)). A row's text is its segments in x order, so a vessel-table label
# and its value, or "8." and "Recommendations" (BIG_STICK), become one row.
#
# **The ROI template (2.3)** — written from the seeded sample (VICAR_602, CUMBERLAND_II, BIG_STICK, KIM_LY) and the OCR
# sample (UNA_MAS), then widened only with the variants the fingerprint (Phase 3) found in the other reports:
#
# | Part | What the template expects | Variants found |
# |---|---|---|
# | Cover (p.1) | "Report of (the) Investigation into the …", MISLE Activity Number | image-only on 7 reports (OCR'd) |
# | Letter start | file block `16732…` + date at the right, letterhead above it | continuation pages repeat file block + date |
# | Casualty title | bold capitals, centred, above each letter heading | wording differs between letters of one report |
# | Letters | ACTION BY THE COMMANDANT (+ ACTION ON RECOMMENDATION[S]); ENDORSEMENT BY THE COMMANDER, <district> (+ ENDORSEMENT ON RECOMMENDATIONS); ENDORSEMENT BY THE OFFICER IN CHARGE, MARINE INSPECTION (+ COMMENTS ON THE REPORT); EXECUTIVE SUMMARY | "COMMANDANT'S ACTION ON REPORT OF INVESTIGATION"; "ENDORSEMENT/RECOMMENDATIONS"; "MARINE INSPECTIONS"; district name on its own row; "ENDORSEMENT BY THE DISTRICT COMMANDER" |
# | Report | INVESTIGATING OFFICER'S REPORT, sections 1–8 | "DISTRICT FORMAL INVESTIGATION REPORT" (SPIRIT_OF_BOSTON); a 2013 **memorandum** (QUEEN_OF_THE_WEST: From/To/Subj/Ref, "Findings of Fact:" …) |
# | Section titles | 1 Preliminary Statement · 2 Vessel(s) Involved in the Incident · 3 Deceased, Missing, and/or Injured Persons · 4 Findings of Fact · 5 Analysis · 6 Conclusions · 7 Actions Taken Since the Incident · 8 Recommendations | "Vessels and Motor Vehicle Involved", "Craft Involved", "Record of Deceased, Missing, and Injured", "Finding of Fact"; memo "Vessel Data:", "Personnel Data:"; numbers missing (CUMBERLAND_II 7–8) or slipped (BIG_STICK "5. Conclusions", LA6893ER "4. Analysis") |
# | Numbering | `4.1.1.` paragraphs, depth = number of levels | trailing dot optional ("6.4 Evidence …") |
# | Vessel block | label column + value column: Official Name, Identification Number, Flag, Vessel Class/Type/Sub-Type, Build Year, Gross Tonnage, Length, Beam/Width, Draft/Depth, Main/Primary Propulsion, Owner, Operator | "Vessel Name:", "Gross Tons:", memo "Name:", "Official Number:", "Service:" |
# | Persons table | Relationship to Vessel · Sex · Age · Status | "Relationship to Motor Vehicle"; memo "Deceased Age Position Period of Employment" |
# | Figures | caption "Figure N." / "Figure N:" / "Figure N -" under the image | photo credits run on the next caption row |
# | Layout | page number at the bottom centre (arabic or roman), "Enclosure (1)" footer, running header on PROWLER_ATTESSA_IV / QUEEN_OF_THE_WEST, table of contents (CAROL_ANN, CONCHRD, PROWLER_ATTESSA_IV, SPIRIT_OF_BOSTON) | |
# | Signature block | NAME in capitals, rank ", U.S. Coast Guard", office lines ("By Direction", "Chief, …") | the signature itself is usually redacted (black box) |

# %% cell 26
# =========================================================
# 2.1 Unified line table (native + OCR, all 23 reports)
# =========================================================
BODY_SIZE = 12.0                       # Word body text (Times New Roman 12 pt) in the native reports
MIN_IMAGE_W, MIN_IMAGE_H = 60, 40      # an image placement large enough to carry labels


def is_bold_span(s: dict) -> bool:
    return bool(s["flags"] & 16) or "Bold" in s["font"]


# ---- character repairs (reviewed, 2026-09-26) ----
# (1) Native text: control characters 0x03–0x1F are glyph codes of subset fonts without a Unicode map, shifted by 29
#     (0x03 -> space, 0x11 -> '.', 0x13–0x1C -> '0'–'9'). Evidence: CUMBERLAND_II '4.1.1\x11 At 1151' (paragraph dots)
#     and '\x1a\x11 Actions Taken…' / '\x1b\x11 Recommendations' between 6.7 and 8.1 (-> '7.', '8.'); BIG_STICK file date
#     '2\x19 Jan 2026' (-> 26 Jan); NC3250BW '2\x17 October 2025' (-> 24 October); LA6893ER '\x03' spaces and page numbers.
# (2) OCR / OCR-layer text: control characters are misreadings of the letterhead seal -> removed.
# (3) CUYAHOGA's font maps the right quote to '¶' and the en dash to '±' ("Officer¶s Report", "Department¶s swift
#     actions", "Fire Department ± Fire Prevention Bureau") -> repaired for that report only ('½' is a real fraction).
GLYPH_SHIFT = 29
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
REPORT_CHAR_REPAIRS = {"CUYAHOGA": {"¶": "’", "±": "–"}}
text_repairs = Counter()


def clean_text(t: str, rid: str, provenance: str) -> str:
    if CONTROL_RE.search(t):
        if provenance == "native":
            text_repairs[(rid, "glyph_shift_29")] += len(CONTROL_RE.findall(t))
            t = CONTROL_RE.sub(lambda m: chr(ord(m.group(0)) + GLYPH_SHIFT), t)
        else:
            text_repairs[(rid, "ocr_control_removed")] += len(CONTROL_RE.findall(t))
            t = CONTROL_RE.sub("", t)
    for bad, good in REPORT_CHAR_REPAIRS.get(rid, {}).items():
        if bad in t:
            text_repairs[(rid, f"{bad}->{good}")] += t.count(bad)
            t = t.replace(bad, good)
    return " ".join(unicodedata.normalize("NFC", t).replace("­", "").split())


line_records = []
for r in pages_df.itertuples():
    rid, p = r.report_id, r.page_number
    if r.text_source == "native":
        page = docs[rid][p - 1]
        images = [i["bbox"] for i in page.get_image_info()
                  if i["bbox"][2] - i["bbox"][0] >= MIN_IMAGE_W and i["bbox"][3] - i["bbox"][1] >= MIN_IMAGE_H]
        k = 0
        for b in page_dict(rid, p)["blocks"]:
            for l in b["lines"]:
                spans = [s for s in l["spans"] if s["text"].strip()]
                if not spans:
                    continue
                main = max(spans, key=lambda s: len(s["text"].strip()))
                sup = lambda s: bool(s["flags"] & 1) and s["size"] < 0.8 * main["size"]
                text = clean_text("".join(s["text"] for s in l["spans"] if not sup(s)), rid, "native")
                if not text:
                    continue
                x0, y0, x1, y1 = l["bbox"]
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                line_records.append({
                    "line_key": f"{rid}|{p:03d}|n{k:04d}", "report_id": rid, "page_number": p, "provenance": "native",
                    "x0": round(x0, 1), "y0": round(y0, 1), "x1": round(x1, 1), "y1": round(y1, 1),
                    "baseline": round(main["origin"][1], 1), "text": text,
                    "markers": [s["text"].strip() for s in l["spans"] if sup(s) and s["text"].strip()],
                    "size": round(main["size"], 1), "bold": all(is_bold_span(s) for s in spans if not sup(s)),
                    "conf": np.nan, "in_image": any(a[0] <= cx <= a[2] and a[1] <= cy <= a[3] for a in images),
                    "figure_internal": False, "ocr_noise": False})
                k += 1
    else:
        used_here = scan_lines_df[(scan_lines_df["report_id"] == rid) & (scan_lines_df["page_number"] == p)
                                  & scan_lines_df["used"]]
        for s in used_here.itertuples():
            x0, y0, x1, y1 = s.bbox
            text = clean_text(s.text, rid, "ocr" if r.text_source == "ocr" else "ocr_layer")
            if not text:
                continue
            line_records.append({
                "line_key": f"{rid}|{p:03d}|{'o' if s.source == 'rapidocr' else 'l'}{s.line_no:04d}",
                "report_id": rid, "page_number": p, "provenance": "ocr" if r.text_source == "ocr" else "ocr_layer",
                "x0": x0, "y0": y0, "x1": x1, "y1": y1, "baseline": round(y1 - 0.2 * (y1 - y0), 1), "text": text,
                "markers": [], "size": np.nan, "bold": None, "conf": s.conf, "in_image": False,
                "figure_internal": bool(s.figure_internal), "ocr_noise": bool(s.ocr_noise)})

lines_df = pd.DataFrame(line_records)
lines_df["n_chars"] = lines_df["text"].str.len()
print("Lines:", len(lines_df), lines_df["provenance"].value_counts().to_dict())
print("Lines per report:", lines_df.groupby("report_id").size().to_dict())
print("Character repairs:", dict(text_repairs))
print("Native lines inside an image placement:", int(lines_df["in_image"].sum()),
      "| OCR figure-internal:", int(lines_df["figure_internal"].sum()), "| OCR noise:", int(lines_df["ocr_noise"].sum()))

# %% cell 27
# =========================================================
# 2.2 Rows by baseline
# =========================================================
NATIVE_ROW_TOL = 2.5


def row_tolerance(r) -> float:
    return NATIVE_ROW_TOL if r.provenance == "native" else max(3.0, 0.35 * (r.y1 - r.y0))


row_records, row_of_line = [], {}
for (rid, p), grp in lines_df.groupby(["report_id", "page_number"], sort=True):
    grp = grp.sort_values(["baseline", "x0"])
    members, base = [], None
    groups = []
    for r in grp.itertuples():
        if members and abs(r.baseline - base) > row_tolerance(r):
            groups.append(members)
            members = []
        if not members:
            base = r.baseline
        members.append(r.Index)
    if members:
        groups.append(members)
    # a baseline group is split into rows whose segments never overlap horizontally and (native) share a font size:
    # a caption printed across a body line (SPIRIT_OF_BOSTON p.18), two captions on one baseline (WAYMON_BOYD p.17)
    # or a stray glyph of an OCR layer (MERRICK p.15) stays a row of its own
    split_groups = []
    for m in groups:
        subrows: list[list[int]] = []
        for i in sorted(m, key=lambda i: lines_df.at[i, "x0"]):
            li = lines_df.loc[i]
            for sr in subrows:
                last = lines_df.loc[sr[-1]]
                same_size = li["provenance"] != "native" or abs(li["size"] - last["size"]) <= 1.5
                if li["x0"] >= last["x1"] - 2.0 and same_size:
                    sr.append(i)
                    break
            else:
                subrows.append([i])
        split_groups.extend(subrows)
    groups = sorted(split_groups, key=lambda m: (lines_df.loc[m, "y0"].min(), lines_df.loc[m, "x0"].min()))
    for k, m in enumerate(groups):
        seg = lines_df.loc[m].sort_values("x0")
        row_id = f"{rid}|{p:03d}|r{k:03d}"
        native = seg["provenance"].eq("native").all()
        row_records.append({
            "row_id": row_id, "report_id": rid, "page_number": p,
            "provenance": seg["provenance"].iloc[0],
            "x0": float(seg["x0"].min()), "y0": float(seg["y0"].min()), "x1": float(seg["x1"].max()),
            "y1": float(seg["y1"].max()), "baseline": float(seg["baseline"].min()),
            "text": " ".join(seg["text"]), "segments": [(float(a), float(b), t) for a, b, t in zip(seg["x0"], seg["x1"], seg["text"])],
            "line_keys": seg["line_key"].tolist(), "markers": [mk for ms in seg["markers"] for mk in ms],
            "bold": bool(seg["bold"].all()) if native else None,
            "size": float(seg["size"].max()) if native else np.nan,
            "height": float((seg["y1"] - seg["y0"]).median()),
            "conf": float(seg["conf"].min()) if not native else np.nan,
            "in_image": bool(seg["in_image"].any()),
            "figure_internal": bool(seg["figure_internal"].all()), "ocr_noise": bool(seg["ocr_noise"].all()),
        })
        for i in m:
            row_of_line[i] = row_id

rows_df = pd.DataFrame(row_records).sort_values(["report_id", "page_number", "y0", "x0"]).reset_index(drop=True)
lines_df["row_id"] = lines_df.index.map(row_of_line)
rows_df["centre"] = (rows_df["x0"] + rows_df["x1"]) / 2
print(f"Rows: {len(rows_df)} from {len(lines_df)} lines | rows with several segments: "
      f"{int(rows_df['segments'].map(len).gt(1).sum())}")
print(rows_df.loc[(rows_df["report_id"] == "BIG_STICK") & rows_df["text"].str.contains("Recommendations$"),
                  ["page_number", "text", "segments"]].to_string())

# %% cell 28
# =========================================================
# 2.3 ROI template spec (reviewed, 2026-09-26)
# =========================================================
ROI_TEMPLATE = {
    # letter headings: centred capitals; a heading may continue on the next row (district name)
    "letters": {
        "action_commandant": r"^(ACTION BY THE COMMANDANT|COMMANDANT.?S ACTION ON (THE )?REPORT OF (THE )?INVESTIGATION)$",
        "action_on_recommendations": r"^ACTION ON (THE )?RECOMMENDATIONS?$",
        "endorsement_district": r"^ENDORSEMENT BY THE (DISTRICT )?COMMANDER\b.*$",
        "endorsement_ocmi": r"^ENDORSEMENT BY THE OFFICER IN CHARGE,? MARINE INSPECTIONS?$",
        "endorsement_on_recommendations": r"^(ENDORSEMENTS? ON (THE )?RECOMMENDATIONS?|ENDORSEMENT/RECOMMENDATIONS"
                                          r"|ENDORSEMENT/ACTION ON (SAFETY |ADMINISTRATIVE )?RECOMMENDATIONS)$",
        "comments_on_report": r"^COMMENTS ON THE\s?REPORT$",
        "executive_summary": r"^EXECUTIVE SUMMARY:?$",
        "io_report": r"^(INVESTIGATING\s?OFFICER.?S REPORT|DISTRICT FORMAL INVESTIGATION REPORT|MEMORANDUM)$",
    },
    "front_matter": {
        "table_of_contents": r"^(TABLE OF CONTENTS|Table of Contents)$",
        "list_of_acronyms": r"^LIST OF ACRONYMS$",
    },
    # report sections: number optional (missing or slipped in some reports), trailing colon optional (memorandum)
    "sections": {
        1: r"Preliminary Statement",
        2: r"(Vessels?|Vessel\(s\)|Craft)( and Motor Vehicles?)? Involved( in the (Incident|Casualty|Accident))?|Vessel Data"
           r"|The [Vv]essel",
        3: r"(Record of )?Deceased,? Missing,? and(/or)? Injured( Persons)?|Personnel Data",
        4: r"Findings? of Fact",
        5: r"Analysis",
        6: r"Conclusions?",
        7: r"Actions Taken Since the (Incident|Casualty|Accident)",
        8: r"Recommendations?",
    },
    "section_suffix": r"(\s*[-–—]\s*.+)?",      # SPIRIT_OF_BOSTON: "3. Findings of Fact – The Incident", "4. … - Additional…"
    "paragraph_number": r"^(\d{1,2}(?:\.\d{1,2}){1,5})\.?(?=\s|$)",
    "file_block": r"^16732\b",
    "cover": r"(?:REPORT OF (?:THE )?(?:DISTRICT FORMAL )?INVESTIGATION|INCIDENT INVESTIGATION REPORT)",
    # figure captions, table captions (SPIRIT_OF_BOSTON) and "Above : Photograph of …" (PROWLER_ATTESSA_IV)
    "caption": r"^(?:Fig(?:ure|\.)?\s*\d+\s*[.:\-–—]?|Table\s*\d+\s*[.:\-–—]|Above\s*:\s*Photo)",
    "page_number": r"^([ivxlc]{1,5}|\d{1,3})$",
    "enclosure_footer": r"^Enclosure\s*\(\d+\)$",
    "vessel_label": r"^(Official Name/State Number|Official Name|Vessel Name|Name|Identification Number|Vessel Identification Number|Official Number"
                    r"|Flag|Vessel Class/Type/Sub-?Type|Service|Build Year|Gross Tonnage|Gross Tons|Length|Beam/Width"
                    r"|Draft/Depth|Draft|Hull Material|Main/Primary Propulsion|Main Primary Propulsion|Propulsion|Owner"
                    r"|Operator)\s*:?",
    "persons_header": r"^(?:Relationship to (?:Vessel|Motor Vehicle|Craft)\b.*|Deceased Age Position.*|Name \(First.*Status)",
    "memo_header": r"^(MEMORANDUM|From:|To:|Subj:|Ref:)",
    "rank": r"(Captain|Commander|Lieutenant( Commander)?|Rear Admiral|Vice Admiral|Chief Warrant Officer|Ensign)\b.*"
            r"U\.\s?S\.\s?Coast Guard",
}
LETTER_RE = {k: re.compile(v) for k, v in ROI_TEMPLATE["letters"].items()}
FRONT_RE = {k: re.compile(v) for k, v in ROI_TEMPLATE["front_matter"].items()}
SECTION_RE = {k: re.compile(rf"^(?:(?P<num>\d{{1,2}})\s*\.?\s*)?(?P<title>{v}){ROI_TEMPLATE['section_suffix']}\s*:?$",
                            re.IGNORECASE) for k, v in ROI_TEMPLATE["sections"].items()}
PARA_NUM_RE = re.compile(ROI_TEMPLATE["paragraph_number"])
FILE_BLOCK_RE = re.compile(ROI_TEMPLATE["file_block"])
CAPTION_START_RE = re.compile(ROI_TEMPLATE["caption"], re.IGNORECASE)
PAGE_NUMBER_RE = re.compile(ROI_TEMPLATE["page_number"], re.IGNORECASE)
ENCLOSURE_FOOTER_RE = re.compile(ROI_TEMPLATE["enclosure_footer"])
VESSEL_LABEL_RE = re.compile(ROI_TEMPLATE["vessel_label"], re.IGNORECASE)
PERSONS_HEADER_RE = re.compile(ROI_TEMPLATE["persons_header"], re.IGNORECASE)
MEMO_HEADER_RE = re.compile(ROI_TEMPLATE["memo_header"])
RANK_RE = re.compile(ROI_TEMPLATE["rank"])


def letter_of(text: str) -> str | None:
    t = " ".join(text.split()).upper().replace("’", "'")
    return next((k for k, rx in LETTER_RE.items() if rx.match(t)), None)


def section_of(text: str) -> tuple[int, str | None] | None:
    t = " ".join(text.split())
    for k, rx in SECTION_RE.items():
        if m := rx.match(t):
            return k, m.group("num")
    return None


assert letter_of("ACTION BY THE COMMANDANT") == "action_commandant"
assert letter_of("INVESTIGATING OFFICER’S REPORT") == letter_of("INVESTIGATINGOFFICER'S REPORT") == "io_report"
assert section_of("2. Vessels and Motor Vehicle Involved in the Incident") == (2, "2")
assert section_of("Actions Taken Since the Incident") == (7, None) and section_of("5. Conclusions") == (6, "5")
assert section_of("Findings of Fact:") == (4, None) and section_of("8.1. Safety Recommendation:") is None
print("ROI template ready:", len(LETTER_RE), "letter headings,", len(SECTION_RE), "sections")

# %% cell 29
# =========================================================
# 2.4 Phase 2 validation
# =========================================================
assert lines_df["line_key"].is_unique and rows_df["row_id"].is_unique
assert lines_df["row_id"].notna().all(), "Every line belongs to exactly one row."
assert sorted(k for ks in rows_df["line_keys"] for k in ks) == sorted(lines_df["line_key"])
assert set(lines_df.groupby(["report_id", "page_number"]).groups) == set(zip(pages_df["report_id"], pages_df["page_number"])), \
    "Every page contributes text (all 134 scanned pages carry text, Phase 1b)."
assert (lines_df.loc[lines_df["provenance"] == "ocr", "conf"].between(0, 1)).all()
assert lines_df.loc[lines_df["provenance"] != "ocr", "ocr_noise"].eq(False).all()
# rows never join two lines that overlap horizontally (that would be two printed rows)
for r in rows_df[rows_df["segments"].map(len) > 1].itertuples():
    xs = sorted(lines_df.set_index("line_key").loc[r.line_keys, ["x0", "x1"]].itertuples(index=False))
    assert all(a.x1 <= b.x0 + 2.0 for a, b in zip(xs, xs[1:])), f"Overlapping segments in one row: {r.row_id} {r.text[:60]!r}"

# ---- reviewed snapshot (2026-09-26) ----
REVIEWED_LINES = {"native": 14224, "ocr": 4085, "ocr_layer": 690}   # 14 lines were control characters only (no text)
assert lines_df["provenance"].value_counts().to_dict() == REVIEWED_LINES, lines_df["provenance"].value_counts().to_dict()
print("✅ Phase 2 validation passed.")
print("Lines:", len(lines_df), REVIEWED_LINES, "| rows:", len(rows_df))

# %% [markdown] cell 30
# # Phase 3 — Template fingerprint of all 23 reports (text only) + 3b individual inspection of the deviating ones
#
# Every report is compared with the ROI template of Phase 2 using the row texts only (no layout parsing): cover page,
# letter headings, the start of the investigating officer's report, the eight sections (found, order, printed number),
# vessel-block labels, persons table, figure captions, table of contents, running header. What differs from the
# template is a **deviation**; a report without deviation is `conformant`.
#
# **3b** — each deviating report was then inspected individually (only those), and every deviation receives a recorded
# decision: how the parser handles it. The reviewed list is asserted against the computed one, so a new or vanished
# deviation stops the notebook.

# %% cell 31
# =========================================================
# 3.1 Fingerprint
# =========================================================
TOP_BAND, BOTTOM_BAND = 90.0, 700.0
COVER_RE = re.compile(ROI_TEMPLATE["cover"], re.IGNORECASE)


def mask_digits(t: str) -> str:
    return re.sub(r"\d+", "#", " ".join(t.split()).upper())


fingerprint_records, section_hits = [], []
for rid, g in rows_df.groupby("report_id", sort=True):
    g = g.sort_values(["page_number", "y0"])
    letters = [(r.page_number, r.y0, letter_of(r.text)) for r in g.itertuples() if letter_of(r.text)]
    front = {k: sorted({r.page_number for r in g.itertuples() if rx.match(" ".join(r.text.split()))})
             for k, rx in FRONT_RE.items()}
    toc_pages = set(front["table_of_contents"])
    io = [(p, y) for p, y, k in letters if k == "io_report"]
    # the report body starts at its heading; two reports print none (CUYAHOGA, LITTLE_G) and start directly with
    # "1. Preliminary Statement"; the convening MEMORANDUM of SPIRIT_OF_BOSTON is front matter (its report has a heading)
    real_io = [(p, y) for (p, y), k in zip([(a, b) for a, b, _ in letters], [k for _, _, k in letters])
               if k == "io_report" and not g.loc[(g["page_number"] == p) & (g["y0"] == y), "text"].str.strip().eq("MEMORANDUM").all()]
    prelim = [(r.page_number, r.y0) for r in g.itertuples()
              if r.x0 < 150 and section_of(r.text) and section_of(r.text)[0] == 1 and r.page_number not in toc_pages]
    io_start = (real_io or io or prelim or [(int(g["page_number"].max()) + 1, 0.0)])[0]
    secs = []
    for r in g.itertuples():
        if (r.page_number, r.y0) < io_start or r.page_number in toc_pages or r.x0 > 150 or len(r.text) > 90:
            continue
        hit = section_of(r.text)
        if hit and hit[0] not in [s[0] for s in secs]:
            secs.append((hit[0], hit[1], r.page_number, r.row_id))
    for s in secs:
        section_hits.append({"report_id": rid, "section": s[0], "printed_number": s[1], "page_number": s[2], "row_id": s[3]})
    # running header: a top-band row repeated on >= 3 pages of the report body (letterheads repeat on letter pages only)
    top = g[(g["y1"] <= TOP_BAND) & (g["page_number"] > io_start[0])]
    repeated = top.groupby(top["text"].map(mask_digits))["page_number"].nunique()
    fingerprint_records.append({
        "report_id": rid,
        "cover": bool(g[g["page_number"] == 1]["text"].str.contains(COVER_RE).any()),
        "letters": [k for _, _, k in letters],
        "memorandum": "MEMORANDUM" in set(g["text"].str.strip()) and not real_io,
        "io_start_page": io_start[0] if (io or prelim) else None,
        "report_heading": bool(io),
        "sections": [s[0] for s in secs], "printed": [s[1] for s in secs],
        "vessel_blocks": int(g["text"].str.match(r"^(?:Official Name|Vessel Name|Name)(?:/State Number)?\s*:", case=False).sum()),
        "persons_header": int(g["text"].str.match(PERSONS_HEADER_RE).sum()),
        "captions": int(g["text"].str.match(CAPTION_START_RE).sum()),
        "toc_pages": sorted(toc_pages), "acronym_pages": front["list_of_acronyms"],
        "running_header_rows": int((repeated >= 3).sum()),
    })
fingerprint_df = pd.DataFrame(fingerprint_records)
section_hits_df = pd.DataFrame(section_hits)


def deviations_of(f) -> list[str]:
    dev = []
    if not f["cover"]:
        dev.append("no_cover_title")
    if f["memorandum"]:
        dev.append("memorandum_format")
    if not f["report_heading"]:
        dev.append("no_report_heading")
    if f["letters"].count("action_commandant") != 1:
        dev.append(f"commandant_actions_{f['letters'].count('action_commandant')}")
    missing = [k for k in range(1, 9) if k not in f["sections"]]
    if missing:
        dev.append("sections_missing_" + "".join(map(str, missing)))
    if f["sections"] != sorted(f["sections"]):
        dev.append("sections_out_of_order")
    for k, n in zip(f["sections"], f["printed"]):
        if n is None and not f["memorandum"]:
            dev.append(f"section_{k}_unnumbered")
        elif n is not None and int(n) != k:
            dev.append(f"section_{k}_printed_{n}")
    if f["vessel_blocks"] == 0:
        dev.append("no_vessel_block_label")
    if f["persons_header"] == 0:
        dev.append("no_persons_table")
    if f["toc_pages"]:
        dev.append("table_of_contents")
    if f["acronym_pages"]:
        dev.append("list_of_acronyms")
    if f["running_header_rows"]:
        dev.append("running_header")
    return dev


fingerprint_df["deviations"] = fingerprint_df.apply(deviations_of, axis=1)
fingerprint_df["status"] = np.where(fingerprint_df["deviations"].map(len) == 0, "conformant", "deviating")
with pd.option_context("display.max_rows", None, "display.max_colwidth", 120, "display.width", 250):
    display(fingerprint_df[["report_id", "sections", "printed", "vessel_blocks", "persons_header", "captions",
                            "running_header_rows", "status", "deviations"]])
print(fingerprint_df["status"].value_counts().to_dict())

# %% cell 32
# =========================================================
# 3.2 (3b) Individual inspection of the deviating reports — reviewed decisions (2026-09-26)
# =========================================================
# Every deviation of 3.1 was inspected on the report itself (rows / renders); the decision says how the parser handles
# it. Numbering slips are recorded, never "corrected": the canonical section comes from the printed title.
REVIEWED_DEVIATIONS = {
    "BIG_STICK": {
        "section_6_printed_5": "numbering slip (plan §0): heading printed '5. Conclusions' above paragraphs 6.1–6.7 -> "
                               "canonical section 6 from the title; slip recorded"},
    "CAROL_ANN": {"table_of_contents": "front matter: table of contents (p.17) -> metadata, cross-checked with the headings"},
    "CONCHRD": {
        "table_of_contents": "front matter: table of contents (p.6) -> metadata, cross-checked with the headings",
        "list_of_acronyms": "front matter: list of acronyms (p.7) -> one glossary unit (expands the acronyms of the report)"},
    "CUYAHOGA": {"no_report_heading": "the investigating officer's report prints no heading: it starts at "
                                      "'1. Preliminary Statement' (p.10) -> report start anchored there"},
    "LA6893ER": {"section_5_printed_4": "numbering slip: heading printed '4. Analysis' after '4. Findings of Fact' -> "
                                        "canonical section 5 from the title; slip recorded"},
    "LITTLE_G": {"no_report_heading": "no report heading printed: starts at '1. Preliminary Statement' (p.6) -> anchored there"},
    "MICHIPICOTEN": {"no_persons_table": "Section 3 prints 'None' (no one killed, missing or injured) -> no persons rows"},
    "PROWLER_ATTESSA_IV": {
        "table_of_contents": "front matter: table of contents (p.6) -> metadata, cross-checked with the headings",
        "running_header": "casualty title + file number + date repeated at the top of every report page -> layout"},
    "QUEEN_OF_THE_WEST": {
        "memorandum_format": "2013 memorandum ROI (MEMORANDUM, From/To/Subj/Ref, 'Executive Summary:', 'Vessel Data:', "
                             "'Personnel Data:', 'Findings of Fact:' …, paragraphs numbered 1., 2. …) -> headings by "
                             "title, memorandum header -> metadata, 'Vessel Data' = section 2, 'Personnel Data' = section 3",
        "commandant_actions_2": "two Commandant letters: closure of the investigation (20 Oct 2022) and action on the 17 "
                                "recommendations (31 Aug 2026) -> both kept; version_date = the later action",
        "sections_missing_17": "the memorandum has no Preliminary Statement and no Actions Taken section -> nothing to parse",
        "running_header": "file number, subject line and date repeated on every memorandum page -> layout"},
    "SPIRIT_OF_BOSTON": {
        "sections_missing_3": "no Section 3: no one was killed, missing or injured; the Findings of Fact are printed as two "
                              "numbered sections '3. … – The Incident' and '4. … – Additional/Supporting Information'",
        "section_4_printed_3": "both Findings parts -> canonical section 4 (two parts, printed numbers recorded)",
        "no_persons_table": "no casualties -> no persons rows",
        "table_of_contents": "front matter: table of contents (p.12) -> metadata, cross-checked with the headings"},
    "VICAR_602": {"no_persons_table": "Section 3 is one sentence ('There were no deceased, missing, or injured personnel "
                                      "…') -> kept as a paragraph"},
}

actual_dev = {r.report_id: set(r.deviations) for r in fingerprint_df.itertuples() if r.deviations}
reviewed_dev = {k: set(v) for k, v in REVIEWED_DEVIATIONS.items()}
assert actual_dev == reviewed_dev, {
    "not reviewed": {k: actual_dev[k] - reviewed_dev.get(k, set()) for k in actual_dev if actual_dev[k] - reviewed_dev.get(k, set())},
    "vanished": {k: reviewed_dev[k] - actual_dev.get(k, set()) for k in reviewed_dev if reviewed_dev[k] - actual_dev.get(k, set())}}
deviation_decisions_df = pd.DataFrame([{"report_id": k, "deviation": d, "decision": t}
                                       for k, v in REVIEWED_DEVIATIONS.items() for d, t in v.items()])
with pd.option_context("display.max_colwidth", 140, "display.max_rows", None):
    display(deviation_decisions_df)

# %% cell 33
# =========================================================
# 3.3 Phase 3 validation
# =========================================================
assert len(fingerprint_df) == 23 and fingerprint_df["cover"].all(), "Every report has a cover title (p.1)."
assert fingerprint_df["io_start_page"].notna().all(), "Every report has a findable start of the report body."
fp = fingerprint_df.set_index("report_id")
assert fp.loc[["CUMBERLAND_II", "KIM_LY", "UNA_MAS"], "status"].eq("conformant").all()
# the template holds for every report that is not the memorandum: sections 1–8 in order (SPIRIT_OF_BOSTON: no section 3)
for r in fingerprint_df[~fingerprint_df["memorandum"]].itertuples():
    expected = [k for k in range(1, 9) if not (r.report_id == "SPIRIT_OF_BOSTON" and k == 3)]
    assert r.sections == expected, (r.report_id, r.sections)
# ---- reviewed snapshot (2026-09-26) ----
REVIEWED_STATUS = {"conformant": 12, "deviating": 11}
assert fingerprint_df["status"].value_counts().to_dict() == REVIEWED_STATUS, fingerprint_df["status"].value_counts().to_dict()
NUMBERING_SLIPS = {("BIG_STICK", 6): "5", ("LA6893ER", 5): "4", ("SPIRIT_OF_BOSTON", 4): "3"}
slips = {(r.report_id, r.section): r.printed_number for r in section_hits_df.itertuples()
         if pd.notna(r.printed_number) and int(r.printed_number) != r.section}
assert slips == NUMBERING_SLIPS, slips
print("✅ Phase 3 validation passed.")
print("Fingerprint:", fingerprint_df["status"].value_counts().to_dict(), "| deviations reviewed:", len(deviation_decisions_df),
      "| numbering slips:", NUMBERING_SLIPS)

# %% [markdown] cell 34
# # Phase 4 — Template-driven structured extraction
#
# One parser for all 23 reports (plan §1.1): it walks the rows of each report in reading order and gives every row a
# **role** from the ROI template (Phase 2) and the reviewed deviations (3b). No row is left without a role.
#
# | Role | Rows | Destination |
# |---|---|---|
# | `page_number`, `enclosure_footer`, `running_header`, `letterhead` | page furniture | layout (never chunked) |
# | `file_block`, `file_date` | "16732/IIA # …" + the date under it | metadata (the Commandant's date = `version_date`) |
# | `casualty_title` | the capitalised casualty title above each letter / report heading | metadata (report title) |
# | `cover` | page 1 ("Report of the Investigation into …", MISLE Activity Number) | metadata |
# | `toc`, `memo_header`, `enclosures` | table of contents, From/To/Subj/Ref, "Enclosures: (1) …" | metadata |
# | `signature` | the signer's name, rank and office under a letter | excluded (personal names, no retrieval value; the letter is identified by its heading) |
# | `letter_heading`, `section_heading`, `front_heading` | template headings | structure (titles, paths) |
# | `caption` | "Figure N …" and its continuation rows | figure units (ADR-020) |
# | `footnote` | native notes at the page bottom (smaller type, numbered) | notes policy (Phase 5) |
# | `figure_internal`, `ocr_noise` | text inside images / OCR marks (Phase 1b) | excluded with reason |
# | `body` | everything else | paragraphs (Phases 6–8) |
#
# Letters are delimited by their headings; the report body starts at its heading or, where none is printed
# (CUYAHOGA, LITTLE_G), at "1. Preliminary Statement" (3b).

# %% cell 35
# =========================================================
# 4.1 Row roles
# =========================================================
DATE_RE = re.compile(r"^(\d{1,2}\s*[A-Za-z]{3,9},?\s*\d{2,4}|[A-Za-z]{3,9}\.?\s+\d{1,2},?\s*\d{4}|\d{1,2}[A-Za-z]{3}\d{2})\.?$")
ENCLOSURES_RE = re.compile(r"^Encl(?:osures?)?\s*(?:\(\d+\))?\s*:", re.IGNORECASE)   # "Enclosures:", "Encl (1):"
ENCLOSURE_ITEM_RE = re.compile(r"^\(\d+\)\s")
SIGNATURE_OFFICE_RE = re.compile(r"^(By [Dd]irection|Acting\b|Chief\b|Commanding Officer|Officer in Charge|Investigating "
                                 r"Officer|Director\b|Office of|Captain of the Port|Commander\b|Prevention Division|"
                                 r"Deputy\b|Sector\b|Marine Safety|U\.S\. Coast Guard|District\b|Supervisor\b)")
OCR_CAPTION_RE = re.compile(r"^Fig(?:ure|\.)?\s*[lI]\s*[.:\-–—]")         # OCR read "1" as "l" (MERRICK p.6)


def is_caption_start(t: str) -> bool:
    t = t.strip()
    return bool((CAPTION_START_RE.match(t) or OCR_CAPTION_RE.match(t)) and not FIG_REFERENCE_RE.match(t)
                and not CFR_TABLE_RE.match(t))


# reviewed: body sentences wrapped so that a line starts with "Figure N." — the page has no image, the real caption
# of that figure is printed elsewhere (SPIRIT_OF_BOSTON Figure 16 on p.42)
REFERENCE_NOT_CAPTION = {("SPIRIT_OF_BOSTON", 40, "Figure 16. There is no separate slide")}


CFR_TABLE_RE = re.compile(r"^Table\s*\d+\.\d")          # "Table 2.01-7(a)(4), such as …": a CFR table (WAYMON_BOYD)
FIG_REFERENCE_RE = re.compile(r"^Fig(?:ure|\.)?\s*\d+\s*\)")
NAME_RE = re.compile(r"^[A-Z0-9][A-Z.\-’' ]*[A-Z]\.?\)?(?:,? JR\.?)?$")    # "E. B. SAMMS", "MATTHEW J. MESKUN", "D. H. COST"


def upper_share(t: str) -> float:
    letters = [c for c in t if c.isalpha()]
    return sum(c.isupper() for c in letters) / len(letters) if letters else 0.0


fp_by_report = fingerprint_df.set_index("report_id")
role_records = []
for rid, g in rows_df.groupby("report_id", sort=True):
    g = g.sort_values(["page_number", "y0", "x0"])
    role = {}
    body_start = (int(fp_by_report.at[rid, "io_start_page"]), 0.0)
    io_rows = g[g["text"].map(letter_of).eq("io_report")]
    if len(io_rows):
        body_start = (int(io_rows["page_number"].iloc[0]), float(io_rows["y0"].iloc[0]))
    toc_pages = set(fp_by_report.at[rid, "toc_pages"])
    # running header: top-band rows repeated on >= 3 body pages (3.1)
    # compared on their letters only and fuzzily: OCR reads the same header slightly differently on each page
    # ("PROWLER (O.N." / "PROWLER(O.N.", "FOLLOWING MAN" / "FOLLQWING MÁN")
    top = g[(g["y1"] <= TOP_BAND) & (g["page_number"] > body_start[0])]
    clusters: list[tuple[str, set]] = []
    for r in top.itertuples():
        key = re.sub(r"[^A-Z]", "", r.text.upper())
        if len(key) < 4:
            continue
        for ck, pages in clusters:
            if difflib.SequenceMatcher(None, key, ck).ratio() >= 0.85:
                pages.add(r.page_number)
                break
        else:
            clusters.append((key, {r.page_number}))
    running = [ck for ck, pages in clusters if len(pages) >= 3]


    def is_running(t: str) -> bool:
        key = re.sub(r"[^A-Z]", "", t.upper())
        return len(key) >= 4 and any(difflib.SequenceMatcher(None, key, ck).ratio() >= 0.85 for ck in running)


    for r in g.itertuples():
        t = r.text.strip()
        if r.ocr_noise:
            role[r.row_id] = "ocr_noise"
        elif r.figure_internal:
            role[r.row_id] = "figure_internal"
        elif r.y0 > BOTTOM_BAND and PAGE_NUMBER_RE.match(t) and abs(r.centre - 306) < 60:
            role[r.row_id] = "page_number"
        elif r.y0 > BOTTOM_BAND and ENCLOSURE_FOOTER_RE.match(t):
            role[r.row_id] = "enclosure_footer"
        elif not re.search(r"[A-Za-z0-9]", t):
            role[r.row_id] = "no_text"
        elif r.y1 <= TOP_BAND and r.page_number > body_start[0] and is_running(t):
            role[r.row_id] = "running_header"
        elif r.page_number == 1 and fp_by_report.at[rid, "cover"]:
            role[r.row_id] = "cover"
        elif r.page_number in toc_pages:
            role[r.row_id] = "toc"

    # ---- headings (a letter heading may continue on the next row: the district name) ----
    rows_list = [r for r in g.itertuples()]
    for i, r in enumerate(rows_list):
        if r.row_id in role:
            continue
        k = letter_of(r.text)
        if k and (abs(r.centre - 306) < 90 or r.text.strip().endswith(":")) or (k == "io_report" and r.text.strip() == "MEMORANDUM"):
            role[r.row_id] = "letter_heading"
            if k == "endorsement_district" and r.text.strip().endswith(",") and i + 1 < len(rows_list):
                nxt = rows_list[i + 1]
                if upper_share(nxt.text) > 0.9 and nxt.page_number == r.page_number:
                    role[nxt.row_id] = "letter_heading_cont"
        elif (r.page_number, r.y0) >= body_start and r.x0 < 150 and len(r.text) < 90 and section_of(r.text):
            role[r.row_id] = "section_heading"
        elif any(rx.match(" ".join(r.text.split())) for rx in FRONT_RE.values()):
            role[r.row_id] = "front_heading"

    # ---- letter / report starts, anchored on the first heading of a page (robust to OCR: "13732", merged rows) ----
    # above the heading: the capitalised casualty title; above it, at the right, the file block + date; the rest of
    # the top of the page is the letterhead
    for p, pg in g.groupby("page_number"):
        # anchor = the first letter heading; a report printed without heading starts at "1. Preliminary Statement"
        anchors = pg["row_id"].map(role).eq("letter_heading") | (
            ~fp_by_report.at[rid, "report_heading"] & pg["row_id"].map(role).eq("section_heading")
            & pg["text"].map(lambda t: (section_of(t) or (0,))[0] == 1))
        heads = pg[anchors].sort_values("y0")
        if heads.empty:
            continue
        h = heads.iloc[0]
        above = pg[(pg["y0"] < h.y0) & ~pg["row_id"].isin(role)].sort_values("y0", ascending=False)
        in_title = True
        for r in above.itertuples():
            t = r.text.strip()
            if in_title and upper_share(t) >= 0.85 and len(t) >= 3 and r.x0 > 55 and not FILE_BLOCK_RE.match(t) \
                    and not DATE_RE.match(t):
                role[r.row_id] = "casualty_title"
                continue
            in_title = False
            if r.x0 > 280 and (FILE_BLOCK_RE.match(t) or re.match(r"^1\d732\b", t) or re.match(r"^[A-Z]-\d{4,}", t)):
                role[r.row_id] = "file_block"
            elif r.x0 > 280 and DATE_RE.match(t):
                role[r.row_id] = "file_date"
            else:
                role[r.row_id] = "letterhead"
    # continuation pages of a letter repeat the file block + date at the top right
    for p, pg in g.groupby("page_number"):
        for r in pg[(pg["y0"] < 80) & (pg["x0"] > 280) & ~pg["row_id"].isin(role)].itertuples():
            t = r.text.strip()
            if FILE_BLOCK_RE.match(t):
                role[r.row_id] = "file_block"
            elif DATE_RE.match(t):
                role[r.row_id] = "file_date"

    # ---- memorandum header (From/To/Subj/Ref + their continuation rows) ----
    in_memo = False
    for r in rows_list:
        t = r.text.strip()
        if role.get(r.row_id) == "letter_heading" and t == "MEMORANDUM":
            in_memo = True
            continue
        if in_memo:
            if r.row_id in role:
                continue
            if MEMO_HEADER_RE.match(t) or (r.x0 > 95 and not PARA_NUM_RE.match(t) and not re.match(r"^\d+\.\s", t)):
                role[r.row_id] = "memo_header"
                continue
            in_memo = False

    # ---- signature blocks: a rank row (", U.S. Coast Guard") + the name above it + office rows below ----
    for i, r in enumerate(rows_list):
        if r.row_id in role or not RANK_RE.search(r.text) or r.x0 < 120 or len(r.text) > 90:
            continue
        role[r.row_id] = "signature"
        j = i - 1
        while j >= 0 and rows_list[j].page_number == r.page_number and rows_list[j].row_id not in role \
                and rows_list[j].x0 > 120 and r.y0 - rows_list[j].y1 < 30 and NAME_RE.match(rows_list[j].text.strip()):
            role[rows_list[j].row_id] = "signature"
            j -= 1
        j, prev = i + 1, r
        while j < len(rows_list) and rows_list[j].page_number == r.page_number and rows_list[j].row_id not in role \
                and rows_list[j].x0 > 120 and rows_list[j].y0 - prev.y1 < 12:
            role[rows_list[j].row_id] = "signature"
            prev = rows_list[j]
            j += 1

    # ---- enclosures list ----
    for i, r in enumerate(rows_list):
        if r.row_id in role or not ENCLOSURES_RE.match(r.text.strip()) or r.x0 > 150:
            continue
        role[r.row_id] = "enclosures"
        j = i + 1
        while j < len(rows_list) and rows_list[j].page_number == r.page_number and rows_list[j].row_id not in role \
                and ENCLOSURE_ITEM_RE.match(rows_list[j].text.strip()):
            role[rows_list[j].row_id] = "enclosures"
            j += 1

    # ---- captions (+ continuation rows: smaller type / tight spacing, same column) ----
    for i, r in enumerate(rows_list):
        if r.row_id in role or not is_caption_start(r.text) or any(
                (r.report_id, r.page_number) == (a, b) and r.text.strip().startswith(c) for a, b, c in REFERENCE_NOT_CAPTION):
            continue                                    # "Figure 3) was removed …": a wrapped in-text reference (WAYMON_BOYD)
        role[r.row_id] = "caption"
        j, prev = i + 1, r
        while j < len(rows_list):
            n = rows_list[j]
            if n.page_number != r.page_number or n.row_id in role:
                break
            # same type as the caption's first row (native) / not taller (OCR), set tight under it, same column
            same_type = abs(n.size - r.size) <= 0.6 if n.provenance == "native" else n.height <= 1.1 * r.height + 0.5
            tight = n.y0 - prev.y1 < max(4.0, 0.6 * prev.height)
            if not (same_type and tight) or is_caption_start(n.text) or PARA_NUM_RE.match(n.text.strip()):
                break
            role[n.row_id] = "caption"
            prev, j = n, j + 1

    # ---- native text inside an image placement that is not a caption: labels printed on a figure ----
    for r in rows_list:
        if r.row_id not in role and r.in_image:
            role[r.row_id] = "figure_internal"

    # ---- footnotes (native): small type at the bottom of the page, starting with the note number ----
    for p, pg in g.groupby("page_number"):
        cand = pg[(pg["provenance"] == "native") & (pg["size"] <= 10.5) & (pg["y0"] > 480) & ~pg["row_id"].isin(role)]
        started = False
        for r in cand.sort_values("y0").itertuples():
            if re.match(r"^\d{1,3}\s*\S", r.text.strip()) or started:
                role[r.row_id] = "footnote"
                started = True

    for r in rows_list:
        role.setdefault(r.row_id, "body")
    role_records += [{"row_id": k, "role": v} for k, v in role.items()]

roles_df = pd.DataFrame(role_records)
rows_df = rows_df.drop(columns=["role"], errors="ignore").merge(roles_df, on="row_id", how="left")
print(rows_df["role"].value_counts().to_dict())

# %% cell 36
# =========================================================
# 4.2 Document parts (letters, report sections), dates, incident date, vessel label
# =========================================================
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]


def parse_date(t: str) -> str | None:
    """ISO date of a printed date ('27 March 2026', 'March 16, 2026', '26 Jan 2026', '06May13', '03Mar 2026',
    'October 17,2019'); an OCR-damaged month ('Junc') is matched to the closest month name."""
    t = " ".join(t.replace(",", " , ").split())
    m = re.search(r"(\d{1,2})\s*([A-Za-z]{3,9})\.?\s*,?\s*(\d{4}|\d{2})\b", t) or None
    if m:
        d, mon, y = m.group(1), m.group(2), m.group(3)
    else:
        m = re.search(r"([A-Za-z]{3,9})\.?\s+(\d{1,2})\s*,?\s*(\d{4})\b", t)
        if not m:
            return None
        mon, d, y = m.group(1), m.group(2), m.group(3)
    mon = mon.lower()
    cands = [k for k in MONTHS if k.startswith(mon[:3])] or difflib.get_close_matches(mon, MONTHS, n=1, cutoff=0.6)
    if not cands:
        return None
    year = int(y) + (2000 if len(y) == 2 else 0)
    try:
        return pd.Timestamp(year=year, month=MONTHS.index(cands[0]) + 1, day=int(d)).strftime("%Y-%m-%d")
    except ValueError:
        return None


assert parse_date("27 March 2026") == "2026-03-27" and parse_date("October 17,2019") == "2019-10-17"
assert parse_date("06May13") == "2013-05-06" and parse_date("Junc 5, 2025") == "2025-06-05"
assert parse_date("03Mar 2026") == "2026-03-03" and parse_date("18 Dec, 2025") == "2025-12-18"

PARENT_PARTS = {"action_commandant", "endorsement_district", "endorsement_ocmi", "executive_summary", "io_report"}
SUB_PARTS = {"action_on_recommendations", "endorsement_on_recommendations", "comments_on_report"}

part_records, part_of_row = [], {}
for rid, g in rows_df.sort_values(["report_id", "page_number", "y0", "x0"]).groupby("report_id", sort=True):
    has_report_heading = bool(fp_by_report.at[rid, "report_heading"])
    real_io_seen = any(letter_of(t) == "io_report" and t.strip() != "MEMORANDUM"
                       for t in g.loc[g["role"] == "letter_heading", "text"])
    n, part, section, sub = 0, "cover", None, None
    for r in g.itertuples():
        if r.role == "letter_heading":
            k = letter_of(r.text)
            if r.text.strip() == "MEMORANDUM" and real_io_seen:
                k = "convening_memorandum"          # SPIRIT_OF_BOSTON: the order convening the formal investigation
            if k in PARENT_PARTS or k == "convening_memorandum":
                n += 1
                part, section, sub = k, None, None
                part_records.append({"report_id": rid, "part_no": n, "part": k, "heading_row": r.row_id,
                                     "heading": " ".join(r.text.split()), "page_start": r.page_number})
            elif k in SUB_PARTS:
                sub = k
        elif r.role == "front_heading":
            n += 1
            part = "list_of_acronyms" if FRONT_RE["list_of_acronyms"].match(" ".join(r.text.split())) else "front"
            section, sub = None, None
            part_records.append({"report_id": rid, "part_no": n, "part": part, "heading_row": r.row_id,
                                 "heading": " ".join(r.text.split()), "page_start": r.page_number})
        elif r.role == "section_heading":
            if part != "io_report":                        # CUYAHOGA / LITTLE_G: the report starts at section 1
                n += 1
                part = "io_report"
                part_records.append({"report_id": rid, "part_no": n, "part": "io_report", "heading_row": None,
                                     "heading": "(no heading printed)", "page_start": r.page_number})
            section, sub = section_of(r.text)[0], None
        part_of_row[r.row_id] = (n, part, section, sub)

rows_df["part_no"] = rows_df["row_id"].map(lambda i: part_of_row[i][0])
rows_df["part"] = rows_df["row_id"].map(lambda i: part_of_row[i][1])
rows_df["section"] = rows_df["row_id"].map(lambda i: part_of_row[i][2]).astype("Int64")
rows_df["sub_part"] = rows_df["row_id"].map(lambda i: part_of_row[i][3])
parts_df = pd.DataFrame(part_records)

# a letter's date = the file date printed above its heading, on the heading's page
dates = []
for p in parts_df.itertuples():
    same_page = rows_df[(rows_df["report_id"] == p.report_id) & (rows_df["page_number"] == p.page_start)]
    head_y = rows_df.set_index("row_id").at[p.heading_row, "y0"] if isinstance(p.heading_row, str) else 1e9
    fd = same_page[(same_page["role"] == "file_date") & (same_page["y0"] < head_y)]
    raw = fd["text"].iloc[-1].strip() if len(fd) else None
    dates.append((raw, parse_date(raw) if raw else None))
parts_df["date_printed"] = [d[0] for d in dates]
parts_df["date"] = [d[1] for d in dates]
parts_df["page_end"] = parts_df.groupby("report_id")["page_start"].shift(-1).fillna(
    parts_df["report_id"].map(reports_df.set_index("report_id")["pages"])).astype(int)

# ---- version_date = the Commandant's action (the later one when there are two: QUEEN_OF_THE_WEST) ----
cmd = parts_df[parts_df["part"] == "action_commandant"]
VERSION_DATE_OF = cmd.groupby("report_id")["date"].max().to_dict()

# ---- incident date: the date closing the casualty titles ("… ON APRIL 6, 2024"), most frequent across the letters ----
INCIDENT_DATE_RE = re.compile(r"\b(?:ON|OF)\s+([A-Z][A-Za-z]+\.?\s+\d{1,2},?\s*\d{4})", re.IGNORECASE)
incident = {}
for rid, g in rows_df[rows_df["role"].isin(["casualty_title", "cover"])].groupby("report_id"):
    found = []
    for (_, pn), tg in g.groupby(["part_no", "page_number"]):
        txt = " ".join(tg.sort_values("y0")["text"])
        found += [parse_date(m) for m in INCIDENT_DATE_RE.findall(txt)]
    found = [f for f in found if f]
    incident[rid] = Counter(found).most_common(1)[0][0] if found else None
INCIDENT_DATE_OF = incident

# ---- vessel label for chunk headers: the first official name; both vessels for the collision named in the file ----
OFFICIAL_NAME_RE = re.compile(r"^(?:Official Name|Vessel Name|Name)(?:/State Number)?\s*:\s*(.+)$", re.IGNORECASE)
VESSEL_LABEL_OF = {}
for rid, g in rows_df.groupby("report_id"):
    names = [OFFICIAL_NAME_RE.match(t).group(1).strip() for t in g["text"] if OFFICIAL_NAME_RE.match(t)]
    VESSEL_LABEL_OF[rid] = names[0].upper()
VESSEL_LABEL_OF["PROWLER_ATTESSA_IV"] = "PROWLER / ATTESSA IV"      # collision: both vessels are the subject (file name)

meta_df = pd.DataFrame({"report_id": REPORT_IDS})
meta_df["misle"] = meta_df["report_id"].map(MISLE_OF_FILE)
meta_df["vessel_label"] = meta_df["report_id"].map(VESSEL_LABEL_OF)
meta_df["incident_date"] = meta_df["report_id"].map(INCIDENT_DATE_OF)
meta_df["version_date"] = meta_df["report_id"].map(VERSION_DATE_OF)
print("Report metadata:", meta_df.shape, "| missing values:", meta_df.isna().sum()[lambda s: s > 0].to_dict())
print("Parts per kind:", parts_df.groupby("part").size().to_dict())
display(meta_df.head(5))

# %% cell 37
# =========================================================
# 4.3 Tables: vessel / vehicle blocks (Section 2) and persons tables (Section 3)
# =========================================================
# Cells come from the drawn horizontal rules of the table (native: vector drawings; scanned pages: long dark pixel
# runs in the page image), because a label is printed in the vertical middle of a multi-line cell (CUMBERLAND_II
# "Owner:" beside a 4-line address). Without rules (the memorandum), a row without label continues the previous cell.
LABEL_CANON = [
    (r"(Official Name(/State Number)?|Vessel Name|Name)", "name"),
    (r"(Vessel )?Identification Number|Official Number", "identification_number"),
    (r"Hull Identification Number", "hull_identification_number"),
    (r"Flag", "flag"),
    (r"Vessel Class/Type/Sub-?Type|Service", "vessel_class"),
    (r"Build Year", "build_year"),
    (r"Gross Ton(nage|s)( \(GRT\))?", "gross_tonnage"),
    (r"(Registered )?Length", "length"),
    (r"Beam(/Width)?", "beam"),
    (r"Draft(/Depth)?|Depth", "draft_depth"),
    (r"Hull Material|Hull Construction", "hull"),
    (r"Main[/ ]Primary Propulsion.*|Propulsion", "propulsion"),
    (r"Maximum Passengers and Crewpersons", "max_persons"),
    (r"Owner ?/ ?Operator", "owner_operator"),
    (r"Owner(/Managing Owner)?", "owner"),
    (r"Operator", "operator"),
    (r"Make", "vehicle_make"), (r"Model", "vehicle_model"), (r"Year", "vehicle_year"), (r"Color", "vehicle_color"),
    (r"License Plate", "vehicle_license_plate"), (r"State and County of Registration", "vehicle_registration"),
]
LABEL_CANON_RE = [(re.compile(rf"^(?:{p})\s*:?$", re.IGNORECASE), f) for p, f in LABEL_CANON]
LABEL_HEAD_RE = re.compile(r"^(?P<label>[A-Za-z][A-Za-z/()\-, ]{1,45}?)\s*:\s*(?P<rest>.*)$")


def canon_label(label: str) -> str | None:
    lab = re.sub(r"\s*\(.*$", "", " ".join(label.split())).strip(" :")       # "Main/Primary Propulsion (Configuration…"
    return next((f for rx, f in LABEL_CANON_RE if rx.match(lab)), None)


def has_label(first_seg: tuple, split: float) -> bool:
    """True when the row's first segment is a known label left of the value column."""
    x, _, t = first_seg
    m = LABEL_HEAD_RE.match(t)
    return bool(x < split and ((m and canon_label(m["label"])) or canon_label(t)))


def horizontal_rules(rid: str, p: int, x0: float, x1: float) -> list[float]:
    """y positions (pt) of horizontal lines spanning >= 50 % of [x0, x1] on page p."""
    ys = []
    if pages_df.set_index(["report_id", "page_number"]).at[(rid, p), "text_source"] == "native":
        for d in docs[rid][p - 1].get_drawings():
            for it in d["items"]:
                if it[0] == "re":
                    r = it[1]
                    if r.height <= 2.5 and r.width >= 0.5 * (x1 - x0) and r.x0 < x1 and r.x1 > x0:
                        ys.append((r.y0 + r.y1) / 2)
                elif it[0] == "l" and abs(it[1].y - it[2].y) < 1.0 and abs(it[2].x - it[1].x) >= 0.5 * (x1 - x0):
                    ys.append(it[1].y)
    else:
        s = GRAPHIC_DPI / 72
        pix = docs[rid][p - 1].get_pixmap(dpi=GRAPHIC_DPI, colorspace=pymupdf.csGRAY)
        grey = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
        band = grey[:, max(0, int(x0 * s)):int(x1 * s)] < 140
        dark = band.sum(axis=1) >= 0.5 * band.shape[1]
        ys = [i / s for i in np.flatnonzero(dark)]
    merged = []
    for y in sorted(ys):
        if not merged or y - merged[-1][-1] > 2.0:
            merged.append([y])
        else:
            merged[-1].append(y)
    return [round(float(np.mean(m)), 1) for m in merged]


def table_rows_of(sec_rows: pd.DataFrame, split: float) -> pd.DataFrame:
    """The key–value rows of a Section 2 part: rows with a label, value-only rows and label continuations."""
    keep, started = [], False
    for r in sec_rows.itertuples():
        first_x, _, first_t = r.segments[0]
        labelled = first_x < split and (LABEL_HEAD_RE.match(first_t) and canon_label(LABEL_HEAD_RE.match(first_t)["label"])
                                        or canon_label(first_t))
        value_only = first_x >= split - 25
        continuation = started and len(r.segments) >= 1 and first_x < split and not labelled \
            and (len(r.segments) > 1 or len(first_t) < 60) and not PARA_NUM_RE.match(first_t)
        if r.role == "body" and (labelled or (started and (value_only or continuation))):
            keep.append(r.row_id)
            started = True
        elif started and r.role not in ("page_number", "running_header", "caption", "figure_internal"):
            started = False
    return sec_rows[sec_rows["row_id"].isin(keep)]


vessel_field_records = []
for rid, g in rows_df[(rows_df["section"] == 2)].groupby("report_id", sort=True):
    g = g.sort_values(["page_number", "y0", "x0"])
    two = [seg for segs in g.loc[g["role"] == "body", "segments"] for seg in segs[1:2]]
    split = float(np.median([s[0] for s in two])) - 10 if two else 250.0
    trows = table_rows_of(g, split)
    cells = []                                          # list of lists of row_ids
    for p, pg in trows.groupby("page_number", sort=True):
        x0, x1 = float(pg["x0"].min()), float(pg["x1"].max())
        rules = horizontal_rules(rid, int(p), x0, max(x1, x0 + 200))
        rules = [y for y in rules if pg["y0"].min() - 20 <= y <= pg["y1"].max() + 20]
        if len(rules) >= 3:     # a rule the page image lost at the top / bottom (H20_BELOW, MERRICK): close the table
            rules = sorted({pg["y0"].min() - 1, *rules, pg["y1"].max() + 1})
        if len(rules) >= 3:
            for a, b in zip(rules, rules[1:]):
                members = pg[((pg["y0"] + pg["y1"]) / 2 > a) & ((pg["y0"] + pg["y1"]) / 2 < b)]
                labelled = [r for r in members.itertuples() if has_label(r.segments[0], split)]
                if len(labelled) >= 2:
                    # a rule the page image lost (OCR'd pages: H20_BELOW Beam/Draft, QUEEN_OF_THE_WEST Gross Tons/Hull):
                    # one sub-cell per labelled row, an unlabelled row joins the nearest one
                    ymid = lambda r: (r.y0 + r.y1) / 2
                    sub = {r.row_id: [] for r in labelled}
                    for r in members.itertuples():
                        sub[min(labelled, key=lambda l: abs(ymid(l) - ymid(r))).row_id].append(r.row_id)
                    cells.extend(sub.values())
                elif len(members):
                    cells.append(members["row_id"].tolist())
        else:
            for r in pg.itertuples():
                if has_label(r.segments[0], split) or not cells:
                    cells.append([r.row_id])
                else:
                    cells[-1].append(r.row_id)
    R = rows_df.set_index("row_id")
    vessel_no, block = 0, "vessel"
    for cell in cells:
        segs = [s for rid_ in cell for s in R.at[rid_, "segments"]]
        label_parts = [t for x, _, t in segs if x < split]
        value_parts = [t for x, _, t in segs if x >= split]
        label = " ".join(label_parts)
        m = LABEL_HEAD_RE.match(label)
        if m and m["rest"] and not value_parts and not m["rest"].startswith("("):   # "Official Name/State Number: LA6893ER"
            label, value_parts = m["label"], [m["rest"]]
        value = " ".join(" ".join(value_parts).split())
        if not label.strip() and vessel_field_records and vessel_field_records[-1]["report_id"] == rid:
            prev = vessel_field_records[-1]                                     # a value-only cell continues the previous one
            prev["value"] = f"{prev['value']} {value}".strip()
            prev["row_ids"] = prev["row_ids"] + cell
            continue
        field = canon_label(label)
        if field == "name":
            vessel_no, block = vessel_no + 1, "vessel"
        if field and field.startswith("vehicle_") and block != "vehicle":
            block, vessel_no = "vehicle", vessel_no + 1
        vessel_field_records.append({
            "report_id": rid, "block_no": max(vessel_no, 1), "block_kind": block,
            "label_printed": " ".join(label.split()).strip(" :"), "field": field, "value": value,
            "page_number": int(R.at[cell[0], "page_number"]), "row_ids": cell})

vessel_fields_df = pd.DataFrame(vessel_field_records)
assert set(r for ids in vessel_fields_df["row_ids"] for r in ids) == set(
    pd.concat([table_rows_of(g.sort_values(["page_number", "y0", "x0"]),
                             float(np.median([s[0] for segs in g.loc[g["role"] == "body", "segments"] for s in segs[1:2]])) - 10)
               for _, g in rows_df[rows_df["section"] == 2].groupby("report_id")])["row_id"]), "a table row fell outside every cell"

# ---- persons tables (Section 3): columns from the header row; a row is a new person when it has a value in the
#      relationship / position column AND in another column, otherwise it continues the previous person's cells ----
PERSONS_SUBHEADER_RE = re.compile(r"^(Deceased|Survivor)\s+Age\s+Position")      # the memorandum's two tables
person_records, persons_statement = [], {}
for rid, g in rows_df[(rows_df["section"] == 3) & (rows_df["role"] == "body")].groupby("report_id", sort=True):
    g = g.sort_values(["page_number", "y0", "x0"])
    cols, table_no, key_col, current = None, 0, None, None
    for r in g.itertuples():
        t = r.text.strip()
        if PERSONS_HEADER_RE.match(t) or PERSONS_SUBHEADER_RE.match(t):
            table_no += 1
            cols = [(a, b, " ".join(h.split())) for a, b, h in r.segments]
            key_col = next((i for i, (_, _, h) in enumerate(cols) if re.match(r"(Relationship|Position)", h, re.I)), 0)
            header_kind = PERSONS_SUBHEADER_RE.match(t).group(1).lower() if PERSONS_SUBHEADER_RE.match(t) else None
            current = None
            continue
        if cols is None:
            persons_statement.setdefault(rid, []).append(t)             # 'None', 'There were no deceased …'
            continue
        cells = {}
        for a, b, txt in r.segments:
            centre = (a + b) / 2
            k = min(range(len(cols)), key=lambda i: 0 if cols[i][0] - 5 <= centre <= cols[i][1] + 5
                    else min(abs(centre - cols[i][0]), abs(centre - cols[i][1])))
            cells[k] = f"{cells.get(k, '')} {txt}".strip()
        if key_col in cells and len(cells) >= 2:
            current = {"report_id": rid, "table_no": table_no, "table_kind": header_kind,
                       "cells": {cols[i][2]: v for i, v in cells.items()}, "row_ids": [r.row_id],
                       "page_number": r.page_number}
            person_records.append(current)
        elif current is not None:
            for i, v in cells.items():
                current["cells"][cols[i][2]] = f"{current['cells'].get(cols[i][2], '')} {v}".strip()
            current["row_ids"].append(r.row_id)
        else:
            persons_statement.setdefault(rid, []).append(t)


def cell_of(cells: dict, pattern: str) -> str | None:
    return next((v for k, v in cells.items() if re.match(pattern, k, re.I)), None)


persons_df = pd.DataFrame([{
    "report_id": p["report_id"], "table_no": p["table_no"], "table_kind": p["table_kind"],
    "relationship": cell_of(p["cells"], r"(Relationship|Position)"),
    "sex": cell_of(p["cells"], r"Sex"), "age": cell_of(p["cells"], r"Age"),
    "status": cell_of(p["cells"], r"Status") or ({"deceased": "Deceased", "survivor": "Survivor"}.get(p["table_kind"])),
    "page_number": p["page_number"], "row_ids": p["row_ids"], "n_cells": len(p["cells"]),
} for p in person_records])
# a table whose only row is 'None N/A …' (CUYAHOGA) records no person
none_rows = persons_df["relationship"].fillna("").str.match(r"^(None|N/A)$") & persons_df["status"].fillna("N/A").eq("N/A")
persons_statement.update({r.report_id: persons_statement.get(r.report_id, []) + ["table printed with 'None'"]
                          for r in persons_df[none_rows].itertuples()})
persons_none_rows = persons_df[none_rows]
persons_df = persons_df[~none_rows].reset_index(drop=True)
print("Persons:", len(persons_df), "in", persons_df["report_id"].nunique(), "reports | reports without persons:",
      sorted(set(REPORT_IDS) - set(persons_df["report_id"])))
display(persons_df[["report_id", "table_no", "relationship", "sex", "age", "status"]].head(5))
print("Vessel / vehicle fields:", len(vessel_fields_df), "| unknown labels:",
      vessel_fields_df.loc[vessel_fields_df["field"].isna(), ["report_id", "label_printed", "value"]].values.tolist()[:10])
print("Blocks per kind:", vessel_fields_df.drop_duplicates(["report_id", "block_no"])["block_kind"].value_counts().to_dict(),
      "| reports:", vessel_fields_df["report_id"].nunique())
display(vessel_fields_df[["report_id", "block_no", "block_kind", "field", "value"]].head(5))

# %% [markdown] cell 38
# ### 4.4–4.7 Persons, figures, enclosures, table of contents, validation
#
# - **Persons (4.4):** the printed relationship/position is the role label (plan §4.6: roles, never names); class
#   `crew` / `passenger` / `other` and outcome `dead_or_missing` / `injured` / `uninjured`, plus `survivor_unspecified`
#   for the memorandum's survivor table (it does not say whether a survivor was injured, so nothing is guessed).
# - **Figures (4.5):** one unit per caption; the image region is recorded so its internal text never leaks into the
#   body. Value gate (ADR-020): all figures are raster images with no text-readable data → `caption_only`.
#   Wrapped in-text references ("Figure 3) was removed …", "Table 2.01-7(a)(4) …") are not captions.
# - **Enclosures and TOC (4.6):** metadata only; they cross-check that the parser found every announced part and section.
# - **Validation (4.7):** structural asserts + a reviewed snapshot of every count.

# %% cell 39
# =========================================================
# 4.4 Persons: role label, class and outcome (plan §4.6: roles, never names)
# =========================================================
# The printed "Relationship to Vessel" / "Position" is the person's role label; the Name column is never kept.
# class: passenger / crew / other (an owner who did not operate the vessel, an industrial worker carried on board);
# outcome from the printed status. "Survivor" (the memorandum's survivor table) does not say whether the person was
# injured, so it gets its own outcome instead of a guessed "uninjured".
PASSENGER_RE = re.compile(r"passenger", re.I)
OTHER_ROLE_RE = re.compile(r"^(Owner|Worker\b.*Industrial)", re.I)          # "Owner" alone; "Owner/Operator" operates
OUTCOME_RULES = [(r"deceased|dead|missing", "dead_or_missing"), (r"^injured", "injured"),
                 (r"^uninjured", "uninjured"), (r"^survivor$", "survivor_unspecified")]


def person_class(rel: str) -> str:
    if PASSENGER_RE.search(rel):
        return "passenger"
    if OTHER_ROLE_RE.match(rel) and not re.search(r"operator", rel, re.I):
        return "other"
    return "crew"


def person_outcome(status: str) -> str | None:
    return next((o for p, o in OUTCOME_RULES if re.search(p, status.strip(), re.I)), None)


persons_df["role_label"] = persons_df["relationship"].map(lambda t: " ".join(t.split()).split(" – ")[0])
persons_df["person_class"] = persons_df["relationship"].map(person_class)
persons_df["outcome"] = persons_df["status"].map(person_outcome)
# SPIRIT_OF_BOSTON prints no persons section (its sections run 1, 2, 4… with the Findings in two parts, 3b)
persons_statement.setdefault("SPIRIT_OF_BOSTON", ["no persons section printed"])
print("Persons:", len(persons_df), "| class:", persons_df["person_class"].value_counts().to_dict(),
      "| outcome:", persons_df["outcome"].value_counts(dropna=False).to_dict())
print("Reports with a persons statement instead of a table:", sorted(persons_statement))
display(persons_df[["report_id", "role_label", "person_class", "outcome"]].head(5))

# %% cell 40
# =========================================================
# 4.5 Figures and tables: caption units, image region, value gate (ADR-020)
# =========================================================
# A caption unit = its start row ("Figure N …", "Table N …", "Above: Photograph …") + the continuation rows Phase 4.1
# gave the role `caption` (credits, second line). Two captions can share a baseline (WAYMON_BOYD p.17): a
# continuation row joins the start row of its own column. The image region is the nearest graphic region of the page.
FIG_NO_RE = re.compile(r"^(?P<kind>Fig(?:ure|\.)?|Table)\s*(?P<no>\d+|[lI](?=\s*[.:\-–—]))", re.I)
DIAGRAM_RE = re.compile(r"\b(chart(let)?|diagram|graph|map|track(line)?|AIS|plot|timeline|schematic|drawing|layout|"
                        r"sketch|arrangement|illustration|rendering|ECDIS|radar|plan view|profile view|screenshot|"
                        r"screen ?shot|data|weather|forecast|buoy)\b", re.I)

cap = rows_df[rows_df["role"] == "caption"].sort_values(["report_id", "page_number", "y0", "x0"])
figure_records = []
for (rid, p), g in cap.groupby(["report_id", "page_number"], sort=True):
    open_ = []                                                     # figure records started on this page
    for r in g.itertuples():
        t = " ".join(r.text.split())
        if is_caption_start(t):
            m = FIG_NO_RE.match(t)
            rec = {"report_id": rid, "page_number": int(p), "kind": "table" if m and m["kind"].lower() == "table" else "figure",
                   "number": int(m["no"].replace("l", "1").replace("I", "1")) if m else None, "caption": t, "row_ids": [r.row_id],
                   "x0": r.x0, "x1": r.x1, "y0": r.y0, "y1": r.y1}
            figure_records.append(rec); open_.append(rec)
        elif open_:
            rec = max(open_, key=lambda f: min(f["x1"], r.x1) - max(f["x0"], r.x0))     # same column
            rec["caption"] += " " + t; rec["row_ids"].append(r.row_id); rec["y1"] = max(rec["y1"], r.y1)
figures_df = pd.DataFrame(figure_records)
figures_df["figure_id"] = [f"{r.report_id}:fig{i:02d}" for i, r in
                           zip(figures_df.groupby("report_id").cumcount() + 1, figures_df.itertuples())]

graphic_regions = graphics_df[graphics_df["kind"].isin(["graphic", "table"])]
by_page = {k: g for k, g in graphic_regions.groupby(["report_id", "page_number"])}


TEXT_SOURCE_OF = pages_df.set_index(["report_id", "page_number"])["text_source"].to_dict()


def region_of(f) -> tuple | None:
    """Native page: the nearest image placement; OCR'd page: the nearest graphic region of Phase 1b."""
    if TEXT_SOURCE_OF[(f.report_id, f.page_number)] == "native":
        boxes = [tuple(i["bbox"]) for i in docs[f.report_id][f.page_number - 1].get_image_info()
                 if (i["bbox"][2] - i["bbox"][0]) * (i["bbox"][3] - i["bbox"][1]) > 2000]     # not a logo speck
    else:
        g = by_page.get((f.report_id, f.page_number))
        boxes = [] if g is None else list(g["bbox"])
    if not boxes:
        return None
    gap = lambda b: max(f.y0 - b[3], b[1] - f.y1, 0)               # vertical distance caption ↔ region
    return tuple(round(float(v), 1) for v in min(boxes, key=gap))


figures_df["region"] = [region_of(f) for f in figures_df.itertuples()]
figures_df["figure_class"] = np.where(figures_df["kind"] == "table", "table",
                                      np.where(figures_df["caption"].map(lambda c: bool(DIAGRAM_RE.search(c))),
                                               "diagram_or_chart", "photo"))
# Value gate (ADR-020). Every figure here is a raster image: no plotted value can be read as text, and the text
# printed inside it is excluded as `figure_internal` (4.1). The caption carries the figure's claim and the numbered
# findings carry the event, so every unit is `caption_only`; the class only records what the caption says it shows.
figures_df["gate"] = "caption_only"
figures_df["gate_reason"] = figures_df["figure_class"].map({
    "photo": "photograph: caption only (ADR-020)",
    "diagram_or_chart": "raster diagram/chart/map: no text-readable data; caption kept, internal text excluded",
    "table": "table image: caption kept, cell text excluded as figure_internal"})
# printed numbering: a number used twice in one report (SPIRIT_OF_BOSTON 2; WAYMON_BOYD: 4, and a second series 6–13)
# is kept as printed; `figure_id` is the unique key
num = figures_df[figures_df["number"].notna()]
FIGURE_NUMBER_REPEATS = {(r, int(n)) for r, n in num.loc[num.duplicated(["report_id", "kind", "number"]),
                                                         ["report_id", "number"]].itertuples(index=False)}
print("Caption units:", len(figures_df), "| class:", figures_df["figure_class"].value_counts().to_dict(),
      "| without region:", int(figures_df["region"].isna().sum()), "| caption rows used:",
      sum(map(len, figures_df["row_ids"])), "of", len(cap))
print("Printed figure numbers used twice:", sorted(FIGURE_NUMBER_REPEATS))
display(figures_df[["figure_id", "page_number", "figure_class", "caption"]].head(5))

# %% cell 41
# =========================================================
# 4.6 "Enclosures" lists and the table of contents, cross-checked against the parts and sections found
# =========================================================
# The enclosures list of a letter names the parts that follow it; the TOC names the sections and sub-sections of the
# report. Both are metadata (never chunked); here they only check that the parser found what the report announces.
ENCLOSURE_PART_RULES = [(r"executive summary", "executive_summary"), (r"investigating officer|report of investigation|"
                         r"formal investigation report", "io_report"), (r"district|commander", "endorsement_district"),
                        (r"officer in charge|ocmi|captain of the port|sector", "endorsement_ocmi")]
enclosure_records = []
for rid, g in rows_df[rows_df["role"] == "enclosures"].sort_values(["page_number", "y0"]).groupby("report_id"):
    lists = []                                          # one list per letter: a header row starts a new one
    for t in g["text"]:
        t = " ".join(t.split())
        if ENCLOSURES_RE.match(t):
            n = re.match(r"^Encl\w*\s*\((\d+)\)", t, re.I)                  # "Encl (1): Report of …" (CUMBERLAND_II)
            lists.append((f"({n[1]}) " if n else "") + ENCLOSURES_RE.sub("", t, count=1).strip())
        else:
            lists[-1] += " " + t
    for list_no, text in enumerate(lists, start=1):
        for n, item in re.findall(r"\((\d+)\)\s*(.*?)(?=\s*\(\d+\)\s|$)", text):
            part = next((pt for pat, pt in ENCLOSURE_PART_RULES if re.search(pat, item, re.I)), None)
            enclosure_records.append({"report_id": rid, "list_no": list_no, "enclosure_no": int(n), "title": item.strip(),
                                      "part": part,
                                      "part_found": part in set(parts_df.loc[parts_df["report_id"] == rid, "part"])})
enclosures_df = pd.DataFrame(enclosure_records)

TOC_ENTRY_RE = re.compile(r"^(?P<no>\d+(?:\.\d+)*)\.?\s+(?P<title>.+?)\s*(?:\.{3,}\s*)?(?P<page>[ivx\d]+)?$", re.I)
toc_records = []
for rid, g in rows_df[rows_df["role"] == "toc"].sort_values(["page_number", "y0"]).groupby("report_id"):
    for t in g["text"]:
        t = " ".join(t.split())
        m = TOC_ENTRY_RE.match(t)
        if m:
            toc_records.append({"report_id": rid, "no": m["no"], "title": re.sub(r"\s*\.{3,}.*$", "", m["title"])})
        elif toc_records and toc_records[-1]["report_id"] == rid and not re.match(r"^Table of Contents$", t, re.I):
            toc_records[-1]["title"] += " " + re.sub(r"\s*\.{3,}.*$", "", t)      # a title wrapped onto the next row
toc_df = pd.DataFrame(toc_records)


def heading_found(r) -> bool:
    """Top level: a section heading with that number; deeper: a row of the report that starts with that number."""
    g = rows_df[rows_df["report_id"] == r.report_id]
    if "." not in r.no:     # a slip (3b) counts under its printed number too: SPIRIT_OF_BOSTON prints its section 4
        found = {int(k) for k in g["section"].dropna().unique()}           # (Findings) in two parts, "3." and "4."
        return r.no in {str(k) for k in found} | {NUMBERING_SLIPS[(r.report_id, k)] for k in found
                                                   if (r.report_id, k) in NUMBERING_SLIPS}
    return bool(g["text"].map(lambda t: bool(re.match(rf"^{re.escape(r.no)}\.?\s", t.strip()))).any())


toc_df["found"] = [heading_found(r) for r in toc_df.itertuples()]
# reviewed: VICAR_602's letters list an Executive Summary that the public release does not contain (no row of the
# report carries it outside the two lists) — recorded, nothing to parse
ENCLOSURES_NOT_IN_RELEASE = {("VICAR_602", "executive_summary")}
enclosures_df["not_in_release"] = [(r.report_id, r.part) in ENCLOSURES_NOT_IN_RELEASE for r in enclosures_df.itertuples()]
print("Enclosure items:", len(enclosures_df), "in", enclosures_df["report_id"].nunique(), "reports | part found:",
      int(enclosures_df["part_found"].sum()), "| listed, not in the release:", int(enclosures_df["not_in_release"].sum()),
      "| unexplained:", enclosures_df.loc[~enclosures_df["part_found"] & ~enclosures_df["not_in_release"],
                                           ["report_id", "enclosure_no", "title"]].values.tolist()[:8])
print("TOC entries:", len(toc_df), "in", toc_df["report_id"].nunique(), "reports | not found:",
      toc_df.loc[~toc_df["found"], ["report_id", "no", "title"]].values.tolist()[:8])

# %% cell 42
# =========================================================
# 4.7 Phase 4 validation
# =========================================================
assert rows_df["role"].notna().all(), "Every row has a role."
assert "name" not in " ".join(persons_df.columns).lower(), "The persons units never keep a Name column (plan §4.6)."
assert meta_df[["misle", "vessel_label", "incident_date", "version_date"]].notna().all().all(), meta_df.isna().sum().to_dict()
# vessels: every report has a named block, every printed label is mapped
assert vessel_fields_df["field"].notna().all(), vessel_fields_df[vessel_fields_df["field"].isna()].head()
assert set(vessel_fields_df.loc[vessel_fields_df["field"] == "name", "report_id"]) == set(REPORT_IDS)
# persons: every report has persons rows or a printed statement, each person has a role, a class and an outcome
assert set(persons_df["report_id"]) | set(persons_statement) == set(REPORT_IDS)
assert persons_df[["role_label", "person_class", "outcome"]].notna().all().all()
# figures: every caption row is in exactly one unit, every unit passed the gate
assert sorted(r for ids in figures_df["row_ids"] for r in ids) == sorted(rows_df.loc[rows_df["role"] == "caption", "row_id"])
assert figures_df["figure_id"].is_unique and figures_df["gate"].notna().all()
# enclosures and TOC agree with what the parser found
assert (enclosures_df["part_found"] | enclosures_df["not_in_release"]).all()
assert toc_df["found"].all(), toc_df[~toc_df["found"]]
# ---- reviewed snapshot (2026-09-26) ----
REVIEWED_PHASE4 = {
    "roles": {"body": 14054, "letterhead": 627, "page_number": 503, "caption": 368, "casualty_title": 262,
        "figure_internal": 230, "signature": 212, "section_heading": 182, "letter_heading": 177, "cover": 169,
        "file_block": 157, "footnote": 146, "file_date": 128, "toc": 100, "running_header": 56, "enclosures": 45,
        "memo_header": 18, "no_text": 14, "letter_heading_cont": 12, "enclosure_footer": 9, "front_heading": 1,
        "ocr_noise": 1},
    "parts": {"io_report": 25, "action_commandant": 24, "endorsement_district": 23, "executive_summary": 22,
        "endorsement_ocmi": 20, "list_of_acronyms": 1, "convening_memorandum": 1},
    "vessel_fields": 297,
    "blocks": {"vessel": 26, "vehicle": 1},
    "persons": 41,
    "person_class": {"crew": 34, "passenger": 5, "other": 2},
    "outcome": {"dead_or_missing": 26, "injured": 8, "survivor_unspecified": 5, "uninjured": 2},
    "figure_class": {"photo": 167, "diagram_or_chart": 35, "table": 2},
    "figures_without_region": [],
    "enclosures": 44,
    "toc": 82}
actual = {"roles": rows_df["role"].value_counts().to_dict(), "parts": parts_df["part"].value_counts().to_dict(),
          "vessel_fields": len(vessel_fields_df),
          "blocks": vessel_fields_df.drop_duplicates(["report_id", "block_no"])["block_kind"].value_counts().to_dict(),
          "persons": len(persons_df), "person_class": persons_df["person_class"].value_counts().to_dict(),
          "outcome": persons_df["outcome"].value_counts().to_dict(),
          "figure_class": figures_df["figure_class"].value_counts().to_dict(),
          "figures_without_region": sorted(figures_df.loc[figures_df["region"].isna(), "figure_id"]),
          "enclosures": len(enclosures_df), "toc": len(toc_df)}
# reviewed: parts printed twice are genuine — CONCHRD's report title page (p.9) + body (p.11), H20_BELOW's two district
# endorsements (Heartland, Eighth), QUEEN_OF_THE_WEST's two Commandant actions and its memorandum + report body
dup_parts = parts_df.groupby(["report_id", "part"]).size()
assert set(dup_parts[dup_parts > 1].index) == {("CONCHRD", "io_report"), ("H20_BELOW", "endorsement_district"),
                                               ("QUEEN_OF_THE_WEST", "action_commandant"),
                                               ("QUEEN_OF_THE_WEST", "io_report")}, dup_parts[dup_parts > 1]
assert FIGURE_NUMBER_REPEATS == {("SPIRIT_OF_BOSTON", 2), *(("WAYMON_BOYD", n) for n in (4, 6, 7, 10, 11, 12, 13))}
assert actual == REVIEWED_PHASE4,{k: v for k, v in actual.items() if v != REVIEWED_PHASE4[k]}
print("✅ Phase 4 validation passed.")
print("Phase 4:", len(meta_df), "reports |", len(parts_df), "parts |", actual["vessel_fields"], "vessel/vehicle fields |",
      actual["persons"], "persons |", len(figures_df), "caption units |", actual["enclosures"], "enclosure items |",
      actual["toc"], "TOC entries")

# %% [markdown] cell 43
# # Phase 5 — Notes / footnotes and superscripts
#
# Policy as in the IMO / LPI notebooks: a **note registry** per report (`note_no → text`), every inline marker resolved
# to its note, one reviewed **policy** per note — `informative` (appended to the paragraph that cites it as
# `Note: …` in Phase 9), `citation_only` (an evidence reference — exhibit, transcript, website — kept as metadata of
# the citing unit, never indexed as prose) or `redacted` (the note prints only "Redacted": nothing to keep).
#
# Phase 2 split every **superscript** span off the native text (as in the IMO notebook). Not every superscript is a note
# marker, so each one gets a disposition (5.1):
#
# | Superscript | Example | Disposition |
# |---|---|---|
# | note number in a report that prints notes | SPIRIT_OF_BOSTON "…wait station.¹" | `note_ref` (5.3) |
# | ordinal suffix | MICHIPICOTEN "the 1ˢᵗ Officer", "E 9ᵗʰ St." | `restored` into the text (reviewed position) |
# | exponent | CONCHRD "40 in²" | `restored` |
# | trademark sign | SPIRIT_OF_BOSTON "Sterno®" | `restored` after the only brand word of the row |
#
# Without the restore the text would read "the 1 Officer" or "(SternoDon and …" — wrong facts or broken words.
#
# Sources of notes (5.2): the native footnote zone (small type at the page bottom, Phase 4 role `footnote`) of
# SPIRIT_OF_BOSTON, WAYMON_BOYD, WILDERNESS_I and MICHIPICOTEN, and the **OCR footnotes** of H20_BELOW (a scan has no
# font size: a note is a row in the bottom zone that starts left of the page's text column with its number). The
# SPIRIT_OF_BOSTON **List of Figures / List of Tables** (last pages, small type) was taken for footnotes by the
# Phase 4 zone rule; it is a list of captions and becomes metadata (`figure_list`), cross-checked against the captions.

# %% cell 44
# =========================================================
# 5.1 Superscripts: note markers, restored ordinals / exponents / trademark signs
# =========================================================
NOTE_REPORTS = ["SPIRIT_OF_BOSTON", "WAYMON_BOYD", "WILDERNESS_I", "MICHIPICOTEN", "H20_BELOW"]
ORDINAL_RE = re.compile(r"^(st|nd|rd|th)$")
# reviewed positions (report, page, printed text without the superscript, restored text); each must match one row
SUPERSCRIPT_RESTORES = [
    ("GENERAL_MACARTHUR", 8, "725(5 Dir.", "725(5th Dir."),          # case citation, kept as printed ("Dir.")
    ("GENERAL_MACARTHUR", 9, "June 19, 2023", "June 19th, 2023"),
    ("GENERAL_MACARTHUR", 10, "June 19, 2023", "June 19th, 2023"),
    ("GENERAL_MACARTHUR", 11, "June 19, 2023", "June 19th, 2023"),
    ("LITTLE_G", 6, "1500 15 Street", "1500 15th Street"),
    ("MICHIPICOTEN", 4, "E 9 St.", "E 9th St."),
    ("MICHIPICOTEN", 10, "the 1 officer", "the 1st officer"),
    ("MICHIPICOTEN", 11, "The 1 Officer", "The 1st Officer"),
    ("MICHIPICOTEN", 11, "the 2 Officer", "the 2nd Officer"),
    ("MICHIPICOTEN", 15, "The 1 Officer", "The 1st Officer"),
    ("UNA_MAS", 3, "915 2 Avenue", "915 2nd Avenue"),
    ("CONCHRD", 29, "= 40 in", "= 40 in²"),
    ("CONCHRD", 29, "= 200 in", "= 200 in²"),
    ("CONCHRD", 29, "= 400 in", "= 400 in²"),
    ("CONCHRD", 29, "inof drainage", "in² of drainage"),
    ("SPIRIT_OF_BOSTON", 38, "(SternoDon and", "(Sterno®, Don® and"),  # the only row with two signs
]
BRAND_RE = re.compile(r"\bsterno\b", re.I)          # every other "®" follows the only "Sterno" of its row


def restore_in(frame: pd.DataFrame, idx, old: str, new: str) -> None:
    t = frame.at[idx, "text"]
    assert t.count(old) == 1, (frame.at[idx, frame.columns[0]], old, t)
    frame.at[idx, "text"] = t.replace(old, new)


superscript_records = []
line_of = lines_df.set_index("line_key")
for r in lines_df[lines_df["markers"].map(len) > 0].itertuples():
    for mk in r.markers:
        kind = ("ordinal" if ORDINAL_RE.match(mk) else "trademark" if "®" in mk
                else "note_ref" if mk.isdigit() and r.report_id in NOTE_REPORTS else "exponent" if mk.isdigit() else "unknown")
        superscript_records.append({"line_key": r.line_key, "row_id": r.row_id, "report_id": r.report_id,
                                    "page_number": r.page_number, "marker": mk, "kind": kind})
superscripts_df = pd.DataFrame(superscript_records)
assert not (superscripts_df["kind"] == "unknown").any(), superscripts_df[superscripts_df["kind"] == "unknown"]

# restore the reviewed positions in both the row and its line (the coverage audit reads the lines, Phase 19)
row_ix = pd.Series(rows_df.index, index=rows_df["row_id"])
line_ix = pd.Series(lines_df.index, index=lines_df["line_key"])
restored_lines = set()
for rid, p, old, new in SUPERSCRIPT_RESTORES:
    hit = superscripts_df[(superscripts_df["report_id"] == rid) & (superscripts_df["page_number"] == p)
                          & (superscripts_df["kind"] != "note_ref")]
    hit = hit[hit["line_key"].map(lambda k: old in lines_df.at[line_ix[k], "text"]) & ~hit["line_key"].isin(restored_lines)]
    keys = hit["line_key"].unique()
    assert len(keys) == 1, (rid, p, old, keys)
    restore_in(lines_df, line_ix[keys[0]], old, new)
    restore_in(rows_df, row_ix[hit["row_id"].iloc[0]], old, new)
    restored_lines.add(keys[0])
    for fi in figures_df.index[figures_df["row_ids"].map(lambda ids: hit["row_id"].iloc[0] in ids)]:
        assert figures_df.at[fi, "caption"].count(old) == 1           # the caption unit carries the same text
        figures_df.at[fi, "caption"] = figures_df.at[fi, "caption"].replace(old, new)
for k, g in superscripts_df[(superscripts_df["kind"] == "trademark") & ~superscripts_df["line_key"].isin(restored_lines)
                            ].groupby("line_key"):
    li = line_ix[k]; t = lines_df.at[li, "text"]
    assert len(g) == 1 and len(BRAND_RE.findall(t)) == 1, (k, t)
    m = BRAND_RE.search(t); new = t[:m.end()] + "®" + t[m.end():]
    ri = row_ix[g["row_id"].iloc[0]]
    restore_in(rows_df, ri, t, new)
    lines_df.at[li, "text"] = new
    restored_lines.add(k)
superscripts_df["disposition"] = np.where(superscripts_df["kind"] == "note_ref", "note_ref",
                                          np.where(superscripts_df["line_key"].isin(restored_lines), "restored", None))
assert superscripts_df["disposition"].notna().all(), superscripts_df[superscripts_df["disposition"].isna()]
print("Superscripts:", len(superscripts_df), superscripts_df["kind"].value_counts().to_dict(),
      "| restored lines:", len(restored_lines))
display(superscripts_df[superscripts_df["kind"] != "note_ref"][["report_id", "page_number", "marker", "kind"]].head(5))

# %% cell 45
# =========================================================
# 5.2 Note registry: native footnote zone + OCR footnotes; List of Figures / Tables -> metadata
# =========================================================
# (a) SPIRIT_OF_BOSTON's List of Figures / List of Tables (last pages): metadata, cross-checked against the captions
LIST_HEAD_RE = re.compile(r"^List of (Figures|Tables)$")
FIGURE_LIST_ENTRY_RE = re.compile(r"^(?P<no>\d{1,2})\s+(?P<caption>\S.*?)\s+(?P<page>\d{1,3})$")
heads = rows_df[rows_df["text"].str.strip().map(lambda t: bool(LIST_HEAD_RE.match(t)))]
assert heads["report_id"].unique().tolist() == ["SPIRIT_OF_BOSTON"], heads
first = heads.sort_values(["page_number", "y0"]).iloc[0]
in_list = ((rows_df["report_id"] == first.report_id) & (rows_df["page_number"] >= first.page_number)
           & ~((rows_df["page_number"] == first.page_number) & (rows_df["y0"] < first.y0))
           & rows_df["role"].isin(["body", "footnote"]))
assert rows_df.loc[rows_df["report_id"] == first.report_id, "page_number"].max() == 97, "The lists are the last pages."
rows_df.loc[in_list, "role"] = "figure_list"
figure_list = []
for r in rows_df[in_list].sort_values(["page_number", "y0"]).itertuples():
    t = r.text.strip()
    if LIST_HEAD_RE.match(t):
        kind = LIST_HEAD_RE.match(t).group(1)[:-1].lower()
    elif m := FIGURE_LIST_ENTRY_RE.match(t):
        figure_list.append({"kind": kind, "number": int(m["no"]), "page": int(m["page"])})
# the table entries print "caption" and "no page" on two baselines ("1 3", "2 20")
figure_list += [{"kind": "table", "number": int(m[1]), "page": int(m[2])}
                for t in rows_df.loc[in_list, "text"] if (m := re.match(r"^(\d)\s+(\d{1,3})$", t.strip()))]
figure_list_df = pd.DataFrame(figure_list).drop_duplicates()
spirit_caps = figures_df[figures_df["report_id"] == first.report_id]
for kind in ("figure", "table"):
    listed = sorted(figure_list_df.loc[figure_list_df["kind"] == kind, "number"])
    printed = sorted(set(spirit_caps.loc[spirit_caps["kind"] == kind, "number"].astype(int)))
    assert listed == printed, (kind, listed, printed)
print("SPIRIT_OF_BOSTON figure/table lists -> metadata:", int(in_list.sum()), "rows |",
      figure_list_df["kind"].value_counts().to_dict(), "entries = the printed captions")

# (b) OCR footnotes: bottom zone, left of the page's text column, starting with the note number
NOTE_START_RE = re.compile(r"^(?P<no>\d{1,3})(?:\s+(?P<a>\S.*)|(?P<b>[A-Za-z].*))$")     # "7CG 028 …" has no space; "4.2.9." is not a note
OCR_NOTE_START_RE = re.compile(r"^\d{1,2}\s+[A-Z]")
ocr_body = rows_df[(rows_df["provenance"] != "native") & (rows_df["role"] == "body")]
col_left = ocr_body.groupby(["report_id", "page_number"])["x0"].median()
ocr_note_rows = []
for (rid, p), pg in ocr_body[ocr_body["y0"] > 640].groupby(["report_id", "page_number"]):
    started = False
    for r in pg.sort_values("y0").itertuples():
        left = r.x0 < col_left[(rid, p)] - 25
        if left and (OCR_NOTE_START_RE.match(r.text.strip()) or started):
            ocr_note_rows.append(r.row_id); started = True
        else:
            started = False
rows_df.loc[rows_df["row_id"].isin(ocr_note_rows), "role"] = "footnote"
assert rows_df.loc[rows_df["row_id"].isin(ocr_note_rows), "report_id"].unique().tolist() == ["H20_BELOW"]

# (c) registry: a row starts note n when it prints the next number of its report; other rows continue the current note
NOTE_LABEL_SLIPS = {("SPIRIT_OF_BOSTON", 62, 54): 55}   # p.62 prints "54" again for the note of marker 55 (reviewed)
NOTE_ROW_OVERRIDES = {("SPIRIT_OF_BOSTON", 62): {"• Passenger ships": 54, "Oil tankers": 54,
                                                 "not later than July 1, 1998.": 54, "Other cargo ships": 54}}
# ^ the bullet list continues note 54 of p.61 ("…mandatory for three types of vessels, …:"), printed below note 55
note_parts, note_of_row = {}, {}
for rid, g in rows_df[rows_df["role"] == "footnote"].sort_values(["page_number", "y0"]).groupby("report_id", sort=False):
    last = 0
    for r in g.itertuples():
        t = r.text.strip()
        ovr = next((n for pre, n in NOTE_ROW_OVERRIDES.get((rid, r.page_number), {}).items() if t.startswith(pre)), None)
        m = NOTE_START_RE.match(t)
        n = NOTE_LABEL_SLIPS.get((rid, r.page_number, int(m["no"])), int(m["no"])) if m else None
        if ovr is not None:
            no, text = ovr, t
        elif m and n == last + 1:
            no, text, last = n, m["a"] or m["b"], n
        else:
            assert last, (rid, r.page_number, t)
            no, text = last, t
        note_parts.setdefault((rid, no), []).append((r.page_number, r.row_id, text))
        note_of_row[r.row_id] = (rid, no)
note_records = []
for (rid, no), parts in note_parts.items():
    text = ""
    for _, _, t in parts:                       # a row ending in "-" is a word split at the line end ("pre-" + "dives")
        text = text + t if text.endswith("-") else (text + " " + t if text else t)
    text = re.sub(r"\s+", " ", text).strip()
    note_records.append({"report_id": rid, "note_no": no, "text": text, "page_number": parts[0][0],
                         "row_ids": [x for _, x, _ in parts]})
notes_df = pd.DataFrame(note_records).sort_values(["report_id", "note_no"]).reset_index(drop=True)
for rid, g in notes_df.groupby("report_id"):
    assert g["note_no"].tolist() == list(range(1, len(g) + 1)), (rid, g["note_no"].tolist())
print("Notes:", len(notes_df), notes_df.groupby("report_id").size().to_dict())
display(notes_df[["report_id", "note_no", "text"]].head(5))

# %% cell 46
# =========================================================
# 5.3 Note references and policies
# =========================================================
# native: the superscript markers of 5.1 (kind note_ref); OCR (H20_BELOW): the number was read into the word —
# reviewed positions, the number is removed from the text and becomes the reference
OCR_NOTE_REFS = [("H20_BELOW", 10, "water1.", "water.", 1), ("H20_BELOW", 14, "measure.²", "measure.", 2),
                 ("H20_BELOW", 15, "it. 3", "it.", 3), ("H20_BELOW", 15, "lungs.4", "lungs.", 4)]
ref_records = [{"report_id": s.report_id, "note_no": int(s.marker), "row_id": s.row_id, "page_number": s.page_number,
                "line_key": s.line_key, "source": "superscript"}
               for s in superscripts_df[superscripts_df["kind"] == "note_ref"].itertuples()]
for rid, p, old, new, no in OCR_NOTE_REFS:
    ln = lines_df[(lines_df["report_id"] == rid) & (lines_df["page_number"] == p) & lines_df["text"].str.contains(old, regex=False)]
    assert len(ln) == 1, (rid, p, old)
    restore_in(lines_df, ln.index[0], old, new)
    restore_in(rows_df, row_ix[ln["row_id"].iloc[0]], old, new)
    ref_records.append({"report_id": rid, "note_no": no, "row_id": ln["row_id"].iloc[0], "page_number": p,
                        "line_key": ln["line_key"].iloc[0], "source": "ocr_digit"})
note_refs_df = pd.DataFrame(ref_records)

# policy: suggested by rule, then reviewed one by one (overrides with reasons)
CITATION_RE = re.compile(r"^(CG \d{3}|Email\b|Spirit of Norfolk (Public|Formal) Hearing|USCG Marine Safety Alert|"
                         r"Provided by\b|International Safety Management Code, IMO Resolution|Hollis Inc\.|"
                         r"Information (retrieved|provided)\b)")


def suggest_policy(text: str) -> str:
    if re.fullmatch(r"Redacted\.?", text.strip()):
        return "redacted"
    return "citation_only" if CITATION_RE.match(text) else "informative"


NOTE_POLICY_OVERRIDES = {}   # reviewed 2026-09-26: every suggestion checked, none changed (see the list below)
notes_df["policy"] = [NOTE_POLICY_OVERRIDES.get((r.report_id, r.note_no), suggest_policy(r.text)) for r in notes_df.itertuples()]
# reviewed informative notes (definitions, route/crew facts, quoted rules): SPIRIT 1,3,4,5,10,12,14,16,40,54,62;
# WAYMON 1–9; WILDERNESS 1; MICHIPICOTEN 1. SPIRIT 16 (quoted ISM definition of the Designated Person) and 40
# (SafeCruise programme, "CG Exhibit 061 contains samples…") carry facts beyond the citation -> informative.
REVIEWED_INFORMATIVE = {"SPIRIT_OF_BOSTON": [1, 3, 4, 5, 10, 12, 14, 16, 40, 54, 62], "WAYMON_BOYD": list(range(1, 10)),
                        "WILDERNESS_I": [1], "MICHIPICOTEN": [1]}
actual_inf = notes_df[notes_df["policy"] == "informative"].groupby("report_id")["note_no"].apply(list).to_dict()
assert actual_inf == REVIEWED_INFORMATIVE, actual_inf
print("Note policies:", notes_df["policy"].value_counts().to_dict(), "| references:", len(note_refs_df),
      note_refs_df["source"].value_counts().to_dict())

# %% cell 47
# =========================================================
# 5.4 Phase 5 validation
# =========================================================
keys_notes = set(zip(notes_df["report_id"], notes_df["note_no"]))
keys_refs = set(zip(note_refs_df["report_id"], note_refs_df["note_no"]))
assert keys_refs <= keys_notes, sorted(keys_refs - keys_notes)            # every marker resolves to a note
assert keys_notes <= keys_refs, sorted(keys_notes - keys_refs)            # every note is cited
assert note_refs_df.groupby(["report_id", "note_no"]).size().max() == 1, "One citing marker per note."
assert set(notes_df["policy"]) <= {"informative", "citation_only", "redacted"}
note_refs_df["anchor"] = note_refs_df["row_id"].map(rows_df.set_index("row_id")["role"]).map(
    {"body": "paragraph", "section_heading": "heading"})
assert note_refs_df["anchor"].notna().all()
# reviewed: WAYMON_BOYD note 9 (scope of the investigation) is cited by the heading "5. Analysis" -> own note unit in
# that section (as the IMO "*" note on a heading); every other marker sits in a paragraph
assert set(zip(*note_refs_df.loc[note_refs_df["anchor"] == "heading", ["report_id", "note_no"]].values.T)) == {("WAYMON_BOYD", 9)}
assert sorted(r for ids in notes_df["row_ids"] for r in ids) == sorted(rows_df.loc[rows_df["role"] == "footnote", "row_id"])
assert not rows_df["text"].str.contains("SternoDon|inof drainage|water1\\.", regex=True).any()
REVIEWED_PHASE5 = {"superscripts": {"note_ref": 89, "trademark": 29, "ordinal": 11, "exponent": 4},
                   "notes": {"SPIRIT_OF_BOSTON": 78, "WAYMON_BOYD": 9, "H20_BELOW": 4, "MICHIPICOTEN": 1, "WILDERNESS_I": 1},
                   "policy": {"citation_only": 65, "informative": 22, "redacted": 6},
                   "figure_list_rows": 100, "ocr_note_rows": 5}
actual = {"superscripts": superscripts_df["kind"].value_counts().to_dict(),
          "notes": notes_df["report_id"].value_counts().to_dict(), "policy": notes_df["policy"].value_counts().to_dict(),
          "figure_list_rows": int((rows_df["role"] == "figure_list").sum()), "ocr_note_rows": len(ocr_note_rows)}
assert actual == REVIEWED_PHASE5, {k: v for k, v in actual.items() if v != REVIEWED_PHASE5[k]}
print("✅ Phase 5 validation passed.")
print("Phase 5:", len(notes_df), "notes in", notes_df["report_id"].nunique(), "reports |", len(note_refs_df),
      "references |", int(superscripts_df["disposition"].eq("restored").sum()), "superscripts restored")

# %% [markdown] cell 48
# # Phases 6–8 — Body, numbered paragraphs, sections
#
# **Phase 6 (body).** The body is what Phase 4 left with the role `body`, minus what is already a structured unit or
# metadata: the vessel/vehicle table cells and the persons tables (4.3), their printed column headers and block titles,
# the persons statements ("None", "There were no deceased…" → the persons unit), and the **acronym lists** (CONCHRD's
# LIST OF ACRONYMS part and SPIRIT_OF_BOSTON's List of Acronyms page → one glossary unit each, plan §6).
# The remaining rows are joined into **paragraphs** in reading order:
#
# - a new paragraph starts at a printed paragraph number (`4.1.3.`), a list item (`1.`, `(a)`, `•`), a letter label
#   (`Recommendation 1:`, `Action:`, `Endorsement 1:`), a change of part / sub-part / section, or a heading;
# - on the same page, a baseline step larger than 1.4 × the report's usual line pitch ends the paragraph, and so does a
#   visible last line (it ends a sentence and is shorter than the text column) before a capitalised row — the OCR
#   pages print no extra space between paragraphs;
# - **across a page** (and around a figure / page furniture in the middle of a page) the paragraph continues unless
#   the last row is visibly the last line of a paragraph (it ends a sentence and is shorter than the text column) —
#   merging two paragraphs costs nothing for retrieval, cutting one in two would separate a sentence from its subject;
# - a row that ends in "-" is joined without a space (a compound split at the line end: "pre-" + "dives").
#
# **Phase 7 (numbering).** Depth = number of components of the printed number; every paragraph gets the number of the
# numbered paragraph it belongs to (unnumbered prose, bullets and list items belong to the last numbered paragraph).
# Numbering continuity is checked (each number is the first child or the next sibling of an open number); the
# exceptions are reviewed. A numbered paragraph that is only a title ("4.1. The Incident:") is a **sub-heading**.
#
# **Phase 8 (sections).** Every paragraph gets its place: document part (letter or report) → sub-part → canonical
# section (the eight ROI sections, whatever title variant is printed) → sub-heading path. This becomes the chunk
# header `USCG ROI <vessel> (MISLE <n>, <incident date>) — <section path>` (plan §3, Phase 14).

# %% cell 49
# =========================================================
# 6.1 Body rows: exclusions (structured units, table headers, persons statements, glossaries)
# =========================================================
# (a) corrections of Phase 4 roles found while reading the body (reviewed 2026-09-26):
#     signer names / offices under a letter whose rank row is missing or OCR-damaged -> signature (never kept);
#     a memorandum's "Copy:" distribution line -> memo_header;
#     a roman page number of the executive summary -> page_number; labels printed inside OCR images -> figure_internal;
#     an OCR caption's second line -> caption (appended to its figure unit)
NAME_ONLY_RE = re.compile(r"^(?:(?:[A-Z]\.\s?){1,2}\s?[A-Z][A-Za-z'’\-]{2,}|[A-Z][a-z]+\s[A-Z]\.\s[A-Z][A-Za-z'’\-]+)$")
OFFICE_ONLY_RE = re.compile(r"^(?:.{0,25}(?:Coast Guard|oas Guard)\s)?Investigating\s?Officer$")
RANK_ONLY_RE = re.compile(r"^(?:Civilian|Captain|Commander|L\w{1,3}tenant|LT|LCDR|CDR|CAPT|CWO\d?|Chief Warrant Officer\s?\d?|"
                          r"Ensign|Rear Admiral)\s?,\s*U\.?\s?S?\.?\s?\.?\s*Coa\S*(?:\s\S+)?$|^U\.\s?S\.\s?Coast Guard$|^\. \. oas Guard$")
FIGURE_LABEL_ROWS = [("H20_BELOW", 10, "H2O BELOW", 1), ("H20_BELOW", 10, "TRAVEL LINE", 1), ("H20_BELOW", 12, "Shearwater", 2)]
CAPTION_CONTINUATIONS = [("LITTLE_G", 9, "Alabama River. (Google Maps)")]
b = rows_df["role"] == "body"
sig = b & rows_df["text"].str.strip().map(lambda t: bool(NAME_ONLY_RE.match(t) or OFFICE_ONLY_RE.match(t)
                                                        or (len(t) <= 90 and RANK_ONLY_RE.match(t))))
rows_df.loc[sig, "role"] = "signature"
# an office row printed right under a signer row ("Commander, Sector Long Island Sound") belongs to the signature
for _ in range(3):
    o = rows_df.sort_values(["report_id", "page_number", "y0"])
    prev_sig = (o["role"].shift(1) == "signature") & (o["report_id"].shift(1) == o["report_id"]) \
        & (o["page_number"].shift(1) == o["page_number"]) & ((o["y0"] - o["y0"].shift(1)) < 20)
    office = (o["role"] == "body") & prev_sig & o["text"].str.strip().map(lambda t: len(t) <= 90 and bool(SIGNATURE_OFFICE_RE.match(t)))
    rows_df.loc[office[office].index, "role"] = "signature"
    sig = sig | rows_df.index.isin(office[office].index)
copy_line = b & rows_df["text"].str.strip().str.startswith("Copy:")      # memorandum distribution line -> metadata
rows_df.loc[copy_line, "role"] = "memo_header"
roman = b & rows_df["text"].str.strip().map(lambda t: bool(re.fullmatch(r"[ivx]{1,4}", t)))
rows_df.loc[roman, "role"] = "page_number"
for rid, p, text, n in FIGURE_LABEL_ROWS:
    hit = b & (rows_df["report_id"] == rid) & (rows_df["page_number"] == p) & (rows_df["text"].str.strip() == text)
    assert hit.sum() == n, (rid, p, text, int(hit.sum()))
    rows_df.loc[hit, "role"] = "figure_internal"
for rid, p, text in CAPTION_CONTINUATIONS:
    hit = rows_df[b & (rows_df["report_id"] == rid) & (rows_df["page_number"] == p) & (rows_df["text"].str.strip() == text)]
    assert len(hit) == 1, (rid, p, text)
    above = rows_df[(rows_df["report_id"] == rid) & (rows_df["page_number"] == p) & (rows_df["role"] == "caption")
                    & (rows_df["y0"] < hit["y0"].iloc[0])].sort_values("y0").iloc[-1]
    fi = figures_df.index[figures_df["row_ids"].map(lambda ids: above.row_id in ids)][0]
    figures_df.at[fi, "row_ids"] = figures_df.at[fi, "row_ids"] + [hit["row_id"].iloc[0]]
    figures_df.at[fi, "caption"] = figures_df.at[fi, "caption"] + " " + text
    rows_df.loc[hit.index, "role"] = "caption"
role_fixes = {"signature": int(sig.sum()), "page_number": int(roman.sum()), "memo_header": int(copy_line.sum()), "figure_internal": sum(n for *_, n in FIGURE_LABEL_ROWS),
              "caption": len(CAPTION_CONTINUATIONS)}
print("Phase 4 role corrections:", role_fixes)

structured_rows = {x for ids in pd.concat([vessel_fields_df["row_ids"], persons_df["row_ids"], persons_none_rows["row_ids"]])
                   for x in ids}
body_role = pd.Series(None, index=rows_df.index, dtype=object)
is_body = rows_df["role"] == "body"
in_tables = is_body & rows_df["part"].eq("io_report") & rows_df["section"].isin([2, 3])
body_role[is_body & rows_df["row_id"].isin(structured_rows)] = "structured_table"
body_role[is_body & rows_df["part"].eq("io_report") & body_role.isna()
          & rows_df["text"].map(lambda t: bool(PERSONS_HEADER_RE.match(t.strip())))] = "table_header"
# reviewed: QUEEN_OF_THE_WEST prints a block title above its vessel table; two reports print a statement, not a table
TABLE_TITLE_ROWS = {("QUEEN_OF_THE_WEST", "PASSENGER VESSEL QUEEN OF THE WEST"): "table_header",
                    ("MICHIPICOTEN", "None"): "persons_statement",
                    ("VICAR_602", "There were no deceased, missing, or injured personnel as a result of this marine casualty."):
                        "persons_statement"}
for (rid, text), kind in TABLE_TITLE_ROWS.items():
    hit = in_tables & (rows_df["report_id"] == rid) & (rows_df["text"].str.strip() == text) & body_role.isna()
    assert hit.sum() == 1, (rid, text, int(hit.sum()))
    body_role[hit] = kind
# glossaries: CONCHRD's LIST OF ACRONYMS part, SPIRIT_OF_BOSTON's "List of Acronyms" page (before the figure list)
spirit_acr = rows_df[(rows_df["report_id"] == "SPIRIT_OF_BOSTON") & (rows_df["text"].str.strip() == "List of Acronyms") & is_body]
assert len(spirit_acr) == 1
acr = spirit_acr.iloc[0]
body_role[is_body & (rows_df["part"] == "list_of_acronyms")] = "glossary"
body_role[is_body & (rows_df["report_id"] == acr.report_id) & (rows_df["page_number"] == acr.page_number)
          & (rows_df["y0"] >= acr.y0)] = "glossary"
body_role[is_body & body_role.isna()] = "paragraph"
rows_df["body_role"] = body_role
glossary_records = []
for rid, g in rows_df[rows_df["body_role"] == "glossary"].sort_values(["page_number", "y0"]).groupby("report_id"):
    left = g["x0"].min()
    for r in g.itertuples():
        t = r.text.strip()
        if t in ("Acronym Title", "List of Acronyms"):
            continue
        if r.x0 > left + 100:                                   # a wrapped meaning ("…Atmospheric" / "Administration")
            glossary_records[-1]["meaning"] += " " + t; glossary_records[-1]["row_ids"].append(r.row_id)
            continue
        segs = [s_[2].strip() for s_ in sorted(r.segments)]     # acronym and meaning are two printed columns
        acronym, meaning = (segs[0], " ".join(segs[1:])) if len(segs) > 1 else t.split(" ", 1)
        glossary_records.append({"report_id": rid, "acronym": acronym, "meaning": meaning, "row_ids": [r.row_id]})
glossary_df = pd.DataFrame(glossary_records)
print("Body rows:", rows_df["body_role"].value_counts().to_dict())
print("Glossary entries:", glossary_df.groupby("report_id").size().to_dict())
display(glossary_df.head(3))

# %% cell 50
# =========================================================
# 6.2 Paragraphs (reading order, page breaks, figures in the middle of a paragraph)
# =========================================================
PARA_START_RES = {
    # "4.1.3. Text", "4.2.3.5 Freeing Ports", "4.1.2PROWLER" (OCR); not a wrapped "5.90 hours" or a cross-reference
    # "4.2.19." / "8.1.2" alone at the start of a line (the atomic group keeps the whole printed number)
    "numbered": re.compile(r"^(?>\d{1,2}(?:\.\d{1,2}){1,5})(?:\.\s*(?=\S)|\s+(?=[A-Z0-9(“\"])|(?=[A-Z]))"),
    "item": re.compile(r"^(?:\(?\d{1,2}[.)]\s|\(?[a-z][.)]\s|\([ivx]{1,4}\)\s)"),
    "bullet": re.compile(r"^[•●▪■◦]"),
    "label": re.compile(r"^(?:(?:Safety|Administrative)\s+)?(?:Recommendation|Action|Endorsement|Comment|Response)"
                        r"(?:\s+\d{1,2}(?:\.\d{1,2}){0,3})?\s*[:.–—-]"),
}
HARD_BREAK_ROLES = {"section_heading", "letter_heading", "letter_heading_cont", "front_heading", "casualty_title",
                    "signature", "enclosures", "memo_header", "toc", "cover", "figure_list"}
LONE_NUMBER_RE = re.compile(r"^\d{1,2}(?:\.\d{1,2}){1,5}\.?$")
TERMINAL_RE = re.compile(r"[.!?:;”\"’)]$")


# the OCR layer of MERRICK prints spaces inside numbers ("4 .1. 8.", "4.1 .12.")
OCR_NUMBER_RE = re.compile(r"^(?>\d{1,2}(?:\s?\.\s?\d{1,2}){1,5})(?:\.\s*(?=\S)|\s+(?=[A-Z0-9(“\"])|(?=[A-Z]))")


def start_kind(t: str, ocr: bool = False) -> str | None:
    if ocr and OCR_NUMBER_RE.match(t):
        return "numbered"
    return next((k for k, rx in PARA_START_RES.items() if rx.match(t)), None)


def join_text(a: str, b: str) -> str:
    return a + b if a.endswith("-") and b[:1].isalpha() else (a + " " + b if a else b)


flow = rows_df.sort_values(["report_id", "page_number", "y0", "x0"])
para_records, para_of_row = [], {}
for rid, g in flow.groupby("report_id", sort=True):
    body_g = g[g["body_role"] == "paragraph"]
    steps = body_g.groupby("page_number")["y0"].diff()
    pitch = float(steps[(steps > 5) & (steps < 30)].median())          # the report's usual baseline step
    col_right = float(body_g["x1"].quantile(0.9))                        # right edge of the text column
    cur, prev, soft = None, None, False
    for r in g.itertuples():
        if r.body_role != "paragraph":
            if r.role in HARD_BREAK_ROLES or r.body_role in ("structured_table", "table_header", "persons_statement", "glossary"):
                cur = None
            else:
                soft = True                                              # furniture, caption, footnote, image text
            continue
        t = r.text.strip()
        kind = start_kind(t, r.provenance != "native")
        if kind is None and LONE_NUMBER_RE.match(t) and (prev is None or TERMINAL_RE.search(prev.text.strip())):
            kind = "numbered"               # "4.2.16." printed on its own row, the text on the next baseline (CUYAHOGA);
                                            # after a line that runs on it is a cross-reference ("…discussed in 4.2.19.")
        ctx = (r.part, r.sub_part if isinstance(r.sub_part, str) else None, None if pd.isna(r.section) else int(r.section))
        new = cur is None or kind is not None or ctx != cur["ctx"]
        if not new and prev is not None:
            ended = bool(TERMINAL_RE.search(prev.text.strip())) and prev.x1 < col_right - 40
            if r.page_number == prev.page_number and not soft:
                new = (r.y0 - prev.y0) > 1.4 * pitch or (ended and t[:1].isupper())
            else:
                new = ended and not t[:1].islower()
        if new:
            cur = {"report_id": rid, "ctx": ctx, "kind": kind or "prose", "row_ids": [], "text": "", "ocr": r.provenance != "native",
                   "page_start": r.page_number, "page_end": r.page_number}
            para_records.append(cur)
        cur["row_ids"].append(r.row_id); cur["text"] = join_text(cur["text"], t); cur["page_end"] = r.page_number
        prev, soft = r, False
paragraphs_df = pd.DataFrame(para_records)
paragraphs_df[["part", "sub_part", "section"]] = pd.DataFrame(paragraphs_df["ctx"].tolist(), index=paragraphs_df.index)
paragraphs_df = paragraphs_df.drop(columns="ctx")
paragraphs_df["para_no"] = paragraphs_df.groupby("report_id").cumcount() + 1
paragraphs_df["para_id"] = paragraphs_df["report_id"] + ":p" + paragraphs_df["para_no"].map("{:03d}".format)
paragraphs_df["text"] = paragraphs_df["text"].map(lambda s: re.sub(r"\s+", " ", s).strip())
# an unnumbered one-row title inside a section ("Regulatory Framework", "EPIC Dock Project Plans", "Safety") heads the
# paragraph after it: kind `inline_heading`, joined to that paragraph when the units are built (Phase 9)
ctx_key = pd.Series([f"{a}|{b}|{c}" for a, b, c in zip(paragraphs_df["part"], paragraphs_df["sub_part"], paragraphs_df["section"])],
                    index=paragraphs_df.index)
nxt_ctx = ctx_key.groupby(paragraphs_df["report_id"]).shift(-1)
paragraphs_df.loc[(paragraphs_df["kind"] == "prose") & (paragraphs_df["row_ids"].map(len) == 1)
                  & paragraphs_df["text"].map(lambda t: len(t) <= 60 and not re.search(r"[.;,?!”\"]$", t) and t[:1].isupper()
                                              and not re.match(r"^[QA]\.?\s", t))
                  & (nxt_ctx == ctx_key), "kind"] = "inline_heading"
paragraphs_df["n_chars"] = paragraphs_df["text"].str.len()
for p in paragraphs_df.itertuples():
    for x in p.row_ids:
        para_of_row[x] = p.para_id
print("Paragraphs:", len(paragraphs_df), "| kinds:", paragraphs_df["kind"].value_counts().to_dict(),
      "| across pages:", int((paragraphs_df["page_end"] > paragraphs_df["page_start"]).sum()))
print("Paragraph length: median", int(paragraphs_df["n_chars"].median()), "| max", int(paragraphs_df["n_chars"].max()))

# %% cell 51
# =========================================================
# 7.1 Numbering: printed number, depth, owning number, sub-headings
# =========================================================
NUM_RE = re.compile(r"^(?P<num>(?>\d{1,2}(?:\.\d{1,2}){1,5}))\.?")
OCR_NUM_RE = re.compile(r"^(?P<num>(?>\d{1,2}(?:\s?\.\s?\d{1,2}){1,5}))\.?")
ITEM_NUM_RE = re.compile(r"^\(?(?P<num>\d{1,2}|[a-z]|[ivx]{1,4})[.)]")
LABEL_RE = re.compile(r"^(?:(?P<qual>Safety|Administrative)\s+)?(?P<label>Recommendation|Action|Endorsement|Comment|Response)"
                      r"(?:\s+(?P<num>\d{1,2}(?:\.\d{1,2}){0,3}))?")


def printed_number(kind: str, t: str, ocr: bool = False) -> str | None:
    t = t.strip()
    if kind == "numbered":
        return re.sub(r"\s", "", (OCR_NUM_RE if ocr else NUM_RE).match(t)["num"])
    if kind == "item":
        return ITEM_NUM_RE.match(t)["num"]
    if kind == "label":
        m = LABEL_RE.match(t)
        return " ".join(x for x in (m["qual"], m["label"], m["num"]) if x)
    return None


paragraphs_df["number"] = [printed_number(k, t, o) for k, t, o in zip(paragraphs_df["kind"], paragraphs_df["text"], paragraphs_df["ocr"])]
# a printed number whose first part is not its section's number is the numbering of a quoted list (SPIRIT_OF_BOSTON
# quotes a university's Sterno guideline "3.1.1 … 3.2.16" inside 4.4.3.3) -> list item, not a report paragraph
printed_section = {(r.report_id, r.section): str(r.printed_number) for r in section_hits_df.itertuples()}


QUOTED_LIST_SPANS = [("SPIRIT_OF_BOSTON", "4.4.3.3", "4.4.3.4")]   # reviewed: numbered paragraphs between these two
own_prefix = pd.Series(False, index=paragraphs_df.index)
for rid, a, b in QUOTED_LIST_SPANS:
    g = paragraphs_df[(paragraphs_df["report_id"] == rid)]
    ia, ib = g.index[g["number"] == a][0], g.index[g["number"] == b][0]
    own_prefix[(paragraphs_df.index > ia) & (paragraphs_df.index < ib) & (paragraphs_df["kind"] == "numbered")] = True
quoted_list_df = paragraphs_df.loc[own_prefix, ["report_id", "para_id", "number"]]
paragraphs_df.loc[own_prefix, "kind"] = "item"
paragraphs_df["depth"] = paragraphs_df["number"].where(paragraphs_df["kind"] == "numbered").map(
    lambda n: n.count(".") + 1 if isinstance(n, str) else np.nan)
# owning number: the last numbered paragraph of the same part / section (prose, bullets and items belong to it)
owner, last = [], {}
for p in paragraphs_df.itertuples():
    key = (p.report_id, p.part, p.sub_part, p.section)
    if p.kind == "numbered":
        last[key] = p.number
    owner.append(last.get(key))
paragraphs_df["owner_number"] = owner
# sub-heading: a numbered paragraph that is only a title and is followed by its first child
nxt = paragraphs_df.groupby("report_id")["number"].shift(-1)
title_only = paragraphs_df["text"].map(lambda t: len(t) <= 90 and not re.search(r"[.!?]\s+\S", NUM_RE.sub("", t, 1).strip()))
paragraphs_df["is_subheading"] = ((paragraphs_df["kind"] == "numbered") & title_only
                                  & (nxt.fillna("") == paragraphs_df["number"].fillna("-") + ".1"))
paragraphs_df["title"] = np.where(paragraphs_df["is_subheading"],
                                  paragraphs_df["text"].map(lambda t: NUM_RE.sub("", t, 1).strip(" .:–-")), None)
print("Numbered:", int((paragraphs_df["kind"] == "numbered").sum()), "| depth:",
      paragraphs_df["depth"].value_counts().sort_index().to_dict(), "| sub-headings:", int(paragraphs_df["is_subheading"].sum()))

# %% cell 52
# =========================================================
# 7.2 Numbering continuity (reviewed exceptions)
# =========================================================
def next_numbers(open_nums: list[str]) -> set[str]:
    """Numbers allowed after the open chain: the first child of the last one, or the next sibling at any level."""
    if not open_nums:
        return set()
    last = open_nums[-1].split(".")
    ok = {".".join(last + ["1"])}
    for k in range(1, len(last) + 1):
        head = last[:k]
        ok.add(".".join(head[:-1] + [str(int(head[-1]) + 1)]))
    return ok


numbering_issues = []
for (rid, part, sec), g in paragraphs_df[paragraphs_df["kind"] == "numbered"].groupby(
        ["report_id", "part", "section"], sort=False, dropna=False):
    chain = []
    for p in g.itertuples():
        if chain and p.number not in next_numbers(chain):
            numbering_issues.append((rid, p.number, "sequence", chain[-1]))
        chain = [p.number]
numbering_issues_df = pd.DataFrame(numbering_issues, columns=["report_id", "number", "issue", "context"])
print("Numbering issues:", len(numbering_issues_df), numbering_issues_df["issue"].value_counts().to_dict())
display(numbering_issues_df.head(40))

# %% cell 53
# =========================================================
# 8.1 Sections: part -> sub-part -> canonical section -> sub-heading path
# =========================================================
PART_LABELS = {"action_commandant": "Action by the Commandant", "endorsement_district": "Endorsement by the District Commander",
               "endorsement_ocmi": "Endorsement by the Officer in Charge, Marine Inspection",
               "executive_summary": "Executive Summary", "io_report": "Investigating Officer's Report",
               "convening_memorandum": "Convening memorandum", "list_of_acronyms": "List of acronyms", "cover": "Cover"}
SUB_PART_LABELS = {"action_on_recommendations": "Action on Recommendations",
                   "endorsement_on_recommendations": "Endorsement on Recommendations",
                   "comments_on_report": "Comments on the Report"}
CANONICAL_SECTIONS = {1: "Preliminary Statement", 2: "Vessels Involved", 3: "Deceased, Missing, and Injured Persons",
                      4: "Findings of Fact", 5: "Analysis", 6: "Conclusions", 7: "Actions Taken Since the Incident",
                      8: "Recommendations"}
# printed section titles (the variants Phase 2 mapped to the canonical eight)
sections_df = section_hits_df.merge(rows_df[["row_id", "text"]], on="row_id", how="left").rename(columns={"text": "printed_title"})
sections_df["canonical_title"] = sections_df["section"].map(CANONICAL_SECTIONS)
sections_df["printed_slip"] = [NUMBERING_SLIPS.get((r.report_id, r.section)) is not None for r in sections_df.itertuples()]

sub_title = {(p.report_id, p.number): p.title for p in paragraphs_df[paragraphs_df["is_subheading"]].itertuples()}


def heading_chain(rid: str, number, is_sub: bool) -> list[str]:
    """Titles of the sub-headings above a paragraph (its own title is not part of its path)."""
    if not isinstance(number, str):
        return []
    comps = number.split(".")
    stop = len(comps) - 1 if is_sub else len(comps)
    chain = []
    for k in range(2, stop + 1):
        n = ".".join(comps[:k])
        if (rid, n) in sub_title:
            chain.append(f"{n} {sub_title[(rid, n)]}")
    return chain


def section_path(p) -> tuple[str, str | None]:
    parent = PART_LABELS[p.part]
    if isinstance(p.sub_part, str):
        parent += " > " + SUB_PART_LABELS[p.sub_part]
    if p.part == "io_report" and not pd.isna(p.section):
        parent += " > " + CANONICAL_SECTIONS[int(p.section)]
    num = p.number if p.kind == "numbered" else p.owner_number
    chain = heading_chain(p.report_id, num, bool(p.is_subheading) and p.kind == "numbered")
    return parent, (" > ".join(chain) or None)


paths = [section_path(p) for p in paragraphs_df.itertuples()]
paragraphs_df["parent_chunk"] = [a for a, _ in paths]
paragraphs_df["sub_chunk"] = [b for _, b in paths]
meta_of = meta_df.set_index("report_id")
paragraphs_df["header"] = [f"USCG ROI {meta_of.at[p.report_id, 'vessel_label']} (MISLE {meta_of.at[p.report_id, 'misle']}, "
                           f"{pd.Timestamp(meta_of.at[p.report_id, 'incident_date']):%Y-%m-%d}) — {p.parent_chunk}"
                           + (f" > {p.sub_chunk}" if p.sub_chunk else "") for p in paragraphs_df.itertuples()]
print("Sections:", len(sections_df), "| printed title variants:", sections_df["printed_title"].str.strip().nunique(),
      "| printed-number slips:", int(sections_df["printed_slip"].sum()))
print("Paragraph paths:", paragraphs_df["parent_chunk"].nunique(), "parents |",
      int(paragraphs_df["sub_chunk"].notna().sum()), "paragraphs under a sub-heading")
print("Example header:", paragraphs_df.loc[paragraphs_df["sub_chunk"].notna(), "header"].iloc[0])

# %% cell 54
# =========================================================
# 8.2 Phases 6–8 validation
# =========================================================
para_rows = [x for ids in paragraphs_df["row_ids"] for x in ids]
assert len(para_rows) == len(set(para_rows)), "A row belongs to one paragraph."
assert set(para_rows) == set(rows_df.loc[rows_df["body_role"] == "paragraph", "row_id"])
assert rows_df.loc[rows_df["role"] == "body", "body_role"].notna().all()
assert paragraphs_df["para_id"].is_unique and paragraphs_df["part"].notna().all()
io = paragraphs_df["part"] == "io_report"
assert paragraphs_df.loc[io, "section"].between(1, 8).all(), "Every report paragraph sits in a canonical section."
assert (paragraphs_df["n_chars"] > 0).all()
# personal names of signers never reach a paragraph (Phase 6.1 corrections); the persons units keep roles only
assert not paragraphs_df["text"].map(lambda t: bool(NAME_ONLY_RE.match(t) or RANK_ONLY_RE.match(t))).any()
# reviewed numbering exceptions (printed in the source; kept as printed, recorded in Phase 9 errata)
REVIEWED_NUMBERING = {("CAROL_ANN", "4.2.3.5"),          # "4.2.3.5" printed twice (Freeing Ports / Best Practices)
                      ("GENERAL_MACARTHUR", "4.2.6"),    # "4.2.6" printed twice
                      ("PROWLER_ATTESSA_IV", "4.3.8"),   # 4.3.8–4.3.10 follow 4.2.7 (no 4.3 heading printed)
                      ("SPIRIT_OF_BOSTON", "4.1"),       # the second Findings part restarts at 4.1 after 3.25 (3b)
                      ("UNA_MAS", "8.2.1.1"),            # 8.2.1 is not printed
                      ("WAYMON_BOYD", "4.06"), ("WAYMON_BOYD", "4.1.23"),   # a stray "4.06." between 4.1.22 and 4.1.23
                      ("WILDERNESS_I", "4.1")}           # "4.1" printed twice (The Incident / Medical Evaluation)
assert set(zip(numbering_issues_df["report_id"], numbering_issues_df["number"])) == REVIEWED_NUMBERING, \
    set(zip(numbering_issues_df["report_id"], numbering_issues_df["number"])) ^ REVIEWED_NUMBERING
REVIEWED_PHASE6_8 = {"paragraphs": 3170, "kinds": {"numbered": 2108, "prose": 539, "label": 256, "item": 205, "bullet": 37,
                                                "inline_heading": 25},
                     "subheadings": 202, "across_pages": 124, "glossary": {"CONCHRD": 27, "SPIRIT_OF_BOSTON": 26},
                     "body_roles": {"paragraph": 13415, "structured_table": 415, "glossary": 58, "table_header": 21,
                                    "persons_statement": 2},
                     "quoted_list_items": 15,
                     "role_fixes": {"signature": 57, "page_number": 1, "memo_header": 1, "figure_internal": 4, "caption": 1}}
actual = {"paragraphs": len(paragraphs_df), "kinds": paragraphs_df["kind"].value_counts().to_dict(),
          "subheadings": int(paragraphs_df["is_subheading"].sum()),
          "across_pages": int((paragraphs_df["page_end"] > paragraphs_df["page_start"]).sum()),
          "glossary": glossary_df["report_id"].value_counts().to_dict(),
          "body_roles": rows_df["body_role"].value_counts().to_dict(), "quoted_list_items": len(quoted_list_df),
          "role_fixes": role_fixes}
assert actual == REVIEWED_PHASE6_8, {k: v for k, v in actual.items() if v != REVIEWED_PHASE6_8[k]}
print("✅ Phases 6–8 validation passed.")
print("Phases 6–8:", len(paragraphs_df), "paragraphs |", actual["subheadings"], "sub-headings |",
      len(glossary_df), "glossary entries |", len(numbering_issues_df), "reviewed numbering exceptions")

# %% [markdown] cell 55
# # Phase 9 — Unified logical units, errata, access and personal data
#
# One pre-chunking table (`units_df`) with a single authoritative text field (`content`):
#
# | unit_type | Source | One unit = |
# |---|---|---|
# | `paragraph` | Phases 6–8 | one paragraph; an inline heading or a title-only sub-heading is joined to the paragraph after it; informative notes appended as `Note: …` (Phase 5) |
# | `note` | WAYMON_BOYD note 9 | an informative note printed on a heading ("5. Analysis"), own unit in that section (as the IMO `*` note) |
# | `vessel_block` | 4.3 | one vessel / vehicle particulars table, `label: value` per printed row |
# | `persons` | 4.3–4.4 | the deceased / missing / injured persons table (roles only) or the printed statement |
# | `glossary` | 6.1 | one list of acronyms |
#
# Citation-only notes stay in the unit's `citations` (metadata, never in `content`).
#
# **Figures are not units.** All 204 figures are raster images gated `caption_only` (4.5, ADR-020): a caption names a
# photo the system cannot show ("Photograph of … Source: …"), and the facts a few captions add are printed in the
# report text too (measured: median 11–18 % of a caption's content words are not in its report's text, mostly image
# annotations such as "yellow pin" or "red oval"). As chunks they would only compete with the paragraphs in
# retrieval, so the captions stay **metadata** in the extracted file (figure id, caption, page, class, gate).
#
# **Personal data (plan §4.6).** Report text is kept as published (public redacted release). Curated text — headers,
# paths, the persons and vessel units, the incident profiles — uses roles: the signers' names were excluded in
# Phases 4/6, and an **individual** owner or operator in a vessel table (BIG_STICK, CUMBERLAND_II, GOOD_GULF, KIM_LY,
# MERRICK, NC3250BW, UNA_MAS; every other printed party is a company or a redacted name, asserted) is written
# as a role, never by name (company names are kept).
#
# **Errata (ADR-022).** KIM_LY: the executive-summary clause "On 19 February 2024," contradicts the report's own dates
# (the casualty titles and 4.1.1: 20 February 2024) → the clause is excluded, never corrected. Printed numbering slips
# (3b, 7.2) are kept as printed and recorded.
#
# **Access (ADR-021).** Every unit is level 1 / Operations (`docs/rbac_mapping.md` §4: a public federal report). The
# money keyword pre-filter still lists every candidate unit, and each gets the reviewed decision with its reason.

# %% cell 56
# =========================================================
# 9.1 Logical units
# =========================================================
DEPARTMENT, LEVEL = "Operations", 1
assert DEPARTMENT in KNOWN_DEPARTMENTS
prov_of_row = rows_df.set_index("row_id")["provenance"]
page_of_row = rows_df.set_index("row_id")["page_number"]


def provenance_of(row_ids) -> str:
    p = set(prov_of_row[list(row_ids)])
    return "ocr" if p & {"ocr", "ocr_layer"} else "pdf_text"


unit_records = []


def add_unit(rid, unit_type, content, row_ids, parent, sub, **extra):
    pages = sorted(set(page_of_row[list(row_ids)])) if row_ids else [np.nan]
    unit_records.append({"report_id": rid, "unit_type": unit_type, "content": content, "row_ids": list(row_ids),
                         "page_start": pages[0], "page_end": pages[-1], "parent_chunk": parent, "sub_chunk": sub,
                         "provenance": provenance_of(row_ids) if row_ids else "curated_from_report", **extra})


# (a) paragraphs: leads (inline headings, title-only sub-headings) join the next paragraph of the same context
for rid, g in paragraphs_df.groupby("report_id", sort=True):
    lead = []
    recs = list(g.itertuples())
    for i, p in enumerate(recs):
        is_lead = p.kind == "inline_heading" or bool(p.is_subheading)
        nxt = recs[i + 1] if i + 1 < len(recs) else None
        same_ctx = nxt is not None and (nxt.part, nxt.sub_part, nxt.section) == (p.part, p.sub_part, p.section) \
            and not (pd.isna(p.section) ^ pd.isna(nxt.section))
        if is_lead and same_ctx:
            lead.append(p); continue
        members = lead + [p]; lead = []
        add_unit(rid, "paragraph", "\n".join(m.text for m in members), [x for m in members for x in m.row_ids],
                 p.parent_chunk, p.sub_chunk, para_ids=[m.para_id for m in members], number=p.number,
                 part=p.part, sub_part=p.sub_part, section=p.section, kind=p.kind)

# (b) vessel / vehicle blocks (individual owners and operators by role, reviewed)
INDIVIDUAL_PARTIES = {("BIG_STICK", "operator"), ("KIM_LY", "owner"), ("KIM_LY", "operator"), ("MERRICK", "operator"),
                      ("UNA_MAS", "owner"), ("UNA_MAS", "operator"), ("CUMBERLAND_II", "owner_operator"),
                      ("GOOD_GULF", "owner_operator"), ("NC3250BW", "owner_operator")}
PARTY_ROLE = {"owner": "an individual owner (name not kept)", "operator": "an individual operator (name not kept)",
              "owner_operator": "an individual owner/operator (name not kept)"}
# guard: every printed owner / operator is a company, a reviewed individual, empty, or a location only (name redacted)
COMPANY_RE = re.compile(r"\b(LLC|L\.L\.C|Inc|Corp|Corporation|Company|Co\.|Ltd|Limited|Charterers?|Charters|Towing|Marine|"
                        r"Cruises|Department|STATE OF|Construction|Physics|Boat Co)\b", re.I)
LOCATION_ONLY = {("LADY_ELLEN", "owner_operator"), ("PROWLER_ATTESSA_IV", "operator"), ("VICAR_602", "owner"),
                 ("VICAR_602", "operator")}
for f in vessel_fields_df[vessel_fields_df["field"].isin(PARTY_ROLE)].itertuples():
    v = f.value.strip()
    assert not v or COMPANY_RE.search(v) or (f.report_id, f.field) in INDIVIDUAL_PARTIES | LOCATION_ONLY, (f.report_id, f.field)
for (rid, block), g in vessel_fields_df.groupby(["report_id", "block_no"], sort=True):
    name = g.loc[g["field"] == "name", "value"]
    kind = g["block_kind"].iloc[0]
    title = f"{'Vehicle' if kind == 'vehicle' else 'Vessel'} particulars" + (f" — {name.iloc[0].strip()}" if len(name) else "")
    lines = []
    for f in g.itertuples():
        value = f.value.strip()
        if (rid, f.field) in INDIVIDUAL_PARTIES and value:
            value = PARTY_ROLE[f.field]
        lines.append(f"{f.label_printed.strip().rstrip(':')}: {value if value else '(blank in the table)'}")
    add_unit(rid, "vessel_block", title + "\n" + "\n".join(lines), [x for ids in g["row_ids"] for x in ids],
             "Investigating Officer's Report > Vessels Involved", title.split(" — ")[-1] if len(name) else None,
             part="io_report", section=2, block_no=int(block))

# (c) persons: the printed table (roles only) or the printed statement
PERSONS_TITLE = "Deceased, missing and injured persons (as printed; roles only)"
EMPLOYMENT_RE = re.compile(r"\d+\+?\s*(?:weeks?|months?|years?)\b", re.I)
row_text = rows_df.set_index("row_id")["text"]
for rid, g in persons_df.groupby("report_id", sort=True):
    lines = []
    for p in g.itertuples():
        cells = [" ".join(str(p.relationship).split())] + [str(x).strip() for x in (p.sex, p.age) if pd.notna(x) and str(x).strip()] \
            + [str(p.status).strip()]
        # QUEEN_OF_THE_WEST prints a "Period of Employment" column (reviewed); the Name column is never kept
        period = [m.group(0) for x in p.row_ids for m in [EMPLOYMENT_RE.search(row_text[x])] if m] if p.report_id == "QUEEN_OF_THE_WEST" else []
        lines.append("- " + " — ".join(cells) + (f" — period of employment: {period[0]}" if period else ""))
    header_rows = rows_df[(rows_df["report_id"] == rid) & (rows_df["body_role"] == "table_header")]["row_id"].tolist()
    add_unit(rid, "persons", PERSONS_TITLE + ":\n" + "\n".join(lines), [x for ids in g["row_ids"] for x in ids] + header_rows,
             "Investigating Officer's Report > Deceased, Missing, and Injured Persons", None, part="io_report", section=3)
for r in rows_df[rows_df["body_role"] == "persons_statement"].itertuples():
    add_unit(r.report_id, "persons", PERSONS_TITLE + ": " + r.text.strip(), [r.row_id],
             "Investigating Officer's Report > Deceased, Missing, and Injured Persons", None, part="io_report", section=3)
for rid, g in persons_none_rows.groupby("report_id"):
    header_rows = rows_df[(rows_df["report_id"] == rid) & (rows_df["body_role"] == "table_header")]["row_id"].tolist()
    cells = " | ".join(str(x) for x in g[["relationship", "sex", "age", "status"]].iloc[0])
    add_unit(rid, "persons", PERSONS_TITLE + f": none — the table prints one row: None | {cells}.",
             [x for ids in g["row_ids"] for x in ids] + header_rows,
             "Investigating Officer's Report > Deceased, Missing, and Injured Persons", None, part="io_report", section=3)

# (d) figures: no units — raster captions stay metadata in the extracted file (see above)

# (e) glossaries
for rid, g in glossary_df.groupby("report_id"):
    heads = rows_df[(rows_df["report_id"] == rid) & (rows_df["body_role"] == "glossary")
                    & rows_df["text"].str.strip().isin(["Acronym Title", "List of Acronyms"])]["row_id"].tolist()
    part = "list_of_acronyms" if rid == "CONCHRD" else "io_report"
    add_unit(rid, "glossary", "List of acronyms:\n" + "\n".join(f"{a.acronym} — {a.meaning}" for a in g.itertuples()),
             [x for ids in g["row_ids"] for x in ids] + heads, "List of acronyms", None, part=part)

# (f) the informative note printed on a heading -> own unit
for n in note_refs_df[note_refs_df["anchor"] == "heading"].itertuples():
    note = notes_df[(notes_df["report_id"] == n.report_id) & (notes_df["note_no"] == n.note_no)].iloc[0]
    head = rows_df.set_index("row_id").loc[n.row_id]
    ctx = type("P", (), {"part": head.part, "sub_part": head.sub_part, "section": head.section, "kind": "note",
                         "number": None, "owner_number": None, "is_subheading": False, "report_id": n.report_id})
    parent, _ = section_path(ctx)
    add_unit(n.report_id, "note", f"Note to \"{head.text.strip()}\": {note.text}", note.row_ids, parent, None,
             part=head.part, section=head.section, note_no=int(n.note_no))

units_df = pd.DataFrame(unit_records)
units_df["unit_no"] = units_df.groupby("report_id").cumcount() + 1
units_df["unit_id"] = units_df["report_id"] + ":u" + units_df["unit_no"].map("{:04d}".format)

# (g) notes: informative -> appended to the citing paragraph unit; citation-only -> `citations`; redacted -> counted
unit_of_row = {x: u.unit_id for u in units_df.itertuples() for x in u.row_ids}
units_df["citations"] = [[] for _ in range(len(units_df))]
units_df["redacted_notes"] = 0
ux = pd.Series(units_df.index, index=units_df["unit_id"])
for n in note_refs_df[note_refs_df["anchor"] == "paragraph"].itertuples():
    note = notes_df[(notes_df["report_id"] == n.report_id) & (notes_df["note_no"] == n.note_no)].iloc[0]
    i = ux[unit_of_row[n.row_id]]
    if note.policy == "informative":
        units_df.at[i, "content"] += f"\nNote: {note.text}"
    elif note.policy == "citation_only":
        units_df.at[i, "citations"] = units_df.at[i, "citations"] + [note.text]
    else:
        units_df.at[i, "redacted_notes"] += 1
print("Units:", len(units_df), units_df["unit_type"].value_counts().to_dict())
display(units_df[["unit_id", "unit_type", "parent_chunk", "content"]].head(3))

# %% cell 57
# =========================================================
# 9.2 Errata (ADR-022) and recorded numbering slips
# =========================================================
UNIT_ERRATA = [{"report_id": "KIM_LY", "part": "executive_summary", "excluded": "On 19 February 2024, ",
                "evidence": "casualty titles (cover p.1, action p.4) and 4.1.1 date the casualty 20 February 2024; the "
                            "incident date of the report is 2024-02-20 (Phase 4)"}]
errata_records = []
for e in UNIT_ERRATA:
    hit = units_df[(units_df["report_id"] == e["report_id"]) & (units_df["part"] == e["part"])
                   & units_df["content"].str.contains(e["excluded"], regex=False)]
    assert len(hit) == 1 and hit["content"].iloc[0].count(e["excluded"]) == 1, e
    i = hit.index[0]
    units_df.at[i, "content"] = units_df.at[i, "content"].replace(e["excluded"], "", 1)
    units_df.at[i, "content"] = units_df.at[i, "content"][:1].upper() + units_df.at[i, "content"][1:]
    errata_records.append({**e, "unit_id": units_df.at[i, "unit_id"], "kind": "clause_excluded"})
for (rid, sec), printed in NUMBERING_SLIPS.items():
    errata_records.append({"report_id": rid, "part": "io_report", "excluded": None, "kind": "numbering_slip_kept",
                           "evidence": f"section {sec} ({CANONICAL_SECTIONS[sec]}) printed as \"{printed}\"; canonical "
                                       f"section used for the path, text kept as printed", "unit_id": None})
for rid, num in sorted(REVIEWED_NUMBERING):
    errata_records.append({"report_id": rid, "part": "io_report", "excluded": None, "kind": "paragraph_numbering_kept",
                           "evidence": f"paragraph number {num} breaks the printed sequence (7.2); kept as printed",
                           "unit_id": None})
errata_df = pd.DataFrame(errata_records)
print("Errata / recorded slips:", errata_df["kind"].value_counts().to_dict())

# %% cell 58
# =========================================================
# 9.3 Access (ADR-021) and personal data (plan §4.6)
# =========================================================
units_df["department"], units_df["sensitivity_level"] = DEPARTMENT, LEVEL
MONEY_RE = re.compile(r"\$\s?\d|\bdollars?\b|\bcosts?\b|\bcostly\b|\bfinanc|\bprices?\b|\bfined?\b|\bfines\b|\bpenalt|"
                      r"\binsur|\bclaims?\b|\bbudget|\brevenue|\bprofit", re.I)
access_candidates = units_df[units_df["content"].map(lambda t: bool(MONEY_RE.search(t)))]
# reviewed 2026-09-26: the candidates are damage estimates, civil-penalty findings, costs of safety measures and
# insurance/claims facts printed in a public federal report — none is NileGate's own financial data -> level 1 / Operations
ACCESS_REASON = "public_federal_report_fact (rbac_mapping §4)"
access_decisions_df = access_candidates[["unit_id"]].assign(level=LEVEL, department=DEPARTMENT, reason=ACCESS_REASON)
assert access_decisions_df["unit_id"].tolist() == access_candidates["unit_id"].tolist()

# personal names never in curated text: the signers (excluded rows) and the individual parties of the vessel tables
signer_names = {t.strip() for t in rows_df.loc[rows_df["role"] == "signature", "text"] if NAME_ONLY_RE.match(t.strip())}
party_values = {vessel_fields_df.loc[(vessel_fields_df["report_id"] == rid) & (vessel_fields_df["field"] == f), "value"].iloc[0]
                for rid, f in INDIVIDUAL_PARTIES}
party_names = {" ".join(v.split()[:2]) for v in party_values if v.strip()}
curated = units_df[units_df["unit_type"].isin(["vessel_block", "persons", "glossary"])]["content"].tolist() \
    + units_df["parent_chunk"].tolist() + units_df["sub_chunk"].dropna().tolist() + paragraphs_df["header"].tolist()
leaks = sorted({n for n in signer_names | party_names for t in curated if n in t})
assert not leaks, leaks
HONORIFIC_RE = re.compile(r"\b(?:Mr|Mrs|Ms)\.\s[A-Z][a-z]+")
honorific_mentions = units_df["content"].map(lambda t: len(HONORIFIC_RE.findall(t))).sum()
print("Access candidates:", len(access_candidates), "-> all level 1 / Operations (reviewed) | curated-text name leaks: 0 |",
      "signer names excluded:", len(signer_names), "| individual parties by role:", len(INDIVIDUAL_PARTIES),
      "| honorific names in report text (kept as published):", int(honorific_mentions))

# %% cell 59
# =========================================================
# 9.4 Phase 9 validation
# =========================================================
assert units_df["unit_id"].is_unique and units_df["content"].str.strip().str.len().gt(0).all()
unit_rows = [x for ids in units_df["row_ids"] for x in ids]
assert len(unit_rows) == len(set(unit_rows)), "A row feeds one unit."
expected_rows = set(rows_df.loc[rows_df["body_role"].isin(["paragraph", "structured_table", "persons_statement",
                                                           "glossary", "table_header"]), "row_id"]) \
    | {x for n in note_refs_df[note_refs_df["anchor"] == "heading"].itertuples()
       for x in notes_df[(notes_df["report_id"] == n.report_id) & (notes_df["note_no"] == n.note_no)]["row_ids"].iloc[0]}
missing = expected_rows - set(unit_rows)
# reviewed: QUEEN_OF_THE_WEST's vessel-block title is metadata (the block unit has its own title)
assert {rows_df.set_index("row_id").at[x, "text"].strip() for x in missing} <= {"PASSENGER VESSEL QUEEN OF THE WEST"}, missing
assert not (units_df["unit_type"] == "figure").any(), "Captions are metadata, not units." 
assert (units_df["sensitivity_level"] == 1).all() and (units_df["department"] == "Operations").all()
inf = notes_df[notes_df["policy"] == "informative"]
assert units_df["content"].str.count("\nNote: ").sum() == len(inf) - 1, "Informative notes appended (WAYMON 9 is a unit)."
assert units_df["citations"].map(len).sum() == (notes_df["policy"] == "citation_only").sum()
assert units_df["redacted_notes"].sum() == (notes_df["policy"] == "redacted").sum()
REVIEWED_PHASE9 = {"units": {"paragraph": 2946, "vessel_block": 27, "persons": 22, "glossary": 2, "note": 1},
                   "errata": {"paragraph_numbering_kept": 8, "numbering_slip_kept": 3, "clause_excluded": 1},
                   "access_candidates": 60, "honorific_mentions": 78}
actual = {"units": units_df["unit_type"].value_counts().to_dict(), "errata": errata_df["kind"].value_counts().to_dict(),
          "access_candidates": len(access_candidates), "honorific_mentions": int(honorific_mentions)}
assert actual == REVIEWED_PHASE9, {k: v for k, v in actual.items() if v != REVIEWED_PHASE9[k]}
print("✅ Phase 9 validation passed.")
print("Phase 9:", len(units_df), "units |", len(errata_df), "errata / recorded slips |", len(access_candidates),
      "access candidates reviewed")

# %% [markdown] cell 60
# # Phases 10–12 — Deduplication (ADR-010, ADR-019)
#
# Dedup happens on the units, before chunking:
#
# - **10 — within a report: the Executive Summary is non-canonical** (plan §4.4, the HbR policy of ADR-019). Each of
#   its sentences is compared with the sentences of the same report's Investigating Officer's Report: a sentence is
#   **covered** when ≥ 85 % of its content words are in one report sentence and every number it prints is printed
#   there too. Covered sentences are trimmed (recorded with the covering unit), new ones are kept; a summary
#   paragraph left with nothing is dropped (recorded).
#   The letters restate the recommendations they act on (the Commandant's action, the endorsements). Those restatements
#   are **kept**: each letter is its own decision document, and the recommendation beside its action / endorsement is
#   what makes that unit answerable (plan §3, Phase 14 candidate "recommendations with the Commandant's action"). They
#   are measured and recorded in the duplicate audit.
# - **11 — across reports:** template boilerplate ("The record and the report of the investigation … have been
#   reviewed.") is kept inside each report's units (plan §4.5), never made a standalone unit; the repeated sentences are
#   counted in the audit.
# - **12 — across sources:** every unit sentence is compared with the 619 chunks of the other sources (same test);
#   a covered sentence would be removed under the canonical-source policy (the earlier source is canonical).

# %% cell 61
# =========================================================
# 10.1 Sentences and the coverage test
# =========================================================
ABBREV = {"u.s", "a.m", "p.m", "mr", "mrs", "ms", "dr", "no", "st", "ste", "mt", "ft", "inc", "co", "ltd", "vs", "e.g", "i.e",
          "approx", "vol", "pg", "o.n", "jr", "sr", "lt", "cdr", "capt", "cwo", "gen", "adm", "fig", "sec", "ref", "encl",
          "u.s.c", "c.f.r", "etc"}
STOP_WORDS = set("the a an and or of to in on at for with by from was were is are be been as that this it its his her "
                 "their he she they them which who whom than then there these those into onto over under after before "
                 "during while not no any all also has had have would could should may might did do does".split())


def sentences(text: str) -> list[str]:
    """Split on sentence ends, not after abbreviations or initials ("U.S. Coast", "O.N. 588734", "Sault Ste. Marie")."""
    out, start = [], 0
    for m in re.finditer(r"[.!?][”\")]?\s+(?=[A-Z“\"(0-9])", text):
        tok = re.findall(r"(\S+)$", text[start:m.start()])
        last = tok[0].lower().lstrip("(“\"").rstrip(".") if tok else ""
        if last in ABBREV or re.fullmatch(r"[a-z]", last) or re.fullmatch(r"(?:[a-z]\.)+[a-z]", last):
            continue
        out.append(text[start:m.end()].strip()); start = m.end()
    if text[start:].strip():
        out.append(text[start:].strip())
    return out


def content_words(s: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) >= 3 and w not in STOP_WORDS]


def numbers_in(s: str) -> set[str]:
    return set(re.findall(r"\d+(?:[.,:]\d+)*", s))


def is_covered(s: str, b: str) -> bool:
    cw = content_words(s)
    if not cw:
        return False
    bw = set(content_words(b))
    return sum(w in bw for w in cw) / len(cw) >= 0.85 and numbers_in(s) <= numbers_in(b)


class SentenceIndex:
    """Candidate retrieval by shared word 3-grams, then the coverage test on the best five candidates."""
    def __init__(self, items):                      # items: [(owner_id, sentence)]
        self.items, self.idx = items, {}
        for i, (_, s) in enumerate(items):
            for g in self.grams(s):
                self.idx.setdefault(g, set()).add(i)

    @staticmethod
    def grams(s: str) -> set[str]:
        w = re.findall(r"[a-z0-9]+", s.lower())
        return {" ".join(w[i:i + 3]) for i in range(max(len(w) - 2, 1))} if w else set()

    def cover(self, s: str):
        cand = Counter(i for g in self.grams(s) for i in self.idx.get(g, ()))
        for i, _ in cand.most_common(5):
            if is_covered(s, self.items[i][1]):
                return self.items[i][0]
        return None


assert sentences("The U.S. Coast Guard (O.N. 588734) arrived. It left at 2 p.m. Then it sank.") == \
    ["The U.S. Coast Guard (O.N. 588734) arrived.", "It left at 2 p.m. Then it sank."]
print("Sentence tools ready.")

# %% cell 62
# =========================================================
# 10.2 Within a report: Executive Summary (non-canonical) trimmed against the report
# =========================================================
dup_records = []
exec_units = units_df[units_df["part"] == "executive_summary"]
for rid, g in exec_units.groupby("report_id"):
    body = units_df[(units_df["report_id"] == rid) & (units_df["part"] == "io_report")
                    & units_df["unit_type"].isin(["paragraph", "persons", "vessel_block"])]
    index = SentenceIndex([(u.unit_id, s) for u in body.itertuples() for s in sentences(u.content)])
    for u in g.itertuples():
        kept = []
        for s in sentences(u.content):
            by = index.cover(s)
            if by:
                dup_records.append({"scope": "within_report", "unit_id": u.unit_id, "report_id": rid, "sentence": s,
                                    "covered_by": by, "action": "trimmed"})
            else:
                kept.append(s)
        new = " ".join(kept)
        if new != u.content:
            units_df.at[u.Index, "content"] = new
exec_dropped = units_df[(units_df["part"] == "executive_summary") & (units_df["content"].str.strip() == "")]["unit_id"].tolist()
for uid in exec_dropped:
    dup_records.append({"scope": "within_report", "unit_id": uid, "report_id": uid.split(":")[0], "sentence": None,
                        "covered_by": None, "action": "unit_dropped_all_sentences_covered"})
units_df = units_df[~units_df["unit_id"].isin(exec_dropped)].reset_index(drop=True)
# restated recommendations in the letters: measured, kept (see above)
restated = 0
for rid, g in units_df[units_df["sub_part"].isin(["action_on_recommendations", "endorsement_on_recommendations"])].groupby("report_id"):
    body = units_df[(units_df["report_id"] == rid) & (units_df["part"] == "io_report") & (units_df["unit_type"] == "paragraph")]
    index = SentenceIndex([(u.unit_id, s) for u in body.itertuples() for s in sentences(u.content)])
    for u in g.itertuples():
        for s in sentences(u.content):
            if (by := index.cover(s)):
                restated += 1
                dup_records.append({"scope": "within_report", "unit_id": u.unit_id, "report_id": rid, "sentence": s,
                                    "covered_by": by, "action": "kept_restated_in_letter"})
n_trim = sum(r["action"] == "trimmed" for r in dup_records)
print("Executive Summary:", len(exec_units), "units |", n_trim, "covered sentences trimmed |", len(exec_dropped),
      "units dropped | letters: restated sentences kept:", restated)

# %% cell 63
# =========================================================
# 11–12 Across reports (boilerplate kept) and across sources (canonical-source policy)
# =========================================================
sent_reports = {}
for u in units_df[units_df["unit_type"] == "paragraph"].itertuples():
    for s in sentences(u.content):
        key = " ".join(content_words(s))
        if len(key) > 30:
            sent_reports.setdefault(key, set()).add(u.report_id)
boilerplate = {k: v for k, v in sent_reports.items() if len(v) >= 3}
for k, v in boilerplate.items():
    dup_records.append({"scope": "across_reports", "unit_id": None, "report_id": ",".join(sorted(v)), "sentence": k,
                        "covered_by": None, "action": "kept_in_context_boilerplate"})
OTHER_CHUNK_FILES = sorted(p for p in (PROCESSED_RAG_DIR / "chunks").glob("*_chunks.parquet") if not p.name.startswith("USCG"))
other_chunks = pd.concat([pd.read_parquet(p) for p in OTHER_CHUNK_FILES], ignore_index=True)
other_index = SentenceIndex([(c.chunk_id, s) for c in other_chunks.itertuples() for s in sentences(c.text)])
cross = []
for u in units_df.itertuples():
    for s in sentences(u.content):
        if len(content_words(s)) >= 6 and (by := other_index.cover(s)):
            cross.append({"scope": "across_sources", "unit_id": u.unit_id, "report_id": u.report_id, "sentence": s,
                          "covered_by": by, "action": "review"})
duplicate_audit_df = pd.DataFrame(dup_records + cross)
print("Across reports: boilerplate sentences kept in context:", len(boilerplate), "| across sources:", len(other_chunks),
      "chunks in", len(OTHER_CHUNK_FILES), "files -> covered unit sentences:", len(cross))
display(duplicate_audit_df.groupby(["scope", "action"]).size())

# %% cell 64
# =========================================================
# 12.1 Phases 10–12 validation
# =========================================================
assert len(other_chunks) == 619, len(other_chunks)
assert not cross, pd.DataFrame(cross).head()          # no USCG sentence is already in the corpus
assert units_df["content"].str.strip().str.len().gt(0).all()
es = units_df[units_df["part"] == "executive_summary"]
assert all(not SentenceIndex([(0, s) for u in units_df[(units_df["report_id"] == r.report_id) & (units_df["part"] == "io_report")
                                                        ].itertuples() for s in sentences(u.content)]).cover(s)
           for r in es.itertuples() for s in sentences(r.content)), "No covered sentence is left in a summary."
REVIEWED_PHASE10_12 = {"trimmed": 49, "dropped": 2, "restated_kept": 390, "boilerplate": 39, "units": 2996}
# reviewed: the two dropped summary units are CUYAHOGA's drydock sentence and its firefighting-water sentences (4.1.x)
actual = {"trimmed": n_trim, "dropped": len(exec_dropped), "restated_kept": restated, "boilerplate": len(boilerplate),
          "units": len(units_df)}
assert actual == REVIEWED_PHASE10_12, actual
print("✅ Phases 10–12 validation passed.")
print("Phases 10–12:", n_trim, "summary sentences trimmed |", len(exec_dropped), "summary units dropped |",
      len(boilerplate), "boilerplate sentences kept in context | 0 cross-source duplicates |", len(units_df), "units")

# %% [markdown] cell 65
# # Phase 12b — IMO incident profiles (plan §4.3, ADR-023)
#
# One **incident profile per report**, coded with the field catalogue of the IMO circular MSC-MEPC.3/Circ.4/Rev.1
# (read from the IMO notebook's extracted file, key `field_catalogue`). Rule (ADR-020): **only values printed in the
# report**, each with its evidence:
#
# | Kind | Fields | Evidence |
# |---|---|---|
# | printed value | 1.2.2 date; per ship 2.1.2 name, 2.1.5 flag, 2.1.6 type (as printed), 2.1.7 gross tonnage, 2.1.8 length, 2.1.10 owner, 2.1.12 year of build, 2.1.14 hull material, 2.1.16 propulsion | the table / title rows it was read from (traced to the line in Phase 20) |
# | count of printed rows | 1.1.2 number of ships involved; 2.4.1–2.4.3 dead or missing crew / passengers / others | the vessel blocks and the persons table (4.3–4.4) |
# | reviewed code | 1.2.6 location (table 3), 1.2.7 overall casualty event (table 4), 1.2.8 severity (table 5) | one report sentence (unit id + sentence number) |
#
# Deliberately **not** coded: "seriously injured" (2.4.4–2.4.6 — the reports print "Injured" without saying serious;
# the printed count is kept as `injured_as_printed`), and a location the text does not establish (GOOD_GULF) — left
# empty with its reason rather than guessed. Severity follows the circular's categories: loss of life or total loss
# of the ship → very serious marine casualty; otherwise marine casualty (each with its evidence sentence).
# Individual owners stay roles (plan §4.6). The profile becomes one curated chunk per report (Phase 14), and the whole
# profile with its evidence goes to the extracted file (Phase 13).

# %% cell 66
# =========================================================
# 12b.1 Field catalogue and reviewed codes
# =========================================================
IMO_EXTRACTED = PROCESSED_RAG_DIR / "extracted" / "IMO_MSC-MEPC_3_Circ_4_Rev_1_extracted.json"
catalogue = json.loads(IMO_EXTRACTED.read_text(encoding="utf-8"))["field_catalogue"]
FIELD = {f["field_id"]: f["description"] for f in catalogue["fields"]}
OPTION = {(t["table_no"], o["code"]): o["label"] for t in catalogue["option_tables"] for o in t["options"]}
# reviewed per report: (code, evidence substring of one report sentence); None = not determinable from the text
REVIEWED_CODES = {
    "BIG_STICK": {"1.2.6": (".11", "intended to fish at an unspecified location"), "1.2.7": (".29", "the operator going overboard")},
    "CAROL_ANN": {"1.2.6": (".10", "approximately 80 nautical miles offshore"), "1.2.7": (".20", "the F/V CAROL ANN lost stability")},
    "CONCHRD": {"1.2.6": (".10", "approximately 15 miles off the coast of Cape May"),
                "1.2.7": (".17", "overloading/improper loading of the vessel with conch pots")},
    "CUMBERLAND_II": {"1.2.6": (".7", "mile marker 104 of the Cumberland River"),
                      "1.2.7": (".33", "breaking through the set of closed gates")},
    "CUYAHOGA": {"1.2.6": (".1", "berthed at Kinder Morgan Pinney Dock"), "1.2.7": (".9", "a fire ignited on the forward bulkhead")},
    "GENERAL_MACARTHUR": {"1.2.6": (".1", "dry-docked in Amelia, Louisiana"),
                          "1.2.7": (".32", "put his body into the pump impeller opening")},
    "GOOD_GULF": {"1.2.6": None, "1.2.7": (".29", "or if he fell overboard")},
    "H20_BELOW": {"1.2.6": (".10", "The vessel was 21 nautical miles offshore"), "1.2.7": (".33", "was the death of Passenger 1")},
    "KIM_LY": {"1.2.6": (".5", "underway shrimping in Corpus Christi Bay"), "1.2.7": (".32", "becoming entangled in the winch")},
    "LA6893ER": {"1.2.6": (".5", "last known location was in Lake Chien"), "1.2.7": (".29", "the master fell overboard from the LA6893ER")},
    "LADY_ELLEN": {"1.2.6": (".5", "near Mud Rock in Tangier Sound"), "1.2.7": (".29", "when the Crewmember fell into the water")},
    "LITTLE_G": {"1.2.6": (".7", "multi-day transit on the Alabama River"), "1.2.7": (".19", "was flooding over the stern of the LITTLE G")},
    "MERRICK": {"1.2.6": (".5", "out of the Housatonic River into Long Island Sound"),
                "1.2.7": (".19", "began taking on water undetected")},
    "MICHIPICOTEN": {"1.2.6": (".5", "on western Lake Superior"), "1.2.7": (".11", "structural failure of the exterior hull plating")},
    "NC3250BW": {"1.2.6": (".5", "for fishing operations in Cedar Island Bay"), "1.2.7": (".29", "the operator of NC3250BW falling overboard")},
    "PROWLER_ATTESSA_IV": {"1.2.6": (".9", "nine miles southwest of Imperial Beach"),
                           "1.2.7": (".3", "was the collision between the PROWLER and ATTESSA IV")},
    "QUEEN_OF_THE_WEST": {"1.2.6": (".1", "moored at the marina in Rainier"), "1.2.7": (".29", "fall overboard from the port paddlewheel")},
    "SPIRIT_OF_BOSTON": {"1.2.6": (".1", "docked at its regular berth"), "1.2.7": (".9", "Once aware of the fire in the wait station area")},
    "TOO_SHORT": {"1.2.6": (".5", "arrived at Whitehall Bay and anchored"), "1.2.7": (".33", "when Passenger 1 drowned")},
    "UNA_MAS": {"1.2.6": (".9", "approximately 04 nautical miles offshore of Gold Beach"), "1.2.7": (".17", "capsized during adverse weather conditions")},
    "VICAR_602": {"1.2.6": (".7", "Middle Branch of the Patapsco River"), "1.2.7": (".3", "collided with the rowing scull")},
    "WAYMON_BOYD": {"1.2.6": (".3", "located in the Corpus Christi Ship Channel"), "1.2.7": (".10", "resulting in a rapid and fatal explosion")},
    "WILDERNESS_I": {"1.2.6": (".5", "arrived at Bayou Segnette Landing pier"), "1.2.7": (".6", "first allision of the Wilderness I with branches")},
}
TOTAL_LOSS_EVIDENCE = {"CUYAHOGA": "the vessel was deemed a constructive total loss"}
NON_FATAL_EVIDENCE = {"MICHIPICOTEN": "structural failure of the exterior hull plating",
                      "SPIRIT_OF_BOSTON": "approximately $3.1 million", "VICAR_602": "collided with the rowing scull"}
assert set(REVIEWED_CODES) == set(REPORT_IDS)
report_sentences = {}
for u in units_df.itertuples():
    for k, s in enumerate(sentences(u.content)):
        report_sentences.setdefault(u.report_id, []).append((u.part, f"{u.unit_id}#s{k + 1}", s))


def evidence_of(rid: str, needle: str) -> dict:
    """The first report sentence (Investigating Officer's Report first) that prints the evidence text."""
    hits = [x for x in report_sentences[rid] if needle.lower() in x[2].lower()]
    hits.sort(key=lambda x: x[0] != "io_report")
    assert hits, (rid, needle)
    return {"sentence_id": hits[0][1], "sentence": hits[0][2]}


print("IMO catalogue:", len(FIELD), "fields,", len(catalogue["option_tables"]), "option tables | reviewed reports:", len(REVIEWED_CODES))

# %% cell 67
# =========================================================
# 12b.2 Profiles
# =========================================================
SHIP_FIELDS = {"name": "2.1.2", "flag": "2.1.5", "vessel_class": "2.1.6", "gross_tonnage": "2.1.7", "length": "2.1.8",
               "owner": "2.1.10", "owner_operator": "2.1.10", "build_year": "2.1.12", "hull": "2.1.14", "propulsion": "2.1.16"}
first_title_row = rows_df[rows_df["role"] == "casualty_title"].sort_values(["page_number", "y0"]).groupby("report_id")["row_id"].first()
profiles, profile_values = {}, []
for rid in REPORT_IDS:
    vals = []

    def put(field_id, value, basis, evidence, **kw):
        vals.append({"field_id": field_id, "field": FIELD[field_id], "value": value, "basis": basis, "evidence": evidence, **kw})

    put("1.2.2", str(pd.Timestamp(meta_of.at[rid, "incident_date"]).date()), "printed",
        {"row_ids": [first_title_row[rid]], "printed": "casualty title (Phase 4 incident date)"})
    ships = vessel_fields_df[(vessel_fields_df["report_id"] == rid) & (vessel_fields_df["block_kind"] == "vessel")]
    put("1.1.2", int(ships["block_no"].nunique()), "count", {"vessel_blocks": sorted(ships["block_no"].unique().tolist())})
    for (b,), g in ships.groupby(["block_no"]):
        ship = g.loc[g["field"] == "name", "value"].iloc[0].strip()
        for f in g.itertuples():
            if f.field in SHIP_FIELDS and f.value.strip():
                value = PARTY_ROLE[f.field] if (rid, f.field) in INDIVIDUAL_PARTIES else f.value.strip()
                put(SHIP_FIELDS[f.field], value, "printed_role" if value != f.value.strip() else "printed",
                    {"row_ids": f.row_ids, "printed": f.label_printed.strip()}, ship=ship, source_field=f.field)
    pers = persons_df[persons_df["report_id"] == rid].copy()
    # reviewed: CUMBERLAND_II's table is "Relationship to Motor Vehicle" — the car's owner/operator is not ship's crew
    pers.loc[(pers["report_id"] == "CUMBERLAND_II") & (pers["relationship"].str.strip() == "Owner/Operator"), "person_class"] = "other"
    for fid, cls in (("2.4.1", "crew"), ("2.4.2", "passenger"), ("2.4.3", "other")):
        n = int(((pers["person_class"] == cls) & (pers["outcome"] == "dead_or_missing")).sum())
        put(fid, n, "count", {"persons_rows": [x for ids in pers["row_ids"] for x in ids]})
    injured = int((pers["outcome"] == "injured").sum())
    vals.append({"field_id": None, "field": "injured_as_printed (seriousness not stated; not coded to 2.4.4–2.4.6)",
                 "value": injured, "basis": "count", "evidence": {"persons_rows": [x for ids in pers["row_ids"] for x in ids]}})
    for fid, table in (("1.2.6", 3), ("1.2.7", 4)):
        rc = REVIEWED_CODES[rid][fid]
        if rc is None:
            put(fid, None, "not_determinable", {"reason": "the report does not print where the casualty happened precisely enough"})
        else:
            code, needle = rc
            put(fid, OPTION[(table, code)], "reviewed_code", evidence_of(rid, needle), table_no=table, code=code)
    dead = int((pers["outcome"] == "dead_or_missing").sum())
    if dead or rid in TOTAL_LOSS_EVIDENCE:
        ev = evidence_of(rid, TOTAL_LOSS_EVIDENCE[rid]) if rid in TOTAL_LOSS_EVIDENCE else \
            {"persons_rows": [x for ids in pers["row_ids"] for x in ids], "dead_or_missing": dead}
        put("1.2.8", OPTION[(5, ".1")], "reviewed_code", ev, table_no=5, code=".1")
    else:
        put("1.2.8", OPTION[(5, ".2")], "reviewed_code", evidence_of(rid, NON_FATAL_EVIDENCE[rid]), table_no=5, code=".2")
    profiles[rid] = vals
    profile_values += [{"report_id": rid, **v} for v in vals]
profile_df = pd.DataFrame(profile_values)


def profile_text(rid: str) -> str:
    m = meta_of.loc[rid]
    lines = [f"Incident profile (IMO casualty-reporting fields, MSC-MEPC.3/Circ.4/Rev.1) — values as printed in the report:"]
    for v in profiles[rid]:
        if v["value"] is None:
            continue
        where = f" [{v['ship']}]" if v.get("ship") else ""
        code = f" ({v['code']})" if v.get("code") else ""
        label = f"{v['field_id']} {v['field']}" if v["field_id"] else v["field"].split(" (")[0]
        lines.append(f"- {label}{where}: {v['value']}{code}")
    return "\n".join(lines)


for rid in REPORT_IDS:
    add_unit(rid, "incident_profile", profile_text(rid), [], "Incident profile", None, part="profile")
units_df = pd.concat([units_df, pd.DataFrame(unit_records[-len(REPORT_IDS):])], ignore_index=True)
prof = units_df["unit_type"] == "incident_profile"
units_df.loc[prof, "unit_id"] = units_df.loc[prof, "report_id"] + ":profile"
units_df.loc[prof, "department"], units_df.loc[prof, "sensitivity_level"] = DEPARTMENT, LEVEL
units_df["citations"] = units_df["citations"].map(lambda x: x if isinstance(x, list) else [])
units_df["redacted_notes"] = units_df["redacted_notes"].fillna(0).astype(int)
print("Profiles:", len(profiles), "| values:", len(profile_df), profile_df["basis"].value_counts().to_dict())
print(profile_text("KIM_LY")[:600])

# %% cell 68
# =========================================================
# 12b.3 Phase 12b validation (the full trace of every value is Phase 20)
# =========================================================
assert set(profiles) == set(REPORT_IDS) and units_df["unit_id"].is_unique
codes = profile_df[profile_df["basis"] == "reviewed_code"]
assert all((t, c) in OPTION for t, c in zip(codes["table_no"], codes["code"])), "Every code exists in the catalogue."
assert profile_df["field_id"].dropna().isin(FIELD).all()
assert (profile_df.groupby("report_id")["field_id"].apply(lambda s: {"1.2.2", "1.2.7", "1.2.8"} <= set(s))).all()
names_in_profiles = [n for n in signer_names | party_names if units_df.loc[prof, "content"].str.contains(n, regex=False).any()]
assert not names_in_profiles, names_in_profiles
REVIEWED_PHASE12B = {"values": 407, "basis": {"printed": 219, "count": 115, "reviewed_code": 68, "printed_role": 4,
                                                "not_determinable": 1},
                     "severity": {"Very serious marine casualty": 20, "Marine casualty": 3}, "events": 11,
                     "dead_or_missing": {"2.4.1": 20, "2.4.2": 3, "2.4.3": 3}}
actual = {"values": len(profile_df), "basis": profile_df["basis"].value_counts().to_dict(),
          "severity": profile_df.loc[profile_df["field_id"] == "1.2.8", "value"].value_counts().to_dict(),
          "events": profile_df.loc[profile_df["field_id"] == "1.2.7", "value"].nunique(),
          "dead_or_missing": profile_df[profile_df["field_id"].isin(["2.4.1", "2.4.2", "2.4.3"])].groupby("field_id")["value"].sum().to_dict()}
assert actual == REVIEWED_PHASE12B, actual
print("✅ Phase 12b validation passed.")
print("Phase 12b:", len(profiles), "incident profiles |", len(profile_df), "values |", len(codes), "reviewed codes")

# %% [markdown] cell 69
# # Phase 13 — Save extracted + cleaned artifacts
#
# One file per layer (plan §3):
# - `extracted/USCG_ROI_extracted.json` — the raw structured layer **per report**: file, SHA-256, MISLE number, vessel
#   label, incident and version dates, page classes and OCR use, document parts and printed section titles, vessel /
#   vehicle fields (individual owners by role), persons (roles only), figures with their gate, enclosures, TOC,
#   notes with policies, glossary, numbering exceptions, and the **incident profile with its evidence**; plus the
#   corpus-level superscript dispositions, Phase 4 role corrections, errata and access decisions.
# - `cleaned/USCG_ROI_logical_units.json` — **the single cleaned file** `{source, units, duplicate_audit}`; Phase 19
#   adds `coverage_audit`.
#
# Both are reloaded from disk and re-validated.

# %% cell 70
# =========================================================
# 13.1 Write
# =========================================================
EXTRACTED_PATH = EXTRACTED_DIR / f"{SOURCE_NAME}_extracted.json"
CLEANED_PATH = CLEANED_DIR / f"{SOURCE_NAME}_logical_units.json"


def records(df: pd.DataFrame) -> list[dict]:
    return json.loads(df.to_json(orient="records", date_format="iso", force_ascii=False))


def day(x) -> str:
    return str(pd.Timestamp(x).date())


vf_safe = vessel_fields_df.copy()
for rid, f in INDIVIDUAL_PARTIES:
    vf_safe.loc[(vf_safe["report_id"] == rid) & (vf_safe["field"] == f) & (vf_safe["value"].str.strip() != ""), "value"] = PARTY_ROLE[f]
report_layers = []
for rid in REPORT_IDS:
    sel = lambda df: df[df["report_id"] == rid].drop(columns=["report_id"])
    pg = pages_df[pages_df["report_id"] == rid]
    report_layers.append({
        "report_id": rid, "filename": FILE_OF[rid], "sha256": SHA_OF[rid], "misle": str(meta_of.at[rid, "misle"]),
        "vessel_label": meta_of.at[rid, "vessel_label"], "incident_date": day(meta_of.at[rid, "incident_date"]),
        "version_date": day(meta_of.at[rid, "version_date"]), "pages": int(len(pg)),
        "page_classes": pg["text_class"].value_counts().to_dict(), "text_sources": pg["text_source"].value_counts().to_dict(),
        "parts": records(sel(parts_df)), "sections": records(sel(sections_df)),
        "vessel_fields": records(sel(vf_safe)),
        "persons": records(sel(persons_df)[["table_no", "relationship", "sex", "age", "status", "role_label",
                                              "person_class", "outcome", "page_number"]]),
        "persons_statement": persons_statement.get(rid),
        "figures": records(sel(figures_df)[["figure_id", "kind", "number", "caption", "page_number", "figure_class",
                                            "gate", "gate_reason"]]),
        "enclosures": records(sel(enclosures_df)), "toc": records(sel(toc_df)),
        "notes": records(sel(notes_df)[["note_no", "text", "policy", "page_number"]]),
        "glossary": records(sel(glossary_df)[["acronym", "meaning"]]),
        "numbering_exceptions": records(sel(numbering_issues_df)),
        "incident_profile": profiles[rid]})
extracted = {"source": source_metadata, "reports": report_layers,
             "superscripts": records(superscripts_df.drop(columns=["row_id"])),
             "phase4_role_corrections": role_fixes, "errata": records(errata_df),
             "access_decisions": records(access_decisions_df), "imo_catalogue_file": IMO_EXTRACTED.name}
unit_cols = ["unit_id", "report_id", "unit_type", "part", "sub_part", "section", "parent_chunk", "sub_chunk", "content",
             "page_start", "page_end", "provenance", "row_ids", "citations", "redacted_notes", "department", "sensitivity_level"]
cleaned = {"source": source_metadata, "units": records(units_df[unit_cols]), "duplicate_audit": records(duplicate_audit_df)}
EXTRACTED_PATH.write_text(json.dumps(extracted, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
CLEANED_PATH.write_text(json.dumps(cleaned, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
print("Saved:", EXTRACTED_PATH.name, f"{EXTRACTED_PATH.stat().st_size / 1e6:.1f} MB |", CLEANED_PATH.name,
      f"{CLEANED_PATH.stat().st_size / 1e6:.1f} MB")

# %% cell 71
# =========================================================
# 13.2 Reload and re-validate
# =========================================================
ex = json.loads(EXTRACTED_PATH.read_text(encoding="utf-8"))
cl = json.loads(CLEANED_PATH.read_text(encoding="utf-8"))
assert [r["report_id"] for r in ex["reports"]] == list(REPORT_IDS)
assert all(len(r["incident_profile"]) == len(profiles[r["report_id"]]) for r in ex["reports"])
assert sum(len(r["notes"]) for r in ex["reports"]) == len(notes_df)
assert sum(len(r["figures"]) for r in ex["reports"]) == len(figures_df)
assert not any(v["value"] and any(n in str(v["value"]) for n in party_names) for r in ex["reports"] for v in r["vessel_fields"])
assert set(cl) == {"source", "units", "duplicate_audit"} and len(cl["units"]) == len(units_df)
assert [u["unit_id"] for u in cl["units"]] == units_df["unit_id"].tolist()
assert all(u["content"] == c for u, c in zip(cl["units"], units_df["content"]))
assert len(cl["duplicate_audit"]) == len(duplicate_audit_df)
print("✅ Phase 13 validation passed.")
print("Phase 13:", len(ex["reports"]), "report layers |", len(cl["units"]), "units |", len(cl["duplicate_audit"]), "audit rows")

# %% [markdown] cell 72
# # Phases 14–15 — Chunking and validation
#
# Owner's rule (plan §4.7): **the best split per content, not a fixed rule**. Every chunk stands alone: its first line
# is the header `USCG ROI <vessel> (MISLE <n>, <incident date>) — <section path>`. A chunk never crosses a document
# part, sub-part or report section, never mixes access levels (all level 1 here), and a unit is never cut unless it is
# longer than `MAX_CHUNK_CHARS`.
#
# | Content | One chunk = | Why |
# |---|---|---|
# | vessel / vehicle particulars | one table | a table is answered as a whole ("how long was the BIG STICK?") |
# | persons table / statement | one table | the casualty's human toll in one place |
# | Findings / Analysis / Conclusions / Actions / Recommendations | a **numbered group**: a numbered paragraph with its sub-items (`4.1.3` + `4.1.3.1…`), grouped while short | a finding is understood with its sub-items |
# | Conclusions 6.1 | **Determination of Cause whole** (initiating event + causal factors), split balanced only if too long | the causal chain is one answer |
# | Recommendations with the letters | in "Action / Endorsement on Recommendations": one **recommendation with its action or endorsement** | the decision is meaningless without what it decides on |
# | letters, Executive Summary, Preliminary Statement | paragraphs grouped while short | prose |
# | glossary, incident profile, note on a heading | one chunk each | self-contained |
#
# **Packing.** Inside one section, groups are joined in reading order while the chunk is below `MIN_CHUNK_CHARS` and
# the next group still fits; a last piece below `MIN_CHUNK_CHARS` joins the previous chunk when it fits. A group longer
# than the budget (`MAX_CHUNK_CHARS` minus the header) is split into the **fewest balanced parts** at unit, then
# sentence boundaries. Tables and the profile are never merged with prose. Figure captions are metadata (Phase 9).

# %% cell 73
# =========================================================
# 14.1 Reading order and groups
# =========================================================
rows_pos = rows_df.set_index("row_id")[["page_number", "y0"]]


def position(row_ids) -> tuple:
    if not row_ids:
        return (-1, -1.0)
    p = rows_pos.loc[list(row_ids)]
    first = p.sort_values(["page_number", "y0"]).iloc[0]
    return (int(first.page_number), float(first.y0))


units_df["pos"] = units_df["row_ids"].map(position)
units_df = units_df.sort_values(["report_id", "pos"], kind="stable").reset_index(drop=True)
STANDALONE = {"vessel_block", "persons", "glossary", "incident_profile", "note"}
REC_LABEL_RE = re.compile(r"^(?:(?:Safety|Administrative)\s+)?Recommendation")


def section_key(u) -> tuple:
    return (u.report_id, u.part, u.sub_part if isinstance(u.sub_part, str) else None,
            None if pd.isna(u.section) else int(u.section))


def group_key(u) -> str | None:
    """Numbered group of an io_report paragraph: 6.1.* -> '6.1' (Determination of Cause), else the first 3 levels."""
    num = u.number if isinstance(u.number, str) and u.kind == "numbered" else None
    if num is None:
        return None
    comps = num.split(".")
    if u.part == "io_report" and u.section == 6 and comps[:2] == ["6", "1"]:
        return "6.1"
    return ".".join(comps[:3])


group_records = []
for rid, g in units_df.groupby("report_id", sort=True):
    cur = None
    for u in g.itertuples():
        sk = section_key(u)
        if u.unit_type in STANDALONE:
            group_records.append({"key": sk, "kind": u.unit_type, "units": [u.unit_id], "parent": u.parent_chunk,
                                  "subs": [u.sub_chunk]})
            cur = None
            continue
        rec_start = isinstance(u.sub_part, str) and u.sub_part.endswith("on_recommendations") and u.kind == "label" \
            and bool(REC_LABEL_RE.match(u.content))
        gk = group_key(u) if u.part == "io_report" and (u.section or 0) >= 4 else None
        same = cur is not None and cur["key"] == sk and (
            (cur["kind"] == "recommendation_action" and not rec_start) or
            (cur["kind"] == "numbered_group" and gk is None) or
            (cur["kind"] == "numbered_group" and gk == cur["gk"]))
        if same:
            cur["units"].append(u.unit_id); cur["subs"].append(u.sub_chunk)
            continue
        kind = "recommendation_action" if rec_start else "numbered_group" if gk else "paragraphs"
        cur = {"key": sk, "kind": kind, "gk": gk, "units": [u.unit_id], "parent": u.parent_chunk, "subs": [u.sub_chunk]}
        group_records.append(cur)
        if kind == "paragraphs":
            cur = None                     # prose: one group per unit, joined by the packing below
print("Groups:", len(group_records), Counter(g["kind"] for g in group_records))

# %% cell 74
# =========================================================
# 14.2 Packing and balanced splits
# =========================================================
content_of = units_df.set_index("unit_id")["content"]
unit_page = units_df.set_index("unit_id")["page_start"]


def header_of(rid: str, parent: str, sub: str | None) -> str:
    m = meta_of.loc[rid]
    return (f"USCG ROI {m.vessel_label} (MISLE {m.misle}, {day(m.incident_date)}) — {parent}" + (f" > {sub}" if sub else ""))


def common_sub(subs) -> str | None:
    parts = [s.split(" > ") for s in subs if isinstance(s, str)]
    if not parts or len(parts) < len(subs):
        return None
    out = []
    for level in zip(*parts):
        if len(set(level)) != 1:
            break
        out.append(level[0])
    return " > ".join(out) or None


def balanced(pieces: list[str], budget: int) -> list[list[str]]:
    """Fewest parts that fit, cut where the running size crosses equal fractions of the total."""
    total = sum(len(p) + 1 for p in pieces)
    k = max(1, -(-total // budget))
    while True:
        parts, cur, run = [], [], 0
        for p in pieces:
            if cur and run + len(p) + 1 > total * (len(parts) + 1) / k + 1e-9 and len(parts) < k - 1:
                parts.append(cur); cur = []
            cur.append(p); run += len(p) + 1
        parts.append(cur)
        if all(sum(len(x) + 1 for x in part) - 1 <= budget for part in parts):
            return parts
        k += 1


def pieces_of(unit_ids: list[str], budget: int) -> list[str]:
    out = []
    for uid in unit_ids:
        c = content_of[uid]
        if len(c) <= budget:
            out.append(c)
        else:                                            # a unit longer than the budget: cut at sentence ends
            out += sentences(c)
    assert all(len(p) <= budget for p in out), [len(p) for p in out if len(p) > budget]
    return out


chunk_records = []
by_key = {}
for g in group_records:
    by_key.setdefault(g["key"], []).append(g)
for key, groups in by_key.items():
    rid = key[0]
    packs, cur = [], None
    for g in groups:
        size = sum(len(content_of[u]) + 1 for u in g["units"])
        mergeable = g["kind"] in ("paragraphs", "numbered_group", "recommendation_action")
        if cur is not None and mergeable and cur["mergeable"] and cur["size"] < MIN_CHUNK_CHARS \
                and cur["size"] + size <= MAX_CHUNK_CHARS - 200:
            cur["groups"].append(g); cur["size"] += size
            continue
        cur = {"groups": [g], "size": size, "mergeable": mergeable}
        packs.append(cur)
    # a short last pack joins the previous one when it fits
    if len(packs) > 1 and packs[-1]["mergeable"] and packs[-2]["mergeable"] and packs[-1]["size"] < MIN_CHUNK_CHARS \
            and packs[-2]["size"] + packs[-1]["size"] <= MAX_CHUNK_CHARS - 200:
        packs[-2]["groups"] += packs[-1]["groups"]; packs.pop()
    for pk in packs:
        units = [u for g in pk["groups"] for u in g["units"]]
        subs = [s for g in pk["groups"] for s in g["subs"]]
        kinds = [g["kind"] for g in pk["groups"]]
        kind = kinds[0] if len(set(kinds)) == 1 else "paragraphs"
        parent = pk["groups"][0]["parent"]
        sub = common_sub(subs)
        header = header_of(rid, parent, sub)
        budget = MAX_CHUNK_CHARS - len(header) - 1
        parts = balanced(pieces_of(units, budget), budget)
        for i, part in enumerate(parts):
            body = "\n".join(part)
            members = [u for u in units if any(content_of[u] == p or (p in content_of[u]) for p in part)]
            chunk_records.append({"report_id": rid, "unit_type": kind, "units": members or units, "parent_chunk": parent,
                                  "sub_chunk": sub, "header": header, "text": header + "\n" + body,
                                  "part_no": i + 1, "n_parts": len(parts)})
chunks_raw = pd.DataFrame(chunk_records)
chunks_raw["char_count"] = chunks_raw["text"].str.len()
print("Chunks:", len(chunks_raw), chunks_raw["unit_type"].value_counts().to_dict())
print("Size: median", int(chunks_raw["char_count"].median()), "| max", int(chunks_raw["char_count"].max()),
      "| below MIN:", int((chunks_raw["char_count"] < MIN_CHUNK_CHARS).sum()), "| split groups:",
      int((chunks_raw["n_parts"] > 1).sum()))

# %% cell 75
# =========================================================
# 14.3 Chunk table (16-column schema, ARCHITECTURE §5)
# =========================================================
SCHEMA = ["page", "unit_type", "logical_unit", "chunk_id", "parent_chunk", "sub_chunk", "title", "text", "char_count",
          "filename", "source", "real_or_synthetic", "document_type", "department", "sensitivity_level", "version_date"]
chunks_raw["chunk_no"] = chunks_raw.groupby("report_id").cumcount() + 1
first_page = [next((int(unit_page[u]) for u in us if pd.notna(unit_page[u])), None) for us in chunks_raw["units"]]
chunks_df = pd.DataFrame({
    "page": pd.array(first_page, dtype="Int64"),
    "unit_type": chunks_raw["unit_type"],
    "logical_unit": chunks_raw["units"].map(";".join),
    "chunk_id": CHUNK_PREFIX + "_" + chunks_raw["report_id"].str.lower() + "_" + chunks_raw["chunk_no"].map("{:03d}".format),
    "parent_chunk": chunks_raw["parent_chunk"],
    "sub_chunk": chunks_raw["sub_chunk"],
    "title": [f"USCG Report of Investigation — {meta_of.at[r, 'vessel_label']} (MISLE {meta_of.at[r, 'misle']})"
              for r in chunks_raw["report_id"]],
    "text": chunks_raw["text"],
    "char_count": pd.array(chunks_raw["char_count"], dtype="Int64"),
    "filename": chunks_raw["report_id"].map(FILE_OF),
    "source": SOURCE_PUBLISHER, "real_or_synthetic": REAL_OR_SYNTHETIC, "document_type": DOCUMENT_TYPE,
    "department": DEPARTMENT,
    "sensitivity_level": pd.array([LEVEL] * len(chunks_raw), dtype="Int64"),
    "version_date": chunks_raw["report_id"].map(lambda r: day(meta_of.at[r, "version_date"])),
})[SCHEMA]
print("Chunk table:", chunks_df.shape)
display(chunks_df[["chunk_id", "unit_type", "char_count", "sub_chunk"]].head(5))

# %% cell 76
# =========================================================
# 15.1 Phases 14–15 validation (reviewed on the samples)
# =========================================================
assert list(chunks_df.columns) == SCHEMA and chunks_df["chunk_id"].is_unique
assert chunks_df["char_count"].max() <= MAX_CHUNK_CHARS and chunks_df["char_count"].min() >= FRAGMENT_MIN_CHARS
assert (chunks_df["text"].str.len() == chunks_df["char_count"]).all()
assert chunks_df["text"].str.startswith("USCG ROI ").all(), "Every chunk starts with its header."
# every unit is in the chunks: whole (one chunk) or, when longer than the budget, sentence by sentence
text_of_chunks = chunks_df.groupby(chunks_raw["report_id"])["text"].apply("\n".join)
unit_hits = {}
for c, us in zip(chunks_df["text"], chunks_raw["units"]):
    for u in us:
        unit_hits.setdefault(u, []).append(c)
for u in units_df.itertuples():
    texts = unit_hits.get(u.unit_id, [])
    assert texts, u.unit_id
    whole = [t for t in texts if u.content in t]
    assert len(whole) == 1 or all(any(s in t for t in texts) for s in sentences(u.content)), u.unit_id
# no chunk mixes sections, parts or levels
key_of = {u.unit_id: section_key(u) for u in units_df.itertuples()}
assert all(len({key_of[u] for u in us}) == 1 for us in chunks_raw["units"])
assert chunks_df.groupby(chunks_df.index)["sensitivity_level"].nunique().max() == 1
# personal names never in headers / paths / curated chunks
assert not any(n in t for n in signer_names | party_names for t in chunks_df["parent_chunk"].tolist()
               + chunks_df["sub_chunk"].dropna().tolist() + chunks_df.loc[chunks_df["unit_type"].isin(
                   ["vessel_block", "persons", "incident_profile"]), "text"].tolist())
# Determination of Cause kept whole when it fits
doc = chunks_raw[chunks_raw["sub_chunk"].fillna("").str.contains("6.1 Determination of Cause")]
REVIEWED_PHASE14 = {"chunks": 1544, "types": {"numbered_group": 1000, "paragraphs": 307, "recommendation_action": 162,
                                               "vessel_block": 27, "incident_profile": 23, "persons": 22,
                                               "glossary": 2, "note": 1},
                    "below_min": 40, "split_chunks": 209, "determination_whole": 16}
actual = {"chunks": len(chunks_df), "types": chunks_df["unit_type"].value_counts().to_dict(),
          "below_min": int((chunks_df["char_count"] < MIN_CHUNK_CHARS).sum()),
          "split_chunks": int((chunks_raw["n_parts"] > 1).sum()),
          "determination_whole": int((doc.drop_duplicates("header")["n_parts"] == 1).sum())}
assert actual == REVIEWED_PHASE14, actual
print("✅ Phases 14–15 validation passed.")
print("Phases 14–15:", len(chunks_df), "chunks | median", int(chunks_df["char_count"].median()), "chars |",
      actual["below_min"], "whole short pieces below MIN (a table, a one-paragraph section) |", actual["split_chunks"],
      "parts of balanced splits")

# %% [markdown] cell 77
# # Phases 16–18 — Schema, save / reload, cross-source check
#
# The chunks are checked against the unified 16-column schema and the dtypes of the existing corpus, saved as
# `chunks/USCG_ROI_chunks.parquet`, reloaded from disk and compared cell by cell, and concatenated with the 619 chunks
# of the other sources (unique `chunk_id`, same columns and dtypes, valid department and level).

# %% cell 78
# =========================================================
# 16–18 Schema, save / reload, cross-source
# =========================================================
ref_dtypes = other_chunks.dtypes.astype(str).to_dict()
assert list(other_chunks.columns) == SCHEMA
for col in ("page", "char_count", "sensitivity_level"):
    assert str(chunks_df[col].dtype) == "Int64" == ref_dtypes[col], col
assert chunks_df["sensitivity_level"].between(1, 3).all() and chunks_df["department"].isin(KNOWN_DEPARTMENTS).all()
assert chunks_df[["unit_type", "logical_unit", "chunk_id", "parent_chunk", "title", "text", "filename", "source",
                  "real_or_synthetic", "document_type", "department", "version_date"]].notna().all().all()
CHUNKS_PATH = CHUNKS_DIR / f"{SOURCE_NAME}_chunks.parquet"
chunks_df.to_parquet(CHUNKS_PATH, index=False)
reloaded = pd.read_parquet(CHUNKS_PATH)
assert list(reloaded.columns) == SCHEMA and len(reloaded) == len(chunks_df)
for col in SCHEMA:
    a, b = reloaded[col].astype(object).where(reloaded[col].notna(), None), chunks_df[col].astype(object).where(chunks_df[col].notna(), None)
    assert a.tolist() == b.tolist(), col
corpus = pd.concat([other_chunks, reloaded], ignore_index=True)
assert corpus["chunk_id"].is_unique and len(corpus) == len(other_chunks) + len(reloaded)
assert not corpus["chunk_id"].str.startswith("uscg_").iloc[:len(other_chunks)].any()
print("✅ Phases 16–18 validation passed.")
print("Phases 16–18:", CHUNKS_PATH.name, "|", len(reloaded), "chunks reloaded | corpus:", len(other_chunks), "+",
      len(reloaded), "=", len(corpus), "chunks | levels:", corpus["sensitivity_level"].value_counts().to_dict())

# %% [markdown] cell 79
# # Phase 19 — Coverage audit (every line of the 23 reports)
#
# Proof that nothing was dropped silently: **every line** of Phase 2 (`lines_df`, native and OCR) gets exactly one
# disposition:
#
# | Disposition | Meaning |
# |---|---|
# | `in_chunks` / `in_chunks_ocr` | the line's text is in the chunks of **its own unit** (whitespace ignored; tables and glossaries checked word by word, since the cells are rewritten as `label: value`) |
# | `metadata` | cover, file number and date, casualty titles, letter and section headings (→ chunk header / path), TOC, memo headers, enclosure lists, figure lists, figure captions (extracted file), table column headers, citation-only notes |
# | `layout_excluded` | page numbers, letterheads, running headers, enclosure footers |
# | `signature_excluded` | signer names, ranks, offices (plan §4.6) |
# | `figure_internal` / `ocr_noise` / `no_text` | text printed inside images, OCR marks, punctuation only |
# | `duplicate_trimmed` | an Executive Summary line whose sentence the report already prints (Phase 10) |
# | `erratum_excluded` | the KIM_LY clause (ADR-022) |
# | `pii_role_replaced` | an individual owner / operator cell, written as a role |
# | `pii_excluded` | a Name cell of a persons table (roles only) |
# | `redacted_note` | a note that prints only "Redacted" |
#
# The line-level result is added to the single cleaned file (`coverage_audit`).

# %% cell 80
# =========================================================
# 19.1 Line dispositions
# =========================================================
ROLE_DISPOSITION = {"page_number": "layout_excluded", "letterhead": "layout_excluded", "running_header": "layout_excluded",
                    "enclosure_footer": "layout_excluded", "file_block": "metadata", "file_date": "metadata",
                    "casualty_title": "metadata", "cover": "metadata", "toc": "metadata", "memo_header": "metadata",
                    "enclosures": "metadata", "figure_list": "metadata", "caption": "metadata", "letter_heading": "metadata",
                    "letter_heading_cont": "metadata", "section_heading": "metadata", "front_heading": "metadata",
                    "signature": "signature_excluded", "figure_internal": "figure_internal", "ocr_noise": "ocr_noise",
                    "no_text": "no_text"}
norm = lambda t: re.sub(r"\s+", "", str(t)).lower()
words = lambda t: re.findall(r"[a-z0-9]+", str(t).lower())
chunks_of_unit = {}
for text, us in zip(chunks_df["text"], chunks_raw["units"]):
    for u in us:
        chunks_of_unit.setdefault(u, []).append(text)
report_chunk_text = {rid: norm("\n".join(t)) for rid, t in chunks_df.groupby(chunks_raw["report_id"])["text"]}
unit_of_row = {x: u.unit_id for u in units_df.itertuples() for x in u.row_ids}
unit_type_of = units_df.set_index("unit_id")["unit_type"]
row_info = rows_df.set_index("row_id")
trimmed_units = set(duplicate_audit_df.loc[duplicate_audit_df["action"].isin(
    ["trimmed", "unit_dropped_all_sentences_covered"]), "unit_id"])
exec_para_text = {p.para_id: norm(p.text) for p in paragraphs_df[paragraphs_df["part"] == "executive_summary"].itertuples()}
exec_rows = {x: p.para_id for p in paragraphs_df[paragraphs_df["part"] == "executive_summary"].itertuples() for x in p.row_ids}
note_policy_of_row = {x: n.policy for n in notes_df.itertuples() for x in n.row_ids}
party_rows = {x for rid, f in INDIVIDUAL_PARTIES
              for ids in vessel_fields_df.loc[(vessel_fields_df["report_id"] == rid) & (vessel_fields_df["field"] == f), "row_ids"]
              for x in ids}
erratum_needle = norm(UNIT_ERRATA[0]["excluded"])


def in_chunks(line_text: str, texts: list[str], by_words: bool) -> bool:
    if not texts:
        return False
    texts = texts + ["\n".join(t.split("\n", 1)[1] for t in texts)]     # a unit split over chunks: its parts in order
    if by_words:
        pool = set(w for t in texts for w in words(t))
        return all(w in pool for w in words(line_text))
    n = norm(line_text)
    return any(n in norm(t) for t in texts)


dispositions = []
for ln in lines_df.itertuples():
    r = row_info.loc[ln.row_id]
    role, body_role = r["role"], r["body_role"]
    ocr = ln.provenance != "native"
    ok = "in_chunks_ocr" if ocr else "in_chunks"
    if role in ROLE_DISPOSITION:
        d = ROLE_DISPOSITION[role]
    elif role == "footnote":
        pol = note_policy_of_row[ln.row_id]
        if pol == "citation_only":
            d = "metadata"
        elif pol == "redacted":
            d = "redacted_note"
        else:
            t = NOTE_START_RE.match(ln.text.strip())
            t = (t["a"] or t["b"]) if t and not ln.text.strip().startswith(("•",)) else ln.text
            d = ok if norm(t) in report_chunk_text[ln.report_id] or norm(ln.text) in report_chunk_text[ln.report_id] else "UNACCOUNTED"
    elif body_role == "table_header" or (body_role == "glossary" and r["text"].strip() in ("Acronym Title", "List of Acronyms")):
        d = "metadata"
    elif ln.row_id in party_rows and not in_chunks(ln.text, chunks_of_unit.get(unit_of_row.get(ln.row_id), []), True):
        d = "pii_role_replaced"
    elif body_role == "structured_table" and NAME_ONLY_RE.match(ln.text.strip()):
        d = "pii_excluded"                  # a Name cell of a persons table (QUEEN_OF_THE_WEST), roles only
    else:
        uid = unit_of_row.get(ln.row_id)
        by_words = uid is not None and unit_type_of[uid] in ("vessel_block", "persons", "glossary")
        if uid is not None and in_chunks(ln.text, chunks_of_unit.get(uid, []), by_words):
            d = ok
        elif erratum_needle in norm(ln.text) and ln.report_id == UNIT_ERRATA[0]["report_id"]:
            d = "erratum_excluded"
        elif ln.row_id in exec_rows and (uid in trimmed_units or uid is None) and norm(ln.text) in exec_para_text[exec_rows[ln.row_id]]:
            d = "duplicate_trimmed"
        else:
            d = "UNACCOUNTED"
    dispositions.append({"line_key": ln.line_key, "report_id": ln.report_id, "page_number": ln.page_number,
                         "provenance": ln.provenance, "disposition": d})
coverage_df = pd.DataFrame(dispositions)
print("Lines:", len(coverage_df), coverage_df["disposition"].value_counts().to_dict())
display(coverage_df[coverage_df["disposition"] == "UNACCOUNTED"].merge(lines_df[["line_key", "text"]], on="line_key").head(20))

# %% cell 81
# =========================================================
# 19.2 Coverage validation + cleaned file update
# =========================================================
assert len(coverage_df) == len(lines_df) and coverage_df["line_key"].is_unique
unaccounted = coverage_df[coverage_df["disposition"] == "UNACCOUNTED"]
assert unaccounted.empty, unaccounted.merge(lines_df[["line_key", "text"]], on="line_key").head(20)
per_report = coverage_df.pivot_table(index="report_id", columns="disposition", values="line_key", aggfunc="count", fill_value=0)
page_content = coverage_df.assign(c=coverage_df["disposition"].str.startswith("in_chunks")).groupby(
    ["report_id", "page_number"])["c"].any()
pages_without_content = page_content[~page_content]
coverage_audit = {"lines": len(coverage_df), "dispositions": coverage_df["disposition"].value_counts().to_dict(),
                  "per_report": {rid: {k: int(v) for k, v in row.items() if v} for rid, row in per_report.iterrows()},
                  "pages_without_chunk_text": [f"{r}:p{p}" for r, p in pages_without_content.index],
                  "line_dispositions": records(coverage_df[["line_key", "disposition"]])}
cl = json.loads(CLEANED_PATH.read_text(encoding="utf-8"))
cl["coverage_audit"] = coverage_audit
CLEANED_PATH.write_text(json.dumps(cl, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
assert set(json.loads(CLEANED_PATH.read_text(encoding="utf-8"))) == {"source", "units", "duplicate_audit", "coverage_audit"}
REVIEWED_COVERAGE = {"in_chunks": 11413, "in_chunks_ocr": 3127, "metadata": 2044, "layout_excluded": 1597,
                     "figure_internal": 426, "signature_excluded": 269, "duplicate_trimmed": 84, "no_text": 15,
                     "pii_role_replaced": 15, "redacted_note": 6, "pii_excluded": 1, "ocr_noise": 1, "erratum_excluded": 1}
assert coverage_audit["dispositions"] == REVIEWED_COVERAGE, coverage_audit["dispositions"]
print("✅ Phase 19 validation passed.")
print("Phase 19:", len(coverage_df), "lines | 0 unaccounted |", len(pages_without_content),
      "pages carry no chunk text (covers, letterhead-only, photo pages) |",
      int(coverage_df["disposition"].eq("in_chunks_ocr").sum()), "OCR lines verified in their chunks")

# %% [markdown] cell 82
# # Phase 20 — IMO incident profiles: trace and validation
#
# Every printed value is traced to the line(s) it was read from; every count is recomputed from the rows; every
# reviewed code has an evidence sentence that still exists (unit id + sentence number, same text) and a code that
# exists in the IMO catalogue. The date is traced to the title / cover lines that print it.

# %% cell 83
# =========================================================
# 20.1 Trace every profile value
# =========================================================
line_text = lines_df.set_index("row_id").groupby(level=0)["text"].apply(" ".join)
lines_of_row = lines_df.groupby("row_id")["line_key"].apply(list)
MONTH_NAMES = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
               "november", "december"]


def date_forms(ts) -> set[str]:
    t = pd.Timestamp(ts); m = MONTH_NAMES[t.month - 1]
    return {f"{m}{t.day},{t.year}", f"{m}{t.day:02d},{t.year}", f"{t.day}{m}{t.year}", f"{t.day:02d}{m}{t.year}",
            f"{t.day:02d}{m[:3]}{t.year}", f"{t.day}{m[:3]}{t.year}"}


trace_records = []
sent_of = {sid: s for rid, xs in report_sentences.items() for _, sid, s in xs}
for p in profile_df.itertuples():
    ev, ok, lines = p.evidence, False, []
    if p.field_id == "1.2.2":
        forms = date_forms(meta_of.at[p.report_id, "incident_date"])
        cand = rows_df[(rows_df["report_id"] == p.report_id) & rows_df["role"].isin(["casualty_title", "cover"])]
        for pg, g in cand.groupby("page_number"):
            if any(f in norm(" ".join(g.sort_values("y0")["text"])) for f in forms):
                ok, lines = True, [k for x in g["row_id"] for k in lines_of_row[x]]
                break
    elif p.basis == "printed":
        pool = " ".join(line_text[x] for x in ev["row_ids"])     # a cell can wrap beside its label: word test
        ok = norm(p.value) in norm(pool) or set(words(p.value)) <= set(words(pool))
        lines = [k for x in ev["row_ids"] for k in lines_of_row[x]]
    elif p.basis == "printed_role":
        ok = (p.report_id, p.source_field) in INDIVIDUAL_PARTIES
    elif p.basis == "count":
        if p.field_id == "1.1.2":
            ok = p.value == len(ev["vessel_blocks"])
        else:
            ok = p.value == p.value and isinstance(p.value, (int, np.integer))
        lines = [k for x in ev.get("persons_rows", []) for k in lines_of_row[x]]
    elif p.basis == "reviewed_code":
        if "sentence_id" in ev:
            ok = sent_of.get(ev["sentence_id"]) == ev["sentence"] and (p.table_no, p.code) in OPTION
        else:
            ok = ev["dead_or_missing"] > 0 and (p.table_no, p.code) in OPTION
    elif p.basis == "not_determinable":
        ok = bool(ev.get("reason"))
    trace_records.append({"report_id": p.report_id, "field_id": p.field_id, "basis": p.basis, "traced": ok, "lines": lines})
trace_df = pd.DataFrame(trace_records)
# the dead / missing counts equal the persons units (Phase 4) per report
dm = profile_df[profile_df["field_id"].isin(["2.4.1", "2.4.2", "2.4.3"])].groupby("report_id")["value"].sum()
assert dm.to_dict() == {rid: int((persons_df.loc[persons_df["report_id"] == rid, "outcome"] == "dead_or_missing").sum())
                        for rid in REPORT_IDS}
assert trace_df["traced"].all(), trace_df[~trace_df["traced"]].head(20)
assert trace_df.loc[trace_df["basis"] == "printed", "lines"].map(len).gt(0).all()
print("✅ Phase 20 validation passed.")
print("Phase 20:", len(trace_df), "profile values traced |", trace_df["basis"].value_counts().to_dict())

# %% cell 84
# =========================================================
# Final Checkpoint — pipeline summary (every number below was asserted in its phase)
# =========================================================
final_summary = {
    "reports / pages": f"{len(REPORT_IDS)} / {len(pages_df)}",
    "page classes": pages_df["text_class"].value_counts().to_dict(),
    "lines (native / ocr / ocr_layer)": lines_df["provenance"].value_counts().to_dict(),
    "rows": len(rows_df),
    "template status": fingerprint_df["status"].value_counts().to_dict(),
    "document parts": len(parts_df),
    "vessel / vehicle fields": len(vessel_fields_df),
    "persons (roles only)": len(persons_df),
    "figure captions (metadata, all caption_only)": len(figures_df),
    "notes (informative / citation / redacted)": notes_df["policy"].value_counts().to_dict(),
    "superscripts restored": int(superscripts_df["disposition"].eq("restored").sum()),
    "paragraphs": len(paragraphs_df),
    "logical units": units_df["unit_type"].value_counts().to_dict(),
    "summary sentences trimmed": n_trim,
    "cross-source duplicates": len(cross),
    "incident profiles / values": f"{len(profiles)} / {len(profile_df)}",
    "chunks": len(chunks_df),
    "chunk types": chunks_df["unit_type"].value_counts().to_dict(),
    "chunk chars (median / max)": f"{int(chunks_df['char_count'].median())} / {int(chunks_df['char_count'].max())}",
    "corpus after this source": len(corpus),
    "lines accounted for": f"{len(coverage_df)} (unaccounted 0)",
}
assert len(chunks_df) == 1544 and len(corpus) == 619 + 1544
assert coverage_df["disposition"].ne("UNACCOUNTED").all() and trace_df["traced"].all()
assert (chunks_df["sensitivity_level"] == 1).all() and (chunks_df["department"] == "Operations").all()
for k, v in final_summary.items():
    print(f"{k:45s} {v}")
print("✅ Final Checkpoint passed.")

# %% [markdown] cell 85
# Final Checkpoint: see pipelines/checkpoints/rag/USCG_ROI_chunking.md
