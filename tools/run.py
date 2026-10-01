"""Run a pipeline script with a small, low-token summary (replaces `tools/nb.py run` for scripts).

  uv run python tools/run.py <script.py> [--timeout S] [--compare]
  uv run python tools/run.py all [--from STEM] [--compare]   every script in ORDER, stops at the first failure

- Runs the script from the project root, output to Notebooks/_scratch/run_<stem>.log (git-ignored).
- Prints the exit code, every validation line (✅ / "validation passed") and, on failure, the traceback tail.
- Always reports which files under Data/processed/ and db/migrations/ the run changed or created (SHA-256 before /
  after; no git needed), so "the outputs did not change" is checked on every run.
- --compare: also compares the validation lines with the saved outputs of the source notebook named in the script's
  header ("Converted from Notebooks/....ipynb"), for the notebooks → scripts verification.
Exit code 1 when the script fails or --compare finds a difference.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / "Notebooks" / "_scratch"
OK_RE = re.compile(r"✅|validation passed", re.I)
WATCH = [ROOT / "Data" / "processed", ROOT / "db" / "migrations"]


def snapshot() -> dict[str, str]:
    out = {}
    for base in WATCH:
        for p in sorted(base.rglob("*")):
            if p.is_file():
                out[p.relative_to(ROOT).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def notebook_ok_lines(script: Path) -> tuple[Path | None, list[str]]:
    m = re.search(r"Converted from (Notebooks/\S+\.ipynb)", script.read_text(encoding="utf-8")[:2000])
    if not m:
        return None, []
    nb = ROOT / m.group(1)
    if not nb.exists():                                   # archived after verification
        nb = ROOT / "docs" / "archive" / "notebooks" / Path(m.group(1)).relative_to("Notebooks")
    if not nb.exists():
        return None, []
    lines = []
    for c in json.loads(nb.read_text(encoding="utf-8"))["cells"]:
        for o in c.get("outputs", []) if c["cell_type"] == "code" else []:
            if o.get("output_type") == "stream":
                lines += [l.strip() for l in "".join(o.get("text", "")).splitlines() if OK_RE.search(l)]
    return nb, lines


# Verification order for `all`: smallest first; LPI Methodology before LPI Connecting to Compete (it reads its units).
ORDER = [
    "structured/ExtractPortsAttributes", "structured/ExtractPortsConnection", "rag/Documents_registry",
    "semi_structured/EDI_generator", "semi_structured/AIS_generator", "rag/Suez_Notes_chunking",
    "semi_structured/AIS_EDI_profiling", "synthetic/SyntheticGenerator", "semi_structured/MongoDB_loader",
    "rag/FBL_chunking", "rag/IMO_MSC-MEPC_3_Circ_4_Rev_1_chunking", "rag/USCG_ROI_chunking",
    "rag/HbR_Annual_report_2025_chunking", "rag/LPI_methodology_chunking", "rag/LPI_Connecting_to_Compete_chunking",
]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("script"); p.add_argument("--timeout", type=int, default=7200)
    p.add_argument("--compare", action="store_true")
    p.add_argument("--from", dest="frm", help="with `all`: start at this script stem (resume after a fix)")
    a = p.parse_args()
    if a.script == "all":
        keys = ORDER
        if a.frm:
            starts = [i for i, k in enumerate(ORDER) if k.split("/")[1] == a.frm]
            if not starts:
                print(f"unknown stem: {a.frm}"); return 1
            keys = ORDER[starts[0]:]
        for k in keys:
            print(f"===== {k}", flush=True)
            if run_one(ROOT / "pipelines" / "scripts" / f"{k}.py", a.timeout, a.compare):
                print(f"STOPPED at {k}; resume with: uv run python tools/run.py all --compare --from {k.split('/')[1]}")
                return 1
        print(f"ALL {len(keys)} SCRIPTS PASSED")
        return 0
    return run_one(Path(a.script), a.timeout, a.compare)


def run_one(script: Path, timeout: int, compare: bool) -> int:
    script = script.resolve()
    if not script.is_file() or script.suffix != ".py":
        print(f"script not found: {script} (give the real path, e.g. pipelines/scripts/rag/FBL_chunking.py)")
        return 1
    SCRATCH.mkdir(parents=True, exist_ok=True)
    log = SCRATCH / f"run_{script.stem}.log"
    env = dict(os.environ, PYTHONIOENCODING="utf-8", MPLBACKEND="Agg")
    before = snapshot()
    t0 = time.time()
    with open(log, "w", encoding="utf-8") as fh:
        try:
            rc = subprocess.run([sys.executable, str(script)], cwd=ROOT, env=env, stdout=fh, stderr=subprocess.STDOUT,
                                timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            rc = "timeout"
    after = snapshot()
    text = log.read_text(encoding="utf-8", errors="replace")
    ok = [l.strip() for l in text.splitlines() if OK_RE.search(l)]
    for l in ok:
        print(l[:160])
    print(f"exit {rc} in {time.time() - t0:.0f}s | validation lines: {len(ok)} | log: {log.relative_to(ROOT)}")
    if rc != 0:
        print("-- last log lines --"); print("\n".join(text.splitlines()[-15:]))
    changed = sorted(k for k in after if k in before and after[k] != before[k])
    created = sorted(k for k in after if k not in before)
    removed = sorted(k for k in before if k not in after)
    print(f"files changed: {len(changed)} | created: {len(created)} | removed: {len(removed)} "
          f"(Data/processed, db/migrations)")
    for k in (changed + created + removed)[:30]:
        print(f"  {'changed' if k in changed else 'created' if k in created else 'removed'}: {k}")
    bad = rc != 0
    if compare:
        nb, want = notebook_ok_lines(script)
        if nb is None:
            print("compare: source notebook not found"); bad = True
        elif ok == want:
            print(f"compare: ✅ identical validation lines ({len(ok)}) to {nb.relative_to(ROOT)}")
        else:
            bad = True
            print(f"compare: DIFFERENT — script {len(ok)} lines, notebook {len(want)} lines")
            for i, (g, w) in enumerate(zip(ok, want)):
                if g != w:
                    print(f"  first difference at line {i}:\n    script:   {g[:150]}\n    notebook: {w[:150]}")
                    break
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
