-- =====================================================================
-- 007 — Read-only group role for tools, agents and generators
-- Decisions: ADR-034. Plan: docs/plans/PostgreSQL_Closure_plan.md (F7).
-- ports_readonly cannot log in; a login user joins it (db/create_readonly_user.ps1, credentials from .env, run by the
-- owner). SELECT only, on every current table and, through default privileges, on tables created later by postgres.
-- RBAC (docs/rbac_mapping.md) is applied by the tool layer as a query predicate; this role only guarantees read-only.
-- =====================================================================
BEGIN;

CREATE ROLE ports_readonly NOLOGIN;
COMMENT ON ROLE ports_readonly IS 'Read-only access to ports_logistics.public (SELECT only). Login users join it (ADR-034).';

GRANT CONNECT ON DATABASE ports_logistics TO ports_readonly;
GRANT USAGE ON SCHEMA public TO ports_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO ports_readonly;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT SELECT ON TABLES TO ports_readonly;
ALTER ROLE ports_readonly SET default_transaction_read_only = on;

-- nobody but the owner creates objects in public (already the PostgreSQL 15+ default; stated explicitly)
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

COMMIT;
