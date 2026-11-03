"""Sentry error capture, logs and the weekly pack's cron monitor (Observability plan S1; free Developer plan).

- **On only inside the CLIs' `main()`, and only when `SENTRY_DSN` is set.** Checks and evaluations never call
  `init` (a planted failure must not spend the plan's 5k errors); three checks load the CLIs as modules, so nothing
  starts at import, and every other call here is a no-op until `init` succeeds.
- **No tracing, no LLM spans:** `auto_enabling_integrations=False` drops LangChain / LangGraph / OpenAI / Google
  GenAI / httpx / pymongo, which turn themselves on when their package is installed; LangSmith stays the only LLM
  tracer (ADR-054). The defaults stay: excepthook, logging, atexit, dedupe, stdlib, threading, argv, modules.
- **What is sent:** uncaught or `capture`d exceptions and ERROR logs as events; WARNING and above as Sentry Logs;
  INFO as breadcrumbs. Tags `entry`, `launched_by`, `thread_id` (the LangSmith metadata's and the `agent_state`
  thread's id: the link between the two tools), `run_as`. Every string passes `redact()` and the DSN is masked; the
  SDK's scrubber also drops variables named like secrets. An event that cannot be cleaned is dropped, never sent raw.
- **One cron monitor** (the free plan's only one, owner 2026-10-31): `Weekly_pack.py scheduled`, upserted by the SDK
  from `WEEKLY_PACK_MONITOR` on each check-in; the voyage watch sends errors only.
- **A Sentry failure never fails a run:** every call swallows its own errors; the exit flush waits ≤ 5 s.
"""
import logging
import os
import time
import tomllib
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, cast

CRON_WEEKLY_PACK = "nilegate-weekly-pack"
WEEKLY_PACK_MONITOR = {                        # the task "NileGate Weekly Finance Pack" (ADR-054)
    "schedule": {"type": "crontab", "value": "30 10 * * 1"},
    "timezone": "Africa/Cairo",
    "checkin_margin": 720,                     # minutes: the task starts when the owner logs on after a missed start
    "max_runtime": 60,                         # minutes: the task's 1 h limit
    "failure_issue_threshold": 1,
    "recovery_threshold": 1,
}
EXTRA_DENYLIST = ("dsn", "sentry_dsn", "conninfo", "pgpassword")
SHUTDOWN_TIMEOUT_S = 5
_on = False
log = logging.getLogger(__name__)


def is_on() -> bool:
    return _on


def _release() -> str:
    from pipelines.lib.common import project_root
    with open(project_root() / "pyproject.toml", "rb") as f:
        return f"nilegate-agents@{tomllib.load(f)['project']['version']}"


def _scrub(obj):
    """`redact()` on every string of an event or a log, plus the DSN itself."""
    from pipelines.lib.common import redact
    if isinstance(obj, str):
        dsn = os.environ.get("SENTRY_DSN", "")
        text = redact(obj)
        return text.replace(dsn, "***") if len(dsn) >= 8 else text
    if isinstance(obj, dict):
        return {k: _scrub(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_scrub(v) for v in obj]
    return obj


def _before_send(item, _hint):
    try:
        return _scrub(item)
    except Exception:  # noqa: BLE001 — an event that cannot be cleaned is dropped, never sent raw
        return None


def init(entry: str, launched_by: str = "cli", *, transport=None) -> bool:
    """Start Sentry for this process when `SENTRY_DSN` is set; True when on. `transport` = a check's recorder."""
    global _on
    from pipelines.lib.common import load_env
    load_env()                    # variables already set win: an empty SENTRY_DSN in the environment = off
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    _on = False
    if not dsn:
        return False
    try:
        import sentry_sdk
        from sentry_sdk.integrations.logging import LoggingIntegration
        from sentry_sdk.scrubber import DEFAULT_DENYLIST, EventScrubber
        sentry_sdk.init(
            dsn=dsn, environment=os.environ.get("SENTRY_ENVIRONMENT", "").strip() or "local", release=_release(),
            auto_enabling_integrations=False, traces_sample_rate=None, send_default_pii=False,
            include_local_variables=True, enable_logs=True, shutdown_timeout=SHUTDOWN_TIMEOUT_S,
            event_scrubber=EventScrubber(denylist=[*DEFAULT_DENYLIST, *EXTRA_DENYLIST]),
            integrations=[LoggingIntegration(level=logging.INFO, event_level=logging.ERROR,
                                             sentry_logs_level=logging.WARNING)],
            before_send=cast(Any, _before_send), before_send_log=cast(Any, _before_send), transport=transport)
        sentry_sdk.set_tag("entry", entry)
        sentry_sdk.set_tag("launched_by", launched_by)
        _on = True
    except Exception as exc:  # noqa: BLE001 — monitoring degrades to off
        log.warning("Sentry off: %s", type(exc).__name__)
    return _on


def tag(**labels) -> None:
    """Scope tags for what follows (e.g. `thread_id`, `run_as`); None values are skipped."""
    if not _on:
        return
    try:
        import sentry_sdk
        for k, v in labels.items():
            if v is not None:
                sentry_sdk.set_tag(k, str(v))
    except Exception as exc:  # noqa: BLE001
        log.warning("Sentry tag failed: %s", type(exc).__name__)


def capture(exc: BaseException) -> None:
    """An exception a CLI caught and turned into an exit code (the excepthook never sees it)."""
    if not _on:
        return
    try:
        import sentry_sdk
        sentry_sdk.capture_exception(exc)
    except Exception as err:  # noqa: BLE001
        log.warning("Sentry capture failed: %s", type(err).__name__)


def flush(timeout: float = SHUTDOWN_TIMEOUT_S) -> None:
    """Send what is queued now (the exit does it too). `sentry_sdk.flush` lets a transport's error through from the
    log batcher (Monitoring_check Phase 5): logged here, never raised."""
    if not _on:
        return
    try:
        import sentry_sdk
        sentry_sdk.flush(timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        log.warning("Sentry flush failed: %s", type(exc).__name__)


def _checkin(slug: str, status: str, check_in_id: str | None = None, duration: float | None = None) -> str | None:
    try:
        from sentry_sdk.crons import capture_checkin
        return capture_checkin(monitor_slug=slug, check_in_id=check_in_id, status=status, duration=duration,
                               monitor_config=cast(Any, WEEKLY_PACK_MONITOR if slug == CRON_WEEKLY_PACK else None))
    except Exception as exc:  # noqa: BLE001
        log.warning("Sentry check-in failed: %s", type(exc).__name__)
        return None


@contextmanager
def cron(slug: str) -> Iterator[dict]:
    """Check-ins around one scheduled firing: `in_progress`, then `ok` when the block sets `result["exit"] = 0`,
    else `error` (a non-zero exit code or an exception, which propagates)."""
    result = {"exit": None}
    if not _on:
        yield result
        return
    t0, cid = time.monotonic(), _checkin(slug, "in_progress")
    try:
        yield result
    except BaseException:
        _checkin(slug, "error", cid, time.monotonic() - t0)
        raise
    _checkin(slug, "ok" if result["exit"] == 0 else "error", cid, time.monotonic() - t0)
