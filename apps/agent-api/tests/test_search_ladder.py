"""Executor-level tests for the recall-first relaxation ladder.

The ladder runs when the interpreted intent yields anchors: it starts
focused, broadens on empty results, enriches criteria via the technical
document, and stays honest about broadening / no results.
"""

from __future__ import annotations

import pytest

from app.graph.nodes import NodeContext, execute_llm_plan
from app.mcp.mock_client import MockMcpClient
from app.models.graph_state import GraphState
from app.models.intent import InterpretedIntent, LlmToolPlan, PlannedToolCall
from app.models.tools import McpTool
from app.services.search_service import _base_message, _build_message


_SEARCH_TOOL = McpTool(
    name="searchCandidates",
    description="Search candidates.",
    input_schema={
        "type": "object",
        "properties": {
            "keywords": {"type": "string"},
            "keywordsType": {"type": "string"},
            "experiences": {"type": "array", "items": {"type": "integer"}},
            "tools": {"type": "array", "items": {"type": "string"}},
            "page": {"type": "integer"},
            "maxResults": {"type": "integer"},
        },
    },
)
_DICTIONARY_TOOL = McpTool(
    name="getDictionary",
    description="Reference dictionary.",
    input_schema={"type": "object", "properties": {}},
)
_TECH_DOC_TOOL = McpTool(
    name="getCandidateTechnicalDocument",
    description="Technical document.",
    input_schema={
        "type": "object",
        "properties": {"candidateId": {"type": "integer"}},
    },
)


async def _dict_handler(_inputs: dict[str, object]):
    return [
        {
            "setting": {
                "experience": [{"id": 5, "label": "10+ years"}],
                "tool": [{"id": "java-id", "label": "Java"}],
            }
        }
    ]


def _ctx(client: MockMcpClient, *, max_enrichments: int = 5) -> NodeContext:
    return NodeContext(
        mcp_client=client,
        max_replan_attempts=0,
        mcp_max_retries=1,
        max_enrichments=max_enrichments,
    )


def _search_plan() -> LlmToolPlan:
    return LlmToolPlan(
        interpreted_intent={"objective": "find"},
        plan=[
            PlannedToolCall(
                tool_name="searchCandidates",
                inputs={"keywords": "ignored-by-ladder"},
            )
        ],
    )


@pytest.mark.asyncio
async def test_ladder_broadens_when_primary_pass_is_empty() -> None:
    captured: list[dict[str, object]] = []

    async def search_handler(inputs: dict[str, object]):
        captured.append(dict(inputs))
        # The primary skill keyword returns nothing; a later relaxed pass
        # (role/title) succeeds.
        if inputs.get("keywords") == "java":
            return []
        return [{"id": 1, "attributes": {"jobTitle": "Java Engineer"}}]

    client = MockMcpClient(
        tools=[_SEARCH_TOOL, _DICTIONARY_TOOL],
        handlers={"searchCandidates": search_handler, "getDictionary": _dict_handler},
    )
    state = GraphState(
        original_query="java developer",
        interpreted_intent=InterpretedIntent(
            objective="find",
            entities=["java"],
            constraints={"role": "developer"},
        ),
        available_tools=[_SEARCH_TOOL, _DICTIONARY_TOOL],
        llm_plan=_search_plan(),
    )

    result = await execute_llm_plan(state, _ctx(client))

    # The primary "java" pass ran first and a later relaxed pass recovered.
    assert len(captured) >= 2
    assert captured[0]["keywords"] == "java"
    assert captured[-1]["keywords"] == "developer"
    assert result.results and result.results[0].id == "1"
    assert any(w.code == "search_broadened" for w in result.warnings)


@pytest.mark.asyncio
async def test_ladder_reports_no_results_after_fallback() -> None:
    async def empty_search(_inputs: dict[str, object]):
        return []

    client = MockMcpClient(
        tools=[_SEARCH_TOOL, _DICTIONARY_TOOL],
        handlers={"searchCandidates": empty_search, "getDictionary": _dict_handler},
    )
    state = GraphState(
        original_query="java dev 10 years cib",
        interpreted_intent=InterpretedIntent(
            objective="find",
            entities=["java"],
            constraints={"min_experience_years": "10", "domain": "cib"},
        ),
        available_tools=[_SEARCH_TOOL, _DICTIONARY_TOOL],
        llm_plan=_search_plan(),
    )

    result = await execute_llm_plan(state, _ctx(client))

    assert result.results == []
    assert any(w.code == "no_results_after_fallback" for w in result.warnings)
    # The user-facing message is honest about the exhausted fallback.
    message = _base_message([], result)
    assert "even after broader fallback searches" in message
    assert message != "No candidates matched your search."


@pytest.mark.asyncio
async def test_ladder_searches_named_person_first_and_succeeds() -> None:
    captured: list[dict[str, object]] = []

    async def search_handler(inputs: dict[str, object]):
        captured.append(dict(inputs))
        # The name pass finds the person; any criteria pass would also return
        # data, but the ladder must stop at the successful name pass.
        if inputs.get("keywords") == "Taher ben abdallah":
            return [
                {
                    "id": 40706,
                    "attributes": {
                        "jobTitle": "Tech Lead Java backend",
                        "skills": "Java",
                    },
                }
            ]
        return [{"id": 999, "attributes": {"jobTitle": "Other Java dev"}}]

    client = MockMcpClient(
        tools=[_SEARCH_TOOL, _DICTIONARY_TOOL],
        handlers={"searchCandidates": search_handler, "getDictionary": _dict_handler},
    )
    state = GraphState(
        original_query="10 years java developer named Taher ben abdallah",
        interpreted_intent=InterpretedIntent(
            objective="find",
            entities=["java"],
            constraints={
                "role": "developer",
                "min_experience_years": "10",
                "name": "Taher ben abdallah",
            },
        ),
        available_tools=[_SEARCH_TOOL, _DICTIONARY_TOOL],
        llm_plan=_search_plan(),
    )

    result = await execute_llm_plan(state, _ctx(client))

    # The very first searchCandidates call is the name pass.
    assert captured[0]["keywords"] == "Taher ben abdallah"
    assert captured[0]["keywordsType"] == "resumeTd"
    # The named candidate is returned and no honest-miss warning fires.
    assert result.results and result.results[0].id == "40706"
    assert not any(w.code == "name_not_found" for w in result.warnings)
    assert not any(w.code == "search_broadened" for w in result.warnings)


@pytest.mark.asyncio
async def test_ladder_labels_name_miss_then_relaxes_to_criteria() -> None:
    captured: list[dict[str, object]] = []

    async def search_handler(inputs: dict[str, object]):
        captured.append(dict(inputs))
        # No one by that name; the criteria ladder (java) recovers candidates.
        if inputs.get("keywords") == "zzzz qqqq":
            return []
        return [{"id": 1, "attributes": {"jobTitle": "Java Engineer"}}]

    client = MockMcpClient(
        tools=[_SEARCH_TOOL, _DICTIONARY_TOOL],
        handlers={"searchCandidates": search_handler, "getDictionary": _dict_handler},
    )
    state = GraphState(
        original_query="java developer named zzzz qqqq",
        interpreted_intent=InterpretedIntent(
            objective="find",
            entities=["java"],
            constraints={"role": "developer", "name": "zzzz qqqq"},
        ),
        available_tools=[_SEARCH_TOOL, _DICTIONARY_TOOL],
        llm_plan=_search_plan(),
    )

    result = await execute_llm_plan(state, _ctx(client))

    # Name searched first, returned nothing, then the criteria ladder ran.
    assert captured[0]["keywords"] == "zzzz qqqq"
    assert result.results and result.results[0].id == "1"
    # Honest, labeled fallback — and NOT the generic "search_broadened".
    miss = next((w for w in result.warnings if w.code == "name_not_found"), None)
    assert miss is not None
    assert "zzzz qqqq" in miss.message
    assert not any(w.code == "search_broadened" for w in result.warnings)
    # The user-facing message leads with the honest miss note.
    message = _build_message([], result)
    assert "zzzz qqqq" in message


@pytest.mark.asyncio
async def test_ladder_enriches_best_by_evidence_not_boond_order() -> None:
    tech_called: list[int] = []

    async def search_handler(_inputs: dict[str, object]):
        # Boond order: the plain Java profile first, the Java+CIB profile
        # (relevant to the domain) second.
        return [
            {
                "id": 111,
                "attributes": {"jobTitle": "Java Developer", "skills": "Java"},
            },
            {
                "id": 222,
                "attributes": {
                    "jobTitle": "Software Engineer at SGCIB",
                    "skills": "Java, Spring",
                },
            },
        ]

    async def tech_handler(inputs: dict[str, object]):
        tech_called.append(int(inputs.get("candidateId") or 0))
        return [{"candidateId": inputs.get("candidateId"), "skills": "Java"}]

    client = MockMcpClient(
        tools=[_SEARCH_TOOL, _DICTIONARY_TOOL, _TECH_DOC_TOOL],
        handlers={
            "searchCandidates": search_handler,
            "getDictionary": _dict_handler,
            "getCandidateTechnicalDocument": tech_handler,
        },
    )
    state = GraphState(
        original_query="java dev in cib",
        interpreted_intent=InterpretedIntent(
            objective="find", entities=["java"], constraints={"domain": "cib"}
        ),
        available_tools=[_SEARCH_TOOL, _DICTIONARY_TOOL, _TECH_DOC_TOOL],
        llm_plan=LlmToolPlan(
            interpreted_intent={"objective": "find"},
            plan=[
                PlannedToolCall(
                    tool_name="searchCandidates", inputs={"keywords": "x"}
                ),
                PlannedToolCall(
                    tool_name="getCandidateTechnicalDocument",
                    inputs={},
                    depends_on="searchCandidates",
                    result_selector="candidate_ids",
                ),
            ],
        ),
    )

    # Only one enrichment slot — it must go to the evidence-best candidate.
    await execute_llm_plan(state, _ctx(client, max_enrichments=1))

    # The Java+CIB candidate (222) is enriched even though it is 2nd in
    # BoondManager order — pre-ranking by visible evidence put it first.
    assert tech_called == [222]


@pytest.mark.asyncio
async def test_ladder_enriches_with_tech_doc_not_detail() -> None:
    calls: list[str] = []

    async def search_handler(_inputs: dict[str, object]):
        calls.append("searchCandidates")
        return [{"id": 7, "attributes": {"jobTitle": "Java Engineer"}}]

    async def tech_handler(inputs: dict[str, object]):
        calls.append("getCandidateTechnicalDocument")
        return [{"candidateId": inputs.get("candidateId"), "skills": "Java"}]

    async def detail_handler(_inputs: dict[str, object]):
        calls.append("getCandidateDetail")
        return [{"id": 7}]

    detail_tool = McpTool(
        name="getCandidateDetail",
        description="Detail.",
        input_schema={
            "type": "object",
            "properties": {"candidateId": {"type": "integer"}},
        },
    )
    client = MockMcpClient(
        tools=[_SEARCH_TOOL, _DICTIONARY_TOOL, _TECH_DOC_TOOL, detail_tool],
        handlers={
            "searchCandidates": search_handler,
            "getDictionary": _dict_handler,
            "getCandidateTechnicalDocument": tech_handler,
            "getCandidateDetail": detail_handler,
        },
    )
    state = GraphState(
        original_query="java dev",
        interpreted_intent=InterpretedIntent(objective="find", entities=["java"]),
        available_tools=[_SEARCH_TOOL, _DICTIONARY_TOOL, _TECH_DOC_TOOL, detail_tool],
        llm_plan=LlmToolPlan(
            interpreted_intent={"objective": "find"},
            plan=[
                PlannedToolCall(
                    tool_name="searchCandidates", inputs={"keywords": "x"}
                ),
                PlannedToolCall(
                    tool_name="getCandidateDetail",
                    inputs={},
                    depends_on="searchCandidates",
                    result_selector="candidate_ids",
                ),
                PlannedToolCall(
                    tool_name="getCandidateTechnicalDocument",
                    inputs={},
                    depends_on="searchCandidates",
                    result_selector="candidate_ids",
                ),
            ],
        ),
    )

    await execute_llm_plan(state, _ctx(client))

    assert "getCandidateTechnicalDocument" in calls
    # getCandidateDetail is dropped from criteria enrichment.
    assert "getCandidateDetail" not in calls
