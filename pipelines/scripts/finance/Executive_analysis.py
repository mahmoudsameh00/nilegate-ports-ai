"""Executive analysis 2025 — the numbers of the executive financial-intelligence deck, from the `finance` views.

Plan:    docs/analysis/financial_intelligence/implementation_roadmap.md Phase A (owner approval 2026-10-31, R0–R5);
         findings F1–F13 in docs/analysis/financial_intelligence/advanced_analytics_findings.md.
Run:     uv run python tools/run.py pipelines/scripts/finance/Executive_analysis.py  (ports-postgres up)

Reads:   PostgreSQL read-only (PG_RO_USER): finance.fact_invoice, fact_payment, fact_ar_snapshot, kpi_weekly,
         kpi_weekly_category, kpi_customer_13w, invoice_audit, dim_customer; public.vessels (category, condition).
Writes:  Data/processed/finance/executive_2025/numbers.json (every number a slide may show),
         weekly.csv, customers.csv, categories.csv, ar90_by_customer.csv, cohorts.csv, aging_w52_by_customer.csv,
         payments_asof.csv (the chart series).
Re-run:  safe (read-only on the database; the outputs are rewritten with the same content).

As-of rule: receivables statements are as of 2025-12-28 (Sunday of report week 52). A payment dated later is unknown
at that date and is never used for an as-of figure (fact_invoice.paid_date runs to 2026-03-31).

Phases
1. Inputs: the views, row counts against a reviewed snapshot.
2. Reconciliation: as-of AR, billing, DSO recomputed from invoices = kpi_weekly; no leakage.
3. Revenue and budget (F1–F3): trend and noise, rolling 13 weeks with a noise band, price-volume split of the gap.
4. Customers and credit (F4–F6, F12): risk table, rating and segment shares, size vs lateness, Pareto.
5. Receivables (F7–F11): 90+ build-up and owner, DSO split (M12), collection scenario, cohorts, billing → cash lag.
6. Billing integrity (F13): the live audit findings.
7. Save, reload, re-validate.
Final Checkpoint: the headline numbers against the reviewed snapshot.
"""
# %% Setup
import datetime as dt
import json
import math
import os
import sys
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg
from scipy import stats

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())
sys.path.insert(0, str(ROOT))
from pipelines.lib.common import load_env  # noqa: E402

load_env(ROOT)
OUT = ROOT / "Data" / "processed" / "finance" / "executive_2025"
ASOF = pd.Timestamp("2025-12-28")               # Sunday of report week 52
WARMUP_LAST = 13                                 # weeks 1–13: receivables still building up (P2-2)
ROLL = 13                                        # rolling window, weeks (as M7 / M8)
LATE_RISK_DAYS = 10                              # "late payer" threshold for the risk quadrant (mean days after due)
SCENARIO_TOPS = (3, 5, 10)


def pg():
    e = os.environ
    return psycopg.connect(host=e["PGHOST"], port=e["PGPORT"], dbname=e["PGDATABASE"], user=e["PG_RO_USER"],
                           password=e["PG_RO_PASSWORD"], options="-c default_transaction_read_only=on",
                           connect_timeout=5)


def q(conn, sql: str, params=None) -> pd.DataFrame:
    cur = conn.execute(sql, params)
    df = pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])
    for c in df.columns:
        sample = df[c].dropna()
        if len(sample) and isinstance(sample.iloc[0], Decimal):
            df[c] = df[c].astype(float)
        elif len(sample) and isinstance(sample.iloc[0], dt.date):
            df[c] = pd.to_datetime(df[c])
    return df


def r(x, nd=4):
    """A plain JSON number (None for NaN). 4 decimals by default: the deck rounds once for display — storing 2 and
    rounding again on the slide turned 27.2502 % into 27.25 → "27.2 %" (review 2026-10-31: double rounding)."""
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), nd)


N: dict = {"meta": {"as_of": ASOF.date().isoformat(), "period": "2025 ISO weeks 1-52", "unit": "SDR",
                    "source": "schema finance (read-only)", "data": "synthetic company data"}}


# %% Phase 1 — Inputs
with pg() as conn:
    fi = q(conn, "SELECT f.*, c.customer_name, c.segment, c.credit_rating FROM finance.fact_invoice f "
                 "JOIN finance.dim_customer c USING (customer_id)")
    kw = q(conn, "SELECT * FROM finance.kpi_weekly ORDER BY report_week")
    kc = q(conn, "SELECT * FROM finance.kpi_weekly_category ORDER BY report_week, vessel_category")
    snap = q(conn, "SELECT s.*, c.customer_name, c.credit_rating, c.segment FROM finance.fact_ar_snapshot s "
                   "JOIN finance.dim_customer c USING (customer_id)")
    c13 = q(conn, "SELECT report_week, customer_id, share_13w_pct, rank_13w FROM finance.kpi_customer_13w")
    audit = q(conn, "SELECT * FROM finance.invoice_audit ORDER BY report_week")
    vessels = q(conn, "SELECT vessel_type AS vessel_category, count(*) AS vessels FROM vessels GROUP BY 1")

counts = {"fact_invoice": len(fi), "kpi_weekly": len(kw), "kpi_weekly_category": len(kc), "fact_ar_snapshot": len(snap),
          "kpi_customer_13w": len(c13), "invoice_audit": len(audit), "vessel_categories": len(vessels),
          "vessels": int(vessels.vessels.sum())}
REVIEWED_COUNTS = {"fact_invoice": 1000, "kpi_weekly": 52, "kpi_weekly_category": 676, "fact_ar_snapshot": 7033,
                   "kpi_customer_13w": 2080, "invoice_audit": 3, "vessel_categories": 13, "vessels": 500}
print("rows:", counts)
assert counts == REVIEWED_COUNTS, {k: (v, REVIEWED_COUNTS.get(k)) for k, v in counts.items() if v != REVIEWED_COUNTS.get(k)}
assert kw.report_week.tolist() == list(range(1, 53))
print("✅ Phase 1 validation passed: every input view has its reviewed row count")


# %% Phase 2 — Reconciliation and the as-of rule
# The invoices of the report weeks (996; the 4 of ISO 2026-W01 are outside), with the payment state known at ASOF.
y = fi[fi.invoice_report_week.notna()].copy()
y["paid_asof"] = y.paid_date.notna() & (y.paid_date <= ASOF)
y["open_asof"] = ~y.paid_asof
y["dpd_asof"] = np.where(y.open_asof, (ASOF - y.due_date).dt.days, np.nan)            # days past due at ASOF
y["late_days"] = np.where(y.paid_asof, (y.paid_date - y.due_date).dt.days, np.nan)     # paid − due (≤ 0 = on time)
w52 = kw.iloc[-1]
ar_asof = y.loc[y.open_asof, "amount_sdr"].sum()
od_asof = y.loc[y.dpd_asof >= 1, "amount_sdr"].sum()
dso_recomputed = ar_asof / w52.dso_window_billed_sdr * w52.dso_window_days
checks = {"billed": (y.amount_sdr.sum(), kw.billed_sdr.sum()), "ar_w52": (ar_asof, w52.ar_sdr),
          "overdue_w52": (od_asof, w52.overdue_sdr), "dso_w52": (round(dso_recomputed, 1), w52.dso_days),
          "invoices": (len(y), kw.invoices_billed.sum())}
for k, (a, b) in checks.items():
    assert abs(a - b) <= 0.011, (k, a, b)
assert not (y.paid_asof & (y.paid_date > ASOF)).any()                 # leakage guard
late_after_asof = int((y.paid_date > ASOF).sum())
print({k: r(a, 2) for k, (a, b) in checks.items()}, "| payments after the as-of date ignored:", late_after_asof)
N["meta"].update({"payments_after_asof": late_after_asof,
                  "payments_horizon": fi.paid_date.max().date().isoformat()})
N["year"] = {"billed": r(kw.billed_sdr.sum()), "invoices": int(kw.invoices_billed.sum()),
             "budget": r(kw.budget_sdr.sum()), "variance": r(kw.billed_sdr.sum() - kw.budget_sdr.sum()),
             "variance_pct": r((kw.billed_sdr.sum() / kw.budget_sdr.sum() - 1) * 100),
             "collected": r(kw.collected_sdr.sum()), "ar_w52": r(w52.ar_sdr), "overdue_w52": r(w52.overdue_sdr),
             "overdue_share_w52_pct": r(w52.overdue_sdr / w52.ar_sdr * 100), "ar90_w52": r(w52.aging_90_plus_sdr),
             "dso_w52": r(w52.dso_days, 1), "weekly_billed_mean": r(kw.billed_sdr.mean())}
print("✅ Phase 2 validation passed: invoices as of 2025-12-28 = kpi_weekly (billing, AR, overdue, DSO); no leakage")


# %% Phase 3 — Revenue and budget (F1–F3)
# F1: is there a trend, or noise? A linear trend, lag-1 autocorrelation, Poisson dispersion of the invoice count.
wk = kw.report_week
trend = stats.linregress(wk, kw.billed_sdr)
disp = kw.invoices_billed.var() / kw.invoices_billed.mean()
z = (kw.billed_sdr - kw.billed_sdr.mean()) / kw.billed_sdr.std()
quarter = (wk - 1) // 13 + 1
wow_abs = kw.billed_wow_pct.abs()
N["F1"] = {"trend_slope_per_week": r(trend.slope), "trend_p": r(trend.pvalue, 3),
           "lag1_autocorr": r(kw.billed_sdr.autocorr(1)), "count_dispersion": r(disp),
           "quarters_billed": [r(v) for v in kw.groupby(quarter).billed_sdr.sum()],
           "quarters_budget": [r(v) for v in kw.groupby(quarter).budget_sdr.sum()],
           "weeks_abs_z_gt2": kw.loc[z.abs() > 2, "report_week"].tolist(),
           "wow_abs_median_pct": r(wow_abs.median()), "weeks_wow_gt20_pct": r((wow_abs > 20).sum() / wow_abs.notna().sum() * 100),
           "category_weeks_zero_pct": r((kc.invoices_billed == 0).mean() * 100),
           "weekly_sd": r(kw.billed_sdr.std())}
# F3: rolling 13 weeks; the noise band of a 13-week sum if weeks are independent (F1): 13·mean ± 2·σ·√13
kw["billed_13w"] = kw.billed_sdr.rolling(ROLL).sum()
kw["budget_13w"] = kw.budget_sdr.rolling(ROLL).sum()
kw["var_13w_pct"] = (kw.billed_13w / kw.budget_13w - 1) * 100
band_mid, band_half = ROLL * kw.billed_sdr.mean(), 2 * kw.billed_sdr.std() * math.sqrt(ROLL)
kw["band_lo"], kw["band_hi"] = band_mid - band_half, band_mid + band_half
inside = kw.billed_13w.dropna().between(band_mid - band_half, band_mid + band_half).mean()
N["F3"] = {"var_13w_pct_at": {str(w): r(kw.var_13w_pct.iloc[w - 1], 1) for w in (13, 26, 39, 52)},
           "var_13w_min": r(kw.var_13w_pct.min(), 1), "var_13w_max": r(kw.var_13w_pct.max(), 1),
           "corr_weekly_variance_billed": r(kw.budget_variance_sdr.corr(kw.billed_sdr), 3),
           "band_mid": r(band_mid), "band_half": r(band_half), "rolling_inside_band_pct": r(inside * 100)}
# F2: price-volume split per category. Plan volume = vessels × 2 transits (Finance_generator R6); plan ticket = budget
# ÷ plan volume. Volume effect = (n − plan n) × plan ticket; ticket / mix effect = (ticket − plan ticket) × n.
bud = kc.groupby("vessel_category").budget_sdr.sum().rename("budget")
cat = (y.groupby("vessel_category").agg(n=("amount_sdr", "size"), billed=("amount_sdr", "sum"),
                                        n_ballast=("priced_condition", lambda s: int((s == "Ballast").sum())))
       .join(bud).join(vessels.set_index("vessel_category")).reset_index())
cat["plan_n"] = cat.vessels * 2
cat["plan_ticket"], cat["ticket"] = cat.budget / cat.plan_n, cat.billed / cat.n
cat["variance"] = cat.billed - cat.budget
cat["variance_pct"] = cat.variance / cat.budget * 100
cat["volume_effect"] = (cat.n - cat.plan_n) * cat.plan_ticket
cat["ticket_effect"] = (cat.ticket - cat.plan_ticket) * cat.n
# ballast re-valued at the category's average laden ticket (an estimate: tonnage differs between invoices)
tickets = y.groupby(["vessel_category", "priced_condition"]).amount_sdr.mean().unstack()
cat["ballast_effect"] = -cat.vessel_category.map(
    lambda c: 0.0 if pd.isna(tickets.loc[c].get("Ballast")) else
    (cat.set_index("vessel_category").n_ballast[c] * (tickets.loc[c, "Laden"] - tickets.loc[c, "Ballast"])))
# the plan volume is binomial (1,000 draws, p = vessels / 500): a volume gap beyond 2 σ would be more than noise
cat["volume_z"] = (cat.n - cat.plan_n) / np.sqrt(cat.plan_n * (1 - cat.vessels / 500))
cat = cat.sort_values("variance").reset_index(drop=True)
assert abs(cat.volume_effect.sum() + cat.ticket_effect.sum() - cat.variance.sum()) < 0.05
assert abs(cat.variance.sum() - (kw.billed_sdr.sum() - kw.budget_sdr.sum())) < 0.05
gap = cat.variance.sum()
N["F2"] = {"gap": r(gap), "volume_effect": r(cat.volume_effect.sum()), "ticket_effect": r(cat.ticket_effect.sum()),
           "ballast_effect": r(cat.ballast_effect.sum()), "ballast_share_of_gap_pct": r(cat.ballast_effect.sum() / gap * 100),
           "other_ticket_effect": r(cat.ticket_effect.sum() - cat.ballast_effect.sum()),
           "invoices": len(y), "plan_invoices": int(cat.plan_n.sum()), "ballast_invoices": int(cat.n_ballast.sum()),
           "ballast_share_pct": r(cat.n_ballast.sum() / len(y) * 100),
           "max_abs_volume_z": r(cat.volume_z.abs().max()),
           "categories": [{"category": c.vessel_category, "variance": r(c.variance), "variance_pct": r(c.variance_pct, 1),
                           "volume_effect": r(c.volume_effect), "ticket_effect": r(c.ticket_effect),
                           "n": int(c.n), "plan_n": int(c.plan_n)} for c in cat.itertuples()]}
print(f"F1 slope p={trend.pvalue:.2f}, dispersion {disp:.2f}; F2 gap {gap / 1e6:.2f} M = volume "
      f"{cat.volume_effect.sum() / 1e6:+.2f} + ticket {cat.ticket_effect.sum() / 1e6:+.2f} (ballast "
      f"{cat.ballast_effect.sum() / 1e6:+.2f}); max |volume z| {cat.volume_z.abs().max():.2f}; "
      f"F3 rolling var {N['F3']['var_13w_pct_at']}")
assert trend.pvalue > 0.05 and 0.5 < disp < 1.5, "billing is no longer a trend-free Poisson-like series: review F1"
print("✅ Phase 3 validation passed: no billing trend; the gap splits exactly into volume + ticket per category")


# %% Phase 4 — Customers and credit (F4–F6, F12)
pay = y[y.paid_asof]
cu = (y.groupby(["customer_id", "customer_name", "segment", "credit_rating", "payment_terms_days"])
      .agg(invoices=("amount_sdr", "size"), revenue=("amount_sdr", "sum")).reset_index())
cu = cu.merge(y[y.open_asof].groupby("customer_id").amount_sdr.sum().rename("ar"), on="customer_id", how="left")
cu = cu.merge(y[y.dpd_asof >= 1].groupby("customer_id").amount_sdr.sum().rename("overdue"), on="customer_id", how="left")
cu = cu.merge(y[y.dpd_asof > 90].groupby("customer_id").amount_sdr.sum().rename("ar90"), on="customer_id", how="left")
cu = cu.merge(pay.groupby("customer_id").late_days.agg(late_mean="mean", paid="size",
                                                       ontime=lambda s: (s <= 0).mean() * 100),
              on="customer_id", how="left")
cu[["ar", "overdue", "ar90"]] = cu[["ar", "overdue", "ar90"]].fillna(0.0)
cu = cu.sort_values("revenue", ascending=False).reset_index(drop=True)
for c in ("revenue", "ar", "overdue"):
    cu[f"{c}_share"] = cu[c] / cu[c].sum() * 100
cu["cum_revenue_share"] = cu.revenue_share.cumsum()
cu["days_to_cash"] = cu.payment_terms_days + cu.late_mean
assert abs(cu.ar.sum() - w52.ar_sdr) < 0.05 and abs(cu.overdue.sum() - w52.overdue_sdr) < 0.05
top = cu.iloc[0]
rho = stats.spearmanr(cu.revenue, cu.late_mean, nan_policy="omit")
hi_rev, late = cu.revenue_share >= cu.revenue_share.median(), cu.late_mean >= LATE_RISK_DAYS
w13 = c13[(c13.customer_id == top.customer_id) & c13.report_week.isin([13, 26, 39, 52])].sort_values("report_week")
top_ar_share = (snap[snap.customer_id == top.customer_id].groupby("report_week").amount_sdr.sum()
                / kw.set_index("report_week").ar_sdr).loc[WARMUP_LAST + 1:].mean() * 100
N["F4"] = {"top_customer": {"id": int(top.customer_id), "name": top.customer_name, "rating": top.credit_rating,
                            "segment": top.segment, "terms": int(top.payment_terms_days),
                            "invoices": int(top.invoices), "revenue": r(top.revenue),
                            "revenue_share_pct": r(top.revenue_share), "ar_share_pct": r(top.ar_share),
                            "overdue_share_pct": r(top.overdue_share), "late_mean_days": r(top.late_mean, 1),
                            "ontime_pct": r(top.ontime, 1), "days_to_cash": r(top.days_to_cash, 0),
                            "rank1_from_week13": bool((c13[(c13.customer_id == top.customer_id)
                                                           & (c13.report_week >= 13)].rank_13w == 1).all()),
                            "share_13w_at": {str(int(a)): r(b) for a, b in zip(w13.report_week, w13.share_13w_pct)},
                            "ar_share_mean_w14_52_pct": r(top_ar_share, 1)},
           "high_revenue_late_payers": [{"name": c.customer_name, "rating": c.credit_rating,
                                         "revenue_share_pct": r(c.revenue_share, 1), "ar_share_pct": r(c.ar_share, 1),
                                         "overdue_share_pct": r(c.overdue_share, 1), "late_mean_days": r(c.late_mean, 1)}
                                        for c in cu[hi_rev & late].itertuples()]}
N["F6"] = {"spearman_rho": r(rho.statistic, 3), "p": r(rho.pvalue, 2),
           "quadrants": {"large_late": int((hi_rev & late).sum()), "large_prompt": int((hi_rev & ~late).sum()),
                         "small_late": int((~hi_rev & late).sum()), "small_prompt": int((~hi_rev & ~late).sum())}}


def lens(col: str) -> list[dict]:
    g = cu.groupby(col)
    t = pd.DataFrame({"customers": g.size(), "revenue_share": g.revenue_share.sum(), "ar_share": g.ar_share.sum(),
                      "overdue_share": g.overdue_share.sum(), "overdue": g.overdue.sum()})
    lp = pay.groupby(col).late_days
    t["late_mean"], t["late_median"], t["ontime_pct"] = lp.mean(), lp.median(), lp.apply(lambda s: (s <= 0).mean() * 100)
    return [{col: k, **{c: r(v, 1) if c != "overdue" else r(v) for c, v in row.items()}} for k, row in t.iterrows()]


kr = stats.kruskal(*[g.late_days for _, g in pay.groupby("credit_rating")])
N["F5"] = {"by_rating": lens("credit_rating"), "by_segment": lens("segment"), "kruskal_p": float(f"{kr.pvalue:.2e}"),
           "payments_asof": len(pay),
           # the deck's appendix text (review 2026-10-31: these were hand-typed on the slide)
           "b_late_max": int(pay[pay.credit_rating == "B"].late_days.max()),
           "c_late_over_90": int((pay[pay.credit_rating == "C"].late_days > 90).sum())}
hhi = (cu.revenue_share ** 2).sum()
post = kw[kw.report_week > WARMUP_LAST]
N["F12"] = {"top_n_share_pct": {str(n): r(cu.revenue_share.head(n).sum(), 1) for n in (1, 5, 10, 20)},
            "customers_for_80pct": int((cu.cum_revenue_share < 80).sum() + 1), "hhi": r(hhi, 0),
            "top10_13w_min": r(post.top10_share_13w_pct.min()), "top10_13w_max": r(post.top10_share_13w_pct.max()),
            "trend_note": "overlapping 13-week windows: a regression p-value is not valid, no trend is claimed"}
by_rating = {d["credit_rating"]: d for d in N["F5"]["by_rating"]}
print(f"F4 {top.customer_name}: revenue {top.revenue_share:.1f} %, AR {top.ar_share:.1f} %, overdue "
      f"{top.overdue_share:.1f} %, late {top.late_mean:.1f} d; F5 overdue share A/B/C "
      f"{[by_rating[k]['overdue_share'] for k in 'ABC']}; F6 rho {rho.statistic:.2f}; HHI {hhi:.0f}")
assert by_rating["C"]["overdue_share"] > by_rating["C"]["revenue_share"] * 2, "the rating finding changed: review F5"
print("✅ Phase 4 validation passed: customer AR and overdue add up to kpi_weekly week 52")


# %% Phase 5 — Receivables (F7–F11)
# F7: 90+ by week and customer, its trend over weeks 14–52 and who holds it.
a90 = snap[snap.aging_bucket == "90+"].groupby(["report_week", "customer_id", "customer_name"]).amount_sdr.sum().reset_index()
a90w = a90.groupby("report_week").amount_sdr.sum()
t90 = stats.linregress(post.report_week, post.aging_90_plus_sdr)
holder = a90.groupby(["customer_id", "customer_name"]).amount_sdr.sum().idxmax()
hshare = (a90[a90.customer_id == holder[0]].set_index("report_week").amount_sdr / a90w).reindex(a90w.index).fillna(0) * 100
hinv = fi[fi.customer_id == holder[0]]
holder_first = int(hshare[hshare > 0].index.min())
hold_from = int(hshare[hshare == 100].index.min())          # from here on the holder dominates 90+
hs = hshare.loc[hold_from:]
# the other 90+ customers: their invoices pass through 90+ and are paid later (or are not)
others = (snap[(snap.aging_bucket == "90+") & (snap.customer_id != holder[0])]
          .groupby(["customer_id", "customer_name", "invoice_number"]).report_week.agg(["min", "max"]).reset_index()
          .merge(fi[["invoice_number", "paid_date", "amount_sdr"]], on="invoice_number"))
others_trend = {c: r(stats.linregress(post.report_week, post[c]).pvalue, 3)
                for c in ("ar_sdr", "overdue_sdr", "dso_days")}
N["F7"] = {"first_week": int(a90w.index.min()), "slope_per_week": r(t90.slope), "p": float(f"{t90.pvalue:.1e}"),
           "w52": r(w52.aging_90_plus_sdr), "share_of_ar_w52_pct": r(w52.aging_90_plus_sdr / w52.ar_sdr * 100, 1),
           "other_trend_p": others_trend,
           "holder": {"id": int(holder[0]), "name": holder[1],
                      "rating": cu.set_index("customer_id").credit_rating[holder[0]],
                      "revenue_share_pct": r(cu.set_index("customer_id").revenue_share[holder[0]], 1),
                      "first_week_in_90": holder_first, "dominant_from_week": hold_from,
                      "share_of_90_min_from_pct": r(hs.min(), 0), "weeks_at_100pct": int((hs == 100).sum()),
                      "weeks_from": len(hs), "share_of_90_w52_pct": r(hshare.loc[52], 0),
                      "billed_2025": r(hinv[hinv.invoice_report_week.notna()].amount_sdr.sum()),
                      "invoices_2025": int(hinv.invoice_report_week.notna().sum()),
                      "unpaid_at_horizon": int(hinv.paid_date.isna().sum()),
                      "unpaid_at_horizon_sdr": r(hinv.loc[hinv.paid_date.isna(), "amount_sdr"].sum())},
           "other_90_invoices": [{"customer": o.customer_name, "invoice": o.invoice_number, "weeks": [int(o.min), int(o.max)],
                                  "amount": r(o.amount_sdr),
                                  "paid_date": None if pd.isna(o.paid_date) else o.paid_date.date().isoformat()}
                                 for o in others.itertuples()],
           "unpaid_at_horizon_all": int(fi.paid_date.isna().sum()),
           "unpaid_at_horizon_all_sdr": r(fi.loc[fi.paid_date.isna(), "amount_sdr"].sum())}
# F8 (M12): best-possible DSO = current AR ÷ window billing × window days; delinquency DSO = DSO − best-possible
kw["dso_best"] = kw.aging_current_sdr / kw.dso_window_billed_sdr * kw.dso_window_days
kw["dso_delinquency"] = kw.dso_days - kw.dso_best
post = kw[kw.report_week > WARMUP_LAST]
d = np.log(post[["dso_days", "ar_sdr", "dso_window_billed_sdr"]]).diff().dropna()
N["F8"] = {"dso_w52": r(w52.dso_days, 1), "best_w52": r(kw.dso_best.iloc[-1], 1),
           "delinquency_w52": r(kw.dso_delinquency.iloc[-1], 1),
           "dso_min_w14_52": r(post.dso_days.min(), 1), "dso_max_w14_52": r(post.dso_days.max(), 1),
           "best_mean_w14_52": r(post.dso_best.mean(), 1), "delinquency_mean_w14_52": r(post.dso_delinquency.mean(), 1),
           "trend_p": {c: r(stats.linregress(post.report_week, post[c]).pvalue, 2)
                       for c in ("dso_days", "dso_best", "dso_delinquency")},
           "dso_move_share_from_ar": r(np.cov(d.dso_days, d.ar_sdr)[0, 1] / d.dso_days.var(), 2),
           "corr_dso_ar": r(post.dso_days.corr(post.ar_sdr)),
           "corr_dso_window_billing": r(post.dso_days.corr(post.dso_window_billed_sdr))}
# F9: arithmetic scenario at week 52 — remove the overdue AR of the N largest overdue customers
od_rank = cu.sort_values("overdue", ascending=False)
scen = [{"label": "current", "released": 0.0, "dso": r(w52.dso_days, 1)}]
for n in (*SCENARIO_TOPS, len(cu)):
    rel = od_rank.overdue.head(n).sum()
    scen.append({"label": f"top{n}" if n < len(cu) else "all", "released": r(rel),
                 "dso": r((w52.ar_sdr - rel) / w52.dso_window_billed_sdr * w52.dso_window_days, 1)})
N["F9"] = {"scenarios": scen, "top5_overdue_share_pct": r(od_rank.overdue_share.head(5).sum(), 1),
           "top5_names": od_rank.customer_name.head(5).tolist(), "note": "arithmetic, not a forecast"}
# F10: invoice-month cohorts (payments known by ASOF); a cohort is mature only if every due + 30 days ≤ ASOF
y["month"] = y.invoice_date.dt.month
coh = y.groupby("month").apply(lambda g: pd.Series({
    "invoices": len(g), "ontime_pct": (g.paid_asof & (g.paid_date <= g.due_date)).mean() * 100,
    "within30_pct": (g.paid_asof & (g.paid_date <= g.due_date + pd.Timedelta(days=30))).mean() * 100,
    "open_asof_pct": g.open_asof.mean() * 100,
    "mature": bool((g.due_date + pd.Timedelta(days=30)).max() <= ASOF)}), include_groups=False).reset_index()
mature = coh[coh.mature]
N["F10"] = {"mature_months": mature.month.tolist(),
            "ontime_range": [r(mature.ontime_pct.min(), 1), r(mature.ontime_pct.max(), 1)],
            "within30_range": [r(mature.within30_pct.min(), 1), r(mature.within30_pct.max(), 1)],
            "early_paid_pct": r((pay.late_days < 0).mean() * 100, 1)}
# F11: billing → collection lag and the warm-up artefact
bc, cc = kw.billed_sdr - kw.billed_sdr.mean(), kw.collected_sdr - kw.collected_sdr.mean()
xc = {lag: bc.corr(cc.shift(-lag)) for lag in range(0, 13)}
peak = max(xc, key=xc.get)
N["F11"] = {"xcorr_peak_lag_weeks": peak, "xcorr_peak": r(xc[peak]),
            "collected_to_billed_by_quarter": [r(v) for v in kw.groupby(quarter).collected_sdr.sum()
                                               / kw.groupby(quarter).billed_sdr.sum()]}
print(f"F7 90+ from week {N['F7']['first_week']}, {t90.slope:,.0f}/week, holder {holder[1]} "
      f"from week {hold_from}: {hs.min():.0f}–100 %, 100 % in {(hs == 100).sum()} / {len(hs)} weeks; "
      f"others {len(others)} invoices, all paid later: {others.paid_date.notna().all()}; F8 DSO "
      f"{w52.dso_days} = {kw.dso_best.iloc[-1]:.1f} + "
      f"{kw.dso_delinquency.iloc[-1]:.1f}; F9 {[(s['label'], s['dso']) for s in scen]}; F10 mature months "
      f"{mature.month.min()}–{mature.month.max()}; F11 peak lag {peak}")
assert abs(kw.dso_best.iloc[-1] + kw.dso_delinquency.iloc[-1] - w52.dso_days) < 1e-9
assert scen[-1]["dso"] == r(kw.dso_best.iloc[-1], 1), "collecting all overdue must leave the best-possible DSO"
print("✅ Phase 5 validation passed: DSO = best-possible + delinquency; the all-overdue scenario lands on the floor")


# %% Phase 6 — Billing integrity (F13)
N["F13"] = {"findings": [{"week": int(a.report_week), "invoice": a.invoice_number, "category": a.vessel_category,
                          "check": a.check_code, "duplicate_of": a.duplicate_of, "amount": r(a.difference_sdr),
                          "review": a.review} for a in audit.itertuples()],
            "total": r(audit.difference_sdr.sum()),
            "share_of_billing_pct": r(audit.difference_sdr.sum() / kw.billed_sdr.sum() * 100)}
assert set(audit.review) == {"error"} and set(audit.check_code) == {"duplicate_charge"}
print(f"F13 {len(audit)} duplicate charges, {audit.difference_sdr.sum():,.2f} SDR")
print("✅ Phase 6 validation passed: the live audit holds only duplicate charges (errors)")


# %% Phase 7 — Save, reload, re-validate
OUT.mkdir(parents=True, exist_ok=True)
weekly_cols = ["report_week", "week_start", "is_warmup", "invoices_billed", "billed_sdr", "budget_sdr",
               "budget_variance_sdr", "collected_sdr", "ar_sdr", "overdue_sdr", "aging_current_sdr", "aging_1_30_sdr",
               "aging_31_60_sdr", "aging_61_90_sdr", "aging_90_plus_sdr", "dso_days", "dso_best", "dso_delinquency",
               "billed_13w", "budget_13w", "var_13w_pct", "band_lo", "band_hi", "top10_share_13w_pct"]
aging52 = (snap[snap.report_week == 52].pivot_table(index=["customer_id", "customer_name", "credit_rating"],
                                                    columns="aging_bucket", values="amount_sdr", aggfunc="sum",
                                                    fill_value=0.0).reset_index())
FILES = {"weekly.csv": kw[weekly_cols], "customers.csv": cu, "categories.csv": cat,
         "ar90_by_customer.csv": a90, "cohorts.csv": coh, "aging_w52_by_customer.csv": aging52,
         "payments_asof.csv": pay[["invoice_number", "customer_id", "credit_rating", "segment", "payment_terms_days",
                                   "late_days"]]}
for name, df in FILES.items():
    df.round(4).to_csv(OUT / name, index=False, lineterminator="\n")
(OUT / "numbers.json").write_text(json.dumps(N, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
back = json.loads((OUT / "numbers.json").read_text(encoding="utf-8"))
assert back == json.loads(json.dumps(N)), "numbers.json does not reload equal"
for name, df in FILES.items():
    rb = pd.read_csv(OUT / name)
    assert rb.shape == df.shape, (name, rb.shape, df.shape)
print("saved:", sorted(p.name for p in OUT.iterdir()))
print(f"✅ Phase 7 validation passed: numbers.json and {len(FILES)} series reload with the saved shape")


# %% Final Checkpoint
# The headline numbers of the deck, reviewed 2026-10-31 (advanced_analytics_findings.md). A change in the data or the
# views stops here before a slide shows a different number. Narrative: pipelines/checkpoints/finance/Executive_analysis.md
actual = {"billed": N["year"]["billed"], "budget": N["year"]["budget"], "ar_w52": N["year"]["ar_w52"],
          "overdue_w52": N["year"]["overdue_w52"], "ar90_w52": N["year"]["ar90_w52"], "dso_w52": N["year"]["dso_w52"],
          "gap_volume": r(N["F2"]["volume_effect"] / 1e6, 2), "gap_ticket": r(N["F2"]["ticket_effect"] / 1e6, 2),
          "top_customer": N["F4"]["top_customer"]["name"],
          "top_customer_shares": [r(N["F4"]["top_customer"][k], 1) for k in
                                  ("revenue_share_pct", "ar_share_pct", "overdue_share_pct")],
          "overdue_share_by_rating": [by_rating[k]["overdue_share"] for k in "ABC"],
          "holder_90": N["F7"]["holder"]["name"],
          "holder_90_from": [N["F7"]["holder"][k] for k in ("dominant_from_week", "share_of_90_min_from_pct",
                                                              "weeks_at_100pct", "weeks_from")],
          "dso_split_w52": [N["F8"]["best_w52"], N["F8"]["delinquency_w52"]],
          "scenario_dso": [s["dso"] for s in scen], "duplicates_total": N["F13"]["total"]}
REVIEWED = {"billed": 267892000.68, "budget": 302099899.07, "ar_w52": 40693503.44, "overdue_w52": 11089028.88,
            "ar90_w52": 1286102.15, "dso_w52": 55.0, "gap_volume": 0.45, "gap_ticket": -34.66,
            "top_customer": "Belanor Tankers", "top_customer_shares": [14.5, 21.2, 18.9],
            "overdue_share_by_rating": [8.6, 28.1, 63.3], "holder_90": "Korussa Container Lines",
            "holder_90_from": [26, 67.0, 20, 27], "dso_split_w52": [40.0, 15.0], "scenario_dso": [55.0, 48.1, 45.5, 41.8, 40.0], "duplicates_total": 336909.0}
diff = {k: (actual[k], REVIEWED[k]) for k in REVIEWED if actual[k] != REVIEWED[k]}
print("Final Checkpoint:", {k: actual[k] for k in ("billed", "ar_w52", "dso_w52", "top_customer", "holder_90")})
assert not diff, diff
print("✅ Final Checkpoint passed: the headline numbers equal the reviewed snapshot")
