"""Documents uploaded at inference time: the company document shape "NileGate Document v1" and its validator
(RAG plan Phase 8 §a; spec for people: docs/templates/NileGate_document_v1.md).

`validate_upload(data, filename, uploader)` takes the raw bytes of a PDF or DOCX and returns a `ValidationReport`:
- G0 hard gates (stop at the first): supported type by magic bytes, size;
- the file is read in a child process with a timeout (`read_isolated`, `upload_reader`): G1 file-level safety and
  G2 hidden-text findings come back with the lines;
- G2 shape: metadata block, field vocabularies, uploader access (ADR-006), footer, heading numbering, required sections;
- G3 screening (`screening`): control characters; injection patterns per part.
Every G1-G3 reason is collected so the employee fixes everything in one round. Owner decision Q8: a *section* with
hidden text or an injection hit is removed and reported (`removed`), the rest is accepted; a hit in a required part
(metadata block, footer, header) or a file-level threat refuses the whole file.

An accepted report carries the chunks: one logical unit per numbered section, the corpus chunk contract (16 columns,
`chunks.check`, title / text rule of ADR-041), ready to embed. Nothing is written anywhere by this module.
"""
import datetime as dt
import json
import re
import subprocess
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass, field

import pandas as pd

from pipelines.lib import chunks, screening
from pipelines.lib.common import project_root
from pipelines.lib.retrieval import User, allowed

TEMPLATE_TAG = "NILEGATE-DOC v1"
END_TAG = "END-METADATA"
MAX_BYTES = 5 * 1024 * 1024
MAX_BODY_CHARS = 60_000
PARSE_TIMEOUT_S = 30.0
MAX_CHARS = chunks.MAX_CHARS      # 2,000: the corpus safety cap
SOURCE = "NileGate"               # every company document is synthetic in this project (fictional company)

DEPT_CODES = {"OPS": "Operations", "CUS": "Customs", "FIN": "Finance", "HR": "HR", "IT": "IT"}
TYPE_CODES = {"POL": "policy", "PRC": "procedure", "CIR": "circular", "RPT": "report", "MIN": "minutes",
              "GDL": "guideline"}
FIELDS = ("document_code", "title", "document_type", "department", "sensitivity_level", "version_date", "language",
          "data_origin", "personal_data")
CODE_RE = re.compile(r"NG-(" + "|".join(DEPT_CODES) + r")-(" + "|".join(TYPE_CODES) + r")-(\d{4})")
FOOTER_RE = re.compile(r"NileGate · (\S+) · page (\S+) of (\S+) · level (\S+)")
HEADING_RE = re.compile(r"(\d{1,2}(?:\.\d{1,2}){0,2})\.?\s+(\S.{0,150})")
REQUIRED_SECTIONS = {"1": ("purpose", "الغرض"), "2": ("scope", "النطاق")}


@dataclass
class Reason:
    code: str
    where: str
    message: str


@dataclass
class ValidationReport:
    accepted: bool
    filename: str
    format: str | None = None
    document: dict | None = None          # the metadata block (+ document_id) when it parsed
    chunks: list[dict] = field(default_factory=list)
    reasons: list[Reason] = field(default_factory=list)   # refusals: any one = not accepted
    removed: list[Reason] = field(default_factory=list)   # sections removed by screening (Q8)
    notes: list[Reason] = field(default_factory=list)     # parts never read (comments, tracked deletions, ...)
    stats: dict = field(default_factory=dict)

    def codes(self) -> list[str]:
        return sorted({r.code for r in self.reasons})

    def message(self) -> str:
        """What the employee is told (English; the assistant translates)."""
        if not self.accepted:
            head = f"'{self.filename}' was not accepted ({len(self.reasons)} problem(s)):"
            return "\n".join([head] + [f"- [{r.code}] {r.where}: {r.message}" for r in self.reasons])
        lines = [f"'{self.filename}' accepted: {self.document['title']} ({self.document['document_code']}), "
                 f"{len(self.chunks)} chunks, usable in this conversation only."]
        lines += [f"- removed {r.where}: {r.message}" for r in self.removed]
        return "\n".join(lines)

    def to_json(self) -> dict:
        d = asdict(self)
        d.pop("chunks")
        d["chunk_count"] = len(self.chunks)
        return d


# ------------------------------------------------------------------------------------------------- G0 + reading ---
def sniff(data: bytes) -> str | None:
    if data[:1024].lstrip().startswith(b"%PDF-") or b"%PDF-" in data[:1024]:
        return "pdf"
    if data[:4] == b"PK\x03\x04":
        return "docx"
    return None


def read_isolated(data: bytes, fmt: str, timeout: float = PARSE_TIMEOUT_S) -> dict:
    """Run `upload_reader` in a child process: a hang is cut at `timeout`, a crash stays in the child."""
    proc = subprocess.run([sys.executable, "-s", "-m", "pipelines.lib.upload_reader", fmt], input=data,
                          capture_output=True, timeout=timeout, cwd=project_root())
    if proc.returncode != 0:
        raise RuntimeError(f"reader exited with {proc.returncode}")
    return json.loads(proc.stdout.decode("utf-8"))


# ------------------------------------------------------------------------------------------------- G2: the shape ---
def _clean(text: str) -> str:
    """Stored form of upload text: NFKC (Arabic presentation forms and ligatures back to letters), invisible / bidi
    characters removed."""
    return screening.strip_controls(unicodedata.normalize("NFKC", text))[0].strip()


def parse_metadata(lines: list[dict]) -> tuple[dict, int, list[Reason]]:
    """The key: value block between TEMPLATE_TAG and END_TAG at the start of the body. Returns (fields, index of the
    first body line after the block, reasons). A line without 'key:' continues the previous value (a wrapped title)."""
    reasons: list[Reason] = []
    if not lines or _clean(lines[0]["text"]) != TEMPLATE_TAG:
        return {}, 0, [Reason("E_NO_METADATA_BLOCK", "first line",
                              f"the document must start with '{TEMPLATE_TAG}' (use the company template)")]
    meta, last = {}, None
    for i, ln in enumerate(lines[1:], start=1):
        text = _clean(ln["text"])
        if text == END_TAG:
            break
        m = re.fullmatch(r"([a-z_]+)\s*:\s*(.*)", text)
        if m and m.group(1) in FIELDS:
            key = m.group(1)
            if key in meta:
                reasons.append(Reason("E_BAD_FIELD", key, "the field appears twice"))
            meta[key], last = m.group(2).strip(), key
        elif m:
            reasons.append(Reason("E_BAD_FIELD", m.group(1), f"unknown field (allowed: {', '.join(FIELDS)})"))
        elif last:
            meta[last] = f"{meta[last]} {text}".strip()
        else:
            reasons.append(Reason("E_NO_METADATA_BLOCK", "metadata", f"unreadable line {text[:40]!r}"))
    else:
        return meta, len(lines), reasons + [Reason("E_NO_METADATA_BLOCK", "metadata", f"no '{END_TAG}' line")]
    return meta, i + 1, reasons


def check_metadata(meta: dict, uploader: User) -> list[Reason]:
    r: list[Reason] = []
    for f in FIELDS:
        if not meta.get(f):
            r.append(Reason("E_BAD_FIELD", f, "missing"))
    code = meta.get("document_code", "")
    m = CODE_RE.fullmatch(code)
    if code and not m:
        r.append(Reason("E_BAD_FIELD", "document_code", f"{code!r} is not NG-<DEPT>-<TYPE>-<NNNN> "
                                                       f"(DEPT {'/'.join(DEPT_CODES)}, TYPE {'/'.join(TYPE_CODES)})"))
    title = meta.get("title", "")
    if title and not 10 <= len(title) <= 200:
        r.append(Reason("E_BAD_FIELD", "title", "10-200 characters"))
    if meta.get("document_type") and meta["document_type"] not in TYPE_CODES.values():
        r.append(Reason("E_BAD_FIELD", "document_type", f"one of {', '.join(TYPE_CODES.values())}"))
    if meta.get("department") and meta["department"] not in chunks.DEPARTMENTS:
        r.append(Reason("E_BAD_FIELD", "department", f"one of {', '.join(sorted(chunks.DEPARTMENTS))}"))
    if m and meta.get("department") in chunks.DEPARTMENTS and DEPT_CODES[m.group(1)] != meta["department"]:
        r.append(Reason("E_BAD_FIELD", "document_code", f"department code {m.group(1)} does not match "
                                                       f"department {meta['department']}"))
    if m and meta.get("document_type") in TYPE_CODES.values() and TYPE_CODES[m.group(2)] != meta["document_type"]:
        r.append(Reason("E_BAD_FIELD", "document_code", f"type code {m.group(2)} does not match "
                                                       f"document_type {meta['document_type']}"))
    lvl = meta.get("sensitivity_level", "")
    if lvl and lvl not in ("1", "2", "3"):
        r.append(Reason("E_BAD_FIELD", "sensitivity_level", "1, 2 or 3"))
    vd = meta.get("version_date", "")
    if vd:
        try:
            if dt.date.fromisoformat(vd) > dt.date.today() or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", vd):
                raise ValueError
        except ValueError:
            r.append(Reason("E_BAD_FIELD", "version_date", "a past or present date YYYY-MM-DD"))
    for f, allowed_values in (("language", ("en", "ar")), ("data_origin", ("public", "internal")),
                              ("personal_data", ("yes", "no"))):
        if meta.get(f) and meta[f] not in allowed_values:
            r.append(Reason("E_BAD_FIELD", f, " or ".join(allowed_values)))
    # ADR-006: the uploader must be entitled to a document of this level and department, so a session never holds a
    # label its owner could not see (and a promotion never starts from one).
    if lvl in ("1", "2", "3") and meta.get("department") in chunks.DEPARTMENTS \
            and not allowed(uploader, int(lvl), meta["department"]):
        r.append(Reason("E_LEVEL_ABOVE_UPLOADER", "sensitivity_level",
                        f"level {lvl} / {meta['department']} is above your access ({uploader.role}, "
                        f"{uploader.department})"))
    return r


def _next_ok(prev: list[int] | None, cur: list[int]) -> bool:
    """Heading numbers go 1, 1.1, 1.1.1, 1.2, 2 ...: a child (.1), the next sibling, or the next number of an
    ancestor."""
    if prev is None:
        return cur == [1]
    if cur == prev + [1] and len(cur) <= 3:
        return True
    return any(cur == prev[:k] + [prev[k] + 1] for k in range(len(prev)))


@dataclass
class Unit:
    number: str
    heading: str
    path: list[str]                 # ancestor headings incl. this one ("3 Inspection", "3.2 Pre-trip")
    paragraphs: list[str] = field(default_factory=list)
    page: int | None = None
    hidden: set = field(default_factory=set)


def build_units(body: list[dict]) -> tuple[list[Unit], list[Reason]]:
    """Body lines (after the metadata block, footers removed) -> numbered sections. A heading = a line set like a
    heading whose text is '<number> <title>'; the numbers must follow each other (no gaps, depth <= 3)."""
    reasons: list[Reason] = []
    units: list[Unit] = []
    prev_num, stack = None, {}
    cur, cur_block, para = None, None, []

    def flush_para():
        """The lines of one PDF block form a paragraph (a DOCX line already is one). A line ending in '-' before a
        lower-case continuation is a word broken at its hyphen ("pre-" + "trip"): joined without a space."""
        nonlocal para
        if para and cur is not None:
            joined = para[0]
            for nxt in para[1:]:
                joined += nxt if joined.endswith("-") and nxt[:1].islower() else f" {nxt}"
            cur.paragraphs.append(joined)
        para = []

    for ln in body:
        text = _clean(ln["text"])
        m = HEADING_RE.fullmatch(text) if ln["heading_style"] else None
        if m:
            flush_para()
            nums = [int(x) for x in m.group(1).split(".")]
            if not _next_ok(prev_num, nums):
                reasons.append(Reason("E_HEADINGS", f"heading {m.group(1)}",
                                      f"does not follow {'.'.join(map(str, prev_num)) if prev_num else 'the start'}"
                                      " (numbering 1, 1.1, 1.1.1, 1.2, 2 ...; depth <= 3)"))
            prev_num = nums
            label = f"{m.group(1)} {m.group(2).strip()}"
            stack = {k: v for k, v in stack.items() if k < len(nums)}
            stack[len(nums)] = label
            cur = Unit(m.group(1), m.group(2).strip(), [stack[k] for k in sorted(stack)], page=ln["page"])
            cur.hidden |= set(ln["hidden"])
            units.append(cur)
            cur_block = None
            continue
        if cur is None:
            reasons.append(Reason("E_HEADINGS", "before 1. Purpose", f"text before the first heading: {text[:40]!r}"))
            continue
        if ln["block"] != cur_block:
            # PDF: the layout sometimes splits one paragraph over two text blocks; a block that follows text not
            # ending a sentence continues the paragraph (DOCX lines are real paragraphs: always a new one).
            pdf_continuation = ln["page"] is not None and para and not para[-1].rstrip().endswith(
                (".", "!", "?", ":", "؟", ";"))
            if not pdf_continuation:
                flush_para()
            cur_block = ln["block"]
        para.append(text)
        cur.hidden |= set(ln["hidden"])
    flush_para()
    if not units:
        reasons.append(Reason("E_MISSING_SECTION", "body", "no numbered heading found (1. Purpose, 2. Scope, ...)"))
    for num, names in REQUIRED_SECTIONS.items():
        u = next((u for u in units if u.number == num), None)
        if u is None or u.heading.lower().strip(" :") not in names:
            reasons.append(Reason("E_MISSING_SECTION", f"section {num}",
                                  f"section {num} must be '{num}. {names[0].title()}' ('{names[1]}')"))
    return units, reasons


# -------------------------------------------------------------------------------------------------- chunk units ---
_SENT = re.compile(r"(?<=[.!?؟])\s+")


def _pack(pieces: list[str], sep: str) -> list[str]:
    out, cur = [], ""
    for p in pieces:
        if len(p) > MAX_CHARS:
            if cur:
                out.append(cur)
                cur = ""
            if sep == "\n":
                out += _pack(_SENT.split(p), " ")
            else:
                out += [p[i:i + MAX_CHARS] for i in range(0, len(p), MAX_CHARS)]
            continue
        cand = f"{cur}{sep}{p}" if cur else p
        if len(cand) > MAX_CHARS:
            out.append(cur)
            cur = p
        else:
            cur = cand
    if cur:
        out.append(cur)
    return out


def document_id(code: str) -> str:
    return code.lower().replace("-", "_")


def chunk_units(units: list[Unit], meta: dict, filename: str) -> list[dict]:
    """One chunk per section body (split at paragraph, then sentence boundaries above 2,000 characters); the title
    is the document title + the section path (ADR-041: the text never starts with its heading). A section with no
    body (a heading directly followed by its sub-heading) gives no chunk: its heading lives in the children's titles."""
    doc_id = document_id(meta["document_code"])
    rows = []
    for u in units:
        body = [p for p in u.paragraphs if p.strip()]
        if not body:
            continue
        parts = _pack(body, "\n")
        base = f"{doc_id}_s{u.number.replace('.', '_')}"
        title = f"{meta['title']} — {' › '.join(u.path)}"
        for i, text in enumerate(parts, start=1):
            rows.append({"page": u.page, "unit_type": "section", "logical_unit": base,
                         "chunk_id": base if len(parts) == 1 else f"{base}_p{i}",
                         "parent_chunk": None if len(parts) == 1 else base,
                         "sub_chunk": None, "title": title, "text": text, "char_count": len(text),
                         "filename": filename, "source": SOURCE, "real_or_synthetic": "synthetic",
                         "document_type": meta["document_type"], "department": meta["department"],
                         "sensitivity_level": int(meta["sensitivity_level"]), "version_date": meta["version_date"]})
    # a composed chunk under the contract's 50-character minimum joins the chunk before it (same document)
    merged = []
    for r in rows:
        if merged and len(chunks.compose(r["title"], r["text"])) < chunks.MIN_CHARS \
                and len(merged[-1]["text"]) + len(r["text"]) + 60 <= MAX_CHARS:
            merged[-1]["text"] += f"\n{r['title'].split(' — ', 1)[-1].split(' › ')[-1]}: {r['text']}"
            merged[-1]["char_count"] = len(merged[-1]["text"])
            continue
        merged.append(r)
    return merged


def to_frame(rows: list[dict]) -> pd.DataFrame:
    """Upload chunks as a DataFrame with the corpus dtypes, so `chunks.check` and a concat with the corpus hold."""
    df = pd.DataFrame(rows, columns=chunks.COLUMNS)
    for c in ("page", "char_count", "sensitivity_level"):
        df[c] = pd.array(df[c], dtype="Int64")
    for c in chunks.COLUMNS:
        if c not in ("page", "char_count", "sensitivity_level", "sub_chunk"):
            df[c] = df[c].astype("string")
    df["sub_chunk"] = df["sub_chunk"].astype(object)
    return df


# --------------------------------------------------------------------------------------------------- the entry ---
def validate_upload(data: bytes, filename: str, uploader: User, timeout: float = PARSE_TIMEOUT_S) -> ValidationReport:
    t0 = time.perf_counter()
    name = re.sub(r"[^\w.\- ]", "_", filename)[:120] or "upload"
    rep = ValidationReport(False, name)
    # G0: hard gates, one reason, stop.
    fmt = sniff(data)
    if fmt is None:
        rep.reasons.append(Reason("E_NOT_SUPPORTED", "file", "only PDF and DOCX made from the company template"))
        return rep
    rep.format = fmt
    if len(data) > MAX_BYTES:
        rep.reasons.append(Reason("E_TOO_LARGE", "file", f"{len(data) / 2**20:.1f} MB (limit {MAX_BYTES // 2**20} MB)"))
        return rep
    try:
        doc = read_isolated(data, fmt, timeout)
    except subprocess.TimeoutExpired:
        rep.reasons.append(Reason("E_PARSE_TIMEOUT", "file", f"reading took over {timeout:.0f} s"))
        return rep
    except Exception as e:  # noqa: BLE001 — a crashed reader is a refusal
        rep.reasons.append(Reason("E_PARSE", "file", f"the file could not be read ({type(e).__name__})"))
        return rep
    t_read = time.perf_counter()
    rep.stats["pages"] = doc["pages"]

    # G1: file-level findings refuse the whole file (no section to remove).
    rep.reasons += [Reason(i["code"], "file", i["detail"]) for i in doc["file_issues"]]
    rep.notes += [Reason(n["code"], "file", n["detail"]) for n in doc["notes"]]
    if any(r.code in ("E_PARSE", "E_ENCRYPTED", "E_TOO_MANY_PAGES", "E_TOO_LARGE") for r in rep.reasons):
        return rep
    if doc["textless_pages"]:
        rep.reasons.append(Reason("E_NO_TEXT_LAYER", f"pages {doc['textless_pages']}",
                                  "no text on the page (a scan?): export the document from the template"))

    # G3a: invisible / bidi characters over the limit (smuggling) refuse; below it they are just removed.
    n_ctrl = sum(screening.strip_controls(ln["text"])[1] for ln in doc["lines"])
    if n_ctrl > screening.CONTROL_LIMIT:
        rep.reasons.append(Reason("E_CONTROL_CHARS", "text", f"{n_ctrl} invisible / direction-control characters"))

    body = [ln for ln in doc["lines"] if ln["part"] == "body"]
    footers = [ln for ln in doc["lines"] if ln["part"] == "footer"]
    headers = [ln for ln in doc["lines"] if ln["part"] == "header"]
    if fmt == "pdf":  # PDF footers are ordinary lines: recognised by the exact template pattern
        footers = [ln for ln in body if FOOTER_RE.fullmatch(_clean(ln["text"]))]
        body = [ln for ln in body if not FOOTER_RE.fullmatch(_clean(ln["text"]))]

    # G2: metadata block + the uploader's access
    meta, start, r = parse_metadata(body)
    rep.reasons += r
    meta_lines = body[:start]
    if meta:
        rep.reasons += check_metadata(meta, uploader)
    for ln in meta_lines:
        if ln["hidden"]:
            rep.reasons.append(Reason("E_HIDDEN_TEXT", "metadata block", f"hidden text ({', '.join(ln['hidden'])})"))
        for h in screening.screen_text(ln["text"]):
            rep.reasons.append(Reason("E_INJECTION", "metadata block", f"{h.pattern}: {h.excerpt!r}"))

    # G2: footer on every page (PDF) / in the footer part (DOCX), equal to the metadata block
    code, lvl = meta.get("document_code"), meta.get("sensitivity_level")
    parsed = [FOOTER_RE.fullmatch(_clean(ln["text"])) for ln in footers]
    if fmt == "pdf" and doc["pages"]:
        pages_with = {ln["page"] for ln, m in zip(footers, parsed) if m}
        missing = sorted(set(range(1, doc["pages"] + 1)) - pages_with)
        if missing:
            rep.reasons.append(Reason("E_FOOTER_MISMATCH", f"pages {missing}", "no 'NileGate · <code> · page N of M "
                                                                              "· level L' footer"))
        for ln, m in zip(footers, parsed):
            if m and (m.group(2) != str(ln["page"]) or m.group(3) != str(doc["pages"])):
                rep.reasons.append(Reason("E_FOOTER_MISMATCH", f"page {ln['page']}", "wrong page numbers in the footer"))
    elif fmt == "docx" and not any(parsed):
        rep.reasons.append(Reason("E_FOOTER_MISMATCH", "footer", "no 'NileGate · <code> · page N of M · level L' "
                                                                 "footer"))
    for ln, m in zip(footers, parsed):
        if m and code and lvl and (m.group(1) != code or m.group(4) != lvl):
            rep.reasons.append(Reason("E_FOOTER_MISMATCH", f"page {ln['page'] or 'footer'}",
                                      f"footer says {m.group(1)} / level {m.group(4)}, the metadata block says "
                                      f"{code} / level {lvl} (a page from another document?)"))
            break
    for ln in footers + headers:  # required / fixed parts: a hit refuses
        if ln["hidden"]:
            rep.reasons.append(Reason("E_HIDDEN_TEXT", ln["part"], f"hidden text ({', '.join(ln['hidden'])})"))
        for h in screening.screen_text(ln["text"]):
            rep.reasons.append(Reason("E_INJECTION", ln["part"], f"{h.pattern}: {h.excerpt!r}"))
    for t in doc["metadata_text"]:  # document properties: never indexed, so only a note
        for h in screening.screen_text(t):
            rep.notes.append(Reason("N_PROPERTIES_IGNORED", "document properties",
                                    f"injection-like text in the file properties was ignored ({h.pattern})"))
            break

    # G2: sections; G3b: hidden text or injection inside a section removes that section (Q8). Without a metadata
    # block the shape is unknown: the sections are not judged (one clear reason instead of one per line).
    if not meta:
        return rep
    units, r = build_units(body[start:])
    rep.reasons += r
    if sum(len(p) for u in units for p in u.paragraphs) > MAX_BODY_CHARS:
        rep.reasons.append(Reason("E_TOO_LONG", "body", f"over {MAX_BODY_CHARS:,} characters"))
    kept = []
    for u in units:
        where = f"section {u.number} '{u.heading[:40]}'"
        hits = screening.screen_text("\n".join([u.heading, *u.paragraphs]))
        if u.hidden:
            rep.removed.append(Reason("W_SECTION_REMOVED", where, f"hidden text ({', '.join(sorted(u.hidden))})"))
        elif hits:
            rep.removed.append(Reason("W_SECTION_REMOVED", where, "instruction-like text "
                                      f"({', '.join(sorted({h.pattern for h in hits}))}): {hits[0].excerpt!r}"))
        else:
            kept.append(u)
    if units and not kept:
        rep.reasons.append(Reason("E_NOTHING_LEFT", "body", "every section was removed by the screening"))

    rep.stats.update({"units": len(units), "units_kept": len(kept), "read_ms": round((t_read - t0) * 1000, 1)})
    if rep.reasons:
        return rep
    meta = {**meta, "document_id": document_id(meta["document_code"])}
    rows = chunk_units(kept, meta, name)
    if not rows:
        rep.reasons.append(Reason("E_NOTHING_LEFT", "body", "the sections have no text"))
        return rep
    chunks.check(to_frame(rows))  # the corpus contract, as for every chunk file
    rep.accepted, rep.document, rep.chunks = True, meta, rows
    rep.stats.update({"chunks": len(rows), "total_ms": round((time.perf_counter() - t0) * 1000, 1)})
    return rep
