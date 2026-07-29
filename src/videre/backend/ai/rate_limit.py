"""
Redis counters for rate limiting Gemini requests.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Request
from redis.asyncio import Redis

from ..settings import Settings

logger = logging.getLogger("videre.backend.ai.ratelimit")

KEY_PREFIX = "ratelimit:ai"
SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600
UNKNOWN_CLIENT = "unknown"


def current_time() -> datetime:
    return datetime.now(UTC)


def client_identifier(request: Request) -> str:
    return request.client.host if request.client else UNKNOWN_CLIENT


@dataclass(frozen=True)
class RateLimitWindow:
    name: str
    key: str
    limit: int
    ttl_seconds: int


class RateLimitExceeded(Exception):
    def __init__(self, window_name: str, limit: int, retry_after_seconds: int) -> None:
        super().__init__(f"{window_name} limit of {limit} exceeded; retry in {retry_after_seconds}s")
        self.window_name = window_name
        self.limit = limit
        self.retry_after_seconds = retry_after_seconds
    
    @property
    def message(self) -> str:
        if self.retry_after_seconds < SECONDS_PER_MINUTE:
            return f"AI analysis is rate limited. Try again in {self.retry_after_seconds} seconds."
        if self.retry_after_seconds < SECONDS_PER_HOUR:
            minutes = max(round(self.retry_after_seconds / SECONDS_PER_MINUTE), 1)
            return f"AI analysis is rate limited. Try again in {minutes} minutes."
        hours = max(round(self.retry_after_seconds / SECONDS_PER_HOUR), 1)
        return f"AI analysis is rate limited. Try again in {hours} hours."


def _seconds_until_next_day(now: datetime) -> int:
    next_day = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(int((next_day - now).total_seconds()), 1)


def _seconds_until_next_minute(now: datetime) -> int:
    return max(SECONDS_PER_MINUTE - now.second, 1)


def build_windows(settings: Settings, client: str, now: datetime) -> list[RateLimitWindow]:
    day = now.strftime("%Y-%m-%d")
    minute = int(now.timestamp()) // SECONDS_PER_MINUTE
    day_ttl = _seconds_until_next_day(now)
    minute_ttl = _seconds_until_next_minute(now)
    
    return [
        RateLimitWindow(
            "per-client per-minute",
            f"{KEY_PREFIX}:ip:{client}:min:{minute}",
            settings.ai_client_minute_limit,
            minute_ttl,
        ),
        RateLimitWindow(
            "per-client per-day",
            f"{KEY_PREFIX}:ip:{client}:day:{day}",
            settings.ai_client_daily_limit,
            day_ttl,
        ),
        RateLimitWindow(
            "global per-minute",
            f"{KEY_PREFIX}:global:min:{minute}",
            settings.ai_global_minute_limit,
            minute_ttl,
        ),
        RateLimitWindow(
            "global per-day",
            f"{KEY_PREFIX}:global:day:{day}",
            settings.ai_global_daily_limit,
            day_ttl,
        )
    ]


async def enforce_rate_limit(redis_client: Redis, settings: Settings, client: str) -> None:
    for window in build_windows(settings, client, current_time()):
        count = await redis_client.incr(window.key)
        await redis_client.expire(window.key, window.ttl_seconds)
        
        if count > window.limit:
            logger.warning(
                "ai request rate limited",
                extra={
                    "window": window.name,
                    "limit": window.limit,
                    "count": count,
                    "client": client,
                    "retry_after_seconds": window.ttl_seconds,
                },
            )
            raise RateLimitExceeded(window.name, window.limit, window.ttl_seconds)
