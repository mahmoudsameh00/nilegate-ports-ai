# Plan — Close the PostgreSQL database (integrity, performance, access, documentation)

## Implementation record
- **Status:** IMPLEMENTED (2026-09-27).
- **Results:** migrations 006 (32 CHECK + 1 UNIQUE, 10 FK indexes, 2 GIST), 007 (`ports_readonly`), 008–009 (comments on every table and column) applied; `ANALYZE`; `verify_readonly.sql` §13–§15 all zero, 0 errors; negative test 14 / 14 rejected; read-only role 8 / 8 (throwaway member, dropped); `ports-postgres` re-created on the same volume and image, published on `127.0.0.1` and `[::1]` only (5432 closed on the LAN addresses), data identical before / after, `SyntheticGenerator.ipynb` 28 / 28. ADR-033, ADR-034.
- **Deviations:** (1) 009 was added because 008 commented the `documents` table but not its columns (an applied migration is never edited). (2) The first re-creation published IPv4 only; `PGHOST=localhost` resolves to `::1` first on Windows, so every connection waited 5 s — re-created with both loopback addresses (0.03 s). (3) The old container was renamed, verified, then removed (no data: the named volume is kept).
- **Left to the owner:** create the login user (`db/create_readonly_user.ps1`, writes `.env`); decide on the orphan volume (an old PostgreSQL 16 cluster, 108 MB, 2026-09-12).

---

- **Original status:** APPROVED (2026-09-27). Owner instruction: "close every remaining issue and examine PostgreSQL so the database is finished before the next phase". Executed by the assistant with full access (owner decision of the same day).
- **Out of scope (other owners):** land-crossing AIS routes (separate running task "Keep synthetic AIS routes at sea"); filling the `documents` registry (it needs the RAG decisions on `document_id` slugs and versions, ARCHITECTURE §10 Q2 → next phase); aligning invoices with voyages (the causal-consistency phase, §10 Q4).

## 1. Examination (read-only, 2026-09-27)

Clean: sequences in step with max(id); no duplicates on any natural key; every geometry valid, SRID 4326, `ports.lon/lat = ST_X/ST_Y`, every connection starts / ends exactly at its two ports; every categorical column inside a closed value set; every numeric range plausible; `vessel_id = imo_number − 9000000`; no self-loops; no vessel with origin = destination.

Found:
| # | Finding | Fix |
|---|---|---|
| F1 | No CHECK constraints outside `documents` / `vessels.mmsi`: nothing stops a bad status, a negative tonnage, an unknown vessel category or a malformed code from being inserted | Migration 006: CHECK constraints on every closed value set, format and range (all verified against the data first) |
| F2 | `port_connections.country1/2` differ from `ports.country` on all 19,990 rows — not an error: ISO alpha-2 codes (= first two letters of the LOCODE) vs country names | 006: CHECK `country1 = left(port1_locode, 2)` (and 2); 008: comments explain both columns |
| F3 | `vessels.vessel_type` ↔ `toll_rate_bands.vessel_category` has no constraint (a FK is impossible: the category is not unique in the bands table) | 006: the same 13-value CHECK on both columns |
| F4 | `toll_rate_bands` has no unique key on (category, condition, band order) | 006: UNIQUE |
| F5 | 10 foreign-key columns without an index; no spatial (GIST) index | 006: 10 B-tree + 2 GIST indexes |
| F6 | Planner statistics were never collected (`pg_stat_user_tables`: only `vessels` analyzed) | `ANALYZE` after the migrations (maintenance, no data change) |
| F7 | Only the `postgres` superuser exists | Migration 007: `ports_readonly` group role (NOLOGIN, SELECT only, default privileges for future tables); the login user is created by the owner from `.env` with `db/create_readonly_user.ps1` (credentials are the owner's) |
| F8 | No comments on any table / column (future tools and agents read them) | Migration 008: COMMENT on every table and column |
| F9 | `ports-postgres` publishes 5432 on `0.0.0.0` while `pg_hba` accepts password logins from any address | Re-create the container on the same volume and image with `127.0.0.1:5432` (the old container is renamed, not deleted, until verified) |
| F10 | Orphan anonymous Docker volume `2da3fd51…` (2026-09-12) | Inspect read-only; deletion is the owner's (permanent data deletion) |

## 2. Steps
1. Write and apply 006, 007, 008 (each one transaction, `ON_ERROR_STOP=1`), then `ANALYZE`.
2. Extend `db/verify_readonly.sql` (§14 constraints and indexes, §15 roles and comments), refresh the snapshot, run the audit.
3. Re-create `ports-postgres` bound to 127.0.0.1; verify from the host (psycopg) and from the notebooks (`SyntheticGenerator`, `MongoDB_loader` consistency audit).
4. Docs: ADR-033, ADR-034, ARCHITECTURE §2/§4/§7/§10, ROADMAP, db/README, `.env.example`.

## Implementation log
- 2026-09-27: examination done (F1–F10); 006–009 applied, ANALYZE, negative test 14/14, read-only role 8/8, container re-created (loopback IPv4 + IPv6), audit §13–§15 all zero; docs (ADR-033/034, ARCHITECTURE, ROADMAP, db/README); plan archived.
