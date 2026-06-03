"""Centralized runtime settings loaded from environment / .env."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings.

    Defaults are tuned for local development; production overrides
    must come from real environment variables, not `.env`.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = Field(default="local")
    log_level: str = Field(default="INFO")
    agent_trace: Literal["off", "on", "verbose"] = Field(
        default="on",
        description=(
            "Console logging mode (env AGENT_TRACE = off|on|verbose). "
            "'on' (default) logs a readable per-request decision/think/replan "
            "chain to the 'agent.trace' logger with plain app lines (no JSON). "
            "'verbose' additionally appends the structured extra={} payloads as "
            "JSON for deep debugging and shows a fuller trace. 'off' disables "
            "the trace. Third-party log noise is quieted in every mode."
        ),
    )

    mcp_server_url: str = Field(default="http://localhost:8001/mcp")
    mcp_timeout_seconds: float = Field(default=15.0, ge=0.1)
    mcp_max_retries: int = Field(default=2, ge=0, le=5)
    mcp_transport: str = Field(default="streamable_http")

    max_replan_attempts: int = Field(default=1, ge=0, le=3)
    use_llm_replan: bool = Field(
        default=True,
        description=(
            "Enable the LLM-driven reflection/replan loop in the LLM "
            "workflow. The LLM judges the ranked results and decides whether "
            "to run another (guided) search pass, bounded by "
            "max_replan_attempts. False ⇒ the LLM workflow stays single-shot."
        ),
    )
    replan_skip_score: float = Field(
        default=0.8, ge=0.0, le=1.0,
        description=(
            "Quality gate that skips the reflection LLM call: if a candidate "
            "is already a full match or the top score is at least this value, "
            "the results are considered good enough and no replan is "
            "considered (bounds cost)."
        ),
    )

    use_mock_mcp: bool = Field(default=True)

    enable_mcp_debug_endpoints: bool = Field(
        default=False,
        description=(
            "Gate for development-only MCP introspection endpoints "
            "(e.g. POST /api/mcp/tools/{tool_name}/call). Must remain "
            "False in shared / production environments."
        ),
    )

    # --- LLM planner -----------------------------------------------------
    use_llm_planner: bool = Field(
        default=False,
        description=(
            "When true, the primary planner is an LLM with discovered MCP "
            "tool information. When false, the deterministic fallback "
            "planner runs (useful for tests, mock mode, and dev without "
            "LLM credentials)."
        ),
    )
    llm_provider: str = Field(
        default="anthropic",
        description="LLM backend identifier ('anthropic' or 'openai').",
    )
    llm_model: str = Field(
        default="claude-sonnet-4-6",
        description="Model name passed to the configured LLM provider.",
    )
    llm_api_key: str | None = Field(
        default=None,
        description=(
            "API key for the configured LLM provider. Required when "
            "USE_LLM_PLANNER=true."
        ),
    )
    llm_temperature: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Temperature passed to the LLM. Default 0 for determinism.",
    )
    llm_timeout_seconds: float = Field(
        default=60.0, ge=1.0,
        description="Maximum time to wait for one LLM planner response.",
    )
    llm_max_plan_steps: int = Field(
        default=6, ge=1, le=20,
        description="Hard upper bound on planned tool calls per query.",
    )
    llm_planner_role: str = Field(
        default=(
            "You are an expert technical recruiter and CV search, matching, "
            "and ranking specialist. You interpret natural-language hiring "
            "requests, search a candidate database through the available MCP "
            "tools, and decide which candidate criteria matter most so the "
            "best-fitting profiles rank first. You are precise and "
            "evidence-driven, and you never invent candidate data."
        ),
        description=(
            "Role/persona preamble prepended to the LLM planner's system "
            "prompt. Framing only — the planner's rules and JSON output "
            "schema are fixed and always applied regardless of this value. "
            "Set empty to disable."
        ),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings instance."""
    return Settings()
