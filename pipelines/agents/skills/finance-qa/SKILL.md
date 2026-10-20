---
name: finance-qa
description: How to answer one finance question about NileGate: which tool and dataset to call, numbers as slots, sources, and when to answer "not in the data" or "not permitted" instead of guessing. Load before answering any finance question.
stage: 1
reviewed_by_owner: no
---
# Finance Q&A

You answer one question from a NileGate employee. The system knows who asks and enforces access; never ask for it.

## Steps
1. **Read the question:** the week (ISO week 1–52 of 2025, "2025-W23" = week 23), the metric, a category, customer
   or invoice it names. A week outside 2025 or in the future, or a metric NileGate does not compute (profit, margin,
   costs, headcount), is **not in the data**: answer with status `not_in_data` and no tool call.
2. **Call the one tool that holds it:**
   - `finance_kpi(report_week, dataset)`: `weekly` (billed, invoices, collected, AR, overdue, aging, DSO, budget
     variance, top-10 share and their WoW), `category` (billed / budget / WoW per vessel category, largest change
     first = the drivers), `customers` (13-week ranking, share, previous rank), `overdue` (overdue invoices, largest
     first), `trend` (13 weeks).
   - `invoice_audit(report_week)` for flagged / duplicate / wrong invoices; `compute_toll(...)` for a Suez toll;
     `search_documents(query)` for a document (annual report, tariff notes); `suez_transits` for canal traffic.
3. **A tool result with status `not_permitted`:** answer with status `not_permitted`, say the user's role has no
   access to that data, and give **no number**. Never answer from memory or another tool instead.
4. **`no_data` or nothing relevant in the passages:** status `not_in_data`; say what is missing. Never estimate.

## Writing the answer
- Two to four sentences, in the question's language (English, or Egyptian Arabic for an Arabic question; keep the
  metric and category names as the tools give them).
- **Every NileGate number is a slot**, never typed: `{<evidence id>:<field>|<format>}` for a one-row result,
  `{<evidence id>[<row key>]:<field>|<format>}` for lists (the row key = the category, customer name or invoice
  number). Formats: money `M` / `k` / `sdr`, percent `%1` / `%2`, days and counts none; add `|dir` to a change field
  (wow, change, variance) to write the direction ("up 3.2 %" / "ارتفع 3.2 %"). A slot writes its own unit and
  direction: no "SDR", "%" or "up" next to it.
- Literal numbers allowed: the week and year, an invoice number, a date, numbers the question itself gives (a
  tonnage), and a figure quoted from a document passage you cite (with its document).
- Answer exactly what was asked: the week, the metric, the row. Name the category / customer / invoice in words too.
- `evidence_ids`: the ids of the results your slots and quotes use (from the evidence list).

## Examples
- "How much did we bill in week 23?" → `NileGate billed {insight.c1:billed_sdr|M} in week 23 of 2025
  ({insight.c1:invoices_billed} invoices).`
- "Which category drove week 24?" → `Crude Oil Tankers drove the change in week 24:
  {insight.c2[Crude Oil Tankers]:billed_wow_change_sdr|M|dir} week over week.`
- An Operations employee asks for receivables, `finance_kpi` returns not_permitted → status `not_permitted`:
  "Your role has no access to NileGate's receivables (Finance data)."
