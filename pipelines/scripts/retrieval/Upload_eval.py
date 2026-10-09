"""Phase 8 measurements of the session lane (conversation uploads): the local model, its runtime settings, the score
floor, the corpus baseline with uploads present, isolation, and latency (design §d, §e: M1-M5).

Plan:    docs/archive/2026-10-08_RAG_Embeddings_Qdrant_plan.md, Phase 8 (owner answers Q1, Q2, Q4).
Run:     uv run python tools/run.py pipelines/scripts/retrieval/Upload_eval.py  (ports-qdrant and ports-postgres up;
         bge-m3 exported by tools/export_onnx.py under models/onnx/; the rejected candidates are optional)
Reads:   the upload fixtures and questions (Upload_fixtures.py); the frozen golden set and golden facts; the baseline
         Data/processed/rag/eval/results_2026-10-08.json; the reviewed upload_eval_2026-10-08.json (rows of candidates
         not exported here); Qdrant `nilegate_docs` (read only)
Writes:  Data/processed/rag/eval/uploads/upload_eval_<date>.json; the query cache may gain nothing (every golden
         question is cached); Jina: up to 64 rerank calls (M1 with the default reranker), memoized
Re-run:  safe; the golden questions make no Gemini call (asserted); the two isolation questions of Phase 6 cost one
         Gemini query call each on the first run only (query cache)

Rules fixed before any run (plan, owner answers 2026-10-08):
- Model (Q1): the owner's model `llama2-embedding-600m-8k` is kept if it reaches session-lane hit@3 >= 0.85 on the
  English and >= 0.75 on the Arabic upload questions; otherwise the best candidate that reaches both is used and the
  owner is told. int8 replaces fp32 only if it loses no more than 0.02 hit@3 in either language (and, since the plan's
  close, is at least 20 % faster: MIN_SPEEDUP).
- Floor (M2): the smallest score that keeps upload chunks out of >= 95 % of the 64 golden (corpus) questions,
  rounded up to 0.01; then M3 is re-measured with the floor applied. Changed by the owner after the first full run
  to >= 80 % (FLOOR_KEEP_OUT below); the chosen model must still meet the thresholds with its floor.
- Baseline (M1): with a session holding all four upload documents, the corpus results of the 64 golden questions are
  identical (ids and order) to the results without a session, and the ADR-040 balanced score equals the baseline
  file's (dense 0.812; dense + rerank recomputed and reported).

Phases
1. Inputs: the four clean upload documents validated through the real validator; questions; golden set.
2. M3 model choice: every available candidate x precision, ranking only (no floor).
3. M5 runtime settings of the chosen model: precision x threads x batch size; providers available.
4. M2 floor calibration and M3 with the floor.
5. M1 the corpus baseline through the real tool, with and without the session.
6. M4 isolation (owner, other employee, expiry, close; no write to Qdrant or Data/) and RBAC defence.
7. M5 end-to-end latency (upload of a document; session lane per question) and the report.
"""
# %% Setup
import datetime as dt
import hashlib
import json
import os
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
import pandas as pd

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())
sys.path.insert(0, str(ROOT))
from pipelines.lib import chunks, common, evaluation, local_embeddings, qdrant_store, retrieval  # noqa: E402
from pipelines.lib import session_store, uploads  # noqa: E402

common.load_env(ROOT)
EVAL = ROOT / "Data" / "processed" / "rag" / "eval"
UP = EVAL / "uploads"
GOLDEN_SHA256 = "a187b4966f250211d7498b87d34d56b518af41d851cf8570716fce01f2dbb8bc"
FACTS_SHA256 = "09b5f5b6892133806a9c11a006490c31c63782e560cb9a038977b1d2f5998d25"
OWNER_MODEL = "llama2-embedding-600m-8k"
CANDIDATES = [OWNER_MODEL, "multilingual-e5-base", "bge-m3"]
HIT3_MIN = {"en": 0.85, "ar": 0.75}
INT8_MAX_LOSS = 0.02
MIN_SPEEDUP = 0.20  # a smaller precision must also be >= 20 % faster than fp32: a laptop's timings vary by +-20 %
PRECISIONS = ("fp32", "int8", "int4")
# Reviewed outcome of Phase 2 (2026-10-08): the owner's model and e5-base miss the Arabic threshold; bge-m3 (measured
# once the project moved to D:) meets both thresholds.
REVIEWED_CHOICE = ("bge-m3", "fp32", True)
# Owner decision 2026-10-08 (after the first full run): 80 % keep-out instead of 95 % — the session list is separate
# and labelled, so an extra off-topic upload chunk costs little, a hidden relevant one costs the employee their own
# document (95 % gave bge-m3 floor 0.52 and Arabic hit@3 0.733 < 0.75).
FLOOR_KEEP_OUT = 0.80
CEO, EMP_OPS, MGR_CUS, MGR_HR, EMP_FIN = 1, 12, 4, 8, 13
CLEAN = {"clean_D1.pdf": EMP_OPS, "clean_D2.docx": MGR_CUS, "clean_D3.pdf": MGR_HR, "clean_D4.docx": EMP_OPS}


# %% Phase 1 — Inputs
def load_frozen(name: str, sha: str) -> list[dict]:
    p = EVAL / name
    assert hashlib.sha256(p.read_bytes()).hexdigest() == sha, f"{name} is not the frozen file"
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()]


golden = [q for q in load_frozen("golden_set.jsonl", GOLDEN_SHA256) if q["kind"] == "query"]
facts = {r["qid"]: r["facts"] for r in load_frozen("golden_facts.jsonl", FACTS_SHA256)}
questions = [json.loads(line) for line in (UP / "upload_questions.jsonl").read_text(encoding="utf-8").splitlines()]
baseline = json.loads((EVAL / "results_2026-10-08.json").read_text(encoding="utf-8"))["configurations"]

R = retrieval.Retriever(rerank_max_wait=300.0)
USERS = {u: R.user(u) for u in (CEO, EMP_OPS, MGR_CUS, MGR_HR, EMP_FIN)}
reports = {f: uploads.validate_upload((UP / "fixtures" / f).read_bytes(), f, USERS[u]) for f, u in CLEAN.items()}
assert all(r.accepted and not r.removed for r in reports.values())
rows = [r for rep in reports.values() for r in rep.chunks]
texts = [chunks.compose(r["title"], r["text"]) for r in rows]
units = [r["logical_unit"] for r in rows]
print(f"upload chunks {len(rows)} from {len(reports)} documents; questions {len(questions)} "
      f"({sum(q['lang'] == 'en' for q in questions)} en / {sum(q['lang'] == 'ar' for q in questions)} ar); "
      f"golden {len(golden)}")
assert len(rows) == 32 and len(questions) == 60 and len(golden) == 64
print("✅ Phase 1 validation passed.")


# %% Phase 2 — M3 model choice (ranking only)
def m3(P: np.ndarray, Q: np.ndarray, floor: float | None = None) -> dict:
    """hit@1 / hit@3 / MRR per language: the expected unit among the top chunks (a chunk under the floor is dropped)."""
    S = Q @ P.T
    per = {"en": [], "ar": []}
    for i, q in enumerate(questions):
        order = [j for j in np.argsort(-S[i]) if floor is None or S[i, j] >= floor]
        ranks = [k for k, j in enumerate(order) if units[j] == q["expected"]]
        r = ranks[0] + 1 if ranks else None
        per[q["lang"]].append(r)
    out = {}
    for lang, rs in per.items():
        out[lang] = {"hit@1": round(np.mean([r == 1 for r in rs]), 3),
                     "hit@3": round(np.mean([r is not None and r <= 3 for r in rs]), 3),
                     "mrr": round(np.mean([1 / r if r else 0 for r in rs]), 3)}
    return out


def passes(m: dict) -> bool:
    return all(m[lang]["hit@3"] >= HIT3_MIN[lang] for lang in HIT3_MIN)


# A candidate not exported here keeps its measured rows from the reviewed report, labelled "recorded": the two rejected
# models were deleted at the plan's close (owner, 2026-10-08: 6.4 GB); a re-run measures every model that is present.
RECORDED = UP / "upload_eval_2026-10-08.json"
available = [c for c in CANDIDATES if (local_embeddings.MODELS_DIR / c / "manifest.json").exists()]
assert session_store.LOCAL_MODEL in available, "the session-lane model must be exported first (tools/export_onnx.py)"
recorded = json.loads(RECORDED.read_text(encoding="utf-8"))["m3_choice_table"]
choice_table, vectors = {}, {}
for name in CANDIDATES:
    if name not in available:
        choice_table.update({f"{name}/{p}": {**recorded[f"{name}/{p}"], "recorded": RECORDED.name} for p in PRECISIONS})
        print(f"⚠️ {name} is not exported here: its rows are the recorded ones of {RECORDED.name}")
        continue
    for prec in PRECISIONS:
        emb = local_embeddings.LocalEmbedder(name, precision=prec)
        emb.embed(texts[:4], "passage")  # warm-up: ONNX Runtime allocates on the first runs (a cold fp32 run lost)
        runs = []
        for _ in range(2):
            t = time.perf_counter()
            P = emb.embed(texts, "passage")
            runs.append(time.perf_counter() - t)
        t0, t1 = 0.0, min(runs)
        t = time.perf_counter()
        Q = emb.embed([q["question"] for q in questions], "query")
        t2 = t1 + (time.perf_counter() - t)
        vectors[(name, prec)] = (P, Q, emb)
        m = m3(P, Q)
        choice_table[f"{name}/{prec}"] = {**m, "passes": passes(m), "passages_ms": round((t1 - t0) * 1000),
                                          "queries_ms_each": round((t2 - t1) * 1000 / len(questions), 1),
                                          "load_ms": round(emb.load_ms), "truncated": emb.truncated}
        print(f"{name:26s} {prec}: en {m['en']} | ar {m['ar']} | passes {passes(m)} | "
              f"{(t1 - t0) * 1000:.0f} ms for {len(texts)} chunks")


def pick_precision(name: str) -> str:
    """fp32 unless a smaller variant keeps hit@3 within INT8_MAX_LOSS of fp32 in both languages AND is at least
    MIN_SPEEDUP faster; then the fastest such variant (weight-only int8 / int4 save memory but are not faster on this
    CPU: MatMulNBits dequantizes the weights at run time). The margin (owner, 2026-10-08) keeps timing noise from
    deciding: a Phase 9 re-run picked int4 for being 33 ms (0.5 %) faster than fp32."""
    ref = choice_table[f"{name}/fp32"]
    ok = [p for p in PRECISIONS if p == "fp32" or (
          all(ref[lang]["hit@3"] - choice_table[f"{name}/{p}"][lang]["hit@3"] <= INT8_MAX_LOSS for lang in HIT3_MIN)
          and choice_table[f"{name}/{p}"]["passages_ms"] <= (1 - MIN_SPEEDUP) * ref["passages_ms"])]
    return min(ok, key=lambda p: choice_table[f"{name}/{p}"]["passages_ms"])


def mean_hit3(name: str, prec: str) -> float:
    return float(np.mean([choice_table[f"{name}/{prec}"][lang]["hit@3"] for lang in HIT3_MIN]))


owner_prec = pick_precision(OWNER_MODEL)
passing = [(n, pick_precision(n)) for n in CANDIDATES if choice_table[f"{n}/{pick_precision(n)}"]["passes"]]
if (OWNER_MODEL, owner_prec) in passing:
    MODEL, PREC, MEETS, why = OWNER_MODEL, owner_prec, True, "the owner's model meets the thresholds"
elif passing:
    MODEL, PREC = max(passing, key=lambda c: mean_hit3(*c))
    MEETS, why = True, f"the owner's model misses the thresholds; {MODEL} meets them"
else:  # nobody meets the rule: the best candidate is used PROVISIONALLY and the owner decides (never silent)
    MODEL, PREC = max(((n, pick_precision(n)) for n in CANDIDATES), key=lambda c: mean_hit3(*c))
    MEETS = False
    why = (f"NO candidate meets hit@3 >= {HIT3_MIN}: provisional choice {MODEL} (best mean hit@3); owner's model en "
           f"{choice_table[f'{OWNER_MODEL}/{owner_prec}']['en']['hit@3']} / ar "
           f"{choice_table[f'{OWNER_MODEL}/{owner_prec}']['ar']['hit@3']}")
print(f"choice: {MODEL} / {PREC} — {why}")
if not MEETS:
    print("⚠️ the session lane runs on a provisional model: Arabic questions over English uploads are below the "
          "threshold (owner decision pending)")
assert MODEL == session_store.LOCAL_MODEL, f"session_store.LOCAL_MODEL must be the measured choice {MODEL}"
assert PREC == local_embeddings.DEFAULTS["precision"], f"local_embeddings precision default must be {PREC}"
assert (MODEL, PREC, MEETS) == REVIEWED_CHOICE, f"reviewed choice differs: {(MODEL, PREC, MEETS)}"
print("✅ Phase 2 validation passed.")


# %% Phase 3 — M5 runtime settings of the chosen model
settings = []
cpu = os.cpu_count() or 2
for prec in (PREC,):
    for threads in sorted({1, 2, 4, cpu // 2, cpu}):
        for bs in (1, 8, 32):
            emb = local_embeddings.LocalEmbedder(MODEL, precision=prec, threads=threads, batch_size=bs)
            emb.embed(texts[:4], "passage")  # warm-up
            runs = []
            for _ in range(3):  # a laptop's timings vary by +-20 % (heat, background): the best of 3
                t0 = time.perf_counter()
                emb.embed(texts, "passage")
                runs.append(time.perf_counter() - t0)
            t0, t1 = 0.0, min(runs)
            lat = []
            for q in questions[:10]:
                t = time.perf_counter()
                emb.embed([q["question"]], "query")
                lat.append((time.perf_counter() - t) * 1000)
            settings.append({"precision": prec, "threads": threads, "batch_size": bs,
                             "passages_ms": round((t1 - t0) * 1000), "query_ms_p50": round(statistics.median(lat), 1)})
st = pd.DataFrame(settings)
best = st[st.precision == PREC].sort_values(["passages_ms", "query_ms_p50"]).iloc[0].to_dict()
print(st.sort_values("passages_ms").head(6).to_string(index=False))
print(f"best for {PREC}: {best}; providers available here: {ort.get_available_providers()}")
default = st[(st.threads == local_embeddings.DEFAULTS["threads"]) & (st.batch_size == local_embeddings.DEFAULTS[
    "batch_size"])].iloc[0]
print(f"defaults ({local_embeddings.DEFAULTS['threads']} threads, batch {local_embeddings.DEFAULTS['batch_size']}): "
      f"{default.passages_ms} ms, query p50 {default.query_ms_p50} ms")
# a laptop's load changes from run to run (an editor indexing, a browser): the defaults must stay within 30 % of the
# best setting of THIS run, a guard against a bad default, not a benchmark
assert default.passages_ms <= 1.3 * best["passages_ms"], "the default settings are not within 30 % of the best"
print("✅ Phase 3 validation passed.")


# %% Phase 4 — M2 floor calibration, then M3 with the floor
P, Q, emb = vectors[(MODEL, PREC)]
G = emb.embed([q["question"] for q in golden], "query")
gmax = (G @ P.T).max(axis=1)
def floor_for(keep_out: float) -> float:
    """The smallest 2-decimal score that lets at most floor((1 - keep_out) * n) golden questions reach an upload
    chunk (an interpolated quantile can let one more through)."""
    allowed = int(np.floor((1 - keep_out) * len(gmax) + 1e-9))
    x = float(np.sort(gmax)[::-1][allowed])          # the first golden score that must stay below the floor
    f_ = float(np.ceil(x * 100) / 100)
    return round(f_ + 0.01 if f_ <= x else f_, 2)


floor = floor_for(FLOOR_KEEP_OUT)
inclusion = float(np.mean(gmax >= floor))
m_floor = m3(P, Q, floor)
print(f"golden max score: median {np.median(gmax):.3f}, p95 {np.quantile(gmax, 0.95):.3f}, max {gmax.max():.3f} -> "
      f"floor {floor:.2f}; golden questions reaching a session chunk {inclusion:.3f}")
print(f"M3 with the floor: en {m_floor['en']} | ar {m_floor['ar']} | passes {passes(m_floor)}")
# The trade-off, reported for the owner: a lower floor lets more off-topic upload chunks into session_results (a
# separate, labelled list: the corpus results are untouched) but loses fewer relevant ones.
floor_table = {}
for keep_out in (0.95, 0.80, 0.50, 0.0):
    f_ = floor_for(keep_out) if keep_out else 0.0
    mm = m3(P, Q, f_)
    floor_table[str(keep_out)] = {"floor": f_, "golden_inclusion": round(float(np.mean(gmax >= f_)), 3),
                                  "hit@3_en": mm["en"]["hit@3"], "hit@3_ar": mm["ar"]["hit@3"]}
print(pd.DataFrame(floor_table).T.to_string())
assert inclusion <= 1 - FLOOR_KEEP_OUT + 1e-9
assert session_store.FLOORS.get(MODEL) == floor, f"set session_store.FLOORS[{MODEL!r}] = {floor} (measured)"
assert passes(m_floor) or not MEETS, "with its floor, the chosen model must still meet the thresholds"
print("✅ Phase 4 validation passed.")


# %% Phase 5 — M1 the corpus baseline with the session present
store = session_store.SessionStore()
sess = store.open(CEO)
for f in CLEAN:
    rep = store.add_upload(sess, (UP / "fixtures" / f).read_bytes(), f, USERS[CEO])
    assert rep.accepted, rep.message()
assert sess.chunk_count() == len(rows)
corpus = chunks.load(ROOT / "Data" / "processed" / "rag" / "chunks")
pos = {c: i for i, c in enumerate(corpus.chunk_id)}
judges = evaluation.judges(golden, facts, corpus.chunk_id.tolist(),
                           [chunks.compose(t, x) for t, x in zip(corpus.title, corpus.text)])
qmeta = pd.DataFrame(golden)[["qid", "lang", "sources", "type", "identifier"]]


def run(cfg: dict, session=None) -> tuple[dict, list, int, int]:
    per, ids, emb_calls, with_session = [], [], 0, 0
    for q in golden:
        res = R.search(q["question"], CEO, k=evaluation.K_RETRIEVAL, session=session, **cfg)
        emb_calls += res.api_calls["embedding"]
        with_session += bool(res.session_results)
        ids.append([r["chunk_id"] for r in res.results])
        per.append({"qid": q["qid"], **judges[q["qid"]].score([pos[c] for c in ids[-1]])})
    d = pd.DataFrame(per).merge(qmeta, on="qid")
    d["source"] = d.sources.str[0]
    return evaluation.aggregate(d), ids, emb_calls, with_session


m1 = {}
for label, cfg in (("dense", dict(hybrid=False, rerank=False)), ("dense+rerank", dict(hybrid=False, rerank=True))):
    s0, ids0, c0, _ = run(cfg)
    s1, ids1, c1, n_sess = run(cfg, sess)
    same = ids0 == ids1
    m1[label] = {"balanced_without": round(s0["balanced"], 4), "balanced_with_session": round(s1["balanced"], 4),
                 "baseline_file": round(baseline[label]["balanced"], 4), "identical_results": same,
                 "golden_with_session_results": n_sess, "embedding_calls": c0 + c1}
    print(f"{label}: {m1[label]}")
    assert same, f"{label}: the session changed corpus results"
    assert c0 + c1 == 0, "every golden question must come from the query cache"
assert round(m1["dense"]["balanced_with_session"], 3) == round(baseline["dense"]["balanced"], 3)
assert m1["dense+rerank"]["balanced_with_session"] >= baseline["dense+rerank"]["balanced"] - 0.02, \
    "rerank run fell outside the ADR-040 allowance (Jina drift)"
print("✅ Phase 5 validation passed.")


# %% Phase 6 — M4 isolation and RBAC
q = "What size of hole makes a reefer fail the visual check?"
for warm in (q, "What is the night shift allowance?"):  # their query vectors enter the cache before the snapshot
    R.search(warm, CEO, rerank=False)
qdrant_before = R.qdrant.count(qdrant_store.COLLECTION, exact=True).count
data_before = {str(p.relative_to(ROOT)): p.stat().st_mtime_ns for p in (ROOT / "Data").rglob("*") if p.is_file()}
fake_now = [time.time()]
iso = session_store.SessionStore(clock=lambda: fake_now[0], ttl_s=60)
a, b = iso.open(EMP_OPS), iso.open(EMP_FIN)
rep = iso.add_upload(a, (UP / "fixtures" / "clean_D1.pdf").read_bytes(), "clean_D1.pdf", USERS[EMP_OPS])
assert rep.accepted
own = R.search(q, EMP_OPS, rerank=False, session=a)
other_session = R.search(q, EMP_FIN, rerank=False, session=b)
checks = {"owner_sees_upload": bool(own.session_results),
          "results_labelled_untrusted": all(r["trust"] == "untrusted_upload" and r["lane"] == "session"
                                            for r in own.session_results),
          "other_session_empty": other_session.session_results == []}
for label, fn in (("other_employee_search", lambda: R.search(q, EMP_FIN, rerank=False, session=a)),
                  ("other_employee_get", lambda: iso.get(a.session_id, EMP_FIN)),
                  ("other_employee_upload", lambda: iso.add_upload(a, b"%PDF-", "x.pdf", USERS[EMP_FIN]))):
    try:
        fn()
        checks[label + "_refused"] = False
    except PermissionError:
        checks[label + "_refused"] = True
refused = iso.add_upload(b, (UP / "fixtures" / "clean_D3.pdf").read_bytes(), "clean_D3.pdf", USERS[EMP_FIN])
checks["level_above_uploader_refused"] = refused.codes() == ["E_LEVEL_ABOVE_UPLOADER"]
checks["corpus_request_unchanged"] = own.request["prefetch"] == R.search(q, EMP_OPS, rerank=False).request["prefetch"]
fake_now[0] += 61
expired = R.search(q, EMP_OPS, rerank=False, session=a)
checks["expired_session_empty"] = expired.session_results == [] and expired.request["session"].get("expired") is True
checks["sweep_cleared"] = iso.sweep() == 2 and not a.uploads and not iso.sessions
try:
    iso.get(a.session_id, EMP_OPS)
    checks["closed_session_gone"] = False
except session_store.SessionExpired:
    checks["closed_session_gone"] = True
# RBAC defence: a manager's own-department level-2 upload is visible to them; every session result is allowed
hr = store.open(MGR_HR)
store.add_upload(hr, (UP / "fixtures" / "clean_D3.pdf").read_bytes(), "clean_D3.pdf", USERS[MGR_HR])
res = R.search("What is the night shift allowance?", MGR_HR, rerank=False, session=hr)
checks["manager_sees_own_level2"] = any(r["sensitivity_level"] == 2 for r in res.session_results)
checks["all_session_results_allowed"] = all(retrieval.allowed(USERS[MGR_HR], r["sensitivity_level"], r["department"])
                                            for r in res.session_results)
data_after = {str(p.relative_to(ROOT)): p.stat().st_mtime_ns for p in (ROOT / "Data").rglob("*") if p.is_file()}
checks["qdrant_unchanged"] = R.qdrant.count(qdrant_store.COLLECTION, exact=True).count == qdrant_before == 2163
checks["data_tree_unchanged"] = data_after == data_before
print(checks)
assert all(checks.values()), [k for k, v in checks.items() if not v]
print("✅ Phase 6 validation passed.")


# %% Phase 7 — M5 end-to-end latency and the report
lat_upload, lat_lane = [], []
for _ in range(3):
    s = store.open(EMP_OPS)
    t = time.perf_counter()
    store.add_upload(s, (UP / "fixtures" / "clean_D1.pdf").read_bytes(), "clean_D1.pdf", USERS[EMP_OPS])
    lat_upload.append((time.perf_counter() - t) * 1000)
    store.close(s.session_id)
for qq in questions:
    t = time.perf_counter()
    sess.search(qq["question"], USERS[CEO])
    lat_lane.append((time.perf_counter() - t) * 1000)
latency = {"upload_D1_pdf_ms_p50": round(statistics.median(lat_upload)),
           "session_lane_ms_p50": round(statistics.median(lat_lane), 1),
           "session_lane_ms_p95": round(sorted(lat_lane)[int(0.95 * (len(lat_lane) - 1))], 1)}
print(f"latency {latency}")
report = {"date": dt.date.today().isoformat(), "rules": {"hit3_min": HIT3_MIN, "int8_max_loss": INT8_MAX_LOSS,
                                                         "floor_keep_out": FLOOR_KEEP_OUT},
          "m3_choice_table": choice_table, "choice": {"model": MODEL, "precision": PREC, "why": why},
          "m5_settings": settings, "best_setting": {k: (int(v) if isinstance(v, (np.integer,)) else v)
                                                    for k, v in best.items()},
          "providers_available": ort.get_available_providers(),
          "m2_floor": {"floor": floor, "golden_inclusion": inclusion, "golden_max_median": float(np.median(gmax))},
          "m3_with_floor": m_floor, "floor_table": floor_table, "m1_baseline": m1, "m4_isolation": checks, "m5_latency": latency}
out = UP / f"upload_eval_{dt.date.today().isoformat()}.json"
out.write_text(json.dumps(report, indent=1, ensure_ascii=False, default=float), encoding="utf-8")
assert latency["session_lane_ms_p95"] < 1_000 and latency["upload_D1_pdf_ms_p50"] < 30_000
print("✅ Phase 7 validation passed.")


# %% Final Checkpoint
# Narrative: the RAG plan's Phase 8 record (docs/archive/2026-10-08_RAG_Embeddings_Qdrant_plan.md), as for the other retrieval scripts
print(f"Final checkpoint: {MODEL}/{PREC} (hit@3 en {m_floor['en']['hit@3']}, ar {m_floor['ar']['hit@3']} with floor "
      f"{floor:.2f}); corpus baseline identical with a session (dense {m1['dense']['balanced_with_session']}, "
      f"dense+rerank {m1['dense+rerank']['balanced_with_session']}); isolation {sum(checks.values())}/{len(checks)}")
print("✅ Final checkpoint passed.")
