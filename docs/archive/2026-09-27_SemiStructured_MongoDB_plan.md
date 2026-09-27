# Plan — Semi-structured phase: AIS + EDI → MongoDB

## Implementation record

- **Status:** IMPLEMENTED (2026-09-27). All phases 0–9 done the same day; Phases 0–2 step by step with the owner, steps 3.1–3.4 hands-on by the owner, the rest executed by the assistant with full access (owner decision).
- **Results:**
  - Notebooks (`Notebooks/semi_structured/`, all runs 0 errors): `AIS_EDI_profiling` 28 cells / 8 ✅, `AIS_generator` 22 / 7 ✅, `EDI_generator` 16 / 5 ✅, `MongoDB_loader` 32 / 9 ✅.
  - MongoDB 8.0.32 (`ports-mongo`): `ais_positions` 900,899 (9,982 AISHub + 967 NOAA + 889,950 synthetic), `ais_vessels` 10,534 (9,982 + 52 + 500), `edi_messages` 435 (1 sample + 434 synthetic). 0 schema violations, 0 duplicates, 0 unaccounted input records (50 real rows rejected with reasons), 18 consistency checks = 0, identical content hashes on consecutive loads.
  - PostgreSQL: migrations 004–005 (`vessels.mmsi`), snapshot + verify (§13 all zero, 0 errors); `vessels.csv` mirror with `mmsi`.
  - ADR-027 – ADR-032 recorded; ARCHITECTURE (§1, §2, §3, §4, new §5A, §6, §7, §8, §9, §10), ROADMAP, rbac_mapping §3, the project rules, db/README, db/mongo/README updated.
- **Deviations (details in the implementation log at the end):**
  1. D5: the ITU MID table is stored in `db/reference/` (not `Data/raw/structured/`, edit-denied by the project settings); it was captured from the ITU page by the assistant.
  2. D10: tracks cover each vessel's **current voyage** up to the as-of instant instead of a fixed 30-day window (long voyages would not start at their origin); earliest departure 2026-07-15.
  3. D16 confirmed by the probe: no server validator on the time-series collection (refused by 8.0.32); MongoDB also creates `meta_1_ts_1` itself.
  4. The IFTMIN sample is a self-described synthetic template (stored as synthetic, flagged `unt_count_mismatch`).
  5. Out-of-plan fixes found on the way: `SyntheticGenerator.ipynb` still built `employees.status` (ADR-017 drift) and could not pass — fixed with the draw kept; `save_or_verify` accepts database-owned columns.
  6. `db/` organised: `db/reference/`, `db/mongo/` (run.ps1 + scripts 001–004 + audit), `db/export_vessels_mirror.py`; nothing deleted (deletion is denied by the settings; candidates are listed for the owner).
- **Open points handed to ROADMAP:** routes can cross land (§10 Q5); invoices not aligned with voyages (§10 Q4); `ports-postgres` on `0.0.0.0:5432`; orphan Docker volume; sequential identifiers (Q-A).

---

- **Original status:** APPROVED (2026-09-27). The owner approved the whole plan, including the recommended (first) option of every decision D1–D18 in §4.
- **Owner decisions this plan is built on:** 2026-09-27, items 1–7 (MongoDB in Docker; profiling before design; vessel identity in PostgreSQL + MMSI migrations; collections; idempotent loader; generators in this plan; AIS/EDI not in RAG).
- **Reference workflow:** skill `notebook-dev-loop` + `tools/nb.py` for every notebook step; handoff file `Notebooks/_scratch/semi_structured_handoff.md`.
- **Labels used:** EXISTING, PLANNED, PROPOSED, DEFERRED, UNCERTAIN (as in `ARCHITECTURE.md`).

---

## 1. Context

### 1.1 Where we are (EXISTING, from the docs read at session start)
- PostgreSQL 16.9 + PostGIS 3.5.2 in the Docker container `ports-postgres` (db `ports_logistics`) is IMPLEMENTED and verified (2026-09-23, migrations 001–003). Only the `postgres` superuser exists.
- Relevant tables (from `db/schema_snapshot.sql`):
  - `vessels` (500): `vessel_id` PK, `imo_number varchar(7)` UNIQUE, `vessel_name`, `vessel_type` (13 values = Suez vessel categories), `flag_country` (full country / territory names, 159 distinct in `vessels.csv`), `scnt_tons`, `origin_locode` / `destination_locode` → `ports`, `condition`, `status` (`In Transit` 219, `At Port` 130, `Anchored` 78, `Completed` 73). **No MMSI, no call sign.**
  - `ports` (837): `locode varchar(5)` PK, `name`, `country`, `function`, `status`, `outflows`, `lon`, `lat`, `geom Point 4326`.
  - `port_connections` (19,990): PK (`port1_locode`, `port2_locode`) → `ports`, `flows`, `country1`, `country2`, `geom LineString 4326`.
  - `containers` (1,000): `container_id` PK, `container_number varchar(11)` UNIQUE, `container_type`, `size_ft`, `status`, `vessel_id` → `vessels`, `origin_locode` / `destination_locode` → `ports`.
  - `invoices` (1,000): `invoice_id` PK, `invoice_number` UNIQUE, `vessel_id` → `vessels`, `toll_rate_band_id` → `toll_rate_bands` (nullable), `invoice_date` (2025-01-01 … 2025-12-30 in the CSV), `scnt_tons`, `rate_sdr_per_ton`, `amount` (SDR), `description` (e.g. "Suez Canal transit dues – …"), `status`.
- The RAG part is closed (7 sources, 2,228 chunks). `docs/plans/` was empty before this plan.
- MongoDB is PLANNED (ADR-001, ADR-014: AIS/EDI moved from PostgreSQL JSONB to MongoDB). ROADMAP marks the collection design as **BLOCKED on profiling the samples**.
- Inputs (`Data/raw/semi-structured/`, never modified): `AISHub sample.json` (~5 MB), `NOAA AccessAIS.csv` (~108 KB), `IFTMIN_D12A_sample.edi` (530 B). Roles today (`ARCHITECTURE.md` §3): AISHub → vessel type / NAVSTAT diversity; NOAA → movement behaviour; IFTMIN → EDIFACT structure for the generator. **UNCERTAIN until Phase 1:** the internal structure of all three files (not opened in this session — the guard hook keeps `Data/raw` out of the assistant's reads; the profiling notebook, run by the owner, is the first inspection).

### 1.2 Architecture check (conflicts found and how this plan resolves them)
| # | Finding | Resolution in this plan |
|---|---|---|
| C1 | `ARCHITECTURE.md` §2 and `docs/rbac_mapping.md` §3 name the AIS collection `ais_events`; the owner's decision uses `ais_positions` + `ais_vessels`. | ADR-029 (below) renames it; §2 / §3 of both docs updated in Phase 2 (after the profile confirms the split). No silent override. |
| C2 | the project rules and ADR-015 mention `.env.example`, but no `.env.example` exists in the project root (checked 2026-09-27). | Phase 3 creates it with the existing `PG*` names **and** the new `MONGO_*` names, all without values. |
| C3 | Convention "CSVs in `Data/processed/…` mirror DB tables". Adding `vessels.mmsi` in PostgreSQL makes `vessels.csv` stale. `SyntheticGenerator.ipynb` owns that CSV and only verifies (never overwrites). | Decision §4.D7 (recommended: DB canonical for `mmsi`, like invoices in ADR-013; the CSV mirror is refreshed by an explicit, owner-run export). |
| C4 | ADR-001 says Docker Compose comes later; the owner confirms Compose stays deferred. | Consistent: `ports-mongo` is started with `docker run`, like `ports-postgres`. |
| C5 | ADR-016: PostgreSQL schema changes only through numbered migrations. | Consistent: migrations `004` and `005`, applied by the owner, then snapshot + verify. `db/verify_readonly.sql` gets MMSI checks (same phase). |
| C6 | ADR-006 / `rbac_mapping.md` §3: `edi_messages` level 1 / Operations "can move to 2 if commercial values must be restricted". | Decision §4.D14: synthetic IFTMIN carries **no amounts** (no MOA segments), only an invoice number reference → stays level 1. |
| C7 | `ARCHITECTURE.md` §10 Q4: the shared per-vessel "event timeline" is still open. The AIS generator needs voyage times, and invoices are Suez transit dues with dates. | Decision §4.D10: this phase fixes an as-of instant and a window; aligning tracks with invoice dates (a Suez passage near `invoice_date`) is left to the causal-consistency phase unless the owner wants it now. |
| C8 | PostgreSQL has only the superuser; the AIS / EDI generators must read PostgreSQL. | Reads are SELECT-only, in notebooks the owner runs (as today). A read-only PG role stays in ROADMAP → Recommended (§4.D18). |

### 1.3 Scope
**In scope:** profiling notebook; design confirmation; MongoDB container + users + `pymongo`; migrations 004/005 (MMSI); a single idempotent loader notebook; AIS generator; EDI generator; consistency audit; docs, ADRs, archive.
**Out of scope (unchanged):** RAG / Qdrant / embeddings; agents, tools, API; Docker Compose; DuckDB / Redis / MinIO (ADR-018); synthetic incidents; aligning AIS tracks with invoices / incidents (causal-consistency phase, unless §4.D10 says otherwise).

### 1.4 Purpose of the data (owner decision 7)
AIS and EDI do **not** feed RAG. They serve (a) tools / agents (e.g. "where is vessel X now", "which containers are declared on voyage Y", "vessels anchored near port Z") and (b) analytics (dwell time, speed profiles, port calls). This is recorded as ADR-030 and in `ARCHITECTURE.md` §1/§3 at close.

---

## 2. Proposed ADRs (drafts; written to `docs/decisions.md` when the phase that proves them is done)

- **ADR-027 — MongoDB runtime: own Docker container, localhost only, least privilege.** MongoDB 8.0 in container `ports-mongo`, image pinned to an exact `mongo:8.0.x` tag (recorded with its digest), named volume `ports-mongo-data`, port published as `127.0.0.1:27017:27017` only. A root user (administration only) and an application user with `readWrite` on the project database only. Credentials in `.env` as `MONGO_*` (extends ADR-015), names in `.env.example` without values. Checks with `mongosh` inside the container (no host install). `pymongo` pinned with `uv add`. Docker Compose deferred (ADR-001, ADR-018). All timestamps UTC (BSON dates; `pymongo` with `tz_aware=True`, `tzinfo=UTC`).
- **ADR-028 — Vessel identity stays in PostgreSQL; MMSI added there; real AIS vessels are reference data.** `vessels.mmsi` (9 digits, UNIQUE, MID consistent with `flag_country`) via migrations 004 (add) and 005 (fill + NOT NULL). MongoDB documents carry `mmsi` / `imo` as references, never own identity. Real AIS vessels are stored with `real_or_synthetic = "real"` and are never linked to `vessels`; the identifier spaces (MMSI, IMO) of real and synthetic vessels must be disjoint (audited, not assumed).
- **ADR-029 — Semi-structured collections.** `ais_positions` (time-series), `ais_vessels` (static / voyage data, unique `mmsi` per source), `edi_messages` (raw + parsed + business keys). Every document carries provenance and the RBAC pair (`sensitivity_level`, `department`). `$jsonSchema` validators where the pinned version supports them; otherwise validation in the loader plus a post-load `$jsonSchema` audit query. Replaces the name `ais_events` (ARCHITECTURE §2, rbac_mapping §3).
- **ADR-030 — AIS / EDI are not RAG sources.** They serve tools / agents and analytics.
- **ADR-031 — Files first, one writer (PROPOSED, needs §4.D8).** Generators write versioned artifacts to `Data/processed/semi-structured/`; a single idempotent loader notebook is the only writer to MongoDB (drop + recreate of its own collections, then reload-and-verify). Same shape as RAG: chunks as files, loading as a separate step. This reconciles "the loader drops and reloads only its own collections" with real and synthetic data sharing a collection.
- **ADR-032 — Synthetic AIS / EDI rules.** Fixed seeds (42); distributions (speeds, NAVSTAT, reporting intervals) drawn from the reviewed real profiles; routes over `port_connections` geometry; synthetic EDI built on the profiled IFTMIN template; a consistency audit against PostgreSQL is a hard gate before loading.

---

## 3. Phases

Every notebook phase: cells written as cell files in `Notebooks/_scratch/semi_structured_cells_<X>.py`, tested with `uv run python tools/nb.py test …`, appended with `tools/nb.py append`, drift = 0, whole notebook run with `tools/nb.py run`; one markdown cell per phase (what and why), one validation cell per phase ending in asserts + a **reviewed snapshot** and `✅ Phase N validation passed.`; Final Checkpoint code + markdown at the end. The owner runs every command, notebook, migration and MongoDB script; the assistant writes the files and reads the saved outputs. After every phase group: handoff file + a dated line in the implementation log of this plan.

### Phase 0 — Plan approval (this session)
- Discuss this plan, answer §4, set `Status: APPROVED (date)`.
- Create `Notebooks/_scratch/semi_structured_handoff.md`.

### Phase 1 — Profiling notebook (no database, no `pymongo`)
Notebook: `Notebooks/semi_structured/AIS_EDI_profiling.ipynb`. Inputs are read-only; only Python standard library + pandas/numpy (already installed). Reference data for cross-checks comes from the existing CSV mirrors (`Data/processed/structured/ports.csv`, `Data/processed/synthetic/vessels.csv`, `containers.csv`) — no DB connection in this notebook.

1.1 **Setup and file registry.** Root discovery (upward from `Path.cwd()`), the three input paths, `sha256` + size + first bytes / encoding / BOM / line endings per file → `source_files` dict (reused as provenance later). Assert the files exist and are non-empty.

1.2 **AISHub JSON — structure.** Top-level shape (AISHub API usually returns `[ {ERROR, USERNAME, FORMAT, RECORDS}, [records…] ]`; confirm, do not assume). Detect the **FORMAT**: format 0 = AIS encoding (lat/lon in 1/10,000 minute, SOG and COG in tenths) vs format 1 = human-readable. Record count vs the header's `RECORDS`.

1.3 **AISHub JSON — field profile.** For every field: types seen, null / empty counts, distinct counts, min/max. Then domain checks:
- MMSI: 9 digits; MID (first 3 digits) in the ship range 201–775; other prefixes classified (`00` coast station, `111` SAR aircraft, `970/972/974` SART/MOB/EPIRB, `99` AtoN, `8` handheld); invalid ones listed.
- IMO: presence, 7 digits, **check digit** (weights 7…2, last digit = sum mod 10); `0` / empty as "absent".
- Call sign: presence, pattern.
- Positions: lat ∈ [−90, 90], lon ∈ [−180, 180]; sentinels lat 91 / lon 181 = unavailable; (0, 0) flagged.
- SOG: sentinel 102.3 (not available), negatives, > 50 kn outliers; COG: 360 = not available; HEADING: 511 = not available.
- NAVSTAT distribution (0–15; 15 = not defined) with labels.
- Ship TYPE distribution (0–99) mapped to AIS categories (60–69 passenger, 70–79 cargo, 80–89 tanker, …).
- Dimensions A/B/C/D, DRAUGHT, DEST (free text: how many look like a 5-character UN/LOCODE and how many of those are in `ports.csv`), ETA.
- TIME: parsed as UTC, min/max, span.
- Duplicates: exact duplicate records; same MMSI + same time; messages per MMSI (expected ~1 per MMSI for a snapshot — confirm).

1.4 **NOAA AccessAIS CSV — field profile.** Same checks as 1.3 on its columns (expected: MMSI, BaseDateTime, LAT, LON, SOG, COG, Heading, VesselName, IMO, CallSign, VesselType, Status, Length, Width, Draft, Cargo, TransceiverClass — **UNCERTAIN until profiled**), plus the track view:
- time coverage per MMSI; **reporting intervals** (per-MMSI time differences: quantiles by NAVSTAT / SOG band) → input for the `ais_positions` granularity and for the generator's intervals;
- implied speed between consecutive fixes vs reported SOG → the "no teleporting" threshold used later;
- stop episodes (SOG < 0.5 kn for ≥ N minutes);
- SOG distribution per ship-type category (the generator's speed source);
- Class A vs Class B (`TransceiverClass`).

1.5 **Cross-sample and our-side checks (CSV mirrors).**
- MMSI and IMO overlap between AISHub and NOAA.
- Real IMO numbers vs `vessels.imo_number` (any overlap is a finding for ADR-028).
- Our side: IMO check digit validity of the 500 `vessels.imo_number`; ISO 6346 check digit of the 1,000 `containers.container_number`; `flag_country` list vs the MID table (source: §4.D5) → unmapped flags listed. Findings are reported, **never fixed** here (PostgreSQL is canonical).

1.6 **IFTMIN D12A — EDIFACT profile.** A small own tokenizer (§4.D15): UNA service string advice (defaults `:+.? '` when absent), release character `?`, segment terminator, element / component split. Then:
- segment inventory in order with counts (expected envelope UNA/UNB/UNH … UNT/UNZ);
- per segment: qualifiers used (e.g. BGM document name code, DTM 137/…, TDT stage qualifier and transport means id, LOC 5/8/9/11…, NAD party qualifiers, EQD `CN`, RFF qualifiers) and the code lists they refer to — **UNCERTAIN until profiled**, recorded as found;
- envelope integrity: UNT segment count = actual, UNH ref = UNT ref, UNB interchange ref = UNZ ref, UNZ message count;
- business keys present: message reference, vessel id (IMO / name), voyage number, UN/LOCODEs (and whether they are in `ports.csv`), container numbers (ISO 6346 check), dates;
- the **template** the generator will follow: required vs optional segments, their order and repetition.

1.7 **Save and reload.** One profile per source in `Data/processed/semi-structured/profiles/<stem>_profile.json` (+ the IFTMIN template as `iftmin_template.json`), reloaded from disk and re-validated (keys, types, counts equal to the in-memory profile).

1.8 **Reviewed snapshots + Final Checkpoint.** One snapshot per source (record counts, invalid counts by reason, distinct MMSI, NAVSTAT / type histograms, time span, segment counts). Final Checkpoint lists every finding and what it means for the design.

**Gate:** the owner reviews the profile summary (✅ lines + the Final Checkpoint markdown) before Phase 2.

### Phase 2 — Design confirmation (docs only)
- Write the collection specs from the profile into this plan (§3.2a, added then): field names, BSON types, units after normalisation (degrees, knots, UTC dates), `ais_positions` granularity (`seconds` / `minutes` / `hours`, or custom bucket settings if the intervals are irregular), the index list, validators.
- Reviewed mapping tables (in the plan, then as data in the generator notebook): `vessel_type` (13 Suez categories) → AIS ship-type code; `vessels.status` → NAVSTAT; `flag_country` → MID (from the §4.D5 source, with a reviewed override list for territories).
- Draft document shapes (to be confirmed by the profile):
  - `ais_positions`: `{ ts: Date, meta: { mmsi, imo|null, source, real_or_synthetic, load_run }, loc: {type:"Point", coordinates:[lon, lat]}, sog, cog, heading, navstat, src_row, sensitivity_level: 1, department: "Operations" }`. Indexes: `{ "meta.mmsi": 1, ts: 1 }`, `{ loc: "2dsphere" }`. A time-series collection cannot have a unique index → duplicates (`mmsi`, `ts`) are removed in the loader and audited after load.
  - `ais_vessels`: `{ mmsi, imo|null, call_sign|null, name, ship_type, dims{a,b,c,d}, draught, destination, eta, source, real_or_synthetic, vessel_id|null (synthetic only), provenance{…}, sensitivity_level, department }`. Unique index `{ source: 1, mmsi: 1 }` (the same real MMSI may appear in both samples; §4.D9 covers synthetic static records).
  - `edi_messages`: `{ message_ref, interchange_ref, message_type: "IFTMIN", version: "D:12A", raw, segments:[{tag, elements:[[…]]}], keys:{ vessel_imo, voyage, locodes{…}, container_numbers[], invoice_number|null, dates{…} }, source, real_or_synthetic, provenance{…}, sensitivity_level, department }`. Unique index `{ source: 1, interchange_ref: 1, message_ref: 1 }`; indexes on `keys.vessel_imo`, `keys.container_numbers`.
  - `provenance`: `{ source_file, source_sha256, load_run, loaded_at, generator: {notebook, seed, params_hash}|null }`.
- Update `ARCHITECTURE.md` §2 (MongoDB row: collection names, still PLANNED) and `docs/rbac_mapping.md` §3 (three collections). ADR-029 text finalised.

**Gate:** owner approval of the collection specs.

#### 3.2a Collection specs from the Phase 1 profile (PROPOSED 2026-09-27, waiting for the gate)
Profile facts used: AISHub = one fix per MMSI in a 30-min snapshot (10,000; 9,982 ship MMSIs), every value a string; NOAA = 999 fixes / 54 vessels / 78 min, intervals median ~70 s moving and ~180 s stationary, 6 duplicate (MMSI, time); IMO often absent or a placeholder in real data; our `imo_number` / `container_number` are sequential and mostly fail their check digits; the IFTMIN sample is a self-described synthetic template with a wrong UNT count.

**`ais_positions`** — time-series, `timeField: "ts"`, `metaField: "meta"`, `granularity: "minutes"`.
| Field | BSON type | Rule |
|---|---|---|
| `ts` | date | UTC |
| `meta.mmsi` | string | 9 digits, ship class only (MID 201–775) |
| `meta.imo` | string \| null | valid check digit for real data; placeholders (`0`, `1234567`, …) → null; synthetic = PostgreSQL value as is |
| `meta.source` | string | `aishub` \| `noaa` \| `synthetic_ais` |
| `meta.real_or_synthetic` | string | `real` \| `synthetic` |
| `meta.load_run` | string | loader run id |
| `loc` | object | GeoJSON Point `[lon, lat]`; sentinels / null island rejected |
| `sog`, `cog`, `heading` | double \| null | sentinels 102.3 / 360 / 511 → null |
| `navstat` | int \| null | 0–15 |
| `src_row` | int \| null | row index in the source file (real) for the coverage audit |
| `sensitivity_level`, `department` | int, string | 1, `Operations` |
Indexes: `{meta.mmsi: 1, ts: 1}`, `{loc: "2dsphere"}`. Rejections (reviewed reasons): `invalid_mmsi`, `non_ship_mmsi`, `duplicate_mmsi_ts`, `position_unavailable`. AISHub fixes are loaded too (the latest known position of 9,982 real vessels). Expected real volume ≈ 10,900 documents.

**`ais_vessels`** — one document per (`source`, `mmsi`); unique index `{source: 1, mmsi: 1}`, indexes on `imo`, `vessel_id`.
Fields: `mmsi` string; `imo` string \| null; `call_sign` string \| null (placeholders `DATAHUB`, `0000000`, `0` → null); `name` string \| null; `ship_type` int \| null + `ship_type_category` string \| null; `length_m`, `beam_m` double \| null (A+B, C+D; 0 → null); `draught_m` double \| null (0 → null); `destination_raw` string \| null; `destination_locode` string \| null (only when it is one of our 837 ports); `eta_raw` string \| null (AIS ETA has no year, kept as `MM-DD HH:MM`; `00-00 24:60` → null); `transceiver_class` string \| null (NOAA); `last_seen` date; `vessel_id` int \| null (synthetic only); `source`, `real_or_synthetic`, `provenance`, `sensitivity_level` 1, `department` `Operations`. NOAA static values: the last non-empty value per MMSI.

**`edi_messages`** — unique index `{source: 1, interchange_ref: 1, message_ref: 1}`, indexes on `keys.vessel_imo`, `keys.container_numbers`.
Fields as drafted above, plus `flags` (array of strings, e.g. `unt_count_mismatch`) and `document_number` (BGM). The sample is stored as `source: "iftmin_sample"`, `real_or_synthetic: "synthetic"` (template).

**Synthetic volume (D10 + D11):** reporting every 10 min when moving and every 60 min when stationary over 30 days: ≈ 219 × 30 × 144 + 281 × 30 × 24 ≈ 1.15 M documents (≤ the 2 M bound).

**Check digits:** enforced on real identifiers only. Our sequential IMO / container numbers are accepted as PostgreSQL gives them (open question Q-A in the implementation log).

### Phase 3 — MongoDB container, users, `pymongo` (owner runs every command)
New folder `db/mongo/` (mirrors `db/`): `README.md` (commands), numbered `mongosh` scripts, `audit/` for saved outputs.
3.1 **Pick the exact image.** `docker pull mongo:8.0` then read the exact version and digest (`docker image inspect`), pin `mongo:8.0.<patch>` in `db/mongo/README.md` and ADR-027. (No version is invented in this plan.)
3.2 **Credentials.** Add to `.env` (owner, by hand): `MONGO_HOST=127.0.0.1`, `MONGO_PORT=27017`, `MONGO_DB=ports_logistics`, `MONGO_ROOT_USER`, `MONGO_ROOT_PASSWORD`, `MONGO_APP_USER`, `MONGO_APP_PASSWORD`, `MONGO_AUTH_SOURCE=admin`. Create `.env.example` with all `PG*` and `MONGO_*` names, no values (C2).
3.3 **Volume + container.** `docker volume create ports-mongo-data`; `docker run -d --name ports-mongo -p 127.0.0.1:27017:27017 -v ports-mongo-data:/data/db -e MONGO_INITDB_ROOT_USERNAME -e MONGO_INITDB_ROOT_PASSWORD mongo:8.0.<patch>` with the two variables set in the PowerShell session from `.env` first (`-e NAME` without a value takes it from the session, so the password is not in the command history; §4.D3). Note: `docker inspect` still shows container env values — acceptable for a local dev container, same exposure as `ports-postgres`.
3.4 **Checks.** `docker port ports-mongo` shows `127.0.0.1:27017` only; `docker exec ports-mongo mongosh --quiet --eval "db.version()"` (with root auth) prints the pinned version.
3.5 **Application user.** `db/mongo/001_create_app_user.js`, run with `docker exec -e APP_USER -e APP_PWD ports-mongo mongosh … --file`: creates the user in `admin` with `roles: [{ role: "readWrite", db: "ports_logistics" }]`. `readWrite` includes `createCollection` (with validator options), `createIndex`, `dropCollection` — enough for the loader; it does **not** include `collMod`, so validators are always set at create time. Negative tests saved to `db/mongo/audit/`: the app user cannot write to another database and cannot list users.
3.6 **Feature probe (UNCERTAIN → verified).** `db/mongo/002_probe_features.js`, run as root in a throwaway database `ports_probe` that the script drops at the end: create a time-series collection with a `$jsonSchema` validator, insert one valid and one invalid document (is the invalid one rejected?), create a `2dsphere` index on the measurement `loc` field and a compound `meta.mmsi + ts` index, test the granularity / bucket options chosen in Phase 2. Output saved as `db/mongo/audit/YYYY-MM-DD_probe.txt`. ADR-029's validator clause is finalised from this output.
3.7 **Driver.** `uv add pymongo==<latest 4.x at install time>` (reported: `pyproject.toml` / `uv.lock` diff). Smoke test by the owner: `uv run python -c` one-liner connecting as the app user from `.env` and printing `ping` + server version (no credentials printed).
3.8 **Docs.** `ARCHITECTURE.md` §2 (MongoDB row IMPLEMENTED: image, container, volume, port, users), §8 (pymongo), ADR-027 into `docs/decisions.md`.

### Phase 4 — PostgreSQL: `vessels.mmsi` (migrations the owner applies)
4.1 `db/migrations/004_add_vessels_mmsi.sql`: `ALTER TABLE public.vessels ADD COLUMN mmsi varchar(9)` (type per §4.D4) + `CHECK (mmsi ~ '^[2-7][0-9]{8}$')` + `UNIQUE (mmsi)`; nullable at this step.
4.2 `db/migrations/005_fill_vessels_mmsi.sql`: a reviewed `flag_country → MID` VALUES list (from §4.D5), the deterministic fill (§4.D6), assertions inside the transaction (`DO $$ … RAISE EXCEPTION` if any row is NULL, duplicated, or whose MID does not map to its flag), then `ALTER COLUMN mmsi SET NOT NULL`. One transaction, `ON_ERROR_STOP=1`.
4.3 Before writing 005: a read-only preview query (owner runs it) that computes the MMSIs without writing, and a check that none equals a real MMSI from the Phase 1 profiles (ADR-028 disjointness).
4.4 After applying: refresh `db/schema_snapshot.sql`; extend `db/verify_readonly.sql` with MMSI checks (500 non-null, unique, 9 digits, MID matches flag); run it and save `db/audit/YYYY-MM-DD_after_004_005_report.txt`; update the migration table in `db/README.md`.
4.5 The CSV mirror per §4.D7. `ARCHITECTURE.md` §4 schema + invariants; ADR-028 into `docs/decisions.md`.

### Phase 5 — Loader notebook, real samples
Notebook: `Notebooks/semi_structured/MongoDB_loader.ipynb` (the only writer to MongoDB, ADR-031).
5.1 Connect as the app user (`.env`), print server version and database name only.
5.2 Parse the real samples with the parsing code validated in Phase 1 (copied; a check compares the parsed record counts and field sets with the saved profiles, so a silent divergence stops the notebook).
5.3 Normalise (units, UTC, GeoJSON `[lon, lat]`, sentinels → `null`), then validate in Python against the Phase 2 spec. **Every source record gets exactly one disposition**: `loaded`, `rejected:<reason>` (invalid position, duplicate, non-ship MMSI, …), or `static_only` (records that only feed `ais_vessels`). Reviewed list of rejection reasons, asserted.
5.4 Drop and recreate **only** `ais_positions`, `ais_vessels`, `edi_messages` (validators and time-series options at create time), create indexes, `insert_many(ordered=False)` in batches.
5.5 **Reload and re-validate from MongoDB:** counts per collection / source / `real_or_synthetic`; `$jsonSchema` audit query (`{$nor: [{$jsonSchema: …}]}` must return 0) — required where the validator is unsupported, done everywhere as a second guard; index list equals the spec; no duplicate (`mmsi`, `ts`); coverage: loaded + rejected + static_only = source records, 0 unaccounted; provenance and RBAC fields present on every document; real documents have `vessel_id = null`.
5.6 Idempotency: a second run gives the same counts and the same content hash (excluding `load_run`, `loaded_at`).
5.7 Load report `Data/processed/semi-structured/load_audit/<load_run>.json`; reviewed snapshot; Final Checkpoint (to be extended in Phase 8).

### Phase 6 — AIS generator (synthetic tracks for our 500 vessels)
Notebook: `Notebooks/semi_structured/AIS_generator.ipynb`. Reads PostgreSQL read-only (`vessels` incl. `mmsi`, `ports`, `port_connections` geometry) and the Phase 1 profiles. Writes files only.
6.1 **Network profile (read-only PostGIS).** Vertex counts of `port_connections.geom`, whether each vessel's origin → destination pair has a direct connection, graph connectivity (components). Findings decide the §4.D12 fallback use.
6.2 **Routing.** Graph over `port_connections` weighted by geodesic length; shortest path origin → destination with `scipy.sparse.csgraph` (already installed; no new dependency). No path → reviewed fallback (great-circle segment, flagged `route_fallback`). Limitation recorded: the connection lines may cross land.
6.3 **Timeline per vessel** (as-of instant and window from §4.D10), consistent with `vessels.status`: `In Transit` → somewhere on the route at the as-of instant, NAVSTAT 0; `Anchored` → inside an anchorage radius near the destination, NAVSTAT 1; `At Port` → moored at the destination, NAVSTAT 5; `Completed` → arrived before the as-of instant, then moored. Reviewed mapping table, asserted.
6.4 **Kinematics from the real profiles:** SOG per AIS ship-type category drawn from the profiled distribution (clipped to profiled quantiles), COG = route bearing (+ small noise), heading ≈ COG, reporting intervals per NAVSTAT from §4.D11. `random.seed(42)` / `numpy.random.default_rng(42)`.
6.5 **Static records** for `ais_vessels` (if §4.D9 = yes): identity copied from PostgreSQL (`mmsi`, `imo`, name, `vessel_id`), generated call sign (seeded, format per flag, no collision with real ones), ship type from the mapping, destination = destination LOCODE, ETA from the timeline.
6.6 **Validation (hard asserts):** monotonic `ts` per vessel; valid positions; implied speed between consecutive fixes ≤ profiled threshold (**no teleporting**); first fix within R km of the origin port, last fix within R km of the destination for arrived vessels, and on-route for vessels in transit; every `mmsi` / `imo` pair equals PostgreSQL; synthetic MMSIs ∩ real MMSIs = ∅; volume within the §4.D11 estimate; seed reproducibility (two runs → same hash).
6.7 Artifacts: `Data/processed/semi-structured/synthetic/ais_positions_synthetic.parquet`, `ais_vessels_synthetic.parquet` (+ a small `generation_manifest.json`: seed, params, as-of, input table row counts, hashes); reloaded and re-validated; reviewed snapshot; Final Checkpoint.

### Phase 7 — EDI generator (synthetic IFTMIN D12A)
Notebook: `Notebooks/semi_structured/EDI_generator.ipynb`. Reads PostgreSQL read-only (`containers`, `vessels`, `ports`, `invoices`) and the Phase 1 IFTMIN template.
7.1 Message granularity per §4.D13 (recommended: one IFTMIN per consignment group = vessel + container origin + container destination, one EQD per container).
7.2 Build segments from the template: envelope (UNB/UNH/UNT/UNZ with correct refs and counts), BGM, DTM (UTC, dates consistent with the AIS timeline), TDT with vessel IMO and a voyage number, LOC with UN/LOCODEs, EQD per container (existing `container_number`), RFF with the invoice number when the vessel has one (§4.D13), no MOA (§4.D14). Escaping with the release character.
7.3 **Round trip:** every generated message is parsed back with the Phase 1 tokenizer and must give the same business keys; envelope integrity asserted.
7.4 Validation: every IMO, LOCODE, container number exists in PostgreSQL and matches (container → vessel_id → IMO); ISO 6346 check digits reported (not fixed); seed reproducibility.
7.5 Artifact `Data/processed/semi-structured/synthetic/edi_messages_synthetic.jsonl` (+ manifest); reloaded, re-validated; reviewed snapshot; Final Checkpoint.

### Phase 8 — Load synthetic data + consistency audit
Extend `MongoDB_loader.ipynb` (new phases appended via `tools/nb.py`): load the Phase 6–7 artifacts together with the real samples (one run, drop + recreate).
**Consistency audit (hard gate, saved to `load_audit/`):** every synthetic `mmsi`, `imo`, UN/LOCODE, container number exists in PostgreSQL (read-only queries); `(mmsi, imo)` pairs equal `vessels`; tracks start / end at the vessel's origin / destination ports; no teleporting (recomputed from MongoDB data, not from the parquet); EDI vessel / voyage consistent with the AIS timeline; real documents reference nothing in PostgreSQL; real ∩ synthetic identifiers = ∅; coverage 0 unaccounted for every input record (real and synthetic). Reviewed snapshot; Final Checkpoint code + markdown.

### Phase 9 — Close
- ADR-027 … ADR-032 in `docs/decisions.md` (final text, with results); `ARCHITECTURE.md` §1 (MongoDB IMPLEMENTED), §2, §3 (targets and purpose, ADR-030), §4 (`vessels.mmsi`), new subsection "MongoDB collections" (verified specs), §8, §9, §10 (answered / remaining questions); `docs/rbac_mapping.md` §3; `docs/ROADMAP.md` (status rows, next step).
- Plan: implementation record at the top (`Status: IMPLEMENTED (date)`, deviations, results), moved to `docs/archive/YYYY-MM-DD_SemiStructured_MongoDB.md`, row in `docs/archive/README.md`.
- `Notebooks/_scratch/` emptied (cell files, logs, states, handoff); the session-start note there is deleted too.
- Git commands for the owner (the assistant never runs git).

### Files this plan creates or changes (summary)
New: `Notebooks/semi_structured/{AIS_EDI_profiling, MongoDB_loader, AIS_generator, EDI_generator}.ipynb`; `Data/processed/semi-structured/{profiles, synthetic, load_audit}/…`; `db/mongo/{README.md, 001_create_app_user.js, 002_probe_features.js, audit/}`; `db/migrations/004_add_vessels_mmsi.sql`, `005_fill_vessels_mmsi.sql`; `.env.example`.
Changed: `.env` (owner only), `pyproject.toml` / `uv.lock` (`pymongo`), `db/schema_snapshot.sql`, `db/verify_readonly.sql`, `db/README.md`, `ARCHITECTURE.md`, `docs/decisions.md`, `docs/rbac_mapping.md`, `docs/ROADMAP.md`, `Data/processed/synthetic/vessels.csv` (only per §4.D7).
Never touched: `Data/raw/`, RAG notebooks and artifacts, completed PostgreSQL tables other than the `vessels.mmsi` column.

### Risks
| Risk | Mitigation |
|---|---|
| Samples too small / not representative (a 5 MB snapshot, a 108 KB track file) | Distributions clipped to profiled quantiles; each generator parameter records whether it came from the profile or from a documented default. |
| AISHub FORMAT 0 values read as degrees | Phase 1.2 detects the format before any range check. |
| Time-series limits (no unique index, validator support uncertain) | Loader dedup + post-load audits; feature probe in Phase 3.6 before the spec is final. |
| Synthetic ids collide with real ids | Disjointness asserted in Phases 4.3, 6.6 and 8. |
| Routes over straight connection lines cross land | Documented limitation (§4.D12); a sea-lane router is a later option. |
| Data volume | Estimate in Phase 2 from §4.D10/§4.D11; asserted in 6.6. |
| Credentials leak | `.env` only; `-e NAME` without values; app user least privilege; no URIs with passwords printed. |

---

## 4. Decisions (open questions for the owner)

Recommended option first. **Resolved 2026-09-27: the owner chose the recommended option of every item (D1–D18).**

- **D1 — Versions.** Pin `mongo:8.0.<latest patch at install>` (+ digest) and `pymongo==<latest 4.x at install>`, both recorded in ADR-027. *Alternative:* a specific patch you already have in mind.
- **D2 — Database name and auth.** MongoDB database `ports_logistics` (same as PostgreSQL); app user created in `admin` (`authSource=admin`) with `readWrite` on `ports_logistics` only. *Alternative:* user created inside `ports_logistics`.
- **D3 — Passing root credentials to `docker run`.** `-e MONGO_INITDB_ROOT_USERNAME -e MONGO_INITDB_ROOT_PASSWORD` without values, set in the session from `.env` (nothing in history). *Alternative:* `--env-file` with a separate git-ignored file containing only the two init variables.
- **D4 — MMSI type.** `varchar(9)` + CHECK in PostgreSQL and a **string** in MongoDB (an identifier, like `imo_number`; one type in both stores). *Alternative:* `integer` in both (AIS sources deliver numbers; smaller).
- **D5 — MID source.** The ITU "Maritime Identification Digits" table saved by the owner under `Data/raw/structured/` (real public source, like the other anchors), with a reviewed override list for territories that have no own MID (→ the sovereign state's MID). *Alternative:* a hand-reviewed VALUES list written directly in migration 005.
- **D6 — Deterministic fill.** Pure SQL formula in 005: `mmsi = MID || lpad(((vessel_id * 7919 + 42) % 1000000)::text, 6, '0')` — collision-free by construction (7919 is coprime with 10⁶), reviewable, no generated file; "42" is the seed offset. *Alternative:* values drawn in Python with `random.seed(42)` and written into 005 as a reviewed VALUES list.
- **D7 — `vessels.csv` mirror.** PostgreSQL is canonical for `mmsi` (ADR-013 pattern); the owner refreshes `vessels.csv` with an explicit export command after 005 and `SyntheticGenerator.ipynb` keeps verifying the other columns. *Alternative:* extend `SyntheticGenerator.ipynb` to compute `mmsi` with the same formula.
- **D8 — One writer (ADR-031).** Generators write files; `MongoDB_loader.ipynb` is the only notebook that writes MongoDB. *Alternative:* each generator writes its own documents and deletes only its own `source` (collections are then not dropped, only filtered).
- **D9 — Synthetic static records in `ais_vessels`.** Yes: one static record per our vessel (identity copied from PostgreSQL and audited), so tools query real and synthetic AIS the same way. *Alternative:* `ais_vessels` holds real vessels only.
- **D10 — Time anchor.** As-of `2026-09-13T00:00:00Z` (the project's generator anchor) and a 30-day window; aligning a Suez passage with `invoice_date` (2025) is left to the causal-consistency phase. *Alternative:* anchor on the 2025 invoice dates now.
- **D11 — Synthetic reporting interval.** Downsampled, profile-informed intervals (e.g. minutes under way, ~1 h at anchor / moored; final values after Phase 1), volume ≤ ~2 M documents. *Alternative:* realistic AIS rates (seconds), much larger volume.
- **D12 — Routing.** Shortest path over `port_connections` with `scipy` (no new dependency), limitation documented. *Alternatives:* a sea-lane router package (new dependency, realistic lanes) or straight great-circle only.
- **D13 — IFTMIN granularity.** One message per consignment group (vessel + container origin + destination), one EQD per container, RFF with the vessel's invoice number when one exists. *Alternative:* one message per container.
- **D14 — `edi_messages` sensitivity.** Level 1 / Operations; synthetic IFTMIN carries no amounts (no MOA). *Alternative:* level 2 / Finance if amounts are added.
- **D15 — EDIFACT parser.** An own small tokenizer (UNA, release character, segments/elements/components; educational, no dependency). *Alternative:* a library such as `pydifact` via `uv add`.
- **D16 — Validators on the time-series collection.** Follow the Phase 3.6 probe; if unsupported, loader validation + post-load `$jsonSchema` audit (already planned everywhere as a second guard). No decision needed unless you want a stricter rule.
- **D17 — Folder names.** Data under `Data/processed/semi-structured/` (matches `Data/raw/semi-structured/`); notebooks under `Notebooks/semi_structured/` (your decision). *Alternative:* underscore in both.
- **D18 — PostgreSQL access for the generators.** Read-only SELECTs with the existing `.env` credentials; a read-only PG role stays in ROADMAP → Recommended (agents phase). *Alternative:* add a read-only role now as migration 006.

---

## Implementation log

- 2026-09-27: plan approved (all D1–D18 = recommended option). Phase 1 started: cell group A (1.1 file registry + 1.2 AISHub structure).
- 2026-09-27: `Notebooks/semi_structured/AIS_EDI_profiling.ipynb` created; notebook phases 1–2 appended and run (0 errors). AISHub finding: plain list of 10,000 records, no header object, all 19 fields strings, time field `TSTAMP`, positions in degrees (format 1).
- 2026-09-27: **Phase 1 DONE.** `AIS_EDI_profiling.ipynb`: 28 cells (18 code), 8 validations incl. Final Checkpoint, 0 errors; 5 profiles in `Data/processed/semi-structured/profiles/`, byte-identical on re-run. Deviations: (1) `flag_country` → MID coverage moved to Phase 4 (needs the ITU MID table, D5); (2) the IFTMIN sample is self-described synthetic → stored as a synthetic template (ARCHITECTURE §3 says "real template"; corrected at close); (3) implied speed measured on steps ≥ 10 s (2 jitter steps of 250–320 kn in NOAA). Collection specs written in §3.2a (Phase 2 gate).
- **Open question Q-A (owner):** our `vessels.imo_number` (`9000001…`, 50/500 valid check digits) and `containers.container_number` (`NGCU0000001…`, 101/1,000 valid ISO 6346) are sequential. Recommended: keep them (PostgreSQL canonical, ADR-013) and enforce check digits on real data only. Alternative: a migration that makes them valid (touches completed tables and every CSV mirror).
- 2026-09-27: **Phase 2 gate passed** — the owner approved §3.2a and Q-A = recommended (keep our sequential IMO / container numbers; check digits enforced on real data only). Docs updated: `ARCHITECTURE.md` §2 (MongoDB row) and §3 (sample roles; IFTMIN = synthetic template), `docs/rbac_mapping.md` §3 (three collections). **Phase 2 DONE.** Phase 3 (Docker) is done hands-on by the owner, step by step, with the assistant guiding (owner request).
- 2026-09-27: **Mode change (owner):** full access incl. Docker; the assistant executes the rest of the plan in one go and reports A→Z at the end. Steps 3.1–3.4 had been done hands-on by the owner.
- 2026-09-27: **Phase 3 DONE.** `mongo:8.0.32` (digest `4968f22d…`), app user via `db/mongo/001_create_app_user.js` + `db/mongo/run.ps1` (credentials passed by name, never on a command line); privilege check `002` 6/6 PASS; probe `003` on 8.0.32: **a time-series collection rejects `$jsonSchema` validators and unique indexes (`InvalidOptions`)** → D16 fallback confirmed (loader validation + post-load `$nor/$jsonSchema` audit for `ais_positions`; real validators on `ais_vessels`, `edi_messages`); 2dsphere + `meta.mmsi/ts` index OK. `pymongo==4.18.2`.
- 2026-09-27: **Phase 4 DONE.** Deviation D5: the ITU MID table is stored in `db/reference/itu_mid_table.csv` (Data/raw is edit-denied); mapping `db/reference/flag_country_mid.csv` (144 auto, 15 name forms, Guam → 338 and Mayotte → 226 sovereign fallbacks). Migrations 004/005 applied, snapshot refreshed, verify §13 all zero, 0 errors. `vessels.csv` mirror ends with `mmsi`. `SyntheticGenerator.ipynb`: `save_or_verify` accepts DB-owned columns; **pre-existing ADR-017 drift fixed** (the notebook still built `employees.status` and could not pass); full run 28/28, all CSVs identical.
- 2026-09-27: **Phases 5–8 DONE.** Loader (L1 real, LS synthetic, L2 write + reload, LA consistency audit, L3 report); AIS generator (routes: 2 fallbacks, 889,950 fixes, max 19.82 kn); EDI generator (434 messages, round trip + template order, 24 without seals because all their containers are empty). Example queries (`db/mongo/004`) use `mmsi_ts` and `vessel_imo`.
- 2026-09-27: **Phase 9 DONE.** Docs, ADRs, archive. Plan moved to `docs/archive/2026-09-27_SemiStructured_MongoDB_plan.md`.
