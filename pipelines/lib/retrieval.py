"""`search_documents`: the document tool of docs/RETRIEVAL_FLOW.md (RAG plan Phase 6).

One call = the user's question + who asks (employee_id) + optional metadata filters -> the allowed chunks, best first,
with citations. Built from the decisions of this plan:

- Query embedding: Gemini `gemini-embedding-2`, RETRIEVAL_QUERY (ADR-037), through a **query cache** keyed by the
  SHA-256 of the question (a repeated question costs no API call) and a **query-time rate policy** (its own limits;
  a wait over QUERY_MAX_WAIT_S raises RateLimited at once: the user never waits a minute).
- RBAC (ADR-006): role ceiling and department read from PostgreSQL (read-only user) **at query time**; the filter
  `level <= ceiling OR (department = own AND level <= 2)` sits **inside every prefetch**, never as a post-filter.
  Results are re-checked against the same rule (defence in depth: a violation raises).
- Metadata filters (ADR-039 amendment): document_type, source, document_id, department, unit_kind, year_from,
  year_to; unknown keys raise. They are ANDed with RBAC in the same filter.
- Search: exact dense search (owner decision 2026-10-08: IVF / HNSW bring nothing at this size) and, with
  `hybrid=True`, a BM25 prefetch (server-side, composed unit) fused by RRF, in ONE Qdrant query.
- Defaults (ADR-038, Phase 7 by the ADR-040 rule): exact dense search, 24 candidates reranked by Jina, no hybrid, no
  context shaping. If the reranker's rate limit is reached at query time, the dense order is returned
  (`request["reranked"] = False`). `hybrid`, `max_per_document` and `dedupe` remain available, off by default.
"""
import hashlib
import re
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import numpy as np
import psycopg
from qdrant_client import models

from pipelines.lib import embeddings, qdrant_store
from pipelines.lib.chunks import compose
from pipelines.lib.common import project_root, redact

QUERY_LIMITS = {"rpm": 60, "tpm": 30_000}   # query time: Gemini's per-minute limits, not the batch budget
QUERY_MAX_WAIT_S = 5.0
QUERY_CACHE = project_root() / "Data" / "embeddings" / "gemini-embedding-2" / "cache_queries"  # git-ignored
RERANK_MODEL = "jina-reranker-v3.5"
# Jina publishes no limit headers; the evaluation hit 429 after a few back-to-back calls of ~8k tokens each.
RERANK_LIMITS = {"rpm": 60, "tpm": 60_000}
FILTER_KEYS = {"document_type", "source", "document_id", "department", "unit_kind", "year_from", "year_to"}


@dataclass
class User:
    employee_id: int
    role: str
    ceiling: int
    department: str


@dataclass
class SearchResult:
    results: list[dict]
    user: User
    request: dict                       # what was sent to Qdrant (filters per prefetch), for audit and tests
    timing_ms: dict = field(default_factory=dict)
    api_calls: dict = field(default_factory=dict)


def rbac_filter(user: User) -> models.Filter:
    """ADR-006: level <= ceiling OR (own department AND level <= 2); level 3 is never unlocked by department."""
    return models.Filter(should=[
        models.FieldCondition(key="sensitivity_level", range=models.Range(lte=user.ceiling)),
        models.Filter(must=[models.FieldCondition(key="department", match=models.MatchValue(value=user.department)),
                            models.FieldCondition(key="sensitivity_level", range=models.Range(lte=2))])])


def allowed(user: User, level: int, department: str) -> bool:
    return level <= user.ceiling or (department == user.department and level <= 2)


class QueryCache:
    """Question SHA-256 -> query vector. Held in memory (a lookup is a dict access, ~0.2 µs) and persisted on disk
    so a restart keeps it. Benchmark 2026-10-08: the former per-call file read took 1.7 ms with 2 files and 589 ms
    after 1,000 questions (slower than calling Gemini); Redis GET 0.57 ms. Part files are compacted into one when
    the cache is opened with more than COMPACT_AT of them."""
    COMPACT_AT = 50

    def __init__(self, folder: Path):
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=True)
        self.vectors = {k: v for k, (_, v) in embeddings.load_cache(folder).items()}
        parts = sorted(folder.glob("part_*.npz"))
        if len(parts) > self.COMPACT_AT:
            keys = sorted(self.vectors)
            tmp = folder / "compact.tmp.npz"
            np.savez(tmp, ids=np.array(keys), shas=np.array(keys), vecs=np.stack([self.vectors[k] for k in keys]))
            for p in parts:
                p.unlink()
            tmp.rename(folder / "part_00000.npz")

    def get(self, key: str):
        return self.vectors.get(key)

    def put(self, key: str, vec) -> None:
        self.vectors[key] = vec
        n = len(list(self.folder.glob("part_*.npz")))
        np.savez(self.folder / f"part_{n:05d}.npz", ids=np.array([key]), shas=np.array([key]),
                 vecs=np.asarray([vec], dtype=np.float32))


DEDUPE_CONTAINMENT = 0.8  # >= 80 % of the shorter body's 5-word shingles appear in the other body
DEDUPE_MIN_SHINGLES = 8   # very short bodies are never judged duplicates


def shingles(text: str, n: int = 5) -> set[str]:
    words = re.findall(r"[0-9a-z]+", text.lower())
    return {" ".join(words[i:i + n]) for i in range(max(1, len(words) - n + 1))}


def near_duplicate(a: set[str], b: set[str]) -> bool:
    """Context shaping: a body mostly contained in a higher-ranked one says nothing new. Containment, not Jaccard:
    a restated USCG recommendation sits inside a chunk that also holds the Commandant's action (Jaccard 0.51,
    containment 0.79-1.00); two writings of the same facts in different words (Conclusions vs Executive Summary,
    containment 0.05) are kept. Measured 2026-10-08: of 953 corpus pairs >= 0.8, 827 cross-document ones are USCG
    template boilerplate ("The record and the report ... have been reviewed"), whose second copy adds nothing."""
    if len(a) < DEDUPE_MIN_SHINGLES or len(b) < DEDUPE_MIN_SHINGLES:
        return False
    return len(a & b) / min(len(a), len(b)) >= DEDUPE_CONTAINMENT


def metadata_conditions(filters: dict | None) -> list:
    if not filters:
        return []
    unknown = set(filters) - FILTER_KEYS
    if unknown:
        raise ValueError(f"unknown filter keys {sorted(unknown)}; allowed: {sorted(FILTER_KEYS)}")
    out = []
    for key in ("document_type", "source", "document_id", "department", "unit_kind"):
        if key in filters:
            v = filters[key]
            vals = [v] if isinstance(v, str) else list(v)
            out.append(models.FieldCondition(key=key, match=models.MatchAny(any=vals)))
    if "year_from" in filters or "year_to" in filters:
        out.append(models.FieldCondition(key="year", range=models.Range(gte=filters.get("year_from"),
                                                                         lte=filters.get("year_to"))))
    return out


class Retriever:
    """Holds the connections (Qdrant, HTTP, PostgreSQL settings) so repeated searches do not reconnect."""

    def __init__(self, query_cache: Path = QUERY_CACHE, rerank_max_wait: float = QUERY_MAX_WAIT_S):
        self.qdrant = qdrant_store.connect()
        self.http = httpx.Client(timeout=30.0)
        self.embedder = embeddings.Embedder("gemini", self.http, limits=QUERY_LIMITS, max_wait_s=QUERY_MAX_WAIT_S)
        self.query_cache = query_cache
        self.qcache = QueryCache(query_cache)
        self.rerank_calls = 0
        self._rerank_memo: dict = {}
        # the reranker gets the same kind of budget; query time fails fast, an evaluation may allow longer waits
        self.rerank_max_wait = rerank_max_wait
        self.rerank_budget = embeddings.Budget(**RERANK_LIMITS, max_wait=rerank_max_wait)

    # --- who asks (read at query time: a role change applies to the next question) ---------------------------------
    def user(self, employee_id: int) -> User:
        e = os.environ
        with psycopg.connect(host=e["PGHOST"], port=e["PGPORT"], dbname=e["PGDATABASE"], user=e["PG_RO_USER"],
                             password=e["PG_RO_PASSWORD"], options="-c default_transaction_read_only=on",
                             connect_timeout=5) as conn:
            row = conn.execute(
                "SELECT r.role_name, r.allowed_sensitivity_level, d.department_name FROM employees e "
                "JOIN roles r USING (role_id) JOIN departments d USING (department_id) WHERE e.employee_id = %s",
                (employee_id,)).fetchone()
        if row is None:
            raise PermissionError(f"unknown employee {employee_id}: no access")
        return User(employee_id, row[0], int(row[1]), row[2])

    # --- the question as a vector (cache first) -----------------------------------------------------------------
    def query_vector(self, query: str) -> list[float]:
        key = hashlib.sha256(query.encode("utf-8")).hexdigest()
        vec = self.qcache.get(key)
        if vec is None:
            vec = np.asarray(self.embedder.embed([query], "query")[0], dtype=np.float32)
            self.qcache.put(key, vec)
        return vec.tolist()

    # --- optional reranker (memoized per question + candidate set: the same input is never sent twice) ------------
    def rerank(self, query: str, points: list) -> list:
        key = (query, tuple(str(p.id) for p in points))
        if key in self._rerank_memo:
            order = self._rerank_memo[key]
            return [points[i] for i in order]
        docs = [compose(p.payload["title"], p.payload["text"]) for p in points]
        est = embeddings.est_tokens(query) + sum(embeddings.est_tokens(d) for d in docs)
        waited = 0.0
        for attempt in range(6):
            waited += self.rerank_budget.wait(est)
            r = self.http.post("https://api.jina.ai/v1/rerank",
                               headers={"Authorization": f"Bearer {os.environ['JINA_API_KEY']}"},
                               json={"model": RERANK_MODEL, "query": query, "top_n": len(points), "documents": docs})
            if r.status_code == 429:  # Jina's limit is per minute and not published in headers
                self.rerank_budget.record(est)
                pause = min(60.0, 5.0 * 2 ** attempt)
                if waited + pause > self.rerank_max_wait:
                    raise embeddings.RateLimited("reranker rate limit reached")
                time.sleep(pause)
                waited += pause
                continue
            if r.status_code != 200:
                raise RuntimeError(redact(f"reranker HTTP {r.status_code}: {r.text[:300]}"))
            break
        else:
            raise embeddings.RateLimited("reranker rate limit: gave up after 6 attempts")
        self.rerank_budget.record(r.json().get("usage", {}).get("total_tokens") or est)
        self.rerank_calls += 1
        order = [x["index"] for x in r.json()["results"]]
        self._rerank_memo[key] = order
        return [points[i] for i in order]

    def search(self, query: str, employee_id: int, k: int = 8, filters: dict | None = None, hybrid: bool = False,
               rerank: bool = True, max_per_document: int | None = None, dedupe: bool = False,
               candidates: int = 24) -> SearchResult:
        """`max_per_document` and `dedupe` shape the context (see `near_duplicate`); both only drop candidates and
        let the next ones move up, so k chunks are still returned when the candidates allow it."""
        t0 = time.perf_counter()
        user = self.user(employee_id)
        flt = models.Filter(must=[rbac_filter(user), *metadata_conditions(filters)])
        t1 = time.perf_counter()
        calls_before = self.embedder.calls
        qvec = self.query_vector(query)
        t2 = time.perf_counter()

        exact = models.SearchParams(exact=True)
        limit = candidates if (rerank or max_per_document or dedupe or hybrid) else k
        if hybrid:
            prefetch = [models.Prefetch(query=qvec, using="dense", filter=flt, limit=candidates, params=exact),
                        models.Prefetch(query=models.Document(text=query, model=qdrant_store.BM25_MODEL),
                                        using="bm25", filter=flt, limit=candidates)]
            res = self.qdrant.query_points(qdrant_store.COLLECTION, prefetch=prefetch,
                                           query=models.FusionQuery(fusion=models.Fusion.RRF), limit=limit,
                                           with_payload=True)
            request = {"mode": "hybrid", "prefetch": [{"using": p.using, "filter": p.filter.model_dump()}
                                                      for p in prefetch]}
        else:
            res = self.qdrant.query_points(qdrant_store.COLLECTION, query=qvec, using="dense", query_filter=flt,
                                           search_params=exact, limit=limit, with_payload=True)
            request = {"mode": "dense", "prefetch": [{"using": "dense", "filter": flt.model_dump()}]}
        points = list(res.points)
        t3 = time.perf_counter()
        reranked = False
        if rerank and points:
            try:
                points, reranked = self.rerank(query, points), True
            except embeddings.RateLimited:  # graceful: the dense order is still a good answer (ADR-038)
                pass
        t4 = time.perf_counter()

        out, per_doc, kept_shingles = [], {}, []
        for p in points:
            doc = p.payload["document_id"]
            if max_per_document and per_doc.get(doc, 0) >= max_per_document:
                continue
            if dedupe:
                sh = shingles(p.payload["text"])
                if any(near_duplicate(sh, other) for other in kept_shingles):
                    continue
                kept_shingles.append(sh)
            per_doc[doc] = per_doc.get(doc, 0) + 1
            pl = p.payload
            if not allowed(user, pl["sensitivity_level"], pl["department"]):  # defence in depth
                raise PermissionError(f"RBAC violation: {pl['chunk_id']} returned to employee {employee_id}")
            out.append({"rank": len(out) + 1, "score": float(p.score), "chunk_id": pl["chunk_id"],
                        "document_id": doc, "title": pl["title"], "text": pl["text"],
                        "sensitivity_level": pl["sensitivity_level"], "department": pl["department"],
                        "unit_kind": pl["unit_kind"], "year": pl["year"], "source": pl["source"],
                        "citation": {"filename": pl["filename"], "page": pl["page"], "title": pl["title"]}})
            if len(out) == k:
                break
        timing = {"user_ms": (t1 - t0) * 1000, "embed_ms": (t2 - t1) * 1000, "qdrant_ms": (t3 - t2) * 1000,
                  "rerank_ms": (t4 - t3) * 1000, "total_ms": (time.perf_counter() - t0) * 1000}
        request["reranked"] = reranked  # False when rerank was off, or skipped because its rate limit was reached
        return SearchResult(out, user, request, {k_: round(v, 1) for k_, v in timing.items()},
                            {"embedding": self.embedder.calls - calls_before})


_default: Retriever | None = None


def search_documents(query: str, employee_id: int, **kwargs) -> SearchResult:
    """Module-level entry point for tools / agents (one shared Retriever per process)."""
    global _default
    if _default is None:
        _default = Retriever()
    return _default.search(query, employee_id, **kwargs)
