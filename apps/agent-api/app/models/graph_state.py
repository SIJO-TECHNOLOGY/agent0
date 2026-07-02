"""LangGraph state schema."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.models.errors import AgentError
from app.models.intent import InterpretedIntent, LlmToolPlan, PlanStep
from app.models.results import SearchResult
from app.models.tools import McpTool, ToolCall
from app.models.warnings import Warning


class GraphState(BaseModel):
    """Typed state passed between LangGraph nodes."""

    model_config = ConfigDict(extra="forbid")

    original_query: str
    filters: dict[str, object] = Field(default_factory=dict)

    session_id: str | None = None
    conversation_history: list[dict[str, object]] = Field(default_factory=list)
    session_context: dict[str, object] = Field(default_factory=dict)
    current_search: dict[str, object] = Field(default_factory=dict)
    is_follow_up: bool = False
    should_reset_search: bool = False
    current_candidates: list[dict[str, object]] = Field(default_factory=list)

    interpreted_intent: InterpretedIntent | None = None
    execution_plan: list[PlanStep] = Field(default_factory=list)
    available_tools: list[McpTool] = Field(default_factory=list)
    selected_tools: list[str] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    results: list[SearchResult] = Field(default_factory=list)
    llm_plan: LlmToolPlan | None = None

    summary: str = ""
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    warnings: list[Warning] = Field(default_factory=list)
    errors: list[AgentError] = Field(default_factory=list)
    replan_count: int = Field(ge=0, default=0)
    replan_feedback: str = Field(
        default="",
        description=(
            "LLM reflection guidance for the next plan pass. Non-empty is the "
            "single signal that an LLM-decided replan is pending; consumed and "
            "cleared by plan_with_llm so the bounded loop cannot spin."
        ),
    )
    clarification_question: str = Field(
        default="",
        description=(
            "Non-empty when Agent0's reflection decided to ask the user for "
            "clarification instead of replanning. Drives a clarification UI in "
            "the final response; the run finalizes (no further search pass)."
        ),
    )
    clarification_fields: list[str] = Field(
        default_factory=list,
        description="Field names the user is asked to provide in the clarification form.",
    )

