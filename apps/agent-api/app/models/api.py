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
    location: str | None = None
    availability: str | None = None
    skills: list[str] = Field(default_factory=list)
    match_score: float | None = None
    summary: str | None = None
    boond_url: str | None = None


class CandidateCardsUI(BaseModel):
    """UI block presenting a list of candidate cards."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["candidate_cards"] = "candidate_cards"
    candidates: list[CandidateCard] = Field(default_factory=list)


class SearchResponse(BaseModel):
    """Frontend-oriented search response envelope.

    The Agent API normalizes orchestration output into a small,
    UI-shaped contract. Raw MCP payloads, execution plans, and
    tool-call traces never leak through this surface.
    """

    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    message: str
    ui: CandidateCardsUI


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
