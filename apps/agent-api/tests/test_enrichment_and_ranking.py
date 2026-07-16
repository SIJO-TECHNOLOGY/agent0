"""Tests for `enrich_candidates` and `rank_candidates` graph nodes."""

from __future__ import annotations

import pytest

from app.graph.nodes import (
    ENRICHMENT_DETAIL_KEY,
    ENRICHMENT_TECH_DOC_KEY,
    NodeContext,
    _candidate_min_years,
    enrich_candidates,
    rank_candidates,
)


def test_candidate_min_years_trusts_agent1_not_loose_text() -> None:
    # Agent1 resolved 3 years; a stray "10 ans" in the haystack must NOT inflate
    # the candidate's experience used for seniority scoring.
    result = SearchResult(
        id="1", type="candidate", title="", score=0.5, source_tool="searchCandidates",
        data={"_normalized_experience_years": 3},
    )
    assert _candidate_min_years(result, "java 10 ans projet sur 10 ans") == 3


def test_candidate_min_years_falls_back_to_text_when_agent1_empty() -> None:
    # No Agent1 value (e.g. pre-ranking) → fall back to the loose text parse.
    result = SearchResult(
        id="2", type="candidate", title="", score=0.5, source_tool="searchCandidates",
        data={},
    )
    assert _candidate_min_years(result, "8 ans d'expérience java") == 8
from app.mcp.mock_client import MockMcpClient
from app.models.graph_state import GraphState
from app.models.intent import InterpretedIntent
from app.models.results import SearchResult
from app.models.tools import McpTool, ToolCallStatus


def _detail_tool() -> McpTool:
    return McpTool(
        name="getCandidateDetail",
        description="Fetch candidate by id.",
        input_schema={
            "type": "object",
            "properties": {"candidateId": {"type": "integer"}},
        },
    )


def _tech_doc_tool() -> McpTool:
    return McpTool(
        name="getCandidateTechnicalDocument",
        description="Fetch the candidate's technical document.",
        input_schema={
            "type": "object",
            "properties": {"candidateId": {"type": "integer"}},
        },
    )


def _result(
    *, candidate_id: str, source_tool: str = "searchCandidates", data: dict | None = None
) -> SearchResult:
    return SearchResult(
        id=candidate_id,
        type="candidate",
        title="",
        score=0.5,
        source_tool=source_tool,
        data=dict(data or {}),
    )


def _ctx(client: MockMcpClient, *, max_enrichments: int = 5) -> NodeContext:
    return NodeContext(
        mcp_client=client,
        max_replan_attempts=0,
        mcp_max_retries=1,
        max_enrichments=max_enrichments,
    )


@pytest.mark.asyncio
async def test_enrich_calls_get_candidate_detail_for_top_n() -> None:
    captured: list[dict[str, object]] = []

    async def detail_handler(inputs: dict[str, object]) -> list[dict[str, object]]:
        captured.append(dict(inputs))
        cid = inputs.get("candidateId") or inputs.get("id")
        return [{"id": cid, "firstName": f"First{cid}", "lastName": "Last"}]

    client = MockMcpClient(
        tools=[_detail_tool()],
        handlers={"getCandidateDetail": detail_handler},
    )

    state = GraphState(
        original_query="dev java",
        interpreted_intent=InterpretedIntent(
            objective="find_consultants", entities=["java"]
        ),
        available_tools=[_detail_tool()],
        results=[
            _result(candidate_id="1"),
            _result(candidate_id="2"),
            _result(candidate_id="3"),
        ],
    )

    result = await enrich_candidates(state, _ctx(client))

    assert sorted([c["candidateId"] for c in captured]) == [1, 2, 3]
    for enriched in result.results:
        assert ENRICHMENT_DETAIL_KEY in enriched.data
        assert "firstName" in enriched.data
    # All three detail calls recorded.
    detail_calls = [c for c in result.tool_calls if c.tool == "getCandidateDetail"]
    assert len(detail_calls) == 3
    assert all(c.status is ToolCallStatus.SUCCESS for c in detail_calls)


@pytest.mark.asyncio
async def test_enrich_respects_max_enrichments_limit() -> None:
    async def detail_handler(inputs: dict[str, object]) -> list[dict[str, object]]:
        return [{"id": inputs.get("candidateId"), "firstName": "X"}]

    client = MockMcpClient(
        tools=[_detail_tool()],
        handlers={"getCandidateDetail": detail_handler},
    )

    state = GraphState(
        original_query="dev java",
        interpreted_intent=InterpretedIntent(
            objective="find_consultants", entities=["java"]
        ),
        available_tools=[_detail_tool()],
        results=[_result(candidate_id=str(i)) for i in range(10)],
    )

    result = await enrich_candidates(state, _ctx(client, max_enrichments=2))

    detail_calls = [c for c in result.tool_calls if c.tool == "getCandidateDetail"]
    assert len(detail_calls) == 2


@pytest.mark.asyncio
async def test_enrich_skips_results_from_non_search_tools() -> None:
    async def detail_handler(_inputs: dict[str, object]) -> list[dict[str, object]]:
        return [{"id": 42}]

    client = MockMcpClient(
        tools=[_detail_tool()],
        handlers={"getCandidateDetail": detail_handler},
    )

    state = GraphState(
        original_query="candidate id 42",
        interpreted_intent=InterpretedIntent(
            objective="get_candidate_detail", constraints={"candidate_id": "42"}
        ),
        available_tools=[_detail_tool()],
        results=[_result(candidate_id="42", source_tool="getCandidateDetail")],
    )

    result = await enrich_candidates(state, _ctx(client))

    # No additional detail calls — the direct candidate-detail flow is
    # already authoritative and must not be re-fetched.
    assert result.tool_calls == []


@pytest.mark.asyncio
async def test_enrich_calls_technical_document_when_available_and_relevant() -> None:
    async def detail_handler(inputs: dict[str, object]) -> list[dict[str, object]]:
        return [{"id": inputs.get("candidateId"), "firstName": "Sarah"}]

    async def doc_handler(inputs: dict[str, object]) -> list[dict[str, object]]:
        return [
            {
                "candidateId": inputs.get("candidateId"),
                "skills": ["Java", "Spring"],
                "text": "10 years backend experience on CIB platforms.",
            }
        ]

    client = MockMcpClient(
        tools=[_detail_tool(), _tech_doc_tool()],
        handlers={
            "getCandidateDetail": detail_handler,
            "getCandidateTechnicalDocument": doc_handler,
        },
    )

    state = GraphState(
        original_query="dev java cib",
        interpreted_intent=InterpretedIntent(
            objective="find_consultants", entities=["java", "cib"]
        ),
        available_tools=[_detail_tool(), _tech_doc_tool()],
        results=[_result(candidate_id="1")],
    )

    result = await enrich_candidates(state, _ctx(client))

    tools_called = [c.tool for c in result.tool_calls]
    assert "getCandidateDetail" in tools_called
    assert "getCandidateTechnicalDocument" in tools_called
    assert ENRICHMENT_TECH_DOC_KEY in result.results[0].data


@pytest.mark.asyncio
async def test_enrich_is_noop_when_detail_tool_missing() -> None:
    # No tools available means enrichment has nothing safe to do.
    client = MockMcpClient(tools=[])
    state = GraphState(
        original_query="dev java",
        interpreted_intent=InterpretedIntent(
            objective="find_consultants", entities=["java"]
        ),
        available_tools=[],
        results=[_result(candidate_id="1")],
    )

    result = await enrich_candidates(state, _ctx(client))

    assert result.tool_calls == []
    assert result.results == state.results


@pytest.mark.asyncio
async def test_rank_named_person_beats_perfect_criteria_stranger() -> None:
    # The Taher case: a stranger with perfect criteria but only a shared
    # surname must NOT outrank the actually-requested person.
    state = GraphState(
        original_query="10 years java developer named Taher ben abdallah",
        interpreted_intent=InterpretedIntent(
            objective="find",
            entities=["java"],
            constraints={
                "role": "developer",
                "min_experience_years": "10",
                "name": "Taher ben abdallah",
                # The LLM ranks the name as the most important criterion.
                "ranking_priority": "name,skill,seniority,role",
            },
        ),
        results=[
            # Stranger: perfect criteria, shares only "abdallah".
            _result(
                candidate_id="38964",
                data={
                    "firstName": "Abdallah",
                    "lastName": "Khirallah",
                    "jobTitle": "Java Developer",
                    "experienceMinYears": 10,
                    "skills": ["Java"],
                },
            ),
            # The requested person: exact name, Java + 10y, but title is
            # "Tech Lead" (no literal "developer" token).
            _result(
                candidate_id="40278",
                data={
                    "firstName": "TAHER",
                    "lastName": "BEN ABDALLAH",
                    "jobTitle": "Tech Lead Java backend",
                    "experienceMinYears": 10,
                    "skills": ["Java"],
                },
            ),
        ],
    )

    result = await rank_candidates(state, _ctx(MockMcpClient()))

    # The exact-name person ranks first and outscores the stranger.
    assert result.results[0].id == "40278"
    assert result.results[0].score > result.results[1].score
    # The stranger is never labelled a full match and lists the name as unmet.
    stranger = next(r for r in result.results if r.id == "38964")
    assert stranger.is_full_match is False
    assert "Taher ben abdallah" in stranger.unmet_criteria


@pytest.mark.asyncio
async def test_rank_priority_demotes_coach_below_cib_developer() -> None:
    # The JEROME case end-to-end: with the LLM ranking domain/role above
    # seniority, a java+10y "coach" (no CIB, not a dev) must rank below a
    # java+CIB developer that matches fewer of the "easy" criteria.
    state = GraphState(
        original_query="java dev with 10 yrs experience whose last job is in CIB",
        interpreted_intent=InterpretedIntent(
            objective="find",
            entities=["java"],
            constraints={
                "role": "developer",
                "domain": "CIB",
                "min_experience_years": "10",
                "ranking_priority": "domain,role,skill,seniority",
            },
        ),
        results=[
            _result(
                candidate_id="40706",
                data={
                    "firstName": "Jerome",
                    "lastName": "Moliere",
                    "jobTitle": "Coach Craft Java",
                    "experienceMinYears": 10,
                    "skills": ["Java"],
                },
            ),
            _result(
                candidate_id="8378",
                data={
                    "firstName": "Antoni",
                    "lastName": "Galmiche",
                    "jobTitle": "Java Developer at SGCIB",
                    "skills": ["Java"],
                },
            ),
        ],
    )

    result = await rank_candidates(state, _ctx(MockMcpClient()))

    # The CIB developer outranks the coach because the LLM ranked domain first.
    assert result.results[0].id == "8378"
    assert result.results[0].score > result.results[1].score


@pytest.mark.asyncio
async def test_role_exclusive_excludes_conflicting_metier() -> None:
    # "uniquement des développeurs": a Business Analyst title is EXCLUDED
    # from the results, not merely demoted.
    state = GraphState(
        original_query="java dev, je veux uniquement des développeurs",
        interpreted_intent=InterpretedIntent(
            objective="find",
            entities=["java"],
            constraints={"role": "développeur", "role_exclusive": "true"},
        ),
        results=[
            _result(
                candidate_id="ba1",
                data={"jobTitle": "Business Analyst", "skills": ["Java"]},
            ),
            _result(
                candidate_id="dev1",
                data={"jobTitle": "Développeur Java", "skills": ["Java"]},
            ),
        ],
    )

    result = await rank_candidates(state, _ctx(MockMcpClient()))

    ids = [r.id for r in result.results]
    assert "dev1" in ids
    assert "ba1" not in ids


@pytest.mark.asyncio
async def test_role_exclusive_excludes_ba_abbreviated_title() -> None:
    # The Stephane MALTESE case: the BoondManager title abbreviates the
    # métier as "BA ..." — it must still be recognised and excluded.
    state = GraphState(
        original_query="développeur fullstack java, uniquement des développeurs",
        interpreted_intent=InterpretedIntent(
            objective="find",
            entities=["java"],
            constraints={"role": "développeur fullstack", "role_exclusive": "true"},
        ),
        results=[
            _result(
                candidate_id="maltese",
                data={
                    "firstName": "Stephane",
                    "lastName": "MALTESE",
                    "jobTitle": "BA Finance de Marché en Banque d'investissements",
                    "skills": ["marchés financiers", "java"],
                },
            ),
            _result(
                candidate_id="dev1",
                data={"jobTitle": "Développeur Java", "skills": ["Java"]},
            ),
        ],
    )

    result = await rank_candidates(state, _ctx(MockMcpClient()))

    ids = [r.id for r in result.results]
    assert "dev1" in ids
    assert "maltese" not in ids


@pytest.mark.asyncio
async def test_role_exclusive_never_reads_a_surname_as_a_metier() -> None:
    # When no job title exists, result.title falls back to the person's
    # NAME — the surname "Ba" must not register as Business Analyst and
    # get the candidate wrongly excluded.
    state = GraphState(
        original_query="développeur java, uniquement des développeurs",
        interpreted_intent=InterpretedIntent(
            objective="find",
            entities=["java"],
            constraints={"role": "développeur", "role_exclusive": "true"},
        ),
        results=[
            SearchResult(
                id="amadou",
                type="candidate",
                title="Amadou Ba",  # name fallback, no job title anywhere
                score=0.5,
                source_tool="searchCandidates",
                data={"firstName": "Amadou", "lastName": "Ba", "skills": ["Java"]},
            ),
        ],
    )

    result = await rank_candidates(state, _ctx(MockMcpClient()))

    assert [r.id for r in result.results] == ["amadou"]


@pytest.mark.asyncio
async def test_conflicting_metier_stays_visible_without_exclusive_flag() -> None:
    # Without the exclusivity flag the BA keeps the visible-but-demoted
    # behaviour: present, but strictly below the actual developer.
    state = GraphState(
        original_query="développeur java",
        interpreted_intent=InterpretedIntent(
            objective="find",
            entities=["java"],
            constraints={"role": "développeur"},
        ),
        results=[
            _result(
                candidate_id="ba1",
                data={"jobTitle": "Business Analyst", "skills": ["Java"]},
            ),
            _result(
                candidate_id="dev1",
                data={"jobTitle": "Développeur Java", "skills": ["Java"]},
            ),
        ],
    )

    result = await rank_candidates(state, _ctx(MockMcpClient()))

    ids = [r.id for r in result.results]
    assert ids.index("dev1") < ids.index("ba1")
    dev = next(r for r in result.results if r.id == "dev1")
    ba = next(r for r in result.results if r.id == "ba1")
    assert dev.score > ba.score


@pytest.mark.asyncio
async def test_rank_promotes_candidates_with_matching_evidence() -> None:
    state = GraphState(
        original_query="dev java cib",
        interpreted_intent=InterpretedIntent(
            objective="find_consultants", entities=["java", "cib"]
        ),
        results=[
            # Candidate with no evidence at all.
            _result(candidate_id="1", data={"firstName": "Alone"}),
            # Candidate whose tech doc mentions both Java and CIB.
            _result(
                candidate_id="2",
                data={
                    "firstName": "Sarah",
                    ENRICHMENT_TECH_DOC_KEY: {
                        "skills": ["Java"],
                        "text": "Long experience on CIB platforms",
                    },
                },
            ),
        ],
    )

    result = await rank_candidates(state, _ctx(MockMcpClient()))

    # Evidence-rich candidate is the only one kept (zero-score candidate dropped).
    assert result.results[0].id == "2"
    assert result.results[0].score > 0.0
    # Candidate with no evidence is filtered out.
    assert all(r.id != "1" for r in result.results)


@pytest.mark.asyncio
async def test_rank_scores_by_evidence_fraction_and_nulls_zero_evidence() -> None:
    state = GraphState(
        original_query="java cib",
        interpreted_intent=InterpretedIntent(
            objective="find_consultants", entities=["java", "cib"]
        ),
        results=[
            # Only Java evidence -> half the criteria -> 0.5.
            _result(candidate_id="1", data={"jobTitle": "Java Engineer"}),
            # Both Java and CIB evidenced -> full coverage -> 1.0.
            _result(
                candidate_id="2",
                data={"jobTitle": "Java Dev", "skills": ["CIB"]},
            ),
            # Visibly contradicts the request, no evidence -> 0.0.
            _result(candidate_id="3", data={"jobTitle": "C# Developer"}),
        ],
    )

    result = await rank_candidates(state, _ctx(MockMcpClient()))

    by_id = {r.id: r.score for r in result.results}
    # Full / half criteria coverage, then ×0.85: neither profile carries any
    # corroborating data (no tech doc, no CV, no known experience figure).
    assert by_id["2"] == 0.85
    assert by_id["1"] == 0.425
    # C# developer has no evidence and is filtered out (zero-score removed when positives exist).
    assert "3" not in by_id
    # Best-evidenced first.
    assert result.results[0].id == "2"
    assert result.results[1].id == "1"


@pytest.mark.asyncio
async def test_rank_flags_unverifiable_criteria_as_warning() -> None:
    state = GraphState(
        original_query="java cib",
        interpreted_intent=InterpretedIntent(
            objective="find_consultants", entities=["java", "cib"]
        ),
        results=[
            _result(
                candidate_id="1",
                data={"jobTitle": "Java Engineer", "skills": ["Java", "Spring"]},
            ),
        ],
    )

    result = await rank_candidates(state, _ctx(MockMcpClient()))

    # 'cib' was never evidenced on any candidate -> recorded as unverified.
    warn = next(w for w in result.warnings if w.code == "criteria_unverified")
    assert "cib" in warn.message
    # 'java' WAS evidenced, so it must not be flagged as unverified.
    assert "java" not in warn.message
    # Partial coverage never reads as a full-confidence match
    # (0.5 coverage × 0.85 unverified-profile discount).
    assert result.results[0].score == 0.425


@pytest.mark.asyncio
async def test_rank_domain_phrase_in_title_beats_plain_skill_match() -> None:
    # Reproduction of the live bug: the domain phrase "Corporate & Investment
    # Banking" (with "&") must still credit a title that spells it with "and",
    # so the real domain candidate ranks first — not a plain Java profile.
    state = GraphState(
        original_query="java dev in cib",
        interpreted_intent=InterpretedIntent(
            objective="find",
            entities=["java"],
            constraints={"domain": "Corporate & Investment Banking"},
        ),
        results=[
            _result(candidate_id="plain", data={"jobTitle": "Java Developer"}),
            _result(
                candidate_id="cib",
                data={
                    "jobTitle": (
                        "Software Engineer at Societe Generale Corporate "
                        "and Investment Banking - SGCIB"
                    ),
                    "skills": ["Java"],
                },
            ),
        ],
    )

    result = await rank_candidates(state, _ctx(MockMcpClient()))

    assert result.results[0].id == "cib"
    by_id = {r.id: r.score for r in result.results}
    assert by_id["cib"] > by_id["plain"]
    # The domain IS evidenced (in the title) — never "could not verify".
    assert not any(w.code == "criteria_unverified" for w in result.warnings)
    assert any(w.code == "criteria_visible" for w in result.warnings)


@pytest.mark.asyncio
async def test_rank_generic_csharp_in_banking_not_java_specific() -> None:
    state = GraphState(
        original_query="c# dev in banking",
        interpreted_intent=InterpretedIntent(
            objective="find",
            entities=["c#"],
            constraints={"domain": "banking"},
        ),
        results=[
            _result(candidate_id="plain", data={"jobTitle": "C# Developer"}),
            _result(
                candidate_id="bank",
                data={"jobTitle": "C# Developer at Retail Banking"},
            ),
        ],
    )

    result = await rank_candidates(state, _ctx(MockMcpClient()))

    assert result.results[0].id == "bank"


@pytest.mark.asyncio
async def test_rank_marks_domain_visible_not_unverified_when_in_title() -> None:
    state = GraphState(
        original_query="java dev in cib",
        interpreted_intent=InterpretedIntent(
            objective="find",
            entities=["java"],
            # Verbose, ambiguous business-domain term.
            constraints={"domain": "cib (corporate & investment banking)"},
        ),
        results=[
            # Java + CIB both VISIBLE in the title, but no technical document.
            _result(
                candidate_id="vis",
                data={"jobTitle": "Java Developer at SGCIB"},
            ),
        ],
    )

    result = await rank_candidates(state, _ctx(MockMcpClient()))

    # Visible-but-unconfirmed — NOT a global "could not verify".
    assert any(w.code == "criteria_visible" for w in result.warnings)
    assert not any(w.code == "criteria_unverified" for w in result.warnings)
    visible = next(w for w in result.warnings if w.code == "criteria_visible")
    # The original acronym is preserved in the message.
    assert "cib" in visible.message.lower()


@pytest.mark.asyncio
async def test_rank_marks_criteria_verified_when_in_technical_document() -> None:
    state = GraphState(
        original_query="java dev in cib",
        interpreted_intent=InterpretedIntent(
            objective="find",
            entities=["java"],
            constraints={"domain": "cib (corporate & investment banking)"},
        ),
        results=[
            _result(
                candidate_id="ver",
                data={
                    "jobTitle": "Java Developer",
                    ENRICHMENT_TECH_DOC_KEY: {
                        "summary": "10 years on java platforms at SGCIB.",
                    },
                },
            ),
        ],
    )

    result = await rank_candidates(state, _ctx(MockMcpClient()))

    # Both java and the domain are confirmed in the technical document.
    assert not any(
        w.code in ("criteria_unverified", "criteria_visible")
        for w in result.warnings
    )


@pytest.mark.asyncio
async def test_rank_sets_is_full_match_true_when_all_criteria_evidenced() -> None:
    state = GraphState(
        original_query="java 10 years cib",
        interpreted_intent=InterpretedIntent(
            objective="find",
            entities=["java"],
            constraints={"domain": "cib", "min_experience_years": "10"},
        ),
        results=[
            _result(
                candidate_id="full",
                data={
                    "jobTitle": "Java Developer at SGCIB",
                    "experienceMinYears": 11,
                },
            )
        ],
    )

    result = await rank_candidates(state, _ctx(MockMcpClient()))

    card = result.results[0]
    assert card.is_full_match is True
    assert card.unmet_criteria == []


@pytest.mark.asyncio
async def test_rank_sets_is_full_match_false_with_unmet_labels() -> None:
    state = GraphState(
        original_query="java 10 years cib",
        interpreted_intent=InterpretedIntent(
            objective="find",
            entities=["java"],
            constraints={"domain": "cib", "min_experience_years": "10"},
        ),
        results=[
            # Java only — no CIB, only 3 years.
            _result(
                candidate_id="partial",
                data={"jobTitle": "Java Developer", "experienceMinYears": 3},
            )
        ],
    )

    result = await rank_candidates(state, _ctx(MockMcpClient()))

    card = result.results[0]
    assert card.is_full_match is False
    assert "cib" in card.unmet_criteria
    assert "10+ years" in card.unmet_criteria


@pytest.mark.asyncio
async def test_rank_leaves_is_full_match_none_without_criteria() -> None:
    state = GraphState(
        original_query="x",
        interpreted_intent=InterpretedIntent(objective="find"),
        results=[
            _result(candidate_id="1", data={"jobTitle": "Java Developer"})
        ],
    )

    result = await rank_candidates(state, _ctx(MockMcpClient()))

    assert result.results[0].is_full_match is None
    assert result.results[0].unmet_criteria == []


@pytest.mark.asyncio
async def test_rank_prefers_senior_domain_match_over_junior_skill_only() -> None:
    state = GraphState(
        original_query="java dev 10 years cib",
        interpreted_intent=InterpretedIntent(
            objective="find",
            entities=["java"],
            constraints={"domain": "cib", "min_experience_years": "10"},
        ),
        results=[
            # Java, but only 3 years and no domain signal.
            _result(
                candidate_id="junior",
                data={"jobTitle": "Java Developer", "experienceMinYears": 3},
            ),
            # Java + 11 years + CIB (via SGCIB in the title).
            _result(
                candidate_id="senior",
                data={
                    "jobTitle": "Java Developer at SGCIB",
                    "experienceMinYears": 11,
                },
            ),
        ],
    )

    result = await rank_candidates(state, _ctx(MockMcpClient()))

    by_id = {r.id: r.score for r in result.results}
    assert result.results[0].id == "senior"
    # The 3-year skill-only profile must rank strictly below.
    assert by_id["senior"] > by_id["junior"]


@pytest.mark.asyncio
async def test_rank_does_not_warn_when_all_criteria_evidenced() -> None:
    state = GraphState(
        original_query="java",
        interpreted_intent=InterpretedIntent(
            objective="find_consultants", entities=["java"]
        ),
        results=[_result(candidate_id="1", data={"jobTitle": "Java Engineer"})],
    )

    result = await rank_candidates(state, _ctx(MockMcpClient()))

    assert not any(w.code == "criteria_unverified" for w in result.warnings)
    # All criteria evidenced, but the profile carries no corroborating data
    # (no tech doc / CV / known experience) so it cannot read as 100%.
    assert result.results[0].score == 0.85


@pytest.mark.asyncio
async def test_rank_enrichment_bump_never_rescues_zero_evidence() -> None:
    state = GraphState(
        original_query="java",
        interpreted_intent=InterpretedIntent(
            objective="find_consultants", entities=["java"]
        ),
        results=[
            _result(
                candidate_id="1",
                data={
                    "jobTitle": "C# Developer",
                    ENRICHMENT_DETAIL_KEY: {"note": "bar"},
                    ENRICHMENT_TECH_DOC_KEY: {"note": "qux"},
                },
            ),
        ],
    )

    result = await rank_candidates(state, _ctx(MockMcpClient()))

    # Enriched but no 'java' evidence anywhere -> must stay 0.0.
    assert result.results[0].score == 0.0


@pytest.mark.asyncio
async def test_rank_does_not_touch_non_search_results() -> None:
    state = GraphState(
        original_query="candidate id 42",
        interpreted_intent=InterpretedIntent(
            objective="get_candidate_detail", entities=["java"]
        ),
        results=[
            _result(
                candidate_id="42",
                source_tool="getCandidateDetail",
                data={"jobTitle": "Java Engineer"},
            )
        ],
    )

    result = await rank_candidates(state, _ctx(MockMcpClient()))

    # Score must be unchanged for non-search source tools.
    assert result.results[0].score == 0.5


@pytest.mark.asyncio
async def test_rank_empty_dossier_never_tops_documented_profile() -> None:
    # The reported live bug: on "dev java 5 ans d'expérience", candidates with
    # NOTHING in their dossier (no CV, no tech doc, no experience — just the
    # "java" skill tag) surfaced FIRST at 100%. They must rank strictly below
    # a documented profile meeting the seniority bar, and never read as 100%.
    state = GraphState(
        original_query="dev java 5 ans d'expérience",
        interpreted_intent=InterpretedIntent(
            objective="find",
            entities=["java"],
            constraints={"min_experience_years": "5"},
        ),
        results=[
            # Empty dossier: only the skill tag, listed first by BoondManager.
            _result(candidate_id="empty", data={"skills": ["Java"]}),
            # Documented: java + known 6 years + tech doc.
            _result(
                candidate_id="documented",
                data={
                    "jobTitle": "Développeur Java",
                    "experienceMinYears": 6,
                    "skills": ["Java"],
                    ENRICHMENT_TECH_DOC_KEY: {"skills": ["Java", "Spring"]},
                },
            ),
        ],
    )

    result = await rank_candidates(state, _ctx(MockMcpClient()))

    assert result.results[0].id == "documented"
    empty = next(r for r in result.results if r.id == "empty")
    assert empty.score < result.results[0].score
    assert empty.score < 1.0
    assert empty.is_full_match is False


@pytest.mark.asyncio
async def test_rank_parses_min_experience_with_unit_suffix() -> None:
    # The LLM sometimes emits "5 ans" instead of "5"; the seniority dimension
    # must still be scored (a strict int() would silently drop it).
    state = GraphState(
        original_query="dev java 5 ans d'expérience",
        interpreted_intent=InterpretedIntent(
            objective="find",
            entities=["java"],
            constraints={"min_experience_years": "5 ans"},
        ),
        results=[
            _result(candidate_id="bare", data={"skills": ["Java"]}),
            _result(
                candidate_id="senior",
                data={"skills": ["Java"], "experienceMinYears": 7},
            ),
        ],
    )

    result = await rank_candidates(state, _ctx(MockMcpClient()))

    # If the constraint were dropped, both would score identically.
    assert result.results[0].id == "senior"
    assert result.results[0].score > result.results[1].score


@pytest.mark.asyncio
async def test_rank_ties_broken_by_evidence_depth() -> None:
    # At equal criteria coverage, the candidate backed by corroborating data
    # (known years) outranks the bare skill tag — regardless of Boond order.
    state = GraphState(
        original_query="java",
        interpreted_intent=InterpretedIntent(
            objective="find_consultants", entities=["java"]
        ),
        results=[
            _result(candidate_id="bare", data={"skills": ["Java"]}),
            _result(
                candidate_id="known-years",
                data={"skills": ["Java"], "experienceMinYears": 4},
            ),
        ],
    )

    result = await rank_candidates(state, _ctx(MockMcpClient()))

    assert result.results[0].id == "known-years"
