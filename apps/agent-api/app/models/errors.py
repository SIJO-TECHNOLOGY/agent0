"""Internal structured error model used for workflow control and logging."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AgentError(BaseModel):
    """Internal error captured during workflow execution.

    These errors are kept inside graph state for logging and control flow.
    They must be translated to user-safe `Warning` or `ErrorPayload` values
    before reaching the API boundary.
    """

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    node: str | None = None
    details: dict[str, object] = Field(default_factory=dict)
