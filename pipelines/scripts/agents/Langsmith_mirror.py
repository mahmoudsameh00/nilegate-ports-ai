"""LangSmith mirror (Observability plan S2): the frozen golden sets as datasets, each evaluation run as an experiment.

Plan:    docs/plans/Observability_Sentry_plan.md S2 (approved 2026-11-01, S2–S4 as one batch).
Run:     uv run python tools/run.py pipelines/scripts/agents/Langsmith_mirror.py  (from the project root)
         MIRROR_LIVE=1 uploads (needs LANGSMITH_API_KEY in .env); MIRROR_RESULTS=<file>,<file> picks the results files
         (names in Data/processed/agents/eval/; default: the current baselines and their comparisons).

Reads:   Data/processed/agents/eval/ — finance_qa_golden.jsonl, supervisor_qa_golden.jsonl, golden_weeks.json,
         golden_findings.json, the stage1_eval_* / stage2_eval_* results files. No database, no model call.
Writes:  nothing local. Live: LangSmith datasets `nilegate-<set>@<sha8>` (one per frozen file version) and one
         experiment per run of each results file (its target returns the stored answer, its evaluator the stored
         code scores: 0 model calls, one small trace per item).
Re-run:  safe — a dataset whose name (= its sha) exists is reused, an experiment whose results file + run is already
         mirrored is skipped.

The mirror is a view, not a source of truth: the local golden sets (sha256 in git) and the code scorer stay the
acceptance rule (ADR-052); nothing here re-scores or judges.

Phases
1. Build (0 network): the three datasets' examples from the frozen files (sha256 each); every results file's runs as
   experiment rows; every row's id is a dataset example; the stored scores per item (bools → 0 / 1).
2. Datasets (live): create the missing ones; an existing one must hold exactly the frozen examples.
3. Experiments (live): one per results file × run not yet mirrored.
4. Read-back (live): each mirrored experiment found under its dataset with one run per example.
Final Checkpoint (pending phases listed).
"""
# %% Setup
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())
sys.path.insert(0, str(ROOT))
from pipelines.lib.common import load_env  # noqa: E402

EVAL = ROOT / "Data/processed/agents/eval"
DEFAULT_RESULTS = ["stage1_eval_2026-11-01_base3.json", "stage1_eval_2026-11-01_c4.json",
                   "stage1_eval_2026-10-31_dp127b.json", "stage2_eval_2026-10-29.json", "stage2_eval_2026-10-30_c1.json"]
QA_SCORES = ("completeness", "relevance", "status_ok", "numbers_ok", "traceable")
DONE: list[int] = []
load_env(ROOT)
LIVE = os.environ.get("MIRROR_LIVE") == "1"
RESULTS = [s.strip() for s in os.environ.get("MIRROR_RESULTS", "").split(",") if s.strip()] or DEFAULT_RESULTS


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def as_score(v):
    """A stored score as a number: bool → 0 / 1, number as is, anything else skipped."""
    if isinstance(v, bool):
        return int(v)
    return v if isinstance(v, (int, float)) else None


def pack_scores(p: dict) -> dict:
    ratio = lambda a, b: len(a) / len(b) if b else None  # noqa: E731
    return {"published": int(p["published"]), "numbers_ok": int(p["numbers_ok"]),
            "planted_recall": ratio(p["planted_found"], p["planted"]),
            "narrative_recall": ratio(p["findings_met"], p["findings"]),
            "false_alarms": p["false_alarms"], "claims_wrong": p["claims_wrong"], "rewrites": p["rewrites"]}


# %% Phase 1 — build the datasets and the experiment rows (0 network)
# One dataset per frozen file version: the name carries the file's sha256 prefix, so a REFREEZE becomes a new dataset
# and an experiment always points at the exact set it was scored on.
files = {"finance-qa": EVAL / "finance_qa_golden.jsonl", "supervisor-qa": EVAL / "supervisor_qa_golden.jsonl",
         "golden-weeks": EVAL / "golden_weeks.json"}
findings = json.loads((EVAL / "golden_findings.json").read_text(encoding="utf-8"))["weeks"]
datasets = {}
for kind, path in files.items():
    sha = sha256(path)
    if kind == "golden-weeks":
        sha = hashlib.sha256((sha + sha256(EVAL / "golden_findings.json")).encode()).hexdigest()
        rows = [{"inputs": {"id": f"{w['dataset']}:{w['week']}", "dataset": w["dataset"], "week": w["week"]},
                 "outputs": {"rule": w["rule"], "seen": w["seen"],
                             "findings": findings.get(f"{w['dataset']}:{w['week']}", [])},
                 "metadata": {"id": f"{w['dataset']}:{w['week']}"}}
                for w in json.loads(path.read_text(encoding="utf-8"))["weeks"]]
    else:
        rows = [{"inputs": {"id": q["id"], "question": q["question"], "lang": q["lang"], "asker": q["asker"],
                            "employee_id": q["employee_id"], **({"as_of": q["as_of"]} if "as_of" in q else {})},
                 "outputs": {k: q[k] for k in ("expected_status", "elements", "relevance", "tools_needed", "products")
                             if k in q},
                 "metadata": {"id": q["id"]}} for q in jsonl(path)]
    datasets[kind] = {"name": f"nilegate-{kind}@{sha[:8]}", "sha256": sha, "file": path.name, "rows": rows,
                      "ids": {r["inputs"]["id"] for r in rows}}

experiments = []
for name in RESULTS:
    path = EVAL / name
    d = json.loads(path.read_text(encoding="utf-8"))
    for run in d["runs"]:
        parts = []
        if run.get("packs"):
            parts.append(("golden-weeks", "packs", {p["week"]: pack_scores(p) for p in run["packs"]},
                          {p["week"]: {k: p[k] for k in ("status", "stop_reason", "false_alarm_text", "claim_text")
                                       if k in p} for p in run["packs"]}))
        if run.get("answers"):
            parts.append(("finance-qa", "qa", {a["id"]: {k: as_score(a.get(k)) for k in QA_SCORES} for a in run["answers"]},
                          {a["id"]: {"status": a["status"], "answer": a.get("rendered"), "problems": a["problems"]}
                           for a in run["answers"]}))
        if run.get("scores"):
            parts.append(("supervisor-qa", "qa", {s["id"]: {k: as_score(s.get(k)) for k in QA_SCORES} for s in run["scores"]},
                          {s["id"]: {"status": s["status"], "answer": s.get("rendered"), "problems": s["problems"],
                                     "routed": s.get("routed"), "refused": s.get("refused")} for s in run["scores"]}))
        for kind, part, scores, outputs in parts:
            experiments.append({"dataset": kind, "results_file": name, "results_sha256": sha256(path),
                                "repeat": run["repeat"], "part": part, "tag": d.get("tag"),
                                "verdict": (d.get("adr052_vs") or {}).get("verdict"),
                                "prefix": f"{path.stem}-{part}-r{run['repeat']}", "scores": scores, "outputs": outputs})

unknown = {e["prefix"]: sorted(set(e["scores"]) - datasets[e["dataset"]]["ids"]) for e in experiments}
actual = {"datasets": {k: (len(v["rows"]), v["name"].split("@")[0]) for k, v in datasets.items()},
          "experiments": len(experiments), "unknown_ids": {k: v for k, v in unknown.items() if v},
          "every_score_numeric_or_none": all(v is None or isinstance(v, (int, float))
                                             for e in experiments for s in e["scores"].values() for v in s.values())}
expected = {"datasets": {"finance-qa": (42, "nilegate-finance-qa"), "supervisor-qa": (57, "nilegate-supervisor-qa"),
                         "golden-weeks": (11, "nilegate-golden-weeks")},
            "experiments": actual["experiments"], "unknown_ids": {}, "every_score_numeric_or_none": True}
assert actual == expected, {k: (actual[k], expected[k]) for k in actual if actual[k] != expected[k]}
assert actual["experiments"] > 0
print(f"Phase 1: {[(v['name'], len(v['rows'])) for v in datasets.values()]}; "
      f"{len(experiments)} experiment rows from {len(RESULTS)} results files")
print("✅ Phase 1 validation passed: three frozen datasets (sha-named) and every result row maps to a golden item")
DONE.append(1)

# %% Phase 2 — datasets (live)
# Created once per frozen version; an existing one is reused only if it holds exactly the frozen example ids.
if LIVE:
    from langsmith import Client
    client = Client()
    ds_objs = {}
    for kind, ds in datasets.items():
        if client.has_dataset(dataset_name=ds["name"]):
            obj = client.read_dataset(dataset_name=ds["name"])
            have = {(e.metadata or {}).get("id") for e in client.list_examples(dataset_id=obj.id)}
            assert have == ds["ids"], (ds["name"], sorted(have ^ ds["ids"])[:5])
            state = "reused"
        else:
            obj = client.create_dataset(
                ds["name"], description=(f"Frozen golden set {ds['file']} (sha256 {ds['sha256']}). A mirror for "
                                         "item-by-item comparison: the local file and the code scorer stay the "
                                         "acceptance rule (ADR-052)."),
                metadata={"sha256": ds["sha256"], "file": ds["file"]})
            client.create_examples(dataset_id=obj.id, examples=ds["rows"])
            state = "created"
        ds_objs[kind] = obj
        print(f"Phase 2: {ds['name']} {state}")
    print("✅ Phase 2 validation passed: the three datasets exist with exactly the frozen examples")
    DONE.append(2)

# %% Phase 3 — experiments (live)
# The target returns the stored answer of the item, the evaluator its stored code scores: no model is called and
# nothing is re-scored. Skipped when the same results file + run is already mirrored on the dataset.
if LIVE:
    mirrored = {}
    for kind, obj in ds_objs.items():
        for p in client.list_projects(reference_dataset_id=obj.id):
            m = (p.metadata or {})
            m = m.get("metadata", m)
            mirrored[(kind, m.get("results_sha256"), m.get("repeat"), m.get("part"))] = p.name
    sent, skipped = [], []
    for e in experiments:
        key = (e["dataset"], e["results_sha256"], e["repeat"], e["part"])
        if key in mirrored:
            skipped.append(e["prefix"])
            continue

        def target(inputs: dict, e=e) -> dict:
            out = e["outputs"].get(inputs["id"])
            return {**out, "scores": e["scores"][inputs["id"]]} if out is not None else {"missing": True}

        def stored_scores(outputs: dict) -> dict:
            return {"results": [{"key": k, "score": v} for k, v in (outputs.get("scores") or {}).items()
                                if v is not None]}

        client.evaluate(target, data=datasets[e["dataset"]]["name"], evaluators=[stored_scores],
                        experiment_prefix=e["prefix"], max_concurrency=4,
                        description=f"{e['results_file']} run {e['repeat']} ({e['part']}); ADR-052 verdict "
                                    f"{e['verdict']}; stored answers + code scores, 0 model calls",
                        metadata={k: e[k] for k in ("results_file", "results_sha256", "repeat", "part", "tag",
                                                    "verdict")})
        sent.append(e["prefix"])
    print(f"Phase 3: sent {len(sent)}, already mirrored {len(skipped)}")
    print("✅ Phase 3 validation passed: every results run is mirrored once")
    DONE.append(3)

# %% Phase 4 — read-back (live)
# Every experiment row is found under its dataset, with one run per example of the dataset.
if LIVE:
    found = {}
    for kind, obj in ds_objs.items():
        for p in client.list_projects(reference_dataset_id=obj.id, include_stats=True):
            m = (p.metadata or {})
            m = m.get("metadata", m)
            found[(kind, m.get("results_sha256"), m.get("repeat"), m.get("part"))] = p.run_count
    missing = [e["prefix"] for e in experiments
               if (e["dataset"], e["results_sha256"], e["repeat"], e["part"]) not in found]
    short = [e["prefix"] for e in experiments
             if (k := (e["dataset"], e["results_sha256"], e["repeat"], e["part"])) in found
             and found[k] is not None and found[k] < len(datasets[e["dataset"]]["rows"])]
    assert not missing, missing
    print(f"Phase 4: {len(experiments)} experiments found; run counts below the dataset size: {short or 'none'}")
    print("✅ Phase 4 validation passed: every mirrored experiment is read back under its dataset")
    DONE.append(4)

# %% Final Checkpoint
# Narrative: pipelines/checkpoints/agents/Langsmith_mirror.md (every step, its problems and their fixes).
PHASES = {1: "build (0 network)", 2: "datasets (MIRROR_LIVE=1)", 3: "experiments (MIRROR_LIVE=1)",
          4: "read-back (MIRROR_LIVE=1)"}
pending = [f"{k} {v}" for k, v in PHASES.items() if k not in DONE]
assert DONE == sorted(DONE) and set(DONE) <= set(PHASES)
print(f"Final Checkpoint: done {DONE}; pending: {pending}")
print(f"✅ Final Checkpoint: {len(DONE)} / {len(PHASES)} phases passed")
