// =====================================================================
// 005 — Create the read-only user of the agent tools (Agents plan §6a P9-6; ADR-027 least privilege)
// Run as root inside the container (run.ps1, default mode); the user name / password come from the environment
// (RO_USER, RO_PWD = .env MONGO_RO_USER / MONGO_RO_PASSWORD), never from this file. Idempotent: an existing user is
// updated (password + roles), not duplicated.
// Role: read on the project database only — the Stage 2 tools (voyage_status) query ais_positions / ais_vessels and
// can never write, like PG_RO_USER on PostgreSQL. The loader keeps the app user (the only writer, ADR-031).
// The refused write is checked from Python by pipelines/scripts/agents/Stage2_tools_check.py (Phase 0).
// =====================================================================
const user = process.env.RO_USER;
const pwd = process.env.RO_PWD;
const dbName = process.env.APP_DB || "ports_logistics";
if (!user || !pwd) { throw new Error("RO_USER and RO_PWD must be set (MONGO_RO_USER / MONGO_RO_PASSWORD in .env)"); }
if (user === process.env.APP_USER) { throw new Error("the reader must be a different user from the app user"); }

const admin = db.getSiblingDB("admin");
const roles = [{ role: "read", db: dbName }];
if (admin.getUser(user)) {
  admin.updateUser(user, { pwd: pwd, roles: roles });
  print(`updated user ${user}: read on ${dbName}`);
} else {
  admin.createUser({ user: user, pwd: pwd, roles: roles });
  print(`created user ${user}: read on ${dbName}`);
}
const u = admin.getUser(user);
printjson({ user: u.user, db: u.db, roles: u.roles });
