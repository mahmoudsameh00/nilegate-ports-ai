"""Read-only MongoDB access for the agent tools (Agents plan §6a P9-6, ADR-027, ADR-031).

One `MongoClient` per process on the read-only user `MONGO_RO_USER` (role `read` on the project database only,
`db/mongo/005_create_reader_user.js`): a tool cannot write even if a query were wrong — the loader's app user stays
the only writer (ADR-031). Queries are fixed shapes with typed values only; the tools never build a filter from
model text. Datetimes come back timezone-aware (UTC).
"""
import atexit
import os

from pymongo import MongoClient
from pymongo.database import Database

from pipelines.lib.common import load_env

TIMEOUT_MS = 5000      # server selection / connect: a stopped container fails fast instead of holding a run up

_client: MongoClient | None = None


def database() -> Database:
    global _client
    if _client is None:
        load_env()
        e = os.environ
        _client = MongoClient(host=e["MONGO_HOST"], port=int(e["MONGO_PORT"]), username=e["MONGO_RO_USER"],
                              password=e["MONGO_RO_PASSWORD"], authSource=e["MONGO_AUTH_SOURCE"], tz_aware=True,
                              serverSelectionTimeoutMS=TIMEOUT_MS, connectTimeoutMS=TIMEOUT_MS,
                              appname="nilegate-agent-tools")
        atexit.register(close)
    return _client[os.environ["MONGO_DB"]]


def close() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None
