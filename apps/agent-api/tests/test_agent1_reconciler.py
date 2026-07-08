"""Tests for Agent1 conflict detection and LLM reconciliation."""

from __future__ import annotations

import json

import pytest

from app.agents.agent1.normalizer import (
    NORM_CONFLICTS,
    NORM_EXPERIENCE_SOURCE,
    NORM_EXPERIENCE_YEARS,
    NORM_SKILLS,
    detect_conflicts,
    normalize_candidate,
)
from app.agents.agent1.reconciler import (
    Agent1Reconciler,
    ReconcileInput,
    parse_judgements,
)
from app.graph.nodes import NodeContext, normalize_candidates
from app.mcp.mock_client import MockMcpClient
from app.models.graph_state import GraphState
from app.models.results import SearchResult


def _result(**data: object) -> SearchResult:
    return SearchResult(
        id="42", type="candidate", title="", score=1.0,
        source_tool="searchCandidates", data=dict(data),
    )


# ── conflict detection ────────────────────────────────────────────────────────

class TestDetectConflicts:
    def test_flags_age_with_experience(self):
        result = normalize_candidate(
            _result(_enrichment_resume={
                "hasContent": True,
                "extractedText": "40 ans. 16 ans d'expérience en finance.",
            })
        )
        conflicts = result.data[NORM_CONFLICTS]
        assert "age_present_with_experience" in conflicts

    def test_flags_multiple_experience_figures(self):
        data = {
            "_enrichment_resume": {
                "hasContent": True,
                "extractedText": "10 years of experience. Later: 5 ans d'expérience.",
            }
        }
        conflicts = detect_conflicts(data, exp_years=10, exp_source="cv")
        assert "experience_multiple_figures" in conflicts

    def test_flags_structured_disagreement(self):
        data = {
            "experienceMinYears": 4,
            "_enrichment_resume": {
                "hasContent": True,
                "extractedText": "15 ans d'expérience",
            },
        }
        conflicts = detect_conflicts(data, exp_years=15, exp_source="cv")
        assert "experience_vs_structured_disagreement" in conflicts

    def test_coherent_candidate_has_no_conflicts(self):
        result = normalize_candidate(
            _result(_enrichment_resume={
                "hasContent": True,
                "extractedText": "Senior engineer with 8 years of experience in Java.",
            })
        )
        assert result.data[NORM_CONFLICTS] == []


# ── response parsing ──────────────────────────────────────────────────────────

class TestParseJudgements:
    def test_parses_valid_payload(self):
        raw = json.dumps({"judgements": [
            {"candidate_id": "42", "experience_years": 16, "confidence": 0.9},
        ]})
        out = parse_judgements(raw)
        assert out["42"].experience_years == 16

    def test_tolerates_markdown_fence(self):
        raw = "```json\n" + json.dumps({"judgements": [
            {"candidate_id": "42", "confidence": 0.5},
        ]}) + "\n```"
        out = parse_judgements(raw)
        assert "42" in out

    def test_skips_malformed_judgement_keeps_others(self):
        raw = json.dumps({"judgements": [
            {"confidence": "not-a-number"},  # invalid → skipped
            {"candidate_id": "42", "confidence": 0.7},
        ]})
        out = parse_judgements(raw)
        assert list(out) == ["42"]

    def test_raises_on_missing_array(self):
        from app.agents.agent1.reconciler import Agent1ReconcilerError
        with pytest.raises(Agent1ReconcilerError):
            parse_judgements(json.dumps({"nope": []}))


# ── reconciler ────────────────────────────────────────────────────────────────

def _input(cid: str = "42", exp: int | None = 40) -> ReconcileInput:
    return ReconcileInput(
        candidate_id=cid, title="Engineer",
        cv_text="40 ans. 16 ans d'expérience.", techdoc_text="",
        conflicts=["age_present_with_experience"], det_experience_years=exp,
    )


class TestReconciler:
    @pytest.mark.asyncio
    async def test_applies_confident_judgement(self):
        async def chat(system: str, user: str) -> str:
            return json.dumps({"judgements": [
                {"candidate_id": "42", "experience_years": 16, "confidence": 0.95},
            ]})

        rec = Agent1Reconciler(chat, confidence_threshold=0.6)
        out = await rec.reconcile([_input()])
        assert out["42"].experience_years == 16

    @pytest.mark.asyncio
    async def test_drops_low_confidence(self):
        async def chat(system: str, user: str) -> str:
            return json.dumps({"judgements": [
                {"candidate_id": "42", "experience_years": 16, "confidence": 0.2},
            ]})

        rec = Agent1Reconciler(chat, confidence_threshold=0.6)
        assert await rec.reconcile([_input()]) == {}

    @pytest.mark.asyncio
    async def test_failsafe_on_bad_output(self):
        async def chat(system: str, user: str) -> str:
            return "not json at all"

        rec = Agent1Reconciler(chat)
        assert await rec.reconcile([_input()]) == {}

    @pytest.mark.asyncio
    async def test_failsafe_on_chat_exception(self):
        async def chat(system: str, user: str) -> str:
            raise RuntimeError("boom")

        rec = Agent1Reconciler(chat)
        assert await rec.reconcile([_input()]) == {}

    @pytest.mark.asyncio
    async def test_ignores_unknown_candidate_ids(self):
        async def chat(system: str, user: str) -> str:
            return json.dumps({"judgements": [
                {"candidate_id": "999", "experience_years": 5, "confidence": 0.9},
            ]})

        rec = Agent1Reconciler(chat)
        assert await rec.reconcile([_input("42")]) == {}


# ── node integration ──────────────────────────────────────────────────────────

class _FakeReconciler:
    def __init__(self, judgements):
        self._judgements = judgements
        self.called_with = None

    async def reconcile(self, inputs):
        self.called_with = inputs
        return self._judgements


class TestNormalizeCandidatesNode:
    @pytest.mark.asyncio
    async def test_llm_overrides_conflicted_candidate(self):
        from app.agents.agent1.reconciler import Agent1Judgement

        fake = _FakeReconciler({"42": Agent1Judgement(
            candidate_id="42", experience_years=16, confidence=0.9,
        )})
        ctx = NodeContext(mcp_client=MockMcpClient(), agent1_reconciler=fake)
        state = GraphState(
            original_query="x",
            results=[_result(_enrichment_resume={
                "hasContent": True,
                "extractedText": "40 ans. 16 ans d'expérience.",
            })],
        )

        out = await normalize_candidates(state, ctx)

        # Reconciler was invoked because the candidate was flagged.
        assert fake.called_with is not None
        card_data = out.results[0].data
        assert card_data[NORM_EXPERIENCE_YEARS] == 16
        assert card_data[NORM_EXPERIENCE_SOURCE] == "llm"

        # End-to-end: the LLM value reaches the frontend card, and the internal
        # conflicts key is stripped from the card payload.
        from app.services.candidate_mapper import candidate_cards_from_results

        card = candidate_cards_from_results(out.results)[0]
        assert card.experience_years == 16
        assert not hasattr(card, "_normalized_conflicts")

    @pytest.mark.asyncio
    async def test_no_reconciler_keeps_deterministic(self):
        ctx = NodeContext(mcp_client=MockMcpClient(), agent1_reconciler=None)
        state = GraphState(
            original_query="x",
            results=[_result(_enrichment_resume={
                "hasContent": True,
                "extractedText": "8 years of experience in Java.",
            })],
        )
        out = await normalize_candidates(state, ctx)
        assert out.results[0].data[NORM_EXPERIENCE_YEARS] == 8

    @pytest.mark.asyncio
    async def test_coherent_candidates_skip_llm(self):
        fake = _FakeReconciler({})
        ctx = NodeContext(mcp_client=MockMcpClient(), agent1_reconciler=fake)
        state = GraphState(
            original_query="x",
            results=[_result(_enrichment_resume={
                "hasContent": True,
                "extractedText": "8 years of experience in Java.",
            })],
        )
        await normalize_candidates(state, ctx)
        # No conflict → reconciler never called.
        assert fake.called_with is None
