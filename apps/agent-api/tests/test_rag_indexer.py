"""Tests for document building, the indexer, and the RAG service."""

from __future__ import annotations

import pytest

from app.rag.document import build_candidate_document, build_query_document
from app.rag.embeddings import EmbeddingError
from app.rag.index import VectorIndex
from app.rag.indexer import CandidateIndexer, CandidatePayload, compact_summary
from app.rag.models import normalise
from app.rag.service import RagService
from app.rag.sqlite_vector_store import SqliteVectorStore


class FakeEmbeddings:
    """Deterministic stand-in: vector position encodes a keyword."""

    model = "fake-model"
    dims = 3

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.fail = False

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        if self.fail:
            raise EmbeddingError("boom")
        return [normalise(self._vector(text)) for text in texts]

    async def embed_one(self, text: str) -> list[float]:
        vectors = await self.embed([text])
        return vectors[0]

    @staticmethod
    def _vector(text: str) -> list[float]:
        lowered = text.lower()
        return [
            1.0 if "java" in lowered else 0.0,
            1.0 if "python" in lowered else 0.0,
            0.1,
        ]


class FakeMcp:
    def __init__(self, responses: dict[str, dict[str, object]] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[tuple[str, str]] = []

    async def call_tool(self, tool: str, inputs: dict[str, object]):
        candidate_id = str(inputs.get("candidateId"))
        self.calls.append((tool, candidate_id))
        payload = self.responses.get(tool)
        return [payload] if payload else []


@pytest.fixture()
async def store():
    store = SqliteVectorStore(":memory:")
    await store.initialize()
    yield store
    await store.close()


# --- document building ---------------------------------------------------


def test_document_merges_summary_tech_doc_and_cv() -> None:
    document = build_candidate_document(
        summary={"title": "Dev Java", "skills": ["Spring"]},
        technical_document={"skills": ["Kafka"]},
        cv={"hasContent": True, "text": "Experience sur des microservices"},
    )

    assert "Dev Java" in document
    assert "Spring" in document
    assert "Kafka" in document
    assert "microservices" in document


def test_document_excludes_administrative_noise() -> None:
    document = build_candidate_document(
        summary={
            "title": "Dev",
            "email": "a@b.fr",
            "phone": "0600000000",
            "currentSalary": 55000,
        }
    )

    assert "a@b.fr" not in document
    assert "0600000000" not in document
    assert "55000" not in document


def test_document_ignores_a_cv_without_content() -> None:
    document = build_candidate_document(
        summary={"title": "Dev"}, cv={"hasContent": False, "text": "stale"}
    )

    assert "stale" not in document


def test_document_is_empty_when_nothing_is_indexable() -> None:
    assert build_candidate_document(summary={"email": "a@b.fr"}) == ""
    assert build_candidate_document() == ""


def test_document_is_capped() -> None:
    document = build_candidate_document(
        summary={"title": "Dev"},
        cv={"hasContent": True, "text": "mot " * 10_000},
    )

    assert len(document) <= 7500


def test_query_document_joins_role_entities_and_objective() -> None:
    query = build_query_document(
        entities=["java", "spring"], objective="trouver un dev", role="tech lead"
    )

    assert query.startswith("tech lead")
    assert "java" in query and "spring" in query and "trouver un dev" in query


def test_compact_summary_keeps_only_card_fields() -> None:
    compact = compact_summary(
        {"id": "1", "title": "Dev", "email": "a@b.fr", "unknownField": 1}
    )

    assert compact == {"id": "1", "title": "Dev"}


# --- indexer -------------------------------------------------------------


@pytest.mark.asyncio
async def test_indexer_embeds_and_persists(store: SqliteVectorStore) -> None:
    embeddings = FakeEmbeddings()
    indexer = CandidateIndexer(
        mcp_client=FakeMcp(), embeddings=embeddings, store=store
    )
    payload = CandidatePayload(
        summary={"id": "1", "title": "Dev Java"},
        cv={"hasContent": True, "text": "spring boot"},
    )

    entries, report = await indexer.index_payloads([payload])

    assert report.indexed == 1
    assert entries[0].candidate_id == "1"
    assert entries[0].model == "fake-model"
    assert await store.count() == 1


@pytest.mark.asyncio
async def test_indexer_skips_unchanged_documents(store: SqliteVectorStore) -> None:
    embeddings = FakeEmbeddings()
    indexer = CandidateIndexer(
        mcp_client=FakeMcp(), embeddings=embeddings, store=store
    )
    payload = CandidatePayload(summary={"id": "1", "title": "Dev Java"})

    entries, _ = await indexer.index_payloads([payload])
    known = {entries[0].candidate_id: entries[0].doc_hash}
    _, second = await indexer.index_payloads([payload], known_hashes=known)

    assert second.skipped_unchanged == 1
    assert second.indexed == 0
    assert len(embeddings.calls) == 1  # no second embedding call


@pytest.mark.asyncio
async def test_indexer_skips_candidates_without_content(
    store: SqliteVectorStore,
) -> None:
    indexer = CandidateIndexer(
        mcp_client=FakeMcp(), embeddings=FakeEmbeddings(), store=store
    )

    _, report = await indexer.index_payloads(
        [CandidatePayload(summary={"id": "1", "email": "a@b.fr"})]
    )

    assert report.skipped_empty == 1
    assert report.indexed == 0


@pytest.mark.asyncio
async def test_indexer_reports_embedding_failure_without_storing(
    store: SqliteVectorStore,
) -> None:
    embeddings = FakeEmbeddings()
    embeddings.fail = True
    indexer = CandidateIndexer(
        mcp_client=FakeMcp(), embeddings=embeddings, store=store
    )

    entries, report = await indexer.index_payloads(
        [CandidatePayload(summary={"id": "1", "title": "Dev Java"})]
    )

    assert entries == []
    assert report.failed == 1
    assert await store.count() == 0


@pytest.mark.asyncio
async def test_indexer_fetches_through_mcp_for_bulk_indexing(
    store: SqliteVectorStore,
) -> None:
    mcp = FakeMcp(
        {
            "getCandidateTechnicalDocument": {"skills": ["Kafka"]},
            "getCandidateCV": {"hasContent": True, "text": "spring boot"},
        }
    )
    indexer = CandidateIndexer(
        mcp_client=mcp, embeddings=FakeEmbeddings(), store=store
    )

    _, report = await indexer.index([{"id": "7", "title": "Dev Java"}])

    assert report.indexed == 1
    assert ("getCandidateCV", "7") in mcp.calls
    assert ("getCandidateTechnicalDocument", "7") in mcp.calls


@pytest.mark.asyncio
async def test_indexer_survives_a_failing_mcp_tool(
    store: SqliteVectorStore,
) -> None:
    class BrokenMcp(FakeMcp):
        async def call_tool(self, tool: str, inputs: dict[str, object]):
            raise RuntimeError("mcp down")

    indexer = CandidateIndexer(
        mcp_client=BrokenMcp(), embeddings=FakeEmbeddings(), store=store
    )

    # The CV can't be read, but the summary alone is still indexable.
    _, report = await indexer.index([{"id": "7", "title": "Dev Java"}])

    assert report.indexed == 1


# --- service -------------------------------------------------------------


async def _service(store: SqliteVectorStore, **kwargs) -> RagService:
    embeddings = FakeEmbeddings()
    indexer = CandidateIndexer(
        mcp_client=FakeMcp(), embeddings=embeddings, store=store
    )
    service = RagService(
        store=store,
        embeddings=embeddings,  # type: ignore[arg-type]
        indexer=indexer,
        index=VectorIndex(),
        min_score=kwargs.pop("min_score", 0.3),
        **kwargs,
    )
    return service


@pytest.mark.asyncio
async def test_service_search_returns_semantic_matches(
    store: SqliteVectorStore,
) -> None:
    service = await _service(store)
    indexer = service._indexer  # noqa: SLF001 — white-box setup
    await indexer.index_payloads(
        [
            CandidatePayload(summary={"id": "java1", "title": "Dev Java"}),
            CandidatePayload(summary={"id": "py1", "title": "Dev Python"}),
        ]
    )
    await service.load()

    hits = await service.search(entities=["java"], objective="")

    assert [h.candidate_id for h in hits] == ["java1"]


@pytest.mark.asyncio
async def test_service_search_is_empty_when_index_is_empty(
    store: SqliteVectorStore,
) -> None:
    service = await _service(store)
    await service.load()

    assert await service.search(entities=["java"]) == []


@pytest.mark.asyncio
async def test_service_search_excludes_already_found_candidates(
    store: SqliteVectorStore,
) -> None:
    service = await _service(store)
    await service._indexer.index_payloads(  # noqa: SLF001
        [CandidatePayload(summary={"id": "java1", "title": "Dev Java"})]
    )
    await service.load()

    hits = await service.search(entities=["java"], exclude={"java1"})

    assert hits == []


@pytest.mark.asyncio
async def test_service_search_without_query_terms_returns_nothing(
    store: SqliteVectorStore,
) -> None:
    service = await _service(store)
    await service._indexer.index_payloads(  # noqa: SLF001
        [CandidatePayload(summary={"id": "1", "title": "Dev Java"})]
    )
    await service.load()

    assert await service.search(entities=[], objective="", role=None) == []


@pytest.mark.asyncio
async def test_catch_up_indexes_only_missing_candidates(
    store: SqliteVectorStore,
) -> None:
    service = await _service(store)
    await service._indexer.index_payloads(  # noqa: SLF001
        [CandidatePayload(summary={"id": "known", "title": "Dev Java"})]
    )
    await service.load()

    added = await service.catch_up(
        [
            CandidatePayload(summary={"id": "known", "title": "Dev Java"}),
            CandidatePayload(summary={"id": "fresh", "title": "Dev Python"}),
        ]
    )

    assert added == 1
    assert service.size == 2


@pytest.mark.asyncio
async def test_catch_up_can_be_disabled(store: SqliteVectorStore) -> None:
    service = await _service(store, catch_up_enabled=False)
    await service.load()

    added = await service.catch_up(
        [CandidatePayload(summary={"id": "fresh", "title": "Dev Java"})]
    )

    assert added == 0


@pytest.mark.asyncio
async def test_load_degrades_to_empty_when_the_store_fails() -> None:
    class BrokenStore:
        async def load_all(self):
            raise RuntimeError("store down")

    service = RagService(
        store=BrokenStore(),  # type: ignore[arg-type]
        embeddings=FakeEmbeddings(),  # type: ignore[arg-type]
        indexer=None,  # type: ignore[arg-type]
    )

    assert await service.load() == 0
    assert await service.search(entities=["java"]) == []
