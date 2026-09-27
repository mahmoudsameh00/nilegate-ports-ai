// =====================================================================
// 003 — Feature probe on the pinned server version (plan step 3.6). Run AS ROOT.
// Works in the throwaway database `ports_probe`, which is dropped at the end.
// Answers: does a time-series collection accept a $jsonSchema validator and reject invalid documents?
// 2dsphere on a measurement field? compound meta+time index? unique index on a time-series collection?
// =====================================================================
const p = db.getSiblingDB("ports_probe");
p.dropDatabase();
const out = { server: db.version() };
const schema = {
  $jsonSchema: {
    bsonType: "object", required: ["ts", "meta", "loc"],
    properties: {
      ts: { bsonType: "date" },
      meta: { bsonType: "object", required: ["mmsi"], properties: { mmsi: { bsonType: "string", pattern: "^[2-7][0-9]{8}$" } } },
      loc: { bsonType: "object" }, sog: { bsonType: ["double", "null"] },
    },
  },
};
function tryIt(fn) { try { const r = fn(); return r === undefined ? "ok" : r; } catch (e) { return `error: ${e.codeName || e.message}`; } }

const tsOpts = { timeField: "ts", metaField: "meta", granularity: "minutes" };
out.create_ts_with_validator_and_action = tryIt(() => {
  p.createCollection("ts_a", { timeseries: tsOpts, validator: schema, validationAction: "error" });
});
out.create_ts_with_validator_only = tryIt(() => { p.createCollection("ts_b", { timeseries: tsOpts, validator: schema }); });
p.getCollection("ts_a").drop(); p.getCollection("ts_b").drop();
out.create_ts_plain = tryIt(() => { p.createCollection("ts_probe", { timeseries: tsOpts }); });
out.is_timeseries = p.getCollectionInfos({ name: "ts_probe" })[0].type;
out.valid_insert = tryIt(() => { p.ts_probe.insertOne({ ts: new Date(), meta: { mmsi: "211234567" },
  loc: { type: "Point", coordinates: [31.2, 30.0] }, sog: 10.5 }); });
out.invalid_insert_rejected = tryIt(() => { p.ts_probe.insertOne({ ts: new Date(), meta: { mmsi: "12" },
  loc: { type: "Point", coordinates: [31.2, 30.0] }, sog: "fast" }); return "NOT rejected"; });
out.index_2dsphere_measurement = tryIt(() => { p.ts_probe.createIndex({ loc: "2dsphere" }); });
out.index_meta_time = tryIt(() => { p.ts_probe.createIndex({ "meta.mmsi": 1, ts: 1 }); });
out.unique_index_on_ts = tryIt(() => { p.ts_probe.createIndex({ "meta.mmsi": 1, ts: 1 }, { unique: true, name: "u" }); });
out.geo_query = tryIt(() => p.ts_probe.countDocuments({ loc: { $geoWithin: { $centerSphere: [[31.2, 30.0], 0.01] } } }));
out.collection_options = tryIt(() => p.getCollectionInfos({ name: "ts_probe" })[0].options);
out.jsonschema_audit_query = tryIt(() => p.ts_probe.countDocuments({ $nor: [schema] }));
out.regular_collection_validator_rejects = tryIt(() => {
  p.createCollection("plain", { validator: schema, validationAction: "error" });
  try { p.plain.insertOne({ ts: new Date(), meta: { mmsi: "12" }, loc: {} }); return "NOT rejected"; }
  catch (e) { return `rejected (${e.codeName})`; }
});
p.dropDatabase();
out.probe_db_dropped = !db.adminCommand({ listDatabases: 1 }).databases.some(d => d.name === "ports_probe");
printjson(out);
