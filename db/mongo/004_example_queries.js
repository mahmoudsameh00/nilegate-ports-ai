// =====================================================================
// 004 — Example queries the future tools / agents will run (read-only). Run AS THE APP USER (run.ps1 -AsApp).
// Also shows which index each query uses (explain → winning plan stage).
// =====================================================================
const d = db.getSiblingDB(process.env.APP_DB || "ports_logistics");
// time-series explains nest the plan inside aggregation stages, so search the whole explain document
function planOf(explained) {
  const s = JSON.stringify(explained);
  return [...new Set((s.match(/"indexName":"([^"]+)"/g) || []).map(x => x.split(":")[1].replace(/"/g, "")))].join(", ") || "COLLSCAN";
}

// 1. latest position of one of our vessels (vessel_id 1 -> its MMSI from ais_vessels)
const v1 = d.ais_vessels.findOne({ source: "synthetic_ais", vessel_id: 1 }, { _id: 0, mmsi: 1, name: 1, destination_locode: 1 });
const last = d.ais_positions.find({ "meta.mmsi": v1.mmsi }, { _id: 0, ts: 1, loc: 1, sog: 1, navstat: 1 }).sort({ ts: -1 }).limit(1).toArray()[0];
print("1. vessel", JSON.stringify(v1), "last fix", JSON.stringify(last));
print("   plan:", planOf(d.ais_positions.find({ "meta.mmsi": v1.mmsi }).sort({ ts: -1 }).limit(1).explain()));

// 2. vessels at anchor within 20 nm of Alexandria (EGALY, 29.87 E / 31.18 N) at any time — geospatial index
const nm20 = 20 / 3440.065;
const anchored = d.ais_positions.distinct("meta.mmsi", { navstat: 1, loc: { $geoWithin: { $centerSphere: [[29.87, 31.18], nm20] } } });
print("2. MMSIs at anchor near EGALY:", anchored.length);

// 3. which containers are declared on the IFTMIN of the vessel with IMO 9000001
const m = d.edi_messages.findOne({ "keys.vessel_imo": "9000001" }, { _id: 0, "keys.voyage": 1, "keys.container_numbers": 1, "keys.locodes": 1 });
print("3. IFTMIN for IMO 9000001:", JSON.stringify(m));
print("   plan:", planOf(d.edi_messages.find({ "keys.vessel_imo": "9000001" }).explain()));

// 4. counts per collection and kind
["ais_positions", "ais_vessels", "edi_messages"].forEach(c => {
  const key = c === "ais_positions" ? "$meta.real_or_synthetic" : "$real_or_synthetic";
  print("4.", c, JSON.stringify(d.getCollection(c).aggregate([{ $group: { _id: key, n: { $sum: 1 } } }, { $sort: { _id: 1 } }]).toArray()));
});
