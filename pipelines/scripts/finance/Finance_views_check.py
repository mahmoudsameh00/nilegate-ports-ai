"""Finance views check — schema `finance` (migration 013) against an independent pandas computation.

Plan:    docs/plans/Agents_plan.md §5 Phase 2 (owner decisions P2-1…P2-9, 2026-10-14); definitions docs/finance_metrics.md.
Run:     uv run python tools/run.py pipelines/scripts/finance/Finance_views_check.py  (after 013; ports-postgres up)

Reads:   PostgreSQL read-only (PG_RO_USER): the base tables invoices, vessels, customers, payments, budget_weekly,
         employees, roles, departments; every view of schema finance; the privilege catalog. docs/rbac_mapping.md.
Writes:  nothing.
Re-run:  safe (read-only).

Phases
1. Inputs: the base tables and the finance views.
2. Reference: every metric recomputed in pandas from the base tables, without the SQL of the views.
3. Views = reference on all 52 weeks (kpi_weekly, kpi_weekly_category, kpi_customer_13w, kpi_overdue_list) + structure.
4. Invariants: AR roll-forward, aging = AR, Σ categories = total, the ISO edge (2026-W01), warm-up weeks.
5. Hand-check weeks 5 (warm-up), 16 (quietest), 23 (peak), 49 (clean test week): the arithmetic, a reviewed snapshot.
6. RBAC (ADR-006 / ADR-034): matrix over every employee with the tool predicate; privileges of finance_bi.
Final Checkpoint.
"""
# %% Setup
import datetime as dt
import math
import os
import sys
from decimal import Decimal
from pathlib import Path

import pandas as pd
import psycopg

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())
sys.path.insert(0, str(ROOT))
from pipelines.lib.common import load_env  # noqa: E402
from pipelines.lib.retrieval import User, allowed  # noqa: E402  (the ADR-006 predicate of the tool layer)

load_env(ROOT)
WEEK1_MONDAY, HISTORY_START = dt.date(2024, 12, 30), dt.date(2025, 1, 1)
HAND_WEEKS = [5, 16, 23, 49]                       # owner decision P2-7
FINANCE_LEVEL, FINANCE_DEPT = 2, "Finance"         # docs/rbac_mapping.md: finance views = level 2 / Finance
TOL = {"sdr": 0.011, "pct": 0.011, "days": 0.11}   # one unit of the last rounded digit (half-cent float ties)


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


def week_bounds(w: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    s = pd.Timestamp(WEEK1_MONDAY + dt.timedelta(days=7 * (w - 1)))
    return s, s + pd.Timedelta(days=6)


# %% Phase 1 — Inputs
# The base tables are read with plain SELECTs (no view): the reference below never sees the SQL of the views.
with pg() as conn:
    inv = q(conn, "SELECT invoice_number, vessel_id, invoice_date, amount FROM invoices")
    ves = q(conn, "SELECT vessel_id, vessel_type, customer_id FROM vessels")
    cus = q(conn, "SELECT customer_id, payment_terms_days FROM customers")
    pay = q(conn, "SELECT invoice_number, paid_date, amount_sdr FROM payments")
    bud = q(conn, "SELECT iso_week, vessel_category, budget_sdr FROM budget_weekly WHERE budget_year = 2025")
    emp = q(conn, "SELECT e.employee_id, r.role_name, r.allowed_sensitivity_level, d.department_name FROM employees e "
                  "JOIN roles r USING (role_id) JOIN departments d USING (department_id)")
    V = {name: q(conn, f"SELECT * FROM finance.{name}") for name in
         ["dim_date", "dim_week", "dim_customer", "dim_vessel", "dim_toll_band", "fact_invoice", "fact_payment",
          "fact_ar_snapshot", "kpi_weekly", "kpi_weekly_category", "kpi_customer_13w", "kpi_overdue_list",
          "kpi_weekly_trend"]}
    views_in_db = sorted(r[0] for r in conn.execute(
        "SELECT c.relname FROM pg_class c WHERE c.relnamespace = 'finance'::regnamespace AND c.relkind IN ('v', 'm', 'r')"))
    undocumented = conn.execute(
        "SELECT count(*) FILTER (WHERE obj_description(c.oid, 'pg_class') IS NULL), "
        "       (SELECT count(*) FROM pg_attribute a JOIN pg_class t ON t.oid = a.attrelid "
        "        WHERE t.relnamespace = 'finance'::regnamespace AND a.attnum > 0 AND NOT a.attisdropped "
        "          AND col_description(t.oid, a.attnum) IS NULL) "
        "FROM pg_class c WHERE c.relnamespace = 'finance'::regnamespace AND c.relkind = 'v'").fetchone()
    privileges = q(conn, """
        SELECT c.relnamespace::regnamespace::text AS schema, c.relname,
               has_table_privilege('finance_bi', c.oid, 'SELECT') AS bi_select,
               has_table_privilege('finance_bi', c.oid, 'INSERT,UPDATE,DELETE,TRUNCATE') AS bi_write,
               has_table_privilege('ports_readonly', c.oid, 'SELECT') AS ro_select
        FROM pg_class c
        WHERE c.relnamespace IN ('finance'::regnamespace, 'public'::regnamespace, 'finance_test'::regnamespace)
          AND c.relkind IN ('r', 'v')
          AND c.relname NOT IN ('spatial_ref_sys', 'geometry_columns', 'geography_columns')""")  # PostGIS: SELECT to PUBLIC

assert len(inv) == 1000 and len(ves) == 500 and len(cus) == 40 and len(pay) == 994 and len(bud) == 676, "base tables"
print(f"inputs: {len(inv)} invoices, {len(pay)} payments, {len(cus)} customers, {len(bud)} budget rows, "
      f"{len(emp)} employees; views: " + ", ".join(f"{k} {len(v)}" for k, v in V.items()))
print("✅ Phase 1 validation passed: base tables and 13 finance views read")


# %% Phase 2 — Reference (pandas, from the base tables)
# Same definitions as docs/finance_metrics.md, written a second time in another language: billed by invoice date,
# collected by paid date, AR = issued by Sunday and unpaid by Sunday, age = Sunday − (invoice date + terms),
# DSO = AR ÷ billed in the window × window days (window = 91 days, from 2025-01-01 in the warm-up weeks).
f = (inv.merge(ves, on="vessel_id").merge(cus, on="customer_id")
        .merge(pay[["invoice_number", "paid_date"]], on="invoice_number", how="left")
        .rename(columns={"amount": "amount_sdr", "vessel_type": "vessel_category"}))
f["due_date"] = f.invoice_date + pd.to_timedelta(f.payment_terms_days, unit="D")
assert len(f) == 1000 and f.customer_id.notna().all()

BUCKETS = [("current", -10**6, 0), ("1-30", 1, 30), ("31-60", 31, 60), ("61-90", 61, 90), ("90+", 91, 10**6)]
wk_rows, cat_rows, cust_rows, od_rows = [], [], [], []
for w in range(1, 53):
    s, e = week_bounds(w)
    in_week = f.invoice_date.between(s, e)
    paid_in_week = pay.paid_date.between(s, e)
    open_ = f[(f.invoice_date <= e) & (f.paid_date.isna() | (f.paid_date > e))].copy()
    open_["dpd"] = (e - open_.due_date).dt.days
    ws = max(e - pd.Timedelta(days=90), pd.Timestamp(HISTORY_START))
    n_days = (e - ws).days + 1
    window_billed = f.loc[f.invoice_date.between(ws, e), "amount_sdr"].sum()
    t13 = f[f.invoice_date.between(e - pd.Timedelta(days=90), e)].groupby("customer_id").amount_sdr.sum()
    row = dict(report_week=w, is_warmup=n_days < 91, invoices_billed=int(in_week.sum()),
               billed_sdr=f.loc[in_week, "amount_sdr"].sum(), payments_received=int(paid_in_week.sum()),
               collected_sdr=pay.loc[paid_in_week, "amount_sdr"].sum(), ar_invoices=len(open_),
               ar_sdr=open_.amount_sdr.sum(), overdue_invoices=int((open_.dpd > 0).sum()),
               overdue_sdr=open_.loc[open_.dpd > 0, "amount_sdr"].sum(), dso_window_days=n_days,
               dso_window_billed_sdr=window_billed, budget_sdr=bud.loc[bud.iso_week == w, "budget_sdr"].sum(),
               top10_share_13w_pct=100 * t13.nlargest(10).sum() / t13.sum())
    for name, lo, hi in BUCKETS:
        key = {"current": "aging_current_sdr", "90+": "aging_90_plus_sdr"}.get(name, f"aging_{name.replace('-', '_')}_sdr")
        row[key] = open_.loc[open_.dpd.between(lo, hi), "amount_sdr"].sum()
    row["dso_days"] = row["ar_sdr"] / window_billed * n_days
    wk_rows.append(row)
    for cat, b in bud.loc[bud.iso_week == w, ["vessel_category", "budget_sdr"]].itertuples(index=False):
        m = in_week & (f.vessel_category == cat)
        cat_rows.append(dict(report_week=w, vessel_category=cat, invoices_billed=int(m.sum()),
                             billed_sdr=f.loc[m, "amount_sdr"].sum(), budget_sdr=b))
    billed_week = f[in_week].groupby("customer_id").amount_sdr.sum()
    ar_c = open_.groupby("customer_id").amount_sdr.sum()
    od_c = open_[open_.dpd > 0].groupby("customer_id").amount_sdr.sum()
    c13 = pd.DataFrame({"customer_id": cus.customer_id})
    c13["billed_13w_sdr"] = c13.customer_id.map(t13).fillna(0.0)
    c13 = c13.sort_values(["billed_13w_sdr", "customer_id"], ascending=[False, True])
    c13["rank_13w"] = range(1, len(c13) + 1)
    for r in c13.itertuples(index=False):
        cust_rows.append(dict(report_week=w, customer_id=r.customer_id, billed_week_sdr=billed_week.get(r.customer_id, 0.0),
                              billed_13w_sdr=r.billed_13w_sdr, share_13w_pct=100 * r.billed_13w_sdr / t13.sum(),
                              rank_13w=r.rank_13w, is_top10=r.rank_13w <= 10 and r.billed_13w_sdr > 0,
                              ar_sdr=ar_c.get(r.customer_id, 0.0), overdue_sdr=od_c.get(r.customer_id, 0.0)))
    for r in open_[open_.dpd > 0].itertuples(index=False):
        od_rows.append(dict(report_week=w, invoice_number=r.invoice_number, amount_sdr=r.amount_sdr,
                            days_past_due=r.dpd))

ref_wk = pd.DataFrame(wk_rows)
ref_wk["budget_variance_sdr"] = ref_wk.billed_sdr - ref_wk.budget_sdr
ref_wk["budget_variance_pct"] = 100 * ref_wk.budget_variance_sdr / ref_wk.budget_sdr
for c in ["billed", "collected", "ar", "overdue"]:
    prev = ref_wk[f"{c}_sdr"].shift(1)
    ref_wk[f"{c}_wow_pct"] = (100 * (ref_wk[f"{c}_sdr"] - prev) / prev.where(prev != 0))
ref_wk["dso_wow_days"] = ref_wk.dso_days - ref_wk.dso_days.shift(1)
ref_cat = pd.DataFrame(cat_rows).sort_values(["vessel_category", "report_week"])
ref_cat["budget_variance_sdr"] = ref_cat.billed_sdr - ref_cat.budget_sdr
ref_cat["budget_variance_pct"] = 100 * ref_cat.budget_variance_sdr / ref_cat.budget_sdr.where(ref_cat.budget_sdr != 0)
ref_cat["billed_prev_sdr"] = ref_cat.groupby("vessel_category").billed_sdr.shift(1)
ref_cat["billed_wow_change_sdr"] = ref_cat.billed_sdr - ref_cat.billed_prev_sdr
ref_cat["billed_wow_pct"] = 100 * ref_cat.billed_wow_change_sdr / ref_cat.billed_prev_sdr.where(ref_cat.billed_prev_sdr != 0)
ref_cust = pd.DataFrame(cust_rows).sort_values(["customer_id", "report_week"])
ref_cust["rank_13w_prev"] = ref_cust.groupby("customer_id").rank_13w.shift(1)
ref_od = pd.DataFrame(od_rows)

assert len(ref_wk) == 52 and len(ref_cat) == 676 and len(ref_cust) == 52 * 40, "reference shape"
print(f"reference: {len(ref_wk)} weeks, {len(ref_cat)} week × category, {len(ref_cust)} week × customer, "
      f"{len(ref_od)} overdue invoice-weeks")
print("✅ Phase 2 validation passed: reference computed from the base tables")


# %% Phase 3 — Views = reference (all 52 weeks)
# Every numeric column is compared within one unit of its last rounded digit; booleans and counts exactly; NULL
# (week 1 WoW, a zero denominator) must be NULL on both sides.
def tol_of(col: str) -> float:
    return TOL["pct"] if col.endswith("_pct") else TOL["days"] if col.endswith("_days") and "window" not in col else TOL["sdr"]


def compare(view: pd.DataFrame, ref: pd.DataFrame, keys: list[str], name: str) -> int:
    m = view.merge(ref, on=keys, how="outer", suffixes=("_v", "_r"), indicator=True)
    assert (m._merge == "both").all(), f"{name}: rows differ: {m._merge.value_counts().to_dict()}"
    cols = [c for c in ref.columns if c not in keys]
    for c in cols:
        a, b = m[f"{c}_v"], m[f"{c}_r"]
        assert (a.isna() == b.isna()).all(), f"{name}.{c}: NULL mismatch in {int((a.isna() != b.isna()).sum())} rows"
        a, b = a.dropna(), b.dropna()
        if a.dtype == bool or b.dtype == bool or c.endswith(("_invoices", "_received", "invoices_billed", "rank_13w",
                                                           "rank_13w_prev", "dso_window_days")):
            assert (a.astype(float) == b.astype(float)).all(), f"{name}.{c}: exact mismatch"
        else:
            d = (a.astype(float) - b.astype(float)).abs().max() if len(a) else 0.0
            assert d <= tol_of(c), f"{name}.{c}: max |diff| {d} > {tol_of(c)}"
    return len(cols)


n_wk = compare(V["kpi_weekly"], ref_wk, ["report_week"], "kpi_weekly")
n_cat = compare(V["kpi_weekly_category"], ref_cat, ["report_week", "vessel_category"], "kpi_weekly_category")
n_cust = compare(V["kpi_customer_13w"], ref_cust, ["report_week", "customer_id"], "kpi_customer_13w")
n_od = compare(V["kpi_overdue_list"][["report_week", "invoice_number", "amount_sdr", "days_past_due"]], ref_od,
               ["report_week", "invoice_number"], "kpi_overdue_list")
expected_views = ["dim_customer", "dim_date", "dim_toll_band", "dim_vessel", "dim_week", "fact_ar_snapshot",
                  "fact_invoice", "fact_payment", "kpi_customer_13w", "kpi_overdue_list", "kpi_weekly",
                  "kpi_weekly_category", "kpi_weekly_trend"]
assert views_in_db == expected_views, f"finance objects: {views_in_db}"
assert tuple(undocumented) == (0, 0), f"views / columns without COMMENT: {undocumented}"
print(f"compared: kpi_weekly 52 × {n_wk} columns, kpi_weekly_category 676 × {n_cat}, kpi_customer_13w 2080 × {n_cust}, "
      f"kpi_overdue_list {len(ref_od)} × {n_od}; 13 views, every view and column documented")
print("✅ Phase 3 validation passed: every KPI view equals the reference on all 52 weeks")


# %% Phase 4 — Invariants
k = V["kpi_weekly"].set_index("report_week")
roll = (k.ar_sdr.shift(1).fillna(0) + k.billed_sdr - k.collected_sdr - k.ar_sdr).abs().max()
aging = (k[[c for c in k.columns if c.startswith("aging_")]].sum(axis=1) - k.ar_sdr).abs().max()
overdue = (k[["aging_1_30_sdr", "aging_31_60_sdr", "aging_61_90_sdr", "aging_90_plus_sdr"]].sum(axis=1)
           - k.overdue_sdr).abs().max()
cat_sum = (V["kpi_weekly_category"].groupby("report_week").billed_sdr.sum() - k.billed_sdr).abs().max()
fi = V["fact_invoice"]
edge = fi[fi.invoice_report_week.isna()]
snapshot_inv = {"invoices_outside_report_weeks": len(edge),
                "their_dates": sorted(edge.invoice_date.dt.date.astype(str).unique().tolist()),
                "warmup_weeks": k.index[k.is_warmup].tolist() == list(range(1, 14)),
                "dim_date_rows": len(V["dim_date"]), "dim_week_rows": len(V["dim_week"]),
                "fact_invoice_rows": len(fi), "fact_payment_rows": len(V["fact_payment"]),
                "unpaid_at_horizon": int(fi.paid_date.isna().sum())}
reviewed_inv = {"invoices_outside_report_weeks": 4, "their_dates": ["2025-12-29", "2025-12-30"],
                "warmup_weeks": True, "dim_date_rows": 455, "dim_week_rows": 52, "fact_invoice_rows": 1000,
                "fact_payment_rows": 994, "unpaid_at_horizon": 6}
assert roll < 0.05 and aging < 0.05 and overdue < 0.05 and cat_sum < 0.07, (roll, aging, overdue, cat_sum)  # ≤ n × half a cent
assert abs(k.billed_sdr.sum() - fi.loc[fi.invoice_report_week.notna(), "amount_sdr"].sum()) < 0.3, "52 weeks ≠ ISO-2025 invoices"
assert snapshot_inv == reviewed_inv, f"invariants snapshot changed: {snapshot_inv}"
# kpi_weekly_trend (migration 014, M11): weeks w−12 … w of every report week, values identical to kpi_weekly
tr = V["kpi_weekly_trend"]
expected_pairs = {(w, t) for w in range(1, 53) for t in range(max(1, w - 12), w + 1)}
assert set(zip(tr.report_week, tr.trend_week)) == expected_pairs and len(tr) == len(expected_pairs) == 598, "trend rows"
trend_cols = ["invoices_billed", "billed_sdr", "collected_sdr", "ar_sdr", "overdue_sdr", "dso_days", "budget_sdr",
              "budget_variance_sdr", "budget_variance_pct", "top10_share_13w_pct"]
tm = tr.merge(V["kpi_weekly"], left_on="trend_week", right_on="report_week", suffixes=("", "_k"))
assert all(((tm[c] - tm[f"{c}_k"]).abs().fillna(0) == 0).all() for c in trend_cols), "trend ≠ kpi_weekly"
assert (tr.is_report_week == (tr.week_offset == 0)).all() and tr.week_offset.between(-12, 0).all()
print(f"roll-forward max |diff| {roll:.3f}, aging − AR {aging:.3f}, overdue − buckets {overdue:.3f}, "
      f"Σ categories − total {cat_sum:.3f} (rounded inputs); {snapshot_inv}")
print("✅ Phase 4 validation passed: invariants hold, the ISO edge is outside the report weeks")


# %% Phase 5 — Hand-check weeks (P2-7)
# The arithmetic of each chosen week, printed from the view row, recomputed from its parts, and frozen as a reviewed
# snapshot (owner review); a change in data or SQL stops here.
def money(x: float) -> str:
    return f"{x:,.2f}"


snap = {}
for w in HAND_WEEKS:
    r, p = k.loc[w], (k.loc[w - 1] if w > 1 else None)
    s, e = week_bounds(w)
    print(f"--- week {w} ({s.date()} → {e.date()}){' WARM-UP' if r.is_warmup else ''}")
    print(f"  billed     {r.invoices_billed} invoices = {money(r.billed_sdr)} SDR")
    print(f"  collected  {r.payments_received} payments = {money(r.collected_sdr)} SDR")
    print(f"  AR         {money(p.ar_sdr)} + {money(r.billed_sdr)} − {money(r.collected_sdr)} = {money(r.ar_sdr)} "
          f"({r.ar_invoices} invoices)")
    print(f"  aging      current {money(r.aging_current_sdr)} | 1-30 {money(r.aging_1_30_sdr)} | 31-60 "
          f"{money(r.aging_31_60_sdr)} | 61-90 {money(r.aging_61_90_sdr)} | 90+ {money(r.aging_90_plus_sdr)}")
    print(f"  overdue    {r.overdue_invoices} invoices = {money(r.overdue_sdr)} SDR")
    dso = r.ar_sdr / r.dso_window_billed_sdr * r.dso_window_days
    print(f"  DSO        {money(r.ar_sdr)} ÷ {money(r.dso_window_billed_sdr)} × {r.dso_window_days} = {dso:.1f} days "
          f"(view {r.dso_days})")
    print(f"  budget     {money(r.billed_sdr)} − {money(r.budget_sdr)} = {money(r.budget_variance_sdr)} "
          f"({r.budget_variance_pct} %)")
    wow = 100 * (r.billed_sdr - p.billed_sdr) / p.billed_sdr
    print(f"  WoW        ({money(r.billed_sdr)} − {money(p.billed_sdr)}) ÷ {money(p.billed_sdr)} = {wow:.2f} % "
          f"(view {r.billed_wow_pct}); DSO {r.dso_wow_days:+} days")
    print(f"  top-10     {r.top10_share_13w_pct} % of the trailing 13 weeks")
    assert abs(dso - r.dso_days) <= TOL["days"] and abs(wow - r.billed_wow_pct) <= TOL["pct"]
    snap[w] = {c: (round(float(r[c]), 2) if isinstance(r[c], float) else int(r[c]) if not isinstance(r[c], bool) else r[c])
               for c in ["invoices_billed", "billed_sdr", "collected_sdr", "ar_sdr", "overdue_sdr", "dso_days",
                         "budget_variance_pct", "top10_share_13w_pct", "billed_wow_pct"]}

REVIEWED_HAND = {    # owner review 2026-10-14 (the arithmetic above; equal to the first CSV draft and the views)
    5: {"invoices_billed": 21, "billed_sdr": 6902530.53, "collected_sdr": 1411387.4, "ar_sdr": 22103124.27,
        "overdue_sdr": 114612.87, "dso_days": 31.0, "budget_variance_pct": 25.17, "top10_share_13w_pct": 62.58,
        "billed_wow_pct": 24.03},
    16: {"invoices_billed": 11, "billed_sdr": 2934677.21, "collected_sdr": 4005943.1, "ar_sdr": 38599556.67,
         "overdue_sdr": 10250856.93, "dso_days": 51.7, "budget_variance_pct": -47.96, "top10_share_13w_pct": 56.89,
         "billed_wow_pct": -22.1},
    23: {"invoices_billed": 29, "billed_sdr": 8394785.98, "collected_sdr": 5263662.35, "ar_sdr": 47630979.69,
         "overdue_sdr": 12551623.16, "dso_days": 62.2, "budget_variance_pct": 45.62, "top10_share_13w_pct": 59.46,
         "billed_wow_pct": 25.83},
    49: {"invoices_billed": 19, "billed_sdr": 4056397.94, "collected_sdr": 4029984.17, "ar_sdr": 38168362.27,
         "overdue_sdr": 8070396.17, "dso_days": 53.6, "budget_variance_pct": -31.75, "top10_share_13w_pct": 60.36,
         "billed_wow_pct": -43.08}}
if not REVIEWED_HAND:
    print("snapshot to review:", snap)
    raise SystemExit("Phase 5: the hand-check snapshot is not reviewed yet — review the arithmetic above, then freeze it")
assert snap == REVIEWED_HAND, f"hand-check snapshot changed: {snap}"
print("✅ Phase 5 validation passed: weeks 5, 16, 23, 49 equal the reviewed hand-check values")


# %% Phase 6 — RBAC
# ADR-006: level ≤ ceiling, or own department and level ≤ 2. The finance views are level 2 / Finance, so readers are
# Finance staff and every manager / CEO; a role-`employee` outside Finance gets nothing (P2-5). The predicate is the
# one the tools use (pipelines/lib/retrieval.allowed); the rule is restated here independently.
users = [User(int(r.employee_id), r.role_name, int(r.allowed_sensitivity_level), r.department_name)
         for r in emp.itertuples(index=False)]
granted = {u.employee_id: allowed(u, FINANCE_LEVEL, FINANCE_DEPT) for u in users}
expected = {u.employee_id: u.ceiling >= 2 or u.department == FINANCE_DEPT for u in users}
assert granted == expected, "the tool predicate disagrees with ADR-006"
leak = [u.employee_id for u in users if granted[u.employee_id] and u.role == "employee" and u.department != FINANCE_DEPT]
denied = [u for u in users if not granted[u.employee_id]]
assert not leak and denied and all(u.role == "employee" and u.department != FINANCE_DEPT for u in denied)
matrix = (pd.DataFrame([dict(role=u.role, dept=u.department, granted=granted[u.employee_id]) for u in users])
            .groupby(["role", "granted"]).size().to_dict())
rbac_text = (ROOT / "docs" / "rbac_mapping.md").read_text(encoding="utf-8")
assert "`finance.*`" in rbac_text, "the finance views are not registered in docs/rbac_mapping.md"

fin = privileges[privileges.schema == "finance"]
pub = privileges[privileges.schema != "finance"]
assert len(fin) == 13 and fin.bi_select.all() and not fin.bi_write.any() and fin.ro_select.all(), "finance grants"
assert not pub.bi_select.any(), f"finance_bi can read outside finance: {pub[pub.bi_select].relname.tolist()}"
print(f"RBAC matrix (role, granted) → employees: {matrix}; leakage {len(leak)}; denied {len(denied)} "
      f"(all role employee outside Finance)")
print(f"privileges: finance_bi SELECT on {int(fin.bi_select.sum())} / 13 finance views, write 0, "
      f"SELECT on {int(pub.bi_select.sum())} / {len(pub)} public + finance_test tables; ports_readonly reads all 13")
print("✅ Phase 6 validation passed: non-Finance employees get nothing; finance_bi reads only schema finance")


# %% Final Checkpoint
# Narrative: pipelines/checkpoints/finance/Finance_views_check.md
summary = {"weeks": 52, "kpi_views_equal_reference": 4, "hand_weeks": HAND_WEEKS, "rbac_leakage": len(leak),
           "finance_bi_outside_finance": int(pub.bi_select.sum())}
assert summary == {"weeks": 52, "kpi_views_equal_reference": 4, "hand_weeks": [5, 16, 23, 49], "rbac_leakage": 0,
                   "finance_bi_outside_finance": 0}
print(f"Final Checkpoint: {summary}")
print("✅ Final Checkpoint passed: Phase 2 done-when met (KPIs = hand values on the chosen weeks; RBAC 0 leakage)")
