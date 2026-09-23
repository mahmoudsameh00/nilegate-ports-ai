# Database files (PostgreSQL `ports_logistics`)

| Path | Purpose |
|---|---|
| `schema_snapshot.sql` | `pg_dump --schema-only` of the live database. **The schema source of truth.** Current file: 2026-09-23, after migrations 001–003. |
| `verify_readonly.sql` | Read-only audit: row counts, columns, constraints, indexes, data-consistency checks. It forces `default_transaction_read_only = on`. |
| `audit/` | Saved outputs of `verify_readonly.sql`. Latest: `2026-09-23_after_migrations_report.txt`. |
| `migrations/NNN_*.sql` | Every schema change, numbered, applied in order, never edited after being applied. |

## Migration status

| Migration | Status |
|---|---|
| `001_drop_accepted_currencies.sql` | APPLIED 2026-09-23 (output: BEGIN / DROP TABLE / COMMIT) |
| `002_create_documents.sql` | APPLIED 2026-09-23 (BEGIN / CREATE TABLE / CREATE INDEX / COMMIT) |
| `003_drop_employees_status.sql` | APPLIED 2026-09-23 (BEGIN / ALTER TABLE / COMMIT) |

Update this table after applying a migration.

## Commands (PowerShell, from the project root; container must be running: `docker start ports-postgres`)

Apply one migration:

```powershell
docker cp db\migrations\001_drop_accepted_currencies.sql ports-postgres:/tmp/m.sql
docker exec ports-postgres psql -U postgres -d ports_logistics -X -v ON_ERROR_STOP=1 -f /tmp/m.sql
```

Refresh the schema snapshot (after every applied migration):

```powershell
docker exec ports-postgres sh -c "pg_dump -U postgres -d ports_logistics --schema-only --no-owner --no-privileges -N tiger -N tiger_data -N topology -f /tmp/schema_snapshot.sql"
docker cp ports-postgres:/tmp/schema_snapshot.sql db\
```

Run the read-only audit:

```powershell
docker cp db\verify_readonly.sql ports-postgres:/tmp/verify_readonly.sql
docker exec ports-postgres sh -c "psql -U postgres -d ports_logistics -X -f /tmp/verify_readonly.sql > /tmp/verify_report.txt 2>&1"
docker cp ports-postgres:/tmp/verify_report.txt db\audit\YYYY-MM-DD_verify_report.txt   # replace YYYY-MM-DD with today
```
