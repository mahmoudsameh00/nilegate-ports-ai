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
    """The deck as text (Phase 5); Phase 6 renders it into the NileGate PPTX template."""
    title: str = Field(min_length=1, description='"NileGate Weekly Finance Pack — <week> — Draft for approval"')
    slide_titles: list[SlideTitle] = Field(description="one title per slide, slides 1 to 10")
    bullets: list[Bullet] = Field(description="every bullet of every slide, in slide order")


# --- Validator ------------------------------------------------------------------------------------------------------

class Problem(BaseModel):
    rule: Literal["V1", "V2", "V3", "V4"]   # V1 citation, V2 number, V3 draft label, V4 deck shape
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
