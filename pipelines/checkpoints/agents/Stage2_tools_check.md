# Final Checkpoint — Stage2_tools_check (Agents plan Phase 9, 2026-10-27)

**What it proves:** each Stage 2 (Operations Desk) tool in `pipelines/agents/tools/` returns exactly its governed
source, reproduces the synthetic world it reads (ADR-032) on all 500 voyages, never returns the ETA answer key, sees
the world only up to the run's clock, refuses what ADR-006 forbids with no data, and degrades to "context unavailable"
instead of guessing. Design: plan §6a "Concrete design" (owner decisions P9-1…P9-8), ADR-055 / ADR-056.

| Phase | Step | Result (2026-10-27) |
|---|---|---|
| 0 | Foundation (S1): the clock in the run context, the Stage 2 registry, the MongoDB reader | `as_of` default = 2026-09-13T00:00Z; a naive time and a time past the data refused; Stage 1's `RunContext(user, dataset)` unchanged; 3 / 3 calls without a context refused; `nilegate_reader` authenticates as itself with role `read` only, reads `ais_positions`, 3 / 3 writes refused (Unauthorized) |
| 1 | `sea_route` (S2) vs published distances | Singapore ↔ Rotterdam 8,388.5 / 11,876.7 nm both ways (+1.2 % / +1.0 % vs 8,288 / 11,755); Jeddah 4,036.3 / 11,005.1; Port Said ↔ Rotterdam 3,315.8 with and without Suez (Gibraltar only); Bab el-Mandeb closed → the Cape; Sokhna with Suez closed → `no_data`; 9 single-leg voyages = `route_nm` (0.000 nm); sea days + day points; 4 bad argument sets refused; 12 route cases frozen |
| 2 | Migration 020 + `vessel_params` (S4–S5) | tables = the reviewed CSVs (39 + 1); 500 vessels each in one band at its own service speed, fuel = main × (v / v_ref)³ + aux (39 bands used); Containerships band 2 by hand (109.0 t / day at 16.3 kn, × 0.512 main at 80 % speed); 691.24 SDR / t; band edges lower-inclusive; 6 bad argument sets refused |
| 3 | `voyage_status` (S6) vs the generator | 500 / 500: route = `route_nm` (≤ 0.1 nm), last fix = the generator's, status = `vessels.status` (219 / 130 / 78 / 73); distance left ≤ 1.79 nm for the 219 at sea (vs the generator's own timeline); anchored ≈ 5 nm; the cut half-way to the as-of for all 219 uses no later fix and returns no arrival; before departure = Not departed; no fix → `no_data`; no ETA field, no time after the clock |
| 4 | `marine_weather` (S7), offline then live | own date per point; past → Historical Forecast + Marine, future → Forecast; cache hit 0 requests; timeout / 500 / not JSON / wrong shape → context_unavailable, nothing cached; land / beyond the horizon → null + note; 4 bad argument sets refused; live 3 points on 2026-09-13 = the §6a F5 probe (0.84 / 0.52 / 4.14 m; 12.2 / 15.9 / 32.7 kn), cached for good |
| 5 | RBAC matrix + contract (S8) | 100 employees × 4 tools = ADR-006 (400 granted, all level 1); a probe user below every ceiling refused by all 4 with no row and no source (leakage 0); no user / dataset / clock field in any schema; 4 / 4 wrappers refuse a missing context |

Whole run: Phases 0–5 ✅, pending none, ~64 s, files changed 0 (the first run created
`Data/processed/agents/tool_cache/marine_weather.jsonl`, git-ignored). `Tools_check.py` (Stage 1) 8 / 8 ✅ after the
`RunContext` change.

## Problems and fixes

1. **pymongo and a `_`-prefixed collection (S1).** `mdb._privilege_check` is read as an attribute and refused →
   item access `mdb["_privilege_check"]`.
2. **The auto-mode safety check failed intermittently (S2–S3).** Large edits and some reads got no verdict → the
   check script was written in small pieces; the IMO PDF was read through a small dump script (the project hook
   blocks reading files > 400 KB).
3. **Fuel per type alone would be off by multiples (S3).** SCNT spans 5–15× inside a category → 3 SCNT bands per
   category (tertiles of our vessels), mapped by rank to IMO size bins (our SCNT cannot be converted to dwt / TEU /
   cbm), raw IMO figures kept beside the derived ones (D-P9-6); the reference speed = IMO's average speed at sea, the
   speed the consumption belongs to (D-P9-4); main and auxiliary split so the cube law touches the main engine only
   (D-P9-5; cruise ships burn about half their fuel in auxiliaries).
4. **Zero-length legs (S6, D-P9-9).** Two ports snapped to the same MARNET node give a searoute path of length 0;
   `sea_path` calls that "no route" (right for `sea_route`), but the generator still routes through that node: 48
   rebuilt routes were off by up to 78.7 nm → `routes.sea_leg`, the generator's rule exactly.
5. **A flat projection on long steps (S6, D-P9-10).** MARNET steps can be hundreds of nm; projecting the fix in a
   local plane drifted by miles (vessel 423: 2.2 nm) → projection on the sphere, as the generator moves (slerp).
6. **Port visits that retrace the same water (S6, D-P9-11).** Vessel 100 sails into Singapore and back out: two
   projections ~10 nm apart, and the odometer (summed 10-min steps) runs a few nm short at the turns, so it picked
   the wrong pass (9.5 nm) → the projection whose route course matches the fix's COG (± 60°), then the odometer.
7. **`verify_readonly.sql` numbering (S4, D-P9-7).** §20 was taken by migration 016 → the new section is §24.

## Notes for later phases

- The synthetic voyages pass intermediate ports without a stop and sail at a constant service speed, so a
  rule-based ETA (distance left / recent speed) will be nearly exact in this data: Phase 11's baseline comparison
  must account for it (no port-call allowance to learn).
- §6's example question "Port Said → Rotterdam via Suez or the Cape" has no Cape alternative (F1a); the route cases
  start east of the canal.
