"""Search index benchmark: exact search vs IVF (and Qdrant's own exact / HNSW) on our vectors (input to ADR-038).

Plan:    docs/archive/2026-10-08_RAG_Embeddings_Qdrant_plan.md (owner, 2026-10-08: "compare exact with IVF; if there is no
         difference, stay on exact").
Run:     uv run python tools/run.py pipelines/scripts/retrieval/Search_index_benchmark.py  (ports-qdrant up)

Reads:   Data/embeddings/gemini-embedding-2/dense_composed.parquet + manifest; the frozen golden set; the cached Gemini
         query vectors (Data/embeddings/bakeoff/gemini/query; no API call); Qdrant `nilegate_docs` (read only)
Writes:  nothing
Re-run:  safe; deterministic (KMeans random_state 42)

Why IVF is built here: Qdrant offers exact search and HNSW only, no IVF. IVF ("inverted file") clusters the vectors
(k-means, `nlist` lists) and searches only the `nprobe` lists nearest to the query: fast on large corpora, but a
relevant chunk sitting in an unprobed list is missed. It is implemented with scikit-learn (already a dependency) on
the same normalized vectors, so the comparison isolates the index method.

Measures (64 golden queries): agreement with exact search (overlap@10: share of the exact top-10 found), hit@10 on
the expected chunks, and the search compute time per query (in process, so transport does not hide the difference).
"""
# %% Setup
import hashlib
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())
sys.path.insert(0, str(ROOT))
from pipelines.lib import common, embeddings, qdrant_store  # noqa: E402

EMB_DIR = ROOT / "Data" / "embeddings" / "gemini-embedding-2"
GOLDEN = ROOT / "Data" / "processed" / "rag" / "eval" / "golden_set.jsonl"
GOLDEN_SHA256 = "a187b4966f250211d7498b87d34d56b518af41d851cf8570716fce01f2dbb8bc"
QUERY_CACHE = ROOT / "Data" / "embeddings" / "bakeoff" / "gemini" / "query"
K = 10
NLIST = 46            # ≈ sqrt(2,163), the usual starting point
NPROBES = (1, 2, 4, 8, 16)
REPEAT = 20           # timing repetitions per query


# %% Phase 1 — Inputs
def inputs():
    manifest = json.loads((EMB_DIR / "manifest.json").read_text(encoding="utf-8"))
    m = manifest["variants"][manifest["active_variant"]]
    dense_path = EMB_DIR / m["dense_file"]
    assert hashlib.sha256(dense_path.read_bytes()).hexdigest() == m["dense_sha256"]
    dense = pd.read_parquet(dense_path)
    D = embeddings.normalize(np.stack(dense.vector.to_numpy()).astype(np.float32))
    assert hashlib.sha256(GOLDEN.read_bytes()).hexdigest() == GOLDEN_SHA256
    qs = [r for r in map(json.loads, GOLDEN.read_text(encoding="utf-8").splitlines()) if r["kind"] == "query"]
    cache = embeddings.load_cache(QUERY_CACHE)
    assert all(cache[q["qid"]][0] == embeddings.sha256_text(q["question"]) for q in qs), "query cache is stale"
    Q = embeddings.normalize(np.stack([cache[q["qid"]][1] for q in qs]).astype(np.float32))
    return dense.chunk_id.tolist(), D, qs, Q


# %% Phase 2 — Exact and IVF in process
def timed(fn, q) -> tuple[list[int], float]:
    best = float("inf")
    for _ in range(REPEAT):
        t = time.perf_counter()
        out = fn(q)
        best = min(best, time.perf_counter() - t)
    return out, best * 1e6  # microseconds, best of REPEAT (noise-robust)


def exact_fn(D):
    def search(q):
        s = D @ q
        top = np.argpartition(-s, K)[:K]
        return top[np.argsort(-s[top])].tolist()
    return search


def ivf_fn(D, centroids, lists, nprobe):
    def search(q):
        probe = np.argsort(-(centroids @ q))[:nprobe]
        cand = np.concatenate([lists[c] for c in probe])
        s = D[cand] @ q
        k = min(K, len(cand))
        top = np.argpartition(-s, k - 1)[:k]
        return cand[top[np.argsort(-s[top])]].tolist()
    return search


def evaluate(fn, Q, qs, ids, exact_tops=None) -> dict:
    pos = {c: i for i, c in enumerate(ids)}
    tops, us = zip(*(timed(fn, q) for q in Q))
    hit = np.mean([any(pos[c] in t for c in q["expected_chunk_ids"]) for t, q in zip(tops, qs)])
    out = {"hit@10": round(float(hit), 4), "p50_us": round(statistics.median(us), 1),
           "p95_us": round(float(np.percentile(us, 95)), 1), "tops": list(tops)}
    if exact_tops is not None:
        out["overlap@10"] = round(float(np.mean([len(set(a) & set(b)) / K for a, b in zip(tops, exact_tops)])), 4)
    return out


# %% Phase 3 — Qdrant exact vs HNSW (same queries, REST: includes transport)
def qdrant_check(Q, ids) -> dict:
    from qdrant_client import models
    common.load_env(ROOT)
    c = qdrant_store.connect()
    out = {}
    for name, params in [("qdrant_exact", models.SearchParams(exact=True)),
                         ("qdrant_hnsw_ef64", models.SearchParams(hnsw_ef=64))]:
        lat, tops = [], []
        for q in Q:
            t = time.perf_counter()
            r = c.query_points(qdrant_store.COLLECTION, query=q.tolist(), using="dense", limit=K,
                               search_params=params, with_payload=["chunk_id"])
            lat.append((time.perf_counter() - t) * 1000)
            tops.append([p.payload["chunk_id"] for p in r.points])
        out[name] = {"p50_ms": round(statistics.median(lat), 1), "tops": tops}
    return out


def main() -> None:
    ids, D, qs, Q = inputs()
    print(f"Phase 1: {D.shape[0]} vectors × {D.shape[1]} dims, {len(qs)} golden queries (cached vectors)")

    ex = evaluate(exact_fn(D), Q, qs, ids)
    km = KMeans(n_clusters=NLIST, random_state=42, n_init=4).fit(D)
    centroids = embeddings.normalize(km.cluster_centers_.astype(np.float32))
    lists = [np.where(km.labels_ == c)[0] for c in range(NLIST)]
    sizes = sorted(len(x) for x in lists)
    rows = {"exact": ex}
    for npb in NPROBES:
        rows[f"ivf nprobe={npb}"] = evaluate(ivf_fn(D, centroids, lists, npb), Q, qs, ids, ex["tops"])
    print(f"✅ Phase 2 validation passed: IVF nlist {NLIST} (list sizes {sizes[0]}-{sizes[-1]}, median "
          f"{sizes[len(sizes) // 2]}); exact search is the ground truth")
    for name, r in rows.items():
        ov = f"overlap@10 {r['overlap@10']:.3f} | " if "overlap@10" in r else "ground truth      | "
        print(f"✅ {name:16s}: {ov}hit@10 {r['hit@10']:.3f} | compute p50 {r['p50_us']:7.1f} µs  p95 {r['p95_us']:7.1f} µs")

    qd = qdrant_check(Q, ids)
    exact_ids = [[ids[i] for i in t] for t in ex["tops"]]
    for name, r in qd.items():
        ov = np.mean([len(set(a) & set(b)) / K for a, b in zip(r["tops"], exact_ids)])
        print(f"✅ {name:16s}: overlap@10 with in-process exact {ov:.3f} | REST p50 {r['p50_ms']} ms")
    assert np.mean([len(set(a) & set(b)) / K for a, b in zip(qd["qdrant_exact"]["tops"], exact_ids)]) == 1.0, \
        "Qdrant exact search must equal the in-process exact search"


if __name__ == "__main__":
    main()
