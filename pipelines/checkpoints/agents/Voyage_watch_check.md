# Final Checkpoint — Voyage_watch_check (Agents plan Phase 11, 2026-10-28)

**What it proves:** the `voyage_watch` graph (C Voyage & Disruption Watch, ADR-058) estimates every ETA with a rule
fixed before measuring that beats the naive baseline on replayed voyages, raises alerts by fixed rules that find the
planted weather and traffic events (precision and recall measured against the generator's truth), lets the model only
write a brief through number slots that a code Validator checks, never loses an alert when the model fails or the
process crashes, keeps one thread + one file per run, and runs on a replay clock every 12 h. Design: plan §6c
(decisions P11-1…P11-10 taken under the owner's autonomous grant — **reviewed and approved by the owner 2026-10-29**), the skill
`voyage-watch-brief` (**reviewed_by_owner: 2026-10-29**).

| Phase | Step | Result (2026-10-28) |
|---|---|---|
| 1 | ETA rules (S1) on 126 cuts of 50 voyages frozen in `eta_cases.json` before any prediction (25 arrived × 25 / 50 / 75 %, 25 at sea × the cuts ≤ the as-of instant + the as-of instant) | **MAE R 0.885 h, N 117.826 h, S 1.636 h, R0 1.274 h** (frozen in `eta_eval.json` after the first clean run); S2-D5 met (R < N); the ML margin (> 2 h and > 5 % of the mean 366.6 h left) not reached → no ML; worst R −10.8 h (85 days left: the 6 h mean SOG's noise); no predictor saw `arrival_ts`, `eta_raw` or a later fix |
| 2 | Next-leg points + Suez ahead (S2) | 810 points of the 219 at sea vs the generator's timeline: ≤ 1.75 nm at h = 0, ≤ 7.1 nm at +72 h; kept / dropped as the truth 810 / 810; Suez ahead = searoute's passages on all 498 routes (173 cross the canal), 40 of the 219 still have it ahead, 0 bound violations |
| 3 | Alert rules on planted events (S3), fake Open-Meteo / PortWatch | 32 storm discs (6 kinds) on true future positions: weather **precision 1.0, recall 1.0** (27 / 27 incl. passers-by), severities 27 / 27; Suez −30 % and −45 % → 40 / 40 (moderate / high), −10 % and PortWatch down → 0; near-threshold (3.9 m / 33.9 kn) and null discs → none (6 points unknown); same inputs twice → identical; sensitivity: 10 nm discs 22 / 22, 5 nm discs recall 0.95 (below the dead-reckoning error) |
| 4 | The brief's Validator (S3) | 49 / 49 planted errors caught (typed numbers, shifted ETA, slot on an uncited alert, invented id, high alert left out, route / transits evidence, unknown field, wrong format, a date of another day); 0 false alarms on 3 clean briefs; the normaliser touched none; metres / hours / signed percent render |
| 4s | The skill (S3) | 227 chars, 1,071 tokens (≤ 1,200), every named field real, the example slots use real fields and allowed formats, the rules stated; not yet reviewed by the owner |
| 5 | The graph on FakeRoles + the real PostgresSaver (S4) | ok (1 call), no alerts (0 calls), patch (2), validation_failed and output_invalid keep all 12 alerts, PortWatch down / Open-Meteo down → ok + said in the assumptions, moored only → no_data; a crash in the brief: the run file already held the alerts, the resume repeated 0 voyage_status calls and 0 HTTP requests; the run file = the final result |
| 6 | The real model once (S5), live weather / PortWatch through the cache | 297 watched (219 + 78 at anchor), 12 weather alerts (3 high: 7.6 m, 6.8 m, 6.3 m), 5 / 810 points unknown, PortWatch +2.7 % (no traffic alert); **the brief passed the Validator on the first reply** (flash-lite, 1 call; cached afterwards) |
| 7 | RBAC, contract, planner, firings, retention, reader (S5) | 100 employees may read; a probe user → not_permitted with 0 tool and 0 model calls, the reader refuses it; no user / clock / dataset in a model-facing schema; `voyage_eta` = rule R, refused without a run context, an anchored vessel → no_data; the planner (15 instants 09-06 … 09-13, next, resume first, a run by hand counts, done); identity = Operations managers 2 and 3 only; four firings on the whole fleet (start, start, crash, resume); retention 31 days later: 3 ended threads archived + deleted |

Whole run: Phases 1–7 + 4s ✅, pending none, ~140 s, files changed 0 once cached. Regression after the shared changes
(slots, `route_advice.traffic`, scheduling): see the plan's handoff.

## Problems and fixes

1. **The next-leg points started at the last fix, not at the clock (S2).** A fix is up to ~10 min old: 3 nm of
   sailing missing → dead-reckoned from the clock (`lag_h`).
2. **The check's truth was wrong first (S2).** The voyage file's `service_kn` is rounded to 2 decimals: over 1,900 h
   that is 6–10 nm → the truth uses the speed implied by the generator's timeline, as Phase 9's check did. Found
   because h = 0 disagreed with Phase 9's 1.79 nm.
3. **A route fallback vessel has no searoute legs (S2):** its great-circle leg crosses no passage → no canal.
4. **A Suez drop is a fleet-wide event (S3, D-P11-1).** At −45 % every vessel with the canal ahead is a high alert
   (54 high with the weather) → 6 items × 8 ids could not cite them all → one item may cite up to 60 alerts, and it
   names at most three vessels (400 characters) — the skill says so.
5. **The run file was not the final state (S4):** it lacked `run_file` and the model's defaults → render writes the
   validated result.
6. **The alert reader knew one prefix (S5)** → it reads any watch prefix (the check's runs too).
7. **A live run met failing Open-Meteo batches (S5).** The first real run had 213 of 810 points unknown and 7 alerts:
   the designed degradation (a failed batch is never cached, its points are unknown, the assumptions say so); the
   next run fetched them (5 unknown, 12 alerts). The snapshot keeps the complete answer.

8. **The first scheduled firing hit Open-Meteo's per-minute limit (2026-10-29, D-P11-2).** 1,448 points × 2 APIs sent within a minute, counted per location against 600 / min → 848 points lost (exit 0, an incomplete run, said only as "unknown"). Fix: batches paced under 400 network locations / min (cache hits free), one retry after 65 s, the reason kept (`weather_errors`), an explicit assumption when weather stays incomplete. Phase 3 now proves it: 6 refused requests → nothing lost; on a fake clock no 60 s window sends more than 360; cached points wait 0 s.

## Notes for later phases

- The ETA score measures how well the tools rebuild the synthetic data (constant speed, no weather, no port stop):
  real voyages would need the S2-D2 port-call allowance and a weather slow-down, and the ML margin would then mean
  something.
- The weather alerts use the daily maximum at a point once a day; a storm crossed between two points is not seen (the
  5 nm sensitivity shows the limit). Shorter steps cost Open-Meteo quota (counted per location: UNCERTAIN).
- PortWatch publishes about a week late: a replayed run reads data published after its clock (not the vessel truth).
- Phase 12: the supervisor binds `voyage_eta` and reads the saved alerts (`Voyage_watch.read_alerts`) as tools.
