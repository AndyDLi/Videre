"""
Fingerprint-keyed cache of Gemini responses.
"""

from __future__ import annotations

import hashlib
import logging

from pydantic import ValidationError
from redis.asyncio import Redis

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
    payload = await redis_client.get(cache_key(fingerprint))
    if payload is None:
        return None
    
    try:
        return RootCauseAnalysis.model_validate_json(payload)
    except ValidationError:
        logger.warning("discarding unreadable cached analysis", extra={"entity_id": fingerprint.entity_id})
        return None


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
