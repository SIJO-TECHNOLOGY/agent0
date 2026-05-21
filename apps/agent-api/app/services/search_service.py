"""Search service: orchestrates the LangGraph workflow and shapes the API response."""

from __future__ import annotations

import logging
import uuid

from app.graph.nodes import NodeContext
from app.graph.workflow import run_workflow
from app.mcp.client import McpClient
from app.models.api import SearchRequest, SearchResponse
from app.models.graph_state import GraphState
from app.models.intent import InterpretedIntent

logger = logging.getLogger(__name__)


class SearchService:
    """Application service that runs the agent workflow for a search."""

    def __init__(
        self,
        mcp_client: McpClient,
        *,
        max_replan_attempts: int = 1,
        mcp_max_retries: int = 2,
    ) -> None:
        self._ctx = NodeContext(
            mcp_client=mcp_client,
            max_replan_attempts=max_replan_attempts,
            mcp_max_retries=mcp_max_retries,
        )

    async def search(self, request: SearchRequest) -> SearchResponse:
        request_id = uuid.uuid4().hex
        logger.info(
            "search.start",
            extra={"request_id": request_id, "query": request.query},
        )

        initial_state = GraphState(
            original_query=request.query,
            filters=dict(request.filters),
        )
        final_state = await run_workflow(initial_state, self._ctx)

        interpreted = final_state.interpreted_intent or InterpretedIntent(
            objective="unknown",
        )
        logger.info(
            "search.complete",
            extra={
                "request_id": request_id,
                "result_count": len(final_state.results),
                "confidence": final_state.confidence,
                "warning_count": len(final_state.warnings),
                "replan_count": final_state.replan_count,
            },
        )

        return SearchResponse(
            original_query=final_state.original_query,
            interpreted_intent=interpreted,
            execution_plan=final_state.execution_plan,
            tool_calls=final_state.tool_calls,
            results=final_state.results,
            summary=final_state.summary,
            confidence=final_state.confidence,
            warnings=final_state.warnings,
        )
