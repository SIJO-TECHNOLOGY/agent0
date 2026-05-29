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
from collections.abc import AsyncIterator
from typing import Final, Protocol


class EventEmitter(Protocol):
    """Async emitter for workflow progress events."""

    async def emit(
        self, event_type: str, payload: dict[str, object]
    ) -> None: ...


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
