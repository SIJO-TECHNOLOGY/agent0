"""Compatibility facade over the structured session memory package."""

from __future__ import annotations

from app.session import memory as session_memory

PAGE_SIZE = session_memory.PAGE_SIZE
SESSION_STORE = session_memory.SESSION_STORE

# Backwards-compatible views used by existing routes/tests. They mirror the
# richer SessionMemory fields but are not the source of truth anymore.
_queries: dict[str, str] = {}
_pools: dict[str, dict] = {}


def new_conversation_id() -> str:
    return session_memory.new_session_id().replace("session_", "conv_", 1)


def new_session_id() -> str:
    return session_memory.new_session_id()


def is_more_request(message: str) -> bool:
    return session_memory.is_more_request(message)


def combine_query(prior: str, new_message: str) -> str:
    return session_memory.combine_query(prior, new_message)


def accumulate_query(conversation_id: str, message: str) -> str:
    memory = session_memory.get_or_create(conversation_id)
    prior = str(memory.current_search.get("effectiveQuery", memory.last_user_query))
    effective = session_memory.combine_query(prior, message)
    _queries[conversation_id] = effective
    memory.last_user_query = effective
    memory.current_search = {**memory.current_search, "effectiveQuery": effective}
    memory.touch()
    return effective


def store_results(conversation_id: str, candidates: list[dict]) -> None:
    _pools[conversation_id] = {
        "candidates": list(candidates),
        "shown": 0,
        "total": len(candidates),
    }
    memory = session_memory.get_or_create(conversation_id)
    session_memory.save_search_results(
        conversation_id,
        query=memory.last_user_query,
        effective_query=str(memory.current_search.get("effectiveQuery", memory.last_user_query)),
        candidates=list(candidates),
    )


def mark_all_shown(conversation_id: str) -> None:
    """Record that every stored candidate has been displayed (no pagination)."""
    pool = _pools.get(conversation_id)
    if pool is not None:
        pool["shown"] = pool["total"]


def has_pool(conversation_id: str) -> bool:
    return conversation_id in _pools or bool(
        session_memory.get_or_create(conversation_id).current_candidates
    )


def next_page(conversation_id: str) -> dict:
    if conversation_id not in _pools:
        candidates = session_memory.get_or_create(conversation_id).current_candidates
        _pools[conversation_id] = {
            "candidates": list(candidates),
            "shown": 0,
            "total": len(candidates),
        }
    pool = _pools.get(conversation_id) or {"candidates": [], "shown": 0, "total": 0}
    candidates: list[dict] = pool["candidates"]
    shown: int = pool["shown"]
    total: int = pool["total"]
    page = candidates[shown : shown + PAGE_SIZE]
    if page:
        pool["shown"] = shown + len(page)
        _pools[conversation_id] = pool
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


def reset(conversation_id: str) -> None:
    _queries.pop(conversation_id, None)
    _pools.pop(conversation_id, None)
    session_memory.reset(conversation_id)
