"""Pydantic schemas for the public HTTP API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.tools import McpTool
from app.models.warnings import Warning


class SearchRequest(BaseModel):
    """Incoming search request from the web UI."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(description="Natural-language search request.")
    filters: dict[str, object] = Field(default_factory=dict)
    conversation_id: str | None = Field(
        default=None,
        description=(
            "Conversation this turn belongs to. When present, the search "
            "reuses the conversation's in-session context (accumulated query, "
            "result pagination)."
        ),
    )
    sessionId: str | None = Field(
        default=None,
        description="Camel-case session identifier accepted from the web UI.",
    )

    @field_validator("query")
    @classmethod
    def _query_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("query must be a non-empty string after trimming")
        return stripped


class CandidateCard(BaseModel):
    """UI-friendly candidate card derived from MCP results.

    Values are normalized away from raw MCP/BoondManager payloads so the
    frontend never sees provider-specific shapes. Unknown scalar fields
    are ``None`` and unknown list fields are ``[]``.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    full_name: str | None = None
    title: str | None = None
    experience_years: float | None = None
    experience_label: str | None = None
    location: str | None = None
    availability: str | None = None
    skills: list[str] = Field(default_factory=list)
    match_score: float | None = None
    summary: str | None = None
    boond_url: str | None = None
    highlights: list[str] = Field(default_factory=list)
    experiences: list[dict[str, object]] = Field(default_factory=list)
    ai_evaluation: dict[str, object] | None = None
    contract_preferences: list[str] = Field(default_factory=list)
    salary_expectation: str | None = None
    tjm: str | None = None
    mobility: str | None = None
    strengths: list[str] = Field(default_factory=list)
    watch_points: list[str] = Field(default_factory=list)
    state_label: str | None = None
    source: str | None = None
    last_update: str | None = None
    technical_summary: str | None = None
    diplomas: list[str] = Field(default_factory=list)
    expertise_areas: list[str] = Field(default_factory=list)
    activity_areas: list[str] = Field(default_factory=list)
    tools: list[dict[str, object]] = Field(default_factory=list)
    languages: list[dict[str, object]] = Field(default_factory=list)


class CandidateCardsUI(BaseModel):
    """UI block presenting a list of candidate cards."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["candidate_cards"] = "candidate_cards"
    candidates: list[CandidateCard] = Field(default_factory=list)


class ClarificationQuestion(BaseModel):
    """A single field the user is asked to fill to refine the search."""

    model_config = ConfigDict(extra="forbid")

    field: str
    label: str
    required: bool = False


class ClarificationUI(BaseModel):
    """UI block asking the user to clarify their search before retrying.

    Emitted when Agent0 judges that another search would not help without more
    information (e.g. a query parameter could not be resolved). The frontend
    renders a small form and resends the answers as an ``interaction``.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["clarification"] = "clarification"
    title: str = ""
    questions: list[ClarificationQuestion] = Field(default_factory=list)


class SearchResponse(BaseModel):
    """Frontend-oriented search response envelope.

    The Agent API normalizes orchestration output into a small,
    UI-shaped contract. Raw MCP payloads, execution plans, and
    tool-call traces never leak through this surface.
    """

    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    message: str
    ui: CandidateCardsUI | ClarificationUI
    answer: str = ""
    sessionId: str = ""
    candidates: list[dict[str, object]] = Field(default_factory=list)
    context: dict[str, object] = Field(default_factory=dict)
    debug: dict[str, object] = Field(default_factory=dict)


class ChatRequest(BaseModel):
    """Incoming chat request from the web UI."""

    model_config = ConfigDict(extra="forbid")

    message: str | None = None
    conversation_id: str | None = None
    sessionId: str | None = None
    debug: bool = False
    interaction: dict[str, object] | None = None

    @field_validator("message")
    @classmethod
    def _message_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("message must be non-empty when provided")
        return stripped


class ChatResponse(BaseModel):
    """Outgoing chat response expected by the web UI."""

    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    message: str
    answer: str = ""
    sessionId: str = ""
    ui: dict[str, object]
    candidates: list[dict[str, object]] = Field(default_factory=list)
    context: dict[str, object] = Field(default_factory=dict)
    debug: dict[str, object] = Field(default_factory=dict)


class SessionResetRequest(BaseModel):
    """Reset one in-memory chat session."""

    model_config = ConfigDict(extra="forbid")

    sessionId: str | None = None
    conversation_id: str | None = None


class SessionResetResponse(BaseModel):
    """Reset acknowledgement."""

    model_config = ConfigDict(extra="forbid")

    ok: bool = True
    sessionId: str


class ConversationCreateRequest(BaseModel):
    """Create a lightweight frontend conversation shell."""

    model_config = ConfigDict(extra="forbid")

    title: str = "Nouvelle conversation"


class ConversationRenameRequest(BaseModel):
    """Rename a conversation (sets a user-chosen, persistent title)."""

    model_config = ConfigDict(extra="forbid")

    title: str

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("title must be non-empty")
        return stripped[:120]


class ConversationSummary(BaseModel):
    """Conversation list item consumed by the frontend sidebar."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    created_at: str
    updated_at: str


class ConversationDetail(ConversationSummary):
    """Conversation detail payload consumed by the frontend."""

    messages: list[dict[str, object]] = Field(default_factory=list)


class ErrorPayload(BaseModel):
    """Stable error body matching the documented contract."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    details: dict[str, object] = Field(default_factory=dict)


class ErrorEnvelope(BaseModel):
    """API-level error envelope."""

    model_config = ConfigDict(extra="forbid")

    error: ErrorPayload
    warnings: list[Warning] = Field(default_factory=list)


class McpDependencyStatus(BaseModel):
    """Status of the MCP dependency as known at app startup.

    `status="mock"` means the Agent API is running with an in-memory mock
    and no real server is required. `"connected"` means the Streamable HTTP
    session opened successfully. `"unavailable"` means the real client was
    requested but `connect()` failed; `error` carries a sanitized message.
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal["mock", "connected", "unavailable"]
    url: str
    transport: str
    error: str | None = None


class HealthDependencies(BaseModel):
    """External dependencies surfaced by the health endpoint."""

    model_config = ConfigDict(extra="forbid")

    mcp: McpDependencyStatus


class HealthResponse(BaseModel):
    """Health check payload."""

    model_config = ConfigDict(extra="forbid")

    status: str = "ok"
    version: str
    dependencies: HealthDependencies


class McpToolsResponse(BaseModel):
    """Catalogue of MCP tools discovered from the connected server."""

    model_config = ConfigDict(extra="forbid")

    tools: list[McpTool] = Field(default_factory=list)
    count: int = Field(ge=0, default=0)

