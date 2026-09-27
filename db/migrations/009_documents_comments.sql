-- =====================================================================
-- 009 — Column comments of documents (008 commented the table only)
-- Decisions: ADR-009, ADR-033.
-- =====================================================================
BEGIN;

COMMENT ON COLUMN public.documents.document_id IS 'Stable slug of the source, e.g. lpi_methodology; carried in every Qdrant payload';
COMMENT ON COLUMN public.documents.filename IS 'File name under Data/raw/...';
COMMENT ON COLUMN public.documents.title IS 'Document title';
COMMENT ON COLUMN public.documents.source IS 'Publisher, e.g. The World Bank';
COMMENT ON COLUMN public.documents.real_or_synthetic IS 'real or synthetic';
COMMENT ON COLUMN public.documents.document_type IS 'Same values as the chunk column document_type';
COMMENT ON COLUMN public.documents.department_id IS 'Owner department (default; a chunk may differ, ADR-021)';
COMMENT ON COLUMN public.documents.sensitivity_level IS 'Default level 1-3; a chunk may be higher (ADR-021)';
COMMENT ON COLUMN public.documents.version_date IS 'As published; precision varies by source';
COMMENT ON COLUMN public.documents.ingestion_scope IS 'Part of the document ingested; NULL = whole document';
COMMENT ON COLUMN public.documents.source_url IS 'Where the document was obtained';
COMMENT ON COLUMN public.documents.sha256 IS 'Fingerprint of the raw file (change detection); a new version = a new row';
COMMENT ON COLUMN public.documents.file_size_bytes IS 'Raw file size';
COMMENT ON COLUMN public.documents.page_count IS 'Pages of the raw file';
COMMENT ON COLUMN public.documents.chunk_count IS 'Chunks produced; NULL until chunked';
COMMENT ON COLUMN public.documents.ingested_at IS 'When loaded into Qdrant; NULL until then';
COMMENT ON COLUMN public.documents.created_at IS 'Row creation time';

COMMIT;
