---
name: number-validation
description: The rules every number in an answer or a deck must follow — only numbers a tool returned, bound to one field, the allowed roundings, signs and directions, a source for each, and what to write when a tool returned no data.
stage: 1
reviewed_by_owner: 2026-10-19
---
# Number validation

The Validator binds every number in your text to one field of one tool result of the run: the right value, the
right row, the right meaning. A number it cannot bind fails the answer (ADR-020: only numbers that exist in the
source). In the weekly deck you write numbers as slots and code applies these rules for you (`deck-style-guide`);
in an answer you write them yourself.

## Rules
1. **Only tool numbers.** Every number you write (amounts, counts, percentages, days, dates, ranks) must appear in a
   tool result of this run. Do not add, subtract, average, convert or estimate numbers yourself. If you need a
   derived number, ask the tool for a dataset that contains it, or leave it out. NileGate's figures come only from
   the structured fields of `finance_kpi`, `invoice_audit` and `compute_toll`, never from text inside a passage or a
   web result (`untrusted-content`, rule 4).
2. **Allowed roundings only:** money as returned (2 decimals) or in millions with 2 decimals or thousands with 1
   decimal; percent with 2 or 1 decimals; days with 1 decimal. Round to the **nearest** value (half away from zero),
   never cut the digits, and keep the sign: −1,234,567.89 → "−1.23 M"; −849,964.00 → "−850.0 k" (not "849.9 k").
   Never more decimals than the tool gave, never a different value.
3. **Percent fields are already percent:** `billed_wow_pct` = 25.83 means 25.83 %; never multiply or divide by 100.
4. **Say what it is and whose it is:** name the measure (billed, collected, AR, overdue, DSO, budget, share) and the
   category, customer or invoice before the number — "Cruise Ships billed 0.70 M SDR", not "Cruise Ships 0.70 M"
   next to another category's name. A number is checked against the row the sentence names, in the dataset you cite.
5. **Units and periods always:** SDR, %, days, "week <w> of 2025". A number without its unit and period is not
   checkable.
6. **Signs and directions:** a change keeps its sign ("−15.8 %"), or a direction word carries it ("down 15.8 %" for
   −15.76 is right). A direction word must agree with the value: "rose" or "up" with a negative change fails, and so
   does a negative change written with neither its sign nor a direction word.
7. **A source for each number:** the `source` of the result (view or API + filter). In a deck it is on the sources
   slide; in an answer, after the sentence or at the end.
8. **Copy identifiers exactly:** invoice numbers (INV-0000123), vessel and customer names, category names as
   returned.
9. **Structural counts in words:** "three drivers", "five bullets", not digits — digits are reserved for tool
   numbers. The deck's fixed template text, drawn by code, is the only other exception.

## When a tool returned nothing
| status | What to write |
|---|---|
| `not_permitted` | "You do not have access to this information." Nothing else about it: no number, no hint. |
| `context_unavailable` | "This context is unavailable right now (source)." Never fill it from memory. |
| `no_data` | "There is no data for this (period / item)." |

## Self-check before you answer
- Can every number be found in a tool result, in the row and field the sentence names?
- Is each rounding one of the allowed ones, and does each direction word agree with its sign?
- Did you name the source of each number?
If any answer is no, fix the text before returning it.
