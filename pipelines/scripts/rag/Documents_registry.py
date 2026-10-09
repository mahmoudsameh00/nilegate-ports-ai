"""RAG document registry: fill `documents` (one row per raw PDF of the corpus) and prove the database equals the mirror.

Origin:  Converted from Notebooks/rag/Documents_registry.ipynb (archived in docs/archive/notebooks/).
         Refactored (ADR-036 D3) 2026-10-01: the same four phases as functions; same outputs byte for byte; same
         validation lines.
Run:     uv run python tools/run.py pipelines/scripts/rag/Documents_registry.py  (from the project root)

Reads:   Data/raw/unstructured/ (the 29 PDFs); Data/processed/rag/chunks/*.parquet; PostgreSQL (read-only session)
Writes:  Data/processed/rag/documents.csv; db/migrations/010_fill_documents.sql (regenerated identical; already
         applied, never re-applied)
Re-run:  safe: read-only on the database; rewrites the same two files
Final Checkpoint (what was done, problems, fixes): pipelines/checkpoints/rag/Documents_registry.md

What `documents` is (ADR-009): the registry and lineage of the RAG corpus. Every chunk (and later every Qdrant point)
carries its `document_id`, so an answer can be traced to the exact file, its fingerprint and its access defaults.

Decisions (ADR-035):
- one row per raw file: 29 rows (6 sources + 23 USCG reports — a corpus is one script but each report is its own file);
- `document_id` = a stable slug; a changed file (new `sha256`) is a new version: a new row `<slug>_v2` and re-ingestion
  of its chunks (no version-history table: all sources are fixed publications);
- `department` / `sensitivity_level` are the document defaults (the values of most of its chunks); the chunk values
  stay authoritative (ADR-021: HbR has 5 level-3 / Finance chunks under a level-1 / Operations default);
- titles as printed (PDF metadata for the USCG reports, the first page otherwise); `source_url` NULL (never recorded,
  not invented); `ingested_at` NULL until Qdrant, then filled by migration 011 (RAG plan Phase 9, 2026-10-08).

Phases
1. Inventory: raw PDFs ↔ chunk files (same 29 file names, 2,163 chunks).
2. Build the rows (reviewed slugs for the 6 single-file sources; `uscg_roi_<vessel>_<MISLE>` for the reports).
3. Save the mirror and render the migration (department looked up by name, so no serial ids in the file).
4. The database equals the mirror, column by column (read-only).
"""
import hashlib
import json
import os
from pathlib import Path

import pandas as pd
import psycopg
import pymupdf

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())
RAW = ROOT / "Data" / "raw"
CHUNKS = ROOT / "Data" / "processed" / "rag" / "chunks"
MIRROR = ROOT / "Data" / "processed" / "rag" / "documents.csv"
MIGRATION = ROOT / "db" / "migrations" / "010_fill_documents.sql"
INGESTED_AT = "2026-10-08 16:58:18+03:00"  # migration 011: the last full load of Qdrant `nilegate_docs`
COLS = ["document_id", "filename", "title", "source", "real_or_synthetic", "document_type", "department",
        "sensitivity_level", "version_date", "ingestion_scope", "source_url", "sha256", "file_size_bytes", "page_count",
        "chunk_count"]

SINGLE = {  # filename: (document_id, title as printed, ingestion_scope)
    "FBL_template.pdf": ("fbl_template", "Negotiable FIATA Multimodal Transport Bill of Lading (FBL)", None),
    "HbR_Annual_report_2025_highlights.pdf": ("hbr_annual_report_2025",
        "Havenbedrijf Rotterdam Jaarverslag 2025 (Port of Rotterdam Authority Annual Report 2025, highlights)", None),
    "LPI.pdf": ("lpi_connecting_to_compete_2025", "Connecting to Compete 2025: Trade Logistics in the Global Economy", None),
    "LPI_Methodology.pdf": ("lpi_methodology",
        "The New Logistics Performance Indicators 2.0 (LPI 2.0): Methodology and User Guide", None),
    "MSC-MEPC_3-Circ_4-Rev_1.pdf": ("imo_msc_mepc_3_circ_4_rev_1",
        "MSC-MEPC.3/Circ.4/Rev.1 — Casualty-related matters: Reports on marine casualties and incidents", None),
    "Transit_Dues_Rates.pdf": ("suez_transit_dues_2023",
        "Suez Canal Authority “Transit Dues Rates” Schedules applicable from the first of January, 2023",
        "notes_section_only"),
}
REVIEWED_2 = {"rows": 29, "chunks": 2163, "pages": 765,  # reviewed 2026-09-27
              "by_department_level": {"Finance|1": 1, "Operations|1": 28}}


def load_env() -> None:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def connect_ro() -> psycopg.Connection:
    env = os.environ
    return psycopg.connect(host=env["PGHOST"], port=env["PGPORT"], dbname=env["PGDATABASE"], user=env["PGUSER"],
                           password=env["PGPASSWORD"], options="-c default_transaction_read_only=on")


# ---------------------------------------------------------------------------------------------------- phase 1

def inventory() -> tuple[pd.DataFrame, dict[str, Path]]:
    chunks = pd.concat([pd.read_parquet(f) for f in sorted(CHUNKS.glob("*.parquet"))], ignore_index=True)
    pdfs = {p.name: p for p in sorted((RAW / "unstructured").rglob("*.pdf"))}
    print("chunks:", len(chunks), "| chunk filenames:", chunks["filename"].nunique(), "| raw PDFs:", len(pdfs))
    assert set(chunks["filename"]) == set(pdfs), set(chunks["filename"]) ^ set(pdfs)
    assert len(chunks) == 2163 and chunks["chunk_id"].is_unique
    per_file = chunks.groupby("filename").agg(n=("chunk_id", "size"), versions=("version_date", "nunique"),
                                              sources=("source", "nunique"), types=("document_type", "nunique"))
    assert (per_file[["sources", "types"]] == 1).all().all() and (per_file["versions"] <= 1).all()
    print("✅ Phase 1 validation passed.")
    return chunks, pdfs


# ---------------------------------------------------------------------------------------------------- phase 2

def build_rows(chunks: pd.DataFrame, pdfs: dict[str, Path]) -> pd.DataFrame:
    with connect_ro() as conn:
        dept_id = dict(conn.execute("SELECT department_name, department_id FROM departments").fetchall())
    rows = []
    for name, path in pdfs.items():
        data = path.read_bytes()
        with pymupdf.open(path) as d:
            pages, meta_title = d.page_count, ((d.metadata or {}).get("title") or "").strip()
        c = chunks[chunks["filename"] == name]
        dept = c["department"].mode().iloc[0]
        level = int(c.loc[c["department"] == dept, "sensitivity_level"].mode().iloc[0])
        if name in SINGLE:
            doc_id, title, scope = SINGLE[name]
        else:  # USCG report: <VESSEL>_<MISLE>_ROI_Redacted.pdf, title from the PDF metadata as published
            stem = name.removesuffix("_ROI_Redacted.pdf")
            doc_id, title, scope = "uscg_roi_" + stem.lower(), " ".join(meta_title.split()), None
        vd = c["version_date"].dropna()
        rows.append({"document_id": doc_id, "filename": str(path.relative_to(RAW)).replace("\\", "/"), "title": title,
                     "source": c["source"].iloc[0], "real_or_synthetic": c["real_or_synthetic"].iloc[0],
                     "document_type": c["document_type"].iloc[0], "department": dept, "department_id": dept_id[dept],
                     "sensitivity_level": level, "version_date": vd.iloc[0] if len(vd) else None,
                     "ingestion_scope": scope, "source_url": None, "sha256": hashlib.sha256(data).hexdigest(),
                     "file_size_bytes": len(data), "page_count": pages, "chunk_count": len(c)})
    docs = pd.DataFrame(rows).sort_values("document_id").reset_index(drop=True)
    print(docs[["document_id", "department", "sensitivity_level", "version_date", "page_count", "chunk_count"]].to_string())
    mixed = {}
    for r in docs.itertuples():
        levels = chunks.loc[chunks["filename"] == Path(r.filename).name, "sensitivity_level"]
        if (levels > r.sensitivity_level).any():
            mixed[r.document_id] = int((levels > r.sensitivity_level).sum())
    print("mixed-level documents (chunk level above the default):", mixed)
    return docs


def validate_rows(docs: pd.DataFrame, chunks: pd.DataFrame) -> None:
    assert len(docs) == 29 and docs["document_id"].is_unique and docs["sha256"].is_unique
    assert docs["document_id"].str.fullmatch(r"[a-z0-9_]+").all() and docs["title"].str.len().gt(10).all()
    assert docs["sensitivity_level"].between(1, 3).all() and docs["department_id"].notna().all()
    assert docs["chunk_count"].sum() == len(chunks) and (docs["page_count"] > 0).all() and (docs["file_size_bytes"] > 0).all()
    assert docs["filename"].map(lambda f: (RAW / f).exists()).all()
    uscg = docs[docs["source"] == "United States Coast Guard"]
    assert len(uscg) == 23 and uscg["title"].str.startswith("U.S. Coast Guard Report of Investigat").all()
    actual = {"rows": len(docs), "chunks": int(docs["chunk_count"].sum()), "pages": int(docs["page_count"].sum()),
              "by_department_level": {f"{d}|{l}": int(n)
                                      for (d, l), n in docs.groupby(["department", "sensitivity_level"]).size().items()}}
    if REVIEWED_2:
        assert actual == REVIEWED_2, f"registry changed: {actual}"
    else:
        print("snapshot pending review:", json.dumps(actual))
    print("✅ Phase 2 validation passed.")


# ---------------------------------------------------------------------------------------------------- phase 3

def lit(v) -> str:
    """SQL literal: NULL, an integer, or a single-quoted string."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "NULL"
    if isinstance(v, (int,)) or (hasattr(v, "dtype") and str(v.dtype).startswith("int")):
        return str(int(v))
    return "'" + str(v).replace("'", "''") + "'"


def render_migration(docs: pd.DataFrame) -> str:
    """Migration 010 exactly as applied (its header names the notebook that generated it; never edited)."""
    values = ",\n".join(
        "    (" + ", ".join([lit(r.document_id), lit(r.filename), lit(r.title), lit(r.source), lit(r.real_or_synthetic),
                             lit(r.document_type), lit(r.department), str(int(r.sensitivity_level)), lit(r.version_date),
                             lit(r.ingestion_scope), lit(r.source_url), lit(r.sha256), str(int(r.file_size_bytes)),
                             str(int(r.page_count)), str(int(r.chunk_count))]) + ")"
        for r in docs.itertuples())
    return f"""-- =====================================================================
-- 010 — Fill the RAG document registry (29 raw files: 6 sources + 23 USCG reports)
-- Decisions: ADR-009 (registry), ADR-035 (one row per raw file, stable slugs, versions by sha256, document defaults).
-- Generated by Notebooks/rag/Documents_registry.ipynb from the raw PDFs and the chunk files; never edited after applying.
-- ingested_at stays NULL until the chunks are loaded into Qdrant.
-- =====================================================================
BEGIN;

INSERT INTO public.documents (document_id, filename, title, source, real_or_synthetic, document_type, department_id,
                              sensitivity_level, version_date, ingestion_scope, source_url, sha256, file_size_bytes,
                              page_count, chunk_count)
SELECT v.document_id, v.filename, v.title, v.source, v.real_or_synthetic, v.document_type, d.department_id,
       v.sensitivity_level, v.version_date, v.ingestion_scope, v.source_url, v.sha256, v.file_size_bytes, v.page_count,
       v.chunk_count
FROM (VALUES
{values}
) AS v (document_id, filename, title, source, real_or_synthetic, document_type, department, sensitivity_level,
        version_date, ingestion_scope, source_url, sha256, file_size_bytes, page_count, chunk_count)
JOIN public.departments d ON d.department_name = v.department;

DO $$
BEGIN
    IF (SELECT count(*) FROM public.documents) <> 29 OR (SELECT sum(chunk_count) FROM public.documents) <> 2163 THEN
        RAISE EXCEPTION 'documents: expected 29 rows and 2163 chunks';
    END IF;
END $$;

COMMIT;
"""


def save(docs: pd.DataFrame) -> None:
    docs[COLS].to_csv(MIRROR, index=False, lineterminator="\n")
    sql = render_migration(docs)
    MIGRATION.write_text(sql, encoding="utf-8", newline="\n")
    print("mirror:", MIRROR.relative_to(ROOT), "| migration:", MIGRATION.relative_to(ROOT), len(sql), "chars")
    back = pd.read_csv(MIRROR, dtype=str, keep_default_na=False)
    assert len(back) == 29 and back.columns.tolist() == COLS and back["document_id"].tolist() == docs["document_id"].tolist()
    assert MIGRATION.read_text(encoding="utf-8").count("\n    ('") == 29
    print("✅ Phase 3 validation passed.")


# ---------------------------------------------------------------------------------------------------- phase 4

def compare_with_database() -> pd.DataFrame:
    with connect_ro() as conn:
        cur = conn.execute("SELECT d.document_id, d.filename, d.title, d.source, d.real_or_synthetic, d.document_type, "
                           "p.department_name AS department, d.sensitivity_level, d.version_date, d.ingestion_scope, "
                           "d.source_url, d.sha256, d.file_size_bytes, d.page_count, d.chunk_count, d.ingested_at "
                           "FROM documents d JOIN departments p USING (department_id) ORDER BY d.document_id")
        db = pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])
    db_str = db[COLS].astype(object).where(db[COLS].notna(), "").astype(str)
    mirror = pd.read_csv(MIRROR, dtype=str, keep_default_na=False)
    assert len(db) == 29, f"documents has {len(db)} rows: apply db/migrations/010_fill_documents.sql first"
    pd.testing.assert_frame_equal(db_str.reset_index(drop=True), mirror.reset_index(drop=True), check_dtype=False)
    # migration 011 (RAG plan Phase 9): every document loaded into Qdrant by the last full Qdrant_loader run
    assert (db["ingested_at"] == pd.Timestamp(INGESTED_AT)).all(), "apply db/migrations/011_documents_ingested_at.sql"
    print("✅ Phase 4 validation passed.")
    return db


def main() -> None:
    load_env()
    chunks, pdfs = inventory()
    docs = build_rows(chunks, pdfs)
    validate_rows(docs, chunks)
    save(docs)
    db = compare_with_database()
    print(json.dumps({"rows": len(db), "chunks": int(db["chunk_count"].sum()), "pages": int(db["page_count"].sum())}))
    print("✅ Final Checkpoint validation passed.")


if __name__ == "__main__":
    main()
