"""The result every Stage 1 tool returns (Agents plan §3 "Structured outputs", §5a).

One shape for all tools so the Validator (Phase 6) and the deck's sources slide read every result the same way:
`status`, the rows, and the `source` (view / table / URL + the exact filter) that produced them. Kept shallow
(no unions, `Literal` statuses) because free providers support different JSON-schema subsets.
Invariants (checked on construction): only an `ok` result carries rows, and an `ok` result names its source —
a refused or failed call can never leak a number, and a number can never lack a source.
"""
from typing import Literal

from pydantic import BaseModel, Field, model_validator

Status = Literal["ok", "not_permitted", "context_unavailable", "no_data"]


class Source(BaseModel):
    kind: Literal["view", "table", "api", "documents"]
    name: str = Field(description="the view / table (schema.name) or the API endpoint")
    filter: str = Field(description="the exact filter that selected the rows, e.g. report_week = 23")
    retrieved_at: str | None = Field(default=None, description="external sources: when the data was fetched (UTC)")


class ToolResult(BaseModel):
    tool: str
    status: Status
    rows: list[dict] = Field(default_factory=list)
    source: Source | None = None
    note: str | None = Field(default=None, description="why there are no rows, or a caveat such as a warm-up week")

    @model_validator(mode="after")
    def _guard(self):
        if self.status != "ok" and self.rows:
            raise ValueError(f"{self.tool}: a '{self.status}' result must carry no rows")
        if self.status == "ok" and self.source is None:
            raise ValueError(f"{self.tool}: an ok result must name its source")
        return self
