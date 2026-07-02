"""Typed session-memory models."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field


class SessionMemory(BaseModel):
    """In-memory business context for one conversational session."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    messages: list[dict[str, object]] = Field(default_factory=list)
    current_search: dict[str, object] = Field(default_factory=dict)
    last_filters: dict[str, object] = Field(default_factory=dict)
    current_candidates: list[dict[str, object]] = Field(default_factory=list)
    last_user_query: str = ""
    last_agent_response: str = ""
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def touch(self) -> None:
        self.updated_at = datetime.now(UTC)

    def public_context(self) -> dict[str, object]:
        return {
            "currentSearch": dict(self.current_search),
            "lastFilters": dict(self.last_filters),
            "candidateCount": len(self.current_candidates),
        }
