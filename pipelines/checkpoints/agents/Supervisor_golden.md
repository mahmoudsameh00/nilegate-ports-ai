# Supervisor_golden — Final Checkpoint

Script: `pipelines/scripts/agents/Supervisor_golden.py` (Agents plan Phase 12, §6d step S1; §8a G2 / G3 / G4; owner
answers of 2026-10-29: the customer bridge in, one pinned clock + explicit 2025 weeks, the partial answer scored on
the result and the text, 10 Arabic twins). 0 model calls, 0 Open-Meteo / PortWatch / web calls.

## Steps
1. **Clock and askers.** One clock for every item: 2026-09-13T00:00Z (the data's as-of instant) = the clock of the
   watch run `voyage_watch:20260913T0000Z:1`, pinned by its file's sha256 `3164190cbbfa106f…` (12 alerts, 3 high,
   0 failed weather points, 5 unknown). Askers by the Stage 1 v2 rule: Operations employees 12 / 17, Operations
   managers 2 / 3, Finance employees 13 / 24, the CEO 1.
2. **21 operations items (EN)**, asked by the Operations employees (the watch items by the managers): voyage status
   ×4, ETA ×4 (`voyage_eta` at the clock = the pinned run's ETA, asserted), route advice ×4 (the `route_advice`
   graph's code rows without its context, frozen route cases 1 / 2 / 3 / 8), the watch ×3 (alerts and the fleet row),
   fuel ×2, distance ×1, abstention ×3 (vessel 9999, a real ship's live AIS — ADR-056 —, Suez traffic in December
   2026). Vessels picked by rule (lowest ids with the property), asserted in a reviewed snapshot.
3. **10 cross-product items (EN)**, asked by the Finance employees: the finance part names its 2025 week (49 or 52),
   the operations part is "now". Customer → vessels through `vessels.customer_id` (the bridge S2 builds as the tool
   `fleet_customers`). An element selected by a finance result is a finance element. Each item lists `tools_needed`.
4. **RBAC twins (16).** Each cross item asked by an Operations employee → `partial` with the refused tools and words,
   only the operations elements required, must-not = every finance value (SDR with any separator, thousands,
   millions, % and days, Western and Arabic-Indic digits) and every level-2 name not in the question; 6 of the 10
   keep no operations element (selected by finance) and accept `not_permitted`. Five operations items asked by a
   Finance employee → `answered`; c06 asked by the CEO → `answered`. Each must-not pattern is checked on hand
   sentences: it catches its finance value and misses the item's operations values, its question and its names.
5. **10 Egyptian Arabic twins** (6 operations + 4 cross), the same elements (name and date forms hold Arabic words);
   threshold fixed before any run: AR completeness ≥ EN − 0.10. Frozen:
   `Data/processed/agents/eval/supervisor_qa_golden.jsonl`, **57 items** (47 EN + 10 AR; 44 answered, 10 partial,
   3 not_in_data), sha256 `070a745bee233a92…`; reloaded and re-validated; a second run changes 0 files.

## Picks (reviewed snapshot)
o01–o08 vessels 1, 2, 3 (anchored), 7 (arrived), 5, 6, 10, 12; o09 vessel 21 → Suez cheaper; o12 vessel 6 → the
Cape; o13 high alerts 234 / 339 / 420. Top 5 customers to week 52 = 9, 34, 10, 37, 1; their alerted vessels 84, 198,
234, 315, 401, 423; the overdue invoice of week 49 with an alert = INV-0000005 (vessel 420, high); largest overdue of
week 49 = INV-0000723 (vessel 165, at port); overdue vessels at sea (week 52) 238 / 271 / 274; the customer with the
most alerted vessels = Korilis Cruises.

## Problems and fixes
- **Operations managers may read the finance views** (ceiling 2 ≥ level 2): only the Operations *employees* are the
  refused side (Stage 1 refused the managers only level 3). The askers' assertion was corrected; the twins use the
  employees.
- **An invoice is a Suez toll**: the toll of vessel 420 from the public tariff (level 1) = its overdue invoice's
  amount (622,758.68 SDR), caught by the must-not check (the permitted value matched the refused one). c06 asks the
  days past due instead; the equality is asserted in the script, and noted for the owner (plan D-P12-2).
- **v2 re-freeze (D-P12-3, 2026-10-29, before any model run):** `Supervisor_tools_check.py` Phase 4 could not
  reproduce o12 — route case 8 sails at 12 kn, but o12's question and args left the speed out (the expected values
  were computed at 12 kn). The case's speed now enters the args and o12's question ("at 12 knots"); re-frozen through
  the recorded transition `070a745bee233a92…` → `722f3ca3b7bf86f7…`; a second run changes nothing.
- The first freeze wrote the file before the format checks (a missing `watch_sha` on three watch items); the checks
  now run before writing, the file was removed and re-frozen.
