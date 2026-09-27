// =====================================================================
// 001 — Create the application user (ADR-027: least privilege)
// Run as root inside the container; the user name / password come from the environment (APP_USER, APP_PWD),
// never from this file. Idempotent: an existing user is updated (password + roles), not duplicated.
// Role: readWrite on the project database only (createCollection with validators, createIndex, dropCollection,
// CRUD). No collMod, no user administration, no other database.
// =====================================================================
const user = process.env.APP_USER;
const pwd = process.env.APP_PWD;
const dbName = process.env.APP_DB || "ports_logistics";
if (!user || !pwd) { throw new Error("APP_USER and APP_PWD must be set"); }

const admin = db.getSiblingDB("admin");
const roles = [{ role: "readWrite", db: dbName }];
if (admin.getUser(user)) {
  admin.updateUser(user, { pwd: pwd, roles: roles });
  print(`updated user ${user}: readWrite on ${dbName}`);
} else {
  admin.createUser({ user: user, pwd: pwd, roles: roles });
  print(`created user ${user}: readWrite on ${dbName}`);
}
const u = admin.getUser(user);
printjson({ user: u.user, db: u.db, roles: u.roles });
