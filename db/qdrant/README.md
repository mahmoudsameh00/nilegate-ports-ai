# Qdrant files (container `ports-qdrant`)

| Path | Purpose |
|---|---|
| `README.md` | This file: the pinned image and every command. |
| `create_container.ps1` | Creates the volume and the container once. `QDRANT_API_KEY` is read from `.env` and passed by name only (never in a command line). Refuses to run if the container exists. |
| `probe_qdrant.py` | Probe of the pinned server in a throwaway collection (deleted at the end): API key enforced, LAN closed, the collection shape we need, **server-side BM25 (D4)**, the ADR-006 filter inside both prefetches of a hybrid RRF query. Raw REST on purpose (qdrant-client could run BM25 locally and hide the answer). |
| `audit/` | Saved outputs of the probe (`YYYY-MM-DD_probe.txt`). |

The collection `nilegate_docs` is **not** created here: `pipelines/scripts/retrieval/Qdrant_loader.py` (RAG plan
Phase 5) is the only writer (ADR-031 pattern).

## Pinned image

| Item | Value |
|---|---|
| Image | `qdrant/qdrant:v1.19.1` (same minor version as `qdrant-client==1.19.1`) |
| Digest | `sha256:12364fe851b9f17356fc88189fc06d1b521262e04659ec7345975b00c9246a10` (pulled 2026-10-02) |
| Container | `ports-qdrant` |
| Volume | `ports-qdrant-data` → `/qdrant/storage` |
| Ports | `127.0.0.1:6333` (REST) and `127.0.0.1:6334` (gRPC) only |
| Security | API key required on every request (`QDRANT__SERVICE__API_KEY` from `.env` `QDRANT_API_KEY`); telemetry off |

## Commands (PowerShell, from the project root)

### First creation (done 2026-10-02)

```powershell
docker pull qdrant/qdrant:v1.19.1
powershell -NoProfile -ExecutionPolicy Bypass -File db\qdrant\create_container.ps1
```

The key is read when the container starts. To change it: update `.env`, then re-create the container (the data stays
in the volume): `docker rm -f ports-qdrant` and the script again.

### Daily use

```powershell
docker start ports-qdrant
docker ps --filter name=ports-qdrant --format "{{.Names}} | {{.Image}} | {{.Status}} | {{.Ports}}"
```

### Probe (output saved under `audit/`)

```powershell
uv run python db/qdrant/probe_qdrant.py
```

## Verified results (2026-10-02, `audit/2026-10-02_probe.txt`)

- No key / wrong key → HTTP 401; version 1.19.1; both LAN addresses refuse port 6333.
- Collection with `dense` (cosine) + `bm25` (sparse, IDF modifier) named vectors; integer and keyword payload indexes.
- **D4: server-side BM25 is available**: an upsert with `{"text", "model": "qdrant/bm25"}` stores a server-built sparse
  vector, and a BM25-only query ranks the matching text first → no `fastembed` dependency.
- Hybrid query (dense + bm25 prefetch, RRF) with the ADR-006 filter in each prefetch: the level-3 point is returned
  to the CEO only (first for its own question); a Finance employee / manager sees the level-2 Finance point, never
  the level-3 one; an Operations employee sees neither.
- Note: a payload index on an empty collection takes 9–16 s with `wait=true` (Docker Desktop volume I/O on Windows).
