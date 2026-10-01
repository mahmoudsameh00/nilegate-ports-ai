### Final Checkpoint — what was done, what went wrong, how it was fixed

| Step | What | Problem found | Fix / consequence |
|---|---|---|---|
| 1 | Connect as the app user; compare raw-sample hashes with the profiles | — | A changed sample stops the load. |
| 2 | Parsing helpers copied from the profiling notebook | No shared `.py` module yet | Phases 3–4 compare the results with the saved profiles (MMSI classes, record counts), so a divergence stops the notebook. |
| 3 | Real AIS dispositions | 23 invalid MMSIs, 21 non-ship MMSIs, 6 NOAA duplicates (MMSI, time); `.replace(x, None)` is ambiguous across pandas versions | Every row gets one reviewed reason (50 rejected, listed in `load_audit/<run>_rejected.csv`); explicit `blank_none()` helper. |
| 4 | EDI sample | Its `UNT` count is wrong (17 for 16) | Stored as sent, `flags: ["unt_count_mismatch"]`. |
| 5 | Synthetic artifacts | — | Manifest hashes verified; synthetic rows pass the same rules (0 rejected). |
| Load | Specs, validators, indexes | MongoDB 8.0.32 refuses `$jsonSchema` and unique indexes on time-series collections (probe `003`); it also creates `meta_1_ts_1` by itself | `ais_positions` validated in Python + post-load audit; `ais_vessels` / `edi_messages` have server validators; the automatic index is listed as expected. |
| Reload | Counts, schema audit, indexes, duplicates, coverage, hashes — read from MongoDB | Sorting ~900k time-series documents exceeds the in-memory sort limit | `allow_disk_use(True)` on the hash scan; 0 violations, 0 duplicates, 0 unaccounted. |
| Audit | Consistency with PostgreSQL (18 checks) | — | All 0: identities, codes, containers, start/end ports, no teleporting (max 19.82 kn), EDI ↔ AIS voyage, no shared identifiers between real and synthetic data. |
| Report | `load_audit/<run>.json` + rejected rows | — | Content hashes identical on consecutive runs → the load is idempotent. |
