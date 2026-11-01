---
name: voyage-watch-brief
description: How to write the voyage watch brief from the voyage_watch evidence: which alerts to name first, every high alert cited, numbers as slots, dates copied from the alerts, the shape of WatchBrief. Load before writing a watch brief.
stage: 2
reviewed_by_owner: 2026-10-29
---
# Voyage watch brief

Code has watched the fleet, estimated every ETA and raised every alert by fixed rules. You write a short brief for the
Operations desk about those alerts. Never add, drop, rank by your own judgement, recompute or round anything.

## The evidence you get
- `watch.fleet` (one row): `as_of`, `vessels_watched`, `in_transit`, `anchored`, `alerts_total`, `alerts_high`,
  `alerts_moderate`, `weather_alerts`, `suez_traffic_alerts`, `suez_ahead_vessels`, `weather_points`,
  `weather_unknown_points`, `change_transits_pct` (null when IMF PortWatch did not answer).
- `watch.alerts`: one row per alert, keyed `vessel_id/kind` (e.g. `watch.alerts[36/weather]`), high first:
  `severity` (high / moderate), `vessel_name`, `destination`, `next_port`, `eta_utc`, `eta_in_h`, `reason`;
  weather alerts add `date`, `hours_ahead_h`, `wave_height_max_m`, `wind_speed_10m_max_kn`; Suez traffic alerts add
  `change_transits_pct`.

## Writing WatchBrief
- `headline`: one sentence — how many alerts and how many are high, from `watch.fleet`, and the most serious one.
- `items`: 1 to 6 sentences. **Every high alert must be in some item's `alert_ids`.** High alerts first, then
  moderate; several weather alerts may share one item (up to 8 ids); a Suez traffic drop concerns every vessel with
  the canal ahead, so **one** item lists every `suez_traffic` alert id (up to 60). An item names **at most three**
  vessels by `vessel_name` (the count of the rest as a slot, e.g. `{watch.fleet:suez_traffic_alerts}`; the alert
  table lists them all) and the destination by its LOCODE, says what (waves, wind, Suez traffic), when (the `date`,
  or "in {…:hours_ahead_h}"), and the ETA; at most 400 characters.
- **Every number is a slot**, never typed: `{watch.alerts[36/weather]:wave_height_max_m}`,
  `{watch.alerts[36/weather]:eta_in_h}`, `{watch.fleet:alerts_high}`. Formats: metres `m`, knots `kn`, hours `h`,
  percent `%1` / `%2`, counts none. A slot writes its unit and sign: no "m", "kn", "h" or "%" next to it.
- A slot on `watch.alerts` must name an alert listed in that item's `alert_ids`.
- Literal numbers allowed: **dates only**, copied exactly from a cited alert's `date` or `eta_utc` (e.g.
  "2026-09-14", "2026-09-15T06:40Z"). Vessel names keep their digits ("Special Voyager 001").
- No alert means no item about it; a missing weather value is "unknown", never "calm". The alert table, the ETAs,
  the assumptions and the sources are written by code: do not repeat them.

## Examples
- Headline: "{watch.fleet:alerts_total} alerts on the next legs, {watch.fleet:alerts_high} high: Crude Voyager 005
  meets {watch.alerts[5/weather]:wave_height_max_m} waves on 2026-09-14."
- High weather item (alert_ids `5/weather`): "Crude Voyager 005 (to NLRTM, ETA 2026-09-20T11:05Z) meets waves of
  {watch.alerts[5/weather]:wave_height_max_m} and wind of {watch.alerts[5/weather]:wind_speed_10m_max_kn} in
  {watch.alerts[5/weather]:hours_ahead_h}."
- Suez items (alert_ids `12/suez_traffic`, `40/suez_traffic`): "Suez Canal transits are
  {watch.alerts[12/suez_traffic]:change_transits_pct|%1} against a year earlier, with the canal still ahead of
  Petroleum Voyager 012 and Containers Voyager 040."
