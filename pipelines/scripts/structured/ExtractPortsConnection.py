"""ExtractPortsConnection

Converted from Notebooks/structured/ExtractPortsConnection.ipynb (2026-10-01) by tools/nb_to_script.py: same cells, same order; `# %% cell N` = notebook cell N.
Run from the project root: uv run python tools/run.py pipelines/scripts/structured/ExtractPortsConnection.py

Reads:   Data/raw/structured/Port_flows/ (shapefile); PostgreSQL (ports)
Writes:  INSERTS INTO PostgreSQL port_connections; Data/processed/structured/port_connections.csv
Re-run:  DO NOT RE-RUN: port_connections is a completed table (the project rules development rule 2). Kept as the record of how the table was built
"""
from IPython.display import display  # outside Jupyter it prints the value (added by the conversion)


def _display_result(value):
    """A notebook shows the value of a cell's last expression unless it is None (added by the conversion)."""
    if value is not None:
        display(value)

# %% cell 0
import geopandas as gpd
from pathlib import Path

PROJECT_ROOT = next(
    root for root in [Path.cwd(), *Path.cwd().parents]
    if (root / "Data").is_dir() and (root / "pyproject.toml").exists()
)

flow_gdf = gpd.read_file(PROJECT_ROOT / "Data" / "raw" / "structured" / "Port_flows" / "port_flows.shp")

# %% cell 1
_display_result(flow_gdf.shape)

# %% cell 2
flow_gdf.columns.tolist()
_display_result(flow_gdf.head())

# %% cell 3
_display_result(flow_gdf.dtypes)

# %% cell 4
_display_result(flow_gdf.isna().sum())

# %% cell 5
_display_result(flow_gdf["geometry"].geom_type.value_counts())

# %% cell 6
_display_result(flow_gdf.crs)

# %% cell 7
_display_result(flow_gdf[["Port1", "Port2"]].head())

# %% cell 8
_display_result(flow_gdf[["Port1", "Port2"]].duplicated().sum())

# %% cell 9
dup_pairs = flow_gdf[
    flow_gdf[["Port1", "Port2"]].duplicated(keep=False)
]

_display_result(dup_pairs.groupby(["Port1", "Port2"]).agg(
    rows=("FLOWS", "size"),
    unique_flows=("FLOWS", "nunique"),
    unique_geometry=("geometry", "nunique"),
).sort_values(
    ["unique_flows", "unique_geometry"],
    ascending=False
).head(20))

# %% cell 10
flow_gdf = flow_gdf.drop_duplicates().reset_index(drop=True)
_display_result(flow_gdf.shape)

# %% cell 11
# IPython magic removed (dependencies come from uv, the project rules rule 6): %pip install "psycopg[binary]"

# %% cell 12
import psycopg
import os
from pathlib import Path


def load_env_file(filename=".env"):
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


load_env_file()


def connect_db():
    """Open a psycopg connection using the PG* variables from .env."""
    return psycopg.connect(
        host=os.environ["PGHOST"],
        port=os.environ["PGPORT"],
        dbname=os.environ["PGDATABASE"],
        user=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
    )

# %% cell 13
conn = connect_db()

ports_db = set(
    row[0]
    for row in conn.execute("SELECT locode FROM ports")
)

# %% cell 14
_display_result(len(ports_db))

# %% cell 15
invalid_port1 = set(flow_gdf["Port1"]) - ports_db
invalid_port2 = set(flow_gdf["Port2"]) - ports_db

_display_result(len(invalid_port1), len(invalid_port2))

# %% cell 16
_display_result(flow_gdf["FLOWS"].describe())

# %% cell 17
_display_result(flow_gdf["FLOWS"].min(), flow_gdf["FLOWS"].max())

# %% cell 18
flow_gdf = flow_gdf.rename(columns={
    "Port1": "port1_locode",
    "Port2": "port2_locode",
    "FLOWS": "flows",
    "Country1": "country1",
    "Country2": "country2",
    "geometry": "geom"
})

# %% cell 19
_display_result(flow_gdf.columns.tolist())

# %% cell 20
conn = connect_db()

# %% cell 21
with conn.cursor() as cur:
    for row in flow_gdf.itertuples(index=False):
        cur.execute(
            """
            INSERT INTO port_connections (
                port1_locode,
                port2_locode,
                flows,
                country1,
                country2,
                geom
            )
            VALUES (
                %s, %s, %s, %s, %s,
                ST_SetSRID(ST_GeomFromText(%s), 4326)
            )
            """,
            (
                row.port1_locode,
                row.port2_locode,
                row.flows,
                row.country1,
                row.country2,
                row.geom.wkt
            )
        )

_display_result(conn.commit())

# %% cell 22
_display_result(conn.close())

# %% cell 23
_display_result(flow_gdf.drop(columns="geom").to_csv(
    PROJECT_ROOT / "Data" / "processed" / "structured" / "port_connections.csv",
    index=False
))
