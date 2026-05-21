"""LangGraph workflow assembly and execution helpers."""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.graph.nodes import (
    NodeContext,
    analyze_intent,
    build_plan,
    evaluate_results,
    execute_mcp_tools,
    generate_final_response,
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


def build_workflow(ctx: NodeContext):
    """Build and compile the Plan-and-Execute LangGraph workflow."""
    graph: StateGraph = StateGraph(GraphState)

    graph.add_node("analyze_intent", _bind(analyze_intent, ctx))
    graph.add_node("build_plan", _bind(build_plan, ctx))
    graph.add_node("select_tools", _bind(select_tools, ctx))
    graph.add_node("execute_mcp_tools", _bind(execute_mcp_tools, ctx))
    graph.add_node("evaluate_results", _bind(evaluate_results, ctx))
    graph.add_node("replan_if_needed", _bind(replan_if_needed, ctx))
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
            "generate_final_response": "generate_final_response",
        },
    )
    graph.add_edge("generate_final_response", END)

    return graph.compile()


async def run_workflow(
    initial_state: GraphState,
    ctx: NodeContext,
) -> GraphState:
    """Run the workflow once and return the typed final state."""
    workflow = build_workflow(ctx)
    raw_state = await workflow.ainvoke(initial_state)
    if isinstance(raw_state, GraphState):
        return raw_state
    return GraphState.model_validate(raw_state)
