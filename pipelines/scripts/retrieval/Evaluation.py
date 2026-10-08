"""Phase 7: evaluate `search_documents` configurations and choose the defaults by the ADR-040 rule (→ ADR-038).

Plan:    docs/plans/RAG_Embeddings_Qdrant_plan.md, Phase 7; rule fixed in ADR-040 before this script ran.
Run:     uv run python tools/run.py pipelines/scripts/retrieval/Evaluation.py  (ports-qdrant and ports-postgres up)

Reads:   the frozen golden set + golden facts; Qdrant `nilegate_docs`; PostgreSQL (read-only, RBAC); the query cache
         (every golden question is cached: 0 embedding calls); .env (JINA_API_KEY for the reranker)
Writes:  Data/processed/rag/eval/results_<date>.json (every configuration's metrics + the decision)
Re-run:  safe; the reranker is called once per (question, candidate set) within a run

Configurations (all through the real tool, as the CEO so the level-3 questions count; RBAC is checked separately):
  dense                   baseline: exact dense search, top 10 (context = the first 8)
  hybrid                  dense + BM25 prefetch, RRF
  dense+rerank            24 dense candidates reranked by Jina
  hybrid+rerank           24 hybrid candidates reranked
  <best>+cap2             the best of the above + at most 2 chunks per document
  <best>+dedupe           the best + near-duplicate removal (containment >= 0.8)
  <best>+cap2+dedupe      both shaping rules

Rule (ADR-040): a configuration replaces the current choice only if the balanced score rises by >= 0.03 AND no primary
(fact recall@10, nDCG@10, sufficiency@8) falls by more than 0.02 in either language AND RBAC leakage is 0; a tie keeps
the simpler configuration. Stage A picks the retrieval mode among the first four (each vs the baseline); stage B
tests the shaping rules on top of the stage-A choice (each vs that choice). Latency is reported, not deciding.
"""
# %% Setup
import datetime as dt
import hashlib
import json
import statistics
import sys
from pathlib import Path

import pandas as pd

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())
sys.path.insert(0, str(ROOT))
from pipelines.lib import chunks as chunk_contract  # noqa: E402
from pipelines.lib import common, evaluation, retrieval  # noqa: E402

common.load_env(ROOT)
EVAL = ROOT / "Data" / "processed" / "rag" / "eval"
GOLDEN_SHA256 = "a187b4966f250211d7498b87d34d56b518af41d851cf8570716fce01f2dbb8bc"
FACTS_SHA256 = "09b5f5b6892133806a9c11a006490c31c63782e560cb9a038977b1d2f5998d25"
CEO = 1
GAIN, MAX_DROP = 0.03, 0.02           # ADR-040
OUT = EVAL / f"results_{dt.date.today().isoformat()}.json"
MODES = {"dense": dict(hybrid=False, rerank=False), "hybrid": dict(hybrid=True, rerank=False),
         "dense+rerank": dict(hybrid=False, rerank=True), "hybrid+rerank": dict(hybrid=True, rerank=True)}
SHAPING = {"cap2": dict(max_per_document=2), "dedupe": dict(dedupe=True),
           "cap2+dedupe": dict(max_per_document=2, dedupe=True)}


# %% Phase 1 — Inputs
def load(name: str, sha: str) -> list[dict]:
    p = EVAL / name
    assert hashlib.sha256(p.read_bytes()).hexdigest() == sha, f"{name} is not the frozen file"
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()]


golden = load("golden_set.jsonl", GOLDEN_SHA256)
queries = [r for r in golden if r["kind"] == "query"]
rbac_cases = [r for r in golden if r["kind"] == "rbac"]
facts = {r["qid"]: r["facts"] for r in load("golden_facts.jsonl", FACTS_SHA256)}
df = chunk_contract.load(ROOT / "Data" / "processed" / "rag" / "chunks")
units = [chunk_contract.compose(t, x) for t, x in zip(df.title, df.text)]
pos = {c: i for i, c in enumerate(df.chunk_id)}
judges = evaluation.judges(queries, facts, df.chunk_id.tolist(), units)
R = retrieval.Retriever(rerank_max_wait=300.0)  # an evaluation may wait for the reranker budget
qmeta = pd.DataFrame(queries)[["qid", "lang", "sources", "type", "identifier"]]


# %% Phase 2 — Run a configuration through the real tool
def run(cfg: dict) -> dict:
    per, lat, emb_calls = [], [], 0
    for q in queries:
        res = R.search(q["question"], CEO, k=evaluation.K_RETRIEVAL, **cfg)
        emb_calls += res.api_calls["embedding"]
        lat.append(res.timing_ms["total_ms"])
        ranking = [pos[r["chunk_id"]] for r in res.results]
        per.append({"qid": q["qid"], **judges[q["qid"]].score(ranking)})
    assert emb_calls == 0, "every golden question must come from the query cache"
    d = pd.DataFrame(per).merge(qmeta, on="qid")
    d["source"] = d.sources.str[0]
    s = evaluation.aggregate(d)
    s["per_language"] = {lang: {dim: s[lang][m] for dim, m in evaluation.PRIMARY.items()} for lang in ("en", "ar")}
    s["latency_ms"] = {"p50": round(statistics.median(lat), 1), "p95": round(sorted(lat)[int(0.95 * len(lat)) - 1], 1)}
    s["per_query"] = [{k: v for k, v in r.items() if k in ("qid", "hit@10", "sufficiency@8", "missing_facts@8")}
                      for r in per]
    return s


def leakage(cfg: dict) -> int:
    """RBAC leakage under this configuration: level-3 chunks reaching anyone but the CEO (golden RBAC cases)."""
    n = 0
    for case in rbac_cases:
        res = R.search(next(q["question"] for q in queries if q["qid"] == case["qid"]), case["employee_id"], k=10,
                       **cfg)
        n += sum(r["sensitivity_level"] == 3 for r in res.results) if res.user.role != "ceo" else 0
    return n


def beats(cand: dict, base: dict) -> tuple[bool, str]:
    gain = cand["balanced"] - base["balanced"]
    drops = {f"{lang}.{dim}": round(base["per_language"][lang][dim] - cand["per_language"][lang][dim], 4)
             for lang in ("en", "ar") for dim in evaluation.PRIMARY}
    worst = max(drops, key=drops.get)
    ok = gain >= GAIN and drops[worst] <= MAX_DROP and cand["leakage"] == 0
    why = f"balanced {gain:+.3f} (need >= +{GAIN}), worst drop {worst} {drops[worst]:+.3f} (max {MAX_DROP})"
    return ok, why


def line(name: str, s: dict) -> str:
    d, pl = s["dimensions"], s["per_language"]
    return (f"{name:22s} | balanced {s['balanced']:.3f} | retrieval {d['retrieval']:.3f} ranking {d['ranking']:.3f} "
            f"context {d['context']:.3f} | AR suff@8 {pl['ar']['context']:.3f} | prec@8 {s['all']['precision@8']:.3f} "
            f"redund@8 {s['all']['redundancy@8']:.3f} | p50 {s['latency_ms']['p50']:.0f} ms | leak {s['leakage']}")


# %% Phase 3 — Stage A: retrieval mode
results, decisions = {}, []
for name, cfg in MODES.items():
    results[name] = run(cfg) | {"config": cfg}
    results[name]["leakage"] = leakage(cfg)
choice = "dense"
for name in ("hybrid", "dense+rerank", "hybrid+rerank"):
    ok, why = beats(results[name], results["dense"])
    decisions.append({"stage": "A", "candidate": name, "vs": "dense", "accepted": ok, "why": why})
    if ok and results[name]["balanced"] > results[choice]["balanced"]:
        choice = name
for name in MODES:
    print("✅ " + line(name, results[name]))
print(f"✅ Stage A (retrieval mode) by the ADR-040 rule: {choice}  —  " +
      "; ".join(f"{d['candidate']}: {'accepted' if d['accepted'] else 'rejected'} ({d['why']})" for d in decisions))

# %% Phase 4 — Stage B: context shaping on top of the stage-A choice
final = choice
for sname, scfg in SHAPING.items():
    name = f"{choice}+{sname}"
    cfg = {**results[choice]["config"], **scfg}
    results[name] = run(cfg) | {"config": cfg}
    results[name]["leakage"] = leakage(cfg)
    ok, why = beats(results[name], results[choice])
    decisions.append({"stage": "B", "candidate": name, "vs": choice, "accepted": ok, "why": why})
    if ok and results[name]["balanced"] > results[final]["balanced"]:
        final = name
    print("✅ " + line(name, results[name]))
print(f"✅ Stage B (context shaping) on {choice}: final = {final}  —  " +
      "; ".join(f"{d['candidate']}: {'accepted' if d['accepted'] else 'rejected'} ({d['why']})"
                for d in decisions if d["stage"] == "B"))

# %% Phase 5 — Save, reload
assert all(r["leakage"] == 0 for r in results.values()), "RBAC leakage in some configuration"
report = {"date": dt.date.today().isoformat(), "rule": "ADR-040", "golden_sha256": GOLDEN_SHA256,
          "facts_sha256": FACTS_SHA256, "model": "gemini-embedding-2 (composed unit)", "user": "CEO (employee 1)",
          "decisions": decisions, "stage_a_choice": choice, "final": final,
          "final_config": results[final]["config"], "rerank_calls_this_run": R.rerank_calls,
          "configurations": results}
OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
back = json.loads(OUT.read_text(encoding="utf-8"))
assert back["final"] == final and set(back["configurations"]) == set(results)
print(f"✅ Phase 5: {OUT.relative_to(ROOT)} written and reloaded; final configuration {final} "
      f"{results[final]['config']}; reranker calls this run {R.rerank_calls}; RBAC leakage 0 in all "
      f"{len(results)} configurations")
