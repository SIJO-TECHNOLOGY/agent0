"""Replaceable in-memory session store for Agent0 conversation context."""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from typing import Final, Literal

from app.session.models import SessionMemory

PAGE_SIZE: Final[int] = 12

SESSION_STORE: dict[str, SessionMemory] = {}

_AFFIRMATIONS: Final[frozenset[str]] = frozenset(
    {"oui", "non", "yes", "no", "ok", "okay", "d'accord", "daccord", "ouais", "yep", "yup"}
)

_MORE_PHRASES: Final[frozenset[str]] = frozenset(
    {
        "d'autres", "dautres", "d'autres profils", "d'autres candidats",
        "autres", "autre", "autres profils", "plus", "plus de profils",
        "encore", "suivant", "suivants", "page suivante",
        "montre m'en plus", "montre moi plus", "montre-moi plus",
        "more", "next", "show more", "others", "other", "more profiles",
    }
)


@dataclass(frozen=True)
class SessionOperation:
    """Decision for one incoming turn before Agent0 runs."""

    session: SessionMemory
    effective_query: str
    is_follow_up: bool
    should_reset_search: bool
    action: Literal["search", "filter", "sort", "more", "explain", "detail"]
    filters: dict[str, object] = field(default_factory=dict)
    candidates: list[dict[str, object]] | None = None
    message: str | None = None


def new_session_id() -> str:
    return f"session_{uuid.uuid4().hex[:12]}"


def get_or_create(session_id: str | None) -> SessionMemory:
    sid = session_id or new_session_id()
    memory = SESSION_STORE.get(sid)
    if memory is None:
        memory = SessionMemory(session_id=sid)
        SESSION_STORE[sid] = memory
    return memory


def reset(session_id: str) -> None:
    SESSION_STORE.pop(session_id, None)


def append_message(
    session_id: str,
    *,
    role: Literal["user", "assistant"],
    content: str,
) -> SessionMemory:
    memory = get_or_create(session_id)
    memory.messages.append({"role": role, "content": content})
    if role == "user":
        memory.last_user_query = content
    else:
        memory.last_agent_response = content
    memory.touch()
    return memory


def context_payload(session_id: str) -> dict[str, object]:
    return get_or_create(session_id).public_context()


def context_snapshot(session_id: str) -> dict[str, object]:
    """Search-session state persisted with each stored turn.

    Enough to rehydrate follow-ups ("more", filters) after a restart:
    the current search (query, provider page, seen ids) and the active
    filters.
    """
    session = get_or_create(session_id)
    return {
        "currentSearch": dict(session.current_search),
        "lastFilters": dict(session.last_filters),
    }


def save_search_results(
    session_id: str,
    *,
    query: str,
    effective_query: str,
    candidates: list[dict[str, object]],
    filters: dict[str, object] | None = None,
) -> SessionMemory:
    memory = get_or_create(session_id)
    merged_filters = {**memory.last_filters, **(filters or {})}
    memory.current_search = {
        "query": query,
        "effectiveQuery": effective_query,
        "candidateCount": len(candidates),
    }
    if merged_filters:
        memory.current_search["filters"] = merged_filters
    memory.last_filters = merged_filters
    memory.current_candidates = list(candidates)
    memory.touch()
    return memory


# Core "more" words, generic result nouns, and harmless filler. A message made
# ONLY of these (with at least one core word) is a "show me more" follow-up —
# so "donne moi d'autres profils" matches, but "d'autres profils java" (new
# criteria) does not.
_MORE_CORE: Final[frozenset[str]] = frozenset(
    {"dautres", "autres", "plus", "more", "next", "suivant", "suivants", "encore", "others"}
)
_MORE_NOUNS: Final[frozenset[str]] = frozenset(
    {"profil", "profils", "candidat", "candidats", "profile", "profiles",
     "candidate", "candidates", "resultat", "resultats", "results", "personnes"}
)
_MORE_FILLER: Final[frozenset[str]] = frozenset(
    {"donne", "donnes", "moi", "montre", "montres", "nous", "en", "de", "des",
     "d", "du", "la", "le", "les", "un", "une", "voir", "veux", "peux", "tu",
     "vous", "je", "merci", "stp", "svp", "plait", "sil", "te", "m", "give",
     "me", "show", "some", "please", "ten", "t", "aurais", "auriez", "avez",
     "as", "a", "y", "il", "quelques", "uns", "unes"}
)


def is_more_request(message: str) -> bool:
    """True when the message only asks for more results (no new criteria)."""
    normalized = _normalized(message).strip(" .!?")
    if normalized in _MORE_PHRASES:
        return True
    tokens = [t for t in re.split(r"[\s'’\-,.!?]+", normalized) if t]
    if not tokens:
        return False
    vocab = _MORE_CORE | _MORE_NOUNS | _MORE_FILLER
    return all(t in vocab for t in tokens) and any(t in _MORE_CORE for t in tokens)


def is_reset_request(message: str) -> bool:
    normalized = _normalized(message)
    return normalized.startswith(("nouvelle recherche", "new search", "reset", "recommence"))


def combine_query(prior: str, new_message: str) -> str:
    new_clean = new_message.strip()
    prior_clean = prior.strip()
    if not prior_clean:
        return new_clean
    if not new_clean:
        return prior_clean
    if _normalized(new_clean).strip(" .!?") in _AFFIRMATIONS:
        return prior_clean
    if new_clean.lower() in prior_clean.lower():
        return prior_clean
    return f"{prior_clean} {new_clean}".strip()


def resolve_turn(session_id: str | None, message: str) -> SessionOperation:
    memory = get_or_create(session_id)
    normalized = _normalized(message)
    should_reset = is_reset_request(message)
    has_context = bool(memory.current_search or memory.current_candidates or memory.last_user_query)

    if should_reset:
        memory.current_search = {}
        memory.last_filters = {}
        memory.current_candidates = []

    if is_more_request(message):
        return SessionOperation(
            session=memory,
            effective_query=memory.current_search.get("effectiveQuery", memory.last_user_query) or message,
            is_follow_up=has_context,
            should_reset_search=False,
            action="more",
        )

    filters = _extract_filters(message)
    if not should_reset and memory.current_candidates:
        if _is_sort_request(normalized):
            candidates = _sort_candidates(memory.current_candidates, normalized)
            return SessionOperation(
                session=memory,
                effective_query=memory.current_search.get("effectiveQuery", memory.last_user_query) or message,
                is_follow_up=True,
                should_reset_search=False,
                action="sort",
                filters=filters,
                candidates=candidates,
                message=_filter_message(candidates, prefix="Candidats triés"),
            )
        if _is_filter_request(normalized, filters):
            candidates = _apply_filters(memory.current_candidates, filters, normalized)
            return SessionOperation(
                session=memory,
                effective_query=combine_query(
                    str(memory.current_search.get("effectiveQuery", memory.last_user_query)),
                    message,
                ),
                is_follow_up=True,
                should_reset_search=False,
                action="filter",
                filters=filters,
                candidates=candidates,
                message=_filter_message(candidates),
            )

    prior = "" if should_reset else str(memory.current_search.get("effectiveQuery", memory.last_user_query))
    return SessionOperation(
        session=memory,
        effective_query=combine_query(prior, message),
        is_follow_up=has_context and not should_reset,
        should_reset_search=should_reset,
        action="search",
        filters=filters,
    )


def _extract_filters(message: str) -> dict[str, object]:
    normalized = _normalized(message)
    filters: dict[str, object] = {}
    if any(term in normalized for term in ("ile-de-france", "ile de france", "idf", "paris")):
        filters["location"] = "Ile-de-France"
    if any(term in normalized for term in ("spring boot", "springboot")):
        filters.setdefault("skills", [])
        filters["skills"] = [*filters["skills"], "Spring Boot"]  # type: ignore[index]
    if "java" in normalized:
        filters.setdefault("skills", [])
        if "Java" not in filters["skills"]:  # type: ignore[operator]
            filters["skills"] = [*filters["skills"], "Java"]  # type: ignore[index]
    if any(term in normalized for term in ("retire", "exclu", "exclus", "sans", "pas en mission")):
        if any(term in normalized for term in ("mission", "occupe", "occupes", "non disponible")):
            filters["exclude_on_assignment"] = True
    if any(term in normalized for term in ("disponible", "disponibilite", "availability")):
        filters["availability"] = "available"
    return filters


def _is_filter_request(normalized: str, filters: dict[str, object]) -> bool:
    if filters:
        return True
    return normalized.startswith(("seulement", "uniquement", "ajoute", "retire", "sans", "filtre"))


def _is_sort_request(normalized: str) -> bool:
    return any(term in normalized for term in ("tri", "trie", "class", "sort")) and any(
        term in normalized for term in ("disponibilite", "availability", "score", "pertinence")
    )


def _apply_filters(
    candidates: list[dict[str, object]],
    filters: dict[str, object],
    normalized_message: str,
) -> list[dict[str, object]]:
    filtered = list(candidates)
    location = filters.get("location")
    if isinstance(location, str):
        wanted = _normalized(location)
        filtered = [
            c for c in filtered
            if wanted in _normalized(c.get("location")) or "paris" in _normalized(c.get("location"))
        ]
    skills = filters.get("skills")
    if isinstance(skills, list) and skills:
        wanted_skills = {_normalized(skill) for skill in skills}
        filtered = [
            c for c in filtered
            if wanted_skills.issubset({_normalized(skill) for skill in c.get("skills", []) if skill})
        ]
    if filters.get("exclude_on_assignment"):
        filtered = [c for c in filtered if not _looks_on_assignment(c)]
    if filters.get("availability") == "available" and "retire" not in normalized_message:
        filtered = [c for c in filtered if _availability_rank(c) < 10]
    return filtered


def _sort_candidates(candidates: list[dict[str, object]], normalized_message: str) -> list[dict[str, object]]:
    if "score" in normalized_message or "pertinence" in normalized_message:
        return sorted(candidates, key=lambda c: float(c.get("match_score") or 0), reverse=True)
    return sorted(candidates, key=_availability_rank)


def _looks_on_assignment(candidate: dict[str, object]) -> bool:
    text = _normalized(" ".join(str(candidate.get(key) or "") for key in ("availability", "state_label", "summary")))
    return any(term in text for term in ("en mission", "occupe", "occupee", "non disponible"))


def _availability_rank(candidate: dict[str, object]) -> int:
    text = _normalized(candidate.get("availability"))
    if not text:
        return 50
    if any(term in text for term in ("immediat", "disponible maintenant", "available immediately")):
        return 0
    match = re.search(r"(\d+)\s*(jour|j|day)", text)
    if match:
        return int(match.group(1))
    match = re.search(r"(\d+)\s*(mois|month)", text)
    if match:
        return int(match.group(1)) * 30
    if "disponible" in text or "available" in text:
        return 5
    if "preavis" in text:
        return 30
    return 50


def _filter_message(candidates: list[dict[str, object]], *, prefix: str = "Contexte mis à jour") -> str:
    count = len(candidates)
    if count == 0:
        return f"{prefix} : aucun candidat conservé avec ces critères."
    if count == 1:
        return f"{prefix} : 1 candidat conservé."
    return f"{prefix} : {count} candidats conservés."


def _normalized(value: object) -> str:
    text = str(value or "").strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    return text
