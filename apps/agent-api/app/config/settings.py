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

    cors_allowed_origins: str = Field(
        default="http://localhost:5500,http://127.0.0.1:5500",
        description=(
            "Comma-separated list of origins allowed by CORS (env "
            "CORS_ALLOWED_ORIGINS). Defaults cover local development; add "
            "the deployed web-ui origin(s) in production, e.g. "
            "'http://localhost:5500,https://assistant.sijo.fr'."
        ),
    )

    mcp_server_url: str = Field(default="http://localhost:8001/mcp")
    mcp_timeout_seconds: float = Field(default=15.0, ge=0.1)
    mcp_max_retries: int = Field(default=2, ge=0, le=5)
    mcp_transport: str = Field(default="streamable_http")

    # --- MCP result caching (ADR-013) --------------------------------------
    mcp_cache_enabled: bool = Field(
        default=True,
        description=(
            "Wrap the MCP client in an in-process TTL cache for semi-stable "
            "results (dictionary, CV text, technical documents, tool "
            "catalogue). Volatile data (search, detail, administrative) is "
            "never cached. False disables all MCP caching."
        ),
    )
    mcp_dictionary_cache_ttl_seconds: float = Field(
        default=21600.0, ge=0.0,
        description=(
            "TTL for cached getDictionary results (default 6h). The "
            "dictionary is quasi-static reference data fetched up to three "
            "times per search without this cache. 0 disables."
        ),
    )
    mcp_candidate_doc_cache_ttl_seconds: float = Field(
        default=21600.0, ge=0.0,
        description=(
            "TTL for cached getCandidateCV / getCandidateTechnicalDocument "
            "results per candidate (default 6h). Bounds how long a freshly "
            "uploaded CV replacement can go unnoticed. 0 disables."
        ),
    )
    mcp_tools_cache_ttl_seconds: float = Field(
        default=300.0, ge=0.0,
        description=(
            "TTL for the cached MCP tool catalogue (default 5 min); "
            "discover_tools runs once per search. 0 disables."
        ),
    )
    mcp_cache_max_entries: int = Field(
        default=512, ge=1,
        description=(
            "Upper bound on cached MCP entries; least-recently-used entries "
            "are evicted beyond this."
        ),
    )

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
    min_match_score: float = Field(
        default=0.5, ge=0.0, le=1.0,
        description=(
            "Low-score replacement gate: after ranking, any returned "
            "candidate scoring strictly below this triggers ONE deterministic "
            "better-targeted replan pass (within max_replan_attempts) to try "
            "to replace it. Results accumulate across passes, so when the "
            "retry finds nothing better the original candidates are returned "
            "unchanged. 0 disables the gate."
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
    allow_clarification: bool = Field(
        default=True,
        description=(
            "When true (and the LLM workflow runs), Agent0's post-ranking "
            "reflection may ask the user to clarify — instead of replanning — "
            "when a query parameter could not be resolved. At most one "
            "clarification per request."
        ),
    )
    # --- Agent1 LLM reconciliation (data-coherence judge) --------------------
    agent1_llm_reconciliation: bool = Field(
        default=False,
        description=(
            "When true, Agent1 sends candidates whose data the deterministic "
            "pass flags as incoherent (e.g. an age conflicting with the stated "
            "experience) to the LLM, which judges coherence across experience, "
            "skills, languages, and title and returns a reconciled view. Only "
            "conflicting candidates trigger a call (one batched call per "
            "search). Requires LLM credentials. Off by default to avoid cost."
        ),
    )
    agent1_confidence_threshold: float = Field(
        default=0.6, ge=0.0, le=1.0,
        description=(
            "Minimum confidence for an Agent1 LLM judgement to override the "
            "deterministic result. Below this, the deterministic value is kept."
        ),
    )
    agent1_max_reconcile_candidates: int = Field(
        default=10, ge=1, le=50,
        description="Hard cap on candidates sent to the Agent1 LLM per search.",
    )
    # --- Semantic scoring (embedding-based skill boost) ----------------------
    enable_semantic_scoring: bool = Field(
        default=False,
        description=(
            "When true, an OpenAI embedding model computes a cosine-similarity "
            "boost on top of the text-matching evidence score. Requires "
            "openai_api_key to be set. Adds one embedding API call per "
            "candidate per search (batched). Off by default to avoid "
            "unexpected costs."
        ),
    )
    openai_api_key: str | None = Field(
        default=None,
        description=(
            "OpenAI API key used exclusively for semantic scoring embeddings. "
            "Required when enable_semantic_scoring=true."
        ),
    )
    semantic_model: str = Field(
        default="text-embedding-3-small",
        description="OpenAI embedding model used for semantic scoring.",
    )
    semantic_boost_weight: float = Field(
        default=0.15,
        ge=0.0,
        le=0.5,
        description=(
            "Maximum additive boost applied to the evidence score from "
            "semantic similarity. 0.15 means a semantically perfect match "
            "adds up to 0.15 to the evidence score (capped at 1.0)."
        ),
    )

    # --- CV semantic retrieval / RAG (ADR-014) -------------------------------
    enable_cv_rag: bool = Field(
        default=False,
        description=(
            "When true, a vector index over candidate CVs runs as a SECOND "
            "recall channel alongside searchCandidates: semantically similar "
            "candidates the keyword search missed are added to the result "
            "pool, then ranked by the normal scoring. Requires an embedding "
            "API key and a populated index (see scripts/index_candidates.py). "
            "Off by default: an empty index simply adds nothing."
        ),
    )
    rag_store: str = Field(
        default="sqlite",
        description=(
            "Backend for the CV vector index: 'sqlite' (local file, dev/tests) "
            "or 'azure_table' (Azure Table Storage, production)."
        ),
    )
    rag_sqlite_path: str = Field(
        default="data/cv_index.db",
        description=(
            "SQLite file for the vector index (rag_store=sqlite). Relative "
            "paths resolve against the working directory; ':memory:' for tests."
        ),
    )
    rag_embedding_model: str = Field(
        default="text-embedding-3-small",
        description="Embedding model used to index CVs and embed queries.",
    )
    rag_embedding_dims: int = Field(
        default=512, ge=64, le=3072,
        description=(
            "Embedding dimensionality (Matryoshka truncation). The whole "
            "index is held in memory, so this directly sets its footprint: "
            "~53 MB at 512 dims for 26k candidates, ~159 MB at 1536. "
            "Changing it invalidates the index — re-run the indexing script."
        ),
    )
    rag_embedding_api_key: str | None = Field(
        default=None,
        description=(
            "API key for the embedding model. Falls back to OPENAI_API_KEY "
            "when unset. Required when enable_cv_rag=true."
        ),
    )
    rag_top_k: int = Field(
        default=10, ge=1, le=200,
        description=(
            "Maximum candidates the vector channel may ADD to a search "
            "(candidates already found by keyword search don't count). "
            "Kept small on purpose: vector hits compete with keyword hits "
            "for the bounded enrichment budget, so the channel should only "
            "put forward candidates it is confident about."
        ),
    )
    rag_min_score: float = Field(
        default=0.45, ge=0.0, le=1.0,
        description=(
            "Cosine-similarity floor for a vector hit to be added. Measured "
            "on the live base: clearly related profiles score ~0.5+, while "
            "barely related ones still reach ~0.4 — 0.45 keeps the channel "
            "precise. Lowering it trades precision for recall."
        ),
    )
    rag_catch_up_enabled: bool = Field(
        default=True,
        description=(
            "When true, candidates seen during a search but missing from the "
            "index are indexed afterwards, so the index fills in with use. "
            "Runs after the response is assembled and never blocks it."
        ),
    )
    rag_index_concurrency: int = Field(
        default=6, ge=1, le=32,
        description=(
            "Concurrent candidates fetched during indexing. Each costs 2 MCP "
            "calls and makes BoondManager re-extract a PDF, so this is the "
            "main throttle on a bulk indexing run."
        ),
    )

    # --- Conversation persistence --------------------------------------------
    conversation_store: str = Field(
        default="sqlite",
        description=(
            "Backend for per-user conversation history: 'sqlite' (local "
            "file, dev/tests) or 'azure_table' (Azure Table Storage, "
            "production)."
        ),
    )
    sqlite_db_path: str = Field(
        default="data/conversations.db",
        description=(
            "SQLite database file path (conversation_store=sqlite). "
            "Relative paths resolve against the working directory; parent "
            "directories are created automatically. ':memory:' for tests."
        ),
    )
    azure_storage_connection_string: str | None = Field(
        default=None,
        description=(
            "Azure Storage connection string (conversation_store="
            "azure_table). Alternative to account URL + managed identity."
        ),
    )
    azure_storage_account_url: str | None = Field(
        default=None,
        description=(
            "Azure Table endpoint, e.g. https://<account>.table.core."
            "windows.net (conversation_store=azure_table). Authenticates "
            "with DefaultAzureCredential (managed identity in Container "
            "Apps); the identity needs the 'Storage Table Data "
            "Contributor' role."
        ),
    )

    # --- Microsoft Entra ID SSO (bearer-token validation) ---------------------
    enable_auth: bool = Field(
        default=False,
        description=(
            "When true, every /api/* route except /api/health and /api/ready "
            "requires a valid Microsoft Entra ID access token issued for this "
            "API (Authorization: Bearer). Startup fails fast if "
            "entra_tenant_id or entra_client_id is missing. Off by default so "
            "local development and tests run unauthenticated — but production "
            "MUST enable it: startup also fails fast when this is false and "
            "APP_ENV is not a local/dev/test value (see validate_auth_settings)."
        ),
    )
    entra_tenant_id: str | None = Field(
        default=None,
        description=(
            "Directory (tenant) ID of the Entra ID app registration. "
            "Required when enable_auth=true. Determines both the JWKS "
            "signing-key endpoint and the accepted token issuers."
        ),
    )
    entra_client_id: str | None = Field(
        default=None,
        description=(
            "Application (client) ID of the Entra ID app registration. "
            "Required when enable_auth=true. Tokens are accepted with "
            "audience 'api://<client-id>' or the bare client id."
        ),
    )
    auth_allowed_email_domain: str | None = Field(
        default="sijo.fr",
        description=(
            "When set, the signed-in account's preferred_username/upn claim "
            "must end with '@<domain>' or the request is rejected with 403. "
            "Covers guest accounts that a single-tenant registration still "
            "admits. None disables the domain check."
        ),
    )

    # --- External candidate discovery (LinkedIn via OpenAI Web Search) -------
    external_search_enabled: bool = Field(
        default=False,
        description=(
            "Master switch for external (LinkedIn/Web) candidate discovery. "
            "When false, the LinkedIn source never executes even if requested, "
            "and 'no source selected' resolves to BoondManager only. When "
            "true, 'no source selected' resolves to BoondManager + LinkedIn."
        ),
    )
    external_search_provider: str = Field(
        default="openai_web",
        description=(
            "External discovery backend. Only 'openai_web' (OpenAI Responses "
            "API built-in web_search) is implemented."
        ),
    )
    external_search_model: str = Field(
        default="gpt-4o",
        description=(
            "Model used for external web search via the OpenAI Responses API. "
            "Must be a model that grounds the built-in web_search tool well: "
            "gpt-4o (default), gpt-5, gpt-5.4 reliably return real "
            "url_citation sources for LinkedIn queries, whereas gpt-4o-mini "
            "tends to fabricate (its ungrounded output is then rejected, so it "
            "yields few/no results). Not hardcoded — override per environment."
        ),
    )
    external_search_structure_model: str = Field(
        default="gpt-4o-mini",
        description=(
            "Model for the SECOND (structuring) pass of external discovery — it "
            "reformats already-cited web findings into JSON with no web search, "
            "so a fast/cheap model keeps latency low with no grounding risk "
            "(URLs are still validated against the citations). Default "
            "gpt-4o-mini."
        ),
    )
    external_search_max_queries: int = Field(
        default=6, ge=1, le=12,
        description=(
            "Hard upper bound on the number of complementary web-search "
            "queries issued per external discovery (the bounded search "
            "ladder). More passes = better recall on niche queries, at higher "
            "cost/latency. Bounds cost and latency."
        ),
    )
    external_search_max_results: int = Field(
        default=20, ge=1, le=100,
        description=(
            "Maximum external candidate profiles returned per search after "
            "canonicalisation and deduplication."
        ),
    )
    external_search_linkedin_only: bool = Field(
        default=True,
        description=(
            "Restrict external discovery to public linkedin.com/in profile "
            "pages. When true, non-profile LinkedIn pages (company/jobs/posts/"
            "pulse) and other domains are rejected."
        ),
    )
    external_search_cache_ttl_seconds: float = Field(
        default=21600.0, ge=0.0,
        description=(
            "TTL for the in-process external web-search cache (default 6h). "
            "Web search is slow and costly, so identical (query + source + "
            "business settings) discoveries are cached. 0 disables."
        ),
    )
    external_search_api_key: str | None = Field(
        default=None,
        description=(
            "API key for the external web-search provider. Falls back to "
            "OPENAI_API_KEY when unset. Required when external_search_enabled "
            "and the LinkedIn source is used."
        ),
    )
    candidate_prefer_consulting_profile: bool = Field(
        default=True,
        description=(
            "SIJO business default: external candidates with evidence of a "
            "consulting/freelance/ESN profile are preferred (positively "
            "weighted in ranking). The planner applies this automatically; the "
            "recruiter need not restate it per query."
        ),
    )
    candidate_long_mission_threshold_months: int = Field(
        default=24, ge=1, le=120,
        description=(
            "SIJO business default: the minimum client-mission duration (in "
            "months) that counts as a 'long mission'. Evidence of at least one "
            "mission >= this threshold is strongly valued for external "
            "candidates. Configurable — never hardcode 24 in the code."
        ),
    )
    external_default_location: str = Field(
        default="Île-de-France, France",
        description=(
            "Default geography for EXTERNAL (LinkedIn) discovery when the "
            "recruiter's query names no location. SIJO recruits in France, so "
            "web search targets this area by default (and ranking prefers it) "
            "instead of returning globally skill-matching profiles. The "
            "recruiter's own location, when stated, always overrides it. Set "
            "empty to disable the geo default."
        ),
    )
    candidate_require_french_or_france_experience: bool = Field(
        default=True,
        description=(
            "SIJO hard filter for external candidates: EXCLUDE a discovered "
            "profile whose current location is a clearly-foreign country AND "
            "that evidences neither French nor an experience in France. "
            "Conservative — a profile whose location cannot be placed, or that "
            "speaks French, or that worked in France, is never excluded (we "
            "never infer absence). False keeps such profiles (demoted, not "
            "excluded)."
        ),
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


    @property
    def cors_origins(self) -> list[str]:
        """`cors_allowed_origins` split into a clean list of origins."""
        return [
            origin.strip()
            for origin in self.cors_allowed_origins.split(",")
            if origin.strip()
        ]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings instance."""
    return Settings()
