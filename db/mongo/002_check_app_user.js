// =====================================================================
// 002 — Least-privilege check of the application user (ADR-027). Run AS THE APP USER (run.ps1 -AsApp).
// Positive: create / write / drop a collection in the project database.
// Negative: another database, user administration and collMod must be refused.
// =====================================================================
const results = [];
function expect(name, shouldWork, fn) {
  let ok, err = null;
  try { fn(); ok = true; } catch (e) { ok = false; err = e.codeName || e.message; }
  const pass = ok === shouldWork;
  results.push({ check: name, expected: shouldWork ? "allowed" : "refused", got: ok ? "allowed" : `refused (${err})`, pass });
}
const own = db.getSiblingDB(process.env.APP_DB || "ports_logistics");
expect("create+insert in project db", true, () => { own.getCollection("_privilege_check").insertOne({ t: new Date() }); });
expect("collMod in project db", false, () => { own.runCommand({ collMod: "_privilege_check", validator: {} }).ok || (() => { throw new Error("collMod not ok"); })(); });
expect("drop in project db", true, () => { own.getCollection("_privilege_check").drop(); });
expect("insert in another db", false, () => { db.getSiblingDB("other_db").getCollection("x").insertOne({ a: 1 }); });
expect("list users", false, () => { const r = db.getSiblingDB("admin").runCommand({ usersInfo: 1 }); if (!r.ok) throw new Error(r.codeName); });
expect("list all databases (full)", false, () => {
  const r = db.adminCommand({ listDatabases: 1, authorizedDatabases: false });
  if (!r.ok) throw new Error(r.codeName);
});
results.forEach(r => print(`${r.pass ? "PASS" : "FAIL"}  ${r.check}: expected ${r.expected}, got ${r.got}`));
if (results.some(r => !r.pass)) { throw new Error("privilege check failed"); }
print("✅ app user privileges as designed");
