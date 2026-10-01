"""Ports: UN/LOCODE-attributed GeoJSON → Data/processed/structured/ports.csv (the mirror of the PostgreSQL table `ports`).

Origin:  Converted from Notebooks/structured/ExtractPortsAttributes.ipynb (archived in docs/archive/notebooks/).
         Refactored (ADR-036 D3) 2026-10-01: same steps, same output file byte for byte; the notebook's exploration
         prints are replaced by assertions and a short summary.
Run:     uv run python tools/run.py pipelines/scripts/structured/ExtractPortsAttributes.py  (from the project root)

Reads:   Data/raw/structured/attributed_ports.geojson
Writes:  Data/processed/structured/ports.csv
Re-run:  safe: rewrites the same CSV

Steps
1. Read the GeoJSON. The file is latin-1 text followed by a .NET "System.IO.MemoryStream" dump; only the part before
   that marker is JSON.
2. One row per feature: LOCODE, Name, Country, Function, Status, outflows, lon, lat.
3. Duplicate LOCODEs (the same port listed twice): keep the first occurrence.
4. Validate: unique 5-character LOCODEs, 8-character Function codes, 2-character Status codes, no nulls, valid
   coordinates, no negative outflows, 837 ports (the row count of `ports` in PostgreSQL).
5. Write the CSV.
"""
import json
from pathlib import Path

import pandas as pd

PROJECT_ROOT = next(
    root for root in [Path.cwd(), *Path.cwd().parents]
    if (root / "Data").is_dir() and (root / "pyproject.toml").exists()
)
RAW_FILE = PROJECT_ROOT / "Data" / "raw" / "structured" / "attributed_ports.geojson"
OUT_FILE = PROJECT_ROOT / "Data" / "processed" / "structured" / "ports.csv"
EXPECTED_PORTS = 837   # rows of `ports` in PostgreSQL (ARCHITECTURE §4)


def load_features(path: Path) -> list[dict]:
    """Return the GeoJSON features; the text after the 'System.IO.MemoryStream' marker is not JSON."""
    text = path.read_bytes().decode("latin-1").split("System.IO.MemoryStream")[0]
    return json.loads(text)["features"]


def ports_frame(features: list[dict]) -> pd.DataFrame:
    """One row per feature, in file order."""
    rows = []
    for feature in features:
        properties = feature["properties"]
        lon, lat = feature["geometry"]["coordinates"][:2]
        rows.append({
            "LOCODE": properties["LOCODE"],
            "Name": properties["Name"],
            "Country": properties["Country"],
            "Function": properties["Function"],
            "Status": properties["Status"],
            "outflows": properties["outflows"],
            "lon": lon,
            "lat": lat,
        })
    return pd.DataFrame(rows)


def report_duplicates(features: list[dict], ports: pd.DataFrame) -> None:
    """Print each duplicated LOCODE with its names, so the 'keep first' rule can be reviewed in the log."""
    duplicated = set(ports.loc[ports["LOCODE"].duplicated(keep=False), "LOCODE"])
    print(f"duplicate LOCODE rows: {int(ports['LOCODE'].duplicated().sum())} ({len(duplicated)} codes)")
    for feature in features:
        p = feature["properties"]
        if p["LOCODE"] in duplicated:
            print(f"  {p['LOCODE']} | Name: {p['Name']} | NameWoDiac: {p['NameWoDiac']}")


def validate(ports: pd.DataFrame) -> None:
    assert ports["LOCODE"].is_unique, "duplicate LOCODEs left"
    assert int(ports.isnull().sum().sum()) == 0, ports.isnull().sum().to_dict()
    assert set(ports["LOCODE"].str.len()) == {5}, "every LOCODE has 5 characters"
    assert set(ports["Function"].str.len()) == {8}, "every Function code has 8 characters"
    assert set(ports["Status"].str.len()) == {2}, "every Status code has 2 characters"
    assert ports["lon"].between(-180, 180).all() and ports["lat"].between(-90, 90).all(), "invalid coordinates"
    assert (ports["outflows"] >= 0).all(), "negative outflows"
    assert len(ports) == EXPECTED_PORTS, f"{len(ports)} ports, expected {EXPECTED_PORTS}"


def main() -> None:
    features = load_features(RAW_FILE)
    print(f"features in the GeoJSON: {len(features)}")
    ports = ports_frame(features)
    report_duplicates(features, ports)
    ports = ports.drop_duplicates(subset=["LOCODE"], keep="first").reset_index(drop=True)
    validate(ports)
    print(f"ports: {len(ports)} | lon {ports['lon'].min()} to {ports['lon'].max()} | "
          f"lat {ports['lat'].min()} to {ports['lat'].max()} | outflows {ports['outflows'].min()} to "
          f"{ports['outflows'].max()}")
    print(f"Status values: {sorted(ports['Status'].unique())}")
    ports.to_csv(OUT_FILE, index=False)
    print(f"✅ ports validation passed: {len(ports)} rows written to {OUT_FILE.relative_to(PROJECT_ROOT).as_posix()}")


if __name__ == "__main__":
    main()
