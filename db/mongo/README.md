# MongoDB files (`ports_logistics` in container `ports-mongo`)

| Path | Purpose |
|---|---|
| `README.md` | This file: the pinned image and every command. |
| `run.ps1` | Runs a `mongosh` script inside the container, as root (default) or as the application user (`-AsApp`). Credentials are read from `.env` and passed by name only. |
| `001_create_app_user.js` | Creates / updates the application user: `readWrite` on `ports_logistics` only (ADR-027). Idempotent. Run as root. |
| `002_check_app_user.js` | Least-privilege check: allowed in its database, refused `collMod`, other databases, user listing, full database list. Run as the app user. |
| `003_probe_features.js` | Feature probe of the pinned version in a throwaway database (`ports_probe`, dropped at the end): time-series + validators / indexes. Run as root. |
| `004_example_queries.js` | Queries the future tools will run (latest fix of a vessel, vessels at anchor near a port, containers on an IFTMIN) and the index each one uses. Run as the app user. |
| `audit/` | Saved outputs of the scripts (`YYYY-MM-DD_NNN_*.txt`). |

Collections and indexes are **not** created here: `Notebooks/semi_structured/MongoDB_loader.ipynb` is the only writer
(ADR-031). Specs: `ARCHITECTURE.md` §5A.

## Pinned image (ADR-027)

| Item | Value |
|---|---|
| Image | `mongo:8.0.32` |
| Digest | `sha256:4968f22d0c6c10ef29952f3e807f62872ba22b3312f25803564fbfc08255efc2` (pulled 2026-09-27 as `mongo:8.0`) |
| Container | `ports-mongo` |
| Volume | `ports-mongo-data` → `/data/db` (the image also declares `/data/configdb`, which Docker keeps as an anonymous volume; unused by a standalone server) |
| Port | `127.0.0.1:27017` only |
| Users | root (`MONGO_ROOT_*`, administration) · application user (`MONGO_APP_*`, `readWrite` on `ports_logistics`, created in `admin`) |

## Commands (PowerShell, from the project root)

### First creation (done 2026-09-27)

```powershell
# root credentials from .env into this session only (the password never appears in a command)
$cfg = @{}; Get-Content .env | Where-Object { $_ -match '^\s*[A-Z_]+=' } | ForEach-Object { $k, $v = $_ -split '=', 2; $cfg[$k.Trim()] = $v.Trim() }
$env:MONGO_INITDB_ROOT_USERNAME = $cfg.MONGO_ROOT_USER; $env:MONGO_INITDB_ROOT_PASSWORD = $cfg.MONGO_ROOT_PASSWORD

docker volume create ports-mongo-data
docker run -d --name ports-mongo -p 127.0.0.1:27017:27017 -v ports-mongo-data:/data/db -e MONGO_INITDB_ROOT_USERNAME -e MONGO_INITDB_ROOT_PASSWORD mongo:8.0.32

[Environment]::SetEnvironmentVariable("MONGO_INITDB_ROOT_USERNAME", $null, "Process"); [Environment]::SetEnvironmentVariable("MONGO_INITDB_ROOT_PASSWORD", $null, "Process"); Remove-Variable cfg

powershell -NoProfile -ExecutionPolicy Bypass -File db\mongo\run.ps1 001_create_app_user.js
```

`MONGO_INITDB_ROOT_*` are read only when `/data/db` is empty (first start). Changing them later has no effect; change
passwords with `mongosh` (`db.getSiblingDB("admin").changeUserPassword(...)`), then update `.env`.

### Daily use

```powershell
docker start ports-mongo
docker ps --filter name=ports-mongo --format "{{.Names}} | {{.Image}} | {{.Status}} | {{.Ports}}"
```

### Scripts and checks (outputs saved under `audit/`)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File db\mongo\run.ps1 002_check_app_user.js -AsApp
powershell -NoProfile -ExecutionPolicy Bypass -File db\mongo\run.ps1 003_probe_features.js
powershell -NoProfile -ExecutionPolicy Bypass -File db\mongo\run.ps1 004_example_queries.js -AsApp
```

One-off `mongosh` as root (Windows PowerShell 5.1 strips embedded `"` for native programs, so the inner quoting uses
`''`, a literal `'` inside a single-quoted string; the variables need no quotes because the passwords are alphanumeric):

```powershell
docker exec ports-mongo sh -c 'mongosh --quiet -u $MONGO_INITDB_ROOT_USERNAME -p $MONGO_INITDB_ROOT_PASSWORD --authenticationDatabase admin --eval ''db.version()'''
```

Negative check (no credentials → must fail with `requires authentication`, verified 2026-09-27):

```powershell
docker exec ports-mongo mongosh --quiet --eval "db.adminCommand({listDatabases: 1})"
```

### Load / reload the collections

```powershell
uv run python tools/nb.py run "$PWD\Notebooks\semi_structured\MongoDB_loader.ipynb"
```

## Verified results (2026-09-27, `audit/`)

- `002`: 6/6 PASS. `003` on 8.0.32: time-series + `$jsonSchema` validator → `InvalidOptions`; unique index on
  time-series → `InvalidOptions`; `2dsphere` on `loc` and `meta.mmsi + ts` → OK; `$nor/$jsonSchema` audit query works;
  a regular collection with a validator rejects invalid documents.
- `004`: the latest fix of a vessel uses `mmsi_ts`; the IFTMIN lookup by IMO uses `vessel_imo`.
