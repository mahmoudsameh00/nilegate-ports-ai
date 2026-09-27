"""Notebook helper for low-token development (the coding assistant and the owner). Never prints cell outputs in full.

  uv run python tools/nb.py cells  <nb.ipynb> [--code|--md] [--from N] [--to M] [--grep REGEX] [--full]
        list cells (index, id, type, first line); --full prints the source (never the outputs)
  uv run python tools/nb.py check  <nb.ipynb>
        from the SAVED outputs: errors (cell, name, message) + validation lines (✅ / "validation passed")
  uv run python tools/nb.py run    <nb.ipynb> [--timeout S]
        execute in place with nbconvert -> Notebooks/_scratch/run_<stem>.log, then print the `check` summary
  uv run python tools/nb.py test   <cells.py> [...]
        exec the code cells of percent-format cell files in ONE namespace (display -> print) -> test log + summary
  uv run python tools/nb.py append <nb.ipynb> <cells.py> [...]
        append the cells of cell files to the notebook
  uv run python tools/nb.py replace <nb.ipynb> <keep_first_N> <cells.py> [...]
        keep the first N cells, replace the rest with the cells of the files
  uv run python tools/nb.py drift  <nb.ipynb> <keep_first_N> <cells.py> [...]
        compare the notebook cells after N with the cell files (source only)

Cell files: '# %% [markdown]' starts a markdown cell (lines prefixed '# '), '# %%' starts a code cell.
Every command exits 1 on failure, so PowerShell can chain: cmd1; if ($LASTEXITCODE -eq 0) { cmd2 }.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / "Notebooks" / "_scratch"
OK_RE = re.compile(r"✅|validation passed", re.I)


def load(nb: Path) -> dict:
    return json.loads(Path(nb).read_text(encoding="utf-8"))


def save(nb: Path, d: dict) -> None:
    Path(nb).write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def src(c: dict) -> str:
    return "".join(c.get("source", []))


def first_line(c: dict) -> str:
    return next((l for l in src(c).split("\n") if l.strip() and not l.startswith("# ====")), "")[:100]


def parse_cells(path: Path) -> list[dict]:
    cells, kind, buf = [], None, []

    def flush():
        if kind is None:
            return
        lines = buf[:]
        while lines and not lines[-1].strip():
            lines.pop()
        if kind == "markdown":
            lines = [l[2:] if l.startswith("# ") else l[1:] if l.startswith("#") else l for l in lines]
        text = "\n".join(lines)
        parts = text.split("\n")
        cell = {"cell_type": kind, "id": uuid.uuid4().hex[:8], "metadata": {},
                "source": [p + "\n" for p in parts[:-1]] + [parts[-1]]}
        if kind == "code":
            cell.update(execution_count=None, outputs=[])
        cells.append(cell)

    for line in Path(path).read_text(encoding="utf-8").split("\n"):
        if line.startswith("# %% [markdown]"):
            flush(); kind, buf = "markdown", []
        elif line.startswith("# %%"):
            flush(); kind, buf = "code", []
        else:
            buf.append(line)
    flush()
    return cells


def summary(d: dict) -> int:
    n_err = 0
    for i, c in enumerate(d["cells"]):
        for o in c.get("outputs", []) if c["cell_type"] == "code" else []:
            if o.get("output_type") == "error":
                n_err += 1
                print(f"ERROR cell {i}: {o.get('ename')}: {str(o.get('evalue'))[:300]}")
            if o.get("output_type") == "stream":
                for line in "".join(o.get("text", "")).splitlines():
                    if OK_RE.search(line):
                        print(f"cell {i}: {line.strip()[:160]}")
    code = [c for c in d["cells"] if c["cell_type"] == "code"]
    print(f"cells: {len(d['cells'])} | code: {len(code)} | executed: {sum(1 for c in code if c.get('execution_count'))} | errors: {n_err}")
    return 1 if n_err else 0


def cmd_cells(a) -> int:
    d = load(a.nb)
    for i, c in enumerate(d["cells"]):
        if (a.code and c["cell_type"] != "code") or (a.md and c["cell_type"] != "markdown"):
            continue
        if i < a.frm or (a.to is not None and i > a.to):
            continue
        s = src(c)
        if a.grep and not re.search(a.grep, s):
            continue
        print(f"[{i}] {c.get('id', '')} {c['cell_type'][:4]} | {first_line(c)}")
        if a.full:
            print(s.rstrip() + "\n")
    return 0


def cmd_run(a) -> int:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    log = SCRATCH / f"run_{Path(a.nb).stem}.log"
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    nb = Path(a.nb).resolve()                      # absolute: nbconvert runs from the notebook's folder
    before = nb.stat().st_mtime
    with open(log, "w", encoding="utf-8") as fh:
        rc = subprocess.run([sys.executable, "-m", "jupyter", "nbconvert", "--to", "notebook", "--execute", "--inplace",
                             f"--ExecutePreprocessor.timeout={a.timeout}", str(nb)],
                            cwd=nb.parent, env=env, stdout=fh, stderr=subprocess.STDOUT).returncode
    print(f"nbconvert exit {rc} (log: {log.relative_to(ROOT)})")
    if rc != 0 or nb.stat().st_mtime == before:
        # never report the outputs of an older run as if they were this run's
        print("RUN FAILED — the notebook was not re-executed; last log lines:")
        print("\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-15:]))
        return 1
    return summary(load(nb))


def cmd_test(a) -> int:
    import contextlib
    import io
    import traceback
    SCRATCH.mkdir(parents=True, exist_ok=True)
    log = SCRATCH / f"test_{Path(a.files[0]).stem}.log"
    ns = {"display": lambda *x, **k: [print(v) for v in x], "__name__": "__main__"}
    buf, rc = io.StringIO(), 0
    os.chdir(Path(a.files[0]).resolve().parent)
    with contextlib.redirect_stdout(buf):
        try:
            for f in a.files:
                for c in parse_cells(Path(f)):
                    if c["cell_type"] == "code":
                        exec(compile(src(c), f"{Path(f).name}:{first_line(c)}", "exec"), ns)
            print("TEST RUN OK")
        except Exception:
            traceback.print_exc(); rc = 1
    text = buf.getvalue()
    log.write_text(text, encoding="utf-8")
    lines = text.splitlines()
    for l in lines:
        if OK_RE.search(l) or "TEST RUN OK" in l:
            print(l[:160])
    if rc:
        print("-- traceback tail --"); print("\n".join(lines[-12:]))
    print(f"log: {log.relative_to(ROOT)} ({len(lines)} lines)")
    return rc


def cmd_append(a) -> int:
    d = load(a.nb); new = [c for f in a.files for c in parse_cells(Path(f))]
    d["cells"] += new; save(a.nb, d); print(f"appended {len(new)} cells -> {len(d['cells'])}"); return 0


def cmd_replace(a) -> int:
    d = load(a.nb); new = [c for f in a.files for c in parse_cells(Path(f))]
    d["cells"] = d["cells"][:a.keep] + new; save(a.nb, d)
    print(f"kept {a.keep}, added {len(new)} -> {len(d['cells'])}"); return 0


def cmd_drift(a) -> int:
    d = load(a.nb); want = [c for f in a.files for c in parse_cells(Path(f))]; have = d["cells"][a.keep:]
    bad = [i for i, (h, w) in enumerate(zip(have, want)) if src(h).rstrip() != src(w).rstrip() or h["cell_type"] != w["cell_type"]]
    extra = len(have) - len(want)
    for i in bad[:20]:
        print(f"DRIFT cell {a.keep + i}: {first_line(have[i])}")
    print(f"drift: {len(bad)} differing cells, count difference {extra}")
    return 1 if bad or extra else 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("cells"); s.add_argument("nb"); s.add_argument("--code", action="store_true")
    s.add_argument("--md", action="store_true"); s.add_argument("--from", dest="frm", type=int, default=0)
    s.add_argument("--to", type=int); s.add_argument("--grep"); s.add_argument("--full", action="store_true")
    s = sp.add_parser("check"); s.add_argument("nb")
    s = sp.add_parser("run"); s.add_argument("nb"); s.add_argument("--timeout", type=int, default=3600)
    s = sp.add_parser("test"); s.add_argument("files", nargs="+")
    s = sp.add_parser("append"); s.add_argument("nb"); s.add_argument("files", nargs="+")
    for name in ("replace", "drift"):
        s = sp.add_parser(name); s.add_argument("nb"); s.add_argument("keep", type=int); s.add_argument("files", nargs="+")
    a = p.parse_args()
    return {"cells": cmd_cells, "check": lambda a: summary(load(a.nb)), "run": cmd_run, "test": cmd_test,
            "append": cmd_append, "replace": cmd_replace, "drift": cmd_drift}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
