"""Read-only PostgreSQL access for the agent tools (Agents plan §5a, D10, ADR-034).

One `psycopg_pool.ConnectionPool` per process on the read-only login `PG_RO_USER` (member of `ports_readonly`), every
session with `default_transaction_read_only = on`: a tool cannot write even if a query were wrong. Queries are
parameterized only; the tools never build SQL from model text.

Numbers: the finance views round once at the end (money 2 decimals, percent 2, days 1; ADR-047), so a NUMERIC is
returned as a float, whose shortest repr is the view's value (8394785.98 stays 8394785.98). Dates stay `date`.
"""
import atexit
import os
from decimal import Decimal

from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from pipelines.lib.common import load_env

POOL_MAX = 4          # one pack runs its steps one after another; the supervisor may call a few tools at once
CONNECT_TIMEOUT_S = 5

_pool: ConnectionPool | None = None


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        load_env()
        e = os.environ
        conninfo = make_conninfo(host=e["PGHOST"], port=e["PGPORT"], dbname=e["PGDATABASE"], user=e["PG_RO_USER"],
                                 password=e["PG_RO_PASSWORD"], connect_timeout=CONNECT_TIMEOUT_S,
                                 options="-c default_transaction_read_only=on")
        _pool = ConnectionPool(conninfo, min_size=1, max_size=POOL_MAX, open=True,
                               kwargs={"row_factory": dict_row, "autocommit": True})
        atexit.register(close)
    return _pool


def close() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def _plain(v):
    return float(v) if isinstance(v, Decimal) else v


def fetch(sql: str, params: tuple | dict = (), exact: bool = False) -> list[dict]:
    """Rows of one parameterized SELECT as dicts (NUMERIC → float; `exact=True` keeps Decimal for arithmetic)."""
    with pool().connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return rows if exact else [{k: _plain(v) for k, v in row.items()} for row in rows]
