"""LangGraph workflow assembly and execution helpers."""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.graph.nodes import (
    NodeContext,
    analyze_intent,
    build_plan,
    discover_mcp_tools,
    enrich_candidates,
    evaluate_results,
    execute_llm_plan,
    execute_mcp_tools,
    generate_final_response,
    plan_with_llm,
    rank_candidates,
    replan_if_needed,
    select_tools,
    should_replan,
)
from app.models.graph_state import GraphState


def _bind(node, ctx: NodeContext):
    """Wrap an async node so LangGraph receives an awaitable directly."""

    async def runner(state: GraphState) -> GraphState:
        return await node(state, ctx)

    runner.__name__ = node.__name__
    return runner


def build_deterministic_workflow(ctx: NodeContext):
    """Build and compile the deterministic Plan-and-Execute workflow.

    This path remains the fallback for tests, mock-mode development,
    and when ``USE_LLM_PLANNER=false``. It is NOT the intended
    real-mode planner — see ``build_llm_workflow``.
    """
    graph: StateGraph = StateGraph(GraphState)

    graph.add_node("analyze_intent", _bind(analyze_intent, ctx))
    graph.add_node("build_plan", _bind(build_plan, ctx))
    graph.add_node("select_tools", _bind(select_tools, ctx))
    graph.add_node("execute_mcp_tools", _bind(execute_mcp_tools, ctx))
    graph.add_node("evaluate_results", _bind(evaluate_results, ctx))
    graph.add_node("replan_if_needed", _bind(replan_if_needed, ctx))
    graph.add_node("enrich_candidates", _bind(enrich_candidates, ctx))
    graph.add_node("rank_candidates", _bind(rank_candidates, ctx))
    graph.add_node("generate_final_response", _bind(generate_final_response, ctx))

    graph.set_entry_point("analyze_intent")
    graph.add_edge("analyze_intent", "build_plan")
    graph.add_edge("build_plan", "select_tools")
    graph.add_edge("select_tools", "execute_mcp_tools")
    graph.add_edge("execute_mcp_tools", "evaluate_results")
    graph.add_edge("evaluate_results", "replan_if_needed")
    graph.add_conditional_edges(
        "replan_if_needed",
        should_replan,
        {
            "build_plan": "build_plan",
            "enrich_candidates": "enrich_candidates",
        },
    )
    graph.add_edge("enrich_candidates", "rank_candidates")
    graph.add_edge("rank_candidates", "generate_final_response")
    graph.add_edge("generate_final_response", END)

    return graph.compile()


def build_llm_workflow(ctx: NodeContext):
    """Build and compile the LLM-driven Plan-and-Execute workflow.

    The LLM owns intent interpretation and tool planning; LangGraph
    validates and executes within bounded fan-out. Enrichment fan-out
    is part of the LLM plan, so a separate enrichment node is not
    required here — `rank_candidates` still re-ranks using the merged
    evidence.
    """
    if ctx.llm_planner is None:
        raise RuntimeError(
            "build_llm_workflow requires NodeContext.llm_planner to be set"
        )

    graph: StateGraph = StateGraph(GraphState)

    graph.add_node("discover_mcp_tools", _bind(discover_mcp_tools, ctx))
    graph.add_node("plan_with_llm", _bind(plan_with_llm, ctx))
    graph.add_node("execute_llm_plan", _bind(execute_llm_plan, ctx))
    graph.add_node("enrich_candidates", _bind(enrich_candidates, ctx))
    graph.add_node("evaluate_results", _bind(evaluate_results, ctx))
    graph.add_node("rank_candidates", _bind(rank_candidates, ctx))
    graph.add_node("generate_final_response", _bind(generate_final_response, ctx))

    graph.set_entry_point("discover_mcp_tools")
    graph.add_edge("discover_mcp_tools", "plan_with_llm")
    graph.add_edge("plan_with_llm", "execute_llm_plan")
    graph.add_edge("execute_llm_plan", "enrich_candidates")
    graph.add_edge("enrich_candidates", "evaluate_results")
    graph.add_edge("evaluate_results", "rank_candidates")
    graph.add_edge("rank_candidates", "generate_final_response")
    graph.add_edge("generate_final_response", END)

    return graph.compile()


# Backwards-compatible alias so existing tests that import
# `build_workflow` keep working with the deterministic graph.
build_workflow = build_deterministic_workflow


async def run_workflow(
    initial_state: GraphState,
    ctx: NodeContext,
) -> GraphState:
    """Run the appropriate workflow once and return the typed final state.

    LLM mode runs when ``ctx.llm_planner`` is set; otherwise the
    deterministic workflow runs.
    """
    workflow = (
        build_llm_workflow(ctx)
        if ctx.llm_planner is not None
        else build_deterministic_workflow(ctx)
    )
    raw_state = await workflow.ainvoke(initial_state)
    if isinstance(raw_state, GraphState):
        return raw_state
    return GraphState.model_validate(raw_state)
