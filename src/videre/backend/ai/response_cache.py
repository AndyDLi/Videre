"""
Fingerprint-keyed cache of Gemini responses.
"""

from __future__ import annotations

import hashlib
import logging
from time import perf_counter

from pydantic import ValidationError
from redis.asyncio import Redis

from ..metrics.performance import AI_CACHE_GET, AI_CACHE_READS
from .analysis import RootCauseAnalysis
from .fingerprint import EntityFingerprint

logger = logging.getLogger("videre.backend.ai.cache")

KEY_PREFIX = "ai:resp"
DIGEST_LENGTH = 16


def cache_key(fingerprint: EntityFingerprint) -> str:
    digest = hashlib.sha256(fingerprint.cache_fingerprint.encode()).hexdigest()[:DIGEST_LENGTH]
    return f"{KEY_PREFIX}:{fingerprint.entity_type.value}:{fingerprint.entity_id}:{digest}"


async def read_cached_analysis(
    redis_client: Redis,
    fingerprint: EntityFingerprint
) -> RootCauseAnalysis | None:
    started = perf_counter()
    outcome = "error"
    try:
        payload = await redis_client.get(cache_key(fingerprint))
        outcome = "success"
    finally:
        AI_CACHE_GET.labels(outcome).observe(perf_counter() - started)
    if payload is None:
        AI_CACHE_READS.labels("miss").inc()
        return None
    
    try:
        analysis = RootCauseAnalysis.model_validate_json(payload)
    except ValidationError:
        AI_CACHE_READS.labels("invalid").inc()
        logger.warning("discarding unreadable cached analysis", extra={"entity_id": fingerprint.entity_id})
        return None
    AI_CACHE_READS.labels("hit").inc()
    return analysis


async def write_cached_analysis(
    redis_client: Redis,
    fingerprint: EntityFingerprint,
    analysis: RootCauseAnalysis,
    ttl_seconds: int
) -> None:
    await redis_client.set(cache_key(fingerprint), analysis.model_dump_json(), ex=ttl_seconds)


async def cached_age_seconds(
    redis_client: Redis,
    fingerprint: EntityFingerprint,
    ttl_seconds: int
) -> int | None:
    remaining = await redis_client.ttl(cache_key(fingerprint))
    if remaining is None or remaining < 0:
        return None
    return max(ttl_seconds - int(remaining), 0)
