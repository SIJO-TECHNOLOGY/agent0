"""GET /api/candidate-states — selectable candidate pipeline states.

Normalized ``{id, label}`` options for the web UI's state-filter
checkboxes, sourced from the BoondManager dictionary via MCP
(``getDictionary`` is TTL-cached, see ADR-013). Excluded states
("Ne plus contacter", "A SUPPRIMER", …) are filtered out server-side
so the UI can never offer them.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.api.dependencies import get_mcp_client
from app.mcp.client import McpClient, McpToolError, McpTransientError
from app.models.api import (
    CandidateStateOption,
    CandidateStatesResponse,
    ErrorEnvelope,
    ErrorPayload,
)
from app.services.dictionary_resolver import candidate_state_options

logger = logging.getLogger(__name__)

router = APIRouter(tags=["candidates"])

_DICTIONARY_TOOL = "getDictionary"


@router.get(
    "/api/candidate-states",
    response_model=CandidateStatesResponse,
    responses={503: {"model": ErrorEnvelope}},
)
async def list_candidate_states(
    mcp_client: McpClient = Depends(get_mcp_client),
) -> CandidateStatesResponse | JSONResponse:
    try:
        raw = await mcp_client.call_tool(_DICTIONARY_TOOL, {})
    except (McpTransientError, McpToolError) as exc:
        logger.warning(
            "candidate_states.dictionary_unavailable", extra={"error": str(exc)}
        )
        envelope = ErrorEnvelope(
            error=ErrorPayload(
                code="mcp_client_unavailable",
                message=(
                    "The candidate state list is currently unavailable "
                    "(reference dictionary could not be fetched)."
                ),
            )
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=jsonable_encoder(envelope),
        )

    records = [r for r in (raw or []) if isinstance(r, dict)]
    options = candidate_state_options(records)
    return CandidateStatesResponse(
        states=[
            CandidateStateOption(id=str(option["id"]), label=str(option["label"]))
            for option in options
        ]
    )
