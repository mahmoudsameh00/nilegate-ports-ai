"""Convert the project notebooks into scripts without changing what the code does (plan: Scripts_and_ingestion_plan.md).

  uv run python tools/nb_to_script.py convert [STEM ...]   write pipelines/scripts/<area>/<stem>.py
                                                            + pipelines/checkpoints/<area>/<stem>.md
  uv run python tools/nb_to_script.py check   [STEM ...]   static proof that every script matches its notebook

The script is in percent format (`# %% cell N` = code cell N of the notebook, `# %% [markdown] cell N` = markdown
cell N as `# ` comment lines), so `uv run python <script>` runs it top to bottom and VS Code still shows the cells.
Every code cell is copied byte for byte, except these listed changes (plan §2 A2):
  1. `from IPython.display import display` in the header when the script calls display();
  2. a cell whose last statement is a bare expression gets it wrapped in `_display_result(...)`: Jupyter showed that
     value (unless None), a script would drop it silently;
  3. an IPython `%pip` line is turned into a comment (dependencies come from uv, the project rules rule 6).
The Final Checkpoint markdown cell moves, unchanged, to the companion .md; the script keeps a pointer at its place.
Empty cells are skipped. `check` rebuilds each notebook cell from the script, undoes the listed changes and asserts
equality with the notebook (code, markdown, Final Checkpoint text), then compiles the script.
"""
import argparse
import ast
import json
import py_compile
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NB_DIR = ROOT / "Notebooks"
SCRIPTS = ROOT / "pipelines" / "scripts"
CHECKPOINTS = ROOT / "pipelines" / "checkpoints"
FC_RE = re.compile(r"final checkpoint", re.I)
WRAP = "_display_result("
WRAP_T = "_display_tuple("       # a bare tuple `a, b`: wrapping it in _display_result( would pass two arguments
DISABLED_TAG = "# DISABLED by the owner (2026-10-01): "
DISABLED_PREFIX = "#! "
# Cells the owner asked to disable (kept as comments, restorable): {notebook key: {cell index: reason}}
DISABLED = {
    "structured/ExtractPortsConnection": {
        21: "the INSERT into port_connections must not run again (completed table, the project rules rule 2); "
            "kept as the record of how the table was loaded",
    },
}

# What a reader needs before running a script (no outputs are visible in a script). Paths relative to the project root.
META = {
    "rag/FBL_chunking": dict(
        reads="Data/raw/unstructured/FBL_template.pdf",
        writes="Data/processed/rag/extracted|cleaned|chunks/ (the FBL files)",
        rerun="safe: rewrites the same three artifacts"),
    "rag/LPI_methodology_chunking": dict(
        reads="Data/raw/unstructured/LPI_Methodology.pdf",
        writes="Data/processed/rag/extracted|cleaned|chunks/ (the LPI Methodology files)",
        rerun="safe: rewrites the same three artifacts"),
    "rag/Suez_Notes_chunking": dict(
        reads="Data/raw/unstructured/Transit_Dues_Rates.pdf",
        writes="Data/processed/rag/extracted|cleaned|chunks/ (the Suez Notes files)",
        rerun="safe: rewrites the same three artifacts"),
    "rag/LPI_Connecting_to_Compete_chunking": dict(
        reads="Data/raw/unstructured/LPI.pdf; Data/processed/rag/cleaned/LPI_Methodology_logical_units.json (dedup)",
        writes="Data/processed/rag/extracted|cleaned|chunks/ (the LPI Connecting to Compete files); "
               "review aids in Notebooks/_scratch/ (git-ignored)",
        rerun="safe: rewrites the same three artifacts; run after LPI_methodology_chunking"),
    "rag/HbR_Annual_report_2025_chunking": dict(
        reads="Data/raw/unstructured/HbR_Annual_report_2025_highlights.pdf",
        writes="Data/processed/rag/extracted|cleaned|chunks/ (the HbR files); review aids in Notebooks/_scratch/ "
               "(git-ignored)",
        rerun="safe: rewrites the same three artifacts"),
    "rag/IMO_MSC-MEPC_3_Circ_4_Rev_1_chunking": dict(
        reads="Data/raw/unstructured/MSC-MEPC_3-Circ_4-Rev_1.pdf",
        writes="Data/processed/rag/extracted|cleaned|chunks/ (the IMO circular files, incl. the field catalogue); "
               "review aids in Notebooks/_scratch/ (git-ignored)",
        rerun="safe: rewrites the same three artifacts"),
    "rag/USCG_ROI_chunking": dict(
        reads="Data/raw/unstructured/us_coast_guard_reports/*.pdf (23); "
              "Data/processed/rag/extracted/ (the IMO field catalogue)",
        writes="Data/processed/rag/extracted|cleaned|chunks/ (the USCG ROI files); "
               "Data/processed/rag/ocr_cache/USCG_ROI/ (one JSON per OCR'd page, reused when present); "
               "review aids in Notebooks/_scratch/ (git-ignored)",
        rerun="safe: rewrites the same artifacts; OCR runs only for pages missing from the cache"),
    "rag/Documents_registry": dict(
        reads="Data/raw/unstructured/ (the 29 PDFs); Data/processed/rag/chunks/; PostgreSQL (read-only session)",
        writes="Data/processed/rag/documents.csv; db/migrations/010_fill_documents.sql (regenerated identical; "
               "already applied, never re-applied)",
        rerun="safe: read-only on the database; rewrites the same two files"),
    "semi_structured/AIS_EDI_profiling": dict(
        reads="Data/raw/semi-structured/ (AISHub sample, NOAA AccessAIS, IFTMIN sample)",
        writes="Data/processed/semi-structured/profiles/",
        rerun="safe: rewrites the same profiles"),
    "semi_structured/AIS_generator": dict(
        reads="Data/processed/semi-structured/profiles/; PostgreSQL (vessels, ports)",
        writes="Data/processed/semi-structured/synthetic/ (AIS parquet files + ais_generation_manifest.json)",
        rerun="safe: fixed seed, rewrites the same files"),
    "semi_structured/EDI_generator": dict(
        reads="Data/processed/semi-structured/profiles/; PostgreSQL",
        writes="Data/processed/semi-structured/synthetic/ (edi_messages_synthetic.jsonl + edi_generation_manifest.json)",
        rerun="safe: fixed seed, rewrites the same files"),
    "semi_structured/MongoDB_loader": dict(
        reads="Data/raw/semi-structured/; Data/processed/semi-structured/; PostgreSQL",
        writes="MongoDB ports_logistics: drops and reloads ais_positions, ais_vessels, edi_messages (ADR-031, the only "
               "MongoDB writer); a new timestamped report in Data/processed/semi-structured/load_audit/ per run",
        rerun="idempotent (same documents after every run); each run adds one new load report"),
    "synthetic/SyntheticGenerator": dict(
        reads="Data/processed/structured/ports.csv; Data/processed/synthetic/*.csv",
        writes="nothing when the CSVs exist: save_or_verify() compares and never overwrites with different data",
        rerun="safe (verification run)"),
    "structured/ExtractPortsAttributes": dict(
        reads="Data/raw/structured/attributed_ports.geojson",
        writes="Data/processed/structured/ports.csv",
        rerun="safe: rewrites the same CSV"),
    "structured/ExtractPortsConnection": dict(
        reads="Data/raw/structured/Port_flows/ (shapefile); PostgreSQL (ports, read only)",
        writes="Data/processed/structured/port_connections.csv. The INSERT into port_connections (cell 21) is "
               "DISABLED (commented out, owner 2026-10-01): the table is complete (the project rules rule 2)",
        rerun="safe: the database write is disabled; rewrites the same CSV"),
}


def src(cell: dict) -> str:
    s = cell.get("source", "")
    return "".join(s) if isinstance(s, list) else s


def notebook_path(key: str) -> Path:
    return NB_DIR / f"{key}.ipynb"


def fc_index(cells: list[dict]) -> int | None:
    """The closing Final Checkpoint narrative: the last markdown cell that names it and has more than a heading."""
    idx = [i for i, c in enumerate(cells) if c["cell_type"] == "markdown" and FC_RE.search(src(c))
           and len([l for l in src(c).splitlines() if l.strip()]) > 1]
    return idx[-1] if idx else None


def bare_expression(code: str) -> ast.Expr | None:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    if not tree.body or not isinstance(tree.body[-1], ast.Expr):
        return None
    v = tree.body[-1].value
    if isinstance(v, ast.Call) and isinstance(v.func, ast.Name) and v.func.id in ("print", "display"):
        return None
    if code.rstrip().endswith(";"):          # Jupyter shows nothing for a trailing semicolon
        return None
    return tree.body[-1]


def transform(code: str, disabled: str | None = None) -> tuple[str, list[str]]:
    """Return the script version of a code cell and the list of changes made (empty = byte-identical)."""
    changes = []
    lines = code.split("\n")
    if disabled:
        return "\n".join([DISABLED_TAG + disabled] + [DISABLED_PREFIX + l for l in lines]), ["disabled"]
    try:
        ast.parse(code)
        magic = []                                       # valid Python: `%s` inside a SQL string is not a magic
    except SyntaxError:
        magic = [i for i, l in enumerate(lines) if re.match(r"%\w", l)]
    if magic:
        for i in magic:
            lines[i] = f"# IPython magic removed (dependencies come from uv, the project rules rule 6): {lines[i].strip()}"
        changes.append("magic")
        return "\n".join(lines), changes
    node = bare_expression(code)
    if node is not None:
        s, e = node.lineno - 1, node.end_lineno - 1
        bare_tuple = isinstance(node.value, ast.Tuple) and not lines[s][node.col_offset:].startswith("(")
        lines[e] = lines[e][:node.end_col_offset] + ")" + lines[e][node.end_col_offset:]
        lines[s] = lines[s][:node.col_offset] + (WRAP_T if bare_tuple else WRAP) + lines[s][node.col_offset:]
        changes.append("wrap_tuple" if bare_tuple else "wrap")
    return "\n".join(lines), changes


def untransform(code: str) -> str:
    lines = code.split("\n")
    if lines and lines[0].startswith(DISABLED_TAG):
        assert all(l.startswith(DISABLED_PREFIX) for l in lines[1:])
        return "\n".join(l[len(DISABLED_PREFIX):] for l in lines[1:])
    if any(l.startswith("# IPython magic removed") for l in lines):
        return "\n".join(l.split(": ", 1)[1] if l.startswith("# IPython magic removed") else l for l in lines)
    tree = ast.parse(code)
    last = tree.body[-1] if tree.body else None
    if (isinstance(last, ast.Expr) and isinstance(last.value, ast.Call) and isinstance(last.value.func, ast.Name)
            and last.value.func.id in (WRAP[:-1], WRAP_T[:-1])):
        node, w = last, WRAP if last.value.func.id == WRAP[:-1] else WRAP_T
        s, e = node.lineno - 1, node.end_lineno - 1
        assert lines[e][node.end_col_offset - 1] == ")"
        lines[e] = lines[e][:node.end_col_offset - 1] + lines[e][node.end_col_offset:]
        assert lines[s][node.col_offset:].startswith(w)
        lines[s] = lines[s][:node.col_offset] + lines[s][node.col_offset + len(w):]
    return "\n".join(lines)


def md_comment(text: str) -> str:
    return "\n".join(f"# {l}" if l else "#" for l in text.split("\n"))


def title_of(cells: list[dict], stem: str) -> str:
    for c in cells:
        if c["cell_type"] == "markdown":
            for l in src(c).splitlines():
                if l.startswith("#"):
                    return l.lstrip("# ").strip()
    return stem


def build(key: str) -> tuple[str, str | None, dict]:
    area, stem = key.split("/")
    cells = json.loads(notebook_path(key).read_text(encoding="utf-8"))["cells"]
    fc = fc_index(cells)
    md_rel = f"pipelines/checkpoints/{area}/{stem}.md"
    body, stats = [], {"code": 0, "markdown": 0, "skipped_empty": 0, "wrap": 0, "wrap_tuple": 0, "magic": 0, "disabled": 0,
                     "fc": fc}
    for i, c in enumerate(cells):
        text = src(c)
        if not text.strip():
            stats["skipped_empty"] += 1
            continue
        assert not re.search(r"^# %%", text, re.M), f"{key} cell {i} contains a cell marker"
        if c["cell_type"] == "markdown":
            stats["markdown"] += 1
            if i == fc:
                body.append(f"# %% [markdown] cell {i}\n# Final Checkpoint: see {md_rel}")
            else:
                body.append(f"# %% [markdown] cell {i}\n{md_comment(text.rstrip(chr(10)))}")
        elif c["cell_type"] == "code":
            stats["code"] += 1
            new, ch = transform(text, DISABLED.get(key, {}).get(i))
            for k in ch:
                stats[k] += 1
            body.append(f"# %% cell {i}\n{new.rstrip(chr(10))}")
    code_all = "\n\n".join(body)
    m = META[key]
    head = [
        f'"""{title_of(cells, stem)}',
        "",
        f"Converted from Notebooks/{key}.ipynb (2026-10-01) by tools/nb_to_script.py: same cells, same order; "
        "`# %% cell N` = notebook cell N.",
        "Run from the project root: " f"uv run python tools/run.py pipelines/scripts/{area}/{stem}.py",
        "",
        f"Reads:   {m['reads']}",
        f"Writes:  {m['writes']}",
        f"Re-run:  {m['rerun']}",
    ]
    if fc is not None:
        head.append(f"Final Checkpoint (what was done, problems, fixes): {md_rel}")
    head.append('"""')
    if re.search(r"\bdisplay\(", code_all) or stats["wrap"] or stats["wrap_tuple"]:
        head.append("from IPython.display import display  # outside Jupyter it prints the value (added by the conversion)")
    if stats["wrap"]:
        head += [
            "",
            "",
            "def _display_result(value):",
            '    """A notebook shows the value of a cell\'s last expression unless it is None (added by the conversion)."""',
            "    if value is not None:",
            "        display(value)",
        ]
    if stats["wrap_tuple"]:
        head += [
            "",
            "",
            "def _display_tuple(*values):",
            '    """A notebook cell ending in `a, b` shows the tuple (a, b) (added by the conversion)."""',
            "    display(values)",
        ]
    script = "\n".join(head) + "\n\n" + code_all + "\n"
    md = src(cells[fc]).rstrip("\n") + "\n" if fc is not None else None
    return script, md, stats


def paths(key: str) -> tuple[Path, Path]:
    area, stem = key.split("/")
    return SCRIPTS / area / f"{stem}.py", CHECKPOINTS / area / f"{stem}.md"


def keys(stems: list[str]) -> list[str]:
    allk = sorted(META)
    found = sorted(p.relative_to(NB_DIR).with_suffix("").as_posix() for p in NB_DIR.glob("*/*.ipynb"))
    assert found == allk, f"notebooks and META differ: {set(found) ^ set(allk)}"
    return [k for k in allk if not stems or k.split("/")[1] in stems]


def cmd_convert(a) -> int:
    for key in keys(a.stems):
        script, md, st = build(key)
        sp, mp = paths(key)
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(script, encoding="utf-8", newline="\n")
        if md is not None:
            mp.parent.mkdir(parents=True, exist_ok=True)
            mp.write_text(md, encoding="utf-8", newline="\n")
        print(f"{key}: code {st['code']}, markdown {st['markdown']}, empty skipped {st['skipped_empty']}, "
              f"wrapped {st['wrap']} + {st['wrap_tuple']} tuples, magic {st['magic']}, disabled {st['disabled']}, "
              f"final checkpoint cell {st['fc']}")
    return 0


def parse_script(text: str) -> list[tuple[str, int, str]]:
    out, cur = [], None
    for line in text.split("\n"):
        m = re.match(r"# %%( \[markdown\])? cell (\d+)$", line)
        if m:
            if cur:
                out.append(cur)
            cur = ["markdown" if m.group(1) else "code", int(m.group(2)), []]
        elif cur:
            cur[2].append(line)
    if cur:
        out.append(cur)
    res = []
    for kind, i, lines in out:
        while lines and not lines[-1].strip():
            lines.pop()
        if kind == "markdown":
            lines = [l[2:] if l.startswith("# ") else l[1:] if l.startswith("#") else l for l in lines]
        res.append((kind, i, "\n".join(lines)))
    return res


def cmd_check(a) -> int:
    bad = 0
    for key in keys(a.stems):
        sp, mp = paths(key)
        cells = json.loads(notebook_path(key).read_text(encoding="utf-8"))["cells"]
        fc = fc_index(cells)
        errs = []
        if not sp.exists():
            print(f"FAIL {key}: script missing"); bad += 1; continue
        got = parse_script(sp.read_text(encoding="utf-8"))
        want = [(c["cell_type"], i, src(c).rstrip("\n")) for i, c in enumerate(cells)
                if src(c).strip() and c["cell_type"] in ("code", "markdown")]
        if [(k, i) for k, i, _ in got] != [(k, i) for k, i, _ in want]:
            errs.append("cell list / order differs")
        changed = 0
        for (gk, gi, gt), (wk, wi, wt) in zip(got, want):
            if gk == "markdown" and gi == fc:
                md = mp.read_text(encoding="utf-8") if mp.exists() else None
                if md is None or md.rstrip("\n") != wt:
                    errs.append(f"Final Checkpoint cell {gi} differs from {mp.relative_to(ROOT)}")
                continue
            back = untransform(gt) if gk == "code" else gt
            if back != wt:
                errs.append(f"cell {gi} differs")
            elif gk == "code" and gt != wt:
                changed += 1
        if fc is None and mp.exists():
            errs.append("a checkpoint .md exists but the notebook has no Final Checkpoint")
        try:
            py_compile.compile(str(sp), doraise=True, cfile=str(ROOT / "Notebooks" / "_scratch" / "pyc" / sp.name) + "c")
        except py_compile.PyCompileError as e:
            errs.append(f"compile: {e.msg[:200]}")
        if errs:
            bad += 1
            print(f"FAIL {key}: " + "; ".join(errs[:5]))
        else:
            print(f"✅ {key}: {len(want)} cells equal ({changed} code cells with listed changes only), "
                  f"checkpoint {'cell ' + str(fc) if fc is not None else 'none'}, compiles")
    print(f"{'ALL OK' if not bad else f'{bad} FAILED'}")
    return 1 if bad else 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)
    for n in ("convert", "check"):
        s = sp.add_parser(n); s.add_argument("stems", nargs="*")
    a = p.parse_args()
    return {"convert": cmd_convert, "check": cmd_check}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
