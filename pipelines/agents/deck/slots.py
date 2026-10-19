"""Number slots (Agents plan §5c, P6-1 / P6-3): the Writer refers to a number, code writes it.

The Writer never types a NileGate number. It writes a reference to a field of a tool result kept in the state, and
this module turns the reference into text with the allowed rounding, the sign and the unit:

    {kpi.weekly:billed_sdr|M}                          → 8.39 M SDR
    {kpi.weekly:collected_wow_pct|%1|dir}              → down 15.8 %
    {kpi.category[Cruise Ships]:billed_wow_change_sdr|M}  → −1.07 M SDR
    {audit.week[INV-0000626/duplicate_charge]:difference_sdr}  → +81,837.02 SDR
    {audit.week:invoices_checked}                      → 19

So every number is bound to its (evidence, row, field) by construction (G1), and the two errors of the Phase 5 real
runs — a sign dropped next to "down", a field cited from the wrong dataset — cannot be written: the sign comes from
the value, and a field that is not in the cited result is refused with a hint naming the result that has it.

One module serves the renderer (tables and tiles use `format_value` directly), the approval payload and the
Validator. Roundings = skill `number-validation` rule 2 (half away from zero, never cut, the sign kept, `*_pct`
already percent). Only the structured tools give numbers (ADR-049, untrusted-content rule 4).
"""
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

# tools whose numeric fields may be cited: NileGate's structured tools (ADR-049) + public structured context
NUMERIC_TOOLS = {"finance_kpi", "invoice_audit", "compute_toll", "suez_transits"}
MINUS = "−"                                            # U+2212, the deck's minus sign (deck-style-guide)

# a result's row key: the field(s) a slot names in [...] to pick one row of a list; "/" joins the parts
ROW_KEYS_BY_VIEW = {"finance.kpi_weekly": (), "finance.kpi_weekly_category": ("vessel_category",),
                    "finance.kpi_customer_13w": ("customer_name",), "finance.kpi_overdue_list": ("invoice_number",),
                    "finance.kpi_weekly_trend": ("trend_week_label",)}
ROW_KEYS_BY_TOOL = {"invoice_audit": ("invoice_number", "check_code"), "suez_transits": ("date",),
                    "compute_toll": ()}
# result-level fields (not in a row), e.g. the audit totals and the mean daily Suez transits
RESULT_FIELDS_SKIP = {"tool", "status", "rows", "source", "note"}

# kind → allowed formats (the first is the default)
FORMATS = {"money": ("sdr", "M", "k"), "pct": ("%2", "%1"), "days": ("d",), "count": ("n",), "number": ("x",)}
DAY_FIELDS = {"days_past_due"}
CHANGE_RE = re.compile(r"wow|change|variance|difference")

SLOT_RE = re.compile(r"\{(?P<eid>(?:kpi|audit|insight)\.[A-Za-z0-9_.:-]+?)(?:\[(?P<key>[^\[\]{}]+)\])?"
                     r":(?P<field>[a-z][a-z0-9_]*)(?:\|(?P<fmt>[A-Za-z0-9%]+))?(?:\|(?P<dir>dir))?\}")


class SlotError(ValueError):
    """A slot that cannot be filled; the message is the one-line fix the Writer needs."""

    def __init__(self, raw: str, message: str):
        super().__init__(f"{raw}: {message}")
        self.raw, self.message = raw, message


@dataclass(frozen=True)
class Slot:
    raw: str
    eid: str
    key: str | None
    field: str
    fmt: str | None
    direction: bool
    start: int
    end: int


@dataclass(frozen=True)
class Bound:
    """A filled slot: where its value comes from and the text written in its place."""
    slot: Slot
    row: int | None            # index in the result's rows; None = a result-level field
    value: float | int
    kind: str
    fmt: str
    text: str


# --- formatting -----------------------------------------------------------------------------------------------------

def field_kind(field: str, value) -> str | None:
    """money / pct / days / count / number by the field's name (the views' suffixes), else by the value's type;
    None for anything that is not a number (text, dates, flags)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if field.endswith("_sdr"):
        return "money"
    if field.endswith("_pct"):
        return "pct"
    if field.endswith("_days") or field in DAY_FIELDS:
        return "days"
    return "count" if isinstance(value, int) else "number"


def is_change(field: str) -> bool:
    """A change (WoW, change, budget variance, audit difference): always written with its sign or direction."""
    return bool(CHANGE_RE.search(field))


def _q(v: Decimal, d: int) -> Decimal:
    return v.quantize(Decimal(1).scaleb(-d), rounding=ROUND_HALF_UP)   # half away from zero (rule 2)


def _magnitude(kind: str, fmt: str, v: Decimal, value) -> str:
    if kind == "money":
        return {"sdr": f"{_q(v, 2):,.2f} SDR", "M": f"{_q(v / 10 ** 6, 2):,.2f} M SDR",
                "k": f"{_q(v / 10 ** 3, 1):,.1f} k SDR"}[fmt]
    if kind == "pct":
        d = int(fmt[1])
        return f"{_q(v, d):.{d}f} %"
    if kind == "days":
        n = f"{v:,}" if isinstance(value, int) else f"{_q(v, 1):,.1f}"
        return f"{n} {'day' if isinstance(value, int) and value == 1 else 'days'}"
    if kind == "count":
        return f"{v:,}"
    return f"{v:,f}"                                     # number: as returned (the decimals the tool gave)


def format_value(field: str, value, fmt: str | None = None, direction: bool = False) -> str:
    """The text of one value. None → "n/a" (deck-style-guide: WoW not available). Changes carry "+" / "−", or with
    `direction` "up …" / "down …" / "unchanged"; other values keep their own sign."""
    if value is None:
        return "n/a"
    kind = field_kind(field, value)
    if kind is None:
        raise ValueError(f"{field} = {value!r} is not a number")
    fmt = fmt or FORMATS[kind][0]
    if fmt not in FORMATS[kind]:
        raise ValueError(f"format {fmt!r} not allowed for {field} ({kind}): use {' or '.join(FORMATS[kind])}")
    v = Decimal(str(value))
    text = _magnitude(kind, fmt, abs(v), abs(value))
    if direction:
        if not is_change(field):
            raise ValueError(f"|dir only on a change field (wow, change, variance, difference), not {field}")
        return "unchanged" if v == 0 else f"{'up' if v > 0 else 'down'} {text}"
    if v < 0:
        return MINUS + text
    return ("+" + text) if (v > 0 and is_change(field)) else text


# --- resolving ------------------------------------------------------------------------------------------------------

def row_keys(res: dict) -> tuple[str, ...]:
    if res.get("tool") == "finance_kpi":
        return ROW_KEYS_BY_VIEW.get((res.get("source") or {}).get("name"), ())
    return ROW_KEYS_BY_TOOL.get(res.get("tool"), ())


def _row_label(row: dict, keys: tuple[str, ...]) -> str:
    return "/".join(str(row.get(k)) for k in keys)


def find_slots(text: str) -> list[Slot]:
    return [Slot(mt.group(0), mt["eid"], mt["key"], mt["field"], mt["fmt"] if mt["fmt"] != "dir" else None,
                 bool(mt["dir"]) or mt["fmt"] == "dir", mt.start(), mt.end()) for mt in SLOT_RE.finditer(text)]


def _holders(field: str, evidence: dict) -> list[str]:
    """Evidence ids whose rows (or result) have `field`: the hint for a field cited from the wrong result."""
    out = []
    for eid, res in sorted(evidence.items()):
        if res.get("status") == "ok" and (field in res and field not in RESULT_FIELDS_SKIP
                                          or any(field in r for r in res.get("rows") or [])):
            out.append(eid)
    return out


def locate(slot: Slot, evidence: dict) -> tuple[int | None, object]:
    """(row index or None for a result-level field, raw value — None allowed) of the field a slot names."""
    raw = slot.raw
    res = evidence.get(slot.eid)
    if res is None:
        raise SlotError(raw, f"no evidence {slot.eid!r}; cite one of: {', '.join(sorted(evidence))}")
    if res.get("status") != "ok":
        raise SlotError(raw, f"{slot.eid} has status {res.get('status')}: no number from it")
    if res.get("tool") not in NUMERIC_TOOLS:
        raise SlotError(raw, f"{slot.eid} is a {res.get('tool')} result: document and web text never gives a "
                             "number (ADR-049); write it as context without a slot")
    rows, keys = res.get("rows") or [], row_keys(res)
    level = slot.field in res and slot.field not in RESULT_FIELDS_SKIP
    if not level and not any(slot.field in r for r in rows):
        where = [e for e in _holders(slot.field, evidence) if e != slot.eid]
        hint = f"; it is in {', '.join(where)}" if where else ""
        raise SlotError(raw, f"{slot.eid} has no field {slot.field!r}{hint}")
    row_i = None
    if slot.key is None:
        if level:
            value = res[slot.field]
        elif len(rows) == 1:
            row_i, value = 0, rows[0].get(slot.field)
        elif not rows:
            raise SlotError(raw, f"{slot.eid} has no rows")
        else:
            raise SlotError(raw, f"{slot.eid} has {len(rows)} rows: name one as {slot.eid}[<{'/'.join(keys)}>]")
    else:
        if not keys:
            raise SlotError(raw, f"{slot.eid} has one row: drop [{slot.key}]")
        # the first key field alone, or every key field joined by "/" (category names hold "/" themselves:
        # "Roll-On/Roll-Off (Ro/Ro) Vessels", so the key is never split)
        hits = [i for i, r in enumerate(rows) if slot.key in (str(r.get(keys[0])), _row_label(r, keys))]
        if not hits:
            names = ", ".join(str(r.get(keys[0])) for r in rows[:15])
            example = binding(slot.eid, slot.field, slot.fmt, str(rows[0].get(keys[0])), slot.direction) if rows else ""
            raise SlotError(raw, f"no row {slot.key!r} in {slot.eid} (key {'/'.join(keys)}); rows: {names}"
                                 + (f" — name the row by its {keys[0]}, e.g. {example}" if example else ""))
        if len(hits) > 1:
            names = ", ".join(_row_label(rows[i], keys) for i in hits)
            raise SlotError(raw, f"{slot.key!r} matches {len(hits)} rows of {slot.eid}: name one of {names}")
        row_i, value = hits[0], rows[hits[0]].get(slot.field)
    return row_i, value


def resolve(slot: Slot, evidence: dict) -> Bound:
    """The value a slot names, formatted; SlotError with the fix otherwise (a null is refused: the Writer says
    'not available' in words)."""
    raw = slot.raw
    row_i, value = locate(slot, evidence)
    if value is None:
        raise SlotError(raw, f"{slot.field} is null in {slot.eid} (not available this week): write 'not available' "
                             "without a slot")
    kind = field_kind(slot.field, value)
    if kind is None:
        raise SlotError(raw, f"{slot.field} is not a number ({value!r}): copy it as text")
    fmt = slot.fmt or FORMATS[kind][0]
    if fmt not in FORMATS[kind]:
        raise SlotError(raw, f"format {fmt!r} not allowed for {slot.field} ({kind}): use "
                             f"{' or '.join(FORMATS[kind])}")
    if slot.direction and not is_change(slot.field):
        raise SlotError(raw, f"|dir only on a change field (wow, change, variance, difference), not {slot.field}")
    return Bound(slot, row_i, value, kind, fmt, format_value(slot.field, value, fmt, slot.direction))


def binding(eid: str, field: str, fmt: str | None = None, row: str | None = None, direction: bool = False) -> str:
    """The slot text of a code-rendered value (a tile, a table cell): the same syntax the Writer uses."""
    return "{" + eid + (f"[{row}]" if row is not None else "") + f":{field}" + (f"|{fmt}" if fmt else "") \
        + ("|dir" if direction else "") + "}"


def bound_text(slot_text: str, evidence: dict) -> str:
    """The text of a code-rendered binding; a null is "n/a" (deck-style-guide: WoW not available)."""
    s = find_slots(slot_text)
    if len(s) != 1 or s[0].raw != slot_text:
        raise SlotError(slot_text, "not one slot")
    _, value = locate(s[0], evidence)
    return format_value(s[0].field, value, s[0].fmt, s[0].direction)


def render_text(text: str, evidence: dict) -> tuple[str, list[Bound], list[SlotError]]:
    """Fill every slot of `text`. A slot that fails stays as written (and is reported); a brace left outside a slot
    is a malformed slot."""
    out, bound, errors, pos = [], [], [], 0
    for s in find_slots(text):
        out.append(text[pos:s.start])
        try:
            b = resolve(s, evidence)
            bound.append(b)
            out.append(b.text)
        except SlotError as exc:
            errors.append(exc)
            out.append(s.raw)
        pos = s.end
    out.append(text[pos:])
    rest = SLOT_RE.sub(" ", text)
    for bad in re.findall(r"\{[^{}]*\}?|\}", rest):
        errors.append(SlotError(bad, "malformed slot: write {<evidence id>[<row>]:<field>|<format>}"))
    return "".join(out), bound, errors
