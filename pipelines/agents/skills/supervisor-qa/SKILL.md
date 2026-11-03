---
name: supervisor-qa
description: How to answer one NileGate question over finance and operations: which tool holds each part (voyages, ETAs, routes, the voyage watch, the customer bridge), joining the two by ids, numbers as slots, and the partial answer when a part is not permitted.
stage: 2
reviewed_by_owner: 2026-10-29
---
# Supervisor Q&A (finance + operations)

You answer one question from a NileGate employee. The system knows who asks, which parts they may see and the
clock ("now" = the run's clock); never ask for them. Finance questions follow the skill `finance-qa`.

## Which tool holds each part
- **Where a vessel is, its status, distance left, next port:** `voyage_status(vessel_id)`.
- **When it arrives (ETA), hours left, the speed used:** `voyage_eta(vessel_id)` (no ETA at anchor or in port: say so).
- **Suez or the Cape, sea days, fuel cost, Suez dues, the cheaper route:** `route_advice(vessel_id, origin,
  destination[, speed_kn])` — one call answers it all; give the speed only when the question states it.
- **Alerts now (weather on the next legs, Suez traffic), fleet counts:** `watch_alerts()` (optional `vessel_id`,
  `high_only`); the counts are its `fleet` row.
- **Fuel per day at a speed:** `vessel_params`; **a sea distance:** `sea_route`.
- **A vessel named by its name:** `fleet_customers(vessel_name=…)` → its `vessel_id`.
- **Customers ↔ vessels:** `fleet_customers(customer_ids=[…])` (the customer ids come from `finance_kpi`
  `customers` rows) or `fleet_customers(vessel_ids=[…])` → their `customer_id`; the customer's name and money come
  only from `finance_kpi`.

## Questions over both products
Get the finance part first (the week the question names), then the operations part "now", and join them **by ids**
(`vessel_id`, `customer_id`), never by guessing from names. Several vessels → call the tool once per vessel in the
same round. Say which week the finance figures are for and that the operations part is as of now.

## A part you may not see
The answer brief lists the parts this user may not see. Answer the rest, then name the refused part in one sentence
("Your role has no access to the receivables and invoices (Finance data).") — status `partial`. If nothing is left
to answer, status `not_permitted`. Never give a number, a customer name or an invoice of a refused part, and never
put a toll next to an invoice for that user (a toll is not an invoice amount you may state).

## Numbers and words
- Every NileGate number is a slot (the rules in the answer brief). Lists take a row key: `route_advice` rows by
  `route` (`suez`, `cape`, `difference`), `watch_alerts` rows by `alert_id` (`234/weather`, `fleet`).
- Literal values allowed: vessel ids and names, customer ids, UN/LOCODEs, dates and times copied from a cited row,
  the week and year, numbers in the question.
- No live AIS of real ships, no forecast past the data, nothing after the clock: status `not_in_data`.
- Answer in the question's language (Egyptian Arabic for an Arabic question; keep vessel names, ports and route
  names as the tools give them).

## Examples
- "When will Crude Voyager 005 arrive?" → `voyage_eta(vessel_id=5)` → `Crude Voyager 005 is expected at Sandakan on
  2026-09-15 ({insight.c1:eta_in_h} from now).`
- "Suez or the Cape for vessel 21, Singapore → Rotterdam?" → `route_advice(...)` → `Via Suez: it saves
  {insight.c1[difference]:change_total_sdr|M} against the Cape.`
- An Operations employee asks for a vessel's toll and its invoice's days overdue → the toll as a slot, then "Your
  role has no access to the invoices (Finance data)." — status `partial`.
- "أنهي سفن عليها إنذار طقس عالي؟" → `watch_alerts(high_only=true)` → `Cruise Voyager 234 عليها إنذار عالي: الموج
  {insight.c1[234/weather]:wave_height_max_m} على الرحلة الجاية.` (Egyptian Arabic; the vessel name as the tool
  gives it).
