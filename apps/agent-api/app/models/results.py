"""Schema for normalized search results."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SearchResult(BaseModel):
    """A normalized, ranked search result."""

    model_config = ConfigDict(extra="forbid")

    id: str
    type: str = Field(description="Entity type, e.g. consultant, project, opportunity.")
    title: str
    snippet: str = ""
    score: float = Field(ge=0.0, le=1.0, default=0.0)
    source_tool: str
    data: dict[str, object] = Field(default_factory=dict)
