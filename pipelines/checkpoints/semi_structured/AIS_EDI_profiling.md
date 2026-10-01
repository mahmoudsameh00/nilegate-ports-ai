### Final Checkpoint — what was done, what went wrong, how it was fixed

| Phase | What | Problem found | Fix / consequence |
|---|---|---|---|
| 1 | File registry (`sha256`, size, encoding) + shared helpers (MMSI class, IMO check digit) | — | Registry is the provenance used by the loader; snapshot guards against a changed sample. |
| 2 | AISHub structure | No header object (not the usual AISHub API shape), so no `FORMAT` field; every value is a string; time field `TSTAMP` | Format inferred from value ranges (all degree-like → format 1); explicit type conversion in the loader. |
| 3 | AISHub field profile | Snapshot of 30 minutes, one record per MMSI (no tracks); 6,050 IMO placeholders (`1234567` even passes the checksum); call-sign placeholders (`DATAHUB`, `0000000`); sentinels hide 2,320 COG / 5,050 HEADING values; DEST free text (883 known UN/LOCODEs); ETA without a year | Reviewed placeholder lists; sentinels → `null`; IMO optional; AISHub feeds `ais_vessels` and code diversity, not movement. |
| 4 | NOAA track profile | Only 78 minutes of harbour traffic, 116 moving steps; 6 same-MMSI-same-time duplicates; 2 jitter steps (2–8 s) gave 250–320 kn implied speed | Implied speed on steps ≥ 10 s (p99 29.6 kn); duplicates removed by the loader; open-sea speeds will be documented defaults. |
| 5 | Cross-sample + our identifiers | Our `imo_number` and `container_number` are sequential and mostly fail their check digits (50/500, 101/1,000) | Not changed (PostgreSQL canonical); check digits are enforced on real data only; raised to the owner. No real IMO equals ours. |
| 6 | IFTMIN EDIFACT profile | Sample self-described as synthetic; `UNT` declares 17 segments for 16; vessel id is not an IMO; no voyage number; container fails ISO 6346 | Stored as a synthetic template with the UNT mismatch flagged; generator writes IMO + voyage and computes UNT. |
| 7 | Profiles saved and reloaded | — | 5 JSON files, byte-identical on re-run, reloaded and compared. |

**Design consequences for plan Phase 2:** `ais_positions` will hold the NOAA fixes (real, thin) and the synthetic
tracks; `ais_vessels` the AISHub static/voyage records (real) and our 500 vessels (synthetic, D9); granularity
`minutes` fits the observed intervals (~70 s moving, ~180 s stationary); IMO and call sign are optional fields;
non-ship MMSIs are rejected with a reason; the EDI sample is a synthetic template.
