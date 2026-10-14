"""Check the Power BI login (member of finance_bi, ADR-047) from the host: password login through the published port,
schema finance readable, every other schema refused, every write refused. Prints no credentials.

    uv run python db/check_finance_bi_user.py
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
if not e.get("PG_BI_USER") or not e.get("PG_BI_PASSWORD"):
    raise SystemExit("PG_BI_USER / PG_BI_PASSWORD missing in .env: run db\\create_finance_bi_user.ps1 first")

results = []


def refused(label: str, sql: str, expected) -> None:
    try:
        conn.execute(sql)
        results.append((label, False, "ACCEPTED"))
    except expected as ex:
        results.append((label, True, type(ex).__name__))


with psycopg.connect(host=e["PGHOST"], port=e["PGPORT"], dbname=e["PGDATABASE"], user=e["PG_BI_USER"],
                     password=e["PG_BI_PASSWORD"], autocommit=True) as conn:
    n = conn.execute("SELECT count(*) FROM finance.kpi_weekly").fetchone()[0]
    results.append(("select finance.kpi_weekly", n == 52, f"{n} rows"))
    n = conn.execute("SELECT count(*) FROM finance.fact_invoice").fetchone()[0]
    results.append(("select finance.fact_invoice", n == 1000, f"{n} rows"))
    ro = conn.execute("SHOW default_transaction_read_only").fetchone()[0]
    results.append(("session read-only by default", ro == "on", ro))
    denied = psycopg.errors.InsufficientPrivilege
    for table in ["public.employees", "public.invoices", "public.payments", "finance_test.invoices"]:
        refused(f"select {table} refused", f"SELECT 1 FROM {table} LIMIT 1", denied)
    writes = [("update finance.dim_customer", "UPDATE finance.dim_customer SET country = country WHERE customer_id = 1"),
              ("create table in finance", "CREATE TABLE finance.x (i int)")]
    for label, sql in writes:
        refused(label + " refused (read-only session)", sql, (psycopg.errors.ReadOnlySqlTransaction, denied))
    # even with read-only mode switched off by the client, the privileges must refuse every write
    conn.execute("SET default_transaction_read_only = off")
    for label, sql in writes:
        refused(label + " refused (privileges)", sql, denied)
for label, ok, detail in results:
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {detail}")
raise SystemExit(0 if all(ok for _, ok, _ in results) else 1)
