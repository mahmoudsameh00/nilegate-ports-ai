## Final Checkpoint

| Phase | What | Problem found | Fix / consequence |
|---|---|---|---|
| 1 | Raw PDFs ↔ chunk files | — | 29 files on both sides; 2,163 chunks; one source / type / version date per file. |
| 2 | Rows | Six sources have no title in their PDF metadata (HbR's is Dutch); the download URLs were never recorded; HbR mixes levels | Titles taken as printed (first page / metadata); `source_url` NULL, not invented; document defaults = the majority of the chunks, chunk values stay authoritative (HbR: 5 chunks above the default). |
| 3 | Mirror + migration | — | `documents.csv` and `010_fill_documents.sql` generated from the same frame. |
| 4 | Database vs mirror | — | Equal on every column of the 29 rows (read-only check); `ingested_at` NULL until Qdrant. |
