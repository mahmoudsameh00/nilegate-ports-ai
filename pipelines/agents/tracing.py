"""LangSmith tracing of the operator entry points (Agents plan Phase 8, §5e P8-4 / S2; D8: free developer plan).

- **On only inside `trace(...)`, and only when a key exists.** `Weekly_pack.py` opens it around `run`, `resume` and
  each scheduled firing's graph run; `Stage1_eval.py` only with `EVAL_TRACE=1` (one evaluation ≈ 400 calls); the
  checks never (except `Scheduler_check.py` Phase 5, the read-back). `.env` never sets a global switch
  (`LANGSMITH_TRACING`); `global_switch()` names one that would trace the whole process — the check asserts there is
  none.
- **One trace per graph run**, in project `nilegate-agents`, tagged with the week, the dataset, the entry point and
  who launched it (`launched_by`); the metadata carries the thread id, the attempt and the run identity (P5-5). Full inputs / outputs
  (all project data is synthetic or public, ADR-037 amendment 2). The graph config is untouched: the checkpoint
  metadata (`run_as`) stays what Phase 5 wrote.
- **A LangSmith failure never fails a run:** no key → off; an error while opening the context → off; uploads run in
  the background and the final flush swallows its errors. An exception of the run itself always propagates.
"""
import logging
import os
import re
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager

PROJECT = "nilegate-agents"
KEY_NAMES = ("LANGSMITH_API_KEY", "LANGCHAIN_API_KEY")   # .env names the first (§5e P8-4); the library reads both
SWITCHES = ("LANGSMITH_TRACING", "LANGSMITH_TRACING_V2", "LANGCHAIN_TRACING", "LANGCHAIN_TRACING_V2")
_THREAD = re.compile(r"weekly_pack:(?P<dataset>\w+):(?P<year>\d{4})-W(?P<week>\d{2}):(?P<attempt>[\w-]+)")
log = logging.getLogger(__name__)


def has_key() -> bool:
    return any(os.environ.get(k, "").strip() for k in KEY_NAMES)


def global_switch() -> str | None:
    """The environment switch that would trace every LangChain call of the process, if one is set to true."""
    return next((k for k in SWITCHES if os.environ.get(k, "").strip().lower() == "true"), None)


def labels(thread_id: str, entry: str, run_as: int | None, launched_by: str = "cli") -> tuple[list[str], dict]:
    """(tags, metadata) of one graph run, from its thread id `weekly_pack:<dataset>:<year>-W<ww>:<attempt>`.
    `launched_by` (cli / task_scheduler / check) is not called `trigger`: the graph config's own metadata (the
    checkpoint's, e.g. `trigger: scheduled` of `scheduling.fire`) wins over the tracing context's on a shared key."""
    m = _THREAD.fullmatch(thread_id)
    week = f"{m['year']}-W{m['week']}" if m else None
    dataset = m["dataset"] if m else None
    tags = (["weekly_pack", f"entry:{entry}", f"launched_by:{launched_by}"]
            + ([f"week:{week}", f"dataset:{dataset}"] if m else []))
    meta = {"thread_id": thread_id, "week": week, "attempt": m["attempt"] if m else None, "dataset": dataset,
            "run_as": run_as, "entry": entry, "launched_by": launched_by}
    return tags, meta


def _flush() -> None:
    try:
        from langchain_core.tracers.langchain import wait_for_all_tracers
        wait_for_all_tracers()
    except Exception as exc:  # noqa: BLE001 — a failed upload is logged, never raised (P8-4)
        log.warning("LangSmith flush failed: %s", type(exc).__name__)


@contextmanager
def trace(thread_id: str, *, entry: str, run_as: int | None, launched_by: str = "cli",
          extra_tags: tuple[str, ...] = ()) -> Iterator[bool]:
    """Trace the graph runs inside the block (yields True) when a key exists; else a no-op (yields False).
    `extra_tags` label runs whose thread id is not a pack's (the evaluation's golden key, a question id)."""
    from pipelines.lib.common import load_env
    load_env()                    # variables already set win: an empty LANGSMITH_API_KEY in the environment = off
    if not has_key():
        yield False
        return
    stack, on = ExitStack(), False
    try:
        from langsmith.run_helpers import tracing_context
        tags, meta = labels(thread_id, entry, run_as, launched_by)
        tags += list(extra_tags)
        stack.enter_context(tracing_context(enabled=True, project_name=PROJECT, tags=tags, metadata=meta))
        on = True
    except Exception as exc:  # noqa: BLE001 — tracing degrades to off
        log.warning("LangSmith tracing off for %s: %s", thread_id, type(exc).__name__)
        stack.close()
    if not on:                    # outside the except block: an error of the run is not chained to this one
        yield False
        return
    try:
        with stack:
            yield True
    finally:
        _flush()
