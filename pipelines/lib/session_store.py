"""Conversation-only uploads (RAG plan Phase 8 §b, §e; owner decisions D12-D14, Q1-Q8).

`SessionStore` keeps each conversation's accepted uploads **in process memory only**: chunk rows + local vectors,
owned by one employee, gone when the session closes or expires (TTL). Nothing is written to disk, Qdrant, PostgreSQL
or the query cache. One embedding path for every session upload: the local ONNX model (`local_embeddings`): no
non-public text leaves the machine (ADR-037), no Gemini quota is spent, one vector space, one score floor.

`Session.search` is the **session lane** of `search_documents` (`retrieval.Retriever.search(..., session=...)`):
cosine over the session's chunks, a calibrated floor, at most `k` results, each labelled
`trust="untrusted_upload"` — upload text is data for the answer, never instructions (project rule 5).

A manager may ask to promote an accepted upload of their own department to the corpus (`request_promotion`): only
then is the original file persisted, to `Data/incoming/promotion/<request_id>/` (git-ignored), for the owner's
offline review (`pipelines/scripts/retrieval/Upload_promotion.py`). Nothing is promoted automatically.
"""
import datetime as dt
import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field

import numpy as np

from pipelines.lib import local_embeddings, qdrant_store, uploads
from pipelines.lib.common import project_root
from pipelines.lib.retrieval import FILTER_KEYS, User, allowed

# Owner's choice (Q1) was llama2-embedding-600m-8k; measured by Upload_eval.py (2026-10-08) it misses both thresholds
# (hit@3 en 0.767 / ar 0.167); multilingual-e5-base misses the Arabic one (0.933 / 0.500). BAAI/bge-m3, measured after
# the project moved to D: (disk space), meets both (1.000 / 1.000): the rule's choice. See the plan, Phase 8.
LOCAL_MODEL = "bge-m3"
SESSION_FLOOR = 0.0                         # fallback; the calibrated floor per model is in FLOORS (Upload_eval M2)
# M2: the floor keeps upload chunks out of >= 80 % of the golden corpus questions (owner decision 2026-10-08; the first
# rule, 95 %, gave 0.52 and hid relevant Arabic hits: hit@3 ar 0.733). bge-m3 at 0.45: hit@3 en 1.000 / ar 0.900, 9 of
# 64 golden questions also get upload chunks — in the separate, labelled session list, never in the corpus results.
FLOORS: dict[str, float] = {"bge-m3": 0.45}
SESSION_K = 3
TTL_S = 8 * 3600
MAX_UPLOADS = 5
MAX_CHUNKS = 300
PROMOTION_DIR = project_root() / "Data" / "incoming" / "promotion"
PROMOTING_ROLES = ("manager",)              # D12: a manager, for their own department (Q3)


class SessionExpired(LookupError):
    pass


@dataclass
class SessionUpload:
    document: dict
    rows: list[dict]
    vectors: np.ndarray
    model: str
    removed: list
    uploaded_at: float
    sha256: str
    filename: str
    original: bytes | None = None   # kept in memory only for a manager's upload (a promotion needs the file)


@dataclass
class Session:
    session_id: str
    employee_id: int
    created: float
    expires_at: float
    store: "SessionStore" = field(repr=False)
    uploads: dict[str, SessionUpload] = field(default_factory=dict)

    def expired(self, now: float | None = None) -> bool:
        return (now or self.store.clock()) >= self.expires_at or self.session_id not in self.store.sessions

    def chunk_count(self) -> int:
        return sum(len(u.rows) for u in self.uploads.values())

    # --- the session lane ----------------------------------------------------------------------------------------
    def search(self, query: str, user: User, filters: dict | None = None, k: int = SESSION_K) -> tuple[list, dict]:
        """(results, info). The question is embedded locally (never expanded with upload text: Q2)."""
        info = {"uploads": len(self.uploads), "chunks": self.chunk_count(), "floor": self.store.floor, "embed_ms": 0.0}
        if user.employee_id != self.employee_id:
            raise PermissionError(f"session {self.session_id} belongs to another employee")
        if self.expired():
            info["expired"] = True
            return [], info
        if not self.uploads:
            return [], info
        unknown = set(filters or {}) - FILTER_KEYS
        if unknown:
            raise ValueError(f"unknown filter keys {sorted(unknown)}")
        t0 = time.perf_counter()
        qv = self.store.embedder.embed([query], "query")[0]
        info["embed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        cands = []
        for up in self.uploads.values():
            scores = up.vectors @ qv
            for row, s in zip(up.rows, scores):
                if s < self.store.floor or not _matches(row, up.document["document_id"], filters):
                    continue
                if not allowed(user, row["sensitivity_level"], row["department"]):  # defence in depth
                    raise PermissionError(f"RBAC violation in session lane: {row['chunk_id']}")
                cands.append((float(s), up, row))
        cands.sort(key=lambda c: -c[0])
        out = []
        for s, up, row in cands[:k]:
            out.append({"rank": len(out) + 1, "score": s, "chunk_id": row["chunk_id"],
                        "document_id": up.document["document_id"], "title": row["title"], "text": row["text"],
                        "sensitivity_level": row["sensitivity_level"], "department": row["department"],
                        "unit_kind": qdrant_store.UNIT_KIND[row["unit_type"]], "year": _year(row),
                        "source": row["source"], "lane": "session", "trust": "untrusted_upload",
                        "uploaded_by": self.employee_id, "document_code": up.document["document_code"],
                        "citation": {"filename": row["filename"], "page": row["page"], "title": row["title"],
                                     "upload": True}})
        return out, info


def _year(row: dict) -> int | None:
    vd = row.get("version_date")
    return int(vd[:4]) if isinstance(vd, str) and vd[:4].isdigit() else None


def _matches(row: dict, document_id: str, filters: dict | None) -> bool:
    """The metadata filters of `search_documents`, applied to a session chunk (same meaning as in Qdrant)."""
    if not filters:
        return True
    derived = {**row, "unit_kind": qdrant_store.UNIT_KIND[row["unit_type"]], "document_id": document_id}
    for key in ("document_type", "source", "document_id", "department", "unit_kind"):
        if key in filters:
            vals = [filters[key]] if isinstance(filters[key], str) else list(filters[key])
            if derived[key] not in vals:
                return False
    y = _year(row)
    if ("year_from" in filters or "year_to" in filters) and y is None:
        return False
    if "year_from" in filters and filters["year_from"] is not None and y < filters["year_from"]:
        return False
    if "year_to" in filters and filters["year_to"] is not None and y > filters["year_to"]:
        return False
    return True


class SessionStore:
    def __init__(self, model: str = LOCAL_MODEL, ttl_s: float = TTL_S, max_uploads: int = MAX_UPLOADS,
                 max_chunks: int = MAX_CHUNKS, floor: float | None = None, clock=time.time, **embed_settings):
        self.model = model
        self.embedder = local_embeddings.get(model, **embed_settings)
        self.floor = FLOORS.get(model, SESSION_FLOOR) if floor is None else floor
        self.ttl_s, self.max_uploads, self.max_chunks, self.clock = ttl_s, max_uploads, max_chunks, clock
        self.sessions: dict[str, Session] = {}

    # --- lifecycle -------------------------------------------------------------------------------------------------
    def open(self, employee_id: int) -> Session:
        self.sweep()
        now = self.clock()
        s = Session(uuid.uuid4().hex, employee_id, now, now + self.ttl_s, self)
        self.sessions[s.session_id] = s
        return s

    def get(self, session_id: str, employee_id: int) -> Session:
        self.sweep()
        s = self.sessions.get(session_id)
        if s is None:
            raise SessionExpired(f"session {session_id} is closed or expired")
        if s.employee_id != employee_id:
            raise PermissionError(f"session {session_id} belongs to another employee")
        return s

    def close(self, session_id: str) -> None:
        s = self.sessions.pop(session_id, None)
        if s is not None:
            s.uploads.clear()   # drop rows, vectors and any kept original right away

    def sweep(self) -> int:
        now = self.clock()
        gone = [sid for sid, s in self.sessions.items() if now >= s.expires_at]
        for sid in gone:
            self.close(sid)
        return len(gone)

    # --- upload ----------------------------------------------------------------------------------------------------
    def add_upload(self, session: Session, data: bytes, filename: str, uploader: User,
                   timeout: float = uploads.PARSE_TIMEOUT_S) -> uploads.ValidationReport:
        """Validate → chunk → embed locally → keep in the session. The report says what the employee is told."""
        if uploader.employee_id != session.employee_id:
            raise PermissionError("an upload belongs to the session owner")
        if session.expired():
            raise SessionExpired(f"session {session.session_id} is closed or expired")
        rep = uploads.validate_upload(data, filename, uploader, timeout)
        if not rep.accepted:
            return rep
        doc_id = rep.document["document_id"]
        replacing = doc_id in session.uploads
        n_up = len(session.uploads) - replacing
        n_ch = session.chunk_count() - (len(session.uploads[doc_id].rows) if replacing else 0)
        if n_up >= self.max_uploads or n_ch + len(rep.chunks) > self.max_chunks:
            rep.accepted = False
            rep.reasons.append(uploads.Reason("E_SESSION_FULL", "session",
                                              f"at most {self.max_uploads} documents / {self.max_chunks} chunks per "
                                              "conversation: start a new conversation or remove a document"))
            return rep
        t0 = time.perf_counter()
        vecs = self.embedder.embed([uploads.chunks.compose(r["title"], r["text"]) for r in rep.chunks], "passage")
        rep.stats["embed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        rep.stats["model"] = self.model
        if replacing:
            rep.notes.append(uploads.Reason("N_REPLACED", doc_id, "an earlier upload of this document in this "
                                                                  "conversation was replaced"))
        session.uploads[doc_id] = SessionUpload(
            rep.document, rep.chunks, vecs, self.model, list(rep.removed), self.clock(),
            hashlib.sha256(data).hexdigest(), rep.filename,
            original=data if uploader.role in PROMOTING_ROLES else None)
        return rep

    def remove_upload(self, session: Session, document_id: str) -> bool:
        return session.uploads.pop(document_id, None) is not None

    # --- promotion request (D12: manager, own department, explicit; Q3, Q5, Q8) ------------------------------------
    def request_promotion(self, session: Session, document_id: str, requester: User, note: str = "",
                          root=None) -> dict:
        """Persist the original file + request.json for the owner's offline review (`Upload_promotion.py`). `root`
        defaults to PROMOTION_DIR (a self-test passes its own scratch folder)."""
        if requester.employee_id != session.employee_id:
            raise PermissionError("only the uploader can ask to promote an upload")
        up = session.uploads.get(document_id)
        problems = []
        if up is None:
            problems.append("no such upload in this conversation")
        else:
            if requester.role not in PROMOTING_ROLES:
                problems.append(f"only a {' / '.join(PROMOTING_ROLES)} can ask to add a document to the corpus")
            if up.document["department"] != requester.department:
                problems.append(f"the document belongs to {up.document['department']}, your department is "
                                f"{requester.department}")
            if up.removed:
                problems.append(f"{len(up.removed)} section(s) were removed by the screening: fix the source "
                                "document and upload it again")
            if up.original is None:
                problems.append("the original file was not kept")
        if problems:
            return {"accepted": False, "problems": problems}
        rid = f"{dt.datetime.now():%Y%m%d_%H%M%S}_{document_id}_{uuid.uuid4().hex[:6]}"
        folder = (root or PROMOTION_DIR) / rid
        folder.mkdir(parents=True, exist_ok=False)
        (folder / up.filename).write_bytes(up.original)
        request = {"request_id": rid, "status": "requested", "requested_at": dt.datetime.now().isoformat(timespec="seconds"),
                   "requested_by": {"employee_id": requester.employee_id, "role": requester.role,
                                    "department": requester.department},
                   "filename": up.filename, "sha256": up.sha256, "document": up.document,
                   "chunk_count": len(up.rows), "note": note[:500]}
        (folder / "request.json").write_text(json.dumps(request, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"accepted": True, "request_id": rid, "folder": folder}
