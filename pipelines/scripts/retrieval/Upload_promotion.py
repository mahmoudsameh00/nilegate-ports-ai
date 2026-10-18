"""Promotion of a manager's upload to the corpus (RAG plan Phase 8 §b; owner decisions D12, D14, Q3, Q5, Q8):
request (in the conversation) → review (offline, by the owner) → approval → registration like the siblings.

Plan:    docs/archive/2026-10-08_RAG_Embeddings_Qdrant_plan.md, Phase 8.
Run:     uv run python pipelines/scripts/retrieval/Upload_promotion.py --list
         uv run python pipelines/scripts/retrieval/Upload_promotion.py --review <request_id>
         uv run python pipelines/scripts/retrieval/Upload_promotion.py --approve <request_id> [--commit]
         uv run python pipelines/scripts/retrieval/Upload_promotion.py --reject <request_id> --reason "..."
         uv run python pipelines/scripts/retrieval/Upload_promotion.py --selftest   (tools/run.py passes no arguments)
Reads:   Data/incoming/promotion/<request_id>/ (the file + request.json written by `SessionStore.request_promotion`
         when a manager asked); PostgreSQL (the requester's CURRENT role and department, read-only user); the corpus
         chunks (near-duplicate check)
Writes:  review.json / review.md / decision.json and approved/ (staged artifacts) in the request folder; with
         --commit only: Data/processed/rag/promoted/<document_id>_chunks.parquet, documents_promoted.csv,
         db/migrations/NNN_register_<document_id>.sql (applied by the owner), Gemini vectors in
         Data/embeddings/gemini-embedding-2/cache_promoted/, the document's points in Qdrant `nilegate_docs`
Re-run:  --review / --approve are repeatable; --commit is idempotent (point ids per document version, ADR-039;
         a second commit re-embeds nothing: the cache is keyed by text hash)

Why a separate folder (`promoted/`) instead of `chunks/`: the corpus scripts (Embeddings.py, Qdrant_loader.py) assert
their reviewed counts (2,163 chunks); a promoted document has the same contract, the same registry table, the same
model, payload and collection, but its own files, so no corpus artifact is rewritten by another script (project rule 3).

The gates, in order (each refusal says why):
1. request: a `manager` (D12), the document's department = the manager's (Q3), no section removed by screening (Q8)
   — enforced when the request is made (`session_store`) and again here with the requester's current role;
2. review: the file is unchanged (SHA-256), it passes the validator again, its chunks pass the corpus contract, and
   near-duplicates of corpus chunks are listed for the reviewer;
3. approval: the data policy (Q5, ADR-037): `data_origin: public` and `personal_data: no`, unless `.env` declares
   `GEMINI_TIER=paid`; otherwise refused with that reason;
4. commit: the raw file must already be in Data/raw/unstructured/company/ with the same SHA-256 (the owner copies
   it: the assistant never writes Data/raw/); then files, registry row + migration, vectors, Qdrant, verification, and a
   retrieval check (a question from the document finds it; RBAC holds).
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
from qdrant_client import models

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())
sys.path.insert(0, str(ROOT))
from pipelines.lib import chunks, common, embeddings, qdrant_store, retrieval, session_store, uploads  # noqa: E402

common.load_env(ROOT)
PROMO = session_store.PROMOTION_DIR
PROMOTED = ROOT / "Data" / "processed" / "rag" / "promoted"
RAW_COMPANY = ROOT / "Data" / "raw" / "unstructured" / "company"
MIGRATIONS = ROOT / "db" / "migrations"
VECTOR_CACHE = ROOT / "Data" / "embeddings" / "gemini-embedding-2" / "cache_promoted"
REGISTRY_COLUMNS = ["document_id", "filename", "title", "source", "real_or_synthetic", "document_type", "department",
                    "sensitivity_level", "version_date", "ingestion_scope", "source_url", "sha256", "file_size_bytes",
                    "page_count", "chunk_count"]
NEAR_DUP = 0.8


def load_request(folder: Path) -> dict:
    return json.loads((folder / "request.json").read_text(encoding="utf-8"))


def save(folder: Path, name: str, obj) -> None:
    (folder / name).write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def users() -> retrieval.Retriever:
    return retrieval.Retriever.__new__(retrieval.Retriever)  # only `user()`: no Qdrant / Gemini connection


# ------------------------------------------------------------------------------------------------------- review ---
def review(folder: Path, corpus: pd.DataFrame | None = None) -> dict:
    req = load_request(folder)
    data = (folder / req["filename"]).read_bytes()
    problems, warnings = [], []
    if hashlib.sha256(data).hexdigest() != req["sha256"]:
        problems.append("the stored file differs from the requested one (SHA-256)")
    requester = users().user(req["requested_by"]["employee_id"])  # current role / department, not the old ones
    if requester.role not in session_store.PROMOTING_ROLES:
        problems.append(f"the requester is now a {requester.role}: only a manager can promote")
    rep = uploads.validate_upload(data, req["filename"], requester)
    if not rep.accepted:
        problems += [f"validation: [{r.code}] {r.where}: {r.message}" for r in rep.reasons]
    if rep.removed:
        problems += [f"screening removed {r.where}: fix the source document" for r in rep.removed]
    doc = rep.document or req["document"]
    if doc["department"] != requester.department:
        problems.append(f"the document belongs to {doc['department']}, the requester's department is "
                        f"{requester.department}")
    dups = []
    if rep.accepted:
        frame = uploads.to_frame(rep.chunks)
        chunks.check(frame)
        if corpus is None:
            corpus = chunks.load(ROOT / "Data" / "processed" / "rag" / "chunks")
        corpus_sh = [(c, retrieval.shingles(x)) for c, x in zip(corpus.chunk_id, corpus.text)]
        for r in rep.chunks:
            sh = retrieval.shingles(r["text"])
            dups += [{"chunk": r["chunk_id"], "corpus_chunk": c} for c, o in corpus_sh
                     if retrieval.near_duplicate(sh, o)]
        if dups:
            warnings.append(f"{len(dups)} chunk(s) nearly duplicate corpus chunks (listed): check before approval")
    policy_ok, policy = data_policy(doc)
    if not policy_ok:
        warnings.append(policy)
    out = {"request_id": req["request_id"], "reviewed_at": dt.datetime.now().isoformat(timespec="seconds"),
           "requester_now": vars(requester), "document": doc, "chunks": len(rep.chunks), "problems": problems,
           "warnings": warnings, "near_duplicates": dups, "data_policy": policy,
           "status": "reviewed" if not problems else "blocked"}
    save(folder, "review.json", out)
    lines = [f"# Promotion review — {doc.get('document_code')} {doc.get('title')}", "",
             f"- requested by employee {req['requested_by']['employee_id']} ({requester.role}, {requester.department})"
             f" on {req['requested_at']}; note: {req.get('note') or '—'}",
             f"- level {doc.get('sensitivity_level')}, department {doc.get('department')}, type "
             f"{doc.get('document_type')}, data_origin {doc.get('data_origin')}, personal_data "
             f"{doc.get('personal_data')}",
             f"- chunks: {len(rep.chunks)}; status: **{out['status']}**", "", "## Problems (block approval)",
             *(f"- {p}" for p in problems or ["none"]), "", "## Warnings", *(f"- {w}" for w in warnings or ["none"]),
             "", "## Chunks"]
    for r in rep.chunks:
        lines += [f"### {r['chunk_id']} — {r['title']}", "", r["text"][:600] + ("…" if len(r["text"]) > 600 else ""),
                  ""]
    (folder / "review.md").write_text("\n".join(lines), encoding="utf-8")
    return out


def data_policy(doc: dict) -> tuple[bool, str]:
    """Q5 / ADR-037: the corpus vectors are Gemini's; its free tier may train on inputs."""
    if doc.get("data_origin") == "public" and doc.get("personal_data") == "no":
        return True, "public, no personal data: Gemini free tier allowed (ADR-037)"
    if os.environ.get("GEMINI_TIER", "free").lower() == "paid":
        return True, "non-public or personal data: allowed because .env declares GEMINI_TIER=paid"
    return False, ("non-public or personal data cannot be embedded on Gemini's free tier (ADR-037): approval needs "
                   "GEMINI_TIER=paid in .env (owner decision Q5)")


# ------------------------------------------------------------------------------------------------------ approve ---
def approve(folder: Path) -> dict:
    """Stage every artifact of the registration in <folder>/approved/ (nothing outside the request folder)."""
    rev = json.loads((folder / "review.json").read_text(encoding="utf-8")) if (folder / "review.json").exists() else {}
    if rev.get("status") != "reviewed":
        return {"approved": False, "why": "run --review first; the review must have no problems"}
    req = load_request(folder)
    ok, policy = data_policy(rev["document"])
    if not ok:
        return {"approved": False, "why": policy}
    data = (folder / req["filename"]).read_bytes()
    requester = users().user(req["requested_by"]["employee_id"])
    rep = uploads.validate_upload(data, req["filename"], requester)
    assert rep.accepted and not rep.removed, "the document changed since the review"
    doc = rep.document
    stage = folder / "approved"
    stage.mkdir(exist_ok=True)
    rows = [{**r, "filename": f"company/{req['filename']}"} for r in rep.chunks]
    frame = uploads.to_frame(rows)
    chunks.check(frame)
    frame.to_parquet(stage / f"{doc['document_id']}_chunks.parquet", index=False)
    row = {"document_id": doc["document_id"], "filename": f"unstructured/company/{req['filename']}",
           "title": doc["title"], "source": uploads.SOURCE, "real_or_synthetic": "synthetic",
           "document_type": doc["document_type"], "department": doc["department"],
           "sensitivity_level": int(doc["sensitivity_level"]), "version_date": doc["version_date"],
           "ingestion_scope": None, "source_url": None, "sha256": req["sha256"], "file_size_bytes": len(data),
           "page_count": rep.stats.get("pages"), "chunk_count": len(rows)}
    pd.DataFrame([row], columns=REGISTRY_COLUMNS).to_csv(stage / "documents_row.csv", index=False)
    (stage / "migration.sql").write_text(migration_sql(row, "NNN", None), encoding="utf-8")
    decision = {"approved": True, "approved_at": dt.datetime.now().isoformat(timespec="seconds"),
                "document_id": doc["document_id"], "chunks": len(rows), "data_policy": policy,
                "next": "copy the original file to Data/raw/unstructured/company/, then --approve <id> --commit"}
    save(folder, "decision.json", decision)
    return decision


def lit(v) -> str:
    if v is None or (isinstance(v, float) and v != v):
        return "NULL"
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    return "'" + str(v).replace("'", "''") + "'"


def migration_sql(row: dict, number: str, ingested_at: str | None) -> str:
    """The registry row as a migration; `ingested_at` = when --commit upserted the document into Qdrant (NULL in the
    preview written at approval)."""
    vals = ", ".join(lit(row[c]) for c in REGISTRY_COLUMNS) + f", {lit(ingested_at)}::timestamptz"
    return f"""-- =====================================================================
-- {number} — Register the promoted company document {row['document_id']}
-- Decisions: ADR-035 (registry row per raw file), RAG plan Phase 8 (manager promotion, owner review).
-- Generated by pipelines/scripts/retrieval/Upload_promotion.py --commit; never edited after applying.
-- =====================================================================
BEGIN;

INSERT INTO public.documents (document_id, filename, title, source, real_or_synthetic, document_type, department_id,
                              sensitivity_level, version_date, ingestion_scope, source_url, sha256, file_size_bytes,
                              page_count, chunk_count, ingested_at)
SELECT v.document_id, v.filename, v.title, v.source, v.real_or_synthetic, v.document_type, d.department_id,
       v.sensitivity_level, v.version_date, v.ingestion_scope, v.source_url, v.sha256, v.file_size_bytes, v.page_count,
       v.chunk_count, v.ingested_at
FROM (VALUES
    ({vals})
) AS v ({', '.join(REGISTRY_COLUMNS)}, ingested_at)
JOIN public.departments d ON d.department_name = v.department;

DO $$
BEGIN
    IF (SELECT count(*) FROM public.documents WHERE document_id = {lit(row['document_id'])}) <> 1 THEN
        RAISE EXCEPTION 'documents: {row['document_id']} not registered exactly once';
    END IF;
END $$;

COMMIT;
"""


def next_migration_number(folder: Path) -> str:
    nums = [int(m.group(1)) for p in folder.glob("*.sql") if (m := re.match(r"(\d{3})_", p.name))]
    return f"{max(nums, default=0) + 1:03d}"


# ------------------------------------------------------------------------------------------------------- commit ---
def commit(folder: Path, collection: str = qdrant_store.COLLECTION, out_dir: Path = PROMOTED,
           migrations: Path = MIGRATIONS, raw_dir: Path = RAW_COMPANY, vector_cache: Path = VECTOR_CACHE,
           require_raw: bool = True) -> dict:
    """Register the approved document like its siblings: chunk file + registry row + migration, Gemini vectors
    (files first), Qdrant upsert (the only writer, `qdrant_store`), verification, retrieval + RBAC check."""
    dec = json.loads((folder / "decision.json").read_text(encoding="utf-8"))
    assert dec.get("approved"), "not approved"
    req = load_request(folder)
    stage = folder / "approved"
    doc_id = dec["document_id"]
    frame = pd.read_parquet(stage / f"{doc_id}_chunks.parquet")
    chunks.check(frame)
    row = pd.read_csv(stage / "documents_row.csv").iloc[0].to_dict()
    if require_raw:
        raw = raw_dir / req["filename"]
        assert raw.exists(), f"copy the original file to {raw.relative_to(ROOT)} first (owner step)"
        assert hashlib.sha256(raw.read_bytes()).hexdigest() == req["sha256"], "the raw file differs from the request"
    out_dir.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(out_dir / f"{doc_id}_chunks.parquet", index=False)
    reg = out_dir / "documents_promoted.csv"
    have = pd.read_csv(reg) if reg.exists() else pd.DataFrame(columns=REGISTRY_COLUMNS)
    have = pd.concat([have[have.document_id != doc_id], pd.DataFrame([row])], ignore_index=True)
    have[REGISTRY_COLUMNS].to_csv(reg, index=False)

    rows = frame.to_dict("records")
    composed = [chunks.compose(r["title"], r["text"]) for r in rows]
    http = httpx.Client(timeout=60.0)
    emb = embeddings.Embedder("gemini", http)
    dense = embeddings.normalize(embeddings.embed_with_cache(emb, vector_cache, [r["chunk_id"] for r in rows],
                                                             composed, "document"))
    client = qdrant_store.connect()
    qdrant_store.ensure_collection(client, dense.shape[1], collection)
    payloads = [qdrant_store.payload(r, doc_id, embeddings.sha256_text(t)) for r, t in zip(rows, composed)]
    up = qdrant_store.upsert_document(client, doc_id, payloads, dense.tolist(), name=collection)
    qdrant_store.verify_document(client, doc_id, [r["chunk_id"] for r in rows], name=collection)
    # the migration is written once the points are verified, so its ingested_at is the first load time; a re-commit
    # keeps it unchanged (a migration is never edited, it may already be applied)
    existing = sorted(migrations.glob(f"*_register_{doc_id}.sql"))
    mig = existing[0] if existing else migrations / f"{next_migration_number(migrations)}_register_{doc_id}.sql"
    if not existing:
        loaded_at = dt.datetime.now().astimezone().isoformat(timespec="seconds")
        mig.write_text(migration_sql(row, mig.name[:3], loaded_at), encoding="utf-8")

    # retrieval check: the title as a question finds the document for its own department's manager; RBAC holds for
    # an employee of another department (no chunk above their access is returned)
    qvec = embeddings.normalize(np.asarray(emb.embed([rows[0]["title"].split(" — ")[0]], "query"), dtype=np.float32))
    R = users()
    checks = {}
    for label, emp in (("owner_department_manager", req["requested_by"]["employee_id"]),
                       ("other_department_employee", 13)):
        user = R.user(emp)
        hits = client.query_points(collection, query=qvec[0].tolist(), using="dense",
                                   query_filter=retrieval.rbac_filter(user), limit=5, with_payload=True,
                                   search_params=models.SearchParams(exact=True)).points
        mine = [h for h in hits if h.payload["document_id"] == doc_id]
        checks[label] = {"user": vars(user), "found": len(mine),
                         "all_allowed": all(retrieval.allowed(user, h.payload["sensitivity_level"],
                                                              h.payload["department"]) for h in hits)}
    expected_other = 1 if retrieval.allowed(R.user(13), int(row["sensitivity_level"]), row["department"]) else 0
    assert checks["owner_department_manager"]["found"] >= 1, "the promoted document is not found by its manager"
    assert all(c["all_allowed"] for c in checks.values()), "RBAC violation"
    assert (checks["other_department_employee"]["found"] > 0) == bool(expected_other), "RBAC level not enforced"
    result = {"committed_at": dt.datetime.now().isoformat(timespec="seconds"), "collection": collection,
              "upsert": up, "migration": str(mig.relative_to(ROOT)) if mig.is_relative_to(ROOT) else str(mig),
              "chunk_file": str((out_dir / f"{doc_id}_chunks.parquet")), "gemini_calls": emb.calls,
              "retrieval_checks": checks}
    save(folder, "commit.json", result)
    return result


def reject(folder: Path, reason: str) -> dict:
    out = {"approved": False, "rejected_at": dt.datetime.now().isoformat(timespec="seconds"), "why": reason[:500]}
    save(folder, "decision.json", out)
    return out


# ----------------------------------------------------------------------------------------------------- selftest ---
def selftest() -> None:
    """End to end on fixtures, without touching the corpus: requests in Notebooks/_scratch/, a throwaway Qdrant
    collection (dropped at the end). Gemini: the 8 chunks of a PUBLIC synthetic document + 2 query vectors."""
    root = ROOT / "Notebooks" / "_scratch" / "promotion_selftest"
    root.mkdir(parents=True, exist_ok=True)
    fx = ROOT / "Data" / "processed" / "rag" / "eval" / "uploads" / "fixtures"
    R = users()
    MGR_CUS, MGR_OPS, EMP_OPS = R.user(4), R.user(2), R.user(12)
    store = session_store.SessionStore()
    results = {}

    def upload(user, name):
        s = store.open(user.employee_id)
        rep = store.add_upload(s, (fx / name).read_bytes(), name, user)
        assert rep.accepted, rep.message()
        return s, rep.document["document_id"]

    s, d = upload(EMP_OPS, "clean_D1.pdf")
    results["employee_refused"] = not store.request_promotion(s, d, EMP_OPS, root=root)["accepted"]
    s, d = upload(MGR_OPS, "clean_D2.docx")   # Customs level 2: visible to any manager (ceiling 2), not his department
    results["other_department_refused"] = not store.request_promotion(s, d, MGR_OPS, root=root)["accepted"]
    s, d = upload(MGR_CUS, "inj_egyptian.docx")
    results["screened_document_refused"] = not store.request_promotion(s, d, MGR_CUS, root=root)["accepted"]
    s, d = upload(MGR_CUS, "clean_D2.docx")   # internal data: request ok, approval refused by the data policy (Q5)
    r = store.request_promotion(s, d, MGR_CUS, note="selftest internal", root=root)
    assert r["accepted"], r
    rv = review(r["folder"])
    tier = os.environ.pop("GEMINI_TIER", None)
    ap = approve(r["folder"])
    if tier is not None:
        os.environ["GEMINI_TIER"] = tier
    results["internal_review_ok"] = rv["status"] == "reviewed" and any("GEMINI_TIER" in w for w in rv["warnings"])
    results["internal_approval_refused"] = not ap["approved"] and "GEMINI_TIER=paid" in ap["why"]
    s, d = upload(MGR_CUS, "clean_D2_public.docx")  # public data: the whole path
    r = store.request_promotion(s, d, MGR_CUS, note="selftest public", root=root)
    rv = review(r["folder"])
    ap = approve(r["folder"])
    assert rv["status"] == "reviewed" and ap["approved"], (rv["problems"], ap)
    test_collection = "nilegate_promotion_selftest"
    client = qdrant_store.connect()
    if client.collection_exists(test_collection):
        client.delete_collection(test_collection)
    try:
        cm = commit(r["folder"], collection=test_collection, out_dir=r["folder"] / "commit_out",
                    migrations=r["folder"] / "commit_out", require_raw=False,
                    vector_cache=root / "vector_cache")
        first_sql = (ROOT / cm["migration"]).read_text(encoding="utf-8")
        again = commit(r["folder"], collection=test_collection, out_dir=r["folder"] / "commit_out",
                       migrations=r["folder"] / "commit_out", require_raw=False, vector_cache=root / "vector_cache")
    finally:
        client.delete_collection(test_collection)
    results["public_committed"] = cm["upsert"]["upserted"] == 8 and cm["upsert"]["stale_removed"] == 0
    results["recommit_idempotent"] = again["upsert"] == {"upserted": 8, "stale_removed": 0} and \
        again["gemini_calls"] == 1  # only the retrieval-check question: the 8 chunk vectors come from the cache
    results["migration_has_ingested_at"] = "::timestamptz" in first_sql and "NULL::timestamptz" not in first_sql and \
        (ROOT / again["migration"]).read_text(encoding="utf-8") == first_sql  # written once, never rewritten
    results["manager_finds_it"] = cm["retrieval_checks"]["owner_department_manager"]["found"] >= 1
    results["other_employee_blocked"] = cm["retrieval_checks"]["other_department_employee"]["found"] == 0
    results["corpus_untouched"] = qdrant_store.connect().count(qdrant_store.COLLECTION, exact=True).count == 2163
    results["throwaway_dropped"] = not client.collection_exists(test_collection)
    print(results)
    assert all(results.values()), [k for k, v in results.items() if not v]
    print("✅ Promotion self-test passed.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true")
    g.add_argument("--review")
    g.add_argument("--approve")
    g.add_argument("--reject")
    g.add_argument("--selftest", action="store_true")
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--reason", default="")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.list:
        for f in sorted(p for p in PROMO.glob("*") if p.is_dir()) if PROMO.exists() else []:
            req = load_request(f)
            status = "requested"
            for name in ("review.json", "decision.json", "commit.json"):
                if (f / name).exists():
                    status = name.split(".")[0]
            print(f"{req['request_id']}  {req['document']['document_code']}  by {req['requested_by']}  [{status}]")
        return
    rid = a.review or a.approve or a.reject
    folder = PROMO / rid
    assert (folder / "request.json").exists(), f"no request {rid}"
    if a.review:
        out = review(folder)
        print(f"{out['status']}: problems {out['problems']}, warnings {out['warnings']} → {folder / 'review.md'}")
    elif a.reject:
        print(reject(folder, a.reason or "rejected by the reviewer"))
    elif a.approve:
        out = approve(folder) if not (folder / "decision.json").exists() or not a.commit else \
            json.loads((folder / "decision.json").read_text(encoding="utf-8"))
        print(out)
        if a.commit and out.get("approved"):
            print(commit(folder))


if __name__ == "__main__":
    main()
