"""Self-test of the shared library `pipelines/lib/` (D11, ADR-039): every module checked on real data, no API call.

Run:     uv run python tools/run.py pipelines/scripts/retrieval/Lib_selftest.py  (project root; needs ports-qdrant up)

Reads:   Data/processed/rag/chunks/*.parquet; the bake-off cache (Notebooks/_scratch/bakeoff/jina/, read-only); .env
Writes:  nothing under Data/; a temporary cache folder in Notebooks/_scratch/ and a temporary Qdrant collection
         `selftest_tmp`, both deleted at the end
Re-run:  safe; 0 embedding API calls (a fake embedder stands in for the provider)

Phases
1. chunks:       the real corpus passes the contract; broken copies are refused.
2. embeddings:   the cache logic (embed only new / changed texts) with a fake embedder; the existing bake-off cache
                 reads back through the library unchanged (format compatibility); redaction.
3. qdrant_store: on the live server, in a throwaway collection: create + checks, server-side BM25 through
                 qdrant-client, idempotent reload, a removed chunk is cleaned, a new version replaces the old one,
                 a wrong dimension is refused.
4. evaluation:   the metrics on a hand-made ranking whose values are computed by hand.
"""
# %% Setup
import os
import shutil
import sys
from pathlib import Path

import numpy as np

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())
sys.path.insert(0, str(ROOT))
from pipelines.lib import chunks, common, embeddings, evaluation, qdrant_store  # noqa: E402

common.load_env(ROOT)
TMP_CACHE = ROOT / "Notebooks" / "_scratch" / "lib_selftest_cache"
TMP_COLL = "selftest_tmp"


def refused(fn, *args) -> bool:
    try:
        fn(*args)
    except AssertionError:
        return True
    return False


# %% Phase 1 — chunks
df = chunks.load(ROOT / "Data" / "processed" / "rag" / "chunks")
summary = chunks.check(df)
assert summary == {"chunks": 2163, "files": 29, "by_level": {1: 2158, 3: 5}}, summary  # reviewed 2026-10-02
bad_level = df.copy(); bad_level.loc[0, "sensitivity_level"] = 4
bad_dept = df.copy(); bad_dept.loc[0, "department"] = "Marketing"
bad_count = df.copy(); bad_count.loc[0, "char_count"] = 1
bad_cols = df.drop(columns=["version_date"])
dup = df.copy(); dup.loc[1, "chunk_id"] = dup.loc[0, "chunk_id"]
headed = df.copy(); headed.loc[0, "text"] = headed.loc[0, "title"] + "\n" + headed.loc[0, "text"]  # ADR-041
headed.loc[0, "char_count"] = len(headed.loc[0, "text"])
assert all(refused(chunks.check, d) for d in (bad_level, bad_dept, bad_count, bad_cols, dup, headed))

# the title / text rule (ADR-041) on hand-made cases: moved, removed, or preserved; lossless and idempotent
cases = [  # (title, text, expected title, expected text, kind)
    ("USCG Report", "USCG ROI X (MISLE 1, 2024-01-01) — Conclusions\nBody.", "USCG ROI X (MISLE 1, 2024-01-01) — Conclusions",
     "Body.", "header_line"),
    ("Time bar", "17. Time bar\nThe Freight Forwarder shall ...", "17. Time bar", "The Freight Forwarder shall ...",
     "heading_line"),
    ("Throughput (x 1,000 t)", "Table: Throughput (x 1,000 t)\nDry bulk — 2025: 66,562", "Table: Throughput (x 1,000 t)",
     "Dry bulk — 2025: 66,562", "heading_line"),
    ("1.1 Liberalizing markets", "1.1 Liberalizing markets. Policies that open markets ...", "1.1 Liberalizing markets",
     "Policies that open markets ...", "run_in_heading"),
    ("Road", "Road infrastructure plays a vital role.", "Road", "Road infrastructure plays a vital role.", "unchanged"),
    ("Abbreviations", "Abbreviations", "Abbreviations", "Abbreviations", "unchanged"),  # no body: nothing to move
]
for t, x, want_t, want_x, kind in cases:
    got = chunks.split_heading(t, x)
    assert got == (want_t, want_x, kind), (t, got)
    assert chunks.split_heading(got[0], got[1])[2] == "unchanged"
assert chunks.compose("17. Time bar", "The Freight Forwarder shall ...") == "17. Time bar\nThe Freight Forwarder shall ..."
print("✅ Phase 1 validation passed: 2,163 chunks / 29 files pass the contract (no heading left in any text); "
      "6 broken copies refused; the title / text rule moves, removes or preserves as designed (6 cases).")


# %% Phase 2 — embeddings (no API call)
class FakeEmbedder:
    """Stands in for embeddings.Embedder: deterministic vectors, counts calls."""
    provider = "jina"

    def __init__(self):
        self.calls = self.texts = 0

    def embed(self, texts, kind):
        self.calls += 1
        self.texts += len(texts)
        return [[float(len(t)), float(sum(map(ord, t)) % 97), 1.0] for t in texts]


shutil.rmtree(TMP_CACHE, ignore_errors=True)
ids, texts = ["a", "b", "c"], ["first text", "second text", "third text"]
fake = FakeEmbedder()
m1 = embeddings.embed_with_cache(fake, TMP_CACHE, ids, texts, "document")
m2 = embeddings.embed_with_cache(fake, TMP_CACHE, ids, texts, "document")
assert (fake.calls, fake.texts) == (1, 3) and (m1 == m2).all(), "an unchanged text must never be re-embedded"
m3 = embeddings.embed_with_cache(fake, TMP_CACHE, ids, ["first text", "second text CHANGED", "third text"], "document")
assert fake.texts == 4 and (m3[[0, 2]] == m1[[0, 2]]).all() and not (m3[1] == m1[1]).all(), "only the changed text"
shutil.rmtree(TMP_CACHE)


class NoCalls:
    provider = "jina"

    def embed(self, texts, kind):
        raise AssertionError("the bake-off cache should be complete: no API call allowed")


jina_doc = ROOT / "Notebooks" / "_scratch" / "bakeoff" / "jina" / "doc"
units = [chunks.compose(t, x) for t, x in zip(df.title, df.text)]
cached = embeddings.load_cache(jina_doc)
served = [(i, u) for i, u in zip(df.chunk_id, units) if cached.get(i, ("",))[0] == embeddings.sha256_text(u)]
assert len(served) >= 1683, len(served)  # at least the chunks whose composed unit equals their pre-ADR-041 text
mat = embeddings.embed_with_cache(NoCalls(), jina_doc, [i for i, _ in served], [u for _, u in served], "document")
assert mat.shape == (len(served), 1024) and np.isfinite(mat).all()
unit = embeddings.normalize(mat)
assert np.allclose(np.linalg.norm(unit, axis=1), 1, atol=1e-5)

saved = os.environ.get("JINA_API_KEY")
os.environ["JINA_API_KEY"] = "abcdefgh12345678"
assert common.redact("bad key abcdefgh12345678 and key=ZZZZZZZZZZZZ") == "bad key *** and key=***"
os.environ["JINA_API_KEY"] = saved
print("✅ Phase 2 validation passed: cache embeds only new / changed texts (3 → 0 → 1), bake-off cache read back "
      f"through the library with 0 calls ({len(served):,} composed units × 1,024), redaction works.")

# %% Phase 3 — qdrant_store on the live server (throwaway collection)
client = qdrant_store.connect()
if client.collection_exists(TMP_COLL):
    client.delete_collection(TMP_COLL)
try:
    assert qdrant_store.ensure_collection(client, 4, TMP_COLL) is True
    assert qdrant_store.ensure_collection(client, 4, TMP_COLL) is False  # exists, config checked
    assert refused(qdrant_store.ensure_collection, client, 8, TMP_COLL), "a wrong dimension must be refused"

    sample = df[df.filename == "Transit_Dues_Rates.pdf"].reset_index(drop=True)  # Suez Notes: 4 chunks
    assert len(sample) == 4

    def rows(doc_id, frame):
        return [qdrant_store.payload(r, doc_id, embeddings.sha256_text(r["text"]))
                for r in frame.to_dict("records")]

    vecs = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    v1 = "suez_transit_dues_2023"
    r1 = qdrant_store.upsert_document(client, v1, rows(v1, sample), vecs, name=TMP_COLL)
    assert r1 == {"upserted": 4, "stale_removed": 0}
    qdrant_store.verify_document(client, v1, sample.chunk_id.tolist(), TMP_COLL)

    pid = qdrant_store.point_id(v1, sample.chunk_id[0])
    stored = client.retrieve(TMP_COLL, ids=[pid], with_vectors=True, with_payload=True)[0]
    assert len(stored.vector["bm25"].indices) >= 5, "the SERVER must have built the bm25 vector"
    assert stored.payload["sensitivity_level"] == 1 and stored.payload["document_id"] == v1
    assert set(stored.payload) == set(chunks.COLUMNS) | {"document_id", "text_sha256", "unit_kind", "year"}
    assert stored.payload["unit_kind"] == "paragraph" and stored.payload["year"] == 2023  # Suez note, 2023-01-01
    assert set(df.unit_type) <= set(qdrant_store.UNIT_KIND), "a unit_type of the corpus has no unit_kind"
    # regression (2026-10-08): `sub_chunk` holds numpy arrays for 556 chunks; payload() must turn them into lists
    arr_row = df[df.sub_chunk.map(lambda v: isinstance(v, np.ndarray))].iloc[0].to_dict()
    arr_payload = qdrant_store.payload(arr_row, "x", "y")
    assert arr_payload["sub_chunk"] == list(arr_row["sub_chunk"]) and isinstance(arr_payload["sub_chunk"], list)

    r2 = qdrant_store.upsert_document(client, v1, rows(v1, sample), vecs, name=TMP_COLL)  # same load again
    assert r2 == {"upserted": 4, "stale_removed": 0}
    assert client.count(TMP_COLL, exact=True).count == 4, "a reload must overwrite, never duplicate"

    r3 = qdrant_store.upsert_document(client, v1, rows(v1, sample.iloc[:3]), vecs[:3], name=TMP_COLL)
    assert r3 == {"upserted": 3, "stale_removed": 1}, r3  # a chunk disappeared from the document
    qdrant_store.verify_document(client, v1, sample.chunk_id[:3].tolist(), TMP_COLL)

    v2 = "suez_transit_dues_2023_v2"
    r4 = qdrant_store.upsert_document(client, v2, rows(v2, sample), vecs, supersedes=(v1,), name=TMP_COLL)
    assert r4 == {"upserted": 4, "stale_removed": 3}, r4  # the whole old version is gone
    qdrant_store.verify_document(client, v2, sample.chunk_id.tolist(), TMP_COLL)
    assert qdrant_store.document_ids_in_store(client, v1, TMP_COLL) == set()
    assert client.count(TMP_COLL, exact=True).count == 4
finally:
    client.delete_collection(TMP_COLL)
assert not client.collection_exists(TMP_COLL)

print("✅ Phase 3 validation passed: collection spec checked (wrong dimension refused), server-built bm25 through "
      "qdrant-client, reload = 0 duplicates, removed chunk cleaned (1), new version replaced the old (3 removed), "
      "throwaway collection deleted.")

# %% Phase 4 — evaluation: metrics on a hand-made ranking whose values are known
texts = ["BIG STICK operator under the influence of alcohol",  # 0: fact f1
         "BIG STICK solo trip, under the influence of alcohol",  # 1: f1 + f2
         "BIG STICK hull details",                               # 2: not relevant
         "another vessel, alcohol",                              # 3: not relevant (no vessel)
         "BIG STICK went alone"]                                 # 4: fact f2
facts = [{"id": "f1", "all": [["BIG STICK"], ["alcohol"]]}, {"id": "f2", "all": [["BIG STICK"], [r"\bsolo\b", r"\balone\b"]]}]
judge = evaluation.QueryJudge(facts, expected_positions={1}, texts=texts)
assert judge.relevant == {0, 1, 4}
m = judge.score(np.array([2, 0, 3, 1, 4]))
assert m["first_expected_rank"] == 4 and m["hit@1"] == 0.0 and m["hit@5"] == 1.0 and abs(m["rr"] - 0.25) < 1e-12
assert m["fact_recall@10"] == 1.0 and m["complete@10"] == 1.0 and m["sufficiency@8"] == 1.0
assert abs(m["precision@8"] - 3 / 8) < 1e-12           # 3 relevant of the 8 context slots
assert abs(m["redundancy@8"] - 1 / 3) < 1e-12          # 0 adds f1, 1 adds f2, 4 adds nothing new
ideal = 1 + 1 / np.log2(3) + 1 / np.log2(4)             # 3 relevant chunks in the corpus
dcg = 1 / np.log2(3) + 1 / np.log2(5) + 1 / np.log2(6)  # relevant at ranks 2, 4, 5
assert abs(m["ndcg@10"] - dcg / ideal) < 1e-12
perfect = judge.score(np.array([1, 0, 4, 2, 3]))
assert perfect["ndcg@10"] == 1.0 and perfect["hit@1"] == 1.0
print("✅ Phase 4 validation passed: evaluation metrics equal hand-computed values (hit, MRR, fact recall, "
      "sufficiency, precision, redundancy, nDCG; a perfect ranking scores nDCG 1).")
