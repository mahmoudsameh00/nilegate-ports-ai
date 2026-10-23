# Qa_golden — Final Checkpoint

Script: `pipelines/scripts/agents/Qa_golden.py` (Agents plan Phase 7, §5d step S3; §8a G2 / G3 / G4).

## Steps
1. **Askers by rule** (lowest employee_id per profile): Finance employee 13 (asks the answerable questions),
   Operations employee 12 and Operations manager 2 (refused cases), the CEO 1 (control). The Operations employee is
   refused the finance views (asserted).
2. **30 English items**, written by hand, expected values from the Stage 1 tools as the CEO (= the views):
   22 answerable (8 week lookups, 5 WoW / vs budget, 3 category drivers, 3 customers, overdue + audit, a toll),
   4 abstention (2024 week, profit margin, an unknown customer, a 2026 week), 3 refused (Operations employee:
   receivables, overdue list; Operations manager: the HbR level-3 revenue) and the CEO control (same HbR question,
   answered: €940.4 million). Element kinds: `value` (a slot bound to the tool / args / row / field), `name`,
   `direction`, `fact`; relevance = week number + a metric word.
3. **10 Egyptian Arabic twins** (G2) of answerable items, same elements, Arabic metric words; threshold fixed before
   any run: AR completeness ≥ EN completeness − 0.10.
4. Frozen: `Data/processed/agents/eval/finance_qa_golden.jsonl`, 40 items, sha256 `d7d1e94f449c137d…`; a re-run
   recomputes and stops on any difference.

## Values picked by rule (reviewed snapshot)
Top driver week 24 = Crude Oil Tankers; furthest below budget week 16 = Containerships; entered the top 10 in week
41 = Ostanor Lines (16 → 9); largest customer 13 weeks to week 23 = Belanor Tankers; largest overdue invoice week
49 = INV-0000723; toll laden containership 50,000 SCNT = 237,150.00 SDR; week 15 audit = INV-0000925 (duplicate).

## Problems and fixes
- The HbR leak pattern first matched a level-1 chunk: "6.6 %" (revenue growth) inside "36.6%" (a market share).
  Fixed with a look-behind; asserted: the pattern matches 2 level-3 chunks and 0 others.

## v2 (2026-10-22, owner review of Phase 7, plan §5f F4)
- **Two askers per profile** (D-P7-3): the two lowest employee ids — Finance employees 13 / 24, Operations
  employees 12 / 17, Operations managers 2 / 3, the CEO 1 — a profile's questions alternating between them in order
  (the Arabic twins keep their English item's asker). **r03b**: the second Operations manager asks the HbR question
  (the profile has one question otherwise). **r05** (D-P7-4): a Finance employee asks it too — refused, level 3 is
  above the owner-department rule (ADR-006). 32 EN + 10 AR = 42 items.
- **Scorer notes fixed by rule, no answer taken from a run:** the category word list holds the 13 categories' type
  names ("tanker", "carrier", "containership", "ship", "floating unit": q14's right answer scored 0); the Arabic
  billing words gain «فاتور» / «فوتنا» (q01_ar); r04 accepts the report's thousands form ("940,355 thousand").
  Checked on hand sentences: right answers pass, off-topic ones and a wrong figure still fail.
- Re-frozen through a recorded transition (`REFREEZE`, the old sha prefix + reason): `d7d1e94f449c137d…` →
  `5cf72ac33e5765d5…`; a second run changes nothing. `Stage1_eval.py` reads 42 questions; Phase 4 still answers 38
  with fake models (the 4 document questions need live retrieval).
