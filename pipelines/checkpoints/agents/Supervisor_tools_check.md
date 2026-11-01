# Supervisor_tools_check — Final Checkpoint

Script: `pipelines/scripts/agents/Supervisor_tools_check.py` (Agents plan Phase 12, §6d step S2; owner answers of
2026-10-29: a new `registry.PRODUCTS` + this check, the watch run resolved by the clock, a stopped advice keeps its
code rows, `fleet_customers` resolves a vessel's name). FakeRoles + the real PostgresSaver; PortWatch / Tavily
answered by a mock transport; 0 real model calls, 0 Open-Meteo calls.

## Code checked
- `pipelines/agents/tools/watch.py` — `watch_alerts` (the latest saved run at or before the clock; rows = its alerts +
  one `fleet` row) and the readers moved from the CLI (`read_alerts`, `can_read`, `run_files`; `Voyage_watch.py`
  imports them).
- `pipelines/agents/tools/fleet.py` — `fleet_customers` (customer ↔ vessel ids, a vessel's name → its id; ids only).
- `pipelines/agents/tools/products.py` — `route_advice` as a tool (`run_route_advice`, `make_route_advice_tool(roles)`):
  the ADR-057 graph in its own thread, rows = its code results + an `advice` row.
- `pipelines/agents/tools/registry.py` — `PRODUCTS`, `ROUTE_ADVICE`, `supervisor_tools(roles)` (14 unique tools).

## Steps
1. **watch_alerts** = the pinned run `voyage_watch:20260913T0000Z:1` (12 alerts + the fleet row, every field equal to
   the file); clock rule 09-06T06 → the 09-06T00 run, 09-06T12 → the 09-06T12 run, before the first run → no_data;
   the vessel / high filters; an empty folder → no_data; the probe refused with no row; a clock past the data refused.
2. **fleet_customers** = an independent SQL over `vessels` (customers 9 + 34 → 98 vessels; vessels 234 / 420 → customers
   34 / 3; "cruise voyager 234" → 234; "Voyager 339" → 339; "Voyager" (too many) and "Ever Given" → no_data; 4 bad
   argument sets rejected); no row carries a customer's name.
3. **route_advice** on cases 1 / 2 / 3 / 8: 5 rows each (suez, cape, difference, traffic, advice), the code rows =
   `route_advice.deterministic`, recommendations Suez / Suez / Suez / the Cape; a twice-bad advice → `ok` + advice
   `validation_failed`, no recommendation, the code rows kept; an unreadable reply → `output_invalid`; Port Said →
   Rotterdam → `no_suez_on_route`; the probe → not_permitted with 0 model calls; the wrapper refuses a missing context.
4. **The golden contract:** all 41 value elements of `supervisor_qa_golden.jsonl` reproduced by their tool as their
   asker at the clock; the 6 finance value elements of the Operations twins refused with no row; every `tools_needed`
   name is in the supervisor's union.
5. **RBAC matrix** 100 employees × the 4 product tools = ADR-006 (400 granted), the probe refused by all 4 with no row
   (leakage 0, route_advice 0 model calls), no user / dataset / clock / run field in a model-facing schema, 4 / 4
   wrappers refuse a missing context. `Tools_check.py`, `Stage2_tools_check.py` and `Voyage_watch_check.py` re-run
   after the change.

## Problems and fixes
- **D-P12-3 — a golden item the tools could not reproduce:** route case 8 sails at 12 kn, but o12 left the speed out
  of its question and args. Fixed in the golden script (v2 re-freeze, recorded transition), and the check passes the
  case's speed.
- **The refusal side of the twins was not tested at first** (0 refusals counted): an Operations twin keeps only its
  operations elements, so the check now takes the finance elements from the item it twins and expects them refused.
- **Check threads left in `agent_state`** (20): the first failed runs stopped before the cleanup, and a refused call
  opens a thread but returns no row (its id was never seen). The check now snapshots the `trigger: supervisor`
  threads first and deletes every new one at the end — also on a failure (`atexit`); the 20 leftovers (all
  `trigger: supervisor`, which only this check could have made) were deleted; the one `cli` thread was kept.
- The `customers 9 + 34` snapshot was a guess (105); the tool and the SQL both give 98.
