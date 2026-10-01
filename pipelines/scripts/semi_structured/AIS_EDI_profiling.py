"""AIS + EDI profiling (no database)

Converted from Notebooks/semi_structured/AIS_EDI_profiling.ipynb (2026-10-01) by tools/nb_to_script.py: same cells, same order; `# %% cell N` = notebook cell N.
Run from the project root: uv run python tools/run.py pipelines/scripts/semi_structured/AIS_EDI_profiling.py

Reads:   Data/raw/semi-structured/ (AISHub sample, NOAA AccessAIS, IFTMIN sample)
Writes:  Data/processed/semi-structured/profiles/
Re-run:  safe: rewrites the same profiles
Final Checkpoint (what was done, problems, fixes): pipelines/checkpoints/semi_structured/AIS_EDI_profiling.md
"""

# %% [markdown] cell 0
# # AIS + EDI profiling (no database)
#
# Plan: `docs/plans/SemiStructured_MongoDB_plan.md`, Phase 1 (notebook phases 1–8 = plan steps 1.1–1.8).
#
# **Why this notebook exists.** The MongoDB collections (`ais_positions`, `ais_vessels`, `edi_messages`) must be designed
# from what the samples really contain, not from what AIS / EDIFACT documentation says they should contain. This notebook
# reads the three raw samples read-only, with no database and no `pymongo`, and saves one reviewed profile per source.
#
# Inputs (`Data/raw/semi-structured/`, never modified): `AISHub sample.json`, `NOAA AccessAIS.csv`,
# `IFTMIN_D12A_sample.edi`. Reference data for cross-checks comes from the CSV mirrors in `Data/processed/`.

# %% [markdown] cell 1
# ## Phase 1 — Setup and file registry
#
# Each input file gets a fingerprint (`sha256`, size), an encoding sniff (BOM, line endings) and a short look at its
# first bytes. The registry is the provenance used later by the loader (`provenance.source_file`, `source_sha256`), so a
# changed sample is detected instead of silently loaded.
#
# The shared helpers are defined here because several phases use them: MMSI classification (AIS sources) and the
# IMO check digit (AIS sources and our own `vessels.imo_number`).

# %% cell 2
import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd


def find_root(start: Path) -> Path:
    for p in [start, *start.parents]:
        if (p / "pyproject.toml").exists() and (p / "Data").is_dir():
            return p
    raise FileNotFoundError("project root not found above " + str(start))


ROOT = find_root(Path.cwd())
RAW = ROOT / "Data" / "raw" / "semi-structured"
PROCESSED = ROOT / "Data" / "processed"
OUT = PROCESSED / "semi-structured" / "profiles"

INPUTS = {
    "aishub": RAW / "AISHub sample.json",
    "noaa": RAW / "NOAA AccessAIS.csv",
    "iftmin": RAW / "IFTMIN_D12A_sample.edi",
}


def sniff(path: Path) -> dict:
    data = path.read_bytes()
    bom = "utf-8-sig" if data.startswith(b"\xef\xbb\xbf") else ("utf-16" if data[:2] in (b"\xff\xfe", b"\xfe\xff") else None)
    return {
        "file": str(path.relative_to(ROOT)).replace("\\", "/"),
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "bom": bom,
        "crlf": data.count(b"\r\n"),
        "lf_only": data.count(b"\n") - data.count(b"\r\n"),
        "non_ascii_bytes": sum(1 for b in data if b > 127),
        "head": data[:60].decode("utf-8", errors="replace"),
    }


source_files = {k: sniff(p) for k, p in INPUTS.items()}
for k, v in source_files.items():
    print(f"{k:7} {v['size_bytes']:>9,} B  sha256={v['sha256'][:12]}…  bom={v['bom']}  "
          f"crlf={v['crlf']} lf={v['lf_only']} non_ascii={v['non_ascii_bytes']}")
    print(f"        head: {v['head']!r}")

# %% cell 3
# ---- Shared helpers ----------------------------------------------------------------------------------------------


def mmsi_class(mmsi) -> str:
    """Classify an MMSI by its leading digits (ITU-R M.585). Only 'ship' records describe vessels."""
    s = str(mmsi).strip()
    if not s.isdigit() or len(s) != 9:
        return "invalid"
    if s.startswith("00"):
        return "coast_station"
    if s.startswith("0"):
        return "group"
    if s.startswith("111"):
        return "sar_aircraft"
    if s.startswith(("970", "972", "974")):
        return "sart_mob_epirb"
    if s.startswith("99"):
        return "aid_to_navigation"
    if s.startswith("98"):
        return "craft_with_parent_ship"
    if s.startswith("8"):
        return "handheld_vhf"
    if 201 <= int(s[:3]) <= 775:
        return "ship"
    return "invalid"


def imo_check_ok(imo) -> bool:
    """True when `imo` is a valid 7-digit IMO ship number (an optional 'IMO' prefix is allowed).

    Rule: multiply the first six digits by 7, 6, 5, 4, 3, 2; the last digit of the sum must equal the 7th digit.
    Absent values (None, NaN, '', 0) are not valid IMO numbers.
    """
    if imo is None or (isinstance(imo, float) and np.isnan(imo)):
        return False
    s = str(imo).strip().upper().removeprefix("IMO").strip()
    if s.endswith(".0"):  # numeric column read as float
        s = s[:-2]
    if len(s) != 7 or not s.isdigit() or s == "0000000":
        return False
    return sum(int(d) * w for d, w in zip(s[:6], range(7, 1, -1))) % 10 == int(s[6])


assert mmsi_class(211234567) == "ship" and mmsi_class("002111111") == "coast_station"
assert mmsi_class(992111111) == "aid_to_navigation" and mmsi_class(12345) == "invalid"
assert imo_check_ok(9074729) and imo_check_ok("IMO9074729")
assert not imo_check_ok(9074728) and not imo_check_ok(0) and not imo_check_ok(None) and not imo_check_ok("")
print("helpers ok")

# %% cell 4
# ---- Phase 1 validation ------------------------------------------------------------------------------------------
assert all(p.exists() for p in INPUTS.values()), "missing input file"
assert all(v["size_bytes"] > 0 for v in source_files.values())
assert len({v["sha256"] for v in source_files.values()}) == 3, "two inputs are identical"

actual_1 = {k: {"size_bytes": v["size_bytes"], "sha256": v["sha256"]} for k, v in source_files.items()}
REVIEWED_1 = {  # reviewed 2026-09-27
    "aishub": {"size_bytes": 5022280, "sha256": "c7511bf92eee1ea5289bfbdfb9ba7e361390f5cba9f92189d9c4497ed663c0b9"},
    "noaa": {"size_bytes": 107607, "sha256": "22eca1f4f9c9a3fb4654c0d8045de3a533e06037f8074761bcf6ea946629b590"},
    "iftmin": {"size_bytes": 530, "sha256": "3d0ddc4c58acce8e1c736f31fd10f7b674b7a970f03d3aaced0a061e6a175edc"},
}
if REVIEWED_1:
    assert actual_1 == REVIEWED_1, f"file registry changed: {actual_1}"
else:
    print("snapshot pending review:", json.dumps(actual_1))
print("✅ Phase 1 validation passed.")

# %% [markdown] cell 5
# ## Phase 2 — AISHub JSON: structure and coordinate format
#
# The AISHub web service usually answers with a two-element list: a header object (`ERROR`, `USERNAME`, `FORMAT`,
# `RECORDS`) followed by the list of records. This is **checked, not assumed**. The header's `USERNAME` is an account
# name, so it is never printed.
#
# `FORMAT` matters before any range check: format 1 is human-readable (degrees, knots), format 0 is the raw AIS encoding
# (latitude / longitude in 1/10,000 minute, SOG and COG in tenths). Reading format-0 numbers as degrees would make
# almost every position look invalid.
#
# **Finding (reviewed):** the sample is a plain list of 10,000 records with no header object, so `FORMAT` is inferred
# from the value ranges: all positions are degree-like → format 1. Every one of the 19 fields is a JSON string (numbers
# included), and the time field is `TSTAMP`, not `TIME` — the loader must convert types explicitly.

# %% cell 6
with open(INPUTS["aishub"], encoding="utf-8-sig") as fh:
    ais_raw = json.load(fh)

ais_header = None
if isinstance(ais_raw, list) and len(ais_raw) == 2 and isinstance(ais_raw[0], dict) and isinstance(ais_raw[1], list):
    ais_header, ais_records = ais_raw
    shape = "header + records"
elif isinstance(ais_raw, list) and all(isinstance(r, dict) for r in ais_raw):
    ais_records, shape = ais_raw, "records only"
elif isinstance(ais_raw, dict):
    list_keys = [k for k, v in ais_raw.items() if isinstance(v, list)]
    ais_records, shape = (ais_raw[list_keys[0]] if len(list_keys) == 1 else []), f"object, list keys {list_keys}"
else:
    raise ValueError(f"unexpected AISHub top-level type: {type(ais_raw).__name__}")

print("shape:", shape, "| records:", len(ais_records))
if ais_header is not None:
    print("header:", {k: ("<hidden>" if k.upper() == "USERNAME" else v) for k, v in ais_header.items()})

field_counts = Counter(k for r in ais_records for k in r)
field_types = {k: Counter(type(r[k]).__name__ for r in ais_records if k in r) for k in field_counts}
print(f"fields: {len(field_counts)}")
for k, n in field_counts.items():
    print(f"  {k:12} present {n:>6}  types {dict(field_types[k])}")

# %% cell 7
ais_df = pd.DataFrame(ais_records)
lat_col = next((c for c in ais_df.columns if c.upper() in ("LATITUDE", "LAT")), None)
lon_col = next((c for c in ais_df.columns if c.upper() in ("LONGITUDE", "LON")), None)
lat = pd.to_numeric(ais_df[lat_col], errors="coerce") if lat_col else pd.Series(dtype=float)
lon = pd.to_numeric(ais_df[lon_col], errors="coerce") if lon_col else pd.Series(dtype=float)

header_format = None if ais_header is None else ais_header.get("FORMAT")
share_out_of_degrees = float(((lat.abs() > 91) | (lon.abs() > 181)).mean()) if len(lat) else float("nan")
ais_format = int(header_format) if header_format is not None else (0 if share_out_of_degrees > 0.5 else 1)
print(f"lat/lon columns: {lat_col}/{lon_col} | header FORMAT={header_format} | "
      f"share outside degree ranges={share_out_of_degrees:.3f} -> format used: {ais_format}")
print("lat min/max:", lat.min(), lat.max(), "| lon min/max:", lon.min(), lon.max())

# %% cell 8
# ---- Phase 2 validation ------------------------------------------------------------------------------------------
assert len(ais_records) > 0, "no AISHub records"
if ais_header is not None and "RECORDS" in ais_header:
    assert int(ais_header["RECORDS"]) == len(ais_records), "header RECORDS != record count"
assert lat_col and lon_col, "no latitude / longitude field"
assert ais_format in (0, 1)
if ais_format == 1:  # after the format decision, the bulk of positions must be degree-like
    assert share_out_of_degrees < 0.05, "format 1 but many positions outside degree ranges"

actual_2 = {"shape": shape, "records": len(ais_records), "fields": sorted(field_counts), "format": ais_format}
REVIEWED_2 = {  # reviewed 2026-09-27: no header object, every value a string, positions already in degrees
    "shape": "records only", "records": 10000,
    "fields": ["A", "B", "C", "CALLSIGN", "COG", "D", "DEST", "DRAUGHT", "ETA", "HEADING", "IMO", "LATITUDE",
               "LONGITUDE", "MMSI", "NAME", "NAVSTAT", "SOG", "TSTAMP", "TYPE"],
    "format": 1,
}
if REVIEWED_2:
    assert actual_2 == REVIEWED_2, f"AISHub structure changed: {actual_2}"
else:
    print("snapshot pending review:", json.dumps(actual_2))
print("✅ Phase 2 validation passed.")

# %% [markdown] cell 9
# ## Phase 3 — AISHub JSON: field profile
#
# Every field is a string in the source, so this phase first converts each one explicitly (empty string → missing) and
# then checks it against its AIS meaning:
#
# - **Identity:** MMSI class (only `ship` MMSIs describe vessels), IMO check digit, and known **placeholders** that pass
#   a format check but carry no identity (`IMO` `0` / `1234567`, call sign `DATAHUB` / `0000000` / `0`). `1234567` even
#   has a valid check digit, which is why a reviewed placeholder list is needed on top of the checksum.
# - **Sentinels** (ITU-R M.1371): latitude 91 / longitude 181 = not available, SOG 102.3 = not available, COG 360 = not
#   available, HEADING 511 = not available. They become `null`, never numbers.
# - **Codes:** NAVSTAT (0–15, 15 = not defined) and ship TYPE (0–99) with their category labels.
# - **Voyage fields:** `DEST` is free text typed by the crew — it is matched against our 837 UN/LOCODEs only when it looks
#   like one; `ETA` is `MM-DD HH:MM` without a year, and `00-00 24:60` means not available.
# - **Duplicates and time coverage.**
#
# The parsing functions defined here are the ones the loader will reuse (copied, and checked against this profile).
#
# **Findings (reviewed):** a 30-minute snapshot (2024-11-19 20:00–20:30 UTC), one record per MMSI (10,000, no duplicates),
# so AISHub gives **no tracks**: it feeds `ais_vessels` and the NAVSTAT / ship-type diversity, not the movement model.
# 9,982 ship MMSIs; 18 non-ship (AtoN, SART, handheld, craft of a parent ship) and 5 invalid. IMO: only 3,903 valid,
# 6,050 placeholders (mostly `0`), 6 bad check digits → IMO is optional in every schema. All positions are valid; the
# sentinels hide 2,320 COG and 5,050 HEADING values. DEST is empty for 3,881 records and a known UN/LOCODE for 883.

# %% cell 10
import re
from datetime import timezone

NAVSTAT_LABELS = {
    0: "under way using engine", 1: "at anchor", 2: "not under command", 3: "restricted manoeuvrability",
    4: "constrained by draught", 5: "moored", 6: "aground", 7: "engaged in fishing", 8: "under way sailing",
    9: "reserved (HSC)", 10: "reserved (WIG)", 11: "power-driven towing astern", 12: "power-driven pushing / towing",
    13: "reserved", 14: "AIS-SART / MOB / EPIRB active", 15: "not defined",
}
IMO_PLACEHOLDERS = {"0", "1234567", "0000000", "9999999"}
CALLSIGN_PLACEHOLDERS = {"", "0", "0000000", "DATAHUB", "NONE", "UNKNOWN"}


def ship_type_category(code) -> str | None:
    """AIS ship-type code (0–99) -> category label (ITU-R M.1371 Table 53)."""
    if code is None or pd.isna(code):
        return None
    c = int(code)
    if c == 0:
        return "not available"
    if 20 <= c <= 29:
        return "wing in ground"
    if c in (30, 31, 32, 33, 34, 35, 36, 37):
        return {30: "fishing", 31: "towing", 32: "towing (large)", 33: "dredging / underwater ops", 34: "diving ops",
                35: "military ops", 36: "sailing", 37: "pleasure craft"}[c]
    if 40 <= c <= 49:
        return "high speed craft"
    if c in (50, 51, 52, 53, 54, 55, 58, 59):
        return {50: "pilot vessel", 51: "search and rescue", 52: "tug", 53: "port tender", 54: "anti-pollution",
                55: "law enforcement", 58: "medical transport", 59: "noncombatant ship"}[c]
    if 60 <= c <= 69:
        return "passenger"
    if 70 <= c <= 79:
        return "cargo"
    if 80 <= c <= 89:
        return "tanker"
    if 90 <= c <= 99:
        return "other type"
    return "reserved / invalid"


def num(s: pd.Series) -> pd.Series:
    """String column -> float; '' and unparsable values -> NaN."""
    return pd.to_numeric(s.astype(str).str.strip().replace("", np.nan), errors="coerce")


def ais_clean_positions(lat: pd.Series, lon: pd.Series, sog: pd.Series, cog: pd.Series, hdg: pd.Series) -> pd.DataFrame:
    """Apply the AIS 'not available' sentinels and range rules; returns cleaned values + a reason per bad position."""
    out = pd.DataFrame({"lat": lat, "lon": lon, "sog": sog, "cog": cog, "heading": hdg})
    pos_na = (lat == 91) | (lon == 181) | lat.isna() | lon.isna()
    pos_bad = ~pos_na & ((lat.abs() > 90) | (lon.abs() > 180))
    pos_zero = ~pos_na & (lat == 0) & (lon == 0)
    out["position_issue"] = np.select([pos_na, pos_bad, pos_zero], ["not_available", "out_of_range", "null_island"], None)
    out.loc[pos_na | pos_bad | pos_zero, ["lat", "lon"]] = np.nan
    out.loc[(sog >= 102.3) | (sog < 0), "sog"] = np.nan
    out.loc[(cog >= 360) | (cog < 0), "cog"] = np.nan
    out.loc[(hdg == 511) | (hdg < 0) | (hdg > 359), "heading"] = np.nan
    return out


def parse_eta(s: str):
    """'MM-DD HH:MM' -> (month, day, hour, minute) or None when not available / invalid."""
    m = re.fullmatch(r"(\d{2})-(\d{2}) (\d{2}):(\d{2})", str(s).strip())
    if not m:
        return None
    mo, d, h, mi = map(int, m.groups())
    if not (1 <= mo <= 12 and 1 <= d <= 31 and h <= 23 and mi <= 59):
        return None
    return mo, d, h, mi


PORT_LOCODES = set(pd.read_csv(PROCESSED / "structured" / "ports.csv", dtype=str)["LOCODE"])


def dest_locode(dest: str) -> str | None:
    """Return a 5-character UN/LOCODE when the free-text destination is one (spaces / '>' tolerated)."""
    t = re.sub(r"[\s>._-]", "", str(dest).upper())
    return t if re.fullmatch(r"[A-Z]{2}[A-Z2-9]{3}", t) else None

# %% cell 11
a = pd.DataFrame(ais_records).astype(str)
a_ts = pd.to_datetime(a["TSTAMP"].str.replace(" GMT", "", regex=False), format="%Y-%m-%d %H:%M:%S", errors="coerce", utc=True)
a_pos = ais_clean_positions(num(a["LATITUDE"]), num(a["LONGITUDE"]), num(a["SOG"]), num(a["COG"]), num(a["HEADING"]))
a_mmsi_class = a["MMSI"].map(mmsi_class)
a_imo = a["IMO"].str.strip()
a_imo_state = np.select(
    [a_imo.eq(""), a_imo.isin(IMO_PLACEHOLDERS), a_imo.map(imo_check_ok)],
    ["absent", "placeholder", "valid"], "invalid_check_digit").tolist()
a_cs = a["CALLSIGN"].str.strip().str.upper()
a_navstat = num(a["NAVSTAT"])
a_type = num(a["TYPE"])
a_dest_code = a["DEST"].map(dest_locode)
a_eta = a["ETA"].map(parse_eta)
a_static_missing = a["TYPE"].str.strip().eq("")

prof_aishub = {
    "records": len(a),
    "time_utc": {"min": a_ts.min().isoformat(), "max": a_ts.max().isoformat(), "unparsed": int(a_ts.isna().sum())},
    "duplicates": {"exact": int(a.duplicated().sum()), "mmsi": int(a["MMSI"].duplicated().sum()),
                   "mmsi_ts": int(a.duplicated(["MMSI", "TSTAMP"]).sum())},
    "mmsi_class": dict(Counter(a_mmsi_class)),
    "imo_state": dict(Counter(a_imo_state)),
    "callsign": {"placeholder_or_empty": int(a_cs.isin(CALLSIGN_PLACEHOLDERS).sum()),
                 "present": int((~a_cs.isin(CALLSIGN_PLACEHOLDERS)).sum())},
    "position_issue": dict(Counter(a_pos["position_issue"].dropna())),
    "not_available": {"sog": int(a_pos["sog"].isna().sum()), "cog": int(a_pos["cog"].isna().sum()),
                      "heading": int(a_pos["heading"].isna().sum())},
    "sog_quantiles": {str(q): float(a_pos["sog"].quantile(q)) for q in (0.5, 0.9, 0.99, 1.0)},
    "navstat": {int(k): v for k, v in sorted(Counter(a_navstat.dropna().astype(int)).items())},
    "ship_type_category": dict(Counter(a_type.map(ship_type_category).dropna())),
    "static_missing_rows": int(a_static_missing.sum()),
    "dims_unknown": int(((num(a["A"]) + num(a["B"])).fillna(0) == 0).sum()),
    "draught_zero": int((num(a["DRAUGHT"]) == 0).sum()),
    "dest": {"empty": int(a["DEST"].str.strip().eq("").sum()), "locode_like": int(a_dest_code.notna().sum()),
             "locode_in_ports": int(a_dest_code.isin(PORT_LOCODES).sum())},
    "eta": {"valid": int(a_eta.notna().sum()), "not_available": int(a_eta.isna().sum())},
}
for k, v in prof_aishub.items():
    print(f"{k:20} {v}")
print("NAVSTAT labels:", {k: NAVSTAT_LABELS.get(k) for k in prof_aishub["navstat"]})
print("top DEST LOCODE matches:", Counter(a_dest_code[a_dest_code.isin(PORT_LOCODES)]).most_common(5))

# %% cell 12
# ---- Phase 3 validation ------------------------------------------------------------------------------------------
assert prof_aishub["time_utc"]["unparsed"] == 0, "unparsed TSTAMP"
assert sum(prof_aishub["mmsi_class"].values()) == len(a)
assert sum(prof_aishub["imo_state"].values()) == len(a)
assert prof_aishub["callsign"]["placeholder_or_empty"] + prof_aishub["callsign"]["present"] == len(a)
assert prof_aishub["eta"]["valid"] + prof_aishub["eta"]["not_available"] == len(a)
assert set(prof_aishub["navstat"]) <= set(range(16)), "NAVSTAT outside 0-15"
assert a_pos[["lat", "lon"]].dropna().abs().le([90, 180]).all().all()
assert prof_aishub["duplicates"]["mmsi_ts"] == 0, "same MMSI and time twice"
# rows without static data are the same rows everywhere (TYPE, A-D and IMO empty together)
assert (a_static_missing == a["A"].str.strip().eq("")).all() and (a_static_missing <= a_imo.eq("")).all()

actual_3 = {k: prof_aishub[k] for k in ("records", "duplicates", "mmsi_class", "imo_state", "position_issue",
                                          "static_missing_rows", "dest", "eta")}
REVIEWED_3 = {  # reviewed 2026-09-27
    "records": 10000, "duplicates": {"exact": 0, "mmsi": 0, "mmsi_ts": 0},
    "mmsi_class": {"ship": 9982, "aid_to_navigation": 5, "invalid": 5, "craft_with_parent_ship": 3, "handheld_vhf": 4,
                   "sart_mob_epirb": 1},
    "imo_state": {"placeholder": 6050, "valid": 3903, "absent": 41, "invalid_check_digit": 6},
    "position_issue": {}, "static_missing_rows": 41,
    "dest": {"empty": 3881, "locode_like": 1582, "locode_in_ports": 883}, "eta": {"valid": 5293, "not_available": 4707},
}
if REVIEWED_3:
    assert json.loads(json.dumps(actual_3)) == REVIEWED_3, f"AISHub profile changed: {actual_3}"
else:
    print("snapshot pending review:", json.dumps(actual_3))
print("✅ Phase 3 validation passed.")

# %% [markdown] cell 13
# ## Phase 4 — NOAA AccessAIS CSV: field profile and track behaviour
#
# NOAA's Marine Cadastre exports are already decoded (degrees, knots, UTC `BaseDateTime` without a zone suffix) and use
# the same sentinels as raw AIS (HEADING 511, COG 360). Unlike AISHub, this sample holds **several fixes per vessel**, so
# it is the source of the movement model:
#
# - **Reporting intervals** per vessel, split by moving (SOG ≥ 0.5 kn) and stationary → the `ais_positions` granularity
#   and the synthetic reporting intervals (decision D11).
# - **Implied speed** between consecutive fixes (great-circle distance / time) compared with the reported SOG → the
#   "no teleporting" threshold used by the generator and the audit.
# - **Stop episodes** and **SOG per ship-type category** (moving fixes only) → the generator's speed distributions.
#
# The same identity checks as AISHub apply (MMSI class, IMO check digit — here with an `IMO` prefix — and placeholders).
#
# **Findings (reviewed):** 999 fixes of 54 vessels in **78 minutes** (2022-04-15 00:00–01:18 UTC) inside the
# Los Angeles / Long Beach harbour area: mostly moored (NAVSTAT 5: 442) and only **116 moving steps**. Reporting
# interval: median ~70 s moving, ~180 s stationary (the export is already thinned from the raw AIS rates).
# 6 same-MMSI-same-time duplicates (the loader removes them), 18 fixes with invalid MMSIs, IMO absent on 458 fixes but
# never a placeholder. Two short steps (2–8 s) produced 250–320 kn of implied speed from position jitter, so implied speed
# is measured on steps ≥ 10 s: 99th percentile 29.6 kn (fast passenger craft). **Limitation for the generator:** this is
# harbour behaviour (tankers 6–7 kn, no moving cargo fixes at all); open-sea speeds cannot come from this sample and
# will be documented defaults per ship-type category (plan risk "samples too small").

# %% cell 14
R_EARTH_NM = 3440.065


def haversine_nm(lat1, lon1, lat2, lon2):
    """Great-circle distance in nautical miles (vectorised)."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp, dl = p2 - p1, np.radians(np.asarray(lon2) - np.asarray(lon1))
    h = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * R_EARTH_NM * np.arcsin(np.sqrt(h))


n = pd.read_csv(INPUTS["noaa"], dtype=str, keep_default_na=False)
n_ts = pd.to_datetime(n["BaseDateTime"], format="%Y-%m-%dT%H:%M:%S", errors="coerce", utc=True)
n_pos = ais_clean_positions(num(n["LAT"]), num(n["LON"]), num(n["SOG"]), num(n["COG"]), num(n["Heading"]))
n_imo = n["IMO"].str.strip()
n_imo_state = np.select(
    [n_imo.eq(""), n_imo.str.removeprefix("IMO").isin(IMO_PLACEHOLDERS), n_imo.map(imo_check_ok)],
    ["absent", "placeholder", "valid"], "invalid_check_digit").tolist()

trk = pd.DataFrame({"mmsi": n["MMSI"], "ts": n_ts, "lat": n_pos["lat"], "lon": n_pos["lon"], "sog": n_pos["sog"],
                    "navstat": num(n["Status"]), "type": num(n["VesselType"])}).sort_values(["mmsi", "ts"])
g = trk.groupby("mmsi")
trk["dt_s"] = g["ts"].diff().dt.total_seconds()
trk["dist_nm"] = haversine_nm(g["lat"].shift(), g["lon"].shift(), trk["lat"], trk["lon"])
trk["implied_kn"] = trk["dist_nm"] / (trk["dt_s"] / 3600)
trk["moving"] = trk["sog"] >= 0.5
steps = trk[trk["dt_s"] > 0]
# Fixes only seconds apart turn GPS jitter into absurd speeds (0.2-0.6 nm in 2-8 s = 250-320 kn in this sample);
# implied speed is therefore measured only on steps of at least MIN_DT_S seconds, and the glitches are counted.
MIN_DT_S = 10


def q(s: pd.Series, qs=(0.1, 0.5, 0.9, 0.99)) -> dict:
    return {str(x): round(float(s.quantile(x)), 2) for x in qs} if len(s) else {}


fixes_per_mmsi = g.size()
span_h = (g["ts"].max() - g["ts"].min()).dt.total_seconds() / 3600
# a stop episode: consecutive stationary fixes of one vessel lasting at least 30 minutes
run_id = (trk["moving"] != g["moving"].shift()).cumsum()
runs = trk[~trk["moving"]].groupby([trk["mmsi"], run_id])["ts"].agg(["min", "max"])
stop_minutes = (runs["max"] - runs["min"]).dt.total_seconds() / 60

prof_noaa = {
    "records": len(n), "mmsi": int(n["MMSI"].nunique()),
    "time_utc": {"min": n_ts.min().isoformat(), "max": n_ts.max().isoformat(), "unparsed": int(n_ts.isna().sum())},
    "duplicates": {"exact": int(n.duplicated().sum()), "mmsi_ts": int(n.duplicated(["MMSI", "BaseDateTime"]).sum())},
    "mmsi_class": dict(Counter(n["MMSI"].map(mmsi_class))),
    "imo_state": dict(Counter(n_imo_state)),
    "position_issue": dict(Counter(n_pos["position_issue"].dropna())),
    "not_available": {"sog": int(n_pos["sog"].isna().sum()), "cog": int(n_pos["cog"].isna().sum()),
                      "heading": int(n_pos["heading"].isna().sum()), "status": int(n["Status"].eq("").sum())},
    "navstat": {int(k): v for k, v in sorted(Counter(trk["navstat"].dropna().astype(int)).items())},
    "ship_type_category": dict(Counter(trk["type"].map(ship_type_category).dropna())),
    "transceiver_class": dict(Counter(n["TransceiverClass"])),
    "fixes_per_mmsi": q(fixes_per_mmsi, (0.0, 0.5, 1.0)),
    "track_span_h": q(span_h, (0.0, 0.5, 1.0)),
    "interval_s": {"moving": q(steps.loc[steps["moving"], "dt_s"]), "stationary": q(steps.loc[~steps["moving"], "dt_s"])},
    "moving_steps": int(steps["moving"].sum()),
    "short_dt_glitches": int((steps["moving"] & (steps["dt_s"] < MIN_DT_S) & (steps["implied_kn"] > 40)).sum()),
    "implied_kn_moving": q(steps.loc[steps["moving"] & (steps["dt_s"] >= MIN_DT_S), "implied_kn"]),
    "implied_minus_sog_kn": q((steps["implied_kn"] - steps["sog"]).abs()),
    "stop_episodes_ge_30min": int((stop_minutes >= 30).sum()),
    "sog_moving_by_category": {c: q(s) for c, s in trk[trk["moving"]].groupby(trk["type"].map(ship_type_category))["sog"]},
}
for k, v in prof_noaa.items():
    print(f"{k:24} {v}")

# %% cell 15
# ---- Phase 4 validation ------------------------------------------------------------------------------------------
assert prof_noaa["time_utc"]["unparsed"] == 0, "unparsed BaseDateTime"
assert sum(prof_noaa["mmsi_class"].values()) == len(n) and sum(prof_noaa["imo_state"].values()) == len(n)
assert set(prof_noaa["navstat"]) <= set(range(16)), "Status outside 0-15"
assert trk[["lat", "lon"]].dropna().abs().le([90, 180]).all().all()
assert (steps["dt_s"] > 0).all() and len(steps) == len(n) - prof_noaa["mmsi"] - prof_noaa["duplicates"]["mmsi_ts"]
# the implied-speed threshold must come from real behaviour, not from glitches: the 99th percentile stays plausible
assert prof_noaa["implied_kn_moving"]["0.99"] < 40, "implausible implied speeds: inspect before using as a threshold"

actual_4 = {k: prof_noaa[k] for k in ("records", "mmsi", "time_utc", "duplicates", "mmsi_class", "imo_state",
                                        "position_issue", "navstat", "transceiver_class", "stop_episodes_ge_30min",
                                        "moving_steps", "short_dt_glitches")}
REVIEWED_4 = {  # reviewed 2026-09-27
    "records": 999, "mmsi": 54,
    "time_utc": {"min": "2022-04-15T00:00:00+00:00", "max": "2022-04-15T01:18:44+00:00", "unparsed": 0},
    "duplicates": {"exact": 0, "mmsi_ts": 6}, "mmsi_class": {"ship": 973, "craft_with_parent_ship": 8, "invalid": 18},
    "imo_state": {"absent": 458, "valid": 541}, "position_issue": {},
    "navstat": {"0": 149, "1": 34, "5": 442, "12": 63, "15": 19}, "transceiver_class": {"A": 707, "B": 292},
    "stop_episodes_ge_30min": 44, "moving_steps": 116, "short_dt_glitches": 2,
}
if REVIEWED_4:
    assert json.loads(json.dumps(actual_4)) == REVIEWED_4, f"NOAA profile changed: {actual_4}"
else:
    print("snapshot pending review:", json.dumps(actual_4))
print("✅ Phase 4 validation passed.")

# %% [markdown] cell 16
# ## Phase 5 — Cross-sample checks and our own identifiers
#
# ADR-028 keeps real AIS vessels apart from our 500 synthetic vessels, so their identifier spaces must not overlap. This
# phase measures that on both sides before any MMSI is generated:
#
# - MMSI / IMO overlap between the two AIS samples;
# - real IMO numbers vs `vessels.imo_number` (CSV mirror of the PostgreSQL table);
# - validity of our own identifiers: IMO check digit of the 500 vessels and the **ISO 6346** check digit of the 1,000
#   container numbers (owner code + category + serial + check digit; letters map to 10–38 skipping multiples of 11).
#
# Findings are reported, **never fixed** here: PostgreSQL is the system of record (ADR-013, ADR-028). The `flag_country`
# → MID coverage needs the ITU MID table (decision D5), so it moves to the migration step (plan Phase 4.2/4.3).
#
# **Findings (reviewed):** the samples barely overlap (3 MMSIs, 1 IMO) and **no real IMO equals one of ours** — the
# identifier spaces are disjoint today. Our own identifiers, however, are **sequential, not checksummed**:
# `imo_number` runs `9000001, 9000002, …` (only 50 of 500 pass the IMO check digit, i.e. by chance) and
# `container_number` runs `NGCU0000001, …` (101 of 1,000 pass ISO 6346). They are canonical in PostgreSQL and are not
# changed here; consequence for this phase: the loader, generators and audits must **not reject** our own vessels or
# containers on check digits (checks apply to real data only), and the question is raised to the owner.

# %% cell 17
ISO6346_LETTERS = dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ",
                           [10, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 34, 35,
                            36, 37, 38]))


def iso6346_ok(code) -> bool:
    """True when `code` is a valid ISO 6346 container number (4 letters, 6 digits, 1 check digit)."""
    s = str(code).strip().upper()
    if not re.fullmatch(r"[A-Z]{3}[UJZR]\d{7}", s):
        return False
    total = sum((ISO6346_LETTERS[ch] if ch.isalpha() else int(ch)) * 2 ** i for i, ch in enumerate(s[:10]))
    return total % 11 % 10 == int(s[10])


assert iso6346_ok("CSQU3054383") and not iso6346_ok("CSQU3054384") and not iso6346_ok("CSQ3054383")

vessels_csv = pd.read_csv(PROCESSED / "synthetic" / "vessels.csv", dtype=str)
containers_csv = pd.read_csv(PROCESSED / "synthetic" / "containers.csv", dtype=str)

real_imo = set(a_imo[pd.Series(a_imo_state).eq("valid").values]) | {
    s.removeprefix("IMO") for s, st in zip(n_imo, n_imo_state) if st == "valid"}
our_imo = set(vessels_csv["imo_number"])
our_imo_ok = vessels_csv["imo_number"].map(imo_check_ok)
cont_ok = containers_csv["container_number"].map(iso6346_ok)

prof_cross = {
    "mmsi_overlap_aishub_noaa": len(set(a["MMSI"]) & set(n["MMSI"])),
    "imo_overlap_aishub_noaa": len({x for x, st in zip(a_imo, a_imo_state) if st == "valid"}
                                   & {s.removeprefix("IMO") for s, st in zip(n_imo, n_imo_state) if st == "valid"}),
    "real_valid_imo": len(real_imo),
    "real_imo_equal_to_our_imo": sorted(real_imo & our_imo),
    "our_vessels": len(vessels_csv), "our_imo_check_digit_ok": int(our_imo_ok.sum()),
    "our_containers": len(containers_csv), "our_container_iso6346_ok": int(cont_ok.sum()),
    "our_flag_countries": int(vessels_csv["flag_country"].nunique()),
}
for k, v in prof_cross.items():
    print(f"{k:28} {v}")
print("sample of our IMO failing the check digit:", vessels_csv.loc[~our_imo_ok, "imo_number"].head(3).tolist())
print("sample of our containers failing ISO 6346:", containers_csv.loc[~cont_ok, "container_number"].head(3).tolist())

# %% cell 18
# ---- Phase 5 validation ------------------------------------------------------------------------------------------
assert prof_cross["our_vessels"] == 500 and prof_cross["our_containers"] == 1000
assert vessels_csv["imo_number"].is_unique and containers_csv["container_number"].is_unique

actual_5 = prof_cross
REVIEWED_5 = {  # reviewed 2026-09-27
    "mmsi_overlap_aishub_noaa": 3, "imo_overlap_aishub_noaa": 1, "real_valid_imo": 3928,
    "real_imo_equal_to_our_imo": [], "our_vessels": 500, "our_imo_check_digit_ok": 50, "our_containers": 1000,
    "our_container_iso6346_ok": 101, "our_flag_countries": 161,
}
if REVIEWED_5:
    assert json.loads(json.dumps(actual_5)) == REVIEWED_5, f"cross-sample profile changed: {actual_5}"
else:
    print("snapshot pending review:", json.dumps(actual_5))
print("✅ Phase 5 validation passed.")

# %% [markdown] cell 19
# ## Phase 6 — IFTMIN D12A: EDIFACT structure, qualifiers and business keys
#
# EDIFACT is a delimited text format. The optional `UNA` service string advice (exactly 6 characters after `UNA`) sets
# the component separator, element separator, decimal mark, **release character** (escape) and segment terminator;
# without `UNA` the defaults are `:+.? '`. A correct tokenizer must honour the release character (`?+` is a literal
# `+`), so it walks the text character by character instead of calling `split`.
#
# Structure checked: interchange envelope (`UNB` … `UNZ`), message envelope (`UNH` … `UNT`), the segment count in `UNT`
# (it counts every segment from `UNH` to `UNT` inclusive), matching references. Then every segment's qualifiers and the
# business keys the loader will index: message reference, document number, dates, parties, UN/LOCODEs, vessel, voyage,
# container numbers. The ordered segment list becomes the **template** for the EDI generator (plan Phase 7).
#
# **Findings (reviewed):** one interchange with one IFTMIN D:12A message, 18 segments, default separators, references
# consistent (UNB/UNZ, UNH/UNT). The sample is **self-described as synthetic** ("General cargo - synthetic sample") —
# `ARCHITECTURE.md` §3 calls it a "real template"; it is stored as `real_or_synthetic = synthetic` (template).
# Its `UNT` declares **17 segments but the message has 16** (UNH…UNT) — a sample error, kept as a flagged property of
# the document; the generator computes the count. The vessel is `VESSEL123` (code list 146), **not an IMO number**, and
# there is **no voyage number** (TDT element 2 empty): the generator adds both (IMO in TDT, voyage in the conveyance
# reference). Both UN/LOCODEs (`EGALY` loading, `NLRTM` discharge) are our ports; `MSCU1234567` fails ISO 6346.

# %% cell 20
def edi_tokenize(text: str) -> tuple[dict, list[list[list[str]]]]:
    """Split an EDIFACT interchange into segments -> elements -> components, honouring UNA and the release char."""
    text = text.replace("\r", "").replace("\n", "")
    seps = {"comp": ":", "elem": "+", "dec": ".", "rel": "?", "seg": "'"}
    if text.startswith("UNA"):
        una = text[3:9]
        seps = dict(zip(["comp", "elem", "dec", "rel", "_reserved", "seg"], una))
        seps.pop("_reserved")
        text = text[9:]
    segments, seg, elem, comp, i = [], [], [], [], 0
    while i < len(text):
        ch = text[i]
        if ch == seps["rel"] and i + 1 < len(text):
            comp.append(text[i + 1]); i += 2; continue
        if ch == seps["comp"]:
            elem.append("".join(comp)); comp = []
        elif ch == seps["elem"]:
            elem.append("".join(comp)); seg.append(elem); elem, comp = [], []
        elif ch == seps["seg"]:
            elem.append("".join(comp)); seg.append(elem); segments.append(seg); seg, elem, comp = [], [], []
        else:
            comp.append(ch)
        i += 1
    assert not (seg or elem or comp), "text after the last segment terminator"
    return seps, segments


def el(seg, e, c=0, default=""):
    """Component c of element e of a segment (element 0 is the tag), '' when absent."""
    return seg[e][c] if e < len(seg) and c < len(seg[e]) else default


assert edi_tokenize("UNA:+.? 'AAA+x?+y:z'")[1] == [[["AAA"], ["x+y", "z"]]]

edi_text = INPUTS["iftmin"].read_text(encoding="utf-8")
edi_seps, edi_segs = edi_tokenize(edi_text)
tags = [el(s, 0) for s in edi_segs]
i_unh, i_unt = tags.index("UNH"), tags.index("UNT")
unb, unh, unt, unz = (edi_segs[tags.index(t)] for t in ("UNB", "UNH", "UNT", "UNZ"))
by_tag = {t: [s for s in edi_segs if el(s, 0) == t] for t in dict.fromkeys(tags)}
# segments whose first element is a code qualifier (in GID it is the item number, in SEL the seal number)
QUALIFIER_TAGS = ("BGM", "DTM", "FTX", "NAD", "LOC", "TDT", "MEA", "EQD", "RFF")

edi_keys = {
    "interchange_ref": el(unb, 5), "sender": el(unb, 2), "recipient": el(unb, 3),
    "prepared": f"20{el(unb, 4, 0)} {el(unb, 4, 1)}",
    "message_ref": el(unh, 1), "message_type": ":".join(unh[2][:4]),
    "document_code": el(by_tag["BGM"][0], 1), "document_number": el(by_tag["BGM"][0], 2),
    "dates": {el(s, 1, 0): el(s, 1, 1) for s in by_tag.get("DTM", [])},
    "parties": {el(s, 1): el(s, 2) for s in by_tag.get("NAD", [])},
    "locations": {el(s, 1): el(s, 2) for s in by_tag.get("LOC", [])},
    "transport": [{"stage": el(s, 1), "conveyance_ref": el(s, 2), "mode": el(s, 3), "carrier": el(s, 5),
                   "vessel_id": el(s, 8, 0), "vessel_id_code_list": el(s, 8, 1), "vessel_name": el(s, 8, 3)}
                  for s in by_tag.get("TDT", [])],
    "equipment": [{"qualifier": el(s, 1), "number": el(s, 2), "size_type": el(s, 3), "iso6346_ok": iso6346_ok(el(s, 2))}
                  for s in by_tag.get("EQD", [])],
    "measures": [{"qualifier": el(s, 1), "unit": el(s, 3, 0), "value": el(s, 3, 1)} for s in by_tag.get("MEA", [])],
    "free_text": {el(s, 1): el(s, 4) for s in by_tag.get("FTX", [])},
}
prof_iftmin = {
    "separators": edi_seps, "segments": len(edi_segs), "tags_in_order": tags,
    "unt_declared": int(el(unt, 1)), "unt_actual": i_unt - i_unh + 1,
    "unh_unt_ref_match": el(unh, 1) == el(unt, 2), "unb_unz_ref_match": el(unb, 5) == el(unz, 2),
    "unz_message_count": int(el(unz, 1)), "messages": tags.count("UNH"),
    "qualifiers": {t: sorted({el(s, 1) for s in segs}) for t, segs in by_tag.items() if t in QUALIFIER_TAGS},
    "locodes_in_ports": {q: (v in PORT_LOCODES) for q, v in edi_keys["locations"].items()},
    "vessel_imo_present": any(imo_check_ok(t["vessel_id"]) for t in edi_keys["transport"]),
    "voyage_present": any(t["conveyance_ref"] for t in edi_keys["transport"]),
    "self_described_synthetic": any("synthetic" in v.lower() for v in edi_keys["free_text"].values()),
}
iftmin_template = [{"tag": el(s, 0), "qualifier": el(s, 1) if el(s, 0) in QUALIFIER_TAGS else None,
                    "elements": len(s) - 1} for s in edi_segs]
for k, v in prof_iftmin.items():
    print(f"{k:24} {v}")
print("keys:", json.dumps(edi_keys)[:900])

# %% cell 21
# ---- Phase 6 validation ------------------------------------------------------------------------------------------
assert tags[0] == "UNB" and tags[-1] == "UNZ" and tags[i_unh + 1] == "BGM", "envelope order"
assert prof_iftmin["unh_unt_ref_match"] and prof_iftmin["unb_unz_ref_match"]
assert prof_iftmin["unz_message_count"] == prof_iftmin["messages"] == 1
assert edi_keys["message_type"] == "IFTMIN:D:12A:UN"
assert all(prof_iftmin["locodes_in_ports"].values()), "a LOC code is not one of our ports"
# the tokenizer is lossless: re-joining the tokens reproduces the segment text (no release characters in this sample)
rejoined = "".join("+".join(":".join(e) for e in s) + "'" for s in edi_segs)
assert rejoined == edi_text.replace("\n", "").removeprefix("UNA:+.? '"), "tokenizer lost characters"

actual_6 = {k: prof_iftmin[k] for k in ("segments", "unt_declared", "unt_actual", "qualifiers", "locodes_in_ports",
                                          "vessel_imo_present", "voyage_present", "self_described_synthetic")}
actual_6["container_iso6346_ok"] = [e["iso6346_ok"] for e in edi_keys["equipment"]]
REVIEWED_6 = {  # reviewed 2026-09-27
    "segments": 18, "unt_declared": 17, "unt_actual": 16,
    "qualifiers": {"BGM": ["610"], "DTM": ["132", "137"], "FTX": ["AAA", "AAI"], "NAD": ["CN", "CZ"],
                   "LOC": ["11", "9"], "TDT": ["20"], "MEA": ["AAE"], "EQD": ["CN"]},
    "locodes_in_ports": {"9": True, "11": True}, "vessel_imo_present": False, "voyage_present": False,
    "self_described_synthetic": True, "container_iso6346_ok": [False],
}
if REVIEWED_6:
    assert json.loads(json.dumps(actual_6)) == REVIEWED_6, f"IFTMIN profile changed: {actual_6}"
else:
    print("snapshot pending review:", json.dumps(actual_6))
print("✅ Phase 6 validation passed.")

# %% [markdown] cell 22
# ## Phase 7 — Save the profiles and reload them from disk
#
# One JSON profile per source goes to `Data/processed/semi-structured/profiles/`, plus the IFTMIN template for the
# generator. Each file carries the source file registry entry (path, size, `sha256`), so a consumer can tell which
# sample a profile describes. No timestamps are written: re-running the notebook on the same samples rewrites
# byte-identical files. The files are reloaded and compared with the in-memory profiles (after a JSON round trip, which
# turns integer dictionary keys such as NAVSTAT codes into strings).

# %% cell 23
def to_json(obj):
    """JSON-safe copy (numpy scalars -> Python, tuples -> lists)."""
    return json.loads(json.dumps(obj, default=lambda o: o.item() if hasattr(o, "item") else str(o)))


profiles = {
    "aishub_profile.json": {"source": source_files["aishub"], "format": ais_format, "profile": prof_aishub},
    "noaa_profile.json": {"source": source_files["noaa"], "min_dt_s_for_implied_speed": MIN_DT_S, "profile": prof_noaa},
    "iftmin_profile.json": {"source": source_files["iftmin"], "profile": prof_iftmin, "business_keys": edi_keys},
    "iftmin_template.json": {"source": source_files["iftmin"], "message_type": edi_keys["message_type"],
                             "separators": edi_seps, "segments": iftmin_template},
    "cross_profile.json": {"sources": {k: v["sha256"] for k, v in source_files.items()}, "profile": prof_cross},
}
OUT.mkdir(parents=True, exist_ok=True)
for name, content in profiles.items():
    (OUT / name).write_text(json.dumps(to_json(content), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print({name: (OUT / name).stat().st_size for name in profiles})

# %% cell 24
# ---- Phase 7 validation ------------------------------------------------------------------------------------------
reloaded = {name: json.loads((OUT / name).read_text(encoding="utf-8")) for name in profiles}
for name, content in profiles.items():
    assert reloaded[name] == to_json(content), f"{name}: reloaded content differs"
assert reloaded["aishub_profile.json"]["profile"]["records"] == 10000
assert reloaded["noaa_profile.json"]["profile"]["records"] == 999
assert [s["tag"] for s in reloaded["iftmin_template.json"]["segments"]] == prof_iftmin["tags_in_order"]
assert {p["source"]["sha256"] for n, p in reloaded.items() if "source" in p} == {v["sha256"] for v in source_files.values()}

actual_7 = sorted(p.name for p in OUT.glob("*.json"))
REVIEWED_7 = ["aishub_profile.json", "cross_profile.json", "iftmin_profile.json", "iftmin_template.json",
              "noaa_profile.json"]
assert actual_7 == REVIEWED_7, f"unexpected files in {OUT}: {actual_7}"
print("✅ Phase 7 validation passed.")

# %% [markdown] cell 25
# ## Phase 8 — Final Checkpoint

# %% cell 26
final = {
    "inputs": {k: v["size_bytes"] for k, v in source_files.items()},
    "aishub": {"records": prof_aishub["records"], "ship_mmsi": prof_aishub["mmsi_class"]["ship"],
               "valid_imo": prof_aishub["imo_state"]["valid"], "span_min": 30},
    "noaa": {"fixes": prof_noaa["records"], "vessels": prof_noaa["mmsi"], "moving_steps": prof_noaa["moving_steps"],
             "implied_kn_p99": prof_noaa["implied_kn_moving"]["0.99"],
             "interval_s_median": {k: v["0.5"] for k, v in prof_noaa["interval_s"].items()}},
    "iftmin": {"segments": prof_iftmin["segments"], "unt_declared_vs_actual": [prof_iftmin["unt_declared"],
                                                                              prof_iftmin["unt_actual"]]},
    "ours": {"imo_check_ok": prof_cross["our_imo_check_digit_ok"],
             "container_iso6346_ok": prof_cross["our_container_iso6346_ok"],
             "real_imo_collisions": len(prof_cross["real_imo_equal_to_our_imo"])},
    "profiles_saved": len(actual_7),
}
REVIEWED_FINAL = {
    "inputs": {"aishub": 5022280, "noaa": 107607, "iftmin": 530},
    "aishub": {"records": 10000, "ship_mmsi": 9982, "valid_imo": 3903, "span_min": 30},
    "noaa": {"fixes": 999, "vessels": 54, "moving_steps": 116, "implied_kn_p99": 29.6,
             "interval_s_median": {"moving": 69.5, "stationary": 180.0}},
    "iftmin": {"segments": 18, "unt_declared_vs_actual": [17, 16]},
    "ours": {"imo_check_ok": 50, "container_iso6346_ok": 101, "real_imo_collisions": 0},
    "profiles_saved": 5,
}
assert to_json(final) == REVIEWED_FINAL, f"final summary changed: {to_json(final)}"
print(json.dumps(final, indent=1))
print("✅ Final Checkpoint validation passed.")

# %% [markdown] cell 27
# Final Checkpoint: see pipelines/checkpoints/semi_structured/AIS_EDI_profiling.md
