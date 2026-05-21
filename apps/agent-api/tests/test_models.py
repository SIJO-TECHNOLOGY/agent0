"""Pydantic schema tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.api import SearchRequest
from app.models.tools import ToolCall, ToolCallStatus


def test_search_request_strips_query() -> None:
    request = SearchRequest(query="  python consultants  ")
    assert request.query == "python consultants"
    assert request.filters == {}


def test_search_request_rejects_blank_query() -> None:
    with pytest.raises(ValidationError):
        SearchRequest(query="   ")


def test_search_request_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        SearchRequest(query="hi", unexpected="value")  # type: ignore[call-arg]


def test_tool_call_defaults() -> None:
    call = ToolCall(tool="search_consultants", status=ToolCallStatus.EMPTY)
    assert call.attempts == 1
    assert call.latency_ms == 0
    assert call.result_count == 0
    assert call.error_message is None
