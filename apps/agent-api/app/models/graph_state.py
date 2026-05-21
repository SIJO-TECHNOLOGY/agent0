"""LangGraph state schema."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.models.errors import AgentError
from app.models.intent import InterpretedIntent, PlanStep
from app.models.results import SearchResult
from app.models.tools import McpTool, ToolCall
from app.models.warnings import Warning


class GraphState(BaseModel):
    """Typed state passed between LangGraph nodes."""

    model_config = ConfigDict(extra="forbid")

    original_query: str
    filters: dict[str, object] = Field(default_factory=dict)

    interpreted_intent: InterpretedIntent | None = None
    execution_plan: list[PlanStep] = Field(default_factory=list)
    available_tools: list[McpTool] = Field(default_factory=list)
    selected_tools: list[str] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    results: list[SearchResult] = Field(default_factory=list)

    summary: str = ""
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    warnings: list[Warning] = Field(default_factory=list)
    errors: list[AgentError] = Field(default_factory=list)
    replan_count: int = Field(ge=0, default=0)
