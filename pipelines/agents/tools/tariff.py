"""`compute_toll`: Suez Canal transit dues from the progressive toll bands (ADR-004; Agents plan §3, §5a S2).

amount = Σ rate × tons inside each band of (category, condition); the terminal band is the one that holds the last
ton; Special Floating Units are always priced Laden (the tariff has Laden rates only). Exact arithmetic in Decimal,
rounded once to 2 decimals half away from zero (PostgreSQL's round(numeric, 2)). The stored invoices follow no single
rule at the half cent (ADR-013), so checks compare the exact amount with a half-cent tolerance.

This Python implementation is deliberately independent of the SQL audit views (migration 015): the check script
compares the two on every invoice (P4-2).
"""
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from langchain.tools import ToolRuntime, tool
from pydantic import BaseModel, Field, model_validator

from pipelines.agents.tools import context, db
from pipelines.agents.tools.schemas import Source, ToolResult

# = the CHECK on vessels.vessel_type and toll_rate_bands.vessel_category (ADR-033); the check script compares them
CATEGORIES = ("Chemical Tankers & Other Liquid Bulk Tankers", "Containerships", "Crude Oil Tankers", "Cruise Ships",
              "Dry Bulk Vessels", "General Cargo / Multi-Purpose / Heavy Lift Vessels",
              "Liquefied Natural Gas (LNG) Carriers", "Liquefied Petroleum Gas (LPG) Carriers", "Other Vessels",
              "Petroleum Product Tankers", "Roll-On/Roll-Off (Ro/Ro) Vessels", "Special Floating Units",
              "Vehicles Carriers")
SFU = "Special Floating Units"
CENT = Decimal("0.01")

_bands: dict[tuple[str, str], list[dict]] | None = None


def bands() -> dict[tuple[str, str], list[dict]]:
    global _bands
    if _bands is None:
        rows = db.fetch("SELECT id, vessel_category, laden_ballast, band_order, band_label, band_min_tons, "
                        "band_max_tons, rate_sdr_per_ton FROM toll_rate_bands ORDER BY 2, 3, 4", exact=True)
        _bands = {}
        for r in rows:
            _bands.setdefault((r["vessel_category"], r["laden_ballast"]), []).append(r)
    return _bands


def sdr(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def toll(vessel_category: str, laden_ballast: str, scnt_tons) -> dict:
    """The exact progressive toll with its band-by-band breakdown (Decimal values)."""
    priced = "Laden" if vessel_category == SFU else laden_ballast
    tons, amount, lines, terminal = Decimal(str(scnt_tons)), Decimal(0), [], None
    if tons <= 0:
        raise ValueError("scnt_tons must be > 0")
    for b in bands()[(vessel_category, priced)]:
        lo, hi = b["band_min_tons"], b["band_max_tons"]
        if tons > lo:
            inside = (tons if hi is None else min(tons, hi)) - lo
            amount += b["rate_sdr_per_ton"] * inside
            lines.append({"band": b["band_label"], "tons": inside, "rate_sdr_per_ton": b["rate_sdr_per_ton"],
                          "sdr": b["rate_sdr_per_ton"] * inside})
            terminal = b
    return {"vessel_category": vessel_category, "laden_ballast_priced": priced, "scnt_tons": tons,
            "exact_sdr": amount, "amount_sdr": sdr(amount), "terminal_band": terminal["band_label"],
            "terminal_band_id": terminal["id"], "rate_sdr_per_ton": terminal["rate_sdr_per_ton"], "bands": lines}


class TollArgs(BaseModel):
    vessel_id: int | None = Field(default=None, description="one of NileGate's vessels; its category, condition and "
                                                            "SCNT are read from the vessels table")
    vessel_category: Literal[CATEGORIES] | None = Field(default=None, description="tariff vessel category")
    laden_ballast: Literal["Laden", "Ballast"] | None = Field(default=None, description="the vessel's condition")
    scnt_tons: float | None = Field(default=None, gt=0, description="Suez Canal Net Tonnage (SCNT)")

    @model_validator(mode="after")
    def _one_way(self):
        given = [self.vessel_category, self.laden_ballast, self.scnt_tons]
        if self.vessel_id is None and any(v is None for v in given):
            raise ValueError("give vessel_id, or vessel_category + laden_ballast + scnt_tons")
        if self.vessel_id is not None and any(v is not None for v in given):
            raise ValueError("give vessel_id alone, or the three tariff inputs, not both")
        return self


def compute_toll(user, **args) -> ToolResult:
    a = TollArgs.model_validate(args)
    need = [context.TOLL_BANDS] + ([context.VESSELS] if a.vessel_id is not None else [])
    if not context.permitted(user, *need):
        return context.denied("compute_toll")
    if a.vessel_id is not None:
        v = db.fetch("SELECT vessel_type, condition, scnt_tons FROM vessels WHERE vessel_id = %s", (a.vessel_id,),
                     exact=True)
        if not v:
            return ToolResult(tool="compute_toll", status="no_data", note=f"no vessel {a.vessel_id}")
        cat, cond, tons = v[0]["vessel_type"], v[0]["condition"], v[0]["scnt_tons"]
        flt = f"vessel_id = {a.vessel_id} → {cat} / {cond} / {tons} SCNT"
    else:
        cat, cond, tons = a.vessel_category, a.laden_ballast, a.scnt_tons
        flt = f"{cat} / {cond} / {tons} SCNT"
    t = toll(cat, cond, tons)
    row = {"vessel_category": cat, "laden_ballast_priced": t["laden_ballast_priced"], "scnt_tons": float(t["scnt_tons"]),
           "amount_sdr": float(t["amount_sdr"]), "terminal_band": t["terminal_band"],
           "rate_sdr_per_ton": float(t["rate_sdr_per_ton"]),
           "bands": [{"band": b["band"], "tons": float(b["tons"]), "rate_sdr_per_ton": float(b["rate_sdr_per_ton"]),
                      "sdr": float(sdr(b["sdr"]))} for b in t["bands"]]}
    note = "Special Floating Units are priced Laden (the tariff has Laden rates only)" \
        if cat == SFU and cond != "Laden" else None
    return ToolResult(tool="compute_toll", status="ok", rows=[row], note=note,
                      source=Source(kind="table", name="public.toll_rate_bands", filter=flt))


@tool("compute_toll", args_schema=TollArgs)
def compute_toll_tool(runtime: ToolRuntime, **args) -> dict:
    """Compute the Suez Canal transit dues (SDR) of one transit from the official progressive toll bands, for one of
    NileGate's vessels (vessel_id) or for a category, condition and tonnage."""
    return compute_toll(context.user_of(runtime), **args).model_dump(mode="json")
