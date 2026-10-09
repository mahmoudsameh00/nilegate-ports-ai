"""Phase 6 validation of `search_documents` (pipelines/lib/retrieval.py): RBAC, metadata filters, cache, rate policy.

Plan:    docs/archive/2026-10-08_RAG_Embeddings_Qdrant_plan.md, Phase 6.
Run:     uv run python tools/run.py pipelines/scripts/retrieval/Retrieval.py  (ports-qdrant and ports-postgres up)

Reads:   Qdrant `nilegate_docs`; PostgreSQL (read-only user: employees, roles, departments); the frozen golden set; the
         Phase 4 vectors (for the exactness check); the bake-off query cache (seed: the golden questions cost no call)
Writes:  Data/embeddings/gemini-embedding-2/cache_queries/ (the query cache, git-ignored); nothing else
Re-run:  safe; the first run makes 1 Gemini query call (the cache test question) and 1 Jina rerank call, later
         runs only the rerank call

Phases
1. Seed + exactness: the golden questions' vectors seed the query cache; the tool's dense top-10 equals in-process
   exact search over the Phase 4 vectors for all 64 questions (the tool is the system the bake-off evaluated).
2. RBAC matrix (ADR-006): 11 users (CEO, a manager and an employee of every department) x the 4 level-3 questions
   (q35, q36 and their Arabic twins) x dense / hybrid: level-3 chunks reach the CEO only; the RBAC filter is inside
   every prefetch of the request; the 8 golden RBAC cases hold; an unknown employee is refused.
3. Metadata filters: unit_kind, year range, document_id, combinations with RBAC; an unknown key is refused.
4. Query cache and rate policy: a repeated question costs 0 calls; a full rate budget raises at once (no sleep).
5. Latency of the tool (cached query vectors): per step, dense and hybrid.
6. Reranker + context shaping smoke test: one call, at most 2 chunks per document.
"""
# %% Setup
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())
sys.path.insert(0, str(ROOT))
from pipelines.lib import common, embeddings, retrieval  # noqa: E402

common.load_env(ROOT)
GOLDEN = ROOT / "Data" / "processed" / "rag" / "eval" / "golden_set.jsonl"
BAKEOFF_QUERIES = ROOT / "Data" / "embeddings" / "bakeoff" / "gemini" / "query"
DENSE = ROOT / "Data" / "embeddings" / "gemini-embedding-2" / "dense_composed.parquet"
CEO = 1
USERS = [1, 2, 4, 6, 8, 10, 12, 13, 14, 15, 16]  # CEO; managers Ops / Customs / Finance / HR / IT; employees x 5
LEVEL3_QUERIES = ["q35", "q35_ar", "q36", "q36_ar"]
CACHE_TEST_QUESTION = "Which vessel types does the Suez Canal treat as special floating units?"

golden = [json.loads(line) for line in GOLDEN.read_text(encoding="utf-8").splitlines()]
queries = {q["qid"]: q for q in golden if q["kind"] == "query"}
rbac_cases = [r for r in golden if r["kind"] == "rbac"]


# %% Phase 1 — Seed the query cache; the tool equals exact search
def seed_query_cache() -> int:
    src = embeddings.load_cache(BAKEOFF_QUERIES)
    have = embeddings.load_cache(retrieval.QUERY_CACHE)
    rows = []
    for q in queries.values():
        h = embeddings.sha256_text(q["question"])
        if src.get(q["qid"], ("",))[0] == h and h not in have:
            rows.append((h, h, src[q["qid"]][1]))
    if rows:
        retrieval.QUERY_CACHE.mkdir(parents=True, exist_ok=True)
        part = len(list(retrieval.QUERY_CACHE.glob("part_*.npz")))
        np.savez(retrieval.QUERY_CACHE / f"part_{part:05d}.npz", ids=np.array([r[0] for r in rows]),
                 shas=np.array([r[1] for r in rows]), vecs=np.stack([r[2] for r in rows]).astype(np.float32))
    return len(rows)


seeded = seed_query_cache()
R = retrieval.Retriever()  # after seeding: the query cache is loaded into memory once, at start


def S(*a, **kw):
    """The retrieval layer under test, without the reranker (Phase 6 tests the reranker on its own)."""
    return R.search(*a, **{"rerank": False, **kw})

dense = pd.read_parquet(DENSE)
D = embeddings.normalize(np.stack(dense.vector.to_numpy()))
ids = dense.chunk_id.tolist()
mismatch, calls = [], 0
for q in queries.values():
    res = S(q["question"], CEO, k=10)
    calls += res.api_calls["embedding"]
    v = embeddings.normalize(np.asarray([R.query_vector(q["question"])]))[0]
    want = [ids[i] for i in np.argsort(-(D @ v), kind="stable")[:10]]
    if [r["chunk_id"] for r in res.results] != want:
        mismatch.append(q["qid"])
assert not mismatch and calls == 0, (mismatch, calls)
print(f"✅ Phase 1 validation passed: query cache seeded with {seeded} golden questions; for all {len(queries)} "
      f"questions the tool's dense top-10 equals in-process exact search; 0 embedding calls")


# %% Phase 2 — RBAC matrix
level3_hits, violations, request_checks = {}, [], 0
for uid in USERS:
    for qid in LEVEL3_QUERIES:
        for hybrid in (False, True):
            res = S(queries[qid]["question"], uid, k=8, hybrid=hybrid)
            u = res.user
            for p in res.request["prefetch"]:  # the RBAC filter is part of every prefetch's request
                rb = p["filter"]["must"][0]["should"]
                assert rb[0]["key"] == "sensitivity_level" and rb[0]["range"]["lte"] == u.ceiling
                assert rb[1]["must"][0]["match"]["value"] == u.department and rb[1]["must"][1]["range"]["lte"] == 2
                request_checks += 1
            lv3 = [r["chunk_id"] for r in res.results if r["sensitivity_level"] == 3]
            level3_hits[(uid, qid, hybrid)] = len(lv3)
            if lv3 and u.role != "ceo":
                violations.append((uid, qid, hybrid, lv3))
assert not violations, violations
assert all(level3_hits[(CEO, q, h)] >= 1 for q in LEVEL3_QUERIES for h in (False, True)), "the CEO must see level 3"
for case in rbac_cases:
    res = S(queries[case["qid"]]["question"], case["employee_id"], k=8)
    got = "visible" if {r["chunk_id"] for r in res.results} & set(case["level3_chunk_ids"]) else "hidden"
    assert got == case["expect"], (case["case"], got)
try:
    S("anything", 99999)
    raise AssertionError("an unknown employee must be refused")
except PermissionError:
    pass
non_ceo = sum(1 for (uid, _, _), n in level3_hits.items() if uid != CEO)
print(f"✅ Phase 2 validation passed: {len(USERS)} users × {len(LEVEL3_QUERIES)} level-3 questions × dense/hybrid = "
      f"{len(level3_hits)} searches: level-3 chunks reached the CEO in all {len(LEVEL3_QUERIES) * 2} of his, none of "
      f"the {non_ceo} others; RBAC filter found in all {request_checks} prefetches; 8 golden RBAC cases hold; unknown "
      f"employee refused")


# %% Phase 3 — Metadata filters
q_rec = queries["q11"]["question"]      # engine cut-off switch recommendation
r1 = S(q_rec, 12, k=8, filters={"unit_kind": "recommendation"})
assert r1.results and all(r["unit_kind"] == "recommendation" for r in r1.results)
r2 = S(q_rec, 12, k=8, filters={"year_from": 2024, "year_to": 2025})
assert r2.results and all(r["year"] is not None and 2024 <= r["year"] <= 2025 for r in r2.results)
r3 = S(queries["q14"]["question"], 12, k=8, filters={"document_id": "uscg_roi_michipicoten_7971638"})
assert r3.results and all(r["document_id"] == "uscg_roi_michipicoten_7971638" for r in r3.results)
r4 = S(queries["q35"]["question"], 13, k=8, filters={"document_type": "port_authority_annual_report"})
assert r4.results and all(r["sensitivity_level"] < 3 for r in r4.results), "filters never widen RBAC"
r5 = S(queries["q35"]["question"], CEO, k=8, filters={"department": "Finance", "unit_kind": ["table", "figure"]})
assert r5.results and all(r["department"] == "Finance" and r["unit_kind"] in ("table", "figure") for r in r5.results)
try:
    S(q_rec, 12, filters={"colour": "red"})
    raise AssertionError("an unknown filter key must be refused")
except ValueError:
    pass
print("✅ Phase 3 validation passed: unit_kind, year range, document_id, document_type + RBAC (a Finance employee "
      "still gets no level 3), department + unit_kind list — every result matches its filters; unknown key refused")


# %% Phase 4 — Query cache and rate policy
first = S(CACHE_TEST_QUESTION, 12, k=3)
second = S(CACHE_TEST_QUESTION, 12, k=3)
assert second.api_calls["embedding"] == 0 and [r["chunk_id"] for r in first.results] == \
       [r["chunk_id"] for r in second.results]
R2 = retrieval.Retriever()  # a "restart": the cache must come back from disk, in memory
assert R2.search(CACHE_TEST_QUESTION, 12, k=3, rerank=False).api_calls["embedding"] == 0, "the query cache must survive a restart"
key = embeddings.sha256_text(CACHE_TEST_QUESTION)
t = time.perf_counter()
for _ in range(10_000):
    R2.qcache.get(key)
lookup_us = (time.perf_counter() - t) / 10_000 * 1e6
assert lookup_us < 50, lookup_us
b = embeddings.Budget(rpm=1, tpm=10_000, max_wait=1.0)
b.record(10)
t = time.perf_counter()
try:
    b.wait(10)
    raise AssertionError("a full budget must raise")
except embeddings.RateLimited:
    pass
fail_fast_ms = (time.perf_counter() - t) * 1000
assert fail_fast_ms < 100, fail_fast_ms
print(f"✅ Phase 4 validation passed: repeated question = 0 embedding calls (first run {first.api_calls['embedding']}); "
      f"the cache survives a restart (0 calls) and a lookup takes {lookup_us:.2f} µs (in memory); a full rate budget "
      f"raised RateLimited in {fail_fast_ms:.1f} ms instead of sleeping")


# %% Phase 5 — Latency (cached query vectors)
def timings(hybrid: bool) -> dict:
    rows = [S(q["question"], CEO, k=8, hybrid=hybrid).timing_ms for q in queries.values()]
    return {k: round(statistics.median(r[k] for r in rows), 1) for k in rows[0]}


t_dense, t_hybrid = timings(False), timings(True)
print(f"✅ Phase 5 latency (median of 64, cached query vectors): dense {t_dense} | hybrid {t_hybrid}")


# %% Phase 6 — Reranker + context shaping smoke test
before = R.rerank_calls
r6 = R.search(queries["q22"]["question"], CEO, k=8, hybrid=True, rerank=True, max_per_document=2)
per_doc = pd.Series([r["document_id"] for r in r6.results]).value_counts()
assert R.rerank_calls == before + 1 and len(r6.results) == 8 and per_doc.max() <= 2
print(f"✅ Phase 6 validation passed: hybrid + rerank + max 2 per document returned {len(r6.results)} chunks from "
      f"{len(per_doc)} documents in {r6.timing_ms['total_ms']:.0f} ms (rerank {r6.timing_ms['rerank_ms']:.0f} ms)")
