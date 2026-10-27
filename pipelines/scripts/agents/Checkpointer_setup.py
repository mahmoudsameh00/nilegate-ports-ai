"""Deployment step: create (or migrate) the LangGraph checkpoint tables in schema agent_state (Agents plan §5b S4,
P5-3, D3).

Run:     uv run python tools/run.py pipelines/scripts/agents/Checkpointer_setup.py  (from the project root; after
         migration 016; again after an upgrade of langgraph-checkpoint-postgres)
Reads:   .env (the owner account PGUSER / PGPASSWORD).
Writes:  the tables of PostgresSaver.setup() in schema agent_state (owner postgres; its own migration table records
         what it applied). Nothing else: the script checks that no table appears outside agent_state.
Re-run:  safe — setup() applies only the library migrations not yet recorded (the second run changes nothing).

Why the owner account and not the runtime login: agent_writer has DML only (no DDL), so the code that runs every
pack cannot change the schema; the grants on the new tables come from the default privileges of migration 016
(FOR ROLE postgres), so this script must run as postgres — it refuses any other account.
"""
import sys
from pathlib import Path

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())
sys.path.insert(0, str(ROOT))
from pipelines.agents import checkpointer  # noqa: E402

TABLES_SQL = ("SELECT n.nspname AS schema, c.relname AS name, pg_get_userbyid(c.relowner) AS owner "
              "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE c.relkind = 'r' "
              "AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast') ORDER BY 1, 2")
GRANTS_SQL = ("SELECT c.relname AS name, has_table_privilege('agent_writer', c.oid, 'SELECT') AS s, "
              "has_table_privilege('agent_writer', c.oid, 'INSERT') AS i, "
              "has_table_privilege('agent_writer', c.oid, 'UPDATE') AS u, "
              "has_table_privilege('agent_writer', c.oid, 'DELETE') AS d, "
              "has_table_privilege('agent_writer', c.oid, 'TRUNCATE') AS t, "
              "has_table_privilege('ports_readonly', c.oid, 'SELECT') AS ro, "
              "has_table_privilege('finance_bi', c.oid, 'SELECT') AS bi "
              "FROM pg_class c WHERE c.relnamespace = 'agent_state'::regnamespace AND c.relkind = 'r' ORDER BY 1")


def main() -> None:
    with psycopg.connect(checkpointer.conninfo("PGUSER", "PGPASSWORD"), autocommit=True, prepare_threshold=0,
                         row_factory=dict_row) as conn:
        who = conn.execute("SELECT current_user AS u, current_schema() AS s, "
                           "to_regnamespace('agent_state') IS NOT NULL AS schema_ok").fetchone()
        assert who["schema_ok"], "schema agent_state is missing: apply db/migrations/016_agent_state.sql first"
        assert who["u"] == "postgres", f"run as postgres (the default privileges are FOR ROLE postgres), not {who['u']}"
        assert who["s"] == "agent_state", f"search_path must put agent_state first, got {who['s']}"
        before = {(r["schema"], r["name"]) for r in conn.execute(TABLES_SQL).fetchall()}
        PostgresSaver(conn).setup()
        after = conn.execute(TABLES_SQL).fetchall()
        new = sorted({(r["schema"], r["name"]) for r in after} - before)
        mine = [r for r in after if r["schema"] == "agent_state"]
        grants = conn.execute(GRANTS_SQL).fetchall()
        cols = {r["name"]: [c["column_name"] for c in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = 'agent_state' "
            "AND table_name = %s ORDER BY ordinal_position", (r["name"],)).fetchall()] for r in mine}
        applied = conn.execute("SELECT count(*) AS n FROM agent_state.checkpoint_migrations").fetchone()["n"]
    outside = [t for t in new if t[0] != "agent_state"]
    assert not outside, f"setup() created tables outside agent_state: {outside}"
    assert mine and all(r["owner"] == "postgres" for r in mine), mine
    bad = [g["name"] for g in grants if not (g["s"] and g["i"] and g["u"] and g["d"]) or g["t"] or g["ro"] or g["bi"]]
    assert not bad, f"unexpected privileges on {bad} (agent_writer DML only; no TRUNCATE; no ports_readonly / finance_bi)"
    print(f"tables created this run: {[t[1] for t in new]}; library migrations recorded: {applied}")
    for name, c in cols.items():
        print(f"  agent_state.{name}: {', '.join(c)}")
    print(f"✅ Checkpointer setup: {len(mine)} tables in agent_state (owner postgres), agent_writer DML only, "
          "nothing for ports_readonly / finance_bi, nothing outside the schema")


if __name__ == "__main__":
    main()
