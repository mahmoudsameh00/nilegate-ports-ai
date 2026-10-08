"""The `nilegate_docs` collection: its spec, point identity, version-safe upsert and verification (ADR-039).

Qdrant detects nothing by itself: it stores what the loader sends. Change handling is therefore ours:
- point id = UUID5(document_id + "/" + chunk_id): stable across reloads (a reload overwrites, never duplicates), and
  distinct per document version (`<slug>_v2` gets its own points);
- `upsert_document` writes the new points first, then deletes every point of that document (and of the versions it
  supersedes) that is not in the new set: no stale chunk survives, and there is no moment with zero results;
- `verify_document` asserts Qdrant holds exactly the expected ids for a document.
BM25 is computed by the SERVER (`cloud_inference=True` sends the text; probe 2026-10-02 proved Qdrant 1.19.1 builds
the sparse vector), so the client never needs fastembed. Both vectors describe the delivered unit
`compose(title, text)` (ADR-041); the payload keeps `title` and `text` as separate fields.
"""
import os
import uuid

from qdrant_client import QdrantClient, models

from pipelines.lib.chunks import COLUMNS, compose, plain_value

COLLECTION = "nilegate_docs"
URL = "http://127.0.0.1:6333"
BM25_MODEL = "qdrant/bm25"
POINT_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "nilegate/rag/points")
PAYLOAD_INDEXES = {"sensitivity_level": models.PayloadSchemaType.INTEGER,
                   "department": models.PayloadSchemaType.KEYWORD,
                   "document_id": models.PayloadSchemaType.KEYWORD,
                   "document_type": models.PayloadSchemaType.KEYWORD,
                   "source": models.PayloadSchemaType.KEYWORD,
                   "real_or_synthetic": models.PayloadSchemaType.KEYWORD,
                   "unit_kind": models.PayloadSchemaType.KEYWORD,   # derived (below)
                   "year": models.PayloadSchemaType.INTEGER}        # derived (below)
UPSERT_BATCH = 128

# Derived filter fields (ADR-039 amendment, 2026-10-08). The chunk files keep each source's own `unit_type` (23
# source-specific names, e.g. "paragraph" in four sources but "paragraphs" in USCG) and `version_date` at mixed
# precision ("2025", "2024-04-06", null). Filtering needs one vocabulary and one number, so the payload adds:
#   unit_kind = UNIT_KIND[unit_type]  (an unknown unit_type stops the load: a new source must extend this map)
#   year      = the first four digits of version_date, or null
UNIT_KIND = {
    "paragraph": "paragraph", "paragraphs": "paragraph", "explanatory": "paragraph", "note": "paragraph",
    "section": "paragraph",                      # a numbered section of a NileGate company document (Phase 8)
    "numbered_group": "finding",                 # USCG numbered findings / analysis / conclusions items
    "recommendation_action": "recommendation",   # USCG recommendation + the action on it
    "incident_profile": "incident_profile",      # USCG incident coded with the IMO fields
    "vessel_block": "parties", "persons": "parties",
    "table_row": "table", "option_table": "table",
    "field_group": "form", "a4_section": "form", "form": "form", "checklist": "form",
    "clause": "clause",
    "definitions": "definitions", "glossary": "definitions",
    "figure": "figure",
    "box": "box", "iro_box": "box", "milestone": "box", "worked_example": "box",
}


def connect() -> QdrantClient:
    """Client for the local ports-qdrant container; the key comes from the environment (.env), never printed."""
    return QdrantClient(url=URL, api_key=os.environ["QDRANT_API_KEY"], cloud_inference=True, timeout=120)


def point_id(document_id: str, chunk_id: str) -> str:
    return str(uuid.uuid5(POINT_NAMESPACE, f"{document_id}/{chunk_id}"))


def payload(row: dict, document_id: str, text_sha256: str) -> dict:
    """The 16 chunk columns + document_id (ADR-009) + text_sha256 of the embedded unit (change detection, ADR-039);
    JSON-safe values (NA -> None, numpy scalars -> Python, `sub_chunk` arrays -> lists)."""
    out = {c: plain_value(row[c]) for c in COLUMNS}
    out["document_id"] = document_id
    out["text_sha256"] = text_sha256
    assert out["unit_type"] in UNIT_KIND, f"unit_type {out['unit_type']!r} has no unit_kind: extend UNIT_KIND"
    out["unit_kind"] = UNIT_KIND[out["unit_type"]]
    vd = out["version_date"]
    out["year"] = int(vd[:4]) if isinstance(vd, str) and vd[:4].isdigit() else None
    return out


def ensure_collection(client: QdrantClient, dim: int, name: str = COLLECTION) -> bool:
    """Create the collection (dense cosine + bm25 sparse with IDF, payload indexes) or check an existing one.
    Returns True when it was created."""
    if client.collection_exists(name):
        cfg = client.get_collection(name).config.params
        assert cfg.vectors["dense"].size == dim, f"{name}: dense size {cfg.vectors['dense'].size} != {dim}"
        assert cfg.vectors["dense"].distance == models.Distance.COSINE
        assert cfg.sparse_vectors["bm25"].modifier == models.Modifier.IDF
        have = set(client.get_collection(name).payload_schema)
        for field, schema in PAYLOAD_INDEXES.items():  # an index added to the spec later is created here
            if field not in have:
                client.create_payload_index(name, field_name=field, field_schema=schema, wait=True)
        return False
    client.create_collection(
        name,
        vectors_config={"dense": models.VectorParams(size=dim, distance=models.Distance.COSINE)},
        sparse_vectors_config={"bm25": models.SparseVectorParams(modifier=models.Modifier.IDF)})
    for field, schema in PAYLOAD_INDEXES.items():
        client.create_payload_index(name, field_name=field, field_schema=schema, wait=True)
    return True


def upsert_document(client: QdrantClient, document_id: str, rows: list[dict], dense: list[list[float]],
                    supersedes: tuple[str, ...] = (), name: str = COLLECTION) -> dict:
    """Write one document's points, then delete its stale points (and those of the versions it supersedes).
    `rows` are payload dicts (see `payload`), aligned with `dense`."""
    assert len(rows) == len(dense) and rows, "rows and vectors must align"
    assert all(r["document_id"] == document_id for r in rows), "every row must carry this document_id"
    ids = [point_id(document_id, r["chunk_id"]) for r in rows]
    assert len(set(ids)) == len(ids), "duplicate chunk_id within the document"
    points = [models.PointStruct(id=i, payload=r,
                                 vector={"dense": list(map(float, v)),
                                         # the delivered unit (ADR-041): identifiers such as a vessel name or a
                                         # MISLE number live in the title, and BM25 must see them
                                         "bm25": models.Document(text=compose(r["title"], r["text"]),
                                                                 model=BM25_MODEL)})
              for i, r, v in zip(ids, rows, dense)]
    for k in range(0, len(points), UPSERT_BATCH):
        client.upsert(name, points=points[k:k + UPSERT_BATCH], wait=True)
    stale = models.Filter(
        must=[models.FieldCondition(key="document_id",
                                    match=models.MatchAny(any=[document_id, *supersedes]))],
        must_not=[models.HasIdCondition(has_id=ids)])
    removed = client.count(name, count_filter=stale, exact=True).count
    if removed:
        client.delete(name, points_selector=models.FilterSelector(filter=stale), wait=True)
    return {"upserted": len(points), "stale_removed": removed}


def document_ids_in_store(client: QdrantClient, document_id: str, name: str = COLLECTION) -> set[str]:
    flt = models.Filter(must=[models.FieldCondition(key="document_id", match=models.MatchValue(value=document_id))])
    found, offset = set(), None
    while True:
        pts, offset = client.scroll(name, scroll_filter=flt, limit=512, offset=offset,
                                    with_payload=False, with_vectors=False)
        found |= {str(p.id) for p in pts}
        if offset is None:
            return found


def verify_document(client: QdrantClient, document_id: str, chunk_ids: list[str], name: str = COLLECTION) -> None:
    """Qdrant holds exactly the expected points of this document: none missing, none extra."""
    want = {point_id(document_id, c) for c in chunk_ids}
    got = document_ids_in_store(client, document_id, name)
    assert got == want, f"{document_id}: {len(want - got)} missing, {len(got - want)} extra points"
