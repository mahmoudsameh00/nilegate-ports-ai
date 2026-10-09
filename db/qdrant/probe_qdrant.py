"""Probe the pinned Qdrant server (RAG plan Phase 3): security, the collection shape we need, server-side BM25 (D4),
the ADR-006 filter inside both prefetches of a hybrid query. Works in a throwaway collection, deleted at the end.

    uv run python db/qdrant/probe_qdrant.py

Raw REST through httpx (not qdrant-client) on purpose: the client could run BM25 locally (fastembed) and hide whether
the SERVER can do it, which is exactly what D4 asks. The API key is read from .env and never printed.
Output: printed and saved to db/qdrant/audit/<date>_probe.txt. Exit 1 if any check fails.
"""
import datetime as dt
import socket
import sys
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
URL = "http://127.0.0.1:6333"
COLL = "probe_tmp"
EXPECTED_VERSION = "1.19.1"

env = {}
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
KEY = {"api-key": env["QDRANT_API_KEY"]}
lines, failed = [], []


def out(msg: str) -> None:
    print(msg, flush=True)
    lines.append(msg)


def check(name: str, ok: bool, detail: str = "") -> None:
    out(f"{'PASS' if ok else 'FAIL'}  {name}{' — ' + detail if detail else ''}")
    if not ok:
        failed.append(name)


def pid(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"probe/{name}"))


def rbac(ceiling: int, department: str) -> dict:
    """ADR-006 as a Qdrant filter: level <= ceiling OR (own department AND level <= 2)."""
    return {"should": [{"key": "sensitivity_level", "range": {"lte": ceiling}},
                       {"must": [{"key": "department", "match": {"value": department}},
                                 {"key": "sensitivity_level", "range": {"lte": 2}}]}]}


POINTS = [  # (name, level, department, text, dense vector)
    ("suez", 1, "Operations", "Suez Canal transit dues for laden container ships by band", [1, 0, 0, 0]),
    ("net_result", 3, "Finance", "The net result of the Port Authority fell to 266 million euro", [0, 1, 0, 0]),
    ("overboard", 1, "Operations", "The operator fell overboard while fishing alone", [0, 0, 1, 0]),
    ("invoice", 2, "Finance", "Invoice amount of the net result per vessel call", [0, 0.9, 0, 0.1]),
]
QUERY_TEXT, QUERY_DENSE = "net result million euro", [0, 1, 0, 0]

with httpx.Client(base_url=URL, timeout=30) as c:
    out(f"Qdrant probe {dt.datetime.now().isoformat(timespec='seconds')}")
    # --- security -----------------------------------------------------------------------------------------------
    r = c.get("/collections")
    check("no API key → refused", r.status_code in (401, 403), f"HTTP {r.status_code}")
    r = c.get("/collections", headers={"api-key": "wrong-key-for-probe"})
    check("wrong API key → refused", r.status_code in (401, 403), f"HTTP {r.status_code}")
    r = c.get("/", headers=KEY)
    version = r.json().get("version")
    check("API key accepted, pinned version", r.status_code == 200 and version == EXPECTED_VERSION, f"version {version}")
    lan = [ip for ip in socket.gethostbyname_ex(socket.gethostname())[2] if not ip.startswith("127.")]
    for ip in lan:
        try:
            socket.create_connection((ip, 6333), timeout=3).close()
            check(f"LAN address {ip}:6333 closed", False, "connection accepted")
        except OSError as e:
            check(f"LAN address {ip}:6333 closed", True, type(e).__name__)

    # --- collection shape: dense + bm25 named vectors, payload indexes ---------------------------------------------
    c.delete(f"/collections/{COLL}", headers=KEY)
    r = c.put(f"/collections/{COLL}", headers=KEY, json={
        "vectors": {"dense": {"size": 4, "distance": "Cosine"}},
        "sparse_vectors": {"bm25": {"modifier": "idf"}}})
    check("create collection (dense cosine + sparse bm25 with IDF)", r.status_code == 200, r.text[:120])
    for field, schema in [("sensitivity_level", "integer"), ("department", "keyword")]:
        r = c.put(f"/collections/{COLL}/index?wait=true", headers=KEY, json={"field_name": field, "field_schema": schema})
        check(f"payload index {field} ({schema})", r.status_code == 200, r.text[:120])

    # --- D4: server-side BM25 (the server turns text into the sparse vector) ---------------------------------------
    def points(server_bm25: bool) -> list[dict]:
        return [{"id": pid(n), "payload": {"name": n, "sensitivity_level": lv, "department": d, "text": t},
                 "vector": {"dense": v, **({"bm25": {"text": t, "model": "qdrant/bm25"}} if server_bm25 else {})}}
                for n, lv, d, t, v in POINTS]

    r = c.put(f"/collections/{COLL}/points?wait=true", headers=KEY, json={"points": points(True)})
    server_bm25 = r.status_code == 200
    out(f"INFO  D4 server-side BM25 on upsert: {'AVAILABLE' if server_bm25 else 'NOT available'} "
        f"(HTTP {r.status_code}{'' if server_bm25 else ': ' + r.text[:200]})")
    if not server_bm25:
        r = c.put(f"/collections/{COLL}/points?wait=true", headers=KEY, json={"points": points(False)})
        check("upsert without bm25 (dense only)", r.status_code == 200, r.text[:120])
    r = c.post(f"/collections/{COLL}/points/count", headers=KEY, json={"exact": True})
    check("4 points stored", r.json()["result"]["count"] == 4)
    if server_bm25:  # a 200 alone does not prove the server built the sparse vector: look at it, then use it alone
        r = c.post(f"/collections/{COLL}/points", headers=KEY, json={"ids": [pid("suez")], "with_vector": ["bm25"]})
        sv = r.json()["result"][0]["vector"].get("bm25", {})
        check("stored point carries a server-built bm25 vector", len(sv.get("indices", [])) >= 5,
              f"{len(sv.get('indices', []))} terms")
        r = c.post(f"/collections/{COLL}/points/query", headers=KEY, json={
            "query": {"text": "transit dues container ships", "model": "qdrant/bm25"}, "using": "bm25",
            "limit": 1, "with_payload": True})
        top = [p["payload"]["name"] for p in r.json()["result"]["points"]]
        check("bm25-only query finds the matching text", top == ["suez"], f"top {top}")

    # --- hybrid query, RBAC filter inside BOTH prefetches, RRF fusion ---------------------------------------------
    def hybrid(flt: dict) -> list[str]:
        prefetch = [{"query": QUERY_DENSE, "using": "dense", "filter": flt, "limit": 10}]
        if server_bm25:
            prefetch.append({"query": {"text": QUERY_TEXT, "model": "qdrant/bm25"}, "using": "bm25",
                             "filter": flt, "limit": 10})
        r = c.post(f"/collections/{COLL}/points/query", headers=KEY, json={
            "prefetch": prefetch, "query": {"fusion": "rrf"}, "limit": 10, "with_payload": True})
        assert r.status_code == 200, r.text[:300]
        return [p["payload"]["name"] for p in r.json()["result"]["points"]]

    for who, flt, must, must_not in [
        ("CEO (ceiling 3)", rbac(3, "Operations"), {"net_result", "invoice"}, set()),
        ("Operations employee (ceiling 1)", rbac(1, "Operations"), {"suez", "overboard"}, {"net_result", "invoice"}),
        ("Finance employee (ceiling 1)", rbac(1, "Finance"), {"invoice"}, {"net_result"}),
        ("Finance manager (ceiling 2)", rbac(2, "Finance"), {"invoice"}, {"net_result"}),
    ]:
        got = hybrid(flt)
        ok = must <= set(got) and not (must_not & set(got))
        check(f"hybrid{' + bm25' if server_bm25 else ' (dense only)'} RRF, filter in each prefetch: {who}", ok,
              f"returned {got}")
    got = hybrid(rbac(3, "Operations"))
    check("CEO: the level-3 point ranks first for its own question", got[:1] == ["net_result"], f"top {got[:1]}")

    # --- clean up ------------------------------------------------------------------------------------------------
    r = c.delete(f"/collections/{COLL}", headers=KEY)
    check("throwaway collection deleted", r.status_code == 200)
    names = [x["name"] for x in c.get("/collections", headers=KEY).json()["result"]["collections"]]
    check("no collection left behind", COLL not in names, f"collections now {names}")

out(f"RESULT: {'ALL PASS' if not failed else 'FAILED: ' + ', '.join(failed)} | server-side BM25: "
    f"{'yes' if server_bm25 else 'no → fastembed on the client (D4)'}")
audit = ROOT / "db" / "qdrant" / "audit" / f"{dt.date.today().isoformat()}_probe.txt"
audit.parent.mkdir(parents=True, exist_ok=True)
audit.write_text("\n".join(lines) + "\n", encoding="utf-8")
sys.exit(1 if failed else 0)
