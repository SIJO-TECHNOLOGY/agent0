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
        default=None, description="Preferred MCP tool name for this step."
    )
    alternative_tools: list[str] = Field(
        default_factory=list,
        description=(
            "Fallback MCP tool names tried in order when `expected_tool` is "
            "not in the discovered tool catalogue."
        ),
    )
    inputs: dict[str, object] = Field(
        default_factory=dict, description="Suggested tool inputs for this step."
    )


class PlannedToolCall(BaseModel):
    """A single LLM-proposed MCP tool call.

    The shape is intentionally narrow so the LLM cannot embed
    free-form execution semantics. ``depends_on`` and
    ``result_selector`` express bounded fan-out only: "for each
    candidate id returned by the named prior tool, call me once".
    """

    model_config = ConfigDict(extra="forbid")

    tool_name: str = Field(description="Name of a discovered MCP tool.")
    reason: str = Field(
        default="",
        description="Short rationale the LLM proposes for the call.",
    )
    inputs: dict[str, object] = Field(
        default_factory=dict,
        description=(
            "Inputs passed verbatim to the tool; validated against the "
            "tool's input_schema before execution."
        ),
    )
    depends_on: str | None = Field(
        default=None,
        description=(
            "Name of an earlier planned tool whose results provide the "
            "fan-out keys (typically searchCandidates → candidate ids)."
        ),
    )
    result_selector: str | None = Field(
        default=None,
        description=(
            "How to extract fan-out keys from the prior tool's results. "
            "Currently only 'candidate_ids' is recognised."
        ),
    )


class LlmToolPlan(BaseModel):
    """Top-level LLM planning output.

    The agent passes this through a strict validator before any tool
    runs: unknown tools, schema-violating inputs, missing required
    fields, and over-long plans are rejected.
    """

    model_config = ConfigDict(extra="forbid")

    interpreted_intent: dict[str, object] = Field(
        default_factory=dict,
        description="Free-form structured summary of what the LLM understood.",
    )
    plan: list[PlannedToolCall] = Field(
        default_factory=list,
        description="Ordered tool calls the executor should run.",
    )
    assumptions: list[str] = Field(
        default_factory=list,
        description="Plain-text assumptions the LLM made about the query.",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="LLM-emitted caveats; surfaced as agent warnings.",
    )
