"""Shared code of the RAG retrieval pipelines (decision D11 of the RAG plan, ADR-039).

Written once, imported by the retrieval scripts (Phases 2, 4, 5, 6) and the PDF ingestion script (Phase 8):

- `common`        project root, `.env` loading, secret redaction
- `chunks`        the 16-column chunk schema (ARCHITECTURE §5) and its checks
- `embeddings`    API embedding client: per-provider budgets, retries, resumable cache keyed by text SHA-256
- `qdrant_store`  the `nilegate_docs` collection spec, point identity, version-safe upsert, verification
- `evaluation`    retrieval / ranking / context metrics on the golden set and golden facts (ADR-040)
- `retrieval`     `search_documents`: RBAC inside every prefetch, metadata filters, query cache, rate policy

Scripts import it after putting the project root on `sys.path`:

    sys.path.insert(0, str(ROOT)); from pipelines.lib import chunks, embeddings
"""
