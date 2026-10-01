"""Port connections: port-flows shapefile → Data/processed/structured/port_connections.csv (mirror of `port_connections`).

Origin:  Converted from Notebooks/structured/ExtractPortsConnection.ipynb (archived in docs/archive/notebooks/).
         Refactored (ADR-036 D3) 2026-10-01: same steps, same output file byte for byte; exploration displays replaced by
         assertions and a short summary. The original INSERT is kept as `insert_port_connections()` and runs only with
         `--insert` (owner decision 2026-10-01: the table is complete, the project rules rule 2).
Run:     uv run python tools/run.py pipelines/scripts/structured/ExtractPortsConnection.py  (from the project root)

Reads:   Data/raw/structured/Port_flows/port_flows.shp; PostgreSQL `ports` (read-only session)
Writes:  Data/processed/structured/port_connections.csv
Re-run:  safe: reads the database only and rewrites the same CSV (`--insert` refuses a non-empty table)

Steps
1. Read the shapefile (one LineString per port pair).
2. Drop exact duplicate rows (same pair, flows and geometry).
3. Validate against PostgreSQL: every Port1 / Port2 is a LOCODE of `ports`; flows are positive; 19,990 rows.
4. Rename to the table's column names and write the CSV without the geometry.
"""
import argparse
import os
from pathlib import Path

import geopandas as gpd
import psycopg

PROJECT_ROOT = next(
    root for root in [Path.cwd(), *Path.cwd().parents]
    if (root / "Data").is_dir() and (root / "pyproject.toml").exists()
)
RAW_FILE = PROJECT_ROOT / "Data" / "raw" / "structured" / "Port_flows" / "port_flows.shp"
OUT_FILE = PROJECT_ROOT / "Data" / "processed" / "structured" / "port_connections.csv"
EXPECTED_ROWS = 19_990   # rows of `port_connections` in PostgreSQL (ARCHITECTURE §4)
COLUMNS = {"Port1": "port1_locode", "Port2": "port2_locode", "FLOWS": "flows",
           "Country1": "country1", "Country2": "country2", "geometry": "geom"}


def load_env_file(filename: str = ".env") -> Path:
    """Load KEY=VALUE lines from the project's .env into os.environ (existing variables win)."""
    for folder in [Path.cwd(), *Path.cwd().parents]:
        env_path = folder / filename
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())
            return env_path
    raise FileNotFoundError(f"{filename} not found in {Path.cwd()} or its parents")


def connect_db(read_only: bool = True) -> psycopg.Connection:
    """psycopg connection from the PG* variables of .env; read-only unless a write is intended."""
    return psycopg.connect(
        host=os.environ["PGHOST"], port=os.environ["PGPORT"], dbname=os.environ["PGDATABASE"],
        user=os.environ["PGUSER"], password=os.environ["PGPASSWORD"],
        options="-c default_transaction_read_only=on" if read_only else "",
    )


def insert_port_connections(conn: psycopg.Connection, flows: gpd.GeoDataFrame) -> None:
    """How the table was loaded (2026-09): one INSERT per pair. Refuses to run on a non-empty table."""
    existing = conn.execute("SELECT count(*) FROM port_connections").fetchone()[0]
    if existing:
        raise SystemExit(f"port_connections already holds {existing} rows: not inserting (the project rules rule 2)")
    with conn.cursor() as cur:
        for row in flows.itertuples(index=False):
            cur.execute(
                """
                INSERT INTO port_connections (port1_locode, port2_locode, flows, country1, country2, geom)
                VALUES (%s, %s, %s, %s, %s, ST_SetSRID(ST_GeomFromText(%s), 4326))
                """,
                (row.port1_locode, row.port2_locode, row.flows, row.country1, row.country2, row.geom.wkt),
            )
    conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--insert", action="store_true", help="load the rows into an EMPTY port_connections table")
    args = parser.parse_args()

    flows = gpd.read_file(RAW_FILE)
    print(f"shapefile rows: {len(flows)} | columns: {flows.columns.tolist()} | crs: {flows.crs}")
    print(f"geometry types: {flows.geometry.geom_type.value_counts().to_dict()}")
    print(f"duplicate (Port1, Port2) rows before cleaning: {int(flows[['Port1', 'Port2']].duplicated().sum())}")
    flows = flows.drop_duplicates().reset_index(drop=True)
    print(f"rows after dropping exact duplicates: {len(flows)}")

    load_env_file()
    with connect_db() as conn:
        ports_db = {row[0] for row in conn.execute("SELECT locode FROM ports")}
    unknown = (set(flows["Port1"]) | set(flows["Port2"])) - ports_db
    assert not unknown, f"LOCODEs missing from ports: {sorted(unknown)[:10]}"
    assert not flows[["Port1", "Port2"]].duplicated().any(), "a port pair appears twice after cleaning"
    assert (flows["FLOWS"] > 0).all(), "flows must be positive"
    assert len(flows) == EXPECTED_ROWS, f"{len(flows)} rows, expected {EXPECTED_ROWS}"
    print(f"ports in the database: {len(ports_db)} | flows {flows['FLOWS'].min()} to {flows['FLOWS'].max()}")

    flows = flows.rename(columns=COLUMNS)
    if args.insert:
        with connect_db(read_only=False) as conn:
            insert_port_connections(conn, flows)
        print(f"inserted {len(flows)} rows into port_connections")
    flows.drop(columns="geom").to_csv(OUT_FILE, index=False)
    print(f"✅ port connections validation passed: {len(flows)} rows written to "
          f"{OUT_FILE.relative_to(PROJECT_ROOT).as_posix()}")


if __name__ == "__main__":
    main()
