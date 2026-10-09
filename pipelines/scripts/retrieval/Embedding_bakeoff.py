"""Embedding bake-off (RAG plan Phase 2): which API model retrieves the right chunks, in English AND Egyptian Arabic.

Plan:    docs/archive/2026-10-08_RAG_Embeddings_Qdrant_plan.md, Phase 2 (decisions D1, D5); output → ADR-037.
Run:     uv run python tools/run.py pipelines/scripts/retrieval/Embedding_bakeoff.py --timeout 14400  (project root)

Reads:   Data/processed/rag/chunks/*.parquet; Data/processed/rag/eval/golden_set.jsonl (frozen); .env (API keys)
Writes:  Data/embeddings/bakeoff/<run>/part_*.npz (vector cache, git-ignored; in Notebooks/_scratch/ until the plan
         closed, moved because later scripts read it); Data/processed/rag/eval/bakeoff_results.json (metrics; kept)
Re-run:  safe and resumable: every batch is cached by chunk id + text SHA-256, so a re-run (or a run after a quota or
         rate-limit stop) only embeds what is missing; a complete cache means 0 API calls.

Method (fixed before any model ran, owner answer D1)
- Candidates: Jina jina-embeddings-v5-text-small, Voyage voyage-4, Gemini gemini-embedding-2, each with its asymmetric
  retrieval parameters (chunks as documents / passages, questions as queries). Default dimensions (1024 / 1024 / 3072).
- Ranking: cosine similarity in NumPy over all 2,163 chunks (no filter: the CEO view; RBAC is Phase 6).
- Reported besides (ADR-040, decided after D1, so they never change the choice): retrieval (fact recall@10),
  ranking (nDCG@10), context (sufficiency@8) and the balanced score, from Data/processed/rag/eval/golden_facts.jsonl.
- D1 metric: hit@k, i.e. hit-based recall (a query is found if ANY of its expected ids is in the top k; the expected ids are
  equivalent chunks, see Golden_set.py), MRR of the first expected id; overall, per language, per source, per type,
  identifier questions.
- Selection rule (D1): primary = mean(recall@10 English, recall@10 Arabic); a gap < 5 points is a tie; a tie goes to
  Jina (one key for embeddings and reranker). MRR, per-source recall, latency, failures are reported, not deciding.
- Embedded text (D5, ADR-041): stage 1 compares the models on the delivered unit `compose(title, text)` = title + a
  newline + text, the same for every chunk since the title / text normalization; stage 2 embeds the body `text` alone
  with the winner only and compares it with stage 1 (deviation from "all candidates": halves the quota spent; the
  model choice does not depend on the variant because the variant only changes the chunk side, the same way for every
  model). For the 1,683 chunks whose heading moved to `title`, the composed unit equals their former text exactly,
  so their cached vectors stay valid (the cache is keyed by text SHA-256).

Rate limits: the free-tier limits are UNCERTAIN (no provider returns quota headers, Phase 0), so each provider has a
conservative requests-per-minute / tokens-per-minute budget (sliding 60 s window, token counts estimated at 3 chars
per token, replaced by the provider's own count when it returns one); 429 / 5xx are retried with `Retry-After` or
exponential backoff. Keys are sent in headers only and redacted from any error text.
"""

# %% Setup
# The client, budgets, retries and cache live in the shared library (pipelines/lib/embeddings.py, ADR-039); this
# script keeps only the evaluation: scoring, the selection rule and the two stages.
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
from pipelines.lib import common, embeddings, evaluation  # noqa: E402

CHUNKS = ROOT / "Data" / "processed" / "rag" / "chunks"
GOLDEN = ROOT / "Data" / "processed" / "rag" / "eval" / "golden_set.jsonl"
GOLDEN_SHA256 = "a187b4966f250211d7498b87d34d56b518af41d851cf8570716fce01f2dbb8bc"  # frozen in Phase 1
FACTS = ROOT / "Data" / "processed" / "rag" / "eval" / "golden_facts.jsonl"
FACTS_SHA256 = "09b5f5b6892133806a9c11a006490c31c63782e560cb9a038977b1d2f5998d25"  # frozen 2026-10-02 (ADR-040)
CACHE = ROOT / "Data" / "embeddings" / "bakeoff"
RESULTS = ROOT / "Data" / "processed" / "rag" / "eval" / "bakeoff_results.json"
PROVIDERS = embeddings.PROVIDERS
TIE_POINTS = 0.05


# %% Metrics (pipelines/lib/evaluation.py, ADR-040): the D1 primary decides; the three dimensions are reported
def score(doc: np.ndarray, qry: np.ndarray, queries: list[dict], judges: dict) -> list[dict]:
    sims = embeddings.normalize(qry) @ embeddings.normalize(doc).T
    order = np.argsort(-sims, axis=1, kind="stable")
    return [{"qid": q["qid"], **judges[q["qid"]].score(row)} for q, row in zip(queries, order)]


def summarize(per_query: list[dict], queries: list[dict]) -> dict:
    df = pd.DataFrame(per_query).merge(pd.DataFrame(queries)[["qid", "lang", "sources", "type", "identifier"]], on="qid")
    df["source"] = df.sources.str[0]
    s = evaluation.aggregate(df)
    s["primary"] = s["primary_d1"]  # D1: mean of hit@10 (= the former recall@10) en / ar
    return s


def choose(primary: dict[str, float]) -> tuple[str, str]:
    best = max(primary, key=primary.get)
    if best != "jina" and "jina" in primary and primary[best] - primary["jina"] < TIE_POINTS:
        return "jina", f"tie with {best} ({primary[best] - primary['jina']:+.3f} < {TIE_POINTS}) → Jina (D1)"
    return best, f"highest primary metric ({primary[best]:.3f})"


# %% Run
def main() -> None:
    common.load_env(ROOT)
    assert hashlib.sha256(GOLDEN.read_bytes()).hexdigest() == GOLDEN_SHA256, "golden set is not the frozen one"
    golden = [json.loads(line) for line in GOLDEN.read_text(encoding="utf-8").splitlines()]
    queries = [r for r in golden if r["kind"] == "query"]
    chunks = chunk_contract.load(CHUNKS)  # the 16-column contract incl. ADR-041 (no heading left in `text`)
    assert len(chunks) == 2163 and chunks.chunk_id.is_unique and len(queries) == 64
    ids, qids = chunks.chunk_id.tolist(), [q["qid"] for q in queries]
    assert hashlib.sha256(FACTS.read_bytes()).hexdigest() == FACTS_SHA256, "golden facts are not the frozen ones"
    facts = {r["qid"]: r["facts"] for r in map(json.loads, FACTS.read_text(encoding="utf-8").splitlines())}
    units = [chunk_contract.compose(t, x) for t, x in zip(chunks.title, chunks.text)]
    judges = evaluation.judges(queries, facts, ids, units)
    variants = {"composed": units, "body": chunks.text.tolist()}

    results = {"golden_sha256": GOLDEN_SHA256, "method": "D1 primary = mean hit@10 en/ar (decides); retrieval / ranking / context dimensions (ADR-040, reported)",
               "models": {}, "stage1": {}, "stage2": {}}
    with httpx.Client(timeout=120.0) as client:
        # Stage 1: every model on `text`
        embedders, qvecs = {}, {}
        for prov, p in PROVIDERS.items():
            emb = embedders[prov] = embeddings.Embedder(prov, client)
            dvec = embeddings.embed_with_cache(emb, CACHE / prov / "doc", ids, variants["composed"], "document")
            qvecs[prov] = embeddings.embed_with_cache(emb, CACHE / prov / "query", qids, [q["question"] for q in queries], "query")
            assert dvec.shape[0] == 2163 and qvecs[prov].shape == (64, dvec.shape[1])
            per_q = score(dvec, qvecs[prov], queries, judges)
            results["stage1"][prov] = {"summary": summarize(per_q, queries), "per_query": per_q}
            results["models"][prov] = {"model": p["model"], "dim": int(dvec.shape[1])}
            print(f"✅ Stage 1 {prov}: dim {dvec.shape[1]} | primary {results['stage1'][prov]['summary']['primary']:.3f}",
                  flush=True)

        primary = {k: v["summary"]["primary"] for k, v in results["stage1"].items()}
        winner, why = choose(primary)
        results["choice"] = {"model": winner, "rule": why, "primary": primary}

        # Stage 2: the winner on the body `text` alone
        dvec = embeddings.embed_with_cache(embedders[winner], CACHE / winner / "doc_body", ids, variants["body"], "document")
        per_q = score(dvec, qvecs[winner], queries, judges)
        results["stage2"] = {"model": winner, "summary": summarize(per_q, queries), "per_query": per_q}

    for prov, emb in embedders.items():
        results["models"][prov].update({
            "api_calls_this_run": emb.calls, "tokens_this_run": emb.tokens, "retries_this_run": emb.retries,
            "median_batch_latency_ms": round(float(np.median(emb.latencies)), 1) if emb.latencies else None})

    RESULTS.write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    reloaded = json.loads(RESULTS.read_text(encoding="utf-8"))
    assert reloaded["choice"] == results["choice"] and set(reloaded["stage1"]) == set(PROVIDERS)

    s1, s2 = results["stage1"], results["stage2"]["summary"]
    for prov in PROVIDERS:
        s = s1[prov]["summary"]
        d = s["dimensions"]
        print(f"✅ {prov}: D1 primary {s['primary']:.3f} (hit@10 en {s['en']['hit@10']:.3f} ar {s['ar']['hit@10']:.3f})"
              f" | retrieval {d['retrieval']:.3f} ranking {d['ranking']:.3f} context {d['context']:.3f}"
              f" | balanced {s['balanced']:.3f}")
    print(f"✅ Choice (D1): {winner} — {why}")
    print(f"✅ Stage 2 ({winner}, body text only): D1 {s2['primary']:.3f} vs composed {s1[winner]['summary']['primary']:.3f}"
          f" | balanced {s2['balanced']:.3f} vs {s1[winner]['summary']['balanced']:.3f}")

if __name__ == "__main__":
    main()
