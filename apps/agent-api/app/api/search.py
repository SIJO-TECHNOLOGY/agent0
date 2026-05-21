"""POST /api/search endpoint."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse

from app.api.dependencies import get_search_service
from app.models.api import (
    ErrorEnvelope,
    ErrorPayload,
    SearchRequest,
    SearchResponse,
)
from app.services.search_service import SearchService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["search"])


@router.post(
    "/api/search",
    response_model=SearchResponse,
    responses={
        400: {"model": ErrorEnvelope},
        500: {"model": ErrorEnvelope},
    },
)
async def search(
    payload: SearchRequest,
    service: SearchService = Depends(get_search_service),
) -> SearchResponse | JSONResponse:
    try:
        return await service.search(payload)
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001 — boundary guard
        logger.exception("search.unexpected_error")
        envelope = ErrorEnvelope(
            error=ErrorPayload(
                code="internal_error",
                message="An internal error occurred while processing the search.",
            )
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=envelope.model_dump(),
        )
