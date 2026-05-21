"""Schema for user-safe warnings surfaced through the API."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Warning(BaseModel):
    """User-facing warning attached to a search response."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
