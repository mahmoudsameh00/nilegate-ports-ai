"""Structured outputs of the `weekly_pack` graph (Agents plan §3 "Structured outputs", §5b P5-2, P5-4).

One class serves the LLM (`with_structured_output`), the graph state (stored as `model_dump(mode="json")`, so every
checkpoint is plain data), the Validator and the tests. Kept shallow — at most two levels of objects, `Literal`
instead of enums, no unions — because free providers support different JSON-schema subsets (ADR-045, bake-off T3).
Format rules live here (slide range, evidence-id shape, non-empty text); content rules (five summary bullets, every
number from a tool) belong to the Validator, so a broken draft comes back as a readable diff, not as a parse error.

Evidence ids name a tool result kept in the state: `kpi.<dataset>`, `audit.week`, `insight.<tool_call_id>`.
"""
import re
from typing import Literal

from pydantic import BaseModel, Field, model_validator

EVIDENCE_ID = r"^(kpi|audit|insight)\.[A-Za-z0-9_.:-]+$"
SLIDES = 10                                   # deck-style-guide: ten slides in a fixed order


class Cited(BaseModel):
    text: str = Field(min_length=1, description="one sentence; every number in it copied from the cited evidence")
    evidence_ids: list[str] = Field(default_factory=list,
                                    description="ids of the tool results the sentence's numbers come from")

    @model_validator(mode="after")
    def _ids(self):
        bad = [e for e in self.evidence_ids if not re.match(EVIDENCE_ID, e)]
        if bad:
            raise ValueError(f"evidence ids must look like kpi.weekly / audit.week / insight.<id>: {bad}")
        return self


# --- Insight ------------------------------------------------------------------------------------------------------

class Driver(BaseModel):
    vessel_category: str = Field(description="a category among the week's top 3 by |billed_wow_change_sdr|")
    direction: Literal["up", "down"] = Field(description="the sign of billed_wow_change_sdr (budget variance in week 1)")
    flagged_by_audit: bool = Field(description="true if an invoice of this category has an audit finding this week")
    explanation: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)


class InsightNotes(BaseModel):
    """What changed, by how much and why (skill `weekly-variance-analysis`), for the Report Writer."""
    summary: list[Cited] = Field(description="the 5 executive-summary bullets, in the skill's order")
    drivers: list[Driver] = Field(default_factory=list, description="at most 3")
    context: list[Cited] = Field(default_factory=list,
                                 description="external context (Suez transits, news, tariff rules), kept apart "
                                             "from NileGate's numbers; 'context unavailable' when a tool said so")
    caveats: list[str] = Field(default_factory=list, description="warm-up week, flagged invoices, missing context")


# --- Deck draft -----------------------------------------------------------------------------------------------------

class SlideTitle(BaseModel):
    slide: int = Field(ge=1, le=SLIDES)
    title: str = Field(min_length=1, description="states the finding, not the topic")


class Bullet(Cited):
    slide: int = Field(ge=1, le=SLIDES, description="1 title … 10 sources, as in the deck style guide")


class DeckDraft(BaseModel):
    """The deck as text with number slots (Phase 6, §5c); `pipelines/agents/deck/render.py` renders it into the
    NileGate PPTX template."""
    title: str = Field(min_length=1, description='"NileGate Weekly Finance Pack — <week> — Draft for approval"')
    slide_titles: list[SlideTitle] = Field(description="one title per slide, slides 1 to 10")
    bullets: list[Bullet] = Field(description="every bullet of slides 2 to 9, in slide order")


class Fix(BaseModel):
    target: Literal["bullet", "slide_title", "title"]
    index: int = Field(ge=0, description="bullet: its index in DeckDraft.bullets; slide_title: the slide number; "
                                         "title: 0")
    text: str = Field(min_length=1, description="the whole new text, numbers as slots")
    evidence_ids: list[str] = Field(default_factory=list, description="bullets only: the ids its numbers come from")

    @model_validator(mode="after")
    def _ids(self):
        bad = [e for e in self.evidence_ids if not re.match(EVIDENCE_ID, e)]
        if bad:
            raise ValueError(f"evidence ids must look like kpi.weekly / audit.week / insight.<id>: {bad}")
        return self


class DeckPatch(BaseModel):
    """A rewrite after the Validator (§5c, P6-6): replacements for the failing texts only; code merges them."""
    fixes: list[Fix] = Field(description="one replacement per failing text")


# --- Validator ------------------------------------------------------------------------------------------------------

class Problem(BaseModel):
    # V1 citation, V2 number, V3 draft label, V4 deck shape; Phase 6 (§5c): V5 evidence per slide, V6 direction,
    # V7 attribution, V8 the rendered PPTX
    rule: Literal["V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8"]
    slide: int | None = None
    bullet: int | None = Field(default=None, description="index of the bullet in DeckDraft.bullets")
    token: str | None = Field(default=None, description="the number token that failed, if any")
    message: str


class Verdict(BaseModel):
    passed: bool
    problems: list[Problem] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistent(self):
        if self.passed == bool(self.problems):
            raise ValueError("a verdict passes exactly when it has no problems")
        return self


# --- Approval (the interrupt's resume value) ------------------------------------------------------------------------

class Edit(BaseModel):
    bullet: int = Field(ge=0, description="index in DeckDraft.bullets")
    text: str = Field(min_length=1)


class ApprovalDecision(BaseModel):
    decision: Literal["approve", "edit", "reject"]
    approver_employee_id: int = Field(ge=1, description="checked in PostgreSQL: a Finance manager or the CEO")
    edits: list[Edit] = Field(default_factory=list)
    comment: str | None = None

    @model_validator(mode="after")
    def _edits(self):
        if (self.decision == "edit") != bool(self.edits):
            raise ValueError("edits are given exactly when the decision is 'edit'")
        return self


# --- Finance Q&A (Agents plan Phase 7, §5d P7-1: `graphs/finance_qa.py`) --------------------------------------------

class QaAnswer(BaseModel):
    """The answer to one finance question: numbers as slots (deck/slots.py), the evidence they come from."""
    status: Literal["answered", "not_in_data", "not_permitted"] = Field(description=(
        "answered = the tools gave the answer; not_in_data = the data or documents do not hold it; not_permitted = "
        "a tool refused this user's access"))
    answer: str = Field(min_length=1, max_length=1500, description=(
        "the answer in the question's language, two to four sentences; every NileGate number written as a slot"))
    evidence_ids: list[str] = Field(default_factory=list, description="ids of the tool results the answer uses")

    @model_validator(mode="after")
    def _ids(self):
        bad = [e for e in self.evidence_ids if not re.match(EVIDENCE_ID, e)]
        if bad:
            raise ValueError(f"evidence ids look like insight.<id> (from the evidence list): {bad}")
        return self


class SupervisorAnswer(QaAnswer):
    """The answer of the supervisor over both products (Agents plan Phase 12, §6d P12-3): `partial` = the permitted
    parts answered and the refused part named (which part is refused is decided by code, never by the model)."""
    status: Literal["answered", "partial", "not_in_data", "not_permitted"] = Field(description=(
        "answered = the tools gave the whole answer; partial = the permitted parts answered and the part listed as "
        "not permitted named, without its figures; not_in_data = the data does not hold it; not_permitted = nothing "
        "asked is permitted to this user"))
    answer: str = Field(min_length=1, max_length=2000, description=(
        "the answer in the question's language, two to six sentences; every NileGate number written as a slot"))


# --- Route advice (Agents plan Phase 10, §6b: `graphs/route_advice.py`) ---------------------------------------------

ROUTE_EVIDENCE_ID = r"^route\.[a-z_]+$"
ROUTES = ("suez", "cape")
ROUTE_STATUSES = ("ok", "no_suez_on_route", "suez_only", "not_permitted", "no_data", "output_invalid",
                  "validation_failed")


class RouteRequest(BaseModel):
    """One question: a vessel (one of ours, or a hypothetical one) and a voyage; the clock comes from the run context."""
    vessel_id: int | None = Field(default=None, ge=1)
    vessel_type: str | None = None
    condition: Literal["Laden", "Ballast"] | None = None
    scnt_tons: float | None = Field(default=None, gt=0)
    origin: str = Field(pattern=r"^[A-Z]{2}[A-Z2-9]{3}$")
    destination: str = Field(pattern=r"^[A-Z]{2}[A-Z2-9]{3}$")
    speed_kn: float | None = Field(default=None, ge=4, le=25)

    @model_validator(mode="after")
    def _vessel(self):
        hypothetical = [self.vessel_type, self.condition, self.scnt_tons]
        if self.vessel_id is None and any(v is None for v in hypothetical):
            raise ValueError("give vessel_id, or vessel_type + condition + scnt_tons")
        if self.vessel_id is not None and any(v is not None for v in hypothetical):
            raise ValueError("give vessel_id alone, or the hypothetical vessel, not both")
        if self.origin == self.destination:
            raise ValueError("origin and destination must differ")
        return self


class RouteReason(BaseModel):
    text: str = Field(min_length=1, max_length=400, description="one sentence; every number written as a slot")
    evidence_ids: list[str] = Field(default_factory=list, description="ids of the route.* results it uses")

    @model_validator(mode="after")
    def _ids(self):
        bad = [e for e in self.evidence_ids if not re.match(ROUTE_EVIDENCE_ID, e)]
        if bad:
            raise ValueError(f"evidence ids look like route.compare / route.difference / route.news: {bad}")
        return self


class RouteAdvice(BaseModel):
    """What the advisor writes (skill `route-cost-advice`): the choice, a headline and the reasons, numbers as slots;
    the comparison table, the assumptions and the sources are written by code."""
    recommendation: Literal[ROUTES] = Field(description="suez or cape")
    headline: str = Field(min_length=1, max_length=300, description="one sentence: the choice and its main reason")
    reasons: list[RouteReason] = Field(min_length=1, max_length=5, description="cost, time and risk reasons")
    risks: list[RouteReason] = Field(default_factory=list, max_length=4,
                                     description="external context only (route.traffic, route.news): no NileGate "
                                                 "number; 'context unavailable' when a tool said so")


class RouteAdviceResult(BaseModel):
    """The answer the graph returns and keeps in its checkpoint (one thread per question, P10-3)."""
    status: Literal[ROUTE_STATUSES]
    request: dict
    as_of: str
    comparison: list[dict] = Field(default_factory=list, description="route.compare rows (+ the difference row)")
    recommendation: Literal[ROUTES] | None = None
    headline: str | None = None
    reasons: list[str] = Field(default_factory=list, description="rendered: slots filled by code")
    risks: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    sources: list[dict] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)


# --- Voyage watch (Agents plan Phase 11, §6c: `graphs/voyage_watch.py`) ---------------------------------------------

ALERT_ID = r"^\d+/(weather|suez_traffic)$"
WATCH_STATUSES = ("ok", "no_data", "not_permitted")
BRIEF_STATUSES = ("ok", "no_alerts", "output_invalid", "validation_failed")


class WatchRequest(BaseModel):
    """One watch run; the clock comes from the run context. `vessel_ids` = a subset (the checks); None = the fleet."""
    vessel_ids: list[int] | None = Field(default=None, min_length=1, max_length=500)


class WatchItem(BaseModel):
    text: str = Field(min_length=1, max_length=400, description="one sentence; every number written as a slot")
    # a Suez traffic drop is a fleet-wide event: one sentence may cite every vessel with the canal ahead (D-P11-1)
    alert_ids: list[str] = Field(min_length=1, max_length=60,
                                 description="the alerts this sentence is about, e.g. 36/weather, 112/suez_traffic; "
                                             "one Suez traffic sentence may list every suez_traffic alert")

    @model_validator(mode="after")
    def _ids(self):
        bad = [a for a in self.alert_ids if not re.match(ALERT_ID, a)]
        if bad:
            raise ValueError(f"alert ids look like <vessel_id>/weather or <vessel_id>/suez_traffic: {bad}")
        return self


class WatchBrief(BaseModel):
    """What the brief writer returns (skill `voyage-watch-brief`): a headline and up to six items about the alerts,
    numbers as slots; the alert table, the ETAs, the assumptions and the sources are written by code."""
    headline: str = Field(min_length=1, max_length=300, description="one sentence: how many vessels are at risk and "
                                                                    "the most serious alert")
    items: list[WatchItem] = Field(min_length=1, max_length=6, description="every high alert first, then moderate")


class VoyageWatchResult(BaseModel):
    """What one watch run returns and saves (the thread's checkpoint + the run file, P11-5)."""
    status: Literal[WATCH_STATUSES]
    as_of: str
    fleet: dict = Field(default_factory=dict, description="watch.fleet: counts by status, alerts, weather points")
    etas: list[dict] = Field(default_factory=list, description="one row per vessel at sea / at anchor")
    alerts: list[dict] = Field(default_factory=list, description="watch.alerts rows, high first")
    brief_status: Literal[BRIEF_STATUSES] | None = None
    headline: str | None = None
    items: list[dict] = Field(default_factory=list, description="rendered: slots filled by code, with alert ids")
    assumptions: list[str] = Field(default_factory=list)
    sources: list[dict] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)
    run_file: str | None = None
