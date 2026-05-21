"""Schemas for interpreted intent and execution plan steps."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class InterpretedIntent(BaseModel):
    """Structured interpretation of a natural-language search query."""

    model_config = ConfigDict(extra="forbid")

    objective: str = Field(description="High-level goal extracted from the query.")
    entities: list[str] = Field(
        default_factory=list,
        description="Entities like skills, roles, technologies, locations.",
    )
    constraints: dict[str, str] = Field(
        default_factory=dict,
        description="Structured constraints such as seniority, availability, duration.",
    )
    ambiguity_notes: list[str] = Field(
        default_factory=list,
        description="User-visible notes about ambiguous parts of the query.",
    )


class PlanStep(BaseModel):
    """A single bounded step in the execution plan."""

    model_config = ConfigDict(extra="forbid")

    step: int = Field(ge=1, description="1-based step ordinal.")
    description: str = Field(description="Human-readable description of the step.")
    expected_tool: str | None = Field(
        default=None, description="Suggested MCP tool name for this step."
    )
    inputs: dict[str, object] = Field(
        default_factory=dict, description="Suggested tool inputs for this step."
    )
