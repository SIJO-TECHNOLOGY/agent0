"""Schemas for MCP tools and tool call records."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ToolCallStatus(str, Enum):
    """Lifecycle states for a tool call."""

    SUCCESS = "success"
    EMPTY = "empty"
    FAILED = "failed"
    SKIPPED = "skipped"


class McpTool(BaseModel):
    """Metadata describing a discoverable MCP tool."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    input_schema: dict[str, object] = Field(default_factory=dict)


class ToolCall(BaseModel):
    """Sanitized record of an MCP tool invocation."""

    model_config = ConfigDict(extra="forbid")

    tool: str
    inputs: dict[str, object] = Field(default_factory=dict)
    status: ToolCallStatus
    latency_ms: int = Field(ge=0, default=0)
    result_count: int = Field(ge=0, default=0)
    error_message: str | None = None
    attempts: int = Field(ge=1, default=1)
