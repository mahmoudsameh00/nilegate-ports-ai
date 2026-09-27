"""Check the read-only PostgreSQL user (ADR-034) from the host: password login through the published port, SELECT works,
every write is refused, and the superuser credentials are not needed. Prints no credentials.

    uv run python db/check_readonly_user.py
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
if not e.get("PG_RO_USER") or not e.get("PG_RO_PASSWORD"):
    raise SystemExit("PG_RO_USER / PG_RO_PASSWORD missing in .env: run db\\create_readonly_user.ps1 first")

results = []
with psycopg.connect(host=e["PGHOST"], port=e["PGPORT"], dbname=e["PGDATABASE"], user=e["PG_RO_USER"],
                     password=e["PG_RO_PASSWORD"], autocommit=True) as conn:
    n = conn.execute("SELECT count(*) FROM vessels").fetchone()[0]
    results.append(("select vessels", n == 500, f"{n} rows"))
    ro = conn.execute("SHOW default_transaction_read_only").fetchone()[0]
    results.append(("session read-only by default", ro == "on", ro))
    expected = (psycopg.errors.ReadOnlySqlTransaction, psycopg.errors.InsufficientPrivilege)
    cases = [("update vessels", "UPDATE vessels SET status = status WHERE vessel_id = 1"),
             ("insert departments", "INSERT INTO departments (department_name) VALUES ('X')"),
             ("create table", "CREATE TABLE public.x (i int)")]
    for label, sql in cases:
        try:
            conn.execute(sql)
            results.append((label + " refused (read-only session)", False, "ACCEPTED"))
        except expected as ex:
            results.append((label + " refused (read-only session)", True, type(ex).__name__))
    # even with read-only mode switched off by the client, the privileges must refuse every write
    conn.execute("SET default_transaction_read_only = off")
    for label, sql in cases:
        try:
            conn.execute(sql)
            results.append((label + " refused (privileges)", False, "ACCEPTED"))
        except psycopg.errors.InsufficientPrivilege as ex:
            results.append((label + " refused (privileges)", True, type(ex).__name__))
for label, ok, detail in results:
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {detail}")
raise SystemExit(0 if all(ok for _, ok, _ in results) else 1)
