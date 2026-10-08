# NileGate Document v1 — the company document shape

Every document an employee uploads to the assistant follows this one shape (RAG plan Phase 8, owner decision D15;
ADR-042). The assistant checks it at upload time and says exactly what to fix. A filled example:
`docs/templates/NileGate_document_v1_example.docx`. Checked by `pipelines/lib/uploads.py` (`validate_upload`).

## File

- **PDF or DOCX** (owner decision Q6), made from the company template — not a scan: every page needs real text
  (no OCR at upload time).
- At most **5 MB**, **30 pages** (PDF) and **60,000 characters** of body text; a DOCX may not expand beyond 25 MB.
- No macros, embedded files or objects, ActiveX, form fields, JavaScript, remote templates, DDE / INCLUDE fields,
  and no links other than `https://`. A file with any of these is refused as a whole.
- No password protection or encryption.

## 1. Metadata block (first thing in the document)

One `key: value` per line between the two marker lines. Every field is required; nothing is guessed.

```text
NILEGATE-DOC v1
document_code: NG-OPS-PRC-0042
title: Reefer Container Pre-Trip Inspection Procedure
document_type: procedure
department: Operations
sensitivity_level: 1
version_date: 2026-03-15
language: en
data_origin: internal
personal_data: no
END-METADATA
```

| Field | Allowed values | Used for |
|---|---|---|
| `document_code` | `NG-<DEPT>-<TYPE>-<NNNN>`; DEPT `OPS` `CUS` `FIN` `HR` `IT`; TYPE `POL` `PRC` `CIR` `RPT` `MIN` `GDL` | the document id (`ng_ops_prc_0042`); must match `department` and `document_type` |
| `title` | 10-200 characters | citations; the first part of every chunk title |
| `document_type` | `policy`, `procedure`, `circular`, `report`, `minutes`, `guideline` | filters |
| `department` | `Operations`, `Customs`, `Finance`, `HR`, `IT` | owner department (ADR-006) |
| `sensitivity_level` | `1`, `2`, `3` | access (ADR-006); **you cannot upload a document above your own access** |
| `version_date` | `YYYY-MM-DD`, not in the future | filters (year) |
| `language` | `en`, `ar` | evaluation per language |
| `data_origin` | `public`, `internal` | which embedding service may see it (ADR-037) |
| `personal_data` | `yes`, `no` | the same; `yes` can never be promoted on the free tier |

## 2. Sections

- Numbered headings, bold (PDF) or a Heading style (DOCX): `1. Purpose`, `2. Scope`, then any numbered sections,
  `3.`, `3.1`, `3.1.1` (at most three levels). The numbers follow each other: no gaps, no jumps.
- **`1. Purpose` and `2. Scope` are required** (`1. الغرض`, `2. النطاق` in an Arabic document).
- Inside a section: paragraphs, bullet lists (bullets or letters, never `1.` — numbers are for headings), simple
  tables, and figures with a `Figure N:` caption (the image itself is not read).
- No text before `1. Purpose` other than the metadata block.

## 3. Footer on every page

```text
NileGate · NG-OPS-PRC-0042 · page 2 of 5 · level 1
```

The code and the level must equal the metadata block (a page pasted from another document is refused).

## What happens at upload

| Finding | Result |
|---|---|
| a shape error (missing field, wrong code, heading gap, no footer, scan, above your access) | refused; every problem listed |
| active content, macros, embedded files, encryption | refused as a whole |
| hidden text (white, < 4 pt, invisible, Word "hidden") or instruction-like text inside a section | **that section is removed**, you are told which and why, the rest is used (owner decision Q8) |
| instruction-like text in the metadata block or the footer | refused |
| comments, deleted tracked changes, file properties | never read (you are told) |

An accepted upload serves **only the conversation it was uploaded in** and disappears with it (8 hours at most).
A **manager** may ask for a document of **their own department** to join the shared corpus; the request is reviewed
by the system owner before anything is added (D12, Q3).
