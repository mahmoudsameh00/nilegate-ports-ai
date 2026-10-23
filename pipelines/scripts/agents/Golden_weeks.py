"""Golden weeks of the Stage 1 evaluation (Agents plan Phase 7, §5d step S1): chosen by stated rules before any run.

Plan:    docs/plans/Agents_plan.md §5d (approved 2026-10-19); the acceptance rule that uses them = ADR-052.
Run:     uv run python tools/run.py pipelines/scripts/agents/Golden_weeks.py  (from the project root)

Reads:   PostgreSQL read-only (PG_RO_USER): finance.kpi_weekly, finance.invoice_audit, the answer key's test weeks
         through the Stage 1 tools (finance_kpi, invoice_audit) as the CEO; IMF PortWatch through suez_transits (2025 is
         settled: the first run caches it in Data/processed/agents/tool_cache/, later runs make 0 calls).
Writes:  Data/processed/agents/eval/golden_weeks.json — the selection (weeks, dataset, the rule and its value), frozen:
         a re-run recomputes it and stops if it differs (the data under a rule changed).
         Data/processed/agents/eval/golden_weeks_expected.json — the evidence the pack sees for every golden week (the
         expected KPIs, = the views), written only when every week can be read (the test weeks need migration 017,
         step S2); until then a draft goes to Notebooks/_scratch/ for the review of the expected findings.
Re-run:  safe (read-only on the database; frozen files are compared, never overwritten with different content).

Phases
1. The rules (fixed in §5d before any run) applied to the views → 11 golden weeks, seen / unseen marked.
2. The expected evidence per golden week = the pack's KPI + audit evidence; the test weeks' planted findings = the
   answer key.
Final Checkpoint (narrative: pipelines/checkpoints/agents/Golden_weeks.md).
"""
# %% Setup
import hashlib
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())
sys.path.insert(0, str(ROOT))
from pipelines.agents.graphs import weekly_pack  # noqa: E402
from pipelines.agents.tools import context, db, external  # noqa: E402

EVAL = ROOT / "Data" / "processed" / "agents" / "eval"
SELECTION = EVAL / "golden_weeks.json"
EXPECTED = EVAL / "golden_weeks_expected.json"
DRAFT = ROOT / "Notebooks" / "_scratch" / "golden_weeks_expected_draft.json"
# v2 (2026-10-22, D-P7-1, migration 018): the planted budget miss is a real miss; v1 stays as generated for 012
ANSWER_KEY = json.loads((EVAL / "finance_test_answer_key_v2.json").read_text(encoding="utf-8"))
# a frozen file is re-frozen only on a recorded change: its current sha256 must start with the prefix named here
# (one transition; afterwards the guard holds again). Old → new hashes are recorded in the plan's Progress.
# history: bb3b1a3b… → 7909ccfb… (D-P7-1 / migration 018: the week 36 LNG budget, a real planted miss)
REFREEZE = {"golden_weeks_expected.json": ("7909ccfb0d2385b0", "migration 019 (2026-10-22, §5f F5): audit rows carry "
                                           "`review`, the result `invoices_manual_review` (the tariff Notes rule)")}

ceo_id = db.fetch("SELECT e.employee_id FROM employees e JOIN roles r USING (role_id) WHERE r.role_name = 'ceo'")
assert len(ceo_id) == 1, ceo_id
CEO = context.load_user(ceo_id[0]["employee_id"])     # reads every Stage 1 resource: the golden evidence is complete


def dumps(obj) -> str:
    return json.dumps(obj, indent=1, ensure_ascii=False, sort_keys=True) + "\n"


def save_frozen(path: Path, obj) -> str:
    """Write once; a later run must compute the same content (a frozen input never changes silently)."""
    text = dumps(obj)
    if path.exists():
        old = path.read_text(encoding="utf-8")
        old_sha = hashlib.sha256(old.encode("utf-8")).hexdigest()
        prefix, why = REFREEZE.get(path.name, (None, None))
        if old != text and prefix and old_sha.startswith(prefix):
            path.write_text(text, encoding="utf-8", newline="\n")
            print(f"{path.name} RE-FROZEN ({why}): {old_sha[:16]}… → "
                  f"{hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]}…")
        else:
            assert old == text, f"{path.name} differs from the frozen file: the data under a rule changed — review first"
    else:
        path.write_text(text, encoding="utf-8", newline="\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# %% Phase 1 — The rules → the golden weeks
# §5d fixed the rules before any run, so the weeks cannot be picked after seeing how the agents do on them. Test
# weeks (dataset "test", the copy with planted errors) are the answer key's four; each live rule orders the weeks by
# its criterion and takes the first one not already taken (ties → the lowest week). Rules on a change or a level use
# weeks 14–52: weeks 1–13 are the warm-up (receivables building up since 2025-01-01, ADR-047), covered by week 5.
# Weeks 5 / 10 / 23 / 49 shaped the Phase 6 prompts and Validator → "seen"; the rest are "unseen" (reported apart).
SEEN = {5, 10, 23, 49}
TEST_WEEKS = ANSWER_KEY["weeks"]
assert TEST_WEEKS == [10, 23, 36, 49] and ANSWER_KEY["clean_week"] == 49

kw = db.fetch("SELECT report_week, billed_sdr, billed_wow_pct, budget_variance_pct FROM finance.kpi_weekly "
              "ORDER BY report_week")
assert [r["report_week"] for r in kw] == list(range(1, 53))
steady = [r for r in kw if r["report_week"] >= 14]
dup_weeks = sorted({r["report_week"] for r in db.fetch(
    "SELECT report_week FROM finance.invoice_audit WHERE check_code = 'duplicate_charge'")})

# Suez transits per ISO week of 2025 (PortWatch; week 1 starts 2024-12-30, week 52 ends 2025-12-28); windows < 120 days
first, last = date(2024, 12, 23), date(2025, 12, 28)          # one week before week 1, for its WoW
days: dict[str, int] = {}
start = first
while start <= last:
    end = min(start + timedelta(days=external.MAX_WINDOW_DAYS - 1), last)
    res = external.suez_transits(CEO, start=start, end=end)
    assert res.status == "ok", (start, res.status, res.note)
    days.update({r["date"]: r["n_total"] for r in res.rows})
    start = end + timedelta(days=1)
assert len(days) == (last - first).days + 1, f"PortWatch days missing: {(last - first).days + 1 - len(days)}"
suez = {w: sum(days[(date(2024, 12, 30) + timedelta(days=7 * (w - 1) + i)).isoformat()] for i in range(7))
        for w in range(0, 53)}                                 # week 0 = 2024-W52 (the WoW base of week 1)
suez_wow = [{"report_week": w, "transits": suez[w], "prev": suez[w - 1],
             "wow_pct": round((suez[w] - suez[w - 1]) / suez[w - 1] * 100, 2)} for w in range(14, 53)]

taken = set(TEST_WEEKS)
weeks = [{"week": w, "dataset": "test", "rule": "answer key: planted errors" if w != 49 else
          "answer key: clean week (false-alarm check)", "value": None} for w in TEST_WEEKS]


def pick(rule: str, candidates: list[tuple[int, float | None]]) -> None:
    """candidates already ordered by the rule (best first, ties by week); take the first week not taken."""
    w, v = next((w, v) for w, v in candidates if w not in taken)
    taken.add(w)
    weeks.append({"week": w, "dataset": "live", "rule": rule, "value": v})


pick("warm-up week (fixed: week 5)", [(5, None)])
pick("peak: max billed_sdr", [(r["report_week"], r["billed_sdr"])
                              for r in sorted(kw, key=lambda r: (-r["billed_sdr"], r["report_week"]))])
pick("quiet: min |billed_wow_pct|, weeks 14-52", [(r["report_week"], r["billed_wow_pct"]) for r in
                                                  sorted(steady, key=lambda r: (abs(r["billed_wow_pct"]),
                                                                                r["report_week"]))])
pick("trough: min billed_sdr, weeks 14-52", [(r["report_week"], r["billed_sdr"])
                                             for r in sorted(steady, key=lambda r: (r["billed_sdr"],
                                                                                    r["report_week"]))])
pick("live budget miss: min budget_variance_pct, weeks 14-52",
     [(r["report_week"], r["budget_variance_pct"])
      for r in sorted(steady, key=lambda r: (r["budget_variance_pct"], r["report_week"]))])
pick("a real duplicate charge (finance.invoice_audit)", [(w, None) for w in dup_weeks])
pick("Suez transits moved most: max |WoW %| of weekly PortWatch transits, weeks 14-52",
     [(r["report_week"], r["wow_pct"]) for r in sorted(suez_wow, key=lambda r: (-abs(r["wow_pct"]),
                                                                                 r["report_week"]))])
for g in weeks:
    g["seen"] = g["week"] in SEEN

selection = {"plan": "Agents plan §5d (approved 2026-10-19); rules fixed before any run; ADR-052",
             "seen_weeks": sorted(SEEN), "weeks": weeks}
sel_sha = save_frozen(SELECTION, selection)
for g in weeks:
    print(f"  week {g['week']:>2} {g['dataset']:<4} {'seen  ' if g['seen'] else 'unseen'} {g['rule']}"
          + (f" = {g['value']}" if g["value"] is not None else ""))
print(f"live duplicate weeks: {dup_weeks}; selection sha256 {sel_sha[:16]}…")

# reviewed snapshot: the rule outcomes on today's views (a changed view or PortWatch revision stops here)
snapshot = {"n": 11, "test": [10, 23, 36, 49], "dup_weeks": [10, 15, 50]}
actual = {"n": len(weeks), "test": [g["week"] for g in weeks if g["dataset"] == "test"], "dup_weeks": dup_weeks}
assert actual == snapshot, actual
assert len({g["week"] for g in weeks}) == len(weeks), "a week picked twice"
print("✅ Phase 1 validation passed: 11 golden weeks by rule (4 test + 7 live), frozen in golden_weeks.json")


# %% Phase 2 — The expected evidence of each golden week
# What the pack sees for a week is its evidence: the five KPI datasets and the week's audit (weekly_pack.kpi_evidence /
# audit_evidence, the same tool calls). Frozen now, it is the expected KPIs of §5d ("by SQL": the views, verified
# against an independent pandas reference by Finance_views_check). Test weeks read the twin views of migration 017
# (step S2): until they exist, those weeks are pending and only a draft is written for the review of the findings.
twins = db.fetch("SELECT to_regclass('finance_test.kpi_weekly') IS NOT NULL AS weekly, "
                 "to_regclass('finance_test.kpi_weekly_category') IS NOT NULL AS category")[0]
twins_ready = twins["weekly"] and twins["category"]

expected, pending = {}, []
for g in weeks:
    w, ds = g["week"], g["dataset"]
    if ds == "test" and not twins_ready:
        ev = {}
        pending.append(w)
    else:
        ev = weekly_pack.kpi_evidence(CEO, w, ds)
    ev.update(weekly_pack.audit_evidence(CEO, w, ds))
    bad = {k: v["status"] for k, v in ev.items() if v["status"] != "ok"}
    assert not bad, (w, ds, bad)
    expected[f"{ds}:{w}"] = ev

# the planted findings of the answer key appear in the test weeks' audit evidence (the Auditor is code: 5 / 5)
for f in ANSWER_KEY["findings"]:
    if f["error"] == "budget_miss":
        continue
    rows = expected[f"test:{f['iso_week']}"]["audit.week"]["rows"]
    assert any(r["invoice_number"] == f["invoice_number"] for r in rows), f
# the planted budget miss (answer key v2): the category's variance in the test week = the key's
for f in ANSWER_KEY["findings"]:
    if f["error"] == "budget_miss":
        row = next(r for r in expected[f"test:{f['iso_week']}"]["kpi.category"]["rows"]
                   if r["vessel_category"] == f["vessel_category"])
        assert f"{row['budget_variance_pct']:.2f}" == f["expected_variance_pct"], (row, f)
flagged = {k: v["audit.week"]["invoices_flagged"] for k, v in expected.items()}
print("invoices flagged per golden week:", flagged)
assert flagged["test:49"] == 0, "the clean week is flagged"

if pending:
    DRAFT.parent.mkdir(parents=True, exist_ok=True)
    DRAFT.write_text(dumps(expected), encoding="utf-8", newline="\n")
    print(f"PENDING (migration 017, step S2): KPI evidence of test weeks {pending}; draft → {DRAFT.relative_to(ROOT)}")
else:
    exp_sha = save_frozen(EXPECTED, {"selection_sha256": sel_sha, "evidence": expected})
    print(f"expected evidence frozen: {EXPECTED.name} sha256 {exp_sha[:16]}…")
print(f"✅ Phase 2 validation passed: evidence of {len(expected) - len(pending)} / 11 weeks complete, the 5 planted "
      f"invoice errors in the test audit, week 49 clean")


# %% Final Checkpoint
# Narrative: pipelines/checkpoints/agents/Golden_weeks.md
print(f"✅ Final Checkpoint: 11 golden weeks frozen ({sum(not g['seen'] for g in weeks)} unseen); expected evidence "
      + ("frozen" if not pending else f"pending for test weeks {pending} (migration 017)"))
