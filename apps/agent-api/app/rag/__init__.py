"""Semantic CV retrieval (RAG) over the BoondManager candidate base.

See docs/decisions/adr-014-cv-semantic-retrieval.md. The package is
self-contained: it depends on an MCP client for reading candidate data
and on nothing from the graph layer.
"""

from app.rag.embeddings import EmbeddingClient, EmbeddingError
from app.rag.factory import (
    RagConfigurationError,
    create_embedding_client,
    create_rag_service,
    create_vector_store,
)
from app.rag.index import VectorIndex
from app.rag.indexer import CandidateIndexer, CandidatePayload, IndexReport
from app.rag.models import IndexedCandidate, VectorHit
from app.rag.service import RagService
from app.rag.store import VectorStore

__all__ = [
    "CandidateIndexer",
    "CandidatePayload",
    "EmbeddingClient",
    "EmbeddingError",
    "IndexReport",
    "IndexedCandidate",
    "RagConfigurationError",
    "RagService",
    "VectorHit",
    "VectorIndex",
    "VectorStore",
    "create_embedding_client",
    "create_rag_service",
    "create_vector_store",
]
