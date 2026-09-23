-- =====================================================================
-- 002 — Create documents (RAG document registry / lineage)
-- Decisions: ADR-009 (document-level metadata lives here, not in the chunk schema),
--            ADR-006 (RBAC: sensitivity ceiling + owner department).
-- One row per ingested source file. Qdrant chunk payloads carry document_id.
-- =====================================================================
BEGIN;

CREATE TABLE public.documents (
    document_id        TEXT        PRIMARY KEY,                -- stable slug, e.g. 'lpi_methodology'
    filename           TEXT        NOT NULL,                   -- file name under Data/raw/...
    title              TEXT        NOT NULL,
    source             TEXT        NOT NULL,                   -- publisher, e.g. 'The World Bank'
    real_or_synthetic  TEXT        NOT NULL CHECK (real_or_synthetic IN ('real', 'synthetic')),
    document_type      TEXT        NOT NULL,                   -- same values as the chunk column
    department_id      INTEGER     NOT NULL REFERENCES public.departments (department_id),
    sensitivity_level  SMALLINT    NOT NULL CHECK (sensitivity_level BETWEEN 1 AND 3),  -- document default; a chunk may be higher
    version_date       TEXT,                                   -- as published: '2025', '2023-01-01' (precision varies by source)
    ingestion_scope    TEXT,                                   -- e.g. 'notes_section_only'; NULL = whole document
    source_url         TEXT,
    sha256             CHAR(64)    NOT NULL UNIQUE,            -- fingerprint of the raw file (change detection)
    file_size_bytes    BIGINT      NOT NULL CHECK (file_size_bytes > 0),
    page_count         INTEGER     CHECK (page_count > 0),
    chunk_count        INTEGER     CHECK (chunk_count >= 0),   -- NULL until chunked
    ingested_at        TIMESTAMPTZ,                            -- NULL until loaded into Qdrant
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX documents_department_id_idx ON public.documents (department_id);

COMMIT;
