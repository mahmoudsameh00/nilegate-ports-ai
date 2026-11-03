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
- **A link per run (D-P12-11):** the block's root runs are collected; `describe()` = the CLIs' `LangSmith:` line
  with the trace's URL, so a thread in `agent_state` opens its trace in one click (same `thread_id` in the metadata).
- **A LangSmith failure never fails a run:** no key → off; an error while opening the context → off; uploads run in
  the background and the final flush swallows its errors. An exception of the run itself always propagates.
"""
import logging
import os
import re
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from typing import Any, cast

PROJECT = "nilegate-agents"
KEY_NAMES = ("LANGSMITH_API_KEY", "LANGCHAIN_API_KEY")   # .env names the first (§5e P8-4); the library reads both
SWITCHES = ("LANGSMITH_TRACING", "LANGSMITH_TRACING_V2", "LANGCHAIN_TRACING", "LANGCHAIN_TRACING_V2")
_THREAD = re.compile(r"weekly_pack:(?P<dataset>\w+):(?P<year>\d{4})-W(?P<week>\d{2}):(?P<attempt>[\w-]+)")
_last_runs: list = []   # the root runs of the latest traced block (its link: `last_url`)
log = logging.getLogger(__name__)


def has_key() -> bool:
    return any(os.environ.get(k, "").strip() for k in KEY_NAMES)


def global_switch() -> str | None:
    """The environment switch that would trace every LangChain call of the process, if one is set to true."""
    return next((k for k in SWITCHES if os.environ.get(k, "").strip().lower() == "true"), None)


def labels(thread_id: str, entry: str, run_as: int | None, launched_by: str = "cli") -> tuple[list[str], dict]:
    """(tags, metadata) of one graph run, from its thread id `weekly_pack:<dataset>:<year>-W<ww>:<attempt>`.
    Only a pack's thread id gets the `weekly_pack` / `graph:weekly_pack` tags (the other entry points name their
    graph in `extra_tags`), so a filter on either tag finds the packs alone.
    `launched_by` (cli / task_scheduler / check) is not called `trigger`: the graph config's own metadata (the
    checkpoint's, e.g. `trigger: scheduled` of `scheduling.fire`) wins over the tracing context's on a shared key."""
    m = _THREAD.fullmatch(thread_id)
    week = f"{m['year']}-W{m['week']}" if m else None
    dataset = m["dataset"] if m else None
    tags = ((["weekly_pack", "graph:weekly_pack"] if m else []) + [f"entry:{entry}", f"launched_by:{launched_by}"]
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


def last_url() -> str | None:
    """The LangSmith link of the latest traced block's first root run; None when untraced or the lookup fails.
    Two API calls (the project, the workspace) only when a CLI asks; a failure is logged, never raised.
    `Client.get_run_url` is deprecated after 2027-01-31 like `list_runs` (Scheduler_check K7): its replacement in the
    pinned langsmith 0.14.7 needs the project id first, so the call stays until a langsmith upgrade."""
    if not _last_runs:
        return None
    try:
        import warnings
        from types import SimpleNamespace
        from langsmith import Client
        client = Client()
        # the collector's copy of the run names the project `default` (not the tracer's): pass the id alone
        project_id = client.read_project(project_name=PROJECT).id
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            return client.get_run_url(run=cast(Any, SimpleNamespace(id=_last_runs[0].id)), project_id=project_id)
    except Exception as exc:  # noqa: BLE001 — a missing link never fails a run
        log.warning("LangSmith link unavailable: %s", type(exc).__name__)
        return None


def describe(traced: bool) -> str:
    """The CLIs' `LangSmith:` line: the trace's link, else the project, else off."""
    if not traced:
        return "off (no LANGSMITH_API_KEY)"
    return last_url() or f"traced in project {PROJECT} (link unavailable)"


@contextmanager
def trace(thread_id: str, *, entry: str, run_as: int | None, launched_by: str = "cli",
          extra_tags: tuple[str, ...] = ()) -> Iterator[bool]:
    """Trace the graph runs inside the block (yields True) when a key exists; else a no-op (yields False).
    `extra_tags` label runs whose thread id is not a pack's (the evaluation's golden key, a question id)."""
    from pipelines.lib.common import load_env
    load_env()                    # variables already set win: an empty LANGSMITH_API_KEY in the environment = off
    _last_runs.clear()
    if not has_key():
        yield False
        return
    stack, on, runs = ExitStack(), False, None
    try:
        from langchain_core.tracers.context import collect_runs
        from langsmith.run_helpers import tracing_context
        tags, meta = labels(thread_id, entry, run_as, launched_by)
        tags += list(extra_tags)
        stack.enter_context(tracing_context(enabled=True, project_name=PROJECT, tags=tags, metadata=meta))
        runs = stack.enter_context(collect_runs())   # the block's root runs, for `last_url`
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
        _last_runs[:] = cast(Any, runs).traced_runs
        _flush()
