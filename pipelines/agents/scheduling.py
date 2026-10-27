"""Scheduled weekly packs (Agents plan Phase 8, §5e): which week a firing makes, checkpoint retention, the G5 report.

- **Week picker (P8-1, D12 replay of 2025):** the week after the highest *settled* week (published, or skipped after
  `MAX_ATTEMPTS` attempts that ended without a deck); one pending pack at a time — a thread waiting at the approval
  means "wait"; a thread stopped mid-run (an exception, e.g. a quota: ADR-050 (6)) is resumed before anything new.
- **Retention (P8-3, D3):** a thread that ended and whose last checkpoint is older than `RETENTION_DAYS` is first
  appended to the archive (status, stop reason, approval log, run identity), then deleted with
  `PostgresSaver.delete_thread` (agent_writer's DELETE). A thread waiting at the approval is never deleted.
- **G5 report:** approve / edit / reject counts and the edited slides, from the threads still in agent_state, the
  archive and the published folders (one entry per thread) — reported, never scored.
Everything here takes the compiled graph (its checkpointer) and paths as arguments, so the check runs it on a
temporary thread prefix and a temporary folder.
"""
import json
import os
import re
import subprocess
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPORT_YEAR = 2025
LIVE_PREFIX = f"weekly_pack:live:{REPORT_YEAR}-W"
WEEKS = 52
MAX_ATTEMPTS = 2                 # P8-1: a week whose attempt stopped is retried once, then skipped
RETENTION_DAYS = 30              # P8-3
STALE_PENDING_DAYS = 14          # P8-3: a pack waiting longer is reported (never deleted)
ENDED = ("published", "rejected", "not_ready", "not_permitted", "output_invalid", "validation_failed")
LOG_DIR = "_log"                 # under reports/ (git-ignored): scheduled.jsonl, threads_archive.jsonl


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def allowed_run_as(user) -> bool:
    """P5-5: a scheduled pack runs as a Finance manager — not the CEO (level 3 data), not an employee."""
    return user is not None and (user.role, user.department) == ("manager", "Finance")


# --- threads ---------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class ThreadInfo:
    thread_id: str
    week: int
    attempt: int
    state: str                   # pending (at the approval) | ended | stalled (stopped mid-run, resumable)
    status: str | None
    last_at: datetime            # the last checkpoint
    run_as: int | None


def parse_thread(thread_id: str, prefix: str) -> tuple[int, int] | None:
    """(week, attempt) of `<prefix><ww>:<attempt>`; other ids (e.g. a check's `…:check-1a2b`) are not ours."""
    m = re.fullmatch(re.escape(prefix) + r"(\d{2}):(\d+)", thread_id)
    return (int(m[1]), int(m[2])) if m else None


def thread_ids(pool, prefix: str) -> list[str]:
    """Every thread id in agent_state that starts with `prefix` (the checkpointer's pool: login ports_agent)."""
    with pool.connection() as conn:
        rows = conn.execute("SELECT DISTINCT thread_id FROM checkpoints WHERE thread_id LIKE %s ORDER BY 1",
                            (prefix.replace("_", r"\_") + "%",)).fetchall()
    return [r["thread_id"] for r in rows]


def run_as_of(g, cfg) -> int | None:
    """The employee who started the thread (checkpoint metadata, P5-5) — never the approver."""
    return next((s.metadata.get("run_as") for s in g.get_state_history(cfg) if s.metadata.get("run_as")), None)


def describe(g, thread_id: str, prefix: str) -> ThreadInfo | None:
    parsed = parse_thread(thread_id, prefix)
    if parsed is None:
        return None
    cfg = {"configurable": {"thread_id": thread_id}}
    snap = g.get_state(cfg)
    state = "pending" if "approval" in snap.next else ("ended" if not snap.next else "stalled")
    return ThreadInfo(thread_id, *parsed, state=state, status=snap.values.get("status"),
                      last_at=datetime.fromisoformat(snap.created_at), run_as=run_as_of(g, cfg))


def describe_all(g, pool, prefix: str = LIVE_PREFIX) -> list[ThreadInfo]:
    return [i for t in thread_ids(pool, prefix) if (i := describe(g, t, prefix)) is not None]


# --- the week picker (P8-1) ------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Decision:
    action: str                  # wait | resume | start | done
    week: int | None
    thread_id: str | None
    reason: str
    skipped: list[int] = field(default_factory=list)


def plan(infos: list[ThreadInfo], prefix: str = LIVE_PREFIX) -> Decision:
    by_week = lambda xs: sorted(xs, key=lambda i: (i.week, i.attempt))  # noqa: E731
    pending = by_week(i for i in infos if i.state == "pending")
    if pending:
        p = pending[0]
        return Decision("wait", p.week, p.thread_id, f"W{p.week:02d} waits for approval since {p.last_at:%Y-%m-%d}")
    stalled = by_week(i for i in infos if i.state == "stalled")
    if stalled:
        s = stalled[0]
        return Decision("resume", s.week, s.thread_id, f"W{s.week:02d} stopped mid-run; resumed from its checkpoint")
    ended = [i for i in infos if i.state == "ended"]
    published = {i.week for i in ended if i.status == "published"}
    stops = Counter(i.week for i in ended if i.status != "published")
    skipped = sorted(w for w, n in stops.items() if n >= MAX_ATTEMPTS and w not in published)
    week = max(published | set(skipped), default=0) + 1
    skipped = [w for w in skipped if w < week]
    if week > WEEKS:
        return Decision("done", None, None, f"the replay of {REPORT_YEAR} is complete", skipped)
    attempt = max((i.attempt for i in infos if i.week == week), default=0) + 1
    last = by_week(i for i in ended if i.week == week)
    why = f"retry after {last[-1].status}" if last else "next week of the replay"
    return Decision("start", week, f"{prefix}{week:02d}:{attempt}", why, skipped)


# --- retention (P8-3) ------------------------------------------------------------------------------------------------

def archive_record(g, info: ThreadInfo, at: datetime) -> dict:
    v = g.get_state({"configurable": {"thread_id": info.thread_id}}).values
    return {"thread_id": info.thread_id, "report_week": info.week, "attempt": info.attempt, "status": info.status,
            "stop_reason": v.get("stop_reason"), "approval_log": v.get("approval_log") or [],
            "normalized": v.get("normalized") or [],
            "published": v.get("published"), "run_as": info.run_as, "last_checkpoint_at": info.last_at.isoformat(),
            "archived_at": at.isoformat(timespec="seconds"), "retention_days": RETENTION_DAYS}


def append_jsonl(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str) + "\n")
        f.flush()
        os.fsync(f.fileno())     # the record is on disk before its thread is deleted


def prune(g, saver, infos: list[ThreadInfo], archive: Path, now: datetime | None = None,
          dry_run: bool = False) -> dict:
    """Archive, then delete ended threads older than RETENTION_DAYS; report stale pending / stalled ones."""
    now = now or now_utc()
    old = lambda i, days: now - i.last_at > timedelta(days=days)  # noqa: E731
    out = {"deleted": [], "would_delete": [], "stale_pending": [], "stale_stalled": [], "kept": 0}
    for i in sorted(infos, key=lambda i: i.thread_id):
        if i.state == "ended" and old(i, RETENTION_DAYS):
            if dry_run:
                out["would_delete"].append(i.thread_id)
                continue
            append_jsonl(archive, archive_record(g, i, now))
            saver.delete_thread(i.thread_id)
            out["deleted"].append(i.thread_id)
            continue
        if i.state != "ended" and old(i, STALE_PENDING_DAYS):
            out["stale_pending" if i.state == "pending" else "stale_stalled"].append(i.thread_id)
        out["kept"] += 1
    return out


# --- G5 report -------------------------------------------------------------------------------------------------------

def approval_report(entries: list[dict]) -> dict:
    """entries: {thread_id, status, approval_log, normalized}, one per thread. A pack is *decided* once it is
    published or rejected; its edits count whatever came after them. `form_fixes` = the slot-form fixes code made on
    the Writer's text (D-P7-14), so model form errors stay visible although they no longer stop a pack."""
    decided = [e for e in entries if e["status"] in ("published", "rejected")]
    fixes = [len(e.get("normalized") or []) for e in entries]
    edited = [e for e in decided if any(x.get("outcome") == "edited" for x in e["approval_log"])]
    slides = Counter(d["slide"] for e in entries for x in e["approval_log"] if x.get("outcome") == "edited"
                     for d in x.get("diff") or [])
    outcomes = Counter(x.get("outcome") for e in entries for x in e["approval_log"])
    return {"packs_decided": len(decided), "published": sum(e["status"] == "published" for e in decided),
            "rejected": sum(e["status"] == "rejected" for e in decided), "packs_edited": len(edited),
            "edit_rate": round(len(edited) / len(decided), 3) if decided else None,
            "decisions": dict(sorted(outcomes.items())), "edited_slides": dict(sorted(slides.items())),
            "form_fixes": {"packs": sum(n > 0 for n in fixes), "fixes": sum(fixes)},
            "threads": sorted(e["thread_id"] for e in entries)}


def report_entries(g, infos: list[ThreadInfo], reports_dir: Path) -> list[dict]:
    """One entry per thread: agent_state first, then the archive, then the published folders (older packs)."""
    seen: dict[str, dict] = {}
    for i in infos:
        v = g.get_state({"configurable": {"thread_id": i.thread_id}}).values
        seen[i.thread_id] = {"thread_id": i.thread_id, "status": i.status, "approval_log": v.get("approval_log") or [],
                             "normalized": v.get("normalized") or []}
    arch = reports_dir / LOG_DIR / "threads_archive.jsonl"
    if arch.exists():
        for line in arch.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            seen.setdefault(r["thread_id"], {"thread_id": r["thread_id"], "status": r["status"],
                                             "approval_log": r["approval_log"], "normalized": r.get("normalized") or []})
    for run in sorted(reports_dir.glob(f"{REPORT_YEAR}-W*/run.json")):
        r = json.loads(run.read_text(encoding="utf-8"))
        log = json.loads((run.parent / "approval.json").read_text(encoding="utf-8"))
        seen.setdefault(r["thread_id"], {"thread_id": r["thread_id"], "status": "published", "approval_log": log,
                                         "normalized": r.get("normalized") or []})
    return list(seen.values())


# --- the scheduled firing's side effects -----------------------------------------------------------------------------

_TOAST = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(
    [Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$n = $t.GetElementsByTagName('text')
$n.Item(0).AppendChild($t.CreateTextNode($env:NG_TOAST_TITLE)) > $null
$n.Item(1).AppendChild($t.CreateTextNode($env:NG_TOAST_TEXT)) > $null
$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show(
    [Windows.UI.Notifications.ToastNotification]::new($t))
"""


def toast(title: str, text: str) -> bool:
    """A Windows toast through the built-in WinRT API (P8-2; no module). The texts travel as environment variables,
    never inside the command. A failure is reported, never raised: the log line is the record."""
    try:
        r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _TOAST], timeout=30,
                           capture_output=True, env={**os.environ, "NG_TOAST_TITLE": title, "NG_TOAST_TEXT": text})
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def as_log(obj) -> dict:
    return asdict(obj) if hasattr(obj, "__dataclass_fields__") else obj


def fire(g, saver, pool, user, reports_dir: Path, prefix: str = LIVE_PREFIX, notify: bool = True,
         now: datetime | None = None, tracer=None) -> dict:
    """One scheduled firing: plan → start / resume / wait / done → retention. `user` = the scheduled run identity
    (a Finance manager, P5-5); a resumed thread keeps the identity it started with. `tracer(thread_id, run_as)` → a
    context manager around the graph run (LangSmith, `tracing.trace`; None = untraced). Returns the log record; an
    exception inside the pack (e.g. a quota) propagates — the thread waits at its checkpoint for the next firing."""
    from contextlib import nullcontext

    from pipelines.agents.tools.context import RunContext, load_user

    d = plan(describe_all(g, pool, prefix), prefix)
    rec = {"decision": as_log(d)}
    if d.action in ("start", "resume"):
        cfg = {"configurable": {"thread_id": d.thread_id}}
        if d.action == "start":
            cfg["metadata"] = {"run_as": user.employee_id, "trigger": "scheduled"}
            run_as = user.employee_id
            inp, ctx = {"report_week": d.week}, RunContext(user)
        else:
            run_as = run_as_of(g, cfg) or user.employee_id
            inp, ctx = None, RunContext(load_user(run_as))
        with tracer(d.thread_id, run_as) if tracer else nullcontext() as traced:
            for _ in g.stream(inp, cfg, context=ctx, stream_mode="updates", durability="sync"):
                pass
        rec["traced"] = bool(traced)
        after = describe(g, d.thread_id, prefix)
        rec["result"] = {"thread_id": d.thread_id, "state": after.state, "status": after.status}
    pending = rec.get("result", {}).get("state") == "pending" or d.action == "wait"
    if pending and notify:
        rec["toast"] = toast("NileGate Weekly Finance Pack",
                             f"{REPORT_YEAR}-W{d.week:02d} waits for your approval ({d.thread_id})")
    rec["retention"] = prune(g, saver, describe_all(g, pool, prefix), reports_dir / LOG_DIR / "threads_archive.jsonl",
                             now=now)
    return rec
