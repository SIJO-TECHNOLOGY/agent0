"""Pydantic schemas for the public HTTP API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.intent import InterpretedIntent, PlanStep
from app.models.results import SearchResult
from app.models.tools import ToolCall
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


class SearchResponse(BaseModel):
    """Outgoing search response."""

    model_config = ConfigDict(extra="forbid")

    original_query: str
    interpreted_intent: InterpretedIntent
    execution_plan: list[PlanStep]
    tool_calls: list[ToolCall]
    results: list[SearchResult]
    summary: str
    confidence: float = Field(ge=0.0, le=1.0)
    warnings: list[Warning] = Field(default_factory=list)


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
