"""
The cache-first analysis flow.
A miss checks the rate limiter before assembling anything.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from httpx2 import AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..settings import Settings
from .analysis import RootCauseAnalysis
from .fingerprint import EntityFingerprint
from .gemini import GeminiAnalyst
from .rate_limit import enforce_rate_limit
from .response_cache import cached_age_seconds, read_cached_analysis, write_cached_analysis
from .retrieval import assemble_failure_context

logger = logging.getLogger("videre.backend.ai.assistant")


@dataclass(frozen=True)
class AnalysisResult:
    analysis: RootCauseAnalysis
    from_cache: bool
    cache_age_seconds: int | None = None


async def analyze_entity(
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Redis,
    http_client: AsyncClient,
    analyst: GeminiAnalyst,
    settings: Settings,
    fingerprint: EntityFingerprint,
    client: str
) -> AnalysisResult:
    cached = await read_cached_analysis(redis_client, fingerprint)
    if cached is not None:
        age = await cached_age_seconds(redis_client, fingerprint, settings.ai_cache_ttl_seconds)
        logger.info(
            "AI analysis served from cache",
            extra={
                "entity_type": fingerprint.entity_type.value,
                "entity_id": fingerprint.entity_id,
                "cache_age_seconds": age
            }
        )
        return AnalysisResult(analysis=cached, from_cache=True, cache_age_seconds=age)
    
    await enforce_rate_limit(redis_client, settings, client)    # enforce rate limit before doing any work
    
    context = await assemble_failure_context(
        session_factory,
        http_client,
        settings,
        fingerprint.entity_type,
        fingerprint.entity_id
    )
    analysis = await analyst.analyze(context)
    await write_cached_analysis(redis_client, fingerprint, analysis, settings.ai_cache_ttl_seconds)
    return AnalysisResult(analysis=analysis, from_cache=False)
