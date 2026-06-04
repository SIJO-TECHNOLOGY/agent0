"""Transport-agnostic workflow event emitter.

The Agent API workflow produces a sequence of UI-friendly progress
events (``search_started``, ``plan_created``, ``tool_call_started``,
etc.). Whether those events are streamed to an HTTP client, written
to a log, or discarded entirely is decided by the caller via the
``EventEmitter`` they pass into ``NodeContext``.

The default emitter is ``NoopEventEmitter`` so the non-streaming
``POST /api/search`` path runs with zero overhead and no behavioural
change.

This module knows nothing about HTTP, SSE, or LangGraph. Sanitization
of payloads is the responsibility of the caller — we just ferry the
dict the node decided was safe.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Final, Protocol

_trace_logger = logging.getLogger("agent.trace")


class EventEmitter(Protocol):
    """Async emitter for workflow progress events."""

    async def emit(
        self, event_type: str, payload: dict[str, object]
    ) -> None: ...


def _clip(value: object, limit: int = 140) -> str:
    text = value if isinstance(value, str) else str(value)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class DecisionTraceEmitter(EventEmitter):
    """Wraps another emitter and logs a readable per-request decision tree.

    Reuses the workflow's existing progress events (no extra instrumentation)
    and renders only the *decisions* — interpreted plan, search recall, ranking,
    the LLM reflection/replan verdict, and the final outcome — to the
    ``agent.trace`` logger. Mechanical enrichment fan-out (per-candidate
    technical-document fetches) is intentionally collapsed so the tree stays
    about what the LLM/agent decided, not every HTTP call. Always forwards the
    event to the wrapped emitter, so streaming behaviour is unchanged.
    """

    def __init__(self, delegate: EventEmitter, *, verbose: bool = False) -> None:
        self._delegate = delegate
        self._verbose = verbose
        self._reason_clip = 220 if verbose else 90
        self._kw_clip = 200 if verbose else 80

    async def emit(self, event_type: str, payload: dict[str, object]) -> None:
        try:
            for line in self._render(event_type, payload):
                _trace_logger.info(line)
        except Exception:  # noqa: BLE001
            pass
        await self._delegate.emit(event_type, payload)

    def _render(self, event_type: str, p: dict[str, object]) -> list[str]:
        if event_type == "search_started":
            return [
                f"╭─ SEARCH [{p.get('planner_mode', '?')}] {_clip(p.get('query'))}"
            ]
        if event_type == "tools_discovered":
            names = [str(t.get("name")) for t in _as_list(p.get("tools"))]
            return [f"│  tools_discovered: {', '.join(names)}"]
        if event_type in ("plan_created", "replan_created"):
            tag = "REPLAN PLAN" if event_type == "replan_created" else "PLAN"
            lines = [f"│  {tag} (LLM):"]
            for i, step in enumerate(_as_list(p.get("plan")), 1):
                tool = step.get("tool_name") or step.get("tool") or "?"
                kw = _step_keywords(step)
                reason = _clip(step.get("reason"), self._reason_clip)
                kw_s = f" kw={_clip(kw, self._kw_clip)}" if kw else ""
                lines.append(f"│    {i}. {tool}{kw_s}" + (f" — {reason}" if reason else ""))
            return lines
        if event_type == "replan_requested":
            return [
                f"│  ⟲ REPLAN (decided by {p.get('decided_by', '?')}): "
                f"{_clip(p.get('reason'), self._reason_clip)}",
                f"│      guidance: {_clip(p.get('guidance'), self._reason_clip)}",
            ]
        if event_type == "tool_call_completed":
            tool = str(p.get("tool", "?"))
            status = str(p.get("status", "?"))
            if tool.startswith("search"):
                return [f"│  search → {p.get('result_count')} results ({status})"]
            if status not in ("success", "empty"):
                return [f"│  {tool} {status}: {_clip(p.get('error_message'))}"]
            if self._verbose:
                return [f"│    · {tool} → {p.get('result_count')} ({status})"]
            return []
        if event_type == "candidate_cards_partial":
            cards = _as_list(p.get("candidates"))[:3]
            lines = [f"│  RANKED (top {len(cards)} of {len(_as_list(p.get('candidates')))}):"]
            for c in cards:
                lines.append(
                    f"│    {_clip(c.get('full_name'), 30)} "
                    f"score={c.get('match_score')} full={c.get('is_full_match')} "
                    f"unmet={c.get('unmet_criteria')}"
                )
            return lines
        if event_type == "final_response":
            return [f"╰─ RESULT: {_clip(p.get('message'))}"]
        return []


def _as_list(value: object) -> list[dict[str, object]]:
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def _step_keywords(step: dict[str, object]) -> object:
    inputs = step.get("inputs")
    if isinstance(inputs, dict):
        return inputs.get("keywords")
    return None


class NoopEventEmitter(EventEmitter):
    """Discards every event. Used by the non-streaming search path."""

    async def emit(
        self, event_type: str, payload: dict[str, object]
    ) -> None:
        return None


# Sentinel placed onto the queue to signal "no more events" to consumers.
_QUEUE_END: Final[object] = object()


class QueueEventEmitter(EventEmitter):
    """Bounded async-queue emitter consumed by the streaming route.

    The streaming route iterates this emitter with ``async for`` while
    a background task drives the workflow and calls ``emit``. When the
    workflow finishes (or fails) the producer calls ``close``; iteration
    then terminates.
    """

    def __init__(self, *, maxsize: int = 256) -> None:
        self._queue: asyncio.Queue[object] = asyncio.Queue(maxsize=maxsize)
        self._closed = False

    async def emit(
        self, event_type: str, payload: dict[str, object]
    ) -> None:
        if self._closed:
            return
        await self._queue.put({"type": event_type, "data": payload})

    def close(self) -> None:
        """Signal end-of-stream to the consumer. Safe to call twice."""
        if self._closed:
            return
        self._closed = True
        # put_nowait is safe here: the queue is bounded but the sentinel
        # itself is tiny; if the consumer is slow we accept the delay.
        try:
            self._queue.put_nowait(_QUEUE_END)
        except asyncio.QueueFull:
            # Drop one event to make room for the sentinel. The consumer
            # must always learn the stream ended.
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            self._queue.put_nowait(_QUEUE_END)

    def __aiter__(self) -> AsyncIterator[dict[str, object]]:
        return self._consume()

    async def _consume(self) -> AsyncIterator[dict[str, object]]:
        while True:
            item = await self._queue.get()
            if item is _QUEUE_END:
                return
            assert isinstance(item, dict)
            yield item
