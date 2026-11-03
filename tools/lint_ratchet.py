"""Lint ratchet: ruff + pyright may not get worse (Engineering hygiene plan H1; free tools only).

The code base predates both tools (490 ruff findings on the bug rules, 278 pyright errors on pipelines/agents +
pipelines/lib on 2026-11-01). Fixing them in one go would touch the scheduled products' code, so the current counts
are a baseline (`tools/lint_baseline.json`, per tool × rule × file) and a run fails only when a count goes UP —
new code must be clean, old findings are paid down file by file (then `--update` lowers the baseline).

Run:     uv run python tools/lint_ratchet.py            (check; exit 1 on any increase)
         uv run python tools/lint_ratchet.py --update   (write the current counts as the new baseline)
Reads:   the source tree (ruff on pipelines/ tools/ db/, pyright on pipelines/agents/ pipelines/lib/ — pyproject.toml).
Writes:  tools/lint_baseline.json with --update only.
"""
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists())
BASELINE = ROOT / "tools" / "lint_baseline.json"


def rel(path: str) -> str:
    return Path(path).resolve().relative_to(ROOT).as_posix()


def ruff_counts() -> Counter:
    out = subprocess.run([sys.executable, "-m", "ruff", "check", "--output-format", "json", "--exit-zero",
                          "pipelines", "tools", "db"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        raise SystemExit(f"ruff failed: {out.stderr[-500:]}")
    return Counter(f"ruff|{d['code']}|{rel(d['filename'])}" for d in json.loads(out.stdout or "[]"))


def pyright_counts() -> Counter:
    out = subprocess.run([sys.executable, "-m", "pyright", "--outputjson"], cwd=ROOT, capture_output=True,
                         text=True, encoding="utf-8")
    try:
        data = json.loads(out.stdout.lstrip("﻿"))
    except json.JSONDecodeError:
        raise SystemExit(f"pyright gave no JSON: {out.stdout[-300:]} {out.stderr[-300:]}") from None
    return Counter(f"pyright|{d.get('rule', 'error')}|{rel(d['file'])}" for d in data["generalDiagnostics"]
                   if d["severity"] == "error")


def main() -> int:
    now = ruff_counts() + pyright_counts()
    if "--update" in sys.argv:
        BASELINE.write_text(json.dumps(dict(sorted(now.items())), indent=1) + "\n", encoding="utf-8", newline="\n")
        print(f"baseline written: {sum(now.values())} findings in {len(now)} tool|rule|file keys")
        return 0
    base = Counter(json.loads(BASELINE.read_text(encoding="utf-8")))
    worse = {k: (base.get(k, 0), v) for k, v in now.items() if v > base.get(k, 0)}
    better = sum(base.values()) - sum(min(base[k], now.get(k, 0)) for k in base)
    by_tool = {t: sum(v for k, v in now.items() if k.startswith(t)) for t in ("ruff", "pyright")}
    print(f"now: ruff {by_tool['ruff']}, pyright {by_tool['pyright']} (baseline {sum(base.values())}); "
          f"fixed since the baseline: {better}")
    for k, (b, v) in sorted(worse.items()):
        tool, rule, path = k.split("|")
        print(f"  NEW  {tool} {rule} {path}: {b} → {v}")
    if worse:
        print("✗ the ratchet failed: new findings above; fix them (or, for a deliberate exception, a noqa / "
              "type: ignore with a reason)")
        return 1
    print("✅ lint ratchet: no new ruff or pyright findings" + (" — run --update to lock in the fixes" if better else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
