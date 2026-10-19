"""A deterministic slot draft of the weekly deck (Agents plan §5c): what a correct Writer returns.

Test support, not a production path: the checks (`Deck_check.py`, `Weekly_pack_check.py`) use it as the fake
Writer's reply and as the clean base the planted wrong numbers are planted into. It follows the §5c deck — slide
titles, five summary bullets, at most three comments on slides 3–8, a context line on slide 9, nothing on slides 1 and
10 — with every number a slot and every null in words ("not available").
"""
from pipelines.agents.deck import slots

LABEL = "Draft for approval"
MAX_FINDINGS = 3


def top3(evidence: dict) -> tuple[list[str], str]:
    """The week's drivers: top three categories by |WoW change| (week 1: |budget variance|), and that field."""
    rows = evidence["kpi.category"]["rows"]
    by = ("billed_wow_change_sdr" if any(r["billed_wow_change_sdr"] is not None for r in rows)
          else "budget_variance_sdr")
    return [r["vessel_category"] for r in sorted(rows, key=lambda r: -abs(r[by] or 0))[:3]], by


class _Draft:
    def __init__(self, week: int, evidence: dict):
        self.w, self.ev = week, evidence
        self.k = evidence["kpi.weekly"]["rows"][0]

    def s(self, eid, field, fmt=None, row=None, alt="not available", direction=False):
        """A slot, or `alt` when the value is null (a slot to a null is refused)."""
        res = self.ev[eid]
        if row is None:
            value = res[field] if field in res else res["rows"][0][field]
        else:
            keys = slots.row_keys(res)
            pair = row.rsplit("/", 1) if len(keys) > 1 and "/" in row else None
            value = next(r[field] for r in res["rows"]
                         if ([str(r[keys[0]]), str(r[keys[1]])] == pair if pair else str(r[keys[0]]) == row))
        return alt if value is None else slots.binding(eid, field, fmt, row, direction)

    def draft(self) -> dict:
        w, k, s, ev = self.w, self.k, self.s, self.ev
        drivers, by = top3(ev)
        c1 = drivers[0]
        aud = ev["audit.week"]
        lbl = k["iso_week_label"]
        b = []

        def add(slide, text, *ids):
            b.append({"slide": slide, "text": text, "evidence_ids": list(ids)})

        wow = s("kpi.weekly", "billed_wow_pct", "%1", direction=True)
        add(2, f"Billed {s('kpi.weekly', 'billed_sdr', 'M')} in week {w} of 2025, {wow} WoW", "kpi.weekly")
        add(2, f"Budget variance {s('kpi.weekly', 'budget_variance_sdr', 'M')} "
               f"({s('kpi.weekly', 'budget_variance_pct', '%1')})", "kpi.weekly")
        if by == "billed_wow_change_sdr":
            add(2, f"Billing drivers: {', '.join(drivers)}; {c1} billed "
                   f"{s('kpi.category', 'billed_wow_change_sdr', 'M', c1, direction=True)} WoW", "kpi.category")
        else:
            add(2, f"Budget drivers in week one: {', '.join(drivers)}; {c1} budget variance "
                   f"{s('kpi.category', 'budget_variance_sdr', 'M', c1)}", "kpi.category")
        add(2, f"AR {s('kpi.weekly', 'ar_sdr', 'M')}; DSO {s('kpi.weekly', 'dso_days')}", "kpi.weekly")
        add(2, f"{s('audit.week', 'invoices_checked')} invoices checked, {s('audit.week', 'invoices_flagged')} "
               "flagged", "audit.week")
        add(3, f"Collected {s('kpi.weekly', 'collected_sdr', 'M')}, "
               f"{s('kpi.weekly', 'collected_wow_pct', '%1', direction=True)} WoW", "kpi.weekly")
        add(3, f"Overdue {s('kpi.weekly', 'overdue_sdr', 'M')}", "kpi.weekly")
        add(4, f"In {lbl} billed {s('kpi.trend', 'billed_sdr', 'M', lbl)} against a budget of "
               f"{s('kpi.trend', 'budget_sdr', 'M', lbl)}", "kpi.trend")
        add(4, f"{c1} billed {s('kpi.category', 'billed_sdr', 'M', c1)}", "kpi.category")
        add(5, f"{c1} billed {s('kpi.category', 'billed_sdr', 'M', c1)}, budget "
               f"{s('kpi.category', 'budget_sdr', 'M', c1)}", "kpi.category")
        add(6, f"DSO {s('kpi.weekly', 'dso_days')}, {s('kpi.weekly', 'dso_wow_days', direction=True)} WoW",
            "kpi.weekly")
        od = ev["kpi.overdue"]["rows"]
        if od:
            inv = od[0]["invoice_number"]
            add(6, f"Largest overdue {inv}: {s('kpi.overdue', 'amount_sdr', None, inv)}, "
                   f"{s('kpi.overdue', 'days_past_due', None, inv)} past due", "kpi.overdue")
        else:
            add(6, "No overdue invoice this week", "kpi.overdue")
        add(7, f"Top-10 share {s('kpi.weekly', 'top10_share_13w_pct', '%1')}", "kpi.weekly")
        cu = ev["kpi.customers"]["rows"][0]["customer_name"]
        add(7, f"{cu} billed {s('kpi.customers', 'billed_13w_sdr', 'M', cu)} over 13 weeks, a share of "
               f"{s('kpi.customers', 'share_13w_pct', '%1', cu)}", "kpi.customers")
        for f in aud["rows"][:MAX_FINDINGS]:
            key = f"{f['invoice_number']}/{f['check_code']}"
            add(8, f"{f['invoice_number']} ({f['check_code']}): {s('audit.week', 'difference_sdr', None, key)} "
                   "against the expected amount", "audit.week")
        if not aud["rows"]:
            add(8, f"{s('audit.week', 'invoices_checked')} invoices checked, none flagged", "audit.week")
        add(9, "External context unavailable for this week")
        titles = {1: f"Billing, receivables and invoice checks of week {w}", 2: "What changed this week",
                  3: f"Billed {s('kpi.weekly', 'billed_sdr', 'M')} in week {w}", 4: f"{c1} moved revenue most",
                  5: "Revenue mix by vessel category", 6: "Receivables and DSO", 7: "Customer concentration",
                  8: "Invoice exceptions", 9: "Context", 10: "Sources and data freshness"}
        return {"title": f"NileGate Weekly Finance Pack — {lbl} — {LABEL}",
                "slide_titles": [{"slide": i, "title": t} for i, t in titles.items()], "bullets": b}


def slot_draft(week: int, evidence: dict) -> dict:
    return _Draft(week, evidence).draft()
