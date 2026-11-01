"""`vessel_params`: a vessel's speed, fuel per day and the dated bunker price in SDR (Agents plan §6a S5; P9-1, P9-3,
P9-5, D-P9-4 / D-P9-5; migration 020).

- The size band = the `vessel_performance` row of the vessel's tariff category whose SCNT range holds its SCNT
  (bands are contiguous, band 3 open; every one of our 500 vessels falls in exactly one, verify_readonly §24).
- Speed: the `speed_kn` argument if given, else the vessel's own service speed (its synthetic voyage, ADR-032),
  else the band's reference speed (IMO's average speed at sea). The speed used and where it came from are returned.
- Fuel per sea day = main × (speed / ref_speed)³ + aux: the cube law (propulsion power ∝ speed³) applies to the main
  engine only; auxiliaries are constant (D-P9-5). The source rows and both IMO figures travel with the result.
- Money in SDR (ADR-003): the latest dated VLSFO price in USD / t ÷ the USD-per-SDR rate stored beside it; both dates
  are returned so every cost names its assumptions. Exact Decimal arithmetic, rounded once at the end.
- The vessel's condition (laden / ballast) is not an input: the IMO figures are yearly averages over both (D-P9-8).
Access: `vessel_performance` and `bunker_prices` are level 1 / Operations (`docs/rbac_mapping.md` §2); a vessel_id also
reads `vessels` and the voyage file (level 1 / Operations).
"""
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from langchain.tools import ToolRuntime, tool
from pydantic import BaseModel, Field, model_validator

from pipelines.agents.tools import context, db, voyages
from pipelines.agents.tools.schemas import Source, ToolResult
from pipelines.agents.tools.tariff import CATEGORIES

TONNE = Decimal("0.01")
CENT = Decimal("0.01")
FACTOR = Decimal("0.0001")


def _q(x: Decimal, step: Decimal) -> Decimal:
    return x.quantize(step, rounding=ROUND_HALF_UP)


def band(vessel_type: str, scnt_tons) -> dict | None:
    rows = db.fetch("SELECT * FROM vessel_performance WHERE vessel_type = %s AND scnt_min <= %s "
                    "AND (scnt_max IS NULL OR %s < scnt_max)", (vessel_type, scnt_tons, scnt_tons), exact=True)
    return rows[0] if len(rows) == 1 else None


def latest_price() -> dict | None:
    rows = db.fetch("SELECT * FROM bunker_prices WHERE fuel = 'VLSFO' ORDER BY price_date DESC LIMIT 1", exact=True)
    return rows[0] if rows else None


class ParamsArgs(BaseModel):
    vessel_id: int | None = Field(default=None, ge=1, description="one of NileGate's vessels; its category, SCNT and "
                                                                 "service speed are read from the vessels table and "
                                                                 "its voyage")
    vessel_type: Literal[CATEGORIES] | None = Field(default=None, description="tariff vessel category")
    scnt_tons: float | None = Field(default=None, gt=0, description="Suez Canal Net Tonnage (SCNT)")
    speed_kn: float | None = Field(default=None, ge=4, le=25, description="speed in knots to price the fuel at; "
                                                                          "default: the vessel's service speed")

    @model_validator(mode="after")
    def _one_way(self):
        given = [self.vessel_type, self.scnt_tons]
        if self.vessel_id is None and any(v is None for v in given):
            raise ValueError("give vessel_id, or vessel_type + scnt_tons")
        if self.vessel_id is not None and any(v is not None for v in given):
            raise ValueError("give vessel_id alone, or vessel_type + scnt_tons, not both")
        return self


def vessel_params(user, **args) -> ToolResult:
    a = ParamsArgs.model_validate(args)
    need = [context.VESSEL_PARAMS] + ([context.VESSELS, context.AIS_TRACKS] if a.vessel_id is not None else [])
    if not context.permitted(user, *need):
        return context.denied("vessel_params")
    service = None
    if a.vessel_id is not None:
        v = db.fetch("SELECT vessel_type, scnt_tons FROM vessels WHERE vessel_id = %s", (a.vessel_id,), exact=True)
        if not v:
            return ToolResult(tool="vessel_params", status="no_data", note=f"no vessel {a.vessel_id}")
        vt, tons = v[0]["vessel_type"], v[0]["scnt_tons"]
        voy = voyages.voyages()
        if a.vessel_id in voy.index:
            service = Decimal(str(voy.at[a.vessel_id, "service_kn"]))
        flt = f"vessel_id = {a.vessel_id} → {vt} / {tons} SCNT"
    else:
        vt, tons = a.vessel_type, Decimal(str(a.scnt_tons))
        flt = f"{vt} / {tons} SCNT"
    b, p = band(vt, tons), latest_price()
    if b is None or p is None:
        return ToolResult(tool="vessel_params", status="no_data",
                          note="no performance band for this category and SCNT" if b is None else "no bunker price set")
    if a.speed_kn is not None:
        speed, speed_source = Decimal(str(a.speed_kn)), "argument"
    elif service is not None:
        speed, speed_source = service, "vessel service speed (synthetic voyage)"
    else:
        speed, speed_source = b["ref_speed_kn"], "IMO reference speed of the band"
    cube = (speed / b["ref_speed_kn"]) ** 3
    main = b["main_t_per_day"] * cube
    fuel = main + b["aux_t_per_day"]
    sdr_per_t = p["price_usd_per_t"] / p["usd_per_sdr"]
    row = {"vessel_id": a.vessel_id, "vessel_type": vt, "scnt_tons": float(tons), "size_band": b["size_band"],
           "imo_ship_type": b["imo_ship_type"], "imo_size_bin": f"{b['imo_size_bin']} {b['imo_size_unit']}",
           "speed_kn": float(speed), "speed_source": speed_source, "ref_speed_kn": float(b["ref_speed_kn"]),
           "cube_factor": float(_q(cube, FACTOR)), "main_t_per_day_at_ref": float(b["main_t_per_day"]),
           "main_t_per_day": float(_q(main, TONNE)), "aux_t_per_day": float(b["aux_t_per_day"]),
           "fuel_t_per_day": float(_q(fuel, TONNE)),
           "fuel": p["fuel"], "price_usd_per_t": float(p["price_usd_per_t"]), "price_date": p["price_date"].isoformat(),
           "usd_per_sdr": float(p["usd_per_sdr"]), "rate_date": p["rate_date"].isoformat(),
           "price_sdr_per_t": float(_q(sdr_per_t, CENT)), "fuel_cost_sdr_per_day": float(_q(fuel * sdr_per_t, CENT)),
           "source_ref": b["source_ref"]}
    note = (f"fuel at sea = main × (speed / {b['ref_speed_kn']} kn)³ + aux; {p['fuel']} {p['price_usd_per_t']} USD/t of "
            f"{p['price_date']} at {p['usd_per_sdr']} USD per SDR of {p['rate_date']}; yearly IMO averages "
            f"(laden and ballast together)")
    return ToolResult(tool="vessel_params", status="ok", rows=[row], note=note,
                      source=Source(kind="table", name="public.vessel_performance + public.bunker_prices",
                                    filter=f"{flt} → band {b['size_band']}; latest VLSFO price"))


@tool("vessel_params", args_schema=ParamsArgs)
def vessel_params_tool(runtime: ToolRuntime, **args) -> dict:
    """A vessel's speed, fuel consumption per sea day (tonnes) and the bunker price per tonne in SDR, for one of
    NileGate's vessels (vessel_id) or for a category and tonnage; `speed_kn` prices the fuel at another speed."""
    return vessel_params(context.user_of(runtime), **args).model_dump(mode="json")
