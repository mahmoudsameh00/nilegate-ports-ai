"""Refresh the Data/processed/synthetic/vessels.csv mirror from PostgreSQL (plan decision D7, ADR-028).

`mmsi` is owned by the database (migration 005); the other columns are owned by SyntheticGenerator.ipynb. The file is
rewritten only when every generator-owned column is identical to the database, row for row, so this script can never
change data the generator verifies. Read-only on the database.

    uv run python db/export_vessels_mirror.py
"""
import io
import os
from pathlib import Path

import pandas as pd
import psycopg

ROOT = Path(__file__).resolve().parents[1]
DB_OWNED = ["mmsi"]


def load_env() -> None:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def main() -> int:
    load_env()
    e = os.environ
    path = ROOT / "Data" / "processed" / "synthetic" / "vessels.csv"
    raw = path.read_bytes()
    eol = "\r\n" if b"\r\n" in raw[:4096] else "\n"  # keep the file's own line endings (the mirrors use CRLF)
    old = pd.read_csv(path, dtype=str, keep_default_na=False)
    base = [c for c in old.columns if c not in DB_OWNED]
    with psycopg.connect(host=e["PGHOST"], port=e["PGPORT"], dbname=e["PGDATABASE"], user=e["PGUSER"],
                         password=e["PGPASSWORD"], options="-c default_transaction_read_only=on") as conn:
        buf = io.StringIO()
        sql = f"COPY (SELECT {', '.join(base + DB_OWNED)} FROM vessels ORDER BY vessel_id) TO STDOUT WITH (FORMAT csv, HEADER true)"
        with conn.cursor().copy(sql) as cp:
            for chunk in cp:
                buf.write(bytes(chunk).decode("utf-8"))
    new = pd.read_csv(io.StringIO(buf.getvalue()), dtype=str, keep_default_na=False)
    same = len(old) == len(new) and all(
        pd.to_numeric(old[c]).round(6).equals(pd.to_numeric(new[c]).round(6)) if c == "scnt_tons" else old[c].equals(new[c])
        for c in base)
    if not same:
        print("NOT written: generator-owned columns differ between the database and the mirror")
        return 1
    out = old[base].copy()
    for c in DB_OWNED:
        out[c] = new[c].to_numpy()
    out.to_csv(path, index=False, lineterminator=eol)
    print(f"{path.relative_to(ROOT)} refreshed: {len(out)} rows, database-owned columns {DB_OWNED}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
