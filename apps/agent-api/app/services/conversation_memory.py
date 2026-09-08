"""Compatibility facade over the structured session memory package."""

from __future__ import annotations

from app.session import memory as session_memory
from app.session.memory import SessionKey

PAGE_SIZE = session_memory.PAGE_SIZE
SESSION_STORE = session_memory.SESSION_STORE

# Query text and paginated result pools per session. Keyed by SessionKey
# ``(user_oid, conversation_id)`` — never the conversation id alone — so one
# user's pool can never be read or overwritten through another user's request.
_queries: dict[SessionKey, str] = {}
_pools: dict[SessionKey, dict] = {}


def new_conversation_id() -> str:
    return session_memory.new_session_id().replace("session_", "conv_", 1)


def new_session_id() -> str:
    return session_memory.new_session_id()


def is_more_request(message: str) -> bool:
    return session_memory.is_more_request(message)


def combine_query(prior: str, new_message: str) -> str:
    return session_memory.combine_query(prior, new_message)


def accumulate_query(user_oid: str, conversation_id: str, message: str) -> str:
    memory = session_memory.get_or_create(user_oid, conversation_id)
    prior = str(memory.current_search.get("effectiveQuery", memory.last_user_query))
    effective = session_memory.combine_query(prior, message)
    _queries[SessionKey(user_oid=user_oid, conversation_id=conversation_id)] = effective
    memory.last_user_query = effective
    memory.current_search = {**memory.current_search, "effectiveQuery": effective}
    memory.touch()
    return effective


def store_results(user_oid: str, conversation_id: str, candidates: list[dict]) -> None:
    _pools[SessionKey(user_oid=user_oid, conversation_id=conversation_id)] = {
        "candidates": list(candidates),
        "shown": 0,
        "total": len(candidates),
    }
    memory = session_memory.get_or_create(user_oid, conversation_id)
    session_memory.save_search_results(
        user_oid,
        conversation_id,
        query=memory.last_user_query,
        effective_query=str(memory.current_search.get("effectiveQuery", memory.last_user_query)),
        candidates=list(candidates),
    )


def set_query(user_oid: str, conversation_id: str, effective_query: str) -> None:
    """Record the effective query for a session (isolated per user)."""
    _queries[SessionKey(user_oid=user_oid, conversation_id=conversation_id)] = effective_query


def clear_results(user_oid: str, conversation_id: str) -> None:
    """Drop this user's result pool for a conversation (isolated per user)."""
    _pools.pop(SessionKey(user_oid=user_oid, conversation_id=conversation_id), None)


def mark_all_shown(user_oid: str, conversation_id: str) -> None:
    """Record that every stored candidate has been displayed (no pagination)."""
    pool = _pools.get(SessionKey(user_oid=user_oid, conversation_id=conversation_id))
    if pool is not None:
        pool["shown"] = pool["total"]


def has_pool(user_oid: str, conversation_id: str) -> bool:
    key = SessionKey(user_oid=user_oid, conversation_id=conversation_id)
    return key in _pools or bool(
        session_memory.get_or_create(user_oid, conversation_id).current_candidates
    )


def next_page(user_oid: str, conversation_id: str) -> dict:
    key = SessionKey(user_oid=user_oid, conversation_id=conversation_id)
    if key not in _pools:
        candidates = session_memory.get_or_create(user_oid, conversation_id).current_candidates
        _pools[key] = {
            "candidates": list(candidates),
            "shown": 0,
            "total": len(candidates),
        }
    pool = _pools.get(key) or {"candidates": [], "shown": 0, "total": 0}
    candidates: list[dict] = pool["candidates"]
    shown: int = pool["shown"]
    total: int = pool["total"]
    page = candidates[shown : shown + PAGE_SIZE]
    if page:
        pool["shown"] = shown + len(page)
        _pools[key] = pool
    return {
        "candidates": page,
        "start": shown + 1 if page else shown,
        "end": shown + len(page),
        "total": total,
        "has_more": (shown + len(page)) < total,
    }


def pagination_message(info: dict) -> str:
    if not info["candidates"]:
        return "Plus de candidats a afficher pour cette recherche."
    suffix = " Dis 'd'autres' pour la suite." if info["has_more"] else ""
    return f"{info['total']} candidats trouves - affichage {info['start']}-{info['end']}.{suffix}"


def reset(user_oid: str, conversation_id: str) -> None:
    """Drop this user's runtime state for a conversation (isolated per user)."""
    key = SessionKey(user_oid=user_oid, conversation_id=conversation_id)
    _queries.pop(key, None)
    _pools.pop(key, None)
    session_memory.reset(user_oid, conversation_id)
