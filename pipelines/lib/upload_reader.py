"""Read an uploaded PDF or DOCX into plain lines, with file-level and hidden-text findings (RAG plan Phase 8 §a, §c).

Untrusted input, so this module only *reads*: nothing is executed, rendered, followed or stored. It runs in a child
process (`python -m pipelines.lib.upload_reader <pdf|docx>`, bytes on stdin, JSON on stdout) started by
`uploads.read_isolated` with a timeout, so a malformed file that hangs or crashes the parser takes only the child down.

Output (JSON-able dict):
- `lines`: one entry per visible line (PDF) or paragraph / table row (DOCX), in reading order:
  `{text, page, block, part ("body" | "footer" | "header"), heading_style (bool), hidden ([reasons])}`.
  `heading_style` = the line is set like a heading (PDF: every glyph bold; DOCX: a Heading style or all runs bold).
  `hidden` lists why a line is not visible to a human (render mode 3, opacity 0, < 4 pt, white text, Word "vanish").
- `file_issues`: refusal-level findings `{code, detail}` (encryption, active content, embedded files, macros, ...).
- `notes`: parts deliberately never read `{code, detail}` (comments, deleted tracked changes, text outside the page).
- `metadata_text`: document properties (PDF Info / XMP, DOCX docProps) — screened, never indexed.
- `pages`, `textless_pages` (PDF pages without any visible text, e.g. scans: no OCR at inference time).
"""
import io
import json
import re
import sys
import zipfile

MAX_PAGES = 30
MAX_UNZIPPED = 25 * 1024 * 1024   # DOCX: total uncompressed size (zip-bomb guard)
MAX_ZIP_ENTRIES = 1_000
MIN_VISIBLE_PT = 4.0
WHITE = 0xF0                       # every RGB channel >= this = white on the (white) page

# PDF dictionary keys that make a file do something when opened or clicked, or carry other files.
PDF_ACTIVE = re.compile(r"/(JavaScript|JS|Launch|EmbeddedFiles?|RichMedia|XFA|AcroForm|AA|SubmitForm|ImportData|"
                        r"GoToR|GoToE|Sound|Movie|Rendition)(?![A-Za-z0-9])")


def _issue(out: dict, code: str, detail: str) -> None:
    if {"code": code, "detail": detail} not in out["file_issues"]:
        out["file_issues"].append({"code": code, "detail": detail})


def _note(out: dict, code: str, detail: str) -> None:
    if {"code": code, "detail": detail} not in out["notes"]:
        out["notes"].append({"code": code, "detail": detail})


def _empty(fmt: str) -> dict:
    return {"format": fmt, "pages": None, "lines": [], "file_issues": [], "notes": [], "metadata_text": [],
            "textless_pages": []}


# ----------------------------------------------------------------------------------------------------------- PDF ---
def _rgb(c: int) -> tuple[int, int, int]:
    return (c >> 16) & 255, (c >> 8) & 255, c & 255


def _inside(pt: tuple[float, float], r: tuple) -> bool:
    return r[0] - 1 <= pt[0] <= r[2] + 1 and r[1] - 1 <= pt[1] <= r[3] + 1


def read_pdf(data: bytes) -> dict:
    import pymupdf

    out = _empty("pdf")
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as e:  # noqa: BLE001 — any parser error is a refusal, never a crash
        _issue(out, "E_PARSE", f"not a readable PDF ({type(e).__name__})")
        return out
    if doc.needs_pass or doc.is_encrypted:
        _issue(out, "E_ENCRYPTED", "the PDF is encrypted or password-protected")
        return out
    out["pages"] = doc.page_count
    if doc.page_count > MAX_PAGES:
        _issue(out, "E_TOO_MANY_PAGES", f"{doc.page_count} pages (limit {MAX_PAGES})")
        return out

    # Layer 1: active content anywhere in the object table (catalog, pages, annotations, name trees).
    for xref in range(1, doc.xref_length()):
        try:
            obj = doc.xref_object(xref, compressed=True)
        except Exception:  # noqa: BLE001 — a broken object is skipped, the rest is still inspected
            continue
        for m in PDF_ACTIVE.finditer(obj):
            key = m.group(1)
            code = "E_EMBEDDED_FILE" if key.startswith("EmbeddedFile") else "E_ACTIVE_CONTENT"
            _issue(out, code, f"PDF object /{key}")
    if doc.embfile_count():
        _issue(out, "E_EMBEDDED_FILE", f"{doc.embfile_count()} embedded file(s)")

    meta = doc.metadata or {}
    out["metadata_text"] = [str(v) for k, v in meta.items() if v and k not in ("format", "encryption")]
    xmp = doc.get_xml_metadata() or ""
    if xmp.strip():
        out["metadata_text"].append(re.sub(r"<[^>]+>", " ", xmp))

    block_no = 0
    for pno, page in enumerate(doc, start=1):
        for link in page.get_links():
            kind, uri = link.get("kind"), link.get("uri") or ""
            if kind == pymupdf.LINK_URI and not uri.lower().startswith("https://"):
                _issue(out, "E_ACTIVE_CONTENT", f"page {pno}: link that is not https:// ({uri[:40]})")
            elif kind in (pymupdf.LINK_LAUNCH, pymupdf.LINK_GOTOR):
                _issue(out, "E_ACTIVE_CONTENT", f"page {pno}: launch / remote link")
        if page.first_widget is not None:
            _issue(out, "E_ACTIVE_CONTENT", f"page {pno}: form field")

        # Layer 2: glyphs a human does not see. The trace sees every glyph (also off-page and invisible ones);
        # the dict below is clipped to the page, so off-page text is never read — it is only reported.
        prect = page.rect
        invisible = []
        for sp in page.get_texttrace():
            text = "".join(chr(c[0]) for c in sp.get("chars", ()) if c[0] > 32)
            if not text:
                continue
            r = pymupdf.Rect(sp["bbox"])
            if not r.intersects(prect):
                _note(out, "N_OFF_PAGE_TEXT", f"page {pno}: text outside the page box was ignored")
            elif sp.get("type") == 3 or sp.get("opacity", 1) == 0:
                invisible.append(tuple(r))

        d = page.get_text("dict", sort=True)
        page_chars = 0
        for b in d["blocks"]:
            if b.get("type") != 0:
                continue
            block_no += 1
            for ln in b["lines"]:
                spans = [s for s in ln["spans"] if s["text"].strip()]
                if not spans:
                    continue
                hidden = set()
                for s in spans:
                    centre = ((s["bbox"][0] + s["bbox"][2]) / 2, (s["bbox"][1] + s["bbox"][3]) / 2)
                    if any(_inside(centre, r) for r in invisible):
                        hidden.add("invisible")
                    if s["size"] < MIN_VISIBLE_PT:
                        hidden.add("tiny_font")
                    if min(_rgb(s["color"])) >= WHITE:
                        hidden.add("white_text")
                    if s.get("alpha", 255) == 0:
                        hidden.add("invisible")
                text = "".join(s["text"] for s in ln["spans"]).strip()
                bold = all((s["flags"] & 16) or "bold" in s["font"].lower() for s in spans)
                page_chars += len(text)
                out["lines"].append({"text": text, "page": pno, "block": block_no, "part": "body",
                                     "heading_style": bool(bold), "hidden": sorted(hidden)})
        if page_chars == 0:
            out["textless_pages"].append(pno)
    return out


# ---------------------------------------------------------------------------------------------------------- DOCX ---
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
REL_BAD = ("oleObject", "package", "control", "aFChunk", "attachedTemplate", "frame", "subDocument", "printerSettings")
FIELD_BAD = re.compile(r"\b(DDE|DDEAUTO|INCLUDETEXT|INCLUDEPICTURE|IMPORT|LINK|EMBED|MACROBUTTON|AUTOOPEN|AUTOEXEC)\b",
                       re.I)


def _on(el) -> bool:
    """A Word on/off property (<w:b/>, <w:vanish w:val="0"/>)."""
    return el is not None and el.get(W + "val", "true").lower() not in ("0", "false", "off")


def _run_hidden(rpr, hidden_styles: set[str]) -> set[str]:
    reasons = set()
    if rpr is None:
        return reasons
    if _on(rpr.find(W + "vanish")) or _on(rpr.find(W + "specVanish")) or _on(rpr.find(W + "webHidden")):
        reasons.add("hidden_property")
    col = rpr.find(W + "color")
    if col is not None and re.fullmatch(r"[0-9A-Fa-f]{6}", col.get(W + "val", "")):
        if min(_rgb(int(col.get(W + "val"), 16))) >= WHITE:
            reasons.add("white_text")
    sz = rpr.find(W + "sz")
    if sz is not None and (sz.get(W + "val") or "").isdigit() and int(sz.get(W + "val")) < MIN_VISIBLE_PT * 2:
        reasons.add("tiny_font")   # w:sz is in half-points
    st = rpr.find(W + "rStyle")
    if st is not None and st.get(W + "val") in hidden_styles:
        reasons.add("hidden_style")
    return reasons


def _paragraph(p, hidden_styles: set[str], bold_styles: set[str]) -> tuple[str, bool, set[str], bool]:
    """(text, heading_style, hidden reasons, has_deleted_text) of a <w:p>. Deleted tracked changes and comment marks
    are never read; inserted tracked changes count as text (they are what the reader sees)."""
    ppr = p.find(W + "pPr")
    pstyle = ""
    hidden = set()
    if ppr is not None:
        ps = ppr.find(W + "pStyle")
        pstyle = (ps.get(W + "val") if ps is not None else "") or ""
        if pstyle in hidden_styles:
            hidden.add("hidden_style")
        hidden |= _run_hidden(ppr.find(W + "rPr"), hidden_styles) - {"white_text", "tiny_font"}
    parts, bolds, deleted = [], [], False
    for r in p.iter(W + "r"):
        if any(True for _ in r.iter(W + "delText")):
            deleted = True
            continue
        rpr = r.find(W + "rPr")
        txt = []
        for el in r:
            if el.tag == W + "t":
                txt.append(el.text or "")
            elif el.tag == W + "tab":
                txt.append("\t")
            elif el.tag in (W + "br", W + "cr"):
                txt.append("\n")
        t = "".join(txt)
        if t.strip():
            hidden |= _run_hidden(rpr, hidden_styles)
            bolds.append(rpr is not None and _on(rpr.find(W + "b")))
        parts.append(t)
    text = "".join(parts).strip()
    heading = pstyle.lower().startswith(("heading", "titre", "berschrift")) or pstyle in bold_styles \
        or (bool(bolds) and all(bolds))
    return text, heading, hidden, deleted


def _styles(zf: zipfile.ZipFile, parse) -> tuple[set[str], set[str]]:
    """Style ids whose run properties hide text, and paragraph styles that are headings by name."""
    hidden, heading = set(), set()
    if "word/styles.xml" not in zf.namelist():
        return hidden, heading
    root = parse(zf.read("word/styles.xml"))
    for st in root.iter(W + "style"):
        sid = st.get(W + "styleId") or ""
        rpr = st.find(W + "rPr")
        if _run_hidden(rpr, set()) & {"hidden_property", "white_text", "tiny_font"}:
            hidden.add(sid)
        name = st.find(W + "name")
        if name is not None and (name.get(W + "val") or "").lower().startswith("heading"):
            heading.add(sid)
    return hidden, heading


def read_docx(data: bytes) -> dict:
    from defusedxml import ElementTree as DET  # untrusted XML: no DTDs, no entity expansion

    out = _empty("docx")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        infos = zf.infolist()
    except Exception as e:  # noqa: BLE001
        _issue(out, "E_PARSE", f"not a readable DOCX ({type(e).__name__})")
        return out
    if len(infos) > MAX_ZIP_ENTRIES or sum(i.file_size for i in infos) > MAX_UNZIPPED:
        _issue(out, "E_TOO_LARGE", "the DOCX expands beyond the limit (zip bomb guard)")
        return out
    if any(i.flag_bits & 0x1 for i in infos):
        _issue(out, "E_ENCRYPTED", "the DOCX is encrypted")
        return out
    names = set(zf.namelist())
    if "word/document.xml" not in names:
        _issue(out, "E_PARSE", "no word/document.xml: not a Word document")
        return out

    def parse(b: bytes):
        return DET.fromstring(b, forbid_dtd=True)

    # Layer 1: macros, embedded objects, ActiveX, external relationships, dangerous fields.
    try:
        ctypes = zf.read("[Content_Types].xml").decode("utf-8", "replace")
    except KeyError:
        ctypes = ""
    if "macroEnabled" in ctypes or any(n.lower().endswith("vbaproject.bin") for n in names):
        _issue(out, "E_ACTIVE_CONTENT", "macros (vbaProject)")
    for n in names:
        low = n.lower()
        if low.startswith("word/embeddings/") or low.endswith((".bin", ".exe", ".dll", ".js", ".vbs", ".ps1")) \
                and "vbaproject" not in low:
            _issue(out, "E_EMBEDDED_FILE", f"embedded object {n}")
        if low.startswith("word/activex/"):
            _issue(out, "E_ACTIVE_CONTENT", f"ActiveX control {n}")
    for n in sorted(names):
        if not n.endswith(".rels"):
            continue
        try:
            rels = parse(zf.read(n))
        except Exception:  # noqa: BLE001
            _issue(out, "E_PARSE", f"unreadable relationships {n}")
            continue
        for rel in rels:
            rtype = (rel.get("Type") or "").rsplit("/", 1)[-1]
            target, mode = rel.get("Target") or "", rel.get("TargetMode") or ""
            if rtype in REL_BAD:
                _issue(out, "E_ACTIVE_CONTENT", f"relationship {rtype}")
            elif mode == "External":
                if rtype != "hyperlink":
                    _issue(out, "E_ACTIVE_CONTENT", f"external {rtype} ({target[:40]})")
                elif not target.lower().startswith("https://"):
                    _issue(out, "E_ACTIVE_CONTENT", f"link that is not https:// ({target[:40]})")

    hidden_styles, heading_styles = _styles(zf, parse)
    for prop in ("docProps/core.xml", "docProps/app.xml", "docProps/custom.xml"):
        if prop in names:
            out["metadata_text"].append(re.sub(r"<[^>]+>", " ", zf.read(prop).decode("utf-8", "replace")))
    if "word/comments.xml" in names:
        _note(out, "N_COMMENTS_IGNORED", "comments are never read")

    block = 0

    def emit(text, part, heading, hidden):
        nonlocal block
        block += 1
        out["lines"].append({"text": text, "page": None, "block": block, "part": part,
                             "heading_style": bool(heading), "hidden": sorted(hidden)})

    def walk(container, part):
        for el in container:
            if el.tag == W + "p":
                text, heading, hidden, deleted = _paragraph(el, hidden_styles, heading_styles)
                if deleted:
                    _note(out, "N_TRACKED_DELETIONS_IGNORED", "deleted tracked changes are never read")
                if text:
                    emit(text, part, heading, hidden)
            elif el.tag == W + "tbl":
                for tr in el.iter(W + "tr"):
                    cells, hidden = [], set()
                    for tc in tr.findall(W + "tc"):
                        texts = []
                        for p in tc.iter(W + "p"):
                            t, _, h, _ = _paragraph(p, hidden_styles, heading_styles)
                            texts.append(t)
                            hidden |= h
                        cells.append(" ".join(x for x in texts if x))
                    if any(cells):
                        emit(" | ".join(cells), part, False, hidden)
            elif el.tag in (W + "sdt", W + "sdtContent", W + "customXml", W + "ins", W + "smartTag"):
                walk(el, part)

    def fields(root, where):
        for el in root.iter():
            instr = el.text if el.tag == W + "instrText" else el.get(W + "instr") if el.tag == W + "fldSimple" else None
            if instr and FIELD_BAD.search(instr):
                _issue(out, "E_ACTIVE_CONTENT", f"{where}: field {FIELD_BAD.search(instr).group(1).upper()}")
            if el.tag == W + "altChunk":
                _issue(out, "E_ACTIVE_CONTENT", f"{where}: altChunk (imported foreign content)")

    for n in sorted(names):
        m = re.fullmatch(r"word/(header|footer)\d*\.xml", n)
        if m:
            root = parse(zf.read(n))
            fields(root, n)
            walk(root, m.group(1))
    root = parse(zf.read("word/document.xml"))
    fields(root, "document")
    body = root.find(W + "body")
    if body is not None:
        walk(body, "body")
    return out


def read(data: bytes, fmt: str) -> dict:
    readers = {"pdf": read_pdf, "docx": read_docx}
    if fmt not in readers:
        raise ValueError(f"no reader for {fmt!r}")
    return readers[fmt](data)


if __name__ == "__main__":  # child-process entry: bytes on stdin, JSON on stdout
    raw = sys.stdin.buffer.read()
    sys.stdout.write(json.dumps(read(raw, sys.argv[1]), ensure_ascii=False))
