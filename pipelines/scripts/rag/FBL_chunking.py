"""FBL Bill of Lading — Logical-Unit Chunking Pipeline

Origin:  Converted from Notebooks/rag/FBL_chunking.ipynb (archived in docs/archive/notebooks/).
         Refactored (ADR-036 D3), cleanup level (2026-10-01): the notebook's phases, code and validations are unchanged;
         cell markers, Jupyter display() and the conversion helpers became plain sections and print(); proven by
         Appended: title / text normalization appended as the last phase (ADR-041, owner decision 2026-10-02).
         `uv run python tools/nb_to_script.py check FBL_chunking` (AST equal to the archived notebook).
Run:     uv run python tools/run.py pipelines/scripts/rag/FBL_chunking.py  (from the project root)

Reads:   Data/raw/unstructured/FBL_template.pdf
Writes:  Data/processed/rag/extracted|cleaned|chunks/ (the FBL files)
Re-run:  safe: rewrites the same three artifacts
Final Checkpoint (what was done, problems, fixes): pipelines/checkpoints/rag/FBL_chunking.md
"""

# %% FBL Bill of Lading — Logical-Unit Chunking Pipeline
# This notebook is the FBL-specific half of the Ports & Logistics AI RAG chunking pipeline. It was split out of a combined FBL + Suez Canal notebook so each resource has its own self-contained, checkpointed pipeline — the Suez Canal Transit Dues notes are processed the same way in the sibling notebook `Suez_logical_unit_chunking.ipynb`. Both notebooks are organized like the LPI Methodology chunking notebook: classify → extract → build structure-aware logical units → chunk → validate against the shared schema → save → checkpoint.
#
# **Document:** `FBL_template.pdf` — the FIATA Negotiable Multimodal Transport Bill of Lading template (3 PDF pages).
#
# **Why simple page-by-page extraction is not enough:** page 1 is a form (fields, not prose), page 2 mixes a Definitions block with 19 numbered clauses and subclauses, and page 3 is explanatory text with its own internal sections. A generic extractor would flatten the form fields into noise and lose the clause/subclause boundaries that make each piece of text answerable on its own.
#
# So the notebook works in **steps**, each one making one kind of decision and handing a clean result to the next:
#
# `classification → reconstructed text → logical units → chunks → unified schema → saved files`


# %% 1. Document Classification
# Every document in the RAG corpus is classified before extraction, using the same fields as the Suez Canal Notes and LPI Methodology documents: `source`, `real_or_synthetic`, `document_type`, `department`, `sensitivity_level`, `version_date`, and `ingestion_scope`. This keeps document-level metadata consistent across the project's document classification table.
#
# `FBL_template.pdf` is a real, publicly issued FIATA template — not project-synthetic data — so it carries no confidential business data, and the whole 3-page document is in scope for retrieval (`ingestion_scope: full_document`).

import pandas as pd

fbl_classification = pd.DataFrame([{
    "filename": "FBL_template.pdf",
    "source": "FIATA",
    "real_or_synthetic": "real",
    "document_type": "bill_of_lading_template",
    "department": "Operations",
    "sensitivity_level": 1,
    "version_date": None,
    "ingestion_scope": "full_document",
}])

print(fbl_classification.to_string(index=False))


# %% 2. Content Extraction and Reconstruction
# The FBL requires document-specific processing because its PDF structure is different from a standard text document: it contains a form page, multi-column content, definitions, numbered clauses and subclauses, and explanatory sections. Page-level `get_text()` extraction alone is not sufficient here.
#
# This step loads the PDF and reconstructs clean, page-aware text using each page's actual block coordinates. It only repairs PDF-extraction artifacts (broken characters, spacing, mis-ordered columns); it does not change any wording, so the reconstructed text stays source-faithful. The result is divided into logical units in Section 3, and only into retrieval chunks in Section 4.

from pathlib import Path

# Locate the project root by walking up from the notebook's folder until the
# FBL PDF is found (same pattern as the LPI notebook's setup cell), so the
# notebook does not depend on one machine's absolute path.
PDF_RELATIVE_PATH = Path("Data/raw/unstructured/FBL_template.pdf")

search_roots = [Path.cwd(), *Path.cwd().parents]

PROJECT_ROOT = next(
    (root for root in search_roots if (root / PDF_RELATIVE_PATH).exists()),
    None,
)

if PROJECT_ROOT is None:
    raise FileNotFoundError(
        f"{PDF_RELATIVE_PATH} not found above {Path.cwd()}"
    )

fbl_path = PROJECT_ROOT / PDF_RELATIVE_PATH
PROCESSED_RAG_DIR = PROJECT_ROOT / "Data" / "processed" / "rag"

import fitz
import re



def clean_text(text):
    if not text:
        return ""

    text = text.replace("\x00", " ")
    text = text.replace("\x1f", "[ ]")

    # Fix words split across PDF line breaks
    text = re.sub(r"(\w+)-\s*\n\s*([a-z])", r"\1\2", text)

    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def get_blocks(page):
    blocks = []

    for block_no, block in enumerate(page.get_text("blocks")):
        x0, y0, x1, y1, text, *_ = block

        text = text.strip()

        if not text:
            continue

        blocks.append({
            "block_no": block_no,
            "x0": x0,
            "y0": y0,
            "x1": x1,
            "y1": y1,
            "text": text
        })

    return blocks


def is_artifact(text):
    t = text.lower().strip()

    return (
        "text authorized by fiata" in t
        or "copyright reserved" in t
        or "fiata fbl black_pantone" in t
        or re.search(r"\bseite\s+\d+\b", t) is not None
    )


def join_clause_headers(text):
    """
    Page 2:
        1.
        Applicability

    ->
        1. Applicability
    """

    lines = text.splitlines()
    output = []

    i = 0

    while i < len(lines):

        current = lines[i].strip()

        if re.fullmatch(r"\d+\.", current):

            j = i + 1

            while j < len(lines) and not lines[j].strip():
                j += 1

            if j < len(lines):
                output.append(
                    f"{current} {lines[j].strip()}"
                )
                i = j + 1
                continue

        output.append(lines[i])
        i += 1

    return "\n".join(output)


def reconstruct_page_1(page):
    """
    Page 1 is a form, so reconstruct it using the actual
    coordinates of the fields.
    """

    blocks = [
        b for b in get_blocks(page)
        if not is_artifact(b["text"])
    ]

    # ---------------------------------------------------------
    # Header
    # ---------------------------------------------------------

    output = []

    # Block 0: Consignor + FBL
    header_block = next(
        (
            b for b in blocks
            if "Consignor" in b["text"]
            and "FBL" in b["text"]
        ),
        None
    )

    if header_block:
        header_lines = [
            x.strip()
            for x in header_block["text"].splitlines()
            if x.strip()
        ]

        for line in header_lines:
            output.append(line)

    # Emblem block
    emblem_block = next(
        (
            b for b in blocks
            if "Emblem" in b["text"]
            and "Association" in b["text"]
        ),
        None
    )

    if emblem_block:
        output.append(
            "Emblem of National Association"
        )

    # Title block
    title_block = next(
        (
            b for b in blocks
            if "NEGOTIABLE FIATA" in b["text"]
            and "MULTIMODAL TRANSPORT" in b["text"]
            and "BILL OF LADING" in b["text"]
        ),
        None
    )

    if title_block:
        title_lines = [
            x.strip()
            for x in title_block["text"].splitlines()
            if x.strip()
        ]

        # Merge title fragments
        title_parts = []

        for line in title_lines:
            if line.startswith("issued subject to"):
                continue
            title_parts.append(line)

        if title_parts:
            output.append(
                " ".join(title_parts)
            )

        issued_lines = [
            x.strip()
            for x in title_lines
            if x.startswith("issued subject to")
            or (
                "Multimodal Transport Documents"
                in x
            )
        ]

        if issued_lines:
            output.append(
                " ".join(issued_lines)
            )

    output.append("")

    # ---------------------------------------------------------
    # Top fields
    # ---------------------------------------------------------

    field_blocks = {
        "Consigned to order of": None,
        "Notify address": None,
        "Place of receipt": None,
        "Ocean vessel": None,
        "Port of loading": None,
        "Port of discharge": None,
        "Place of delivery": None,
    }

    for b in blocks:

        text = b["text"].strip()

        for field in field_blocks:

            if text == field:
                field_blocks[field] = b

    if field_blocks["Consigned to order of"]:
        output.append("Consigned to order of")

    if field_blocks["Notify address"]:
        output.append("Notify address")

    output.append("")

    if field_blocks["Place of receipt"]:
        output.append("Place of receipt")

    row = []

    if field_blocks["Ocean vessel"]:
        row.append("Ocean vessel")

    if field_blocks["Port of loading"]:
        row.append("Port of loading")

    if row:
        output.append(" | ".join(row))

    row = []

    if field_blocks["Port of discharge"]:
        row.append("Port of discharge")

    if field_blocks["Place of delivery"]:
        row.append("Place of delivery")

    if row:
        output.append(" | ".join(row))

    # ---------------------------------------------------------
    # Cargo fields
    # ---------------------------------------------------------

    cargo_block = next(
        (
            b for b in blocks
            if "Marks and numbers" in b["text"]
            and "Number and kind of packages" in b["text"]
            and "Description of goods" in b["text"]
            and "Gross weight" in b["text"]
            and "Measurement" in b["text"]
        ),
        None
    )

    if cargo_block:

        cargo_lines = [
            x.strip()
            for x in cargo_block["text"].splitlines()
            if x.strip()
        ]

        # The PDF extracted all five fields into one block.
        # They are actually five horizontal fields on the form.
        cargo_labels = [
            "Marks and numbers",
            "Number and kind of packages",
            "Description of goods",
            "Gross weight",
            "Measurement"
        ]

        cargo = []

        for label in cargo_labels:
            if any(label in line for line in cargo_lines):
                cargo.append(label)

        if cargo:
            output.append("")
            output.append(
                " | ".join(cargo)
            )

    # ---------------------------------------------------------
    # Declaration section
    # ---------------------------------------------------------

    declaration_reference = next(
        (
            b for b in blocks
            if b["text"].strip()
            == "according to the declaration of the consignor"
        ),
        None
    )

    declaration_interest = next(
        (
            b for b in blocks
            if "Declaration of Interest of the consignor"
            in b["text"]
        ),
        None
    )

    declared_value = next(
        (
            b for b in blocks
            if "Declared value for ad valorem rate"
            in b["text"]
        ),
        None
    )

    output.append("")

    if declaration_reference:
        output.append(
            "according to the declaration of the consignor"
        )

    if declaration_interest:
        output.append(
            clean_text(
                declaration_interest["text"]
            )
        )

    if declared_value:
        output.append(
            clean_text(
                declared_value["text"]
            )
        )

    # ---------------------------------------------------------
    # Legal statements
    # ---------------------------------------------------------

    legal_blocks = []

    for b in blocks:

        text = b["text"].strip()

        if (
            text.startswith(
                "The goods and instructions are accepted"
            )
            or text.startswith(
                "Taken in charge in apparent good order"
            )
            or text.startswith(
                "One of these Multimodal Transport Bills of Lading"
            )
        ):
            legal_blocks.append(b)

    legal_blocks.sort(
        key=lambda b: b["y0"]
    )

    output.append("")

    for b in legal_blocks:
        output.append(
            clean_text(b["text"])
        )

    # ---------------------------------------------------------
    # Bottom form
    # ---------------------------------------------------------

    bottom_blocks = []

    bottom_keywords = [
        "Freight amount",
        "Freight payable at",
        "Place and date of issue",
        "Cargo Insurance through the undersigned",
        "Number of Original FBL",
        "Stamp and signature",
        "For delivery of goods please apply to",
    ]

    for b in blocks:

        text = b["text"].strip()

        if any(
            keyword.lower() in text.lower()
            for keyword in bottom_keywords
        ):
            bottom_blocks.append(b)

    bottom_blocks.sort(
        key=lambda b: (b["y0"], b["x0"])
    )

    # Cargo insurance is one block and contains the checkboxes.
    # Keep it together.
    for b in bottom_blocks:

        text = clean_text(b["text"])

        # Avoid duplicates caused by matching the same block
        # through multiple keywords.
        if text not in output:
            output.append(text)

    return clean_text(
        "\n".join(output)
    )


def reconstruct_page_2(page):
    """
    Page 2: two-column legal document.
    """

    blocks = [
        b for b in get_blocks(page)
        if not is_artifact(b["text"])
    ]

    midpoint = page.rect.width / 2

    left = []
    right = []

    for b in blocks:

        center_x = (
            b["x0"] + b["x1"]
        ) / 2

        if center_x < midpoint:
            left.append(b)
        else:
            right.append(b)

    left.sort(
        key=lambda b: (b["y0"], b["x0"])
    )

    right.sort(
        key=lambda b: (b["y0"], b["x0"])
    )

    text = (
        "\n".join(b["text"] for b in left)
        + "\n\n"
        + "\n".join(b["text"] for b in right)
    )

    text = join_clause_headers(text)

    return clean_text(text)


def reconstruct_page_3(page):
    """
    Page 3: two-column document.

    The final checklist is special because the PDF stores:

        1.
        text...

        2.
        text...

    as separate blocks.

    We explicitly attach each number to its corresponding
    content.
    """

    blocks = [
        b for b in get_blocks(page)
        if not is_artifact(b["text"])
    ]

    # Remove printed page number "13" at the bottom.
    blocks = [
        b for b in blocks
        if not (
            b["text"].strip() == "13"
            and b["y0"] > page.rect.height * 0.90
        )
    ]

    # ---------------------------------------------------------
    # Header spanning both columns
    # ---------------------------------------------------------

    header_blocks = [
        b for b in blocks
        if b["x0"] < 100
        and b["x1"] > page.rect.width - 100
        and b["y0"] < 115
    ]

    header_blocks.sort(
        key=lambda b: b["y0"]
    )

    header_text = "\n".join(
        b["text"]
        for b in header_blocks
    )

    # Remove header blocks from columns.
    header_ids = {
        b["block_no"]
        for b in header_blocks
    }

    blocks = [
        b for b in blocks
        if b["block_no"] not in header_ids
    ]

    # ---------------------------------------------------------
    # Split columns
    # ---------------------------------------------------------

    midpoint = page.rect.width / 2

    left = []
    right = []

    for b in blocks:

        center_x = (
            b["x0"] + b["x1"]
        ) / 2

        if center_x < midpoint:
            left.append(b)
        else:
            right.append(b)

    left.sort(
        key=lambda b: (b["y0"], b["x0"])
    )

    right.sort(
        key=lambda b: (b["y0"], b["x0"])
    )

    # ---------------------------------------------------------
    # Merge the 1–5 checklist numbers with their content.
    # ---------------------------------------------------------

    number_blocks = []

    for b in right:

        if re.fullmatch(
            r"[1-5]\.",
            b["text"].strip()
        ):
            number_blocks.append(b)

    used_numbers = set()
    used_content = set()

    merged_checklist = []

    for number_block in number_blocks:

        number = number_block["text"].strip()

        candidates = [
            b for b in right
            if b["block_no"] not in used_content
            and b["block_no"] != number_block["block_no"]
            and b["x0"] > number_block["x1"]
            and abs(b["y0"] - number_block["y0"]) <= 3
        ]

        if not candidates:
            continue

        content = min(
            candidates,
            key=lambda b: b["x0"]
        )

        merged_checklist.append({
            "y0": number_block["y0"],
            "x0": number_block["x0"],
            "text":
                number
                + " "
                + content["text"]
        })

        used_numbers.add(
            number_block["block_no"]
        )

        used_content.add(
            content["block_no"]
        )

    # ---------------------------------------------------------
    # Rebuild right column.
    # ---------------------------------------------------------

    right_output = []

    for b in right:

        if b["block_no"] in used_numbers:
            continue

        if b["block_no"] in used_content:
            continue

        right_output.append({
            "y0": b["y0"],
            "x0": b["x0"],
            "text": b["text"]
        })

    right_output.extend(merged_checklist)

    right_output.sort(
        key=lambda b: (b["y0"], b["x0"])
    )

    # ---------------------------------------------------------
    # Final Page 3
    # ---------------------------------------------------------

    page_text_parts = []

    if header_text.strip():
        page_text_parts.append(header_text)

    page_text_parts.append(
        "\n".join(
            b["text"]
            for b in left
        )
    )

    page_text_parts.append(
        "\n".join(
            b["text"]
            for b in right_output
        )
    )

    return clean_text(
        "\n\n".join(page_text_parts)
    )


def reconstruct_fbl(pdf_path):

    doc = fitz.open(pdf_path)

    pages = []

    for page_number, page in enumerate(
        doc,
        start=1
    ):

        if page_number == 1:

            page_text = reconstruct_page_1(page)

        elif page_number == 2:

            page_text = reconstruct_page_2(page)

        elif page_number == 3:

            page_text = reconstruct_page_3(page)

        else:
            page_text = clean_text(
                page.get_text()
            )

        pages.append(
            f"========== PAGE {page_number} ==========\n\n"
            + page_text
        )

    doc.close()

    return "\n\n".join(pages)


# =============================================================
# FINAL RECONSTRUCTION
# =============================================================

fbl_text = reconstruct_fbl(fbl_path)

print(fbl_text)


# %% 3. Structure-Aware Logical Unit Extraction
# After reconstructing the FBL text, the document is divided according to its logical structure.
#
# Page 1 is preserved as the FBL form, while Page 2 is divided into Definitions and Clauses 1–19. Page 3 is represented by its explanatory sections.
#
# The parser also validates that all top-level clauses from 1 to 19 are detected in the expected order.

import re

def parse_fbl_logical_units(fbl_text):

    units = []

    # =========================================================
    # 1. Split FBL into physical pages
    # =========================================================

    page_pattern = re.compile(
        r"={10,}\s*PAGE\s+(\d+)\s*={10,}",
        flags=re.IGNORECASE
    )

    matches = list(page_pattern.finditer(fbl_text))

    if len(matches) != 3:
        raise ValueError(
            f"Expected 3 pages, found {len(matches)}"
        )

    pages = {}

    for i, match in enumerate(matches):

        page_number = int(match.group(1))
        start = match.end()

        if i + 1 < len(matches):
            end = matches[i + 1].start()
        else:
            end = len(fbl_text)

        pages[page_number] = fbl_text[start:end].strip()

    # =========================================================
    # 2. PAGE 1 → FBL Form
    # =========================================================

    units.append({
        "page": 1,
        "unit_type": "form",
        "logical_unit": "fbl_form",
        "clause_number": None,
        "subclause_number": None,
        "title": "Negotiable FIATA Multimodal Transport Bill of Lading",
        "text": pages[1]
    })

    # =========================================================
    # 3. PAGE 2 → Definitions + Clauses
    # =========================================================

    page2 = pages[2]

    # ---------------------------------------------------------
    # Find Clause 1
    # ---------------------------------------------------------

    clause1_match = re.search(
        r"(?m)^\s*1\.\s+Applicability\s*$",
        page2
    )

    if not clause1_match:

        # fallback: search without requiring exact line structure
        clause1_match = re.search(
            r"\b1\.\s+Applicability\b",
            page2,
            flags=re.IGNORECASE
        )

    if not clause1_match:
        raise ValueError("Could not find Clause 1 on Page 2")

    # Everything before Clause 1 belongs to Definitions
    definitions_text = page2[:clause1_match.start()].strip()

    # Remove document heading before "Definitions"
    definitions_match = re.search(
        r"\bDefinitions\b",
        definitions_text,
        flags=re.IGNORECASE
    )

    if definitions_match:
        definitions_text = definitions_text[
            definitions_match.start():
        ].strip()

    units.append({
        "page": 2,
        "unit_type": "definitions",
        "logical_unit": "definitions",
        "clause_number": None,
        "subclause_number": None,
        "title": "Definitions",
        "text": definitions_text
    })

    # ---------------------------------------------------------
    # Find all top-level clauses
    # ---------------------------------------------------------

    clause_pattern = re.compile(
        r"(?m)^\s*(\d+)\.\s+([^\n]+?)\s*$"
    )

    clause_matches = [
        m for m in clause_pattern.finditer(page2)
        if 1 <= int(m.group(1)) <= 19
    ]

    # Check that we found exactly Clauses 1–19
    clause_numbers = [int(m.group(1)) for m in clause_matches]

    if clause_numbers != list(range(1, 20)):
        raise ValueError(
            f"Expected clauses 1-19, found: {clause_numbers}"
        )

    # ---------------------------------------------------------
    # Build Clause logical units
    # ---------------------------------------------------------

    for i, match in enumerate(clause_matches):

        clause_number = int(match.group(1))
        clause_title = match.group(2).strip()

        start = match.start()

        if i + 1 < len(clause_matches):
            end = clause_matches[i + 1].start()
        else:
            end = len(page2)

        clause_text = page2[start:end].strip()

        # Remove ICC footer/note from Clause 19
        if clause_number == 19:

            footer_match = re.search(
                r"The ICC logo denotes that this document",
                clause_text,
                flags=re.IGNORECASE
            )

            if footer_match:
                clause_text = clause_text[
                    :footer_match.start()
                ].strip()

        units.append({
            "page": 2,
            "unit_type": "clause",
            "logical_unit": f"clause_{clause_number}",
            "clause_number": clause_number,
            "subclause_number": None,
            "title": clause_title,
            "text": clause_text
        })

    # =========================================================
    # 4. PAGE 3 → Semantic Logical Units
    # =========================================================

    page3 = pages[3]

    # For boundary detection only:
    # normalize whitespace temporarily.
    page3_search = re.sub(
        r"\s+",
        " ",
        page3
    ).strip()

    # ---------------------------------------------------------
    # Locate semantic boundaries
    # ---------------------------------------------------------

    liability_start = page3_search.lower().find(
        "by issuing a fbl"
    )

    issuing_start = page3_search.lower().find(
        "when issuing an fbl"
    )

    insurance_start = page3_search.lower().find(
        "freight forwarders issuing fbls have to insure their liability"
    )

    if liability_start == -1:
        raise ValueError(
            "Could not find Liability Limits section on Page 3"
        )

    if issuing_start == -1:
        raise ValueError(
            "Could not find Issuing Requirements section on Page 3"
        )

    if insurance_start == -1:
        raise ValueError(
            "Could not find Liability Insurance section on Page 3"
        )

    # ---------------------------------------------------------
    # Overview
    # ---------------------------------------------------------

    overview_text = page3_search[:liability_start].strip()

    # Remove document title
    overview_text = re.sub(
        r"^FBL\s+Negotiable FIATA Multimodal Transport Bill of Lading\s*",
        "",
        overview_text,
        flags=re.IGNORECASE
    ).strip()

    units.append({
        "page": 3,
        "unit_type": "explanatory",
        "logical_unit": "fbl_overview",
        "clause_number": None,
        "subclause_number": None,
        "title": "FBL Overview",
        "text": overview_text
    })

    # ---------------------------------------------------------
    # Liability Limits
    # ---------------------------------------------------------

    liability_text = page3_search[
        liability_start:issuing_start
    ].strip()

    units.append({
        "page": 3,
        "unit_type": "explanatory",
        "logical_unit": "liability_limits",
        "clause_number": None,
        "subclause_number": None,
        "title": "FBL Liability Limits",
        "text": liability_text
    })

    # ---------------------------------------------------------
    # Issuing FBL Requirements
    # Keep the entire checklist together
    # ---------------------------------------------------------

    issuing_text = page3_search[
        issuing_start:insurance_start
    ].strip()

    units.append({
        "page": 3,
        "unit_type": "checklist",
        "logical_unit": "issuing_fbl_requirements",
        "clause_number": None,
        "subclause_number": None,
        "title": "Requirements When Issuing an FBL",
        "text": issuing_text
    })

    # ---------------------------------------------------------
    # Liability Insurance
    # ---------------------------------------------------------

    insurance_text = page3_search[
        insurance_start:
    ].strip()

    units.append({
        "page": 3,
        "unit_type": "explanatory",
        "logical_unit": "liability_insurance",
        "clause_number": None,
        "subclause_number": None,
        "title": "Liability Insurance",
        "text": insurance_text
    })

    return units

fbl_units = parse_fbl_logical_units(fbl_text)


# %% 3.1 Normalize the Logical-Unit Text
# The reconstructed text still carries three PDF-layout artifacts that are not part of the document's wording:
#
# 1. **Hard line wraps.** Page 2 prints the Definitions and Clauses 1–19 in narrow columns, so almost every sentence is broken across several lines (and one column break leaves a stray blank line inside Clause 8). Page-3 sections are already single paragraphs, so without this step the two halves of the document would be formatted differently.
# 2. **A duplicated fragment on the form.** The form's title block and its "issued subject to …" line were merged from overlapping PDF blocks, so *"Multimodal Transport Documents (ICC Publication 481)."* appeared twice.
# 3. **Trailing spaces** at the end of ten lines.
#
# Line breaks are re-joined only where the PDF broke a sentence; every structural break is kept — the clause heading, each subclause (`6.1.`), each list item (`a)`), each definition (`–`), and each new paragraph. The form stays one field label per line. The cell asserts that every non-form unit keeps exactly the same words in the same order, so this step changes layout only, not content.

# Units whose text comes from page 2's prose (Definitions + Clauses 1–19)
# keep the PDF's visual line wrapping; the form (page 1) is line-oriented
# by design and the page-3 sections are already single paragraphs.
STRUCTURAL_LINE = re.compile(r"^(\d+\.\d+\.|[a-z]\)|–)")


def unwrap_pdf_lines(text):
    """
    Re-join lines the PDF broke mid-sentence.

    The first line (the unit heading) is kept as it is, and blank lines left
    by the two-column page layout are dropped.
    Any other line break is kept only when the next line starts a new
    structural element (subclause "6.1.", list item "a)", definition "–"),
    or when the current line ends a sentence and the next line starts a
    new paragraph with a capital letter. Every other break is replaced by
    a single space, so no wording is changed.
    """

    lines = [line.rstrip() for line in text.split("\n") if line.strip()]
    output = [lines[0]]

    for line in lines[1:]:
        previous = output[-1]

        keep_break = (
            len(output) == 1                      # heading line
            or STRUCTURAL_LINE.match(line)
            or (
                previous.endswith((".", ";", ":"))
                and not line[0].islower()
            )
        )

        if keep_break:
            output.append(line)
        else:
            output[-1] = previous + " " + line.lstrip()

    return "\n".join(output)


def drop_repeated_tail(text, min_length=20):
    """
    Remove a trailing fragment of a line when the next line ends with the
    same fragment (a block-merge duplicate from the form reconstruction).
    """

    lines = text.split("\n")

    for i in range(len(lines) - 1):
        current, following = lines[i], lines[i + 1]
        words = current.split(" ")

        for start in range(1, len(words)):
            tail = " " + " ".join(words[start:])
            if len(tail) >= min_length and following.endswith(tail):
                lines[i] = " ".join(words[:start])
                break

    return "\n".join(lines)


def unwrap_form_lines(text, min_prose_length=60):
    """
    The form is line-oriented (one field label per line), so only
    sentence wraps are re-joined: a line is appended to the previous one
    when it starts in lower case, or when the previous line is a long
    prose line that stops mid-sentence (ends in a lower-case word).
    Field labels, headings, and completed sentences are never merged.
    """

    output = []

    for line in text.split("\n"):
        previous = output[-1] if output else ""

        is_wrap = (
            previous.strip()
            and line.strip()
            and not previous.isupper()            # headings stay separate
            and (
                line[0].islower()
                or (
                    len(previous) >= min_prose_length
                    and previous[-1].islower()
                )
            )
        )

        if is_wrap:
            output[-1] = previous + " " + line.lstrip()
        else:
            output.append(line)

    return "\n".join(output)


def normalize_unit_text(unit):
    text = unit["text"]

    if unit["unit_type"] == "form":
        text = "\n".join(line.rstrip() for line in text.split("\n"))
        text = drop_repeated_tail(text)
        text = unwrap_form_lines(text)
    elif unit["page"] == 2:
        text = unwrap_pdf_lines(text)

    return {**unit, "text": text.strip()}


raw_units = fbl_units

fbl_units = [normalize_unit_text(unit) for unit in raw_units]

# Normalization only changes whitespace/line breaks, apart from the
# duplicated fragment removed from the form's title line: every other
# unit must keep exactly the same words in the same order.
for raw, clean in zip(raw_units, fbl_units):
    if clean["unit_type"] != "form":
        assert raw["text"].split() == clean["text"].split(), raw["logical_unit"]

removed_words = len(raw_units[0]["text"].split()) - len(fbl_units[0]["text"].split())

print("Logical units:", len(fbl_units))
print("Characters before normalization:", sum(len(u["text"]) for u in raw_units))
print("Characters after normalization: ", sum(len(u["text"]) for u in fbl_units))
print("Word sequence preserved in all non-form units: True")
print("Duplicated words removed from the form:", removed_words)

for i, unit in enumerate(fbl_units):

    print(
        f"{i:02d} | "
        f"Page {unit['page']} | "
        f"{unit['unit_type']:12} | "
        f"{unit['logical_unit']:30} | "
        f"{len(unit['text']):5} chars | "
        f"{unit['title']}"
    )

fbl_units_df = pd.DataFrame(fbl_units)

fbl_units_df["char_count"] = fbl_units_df["text"].str.len()

print(fbl_units_df[
    [
        "logical_unit",
        "title",
        "char_count"
    ]
].sort_values("char_count", ascending=False))


# %% 3.2 Identifying Large Logical Units
# The extracted logical units are inspected by character count to identify units that may be too large for a single retrieval chunk.
#
# A threshold of 2000 characters is used for this inspection. Large clauses are then examined at the subclause level so that any required splitting follows the document's existing structure.

large_units = [
    unit for unit in fbl_units
    if len(unit["text"]) > 2000
]

for unit in large_units:
    print("\n" + "=" * 80)
    print(
        unit["logical_unit"],
        "|",
        unit["title"],
        "|",
        len(unit["text"]),
        "chars"
    )
    print("=" * 80)
    print(unit["text"])

large_clauses = [
    unit for unit in fbl_units
    if unit["logical_unit"] in ["clause_6", "clause_8", "clause_13"]
]

for unit in large_clauses:
    print("\n" + "=" * 80)
    print(f"{unit['logical_unit']} | {unit['title']}")
    print("=" * 80)

    # Find subclauses like 6.1., 6.2., 8.1., 13.1., etc.
    pattern = rf"(?m)^\s*{unit['clause_number']}\.(\d+)\.\s+"

    matches = list(re.finditer(pattern, unit["text"]))

    for i, match in enumerate(matches):
        subclause_number = int(match.group(1))

        start = match.start()

        if i + 1 < len(matches):
            end = matches[i + 1].start()
        else:
            end = len(unit["text"])

        subclause_text = unit["text"][start:end].strip()

        print(
            f"{unit['clause_number']}.{subclause_number}"
            f" → {len(subclause_text)} chars"
        )


# %% 4. Structure-Aware Chunking
# Large FBL clauses are split using their natural subclause boundaries rather than arbitrary character positions.
#
# Clauses 6, 8, and 13 are divided according to predefined groups of subclauses. The parent clause heading is retained in every resulting chunk so that each chunk remains understandable when retrieved independently.
#
# FBL's own structure is expressed in legal clauses and subclauses, but the resulting chunks store that relationship in the generic `parent_chunk` / `sub_chunk` fields of the unified schema (defined in Section 5). Keeping the field names generic lets other resource types — sections, articles, list items, and so on — reuse the same schema without being described as "clauses".

import re


def split_clause_by_subclauses(unit, groups):

    text = unit["text"]
    clause_number = unit["clause_number"]

    pattern = rf"(?m)^\s*{clause_number}\.(\d+)\.\s+"
    matches = list(re.finditer(pattern, text))

    subclauses = {}

    for i, match in enumerate(matches):

        sub_number = match.group(1)

        start = match.start()

        if i + 1 < len(matches):
            end = matches[i + 1].start()
        else:
            end = len(text)

        subclauses[sub_number] = text[start:end].strip()

    chunks = []

    # Extract the main clause heading
    first_subclause_start = matches[0].start()

    clause_heading = text[:first_subclause_start].strip()

    for chunk_index, group in enumerate(groups, start=1):

        chunk_parts = []

        for sub_number in group:

            if sub_number not in subclauses:
                raise ValueError(
                    f"Could not find subclause "
                    f"{clause_number}.{sub_number}"
                )

            chunk_parts.append(subclauses[sub_number])

        # IMPORTANT:
        # Keep the main clause heading inside every chunk
        chunk_text = "\n\n".join(
            [clause_heading] + chunk_parts
        )

        chunks.append({
            "page": unit["page"],
            "unit_type": unit["unit_type"],
            "logical_unit": unit["logical_unit"],
            "chunk_id": f"{unit['logical_unit']}_chunk_{chunk_index}",
            # Generic structural fields: for FBL these hold the clause
            # number and the subclause numbers it was split from, but
            # another resource type could use section IDs or list
            # positions instead.
            "parent_chunk": clause_number,
            "sub_chunk": [
                f"{clause_number}.{x}" for x in group
            ],
            "title": unit["title"],
            "text": chunk_text,
            "char_count": len(chunk_text)
        })

    return chunks


def build_fbl_final_chunks(fbl_units, threshold=2000):

    final_chunks = []

    split_plan = {
        6: [
            ["1", "2", "3", "4"],
            ["5"],
            ["6"]
        ],
        8: [
            ["1", "2", "3"],
            ["4", "5", "6"],
            ["7", "8", "9"]
        ],
        13: [
            ["1", "2", "3", "4"],
            ["5"],
            ["6"]
        ]
    }

    for unit in fbl_units:

        # -----------------------------------------------------
        # Normal logical unit
        # -----------------------------------------------------

        if len(unit["text"]) <= threshold:

            final_chunks.append({
                "page": unit["page"],
                "unit_type": unit["unit_type"],
                "logical_unit": unit["logical_unit"],
                "chunk_id": f"{unit['logical_unit']}_chunk_1",
                "parent_chunk": unit["clause_number"],
                "sub_chunk": None,
                "title": unit["title"],
                "text": unit["text"],
                "char_count": len(unit["text"])
            })

        # -----------------------------------------------------
        # Large logical unit → split according to structure
        # -----------------------------------------------------

        else:

            clause_number = unit["clause_number"]

            if clause_number not in split_plan:
                raise ValueError(
                    f"Large unit '{unit['logical_unit']}' "
                    f"has no defined split plan."
                )

            chunks = split_clause_by_subclauses(
                unit,
                split_plan[clause_number]
            )

            final_chunks.extend(chunks)

    return final_chunks

fbl_chunks = build_fbl_final_chunks(fbl_units)

fbl_chunks_df = pd.DataFrame(fbl_chunks)

print("Total final chunks:", len(fbl_chunks_df))

print(fbl_chunks_df[
    [
        "chunk_id",
        "logical_unit",
        "sub_chunk",
        "char_count",
        "title"
    ]
])


# %% 4.1 Validate the Chunks
# The final FBL chunks are validated for size, empty content, duplicate identifiers, and overall chunk distribution.
#
# Additional validation checks that the original subclauses remain fully preserved after splitting.

# =========================================================
# Validate final FBL chunks
# =========================================================

print("Total chunks:", len(fbl_chunks_df))

# 1. Check maximum chunk size
print(
    "Maximum chunk size:",
    fbl_chunks_df["char_count"].max()
)

# 2. Check minimum chunk size
print(
    "Minimum chunk size:",
    fbl_chunks_df["char_count"].min()
)

# 3. Check chunks above threshold
print(
    "Chunks above 2000 chars:",
    (fbl_chunks_df["char_count"] > 2000).sum()
)

# 4. Check empty chunks
print(
    "Empty chunks:",
    (fbl_chunks_df["text"].str.strip() == "").sum()
)

# 5. Check duplicated chunk IDs
print(
    "Duplicate chunk IDs:",
    fbl_chunks_df["chunk_id"].duplicated().sum()
)

# =========================================================
# Content preservation validation
# =========================================================

original_chars = sum(
    len(unit["text"])
    for unit in fbl_units
)

chunked_chars = sum(
    len(chunk["text"])
    for chunk in fbl_chunks
)

print("Original logical-unit characters:", original_chars)
print("Final chunk characters:", chunked_chars)
print("Difference:", original_chars - chunked_chars)

# =========================================================
# Validate that every subclause is preserved
# =========================================================

for clause_number in [6, 8, 13]:

    original_unit = next(
        unit for unit in fbl_units
        if unit["clause_number"] == clause_number
    )

    original_text = original_unit["text"]

    pattern = rf"(?m)^\s*{clause_number}\.(\d+)\.\s+"
    matches = list(re.finditer(pattern, original_text))

    print("\n" + "=" * 70)
    print(f"Clause {clause_number}")
    print("=" * 70)

    for i, match in enumerate(matches):

        sub_number = match.group(1)
        start = match.start()

        if i + 1 < len(matches):
            end = matches[i + 1].start()
        else:
            end = len(original_text)

        subclause_text = original_text[start:end].strip()

        # Find the corresponding final chunk
        matching_chunks = [
            chunk
            for chunk in fbl_chunks
            if f"{clause_number}.{sub_number}"
            in (chunk["sub_chunk"] or [])
        ]

        preserved = any(
            subclause_text in chunk["text"]
            for chunk in matching_chunks
        )

        print(
            f"{clause_number}.{sub_number} "
            f"→ preserved: {preserved}"
        )

# Final FBL chunking validation

print("Total chunks:", len(fbl_chunks_df))

print("\nMissing text:")
print(fbl_chunks_df["text"].isna().sum())

print("\nEmpty chunks:")
print((fbl_chunks_df["text"].str.strip() == "").sum())

print("\nChunk size statistics:")
print(fbl_chunks_df["char_count"].describe())

print("\nDuplicate chunks:")
print(
    fbl_chunks_df["text"]
    .duplicated()
    .sum()
)

print("\nChunk distribution by logical unit:")
print(
    fbl_chunks_df["logical_unit"]
    .value_counts()
    .sort_index()
)

print("\nOversized chunks (> 2000 chars):")
print(
    fbl_chunks_df[
        fbl_chunks_df["char_count"] > 2000
    ][
        ["chunk_id", "logical_unit", "char_count"]
    ]
)


# %% 5. Unified Chunk Schema
# The FBL chunks are mapped onto the same 16-column chunk schema used for the Suez Canal Notes and LPI Methodology chunks, so all three resource types can live in one retrieval table. `parent_chunk` / `sub_chunk` hold the FBL clause/subclause numbers, but the field names stay generic so other resource types (sections, articles, list items, …) can reuse the same schema. Document-level metadata — filename, source, document type, department, sensitivity level, version date — is attached alongside the structural fields already produced during chunking.


# %% 5.1 Schema Definition and Validator
# `CHUNK_SCHEMA` and its two helpers (`normalize_chunk_schema`, `validate_chunk_schema`) are the same code used in the Suez Canal Notes and LPI notebooks. Defining them here keeps this notebook runnable on its own.

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


# %% 5.2 Map FBL Chunks to the Schema
# Attach the FBL document-level metadata to every chunk — read directly from the Section 1 classification table, so chunk metadata always matches the corpus-wide classification — then normalize column order and nullable dtypes with `normalize_chunk_schema`. This step only standardizes structure — it does not rewrite any chunk text.

# Document-level metadata is taken from the Section 1 classification table,
# so the chunks always carry the corpus-wide classification values.
fbl_document = fbl_classification.iloc[0]

fbl_chunks_df["filename"] = fbl_document["filename"]

for key in [
    "source",
    "real_or_synthetic",
    "document_type",
    "department",
    "sensitivity_level",
    "version_date",
]:
    fbl_chunks_df[key] = fbl_document[key]

# Schema-only refinement: preserve all chunk values and normalize
# their column order and nullable data types.
fbl_chunks_df = normalize_chunk_schema(fbl_chunks_df)

print("Columns:")
print(fbl_chunks_df.columns.tolist())

print("\nShape:")
print(fbl_chunks_df.shape)

print("\nMetadata sample:")
print(
    fbl_chunks_df[
        [
            "filename",
            "source",
            "real_or_synthetic",
            "document_type",
            "department",
            "sensitivity_level",
            "version_date",
            "page",
            "logical_unit",
            "chunk_id",
            "parent_chunk",
            "sub_chunk",
            "title",
            "char_count",
        ]
    ].head()
)


# %% 5.3 Validate the FBL Chunks
# Run the shared schema validator against the FBL chunks — this is the FBL_chunk test — then inspect the document-level metadata that was attached to confirm every chunk carries a single, consistent set of values.

# 5.3 Metadata & schema validation for FBL chunks
validate_chunk_schema(fbl_chunks_df, "FBL_chunks")

required_metadata = [
    "filename",
    "source",
    "real_or_synthetic",
    "document_type",
    "department",
    "sensitivity_level",
    "version_date",
]

print("Unique document-level metadata:")
print(
    fbl_chunks_df[required_metadata]
    .drop_duplicates()
)

print("\nChunk count:", len(fbl_chunks_df))
print("Unique chunk IDs:", fbl_chunks_df["chunk_id"].nunique())


# %% 5.4 Schema Generality Check
# A short, synthetic check — not derived from any PDF — confirming the same schema and validator accept a resource type that has no page number, no parent/sub-chunk relationship, and no natural title (for example, one turn of an audio-call transcript). This is the same probe used to sign off the schema before the Suez Canal Notes notebook adopted it; it is not run again there.

# A non-PDF probe proves the schema stays stable for a resource type
# that has no pages, parent/sub-chunk relationships, or a title.
probe_text = "Example audio transcript segment."
resource_schema_probe = normalize_chunk_schema(
    pd.DataFrame([
        {
            "unit_type": "transcript_segment",
            "logical_unit": "speaker_turn_001",
            "chunk_id": "audio_call_speaker_turn_001",
            "text": probe_text,
            "char_count": len(probe_text),
            "filename": "operations_call.mp3",
            "source": "Operations",
            "real_or_synthetic": "real",
            "document_type": "audio_transcript",
            "department": "Operations",
            "sensitivity_level": 1,
        }
    ])
)

validate_chunk_schema(resource_schema_probe, "Non-PDF schema probe")
assert resource_schema_probe["page"].isna().all()
assert resource_schema_probe["parent_chunk"].isna().all()


# %% 6. Save the Chunks and Verify
# Persist the reconstructed text, the normalized logical units, and the final chunks so later stages (embeddings, Qdrant ingestion) can reuse them without re-running the FBL-specific extraction and chunking logic above.

# =========================================================
# Save FBL processing artifacts
# =========================================================

from pathlib import Path
import json

# PROCESSED_RAG_DIR is resolved in the setup cell (Section 2).
extracted_dir = PROCESSED_RAG_DIR / "extracted"
cleaned_dir = PROCESSED_RAG_DIR / "cleaned"
chunks_dir = PROCESSED_RAG_DIR / "chunks"

for directory in (extracted_dir, cleaned_dir, chunks_dir):
    directory.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------
# 1. Save reconstructed/extracted text
# ---------------------------------------------------------

extracted_path = extracted_dir / "FBL_template_reconstructed.txt"

extracted_path.write_text(
    fbl_text,
    encoding="utf-8"
)

# ---------------------------------------------------------
# 2. Save cleaned logical units
# ---------------------------------------------------------

cleaned_path = cleaned_dir / "FBL_template_logical_units.json"

with open(cleaned_path, "w", encoding="utf-8") as f:
    json.dump(
        fbl_units,
        f,
        ensure_ascii=False,
        indent=2
    )

# ---------------------------------------------------------
# 3. Save final chunks
# ---------------------------------------------------------

chunks_parquet_path = chunks_dir / "FBL_template_chunks.parquet"

fbl_chunks_df.to_parquet(
    chunks_parquet_path,
    index=False
)

print("FBL artifacts saved successfully:")
print(extracted_path)
print(cleaned_path)
print(chunks_parquet_path)


# %% 6.1 Reload and Verify Saved FBL Chunks
# Reload the chunks that were just written to disk and re-run the shared schema validator against them. This confirms the parquet file on disk — not just the in-memory DataFrame — satisfies the canonical schema.

import pandas as pd

chunks_path = PROCESSED_RAG_DIR / "chunks" / "FBL_template_chunks.parquet"

chunks_df = pd.read_parquet(chunks_path)

validate_chunk_schema(chunks_df, "FBL_chunks (reloaded from disk)")

print(f"Total chunks: {len(chunks_df)}")
print(chunks_df)


# %% Final phase — Title / text normalization (ADR-041)
# One rule for the whole corpus: `title` is the chunk's location label, `text` the body only. The chunk file saved above is normalized in place by `pipelines/lib/chunks.py` (a leading heading line moves to `title`, a run-in heading is removed; lossless, idempotent, chunk ids and order unchanged), then checked against the contract and reloaded. The phases above validated the chunking itself, before this step.

import sys as _sys
from pathlib import Path as _Path

_root = next(p for p in [_Path.cwd(), *_Path.cwd().parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())
if str(_root) not in _sys.path:
    _sys.path.insert(0, str(_root))
from pipelines.lib import chunks as _chunk_contract

_kinds = _chunk_contract.normalize_chunk_file(_root / "Data" / "processed" / "rag" / "chunks" / "FBL_template_chunks.parquet", {'heading_line': 26, 'unchanged': 5})
print(f"✅ Title / text normalization passed (ADR-041): {_kinds}")
