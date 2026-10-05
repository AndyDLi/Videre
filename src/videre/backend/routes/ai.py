"""
AI assistant analysis endpoint.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from videre.database.tables import FailureEntityTable

from ..ai import (
    GeminiRateLimitError,
    GeminiRequestError,
    GeminiResponseError,
    GeminiUnavailableError,
    RateLimitExceeded,
    analyze_entity,
    client_identifier,
    load_fingerprint,
)
from ..dependencies import (
    GeminiAnalystDependency,
    HttpClientDependency,
    RedisDependency,
    SessionFactoryDependency,
    SettingsDependency,
)

logger = logging.getLogger("videre.backend.routes.ai")

router = APIRouter(prefix="/ai", tags=["ai"])

ASSISTANT_UNAVAILABLE = "The AI assistant is temporarily unavailable. Please try again later."


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    entity_type: FailureEntityTable
    entity_id: str = Field(min_length=1, max_length=128)


class AnalysisResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    entity_type: FailureEntityTable
    entity_id: str
    summary: str
    next_steps: list[str]
    from_cache: bool
    cache_age_seconds: int | None


def _log(
    payload: AnalysisRequest,
    client: str,
    started: float,
    outcome: str,
    **details: Any
) -> None:
    logger.info(
        "AI analyze request",
        extra={
            "entity_type": payload.entity_type.value,
            "entity_id": payload.entity_id,
            "client": client,
            "outcome": outcome,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            **details,
        },
    )


@router.post("/analyze", response_model=AnalysisResponse)
async def analyze(
    payload: AnalysisRequest,
    request: Request,
    session_factory: SessionFactoryDependency,
    redis_client: RedisDependency,
    http_client: HttpClientDependency,
    analyst: GeminiAnalystDependency,
    settings: SettingsDependency
) -> AnalysisResponse:
    started = time.perf_counter()
    client = client_identifier(request)
    
    async with session_factory() as session:
        fingerprint = await load_fingerprint(session, payload.entity_type, payload.entity_id)
    if fingerprint is None:
        _log(payload, client, started, "not_found")
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"{payload.entity_type.value} not found"
        )
    
    if analyst is None:
        _log(payload, client, started, "not_configured")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=ASSISTANT_UNAVAILABLE)
    
    try:
        result = await analyze_entity(
            session_factory,
            redis_client,
            http_client,
            analyst,
            settings,
            fingerprint,
            client
        )
    except RateLimitExceeded as error:
        _log(payload, client, started, "rate_limited", window=error.window_name)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail=error.message,
            headers={"Retry-After": str(error.retry_after_seconds)},
        ) from error
    except GeminiRateLimitError as error:
        _log(payload, client, started, "provider_rate_limited")
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="AI analysis is rate limited. Please try again shortly.",
        ) from error
    except GeminiUnavailableError as error:
        _log(payload, client, started, "provider_unavailable")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=ASSISTANT_UNAVAILABLE) from error
    except (GeminiRequestError, GeminiResponseError) as error:
        _log(payload, client, started, "provider_error", error=str(error))
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=ASSISTANT_UNAVAILABLE) from error
    
    _log(
        payload,
        client,
        started,
        "cache_hit" if result.from_cache else "analyzed",
        cache_age_seconds=result.cache_age_seconds,
    )
    
    return AnalysisResponse(
        entity_type=fingerprint.entity_type,
        entity_id=fingerprint.entity_id,
        summary=result.analysis.summary,
        next_steps=result.analysis.next_steps,
        from_cache=result.from_cache,
        cache_age_seconds=result.cache_age_seconds,
    )
