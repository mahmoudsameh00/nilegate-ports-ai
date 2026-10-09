-- =====================================================================
-- 011 — Record when the RAG corpus was loaded into Qdrant (documents.ingested_at)
-- Decisions: ADR-035 (registry), ADR-039 (Qdrant point id per document version); RAG plan Phase 9 (close).
-- Value: the last full, verified load of collection `nilegate_docs` by
-- pipelines/scripts/retrieval/Qdrant_loader.py (2,163 points / 29 documents, re-validated, idempotent),
-- 2026-10-08 16:58:18 +03:00 (owner decision 2026-10-08). Qdrant keeps no load time per point.
-- Rows only (no schema change). Never edited after applying.
-- =====================================================================
BEGIN;

DO $$
BEGIN
    IF (SELECT count(*) FROM public.documents) <> 29 OR (SELECT sum(chunk_count) FROM public.documents) <> 2163 THEN
        RAISE EXCEPTION 'documents: expected the 29 rows / 2163 chunks of migration 010';
    END IF;
    IF EXISTS (SELECT 1 FROM public.documents WHERE ingested_at IS NOT NULL) THEN
        RAISE EXCEPTION 'documents: ingested_at already filled (migration 011 applied twice?)';
    END IF;
END $$;

UPDATE public.documents SET ingested_at = TIMESTAMPTZ '2026-10-08 16:58:18+03:00';

DO $$
BEGIN
    IF (SELECT count(*) FROM public.documents WHERE ingested_at = TIMESTAMPTZ '2026-10-08 16:58:18+03:00') <> 29 THEN
        RAISE EXCEPTION 'documents: ingested_at not set on all 29 rows';
    END IF;
END $$;

COMMIT;
