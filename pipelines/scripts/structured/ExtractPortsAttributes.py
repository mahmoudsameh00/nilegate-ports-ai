"""ExtractPortsAttributes

Converted from Notebooks/structured/ExtractPortsAttributes.ipynb (2026-10-01) by tools/nb_to_script.py: same cells, same order; `# %% cell N` = notebook cell N.
Run from the project root: uv run python tools/run.py pipelines/scripts/structured/ExtractPortsAttributes.py

Reads:   Data/raw/structured/attributed_ports.geojson
Writes:  Data/processed/structured/ports.csv
Re-run:  safe: rewrites the same CSV
"""
from IPython.display import display  # outside Jupyter it prints the value (added by the conversion)


def _display_result(value):
    """A notebook shows the value of a cell's last expression unless it is None (added by the conversion)."""
    if value is not None:
        display(value)

# %% cell 0
import json
from pathlib import Path

PROJECT_ROOT = next(
    root for root in [Path.cwd(), *Path.cwd().parents]
    if (root / "Data").is_dir() and (root / "pyproject.toml").exists()
)

file_path = PROJECT_ROOT / "Data" / "raw" / "structured" / "attributed_ports.geojson"

with open(file_path, "rb") as f:
    raw = f.read()

text = raw.decode("latin-1")

text = text.split("System.IO.MemoryStream")[0]

data = json.loads(text)

print(type(data))
print(data.keys())

# %% cell 1
first_port = data["features"][0]

print(first_port.keys())
print(first_port["properties"])
print(first_port["geometry"])

# %% cell 2
print(len(data["features"]))

# %% cell 3
ports = []

for feature in data["features"]:
    properties = feature["properties"]
    coordinates = feature["geometry"]["coordinates"]

    port = {
        "LOCODE": properties["LOCODE"],
        "Name": properties["Name"],
        "Country": properties["Country"],
        "Function": properties["Function"],
        "Status": properties["Status"],
        "outflows": properties["outflows"],
        "lon": coordinates[0],
        "lat": coordinates[1]
    }

    ports.append(port)

print(len(ports))
print(ports[0])

# %% cell 4
import pandas as pd

ports_df = pd.DataFrame(ports)

print(ports_df.shape)
print(ports_df.columns.tolist())
print(ports_df.head())

# %% cell 5
print("NULL values:")
print(ports_df.isnull().sum())

print("\nDuplicate LOCODEs:")
print(ports_df["LOCODE"].duplicated().sum())

print("\nData types:")
print(ports_df.dtypes)

# %% cell 6
duplicates = ports_df[
    ports_df["LOCODE"].duplicated(keep=False)
].sort_values("LOCODE")

print(duplicates.to_string(index=False))

# %% cell 7
for feature in data["features"]:
    locode = feature["properties"]["LOCODE"]

    if locode in duplicates["LOCODE"].values:
        print(
            locode,
            "| Name:", feature["properties"]["Name"],
            "| NameWoDiac:", feature["properties"]["NameWoDiac"]
        )

# %% cell 8
ports_df = ports_df.drop_duplicates(
    subset=["LOCODE"],
    keep="first"
).reset_index(drop=True)

print(ports_df.shape)
print(ports_df["LOCODE"].duplicated().sum())

# %% cell 9
print("Shape:", ports_df.shape)

print("\nNULL values:")
print(ports_df.isnull().sum())

print("\nDuplicate LOCODEs:")
print(ports_df["LOCODE"].duplicated().sum())

print("\nCoordinate ranges:")
print("Longitude:", ports_df["lon"].min(), "to", ports_df["lon"].max())
print("Latitude :", ports_df["lat"].min(), "to", ports_df["lat"].max())

print("\nOutflows:")
print("Min:", ports_df["outflows"].min())
print("Max:", ports_df["outflows"].max())

# %% cell 10
print("Unique Status values:")
print(sorted(ports_df["Status"].unique()))

print("\nUnique Function values:")
print(sorted(ports_df["Function"].unique()))

print("\nLOCODE length distribution:")
print(ports_df["LOCODE"].str.len().value_counts().sort_index())

# %% cell 11
print("LOCODE lengths:")
print(ports_df["LOCODE"].str.len().value_counts())

print("\nFunction lengths:")
print(ports_df["Function"].str.len().value_counts())

print("\nStatus lengths:")
print(ports_df["Status"].str.len().value_counts())

print("\nNegative outflows:")
print((ports_df["outflows"] < 0).sum())

print("\nInvalid coordinates:")
print(
    (
        (ports_df["lon"] < -180) |
        (ports_df["lon"] > 180) |
        (ports_df["lat"] < -90) |
        (ports_df["lat"] > 90)
    ).sum()
)

# %% cell 12
ports_df.to_csv(PROJECT_ROOT / "Data" / "processed" / "structured" / "ports.csv", index=False)
_display_result(ports_df.shape)
