"""Scheduler check (Agents plan Phase 8, §5e S1): the week picker, the scheduled firing, retention and the G5 report.

Plan:    docs/plans/Agents_plan.md §5e (owner decisions P8-1…P8-4, approved 2026-10-20).
Run:     uv run python tools/run.py pipelines/scripts/agents/Scheduler_check.py  (from the project root)

Reads:   PostgreSQL read-only (PG_RO_USER): employees / roles / departments, the finance and audit views.
         No LLM call (scripted fake models only); no toast. LangSmith only in Phase 5, with a key.
Writes:  checkpoints in agent_state under the prefix `weekly_pack:check:2025-W` (login ports_agent), all deleted at
         the end (and at the start, if a failed run left some); a throw-away temp folder for the published packs,
         the archive and the log (the real `reports/` is never written).
Re-run:  safe.

Phases
0. Week picker (P8-1) on hand-made thread lists: next week, one pending at a time, resume a stalled thread, retry once
   then skip, the end of the replay, foreign thread ids ignored.
1. Retention rules (P8-3) on hand-made threads, dry run: ended + older than 30 days only; pending never; stale
   pending / stalled reported.
2. Scheduled firings end to end on PostgresSaver with fake models: start → wait (idempotent) → edit + approve →
   published; a Writer that stays wrong twice → the week is skipped; a reject; a crash mid-run → resumed by the next
   firing with its own run identity; retention 31 days later (dry run, then archive + delete; the pending thread
   kept); the G5 report from agent_state + archive + published folder (one entry per thread).
3. Run identity (P5-5) and the CLI: only a Finance manager may be the scheduled identity; `prune --dry-run` and
   `report` run on the live threads (read-only).
4. LangSmith tracing contract (P8-4, S2) in a child process with a fake key and a refused local endpoint (no
   network): on only inside `tracing.trace`, tags + metadata per run, a failed upload never fails the run, no global
   switch in .env.
5. LangSmith read-back (S2): one fake-model scheduled firing traced and read back with `langsmith.Client` — only
   with the owner's LANGSMITH_API_KEY (pending without it; one small trace per run of this check).
   `Client.list_runs` is deprecated after 2027-01-31; in the pinned langsmith 0.14.7 its replacement
   `client.runs.query` is async-only (an `AsyncPaginator`) and takes project ids, not names (checked 2026-10-22,
   plan §5f K7) — so the sync call stays until a langsmith upgrade, which re-checks this; if the call disappears,
   this phase fails loudly (AttributeError), never silently.
Final Checkpoint (pending phases listed).
"""
# %% Setup
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from langchain_core.messages import AIMessage
from langgraph.types import Command

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())
sys.path.insert(0, str(ROOT))
from pipelines.agents import checkpointer, roles  # noqa: E402
from pipelines.agents import scheduling as sch  # noqa: E402
from pipelines.agents import tracing  # noqa: E402
from pipelines.agents.deck import sample  # noqa: E402
from pipelines.agents.deck import validator as v2  # noqa: E402
from pipelines.agents.graphs import models as m  # noqa: E402
from pipelines.agents.graphs import weekly_pack as wp  # noqa: E402
from pipelines.agents.tools import context, db  # noqa: E402
from pipelines.lib.common import SECRET_KEYS, load_env  # noqa: E402

DONE: list[int] = []
T0 = datetime(2026, 10, 20, 8, 0, tzinfo=timezone.utc)
P = sch.LIVE_PREFIX


def info(week, attempt, state, status=None, days_old=0, prefix=P):
    return sch.ThreadInfo(f"{prefix}{week:02d}:{attempt}", week, attempt, state, status,
                          T0 - timedelta(days=days_old), 12)


def short(d: sch.Decision):
    return (d.action, d.week, d.thread_id and d.thread_id.removeprefix(P), d.skipped)


# %% Phase 0 — Week picker (P8-1)
# D12 replays 2025. A firing makes the week after the highest settled week (published, or skipped after two attempts
# that ended without a deck); a pack waiting at the approval blocks everything (one pending at a time); a thread
# stopped mid-run (ADR-050 (6): an exception such as a quota) is resumed before anything new; a rejected pack counts
# as an attempt that ended without a deck. Ids that are not `<prefix><ww>:<n>` (a check's `…:check-1a2b`) are ignored.
cases = {
    "empty": ([], ("start", 1, "01:1", [])),
    "after W10": ([info(10, 1, "ended", "published")], ("start", 11, "11:1", [])),
    "pending blocks": ([info(10, 1, "ended", "published"), info(11, 1, "pending", "awaiting_approval")],
                       ("wait", 11, "11:1", [])),
    "pending before stalled": ([info(12, 1, "stalled", "running"), info(11, 1, "pending", "awaiting_approval")],
                               ("wait", 11, "11:1", [])),
    "stalled resumed": ([info(10, 1, "ended", "published"), info(11, 1, "stalled", "running")],
                        ("resume", 11, "11:1", [])),
    "retry once": ([info(10, 1, "ended", "published"), info(11, 1, "ended", "validation_failed")],
                   ("start", 11, "11:2", [])),
    "skip after two": ([info(10, 1, "ended", "published"), info(11, 1, "ended", "validation_failed"),
                        info(11, 2, "ended", "output_invalid")], ("start", 12, "12:1", [11])),
    "rejected = an attempt": ([info(10, 1, "ended", "published"), info(11, 1, "ended", "rejected")],
                              ("start", 11, "11:2", [])),
    "published on retry": ([info(11, 1, "ended", "validation_failed"), info(11, 2, "ended", "published")],
                           ("start", 12, "12:1", [])),
    "end of replay": ([info(52, 1, "ended", "published")], ("done", None, None, [])),
}
got = {name: short(sch.plan(infos)) for name, (infos, _) in cases.items()}
want = {name: exp for name, (_, exp) in cases.items()}
parsed = {t: sch.parse_thread(t, P) for t in (f"{P}07:3", f"{P}23:check-1a2b", f"{P}7:1", "weekly_pack:test:2025-W07:1")}
actual = {"decisions": got, "parsed": parsed,
          "reasons": [sch.plan(cases[k][0]).reason for k in ("retry once", "skip after two")]}
expected = {"decisions": want,
            "parsed": {f"{P}07:3": (7, 3), f"{P}23:check-1a2b": None, f"{P}7:1": None,
                       "weekly_pack:test:2025-W07:1": None},
            "reasons": ["retry after validation_failed", "next week of the replay"]}
assert actual == expected, {k: (actual[k], expected[k]) for k in actual if actual[k] != expected[k]}
print(f"Phase 0: {len(cases)} picker cases, {len(parsed)} thread ids")
print("✅ Phase 0 validation passed: next week of the replay, one pending at a time, stalled resumed, retry once then "
      "skip, end of the replay, foreign ids ignored")
DONE.append(0)

# %% Phase 1 — Retention rules (P8-3), dry run
# Only a thread that ended AND whose last checkpoint is older than 30 days goes (archive first: Phase 2); a pack
# waiting at the approval is never deleted, whatever its age (reported after 14 days); a stalled thread is kept for
# the next firing (reported after 14 days too). The dry run deletes nothing and needs no graph.
threads = [info(1, 1, "ended", "published", 31), info(2, 1, "ended", "rejected", 45),
           info(3, 1, "ended", "validation_failed", 29), info(4, 1, "pending", "awaiting_approval", 90),
           info(5, 1, "pending", "awaiting_approval", 3), info(6, 1, "stalled", "running", 20),
           info(7, 1, "ended", "published", 0)]
out = sch.prune(None, None, threads, Path("unused"), now=T0, dry_run=True)
actual = {k: [t.removeprefix(P) for t in v] if isinstance(v, list) else v for k, v in out.items()}
expected = {"deleted": [], "would_delete": ["01:1", "02:1"], "stale_pending": ["04:1"], "stale_stalled": ["06:1"],
            "kept": 5}
assert actual == expected, actual
print(f"Phase 1: {actual}")
print("✅ Phase 1 validation passed: ended + older than 30 days only; pending never; stale pending / stalled "
      "reported; the dry run deletes nothing")
DONE.append(1)

# %% Phase 2 — Scheduled firings end to end (PostgresSaver, fake models)
# The firing code of the CLI (`scheduling.fire`) on a check prefix and a temp folder. The fake Writer follows a mode
# per week: good (the sample slot draft), wrong (a typed wrong number the patch keeps → validation_failed after two
# rewrites), crash (raises inside the Writer, like a quota error: the thread stays at its checkpoint).
CP = "weekly_pack:check:2025-W"
REPORTS = Path(tempfile.mkdtemp(prefix="scheduler_check_"))
ARCHIVE = REPORTS / sch.LOG_DIR / "threads_archive.jsonl"
people = db.fetch("SELECT e.employee_id, r.role_name, d.department_name FROM employees e "
                  "JOIN roles r USING (role_id) JOIN departments d USING (department_id) ORDER BY e.employee_id")


def first(role, dept=None):
    return next(p["employee_id"] for p in people if p["role_name"] == role and dept in (None, p["department_name"]))


fin_mgr = context.load_user(first("manager", "Finance"))
fin_mgr2 = context.load_user([p["employee_id"] for p in people
                              if (p["role_name"], p["department_name"]) == ("manager", "Finance")][1])


class Script:
    def __init__(self):
        self.modes: dict[int, str] = {}
        self.ev: dict[int, dict] = {}

    def evidence(self, w):
        if w not in self.ev:
            self.ev[w] = {**wp.kpi_evidence(fin_mgr, w), **wp.audit_evidence(fin_mgr, w, "live")}
        return self.ev[w]

    def __call__(self, role, msgs, tools, schema):
        if schema is None:
            return AIMessage(content="Findings ready.")
        if schema is m.InsightNotes:
            return m.InsightNotes(summary=[m.Cited(text="Billed changed WoW", evidence_ids=["kpi.weekly"])])
        w = int(re.search(r"ISO week (\d+) of", str(msgs[0].content))[1])
        mode = self.modes.get(w, "good")
        if mode == "crash":
            raise RuntimeError("simulated quota exhaustion inside the Writer")
        wrong = f"Billed 999.99 M SDR in week {w} of 2025"
        if schema is m.DeckPatch:
            return m.DeckPatch(fixes=[m.Fix(target="bullet", index=0, text=wrong, evidence_ids=["kpi.weekly"])])
        d = sample.slot_draft(w, self.evidence(w))
        if mode == "wrong":
            d["bullets"][0]["text"] = wrong
        return m.DeckDraft.model_validate(d)


script = Script()
saver = checkpointer.saver()
pool = checkpointer.pool()
g = wp.build_graph(roles.FakeRoles(script), saver, REPORTS)


def clean():
    for t in sch.thread_ids(pool, CP):
        saver.delete_thread(t)


clean()                                                        # leftovers of a failed earlier run
log = []


def firing(note):
    try:
        rec = sch.fire(g, saver, pool, fin_mgr, REPORTS, prefix=CP, notify=False)
    except RuntimeError as exc:
        rec = {"error": str(exc)}
    d = rec.get("decision") or {}
    log.append((note, d.get("action"), (d.get("thread_id") or "").removeprefix(CP) or None,
                (rec.get("result") or {}).get("status"), rec.get("error") and "raised"))
    return rec


def decide(thread, decision, **kw):
    cfg = {"configurable": {"thread_id": CP + thread}}
    for _ in g.stream(Command(resume={"decision": decision, "approver_employee_id": fin_mgr2.employee_id, **kw}),
                      cfg, context=context.RunContext(fin_mgr), stream_mode="updates", durability="sync"):
        pass
    return g.get_state(cfg)


firing("first firing")                                         # W01:1 → waits at the approval
firing("second firing, same day")                              # wait: no second attempt
snap = g.get_state({"configurable": {"thread_id": CP + "01:1"}})
bullet0 = v2.render_draft(snap.values["draft"], snap.values["evidence"])["bullets"][0]
edited = decide("01:1", "edit", edits=[{"bullet": 0, "text": bullet0["text"]}], comment="wording kept")
published = decide("01:1", "approve")
script.modes[2] = "wrong"
firing("W02 attempt 1")
firing("W02 attempt 2")
firing("W03 after the skip")
decide("03:1", "reject", comment="not this one")
script.modes[3] = "crash"
firing("W03 attempt 2 crashes")
script.modes[3] = "good"
firing("next firing resumes")
ids = sch.thread_ids(pool, CP)
run_as = {t.removeprefix(CP): sch.run_as_of(g, {"configurable": {"thread_id": t}}) for t in ids}

# retention 31 days later: dry run first, then archive + delete; the pending W03:2 stays
later = sch.now_utc() + timedelta(days=31)
infos = sch.describe_all(g, pool, CP)
dry = sch.prune(g, saver, infos, ARCHIVE, now=later, dry_run=True)
ids_after_dry = sch.thread_ids(pool, CP)
pruned = sch.prune(g, saver, infos, ARCHIVE, now=later)
left = [t.removeprefix(CP) for t in sch.thread_ids(pool, CP)]
rows_left = {t.removeprefix(CP): sum(1 for _ in saver.list({"configurable": {"thread_id": t}}))
             for t in pruned["deleted"]}
archive = [json.loads(x) for x in ARCHIVE.read_text(encoding="utf-8").splitlines()]
report = sch.approval_report(sch.report_entries(g, sch.describe_all(g, pool, CP), REPORTS))
clean()

actual = {
    "firings": log,
    "edit": (edited.values["approval_log"][-1]["outcome"], edited.next),
    "published": (published.values["status"], sorted(p.name for p in (REPORTS / "2025-W01").iterdir())),
    "run_as": run_as,
    "dry_run": (sorted(t.removeprefix(CP) for t in dry["would_delete"]), len(ids_after_dry) == len(ids)),
    "pruned": {k: sorted(t.removeprefix(CP) for t in v) if isinstance(v, list) else v for k, v in pruned.items()},
    "left": left, "rows_left": rows_left,
    "archive": [(a["thread_id"].removeprefix(CP), a["status"], [x["outcome"] for x in a["approval_log"]],
                 a["run_as"]) for a in archive],
    "report": {k: v for k, v in report.items() if k != "threads"}, "report_threads": len(report["threads"]),
    "threads_after_cleanup": sch.thread_ids(pool, CP),
}
expected = {
    "firings": [("first firing", "start", "01:1", "awaiting_approval", None),
                ("second firing, same day", "wait", "01:1", None, None),
                ("W02 attempt 1", "start", "02:1", "validation_failed", None),
                ("W02 attempt 2", "start", "02:2", "validation_failed", None),
                ("W03 after the skip", "start", "03:1", "awaiting_approval", None),
                ("W03 attempt 2 crashes", None, None, None, "raised"),
                ("next firing resumes", "resume", "03:2", "awaiting_approval", None)],
    "edit": ("edited", ("approval",)),
    "published": ("published", ["approval.json", "deck.pptx", "deck_draft.json", "run.json"]),
    "run_as": {k: fin_mgr.employee_id for k in ("01:1", "02:1", "02:2", "03:1", "03:2")},
    "dry_run": (["01:1", "02:1", "02:2", "03:1"], True),
    "pruned": {"deleted": ["01:1", "02:1", "02:2", "03:1"], "would_delete": [], "stale_pending": ["03:2"],
               "stale_stalled": [], "kept": 1},
    "left": ["03:2"], "rows_left": {k: 0 for k in ("01:1", "02:1", "02:2", "03:1")},
    "archive": [("01:1", "published", ["edited", "approved"], fin_mgr.employee_id),
                ("02:1", "validation_failed", [], fin_mgr.employee_id),
                ("02:2", "validation_failed", [], fin_mgr.employee_id),
                ("03:1", "rejected", ["rejected"], fin_mgr.employee_id)],
    "report": {"packs_decided": 2, "published": 1, "rejected": 1, "packs_edited": 1, "edit_rate": 0.5,
               "decisions": {"approved": 1, "edited": 1, "rejected": 1}, "edited_slides": {bullet0["slide"]: 1},
               "form_fixes": {"packs": 0, "fixes": 0}},          # the sample drafts' slots are well formed
    "report_threads": 5,
    "threads_after_cleanup": [],
}
assert actual == expected, {k: (actual[k], expected[k]) for k in actual if actual[k] != expected[k]}
print(f"Phase 2: {len(log)} firings, archive {len(archive)} lines, report {actual['report']}")
print("✅ Phase 2 validation passed: start → wait (idempotent) → edit + approve → published; two stopped attempts → "
      "skipped; reject; crash → resumed with its own identity; retention archives then deletes (pending kept); "
      "G5 report one entry per thread")
DONE.append(2)

# %% Phase 3 — Run identity (P5-5) and the CLI
# Only a Finance manager may be the scheduled identity (not the CEO: level 3 data; not an employee; not another
# department's manager). The CLI's read-only commands run on the live threads: `prune --dry-run` deletes nothing,
# `report` prints the G5 numbers.
who = {"finance manager": first("manager", "Finance"), "finance employee": first("employee", "Finance"),
       "operations manager": first("manager", "Operations"), "ceo": first("ceo")}
rule = {k: sch.allowed_run_as(context.load_user(v)) for k, v in who.items()}
live_before = sch.thread_ids(pool, P)
cli = {c: subprocess.run([sys.executable, "pipelines/scripts/agents/Weekly_pack.py", *c.split()], cwd=ROOT,
                         capture_output=True, text=True, encoding="utf-8", timeout=300,
                         env={**os.environ, "PYTHONIOENCODING": "utf-8"})
       for c in ("prune --dry-run", "report")}
outs = {c: json.loads(r.stdout) if r.returncode == 0 else r.stderr[-800:] for c, r in cli.items()}
actual = {"rule": rule, "exit": {c: r.returncode for c, r in cli.items()},
          "dry_deleted": outs["prune --dry-run"]["deleted"], "report_keys": sorted(outs["report"]),
          "live_unchanged": sch.thread_ids(pool, P) == live_before}
expected = {"rule": {"finance manager": True, "finance employee": False, "operations manager": False, "ceo": False},
            "exit": {"prune --dry-run": 0, "report": 0}, "dry_deleted": [],
            "report_keys": ["decisions", "edit_rate", "edited_slides", "form_fixes", "packs_decided", "packs_edited",
                            "published", "rejected", "threads"],
            "live_unchanged": True}
assert actual == expected, (actual, outs)
print(f"Phase 3: rule {rule}; live report {({k: outs['report'][k] for k in ('packs_decided', 'edit_rate')})}")
print("✅ Phase 3 validation passed: only a Finance manager is a scheduled identity; prune --dry-run and report "
      "run on the live threads and change nothing")
DONE.append(3)

# %% Phase 4 — LangSmith tracing contract (P8-4, S2), no network
# Tracing is on only inside `tracing.trace` and only with a key; no global switch may be set in .env or the
# environment (it would trace the checks and Stage1_eval.py, which stay untouched while c3 is under test). A child
# process with a fake key and an endpoint that refuses connections (127.0.0.1:9: nothing leaves the machine) shows:
# off before and after the block, on inside it (project, tags, metadata), the failed upload does not fail the run, an
# error of the run itself propagates, an empty key = off.
load_env(ROOT)
example = dict(x.split("=", 1) for x in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
               if x and not x.startswith("#"))
CHILD = """
import json, os, sys
sys.path.insert(0, os.getcwd())
from langchain_core.runnables import RunnableLambda
from langsmith.run_helpers import get_tracing_context
from langsmith.utils import tracing_is_enabled
from pipelines.agents import tracing
T = "weekly_pack:live:2025-W11:2"
out, seen = {"before": tracing_is_enabled()}, {}
def body(x):
    tc = get_tracing_context()
    seen.update(on=tracing_is_enabled(), project=tc["project_name"], tags=tc["tags"], metadata=tc["metadata"])
    return x + 1
with tracing.trace(T, entry="run", run_as=12) as on:
    out["yielded"], out["result"] = on, RunnableLambda(body).invoke(1)
out["inside"], out["after"] = seen, tracing_is_enabled()
try:
    with tracing.trace(T, entry="resume", run_as=12):
        raise ValueError("the run's own error")
except ValueError as exc:
    out["propagated"] = str(exc)
os.environ.update(LANGSMITH_API_KEY="", LANGCHAIN_API_KEY="")
with tracing.trace(T, entry="run", run_as=12) as on:
    out["empty_key"] = on
print(json.dumps(out))
"""
child_env = {**os.environ, "PYTHONIOENCODING": "utf-8", "LANGSMITH_API_KEY": "lsv2_check_fake_key_000000",
             "LANGCHAIN_API_KEY": "", "LANGSMITH_ENDPOINT": "http://127.0.0.1:9"}
for k in tracing.SWITCHES:
    child_env.pop(k, None)
t0 = time.monotonic()
child = subprocess.run([sys.executable, "-c", CHILD], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                       timeout=180, env=child_env)
child_s = time.monotonic() - t0
assert child.returncode == 0, child.stderr[-1500:]
got = json.loads(child.stdout.strip().splitlines()[-1])
actual = {"switch_env": tracing.global_switch(), "switch_example": [k for k in tracing.SWITCHES if k in example],
          "example_keys": [k for k in ("LANGSMITH_API_KEY", "PACK_RUN_AS") if k in example],
          "secret": "LANGSMITH_API_KEY" in SECRET_KEYS, "child": got,
          "labels_foreign": tracing.labels("other:thread", "run", None)[1]["week"]}
expected = {"switch_env": None, "switch_example": [], "example_keys": ["LANGSMITH_API_KEY", "PACK_RUN_AS"],
            "secret": True,
            "child": {"before": False, "yielded": True, "result": 2,
                      "inside": {"on": True, "project": "nilegate-agents",
                                 "tags": ["weekly_pack", "entry:run", "launched_by:cli", "week:2025-W11",
                                          "dataset:live"],
                                 "metadata": {"thread_id": "weekly_pack:live:2025-W11:2", "week": "2025-W11",
                                              "attempt": "2", "dataset": "live", "run_as": 12, "entry": "run",
                                              "launched_by": "cli"}},
                      "after": False, "propagated": "the run's own error", "empty_key": False},
            "labels_foreign": None}
assert actual == expected, {k: (actual[k], expected[k]) for k in actual if actual[k] != expected[k]}
print(f"Phase 4: child {child_s:.0f} s (upload refused locally, run unaffected); no global switch; "
      f"key in this environment: {tracing.has_key()}")
print("✅ Phase 4 validation passed: tracing on only inside trace() with a key; tags + metadata per run; a failed "
      "upload never fails the run; the run's own error propagates; no global switch")
DONE.append(4)

# %% Phase 5 — LangSmith read-back (S2; needs the owner's LANGSMITH_API_KEY)
# One scheduled firing with fake models on the check prefix, traced like Task Scheduler's (trigger "check"), read back
# with `langsmith.Client`: the root run of the thread in project nilegate-agents, its tags and metadata, the node runs
# under it; the checkpoint metadata still carries only the run identity (the graph config is untouched). Skipped
# (pending) without a key.
if not tracing.has_key():
    print("Phase 5 pending: no LANGSMITH_API_KEY in .env (owner step of S2)")
else:
    from langsmith import Client
    since = datetime.now(timezone.utc) - timedelta(minutes=2)
    rec = sch.fire(g, saver, pool, fin_mgr, REPORTS, prefix=CP, notify=False,
                   tracer=lambda t, r: tracing.trace(t, entry="scheduled", run_as=r, launched_by="check"))
    tid = rec["result"]["thread_id"]
    cp_meta = [s.metadata for s in g.get_state_history({"configurable": {"thread_id": tid}})]
    client, root, in_trace = Client(), None, 0
    for _ in range(36):           # ingestion lag: up to 3 min; the root can arrive before its child runs
        root = root or next((r for r in client.list_runs(project_name=tracing.PROJECT, is_root=True,
                                                          start_time=since)
                             if ((r.extra or {}).get("metadata") or {}).get("thread_id") == tid), None)
        if root:
            in_trace = sum(1 for _ in client.list_runs(project_name=tracing.PROJECT, trace_id=root.trace_id))
            if in_trace >= 5:
                break
        time.sleep(5)
    clean()
    assert root is not None, f"no root run of {tid} in LangSmith project {tracing.PROJECT}"
    meta = root.extra["metadata"]
    actual = {"traced": rec["traced"], "status": rec["result"]["status"],
              "tags": sorted(set(root.tags) & {"weekly_pack", "entry:scheduled", "launched_by:check", "week:2025-W01",
                                                "dataset:check"}),
              "meta": {k: meta.get(k) for k in ("week", "attempt", "run_as", "entry", "launched_by", "trigger")},
              "error": root.error, "runs_in_trace_ge_5": in_trace >= 5,
              "cp_run_as": {x.get("run_as") for x in cp_meta if x.get("run_as")},
              "cp_trace_keys": sorted({k for x in cp_meta for k in x} & {"entry", "week", "attempt"})}
    expected = {"traced": True, "status": "awaiting_approval",
                "tags": ["dataset:check", "entry:scheduled", "launched_by:check", "week:2025-W01", "weekly_pack"],
                "meta": {"week": "2025-W01", "attempt": "1", "run_as": fin_mgr.employee_id, "entry": "scheduled",
                         "launched_by": "check", "trigger": "scheduled"},    # trigger = the checkpoint's own key
                "error": None, "runs_in_trace_ge_5": True, "cp_run_as": {fin_mgr.employee_id}, "cp_trace_keys": []}
    assert actual == expected, {k: (actual[k], expected[k]) for k in actual if actual[k] != expected[k]}
    print(f"Phase 5: root run {root.id} ({in_trace} runs in the trace), tags {actual['tags']}")
    print("✅ Phase 5 validation passed: a scheduled firing is traced in nilegate-agents and read back with its tags "
          "and metadata; the checkpoint metadata is unchanged")
    DONE.append(5)

# %% Final Checkpoint
# Narrative: pipelines/checkpoints/agents/Scheduler_check.md (every step, its problems and their fixes).
PHASES = {0: "week picker", 1: "retention rules", 2: "scheduled firings end to end", 3: "run identity + CLI",
          4: "tracing contract", 5: "LangSmith read-back (needs LANGSMITH_API_KEY)"}
shutil.rmtree(REPORTS, ignore_errors=True)
pending = [f"{k} {v}" for k, v in PHASES.items() if k not in DONE]
assert DONE == sorted(DONE) and set(DONE) <= set(PHASES)
print(f"Final Checkpoint: done {DONE}; pending: {pending}")
print(f"✅ Final Checkpoint: {len(DONE)} / {len(PHASES)} phases passed")
