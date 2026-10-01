"""Synthetic data generator — departments, roles, employees, vessels, containers, invoices

Converted from Notebooks/synthetic/SyntheticGenerator.ipynb (2026-10-01) by tools/nb_to_script.py: same cells, same order; `# %% cell N` = notebook cell N.
Run from the project root: uv run python tools/run.py pipelines/scripts/synthetic/SyntheticGenerator.py

Reads:   Data/processed/structured/ports.csv; Data/processed/synthetic/*.csv
Writes:  nothing when the CSVs exist: save_or_verify() compares and never overwrites with different data
Re-run:  safe (verification run)
"""
from IPython.display import display  # outside Jupyter it prints the value (added by the conversion)


def _display_result(value):
    """A notebook shows the value of a cell's last expression unless it is None (added by the conversion)."""
    if value is not None:
        display(value)

# %% [markdown] cell 0
# # Synthetic data generator — departments, roles, employees, vessels, containers, invoices
#
# > - Re-running this notebook reproduces `employees.csv`, `vessels.csv` and `containers.csv` **exactly** (fixed seeds, fixed reference date) and checks them against `Data/processed/synthetic/` (`save_or_verify` refuses to overwrite a file with different data).
# > - The invoice section reproduces the **pricing method** (ADR-004) and validates it, but **not the exact rows**: the stored invoices were finalized inside PostgreSQL (ADR-013). The database is the source of truth, so this notebook does **not** save or load invoices.
# > - The invoice section needs the database running and the credentials in `.env` (see `.env.example`).
# > - Dependencies come from `pyproject.toml` (`uv sync`); do not `pip install` inside the notebook.

# %% cell 1
import io
from pathlib import Path

import pandas as pd

PROJECT_ROOT = next(
    root for root in [Path.cwd(), *Path.cwd().parents]
    if (root / "Data").is_dir() and (root / "pyproject.toml").exists()
)

STRUCTURED_DIR = PROJECT_ROOT / "Data" / "processed" / "structured"
SYNTHETIC_DIR = PROJECT_ROOT / "Data" / "processed" / "synthetic"



# Columns the database owns and this notebook does not generate (filled by a migration, exported into the mirror).
DB_OWNED_COLUMNS = {"vessels.csv": ["mmsi"]}  # db/migrations/005_fill_vessels_mmsi.sql (ADR-028)


def save_or_verify(df, path):
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


print("Project root  :", PROJECT_ROOT)
print("Structured in :", STRUCTURED_DIR)
print("Synthetic out :", SYNTHETIC_DIR)

# %% cell 2
import pandas as pd
import random
from datetime import date, timedelta
from faker import Faker

# Faker's relative strings ("-15y") are relative to *today*, so re-running on another day
# shifted every hire_date. Anchor them to the day the canonical data was generated.
REFERENCE_DATE = date(2026, 9, 13)


def days_ago(years=0, days=0):
    """Same arithmetic as Faker's '-Ny' / '-Nd' strings (1 year = 365.24 days), anchored to REFERENCE_DATE."""
    return REFERENCE_DATE + timedelta(days=-(365.24 * years) - days)


fake = Faker()
random.seed(42)
Faker.seed(42)

# Departments
departments = {
    "Operations": 1,
    "Customs": 2,
    "Finance": 3,
    "HR": 4,
    "IT": 5
}

# Roles
roles = {
    "employee": 1,
    "manager": 2,
    "ceo": 3
}

employees = []

# 1 CEO
employees.append({
    "first_name": fake.first_name(),
    "last_name": fake.last_name(),
    "email": "ceo@nilegate.com",
    "role_id": roles["ceo"],
    "department_id": departments["Operations"],
    "hire_date": fake.date_between(start_date=days_ago(years=15), end_date=days_ago(years=5))
})

# 2 managers per department
manager_counter = 1

for department_name, department_id in departments.items():
    for _ in range(2):
        first_name = fake.first_name()
        last_name = fake.last_name()

        employees.append({
            "first_name": first_name,
            "last_name": last_name,
            "email": f"manager{manager_counter}@nilegate.com",
            "role_id": roles["manager"],
            "department_id": department_id,
            "hire_date": fake.date_between(start_date=days_ago(years=12), end_date=days_ago(years=2))
        })

        manager_counter += 1

# 89 regular employees
for i in range(1, 90):
    first_name = fake.first_name()
    last_name = fake.last_name()
    department_id = random.choice(list(departments.values()))

    employees.append({
        "first_name": first_name,
        "last_name": last_name,
        "email": f"employee{i}@nilegate.com",
        "role_id": roles["employee"],
        "department_id": department_id,
        "hire_date": fake.date_between(start_date=days_ago(years=8), end_date=days_ago(days=30)),
    })
    random.random()  # ADR-017: status removed; the draw it used is kept so later values stay identical

employees_df = pd.DataFrame(employees)

print(employees_df.shape)
print("\nRole distribution:")
print(employees_df["role_id"].value_counts().sort_index())

print("\nDepartment distribution:")
print(employees_df["department_id"].value_counts().sort_index())

_display_result(employees_df.head())

# %% cell 3
_display_result(save_or_verify(employees_df, SYNTHETIC_DIR / "employees.csv"))

# %% cell 4
import pandas as pd

ports_df = pd.read_csv(STRUCTURED_DIR / "ports.csv")

print("Shape:", ports_df.shape)
print("\nColumns:")
print(ports_df.columns.tolist())

_display_result(ports_df.head())

# %% cell 5
import pandas as pd
import random
import numpy as np

random.seed(42)
np.random.seed(42)


toll_df = pd.read_csv(STRUCTURED_DIR / "toll_rate_bands.csv")
# Canonical vessel categories from the validated toll data
vessel_types = toll_df["vessel_category"].unique().tolist()

# Countries available from the real ports dataset
countries = ports_df["Country"].dropna().unique().tolist()

# Real port LOCODEs
locodes = ports_df["LOCODE"].dropna().unique().tolist()

# Vessel SCNT ranges (approximate operational ranges for synthetic data)
scnt_ranges = {
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
    "Containerships": (5000, 200000)
}

vessels = []

for i in range(1, 501):

    vessel_type = random.choice(vessel_types)

    # Generate SCNT within the type-specific range
    min_tons, max_tons = scnt_ranges[vessel_type]
    scnt_tons = round(random.uniform(min_tons, max_tons), 2)

    # Select two different real ports
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
        "status": random.choices(
            ["In Transit", "At Port", "Anchored", "Completed"],
            weights=[45, 25, 15, 15],
            k=1
        )[0]
    })

vessels_df = pd.DataFrame(vessels)

print("Shape:", vessels_df.shape)

print("\nVessel type distribution:")
print(vessels_df["vessel_type"].value_counts())

print("\nCondition distribution:")
print(vessels_df["condition"].value_counts())

print("\nStatus distribution:")
print(vessels_df["status"].value_counts())

_display_result(vessels_df.head())

# %% cell 6
print("Duplicate IMO:", vessels_df["imo_number"].duplicated().sum())

print(
    "Same origin/destination:",
    (vessels_df["origin_locode"] == vessels_df["destination_locode"]).sum()
)

print(
    "Invalid origin LOCODEs:",
    (~vessels_df["origin_locode"].isin(ports_df["LOCODE"])).sum()
)

print(
    "Invalid destination LOCODEs:",
    (~vessels_df["destination_locode"].isin(ports_df["LOCODE"])).sum()
)

print(
    "Invalid vessel types:",
    (~vessels_df["vessel_type"].isin(vessel_types)).sum()
)

print(
    "Missing values:",
    vessels_df.isnull().sum().sum()
)

# %% cell 7
_display_result(save_or_verify(vessels_df, SYNTHETIC_DIR / "vessels.csv"))

# %% cell 8
import random
import pandas as pd

random.seed(42)

container_types = ["Dry", "Reefer", "Open Top", "Flat Rack"]

container_statuses = [
    "Empty",
    "Loaded",
    "In Transit",
    "At Port",
    "Delivered"
]

containers = []

for i in range(1, 1001):
    vessel = vessels_df.sample(1).iloc[0]

    origin = vessel["origin_locode"]
    destination = vessel["destination_locode"]

    containers.append({
        "container_number": f"NGCU{i:07d}",
        "container_type": random.choice(container_types),
        "size_ft": random.choice([20, 40]),
        "status": random.choice(container_statuses),
        "vessel_imo": vessel["imo_number"],
        "origin_locode": origin,
        "destination_locode": destination
    })

containers_df = pd.DataFrame(containers)

print("Shape:", containers_df.shape)
print(containers_df.head())

# %% cell 9
print("Duplicate container numbers:",
      containers_df["container_number"].duplicated().sum())

print("Invalid vessel IMO:",
      (~containers_df["vessel_imo"].isin(vessels_df["imo_number"])).sum())

print("Same origin/destination:",
      (containers_df["origin_locode"] == containers_df["destination_locode"]).sum())

print("Invalid origin LOCODEs:",
      (~containers_df["origin_locode"].isin(ports_df["LOCODE"])).sum())

print("Invalid destination LOCODEs:",
      (~containers_df["destination_locode"].isin(ports_df["LOCODE"])).sum())

print("Missing values:",
      containers_df.isnull().sum().sum())

# %% cell 10
# Map vessel IMO to PostgreSQL vessel_id
vessel_id_map = {
    imo: idx
    for idx, imo in enumerate(vessels_df["imo_number"], start=1)
}

containers_df["vessel_id"] = containers_df["vessel_imo"].map(vessel_id_map)

# Remove the temporary IMO column
containers_df = containers_df.drop(columns=["vessel_imo"])

# Reorder columns to match PostgreSQL table
containers_df = containers_df[
    [
        "container_number",
        "container_type",
        "size_ft",
        "status",
        "vessel_id",
        "origin_locode",
        "destination_locode"
    ]
]

print(containers_df.head())
print("\nShape:", containers_df.shape)
print("Missing vessel_id:", containers_df["vessel_id"].isnull().sum())

# %% cell 11
save_or_verify(containers_df, SYNTHETIC_DIR / "containers.csv")

print("Columns:", list(containers_df.columns))

# %% cell 12
toll_df = pd.read_csv(STRUCTURED_DIR / "toll_rate_bands.csv")

print(toll_df.shape)
print(toll_df.columns.tolist())
print(toll_df["vessel_category"].nunique())

# %% cell 13
def calculate_suez_toll(vessel_category, condition, scnt_tons, toll_df):
    bands = toll_df[
        (toll_df["vessel_category"] == vessel_category) &
        (toll_df["laden_ballast"] == condition)
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

# %% cell 14
test_vessel = vessels_df.iloc[0]

_display_result(test_vessel)

# %% cell 15
test_toll = calculate_suez_toll(
    vessel_category=test_vessel["vessel_type"],
    condition=test_vessel["condition"],
    scnt_tons=test_vessel["scnt_tons"],
    toll_df=toll_df
)

print("Vessel Type:", test_vessel["vessel_type"])
print("Condition:", test_vessel["condition"])
print("SCNT:", test_vessel["scnt_tons"])
print("Calculated Toll (SDR):", test_toll)

# %% cell 16
bands_test = toll_df[
    (toll_df["vessel_category"] == test_vessel["vessel_type"]) &
    (toll_df["laden_ballast"] == test_vessel["condition"]) &
    (toll_df["band_min_tons"] < test_vessel["scnt_tons"])
].sort_values("band_order").copy()

bands_test["tons_used"] = (
    bands_test["band_max_tons"]
    .fillna(test_vessel["scnt_tons"])
    .clip(upper=test_vessel["scnt_tons"])
    - bands_test["band_min_tons"]
)

bands_test["amount_sdr"] = (
    bands_test["tons_used"] *
    bands_test["rate_sdr_per_ton"]
)

print(
    bands_test[
        [
            "band_label",
            "band_min_tons",
            "band_max_tons",
            "rate_sdr_per_ton",
            "tons_used",
            "amount_sdr"
        ]
    ]
)

print("\nTotal SDR:", bands_test["amount_sdr"].sum())

# %% cell 17
import random
from datetime import date, timedelta

random.seed(42)

invoices = []

for i in range(1, 1001):
    vessel = vessels_df.sample(1).iloc[0]

    vessel_type = vessel["vessel_type"]
    condition = vessel["condition"]
    scnt_tons = vessel["scnt_tons"]

    # Special Floating Units only has Laden rates
    if vessel_type == "Special Floating Units":
        condition = "Laden"

    amount_sdr = calculate_suez_toll(
        vessel_category=vessel_type,
        condition=condition,
        scnt_tons=scnt_tons,
        toll_df=toll_df
    )

    invoice_date = date(2025, 1, 1) + timedelta(
        days=random.randint(0, 364)
    )

    invoices.append({
        "invoice_number": f"INV-{i:07d}",
        "vessel_imo": vessel["imo_number"],
        "invoice_date": invoice_date,
        "scnt_tons": scnt_tons,
        "amount_sdr": amount_sdr,
        "description": f"Suez Canal transit dues - {vessel_type}",
        "status": random.choice(["Paid", "Pending", "Issued"])
    })

invoices_df = pd.DataFrame(invoices)

print("Shape:", invoices_df.shape)
print(invoices_df.head())

# %% cell 18
invoices_df["amount"] = invoices_df["amount_sdr"]

invoices_df = invoices_df.drop(columns=["amount_sdr"])

print(invoices_df.shape)
print(invoices_df.columns.tolist())
print(invoices_df.head())

# %% cell 19
vessel_id_map = {
    imo: idx
    for idx, imo in enumerate(vessels_df["imo_number"], start=1)
}

invoices_df["vessel_id"] = invoices_df["vessel_imo"].map(vessel_id_map)

print("Missing vessel_id:", invoices_df["vessel_id"].isnull().sum())

# %% cell 20
def get_toll_band_id(vessel_category, condition, scnt_tons, toll_df):
    bands = toll_df[
        (toll_df["vessel_category"] == vessel_category) &
        (toll_df["laden_ballast"] == condition) &
        (toll_df["band_min_tons"] < scnt_tons) &
        (
            toll_df["band_max_tons"].isna() |
            (toll_df["band_max_tons"] >= scnt_tons)
        )
    ].sort_values("band_order")

    if bands.empty:
        return None

    return bands.iloc[0]["band_order"]

# %% cell 21
print(invoices_df.shape)
print(invoices_df.columns.tolist())

# %% cell 22
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

conn = connect_db()

print("Connected!")

# %% cell 23
toll_bands_db = pd.read_sql_query(
    """
    SELECT
        id,
        vessel_category,
        laden_ballast,
        band_order,
        band_label,
        band_min_tons,
        band_max_tons,
        rate_sdr_per_ton
    FROM toll_rate_bands
    ORDER BY id
    """,
    conn
)

conn.close()

# psycopg returns NUMERIC columns as Decimal; convert them so they compare cleanly with floats
numeric_columns = ["band_min_tons", "band_max_tons", "rate_sdr_per_ton"]
toll_bands_db[numeric_columns] = toll_bands_db[numeric_columns].astype(float)

print("Shape:", toll_bands_db.shape)
print(toll_bands_db.head())

# %% cell 24
# Lookup table using the real PostgreSQL band IDs
def get_toll_band_db_id(vessel_category, condition, scnt_tons):
    
    # Special Floating Units has Laden rates only
    if vessel_category == "Special Floating Units":
        condition = "Laden"

    bands = toll_bands_db[
        (toll_bands_db["vessel_category"] == vessel_category) &
        (toll_bands_db["laden_ballast"] == condition) &
        (toll_bands_db["band_min_tons"] < scnt_tons) &
        (
            toll_bands_db["band_max_tons"].isna() |
            (toll_bands_db["band_max_tons"] >= scnt_tons)
        )
    ].sort_values("band_order")

    if bands.empty:
        return None

    return int(bands.iloc[0]["id"])

# %% cell 25
# Add the real PostgreSQL toll_rate_band_id
vessel_lookup = vessels_df.set_index("imo_number")[
    ["vessel_type", "condition"]
]

invoices_df["toll_rate_band_id"] = invoices_df.apply(
    lambda row: get_toll_band_db_id(
        vessel_lookup.loc[row["vessel_imo"], "vessel_type"],
        vessel_lookup.loc[row["vessel_imo"], "condition"],
        row["scnt_tons"]
    ),
    axis=1
)

# rate_sdr_per_ton = rate of the terminal band (the band that contains the vessel's SCNT)
invoices_df["rate_sdr_per_ton"] = invoices_df["toll_rate_band_id"].map(
    toll_bands_db.set_index("id")["rate_sdr_per_ton"]
)

print("Missing rate_sdr_per_ton:",
      invoices_df["rate_sdr_per_ton"].isnull().sum())
print("Missing toll_rate_band_id:",
      invoices_df["toll_rate_band_id"].isnull().sum())

# %% cell 26
print(invoices_df.shape)
print("Missing vessel_id:", invoices_df["vessel_id"].isnull().sum())
print("Missing toll_rate_band_id:", invoices_df["toll_rate_band_id"].isnull().sum())

print(
    invoices_df[
        [
            "invoice_number",
            "vessel_id",
            "toll_rate_band_id",
            "invoice_date",
            "scnt_tons",
            "amount",
            "status"
        ]
    ].head()
)

# %% cell 27
invoices_df = invoices_df[
    [
        "invoice_number",
        "vessel_id",
        "toll_rate_band_id",
        "invoice_date",
        "scnt_tons",
        "rate_sdr_per_ton",
        "amount",
        "description",
        "status"
    ]
]

print("Shape:", invoices_df.shape)
print("Columns:", invoices_df.columns.tolist())

# %% cell 28
# Validate every generated invoice against the pricing rules (ADR-004)
vessels_by_id = vessels_df.assign(vessel_id=range(1, len(vessels_df) + 1)).set_index("vessel_id")
bands_by_id = toll_bands_db.set_index("id")

errors = []

for row in invoices_df.itertuples(index=False):
    vessel = vessels_by_id.loc[row.vessel_id]
    band = bands_by_id.loc[row.toll_rate_band_id]

    # Special Floating Units only have Laden rates
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
