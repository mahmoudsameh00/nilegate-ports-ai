"""Embed the whole corpus with the chosen model, files first (RAG plan Phase 4; ADR-037 model, ADR-041 embedded unit).

Plan:    docs/plans/RAG_Embeddings_Qdrant_plan.md, Phase 4.
Run:     uv run python tools/run.py pipelines/scripts/retrieval/Embeddings.py  (from the project root)

Reads:   Data/processed/rag/chunks/*.parquet (the contract incl. ADR-041); .env (GEMINI_API_KEY, only if vectors are
         missing); optionally the bake-off cache Notebooks/_scratch/bakeoff/gemini/ (seed, read-only)
Writes:  Data/embeddings/gemini-embedding-2/dense_<variant>.parquet (chunk_id, text_sha256, vector) — git-ignored;
         Data/embeddings/gemini-embedding-2/manifest.json — committed (model, task, dimension, variant, the hash of
         every embedded text and of the vector file); Data/embeddings/gemini-embedding-2/cache_<variant>/ — git-ignored
Re-run:  safe and resumable: every vector is cached by chunk id + SHA-256 of the exact embedded text; a complete cache
         means 0 API calls and byte-identical outputs. A changed chunk text is re-embedded, nothing else.

Why files first: the free tier allows roughly a thousand texts a day (ADR-037), so every vector is computed once, kept,
and the Qdrant loader (Phase 5) never calls the API. The manifest lets any clone prove that its local vectors are the
ones described here.

Phases
1. Inputs: the corpus under the contract, the embedded variant (D5), the texts and their hashes.
2. Vectors: seed the working cache from the bake-off cache (same model, same task, same text hash: valid vectors,
   no API call), then embed only what is missing (pipelines/lib/embeddings.py: budgets, retries, resumable).
3. Files + validation: dense parquet and manifest, reloaded and re-validated (count, dimension, finite, unit norm
   after normalization, hashes equal the chunk texts); a reviewed snapshot.
"""
# %% Setup
import hashlib
import json
import sys
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())
sys.path.insert(0, str(ROOT))
from pipelines.lib import chunks as chunk_contract  # noqa: E402
from pipelines.lib import common, embeddings  # noqa: E402

PROVIDER = "gemini"                                  # ADR-037
MODEL = embeddings.PROVIDERS[PROVIDER]["model"]
DIM = 3072
VARIANT = "composed"  # D5: "composed" = compose(title, text) (default, ADR-041) or "body" = text only; set by D5
OUT_DIR = ROOT / "Data" / "embeddings" / MODEL
CACHE = OUT_DIR / f"cache_{VARIANT}"
DENSE = OUT_DIR / f"dense_{VARIANT}.parquet"
MANIFEST = OUT_DIR / "manifest.json"
BAKEOFF_CACHE = ROOT / "Notebooks" / "_scratch" / "bakeoff" / PROVIDER / {"composed": "doc", "body": "doc_body"}[VARIANT]
REVIEWED = {"vectors": 2163, "dim": DIM, "files": 29}  # reviewed 2026-10-05


# %% Phase 1 — Inputs
def inputs() -> tuple[pd.DataFrame, list[str]]:
    df = chunk_contract.load(ROOT / "Data" / "processed" / "rag" / "chunks")
    texts = ([chunk_contract.compose(t, x) for t, x in zip(df.title, df.text)] if VARIANT == "composed"
             else df.text.tolist())
    return df, texts


# %% Phase 2 — Vectors (seed from the bake-off cache, then embed only what is missing)
def seed_from_bakeoff(ids: list[str], texts: list[str]) -> int:
    """Copy bake-off vectors whose text hash equals ours into the working cache (same model and task parameters)."""
    if not BAKEOFF_CACHE.is_dir():
        return 0
    CACHE.mkdir(parents=True, exist_ok=True)
    have = embeddings.load_cache(CACHE)
    src = embeddings.load_cache(BAKEOFF_CACHE)
    rows = [(i, h, src[i][1]) for i, t in zip(ids, texts)
            if (h := embeddings.sha256_text(t)) and src.get(i, ("",))[0] == h and have.get(i, ("",))[0] != h]
    if rows:
        part = len(list(CACHE.glob("part_*.npz")))
        np.savez(CACHE / f"part_{part:05d}.npz", ids=np.array([r[0] for r in rows]),
                 shas=np.array([r[1] for r in rows]), vecs=np.stack([r[2] for r in rows]).astype(np.float32))
    return len(rows)


def vectors(ids: list[str], texts: list[str]) -> tuple[np.ndarray, dict]:
    seeded = seed_from_bakeoff(ids, texts)
    common.load_env(ROOT)
    with httpx.Client(timeout=120.0) as client:
        emb = embeddings.Embedder(PROVIDER, client)
        mat = embeddings.embed_with_cache(emb, CACHE, ids, texts, "document")
    return mat, {"seeded_from_bakeoff": seeded, "api_calls": emb.calls, "api_tokens": emb.tokens,
                 "retries": emb.retries}


# %% Phase 3 — Files + validation
def write_files(df: pd.DataFrame, texts: list[str], mat: np.ndarray) -> dict:
    hashes = [embeddings.sha256_text(t) for t in texts]
    out = pd.DataFrame({"chunk_id": df.chunk_id.astype(str), "text_sha256": hashes,
                        "vector": [v.astype(np.float32) for v in mat]})
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out.to_parquet(DENSE, index=False)
    corpus_hash = hashlib.sha256("\n".join(f"{c}\t{h}" for c, h in zip(out.chunk_id, hashes)).encode()).hexdigest()
    manifest = {
        "provider": PROVIDER, "model": MODEL, "dimension": DIM, "distance": "cosine",
        "task": {"document": "RETRIEVAL_DOCUMENT", "query": "RETRIEVAL_QUERY"},
        "variant": VARIANT, "embedded_unit": ("compose(title, text) = title + newline + text (ADR-041)"
                                              if VARIANT == "composed" else "text only"),
        "decisions": ["ADR-037", "ADR-041"], "vectors": len(out), "files": int(df.filename.nunique()),
        "corpus_sha256": corpus_hash,  # over (chunk_id, text_sha256) in chunk order
        "dense_file": DENSE.name, "dense_sha256": hashlib.sha256(DENSE.read_bytes()).hexdigest(),
    }
    old = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
    variants = {**old.get("variants", {}), VARIANT: manifest}
    MANIFEST.write_text(json.dumps({"active_variant": VARIANT, "variants": variants}, indent=1) + "\n",
                        encoding="utf-8", newline="\n")
    return manifest


def validate(df: pd.DataFrame, texts: list[str], manifest: dict) -> dict:
    back = pd.read_parquet(DENSE)
    assert back.chunk_id.tolist() == df.chunk_id.tolist(), "chunk order differs from the corpus"
    assert back.text_sha256.tolist() == [embeddings.sha256_text(t) for t in texts], "a vector is stale"
    mat = np.stack(back.vector.to_numpy())
    assert mat.dtype == np.float32 and mat.shape == (len(df), DIM)
    unit = embeddings.normalize(mat)  # refuses non-finite or zero vectors
    assert np.allclose(np.linalg.norm(unit, axis=1), 1, atol=1e-5)
    assert hashlib.sha256(DENSE.read_bytes()).hexdigest() == manifest["dense_sha256"]
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert m["active_variant"] == VARIANT and m["variants"][VARIANT] == manifest
    return {"vectors": len(back), "dim": mat.shape[1], "files": manifest["files"]}


def main() -> None:
    df, texts = inputs()
    print(f"Phase 1: {len(df)} chunks, variant {VARIANT}, model {MODEL}")
    mat, stats = vectors(df.chunk_id.tolist(), texts)
    print(f"✅ Phase 2 validation passed: {mat.shape[0]} × {mat.shape[1]} vectors | seeded from the bake-off "
          f"{stats['seeded_from_bakeoff']} | API calls this run {stats['api_calls']} ({stats['api_tokens']} tokens, "
          f"{stats['retries']} retries)")
    manifest = write_files(df, texts, mat)
    actual = validate(df, texts, manifest)
    assert actual == REVIEWED, actual
    print(f"✅ Phase 3 validation passed: {DENSE.relative_to(ROOT)} reloaded = {actual['vectors']} × {actual['dim']}, "
          f"unit-normalizable, every hash equals its chunk text; manifest {MANIFEST.relative_to(ROOT)} "
          f"(corpus sha256 {manifest['corpus_sha256'][:12]}…)")


if __name__ == "__main__":
    main()
