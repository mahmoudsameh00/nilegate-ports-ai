"""Validator v2 of the weekly deck (Agents plan §5c, Phase 6): every number bound to its field (G1).

The Phase 5 Validator accepted a number equal to **any** numeric field of the cited evidence, so a category's value
under another category's name passed. Here every number is bound to one (evidence, row, field):
- a **slot** (`deck/slots.py`) is bound by construction; the check is that the sentence calls it what it is;
- a **literal** number (a human edit, or a Writer that typed one) is bound by search: it must equal, after an allowed
  rounding (number-validation rule 2), a field of a row the sentence names (the nearest category / customer / invoice
  named before it; a one-row result is always named), with the sign it claims, under a word of its field's family.

Rules (the problem list is the diff the Writer gets back, one line per fix):
- V1 cited evidence exists and has data; a literal number needs a citation.
- V2 a slot resolves (`slots.resolve`); a literal number binds to a named row's field with its sign (an unsigned
  number after "down" / "fell" / … is negative, P6-3); otherwise the hint names where that value does live.
- V3 the draft label in the title. V4 the deck's shape (P6-2: ten slide titles, five summary bullets, at most three
  comments on slides 3–8, at least one context line on slide 9, no Writer bullet on slides 1 and 10).
- V5 a bullet cites (and its slots use) only the evidence allowed on its slide.
- V6 direction (G1): a direction word next to a change value (WoW, change, variance, difference) agrees with its sign.
- V7 attribution (G1): a number sits under a word of its field's family (billed / collected / AR / overdue / DSO /
  budget / share) and a slot's row is the row the sentence names; a category called a driver is among the week's top
  three by |WoW change| (week 1: |budget variance|); an invoice number written exists in the evidence.
V8 (the PPTX read back) lives with the renderer (S3).
"""
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from pipelines.agents.deck import slots
from pipelines.agents.graphs import models as m

REPORT_YEAR = 2025                                    # D12: replay of 2025's 52 ISO weeks
DRAFT_LABEL = "Draft for approval"
SUMMARY_BULLETS, MAX_COMMENTS = 5, 3
CODE_SLIDES = (1, 10)                                  # rendered by code only (P6-2)
COMMENT_SLIDES = range(3, 9)
CONTEXT_SLIDE = 9
NILEGATE_TOOLS = {"finance_kpi", "invoice_audit", "compute_toll"}   # NileGate's own data (ADR-049), never context
# evidence a slide may cite (§5c table); "x.*" = every id with that prefix
SLIDE_EVIDENCE = {1: ("kpi.weekly",), 2: ("kpi.*", "audit.week", "insight.*"), 3: ("kpi.weekly",),
                  4: ("kpi.trend", "kpi.category", "audit.week"), 5: ("kpi.category",),
                  6: ("kpi.weekly", "kpi.overdue"), 7: ("kpi.customers", "kpi.weekly"), 8: ("audit.week",),
                  9: ("insight.*",), 10: ()}

# --- number tokens (the Phase 5 rules, kept) -------------------------------------------------------------------------
NUM_RE = re.compile(r"(?<![\w.])([+\-−])?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(?:\s?(%|k\b|M\b))?")
# Writer prose with digits that is not a tool number: aging bucket names, the warm-up footnote, 13-week, top 10.
# (Code-rendered template text is checked by shape name in V8, not here.)
TEMPLATE_RE = re.compile(r"(?i)receivables still building up since 1 jan(?:uary)? 2025"
                         r"|\b(?:1|31|61)\s?(?:[-–]|to)\s?(?:30|60|90)(?:\s?days)?\b|\b90\s?\+|\b90 plus\b"
                         r"|\bover 90 days\b|\b13[- ]weeks?\b|\btop[- ]10\b")
_MON = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
DATE_RE = re.compile(rf"(?i)\b\d{{4}}-\d{{2}}-\d{{2}}(?:[T ]\d{{2}}:\d{{2}}(?::\d{{2}})?Z?)?\b"
                     rf"|\b\d{{1,2}}\s{_MON},?\s\d{{4}}\b|\b{_MON}\s\d{{1,2}},?\s\d{{4}}\b|\b{_MON}\s\d{{4}}\b"
                     rf"|\b\d{{2}}:\d{{2}}(?::\d{{2}})?\s?(?:gmt|utc)?\b")
INVOICE_RE = re.compile(r"\bINV-\d{7}\b")

# --- words ----------------------------------------------------------------------------------------------------------
# field families and the words that name them; alternation order matters (the longest phrase wins at a position)
FAMILY_WORDS = [
    ("share", r"top[- ]?(?:10|ten)(?: share)?|share|concentration"
              r"|of (?:the )?(?:total |13-week |trailing 13-week )?(?:billings?|revenues?)"),
    ("dso", r"dso|days sales outstanding"),
    ("overdue", r"overdue|past due|late payments?"),
    ("collected", r"collect(?:ed|ions?|ing)?|payments? received|received"),
    ("budget", r"budget(?:ed)?|planned|plan|target|variance"),
    ("ar", r"receivables?|\bar\b|outstanding|aging|ageing|buckets?"),
    # the week's drivers are billing changes by definition (weekly-variance-analysis step 3)
    ("billed", r"bill(?:ed|ing|ings)?|revenues?|invoiced|issued|turnover|drivers?"),
]
FAMILY_RE = re.compile("|".join(f"(?P<{f}>\\b(?:{w}))" for f, w in FAMILY_WORDS), re.I)
NEG_WORDS = (r"down|fell|fall(?:s|en|ing)?|decreas(?:e|ed|es|ing)|declin(?:e|ed|es|ing)|drop(?:ped|s)?|lower"
             r"|below|shr[ai]nk(?:s)?|shrunk|contract(?:ed|ion)|slipped")
POS_WORDS = (r"up|rose|ris(?:e|es|en|ing)|increas(?:e|ed|es|ing)|grew|grow(?:n|s|th|ing)?|higher|above"
             r"|gain(?:ed|s)?|climb(?:ed|s)?|jump(?:ed|s)?")
DIR_RE = re.compile(rf"\b(?:(?P<neg>{NEG_WORDS})|(?P<pos>{POS_WORDS}))\b", re.I)
# after a number only the comparatives describe it ("45.62 % above budget", "3.1 % lower"); a verb after it starts
# the next phrase ("Collected 0.96 M SDR, down 12.3 %": "down" is the next number's)
SUFFIX_DIR_RE = re.compile(r"\b(?:(?P<neg>below|lower|less)|(?P<pos>above|higher|more))\b", re.I)
DRIVER_RE = re.compile(r"\b(?:driv\w*|drove)\b", re.I)
WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]*")
SENTENCE_END_RE = re.compile(r"[.;!?](?=\s|$)")
CONNECTOR_RE = re.compile(r"^[\s,()]*(?:SDR\b)?[\s,()]*(?:or|and)?[\s,()]*$")
# a window never crosses a clause: before = after the last comma / semicolon; after = up to the next one or a
# conjunction ("…, down 15.8 % week-on-week, while AR invoices …": "AR" is not the 15.8 %'s)
CLAUSE_BEFORE_RE = re.compile(r"[,;]")
CLAUSE_AFTER_RE = re.compile(r"[,;(]|\b(?:and|while|but|whereas)\b", re.I)
WINDOW_WORDS = 4
UNIT_AFTER_RE = re.compile(r"\s*(SDR\b|%|days?\b)")     # a unit written again right after a slot


def field_families(field: str) -> set[str]:
    """Every family a field's name belongs to: `dso_window_billed_sdr` is DSO and billing (S6: a real sentence
    "a DSO window billed amount of …" was refused when only the first family counted)."""
    fams = {f for f in (field_family(field),) if f}
    if "billed" in field:
        fams.add("billed")
    if "budget" in field:
        fams.add("budget")
    return fams


def field_family(field: str) -> str | None:
    if field.startswith("dso"):
        return "dso"
    if "share" in field:
        return "share"
    if field.startswith("budget"):
        return "budget"
    if field.startswith("overdue") or field == "days_past_due":
        return "overdue"
    if field.startswith(("ar_", "aging")):
        return "ar"
    if field.startswith("collected") or field == "payments_received":
        return "collected"
    if "billed" in field:
        return "billed"
    return None


def _quant(v: Decimal, d: int) -> Decimal:
    return v.quantize(Decimal(1).scaleb(-d), rounding=ROUND_HALF_UP)   # half away from zero


def number_tokens(text: str, strings: list[str]) -> list[tuple[str, Decimal, int, str | None]]:
    """(token, signed value, decimals, suffix) of every number in `text` after the template text, dates and the
    given identifier strings are blanked."""
    text = DATE_RE.sub(" ", TEMPLATE_RE.sub(" ", text))
    for s in strings:
        text = text.replace(s, " ")
    out = []
    for mt in NUM_RE.finditer(text):
        sign, whole, frac, suffix = mt.groups()
        val = Decimal(whole.replace(",", "") + (f".{frac}" if frac else ""))
        out.append((mt.group(0).strip(), -val if sign in ("-", "−") else val, len(frac or ""), suffix))
    return out


def number_matches(value: Decimal, decimals: int, suffix: str | None, candidate) -> bool:
    """`value` written with `decimals` and `suffix` is an allowed rounding of `candidate` (number-validation 2)."""
    c = Decimal(str(candidate))
    if suffix == "M":
        return decimals == 2 and _quant(c / 10 ** 6, 2) == value
    if suffix == "k":
        return decimals == 1 and _quant(c / 10 ** 3, 1) == value
    if suffix == "%":
        return (decimals in (1, 2) and _quant(c, decimals) == value) or c == value
    return c == value


def _sign(v) -> int:
    return (v > 0) - (v < 0)


def allowed_on(eid: str, slide: int) -> bool:
    return any(eid == p or (p.endswith("*") and eid.startswith(p[:-1])) for p in SLIDE_EVIDENCE.get(slide, ()))


def _strings(res: dict) -> list[str]:
    """Identifiers, dates and labels of a structured result (blanked before numbers are read)."""
    if res.get("tool") not in slots.NUMERIC_TOOLS:
        return []           # document / web text gives neither numbers nor blankable strings (ADR-049)
    vals = [v for r in res.get("rows") or [] for v in r.values()]
    vals += [v for k, v in res.items() if k not in slots.RESULT_FIELDS_SKIP]
    return [v for v in vals if isinstance(v, str) and re.search(r"\d", v)]


def _blank(text: str, spans) -> str:
    chars = list(text)
    for s, e in spans:
        chars[s:e] = " " * (e - s)
    return "".join(chars)


@dataclass
class Item:
    start: int
    end: int
    token: str
    origin: str                       # slot | literal
    value: Decimal | None = None      # the bound field's value
    eid: str | None = None
    row: int | None = None
    field: str | None = None
    dir_sign: int | None = None       # sign claimed by a direction word (literals) or written by |dir (slots)
    mag: Decimal | None = None        # literals: the written magnitude, its decimals, suffix and explicit sign
    decimals: int = 0
    suffix: str | None = None
    explicit: int | None = None


# --- context windows ------------------------------------------------------------------------------------------------

def _sentence(bounds: list[int], pos: int) -> tuple[int, int]:
    start = max([b for b in bounds if b <= pos], default=0)
    end = min([b for b in bounds if b > pos], default=10 ** 9)
    return start, end


def _last_words(seg: str, n: int) -> str:
    ws = list(WORD_RE.finditer(seg))
    return seg[ws[-n].start():] if len(ws) > n else seg


def _first_words(seg: str, n: int) -> str:
    ws = list(WORD_RE.finditer(seg))
    return seg[:ws[n - 1].end()] if len(ws) > n else seg


def _families(seg: str) -> set[str]:
    return {mt.lastgroup for mt in FAMILY_RE.finditer(seg)}


def _group_before(text: str, sent_start: int, pos: int) -> set[str]:
    """The family words of the last noun phrase before `pos`: the last family word and those just before it
    ("Collected revenue" → collected + billed)."""
    hits = list(FAMILY_RE.finditer(text, sent_start, pos))
    if not hits:
        return set()
    group = [hits[-1]]
    for h in reversed(hits[:-1]):
        if group[-1].start() - h.end() > 12:
            break
        group.append(h)
    return {h.lastgroup for h in group}


def _dirs(seg: str, regex=DIR_RE) -> list[int]:
    return [-1 if mt["neg"] else 1 for mt in regex.finditer(seg)]


# --- one text (a bullet, a slide title, the deck title) -------------------------------------------------------------

class _Text:
    def __init__(self, text: str, evidence: dict, cited: list[str], report_week: int):
        self.evidence, self.cited, self.week = evidence, cited, report_week
        self.problems: list[tuple[str, str | None, str]] = []          # (rule, token, message)
        out, items, pos, failed = [], [], 0, []
        for s in slots.find_slots(text):
            out.append(text[pos:s.start])
            at = sum(len(x) for x in out)
            try:
                b = slots.resolve(s, evidence)
                out.append(b.text)
                items.append(Item(at, at + len(b.text), s.raw, "slot", Decimal(str(b.value)), s.eid, b.row,
                                  s.field, _sign(b.value) if s.direction else None))
            except slots.SlotError as exc:
                out.append(s.raw)
                failed.append((at, at + len(s.raw)))       # never read as literal numbers ("|%1")
                self.problems.append(("V2", s.raw, exc.message))
            pos = s.end
        out.append(text[pos:])
        self.text = "".join(out)
        for bad in re.findall(r"\{[^{}]*\}?|\}", slots.SLOT_RE.sub(" ", text)):
            self.problems.append(("V2", bad, "malformed slot: write {<evidence id>[<row>]:<field>|<format>}"))
        self.slot_items = items
        self.bounds = [0] + [mt.end() for mt in SENTENCE_END_RE.finditer(self.text)]
        # literal tokens: slots, template text, dates and the cited identifiers blanked (same length: positions kept)
        spans = [(i.start, i.end) for i in items] + failed
        spans += [mt.span() for mt in TEMPLATE_RE.finditer(self.text)] + [mt.span() for mt in DATE_RE.finditer(self.text)]
        ids = sorted({s for e in self._ok(cited) for s in _strings(evidence[e])}, key=len, reverse=True)
        for s in ids:
            spans += [(mt.start(), mt.end()) for mt in re.finditer(re.escape(s), self.text)]
        blanked = _blank(self.text, spans)
        self.literals = []
        for mt in NUM_RE.finditer(blanked):
            sign, whole, frac, suffix = mt.groups()
            if not suffix and not frac and not sign and int(whole.replace(",", "")) in (report_week, REPORT_YEAR):
                continue                                    # the run's week and year
            mag = Decimal(whole.replace(",", "") + (f".{frac}" if frac else ""))
            self.literals.append(Item(mt.start(), mt.end(), mt.group(0).strip(), "literal", mag=mag,
                                      decimals=len(frac or ""), suffix=suffix,
                                      explicit=None if sign is None else (1 if sign == "+" else -1)))
        self.items = sorted(items + self.literals, key=lambda i: i.start)

    def _ok(self, ids):
        return [e for e in ids if (self.evidence.get(e) or {}).get("status") == "ok"]

    # windows around an item: up to WINDOW_WORDS words, never across another number or the sentence end
    def _windows(self, k: int) -> tuple[str, str, int, int]:
        it = self.items[k]
        s0, s1 = _sentence(self.bounds, it.start)
        prev_end = max(s0, self.items[k - 1].end if k else 0)
        next_start = min(s1, self.items[k + 1].start if k + 1 < len(self.items) else len(self.text))
        before = CLAUSE_BEFORE_RE.split(self.text[prev_end:it.start])[-1]
        after = CLAUSE_AFTER_RE.split(self.text[it.end:next_start], maxsplit=1)[0]
        before, after = _last_words(before, WINDOW_WORDS), _first_words(after, WINDOW_WORDS)
        return before, after, s0, prev_end

    def _direction(self, k: int, before: str, after: str, prev_end: int) -> int | None:
        b, a = _dirs(before), _dirs(after, SUFFIX_DIR_RE)
        if b:
            return b[-1]
        if a:
            return a[0]
        if k and CONNECTOR_RE.match(self.text[self.items[k - 1].end:self.items[k].start]):
            return self.items[k - 1].dir_sign                      # "down 1.07 M SDR or 60.3 %"
        return None

    def _family_ok(self, field: str, before: str, after: str, s0: int, start: int) -> bool:
        """The field's measure is named before it (its window, or the last noun phrase before it in the sentence) or
        right after it ("45.62 % above budget"). S6 run 3: "billed … reached {billed} against a budget of {budget}"
        was refused when the after-window's "budget" (the next slot's) outvoted the "Billed" before it."""
        fams = field_families(field)
        if not fams:
            return True
        return bool(fams & (_families(before) | _group_before(self.text, s0, start) | _families(after)))

    def _clause(self, start: int) -> tuple[int, int]:
        """The clause around `start`: between the previous / next number, cut at commas, semicolons, conjunctions."""
        k = next(i for i, it in enumerate(self.items) if it.start == start)
        it = self.items[k]
        s0, s1 = _sentence(self.bounds, it.start)
        lo = max(s0, self.items[k - 1].end if k else 0)
        hi = min(s1, self.items[k + 1].start if k + 1 < len(self.items) else len(self.text))
        cuts = [mt.end() for mt in CLAUSE_BEFORE_RE.finditer(self.text, lo, it.start)]
        lo = cuts[-1] if cuts else lo
        nxt = CLAUSE_AFTER_RE.search(self.text, it.end, hi)
        return lo, (nxt.start() if nxt else hi)

    def _named_rows(self, eid: str, start: int, s0: int) -> list[int] | None:
        """Rows of a list result the sentence names for the number at `start`: a name in its own clause first (S6
        run 3: "{…} on 2025-03-03 and {…} on 2025-03-09" names each row after its number), else the nearest before,
        else the first after; None = a one-row result."""
        res = self.evidence[eid]
        keys = slots.row_keys(res)
        rows = res.get("rows") or []
        if not keys:
            return None
        s1 = _sentence(self.bounds, start)[1]
        hits = []
        for i, r in enumerate(rows):
            name = str(r.get(keys[0]))
            for mt in re.finditer(re.escape(name), self.text[s0:min(s1, len(self.text))]):
                hits.append((s0 + mt.start(), s0 + mt.end(), name))
        if not hits:
            return []
        lo, hi = self._clause(start)
        own = [h for h in hits if lo <= h[0] and h[1] <= hi]
        before = [h for h in hits if h[1] <= start]
        if own:
            name = min(own, key=lambda h: abs(h[0] - start))[2]
        else:
            name = max(before)[2] if before else min(hits)[2]
        return [i for i, r in enumerate(rows) if str(r.get(keys[0])) == name]

    def _candidates(self, start: int, s0: int):
        for eid in self._ok(self.cited):
            res = self.evidence[eid]
            if res.get("tool") not in slots.NUMERIC_TOOLS:
                continue
            for f, v in res.items():
                if f not in slots.RESULT_FIELDS_SKIP and slots.field_kind(f, v):
                    yield eid, None, f, v
            named = self._named_rows(eid, start, s0)
            rows = res.get("rows") or []
            for i in (range(len(rows)) if named is None else named):
                for f, v in rows[i].items():
                    if slots.field_kind(f, v):
                        yield eid, i, f, v

    def _hint(self, it: Item) -> str:
        """Where the written value does live (any structured evidence), for the Writer's fix."""
        found = []
        for eid, res in sorted(self.evidence.items()):
            if res.get("status") != "ok" or res.get("tool") not in slots.NUMERIC_TOOLS:
                continue
            keys = slots.row_keys(res)
            for r in res.get("rows") or []:
                for f, v in r.items():
                    if slots.field_kind(f, v) and number_matches(it.mag, it.decimals, it.suffix, abs(v)):
                        found.append(f"{eid}" + (f"[{r.get(keys[0])}]" if keys else "") + f":{f}")
        return f"; that value is {', '.join(found[:2])}" if found else ""

    def check(self) -> list[tuple[str, str | None, str]]:
        for k, it in enumerate(self.items):
            before, after, s0, prev_end = self._windows(k)
            if it.origin == "literal":
                it.dir_sign = self._direction(k, before, after, prev_end)
                if not self._ok(self.cited):
                    self.problems.append(("V1", it.token, "a number without cited evidence"))
                    continue
                self._bind(it, before, after, s0)
            else:
                self._check_slot(it, before, after, s0)
        self._drivers()
        self._invoices()
        return self.problems

    def _bind(self, it: Item, before: str, after: str, s0: int):
        sign_bad, family_bad = [], []
        for eid, row, f, v in self._candidates(it.start, s0):
            if not number_matches(it.mag, it.decimals, it.suffix, abs(v)):
                continue
            # a direction word gives the sign of a change only; "AR down to 47.6 M SDR" is a level, positive
            said = it.dir_sign if slots.is_change(f) else None
            claimed = it.explicit or said or 1
            sign_ok = (it.explicit is None and said is None) if v == 0 else claimed == _sign(v)
            fam_ok = self._family_ok(f, before, after, s0, it.start)
            if sign_ok and fam_ok:
                it.value, it.eid, it.row, it.field = Decimal(str(v)), eid, row, f
                self._direction_words(it, before, after)
                return
            (sign_bad if fam_ok else family_bad).append((eid, row, f, v))
        if sign_bad:
            eid, row, f, v = sign_bad[0]
            if it.dir_sign is not None and it.explicit is None:
                word = "down" if it.dir_sign < 0 else "up"
                self.problems.append(("V6", it.token, f"the text says {word} but {f} is {v}: use "
                                                      f"{{{eid}{self._key(eid, row)}:{f}|dir}}"))
            else:
                self.problems.append(("V2", it.token, f"the sign is wrong or missing: {f} is {v}"))
        elif family_bad:
            eid, row, f, v = family_bad[0]
            self.problems.append(("V7", it.token, self._family_message(it.token, f, s0)))
        else:
            self.problems.append(("V2", it.token, f"{it.token!r} is no field of the rows this sentence names in "
                                                  f"{', '.join(self.cited) or 'its evidence'} (allowed roundings "
                                                  f"only){self._hint(it)}"))

    def _family_message(self, token: str, f: str, s0: int) -> str:
        s1 = _sentence(self.bounds, s0)[1]
        fams = " / ".join(sorted(field_families(f)))
        if not _families(self.text[s0:s1]):
            return f"{token!r} is {f}: the sentence must say what it is ({fams})"
        return f"{token!r} is {f} ({fams}), but the sentence calls it something else"

    def _key(self, eid, row) -> str:
        keys = slots.row_keys(self.evidence[eid])
        return f"[{self.evidence[eid]['rows'][row].get(keys[0])}]" if keys and row is not None else ""

    def _direction_words(self, it: Item, before: str, after: str):
        if not slots.is_change(it.field):
            return
        s = _sign(it.value)
        for d in _dirs(before) + _dirs(after, SUFFIX_DIR_RE):
            if d != s:
                self.problems.append(("V6", it.token, f"a direction word disagrees with {it.field} = {it.value}"))
                return

    def _check_slot(self, it: Item, before: str, after: str, s0: int):
        if not self._family_ok(it.field, before, after, s0, it.start):
            self.problems.append(("V7", it.token, self._family_message(it.token, it.field, s0)
                                  + ": name it, or cite the field it means"))
        named = self._named_rows(it.eid, it.start, s0)
        if named and it.row not in named:
            row_name = self._key(it.eid, named[0]).strip("[]")
            res = self.evidence[it.eid]
            raw = res[it.field] if it.row is None else res["rows"][it.row][it.field]
            kind = slots.field_kind(it.field, raw)
            same = [f for f, v in res["rows"][named[0]].items() if slots.field_kind(f, v) == kind][:3]
            key = "/".join(str(res["rows"][named[0]].get(k)) for k in slots.row_keys(res))
            if it.row is None:      # a result total (e.g. the week's amount at stake) put on one row
                msg = f"{it.field} is the result's total, not {row_name}'s"
            else:
                msg = f"the slot's row is not the row the sentence names ({row_name})"
            hint = ", ".join(slots.binding(it.eid, f, None, key) for f in same)
            self.problems.append(("V7", it.token, msg + (f": cite {row_name}'s own field, e.g. {hint}" if hint
                                                         else "")))
        self._direction_words(it, before, after)
        if it.dir_sign is not None:   # the slot writes "up" / "down" itself: "up up 25.8 %" (S6 run 4, week 23)
            words = WORD_RE.findall(self.text[max(s0, it.start - 40):it.start])
            if words and DIR_RE.fullmatch(words[-1]):
                self.problems.append(("V2", it.token, f"the slot writes up / down itself (|dir): drop "
                                                      f"{words[-1]!r} before it"))
        unit = UNIT_AFTER_RE.match(self.text, it.end)
        written = self.text[it.start:it.end]
        if unit and written.rstrip("s").endswith(unit.group(1).rstrip("s")):   # "1.2 k SDR SDR", "45 days days"
            self.problems.append(("V2", it.token, f"the slot writes its unit itself: drop the extra "
                                                  f"{unit.group(1)!r} after it"))

    def _drivers(self):
        cat = self.evidence.get("kpi.category") or {}
        if cat.get("status") != "ok":
            return
        rows = cat["rows"]
        by = ("billed_wow_change_sdr" if any(r.get("billed_wow_change_sdr") is not None for r in rows)
              else "budget_variance_sdr")
        top = {r["vessel_category"] for r in sorted(rows, key=lambda r: -abs(r.get(by) or 0))[:3]}
        names = sorted({r["vessel_category"] for r in rows}, key=len, reverse=True)
        for s0, s1 in zip(self.bounds, self.bounds[1:] + [len(self.text)]):
            sent = self.text[s0:s1]
            if not DRIVER_RE.search(sent):
                continue
            rest = sent
            for n in names:
                if n in rest:
                    rest = rest.replace(n, " ")
                    if n not in top:
                        self.problems.append(("V7", n, f"{n} is not among the week's top three drivers by "
                                                       f"|{by}|"))

    def _invoices(self):
        known = {s for res in self.evidence.values() if res.get("status") == "ok" for s in _strings(res)}
        for inv in INVOICE_RE.findall(self.text):
            if inv not in known:
                self.problems.append(("V7", inv, f"{inv} is not in the week's evidence"))


def check_text(text: str, evidence: dict, cited: list[str], report_week: int) -> tuple[str, list]:
    """(rendered text, problems) of one text; problems = (rule, token, message)."""
    t = _Text(text, evidence, cited, report_week)
    return t.text, t.check()


# --- the deck -------------------------------------------------------------------------------------------------------

def validate(draft: dict, evidence: dict, report_week: int) -> m.Verdict:
    d = m.DeckDraft.model_validate(draft)
    problems: list[m.Problem] = []
    seen = set()

    def add(rule, message, slide=None, bullet=None, token=None):
        key = (rule, slide, bullet, token, message)
        if key not in seen:
            seen.add(key)
            problems.append(m.Problem(rule=rule, slide=slide, bullet=bullet, token=token, message=message))

    def on_slide(slide: int) -> list[str]:
        return [e for e in evidence if allowed_on(e, slide)]

    if DRAFT_LABEL not in d.title:
        add("V3", f'the title must say "{DRAFT_LABEL}"')
    for st in d.slide_titles:     # S6 run 4: slide 1's title copied the deck title, so the approved deck said "Draft"
        if DRAFT_LABEL in st.title or "NileGate Weekly Finance Pack" in st.title:
            add("V3", f"slide {st.slide}'s title repeats the deck title or its label (code draws them): state the "
                      "slide's finding", st.slide)
    # (text, slide whose evidence applies, slide reported — None for the deck title, bullet index)
    texts = [(d.title, 1, None, None, on_slide(1))] + [(st.title, st.slide, st.slide, None, on_slide(st.slide))
                                                       for st in d.slide_titles]
    for i, b in enumerate(d.bullets):
        unknown = [e for e in b.evidence_ids if (evidence.get(e) or {}).get("status") != "ok"]
        if unknown:
            add("V1", f"cites evidence that does not exist or has no data: {unknown}", b.slide, i)
        texts.append((b.text, b.slide, b.slide, i, list(b.evidence_ids)))
    for text, slide, where, bullet, cited in texts:
        used = list(dict.fromkeys(cited + [s.eid for s in slots.find_slots(text)]))
        off = [e for e in used if not allowed_on(e, slide)]
        if off:
            allowed = ", ".join(SLIDE_EVIDENCE[slide]) or "none (code renders this slide)"
            add("V5", f"slide {slide} may cite only {allowed}, not {off}", where, bullet)
        if slide == CONTEXT_SLIDE:
            # S6 week 10: a NileGate figure slotted on the context slide could not be fixed by two patches, because
            # the hint named kpi.weekly, which slide 9 may not cite — say what the fix is
            # what the text itself uses: its slots, and a bullet's own citations (a title "cites" the whole slide)
            own = [s.eid for s in slots.find_slots(text)] + (cited if bullet is not None else [])
            nilegate = sorted({s.field for s in slots.find_slots(text) if field_families(s.field)}
                              | {e for e in own if (evidence.get(e) or {}).get("tool") in NILEGATE_TOOLS})
            if nilegate:
                add("V5", f"slide 9 is external context only: no NileGate figure or result here ({nilegate}); drop "
                          "it and keep the line about Suez transits, news or tariff rules", where, bullet)
        for rule, token, message in check_text(text, evidence, used, report_week)[1]:
            add(rule, message, where, bullet, token)
    titles = sorted(st.slide for st in d.slide_titles)
    if titles != list(range(1, m.SLIDES + 1)):
        add("V4", f"one title per slide 1–{m.SLIDES} needed, got {titles}")
    per = {s: sum(1 for b in d.bullets if b.slide == s) for s in range(1, m.SLIDES + 1)}
    if per[2] != SUMMARY_BULLETS:
        add("V4", f"the executive summary needs five bullets, got {per[2]}", 2)
    for s in COMMENT_SLIDES:
        if per[s] > MAX_COMMENTS:
            add("V4", f"at most three comments on slide {s}, got {per[s]}", s)
    for s in CODE_SLIDES:
        if per[s]:
            add("V4", f"slide {s} is written by code: no bullets", s)
    if not per[CONTEXT_SLIDE]:
        add("V4", "slide 9 needs at least one context line (or 'context unavailable')", CONTEXT_SLIDE)
    return m.Verdict(passed=not problems, problems=problems)


def render_draft(draft: dict, evidence: dict) -> dict:
    """The draft with every slot filled (a failed slot stays as written): what the approver reads and the renderer
    lays out."""
    def fill(t):
        return slots.render_text(t, evidence)[0]
    return {**draft, "title": fill(draft["title"]),
            "slide_titles": [{**st, "title": fill(st["title"])} for st in draft["slide_titles"]],
            "bullets": [{**b, "text": fill(b["text"])} for b in draft["bullets"]]}
