"""SQLite ConversationStore behaviour, including per-user scoping."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio

from app.storage.sqlite_store import SqliteConversationStore
from app.storage.store import derive_title

ALICE = "user-alice"
BOB = "user-bob"


@pytest_asyncio.fixture()
async def store() -> AsyncIterator[SqliteConversationStore]:
    instance = SqliteConversationStore(":memory:")
    await instance.initialize()
    yield instance
    await instance.close()


def test_derive_title_truncates_and_tidies() -> None:
    assert derive_title("  développeur   java\nangular  ") == "développeur java angular"
    assert derive_title("") == "Nouvelle conversation"
    long = "cherche un développeur fullstack java angular très senior à Paris"
    title = derive_title(long)
    assert len(title) <= 40
    assert title.endswith("…")


async def test_record_turn_creates_and_auto_titles(store) -> None:
    await store.record_turn(
        ALICE,
        "conv_1",
        user_message="développeur java",
        assistant_message="2 candidats trouvés.",
        assistant_ui={"type": "candidate_cards", "candidates": [{"id": "c1"}]},
        context={"currentSearch": {"page": 1}},
    )
    conversations = await store.list_conversations(ALICE)
    assert [c.id for c in conversations] == ["conv_1"]
    assert conversations[0].title == "développeur java"
    assert conversations[0].context == {"currentSearch": {"page": 1}}

    messages = await store.get_messages(ALICE, "conv_1")
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[1].ui == {
        "type": "candidate_cards",
        "candidates": [{"id": "c1"}],
    }


async def test_auto_title_only_on_first_message(store) -> None:
    await store.record_turn(
        ALICE, "conv_1", user_message="première recherche",
        assistant_message="ok",
    )
    await store.record_turn(
        ALICE, "conv_1", user_message="deuxième message très différent",
        assistant_message="ok",
    )
    conversation = await store.get_conversation(ALICE, "conv_1")
    assert conversation is not None
    assert conversation.title == "première recherche"


async def test_rename_is_custom_and_survives_turns(store) -> None:
    created = await store.create_conversation(ALICE)
    renamed = await store.rename_conversation(ALICE, created.id, "Mission BNP")
    assert renamed is not None and renamed.title == "Mission BNP"
    await store.record_turn(
        ALICE, created.id, user_message="dev python", assistant_message="ok"
    )
    conversation = await store.get_conversation(ALICE, created.id)
    assert conversation is not None
    assert conversation.title == "Mission BNP"
    assert conversation.title_is_custom is True


async def test_user_scoping_isolates_data(store) -> None:
    await store.record_turn(
        ALICE, "conv_alice", user_message="secret", assistant_message="ok"
    )
    assert await store.list_conversations(BOB) == []
    assert await store.get_conversation(BOB, "conv_alice") is None
    assert await store.get_messages(BOB, "conv_alice") == []
    assert await store.rename_conversation(BOB, "conv_alice", "hack") is None
    assert await store.delete_conversation(BOB, "conv_alice") is False
    # Alice's data untouched by Bob's attempts.
    assert len(await store.list_conversations(ALICE)) == 1


async def test_delete_removes_messages(store) -> None:
    await store.record_turn(
        ALICE, "conv_1", user_message="a", assistant_message="b"
    )
    assert await store.delete_conversation(ALICE, "conv_1") is True
    assert await store.get_conversation(ALICE, "conv_1") is None
    assert await store.get_messages(ALICE, "conv_1") == []
    # Recreating the id starts clean (no orphan messages).
    await store.record_turn(
        ALICE, "conv_1", user_message="c", assistant_message="d"
    )
    assert len(await store.get_messages(ALICE, "conv_1")) == 2


async def test_delete_all_only_for_user(store) -> None:
    await store.record_turn(ALICE, "a1", user_message="x", assistant_message="y")
    await store.record_turn(ALICE, "a2", user_message="x", assistant_message="y")
    await store.record_turn(BOB, "b1", user_message="x", assistant_message="y")
    assert await store.delete_all_conversations(ALICE) == 2
    assert await store.list_conversations(ALICE) == []
    assert len(await store.list_conversations(BOB)) == 1


async def test_persistence_across_connections(tmp_path) -> None:
    path = str(tmp_path / "conv.db")
    first = SqliteConversationStore(path)
    await first.initialize()
    await first.record_turn(
        ALICE, "conv_1", user_message="durable ?", assistant_message="oui"
    )
    await first.close()

    second = SqliteConversationStore(path)
    await second.initialize()
    conversations = await second.list_conversations(ALICE)
    assert [c.id for c in conversations] == ["conv_1"]
    assert len(await second.get_messages(ALICE, "conv_1")) == 2
    await second.close()
