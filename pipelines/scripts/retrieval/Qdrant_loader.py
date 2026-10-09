"""Load Qdrant `nilegate_docs` from the chunk files and the Phase 4 vectors (RAG plan Phase 5; the only writer).

Plan:    docs/archive/2026-10-08_RAG_Embeddings_Qdrant_plan.md, Phase 5 (pilot D6: LPI Methodology, then all chunks).
Run:     uv run python tools/run.py pipelines/scripts/retrieval/Qdrant_loader.py  (project root; ports-qdrant up)

Reads:   Data/processed/rag/chunks/*.parquet (contract incl. ADR-041); Data/processed/rag/documents.csv (document_id);
         Data/embeddings/gemini-embedding-2/manifest.json + dense_composed.parquet (ADR-037); .env (QDRANT_API_KEY)
Writes:  Qdrant collection `nilegate_docs` only (nothing on disk). Never calls an embedding API.
Re-run:  safe: point id = UUID5(document_id + chunk_id) and version-safe upserts (ADR-039); a second load changes
         nothing (asserted in Phase 5).

Collection (pipelines/lib/qdrant_store.py): named vectors `dense` (3,072, cosine; Gemini, composed unit) and `bm25`
(sparse, IDF, built by the server from the composed unit); payload = the 16 chunk columns + document_id +
text_sha256; payload indexes on sensitivity_level, department, document_id, document_type, source, real_or_synthetic.

Phases
1. Inputs: chunks, registry, vectors; the vectors are proven to be the manifest's (file hash, text hashes, order).
2. Pilot: LPI Methodology (94 chunks), loaded and fully checked on its own.
3. Full load: all 29 documents.
4. Re-validate from Qdrant: count, exact ids per document, every payload equals its chunk row, sampled stored vectors
   equal the file, the server-built bm25 vector present, payload indexes and vector config as specified.
5. Idempotence: a second full load removes nothing, adds nothing, changes no payload.
"""
# %% Setup
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())
sys.path.insert(0, str(ROOT))
from pipelines.lib import chunks as chunk_contract  # noqa: E402
from pipelines.lib import common, embeddings, qdrant_store  # noqa: E402

EMB_DIR = ROOT / "Data" / "embeddings" / "gemini-embedding-2"
REGISTRY = ROOT / "Data" / "processed" / "rag" / "documents.csv"
PILOT_DOCUMENT = "lpi_methodology"
DIM = 3072
SAMPLE_EVERY = 34  # vector spot-check: every 34th point (64 points)
REVIEWED = {"points": 2163, "documents": 29, "pilot_points": 94, "by_level": {1: 2158, 3: 5}}  # reviewed 2026-10-08


# %% Phase 1 — Inputs, and proof that the vectors are the manifest's
def inputs() -> tuple[pd.DataFrame, np.ndarray]:
    df = chunk_contract.load(ROOT / "Data" / "processed" / "rag" / "chunks")
    reg = pd.read_csv(REGISTRY)
    file_to_doc = dict(zip(reg.filename.map(lambda p: Path(p).name), reg.document_id))
    df = df.assign(document_id=df.filename.map(file_to_doc))
    assert df.document_id.notna().all() and df.document_id.nunique() == len(reg) == 29

    manifest = json.loads((EMB_DIR / "manifest.json").read_text(encoding="utf-8"))
    m = manifest["variants"][manifest["active_variant"]]
    assert manifest["active_variant"] == "composed" and m["dimension"] == DIM and m["model"] == "gemini-embedding-2"
    dense_path = EMB_DIR / m["dense_file"]
    assert hashlib.sha256(dense_path.read_bytes()).hexdigest() == m["dense_sha256"], "vector file != manifest"
    dense = pd.read_parquet(dense_path)
    units = [chunk_contract.compose(t, x) for t, x in zip(df.title, df.text)]
    df["text_sha256"] = [embeddings.sha256_text(u) for u in units]
    assert dense.chunk_id.tolist() == df.chunk_id.tolist(), "vector order != chunk order"
    assert dense.text_sha256.tolist() == df.text_sha256.tolist(), "a vector was computed from another text"
    mat = np.stack(dense.vector.to_numpy())
    assert mat.shape == (len(df), DIM) and np.isfinite(mat).all()
    return df, mat


def rows_of(df: pd.DataFrame) -> list[dict]:
    return [qdrant_store.payload(r, r["document_id"], r["text_sha256"]) for r in df.to_dict("records")]


def load_documents(client, df: pd.DataFrame, mat: np.ndarray, document_ids: list[str]) -> dict:
    totals = {"upserted": 0, "stale_removed": 0}
    for doc in document_ids:
        mask = (df.document_id == doc).to_numpy()
        r = qdrant_store.upsert_document(client, doc, rows_of(df[mask]), mat[mask].tolist())
        totals = {k: totals[k] + r[k] for k in totals}
        qdrant_store.verify_document(client, doc, df.loc[mask, "chunk_id"].tolist())
    return totals


# %% Phase 4 helpers — read everything back from Qdrant
def stored_payloads(client) -> dict[str, dict]:
    out, offset = {}, None
    while True:
        pts, offset = client.scroll(qdrant_store.COLLECTION, limit=512, offset=offset, with_payload=True,
                                    with_vectors=False)
        out.update({str(p.id): p.payload for p in pts})
        if offset is None:
            return out


def revalidate(client, df: pd.DataFrame, mat: np.ndarray) -> dict:
    name = qdrant_store.COLLECTION
    assert client.count(name, exact=True).count == len(df)
    want = {qdrant_store.point_id(d, c): p for d, c, p in zip(df.document_id, df.chunk_id, rows_of(df))}
    got = stored_payloads(client)
    assert set(got) == set(want), f"{len(set(want) - set(got))} missing, {len(set(got) - set(want))} extra points"
    diff = [k for k in want if got[k] != want[k]]
    assert not diff, f"{len(diff)} payloads differ from their chunk rows, e.g. {got[diff[0]]['chunk_id']}"

    sample = list(range(0, len(df), SAMPLE_EVERY))
    ids = [qdrant_store.point_id(df.document_id.iat[i], df.chunk_id.iat[i]) for i in sample]
    pts = {str(p.id): p for p in client.retrieve(name, ids=ids, with_vectors=True)}
    unit = embeddings.normalize(mat[sample])  # Qdrant stores cosine vectors normalized
    for k, i in enumerate(sample):
        v = pts[ids[k]].vector
        assert np.allclose(np.asarray(v["dense"], dtype=np.float32), unit[k], atol=1e-5), df.chunk_id.iat[i]
        assert len(v["bm25"].indices) > 0, f"{df.chunk_id.iat[i]}: no bm25 vector"

    info = client.get_collection(name)
    assert info.config.params.vectors["dense"].size == DIM
    assert set(info.payload_schema) == set(qdrant_store.PAYLOAD_INDEXES), set(info.payload_schema)
    by_level = {int(k): int(v) for k, v in df.sensitivity_level.value_counts().sort_index().items()}
    return {"points": len(got), "documents": int(df.document_id.nunique()), "by_level": by_level,
            "sampled_vectors": len(sample)}


def main() -> None:
    common.load_env(ROOT)
    df, mat = inputs()
    print(f"✅ Phase 1 validation passed: {len(df)} chunks / {df.document_id.nunique()} documents; the vectors are the "
          f"manifest's ({DIM} dims, file hash and every text hash match, same order)")

    client = qdrant_store.connect()
    created = qdrant_store.ensure_collection(client, DIM)
    pilot = load_documents(client, df, mat, [PILOT_DOCUMENT])
    n_pilot = int((df.document_id == PILOT_DOCUMENT).sum())
    assert n_pilot == REVIEWED["pilot_points"] and pilot["upserted"] == n_pilot
    print(f"✅ Phase 2 validation passed: pilot {PILOT_DOCUMENT} — {n_pilot} points, exact ids "
          f"(collection {'created' if created else 'existing, spec checked'}; stale removed {pilot['stale_removed']})")

    docs = sorted(df.document_id.unique())
    full = load_documents(client, df, mat, docs)
    print(f"✅ Phase 3 validation passed: {len(docs)} documents loaded, {full['upserted']} points upserted, "
          f"stale removed {full['stale_removed']}")

    actual = revalidate(client, df, mat)
    assert {k: actual[k] for k in ("points", "documents", "by_level")} == \
           {k: REVIEWED[k] for k in ("points", "documents", "by_level")}, actual
    print(f"✅ Phase 4 validation passed: {actual['points']} points read back = the chunk files (every payload equal, "
          f"exact ids per document); {actual['sampled_vectors']} sampled vectors equal the file, bm25 present; "
          f"payload indexes and dense config as specified")

    again = load_documents(client, df, mat, docs)
    assert again["stale_removed"] == 0 and client.count(qdrant_store.COLLECTION, exact=True).count == len(df)
    assert revalidate(client, df, mat) == actual
    print(f"✅ Phase 5 validation passed: a second full load removed 0 points and changed nothing "
          f"({again['upserted']} upserts of identical points)")


if __name__ == "__main__":
    main()
