"""API embedding client shared by the bake-off (Phase 2), the corpus embedding (Phase 4) and PDF ingestion (Phase 8).

- Providers: Jina, Voyage, Gemini, each with its asymmetric retrieval parameters ('document' vs 'query').
- Budgets: our own requests-per-minute / tokens-per-minute ceiling per provider (sliding 60 s window); the free-tier
  limits are not published in response headers, so the values are conservative and tuned only by evidence.
  Gemini counts every text of a batch against its limits and stops at ~1,000 texts / day (bake-off, 2026-10-02).
- Retries: 429 / 5xx / transport errors, waiting `Retry-After` (header) or Gemini's `retryDelay` (body), else
  exponential backoff; a wait over 15 minutes means a daily quota: stop at once (the cache makes a re-run resume).
- Cache: one `part_NNNNN.npz` per batch (`ids`, `shas`, `vecs`), keyed by id + SHA-256 of the exact text; a text that
  changed is re-embedded, an unchanged one never is (0 API calls for a complete cache).
- Keys are sent in headers only and redacted from every error text.
"""
import hashlib
import os
import re
import time
from collections import deque
from pathlib import Path

import httpx
import numpy as np

from pipelines.lib.common import redact

MAX_WAIT_S = 900

# rpm / tpm: our ceiling per minute; batch_items / batch_tokens: per request (tokens estimated, see est_tokens).
PROVIDERS = {
    "jina": {"model": "jina-embeddings-v5-text-small", "key": "JINA_API_KEY",
             "rpm": 60, "tpm": 90_000, "batch_items": 64, "batch_tokens": 20_000},
    "voyage": {"model": "voyage-4", "key": "VOYAGE_API_KEY",
               "rpm": 3, "tpm": 9_000, "batch_items": 128, "batch_tokens": 8_500},
    "gemini": {"model": "gemini-embedding-2", "key": "GEMINI_API_KEY",
               "rpm": 4, "tpm": 20_000, "batch_items": 25, "batch_tokens": 5_000},
}


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def est_tokens(text: str) -> int:
    return len(text) // 3 + 1  # conservative (English ~4 chars / token; Arabic denser)


def request(provider: str, texts: list[str], kind: str) -> tuple[str, dict, dict]:
    """(url, headers, body) for one batch; kind is 'document' or 'query'."""
    assert kind in ("document", "query"), kind
    p = PROVIDERS[provider]
    key = os.environ[p["key"]]
    if provider == "jina":
        task = "retrieval.passage" if kind == "document" else "retrieval.query"
        return ("https://api.jina.ai/v1/embeddings", {"Authorization": f"Bearer {key}"},
                {"model": p["model"], "task": task, "input": texts})
    if provider == "voyage":
        return ("https://api.voyageai.com/v1/embeddings", {"Authorization": f"Bearer {key}"},
                {"model": p["model"], "input": texts, "input_type": kind})
    task = "RETRIEVAL_DOCUMENT" if kind == "document" else "RETRIEVAL_QUERY"
    return (f"https://generativelanguage.googleapis.com/v1beta/models/{p['model']}:batchEmbedContents",
            {"x-goog-api-key": key},  # header, never ?key= in the URL
            {"requests": [{"model": f"models/{p['model']}", "content": {"parts": [{"text": t}]}, "taskType": task}
                          for t in texts]})


def parse(provider: str, js: dict) -> tuple[list[list[float]], int | None]:
    """(vectors in input order, tokens counted by the provider or None)."""
    if provider == "gemini":
        return [e["values"] for e in js["embeddings"]], js.get("usageMetadata", {}).get("totalTokenCount")
    data = sorted(js["data"], key=lambda d: d["index"])
    return [d["embedding"] for d in data], js.get("usage", {}).get("total_tokens")


class RateLimited(RuntimeError):
    """A request would have to wait longer than the caller allows (query time: fail fast, never sleep a minute)."""


class Budget:
    """Sliding 60-second window of requests and tokens. With `max_wait` (seconds), a wait that would exceed it raises
    RateLimited instead of sleeping (query time); without it, it sleeps as long as needed (batch embedding)."""

    def __init__(self, rpm: int, tpm: int, max_wait: float | None = None):
        self.rpm, self.tpm, self.max_wait, self.log = rpm, tpm, max_wait, deque()  # (time, tokens)

    def wait(self, tokens: int) -> float:
        waited = 0.0
        while True:
            now = time.monotonic()
            while self.log and now - self.log[0][0] >= 60:
                self.log.popleft()
            if len(self.log) < self.rpm and sum(t for _, t in self.log) + tokens <= self.tpm:
                return waited
            pause = max(0.5, 60 - (now - self.log[0][0]) + 0.1)
            if self.max_wait is not None and waited + pause > self.max_wait:
                raise RateLimited(f"rate budget full: next slot in {pause:.0f} s (limit {self.rpm} requests / "
                                  f"{self.tpm} tokens per minute)")
            time.sleep(pause)
            waited += pause

    def record(self, tokens: int) -> None:
        self.log.append((time.monotonic(), tokens))


class Embedder:
    """One provider's client: budget, retries, counters (calls, tokens, retries, latencies)."""

    def __init__(self, provider: str, client: httpx.Client, limits: dict | None = None,
                 max_wait_s: float = MAX_WAIT_S):
        """`limits` overrides the batch rpm / tpm (query time uses its own); `max_wait_s` caps any single wait
        (budget or provider back-off): above it, RateLimited is raised instead of sleeping."""
        p = {**PROVIDERS[provider], **(limits or {})}
        self.provider, self.client, self.max_wait_s = provider, client, max_wait_s
        self.budget = Budget(p["rpm"], p["tpm"], max_wait=None if max_wait_s >= MAX_WAIT_S else max_wait_s)
        self.calls = self.tokens = self.retries = 0
        self.latencies: list[float] = []

    def embed(self, texts: list[str], kind: str) -> list[list[float]]:
        url, headers, body = request(self.provider, texts, kind)
        est = sum(est_tokens(t) for t in texts)
        for attempt in range(8):
            self.budget.wait(est)
            t0 = time.perf_counter()
            try:
                r = self.client.post(url, headers=headers, json=body)
            except httpx.TransportError as e:
                self.budget.record(est)
                self._backoff(attempt, None, type(e).__name__)
                continue
            ms = (time.perf_counter() - t0) * 1000
            if r.status_code == 429 or r.status_code >= 500:
                self.budget.record(est)
                m = re.search(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"', r.text)  # Gemini: the wait is in the body
                wait = r.headers.get("retry-after") or (m.group(1) if m else None)
                self._backoff(attempt, wait, f"HTTP {r.status_code}: {' '.join(r.text.split())[:300]}")
                continue
            if r.status_code != 200:
                raise RuntimeError(redact(f"{self.provider} HTTP {r.status_code}: {r.text[:400]}"))
            vecs, used = parse(self.provider, r.json())
            assert len(vecs) == len(texts), f"{self.provider}: {len(vecs)} vectors for {len(texts)} texts"
            self.budget.record(used or est)
            self.calls += 1
            self.tokens += used or est
            self.latencies.append(ms)
            return vecs
        raise RuntimeError(f"{self.provider}: gave up after 8 attempts (rate limit or quota; a re-run resumes)")

    def _backoff(self, attempt: int, retry_after: str | None, why: str) -> None:
        self.retries += 1
        pause = (float(retry_after) if retry_after and retry_after.replace(".", "").isdigit()
                 else min(120, 5 * 2 ** attempt))
        if pause > MAX_WAIT_S:  # a daily quota, not a per-minute limit
            raise RuntimeError(f"{self.provider}: quota exhausted, provider asks to wait {pause / 3600:.1f} h; "
                               f"re-run after that (resumes from the cache)")
        if pause > self.max_wait_s:  # query time: the user is waiting
            raise RateLimited(f"{self.provider}: provider asks to wait {pause:.0f} s ({redact(why)[:120]})")
        print(f"   {self.provider}: retry {attempt + 1} in {pause:.0f}s ({redact(why)})", flush=True)
        time.sleep(pause)


def load_cache(folder: Path) -> dict[str, tuple[str, np.ndarray]]:
    """id -> (text SHA-256, vector) from every part file of a cache folder (later parts win)."""
    out = {}
    for f in sorted(folder.glob("part_*.npz")):
        z = np.load(f, allow_pickle=False)
        for i, h, v in zip(z["ids"], z["shas"], z["vecs"]):
            out[str(i)] = (str(h), v)
    return out


def embed_with_cache(emb: Embedder, folder: Path, ids: list[str], texts: list[str], kind: str) -> np.ndarray:
    """Vectors for `texts` in order; only ids whose cached text hash differs (or is missing) go to the API."""
    folder.mkdir(parents=True, exist_ok=True)
    cache = load_cache(folder)
    todo = [(i, t) for i, t in zip(ids, texts) if cache.get(i, ("",))[0] != sha256_text(t)]
    p = PROVIDERS[emb.provider]
    batch, btok, part = [], 0, len(list(folder.glob("part_*.npz")))
    if todo:
        print(f"   {emb.provider}/{folder.name}: {len(todo)} of {len(ids)} to embed", flush=True)

    def flush():
        nonlocal batch, btok, part
        vecs = np.asarray(emb.embed([t for _, t in batch], kind), dtype=np.float32)
        np.savez(folder / f"part_{part:05d}.npz", ids=np.array([i for i, _ in batch]),
                 shas=np.array([sha256_text(t) for _, t in batch]), vecs=vecs)
        for (i, t), v in zip(batch, vecs):
            cache[i] = (sha256_text(t), v)
        part += 1
        batch, btok = [], 0

    for i, t in todo:
        tok = est_tokens(t)
        if batch and (len(batch) >= p["batch_items"] or btok + tok > p["batch_tokens"]):
            flush()
        batch.append((i, t))
        btok += tok
    if batch:
        flush()
    assert all(cache[i][0] == sha256_text(t) for i, t in zip(ids, texts)), "cache hash mismatch"
    return np.stack([cache[i][1] for i in ids])


def normalize(m: np.ndarray) -> np.ndarray:
    """Unit-length rows (cosine = dot product); refuses non-finite or zero vectors."""
    n = np.linalg.norm(m, axis=1, keepdims=True)
    assert np.isfinite(m).all() and (n > 0).all(), "non-finite or zero vector"
    return m / n
