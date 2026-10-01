### Final Checkpoint — what was done, what went wrong, how it was fixed

| Phase | What | Problem found | Fix / consequence |
|---|---|---|---|
| 1 | Read `vessels` (with `mmsi`), `ports`, `port_connections` read-only; hash of the vessel rows | — | The manifest ties the artifacts to the database state. |
| 2 | Parameters | The real samples are harbour traffic only (NOAA: 78 min in Los Angeles) | Harbour speed (6.7 kn) and the teleport threshold (30 kn) come from the profile; open-sea speeds are documented defaults per category. |
| 3 | Routes | Every connection is a straight 2-point line; 3 network components; vessels 323 and 442 cannot reach their destination. The first version drew legs as great circles: **49 % of the under-way fixes were on land** | Port sequence from Dijkstra over `port_connections` (scipy); every leg follows a sea path (`searoute`, MARNET) with the port points at its ends; 2 flagged direct-sea fallbacks. Routes ~40 % longer (median 7,178 nm). |
| 4 | Timelines and fixes | A fixed 30-day window (D10) would cut long voyages (up to 19,055 nm) so tracks would not start at the origin; the anchorage check first assumed a straight 5 nm to the port | Each track covers the current voyage up to the as-of instant; earliest departure 2026-06-24; no fix after 2026-09-13T00:00Z. The anchorage is 5 nm before the port along the path (straight line 2–5.3 nm). Open-sea fixes on land (1 km mask, > 20 nm from the route ports): **0.96 %**, all in canals and narrow waterways (Suez first). Max implied speed 19.8 kn; any vessel regenerated alone is identical. |
| 5 | Static records | PostgreSQL has no dimensions / draught / call sign | Dimensions stay `null` (not invented); synthetic call signs `NGX####`, checked against real ones by the loader. |
| 6 | Save + reload | — | 3 Parquet files + manifest, content hashes reviewed; 1,310,619 fixes (under the 2 M bound of D11). |
