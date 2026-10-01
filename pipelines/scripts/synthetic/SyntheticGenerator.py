"""Synthetic company data: employees, vessels, containers (verified against the saved CSVs) and invoices (pricing check).

Origin:  Converted from Notebooks/synthetic/SyntheticGenerator.ipynb (archived in docs/archive/notebooks/).
         Refactored (ADR-036 D3) 2026-10-01: same generators in the same order, so every random draw is unchanged;
         exploration prints replaced by assertions and short summaries; the unused `get_toll_band_id` was removed.
Run:     uv run python tools/run.py pipelines/scripts/synthetic/SyntheticGenerator.py  (from the project root)

Reads:   Data/processed/structured/ports.csv, toll_rate_bands.csv; Data/processed/synthetic/*.csv;
         PostgreSQL `toll_rate_bands` (read-only session)
Writes:  nothing when the CSVs exist: save_or_verify() compares and never overwrites with different data
Re-run:  safe (verification run)

Notes
- Re-running reproduces employees.csv, vessels.csv and containers.csv exactly (fixed seeds, fixed reference date) on
  the owner's Windows machine; on Linux the Faker draws differ (ROADMAP known issues), and save_or_verify stops.
- The invoice section reproduces the pricing method (ADR-004) and validates it, but not the exact rows: the stored
  invoices were finalized inside PostgreSQL (ADR-013), so invoices are neither saved nor loaded here.
- The random generators are seeded per section exactly as in the notebook. `DataFrame.sample` uses NumPy's global
  generator, seeded once before the vessels; the containers and the invoices continue that stream. Do not insert any
  NumPy random call between the sections, or containers.csv changes.
"""
import io
import os
import random
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg
from faker import Faker

PROJECT_ROOT = next(
    root for root in [Path.cwd(), *Path.cwd().parents]
    if (root / "Data").is_dir() and (root / "pyproject.toml").exists()
)
STRUCTURED_DIR = PROJECT_ROOT / "Data" / "processed" / "structured"
SYNTHETIC_DIR = PROJECT_ROOT / "Data" / "processed" / "synthetic"

# Columns the database owns and this script does not generate (filled by a migration, exported into the mirror).
DB_OWNED_COLUMNS = {"vessels.csv": ["mmsi"]}  # db/migrations/005_fill_vessels_mmsi.sql (ADR-028)

# Faker's relative strings ("-15y") are relative to *today*, so re-running on another day shifted every hire_date.
# Anchor them to the day the canonical data was generated.
REFERENCE_DATE = date(2026, 9, 13)

DEPARTMENTS = {"Operations": 1, "Customs": 2, "Finance": 3, "HR": 4, "IT": 5}
ROLES = {"employee": 1, "manager": 2, "ceo": 3}

# Vessel SCNT ranges (approximate operational ranges for synthetic data)
SCNT_RANGES = {
    "Crude Oil Tankers": (5000, 300000),
    "Petroleum Product Tankers": (3000, 150000),
    "Dry Bulk Vessels": (3000, 200000),
    "Liquefied Petroleum Gas (LPG) Carriers": (2000, 100000),
    "Liquefied Natural Gas (LNG) Carriers": (20000, 180000),
    "Chemical Tankers & Other Liquid Bulk Tankers": (2000, 80000),
    "General Cargo / Multi-Purpose / Heavy Lift Vessels": (1000, 70000),
    "Roll-On/Roll-Off (Ro/Ro) Vessels": (3000, 80000),
    "Vehicles Carriers": (5000, 100000),
    "Cruise Ships": (10000, 150000),
    "Special Floating Units": (500, 100000),
    "Other Vessels": (500, 50000),
    "Containerships": (5000, 200000),
}
CONTAINER_TYPES = ["Dry", "Reefer", "Open Top", "Flat Rack"]
CONTAINER_STATUSES = ["Empty", "Loaded", "In Transit", "At Port", "Delivered"]
CONTAINER_COLUMNS = ["container_number", "container_type", "size_ft", "status", "vessel_id", "origin_locode",
                     "destination_locode"]
INVOICE_COLUMNS = ["invoice_number", "vessel_id", "toll_rate_band_id", "invoice_date", "scnt_tons",
                   "rate_sdr_per_ton", "amount", "description", "status"]


# ---------------------------------------------------------------------------------------------------- helpers

def save_or_verify(df: pd.DataFrame, path: Path) -> None:
    """Write df to path. If the file already exists, never overwrite it with different data:
    the saved CSVs mirror the rows loaded into PostgreSQL. Database-owned columns (DB_OWNED_COLUMNS) are
    expected in the saved file and are not compared."""
    if path.exists():
        existing = pd.read_csv(path, dtype=str, keep_default_na=False)
        generated = pd.read_csv(io.StringIO(df.to_csv(index=False)), dtype=str, keep_default_na=False)
        extra = DB_OWNED_COLUMNS.get(path.name, [])
        assert existing.columns.tolist() == generated.columns.tolist() + extra, f"{path.name}: unexpected columns"
        if not existing[generated.columns].equals(generated):
            raise ValueError(
                f"{path.name}: regenerated data differs from the saved file "
                "(which matches the database). File NOT overwritten."
            )
        print(f"{path.name}: identical to the saved file, nothing written.")
        return
    df.to_csv(path, index=False)
    print(f"{path.name}: written ({len(df)} rows).")


def days_ago(years: float = 0, days: float = 0) -> date:
    """Same arithmetic as Faker's '-Ny' / '-Nd' strings (1 year = 365.24 days), anchored to REFERENCE_DATE."""
    return REFERENCE_DATE + timedelta(days=-(365.24 * years) - days)


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


def connect_db() -> psycopg.Connection:
    """Read-only psycopg connection from the PG* variables of .env."""
    return psycopg.connect(
        host=os.environ["PGHOST"], port=os.environ["PGPORT"], dbname=os.environ["PGDATABASE"],
        user=os.environ["PGUSER"], password=os.environ["PGPASSWORD"],
        options="-c default_transaction_read_only=on",
    )


def counts(series: pd.Series) -> dict:
    return series.value_counts().sort_index().to_dict()


# ---------------------------------------------------------------------------------------------------- employees

def generate_employees() -> pd.DataFrame:
    """1 CEO, 2 managers per department, 89 employees. Seeds: random 42, Faker 42."""
    fake = Faker()
    random.seed(42)
    Faker.seed(42)
    employees = [{
        "first_name": fake.first_name(),
        "last_name": fake.last_name(),
        "email": "ceo@nilegate.com",
        "role_id": ROLES["ceo"],
        "department_id": DEPARTMENTS["Operations"],
        "hire_date": fake.date_between(start_date=days_ago(years=15), end_date=days_ago(years=5)),
    }]
    manager_counter = 1
    for department_id in DEPARTMENTS.values():
        for _ in range(2):
            first_name = fake.first_name()
            last_name = fake.last_name()
            employees.append({
                "first_name": first_name,
                "last_name": last_name,
                "email": f"manager{manager_counter}@nilegate.com",
                "role_id": ROLES["manager"],
                "department_id": department_id,
                "hire_date": fake.date_between(start_date=days_ago(years=12), end_date=days_ago(years=2)),
            })
            manager_counter += 1
    for i in range(1, 90):
        first_name = fake.first_name()
        last_name = fake.last_name()
        department_id = random.choice(list(DEPARTMENTS.values()))
        employees.append({
            "first_name": first_name,
            "last_name": last_name,
            "email": f"employee{i}@nilegate.com",
            "role_id": ROLES["employee"],
            "department_id": department_id,
            "hire_date": fake.date_between(start_date=days_ago(years=8), end_date=days_ago(days=30)),
        })
        random.random()  # ADR-017: status removed; the draw it used is kept so later values stay identical
    return pd.DataFrame(employees)


def validate_employees(employees: pd.DataFrame) -> None:
    assert len(employees) == 100 and employees["email"].is_unique
    assert counts(employees["role_id"]) == {1: 89, 2: 10, 3: 1}, counts(employees["role_id"])
    assert set(employees["department_id"]) == set(DEPARTMENTS.values())
    assert int(employees.isnull().sum().sum()) == 0
    print(f"employees: {employees.shape} | roles {counts(employees['role_id'])} | "
          f"departments {counts(employees['department_id'])}")


# ---------------------------------------------------------------------------------------------------- vessels

def generate_vessels(ports: pd.DataFrame, vessel_types: list[str]) -> pd.DataFrame:
    """500 vessels on real ports and the toll categories. Seeds: random 42 and NumPy 42 (NumPy is used later by
    DataFrame.sample in the container and invoice sections)."""
    random.seed(42)
    np.random.seed(42)
    countries = ports["Country"].dropna().unique().tolist()
    locodes = ports["LOCODE"].dropna().unique().tolist()
    vessels = []
    for i in range(1, 501):
        vessel_type = random.choice(vessel_types)
        min_tons, max_tons = SCNT_RANGES[vessel_type]
        scnt_tons = round(random.uniform(min_tons, max_tons), 2)
        origin, destination = random.sample(locodes, 2)
        vessels.append({
            "imo_number": str(9000000 + i),
            "vessel_name": f"{vessel_type.split()[0]} Voyager {i:03d}",
            "vessel_type": vessel_type,
            "flag_country": random.choice(countries),
            "scnt_tons": scnt_tons,
            "origin_locode": origin,
            "destination_locode": destination,
            "condition": random.choice(["Laden", "Ballast"]),
            "status": random.choices(["In Transit", "At Port", "Anchored", "Completed"],
                                     weights=[45, 25, 15, 15], k=1)[0],
        })
    return pd.DataFrame(vessels)


def validate_vessels(vessels: pd.DataFrame, ports: pd.DataFrame, vessel_types: list[str]) -> None:
    assert len(vessels) == 500 and vessels["imo_number"].is_unique
    assert not (vessels["origin_locode"] == vessels["destination_locode"]).any()
    assert vessels["origin_locode"].isin(ports["LOCODE"]).all() and vessels["destination_locode"].isin(ports["LOCODE"]).all()
    assert vessels["vessel_type"].isin(vessel_types).all()
    assert int(vessels.isnull().sum().sum()) == 0
    print(f"vessels: {vessels.shape} | conditions {counts(vessels['condition'])} | statuses {counts(vessels['status'])}")


# ---------------------------------------------------------------------------------------------------- containers

def generate_containers(vessels: pd.DataFrame) -> pd.DataFrame:
    """1,000 containers, each on a sampled vessel (NumPy stream continues), with that vessel's route. Seed: random 42."""
    random.seed(42)
    containers = []
    for i in range(1, 1001):
        vessel = vessels.sample(1).iloc[0]
        containers.append({
            "container_number": f"NGCU{i:07d}",
            "container_type": random.choice(CONTAINER_TYPES),
            "size_ft": random.choice([20, 40]),
            "status": random.choice(CONTAINER_STATUSES),
            "vessel_imo": vessel["imo_number"],
            "origin_locode": vessel["origin_locode"],
            "destination_locode": vessel["destination_locode"],
        })
    return pd.DataFrame(containers)


def link_containers(containers: pd.DataFrame, vessel_id_map: dict) -> pd.DataFrame:
    """Replace the vessel IMO by the PostgreSQL vessel_id and order the columns as the table."""
    containers = containers.copy()
    containers["vessel_id"] = containers["vessel_imo"].map(vessel_id_map)
    return containers.drop(columns=["vessel_imo"])[CONTAINER_COLUMNS]


def validate_containers(containers: pd.DataFrame, ports: pd.DataFrame) -> None:
    assert len(containers) == 1000 and containers["container_number"].is_unique
    assert not (containers["origin_locode"] == containers["destination_locode"]).any()
    assert containers["origin_locode"].isin(ports["LOCODE"]).all()
    assert containers["destination_locode"].isin(ports["LOCODE"]).all()
    assert int(containers.isnull().sum().sum()) == 0, "every container has a vessel_id"
    print(f"containers: {containers.shape} | columns {containers.columns.tolist()}")


# ---------------------------------------------------------------------------------------------------- invoices

def calculate_suez_toll(vessel_category: str, condition: str, scnt_tons: float, toll_df: pd.DataFrame) -> float:
    """Progressive toll (ADR-004): each band's tons at that band's rate, summed, rounded to 0.01 SDR."""
    bands = toll_df[
        (toll_df["vessel_category"] == vessel_category) & (toll_df["laden_ballast"] == condition)
    ].sort_values("band_order")
    total = 0.0
    for _, band in bands.iterrows():
        band_min = band["band_min_tons"]
        band_max = band["band_max_tons"]
        if scnt_tons <= band_min:
            continue
        upper_limit = scnt_tons if pd.isna(band_max) else min(scnt_tons, band_max)
        tons_in_band = upper_limit - band_min
        if tons_in_band > 0:
            total += tons_in_band * band["rate_sdr_per_ton"]
    return round(total, 2)


def check_toll_example(vessel: pd.Series, toll_df: pd.DataFrame) -> None:
    """Worked example on the first vessel: band-by-band amounts must add up to calculate_suez_toll."""
    toll = calculate_suez_toll(vessel["vessel_type"], vessel["condition"], vessel["scnt_tons"], toll_df)
    bands = toll_df[
        (toll_df["vessel_category"] == vessel["vessel_type"])
        & (toll_df["laden_ballast"] == vessel["condition"])
        & (toll_df["band_min_tons"] < vessel["scnt_tons"])
    ].sort_values("band_order").copy()
    bands["tons_used"] = (bands["band_max_tons"].fillna(vessel["scnt_tons"]).clip(upper=vessel["scnt_tons"])
                          - bands["band_min_tons"])
    bands["amount_sdr"] = bands["tons_used"] * bands["rate_sdr_per_ton"]
    print(f"toll example: {vessel['vessel_type']} | {vessel['condition']} | SCNT {vessel['scnt_tons']} → "
          f"{toll} SDR over {len(bands)} bands")
    print(bands[["band_label", "band_min_tons", "band_max_tons", "rate_sdr_per_ton", "tons_used", "amount_sdr"]])
    assert abs(bands["amount_sdr"].sum() - toll) <= 0.01, (bands["amount_sdr"].sum(), toll)


def generate_invoices(vessels: pd.DataFrame, toll_df: pd.DataFrame) -> pd.DataFrame:
    """1,000 invoices in 2025 on sampled vessels (NumPy stream continues). Seed: random 42."""
    random.seed(42)
    invoices = []
    for i in range(1, 1001):
        vessel = vessels.sample(1).iloc[0]
        vessel_type = vessel["vessel_type"]
        condition = vessel["condition"]
        scnt_tons = vessel["scnt_tons"]
        if vessel_type == "Special Floating Units":   # this category only has Laden rates
            condition = "Laden"
        amount_sdr = calculate_suez_toll(vessel_type, condition, scnt_tons, toll_df)
        invoice_date = date(2025, 1, 1) + timedelta(days=random.randint(0, 364))
        invoices.append({
            "invoice_number": f"INV-{i:07d}",
            "vessel_imo": vessel["imo_number"],
            "invoice_date": invoice_date,
            "scnt_tons": scnt_tons,
            "amount_sdr": amount_sdr,
            "description": f"Suez Canal transit dues - {vessel_type}",
            "status": random.choice(["Paid", "Pending", "Issued"]),
        })
    invoices_df = pd.DataFrame(invoices)
    invoices_df["amount"] = invoices_df["amount_sdr"]
    return invoices_df.drop(columns=["amount_sdr"])


def read_toll_bands_db() -> pd.DataFrame:
    load_env_file()
    with connect_db() as conn:
        bands = pd.read_sql_query(
            """
            SELECT id, vessel_category, laden_ballast, band_order, band_label, band_min_tons, band_max_tons,
                   rate_sdr_per_ton
            FROM toll_rate_bands
            ORDER BY id
            """,
            conn,
        )
    # psycopg returns NUMERIC columns as Decimal; convert them so they compare cleanly with floats
    numeric_columns = ["band_min_tons", "band_max_tons", "rate_sdr_per_ton"]
    bands[numeric_columns] = bands[numeric_columns].astype(float)
    return bands


def terminal_band_id(toll_bands_db: pd.DataFrame, vessel_category: str, condition: str, scnt_tons: float):
    """PostgreSQL id of the band that contains the vessel's SCNT (Special Floating Units: Laden only)."""
    if vessel_category == "Special Floating Units":
        condition = "Laden"
    bands = toll_bands_db[
        (toll_bands_db["vessel_category"] == vessel_category)
        & (toll_bands_db["laden_ballast"] == condition)
        & (toll_bands_db["band_min_tons"] < scnt_tons)
        & (toll_bands_db["band_max_tons"].isna() | (toll_bands_db["band_max_tons"] >= scnt_tons))
    ].sort_values("band_order")
    if bands.empty:
        return None
    return int(bands.iloc[0]["id"])


def price_invoices(invoices_df: pd.DataFrame, vessels: pd.DataFrame, vessel_id_map: dict,
                   toll_bands_db: pd.DataFrame) -> pd.DataFrame:
    """Add vessel_id, the terminal band id and its rate; order the columns as the table."""
    invoices_df = invoices_df.copy()
    invoices_df["vessel_id"] = invoices_df["vessel_imo"].map(vessel_id_map)
    lookup = vessels.set_index("imo_number")[["vessel_type", "condition"]]
    invoices_df["toll_rate_band_id"] = invoices_df.apply(
        lambda row: terminal_band_id(toll_bands_db, lookup.loc[row["vessel_imo"], "vessel_type"],
                                     lookup.loc[row["vessel_imo"], "condition"], row["scnt_tons"]),
        axis=1,
    )
    # rate_sdr_per_ton = rate of the terminal band (the band that contains the vessel's SCNT)
    invoices_df["rate_sdr_per_ton"] = invoices_df["toll_rate_band_id"].map(
        toll_bands_db.set_index("id")["rate_sdr_per_ton"])
    for column in ("vessel_id", "toll_rate_band_id", "rate_sdr_per_ton"):
        assert int(invoices_df[column].isnull().sum()) == 0, f"missing {column}"
    return invoices_df[INVOICE_COLUMNS]


def validate_pricing(invoices_df: pd.DataFrame, vessels: pd.DataFrame, toll_bands_db: pd.DataFrame,
                     toll_df: pd.DataFrame) -> None:
    """Every generated invoice follows the pricing rules (ADR-004)."""
    vessels_by_id = vessels.assign(vessel_id=range(1, len(vessels) + 1)).set_index("vessel_id")
    bands_by_id = toll_bands_db.set_index("id")
    errors = []
    for row in invoices_df.itertuples(index=False):
        vessel = vessels_by_id.loc[row.vessel_id]
        band = bands_by_id.loc[row.toll_rate_band_id]
        condition = "Laden" if vessel["vessel_type"] == "Special Floating Units" else vessel["condition"]
        expected_amount = calculate_suez_toll(vessel["vessel_type"], condition, vessel["scnt_tons"], toll_df)
        if row.scnt_tons != vessel["scnt_tons"]:
            errors.append((row.invoice_number, "scnt_tons differs from vessel"))
        if (band["vessel_category"], band["laden_ballast"]) != (vessel["vessel_type"], condition):
            errors.append((row.invoice_number, "band category/condition mismatch"))
        if not (row.scnt_tons > band["band_min_tons"]
                and (pd.isna(band["band_max_tons"]) or row.scnt_tons <= band["band_max_tons"])):
            errors.append((row.invoice_number, "scnt_tons outside the terminal band"))
        if row.rate_sdr_per_ton != band["rate_sdr_per_ton"]:
            errors.append((row.invoice_number, "rate differs from terminal band"))
        if abs(row.amount - expected_amount) > 0.01:
            errors.append((row.invoice_number, "amount differs from progressive calculation"))
    assert invoices_df["invoice_number"].is_unique, "Duplicate invoice numbers"
    assert not errors, errors[:10]
    print(f"All {len(invoices_df)} invoices follow the pricing rules (ADR-004).")
    print("Not saved: the database is the source of truth for invoices (ADR-013).")


# ---------------------------------------------------------------------------------------------------- main

def main() -> None:
    print("Project root  :", PROJECT_ROOT)

    employees = generate_employees()
    validate_employees(employees)
    save_or_verify(employees, SYNTHETIC_DIR / "employees.csv")

    ports = pd.read_csv(STRUCTURED_DIR / "ports.csv")
    toll_df = pd.read_csv(STRUCTURED_DIR / "toll_rate_bands.csv")
    vessel_types = toll_df["vessel_category"].unique().tolist()   # canonical categories from the validated tolls

    vessels = generate_vessels(ports, vessel_types)
    validate_vessels(vessels, ports, vessel_types)
    save_or_verify(vessels, SYNTHETIC_DIR / "vessels.csv")

    vessel_id_map = {imo: idx for idx, imo in enumerate(vessels["imo_number"], start=1)}  # PostgreSQL vessel_id
    containers = link_containers(generate_containers(vessels), vessel_id_map)
    validate_containers(containers, ports)
    save_or_verify(containers, SYNTHETIC_DIR / "containers.csv")
    print("✅ employees, vessels and containers identical to the saved CSVs.")

    check_toll_example(vessels.iloc[0], toll_df)
    invoices_df = generate_invoices(vessels, toll_df)
    toll_bands_db = read_toll_bands_db()
    print(f"toll bands in the database: {toll_bands_db.shape}")
    invoices_df = price_invoices(invoices_df, vessels, vessel_id_map, toll_bands_db)
    validate_pricing(invoices_df, vessels, toll_bands_db, toll_df)
    print("✅ invoice pricing validation passed.")


if __name__ == "__main__":
    main()
