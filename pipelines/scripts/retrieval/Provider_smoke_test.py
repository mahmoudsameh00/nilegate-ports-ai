"""Provider smoke test (RAG plan Phase 0): one tiny call per embedding provider + one rerank call.

Plan:    docs/plans/RAG_Embeddings_Qdrant_plan.md, Phase 0 (all three embedding providers must pass before Phase 1).
Run:     uv run python tools/run.py pipelines/scripts/retrieval/Provider_smoke_test.py  (from the project root)

Reads:   .env (JINA_API_KEY, VOYAGE_API_KEY, GEMINI_API_KEY); the network (4 small HTTPS calls)
Writes:  nothing (stdout only; tools/run.py keeps the log in Notebooks/_scratch/)
Re-run:  safe; each run spends a few hundred tokens of free quota. Not part of `tools/run.py all` (network, keys).

Why: before writing the golden set or embedding 2,163 chunks, prove that each key works, the model ids are right,
and see the vector dimension, latency, quota headers and a first hint of cross-lingual behaviour (cosine between an
English sentence and its Egyptian Arabic twin). Settles the plan's UNCERTAIN points (free amounts, limits, Arabic).

Security: keys are sent in headers only (never in a URL), never printed; any error text is passed through `redact()`
so a key echoed back by a provider or an exception cannot reach the log.

Checks
1. Jina embeddings   jina-embeddings-v5-text-small  (task retrieval.query)
2. Voyage embeddings voyage-4                       (input_type query)
3. Gemini embeddings gemini-embedding-2             (taskType RETRIEVAL_QUERY)
4. Jina rerank       jina-reranker-v3.5             (Arabic query, 3 English passages)
"""
import math
import os
import re
import time
from pathlib import Path

import httpx
import numpy as np

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())
KEYS = ["JINA_API_KEY", "VOYAGE_API_KEY", "GEMINI_API_KEY"]
TIMEOUT = 30.0

# One English question and its Egyptian Arabic twin (same meaning, colloquial phrasing).
EN = "How much does a loaded container ship pay to transit the Suez Canal?"
AR = "سفينة الحاويات المحملة بتدفع كام علشان تعدي قناة السويس؟"
PASSAGES = [  # for the rerank call; index 1 is the relevant one
    "The Logistics Performance Index ranks countries on customs, infrastructure and timeliness.",
    "Suez Canal transit dues for container ships are charged per Suez Canal Net Ton, in SDR, by progressive bands.",
    "The master must report a marine casualty to the flag State without delay.",
]
REVIEWED_DIMS = {"jina_embed": 1024, "voyage_embed": 1024, "gemini_embed": 3072}  # reviewed 2026-10-01, first run
QUOTA_RE = re.compile(r"ratelimit|rate-limit|quota|remaining|retry-after|x-usage", re.I)


def load_env() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def redact(text: str) -> str:
    """Replace every key value (and anything that looks like a key= / key: parameter) with ***."""
    for k in KEYS:
        v = os.environ.get(k, "")
        if len(v) >= 8:
            text = text.replace(v, "***")
    return re.sub(r"(?i)(key[=:]\s*)[A-Za-z0-9_\-\.]{8,}", r"\1***", text)


def quota_headers(r: httpx.Response) -> dict[str, str]:
    return {k: v for k, v in r.headers.items() if QUOTA_RE.search(k)}


def post(client: httpx.Client, url: str, headers: dict, body: dict) -> tuple[httpx.Response, float]:
    t0 = time.perf_counter()
    r = client.post(url, headers=headers, json=body)
    return r, (time.perf_counter() - t0) * 1000


def cosine(a: list[float], b: list[float]) -> float:
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))


def check_vectors(vecs: list[list[float]]) -> int:
    """Two vectors, same non-zero dimension, finite values; returns the dimension."""
    assert len(vecs) == 2, f"expected 2 vectors, got {len(vecs)}"
    dims = {len(v) for v in vecs}
    assert len(dims) == 1 and next(iter(dims)) > 0, f"dimensions {dims}"
    assert all(math.isfinite(x) for v in vecs for x in v), "non-finite values"
    return dims.pop()


# --- one function per check: returns the parsed result; raises on any failure --------------------------------------

def jina_embed(client: httpx.Client) -> dict:
    r, ms = post(client, "https://api.jina.ai/v1/embeddings",
                 {"Authorization": f"Bearer {os.environ['JINA_API_KEY']}"},
                 {"model": "jina-embeddings-v5-text-small", "task": "retrieval.query", "input": [EN, AR]})
    r.raise_for_status()
    js = r.json()
    vecs = [d["embedding"] for d in sorted(js["data"], key=lambda d: d["index"])]
    return {"ms": ms, "dim": check_vectors(vecs), "en_ar_cos": cosine(*vecs),
            "tokens": js.get("usage", {}).get("total_tokens"), "quota": quota_headers(r)}


def voyage_embed(client: httpx.Client) -> dict:
    r, ms = post(client, "https://api.voyageai.com/v1/embeddings",
                 {"Authorization": f"Bearer {os.environ['VOYAGE_API_KEY']}"},
                 {"model": "voyage-4", "input": [EN, AR], "input_type": "query"})
    r.raise_for_status()
    js = r.json()
    vecs = [d["embedding"] for d in sorted(js["data"], key=lambda d: d["index"])]
    return {"ms": ms, "dim": check_vectors(vecs), "en_ar_cos": cosine(*vecs),
            "tokens": js.get("usage", {}).get("total_tokens"), "quota": quota_headers(r)}


def gemini_embed(client: httpx.Client) -> dict:
    model = "gemini-embedding-2"
    r, ms = post(client,
                 f"https://generativelanguage.googleapis.com/v1beta/models/{model}:batchEmbedContents",
                 {"x-goog-api-key": os.environ["GEMINI_API_KEY"]},  # header, never ?key= in the URL
                 {"requests": [{"model": f"models/{model}", "content": {"parts": [{"text": t}]},
                                "taskType": "RETRIEVAL_QUERY"} for t in (EN, AR)]})
    r.raise_for_status()
    js = r.json()
    vecs = [e["values"] for e in js["embeddings"]]
    return {"ms": ms, "dim": check_vectors(vecs), "en_ar_cos": cosine(*vecs),
            "tokens": js.get("usageMetadata", {}).get("totalTokenCount"), "quota": quota_headers(r)}


def jina_rerank(client: httpx.Client) -> dict:
    r, ms = post(client, "https://api.jina.ai/v1/rerank",
                 {"Authorization": f"Bearer {os.environ['JINA_API_KEY']}"},
                 {"model": "jina-reranker-v3.5", "query": AR, "documents": PASSAGES, "top_n": len(PASSAGES)})
    r.raise_for_status()
    js = r.json()
    res = js["results"]
    assert len(res) == len(PASSAGES), f"expected {len(PASSAGES)} results, got {len(res)}"
    return {"ms": ms, "top_index": res[0]["index"], "scores": [round(x["relevance_score"], 3) for x in res],
            "tokens": js.get("usage", {}).get("total_tokens"), "quota": quota_headers(r)}


CHECKS = [  # (name, key it needs, function)
    ("Jina embed (jina-embeddings-v5-text-small)", "JINA_API_KEY", jina_embed),
    ("Voyage embed (voyage-4)", "VOYAGE_API_KEY", voyage_embed),
    ("Gemini embed (gemini-embedding-2)", "GEMINI_API_KEY", gemini_embed),
    ("Jina rerank (jina-reranker-v3.5)", "JINA_API_KEY", jina_rerank),
]


def run_check(client: httpx.Client, name: str, key: str, fn) -> dict:
    if not os.environ.get(key):
        return {"name": name, "ok": False, "error": f"{key} missing or empty in .env"}
    try:
        out = fn(client)
        want = REVIEWED_DIMS.get(fn.__name__)
        assert want is None or out["dim"] == want, f"dimension {out['dim']} != reviewed {want}"
        return {"name": name, "ok": True, **out}
    except httpx.HTTPStatusError as e:
        body = e.response.text[:300].replace("\n", " ")
        return {"name": name, "ok": False, "status": e.response.status_code,
                "error": redact(f"HTTP {e.response.status_code}: {body}"), "quota": quota_headers(e.response)}
    except Exception as e:  # network error, unexpected JSON shape, failed vector check
        return {"name": name, "ok": False, "error": redact(f"{type(e).__name__}: {e}"[:300])}


def report(res: dict) -> None:
    # tools/run.py shows only ✅ lines and the traceback tail, so each pass is one ✅ line (quota headers included)
    # and each failure is carried by the final assertion message.
    quota = f" | quota {res['quota']}" if res.get("quota") else " | no quota headers"
    if res["ok"]:
        extra = (f"dim {res['dim']} | EN↔AR cosine {res['en_ar_cos']:.3f}" if "dim" in res
                 else f"top passage {res['top_index']} (expected 1) | scores {res['scores']}")
        print(f"✅ {res['name']}: 200 | {res['ms']:.0f} ms | {extra} | tokens {res['tokens']}{quota}")
    else:
        print(f"❌ {res['name']}: {res['error']}{quota}")


def main() -> None:
    load_env()
    with httpx.Client(timeout=TIMEOUT) as client:
        results = [run_check(client, *c) for c in CHECKS]
    for res in results:
        report(res)

    failed = [f"{r['name']} -> {r['error']}" for r in results if not r["ok"]]
    assert not failed, f"{len(failed)} of {len(results)} checks failed:\n  " + "\n  ".join(failed)
    print("✅ Phase 0 validation passed (3 embedding providers + 1 reranker).")


if __name__ == "__main__":
    main()
