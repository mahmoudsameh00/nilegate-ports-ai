"""1. Page Classification

Origin:  Converted from Notebooks/rag/LPI_methodology_chunking.ipynb (archived in docs/archive/notebooks/).
         Refactored (ADR-036 D3), cleanup level (2026-10-01): the notebook's phases, code and validations are unchanged;
         cell markers, Jupyter display() and the conversion helpers became plain sections and print(); proven by
         `uv run python tools/nb_to_script.py check LPI_methodology_chunking` (AST equal to the archived notebook).
Run:     uv run python tools/run.py pipelines/scripts/rag/LPI_methodology_chunking.py  (from the project root)

Reads:   Data/raw/unstructured/LPI_Methodology.pdf
Writes:  Data/processed/rag/extracted|cleaned|chunks/ (the LPI Methodology files)
Re-run:  safe: rewrites the same three artifacts
Final Checkpoint (what was done, problems, fixes): pipelines/checkpoints/rag/LPI_methodology_chunking.md
"""

# %% 1. Page Classification
# Before extracting content, we classify each PDF page according to its role in the document.
#
# The goal is to separate:
#
# - Cover / title pages
# - Legal or nearly empty pages
# - Table of contents
# - Actual content pages
# - References
#
# Only pages containing meaningful content for the RAG system will continue to the downstream extraction pipeline.
#
# At this stage, we only inspect and classify pages. No chunking or content extraction is performed yet.

from pathlib import Path
import fitz  # PyMuPDF

# The PDF is located by walking up from the notebook's folder, so the notebook
# does not depend on one machine's absolute path.
PDF_RELATIVE_PATH = Path("Data/raw/unstructured/LPI_Methodology.pdf")

search_roots = [Path.cwd(), *Path.cwd().parents]
candidates = [root / PDF_RELATIVE_PATH for root in search_roots]

PDF_PATH = next((path for path in candidates if path.exists()), None)

if PDF_PATH is None:
    raise FileNotFoundError(
        "LPI_Methodology.pdf not found. Looked in:\n  "
        + "\n  ".join(str(path) for path in candidates)
    )

doc = fitz.open(PDF_PATH)

print(f"Document: {PDF_PATH.name}")
print(f"Total pages: {len(doc)}")

# Build a lightweight inventory for every page
import pandas as pd
page_inventory = []

for page_number, page in enumerate(doc, start=1):
    text = page.get_text("text").strip()

    page_inventory.append({
        "page_number": page_number,
        "char_count": len(text),
        "word_count": len(text.split()),
        "text": text,
    })

pages_df = pd.DataFrame(page_inventory)

print(pages_df.head())

# Inspect the beginning and end of the document

for page_number in list(range(1, 11)) + list(range(len(doc) - 4, len(doc) + 1)):
    page = doc[page_number - 1]
    text = page.get_text("text").strip()

    print("=" * 100)
    print(f"PAGE {page_number}")
    print("=" * 100)
    print(text[:800])
    print()


# %% 1.1 Define Page Classification Rules
# Based on the initial inspection of the LPI 2.0 PDF, we classify pages into two broad groups:
#
# ### Retrieval-worthy
# - Abstract
# - Executive Summary
# - Main body sections
# - Methodology
# - User Guide
# - Other pages containing substantive content
#
# ### Non-retrieval
# - Cover / title pages
# - Blank pages
# - Copyright / legal pages
# - Table of Contents
# - Acknowledgements
# - References
#
# Non-retrieval pages are not deleted from the document. They are simply excluded from the main retrieval corpus.
#
# For each page, we also store a classification reason so the decision can be inspected and validated later.

# =========================================================
# 1.1 Page Classification Rules
# =========================================================

def classify_page(row):
    page_number = row["page_number"]
    text = row["text"].strip()
    text_lower = text.lower()

    # -----------------------------------------------------
    # Blank pages
    # -----------------------------------------------------
    if row["word_count"] == 0:
        return "blank", False, "No extracted text"

    # -----------------------------------------------------
    # Cover / title pages
    # -----------------------------------------------------
    if page_number in [1, 3]:
        return "cover_title", False, "Cover / title page"

    # -----------------------------------------------------
    # Copyright / legal page
    # -----------------------------------------------------
    if page_number == 4 and "copyright" in text_lower:
        return "legal", False, "Copyright / legal information"

    # -----------------------------------------------------
    # Table of Contents
    # -----------------------------------------------------
    if page_number in [5, 6]:
        return "contents", False, "Document navigation / figures / tables list"

    # -----------------------------------------------------
    # Acknowledgements
    # -----------------------------------------------------
    if page_number == 7 and "acknowledgements" in text_lower:
        return "acknowledgements", False, "Acknowledgements section"

    # -----------------------------------------------------
    # References
    # -----------------------------------------------------
    if page_number == 31:
        return "references", False, "Bibliographic references"

    # -----------------------------------------------------
    # Otherwise: substantive content
    # -----------------------------------------------------
    return "content", True, "Substantive document content"


classification = pages_df.apply(
    classify_page,
    axis=1,
    result_type="expand"
)

classification.columns = [
    "page_type",
    "keep_for_rag",
    "classification_reason",
]

pages_df = pd.concat(
    [pages_df, classification],
    axis=1
)

print(pages_df[
    [
        "page_number",
        "word_count",
        "page_type",
        "keep_for_rag",
        "classification_reason",
    ]
])


# %% 1.2 Validate Page Classification
# We validate the classification results before moving to content extraction.
#
# The validation checks:
#
# - Total number of pages
# - Number of retrieval pages
# - Number of excluded pages
# - Which pages are excluded from retrieval

# Classification validation

total_pages = len(pages_df)

retrieval_pages = pages_df["keep_for_rag"].sum()
excluded_pages = total_pages - retrieval_pages

print(f"Total pages:       {total_pages}")
print(f"Retrieval pages:   {retrieval_pages}")
print(f"Excluded pages:    {excluded_pages}")

print("\nExcluded pages:")
print(
    pages_df.loc[
        ~pages_df["keep_for_rag"],
        [
            "page_number",
            "page_type",
            "classification_reason"
        ]
    ]
)


# %% 2. Content Extraction
# Only pages classified as retrieval-worthy are passed to the downstream extraction pipeline.
#
# At this stage, we create a clean working set containing only the substantive document pages.
#
# The excluded pages remain available in the original document, but they are not part of the main RAG extraction flow.

# Create the working set for downstream extraction

content_pages_df = pages_df[
    pages_df["keep_for_rag"]
].copy()

print(f"Pages entering content extraction: {len(content_pages_df)}")

print(
    content_pages_df[
        [
            "page_number",
            "word_count",
            "page_type"
        ]
    ].head()
)


# %% 2.1 Content-Type Inventory
# Before choosing an extraction strategy, we inspect the structure of each retrieval page.
#
# For every page, we identify simple content signals such as:
#
# - Extracted text volume
# - Presence of figures
# - Presence of tables
# - Number of embedded images
#
# These signals will later help route each page to the appropriate extraction path.
#
# No chunking or transformation is performed at this stage.

# Inspect the content structure of retrieval pages

import re


def inspect_page_structure(doc, pages_df):
    records = []

    for _, row in pages_df.iterrows():
        page_number = int(row["page_number"])
        page = doc[page_number - 1]

        text = row["text"]

        figure_markers = re.findall(
            r"\b(?:Figure|Fig\.)\s*\d+",
            text,
            flags=re.IGNORECASE
        )

        table_markers = re.findall(
            r"\bTable\s*\d+",
            text,
            flags=re.IGNORECASE
        )

        records.append({
            "page_number": page_number,
            "word_count": row["word_count"],
            "image_count": len(page.get_images(full=True)),
            "figure_markers": len(figure_markers),
            "table_markers": len(table_markers),
        })

    return pd.DataFrame(records)


content_structure_df = inspect_page_structure(
    doc,
    content_pages_df
)

print(content_structure_df)


# %% 2.2 Detect Visual Candidates
# Images extracted from a PDF are not necessarily informative figures.
#
# Some images may be:
#
# - Decorative elements
# - Logos or visual branding
# - Informational figures or diagrams
#
# Therefore, we first collect visual candidates and their nearby text/caption signals.
#
# We will use this information to distinguish decorative visuals from informational figures in the next step.

# Collect visual candidates from retrieval pages

visual_candidates = []

for _, row in content_pages_df.iterrows():
    page_number = int(row["page_number"])
    page = doc[page_number - 1]

    images = page.get_images(full=True)

    if not images:
        continue

    text = row["text"]

    # Look for Figure captions in the extracted text
    figure_matches = re.findall(
        r"(Figure\s+\d+[^\n]*)",
        text,
        flags=re.IGNORECASE
    )

    visual_candidates.append({
        "page_number": page_number,
        "image_count": len(images),
        "figure_captions": figure_matches,
        "text_preview": text[:500],
    })

visual_candidates_df = pd.DataFrame(visual_candidates)

print(visual_candidates_df)


# %% 2.3 Inspect Figure and Table Markers
# Embedded image count is not sufficient to identify informational figures.
#
# Instead, we inspect explicit Figure and Table markers found in the extracted text.
#
# These markers will help us locate structured visual content and determine which pages require specialized extraction.

# Inspect explicit Figure and Table markers

visual_markers = []

for _, row in content_pages_df.iterrows():
    text = row["text"]
    page_number = int(row["page_number"])

    figure_matches = re.findall(
        r"\bFigure\s+\d+[^.\n]*",
        text,
        flags=re.IGNORECASE
    )

    table_matches = re.findall(
        r"\bTable\s+\d+[^.\n]*",
        text,
        flags=re.IGNORECASE
    )

    if figure_matches or table_matches:
        visual_markers.append({
            "page_number": page_number,
            "figures": figure_matches,
            "tables": table_matches,
        })

visual_markers_df = pd.DataFrame(visual_markers)

print(visual_markers_df)


# %% 2.4 Inspect Figure and Table Caption Candidates
# A page may mention a figure or table inside normal body text without containing the actual visual caption.
#
# Therefore, explicit Figure/Table references are not treated as captions automatically.
#
# We inspect the matching lines and their nearby text first, so that caption detection can distinguish:
#
# - References to a figure/table inside a paragraph
# - Actual Figure/Table captions
# - Other structural references

# Inspect lines containing Figure/Table markers

marker_contexts = []

for _, row in content_pages_df.iterrows():
    page_number = int(row["page_number"])
    text = row["text"]

    lines = [line.strip() for line in text.splitlines() if line.strip()]

    for i, line in enumerate(lines):
        if re.search(r"\b(?:figure|fig\.|table)\s*\d+", line, re.IGNORECASE):

            context_before = lines[i - 1] if i > 0 else ""
            context_after = lines[i + 1] if i + 1 < len(lines) else ""

            marker_contexts.append({
                "page_number": page_number,
                "previous_line": context_before,
                "matched_line": line,
                "next_line": context_after,
            })

marker_contexts_df = pd.DataFrame(marker_contexts)

print(marker_contexts_df)

# Detect actual Figure/Table caption candidates

caption_candidates = []

for _, row in content_pages_df.iterrows():
    page_number = int(row["page_number"])
    text = row["text"]

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    for line in lines:

        # Actual Figure caption candidate
        figure_match = re.match(
            r"^Figure\s+(\d+)\s*(.*)$",
            line,
            flags=re.IGNORECASE
        )

        # Actual Table caption candidate
        table_match = re.match(
            r"^Table\s+(\d+)\s*(.*)$",
            line,
            flags=re.IGNORECASE
        )

        if figure_match:
            caption_candidates.append({
                "page_number": page_number,
                "content_type": "figure",
                "number": int(figure_match.group(1)),
                "caption": line,
            })

        elif table_match:
            caption_candidates.append({
                "page_number": page_number,
                "content_type": "table",
                "number": int(table_match.group(1)),
                "caption": line,
            })


captions_df = pd.DataFrame(caption_candidates)

print(captions_df)


# %% 2.5 Validate Caption Candidates
# A structural marker such as `Figure N` or `Table N` is not sufficient by itself.
#
# Some body-text sentences can also start with a Figure/Table reference.
#
# Therefore, caption candidates must be validated before they are treated as standalone visual or structured elements.
#
# The validation step identifies suspicious candidates that require a stricter detection rule.

# Inspect all caption candidates with their surrounding lines

caption_validation = []

for _, row in captions_df.iterrows():
    page_number = int(row["page_number"])
    page = doc[page_number - 1]

    lines = [
        line.strip()
        for line in page.get_text("text").splitlines()
        if line.strip()
    ]

    target_line = row["caption"]

    # Find the exact line
    try:
        idx = lines.index(target_line)
    except ValueError:
        idx = None

    previous_line = lines[idx - 1] if idx is not None and idx > 0 else ""
    next_line = (
        lines[idx + 1]
        if idx is not None and idx + 1 < len(lines)
        else ""
    )

    caption_validation.append({
        "page_number": page_number,
        "content_type": row["content_type"],
        "number": row["number"],
        "candidate": target_line,
        "previous_line": previous_line,
        "next_line": next_line,
    })

caption_validation_df = pd.DataFrame(caption_validation)

print(caption_validation_df)


# %% 2.6 Refine Figure and Table Caption Detection
# The initial caption detector produced one false positive:
#
# `Figure 5 presents the example ...`
#
# This is a body-text reference rather than an actual figure caption.
#
# Based on the inspected document structure, actual captions consistently follow the pattern:
#
# `Figure N <Caption Title>`
#
# or
#
# `Table N <Caption Title>`
#
# where the caption title begins with an uppercase letter.
#
# We therefore use this structural pattern to reduce false positives while keeping the rule generic and reusable.

# Refined Figure/Table caption detection

caption_candidates = []

for _, row in content_pages_df.iterrows():
    page_number = int(row["page_number"])
    text = row["text"]

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    for line in lines:

        # Figure caption:
        # Figure N <Caption starting with uppercase letter>
        figure_match = re.match(
            r"^Figure\s+(\d+)\s+([A-Z].*)$",
            line
        )

        # Table caption:
        # Table N <Caption starting with uppercase letter>
        table_match = re.match(
            r"^Table\s+(\d+)\s+([A-Z].*)$",
            line
        )

        if figure_match:
            caption_candidates.append({
                "page_number": page_number,
                "content_type": "figure",
                "number": int(figure_match.group(1)),
                "caption": line,
            })

        elif table_match:
            caption_candidates.append({
                "page_number": page_number,
                "content_type": "table",
                "number": int(table_match.group(1)),
                "caption": line,
            })


captions_df = pd.DataFrame(caption_candidates)

print(captions_df)


# %% 2.7 Inspect Section Context
# Each Figure and Table must remain connected to the section in which it appears.
#
# Before automatically detecting section headings, we inspect the beginning of the relevant pages to understand how headings are represented in the extracted PDF text.
#
# This allows us to design a reliable heading-detection rule without relying on page numbers alone.

# Inspect the beginning of pages containing Figures/Tables

element_pages = sorted(captions_df["page_number"].unique())

for page_number in element_pages:
    page_number = int(page_number)

    page = doc[page_number - 1]

    lines = [
        line.strip()
        for line in page.get_text("text").splitlines()
        if line.strip()
    ]

    print("=" * 100)
    print(f"PAGE {page_number}")
    print("=" * 100)

    # Show the first 15 non-empty lines
    for line in lines[:15]:
        print(line)

    print()


# %% 2.7.1 Detect Heading Candidates
# Before removing repeated headers and footers, we first inspect potential section headings.
#
# A heading candidate should be:
#
# - Relatively short compared with normal body paragraphs.
# - Structurally distinct from surrounding text.
# - Potentially written in uppercase or title case.
# - Not one of the repeated document headers or page numbers.
#
# At this stage, we only generate candidates for inspection.
# No heading is accepted as a final section boundary yet.

# Detect potential heading candidates

heading_candidates = []

REPEATED_HEADER_LINES = {
    "THE NEW LOGISTICS PERFORMANCE INDICATORS 2.0 (LPI 2.0)",
    "METHODOLOGY AND USER GUIDE",
}

for _, row in content_pages_df.iterrows():
    page_number = int(row["page_number"])
    text = row["text"]

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    for i, line in enumerate(lines):

        # Skip repeated headers
        if line.upper() in REPEATED_HEADER_LINES:
            continue

        # Skip page numbers
        if re.fullmatch(r"\d+", line):
            continue

        # Basic heading signals
        word_count = len(line.split())
        char_count = len(line)

        is_short = word_count <= 12 and char_count <= 120
        is_uppercase = line.isupper()

        title_case_words = sum(
            1 for word in line.split()
            if word[:1].isupper()
        )

        mostly_title_case = (
            word_count >= 2
            and title_case_words / word_count >= 0.6
        )

        if is_short and (is_uppercase or mostly_title_case):
            heading_candidates.append({
                "page_number": page_number,
                "line_index": i,
                "candidate": line,
                "word_count": word_count,
                "is_uppercase": is_uppercase,
                "mostly_title_case": mostly_title_case,
            })

heading_candidates_df = pd.DataFrame(heading_candidates)

print(heading_candidates_df)


# %% 2.7.2 Inspect the PDF Document Outline
# Before building heuristic heading detection, we check whether the PDF already contains a structural outline (bookmarks).
#
# If available, the outline can provide reliable section and subsection boundaries without relying on text casing or line wrapping.
#
# The outline is used only as structural metadata; it does not affect the retrieval content itself.

# Inspect the PDF's built-in document outline

toc = doc.get_toc()

print(f"Number of outline entries: {len(toc)}")

for entry in toc:
    level, title, page = entry
    print(f"Level {level} | Page {page} | {title}")


# %% 2.7.3 Validate the PDF Outline
# The PDF contains a built-in document outline with hierarchical section information.
#
# We will use this outline as the primary source for:
#
# - Section titles
# - Subsection titles
# - Section hierarchy
#
# Before using its page numbers, we validate them against the extracted page text.
#
# This is necessary because a bookmark may point to a nearby page rather than the exact page where its heading appears.

# Convert the PDF outline into a DataFrame

toc = doc.get_toc()

toc_records = []

for level, title, page in toc:
    toc_records.append({
        "level": level,
        "title": title.strip(),
        "outline_page": int(page),
    })

toc_df = pd.DataFrame(toc_records)

print(toc_df)

# Normalize text for matching headings across line breaks

def normalize_for_match(text):
    text = text.replace("\xad", "")
    text = re.sub(r"-\s*\n", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


page_text_normalized = {}

for page_number in range(1, len(doc) + 1):
    text = doc[page_number - 1].get_text("text")
    page_text_normalized[page_number] = normalize_for_match(text)


# Find where each outline title actually appears
validation_records = []

for _, row in toc_df.iterrows():

    title_norm = normalize_for_match(row["title"])

    matched_pages = []

    for page_number, page_text in page_text_normalized.items():
        if title_norm in page_text:
            matched_pages.append(page_number)

    validation_records.append({
        "level": row["level"],
        "title": row["title"],
        "outline_page": row["outline_page"],
        "matched_pages": matched_pages,
        "first_match": matched_pages[0] if matched_pages else None,
    })


toc_validation_df = pd.DataFrame(validation_records)

print(toc_validation_df)


# %% 2.7.4 Validate Outline Entries Against Page Headings
# The PDF outline provides the document hierarchy and approximate starting pages.
#
# To validate these boundaries, we compare each outline title with the upper portion of its target page and the preceding page.
#
# This avoids false matches caused by:
#
# - References to a section inside body text
# - Table contents
# - Repeated terminology appearing later in the document
#
# The result will tell us which page actually contains the visible section heading.

# Normalize text while preserving word boundaries

def normalize_heading_text(text: str) -> str:
    text = text.replace("\xad", "")
    text = re.sub(r"-\s*\n", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def get_top_page_text(page_number: int, max_lines: int = 25) -> str:
    """
    Return only the upper portion of a page.
    This is where section headings are expected to appear.
    """
    if page_number < 1 or page_number > len(doc):
        return ""

    page = doc[page_number - 1]

    lines = [
        line.strip()
        for line in page.get_text("text").splitlines()
        if line.strip()
    ]

    return normalize_heading_text(" ".join(lines[:max_lines]))


outline_validation = []

for _, row in toc_df.iterrows():

    title = row["title"]
    outline_page = int(row["outline_page"])

    title_norm = normalize_heading_text(title)

    candidate_pages = [
        p for p in [outline_page - 1, outline_page]
        if 1 <= p <= len(doc)
    ]

    matches = []

    for page_number in candidate_pages:

        top_text = get_top_page_text(
            page_number,
            max_lines=25
        )

        if title_norm in top_text:
            matches.append(page_number)

    outline_validation.append({
        "level": row["level"],
        "title": title,
        "outline_page": outline_page,
        "candidate_pages": candidate_pages,
        "heading_matches": matches,
    })


outline_validation_df = pd.DataFrame(outline_validation)

print(outline_validation_df)


# %% 2.7.5 Inspect Unresolved Outline Entries
# Some outline titles could not be matched exactly because PDF text extraction may:
#
# - Split a heading across multiple lines.
# - Represent characters differently.
# - Place the visible heading slightly away from the outline destination page.
#
# We inspect only the unresolved entries and their nearby pages.
#
# This keeps the validation targeted and avoids introducing unnecessary heuristics.

# Inspect unresolved outline entries using title keywords

STOPWORDS = {
    "the", "of", "and", "to", "in", "use", "for", "with",
    "a", "an", "on", "how"
}


def title_keywords(title):
    words = re.findall(r"[a-zA-Z]+", title.lower())
    return [
        word for word in words
        if len(word) >= 4 and word not in STOPWORDS
    ]


unresolved = outline_validation_df[
    outline_validation_df["heading_matches"].apply(len) == 0
].copy()

inspection_records = []

for _, row in unresolved.iterrows():

    title = row["title"]
    keywords = title_keywords(title)

    candidate_pages = row["candidate_pages"]

    for page_number in candidate_pages:

        page = doc[int(page_number) - 1]

        lines = [
            line.strip()
            for line in page.get_text("text").splitlines()
            if line.strip()
        ]

        for i, line in enumerate(lines):

            line_lower = line.lower()

            matched_keywords = [
                keyword
                for keyword in keywords
                if keyword in line_lower
            ]

            if matched_keywords:
                inspection_records.append({
                    "outline_title": title,
                    "page": int(page_number),
                    "line_index": i,
                    "line": line,
                    "matched_keywords": matched_keywords,
                })


unresolved_inspection_df = pd.DataFrame(inspection_records)

print(unresolved_inspection_df)


# %% 2.7.6 Build the Section Map
# The PDF outline provides the document hierarchy, while the previous inspection validated the actual pages where section headings appear.
#
# We now create a canonical section map containing:
#
# - `section`
# - `subsection`
# - `start_page`
# - `level`
#
# This map will later be used to assign every extracted chunk to its correct section and subsection.

# Canonical section map for retrieval-worthy content

section_map = [
    {
        "level": 1,
        "section": "Abstract",
        "subsection": None,
        "start_page": 8,
    },
    {
        "level": 1,
        "section": "Executive summary",
        "subsection": None,
        "start_page": 9,
    },
    {
        "level": 1,
        "section": "Conceptual framework of the Logistics Performance Indicators 2.0",
        "subsection": None,
        "start_page": 11,
    },
    {
        "level": 2,
        "section": "Conceptual framework of the Logistics Performance Indicators 2.0",
        "subsection": "The new indicators",
        "start_page": 12,
    },
    {
        "level": 1,
        "section": "Data source",
        "subsection": None,
        "start_page": 19,
    },
    {
        "level": 2,
        "section": "Data source",
        "subsection": "Maritime",
        "start_page": 20,
    },
    {
        "level": 2,
        "section": "Data source",
        "subsection": "Aviation",
        "start_page": 21,
    },
    {
        "level": 2,
        "section": "Data source",
        "subsection": "Postal",
        "start_page": 21,
    },
    {
        "level": 1,
        "section": "Methodology",
        "subsection": None,
        "start_page": 22,
    },
    {
        "level": 2,
        "section": "Methodology",
        "subsection": "MDS Transmodal",
        "start_page": 22,
    },
    {
        "level": 2,
        "section": "Methodology",
        "subsection": "MarineTraffic",
        "start_page": 23,
    },
    {
        "level": 2,
        "section": "Methodology",
        "subsection": "Major global shipping line",
        "start_page": 24,
    },
    {
        "level": 2,
        "section": "Methodology",
        "subsection": "Cargo iQ",
        "start_page": 26,
    },
    {
        "level": 2,
        "section": "Methodology",
        "subsection": "Universal Postal Union",
        "start_page": 26,
    },
    {
        "level": 1,
        "section": "User guide",
        "subsection": None,
        "start_page": 28,
    },
    {
        "level": 2,
        "section": "User guide",
        "subsection": "Interpretation and use of the LPI 2.0",
        "start_page": 28,
    },
    {
        "level": 2,
        "section": "User guide",
        "subsection": "How to use the LPI 2.0 to benchmark country performance",
        "start_page": 29,
    },
    {
        "level": 2,
        "section": "User guide",
        "subsection": "Potential interpretation issues with tracking indicators",
        "start_page": 29,
    },
    {
        "level": 2,
        "section": "User guide",
        "subsection": "Local data to complement country-level indicators",
        "start_page": 30,
    },
]

section_map_df = pd.DataFrame(section_map)

print(section_map_df)


# %% 3. Extract Figures and Tables
# The document pages have already been classified, and all confirmed Figures and Tables have been identified.
#
# We now extract these structured elements separately from the body text.
#
# The extraction paths are:
#
# 1. Tables → structured tabular data
# 2. Figures → visual/diagram content with their captions
#
# The extracted elements will later be converted into retrieval-ready units and enriched with section metadata.


# %% 3.1 Table Extraction
# Tables are treated as structured information rather than ordinary text.
#
# Each table will first be extracted while preserving its rows and columns.
#
# We will inspect the extracted structure before converting table rows into RAG chunks.

# Extract candidate table pages from the confirmed caption inventory

table_captions_df = captions_df[
    captions_df["content_type"] == "table"
].copy()

print(table_captions_df)

# Extract Table 1 using PyMuPDF

table_page_number = int(
    table_captions_df.loc[
        table_captions_df["number"] == 1,
        "page_number"
    ].iloc[0]
)

table_page = doc[table_page_number - 1]

tables = table_page.find_tables()

print(f"Page: {table_page_number}")
print(f"Tables detected: {len(tables.tables)}")

for i, table in enumerate(tables.tables, start=1):
    print(f"\n--- Table {i} ---")
    
    extracted = table.extract()
    
    for row in extracted:
        print(row)

# Normalize formatting artifacts inside extracted table cells

def normalize_table_cell(value):
    if value is None:
        return None

    value = str(value)

    # Remove soft hyphen characters
    value = value.replace("\xad", "")

    # Convert line breaks to spaces
    value = re.sub(r"\s*\n\s*", " ", value)

    # Normalize repeated whitespace
    value = re.sub(r"\s+", " ", value)

    return value.strip()


# Extract Table 1
table_1 = table_page.find_tables().tables[0].extract()

# First row = headers
table_1_headers = [
    normalize_table_cell(cell)
    for cell in table_1[0]
]

# Remaining rows
table_1_rows = [
    [
        normalize_table_cell(cell)
        for cell in row
    ]
    for row in table_1[1:]
]

table_1_df = pd.DataFrame(
    table_1_rows,
    columns=table_1_headers
)

print(table_1_df)

# Convert each Table 1 row into an independent semantic unit

table_1_units = []

for _, row in table_1_df.iterrows():
    table_1_units.append({
        "unit_type": "table_row",
        "logical_unit": "Table 1: The six core indicators of the LPI 2.0",
        "page_number": table_page_number,
        "table_number": 1,
        "logistics_mode": row["Logistics mode"],
        "connectivity_indicator": row["Connectivity indicators"],
        "time_indicator": row["Time indicators"],
    })

table_1_units_df = pd.DataFrame(table_1_units)

print(table_1_units_df)

# Generic table extraction and normalization

def normalize_table_cell(value):
    if value is None:
        return None

    value = str(value)
    value = value.replace("\xad", "")
    value = re.sub(r"\s*\n\s*", " ", value)
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def extract_table(doc, page_number, table_number):
    page = doc[page_number - 1]

    tables = page.find_tables().tables

    if not tables:
        raise ValueError(
            f"No tables detected on page {page_number}."
        )

    if len(tables) != 1:
        print(
            f"Warning: {len(tables)} tables detected "
            f"on page {page_number}."
        )

    raw_table = tables[0].extract()

    headers = [
        normalize_table_cell(cell)
        for cell in raw_table[0]
    ]

    rows = [
        [
            normalize_table_cell(cell)
            for cell in row
        ]
        for row in raw_table[1:]
    ]

    table_df = pd.DataFrame(
        rows,
        columns=headers
    )

    return table_df


# Extract all confirmed tables

extracted_tables = {}

for _, row in table_captions_df.iterrows():

    page_number = int(row["page_number"])
    table_number = int(row["number"])

    extracted_tables[table_number] = extract_table(
        doc=doc,
        page_number=page_number,
        table_number=table_number,
    )


# Inspect table dimensions

table_inventory = []

for table_number, table_df in extracted_tables.items():

    table_inventory.append({
        "table_number": table_number,
        "rows": len(table_df),
        "columns": len(table_df.columns),
        "columns_list": list(table_df.columns),
    })

table_inventory_df = pd.DataFrame(table_inventory)

print(table_inventory_df)

# Inspect the extracted tables

for table_number, table_df in extracted_tables.items():

    print("=" * 100)
    print(f"TABLE {table_number}")
    print("=" * 100)

    print(table_df)

    print()

BULLET_PATTERN = r"^[•●▪◦]\s*"


def normalize_table_cell(value):
    if value is None:
        return None

    value = str(value)

    # Remove soft hyphen
    value = value.replace("\xad", "")

    # Normalize line breaks / whitespace
    value = re.sub(r"\s*\n\s*", " ", value)
    value = re.sub(r"\s+", " ", value)

    # Remove leading bullet markers
    value = re.sub(BULLET_PATTERN, "", value)

    return value.strip()

def build_table_units(extracted_tables, table_captions_df):

    table_units = []

    for table_number, table_df in extracted_tables.items():

        # --------------------------------------------------
        # Get table metadata
        # --------------------------------------------------
        caption_match = table_captions_df[
            table_captions_df["number"] == table_number
        ]

        if caption_match.empty:
            table_page_number = None
            logical_unit = None

        else:
            caption_row = caption_match.iloc[0]

            table_page_number = int(
                caption_row["page_number"]
            )

            logical_unit = str(
                caption_row.get("caption", "")
            ).strip()

            # Remove "Table X" from the logical unit
            logical_unit = re.sub(
                r"^Table\s+\d+\s*[:.]?\s*",
                "",
                logical_unit,
                flags=re.IGNORECASE
            ).strip()

        # --------------------------------------------------
        # Convert each row into an independent semantic unit
        # --------------------------------------------------
        for row_index, (_, row) in enumerate(table_df.iterrows()):

            # Keep only non-empty cells
            content = {
                column: str(row[column]).strip()
                for column in table_df.columns
                if pd.notna(row[column])
                and str(row[column]).strip() != ""
            }

            # --------------------------------------------------
            # Build semantic content
            # --------------------------------------------------
            content = "\n".join(
                f"{column}: {value}"
                for column, value in content.items()
            )

            # --------------------------------------------------
            # Build semantic unit
            # --------------------------------------------------
            table_units.append({
                "unit_type": "table_row",
                "table_number": table_number,
                "row_index": row_index,
                "page_number": table_page_number,
                "logical_unit": logical_unit,
                "content": content,
            })

    return table_units

table_units = build_table_units(
    extracted_tables=extracted_tables,
    table_captions_df=table_captions_df,
)

print(table_units[0]["content"])

from pprint import pprint

for table_number in sorted(extracted_tables.keys()):

    print("=" * 120)
    print(f"TABLE {table_number}")
    print("=" * 120)

    table_units_for_table = [
        unit
        for unit in table_units
        if unit["table_number"] == table_number
    ]

    for unit in table_units_for_table:

        print(f"\n--- Table Row {unit['row_index'] + 1} ---")

        pprint(unit, sort_dicts=False)

        print()


# %% 3.2 Figure Extraction
# The confirmed Figure inventory is already available in `captions_df`.
#
# For each Figure, we will extract:
#
# 1. Figure caption
# 2. Figure content available as PDF text
# 3. Source / note when present
#
# The extracted content will remain associated with its page and Figure number.
#
# We first test the extraction on Figure 1 before generalizing the process to all Figures.

# 3.2.1 Extract Figure 1

figure_1 = captions_df[
    (captions_df["content_type"] == "figure") &
    (captions_df["number"] == 1)
].iloc[0]

figure_1_page = int(figure_1["page_number"])
figure_1_caption = figure_1["caption"]

page = doc[figure_1_page - 1]
text = page.get_text("text")

print(f"Figure: {figure_1['number']}")
print(f"Page: {figure_1_page}")
print(f"Caption: {figure_1_caption}")
print("\nFigure text:")
print("-" * 80)

print(text.split(figure_1_caption, 1)[1])

# Separate Figure 1 content, source, and note

figure_1_raw = text.split(
    figure_1_caption,
    1
)[1].strip()

source_match = re.search(
    r"Source:\s*(.*?)(?=\nNote:|\Z)",
    figure_1_raw,
    flags=re.DOTALL
)

note_match = re.search(
    r"Note:\s*(.*)",
    figure_1_raw,
    flags=re.DOTALL
)

figure_1_content = figure_1_raw

if source_match:
    figure_1_content = figure_1_content[:source_match.start()].strip()

figure_1_source = (
    source_match.group(1).strip()
    if source_match
    else None
)

figure_1_note = (
    note_match.group(1).strip()
    if note_match
    else None
)

print("FIGURE CONTENT")
print("=" * 80)
print(figure_1_content)

print("\nSOURCE")
print("=" * 80)
print(figure_1_source)

print("\nNOTE")
print("=" * 80)
print(figure_1_note)

# Normalize Figure 1 labels

figure_1_labels = [
    "Import",
    "Export",
    "Transit (shipping)",
    "Supply chain initiation",
    "Supply chain termination",
    "Export dwell time",
    "Import dwell time",
    "Deliver empty to shipper",
    "Gate in full",
    "Load on board full",
    "Empty in depot available",
    "Gate out full",
    "Discharge full",
    "Empty returns",
    "Pickup",
    "Loading",
    "Discharge",
]

print(
    pd.DataFrame({
        "figure_number": 1,
        "label": figure_1_labels
    })
)

# Extract the Figure title without the "Figure N" prefix

figure_1_title = re.sub(
    r"^Figure\s+\d+\s*",
    "",
    figure_1_caption,
    flags=re.IGNORECASE
).strip()

figure_1_content = (
    "The figure illustrates the end-to-end phases of a maritime container "
    "supply chain, progressing from supply chain initiation through export, "
    "transit (shipping), and import to supply chain termination. "
    "On the export side, an empty container is delivered to the shipper, "
    "the full container is gated in and loaded on board, and the export "
    "dwell-time period is associated with the container's time at the "
    "export stage. The container then moves through the transit (shipping) "
    "phase before being discharged at the destination port. "
    "On the import side, the container is discharged and gated out, and "
    "the import dwell-time period is associated with the container's time "
    "at the import stage. The container is then transferred onward and "
    "the empty container is returned, marking supply chain termination. "
    "The figure also shows pickup, loading, and discharge operations along "
    "the container journey. "
    f"Note: {figure_1_note}"
)

print(figure_1_content)

figure_1_unit = {
    "unit_type": "figure",
    "figure_number": 1,
    "page_number": figure_1_page,
    "logical_unit": figure_1_title,
    "content": figure_1_content,
}

print(figure_1_unit)

# Extract Figure 2

figure_2 = captions_df[
    (captions_df["content_type"] == "figure") &
    (captions_df["number"] == 2)
].iloc[0]

figure_2_page = int(figure_2["page_number"])
figure_2_caption = figure_2["caption"]

page = doc[figure_2_page - 1]
text = page.get_text("text")

figure_2_raw = text.split(
    figure_2_caption,
    1
)[1].strip()

print(f"Figure: {figure_2['number']}")
print(f"Page: {figure_2_page}")
print(f"Caption: {figure_2_caption}")
print("\nFigure text:")
print("-" * 80)
print(figure_2_raw)

# Reconstruct Figure 2 from the extracted content

figure_2_title = re.sub(
    r"^Figure\s+\d+\s*",
    "",
    figure_2_caption,
    flags=re.IGNORECASE
).strip()


figure_2_structure = {
    "figure_number": 2,
    "logical_unit": figure_2_title,

    "phases": {
        "Export from origin": [
            {
                "milestone": "FWB",
                "description": "Electronic airway bill received from export forwarder",
            },
            {
                "milestone": "RCS",
                "description": "Shipment received from export forwarder (shipper)",
            },
            {
                "milestone": "DEP",
                "description": "Shipment loaded on booked flight and flight departure",
            },
        ],

        "Import to destination": [
            {
                "milestone": "ARR",
                "description": "Arrival of flight with shipment at destination airport",
            },
            {
                "milestone": "RCF",
                "description": "Shipment received from incoming flight and checked into a warehouse",
            },
            {
                "milestone": "NFD",
                "description": (
                    "Consignee or agent notified that the shipment, including "
                    "documentation, is ready for pickup and initiation of customs clearance"
                ),
            },
            {
                "milestone": "DLV",
                "description": (
                    "Handover of shipment to forwarder after customs clearance"
                ),
            },
        ],
    },

    "indicator_definition": {
        "text": (
            "The time difference between NFD and DLV milestones constitutes "
            "the LPI 2.0 aviation import dwell time indicator."
        ),
        "footnote": "a",
    },

    "footnotes": {
        "a": (
            "NFD is the notification sent by the carrier to the forwarder or third party "
            "that the shipment, including documentation, has arrived and is available "
            "for pickup. DLV marks the physical handover of the cargo. Customs inspection "
            "for air cargo shipments happens between events NFD and DLV, except for "
            "precleared shipments, for which the only processes happening between NFD "
            "and DLV are clearing agent payments of charges (e.g., storage, special "
            "handling fees, customs charges). Once these are clear and the customs "
            "status is clarified, DLV can commence."
        )
    },
}

figure_2_content = (
    "The figure describes milestones in the air cargo supply chain. "
    "For export from origin: "
    "FWB means electronic airway bill received from export forwarder; "
    "RCS means shipment received from export forwarder (shipper); "
    "DEP means shipment loaded on booked flight and flight departure. "
    "For import to destination: "
    "ARR means arrival of flight with shipment at destination airport; "
    "RCF means shipment received from incoming flight and checked into a warehouse; "
    "NFD means the consignee or agent is notified that the shipment, including "
    "documentation, is ready for pickup and initiation of customs clearance; "
    "DLV means handover of shipment to forwarder after customs clearance. "
    "The time difference between NFD and DLV milestones constitutes "
    "the LPI 2.0 aviation import dwell time indicator. "
    f"Footnote a: {figure_2_structure['footnotes']['a']}"
)

print(figure_2_content)

figure_2_unit = {
    "unit_type": "figure",
    "figure_number": 2,
    "page_number": figure_2_page,
    "logical_unit": figure_2_title,
    "content": figure_2_content,
}

print(figure_2_unit)

# Extract Figure 3

figure_3 = captions_df[
    (captions_df["content_type"] == "figure") &
    (captions_df["number"] == 3)
].iloc[0]

figure_3_page = int(figure_3["page_number"])
figure_3_caption = figure_3["caption"]

page = doc[figure_3_page - 1]
text = page.get_text("text")

figure_3_raw = text.split(
    figure_3_caption,
    1
)[1].strip()

print(f"Figure: {figure_3['number']}")
print(f"Page: {figure_3_page}")
print(f"Caption: {figure_3_caption}")
print("\nFigure text:")
print("-" * 80)
print(figure_3_raw)

# Reconstruct Figure 3

figure_3_title = re.sub(
    r"^Figure\s+\d+\s*",
    "",
    figure_3_caption,
    flags=re.IGNORECASE
).strip()


figure_3_structure = {
    "figure_number": 3,
    "logical_unit": figure_3_title,

    "event_categories": {
        "Exporting events": [
            {
                "message_id": "EMA",
                "description": "Posting/collection",
            },
            {
                "message_id": "EMB",
                "description": "Arrival at outward office of exchange",
            },
            {
                "message_id": "EMC",
                "description": "Departure from outward office of exchange",
            },
        ],

        "Transit events": [
            {
                "message_id": "EMJ",
                "description": "Arrival at transit office of exchange",
            },
            {
                "message_id": "EMK",
                "description": "Departure from transit office of exchange",
            },
        ],

        "Importing events": [
            {
                "message_id": "EMD",
                "description": "Arrival at inward office of exchange",
            },
            {
                "message_id": "EME",
                "description": "Held by import customs",
            },
            {
                "message_id": "EMF",
                "description": "Departure from inward office of exchange",
            },
            {
                "message_id": "EMG",
                "description": "Arrival at delivery office",
            },
            {
                "message_id": "EMH",
                "description": "Attempted/unsuccessful delivery",
            },
            {
                "message_id": "EMI",
                "description": "Final delivery",
            },
        ],
    },

    "indicator_definition": (
        "The elapsed time between EMD and EMH/EMI is the delivery time "
        "at destination economy used to create the LPI 2.0 postal delivery indicator."
    ),
}

# Build Figure 3 semantic content

figure_3_content = (
    f"{figure_3_title}. "
    "The exporting events are: "
    "EMA means posting/collection; "
    "EMB means arrival at outward office of exchange; "
    "EMC means departure from outward office of exchange. "
    "The transit events are: "
    "EMJ means arrival at transit office of exchange; "
    "EMK means departure from transit office of exchange. "
    "The importing events are: "
    "EMD means arrival at inward office of exchange; "
    "EME means held by import customs; "
    "EMF means departure from inward office of exchange; "
    "EMG means arrival at delivery office; "
    "EMH means attempted/unsuccessful delivery; "
    "EMI means final delivery. "
    f"{figure_3_structure['indicator_definition']}"
)

print(figure_3_content)

# Store Figure 3 as a Figure unit

figure_3_unit = {
    "unit_type": "figure",
    "figure_number": 3,
    "page_number": figure_3_page,
    "logical_unit": figure_3_title,
    "content": figure_3_content,
}

print(figure_3_unit)

# Extract Figure 4

figure_4 = captions_df[
    (captions_df["content_type"] == "figure") &
    (captions_df["number"] == 4)
].iloc[0]

figure_4_page = int(figure_4["page_number"])
figure_4_caption = figure_4["caption"]

page = doc[figure_4_page - 1]
text = page.get_text("text")

figure_4_raw = text.split(
    figure_4_caption,
    1
)[1].strip()

print(f"Figure: {figure_4['number']}")
print(f"Page: {figure_4_page}")
print(f"Caption: {figure_4_caption}")
print("\nFigure text:")
print("-" * 80)
print(figure_4_raw)

# Reconstruct Figure 4

figure_4_title = re.sub(
    r"^Figure\s+\d+\s*",
    "",
    figure_4_caption,
    flags=re.IGNORECASE
).strip()


# Figure 4 content ends at its Source line
figure_4_content = figure_4_raw.split(
    "Source: World Bank.",
    1
)[0].strip()


figure_4_structure = {
    "figure_number": 4,
    "logical_unit": figure_4_title,

    "port_call_sequence": [
        "Previous port call",
        "Arrival to port",
        "Unloading of containers at terminal",
        "Loading of containers at terminal",
        "Departure from port",
        "Next port call",
    ],

    "time_measures": [
        "Vessel’s port turnaround time",
        "Container export dwell time",
        "Container import dwell time",
    ],
}

print(figure_4_structure)

figure_4_content = (
    "The figure illustrates the relationship between vessel port turnaround "
    "time and container dwell-time measures across a port call. "
    "The vessel moves from the previous port call to arrival at the port, "
    "followed by unloading of containers at the terminal, loading of "
    "containers at the terminal, departure from the port, and the next "
    "port call. The vessel's port turnaround time is represented as the "
    "interval between the latest arrival at port and the earliest departure "
    "from port. Within the same port-call sequence, container import dwell "
    "time and container export dwell time represent the corresponding "
    "container dwell periods associated with unloading and loading "
    "operations at the terminal."
)

print(figure_4_content)

figure_4_unit = {
    "unit_type": "figure",
    "figure_number": 4,
    "page_number": figure_4_page,
    "logical_unit": figure_4_title,
    "content": figure_4_content,
}
print(figure_4_unit)

# Extract Figure 5

figure_5 = captions_df[
    (captions_df["content_type"] == "figure") &
    (captions_df["number"] == 5)
].iloc[0]

figure_5_page = int(figure_5["page_number"])
figure_5_caption = figure_5["caption"]

page = doc[figure_5_page - 1]
text = page.get_text("text")

figure_5_raw = text.split(
    figure_5_caption,
    1
)[1].strip()

print(f"Figure: {figure_5['number']}")
print(f"Page: {figure_5_page}")
print(f"Caption: {figure_5_caption}")
print("\nFigure text:")
print("-" * 80)
print(figure_5_raw)

# Reconstruct Figure 5

figure_5_title = re.sub(
    r"^Figure\s+\d+\s*",
    "",
    figure_5_caption,
    flags=re.IGNORECASE
).strip()


figure_5_structure = {
    "figure_number": 5,
    "logical_unit": figure_5_title,
    "route": "Surabaya (Indonesia) → Bamako (Mali)",

    "events": [
        {
            "date": "May 28, 12:14 a.m.",
            "location": "Surabaya",
            "event": "Container arrives at port",
            "observation": "Export dwell time at Surabaya: 3.6 days",
        },
        {
            "date": "May 31, 2:12 p.m.",
            "location": "Surabaya",
            "event": "Container loaded on ship",
            "observation": "Maritime lead time (including two transshipments): 53 days",
        },
        {
            "date": "June 3, 2:22 a.m.",
            "location": "Singapore",
            "event": "Container discharged from ship",
            "observation": None,
        },
        {
            "date": "June 8, 8:52 p.m.",
            "location": "Singapore",
            "event": "Container loaded on ship",
            "observation": None,
        },
        {
            "date": "June 30, 6:18 p.m.",
            "location": "TangerMed",
            "event": "Container discharged from ship",
            "observation": None,
        },
        {
            "date": "July 1, 8:16 p.m.",
            "location": "TangerMed",
            "event": "Container loaded on ship",
            "observation": None,
        },
        {
            "date": "July 23, 10:49 a.m.",
            "location": "Dakar",
            "event": "Container discharged from ship",
            "observation": "Import dwell time at Dakar: 76 days",
        },
        {
            "date": "October 6, 10:53 p.m.",
            "location": "Dakar",
            "event": "Container transferred to destination",
            "observation": None,
        },
        {
            "date": "October 16, 10:00 a.m.",
            "location": "Bamako",
            "event": "Container arrived at destination",
            "observation": "Corridor lead time Dakar–Bamako: 9.5 days",
        },
        {
            "date": "October 18, 10:00 a.m.",
            "location": "Bamako",
            "event": "Container sent to consignee",
            "observation": "Import dwell time at destination: 2 days",
        },
    ],

    "derived_values": {
        "export_dwell_time_surabaya_days": 3.6,
        "maritime_lead_time_days": 53,
        "import_dwell_time_dakar_days": 76,
        "corridor_lead_time_dakar_bamako_days": 9.5,
        "import_dwell_time_destination_days": 2,
    },

    "calculation": "76 + 9.5 + 2 = 87.5 days",
}

# Build the semantic content representation

event_text = " ".join(
    (
        f"On {event['date']} at {event['location']}, "
        f"{event['event']}."
        + (
            f" {event['observation']}."
            if event["observation"]
            else ""
        )
    )
    for event in figure_5_structure["events"]
)

figure_5_content = (
    f"The figure presents a worked example of a container voyage from "
    f"{figure_5_structure['route']}. "
    f"{event_text} "
    "The example therefore illustrates how the voyage is divided into "
    "export dwell time, maritime lead time, import dwell time at Dakar, "
    "corridor lead time from Dakar to Bamako, and import dwell time at "
    "the final destination. "
    f"The calculation shown is "
    f"{figure_5_structure['calculation']}."
)

print(figure_5_content)

# Store Figure 5 as a worked-example unit

figure_5_unit = {
    "unit_type": "worked_example",
    "figure_number": 5,
    "page_number": figure_5_page,
    "logical_unit": figure_5_title,
    "content": figure_5_content,
}

print(figure_5_unit)

# Extract Figure 6 raw text

figure_6 = captions_df[
    (captions_df["content_type"] == "figure") &
    (captions_df["number"] == 6)
].iloc[0]

figure_6_page = int(figure_6["page_number"])
figure_6_caption = figure_6["caption"]

page = doc[figure_6_page - 1]
text = page.get_text("text")

figure_6_raw = text.split(
    figure_6_caption,
    1
)[1].strip()

print(f"Figure: {figure_6['number']}")
print(f"Page: {figure_6_page}")
print(f"Caption: {figure_6_caption}")
print("\nFigure text:")
print("-" * 80)
print(figure_6_raw)

# Reconstruct Figure 6 from the visual relationships

figure_6_title = re.sub(
    r"^Figure\s+\d+\s*",
    "",
    figure_6_caption,
    flags=re.IGNORECASE
).strip()


figure_6_structure = {
    "figure_number": 6,
    "logical_unit": figure_6_title,

    "port_events": [
        "Arrival at port",
        "Departure from port",
    ],

    "turnaround_time": {
        "start": "Latest arrival at port",
        "end": "Earliest departure from port",
    },

    "surrounding_activities": [
        "Anchoring and waiting outside port vicinity",
        "Anchoring and waiting inside port vicinity",
        "Pilot on board/tugging",
    ],

    "geofenced_events": (
        "Arrivals to and departures from the geofenced area "
        "may occur in any sequence or number."
    ),
}

figure_6_content = (
    "The figure illustrates the elements used to measure ship turnaround time. "
    "A ship arrives at the port and later departs from the port, while activities "
    "around the port vicinity may include anchoring and waiting inside the port "
    "vicinity, anchoring and waiting outside the port vicinity, and pilot "
    "on board/tugging. "
    "The turnaround-time interval is defined from the latest arrival at port "
    "to the earliest departure from port. "
    "The figure also indicates that arrivals to and departures from the "
    "geofenced area may occur in any sequence or number."
)

print(figure_6_content)

figure_6_unit = {
    "unit_type": "figure",
    "figure_number": 6,
    "page_number": figure_6_page,
    "logical_unit": figure_6_title,
    "content": figure_6_content,
}

print(figure_6_unit)


# %% 3.3 Abbreviations (page 7)
# Page 7 stays outside the body pipeline (its Acknowledgements text is not retrieval
# content), but its Abbreviations table (LLDC, B2B, UPU, ...) is: it answers
# "what does X stand for" questions directly.
#
# The table is read from the PDF words. Every line below the heading is a row, and a
# row is split into the abbreviation and its meaning at the first wide horizontal gap
# (words inside one cell are only about 2 points apart, the two columns are 19-33
# points apart). The table becomes one `definitions` unit, the same unit type FBL
# uses for its Definitions clause.

# =========================================================
# 3.3 Extract the Abbreviations table (page 7)
# =========================================================

import re


def _clean_cell_text(text):
    # Local on purpose: the shared text cleaner is only defined later, in section 4.2.
    return re.sub(r"\s+", " ", text.replace("\xad", "")).strip()


def extract_abbreviations(words, heading="Abbreviations", column_gap=10.0, row_tolerance=3.0):
    # Parse a two-column abbreviation table from PyMuPDF `page.get_text("words")`
    # tuples: (x0, y0, x1, y1, text, ...).
    headings = [w for w in words if w[4] == heading]

    if len(headings) != 1:
        raise ValueError(f"Expected exactly one '{heading}' heading; found {len(headings)}.")

    heading_bottom = headings[0][3]

    below = sorted(
        (w for w in words if w[1] >= heading_bottom),
        key=lambda w: (w[1], w[0]),
    )

    lines, current, current_y = [], [], None

    for word in below:
        if current_y is None or abs(word[1] - current_y) <= row_tolerance:
            current.append(word)
            current_y = word[1] if current_y is None else current_y
        else:
            lines.append(current)
            current, current_y = [word], word[1]

    if current:
        lines.append(current)

    rows = []

    for line in lines:
        line = sorted(line, key=lambda w: w[0])

        split = next(
            (i for i in range(1, len(line)) if line[i][0] - line[i - 1][2] > column_gap),
            None,
        )

        if split is None:
            raise ValueError(
                f"Could not split an abbreviation row into two columns: {[w[4] for w in line]}"
            )

        rows.append({
            "abbreviation": _clean_cell_text(" ".join(w[4] for w in line[:split])),
            "meaning": _clean_cell_text(" ".join(w[4] for w in line[split:])),
        })

    return rows


abbreviations = extract_abbreviations(doc[6].get_text("words"))

assert abbreviations, "No abbreviations were extracted."
assert all(row["abbreviation"] and row["meaning"] for row in abbreviations)

abbreviations_unit = {
    "unit_id": "AB1",
    "unit_type": "definitions",
    "logical_unit": "Abbreviations",
    "content": "Abbreviations\n" + "\n".join(
        f"{row['abbreviation']}: {row['meaning']}" for row in abbreviations
    ),
    "section": "Abbreviations",
    "subsection": None,
    "page_start": 7,
    "page_end": 7,
}

print(pd.DataFrame(abbreviations))
print(abbreviations_unit["content"])


# %% 4. Extract Remaining Body Text
# The structured-content extraction stage has already handled the Tables,
# Figures, and Worked Examples that belong to the retrieval corpus.
#
# Figures 7 and 8 (the Egypt example on page 29) are deliberately **not**
# extracted as structured units. Their blocks are simply removed from the body
# text, like every other Figure region.
#
# We now extract the remaining substantive body text from retrieval-worthy pages.
#
# The body-text extraction must avoid duplicating content already represented
# as structured units, while preserving:
#
# - Paragraphs
# - Section headings
# - Footnotes (kept separately, linked to the block that references them)
# - Mathematical expressions
# - Other substantive prose
#
# Steps in this section:
#
# 1. Locate body blocks (drop repeated headers, page numbers, Figure/Table regions, Source/Note lines)
# 2. Clean typographic artifacts (soft hyphens, non-breaking hyphens, zero-width spaces)
# 3. Separate footnotes from the body and strip their reference markers
# 4. Drop blocks that are already represented inside a structured unit
# 5. Audit the result
#
# No paragraph reconstruction or chunking happens in this section.
#
# ## 4.1 Structural Boundaries

# =========================================================
# 4.1 Build generic structural boundaries
# =========================================================

def clean_block_text(text):
    text = text.replace("\x00", " ")
    return re.sub(r"\s+", " ", text).strip()


def get_text_blocks(page):
    """
    Return text blocks in their natural PDF reading order.
    """
    blocks = []

    for block_index, block in enumerate(page.get_text("blocks")):

        x0, y0, x1, y1, raw_text, *_ = block

        text = clean_block_text(raw_text)

        if not text:
            continue

        blocks.append({
            "block_index": block_index,
            "bbox": fitz.Rect(x0, y0, x1, y1),
            "text": text,
        })

    return blocks


def get_figure_block_ranges(page, page_number, captions_df):
    """
    Identify Figure block ranges using confirmed captions and
    the next Source:/Note: block.
    """

    blocks = get_text_blocks(page)

    page_figures = (
        captions_df[
            (captions_df["page_number"] == page_number)
            & (captions_df["content_type"] == "figure")
        ]
        .sort_values("number")
    )

    figure_ranges = []

    for _, figure in page_figures.iterrows():

        caption = clean_block_text(
            str(figure["caption"])
        )

        # Find the block containing the confirmed caption
        caption_index = None

        for i, block in enumerate(blocks):

            if caption.lower() in block["text"].lower():
                caption_index = i
                break

        if caption_index is None:
            continue

        # Find the first Source/Note block after the caption
        end_index = len(blocks) - 1

        for j in range(caption_index + 1, len(blocks)):

            text_lower = blocks[j]["text"].lower()

            if (
                text_lower.startswith("source:")
                or text_lower.startswith("note:")
            ):
                end_index = j
                break

        figure_ranges.append({
            "figure_number": int(figure["number"]),
            "start_index": caption_index,
            "end_index": end_index,
        })

    return blocks, figure_ranges

test_pages = [13, 14, 17, 24, 29]

for page_number in test_pages:

    page = doc[page_number - 1]

    blocks, figure_ranges = get_figure_block_ranges(
        page=page,
        page_number=page_number,
        captions_df=captions_df,
    )

    print("=" * 100)
    print(f"PAGE {page_number}")
    print("FIGURE RANGES:", figure_ranges)

    for figure_range in figure_ranges:

        start = figure_range["start_index"]
        end = figure_range["end_index"]

        print(
            f"\nFigure {figure_range['figure_number']} "
            f"→ blocks {start} to {end}"
        )

        for block in blocks[start:end + 1]:
            print(
                f"  [{block['block_index']}] "
                f"{block['text'][:150]}"
            )


# %% 4.2 Clean Text Artifacts
# PyMuPDF keeps soft hyphens (`U+00AD`) that mark possible line-break points, so
# after whitespace normalization a word such as *measures* appears as `mea­ sures`.
# Non-breaking hyphens (`U+2011`) and zero-width spaces are also present.
#
# `clean_body_text()` removes these so that the text is searchable and embeds
# cleanly. The test cases below use strings taken from the real extraction output.

# =========================================================
# 4.2 Text cleaning
# =========================================================

import re


def clean_body_text(text: str) -> str:
    """
    Remove typographic artifacts that PDF extraction leaves in body text.

    - Soft hyphen (U+00AD): a possible line-break point. The soft hyphen and
      the whitespace that follows it are removed, which rejoins the word.
    - Non-breaking hyphen (U+2011) becomes a normal hyphen.
    - Zero-width space (U+200B) is removed.
    - Non-breaking space (U+00A0) becomes a normal space.
    """
    if not text:
        return text

    text = text.replace("\x00", " ")
    text = text.replace("\u200b", "")
    text = text.replace("\u2011", "-")
    text = text.replace("\xa0", " ")

    text = re.sub(r"\xad\s*", "", text)   # rejoin words split at a soft hyphen
    text = re.sub(r"\s+", " ", text)

    return text.strip()


# ---------------------------------------------------------
# Unit tests (strings copied from the real page 8 / 15 output)
# ---------------------------------------------------------

_cleaning_tests = [
    ("which mea\xad sures the time",
     "which measures the time"),
    ("supplement the core indi\xad cators include",
     "supplement the core indicators include"),
    ("thus prox\xad ies the performance",
     "thus proxies the performance"),
    ("two dimensions\xad—\xadconnectivity and time\xad—\xadacross maritime",
     "two dimensions—connectivity and time—across maritime"),
    ("large-\xadscale tracking data",
     "large-scale tracking data"),
    ("vessel-\xad level tracking",
     "vessel-level tracking"),
    ("a data\u2011driven framework",
     "a data-driven framework"),
    ("export-\xadimport imbal\xad ances",
     "export-import imbalances"),
    ("a\u200bb  c\xa0d",
     "ab c d"),
]

for raw, expected in _cleaning_tests:
    result = clean_body_text(raw)
    assert result == expected, f"clean_body_text failed:\n  got      {result!r}\n  expected {expected!r}"

print(f"clean_body_text: {len(_cleaning_tests)}/{len(_cleaning_tests)} tests passed")


# %% 4.3 Extract Body Blocks
# Final body-block extractor. It removes, in this order: repeated headers and page
# numbers, Figure regions, Table regions, Table captions, and Source/Note lines.
# The text of every kept block is cleaned with `clean_body_text()`.
#
# This replaces the three earlier experimental versions of the function.

# =========================================================
# 4.3 Extract body blocks (final version)
# =========================================================

HEADER_PHRASES = (
    "THE NEW LOGISTICS PERFORMANCE INDICATORS 2.0",
    "METHODOLOGY AND USER GUIDE",
)

PAGE_NUMBER_PATTERN = re.compile(r"^(?:\d+|[ivxlcdm]+)$")

HEADER_ZONE_Y = 80  # points from the top of the page


def extract_body_blocks(
    doc,
    page_number,
    captions_df,
):
    page = doc[page_number - 1]
    blocks = get_text_blocks(page)

    page_elements = captions_df[
        captions_df["page_number"] == page_number
    ].copy()

    # -----------------------------------------------------
    # Figure block ranges (caption -> Source/Note block)
    # -----------------------------------------------------

    _, figure_ranges = get_figure_block_ranges(
        page=page,
        page_number=page_number,
        captions_df=captions_df,
    )

    figure_block_indices = set()

    for figure_range in figure_ranges:
        for index in range(
            figure_range["start_index"],
            figure_range["end_index"] + 1,
        ):
            figure_block_indices.add(index)

    # -----------------------------------------------------
    # Table regions + Table captions
    # -----------------------------------------------------

    table_regions = []
    table_caption_bboxes = []

    table_elements = page_elements[
        page_elements["content_type"] == "table"
    ]

    if not table_elements.empty:

        for table in page.find_tables().tables:
            table_regions.append(fitz.Rect(table.bbox))

        for _, row in table_elements.iterrows():
            matches = page.search_for(str(row["caption"]))

            if matches:
                table_caption_bboxes.append(matches[0])

    # -----------------------------------------------------
    # Keep the remaining blocks
    # -----------------------------------------------------

    body_blocks = []

    for position, block in enumerate(blocks):

        text = block["text"]
        bbox = block["bbox"]

        # Repeated header / page number
        if bbox.y0 < HEADER_ZONE_Y:

            if any(phrase in text.upper() for phrase in HEADER_PHRASES):
                continue

            if PAGE_NUMBER_PATTERN.fullmatch(text.lower()):
                continue

        # Figure content
        if position in figure_block_indices:
            continue

        # Table content
        if any(bbox.intersects(region) for region in table_regions):
            continue

        # Table captions
        if any(bbox.intersects(caption_bbox) for caption_bbox in table_caption_bboxes):
            continue

        # Structural Source / Note lines
        if text.lower().startswith(("source:", "note:")):
            continue

        cleaned = clean_body_text(text)

        if not cleaned:
            continue

        body_blocks.append({
            "page_number": page_number,
            "block_index": block["block_index"],
            "x0": round(bbox.x0, 2),
            "y0": round(bbox.y0, 2),
            "x1": round(bbox.x1, 2),
            "y1": round(bbox.y1, 2),
            "text": cleaned,
        })

    return body_blocks


# %% 4.4 Separate Footnotes
# Footnotes are detected from the PDF's actual block layout rather than from a
# simple bottom-of-page cutoff. A page can contain several numbered notes in one
# PDF text block, and a single note can continue across adjacent blocks.
#
# The separator therefore:
#
# 1. Extracts numbered `N.` entries independently from physical block boundaries.
# 2. Detects inline citation markers in other blocks on the same page.
# 3. Treats a numbered block as a footnote block only when at least one of its
#    entries has an external citation; once validated, all numbered entries in
#    that same block are preserved as footnotes.
# 4. Preserves wrapped continuation blocks using conservative x/y proximity.
# 5. Removes only validated citation markers from body text and stores the
#    corresponding numbers in `footnote_refs`.
# 6. Leaves unmatched numbered blocks and orphan markers in
#    `footnote_issues_df` for review rather than guessing.
#
# This is important for page 15: the `13` marker belongs to the turnaround-time
# paragraph, and that relationship must survive into `paragraphs_df`.

# =========================================================
# 4.4 Footnote separation
# =========================================================

# A PDF text block may contain:
#   - one footnote entry, or
#   - several footnote entries in the same block.
#
# It may also continue the same footnote across adjacent blocks.
#
# We therefore detect numbered footnote entries independently from
# the physical block boundaries, then use page-local marker references
# to decide whether those entries really are footnotes.

FOOTNOTE_ENTRY = re.compile(r"(?<!\S)([1-9]\d{0,2})\.\s+(?=\S)")

# Marker examples seen in the PDF:
#   "...vicinity.13 Turnaround..."
#   "...logistics.4"
#   "...Connecting to Compete 2025,5"
#
# The punctuation pattern keeps the original numeric guard so that
# times such as 12:14 and numeric literals are not damaged.
MARKER_AFTER_PUNCT = re.compile(
    r"(?<!\d[.,:])(?<=[.,;:)\]’”])([1-9]\d{0,2})(?=\s|$|[,;:])"
)

# In this document the comma-attached form is used for citations such as
# "2025,5". It is intentionally enabled only for numbers that were also
# observed as numbered footnote entries on the same page. This prevents
# values such as "1,754" or "5,916" from becoming false footnote markers.
MARKER_AFTER_COMMA = re.compile(
    r"(?<=\d,)([1-9]\d{0,2})(?=\s|$|[.;:)\]])"
)


def extract_footnote_entries(text):
    """
    Return numbered entries embedded in a text block.

    Example:
        "2. First note. 3. Second note."
    becomes two entries.

    The numbering pattern is deliberately limited to 1-3 digits, which
    excludes ordinary years such as 2024.
    """
    matches = list(FOOTNOTE_ENTRY.finditer(text))
    entries = []

    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)

        entries.append({
            "number": int(match.group(1)),
            "start": match.start(),
            "text": text[match.end():end].strip(),
        })

    return entries


def find_footnote_markers(text, known_numbers=None):
    """
    Find candidate inline footnote markers.

    known_numbers is used only for the comma-attached form (e.g. 2025,5).
    This keeps numeric values such as 1,754 from being treated as markers.
    """
    markers = []

    for match in MARKER_AFTER_PUNCT.finditer(text):
        markers.append(int(match.group(1)))

    if known_numbers:
        for match in MARKER_AFTER_COMMA.finditer(text):
            number = int(match.group(1))

            if number in known_numbers:
                markers.append(number)

    return markers


def strip_footnote_marker(text, number):
    """Remove one occurrence of marker `number` without touching numeric literals."""
    for pattern in (MARKER_AFTER_PUNCT, MARKER_AFTER_COMMA):
        for match in pattern.finditer(text):

            if int(match.group(1)) != number:
                continue

            # The comma form is only ever used for accepted footnote refs.
            stripped = text[:match.start()] + text[match.end():]
            return re.sub(r"\s+", " ", stripped).strip(), True

    return text, False


def is_footnote_continuation(previous_block, current_block):
    """
    Detect a block that is a visual continuation of a footnote block.

    The PDF places wrapped footnotes in adjacent blocks with nearly the
    same x-position and a small vertical gap. The tolerance is intentionally
    conservative so that the next reading column is not swallowed.
    """
    if "x0" not in previous_block or "x0" not in current_block:
        return False

    dx = abs(float(current_block["x0"]) - float(previous_block["x0"]))
    dy = float(current_block["y0"]) - float(previous_block["y0"])

    return 0 <= dy <= 60 and dx <= 30


def separate_footnotes(page_blocks):
    """
    Split one page's body blocks into (body_blocks, footnotes, issues).

    A footnote can span:
      1. several numbered entries in one PDF block, or
      2. several adjacent PDF blocks.

    A numbered entry is accepted as a footnote only when its number is
    referenced by marker text in another block on the same page.
    """
    if not page_blocks:
        return [], [], []

    # -----------------------------------------------------
    # 1. Extract all numbered entries first.
    # -----------------------------------------------------

    entries_by_position = {}

    for position, block in enumerate(page_blocks):
        entries = extract_footnote_entries(block["text"])

        if entries:
            entries_by_position[position] = entries

    known_numbers = {
        entry["number"]
        for entries in entries_by_position.values()
        for entry in entries
    }

    # -----------------------------------------------------
    # 2. Locate candidate inline markers.
    # -----------------------------------------------------

    marker_positions = {}

    for position, block in enumerate(page_blocks):

        for number in find_footnote_markers(
            block["text"],
            known_numbers=known_numbers,
        ):
            marker_positions.setdefault(number, []).append(position)

    # -----------------------------------------------------
    # 3. Validate numbered entries using external citations.
    #
    # If one entry in a block is confirmed as a footnote, treat the
    # other numbered entries in the same block as footnotes too.
    # This is required for blocks such as "2. ... 3. ... 4. ...".
    # -----------------------------------------------------

    footnote_block_positions = set()
    accepted_numbers = set()
    ref_at = {}
    issues = []

    for position, entries in entries_by_position.items():

        has_external_reference = any(
            any(citing_position != position
                for citing_position in marker_positions.get(
                    entry["number"], []
                ))
            for entry in entries
        )

        if not has_external_reference:
            for entry in entries:
                issues.append({
                    "page_number": page_blocks[position]["page_number"],
                    "issue": "numbered_block_without_marker",
                    "number": entry["number"],
                    "text": entry["text"][:120],
                })
            continue

        footnote_block_positions.add(position)

        # Once a numbered block is validated as a footnote block, every
        # numbered entry inside that same block belongs to the footnote
        # region. Some entries may not have an inline citation detected
        # independently, but they are still genuine footnote text.
        for entry in entries:

            number = entry["number"]
            accepted_numbers.add(number)

            citing_positions = [
                citing_position
                for citing_position in marker_positions.get(number, [])
                if citing_position != position
            ]

            if citing_positions:
                # Keep one stable reference block for the footnote record.
                ref_at.setdefault(citing_positions[0], []).append(number)

    # -----------------------------------------------------
    # 4. Extend footnote regions across wrapped continuation blocks.
    # -----------------------------------------------------

    continuation_positions = set()
    active_footnote_position = None

    for position, block in enumerate(page_blocks):

        if position in footnote_block_positions:
            active_footnote_position = position
            continue

        if active_footnote_position is None:
            continue

        previous_block = page_blocks[active_footnote_position]

        if is_footnote_continuation(previous_block, block):
            continuation_positions.add(position)
            active_footnote_position = position
        else:
            active_footnote_position = None

    # -----------------------------------------------------
    # 5. Any marker that still has no validated footnote block
    #    remains an explicit review item.
    # -----------------------------------------------------

    for number, positions in marker_positions.items():

        if number in accepted_numbers:
            continue

        for position in positions:
            issues.append({
                "page_number": page_blocks[position]["page_number"],
                "issue": "marker_without_footnote_block",
                "number": number,
                "text": page_blocks[position]["text"][:120],
            })

    # -----------------------------------------------------
    # 6. Build outputs.
    # -----------------------------------------------------

    body_blocks = []
    footnotes = []

    for position, block in enumerate(page_blocks):

        # Confirmed footnote entry block
        if position in footnote_block_positions:

            entries = entries_by_position[position]

            # Emit every numbered entry from a validated footnote block.
            # If no inline citation was detected for a particular entry,
            # ref_block_index is left as None rather than inventing a link.
            for entry in entries:

                number = entry["number"]
                citing_positions = [
                    citing_position
                    for citing_position in marker_positions.get(number, [])
                    if citing_position != position
                ]

                footnotes.append({
                    "page_number": block["page_number"],
                    "footnote_number": number,
                    "block_index": block["block_index"],
                    "ref_block_index": (
                        page_blocks[citing_positions[0]]["block_index"]
                        if citing_positions
                        else None
                    ),
                    "y0": block["y0"],
                    "text": entry["text"],
                })

            continue

        # Wrapped continuation of a confirmed footnote block
        if position in continuation_positions and footnotes:
            continuation_text = block["text"].strip()

            if continuation_text:
                footnotes[-1]["text"] = (
                    f"{footnotes[-1]['text']} {continuation_text}"
                ).strip()

            continue

        # Regular body block
        record = dict(block)
        record["footnote_refs"] = []

        for number in sorted(set(ref_at.get(position, [])), reverse=True):

            record["text"], removed = strip_footnote_marker(
                record["text"],
                number,
            )

            if removed:
                record["footnote_refs"].append(number)

        record["footnote_refs"] = sorted(record["footnote_refs"])
        body_blocks.append(record)

    return body_blocks, footnotes, issues


# ---------------------------------------------------------
# Unit test 1: page-15-like single footnotes + time/number guards
# ---------------------------------------------------------

_test_page = [
    {"page_number": 15, "block_index": 0, "x0": 90.0, "y0": 100.0,
     "text": "excluding waiting time at anchorage outside the port vicinity.13 Turnaround time is calculated as in LPI 2.0 for 1,000 ships."},
    {"page_number": 15, "block_index": 1, "x0": 90.0, "y0": 300.0,
     "text": "until it is loaded on the vessel (from gate in full to load on board full"},
    {"page_number": 15, "block_index": 2, "x0": 90.0, "y0": 650.0,
     "text": "13. Turnaround time is a standard key performance indicator used in the industry."},
    {"page_number": 15, "block_index": 3, "x0": 90.0, "y0": 100.0,
     "text": "events in figure 1). Export dwell time reflects several constraints."},
    {"page_number": 15, "block_index": 4, "x0": 90.0, "y0": 500.0,
     "text": "1. A genuine numbered list item that has no marker on this page."},
    {"page_number": 15, "block_index": 5, "x0": 90.0, "y0": 520.0,
     "text": "On May 28, 12:14 a.m. the ship arrived at the port.14 The next day it left."},
    {"page_number": 15, "block_index": 6, "x0": 90.0, "y0": 740.0,
     "text": "14. All times are local."},
]

_body, _notes, _issues = separate_footnotes(_test_page)

assert [b["block_index"] for b in _body] == [0, 1, 3, 4, 5], \
    "single-footnote block handling failed"

assert [n["footnote_number"] for n in _notes] == [13, 14]
assert _notes[0]["ref_block_index"] == 0
assert _notes[1]["ref_block_index"] == 5

assert "12:14 a.m." in _body[4]["text"]
assert "port. The next day" in _body[4]["text"]
assert "vicinity. Turnaround" in _body[0]["text"]

assert _body[0]["footnote_refs"] == [13]
assert _body[4]["footnote_refs"] == [14]

assert "LPI 2.0" in _body[0]["text"]
assert "1,000 ships" in _body[0]["text"]

assert any(
    issue["issue"] == "numbered_block_without_marker"
    and issue["number"] == 1
    for issue in _issues
)


# ---------------------------------------------------------
# Unit test 2: page-12-like multi-footnote block + 2025,5
# ---------------------------------------------------------

_multi_note_page = [
    {"page_number": 12, "block_index": 2, "x0": 90.0, "y0": 160.0,
     "text": "The core components of logistics performance are time, reliability, and cost.2"},
    {"page_number": 12, "block_index": 3, "x0": 90.0, "y0": 470.0,
     "text": "The LPI 2.0 cover three logistics modes and global trade by value.3 Tracking data are available only for maritime, aviation, and postal logistics.4"},
    {"page_number": 12, "block_index": 4, "x0": 90.0, "y0": 610.0,
     "text": "2. Hummels, Lugovskyy, and Skiba 2009. 3. About 46 percent of global goods trade by value is moved in maritime containers. 4. The LPI 2.0 do not cover road and rail. 5. Arvis et al. 2026."},
    {"page_number": 12, "block_index": 5, "x0": 90.0, "y0": 500.0,
     "text": "The main findings for 2023 and 2024 are discussed in Connecting to Compete 2025,5 and data are available online."},
    {"page_number": 12, "block_index": 6, "x0": 90.0, "y0": 350.0,
     "text": "The core maritime indicator is based on direct services.6 The core aviation indicator uses direct cargo flights.7 The core postal indicator measures inbound and outbound postal connections.8"},
    {"page_number": 12, "block_index": 7, "x0": 90.0, "y0": 720.0,
     "text": "6. A liner shipping container service is a scheduled maritime transport service. 7. Refers to direct flights. 8. Postal connectivity is the average of inbound and outbound partners."},
]

_body, _notes, _issues = separate_footnotes(_multi_note_page)

assert [n["footnote_number"] for n in _notes] == [2, 3, 4, 5, 6, 7, 8], \
    "multi-footnote block was not split correctly"

assert _issues == [], \
    f"unexpected issues in multi-footnote test: {_issues}"

assert _body[0]["footnote_refs"] == [2]
assert _body[1]["footnote_refs"] == [3, 4]
assert _body[2]["footnote_refs"] == [5]
assert _body[3]["footnote_refs"] == [6, 7, 8]

assert "2025" in _body[2]["text"]
assert "2025,5" not in _body[2]["text"]
assert "Connecting to Compete 2025, and data" in _body[2]["text"]


# ---------------------------------------------------------
# Unit test 3: wrapped continuation block
# ---------------------------------------------------------

_continuation_page = [
    {"page_number": 18, "block_index": 0, "x0": 90.0, "y0": 600.0,
     "text": "The LLDC indicator ends here.14"},
    {"page_number": 18, "block_index": 1, "x0": 90.0, "y0": 653.0,
     "text": "14. Corridor lead time does not provide information about multimodal transfers. 15. B2C flows differ from B2B flows."},
    {"page_number": 18, "block_index": 2, "x0": 108.0, "y0": 678.0,
     "text": "International e-commerce is interconnected with postal services."},
    {"page_number": 18, "block_index": 3, "x0": 90.0, "y0": 400.0,
     "text": "The postal indicators are described below.15"},
]

_body, _notes, _issues = separate_footnotes(_continuation_page)

assert [n["footnote_number"] for n in _notes] == [14, 15]
assert _notes[1]["text"].endswith("International e-commerce is interconnected with postal services.")
assert _issues == []
assert _body[0]["footnote_refs"] == [14]
assert _body[1]["footnote_refs"] == [15]

print("separate_footnotes: all tests passed")


# %% 4.5 Run Extraction Across Retrieval Pages

# =========================================================
# 4.5 Run across all retrieval-worthy pages
# =========================================================

all_body_blocks = []
all_footnotes = []
all_footnote_issues = []

for page_number in content_pages_df["page_number"]:

    page_blocks = extract_body_blocks(
        doc=doc,
        page_number=int(page_number),
        captions_df=captions_df,
    )

    page_body, page_footnotes, page_issues = separate_footnotes(page_blocks)

    all_body_blocks.extend(page_body)
    all_footnotes.extend(page_footnotes)
    all_footnote_issues.extend(page_issues)


body_blocks_raw_df = pd.DataFrame(all_body_blocks)

footnotes_df = pd.DataFrame(
    all_footnotes,
    columns=[
        "page_number", "footnote_number", "block_index",
        "ref_block_index", "y0", "text",
    ],
)

footnote_issues_df = pd.DataFrame(
    all_footnote_issues,
    columns=["page_number", "issue", "number", "text"],
)

print(f"Body blocks:  {len(body_blocks_raw_df)}")
print(f"Footnotes:    {len(footnotes_df)}")
print(f"Footnote issues to review: {len(footnote_issues_df)}")

print("\n--- Footnotes separated from the body ---")
print(footnotes_df)

print("\n--- Per-page body summary ---")
print(
    body_blocks_raw_df
    .groupby("page_number")
    .agg(
        body_blocks=("text", "count"),
        body_chars=("text", lambda values: sum(len(v) for v in values)),
    )
    .reset_index()
)


# %% 4.6 Drop Blocks Already Represented as Structured Units
# The Figure regions end at their `Source:` / `Note:` block, but a figure can have
# trailing text after it. For example, on page 15 the sentence *"The elapsed time
# between EMD and EMH/EMI ..."* is part of the Figure 3 unit **and** was also
# being kept as body text, so it would have been indexed twice.
#
# A body block is dropped only when its **whole text** (at least 6 words) already
# appears inside a structured unit. Every dropped block is listed in
# `dropped_duplicates_df`, so nothing disappears silently. Partial overlaps at
# sentence level are only reported.

# =========================================================
# 4.6 Remove body blocks duplicated by structured units
# =========================================================

# Figures 7 and 8 are intentionally not part of the structured units.
dedup_units = table_units + [
    figure_1_unit,
    figure_2_unit,
    figure_3_unit,
    figure_4_unit,
    figure_5_unit,
    figure_6_unit,
]


def normalize_for_unit_match(text):
    text = clean_body_text(str(text)).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return text.strip()


unit_corpus = " | ".join(
    normalize_for_unit_match(unit["content"])
    for unit in dedup_units
)

MIN_WORDS_BLOCK = 6
MIN_WORDS_SENTENCE = 8
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

kept_rows, duplicate_rows, partial_rows = [], [], []

for record in body_blocks_raw_df.to_dict("records"):

    normalized = normalize_for_unit_match(record["text"])

    if len(normalized.split()) >= MIN_WORDS_BLOCK and normalized in unit_corpus:
        duplicate_rows.append(record)
        continue

    kept_rows.append(record)

    for sentence in SENTENCE_SPLIT.split(record["text"]):
        normalized_sentence = normalize_for_unit_match(sentence)

        if (
            len(normalized_sentence.split()) >= MIN_WORDS_SENTENCE
            and normalized_sentence in unit_corpus
        ):
            partial_rows.append({
                "page_number": record["page_number"],
                "block_index": record["block_index"],
                "sentence": sentence,
            })


body_blocks_df = pd.DataFrame(kept_rows)

dropped_duplicates_df = pd.DataFrame(
    duplicate_rows,
    columns=body_blocks_raw_df.columns,
)

partial_duplicates_df = pd.DataFrame(
    partial_rows,
    columns=["page_number", "block_index", "sentence"],
)

print(f"Body blocks before: {len(body_blocks_raw_df)}")
print(f"Dropped (whole block already in a structured unit): {len(dropped_duplicates_df)}")
print(f"Body blocks after:  {len(body_blocks_df)}")

print("\n--- Dropped duplicates ---")
print(dropped_duplicates_df[["page_number", "block_index", "text"]])

print("\n--- Partial sentence overlaps (review only, not dropped) ---")
print(partial_duplicates_df)


# %% 4.7 Body-Text Audit
# Checks that the body text is complete and clean:
#
# - Every retrieval page contributes body text
# - No Figure/Table captions leaked into the body
# - No `Source:` / `Note:` lines leaked into the body
# - No soft hyphens, non-breaking hyphens, or zero-width spaces remain
# - No structured content is duplicated in the body
# - Footnote handling left nothing ambiguous
#
# `PASS` means zero findings. `REVIEW` means the listed rows should be looked at
# before moving on.

# =========================================================
# 4.7 Body-text audit
# =========================================================

audit_rows = []

body_by_page = (
    body_blocks_df
    .groupby("page_number")["text"]
    .apply(list)
    .to_dict()
)

# ---------------------------------------------------------
# 1. Page coverage
# ---------------------------------------------------------

audit_expected_pages = {int(p) for p in content_pages_df["page_number"]}
pages_with_body = {int(p) for p in body_blocks_df["page_number"]}
missing_pages = sorted(audit_expected_pages - pages_with_body)

audit_rows.append(("Retrieval pages without body text", len(missing_pages), missing_pages))

# ---------------------------------------------------------
# 2. Figure/Table caption leaks
# ---------------------------------------------------------

caption_leaks = []

for _, row in captions_df.iterrows():

    page_number = int(row["page_number"])
    caption = clean_body_text(str(row["caption"])).lower()

    if any(caption in block.lower() for block in body_by_page.get(page_number, [])):
        caption_leaks.append(f"{row['content_type']} {int(row['number'])} (p.{page_number})")

audit_rows.append(("Caption leaks", len(caption_leaks), caption_leaks))

# ---------------------------------------------------------
# 3. Source / Note leaks
# ---------------------------------------------------------

source_note_leaks = [
    f"p.{page_number}: {block[:60]}"
    for page_number, blocks in body_by_page.items()
    for block in blocks
    if block.strip().lower().startswith(("source:", "note:"))
]

audit_rows.append(("Source/Note leaks", len(source_note_leaks), source_note_leaks))

# ---------------------------------------------------------
# 4. Residual typographic artifacts
# ---------------------------------------------------------

ARTIFACTS = {"soft hyphen": "\xad", "non-breaking hyphen": "\u2011", "zero-width space": "\u200b"}

all_text = pd.concat([body_blocks_df["text"], footnotes_df["text"]], ignore_index=True)

artifact_hits = {
    name: int(all_text.str.contains(char, regex=False).sum())
    for name, char in ARTIFACTS.items()
}

audit_rows.append((
    "Residual artifacts in text",
    sum(artifact_hits.values()),
    {name: n for name, n in artifact_hits.items() if n},
))

# ---------------------------------------------------------
# 5. Structured-unit duplication
# ---------------------------------------------------------

audit_rows.append((
    "Partial overlaps with structured units",
    len(partial_duplicates_df),
    partial_duplicates_df["page_number"].tolist(),
))

# ---------------------------------------------------------
# 6. Footnote handling
# ---------------------------------------------------------

unmatched_numbered = footnote_issues_df[
    footnote_issues_df["issue"] == "numbered_block_without_marker"
]

audit_rows.append((
    "Numbered blocks kept in body (no marker found)",
    len(unmatched_numbered),
    unmatched_numbered[["page_number", "number"]].values.tolist(),
))

orphan_markers = footnote_issues_df[
    footnote_issues_df["issue"] == "marker_without_footnote_block"
]

audit_rows.append((
    "Marker-like numbers with no footnote block",
    len(orphan_markers),
    orphan_markers[["page_number", "number"]].values.tolist(),
))

# ---------------------------------------------------------
# Result table
# ---------------------------------------------------------

audit_df = pd.DataFrame(audit_rows, columns=["check", "findings", "detail"])
audit_df["status"] = audit_df["findings"].map(lambda n: "PASS" if n == 0 else "REVIEW")

print(audit_df[["check", "findings", "status", "detail"]])

print(f"\nInformational: {len(dropped_duplicates_df)} block(s) dropped as duplicates of structured units (see 4.6).")
print(f"Informational: {len(footnotes_df)} footnote(s) separated from the body.")


# %% 4.8 Inspect Extracted Body Text
# Final visual check on page 15: the body text as extracted, followed by the
# footnotes that were separated from it.

# Inspect body text exactly as extracted (cleaned), plus separated footnotes

raw_page_number = 15

raw_page_blocks = body_blocks_df[
    body_blocks_df["page_number"] == raw_page_number
].sort_values("block_index")

print(f"BODY TEXT — PAGE {raw_page_number}")
print("=" * 100)

for _, row in raw_page_blocks.iterrows():
    refs = f"   [cites footnote(s): {row['footnote_refs']}]" if row["footnote_refs"] else ""
    print(row["text"] + refs)
    print()

print(f"FOOTNOTES — PAGE {raw_page_number}")
print("=" * 100)

for _, row in footnotes_df[footnotes_df["page_number"] == raw_page_number].iterrows():
    print(f"{row['footnote_number']}. {row['text']}")
    print()


# %% 5. Reconstruct Paragraphs
# The extraction stage now has clean body blocks with footnote text removed.
# Step 5 first removes structural section/subsection headings from the body-block
# stream using the validated `section_map`, then rebuilds paragraphs from the
# remaining prose blocks in PDF reading order.
#
# The paragraph reconstruction rules are:
#
# 1. Remove only headings that match the validated section/subsection map; these
#    headings are retained separately in `heading_blocks_df` for auditability.
# 2. Detect whether a retrieval page uses one or two body columns.
# 3. For two-column pages, read the left column top-to-bottom, then the right
#    column top-to-bottom.
# 4. Join adjacent blocks when the previous block is not terminal and the next
#    block clearly starts as a continuation (lowercase text or a closing bracket). A long block that is cut
#    mid-sentence (ending on a letter, digit, or comma) also continues into the
#    next block when that block starts with a capital letter, such as a proper noun.
# 5. Apply the same continuation rule across column boundaries and page
#    boundaries.
# 6. Preserve `footnote_refs` while merging blocks; informative footnotes are
#    appended later as `Note: ...`, while citation-only footnotes stay in metadata.
#
# The result is `paragraphs_df` with:
#
# - `paragraph_id`
# - `text`
# - `page_start`
# - `page_end`
# - `footnote_refs`

# =========================================================
# 5. Reconstruct paragraphs
# =========================================================

# ---------------------------------------------------------
# 5.0 Remove validated structural headings before paragraph
#     reconstruction.
# ---------------------------------------------------------

def normalize_structural_heading(text: str) -> str:
    """Normalize a visible heading for exact structural matching."""
    text = clean_body_text(str(text)).strip().casefold()

    # Allow printed numbering prefixes such as 1., 1.2., 2.1., or roman numerals.
    text = re.sub(
        r"^(?:(?:\d+(?:\.\d+)*)|(?:[ivxlcdm]+))[\s.):-]+",
        "",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


# `section_map` is the authoritative structural-heading inventory for the
# retrieval corpus. Every section/subsection label is represented once here.
heading_target_map = {}

for item in section_map:
    for label in (item.get("section"), item.get("subsection")):
        if not label:
            continue

        key = normalize_structural_heading(label)
        heading_target_map.setdefault(key, []).append(label)


def match_structural_heading(text: str):
    """Return the canonical structural heading label, or None."""
    key = normalize_structural_heading(text)
    labels = heading_target_map.get(key)

    if not labels:
        return None

    return labels[0]


def split_structural_headings(body_df: pd.DataFrame):
    """
    Separate validated section/subsection heading blocks from prose blocks.

    Matching is exact after normalization. Because the target inventory comes
    from the validated section map, the rule applies to the whole corpus rather
    than to named examples such as `Abstract` or `Executive summary`.
    """
    body_rows = []
    heading_rows = []

    for record in body_df.to_dict("records"):
        heading = match_structural_heading(record["text"])

        if heading is None:
            body_rows.append(record)
            continue

        row = dict(record)
        row["heading"] = heading
        heading_rows.append(row)

    clean_body = pd.DataFrame(
        body_rows,
        columns=body_df.columns,
    )

    heading_blocks = pd.DataFrame(
        heading_rows,
        columns=[*body_df.columns, "heading"],
    )

    return clean_body, heading_blocks


body_blocks_for_paragraphs_df, heading_blocks_df = split_structural_headings(
    body_blocks_df,
)

print(f"Body blocks before heading removal: {len(body_blocks_df)}")
print(f"Structural heading blocks removed:    {len(heading_blocks_df)}")
print(f"Body blocks entering reconstruction:  {len(body_blocks_for_paragraphs_df)}")

print("\n--- Structural headings removed from the paragraph stream ---")
print(
    heading_blocks_df[
        ["page_number", "block_index", "heading", "text"]
    ]
)


# ---------------------------------------------------------
# 5.1 Paragraph reading order and continuation rules
# ---------------------------------------------------------

CONTINUATION_START = re.compile(r"^[a-z\)\]\}]")


def is_two_column_page(body_page, page_width):
    """Detect whether meaningful body blocks occupy a right-hand column."""
    if len(body_page) < 2:
        return False

    return float(body_page["x0"].max()) >= page_width * 0.50


def order_body_blocks_for_reading(body_df, doc):
    """
    Return body blocks in document reading order:
    page 1..N, left column top-to-bottom, then right column.
    """
    ordered = []

    for page_number, page_group in body_df.groupby("page_number", sort=True):
        page_number = int(page_number)
        page = doc[page_number - 1]
        group = page_group.copy()

        if is_two_column_page(group, page.rect.width):
            group["__column"] = (
                group["x0"] >= page.rect.width * 0.50
            ).astype(int)

            group = group.sort_values(
                ["__column", "y0", "block_index"],
                ascending=[True, True, True],
            )
        else:
            group = group.sort_values(["y0", "block_index"])

        ordered.extend(
            group.drop(columns=["__column"], errors="ignore").to_dict("records")
        )

    return ordered


def starts_continuation(text):
    """A continuation block starts with lowercase text or a closing bracket."""
    return bool(CONTINUATION_START.match(str(text).lstrip()))


def ends_sentence(text):
    """Terminal punctuation blocks paragraph continuation."""
    text = str(text).rstrip()

    if not text:
        return False

    return text.endswith((".", "!", "?", ";", ")", "]", "}"))


HEADING_FRAGMENT_MAX_WORDS = 6


def is_heading_fragment(text):
    """
    A short block with no closing punctuation is a minor heading, not prose.
    These are the headings that are not listed in `section_map`.
    """
    text = str(text).strip()
    words = text.split()

    if not words or len(words) > HEADING_FRAGMENT_MAX_WORDS:
        return False

    if text.startswith("•"):
        return False

    return not text.endswith(
        (".", "!", "?", ":", ";", ")", "]", "}", "”", '"', "’")
    )


def looks_truncated(text):
    """A long block that stops on a letter, digit, or comma was cut mid-sentence."""
    text = str(text).rstrip()

    return (
        len(text.split()) > HEADING_FRAGMENT_MAX_WORDS
        and bool(re.search(r"[A-Za-z0-9,]$", text))
    )


def should_merge_paragraph_blocks(previous, current):
    if ends_sentence(previous["text"]):
        return False

    if starts_continuation(current["text"]):
        return True

    # A sentence cut at a column/page boundary can continue with a capital
    # letter, for example a proper noun: "...a shipment from" / "Surabaya ...".
    return looks_truncated(previous["text"])


def build_paragraphs(body_df, doc):
    """
    Build paragraphs and their location metadata in one pass.

    This is intentionally the single source of truth for reconstruction. The
    downstream section-assignment step must not re-run the state machine with a
    different input DataFrame, because doing so can drift from `paragraphs_df`.
    """
    ordered_blocks = order_body_blocks_for_reading(body_df, doc)

    paragraph_records = []
    current = None
    paragraph_id = 1

    def start_record(block):
        return {
            "paragraph_id": paragraph_id,
            "text": block["text"],
            "page_start": int(block["page_number"]),
            "page_end": int(block["page_number"]),
            "footnote_refs": list(block.get("footnote_refs") or []),
            "start_x0": float(block["x0"]),
            "start_y0": float(block["y0"]),
            "start_block_index": int(block["block_index"]),
        }

    for block in ordered_blocks:
        if current is None:
            current = start_record(block)
            continue

        if should_merge_paragraph_blocks(current, block):
            current["text"] = (
                f"{current['text'].rstrip()} {block['text'].lstrip()}"
            )
            current["page_end"] = int(block["page_number"])

            for ref in block.get("footnote_refs") or []:
                if ref not in current["footnote_refs"]:
                    current["footnote_refs"].append(ref)
        else:
            paragraph_records.append(current)
            paragraph_id += 1
            current = start_record(block)

    if current is not None:
        paragraph_records.append(current)

    paragraph_location_df = pd.DataFrame(paragraph_records)

    paragraphs_df = paragraph_location_df[
        ["paragraph_id", "text", "page_start", "page_end", "footnote_refs"]
    ].copy()

    paragraphs_df["footnote_refs"] = paragraphs_df["footnote_refs"].apply(sorted)
    paragraph_location_df["footnote_refs"] = paragraph_location_df["footnote_refs"].apply(sorted)

    return paragraphs_df, paragraph_location_df


paragraphs_df, paragraph_location_df = build_paragraphs(
    body_blocks_for_paragraphs_df,
    doc,
)

print(f"Body blocks entering Step 5: {len(body_blocks_for_paragraphs_df)}")
print(f"Reconstructed paragraphs:     {len(paragraphs_df)}")
print(
    f"Block merges performed:        "
    f"{len(body_blocks_for_paragraphs_df) - len(paragraphs_df)}"
)

assert paragraph_location_df["paragraph_id"].tolist() == paragraphs_df["paragraph_id"].tolist()
assert paragraph_location_df["text"].tolist() == paragraphs_df["text"].tolist()
assert paragraph_location_df["footnote_refs"].tolist() == paragraphs_df["footnote_refs"].tolist()

print(paragraphs_df.head(10))


# %% 5.1 Step 5 Validation
# The validation focuses on the cases that motivated paragraph reconstruction:
#
# - Structural headings are removed before paragraph reconstruction and retained
#   separately in `heading_blocks_df`.
# - Page 15: the export dwell-time sentence must be one paragraph even though it
#   crosses the left-column / right-column boundary.
# - Page boundaries: paragraphs may continue from the end of one page into the
#   next page when the continuation rule is satisfied.
# - Every retrieval page should appear in the paragraph output.
# - Remaining paragraphs must not be exact structural-heading matches.
# - A per-page paragraph count is displayed for review.

# =========================================================
# 5.1 Step 5 validation
# =========================================================

paragraph_heading_leaks = paragraphs_df[
    paragraphs_df["text"].apply(
        lambda text: match_structural_heading(text) is not None
    )
].copy()

print("Structural headings still present as paragraphs:", len(paragraph_heading_leaks))
assert paragraph_heading_leaks.empty, (
    "A validated structural heading still entered paragraphs_df."
)

# Corpus-wide coverage: every unique heading represented by section_map must
# have been removed from the paragraph stream, not just the named examples.
expected_heading_keys = set(heading_target_map)
removed_heading_keys = {
    normalize_structural_heading(text)
    for text in heading_blocks_df["text"].tolist()
}

assert removed_heading_keys == expected_heading_keys, (
    "The structural-heading removal inventory does not match the full "
    "section/subsection map."
)
assert len(heading_blocks_df) == len(expected_heading_keys), (
    "Expected one visible heading block per mapped section/subsection."
)

print(f"Validated structural headings removed: {len(heading_blocks_df)}")

print(
    heading_blocks_df[
        ["page_number", "block_index", "heading", "text"]
    ]
)

expected_pages = {int(page_number) for page_number in content_pages_df["page_number"]}
# A paragraph covers every page from its first to its last page.
paragraph_pages = {
    page
    for start, end in zip(paragraphs_df["page_start"], paragraphs_df["page_end"])
    for page in range(int(start), int(end) + 1)
}
missing_paragraph_pages = sorted(expected_pages - paragraph_pages)

print("\nRetrieval pages with no paragraph coverage:", missing_paragraph_pages)
assert not missing_paragraph_pages, (
    "Some retrieval pages have no reconstructed paragraphs."
)

# Regression check for the known column-boundary case. This validates the
# paragraph reconstruction behavior, while the heading validation above is
# corpus-wide.
target_fragment = "from gate in full to load on board full events in figure 1"
target_matches = paragraphs_df[
    paragraphs_df["text"].str.contains(
        target_fragment,
        case=False,
        regex=False,
        na=False,
    )
]
assert len(target_matches) == 1
assert int(target_matches.iloc[0]["page_start"]) == 15
assert int(target_matches.iloc[0]["page_end"]) == 15

turnaround_rows = paragraphs_df[
    paragraphs_df["footnote_refs"].apply(lambda refs: 13 in (refs or []))
]
assert len(turnaround_rows) == 1
assert int(turnaround_rows.iloc[0]["page_start"]) == 15

paragraph_count_by_page = (
    paragraphs_df.groupby("page_start")
    .size()
    .rename("paragraph_count")
    .reset_index()
    .rename(columns={"page_start": "page_number"})
)

print(paragraph_count_by_page)

cross_page_paragraphs_df = paragraphs_df[
    paragraphs_df["page_start"] < paragraphs_df["page_end"]
].copy()

print(f"\nCross-page paragraphs: {len(cross_page_paragraphs_df)}")
print(
    cross_page_paragraphs_df[
        ["paragraph_id", "page_start", "page_end", "footnote_refs", "text"]
    ]
)

# Generic heading-noise review: after removing every mapped structural heading,
# look for short uppercase/title-like prose rows that could still be heading-like.
def looks_like_heading_noise(text):
    text = str(text).strip()
    words = text.split()
    if not words or len(words) > 12 or len(text) > 120:
        return False
    if text.endswith((".", ":", ";", "?", "!")):
        return False
    title_case_ratio = sum(
        1 for word in words if word[:1].isupper()
    ) / len(words)
    return text.isupper() or (len(words) >= 2 and title_case_ratio >= 0.8)

heading_like_remaining_df = paragraphs_df[
    paragraphs_df["text"].apply(looks_like_heading_noise)
].copy()

print(f"\nResidual heading-like paragraph candidates: {len(heading_like_remaining_df)}")
print(
    heading_like_remaining_df[
        ["paragraph_id", "page_start", "page_end", "text"]
    ]
)

print("\nStep 5 validation complete: heading removal is corpus-wide and paragraph reconstruction is internally consistent.")


# %% 6. Footnote review and decision
# Footnotes remain separate from the paragraph text at the extraction stage.
# For the RAG content used below, factual/explanatory footnotes are appended to
# the paragraph content as `Note: ...`, while citation-only footnotes remain in
# `footnote_refs` metadata and are not redundantly injected into `content`.
#
# Example: footnote 13 explains what ship turnaround time measures and why it is
# used as a performance indicator, so it is treated as an informative note and
# will be appended to the paragraph that cites it.
#
# Footnote 5 is citation-only (`Arvis et al. 2026.`), so it is **not** appended
# as a Note. Its reference is retained on the paragraph that cites it.

# =========================================================
# 6.1 Footnote review
# =========================================================

footnote_5 = footnotes_df[
    (footnotes_df["page_number"] == 12)
    & (footnotes_df["footnote_number"] == 5)
].copy()

assert len(footnote_5) == 1, "Footnote 5 should appear exactly once."
assert footnote_5.iloc[0]["text"] == "Arvis et al. 2026.", footnote_5.iloc[0]["text"]

paragraphs_with_footnote_5 = paragraphs_df[
    paragraphs_df["footnote_refs"].apply(
        lambda refs: 5 in (refs or [])
    )
].copy()

assert len(paragraphs_with_footnote_5) == 1, (
    "Footnote 5 should be linked to exactly one paragraph."
)

assert paragraphs_with_footnote_5.iloc[0]["page_start"] == 12
assert "Connecting to Compete 2025" in paragraphs_with_footnote_5.iloc[0]["text"]


footnote_13 = footnotes_df[
    (footnotes_df["page_number"] == 15)
    & (footnotes_df["footnote_number"] == 13)
].copy()

assert len(footnote_13) == 1, "Footnote 13 should appear exactly once."
assert "turnaround time" in footnote_13.iloc[0]["text"].lower()

paragraphs_with_footnote_13 = paragraphs_df[
    paragraphs_df["footnote_refs"].apply(
        lambda refs: 13 in (refs or [])
    )
].copy()

assert len(paragraphs_with_footnote_13) == 1, (
    "Footnote 13 should be linked to exactly one paragraph."
)

print("Footnote 5 text:", footnote_5.iloc[0]["text"])
print("Footnote 5 decision: citation-only -> metadata only.")

print("\nFootnote 13 text:", footnote_13.iloc[0]["text"])
print("Footnote 13 decision: informative -> append as `Note: ...`.")

print(
    paragraphs_with_footnote_13[
        ["paragraph_id", "page_start", "page_end", "footnote_refs", "text"]
    ]
)


# %% 7. Unified Units Table
# The next table is the single pre-chunking unit layer. It combines:
#
# - reconstructed body paragraphs,
# - all `table_units` rows,
# - Figure units 1–4 and 6,
# - Figure 5 as a `worked_example`,
# - the Abbreviations table (page 7) as a `definitions` unit.
#
# Section/subsection assignment is location-based. Headings from `section_map`
# are matched to their actual PDF block position, and the assignment follows the
# PDF reading order, including two-column pages. This matters for pages 21, 26,
# and 29 where subsections share the same page.

# =========================================================
# 7.1 Build location-aware section/subsection map
# =========================================================

from bisect import bisect_right


def _norm_heading_text(text):
    return clean_body_text(str(text)).strip().casefold()


def find_section_heading_positions(doc, section_map):
    """
    Locate each mapped heading at its actual PDF block position.

    Exact normalized block matches are preferred so body mentions such as
    `Cargo iQ, a nonprofit ...` do not become false headings.
    """
    records = []

    for item in section_map:
        page_number = int(item["start_page"])
        target = _norm_heading_text(
            item["subsection"] or item["section"]
        )

        page = doc[page_number - 1]
        exact_hits = []

        for block_index, block in enumerate(page.get_text("blocks")):
            x0, y0, x1, y1, text, *rest = block
            normalized = _norm_heading_text(text)

            if normalized == target:
                exact_hits.append({
                    "page_number": page_number,
                    "x0": float(x0),
                    "y0": float(y0),
                    "x1": float(x1),
                    "y1": float(y1),
                    "block_index": int(block_index),
                    "section": item["section"],
                    "subsection": item["subsection"],
                    "level": int(item["level"]),
                    "heading": clean_body_text(text),
                })

        if not exact_hits:
            # Fallback for a heading that is split by PDF line wrapping.
            contains_hits = []
            for block_index, block in enumerate(page.get_text("blocks")):
                x0, y0, x1, y1, text, *rest = block
                normalized = _norm_heading_text(text)
                if target and target in normalized:
                    contains_hits.append({
                        "page_number": page_number,
                        "x0": float(x0),
                        "y0": float(y0),
                        "x1": float(x1),
                        "y1": float(y1),
                        "block_index": int(block_index),
                        "section": item["section"],
                        "subsection": item["subsection"],
                        "level": int(item["level"]),
                        "heading": clean_body_text(text),
                    })

            exact_hits = contains_hits

        if len(exact_hits) != 1:
            raise ValueError(
                f"Expected exactly one heading match for {item!r}; "
                f"found {len(exact_hits)}: {exact_hits}"
            )

        records.append(exact_hits[0])

    return pd.DataFrame(records)


heading_positions_df = find_section_heading_positions(
    doc=doc,
    section_map=section_map,
)


def page_column(page, x0):
    """Use the same left/right column rule as paragraph reconstruction."""
    return int(float(x0) >= page.rect.width * 0.50)


def reading_key(page_number, x0, y0, doc):
    page = doc[int(page_number) - 1]
    return (
        int(page_number),
        page_column(page, x0),
        float(y0),
        float(x0),
    )


heading_positions_df["reading_key"] = heading_positions_df.apply(
    lambda row: reading_key(
        row["page_number"],
        row["x0"],
        row["y0"],
        doc,
    ),
    axis=1,
)

heading_positions_df = heading_positions_df.sort_values(
    "reading_key"
).reset_index(drop=True)

# Inspect the actual subsection transitions on the ambiguous pages.
print(
    heading_positions_df[
        heading_positions_df["page_number"].isin([21, 26, 29])
    ][
        [
            "page_number",
            "x0",
            "y0",
            "section",
            "subsection",
            "heading",
        ]
    ]
)

# =========================================================
# 7.2 Validate paragraph-location alignment
# =========================================================

# `paragraph_location_df` was produced by the same Step-5 state machine that
# produced `paragraphs_df`. We validate the alignment instead of reconstructing
# paragraphs a second time with a different input DataFrame.
assert len(paragraph_location_df) == len(paragraphs_df)
assert paragraph_location_df["paragraph_id"].tolist() == paragraphs_df["paragraph_id"].tolist()
assert paragraph_location_df["text"].tolist() == paragraphs_df["text"].tolist()
assert paragraph_location_df["footnote_refs"].tolist() == paragraphs_df["footnote_refs"].tolist()

print(f"Paragraphs with location metadata: {len(paragraph_location_df)}")

# =========================================================
# 7.3 Helper: assign section/subsection by reading order
# =========================================================

heading_keys = heading_positions_df["reading_key"].tolist()
heading_records = heading_positions_df.to_dict("records")


def assign_section_subsection(page_number, x0, y0):
    key = reading_key(page_number, x0, y0, doc)
    idx = bisect_right(heading_keys, key) - 1

    if idx < 0:
        return None, None

    record = heading_records[idx]
    return record["section"], record["subsection"]


# Paragraph section mapping based on the first block of each reconstructed paragraph.
paragraph_section_rows = []

for row in paragraph_location_df.to_dict("records"):
    section, subsection = assign_section_subsection(
        row["page_start"],
        row["start_x0"],
        row["start_y0"],
    )

    paragraph_section_rows.append({
        "paragraph_id": row["paragraph_id"],
        "section": section,
        "subsection": subsection,
    })

paragraph_section_df = pd.DataFrame(paragraph_section_rows)

assert paragraph_section_df["section"].notna().all(), (
    "Every paragraph must receive a section."
)

paragraphs_enriched_df = paragraphs_df.merge(
    paragraph_section_df,
    on="paragraph_id",
    how="left",
    validate="one_to_one",
)

print("Paragraph section coverage:")
print(
    paragraphs_enriched_df
    .groupby(["section", "subsection"], dropna=False)
    .size()
    .rename("paragraph_count")
    .reset_index()
)

# =========================================================
# 7.4 Assign section/subsection to structured units by caption location
# =========================================================


def caption_location(content_type, number):
    match = captions_df[
        (captions_df["content_type"] == content_type)
        & (captions_df["number"] == int(number))
    ]

    if match.empty:
        raise ValueError(
            f"No confirmed {content_type} caption found for number {number}."
        )

    row = match.iloc[0]
    page_number = int(row["page_number"])
    caption = str(row["caption"])
    page = doc[page_number - 1]

    matches = page.search_for(caption)
    if not matches:
        raise ValueError(
            f"Could not locate caption on PDF page {page_number}: {caption!r}"
        )

    bbox = matches[0]

    return {
        "page_start": page_number,
        "page_end": page_number,
        "x0": float(bbox.x0),
        "y0": float(bbox.y0),
        "caption": clean_body_text(caption),
    }


def enrich_structured_unit(unit):
    unit = dict(unit)

    if unit["unit_type"] == "table_row":
        loc = caption_location("table", unit["table_number"])
    else:
        loc = caption_location("figure", unit["figure_number"])

    section, subsection = assign_section_subsection(
        loc["page_start"],
        loc["x0"],
        loc["y0"],
    )

    unit["page_start"] = loc["page_start"]
    unit["page_end"] = loc["page_end"]
    unit["section"] = section
    unit["subsection"] = subsection
    unit["_x0"] = loc["x0"]
    unit["_y0"] = loc["y0"]
    return unit


structured_units = [
    enrich_structured_unit(unit)
    for unit in table_units
]

structured_units.extend(
    enrich_structured_unit(unit)
    for unit in [
        figure_1_unit,
        figure_2_unit,
        figure_3_unit,
        figure_4_unit,
        figure_5_unit,
        figure_6_unit,
    ]
)

structured_units_df = pd.DataFrame(structured_units)

print("Structured-unit section assignment:")
print(
    structured_units_df[
        [
            "unit_type",
            "table_number",
            "figure_number",
            "logical_unit",
            "page_start",
            "section",
            "subsection",
        ]
    ]
)

# =========================================================
# 7.5 Apply the footnote policy to the entire corpus
# =========================================================

footnote_text_map = {
    int(row["footnote_number"]): clean_body_text(row["text"])
    for _, row in footnotes_df.iterrows()
}


def is_citation_only_footnote(text):
    """Classify citation-only footnotes by form, not by footnote number."""
    text = clean_body_text(text).strip()

    citation_only_patterns = [
        r"^[A-Z][A-Za-zÀ-ÖØ-öø-ÿ .,'’&-]{1,80}(?:et al\.)?\s+\d{4}\.$",
        r"^See .+\(\d{4}\) for more details.*$",
    ]

    return any(
        re.match(pattern, text, flags=re.IGNORECASE)
        for pattern in citation_only_patterns
    )


footnote_policy_records = []
for number, text in sorted(footnote_text_map.items()):
    policy = "citation_only" if is_citation_only_footnote(text) else "informative"
    footnote_policy_records.append({
        "footnote_number": number,
        "policy": policy,
        "text": text,
    })

footnote_policy_df = pd.DataFrame(footnote_policy_records)


def build_body_content(row):
    content = clean_body_text(row["text"])
    refs = list(row["footnote_refs"] or [])
    notes = []

    for ref in refs:
        note = footnote_text_map.get(int(ref))
        if note and not is_citation_only_footnote(note):
            notes.append(f"Note: {note}")

    if notes:
        content = f"{content} " + " ".join(notes)

    return content


paragraph_units = []
for _, row in paragraphs_enriched_df.iterrows():
    paragraph_units.append({
        "unit_type": "paragraph",
        "logical_unit": None,
        "content": build_body_content(row),
        "section": row["section"],
        "subsection": row["subsection"],
        "page_start": int(row["page_start"]),
        "page_end": int(row["page_end"]),
        "table_number": None,
        "figure_number": None,
        "footnote_refs": list(row["footnote_refs"] or []),
    })

paragraph_units_df = pd.DataFrame(paragraph_units)

# Corpus-wide footnote linkage/policy validation.
known_numbers = set(footnote_text_map)
all_referenced_numbers = {
    int(ref)
    for refs in paragraphs_df["footnote_refs"]
    for ref in (refs or [])
}
assert all_referenced_numbers <= known_numbers
assert all_referenced_numbers == known_numbers, (
    "Every extracted footnote should be linked to a body paragraph."
)

for number, note in footnote_text_map.items():
    linked = paragraphs_enriched_df[
        paragraphs_enriched_df["footnote_refs"].apply(
            lambda refs: number in (refs or [])
        )
    ]

    assert len(linked) == 1, (
        f"Footnote {number} should be linked to exactly one paragraph; "
        f"found {len(linked)}."
    )

    content = paragraph_units_df.loc[linked.index[0], "content"]
    citation_only = is_citation_only_footnote(note)
    expected_note = f"Note: {note}"

    if citation_only:
        assert expected_note not in content, (
            f"Citation-only footnote {number} was injected into content."
        )
    else:
        assert expected_note in content, (
            f"Informative footnote {number} was not appended as `Note: ...`."
        )

print("\nFootnote policy summary across the full corpus:")
print(footnote_policy_df)
print(
    f"Informative footnotes: {(footnote_policy_df['policy'] == 'informative').sum()} | "
    f"Citation-only footnotes: {(footnote_policy_df['policy'] == 'citation_only').sum()} | "
    f"Total footnotes: {len(footnote_policy_df)}"
)

# Keep the original concrete regression examples as examples only; the loop
# above is the actual corpus-wide policy validation.

# =========================================================
# 7.6 Build the unified units table
# =========================================================

def clean_content_lines(text):
    """
    Clean every line of a structured unit but keep the line structure.

    Table rows are built as one `Column: value` line per column, so the line
    breaks are meaningful and must survive the whitespace normalization.
    """
    cleaned = (clean_body_text(line) for line in str(text).splitlines())
    return "\n".join(line for line in cleaned if line)


unit_records = []

# Body paragraphs
for paragraph_id, unit in enumerate(paragraph_units, start=1):
    record = dict(unit)
    record["unit_id"] = f"P{paragraph_id:03d}"
    unit_records.append(record)

# Structured units
for unit in structured_units:
    record = {
        "unit_type": unit["unit_type"],
        "logical_unit": unit.get("logical_unit"),
        "content": clean_content_lines(unit["content"]),
        "section": unit["section"],
        "subsection": unit["subsection"],
        "page_start": int(unit["page_start"]),
        "page_end": int(unit["page_end"]),
        "table_number": unit.get("table_number"),
        "figure_number": unit.get("figure_number"),
        "footnote_refs": [],
    }

    if unit["unit_type"] == "table_row":
        record["unit_id"] = (
            f"T{int(unit['table_number'])}_R{int(unit['row_index']) + 1:02d}"
        )
    elif unit["unit_type"] == "worked_example":
        record["unit_id"] = f"WE{int(unit['figure_number'])}"
    else:
        record["unit_id"] = f"F{int(unit['figure_number'])}"

    unit_records.append(record)


# Abbreviations table (page 7), extracted in section 3.3
abbreviations_record = dict(abbreviations_unit)
abbreviations_record["content"] = clean_content_lines(abbreviations_record["content"])
abbreviations_record.update(table_number=None, figure_number=None, footnote_refs=[])
unit_records.append(abbreviations_record)


units_df = pd.DataFrame(unit_records)[
    [
        "unit_id",
        "unit_type",
        "logical_unit",
        "content",
        "section",
        "subsection",
        "page_start",
        "page_end",
        "table_number",
        "figure_number",
        "footnote_refs",
    ]
].copy()

# Stable reading order for downstream chunking.
units_df["_order_page"] = units_df["page_start"]
units_df["_order_type"] = units_df["unit_type"].map({
    "paragraph": 0,
    "table_row": 1,
    "figure": 2,
    "worked_example": 2,
    "definitions": 1,
})

units_df = units_df.sort_values(
    ["_order_page", "_order_type", "unit_id"]
).drop(
    columns=["_order_page", "_order_type"]
).reset_index(drop=True)

print(f"Unified units: {len(units_df)}")
print("By unit type:")
print(
    units_df["unit_type"].value_counts().rename_axis("unit_type").reset_index(name="count")
)

print("\nUnified units preview:")
print(
    units_df[
        [
            "unit_id",
            "unit_type",
            "section",
            "subsection",
            "page_start",
            "page_end",
            "table_number",
            "figure_number",
        ]
    ].head(25)
)

# =========================================================
# 7.7 Step 7 validation
# =========================================================

assert units_df["section"].notna().all()

# `content` is the single canonical semantic text field. No parallel `rag_text`
# field should survive in the unified layer.
assert "rag_text" not in units_df.columns
assert "content" in units_df.columns
assert units_df["content"].notna().all()
assert units_df["content"].map(lambda value: bool(str(value).strip())).all()


assert (units_df["unit_type"] == "paragraph").sum() == len(paragraphs_df)

assert (units_df["unit_type"] == "table_row").sum() == len(table_units)

figure_ids = set(
    units_df.loc[
        units_df["figure_number"].notna(),
        "figure_number",
    ].astype(int)
)
assert figure_ids == {1, 2, 3, 4, 5, 6}

assert units_df.loc[
    units_df["figure_number"] == 5,
    "unit_type",
].iloc[0] == "worked_example"

assert not units_df["figure_number"].isin([7, 8]).any()


unit_heading_leaks = units_df[
    units_df["unit_type"].eq("paragraph")
    & units_df["content"].apply(
        lambda text: match_structural_heading(
            text.split("Note:", 1)[0].strip()
        ) is not None
    )
]
assert unit_heading_leaks.empty, (
    "A structural heading leaked into the unified paragraph corpus."
)


fn5_rows = units_df[
    units_df["footnote_refs"].apply(
        lambda refs: 5 in (refs or [])
    )
]
assert len(fn5_rows) == 1
assert "Arvis et al. 2026" not in fn5_rows.iloc[0]["content"]

fn13_rows = units_df[
    units_df["footnote_refs"].apply(
        lambda refs: 13 in (refs or [])
    )
]
assert len(fn13_rows) == 1
assert (
    "Note: Turnaround time is a standard key performance indicator"
    in fn13_rows.iloc[0]["content"]
)


unit_section_counts_df = (
    units_df
    .groupby(["section", "subsection", "unit_type"], dropna=False)
    .size()
    .rename("unit_count")
    .reset_index()
)

print(unit_section_counts_df)

print(
    "\nStep 7 validation complete: unified units are clean, "
    "section-aware, and footnote-aware."
)

# =========================================================
# 7.8 Final diagnostics before chunking
# =========================================================

heading_only_paragraphs_df = paragraphs_df[
    paragraphs_df["text"].apply(
        lambda text: match_structural_heading(text) is not None
    )
].copy()

heading_key_check = {
    "expected": sorted(expected_heading_keys),
    "removed": sorted(removed_heading_keys),
}

assert heading_only_paragraphs_df.empty
assert heading_key_check["expected"] == heading_key_check["removed"]

# Final corpus-wide footnote checks use the policy table, not footnote 13 alone.
for number, policy_row in footnote_policy_df.set_index("footnote_number").iterrows():
    linked = paragraph_units_df[
        paragraph_units_df["footnote_refs"].apply(
            lambda refs: int(number) in (refs or [])
        )
    ]
    assert len(linked) == 1

    note = footnote_text_map[int(number)]
    note_text = f"Note: {note}"
    content = linked.iloc[0]["content"]

    if policy_row["policy"] == "informative":
        assert note_text in content
    else:
        assert note_text not in content

print(f"Structural heading blocks removed: {len(heading_blocks_df)}")
print(f"Heading-only paragraphs remaining: {len(heading_only_paragraphs_df)}")
print(
    f"Footnotes validated: {len(footnote_policy_df)} "
    f"({(footnote_policy_df['policy'] == 'informative').sum()} informative, "
    f"{(footnote_policy_df['policy'] == 'citation_only').sum()} citation-only)"
)
print(f"Unified units: {len(units_df)}")

# Show the informative footnote units for inspection without assuming there is
# only one such footnote.
informative_units_df = units_df[
    units_df["footnote_refs"].apply(
        lambda refs: any(
            footnote_policy_df.set_index("footnote_number").loc[int(ref), "policy"] == "informative"
            for ref in (refs or [])
        )
    )
].copy()

print(
    informative_units_df[
        [
            "unit_id",
            "unit_type",
            "page_start",
            "page_end",
            "footnote_refs",
            "content",
        ]
    ]
)

# 7.9 Final paragraph preview after structural-heading removal

print(
    paragraphs_df[
        ["paragraph_id", "page_start", "page_end", "footnote_refs", "text"]
    ].head(12)
)


# %% 8. Final content samples — one representative sample per unit type
# This is the final inspection layer before downstream chunking. It intentionally
# shows one complete `content` sample for every `unit_type` that exists in the
# current corpus, so we can review the semantic shape of every unit family without
# creating another text column such as `rag_text`.

# =========================================================
# 8.1 Build the final content sample gallery
# =========================================================

sample_rows = []

for unit_type, group in units_df.sort_values(["unit_type", "unit_id"]).groupby("unit_type", sort=True):
    row = group.iloc[0]
    sample_rows.append({
        "unit_type": row["unit_type"],
        "unit_id": row["unit_id"],
        "section": row["section"],
        "subsection": row["subsection"],
        "page_start": row["page_start"],
        "page_end": row["page_end"],
        "table_number": row["table_number"],
        "figure_number": row["figure_number"],
        "footnote_refs": row["footnote_refs"],
        "content_char_count": len(str(row["content"])),
        "content": row["content"],
    })

content_samples_df = pd.DataFrame(sample_rows)

# One and only one representative sample per unit type.
assert content_samples_df["unit_type"].is_unique
assert set(content_samples_df["unit_type"]) == set(units_df["unit_type"])
assert content_samples_df["content"].map(lambda value: bool(str(value).strip())).all()

print("\nFinal content samples — one complete sample per unit type:")
print(content_samples_df)

print("\nUnit types represented:", sorted(content_samples_df["unit_type"].tolist()))

# =========================================================
# 8.2 Full content viewer — text output
# =========================================================

for _, row in units_df.iterrows():

    print("=" * 120)
    print(
        f"UNIT ID     : {row['unit_id']}\n"
        f"UNIT TYPE   : {row['unit_type']}\n"
        f"SECTION     : {row['section']}\n"
        f"SUBSECTION  : {row['subsection']}\n"
        f"PAGE        : {row['page_start']} - {row['page_end']}\n"
        f"FOOTNOTES   : {row['footnote_refs']}"
    )
    print("-" * 120)
    print("CONTENT:")
    print()
    print(str(row["content"]))
    print()
    print("=" * 120)
    print()


# %% 9. Save Extracted and Cleaned Artifacts
# The LPI pipeline follows the same persistence flow as the FBL and Suez
# pipelines: **extracted → cleaned → chunks**, stored under
# `processed/rag/{extracted, cleaned, chunks}`.
#
# - **extracted**: what the extraction stage produced from the PDF — the body
#   blocks, the footnotes, and the structured (table / figure / abbreviations) units.
# - **cleaned**: `units_df`, the unified logical units after paragraph
#   reconstruction, footnote policy, and section assignment.
# - **chunks**: saved in Section 12, after chunking and schema mapping.


# %% 9.1 Output Locations

# =========================================================
# 9.1 Output locations and JSON helper
# =========================================================

import json

# Same processed/rag folders used by the FBL and Suez artifacts.
# PDF_PATH is <project>/Data/raw/unstructured/<file>.pdf
PROCESSED_RAG_DIR = PDF_PATH.parents[2] / "processed" / "rag"

EXTRACTED_DIR = PROCESSED_RAG_DIR / "extracted"
CLEANED_DIR = PROCESSED_RAG_DIR / "cleaned"
CHUNKS_DIR = PROCESSED_RAG_DIR / "chunks"

for directory in (EXTRACTED_DIR, CLEANED_DIR, CHUNKS_DIR):
    directory.mkdir(parents=True, exist_ok=True)


def json_safe(value):
    """Convert pandas / numpy values to plain JSON types (NaN and NA become None)."""
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}

    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]

    if hasattr(value, "item"):          # numpy scalar
        value = value.item()

    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass

    return value


print("Processed RAG folder:", PROCESSED_RAG_DIR)


# %% 9.2 Save the Extracted Artifact

# =========================================================
# 9.2 Save extracted artifact
# =========================================================

extracted_path = EXTRACTED_DIR / f"{PDF_PATH.stem}_extracted.json"

extracted_payload = {
    "source_file": PDF_PATH.name,
    "body_blocks": body_blocks_df.to_dict("records"),
    "footnotes": footnotes_df.to_dict("records"),
    "structured_units": [
        *table_units,
        figure_1_unit,
        figure_2_unit,
        figure_3_unit,
        figure_4_unit,
        figure_5_unit,
        figure_6_unit,
        abbreviations_unit,
    ],
}

with open(extracted_path, "w", encoding="utf-8") as f:
    json.dump(json_safe(extracted_payload), f, ensure_ascii=False, indent=2, default=str)

print("Extracted artifact saved:")
print(extracted_path)
print(
    f"  body blocks: {len(extracted_payload['body_blocks'])} | "
    f"footnotes: {len(extracted_payload['footnotes'])} | "
    f"structured units: {len(extracted_payload['structured_units'])}"
)


# %% 9.3 Save the Cleaned Artifact

# =========================================================
# 9.3 Save cleaned artifact (unified logical units)
# =========================================================

cleaned_path = CLEANED_DIR / f"{PDF_PATH.stem}_logical_units.json"

with open(cleaned_path, "w", encoding="utf-8") as f:
    json.dump(
        json_safe(units_df.to_dict("records")),
        f,
        ensure_ascii=False,
        indent=2,
        default=str,
    )

print("Cleaned artifact saved:")
print(cleaned_path)
print(f"  logical units: {len(units_df)}")


# %% 10. Chunking
# The unit of retrieval is the smallest piece of text that answers a question on
# its own, so chunk boundaries follow the meaning of the content, not a size
# target:
#
# 1. **Paragraphs** stay whole. A minor heading that is not in `section_map`
#    (for example *Core indicators*) stays with the paragraph that follows it. A
#    paragraph shorter than **300 characters** is too short to embed well on its
#    own, so it is grouped with its neighbor inside the same subsection. Groups
#    never cross a section or subsection boundary.
# 2. **Table rows** are one chunk each. When a row holds bulleted lists (Table 2),
#    each bullet is one indicator definition, so each bullet becomes its own chunk,
#    prefixed with the row identifier and the column label. The rule depends on the
#    table structure, not on size, so every row of the table is treated the same way.
# 3. **Figures, the worked example, and the abbreviations table** stay one chunk each.
#
# No chunk may exceed **2000 characters** (about 450 tokens, within the input limit
# of common embedding models). It is a safety cap, not a target, and it is one
# constant to adjust once the embedding model is chosen.


# %% 10.1 Chunking Rules and Helpers

# =========================================================
# 10.1 Chunking rules and helpers
# =========================================================

MAX_CHUNK_CHARS = 2000   # safety cap (~450 tokens); chunks are cut by meaning, not by this size
MIN_CHUNK_CHARS = 300    # below this a paragraph is too short to embed well on its own
CHUNK_SEPARATOR = "\n\n"


def unit_location(unit):
    """(section, subsection) of a unit; a missing subsection is None."""
    return tuple(
        None if pd.isna(unit[key]) else unit[key]
        for key in ("section", "subsection")
    )


def group_paragraph_units(units):
    """
    Group adjacent paragraph units without splitting any of them.

    A unit joins the current group only if all of these hold:
    - it is in the same section and subsection,
    - it is not itself a minor heading (a heading starts its own group),
    - the grouped text stays within MAX_CHUNK_CHARS,
    - and either the group ends with a minor heading, the group is still shorter
      than MIN_CHUNK_CHARS, or the unit is shorter than MIN_CHUNK_CHARS.
    """
    groups = []

    for unit in units:

        if groups and unit_location(groups[-1][-1]) == unit_location(unit):

            group = groups[-1]
            group_size = len(CHUNK_SEPARATOR.join(u["content"] for u in group))
            merged_size = group_size + len(CHUNK_SEPARATOR) + len(unit["content"])

            can_merge = (
                not is_heading_fragment(unit["content"])
                and merged_size <= MAX_CHUNK_CHARS
                and (
                    is_heading_fragment(group[-1]["content"])
                    or group_size < MIN_CHUNK_CHARS
                    or len(unit["content"]) < MIN_CHUNK_CHARS
                )
            )

            if can_merge:
                group.append(unit)
                continue

        groups.append([unit])

    return groups


def split_table_row_by_bullets(content):
    """
    A table row is one chunk. When its cells hold bulleted lists (Table 2), each
    bullet is a separate indicator definition, so each bullet becomes its own chunk,
    prefixed with the row identifier (first line) and the column label.

    A row without bullets (Tables 1 and 3) is returned unchanged.
    """
    lines = [line for line in content.split("\n") if line.strip()]
    header, columns = lines[0], lines[1:]

    if not any("•" in column for column in columns):
        return [content]

    parts = []

    for column in columns:
        label, _, value = column.partition(": ")

        items = [item for item in re.split(r"\s*•\s*", value) if item.strip()]

        for item in items:
            parts.append(f"{header}\n{label}: {item.strip()}")

    return parts


def logical_unit_name(unit_id):
    """Readable logical-unit name from a unit id (P013, T2_R01, F3, WE5, AB1)."""
    patterns = [
        (r"P(\d+)", lambda m: f"paragraph_{int(m[1]):03d}"),
        (r"T(\d+)_R(\d+)", lambda m: f"table_{int(m[1])}_row_{int(m[2]):02d}"),
        (r"WE(\d+)", lambda m: f"worked_example_{int(m[1])}"),
        (r"AB(\d+)", lambda m: "abbreviations"),
        (r"F(\d+)", lambda m: f"figure_{int(m[1])}"),
    ]

    for pattern, build in patterns:
        match = re.fullmatch(pattern, unit_id)

        if match:
            return build(match)

    raise ValueError(f"Unrecognized unit_id: {unit_id!r}")


# %% 10.2 Build the Chunks

# =========================================================
# 10.2 Build chunks from the unified units
# =========================================================

TYPE_ORDER = {"paragraph": 0, "table_row": 1, "definitions": 1, "figure": 2, "worked_example": 2}


def make_chunk(units, unit_type, logical_unit, part, title, text):
    first = units[0]

    return {
        "page": int(min(u["page_start"] for u in units)),
        "unit_type": unit_type,
        "logical_unit": logical_unit,
        "chunk_id": f"lpi_{logical_unit}_chunk_{part}",
        "section": first["section"],
        "subsection": None if pd.isna(first["subsection"]) else first["subsection"],
        "title": title,
        "text": text,
        "source_unit_ids": [u["unit_id"] for u in units],
    }


unit_dicts = units_df.to_dict("records")

paragraph_records = sorted(
    (u for u in unit_dicts if u["unit_type"] == "paragraph"),
    key=lambda u: u["unit_id"],
)
structured_records = [u for u in unit_dicts if u["unit_type"] != "paragraph"]

chunk_records = []

# ---------------------------------------------------------
# Paragraphs: heading attachment + grouping of small units
# ---------------------------------------------------------

paragraph_groups = group_paragraph_units(paragraph_records)

for group in paragraph_groups:

    first_name = logical_unit_name(group[0]["unit_id"])

    logical_unit = (
        first_name
        if len(group) == 1
        else f"{first_name}_{logical_unit_name(group[-1]['unit_id']).split('_')[-1]}"
    )

    chunk_records.append(
        make_chunk(
            units=group,
            unit_type="paragraph",
            logical_unit=logical_unit,
            part=1,
            title=(
                group[0]["subsection"]
                if not pd.isna(group[0]["subsection"])
                else group[0]["section"]
            ),
            text=CHUNK_SEPARATOR.join(u["content"] for u in group),
        )
    )

# ---------------------------------------------------------
# Structured units: one chunk each; a table row with bulleted
# cells is split per bullet (indicator definition)
# ---------------------------------------------------------

for unit in structured_records:

    if unit["unit_type"] == "table_row":
        parts = split_table_row_by_bullets(unit["content"])
    else:
        parts = [unit["content"]]

    title = (
        unit["logical_unit"]
        if not pd.isna(unit["logical_unit"])
        else (
            unit["subsection"]
            if not pd.isna(unit["subsection"])
            else unit["section"]
        )
    )

    for part_number, part_text in enumerate(parts, start=1):
        chunk_records.append(
            make_chunk(
                units=[unit],
                unit_type=unit["unit_type"],
                logical_unit=logical_unit_name(unit["unit_id"]),
                part=part_number,
                title=title,
                text=part_text,
            )
        )

# Stable reading order: page, then paragraph / table row / figure.
chunk_records.sort(
    key=lambda r: (r["page"], TYPE_ORDER[r["unit_type"]], r["source_unit_ids"][0])
)

print(f"Units: {len(unit_dicts)}  ->  chunks: {len(chunk_records)}")

print("\nChunks by unit type:")
print(
    pd.Series([r["unit_type"] for r in chunk_records])
    .value_counts()
    .rename_axis("unit_type")
    .reset_index(name="chunks")
)

print("\nParagraph chunks built from more than one unit:")
print(
    pd.DataFrame(
        [
            {
                "chunk_id": r["chunk_id"],
                "units": r["source_unit_ids"],
                "subsection": r["subsection"],
                "chars": len(r["text"]),
            }
            for r in chunk_records
            if len(r["source_unit_ids"]) > 1
        ]
    )
)

print("\nStructured units split into several chunks:")
print(
    pd.DataFrame(
        [
            {"chunk_id": r["chunk_id"], "chars": len(r["text"])}
            for r in chunk_records
            if r["unit_type"] != "paragraph"
            and sum(
                other["source_unit_ids"] == r["source_unit_ids"]
                for other in chunk_records
            ) > 1
        ]
    )
)


# %% 10.3 Validate the Chunks
# Size cap, empty chunks, duplicate IDs, and content preservation, plus the
# LPI-specific rules:
#
# - every unit is fully preserved in the chunk(s) that carry it,
# - a table row keeps one line per column,
# - no chunk crosses a section or subsection boundary,
# - no minor heading is left as a standalone chunk.

# =========================================================
# 10.3 Chunk validation
# =========================================================

chunk_sizes = pd.Series([len(r["text"]) for r in chunk_records])

assert (chunk_sizes <= MAX_CHUNK_CHARS).all(), "A chunk exceeds the size limit."
assert (chunk_sizes > 0).all(), "Empty chunk found."

chunk_ids = [r["chunk_id"] for r in chunk_records]
assert len(chunk_ids) == len(set(chunk_ids)), "Duplicate chunk IDs."

# Table rows must keep the `Column: value` line-per-column structure.
assert all(
    "\n" in u["content"]
    for u in unit_dicts
    if u["unit_type"] == "table_row"
), "A table row lost its column line structure."

# Content preservation: every line (and every bullet) of every unit appears in the chunk text(s).
texts_by_unit = {}

for record in chunk_records:
    for unit_id in record["source_unit_ids"]:
        texts_by_unit.setdefault(unit_id, []).append(record["text"])

units_by_id = {u["unit_id"]: u for u in unit_dicts}

assert set(texts_by_unit) == set(units_by_id), "Some units are missing from the chunks."

for unit_id, unit in units_by_id.items():
    joined = "\n".join(texts_by_unit[unit_id])

    # Split on bullets too: a bulleted table cell is spread over several chunks.
    for line in unit["content"].split("\n"):
        for piece in re.split(r"\s*•\s*", line):
            if piece.strip():
                assert piece.strip() in joined, f"Content of {unit_id} is not preserved."

# No chunk crosses a section / subsection boundary.
for record in chunk_records:
    expected = (record["section"], record["subsection"])

    for unit_id in record["source_unit_ids"]:
        assert unit_location(units_by_id[unit_id]) == expected, (
            f"{record['chunk_id']} crosses a section boundary."
        )

# A minor heading must never be a standalone chunk.
standalone_headings = [
    r["chunk_id"] for r in chunk_records if is_heading_fragment(r["text"])
]
assert not standalone_headings, standalone_headings

print("Total chunks:", len(chunk_records))
print("\nChunk size statistics:")
print(chunk_sizes.describe())

print("\nSmallest chunks:")
print(
    pd.DataFrame(
        [
            {"chunk_id": r["chunk_id"], "chars": len(r["text"]), "text": r["text"][:90]}
            for r in sorted(chunk_records, key=lambda r: len(r["text"]))[:5]
        ]
    )
)

print("\nChunk validation passed.")


# %% 11. Unified Chunk Schema
# The LPI chunks use the same 16-column schema as the FBL and Suez chunks. The
# schema definition and validator below are the same code used in the FBL/Suez
# notebook, so the three resources can be concatenated into one RAG chunks table.
#
# | LPI chunk field | Unified schema field |
# |---|---|
# | first page of the chunk | `page` |
# | `unit_type` (`paragraph`, `table_row`, `figure`, `worked_example`, `definitions`) | `unit_type` |
# | unit id, e.g. `paragraph_013_014`, `table_2_row_01` | `logical_unit` |
# | `lpi_<logical_unit>_chunk_<n>` | `chunk_id` |
# | section | `parent_chunk` |
# | subsection (only when present) | `sub_chunk` (list, like FBL subclauses) |
# | table/figure caption title, else subsection, else section | `title` |
# | chunk content | `text`, `char_count` |
# | document-level values | `filename`, `source`, `real_or_synthetic`, `document_type`, `department`, `sensitivity_level`, `version_date` |
#
# The 16 columns have no place for `page_end`, `table_number`, `figure_number`,
# or `footnote_refs`. Table and figure numbers are encoded in `logical_unit` /
# `chunk_id`, informative footnotes are already inside `text`, and the
# remaining values stay in the cleaned artifact.


# %% 11.1 Schema Definition and Validator

# =========================================================
# 11.1 Canonical chunk schema (same as the FBL / Suez notebook)
# =========================================================

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

    Prints a PASS/FAIL report for every check, then raises an AssertionError
    naming the failed checks if any check failed.
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


# %% 11.2 Map the LPI Chunks to the Schema
# `source`, `sensitivity_level`, and `version_date` come from the document itself
# (`© 2026 The World Bank`, `Public Disclosure Authorized`). `document_type` and
# `department` follow the naming used for the FBL and Suez documents.

# =========================================================
# 11.2 Map LPI chunks to the unified schema
# =========================================================

lpi_metadata = {
    "filename": PDF_PATH.name,
    "source": "The World Bank",
    "real_or_synthetic": "real",
    "document_type": "methodology_report",
    "department": "Operations",
    "sensitivity_level": 1,
    "version_date": "2026",
}

lpi_chunks_df = normalize_chunk_schema(
    pd.DataFrame([
        {
            "page": record["page"],
            "unit_type": record["unit_type"],
            "logical_unit": record["logical_unit"],
            "chunk_id": record["chunk_id"],
            "parent_chunk": record["section"],
            "sub_chunk": (
                [record["subsection"]] if record["subsection"] else None
            ),
            "title": record["title"],
            "text": record["text"],
            "char_count": len(record["text"]),
            **lpi_metadata,
        }
        for record in chunk_records
    ])
)

print("Shape:", lpi_chunks_df.shape)
print(
    lpi_chunks_df[
        [
            "page", "unit_type", "logical_unit", "chunk_id",
            "parent_chunk", "sub_chunk", "title", "char_count",
        ]
    ].head(12)
)


# %% 11.3 Validate the LPI Chunks
# Run the shared validator against the LPI chunks, the same way it was run for the
# FBL and Suez chunks.

# 11.3 Schema validation for LPI chunks
validate_chunk_schema(lpi_chunks_df, "LPI_chunks")

print("Unique document-level metadata:")
print(
    lpi_chunks_df[
        [
            "filename", "source", "real_or_synthetic", "document_type",
            "department", "sensitivity_level", "version_date",
        ]
    ].drop_duplicates()
)


# %% 12. Save Chunks and Verify
# Persist the final chunks, reload them from disk, and re-run the validator against
# what was actually written. The reloaded LPI chunks are then compared with the
# saved FBL and Suez chunks, which must have identical columns and dtypes and
# non-colliding `chunk_id` values before the three sets are concatenated.

# =========================================================
# 12.1 Save and reload the LPI chunks
# =========================================================

lpi_chunks_path = CHUNKS_DIR / f"{PDF_PATH.stem}_chunks.parquet"

lpi_chunks_df.to_parquet(lpi_chunks_path, index=False)

print("Final chunks saved to:")
print(lpi_chunks_path)

lpi_reloaded_df = pd.read_parquet(lpi_chunks_path)

print(validate_chunk_schema(lpi_reloaded_df, "LPI_chunks (reloaded from disk)"))

# =========================================================
# 12.2 Cross-source check against the FBL and Suez chunks
# =========================================================

other_chunk_paths = {
    "FBL": CHUNKS_DIR / "FBL_template_chunks.parquet",
    "Suez": CHUNKS_DIR / "suez_notes_chunks.parquet",
}

loaded_chunks = {"LPI": lpi_reloaded_df}

for label, path in other_chunk_paths.items():
    if path.exists():
        loaded_chunks[label] = pd.read_parquet(path)
    else:
        print(f"{label} chunks not found at {path} -> skipped")

for label, frame in loaded_chunks.items():
    assert list(frame.columns) == list(lpi_reloaded_df.columns), (
        f"{label}: column names or order differ from the LPI chunks."
    )
    assert frame.dtypes.astype(str).equals(lpi_reloaded_df.dtypes.astype(str)), (
        f"{label}: dtypes differ from the LPI chunks."
    )

combined_chunks_df = pd.concat(loaded_chunks.values(), ignore_index=True)

assert combined_chunks_df["chunk_id"].is_unique, "chunk_id collision across resources."

print("===================================")
print("UNIFIED SCHEMA CROSS-SOURCE CHECK: PASSED")
print("===================================")

for label, frame in loaded_chunks.items():
    print(f"{label} rows: {len(frame)}")

print("Combined rows:", len(combined_chunks_df))
