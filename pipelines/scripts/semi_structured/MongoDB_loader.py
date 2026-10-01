"""MongoDB loader — AIS + EDI (the only writer to MongoDB)

Origin:  Converted from Notebooks/semi_structured/MongoDB_loader.ipynb (archived in docs/archive/notebooks/).
         Refactored (ADR-036 D3), cleanup level (2026-10-01): the notebook's phases, code and validations are unchanged;
         cell markers, Jupyter display() and the conversion helpers became plain sections and print(); proven by
         `uv run python tools/nb_to_script.py check MongoDB_loader` (AST equal to the archived notebook).
Run:     uv run python tools/run.py pipelines/scripts/semi_structured/MongoDB_loader.py  (from the project root)

Reads:   Data/raw/semi-structured/; Data/processed/semi-structured/; PostgreSQL
Writes:  MongoDB ports_logistics: drops and reloads ais_positions, ais_vessels, edi_messages (ADR-031, the only MongoDB writer); a new timestamped report in Data/processed/semi-structured/load_audit/ per run
Re-run:  idempotent (same documents after every run); each run adds one new load report
Final Checkpoint (what was done, problems, fixes): pipelines/checkpoints/semi_structured/MongoDB_loader.md
"""

# %% MongoDB loader — AIS + EDI (the only writer to MongoDB)
# Plan: `docs/plans/SemiStructured_MongoDB_plan.md`, Phases 5 and 8 (ADR-029, ADR-031).
#
# **What it does.** Reads the real samples (`Data/raw/semi-structured/`) and the synthetic generator artifacts
# (`Data/processed/semi-structured/synthetic/`), normalises them into the collection specs of plan §3.2a, gives every
# input record exactly one disposition (`loaded` or `rejected:<reason>`), then **drops and recreates only its own three
# collections** (`ais_positions`, `ais_vessels`, `edi_messages`), loads them, reloads everything from MongoDB and
# re-validates it (counts, `$jsonSchema` audit, indexes, duplicates, coverage, content hash).
#
# **Why one writer.** Real and synthetic data share collections. If each producer wrote its own documents, a re-run of one
# would have to delete selectively and the collection state would depend on the order of runs. With files first and one
# loader, a run always rebuilds the same state from the same inputs (idempotent).
#
# **Access.** The notebook connects as the application user (`readWrite` on `ports_logistics` only, ADR-027) and reads
# PostgreSQL read-only. Credentials come from `.env` and are never printed.


# %% Phase 1 — Setup, connections and input fingerprints
# The raw samples must be the ones the profiling notebook reviewed: their `sha256` is compared with the saved profiles,
# so a changed sample stops the load instead of being loaded silently.

import hashlib
import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg
from pymongo import MongoClient


def find_root(start: Path) -> Path:
    for p in [start, *start.parents]:
        if (p / "pyproject.toml").exists() and (p / "Data").is_dir():
            return p
    raise FileNotFoundError("project root not found above " + str(start))


def load_env_file(root: Path) -> None:
    """KEY=VALUE lines of the project's .env into os.environ (existing variables win)."""
    for line in (root / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


ROOT = find_root(Path.cwd())
load_env_file(ROOT)
ENV = os.environ
RAW = ROOT / "Data" / "raw" / "semi-structured"
SEMI = ROOT / "Data" / "processed" / "semi-structured"
PROFILES = SEMI / "profiles"
SYNTH = SEMI / "synthetic"
AUDIT_DIR = SEMI / "load_audit"

client = MongoClient(host=ENV["MONGO_HOST"], port=int(ENV["MONGO_PORT"]), username=ENV["MONGO_APP_USER"],
                     password=ENV["MONGO_APP_PASSWORD"], authSource=ENV["MONGO_AUTH_SOURCE"], tz_aware=True,
                     serverSelectionTimeoutMS=5000)
mdb = client[ENV["MONGO_DB"]]


def pg_connect():
    return psycopg.connect(host=ENV["PGHOST"], port=ENV["PGPORT"], dbname=ENV["PGDATABASE"], user=ENV["PGUSER"],
                           password=ENV["PGPASSWORD"], options="-c default_transaction_read_only=on")


LOAD_RUN = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
LOADED_AT = datetime.now(timezone.utc).replace(microsecond=0)
RBAC = {"sensitivity_level": 1, "department": "Operations"}  # docs/rbac_mapping.md §3

INPUTS = {"aishub": RAW / "AISHub sample.json", "noaa": RAW / "NOAA AccessAIS.csv",
          "iftmin_sample": RAW / "IFTMIN_D12A_sample.edi"}
sha = {k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in INPUTS.items()}
profile_sha = {"aishub": json.loads((PROFILES / "aishub_profile.json").read_text(encoding="utf-8"))["source"]["sha256"],
               "noaa": json.loads((PROFILES / "noaa_profile.json").read_text(encoding="utf-8"))["source"]["sha256"],
               "iftmin_sample": json.loads((PROFILES / "iftmin_profile.json").read_text(encoding="utf-8"))["source"]["sha256"]}
print("mongo server:", client.server_info()["version"], "| database:", mdb.name, "| load_run:", LOAD_RUN)
with pg_connect() as conn:
    print("postgres vessels:", conn.execute("select count(*), count(mmsi) from vessels").fetchone())

# ---- Phase 1 validation ------------------------------------------------------------------------------------------
assert mdb.command("ping")["ok"] == 1.0
assert sha == profile_sha, "a raw sample changed since it was profiled: re-run AIS_EDI_profiling.ipynb first"
print("✅ Phase 1 validation passed.")


# %% Phase 2 — Parsing helpers (copied from the profiling notebook)
# The notebooks have no shared `.py` module yet, so the helpers validated in `AIS_EDI_profiling.ipynb` are copied here.
# A silent divergence is caught in Phases 3–4: the counts they produce are compared with the saved profiles.

IMO_PLACEHOLDERS = {"0", "1234567", "0000000", "9999999"}
CALLSIGN_PLACEHOLDERS = {"", "0", "0000000", "DATAHUB", "NONE", "UNKNOWN"}
PORT_LOCODES = set(pd.read_csv(ROOT / "Data" / "processed" / "structured" / "ports.csv", dtype=str)["LOCODE"])


def mmsi_class(mmsi) -> str:
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
    if imo is None or (isinstance(imo, float) and np.isnan(imo)):
        return False
    s = str(imo).strip().upper().removeprefix("IMO").strip()
    if s.endswith(".0"):
        s = s[:-2]
    if len(s) != 7 or not s.isdigit() or s == "0000000":
        return False
    return sum(int(d) * w for d, w in zip(s[:6], range(7, 1, -1))) % 10 == int(s[6])


def real_imo(raw) -> str | None:
    """Real-data IMO: valid check digit and not a placeholder, else None."""
    s = str(raw).strip().upper().removeprefix("IMO").strip()
    return s if s not in IMO_PLACEHOLDERS and imo_check_ok(s) else None


def num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.strip().replace("", np.nan), errors="coerce")


def ais_clean_positions(lat, lon, sog, cog, hdg) -> pd.DataFrame:
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
    m = re.fullmatch(r"(\d{2})-(\d{2}) (\d{2}):(\d{2})", str(s).strip())
    if not m:
        return None
    mo, d, h, mi = map(int, m.groups())
    return (mo, d, h, mi) if (1 <= mo <= 12 and 1 <= d <= 31 and h <= 23 and mi <= 59) else None


def dest_locode(dest: str) -> str | None:
    t = re.sub(r"[\s>._-]", "", str(dest).upper())
    return t if re.fullmatch(r"[A-Z]{2}[A-Z2-9]{3}", t) and t in PORT_LOCODES else None


def ship_type_category(code) -> str | None:
    if code is None or pd.isna(code):
        return None
    c = int(code)
    named = {30: "fishing", 31: "towing", 32: "towing (large)", 33: "dredging / underwater ops", 34: "diving ops",
             35: "military ops", 36: "sailing", 37: "pleasure craft", 50: "pilot vessel", 51: "search and rescue",
             52: "tug", 53: "port tender", 54: "anti-pollution", 55: "law enforcement", 58: "medical transport",
             59: "noncombatant ship"}
    if c == 0:
        return "not available"
    if c in named:
        return named[c]
    for lo, label in ((20, "wing in ground"), (40, "high speed craft"), (60, "passenger"), (70, "cargo"),
                      (80, "tanker"), (90, "other type")):
        if lo <= c <= lo + 9:
            return label
    return "reserved / invalid"


def edi_tokenize(text: str):
    text = text.replace("\r", "").replace("\n", "")
    seps = {"comp": ":", "elem": "+", "dec": ".", "rel": "?", "seg": "'"}
    if text.startswith("UNA"):
        seps = dict(zip(["comp", "elem", "dec", "rel", "_reserved", "seg"], text[3:9]))
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
    return seg[e][c] if e < len(seg) and c < len(seg[e]) else default


def blank_none(s: pd.Series, extra=()) -> pd.Series:
    """Stripped text; '' and the given placeholders become missing (explicit, version-independent)."""
    s = s.astype(str).str.strip()
    return s.where(~s.isin({"", *extra}), None)


def f_or_none(x):
    return None if x is None or pd.isna(x) else float(x)


def i_or_none(x):
    return None if x is None or pd.isna(x) else int(x)


def s_or_none(x):
    s = None if x is None or (isinstance(x, float) and np.isnan(x)) else str(x).strip()
    return s or None


assert imo_check_ok("IMO9074729") and not imo_check_ok("1234568") and real_imo("1234567") is None
assert mmsi_class("211234567") == "ship" and dest_locode("NL RTM") == "NLRTM"
print("✅ Phase 2 validation passed.")


# %% Phase 3 — Real AIS: normalise, give every record a disposition
# **Positions.** Every source row gets exactly one disposition, decided in this order: `invalid_mmsi`, `non_ship_mmsi`
# (AtoN, SART, handheld, craft of a parent ship: our model is ships), `position_unavailable`, `duplicate_mmsi_ts`
# (a time-series collection cannot enforce uniqueness, so the loader does — the first row wins), else `loaded`.
# AISHub contributes one fix per vessel (the latest known position of 9,982 real ships), NOAA the short harbour tracks.
#
# **Vessels.** One `ais_vessels` document per (`source`, ship MMSI). AISHub already has one record per MMSI; NOAA repeats
# static fields on every fix, so each field takes the **last non-empty value** in time. Placeholders become `null`
# (IMO `0` / `1234567`, call sign `DATAHUB` / `0000000`, dimensions 0, draught 0, ETA `00-00 24:60`); ETA keeps its raw
# `MM-DD HH:MM` text because AIS sends no year. Real vessels are never linked to PostgreSQL (`vessel_id: null`, ADR-028).

ais_raw = pd.DataFrame(json.loads(INPUTS["aishub"].read_text(encoding="utf-8"))).astype(str)
noaa_raw = pd.read_csv(INPUTS["noaa"], dtype=str, keep_default_na=False)


def position_frame(src: str, df: pd.DataFrame, ts: pd.Series, lat, lon, sog, cog, hdg, navstat, imo_col) -> pd.DataFrame:
    p = ais_clean_positions(num(lat), num(lon), num(sog), num(cog), num(hdg))
    f = pd.DataFrame({"source": src, "src_row": np.arange(len(df)), "mmsi": df["MMSI"].str.strip(), "ts": ts,
                      "lat": p["lat"], "lon": p["lon"], "sog": p["sog"], "cog": p["cog"], "heading": p["heading"],
                      "navstat": num(navstat), "imo": df[imo_col].map(real_imo), "position_issue": p["position_issue"]})
    cls = f["mmsi"].map(mmsi_class)
    reason = np.select([cls.eq("invalid"), cls.ne("ship"), f["position_issue"].notna() | f["ts"].isna()],
                       ["invalid_mmsi", "non_ship_mmsi", "position_unavailable"], "")
    f["reason"] = reason
    ok = f["reason"].eq("")
    # duplicates are decided among the rows that survived the earlier rules only
    dup = f[ok].duplicated(["mmsi", "ts"], keep="first").reindex(f.index, fill_value=False)
    f.loc[dup, "reason"] = "duplicate_mmsi_ts"
    f["disposition"] = np.where(f["reason"].eq(""), "loaded", "rejected:" + f["reason"])
    return f


ais_ts = pd.to_datetime(ais_raw["TSTAMP"].str.replace(" GMT", "", regex=False), format="%Y-%m-%d %H:%M:%S", utc=True)
noaa_ts = pd.to_datetime(noaa_raw["BaseDateTime"], format="%Y-%m-%dT%H:%M:%S", utc=True)
pos_real = pd.concat([
    position_frame("aishub", ais_raw, ais_ts, ais_raw["LATITUDE"], ais_raw["LONGITUDE"], ais_raw["SOG"], ais_raw["COG"],
                   ais_raw["HEADING"], ais_raw["NAVSTAT"], "IMO"),
    position_frame("noaa", noaa_raw, noaa_ts, noaa_raw["LAT"], noaa_raw["LON"], noaa_raw["SOG"], noaa_raw["COG"],
                   noaa_raw["Heading"], noaa_raw["Status"], "IMO"),
], ignore_index=True)
pos_real.loc[pos_real["navstat"].notna() & ~pos_real["navstat"].between(0, 15), "navstat"] = np.nan
print(pos_real.groupby(["source", "disposition"]).size().to_string())

def vessel_frame_aishub(df: pd.DataFrame, ts: pd.Series) -> pd.DataFrame:
    a, b, c, d = (num(df[k]) for k in "ABCD")
    length, beam, draught = (a + b), (c + d), num(df["DRAUGHT"])
    eta_ok = df["ETA"].map(parse_eta).notna()
    cs = df["CALLSIGN"].str.strip().str.upper()
    return pd.DataFrame({
        "source": "aishub", "mmsi": df["MMSI"].str.strip(), "imo": df["IMO"].map(real_imo),
        "call_sign": blank_none(cs, CALLSIGN_PLACEHOLDERS), "name": blank_none(df["NAME"]),
        "ship_type": num(df["TYPE"]), "length_m": length.where(length > 0), "beam_m": beam.where(beam > 0),
        "draught_m": draught.where(draught > 0), "destination_raw": blank_none(df["DEST"]),
        "destination_locode": df["DEST"].map(dest_locode), "eta_raw": df["ETA"].str.strip().where(eta_ok),
        "transceiver_class": None, "last_seen": ts})


def vessel_frame_noaa(df: pd.DataFrame, ts: pd.Series) -> pd.DataFrame:
    t = pd.DataFrame({
        "mmsi": df["MMSI"].str.strip(), "ts": ts, "imo": df["IMO"].map(real_imo),
        "call_sign": blank_none(df["CallSign"].str.upper(), CALLSIGN_PLACEHOLDERS),
        "name": blank_none(df["VesselName"]), "ship_type": num(df["VesselType"]),
        "length_m": num(df["Length"]), "beam_m": num(df["Width"]), "draught_m": num(df["Draft"]),
        "transceiver_class": blank_none(df["TransceiverClass"])})
    for k in ("length_m", "beam_m", "draught_m"):
        t[k] = t[k].where(t[k] > 0)
    t = t.sort_values(["mmsi", "ts"])
    g = t.groupby("mmsi")
    out = g[["imo", "call_sign", "name", "ship_type", "length_m", "beam_m", "draught_m", "transceiver_class"]].last()
    out["last_seen"] = g["ts"].max()
    out = out.reset_index()
    out["source"] = "noaa"
    out["destination_raw"] = out["destination_locode"] = out["eta_raw"] = None
    return out


ves_real = pd.concat([vessel_frame_aishub(ais_raw, ais_ts), vessel_frame_noaa(noaa_raw, noaa_ts)], ignore_index=True)
ves_real["class"] = ves_real["mmsi"].map(mmsi_class)
ves_rejected = ves_real[ves_real["class"].ne("ship")]
ves_real = ves_real[ves_real["class"].eq("ship")].drop(columns="class").reset_index(drop=True)
ves_real["ship_type"] = ves_real["ship_type"].where(ves_real["ship_type"].between(0, 99))
ves_real["ship_type_category"] = ves_real["ship_type"].map(ship_type_category)
print("vessels by source:", dict(Counter(ves_real["source"])), "| non-ship / invalid MMSIs not kept:",
      dict(Counter(ves_rejected["source"])))

# ---- Phase 3 validation ------------------------------------------------------------------------------------------
prof_a = json.loads((PROFILES / "aishub_profile.json").read_text(encoding="utf-8"))["profile"]
prof_n = json.loads((PROFILES / "noaa_profile.json").read_text(encoding="utf-8"))["profile"]
assert (pos_real["source"] == "aishub").sum() == prof_a["records"] and (pos_real["source"] == "noaa").sum() == prof_n["records"]
for src, prof in (("aishub", prof_a), ("noaa", prof_n)):  # same MMSI classification as the reviewed profile
    got = pos_real.loc[pos_real["source"] == src, "mmsi"].map(mmsi_class).value_counts().to_dict()
    assert got == prof["mmsi_class"], (src, got)
assert pos_real.groupby("source")["src_row"].apply(lambda s: s.is_unique and s.min() == 0).all()
loaded = pos_real[pos_real["disposition"] == "loaded"]
assert not loaded.duplicated(["mmsi", "ts"]).any() and loaded[["lat", "lon"]].notna().all().all()
assert ves_real.groupby("source")["mmsi"].apply(lambda s: s.is_unique).all()
assert set(ves_real.loc[ves_real["source"] == "aishub", "mmsi"]) == set(loaded.loc[loaded["source"] == "aishub", "mmsi"])

actual_3 = {"positions": {f"{s}|{d}": int(n) for (s, d), n in pos_real.groupby(["source", "disposition"]).size().items()},
            "vessels": {k: int(v) for k, v in Counter(ves_real["source"]).items()},
            "vessels_with_imo": {k: int(v) for k, v in ves_real.dropna(subset=["imo"]).groupby("source").size().items()}}
REVIEWED_3 = {  # reviewed 2026-09-27
    "positions": {"aishub|loaded": 9982, "aishub|rejected:invalid_mmsi": 5, "aishub|rejected:non_ship_mmsi": 13,
                  "noaa|loaded": 967, "noaa|rejected:duplicate_mmsi_ts": 6, "noaa|rejected:invalid_mmsi": 18,
                  "noaa|rejected:non_ship_mmsi": 8},
    "vessels": {"aishub": 9982, "noaa": 52}, "vessels_with_imo": {"aishub": 3903, "noaa": 26},
}
if REVIEWED_3:
    assert actual_3 == REVIEWED_3, f"real AIS dispositions changed: {actual_3}"
else:
    print("snapshot pending review:", json.dumps(actual_3))
print("✅ Phase 3 validation passed.")


# %% Phase 4 — EDI sample: parse into one `edi_messages` document
# The sample is a self-described synthetic template (profiling Phase 6), so it is stored with
# `real_or_synthetic = "synthetic"` and `source = "iftmin_sample"`. The raw text is kept verbatim; the parsed segments
# (tag + elements + components) and the business keys are what tools query. Its wrong `UNT` segment count (17 declared,
# 16 actual) is recorded in `flags`, not corrected: the document is stored as sent.

def edi_document(raw_text: str, source: str, real_or_synthetic: str, provenance: dict) -> dict:
    seps, segs = edi_tokenize(raw_text)
    tags = [el(s, 0) for s in segs]
    by = {t: [s for s in segs if el(s, 0) == t] for t in dict.fromkeys(tags)}
    unb, unh, unt, unz = (segs[tags.index(t)] for t in ("UNB", "UNH", "UNT", "UNZ"))
    flags = []
    if int(el(unt, 1)) != tags.index("UNT") - tags.index("UNH") + 1:
        flags.append("unt_count_mismatch")
    if el(unh, 1) != el(unt, 2):
        flags.append("unh_unt_ref_mismatch")
    if el(unb, 5) != el(unz, 2):
        flags.append("unb_unz_ref_mismatch")
    tdt = by.get("TDT", [[]])[0]
    vessel_id = el(tdt, 8, 0)
    containers = [el(s, 2) for s in by.get("EQD", []) if el(s, 1) == "CN"]
    rff = {el(s, 1, 0): el(s, 1, 1) for s in by.get("RFF", [])}
    return {
        "message_ref": el(unh, 1), "interchange_ref": el(unb, 5), "message_type": el(unh, 2, 0),
        "version": f"{el(unh, 2, 1)}:{el(unh, 2, 2)}", "document_number": el(by["BGM"][0], 2),
        "raw": raw_text, "separators": seps,
        "segments": [{"tag": s[0][0], "elements": s[1:]} for s in segs],
        "keys": {
            "sender": el(unb, 2), "recipient": el(unb, 3),
            "vessel_imo": vessel_id if imo_check_ok(vessel_id) or re.fullmatch(r"\d{7}", vessel_id or "") else None,
            "vessel_id_raw": vessel_id or None, "vessel_name": el(tdt, 8, 3) or None,
            "voyage": el(tdt, 2) or None, "carrier": el(tdt, 5) or None,
            "locodes": {el(s, 1): el(s, 2) for s in by.get("LOC", [])},
            "container_numbers": containers, "invoice_number": rff.get("IV"),
            "dates": {el(s, 1, 0): el(s, 1, 1) for s in by.get("DTM", [])},
            "parties": {el(s, 1): el(s, 2) for s in by.get("NAD", [])},
        },
        "flags": flags, "source": source, "real_or_synthetic": real_or_synthetic, "provenance": provenance, **RBAC,
    }


edi_real = [edi_document(INPUTS["iftmin_sample"].read_text(encoding="utf-8"), "iftmin_sample", "synthetic",
                         {"source_file": "Data/raw/semi-structured/IFTMIN_D12A_sample.edi",
                          "source_sha256": sha["iftmin_sample"], "load_run": LOAD_RUN, "loaded_at": LOADED_AT,
                          "generator": None})]
d = edi_real[0]
print({k: d[k] for k in ("message_ref", "interchange_ref", "message_type", "version", "document_number", "flags")})
print("keys:", d["keys"])

# ---- Phase 4 validation ------------------------------------------------------------------------------------------
assert d["flags"] == ["unt_count_mismatch"] and d["keys"]["vessel_imo"] is None and d["keys"]["voyage"] is None
assert d["keys"]["locodes"] == {"9": "EGALY", "11": "NLRTM"} and d["keys"]["container_numbers"] == ["MSCU1234567"]
assert len(d["segments"]) == 18 and d["raw"] == INPUTS["iftmin_sample"].read_text(encoding="utf-8")
SYNTHETIC = {"positions": [], "vessels": [], "edi": []}  # filled by the synthetic phases, when present
print("✅ Phase 4 validation passed.")


# %% Phase 5 — Synthetic artifacts: verify the manifests, normalise like the real data
# The generators wrote files with manifests (`AIS_generator.ipynb`, `EDI_generator.ipynb`). The loader recomputes each
# artifact's content hash and compares it with its manifest, so a partially written or edited artifact stops the load.
# Synthetic rows then go through **the same rules** as the real rows (MMSI class, positions, duplicates) — they are
# expected to pass them all, and any rejection would show in the dispositions.
#
# Provenance of a synthetic document: `source_file` = the generator's manifest, `source_sha256` = the manifest's hash
# (the manifest holds the content hash of every output file), `generator` = notebook, seed and as-of instant.

def content_sha(df: pd.DataFrame) -> str:
    return hashlib.sha256(pd.util.hash_pandas_object(df, index=False).to_numpy().tobytes()).hexdigest()


ais_manifest_path, edi_manifest_path = SYNTH / "ais_generation_manifest.json", SYNTH / "edi_generation_manifest.json"
ais_man = json.loads(ais_manifest_path.read_text(encoding="utf-8"))
edi_man = json.loads(edi_manifest_path.read_text(encoding="utf-8"))
syn_pos = pd.read_parquet(SYNTH / "ais_positions_synthetic.parquet")
syn_ves = pd.read_parquet(SYNTH / "ais_vessels_synthetic.parquet")
syn_voy = pd.read_parquet(SYNTH / "voyages_synthetic.parquet")
edi_payload = (SYNTH / "edi_messages_synthetic.jsonl").read_bytes()
checks = {"ais_positions_synthetic.parquet": content_sha(syn_pos) == ais_man["outputs"]["ais_positions_synthetic.parquet"]["content_sha256"],
          "ais_vessels_synthetic.parquet": content_sha(syn_ves) == ais_man["outputs"]["ais_vessels_synthetic.parquet"]["content_sha256"],
          "voyages_synthetic.parquet": content_sha(syn_voy) == ais_man["outputs"]["voyages_synthetic.parquet"]["content_sha256"],
          "edi_messages_synthetic.jsonl": hashlib.sha256(edi_payload).hexdigest() == edi_man["outputs"]["edi_messages_synthetic.jsonl"]["sha256"]}
assert all(checks.values()), f"artifact does not match its manifest: {checks}"

ais_prov = {"file": str(ais_manifest_path.relative_to(ROOT)).replace("\\", "/"),
            "sha": hashlib.sha256(ais_manifest_path.read_bytes()).hexdigest(),
            "gen": {"notebook": ais_man["generator"], "seed": ais_man["seed"], "asof_utc": ais_man["asof_utc"]}}
edi_prov = {"file": str(edi_manifest_path.relative_to(ROOT)).replace("\\", "/"),
            "sha": hashlib.sha256(edi_manifest_path.read_bytes()).hexdigest(),
            "gen": {"notebook": edi_man["generator"], "seed": edi_man["seed"]}}

# positions: the same frame layout and rules as position_frame() applied to the real samples
p = pd.DataFrame({"source": "synthetic_ais", "src_row": syn_pos["src_row"].astype(int), "mmsi": syn_pos["mmsi"].astype(str),
                  "ts": syn_pos["ts"], "lat": syn_pos["lat"], "lon": syn_pos["lon"], "sog": syn_pos["sog"],
                  "cog": syn_pos["cog"], "heading": syn_pos["heading"], "navstat": syn_pos["navstat"].astype(float),
                  "imo": syn_pos["imo"].astype(str), "position_issue": None})
cls = p["mmsi"].map(mmsi_class)
p["reason"] = np.select([cls.eq("invalid"), cls.ne("ship"), p["lat"].isna() | p["lon"].isna() | p["ts"].isna()],
                        ["invalid_mmsi", "non_ship_mmsi", "position_unavailable"], "")
dup = p[p["reason"].eq("")].duplicated(["mmsi", "ts"], keep="first").reindex(p.index, fill_value=False)
p.loc[dup, "reason"] = "duplicate_mmsi_ts"
p["disposition"] = np.where(p["reason"].eq(""), "loaded", "rejected:" + p["reason"])
p.attrs.update(src_sha={"synthetic_ais": ais_prov["sha"]}, src_file={"synthetic_ais": ais_prov["file"]},
               src_generator={"synthetic_ais": ais_prov["gen"]})

v = syn_ves.copy()
v["source"] = "synthetic_ais"
v["vessel_id"] = v["vessel_id"].astype(int)
v.attrs.update(p.attrs)

edi_syn = []
for line in edi_payload.decode("utf-8").splitlines():
    rec = json.loads(line)
    edi_syn.append(edi_document(rec["raw"], "synthetic_edi", "synthetic",
                                {"source_file": edi_prov["file"], "source_sha256": edi_prov["sha"], "load_run": LOAD_RUN,
                                 "loaded_at": LOADED_AT, "generator": edi_prov["gen"]}))

SYNTHETIC = {"positions": [p], "vessels": [v], "edi": edi_syn}
print("synthetic positions:", p["disposition"].value_counts().to_dict(), "| vessels:", len(v), "| edi:", len(edi_syn),
      "| edi flags:", Counter(f for d in edi_syn for f in d["flags"]))

# ---- Phase 5 validation ------------------------------------------------------------------------------------------
assert (p["disposition"] == "loaded").all(), "a synthetic fix broke a loading rule"
assert len(v) == 500 and v["mmsi"].is_unique and len(edi_syn) == 434
assert all(not d["flags"] for d in edi_syn), "a synthetic EDI message has envelope flags"
assert all(d["keys"]["vessel_imo"] and d["keys"]["voyage"] for d in edi_syn)
assert not set(v["mmsi"]) & set(ves_real["mmsi"]), "a synthetic MMSI equals a real one (ADR-028)"
print("✅ Phase 5 validation passed.")


# %% Load — collection specs, validators and indexes
# The specs follow plan §3.2a. The feature probe on MongoDB 8.0.32 (`db/mongo/003_probe_features.js`,
# `db/mongo/audit/`) decided how each collection is validated:
#
# | Collection | Kind | Validation |
# |---|---|---|
# | `ais_positions` | time-series (`ts`, `meta`, granularity `minutes`) | **no server validator possible** (8.0.32 refuses `$jsonSchema` and unique indexes on time-series) → checked in Python before insert + `$jsonSchema` audit query after load |
# | `ais_vessels` | regular | server `$jsonSchema` validator (`validationAction: error`) + the same audit query |
# | `edi_messages` | regular | server `$jsonSchema` validator + the same audit query |
#
# The same schema dictionaries serve as server validators and as audit queries (`{$nor: [schema]}` must match 0
# documents), so the rule is written once.

STR_OR_NULL, DBL_OR_NULL, INT_OR_NULL = ["string", "null"], ["double", "null"], ["int", "long", "null"]
RBAC_PROPS = {"sensitivity_level": {"bsonType": ["int", "long"], "enum": [1]},
              "department": {"bsonType": "string", "enum": ["Operations"]}}
PROV = {"bsonType": "object", "required": ["source_file", "source_sha256", "load_run", "loaded_at", "generator"],
        "properties": {"source_file": {"bsonType": "string"}, "source_sha256": {"bsonType": "string", "pattern": "^[0-9a-f]{64}$"},
                       "load_run": {"bsonType": "string"}, "loaded_at": {"bsonType": "date"},
                       "generator": {"bsonType": ["object", "null"]}}}
SOURCES = ["aishub", "noaa", "synthetic_ais"]
SCHEMAS = {
    "ais_positions": {"$jsonSchema": {
        "bsonType": "object",
        "required": ["ts", "meta", "loc", "sog", "cog", "heading", "navstat", "src_row", "sensitivity_level", "department"],
        "properties": {
            "ts": {"bsonType": "date"},
            "meta": {"bsonType": "object", "required": ["mmsi", "imo", "source", "real_or_synthetic", "load_run", "source_sha256"],
                     "properties": {"mmsi": {"bsonType": "string", "pattern": "^[2-7][0-9]{8}$"},
                                    "imo": {"bsonType": STR_OR_NULL, "pattern": "^[0-9]{7}$"},
                                    "source": {"enum": SOURCES}, "real_or_synthetic": {"enum": ["real", "synthetic"]},
                                    "load_run": {"bsonType": "string"}, "source_sha256": {"bsonType": "string"}}},
            "loc": {"bsonType": "object", "required": ["type", "coordinates"],
                    "properties": {"type": {"enum": ["Point"]},
                                   "coordinates": {"bsonType": "array", "minItems": 2, "maxItems": 2,
                                                   "items": {"bsonType": "double"}}}},
            "sog": {"bsonType": DBL_OR_NULL, "minimum": 0, "maximum": 102.2},
            "cog": {"bsonType": DBL_OR_NULL, "minimum": 0, "maximum": 359.99},
            "heading": {"bsonType": DBL_OR_NULL, "minimum": 0, "maximum": 359},
            "navstat": {"bsonType": INT_OR_NULL, "minimum": 0, "maximum": 15},
            "src_row": {"bsonType": ["int", "long"], "minimum": 0},
            **RBAC_PROPS}}},
    "ais_vessels": {"$jsonSchema": {
        "bsonType": "object",
        "required": ["mmsi", "imo", "call_sign", "name", "ship_type", "ship_type_category", "length_m", "beam_m",
                     "draught_m", "destination_raw", "destination_locode", "eta_raw", "transceiver_class", "last_seen",
                     "vessel_id", "source", "real_or_synthetic", "provenance", "sensitivity_level", "department"],
        "properties": {
            "mmsi": {"bsonType": "string", "pattern": "^[2-7][0-9]{8}$"},
            "imo": {"bsonType": STR_OR_NULL, "pattern": "^[0-9]{7}$"},
            "call_sign": {"bsonType": STR_OR_NULL}, "name": {"bsonType": STR_OR_NULL},
            "ship_type": {"bsonType": INT_OR_NULL, "minimum": 0, "maximum": 99},
            "ship_type_category": {"bsonType": STR_OR_NULL},
            "length_m": {"bsonType": DBL_OR_NULL, "minimum": 0}, "beam_m": {"bsonType": DBL_OR_NULL, "minimum": 0},
            "draught_m": {"bsonType": DBL_OR_NULL, "minimum": 0},
            "destination_raw": {"bsonType": STR_OR_NULL},
            "destination_locode": {"bsonType": STR_OR_NULL, "pattern": "^[A-Z]{2}[A-Z2-9]{3}$"},
            "eta_raw": {"bsonType": STR_OR_NULL, "pattern": "^[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}$"},
            "transceiver_class": {"bsonType": STR_OR_NULL, "enum": ["A", "B", None]},
            "last_seen": {"bsonType": "date"}, "vessel_id": {"bsonType": INT_OR_NULL, "minimum": 1},
            "source": {"enum": SOURCES}, "real_or_synthetic": {"enum": ["real", "synthetic"]},
            "provenance": PROV, **RBAC_PROPS}}},
    "edi_messages": {"$jsonSchema": {
        "bsonType": "object",
        "required": ["message_ref", "interchange_ref", "message_type", "version", "document_number", "raw", "separators",
                     "segments", "keys", "flags", "source", "real_or_synthetic", "provenance", "sensitivity_level", "department"],
        "properties": {
            "message_ref": {"bsonType": "string", "minLength": 1}, "interchange_ref": {"bsonType": "string", "minLength": 1},
            "message_type": {"enum": ["IFTMIN"]}, "version": {"enum": ["D:12A"]},
            "document_number": {"bsonType": "string"}, "raw": {"bsonType": "string"},
            "separators": {"bsonType": "object"},
            "segments": {"bsonType": "array", "minItems": 4,
                         "items": {"bsonType": "object", "required": ["tag", "elements"]}},
            "keys": {"bsonType": "object",
                     "required": ["vessel_imo", "voyage", "locodes", "container_numbers", "invoice_number", "dates"],
                     "properties": {"vessel_imo": {"bsonType": STR_OR_NULL, "pattern": "^[0-9]{7}$"},
                                    "container_numbers": {"bsonType": "array", "items": {"bsonType": "string"}},
                                    "locodes": {"bsonType": "object"}}},
            "flags": {"bsonType": "array", "items": {"bsonType": "string"}},
            "source": {"enum": ["iftmin_sample", "synthetic_edi"]}, "real_or_synthetic": {"enum": ["real", "synthetic"]},
            "provenance": PROV, **RBAC_PROPS}}},
}
INDEXES = {
    "ais_positions": [([("meta.mmsi", 1), ("ts", 1)], {"name": "mmsi_ts"}), ([("loc", "2dsphere")], {"name": "loc_2dsphere"})],
    "ais_vessels": [([("source", 1), ("mmsi", 1)], {"name": "source_mmsi_unique", "unique": True}),
                    ([("imo", 1)], {"name": "imo"}), ([("vessel_id", 1)], {"name": "vessel_id"})],
    "edi_messages": [([("source", 1), ("interchange_ref", 1), ("message_ref", 1)], {"name": "source_refs_unique", "unique": True}),
                     ([("keys.vessel_imo", 1)], {"name": "vessel_imo"}),
                     ([("keys.container_numbers", 1)], {"name": "container_numbers"}),
                     ([("keys.invoice_number", 1)], {"name": "invoice_number"})],
}
COLLECTIONS = list(SCHEMAS)
# MongoDB (6.3+) creates this index by itself on every time-series collection with a metaField. It covers the whole
# `meta` object, so `mmsi_ts` (meta.mmsi + ts) is still the one that serves "track of one vessel" queries.
AUTO_INDEXES = {"ais_positions": ["meta_1_ts_1"], "ais_vessels": [], "edi_messages": []}


# %% Load — build the documents
# Real and synthetic frames are concatenated here (`SYNTHETIC` is filled by the synthetic phases when the generator
# artifacts exist). Only `loaded` rows become documents; rejected rows stay in the dispositions for the coverage audit.
# Values are converted to plain Python types (`NaN`/`NA` → `None`, numbers → `float`/`int`) so BSON types match the schema.

def clean(v):
    if v is None or v is pd.NA or (isinstance(v, float) and np.isnan(v)):
        return None
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return float(v)
    return v


src_sha = {"aishub": sha["aishub"], "noaa": sha["noaa"]}
src_file = {"aishub": "Data/raw/semi-structured/AISHub sample.json", "noaa": "Data/raw/semi-structured/NOAA AccessAIS.csv"}
src_generator = {"aishub": None, "noaa": None}
for extra in SYNTHETIC["positions"] + SYNTHETIC["vessels"]:
    src_sha.update(extra.attrs.get("src_sha", {})); src_file.update(extra.attrs.get("src_file", {}))
    src_generator.update(extra.attrs.get("src_generator", {}))

positions_all = pd.concat([pos_real, *SYNTHETIC["positions"]], ignore_index=True)
vessels_all = pd.concat([ves_real, *SYNTHETIC["vessels"]], ignore_index=True)
if "vessel_id" not in vessels_all:
    vessels_all["vessel_id"] = None
edi_all = [*edi_real, *SYNTHETIC["edi"]]
real_of = lambda s: "real" if s in ("aishub", "noaa") else "synthetic"  # noqa: E731


def position_docs(df: pd.DataFrame):
    df = df[df["disposition"] == "loaded"]
    cols = {c: df[c].tolist() for c in ("ts", "mmsi", "imo", "source", "lon", "lat", "sog", "cog", "heading", "navstat", "src_row")}
    for i in range(len(df)):
        s = cols["source"][i]
        yield {"ts": cols["ts"][i].to_pydatetime(),
               "meta": {"mmsi": cols["mmsi"][i], "imo": clean(cols["imo"][i]), "source": s,
                        "real_or_synthetic": real_of(s), "load_run": LOAD_RUN, "source_sha256": src_sha[s]},
               "loc": {"type": "Point", "coordinates": [float(cols["lon"][i]), float(cols["lat"][i])]},
               "sog": clean(cols["sog"][i]), "cog": clean(cols["cog"][i]), "heading": clean(cols["heading"][i]),
               "navstat": clean(None if pd.isna(cols["navstat"][i]) else int(cols["navstat"][i])),
               "src_row": int(cols["src_row"][i]), **RBAC}


VESSEL_FIELDS = ["mmsi", "imo", "call_sign", "name", "ship_type", "ship_type_category", "length_m", "beam_m", "draught_m",
                 "destination_raw", "destination_locode", "eta_raw", "transceiver_class", "vessel_id"]


def vessel_docs(df: pd.DataFrame):
    for r in df.to_dict("records"):
        s = r["source"]
        doc = {k: clean(r.get(k)) for k in VESSEL_FIELDS}
        for k in ("ship_type", "vessel_id"):
            doc[k] = None if doc[k] is None else int(doc[k])
        for k in ("length_m", "beam_m", "draught_m"):
            doc[k] = None if doc[k] is None else float(doc[k])
        doc.update({"last_seen": pd.Timestamp(r["last_seen"]).to_pydatetime(), "source": s, "real_or_synthetic": real_of(s),
                    "provenance": {"source_file": src_file[s], "source_sha256": src_sha[s], "load_run": LOAD_RUN,
                                   "loaded_at": LOADED_AT, "generator": src_generator[s]}, **RBAC})
        yield doc


# Python-side validation of the time-series documents (the server cannot validate them): same rules as the schema
pos_loaded = positions_all[positions_all["disposition"] == "loaded"]
assert pos_loaded["mmsi"].str.fullmatch(r"[2-7]\d{8}").all()
assert pos_loaded["lat"].between(-90, 90).all() and pos_loaded["lon"].between(-180, 180).all()
assert pos_loaded["sog"].dropna().between(0, 102.2).all() and pos_loaded["cog"].dropna().between(0, 359.99).all()
assert pos_loaded["heading"].dropna().between(0, 359).all() and pos_loaded["navstat"].dropna().between(0, 15).all()
assert pos_loaded["ts"].notna().all() and not pos_loaded.duplicated(["mmsi", "ts"]).any()
assert pos_loaded["imo"].dropna().str.fullmatch(r"\d{7}").all()
print("documents to load:", {"ais_positions": len(pos_loaded), "ais_vessels": len(vessels_all), "edi_messages": len(edi_all)})
print("✅ Build validation passed.")


# %% Load — drop, recreate, insert
# Only the three collections of this notebook are dropped. Validators and time-series options are set at creation (the
# application user has no `collMod`, by design). Inserts are unordered batches: one bad document would fail its batch
# with a `BulkWriteError` listing it, which stops the notebook.

BATCH = 50_000
for name in COLLECTIONS:
    mdb.drop_collection(name)
mdb.create_collection("ais_positions", timeseries={"timeField": "ts", "metaField": "meta", "granularity": "minutes"})
mdb.create_collection("ais_vessels", validator=SCHEMAS["ais_vessels"], validationAction="error", validationLevel="strict")
mdb.create_collection("edi_messages", validator=SCHEMAS["edi_messages"], validationAction="error", validationLevel="strict")
for name, specs in INDEXES.items():
    for keys, opts in specs:
        mdb[name].create_index(keys, **opts)


def insert_batches(coll, docs) -> int:
    n, batch = 0, []
    for doc in docs:
        batch.append(doc)
        if len(batch) == BATCH:
            n += len(coll.insert_many(batch, ordered=False).inserted_ids); batch = []
    if batch:
        n += len(coll.insert_many(batch, ordered=False).inserted_ids)
    return n


inserted = {"ais_positions": insert_batches(mdb.ais_positions, position_docs(positions_all)),
            "ais_vessels": insert_batches(mdb.ais_vessels, vessel_docs(vessels_all)),
            "edi_messages": insert_batches(mdb.edi_messages, iter(edi_all))}
print("inserted:", inserted)


# %% Load — reload from MongoDB and re-validate
# Everything below reads **from MongoDB**, not from the frames: counts per collection / source / kind, the `$jsonSchema`
# audit (0 violations), the index list, no duplicate (`mmsi`, `ts`), coverage (every input record is either a document
# — found by `source` + `src_row` — or a reviewed rejection; 0 unaccounted), and a content hash that excludes the
# run-specific fields (`load_run`, `loaded_at`, `_id`), so a second run over the same inputs must give the same hash.

def group_counts(coll, key: str) -> dict:
    return {r["_id"]: r["n"] for r in coll.aggregate([{"$group": {"_id": key, "n": {"$sum": 1}}}])}


db_counts = {name: {f"{k['s']}|{k['k']}": v for k, v in
                    ((r["_id"], r["n"]) for r in mdb[name].aggregate([{"$group": {
                        "_id": {"s": "$meta.source" if name == "ais_positions" else "$source",
                                "k": "$meta.real_or_synthetic" if name == "ais_positions" else "$real_or_synthetic"},
                        "n": {"$sum": 1}}}]))} for name in COLLECTIONS}
schema_violations = {name: mdb[name].count_documents({"$nor": [SCHEMAS[name]]}) for name in COLLECTIONS}
index_names = {name: sorted(i["name"] for i in mdb[name].list_indexes() if i["name"] != "_id_") for name in COLLECTIONS}
dup_mmsi_ts = next(mdb.ais_positions.aggregate([
    {"$group": {"_id": {"m": "$meta.mmsi", "t": "$ts"}, "n": {"$sum": 1}}}, {"$match": {"n": {"$gt": 1}}},
    {"$count": "dups"}], allowDiskUse=True), {"dups": 0})["dups"]
real_linked = mdb.ais_vessels.count_documents({"real_or_synthetic": "real", "vessel_id": {"$ne": None}})

# coverage: rows found in MongoDB (source, src_row) + reviewed rejections = every input row
found = pd.DataFrame(list(mdb.ais_positions.find({}, {"_id": 0, "s": "$meta.source", "r": "$src_row"})))
found_keys = set(zip(found["s"], found["r"]))
expected_loaded = set(zip(pos_loaded["source"], pos_loaded["src_row"]))
rejected = positions_all[positions_all["disposition"] != "loaded"]
coverage = {s: {"input_rows": int((positions_all["source"] == s).sum()),
                "in_mongodb": int(sum(1 for k in found_keys if k[0] == s)),
                "rejected": int((rejected["source"] == s).sum())} for s in positions_all["source"].unique()}
for s, c in coverage.items():
    c["unaccounted"] = c["input_rows"] - c["in_mongodb"] - c["rejected"]


def content_hash(name: str, sort) -> str:
    h = hashlib.sha256()
    proj = {"_id": 0, "meta.load_run": 0} if name == "ais_positions" else {"_id": 0, "provenance.load_run": 0,
                                                                           "provenance.loaded_at": 0}
    for doc in mdb[name].find({}, proj).sort(sort).allow_disk_use(True):
        h.update(json.dumps(doc, sort_keys=True, default=str).encode())
    return h.hexdigest()


hashes = {"ais_positions": content_hash("ais_positions", [("meta.source", 1), ("src_row", 1)]),
          "ais_vessels": content_hash("ais_vessels", [("source", 1), ("mmsi", 1)]),
          "edi_messages": content_hash("edi_messages", [("source", 1), ("interchange_ref", 1), ("message_ref", 1)])}
print("counts:", db_counts)
print("schema violations:", schema_violations, "| dup (mmsi, ts):", dup_mmsi_ts, "| real vessels linked:", real_linked)
print("indexes:", index_names)
print("coverage:", coverage)
print("hashes:", {k: v[:16] for k, v in hashes.items()})

# ---- Reload validation -------------------------------------------------------------------------------------------
assert inserted == {"ais_positions": len(pos_loaded), "ais_vessels": len(vessels_all), "edi_messages": len(edi_all)}
assert sum(db_counts["ais_positions"].values()) == len(pos_loaded)
assert all(v == 0 for v in schema_violations.values()), schema_violations
assert index_names == {n: sorted([o["name"] for _, o in specs] + AUTO_INDEXES[n]) for n, specs in INDEXES.items()}, index_names
assert dup_mmsi_ts == 0 and real_linked == 0
assert found_keys == expected_loaded, "documents in MongoDB differ from the loaded rows"
assert all(c["unaccounted"] == 0 for c in coverage.values()), coverage
assert mdb.ais_positions.find_one({}, {"_id": 1}) is not None and "timeseries" in str(
    mdb.command("listCollections", filter={"name": "ais_positions"})["cursor"]["firstBatch"][0]["type"])
print("✅ Reload validation passed.")


# %% Consistency audit against PostgreSQL (hard gate, plan Phase 8)
# Read **from MongoDB** and compared with PostgreSQL (read-only), so the audit tests what tools will actually query:
#
# 1. every synthetic `mmsi` / `imo` pair (positions and vessels) equals `vessels`; every synthetic vessel is there once;
# 2. every UN/LOCODE (vessel destinations, EDI locations) is one of our ports; every EDI container exists and belongs to
#    the vessel whose IMO the message carries;
# 3. tracks start at the vessel's origin port and end where its status says (destination / anchorage / en route);
# 4. **no teleporting**, recomputed from the stored fixes (implied speed ≤ the profile threshold), and **at sea**: under-way
#    fixes more than 20 nm from every port of the route are on land only in canals / narrow waterways (1 km mask);
# 5. EDI and AIS tell the same story: the instruction date precedes the first fix, the voyage number and the estimated
#    arrival are those of the AIS voyage, and every invoice reference (`RFF+IV`) exists in PostgreSQL for the same vessel;
# 6. real data references nothing in PostgreSQL and shares no identifier with it (MMSI, IMO, call sign).

with pg_connect() as conn:
    def pgf(sql):
        cur = conn.execute(sql)
        return pd.DataFrame(cur.fetchall(), columns=[d.name for d in cur.description])
    pg_v = pgf("SELECT vessel_id, mmsi, imo_number, status, origin_locode, destination_locode FROM vessels")
    pg_ports = pgf("SELECT locode, lat, lon FROM ports").set_index("locode")
    pg_c = pgf("SELECT container_number, vessel_id FROM containers")
    pg_inv = pgf("SELECT invoice_number, vessel_id FROM invoices")
pg_vi = pg_v.set_index("vessel_id")
imo_by_mmsi = pg_v.set_index("mmsi")["imo_number"]

syn = pd.DataFrame(list(mdb.ais_positions.find({"meta.real_or_synthetic": "synthetic"},
                                               {"_id": 0, "mmsi": "$meta.mmsi", "imo": "$meta.imo", "ts": 1,
                                                "lon": {"$arrayElemAt": ["$loc.coordinates", 0]},
                                                "lat": {"$arrayElemAt": ["$loc.coordinates", 1]}, "navstat": 1})))
syn["ts"] = pd.to_datetime(syn["ts"], utc=True)
syn = syn.sort_values(["mmsi", "ts"]).reset_index(drop=True)
sv = pd.DataFrame(list(mdb.ais_vessels.find({"real_or_synthetic": "synthetic"}, {"_id": 0, "mmsi": 1, "imo": 1,
                                                                                 "vessel_id": 1, "destination_locode": 1,
                                                                                 "call_sign": 1})))
rv = pd.DataFrame(list(mdb.ais_vessels.find({"real_or_synthetic": "real"}, {"_id": 0, "mmsi": 1, "imo": 1, "call_sign": 1})))
edi = list(mdb.edi_messages.find({"source": "synthetic_edi"}, {"_id": 0, "keys": 1}))

audit = {}
# 1. identity
audit["positions_pair_mismatch"] = int((syn["imo"] != syn["mmsi"].map(imo_by_mmsi)).sum())
audit["vessels_pair_mismatch"] = int((sv["imo"] != sv["mmsi"].map(imo_by_mmsi)).sum()
                                     + (sv["vessel_id"] != sv["mmsi"].map(pg_v.set_index("mmsi")["vessel_id"])).sum())
audit["synthetic_vessels_vs_pg"] = [len(sv), int(sv["mmsi"].nunique()), len(pg_v), int(syn["mmsi"].nunique())]
# 2. codes and containers
audit["unknown_locodes"] = int((~sv["destination_locode"].isin(pg_ports.index)).sum()
                               + sum(not set(d["keys"]["locodes"].values()) <= set(pg_ports.index) for d in edi))
cont_vessel = pg_c.set_index("container_number")["vessel_id"]
edi_boxes = [(b, d["keys"]["vessel_imo"]) for d in edi for b in d["keys"]["container_numbers"]]
audit["edi_containers"] = [len(edi_boxes), len({b for b, _ in edi_boxes}), len(pg_c)]
audit["edi_container_vessel_mismatch"] = sum(b not in cont_vessel.index or pg_vi.loc[cont_vessel[b], "imo_number"] != imo
                                             for b, imo in edi_boxes)
# 3. start / end
g = syn.groupby("mmsi")
first, last = g.head(1).set_index("mmsi"), g.tail(1).set_index("mmsi")
meta_v = pg_v.set_index("mmsi").loc[first.index]


def dist_to(ports_col, frame):
    pl = pg_ports.loc[meta_v[ports_col]]
    return pd.Series(gc_dist_nm(frame["lat"].to_numpy(), frame["lon"].to_numpy(), pl["lat"].to_numpy(), pl["lon"].to_numpy()),
                     index=frame.index)


def gc_dist_nm(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp, dl = p2 - p1, np.radians(np.asarray(lon2) - np.asarray(lon1))
    h = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * 3440.065 * np.arcsin(np.sqrt(np.clip(h, 0, 1)))


d0, d1 = dist_to("origin_locode", first), dist_to("destination_locode", last.loc[first.index])
st = meta_v["status"]
audit["start_not_at_origin"] = int((d0 > 1.0).sum())
audit["arrived_not_at_destination"] = int((d1[st.isin(["At Port", "Completed"])] > 1.0).sum())
# the anchorage is 5 nm before the port ALONG the sea path, so the straight line is 0.5-5.5 nm (as in the generator)
audit["anchored_not_near_destination"] = int((~d1[st == "Anchored"].between(0.5, 5.5)).sum())
audit["in_transit_not_under_way"] = int((last.loc[st[st == "In Transit"].index, "navstat"] != 0).sum())
# 4. teleporting, from the stored fixes
dt_h = g["ts"].diff().dt.total_seconds() / 3600
step = gc_dist_nm(g["lat"].shift().to_numpy(), g["lon"].shift().to_numpy(), syn["lat"].to_numpy(), syn["lon"].to_numpy())
implied = pd.Series(step, index=syn.index) / dt_h
teleport_kn = json.loads((SYNTH / "ais_generation_manifest.json").read_text(encoding="utf-8"))["params"]["teleport_kn"]
audit["max_implied_kn"] = round(float(implied.max()), 2)
audit["teleport_steps"] = int((implied > teleport_kn).sum())
# 4b. at sea: under-way fixes (NAVSTAT 0) more than 20 nm from every port of the vessel's route, on land in the 1 km mask
from global_land_mask import globe  # noqa: E402

route_ports = syn_voy.set_index("vessel_id")["route"].str.split(">")
vid_by_mmsi = pg_v.set_index("mmsi")["vessel_id"]
far = np.zeros(len(syn), dtype=bool)
for mmsi, idx in syn.groupby("mmsi").groups.items():
    rp = pg_ports.loc[route_ports[vid_by_mmsi[mmsi]]]
    sub = syn.loc[idx]
    dmin = np.min([gc_dist_nm(sub["lat"].to_numpy(), sub["lon"].to_numpy(), la, lo) for la, lo in zip(rp["lat"], rp["lon"])], axis=0)
    far[np.asarray(idx)] = dmin > 20
open_sea = far & (syn["navstat"] == 0).to_numpy()
audit["open_sea_fixes"] = int(open_sea.sum())
audit["open_sea_fixes_on_land"] = int((open_sea & globe.is_land(syn["lat"].to_numpy(), syn["lon"].to_numpy())).sum())
# 5. EDI vs AIS
voy = syn_voy.set_index("vessel_id")
first_ts = g["ts"].min()
mm_by_imo = pg_v.set_index("imo_number")["mmsi"]
vid_by_imo = pg_v.set_index("imo_number")["vessel_id"]
audit["edi_voyage_mismatch"] = sum(d["keys"]["voyage"] != voy.loc[vid_by_imo[d["keys"]["vessel_imo"]], "voyage_no"] for d in edi)
audit["edi_arrival_mismatch"] = sum(d["keys"]["dates"]["132"] != pd.Timestamp(voy.loc[vid_by_imo[d["keys"]["vessel_imo"]], "arrival_ts"]).strftime("%Y%m%d")
                                    for d in edi)
audit["edi_instruction_after_first_fix"] = sum(
    pd.Timestamp(d["keys"]["dates"]["137"], tz="UTC") > first_ts[mm_by_imo[d["keys"]["vessel_imo"]]] for d in edi)
# EDI -> invoice link (owner decision 2026-09-28): the referenced invoice exists and belongs to the message vessel
inv_vessel = pg_inv.set_index("invoice_number")["vessel_id"]
with_inv = [d for d in edi if d["keys"]["invoice_number"]]
audit["edi_with_invoice"] = len(with_inv)
audit["edi_invoice_mismatch"] = int(sum(d["keys"]["invoice_number"] not in inv_vessel.index
                                    or inv_vessel[d["keys"]["invoice_number"]] != vid_by_imo[d["keys"]["vessel_imo"]]
                                    for d in with_inv))
# 6. real vs ours
audit["real_shared_mmsi"] = len(set(rv["mmsi"]) & set(pg_v["mmsi"]))
audit["real_shared_imo"] = len(set(rv["imo"].dropna()) & set(pg_v["imo_number"]))
audit["real_shared_call_sign"] = len(set(rv["call_sign"].dropna()) & set(sv["call_sign"]))
audit["real_linked_to_pg"] = mdb.ais_vessels.count_documents({"real_or_synthetic": "real", "vessel_id": {"$ne": None}})
print(json.dumps(audit, indent=1))

# ---- Consistency audit validation --------------------------------------------------------------------------------
REVIEWED_AUDIT = {
    "positions_pair_mismatch": 0, "vessels_pair_mismatch": 0, "synthetic_vessels_vs_pg": [500, 500, 500, 500],
    "unknown_locodes": 0, "edi_containers": [1000, 1000, 1000], "edi_container_vessel_mismatch": 0,
    "start_not_at_origin": 0, "arrived_not_at_destination": 0, "anchored_not_near_destination": 0,
    "in_transit_not_under_way": 0, "teleport_steps": 0, "edi_voyage_mismatch": 0, "edi_arrival_mismatch": 0,
    "edi_instruction_after_first_fix": 0, "edi_with_invoice": 376, "edi_invoice_mismatch": 0, "real_shared_mmsi": 0, "real_shared_imo": 0, "real_shared_call_sign": 0,
    "real_linked_to_pg": 0,
}
got = {k: audit[k] for k in REVIEWED_AUDIT}
assert got == REVIEWED_AUDIT, {k: (got[k], REVIEWED_AUDIT[k]) for k in got if got[k] != REVIEWED_AUDIT[k]}
assert audit["max_implied_kn"] <= teleport_kn
# canals and narrow waterways (Suez first) are finer than the 1 km mask: reviewed count and a 1.5 % ceiling
assert audit["open_sea_fixes_on_land"] / audit["open_sea_fixes"] < 0.015 and audit["open_sea_fixes_on_land"] == 12156, audit
print("✅ Consistency audit passed.")


# %% Load report and Final Checkpoint
# Each run writes `Data/processed/semi-structured/load_audit/<load_run>.json` (counts, dispositions, audits, index list,
# content hashes, input fingerprints) and `<load_run>_rejected.csv` (every rejected input row with its reason). The
# reviewed snapshot compares the counts **and the content hashes**: a second run over the same inputs must reproduce the
# same MongoDB content exactly (idempotency).

AUDIT_DIR.mkdir(parents=True, exist_ok=True)
report = {
    "load_run": LOAD_RUN, "loaded_at": LOADED_AT.isoformat(), "mongo_version": client.server_info()["version"],
    "inputs": {k: {"file": src_file.get(k, "Data/raw/semi-structured/IFTMIN_D12A_sample.edi"),
                   "sha256": src_sha.get(k, sha.get(k))} for k in [*src_sha, "iftmin_sample"]},
    "dispositions": {f"{s}|{d}": int(n) for (s, d), n in positions_all.groupby(["source", "disposition"]).size().items()},
    "counts": db_counts, "schema_violations": schema_violations, "duplicate_mmsi_ts": dup_mmsi_ts,
    "real_vessels_linked": real_linked, "indexes": index_names, "coverage": coverage, "content_sha256": hashes,
    "consistency_audit": audit,
}
(AUDIT_DIR / f"{LOAD_RUN}.json").write_text(json.dumps(report, indent=1, default=str) + "\n", encoding="utf-8")
rejected[["source", "src_row", "mmsi", "reason"]].to_csv(AUDIT_DIR / f"{LOAD_RUN}_rejected.csv", index=False,
                                                          lineterminator="\n")
reloaded_report = json.loads((AUDIT_DIR / f"{LOAD_RUN}.json").read_text(encoding="utf-8"))
assert reloaded_report["content_sha256"] == hashes and reloaded_report["coverage"] == json.loads(json.dumps(coverage))
print("report:", (AUDIT_DIR / f"{LOAD_RUN}.json").relative_to(ROOT), "| rejected rows:", len(rejected))

final = {"counts": db_counts, "coverage_unaccounted": {s: c["unaccounted"] for s, c in coverage.items()},
         "schema_violations": schema_violations, "content_sha256": hashes}
REVIEWED_FINAL = {  # reviewed 2026-09-28, sea-path tracks + EDI invoice links (identical on consecutive runs = idempotent)
    "counts": {"ais_positions": {"synthetic_ais|synthetic": 1310619, "noaa|real": 967, "aishub|real": 9982},
               "ais_vessels": {"aishub|real": 9982, "noaa|real": 52, "synthetic_ais|synthetic": 500},
               "edi_messages": {"iftmin_sample|synthetic": 1, "synthetic_edi|synthetic": 434}},
    "coverage_unaccounted": {"aishub": 0, "noaa": 0, "synthetic_ais": 0},
    "schema_violations": {"ais_positions": 0, "ais_vessels": 0, "edi_messages": 0},
    "content_sha256": {"ais_positions": "992c706592048b0ea2470c5111ae516bd578307d1efb7773702cb7a3b40e972d",
                       "ais_vessels": "a72e61018cba057d68e8aeae698f486ab50a28bbafe49dd50ca130eae7d2c45c",
                       "edi_messages": "1abe4b6fca431a5ead559f6342d28d9f00e1c4f729266885de57607c4315b0a2"},
}
if json.loads(json.dumps(final)) != REVIEWED_FINAL:
    print("snapshot pending review:", json.dumps(final))
    raise AssertionError("MongoDB content changed")
print("✅ Final Checkpoint validation passed.")
