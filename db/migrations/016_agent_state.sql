-- =====================================================================
-- 016 — Schema agent_state + role agent_writer for the LangGraph checkpointer (Agents plan §5b S4, decision P5-3 of
--       2026-10-19; plan D3)
-- Why: the weekly_pack graph saves a checkpoint after every step (PostgresSaver), so a pack resumes after a crash
-- and waits for the Finance manager's approval across processes and days. ports_readonly cannot write (ADR-034), so
-- the checkpoints need their own schema and a writer that can do nothing else.
-- Least privilege (P5-3):
--   * the schema and its tables belong to postgres; the tables are created by PostgresSaver.setup(), run once as
--     the owner account as a deployment step (pipelines/scripts/agents/Checkpointer_setup.py);
--   * agent_writer (NOLOGIN) gets USAGE on agent_state and, through default privileges, SELECT / INSERT / UPDATE /
--     DELETE on the tables setup() creates (DELETE: delete_thread and the retention job of Phase 8) — no CREATE,
--     no TRUNCATE, nothing in public / finance / finance_test;
--   * the runtime login ports_agent joins agent_writer (db/create_agent_user.ps1, from .env) and gets
--     search_path = agent_state itself (role settings are not inherited by members).
-- Checkpoints hold the run's tool results, i.e. level-2 Finance numbers at rest (docs/rbac_mapping.md):
-- ports_readonly and finance_bi get nothing here (their default privileges are scoped to other schemas).
-- Decisions: ADR-016 (migrations), ADR-034 (read-only role), plan D3. Written by hand; never edited after applying.
-- =====================================================================
BEGIN;

CREATE SCHEMA agent_state AUTHORIZATION postgres;
COMMENT ON SCHEMA agent_state IS 'LangGraph checkpoints of the agents platform (PostgresSaver; Agents plan Phase 5, D3). Tables created by PostgresSaver.setup() as the owner (deployment step); written only through the role agent_writer. Holds level-2 Finance numbers (tool results of a run).';
REVOKE ALL ON SCHEMA agent_state FROM PUBLIC;

CREATE ROLE agent_writer NOLOGIN;
COMMENT ON ROLE agent_writer IS 'Least privilege for the agents'' checkpointer (Agents plan Phase 5, P5-3): USAGE on agent_state and SELECT / INSERT / UPDATE / DELETE on its tables only (no DDL, no TRUNCATE, nothing in other schemas). The login ports_agent joins it (db/create_agent_user.ps1) and sets search_path = agent_state itself.';
GRANT CONNECT ON DATABASE ports_logistics TO agent_writer;
GRANT USAGE ON SCHEMA agent_state TO agent_writer;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA agent_state
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO agent_writer;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA agent_state
    GRANT USAGE, SELECT ON SEQUENCES TO agent_writer;

COMMIT;
