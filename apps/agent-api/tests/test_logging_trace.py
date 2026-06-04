"""Tests for the readable decision-trace logging."""

from __future__ import annotations

import logging

import pytest

from app.main import _ExtraRenderingFormatter, _configure_logging, _NOISY_LOGGERS
from app.services.event_emitter import DecisionTraceEmitter


class _RecordingDelegate:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def emit(self, event_type: str, payload: dict) -> None:
        self.events.append((event_type, payload))


@pytest.mark.asyncio
async def test_trace_emitter_forwards_every_event(caplog) -> None:
    delegate = _RecordingDelegate()
    trace = DecisionTraceEmitter(delegate)
    await trace.emit("search_started", {"query": "java dev", "planner_mode": "llm"})
    await trace.emit("final_response", {"message": "I found 25 candidates."})
    # Always forwarded to the wrapped emitter (streaming unaffected).
    assert [e[0] for e in delegate.events] == ["search_started", "final_response"]


@pytest.mark.asyncio
async def test_trace_emitter_logs_decisions(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="agent.trace"):
        trace = DecisionTraceEmitter(_RecordingDelegate())
        await trace.emit("search_started", {"query": "java dev in CIB", "planner_mode": "llm"})
        await trace.emit(
            "plan_created",
            {"plan": [{"tool_name": "searchCandidates", "inputs": {"keywords": "+java +CIB"}, "reason": "recall"}]},
        )
        await trace.emit(
            "replan_requested",
            {"decided_by": "llm", "reason": "no full matches", "guidance": "add seniority"},
        )
        await trace.emit(
            "candidate_cards_partial",
            {"candidates": [{"full_name": "Antoni", "match_score": 0.63, "is_full_match": False, "unmet_criteria": ["10+ years"]}]},
        )
        await trace.emit("final_response", {"message": "I found 25 candidates."})

    text = "\n".join(r.message for r in caplog.records)
    assert "SEARCH [llm]" in text and "java dev in CIB" in text
    assert "PLAN (LLM)" in text and "+java +CIB" in text
    assert "REPLAN (decided by llm)" in text and "add seniority" in text
    assert "RANKED" in text and "Antoni" in text
    assert "RESULT:" in text


@pytest.mark.asyncio
async def test_trace_collapses_enrichment_calls(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="agent.trace"):
        trace = DecisionTraceEmitter(_RecordingDelegate())
        # searchCandidates is a decision → shown; tech-doc fan-out → collapsed.
        await trace.emit("tool_call_completed", {"tool": "searchCandidates", "status": "success", "result_count": 25})
        await trace.emit("tool_call_completed", {"tool": "getCandidateTechnicalDocument", "status": "success", "result_count": 1})

    lines = [r.message for r in caplog.records]
    assert any("search → 25 results" in m for m in lines)
    assert not any("getCandidateTechnicalDocument" in m for m in lines)


@pytest.mark.asyncio
async def test_trace_verbose_shows_enrichment_calls(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="agent.trace"):
        trace = DecisionTraceEmitter(_RecordingDelegate(), verbose=True)
        await trace.emit(
            "tool_call_completed",
            {"tool": "getCandidateTechnicalDocument", "status": "success", "result_count": 1},
        )
    assert any("getCandidateTechnicalDocument" in r.message for r in caplog.records)


def _record_with_extras() -> logging.LogRecord:
    record = logging.LogRecord(
        name="app.graph.nodes", level=logging.INFO, pathname=__file__, lineno=1,
        msg="graph.rank_candidates", args=(), exc_info=None,
    )
    record.skills = ["java"]
    record.ranked = [{"id": "1", "score": 0.6}]
    return record


def test_extra_rendering_formatter_shows_extra_fields() -> None:
    fmt = _ExtraRenderingFormatter("%(levelname)s %(name)s %(message)s")
    out = fmt.format(_record_with_extras())
    assert "graph.rank_candidates" in out
    assert "skills=" in out and "java" in out
    assert "ranked=" in out


def test_configure_logging_default_hides_json_verbose_shows_it(
    capfd: pytest.CaptureFixture[str],
) -> None:
    # Default (non-verbose): plain formatter -> no JSON tail on app lines.
    _configure_logging("INFO", verbose=False)
    logging.getLogger("app.graph.nodes").handle(_record_with_extras())
    default_err = capfd.readouterr().err
    assert "graph.rank_candidates" in default_err
    assert "skills=" not in default_err  # JSON extras suppressed by default

    # Verbose: extras rendered as JSON.
    _configure_logging("INFO", verbose=True)
    logging.getLogger("app.graph.nodes").handle(_record_with_extras())
    verbose_err = capfd.readouterr().err
    assert "skills=" in verbose_err and "java" in verbose_err


def test_configure_logging_quiets_noisy_loggers() -> None:
    _configure_logging("INFO")
    for noisy in _NOISY_LOGGERS:
        assert logging.getLogger(noisy).level == logging.WARNING


def test_agent_trace_setting_default_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config.settings import Settings

    assert Settings().agent_trace == "on"
    monkeypatch.setenv("AGENT_TRACE", "verbose")
    assert Settings().agent_trace == "verbose"
    monkeypatch.setenv("AGENT_TRACE", "off")
    assert Settings().agent_trace == "off"
