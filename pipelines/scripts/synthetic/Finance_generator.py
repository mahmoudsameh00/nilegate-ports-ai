"""Synthetic finance data for the Weekly Finance Pack (Agents plan Phase 1, rules §4a R1–R10, approved 2026-10-13).

Plan:    docs/plans/Agents_plan.md §4 / §4a; D6 amended (payments realistic, `invoices.status` kept as a label).
Run:     uv run python tools/run.py pipelines/scripts/synthetic/Finance_generator.py  (project root; ports-postgres up)

Reads:   PostgreSQL read-only (vessels, invoices, toll_rate_bands)
Writes:  DRY_RUN = True: nothing (prints the distributions for the owner's review).
         DRY_RUN = False: Data/processed/synthetic/finance/ (customers, vessel_customer, payments, budget_weekly,
         finance_test_invoices, finance_test_budget CSVs + manifest.json with the behaviour classes) and
         Data/processed/agents/eval/finance_test_answer_key.json; never overwrites a file with different data.
Re-run:  safe; fixed seeds (numpy default_rng([42, phase]) — identical on every OS, unlike Faker draws).

Phases
1. Inputs: vessels, invoices, toll bands; the 13 categories; segments.
2. Customers (R1, R3): 40 invented companies, segment, HQ country, terms, credit rating; behaviour class (manifest only).
3. Vessel → customer (R2): Zipf weights inside each segment; every vessel gets a customer.
4. Payments (R4): due = invoice date + terms; paid date = due + a delay drawn by behaviour; horizon 2026-03-31.
5. Weekly budget (R6): fleet × 2.0 transits per vessel-year × toll of the category median SCNT (laden), seasonal ±6 %.
6. Evaluation copy (R7): 4 golden weeks with planted invoice errors + one budget miss, and the answer key.
7. Save + reload (only when DRY_RUN is False).
"""
# %% Setup
import datetime as dt
import json
import math
import os
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "pyproject.toml").exists() and (p / "Data").is_dir())
sys.path.insert(0, str(ROOT))
from pipelines.lib.common import load_env  # noqa: E402

load_env(ROOT)
DRY_RUN = False                      # owner reviewed the dry run 2026-10-13 ("as it is, write")
OUT = ROOT / "Data" / "processed" / "synthetic" / "finance"
ANSWER_KEY = ROOT / "Data" / "processed" / "agents" / "eval" / "finance_test_answer_key.json"
YEAR, HORIZON = 2025, dt.date(2026, 3, 31)
TRANSITS_PER_VESSEL_YEAR = 2.0       # R6 planning assumption (stated, not fitted)
SEASON_AMPLITUDE, SEASON_PEAK, SEASON_LOW = 0.06, 45, 6

SEGMENT_OF = {  # vessel category → customer segment (R1)
    "Containerships": "container",
    "Crude Oil Tankers": "tanker", "Petroleum Product Tankers": "tanker",
    "Chemical Tankers & Other Liquid Bulk Tankers": "tanker", "Liquefied Natural Gas (LNG) Carriers": "tanker",
    "Liquefied Petroleum Gas (LPG) Carriers": "tanker",
    "Dry Bulk Vessels": "bulk", "General Cargo / Multi-Purpose / Heavy Lift Vessels": "bulk",
    "Roll-On/Roll-Off (Ro/Ro) Vessels": "roro", "Vehicles Carriers": "roro",
    "Cruise Ships": "cruise",
    "Other Vessels": "agent", "Special Floating Units": "agent"}
CUSTOMERS_PER_SEGMENT = {"container": 8, "tanker": 10, "bulk": 10, "roro": 5, "cruise": 3, "agent": 4}
SUFFIX = {"container": ["Lines", "Container Lines"], "tanker": ["Tankers", "Shipping"], "bulk": ["Bulk", "Maritime"],
          "roro": ["Car Carriers", "Ro-Ro Lines"], "cruise": ["Cruises"], "agent": ["Shipping Agency", "Marine Services"]}
# invented stems (prefix + ending); not real company names
PREFIXES = ["Nil", "Phar", "Sinai", "Aeg", "Lev", "Kor", "Mer", "Thal", "Cyr", "Ost", "Dal", "Vel", "Zan", "Quor",
            "Bel", "Ard"]
ENDINGS = ["avia", "omar", "enta", "oria", "anor", "ilis", "ussa", "ondo"]
COUNTRIES = (["Greece"] * 5 + ["Singapore"] * 4 + ["China"] * 4 + ["Egypt"] * 4 + ["Germany"] * 3 + ["Japan"] * 3
             + ["United Arab Emirates"] * 3 + ["Denmark"] * 2 + ["Switzerland"] * 2 + ["South Korea"] * 2
             + ["Saudi Arabia"] * 2 + ["Norway"] * 2 + ["Turkey"] * 2 + ["India"] * 2)
BEHAVIOUR_COUNTS = {"prompt": 10, "normal": 16, "slow": 8, "chronic_late": 4, "disputer": 2}       # 40 customers
RATING_GIVEN_BEHAVIOUR = {"prompt": {"A": .8, "B": .2, "C": 0}, "normal": {"A": .4, "B": .5, "C": .1},
                          "slow": {"A": 0, "B": .5, "C": .5}, "chronic_late": {"A": 0, "B": .2, "C": .8},
                          "disputer": {"A": 0, "B": .3, "C": .7}}
DELAY_DAYS = {"prompt": (-10, 0), "normal": (-3, 10), "slow": (10, 45), "chronic_late": (30, 120), "disputer": (10, 45)}
DISPUTE_UNPAID_SHARE = 0.40
TERMS_GIVEN_SEGMENT = {"agent": {30: .8, 45: .2, 60: 0}, "cruise": {30: .8, 45: .2, 60: 0}}
TERMS_DEFAULT = {30: .3, 45: .45, 60: .25}


def rng(phase: int) -> np.random.Generator:
    return np.random.default_rng([42, phase])


def sdr(x) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def pg():
    e = os.environ
    return psycopg.connect(host=e["PGHOST"], port=e["PGPORT"], dbname=e["PGDATABASE"], user=e["PG_RO_USER"],
                           password=e["PG_RO_PASSWORD"], options="-c default_transaction_read_only=on",
                           connect_timeout=5)


# %% Phase 1 — Inputs
with pg() as conn:
    vessels = pd.DataFrame(conn.execute("SELECT vessel_id, vessel_type, scnt_tons, condition FROM vessels "
                                        "ORDER BY vessel_id").fetchall(),
                           columns=["vessel_id", "vessel_type", "scnt_tons", "condition"])
    invoices = pd.DataFrame(conn.execute("SELECT invoice_number, vessel_id, invoice_date, amount, scnt_tons, status "
                                         "FROM invoices ORDER BY invoice_number").fetchall(),
                            columns=["invoice_number", "vessel_id", "invoice_date", "amount", "scnt_tons", "status"])
    bands = conn.execute("SELECT vessel_category, laden_ballast, band_order, band_label, band_min_tons, band_max_tons, "
                         "rate_sdr_per_ton FROM toll_rate_bands ORDER BY 1, 2, 3").fetchall()

BANDS: dict[tuple[str, str], list[tuple]] = {}
for cat, lb, _, label, lo, hi, rate in bands:
    BANDS.setdefault((cat, lb), []).append((label, lo, hi, rate))


def toll_exact(category: str, condition: str, tons) -> Decimal:
    """ADR-004 progressive amount (same rule as the bake-off's compute_toll; consolidated into one tool in Phase 4)."""
    lb = "Laden" if category == "Special Floating Units" else condition
    tons, amount = Decimal(str(tons)), Decimal(0)
    for _, lo, hi, rate in BANDS[(category, lb)]:
        if tons > lo:
            amount += rate * ((tons if hi is None else min(tons, hi)) - lo)
    return amount


def flat_terminal(category: str, condition: str, tons) -> Decimal:
    """A planted error: every ton at the terminal band's rate (not progressive)."""
    lb = "Laden" if category == "Special Floating Units" else condition
    tons, rate = Decimal(str(tons)), None
    for _, lo, _, r in BANDS[(category, lb)]:
        if tons > lo:
            rate = r
    return rate * tons


vessels["segment"] = vessels.vessel_type.map(SEGMENT_OF)
invoices["invoice_date"] = pd.to_datetime(invoices.invoice_date).dt.date
inv = invoices.merge(vessels[["vessel_id", "vessel_type", "condition", "segment"]], on="vessel_id", how="left")
assert len(vessels) == 500 and len(invoices) == 1000 and inv.vessel_type.notna().all()
assert vessels.segment.notna().all() and set(SEGMENT_OF) == set(vessels.vessel_type), "a category lacks a segment"
assert sum(CUSTOMERS_PER_SEGMENT.values()) == 40 == len(COUNTRIES) == sum(BEHAVIOUR_COUNTS.values())
print("vessels per segment:", vessels.segment.value_counts().to_dict())
print("✅ Phase 1 validation passed: 500 vessels, 1,000 invoices, 13 categories → 6 segments, 25 band pairs")


# %% Phase 2 — Customers (R1, R3)
# One row per customer; the behaviour class goes only to the manifest (ground truth for evaluation, never a column the
# agents can read). Ratings correlate with behaviour but do not reveal it.
r2 = rng(2)
stems = [p + e for p in PREFIXES for e in ENDINGS]
r2.shuffle(stems)
behaviours = [b for b, n in BEHAVIOUR_COUNTS.items() for _ in range(n)]
r2.shuffle(behaviours)
countries = list(COUNTRIES)
r2.shuffle(countries)
rows, k = [], 0
for seg, n in CUSTOMERS_PER_SEGMENT.items():
    for _ in range(n):
        k += 1
        beh = behaviours[k - 1]
        terms_p = TERMS_GIVEN_SEGMENT.get(seg, TERMS_DEFAULT)
        rating_p = RATING_GIVEN_BEHAVIOUR[beh]
        rows.append({"customer_id": k, "customer_name": f"{stems[k - 1]} {r2.choice(SUFFIX[seg])}",
                     "country": countries[k - 1], "segment": seg,
                     "payment_terms_days": int(r2.choice(list(terms_p), p=list(terms_p.values()))),
                     "credit_rating": str(r2.choice(list(rating_p), p=list(rating_p.values()))), "_behaviour": beh})
customers = pd.DataFrame(rows)
assert customers.customer_name.is_unique and len(customers) == 40
print("terms:", customers.payment_terms_days.value_counts().sort_index().to_dict(),
      "| ratings:", customers.credit_rating.value_counts().sort_index().to_dict())
print("rating × behaviour:", pd.crosstab(customers._behaviour, customers.credit_rating).to_dict("index"))
print("sample:", customers.head(3)[["customer_name", "country", "segment", "payment_terms_days"]].to_dict("records"))
print("✅ Phase 2 validation passed: 40 customers, unique invented names, behaviour kept out of the table")


# %% Phase 3 — Vessel → customer (R2)
# Inside a segment, customer j gets weight 1 / j (Zipf, s = 1): a few large customers, a long tail — revenue
# concentration comes out of the fleet split, it is reported, not tuned.
r3 = rng(3)
assign = {}
for seg, grp in vessels.groupby("segment"):
    cids = customers.loc[customers.segment == seg, "customer_id"].to_numpy()
    w = 1 / np.arange(1, len(cids) + 1)
    picks = r3.choice(cids, size=len(grp), p=w / w.sum())
    assign.update(dict(zip(grp.vessel_id, picks.tolist())))
vessels["customer_id"] = vessels.vessel_id.map(assign)
inv["customer_id"] = inv.vessel_id.map(assign)
rev = inv.groupby("customer_id").amount.sum().sort_values(ascending=False)
top10 = float(rev.head(10).sum() / rev.sum())
no_vessel = sorted(set(customers.customer_id) - set(vessels.customer_id))
print(f"top-10 customers' share of 2025 billing: {top10:.1%}; customers with no vessel: {no_vessel}; "
      f"vessels per customer (min / median / max): {vessels.customer_id.value_counts().min()} / "
      f"{int(vessels.customer_id.value_counts().median())} / {vessels.customer_id.value_counts().max()}")
assert vessels.customer_id.notna().all()
print("✅ Phase 3 validation passed: every vessel has a customer of its own segment")


# %% Phase 4 — Payments (R4)
# due = invoice date + the customer's terms; paid = due + delay(behaviour); a disputer leaves 40 % unpaid; nothing is
# paid after the horizon 2026-03-31. One payment per paid invoice, the full amount.
r4 = rng(4)
cust = customers.set_index("customer_id")
pay_rows, open_at_horizon = [], 0
inv["due_date"] = [d + dt.timedelta(days=int(cust.loc[c, "payment_terms_days"]))
                   for d, c in zip(inv.invoice_date, inv.customer_id)]
for r in inv.itertuples():
    beh = cust.loc[r.customer_id, "_behaviour"]
    if beh == "disputer" and r4.random() < DISPUTE_UNPAID_SHARE:
        open_at_horizon += 1
        continue
    lo, hi = DELAY_DAYS[beh]
    paid = r.due_date + dt.timedelta(days=int(r4.integers(lo, hi + 1)))
    paid = max(paid, r.invoice_date)
    if paid > HORIZON:
        open_at_horizon += 1
        continue
    pay_rows.append({"invoice_number": r.invoice_number, "paid_date": paid, "amount_sdr": r.amount})
payments = pd.DataFrame(pay_rows)
paid_by = payments.set_index("invoice_number").paid_date
inv["paid_date"] = inv.invoice_number.map(paid_by)
year_end = dt.date(YEAR, 12, 31)
open_ye = inv[inv.paid_date.isna() | (inv.paid_date > year_end)]
dso = float(open_ye.amount.sum() / (inv.amount.sum() / 365))
on_time = float((inv.paid_date.notna() & (inv.paid_date <= inv.due_date)).mean())
label_paid = inv.status == "Paid"
derived_paid = inv.paid_date.notna() & (inv.paid_date <= year_end)
print(f"paid: {len(payments)}, open at the horizon: {open_at_horizon} ({open_at_horizon / 10:.1f} %); "
      f"open at 2025-12-31: {len(open_ye)} invoices, {float(open_ye.amount.sum()) / 1e6:.1f} M SDR; DSO {dso:.0f} days; "
      f"paid on time {on_time:.0%}")
print(f"label vs derived (paid by 2025-12-31): agree {int((label_paid == derived_paid).sum())} / 1,000 "
      f"(the stored status is a random label — reported, not enforced)")
assert (payments.paid_date >= payments.invoice_number.map(inv.set_index("invoice_number").invoice_date)).all()
assert payments.invoice_number.is_unique
print("✅ Phase 4 validation passed: one full payment per paid invoice, paid date ≥ invoice date, horizon respected")


# %% Phase 5 — Weekly budget (R6)
# Annual plan per category = vessels × 2.0 transits × toll(median SCNT, laden), spread over the 52 weeks by a
# piecewise-linear seasonal curve (−6 % at week 6, +6 % at week 45), normalised to a mean of 1. The 2025 invoices are
# not read here.
def season(w: int) -> float:
    rise = (SEASON_PEAK - SEASON_LOW) % 52
    d = (w - SEASON_LOW) % 52
    x = -1 + 2 * d / rise if d <= rise else 1 - 2 * (d - rise) / (52 - rise)
    return 1 + SEASON_AMPLITUDE * x


factors = np.array([season(w) for w in range(1, 53)])
factors = factors / factors.mean()
plan = []
for cat, grp in vessels.groupby("vessel_type"):
    annual = Decimal(len(grp)) * Decimal(str(TRANSITS_PER_VESSEL_YEAR)) * toll_exact(cat, "Laden",
                                                                                     grp.scnt_tons.median())
    for w in range(1, 53):
        plan.append({"iso_week": w, "vessel_category": cat,
                     "budget_sdr": sdr(annual / 52 * Decimal(str(factors[w - 1])))})
budget = pd.DataFrame(plan)
inv["iso_week"] = [d.isocalendar().week if d.isocalendar().year == YEAR else None for d in inv.invoice_date]
actual = inv[inv.iso_week.notna()].groupby("vessel_type").amount.sum()
bud = budget.groupby("vessel_category").budget_sdr.sum()
gap = {c: f"{float(actual.get(c, 0) / bud[c] - 1):+.0%}" for c in bud.index}
print(f"budget 2025: {float(bud.sum()) / 1e6:.1f} M SDR vs actual {float(actual.sum()) / 1e6:.1f} M "
      f"({float(actual.sum() / bud.sum() - 1):+.1%}); seasonal factor min / max {factors.min():.3f} / {factors.max():.3f}")
print("actual vs budget by category:", gap)
assert len(budget) == 52 * 13 and (budget.budget_sdr > 0).all()
print("✅ Phase 5 validation passed: 676 budget rows (52 weeks × 13 categories), independent of the invoices")


# %% Phase 6 — Evaluation copy (R7): planted errors + answer key, never mixed with the real tables
r6 = rng(6)
TEST_WEEKS = {10: ["wrong_band_rate", "scnt_digit_swap"], 23: ["laden_ballast_swap", "duplicate_invoice"],
              36: ["sfu_priced_ballast"], 49: []}                       # week 49: clean (false-alarm check)
BUDGET_MISS = {"iso_week": 36, "factor": 1.5}                          # budget raised 50 % for the week's top category
test_rows, key = [], []
for week, errors in TEST_WEEKS.items():
    wk = inv[inv.iso_week == week].copy()
    wk["test_case"], wk["billed_sdr"] = "clean", wk.amount
    for err in errors:
        cand = wk[(wk.test_case == "clean") & ((wk.vessel_type == "Special Floating Units")
                                               if err == "sfu_priced_ballast" else wk.vessel_type.notna())]
        if err == "laden_ballast_swap":
            cand = cand[cand.vessel_type != "Special Floating Units"]
        i = cand.index[int(r6.integers(len(cand)))]
        row = wk.loc[i]
        if err == "wrong_band_rate":
            billed = sdr(flat_terminal(row.vessel_type, row.condition, row.scnt_tons))
        elif err == "scnt_digit_swap":
            s = f"{int(row.scnt_tons):d}"
            j = next(j for j in range(len(s) - 1) if s[j] != s[j + 1])
            wk.loc[i, "scnt_tons"] = Decimal(s[:j] + s[j + 1] + s[j] + s[j + 2:]) + (row.scnt_tons % 1)
            billed = row.amount                                       # amount of the true tonnage: tons ≠ amount
        elif err == "laden_ballast_swap":
            billed = sdr(toll_exact(row.vessel_type, "Ballast" if row.condition == "Laden" else "Laden",
                                    row.scnt_tons))
        elif err == "sfu_priced_ballast":                              # SFU has Laden rates only (ADR-004)
            billed = sdr(toll_exact("Other Vessels", "Ballast", row.scnt_tons))
        else:                                                          # duplicate_invoice: a second number, same charge
            dup = row.copy()
            dup["invoice_number"] = f"INV-9{int(row.invoice_number[4:]):06d}"
            dup["test_case"] = err
            wk = pd.concat([wk, dup.to_frame().T], ignore_index=True)
            key.append({"iso_week": week, "invoice_number": dup.invoice_number, "error": err,
                        "duplicate_of": row.invoice_number, "billed_sdr": str(row.amount)})
            continue
        wk.loc[i, "billed_sdr"], wk.loc[i, "test_case"] = billed, err
        key.append({"iso_week": week, "invoice_number": row.invoice_number, "error": err,
                    "billed_sdr": str(billed), "expected_sdr": str(sdr(row.amount))})
    test_rows.append(wk)
test_invoices = pd.concat(test_rows, ignore_index=True)
test_budget = budget[budget.iso_week.isin(list(TEST_WEEKS))].copy()
top_cat = inv[inv.iso_week == BUDGET_MISS["iso_week"]].groupby("vessel_type").amount.sum().idxmax()
m = (test_budget.iso_week == BUDGET_MISS["iso_week"]) & (test_budget.vessel_category == top_cat)
test_budget.loc[m, "budget_sdr"] = test_budget.loc[m, "budget_sdr"].map(lambda b: sdr(b * Decimal("1.5")))
key.append({"iso_week": BUDGET_MISS["iso_week"], "error": "budget_miss", "vessel_category": top_cat,
            "budget_factor": BUDGET_MISS["factor"]})
print(f"test copy: {len(test_invoices)} invoices in weeks {list(TEST_WEEKS)}, planted: "
      f"{test_invoices.test_case.value_counts().drop('clean').to_dict()}; budget miss: week 36 {top_cat}")
assert len(key) == 6 and test_invoices.test_case.ne("clean").sum() == 5
print("✅ Phase 6 validation passed: 5 planted invoice errors + 1 budget miss, week 49 clean, answer key with 6 findings")


# %% Phase 7 — Save + reload; the migration (skipped in the dry run)
# Files first (ADR-031 pattern): CSVs + a manifest (behaviour classes, distributions, hashes) + the answer key; the
# migration is generated from the same frames. A file that exists is never overwritten with different content.
# R7 deviation (owner, 2026-10-13): the finance_test copy has no test_case column — the labels are the answer key.
if DRY_RUN:
    print("DRY RUN: nothing written. Review the distributions above, then set DRY_RUN = False (owner).")
    print("✅ Final Checkpoint (dry run): rules R1–R7 applied in memory; no file, no migration")
    raise SystemExit(0)
import hashlib  # noqa: E402

MIGRATION = ROOT / "db" / "migrations" / "012_finance_data.sql"


def write_or_verify(path: Path, text: str) -> str:
    """Write text (LF); if the file exists it must be identical — never overwritten with different content."""
    data = text.encode("utf-8")
    if path.exists():
        assert path.read_bytes() == data, f"{path.name}: regenerated content differs from the saved file (not written)"
        print(f"{path.relative_to(ROOT).as_posix()}: identical, nothing written")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        print(f"{path.relative_to(ROOT).as_posix()}: written")
    return hashlib.sha256(data).hexdigest()


budget.insert(0, "budget_year", YEAR)
test_budget.insert(0, "budget_year", YEAR)
frames = {
    "customers.csv": customers.drop(columns="_behaviour"),
    "vessel_customer.csv": vessels[["vessel_id", "customer_id"]],
    "payments.csv": payments.sort_values("invoice_number"),
    "budget_weekly.csv": budget.sort_values(["iso_week", "vessel_category"]),
    "finance_test_invoices.csv": test_invoices[["invoice_number", "vessel_id", "invoice_date", "scnt_tons",
                                                "billed_sdr"]].sort_values("invoice_number"),
    "finance_test_budget.csv": test_budget.sort_values(["iso_week", "vessel_category"]),
}
hashes = {name: write_or_verify(OUT / name, df.to_csv(index=False, lineterminator="\n")) for name, df in frames.items()}
answer_key = {"rules": "Agents plan §4a R7 (approved 2026-10-13); the finance_test tables carry no label",
              "weeks": list(TEST_WEEKS), "clean_week": 49, "findings": key}
key_sha = write_or_verify(ANSWER_KEY, json.dumps(answer_key, indent=1, ensure_ascii=False) + "\n")
manifest = {
    "generator": "pipelines/scripts/synthetic/Finance_generator.py", "rules": "Agents plan §4a R1–R10",
    "seed": "numpy default_rng([42, phase])", "horizon": HORIZON.isoformat(),
    "transits_per_vessel_year": TRANSITS_PER_VESSEL_YEAR,
    "files": {n: {"rows": len(frames[n]), "sha256": h} for n, h in hashes.items()},
    "answer_key": {"path": ANSWER_KEY.relative_to(ROOT).as_posix(), "sha256": key_sha},
    # ground truth for evaluation only — never a database column (R3)
    "behaviour_by_customer": {int(c): b for c, b in zip(customers.customer_id, customers._behaviour)},
    "distributions": {"top10_share_2025": round(top10, 4), "dso_days_2025_12_31": round(dso, 1),
                      "open_at_horizon": open_at_horizon, "paid_on_or_before_due": round(on_time, 4),
                      "budget_2025_sdr": str(bud.sum()), "actual_2025_sdr": str(actual.sum()),
                      "label_vs_derived_agree": int((label_paid == derived_paid).sum())}}
write_or_verify(OUT / "manifest.json", json.dumps(manifest, indent=1, ensure_ascii=False) + "\n")


def q(v) -> str:
    """A SQL literal: NULL, a number as written, or a quoted string."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "NULL"
    if isinstance(v, (int, Decimal, np.integer)):
        return str(v)
    if isinstance(v, dt.date):
        return f"DATE '{v.isoformat()}'"
    return "'" + str(v).replace("'", "''") + "'"


def values(df: pd.DataFrame) -> str:
    return ",\n".join("    (" + ", ".join(q(v) for v in row) + ")" for row in df.itertuples(index=False))


cats = ", ".join(q(c) for c in sorted(SEGMENT_OF))
segs = ", ".join(q(s) for s in CUSTOMERS_PER_SEGMENT)
sql = f"""-- =====================================================================
-- 012 — Finance data for the Weekly Finance Pack: customers, vessel → customer, payments, weekly budget,
--       and the evaluation copy (schema finance_test)
-- Decisions: Agents plan §4a R1–R10 (approved 2026-10-13; D6 amended: payments follow terms and behaviour, the
-- stored invoices.status is kept as a label), ADR-003 (SDR), ADR-006 (RBAC), ADR-031, ADR-033, ADR-034.
-- Generated by pipelines/scripts/synthetic/Finance_generator.py; never edited after applying.
-- =====================================================================
BEGIN;

CREATE TABLE public.customers (
    customer_id integer PRIMARY KEY,
    customer_name text NOT NULL UNIQUE,
    country text NOT NULL,
    segment text NOT NULL CONSTRAINT customers_segment_chk CHECK (segment IN ({segs})),
    payment_terms_days integer NOT NULL CONSTRAINT customers_terms_chk CHECK (payment_terms_days IN (30, 45, 60)),
    credit_rating text NOT NULL CONSTRAINT customers_rating_chk CHECK (credit_rating IN ('A', 'B', 'C'))
);
INSERT INTO public.customers (customer_id, customer_name, country, segment, payment_terms_days, credit_rating) VALUES
{values(frames["customers.csv"])};

ALTER TABLE public.vessels ADD COLUMN customer_id integer REFERENCES public.customers (customer_id);
UPDATE public.vessels v SET customer_id = x.customer_id FROM (VALUES
{values(frames["vessel_customer.csv"])}
) AS x (vessel_id, customer_id) WHERE v.vessel_id = x.vessel_id;
ALTER TABLE public.vessels ALTER COLUMN customer_id SET NOT NULL;
CREATE INDEX vessels_customer_id_idx ON public.vessels (customer_id);

CREATE TABLE public.payments (
    invoice_number text PRIMARY KEY REFERENCES public.invoices (invoice_number),
    paid_date date NOT NULL,
    amount_sdr numeric NOT NULL CONSTRAINT payments_amount_chk CHECK (amount_sdr > 0)
);
INSERT INTO public.payments (invoice_number, paid_date, amount_sdr) VALUES
{values(frames["payments.csv"])};

CREATE TABLE public.budget_weekly (
    budget_year integer NOT NULL CONSTRAINT budget_weekly_year_chk CHECK (budget_year = 2025),
    iso_week integer NOT NULL CONSTRAINT budget_weekly_week_chk CHECK (iso_week BETWEEN 1 AND 52),
    vessel_category text NOT NULL CONSTRAINT budget_weekly_category_chk CHECK (vessel_category IN ({cats})),
    budget_sdr numeric NOT NULL CONSTRAINT budget_weekly_amount_chk CHECK (budget_sdr >= 0),
    PRIMARY KEY (budget_year, iso_week, vessel_category)
);
INSERT INTO public.budget_weekly (budget_year, iso_week, vessel_category, budget_sdr) VALUES
{values(frames["budget_weekly.csv"])};

CREATE SCHEMA finance_test;
CREATE TABLE finance_test.invoices (
    invoice_number text PRIMARY KEY CONSTRAINT test_invoices_number_chk CHECK (invoice_number ~ '^INV-[0-9]{{7}}$'),
    vessel_id integer NOT NULL REFERENCES public.vessels (vessel_id),
    invoice_date date NOT NULL,
    scnt_tons numeric NOT NULL CONSTRAINT test_invoices_scnt_chk CHECK (scnt_tons > 0),
    billed_sdr numeric NOT NULL CONSTRAINT test_invoices_amount_chk CHECK (billed_sdr > 0)
);
CREATE INDEX test_invoices_vessel_id_idx ON finance_test.invoices (vessel_id);
INSERT INTO finance_test.invoices (invoice_number, vessel_id, invoice_date, scnt_tons, billed_sdr) VALUES
{values(frames["finance_test_invoices.csv"])};
CREATE TABLE finance_test.budget_weekly (LIKE public.budget_weekly INCLUDING ALL);
INSERT INTO finance_test.budget_weekly (budget_year, iso_week, vessel_category, budget_sdr) VALUES
{values(frames["finance_test_budget.csv"])};

COMMENT ON TABLE public.customers IS 'Synthetic customers (shipping lines / agents) billed for Suez transit dues; 40 invented companies (Agents plan §4a R1). Level 2, Finance.';
COMMENT ON COLUMN public.customers.customer_id IS 'Surrogate key';
COMMENT ON COLUMN public.customers.customer_name IS 'Invented company name (not a real company)';
COMMENT ON COLUMN public.customers.country IS 'Headquarters country (not the flag of its vessels)';
COMMENT ON COLUMN public.customers.segment IS 'Customer segment by the vessel types it operates';
COMMENT ON COLUMN public.customers.payment_terms_days IS 'Payment terms: due date = invoice date + these days';
COMMENT ON COLUMN public.customers.credit_rating IS 'Credit rating A / B / C (correlates with payment behaviour, does not reveal it)';
COMMENT ON COLUMN public.vessels.customer_id IS 'The customer billed for this vessel (FK customers; migration 012)';
COMMENT ON TABLE public.payments IS 'One full payment per paid invoice (no partial payments), up to 2026-03-31; an invoice without a row is unpaid. Level 2, Finance.';
COMMENT ON COLUMN public.payments.invoice_number IS 'The paid invoice (FK invoices)';
COMMENT ON COLUMN public.payments.paid_date IS 'Date the payment was received';
COMMENT ON COLUMN public.payments.amount_sdr IS 'Amount paid in SDR (= the invoice amount)';
COMMENT ON TABLE public.budget_weekly IS 'Weekly budget 2025 per vessel category: a planning model (fleet x 2.0 transits x median-tonnage laden toll, seasonal +/-6 %), not fitted to the invoices (Agents plan §4a R6). Level 2, Finance.';
COMMENT ON COLUMN public.budget_weekly.budget_year IS 'Budget year (2025 only)';
COMMENT ON COLUMN public.budget_weekly.iso_week IS 'ISO week of the budget year';
COMMENT ON COLUMN public.budget_weekly.vessel_category IS 'Suez tariff vessel category (same 13 values as vessels.vessel_type)';
COMMENT ON COLUMN public.budget_weekly.budget_sdr IS 'Budgeted transit dues in SDR';
COMMENT ON COLUMN public.invoices.status IS 'Original generator label (Issued / Pending / Paid), drawn at random over 2025 (ADR-013); NOT the payment state — the payment state is derived from payments by the finance views (Agents plan §4a, D6 amended 2026-10-13).';
COMMENT ON SCHEMA finance_test IS 'Evaluation copy only (Agents plan §4a R7): 4 golden weeks with planted invoice errors and a budget miss; never joined with the real tables; the answer key is outside the database.';
COMMENT ON TABLE finance_test.invoices IS 'Invoices of 4 golden weeks as billed, some with planted errors (no label column). Level 2, Finance.';
COMMENT ON COLUMN finance_test.invoices.invoice_number IS 'Invoice number (a planted duplicate has a new number)';
COMMENT ON COLUMN finance_test.invoices.vessel_id IS 'The vessel (FK public.vessels)';
COMMENT ON COLUMN finance_test.invoices.invoice_date IS 'Invoice date';
COMMENT ON COLUMN finance_test.invoices.scnt_tons IS 'Suez Canal Net Tonnage as billed';
COMMENT ON COLUMN finance_test.invoices.billed_sdr IS 'Amount billed in SDR';
COMMENT ON TABLE finance_test.budget_weekly IS 'Budget rows of the 4 golden weeks, one of them changed (a planted budget miss). Level 2, Finance.';

GRANT USAGE ON SCHEMA finance_test TO ports_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA finance_test TO ports_readonly;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA finance_test GRANT SELECT ON TABLES TO ports_readonly;

COMMIT;
ANALYZE public.customers;
ANALYZE public.vessels;
ANALYZE public.payments;
ANALYZE public.budget_weekly;
ANALYZE finance_test.invoices;
ANALYZE finance_test.budget_weekly;
"""
mig_sha = write_or_verify(MIGRATION, sql)

# reload: every file read back from disk and checked against what the run computed
back = {n: pd.read_csv(OUT / n, dtype=str) for n in frames}
assert {n: len(b) for n, b in back.items()} == {n: len(f) for n, f in frames.items()}
assert sum(Decimal(x) for x in back["payments.csv"].amount_sdr) == payments.amount_sdr.sum()
assert sum(Decimal(x) for x in back["budget_weekly.csv"].budget_sdr) == budget.budget_sdr.sum()
assert json.loads(ANSWER_KEY.read_text(encoding="utf-8"))["findings"] == json.loads(json.dumps(key))
assert "test_case" not in back["finance_test_invoices.csv"].columns
reviewed = {"customers": 40, "vessels": 500, "payments": 994, "budget_rows": 676, "test_invoices": 88,
            "test_budget_rows": 52, "findings": 6}
actual_counts = {"customers": len(back["customers.csv"]), "vessels": len(back["vessel_customer.csv"]),
                 "payments": len(back["payments.csv"]), "budget_rows": len(back["budget_weekly.csv"]),
                 "test_invoices": len(back["finance_test_invoices.csv"]),
                 "test_budget_rows": len(back["finance_test_budget.csv"]), "findings": len(key)}
assert actual_counts == reviewed, actual_counts
print(f"migration sha256 {mig_sha[:12]}…")
print("✅ Phase 7 validation passed: 6 CSVs + manifest + answer key + migration 012 written or identical; reload equal")
print("✅ Final Checkpoint: finance data generated by §4a R1–R10 — narrative in "
      "pipelines/checkpoints/synthetic/Finance_generator.md")
