"""Phase 8 validation of the upload validator and the injection screening (pipelines/lib/uploads.py, screening.py,
upload_reader.py): every fixture gets exactly its expected verdict.

Plan:    docs/archive/2026-10-08_RAG_Embeddings_Qdrant_plan.md, Phase 8 (design §a, §c; owner answers Q6-Q8).
Run:     uv run python tools/run.py pipelines/scripts/retrieval/Upload_validation.py  (ports-postgres up: the uploaders'
         roles and departments are read through the read-only user, as at query time)
Reads:   Data/processed/rag/eval/uploads/fixtures/ + expected.json (Upload_fixtures.py); the 2,163 corpus chunks
Writes:  Data/processed/rag/eval/uploads/validation_report.json (verdicts, timings without wall-clock fields)
Re-run:  safe; no API call, nothing else written

Phases
1. Verdicts: the 51 fixture cases (7 clean, 44 attack / shape) — accepted or not, refusal codes, removed sections and
   notes all equal to expected.json; the employee message of a refused and of a partly removed upload.
2. False positives: the visible-text screen over the 2,163 corpus chunks (real regulatory prose) finds nothing.
3. Parity and contract: the same document as PDF and as DOCX gives the same chunks; every accepted upload passes the
   corpus chunk contract and concatenates with the corpus (unique chunk ids, same dtypes).
4. Isolation of the reader: a parse that exceeds its time limit is refused (E_PARSE_TIMEOUT), a crashing reader is
   refused (E_PARSE), and the caller survives both.
5. Latency of validation per fixture (p50 / p95) and the report.
"""
# %% Setup
import json
import statistics
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())
sys.path.insert(0, str(ROOT))
from pipelines.lib import chunks, common, screening, uploads  # noqa: E402
from pipelines.lib.retrieval import Retriever  # noqa: E402

common.load_env(ROOT)
UP = ROOT / "Data" / "processed" / "rag" / "eval" / "uploads"
FIX = UP / "fixtures"
EXPECTED = json.loads((UP / "expected.json").read_text(encoding="utf-8"))
R = Retriever.__new__(Retriever)   # only `user()` is needed: no Qdrant / Gemini connection
USERS = {u: R.user(u) for u in sorted({e["uploader"] for e in EXPECTED.values()})}


# %% Phase 1 — Verdicts
reports, timing, mismatches = {}, {}, []
for name, e in EXPECTED.items():
    fname = name.split("@")[0]
    t0 = time.perf_counter()
    rep = uploads.validate_upload((FIX / fname).read_bytes(), fname, USERS[e["uploader"]])
    timing[name] = (time.perf_counter() - t0) * 1000
    reports[name] = rep
    got = {"accepted": rep.accepted, "codes": rep.codes(), "removed": sorted(r.where.split()[1] for r in rep.removed),
           "notes": sorted({n.code for n in rep.notes})}
    want = {k: e[k] for k in got}
    if got != want:
        mismatches.append((name, got, want))
for name, got, want in mismatches:
    print(f"MISMATCH {name}: got {got}, expected {want}")
assert not mismatches, f"{len(mismatches)} fixture verdicts differ from expected.json"

by_kind = {}
for name, e in EXPECTED.items():
    k = e["kind"] if e["kind"] != "attack" else f"layer{e['layer']}"
    by_kind.setdefault(k, {"cases": 0, "accepted": 0, "with_removal": 0})
    by_kind[k]["cases"] += 1
    by_kind[k]["accepted"] += reports[name].accepted
    by_kind[k]["with_removal"] += bool(reports[name].removed)
print(by_kind)
# what the employee is told (one refused, one accepted with a removed section)
print(reports["file_javascript.pdf"].message())
print(reports["inj_egyptian.docx"].message())
assert "E_ACTIVE_CONTENT" in reports["file_javascript.pdf"].message()
assert "removed section 4" in reports["inj_egyptian.docx"].message()
# a clean upload carries its metadata and chunks; a refused one carries no chunk
assert all(reports[n].chunks and reports[n].document for n, e in EXPECTED.items() if e["accepted"])
assert not any(reports[n].chunks for n, e in EXPECTED.items() if not e["accepted"])
REVIEWED_1 = {"clean": {"cases": 8, "accepted": 8, "with_removal": 0},
              "layer3": {"cases": 13, "accepted": 10, "with_removal": 11},
              "layer2": {"cases": 11, "accepted": 11, "with_removal": 6},
              "layer1": {"cases": 9, "accepted": 0, "with_removal": 0},
              "shape": {"cases": 11, "accepted": 0, "with_removal": 0}}
assert by_kind == REVIEWED_1, f"reviewed snapshot differs: {by_kind}"
print("✅ Phase 1 validation passed.")


# %% Phase 2 — False positives over the corpus
corpus = chunks.load(ROOT / "Data" / "processed" / "rag" / "chunks")
fp = [(c, h.pattern) for c, t, x in zip(corpus.chunk_id, corpus.title, corpus.text)
      for h in screening.screen_text(chunks.compose(t, x))]
print(f"corpus chunks {len(corpus)}, screening hits {len(fp)}")
assert len(corpus) == 2163 and fp == [], f"false positives on the corpus: {fp[:5]}"
print("✅ Phase 2 validation passed.")


# %% Phase 3 — PDF / DOCX parity and the chunk contract
def norm(s: str) -> str:
    return " ".join(s.replace("|", " ").split())  # a table row is "a | b" in DOCX, "a b" in PDF


parity = {}
for k in ("D1", "D2", "D3"):
    a, b = reports[f"clean_{k}.pdf"].chunks, reports[f"clean_{k}.docx"].chunks
    parity[k] = [(r["chunk_id"], r["title"], norm(r["text"])) for r in a] == \
                [(r["chunk_id"], r["title"], norm(r["text"])) for r in b]
print(f"parity {parity}")
assert all(parity.values())
accepted = [n for n, e in EXPECTED.items() if e["accepted"]]
for n in accepted:
    chunks.check(uploads.to_frame(reports[n].chunks))
mixed = pd.concat([corpus, uploads.to_frame(reports["clean_D4.docx"].chunks)], ignore_index=True)
summary = chunks.check(mixed)
lengths = [len(r["text"]) for n in accepted for r in reports[n].chunks]
n_chunks = {k: len(reports[f"clean_{k}.{'docx' if k == 'D4' else 'pdf'}"].chunks) for k in ("D1", "D2", "D3", "D4")}
print(f"concat with corpus {summary}; chunks per clean document {n_chunks}; text length min {min(lengths)} "
      f"max {max(lengths)}")
assert summary["chunks"] == 2163 + n_chunks["D4"] and max(lengths) <= chunks.MAX_CHARS
assert n_chunks == {"D1": 11, "D2": 8, "D3": 7, "D4": 6}, n_chunks
print("✅ Phase 3 validation passed.")


# %% Phase 4 — Isolation of the reader
clean = (FIX / "clean_D1.pdf").read_bytes()
slow = uploads.validate_upload(clean, "clean_D1.pdf", USERS[12], timeout=0.05)
crashed = uploads.validate_upload(b"%PDF-1.7\n" + b"\x00" * 100, "broken.pdf", USERS[12])
print(f"timeout -> {slow.codes()}, broken file -> {crashed.codes()}")
assert slow.codes() == ["E_PARSE_TIMEOUT"] and not slow.accepted
assert crashed.codes() == ["E_PARSE"] and not crashed.accepted
try:  # an unknown format makes the child exit non-zero: the caller gets an exception it turns into E_PARSE
    uploads.read_isolated(clean, "exe")
    raise AssertionError("an unknown reader format must fail")
except RuntimeError:
    pass
print("✅ Phase 4 validation passed.")


# %% Phase 5 — Latency and report
ms = sorted(timing.values())
lat = {"p50_ms": round(statistics.median(ms)), "p95_ms": round(ms[int(0.95 * (len(ms) - 1))]),
       "max_ms": round(ms[-1])}
print(f"validation latency over {len(ms)} cases: {lat}")
report = {"cases": len(EXPECTED), "by_kind": by_kind, "corpus_false_positives": len(fp), "parity": parity,
          "chunks_per_clean_document": n_chunks,
          "verdicts": {n: {"accepted": r.accepted, "codes": r.codes(),
                           "removed": [f"{x.where}: {x.message[:80]}" for x in r.removed],
                           "notes": sorted({x.code for x in r.notes}), "what": EXPECTED[n]["what"]}
                       for n, r in reports.items()}}
(UP / "validation_report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
assert lat["p95_ms"] < 5_000, "validation must stay well inside an interactive budget"
print("✅ Phase 5 validation passed.")


# %% Final Checkpoint
# Narrative: the RAG plan's Phase 8 record (docs/archive/2026-10-08_RAG_Embeddings_Qdrant_plan.md), as for the other retrieval scripts
print(f"Final checkpoint: {len(EXPECTED)} cases as expected, 0 corpus false positives, PDF / DOCX parity "
      f"{sum(parity.values())}/3, reader isolation ok, p95 {lat['p95_ms']} ms")
print("✅ Final checkpoint passed.")
