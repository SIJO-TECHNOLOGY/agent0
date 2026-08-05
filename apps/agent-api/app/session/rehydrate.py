"""Rebuild the in-memory session of a conversation from the durable store.

`SESSION_STORE` lives in process memory, so a server restart forgets
every conversation's search context: a follow-up like "montre-m'en
d'autres" would then restart from scratch instead of continuing on the
provider's next page, and filter/sort turns would lose the candidate
pool they operate on.

Every persisted turn already carries a context snapshot (current
search: query, provider page, seen ids; active filters) and the
candidate cards shown. This module replays them into a fresh
`SessionMemory` the first time a turn arrives for a conversation the
process does not know — making restarts invisible to the user.
"""

from __future__ import annotations

import logging

from app.session import memory as session_memory
from app.storage import ConversationStore

logger = logging.getLogger(__name__)


async def ensure_session_hydrated(
    store: ConversationStore | None,
    user_id: str,
    conversation_id: str,
) -> None:
    """Restore the conversation's session from the store when absent.

    No-ops when the session is already live (the common case: one
    dict lookup), when there is no store (tests without fixture), or
    when the conversation does not exist / belongs to another user.
    Never raises: a failed hydration degrades to the pre-restart
    behaviour (a fresh search) instead of breaking the turn.
    """
    if store is None:
        return
    if conversation_id in session_memory.SESSION_STORE:
        return

    try:
        stored = await store.get_conversation(user_id, conversation_id)
        if stored is None:
            return
        messages = await store.get_messages(user_id, conversation_id)
    except Exception:  # noqa: BLE001 — hydration must never break a turn
        logger.exception("session.rehydrate_failed")
        return

    session = session_memory.get_or_create(conversation_id)

    current_search = stored.context.get("currentSearch")
    if isinstance(current_search, dict):
        session.current_search = dict(current_search)
    last_filters = stored.context.get("lastFilters")
    if isinstance(last_filters, dict):
        session.last_filters = dict(last_filters)

    for message in messages:
        session.messages.append(
            {"role": message.role, "content": message.content}
        )
        if message.role == "user":
            session.last_user_query = message.content
        elif message.role == "assistant":
            session.last_agent_response = message.content

    # The candidate pool filter/sort turns operate on: the cards from
    # the most recent assistant turn that displayed candidates.
    for message in reversed(messages):
        ui = message.ui or {}
        if message.role == "assistant" and ui.get("type") == "candidate_cards":
            candidates = ui.get("candidates")
            if isinstance(candidates, list):
                session.current_candidates = [
                    dict(candidate)
                    for candidate in candidates
                    if isinstance(candidate, dict)
                ]
            break

    session.touch()
    logger.info(
        "session.rehydrated",
        extra={
            "conversation_id": conversation_id,
            "messages": len(messages),
            "candidates": len(session.current_candidates),
            "hasSearchContext": bool(session.current_search),
        },
    )
