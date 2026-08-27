"""Tests for the SQLite vector store and vector (de)serialisation."""

from __future__ import annotations

import math

import pytest

from app.rag.models import (
    IndexedCandidate,
    decode_vector,
    encode_vector,
    normalise,
)
from app.rag.sqlite_vector_store import SqliteVectorStore


@pytest.fixture()
async def store():
    store = SqliteVectorStore(":memory:")
    await store.initialize()
    yield store
    await store.close()


def test_encode_decode_roundtrip_preserves_values() -> None:
    vector = [0.1, -0.25, 0.5, 1.0]

    decoded = decode_vector(encode_vector(vector))

    assert len(decoded) == len(vector)
    for original, restored in zip(vector, decoded):
        assert math.isclose(original, restored, abs_tol=1e-6)


def test_decode_rejects_malformed_input() -> None:
    assert decode_vector("not base64 !!") == []
    assert decode_vector("YWJj") == []  # 3 bytes: not a whole number of floats


def test_normalise_produces_unit_length() -> None:
    result = normalise([3.0, 4.0])

    assert math.isclose(sum(v * v for v in result) ** 0.5, 1.0, abs_tol=1e-6)


def test_normalise_leaves_zero_vector_alone() -> None:
    assert normalise([0.0, 0.0]) == [0.0, 0.0]


@pytest.mark.asyncio
async def test_upsert_then_load_roundtrip(store: SqliteVectorStore) -> None:
    entry = IndexedCandidate(
        candidate_id="42",
        vector=normalise([1.0, 2.0, 3.0]),
        summary={"id": "42", "title": "Dev Java"},
        doc_hash="abc123",
        model="text-embedding-3-small",
    ).with_defaults()

    written = await store.upsert_many([entry])
    loaded = await store.load_all()

    assert written == 1
    assert len(loaded) == 1
    assert loaded[0].candidate_id == "42"
    assert loaded[0].summary["title"] == "Dev Java"
    assert loaded[0].doc_hash == "abc123"
    assert loaded[0].dims == 3
    assert loaded[0].indexed_at  # filled by with_defaults


@pytest.mark.asyncio
async def test_upsert_replaces_an_existing_candidate(
    store: SqliteVectorStore,
) -> None:
    first = IndexedCandidate(
        candidate_id="1", vector=normalise([1.0, 0.0]), doc_hash="old"
    )
    second = IndexedCandidate(
        candidate_id="1", vector=normalise([0.0, 1.0]), doc_hash="new"
    )

    await store.upsert_many([first])
    await store.upsert_many([second])
    loaded = await store.load_all()

    assert await store.count() == 1
    assert loaded[0].doc_hash == "new"


@pytest.mark.asyncio
async def test_get_hashes_returns_the_skip_map(store: SqliteVectorStore) -> None:
    await store.upsert_many(
        [
            IndexedCandidate(candidate_id="1", vector=[1.0], doc_hash="h1"),
            IndexedCandidate(candidate_id="2", vector=[1.0], doc_hash="h2"),
        ]
    )

    assert await store.get_hashes() == {"1": "h1", "2": "h2"}


@pytest.mark.asyncio
async def test_delete_reports_whether_it_removed_anything(
    store: SqliteVectorStore,
) -> None:
    await store.upsert_many(
        [IndexedCandidate(candidate_id="1", vector=[1.0])]
    )

    assert await store.delete("1") is True
    assert await store.delete("1") is False
    assert await store.count() == 0


@pytest.mark.asyncio
async def test_upsert_of_nothing_is_a_noop(store: SqliteVectorStore) -> None:
    assert await store.upsert_many([]) == 0
    assert await store.count() == 0


@pytest.mark.asyncio
async def test_use_before_initialize_raises() -> None:
    store = SqliteVectorStore(":memory:")

    with pytest.raises(RuntimeError):
        await store.count()
