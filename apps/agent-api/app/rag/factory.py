"""Build the RAG stack from settings.

Same philosophy as the MCP and conversation-store factories: the backend
is an explicit configuration decision and misconfiguration fails at
startup, never silently at the first search.
"""

from __future__ import annotations

from app.config.settings import Settings
from app.rag.embeddings import EmbeddingClient
from app.rag.index import VectorIndex
from app.rag.indexer import CandidateIndexer, SupportsCallTool
from app.rag.service import RagService
from app.rag.store import VectorStore


class RagConfigurationError(RuntimeError):
    """Raised at startup when the RAG configuration is invalid."""


def create_vector_store(settings: Settings) -> VectorStore:
    backend = settings.rag_store.strip().lower()
    if backend == "sqlite":
        from app.rag.sqlite_vector_store import SqliteVectorStore

        return SqliteVectorStore(settings.rag_sqlite_path)
    if backend == "azure_table":
        if not (
            settings.azure_storage_connection_string
            or settings.azure_storage_account_url
        ):
            raise RagConfigurationError(
                "RAG_STORE=azure_table requires AZURE_STORAGE_CONNECTION_STRING "
                "or AZURE_STORAGE_ACCOUNT_URL."
            )
        from app.rag.azure_table_vector_store import AzureTableVectorStore

        return AzureTableVectorStore(
            connection_string=settings.azure_storage_connection_string,
            account_url=settings.azure_storage_account_url,
        )
    raise RagConfigurationError(
        f"Unknown RAG_STORE '{settings.rag_store}'. Supported: sqlite, azure_table."
    )


def create_embedding_client(settings: Settings) -> EmbeddingClient:
    api_key = settings.rag_embedding_api_key or settings.openai_api_key
    if not api_key:
        raise RagConfigurationError(
            "ENABLE_CV_RAG=true requires RAG_EMBEDDING_API_KEY (or "
            "OPENAI_API_KEY) for the embedding model."
        )
    return EmbeddingClient(
        api_key=api_key,
        model=settings.rag_embedding_model,
        dims=settings.rag_embedding_dims,
    )


def create_rag_service(
    settings: Settings,
    *,
    mcp_client: SupportsCallTool,
    store: VectorStore | None = None,
    embeddings: EmbeddingClient | None = None,
) -> RagService:
    """Assemble the RAG service. Raises on misconfiguration."""
    store = store or create_vector_store(settings)
    embeddings = embeddings or create_embedding_client(settings)
    indexer = CandidateIndexer(
        mcp_client=mcp_client,
        embeddings=embeddings,
        store=store,
        concurrency=settings.rag_index_concurrency,
    )
    return RagService(
        store=store,
        embeddings=embeddings,
        indexer=indexer,
        index=VectorIndex(),
        top_k=settings.rag_top_k,
        min_score=settings.rag_min_score,
        catch_up_enabled=settings.rag_catch_up_enabled,
    )
