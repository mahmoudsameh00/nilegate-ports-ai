"""Check the agents' checkpointer login (member of agent_writer, migration 016) from the host: password login through
the published port, search_path = agent_state, the checkpoint tables readable and writable (inside a rolled-back
transaction), and everything else refused — DDL, TRUNCATE, DROP, other schemas. Prints no credentials.
Run after Checkpointer_setup.py (the tables must exist):

    uv run python db/check_agent_user.py
"""
import os
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())
e = os.environ
if not e.get("PG_AGENT_USER") or not e.get("PG_AGENT_PASSWORD"):
    raise SystemExit("PG_AGENT_USER / PG_AGENT_PASSWORD missing in .env: run db\\create_agent_user.ps1 first")

results = []
denied = psycopg.errors.InsufficientPrivilege


def refused(label: str, sql: str, expected=denied) -> None:
    try:
        with conn.transaction():
            conn.execute(sql)
        results.append((label, False, "ACCEPTED"))
    except expected as ex:
        results.append((label, True, type(ex).__name__))


class Rollback(Exception):
    pass


with psycopg.connect(host=e["PGHOST"], port=e["PGPORT"], dbname=e["PGDATABASE"], user=e["PG_AGENT_USER"],
                     password=e["PG_AGENT_PASSWORD"], autocommit=True) as conn:
    sp = conn.execute("SHOW search_path").fetchone()[0]
    results.append(("search_path = agent_state", sp == "agent_state", sp))
    tables = [r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'agent_state' "
                                         "ORDER BY 1").fetchall()]
    results.append(("checkpoint tables exist (setup done)", "checkpoints" in tables, ", ".join(tables) or "none"))
    n = conn.execute("SELECT count(*) FROM checkpoints").fetchone()[0]
    results.append(("select agent_state.checkpoints", True, f"{n} rows"))
    # one write cycle on the real table, rolled back: the runtime needs INSERT / UPDATE / DELETE
    try:
        with conn.transaction():
            conn.execute("INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id, checkpoint, metadata) "
                         "VALUES ('check_agent_user', '', 'c1', '{}'::jsonb, '{}'::jsonb)")
            conn.execute("UPDATE checkpoints SET metadata = '{\"x\": 1}'::jsonb WHERE thread_id = 'check_agent_user'")
            gone = conn.execute("DELETE FROM checkpoints WHERE thread_id = 'check_agent_user'").rowcount
            results.append(("insert / update / delete agent_state.checkpoints", gone == 1, f"{gone} row, rolled back"))
            raise Rollback
    except Rollback:
        pass
    refused("create table in agent_state refused", "CREATE TABLE agent_state.x (i int)")
    refused("create schema refused", "CREATE SCHEMA x")
    refused("truncate agent_state.checkpoints refused", "TRUNCATE agent_state.checkpoints")
    refused("drop agent_state.checkpoints refused", "DROP TABLE agent_state.checkpoints")
    refused("alter agent_state.checkpoints refused", "ALTER TABLE agent_state.checkpoints ADD COLUMN x int")
    for table in ["public.employees", "public.invoices", "finance.kpi_weekly", "finance_test.invoices"]:
        refused(f"select {table} refused", f"SELECT 1 FROM {table} LIMIT 1")
    refused("create table in public refused", "CREATE TABLE public.x (i int)")
for label, ok, detail in results:
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {detail}")
raise SystemExit(0 if all(ok for _, ok, _ in results) else 1)
