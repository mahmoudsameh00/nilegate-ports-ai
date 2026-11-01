"""Monitoring check (Observability plan S1): Sentry errors, logs and the weekly pack's cron monitor.

Plan:    docs/plans/Observability_Sentry_plan.md S1 (approved 2026-10-31).
Run:     uv run python tools/run.py pipelines/scripts/agents/Monitoring_check.py  (from the project root)

Reads:   .env (variables already set in the environment win; every phase sets its own SENTRY_DSN). No LLM call, no
         database: the CLIs' database probe is replaced by one that raises.
Writes:  nothing outside a throw-away temp folder (the CLIs' `reports/_log` is pointed there). Phases 1–5 send
         nothing over the network (a recording transport); Phase 6 sends one event and one log to Sentry, only with
         MONITORING_LIVE=1 and the owner's SENTRY_DSN.
Re-run:  safe.

Phases
1. Off and on: no DSN → off and every call a no-op; with a DSN → on, no AI / httpx / pymongo integration, no
   tracing, logs enabled, the defaults (excepthook, logging, …) present.
2. A captured exception → one event with the tags; a secret in the message, in a local variable and the DSN never
   leave the process.
3. Logging: INFO → a breadcrumb only, WARNING → a Sentry log, ERROR → a log and an event; log bodies redacted.
4. Cron: `in_progress` then `ok` / `error` (exit code or exception) with the monitor config; then the real CLIs:
   `Weekly_pack.py scheduled` with a failing database probe → check-ins + the exception, exit 1;
   `Voyage_watch.py scheduled` the same → the exception only (no cron: the free plan's one monitor is the pack's).
5. A Sentry failure never fails a run: a transport that raises, an `init` that raises.
6. Live (MONITORING_LIVE=1 + SENTRY_DSN): one test exception and one WARNING log tagged with a run id, read back by
   Claude through the Sentry MCP (no check-in: a check's check-in would take or disturb the plan's only monitor).
Final Checkpoint (pending phases listed).
"""
# %% Setup
import importlib.util
import json
import logging
import os
import sys
import tempfile
import uuid
from pathlib import Path

import sentry_sdk
from sentry_sdk.transport import Transport

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())
sys.path.insert(0, str(ROOT))
from pipelines.agents import monitoring  # noqa: E402
from pipelines.lib.common import load_env  # noqa: E402

FAKE_DSN = "https://0123456789abcdef0123456789abcdef@o0.ingest.sentry.io/0"
FAKE_SECRET = "gsk_CHECK_ONLY_7f3a9c1e5b2d4f60"
TMP = Path(tempfile.mkdtemp(prefix="monitoring_check_"))
DONE: list[int] = []
log = logging.getLogger("monitoring_check")
log.setLevel(logging.INFO)
load_env(ROOT)
LIVE_DSN = os.environ.get("SENTRY_DSN", "").strip()       # read before the phases replace it


class Recorder(Transport):
    """Keeps every envelope item as (type, json payload); `fail` = a transport that raises."""

    def __init__(self, options=None, fail: bool = False):
        super().__init__(options)
        self.items: list[tuple[str, dict]] = []
        self.fail = fail

    def capture_envelope(self, envelope) -> None:
        if self.fail:
            raise ConnectionError("refused (Monitoring_check)")
        self.items += [(i.type, i.payload.json) for i in envelope.items]

    def flush(self, timeout, callback=None) -> None:
        pass

    def kill(self) -> None:
        pass

    def of(self, kind: str) -> list[dict]:
        return [p for t, p in self.items if t == kind]

    def logs(self) -> list[dict]:
        return [x for p in self.of("log") for x in p.get("items", [])]


def start(rec: Recorder | None, entry: str = "check", dsn: str = FAKE_DSN) -> bool:
    """A fresh scope (no tags or breadcrumbs from an earlier phase), then `monitoring.init` on `rec`."""
    sentry_sdk.get_isolation_scope().clear()
    sentry_sdk.get_current_scope().clear()
    os.environ["SENTRY_DSN"] = dsn
    return monitoring.init(entry=entry, launched_by="check", transport=rec)


def flush() -> None:
    monitoring.flush(timeout=2)


def load_cli(stem: str):
    spec = importlib.util.spec_from_file_location(f"{stem.lower()}_cli", ROOT / f"pipelines/scripts/agents/{stem}.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    return cli


# %% Phase 1 — off and on
# No DSN = no Sentry at all; with one, the AI integrations stay off (they would turn every model call into a span;
# LangSmith is the tracer, ADR-054) and nothing samples traces.
os.environ["SENTRY_DSN"] = ""
off = monitoring.init(entry="check")
monitoring.tag(thread_id="x")
monitoring.capture(RuntimeError("never sent"))
with monitoring.cron(monitoring.CRON_WEEKLY_PACK) as r:
    r["exit"] = 0
off_is_on = monitoring.is_on()
rec = Recorder()
on = start(rec)
client = sentry_sdk.get_client()
names = set(client.integrations)
AI = {"langchain", "langgraph", "openai", "openai_agents", "google_genai", "anthropic", "httpx", "httpx2", "pymongo"}
actual = {"off": off, "is_on_after_off": off_is_on, "on": on, "ai_integrations": sorted(names & AI),
          "defaults_present": {"argv", "atexit", "dedupe", "excepthook", "logging", "modules", "stdlib",
                               "threading"} <= names,
          "traces_sample_rate": client.options["traces_sample_rate"], "enable_logs": client.options["enable_logs"],
          "send_default_pii": client.options["send_default_pii"],
          "release": client.options["release"], "environment": client.options["environment"]}
expected = {"off": False, "is_on_after_off": False, "on": True, "ai_integrations": [], "defaults_present": True,
            "traces_sample_rate": None, "enable_logs": True, "send_default_pii": False,
            "release": "nilegate-agents@0.1.0", "environment": os.environ.get("SENTRY_ENVIRONMENT", "") or "local"}
assert actual == expected, {k: (actual[k], expected[k]) for k in actual if actual[k] != expected[k]}
print(f"Phase 1: integrations {sorted(names)}")
print("✅ Phase 1 validation passed: off without a DSN; on with one, no AI / httpx / pymongo integration, no tracing")
DONE.append(1)


# %% Phase 2 — a captured exception, its tags and its secrets
# The CLIs catch exceptions and turn them into exit codes, so `capture` sends them; `redact()` cleans every string
# (a known secret's value, `key=<token>`, the DSN) and the SDK's scrubber filters variables named like secrets.
def failing_call():
    token = FAKE_SECRET                                     # a variable named like a secret → [Filtered]
    note = f"retry with {FAKE_SECRET}"                      # a secret inside an ordinary variable → ***
    raise RuntimeError(f"provider refused key={FAKE_SECRET} via {FAKE_DSN} ({len(token)}, {len(note)})")


os.environ["GROQ_API_KEY"] = FAKE_SECRET                    # redact() masks the values of the known secret names
rec = Recorder()
start(rec, entry="weekly_pack:run")
monitoring.tag(thread_id="weekly_pack:check:2025-W01:1", run_as=6, unused=None)
try:
    failing_call()
except RuntimeError as exc:
    monitoring.capture(exc)
flush()
events = rec.of("event")
ev = events[0] if events else {}
value = ev.get("exception", {}).get("values", [{}])[-1]
frame_vars = value.get("stacktrace", {}).get("frames", [{}])[-1].get("vars", {})
raw = json.dumps(rec.items, default=str)
actual = {"events": len(events), "type": value.get("type"),
          "tags": {k: ev.get("tags", {}).get(k) for k in ("entry", "launched_by", "thread_id", "run_as", "unused")},
          "secret_anywhere": FAKE_SECRET in raw, "dsn_anywhere": FAKE_DSN in raw,
          "message_masked": "***" in value.get("value", ""), "token_var": frame_vars.get("token"),
          "note_var_masked": "***" in str(frame_vars.get("note")), "user_ip": "ip_address" in ev.get("user", {})}
expected = {"events": 1, "type": "RuntimeError",
            "tags": {"entry": "weekly_pack:run", "launched_by": "check", "thread_id": "weekly_pack:check:2025-W01:1",
                     "run_as": "6", "unused": None},
            "secret_anywhere": False, "dsn_anywhere": False, "message_masked": True, "token_var": "[Filtered]",
            "note_var_masked": True, "user_ip": False}
assert actual == expected, {k: (actual[k], expected[k]) for k in actual if actual[k] != expected[k]}
print(f"Phase 2: message {value.get('value')!r}")
print("✅ Phase 2 validation passed: one event with entry / launched_by / thread_id / run_as; the secret and the DSN "
      "never leave the process")
DONE.append(2)

# %% Phase 3 — logging: breadcrumbs, Sentry logs, events
# INFO only enriches a later event; WARNING is a Sentry log (owner's O4: the 503s and quota warnings show there);
# ERROR is both a log and an event.
rec = Recorder()
start(rec)
log.info("info line (breadcrumb)")
log.warning("provider 503, retry with key=%s", FAKE_SECRET)
log.error("pack stopped (check)")
flush()
events, logs = rec.of("event"), rec.logs()
crumbs = [b.get("message") for b in (events[0].get("breadcrumbs", {}).get("values", []) if events else [])]
actual = {"events": [e.get("logentry", {}).get("formatted") or e.get("message") for e in events],
          "log_levels": sorted(x.get("level") for x in logs),
          "info_logged": any("info line" in x.get("body", "") for x in logs),
          "info_breadcrumb": "info line (breadcrumb)" in crumbs,
          "warning_masked": any("key=***" in x.get("body", "") for x in logs),
          "secret_anywhere": FAKE_SECRET in json.dumps(rec.items, default=str)}
expected = {"events": ["pack stopped (check)"], "log_levels": ["error", "warn"], "info_logged": False,
            "info_breadcrumb": True, "warning_masked": True, "secret_anywhere": False}
assert actual == expected, {k: (actual[k], expected[k]) for k in actual if actual[k] != expected[k]}
print(f"Phase 3: {len(logs)} logs, {len(events)} event, breadcrumbs {crumbs}")
print("✅ Phase 3 validation passed: INFO → breadcrumb, WARNING → log, ERROR → log + event; log bodies redacted")
DONE.append(3)


# %% Phase 4 — cron check-ins, then the real CLIs' scheduled firings
# The SDK upserts the monitor from the config sent with each check-in (no UI step). A firing's exit code decides
# ok / error; an exception is `error` and propagates. Then the CLIs end to end with a probe that raises: the firing's
# own `except` records the error, `capture` sends it, and the pack's cron reports `error`.
def checkins(r: Recorder) -> list[tuple]:
    return [(c["monitor_slug"], c["status"], c.get("monitor_config") == monitoring.WEEKLY_PACK_MONITOR)
            for c in r.of("check_in")]


cases = {}
for name, code in (("ok", 0), ("exit_2", 2)):
    rec = Recorder()
    start(rec)
    with monitoring.cron(monitoring.CRON_WEEKLY_PACK) as res:
        res["exit"] = code
    flush()
    ids = {c["check_in_id"] for c in rec.of("check_in")}
    cases[name] = (checkins(rec), len(ids), all(c.get("duration") is not None for c in rec.of("check_in")[1:]))
rec = Recorder()
start(rec)
try:
    with monitoring.cron(monitoring.CRON_WEEKLY_PACK):
        raise ValueError("firing crashed (check)")
except ValueError:
    cases["exception_propagated"] = True
flush()
cases["exception"] = (checkins(rec), len({c["check_in_id"] for c in rec.of("check_in")}), True)


def failing_probe():
    raise RuntimeError("database probe failed (Monitoring_check)")


clis = {}
ARGV = list(sys.argv)                                       # restored after each CLI: Sentry's argv integration reads it
for stem in ("Weekly_pack", "Voyage_watch"):
    cli = load_cli(stem)
    cli.LOG = TMP / stem                                    # the firing's lock + jsonl go to the temp folder
    cli.probe = failing_probe
    rec = Recorder()
    sentry_sdk.get_isolation_scope().clear()
    sentry_sdk.get_current_scope().clear()
    os.environ["SENTRY_DSN"] = FAKE_DSN
    real_init = monitoring.init
    monitoring.init = lambda entry, launched_by="cli", rec=rec: real_init(entry, launched_by, transport=rec)
    sys.argv = [f"{stem}.py", "scheduled", "--as", "6"]
    try:
        cli.main()
        code = None
    except SystemExit as stop:
        code = stop.code
    finally:
        monitoring.init = real_init
        sys.argv = ARGV
    flush()
    ev = rec.of("event")
    jsonl = (TMP / stem / ("scheduled.jsonl" if stem == "Weekly_pack" else "voyage_watch.jsonl"))
    clis[stem] = {"exit": code, "checkins": checkins(rec),
                  "event": [(e["exception"]["values"][-1]["type"], e["tags"].get("entry"), e["tags"].get("launched_by"))
                            for e in ev],
                  "jsonl_exit": json.loads(jsonl.read_text(encoding="utf-8").splitlines()[-1])["exit"]}
actual = {"cases": cases, "clis": clis}
W = monitoring.CRON_WEEKLY_PACK
expected = {"cases": {"ok": ([(W, "in_progress", True), (W, "ok", True)], 1, True),
                      "exit_2": ([(W, "in_progress", True), (W, "error", True)], 1, True),
                      "exception_propagated": True,
                      "exception": ([(W, "in_progress", True), (W, "error", True)], 1, True)},
            "clis": {"Weekly_pack": {"exit": 1, "checkins": [(W, "in_progress", True), (W, "error", True)],
                                     "event": [("RuntimeError", "weekly_pack:scheduled", "task_scheduler")],
                                     "jsonl_exit": 1},
                     "Voyage_watch": {"exit": 1, "checkins": [],
                                      "event": [("RuntimeError", "voyage_watch:scheduled", "task_scheduler")],
                                      "jsonl_exit": 1}}}
assert actual == expected, json.dumps(actual, default=str)[:1500]
print(f"Phase 4: cases {list(cases)}; CLIs {[(k, v['exit'], len(v['checkins'])) for k, v in clis.items()]}")
print("✅ Phase 4 validation passed: in_progress → ok / error with the monitor config; the pack's scheduled firing "
      "reports its error to the cron and the exception; the voyage watch sends the exception only")
DONE.append(4)

# %% Phase 5 — a Sentry failure never fails a run
# A transport that raises (the network down) and an `init` that raises (a broken SDK) must leave the run's own result.
rec = Recorder(fail=True)
start(rec)
monitoring.capture(RuntimeError("sent to a refusing transport"))
with monitoring.cron(monitoring.CRON_WEEKLY_PACK) as res:
    res["exit"] = 0
log.error("an error log on a refusing transport")
flush()                                                     # sentry_sdk.flush raises here; monitoring.flush does not
start(Recorder())                                           # a working client again before the broken init
real = sentry_sdk.init


def broken_init(**_kw):
    raise OSError("broken SDK (Monitoring_check)")


sentry_sdk.init = broken_init
try:
    os.environ["SENTRY_DSN"] = FAKE_DSN
    broken = monitoring.init(entry="check")
finally:
    sentry_sdk.init = real
actual = {"run_finished": True, "init_after_broken": broken, "is_on": monitoring.is_on()}
expected = {"run_finished": True, "init_after_broken": False, "is_on": False}
assert actual == expected, actual
print("✅ Phase 5 validation passed: a refusing transport and a broken init leave the run alone (monitoring off)")
DONE.append(5)

# %% Phase 6 — live: one event and one log, read back through the Sentry MCP
# Only with MONITORING_LIVE=1 and the owner's DSN (each run spends one of the plan's 5k errors). No check-in.
if os.environ.get("MONITORING_LIVE") == "1" and LIVE_DSN:
    run_id = uuid.uuid4().hex[:12]
    sentry_sdk.get_isolation_scope().clear()
    sentry_sdk.get_current_scope().clear()
    os.environ["SENTRY_DSN"] = LIVE_DSN
    os.environ["GROQ_API_KEY"] = FAKE_SECRET
    assert monitoring.init(entry="monitoring_check:live", launched_by="check")
    monitoring.tag(check_run=run_id, thread_id=f"monitoring_check:{run_id}")
    log.warning("Monitoring_check live log %s key=%s", run_id, FAKE_SECRET)
    try:
        raise RuntimeError(f"Monitoring_check live test {run_id}")
    except RuntimeError as exc:
        monitoring.capture(exc)
    sentry_sdk.flush(timeout=10)
    print(f"Phase 6: sent one event + one log with check_run={run_id} to project python "
          f"(read back: Sentry MCP, issue 'Monitoring_check live test {run_id}')")
    print("✅ Phase 6 validation passed: sent (the read-back is Claude's, through the Sentry MCP)")
    DONE.append(6)
else:
    print("Phase 6: pending (MONITORING_LIVE=1 and SENTRY_DSN in .env)")

# %% Final Checkpoint
# Narrative: pipelines/checkpoints/agents/Monitoring_check.md (every step, its problems and their fixes).
PHASES = {1: "off and on", 2: "captured exception + secrets", 3: "logging", 4: "cron + scheduled CLIs",
          5: "failures never fail a run", 6: "live event + log (needs MONITORING_LIVE=1 + SENTRY_DSN)"}
sentry_sdk.get_client().close()
pending = [f"{k} {v}" for k, v in PHASES.items() if k not in DONE]
assert DONE == sorted(DONE) and set(DONE) <= set(PHASES)
print(f"Final Checkpoint: done {DONE}; pending: {pending}")
print(f"✅ Final Checkpoint: {len(DONE)} / {len(PHASES)} phases passed")
