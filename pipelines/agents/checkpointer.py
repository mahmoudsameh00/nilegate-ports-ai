"""The LangGraph checkpointer of the agents (Agents plan §5b S4–S5, D3, P5-3): PostgresSaver on schema agent_state.

- Runtime login `PG_AGENT_USER` (member of agent_writer, migration 016): DML on the checkpoint tables only, no DDL —
  so `setup()` is never called here; it is a deployment step (`pipelines/scripts/agents/Checkpointer_setup.py`, as
  the owner account). A missing table raises with that instruction instead of a half-initialised store.
- One `psycopg_pool.ConnectionPool` per process with what PostgresSaver requires (autocommit, `dict_row`,
  `prepare_threshold=0`); `search_path = agent_state` is set by the login and again on every connection.
- Separate from the tools' read-only pool (`tools/db.py`): the tools can never write, the checkpointer can write
  only its own schema.
"""
import atexit
import os

from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from pipelines.lib.common import load_env

SCHEMA = "agent_state"
POOL_MAX = 2                 # one pack runs its steps one after another
CONNECT_TIMEOUT_S = 5


class NotSetUp(RuntimeError):
    pass


def conninfo(user_var: str, password_var: str) -> str:
    load_env()
    e = os.environ
    return make_conninfo(host=e["PGHOST"], port=e["PGPORT"], dbname=e["PGDATABASE"], user=e[user_var],
                         password=e[password_var], connect_timeout=CONNECT_TIMEOUT_S,
                         options=f"-c search_path={SCHEMA}")


_pool: ConnectionPool | None = None


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(conninfo("PG_AGENT_USER", "PG_AGENT_PASSWORD"), min_size=1, max_size=POOL_MAX,
                               open=True, kwargs={"autocommit": True, "prepare_threshold": 0,
                                                  "row_factory": dict_row})
        atexit.register(close)
    return _pool


def close() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def saver() -> PostgresSaver:
    with pool().connection() as conn:
        missing = conn.execute(f"SELECT to_regclass('{SCHEMA}.checkpoints') IS NULL AS missing").fetchone()["missing"]
    if missing:
        raise NotSetUp(f"{SCHEMA}.checkpoints does not exist: run "
                       "`uv run python pipelines/scripts/agents/Checkpointer_setup.py` (owner account) first")
    return PostgresSaver(pool())
