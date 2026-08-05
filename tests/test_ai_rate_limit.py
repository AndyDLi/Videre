from datetime import UTC, datetime, timedelta

import pytest

from videre.backend.ai import rate_limit
from videre.backend.ai.rate_limit import (
    RateLimitExceeded,
    build_windows,
    client_identifier,
    enforce_rate_limit,
)
from videre.backend.settings import Settings

NOON = datetime(2026, 7, 28, 12, 0, 30, tzinfo=UTC)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.expiries: dict[str, int] = {}
    
    async def incr(self, key: str) -> int:
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]
    
    async def expire(self, key: str, seconds: int) -> bool:
        self.expiries[key] = seconds
        return True


class FakeClient:
    def __init__(self, host: str) -> None:
        self.host = host


class FakeRequest:
    def __init__(self, host: str | None) -> None:
        self.client = FakeClient(host) if host else None


@pytest.fixture
def clock(monkeypatch):
    holder = {"now": NOON}
    monkeypatch.setattr(rate_limit, "current_time", lambda: holder["now"])
    return holder


def settings_with(**overrides) -> Settings:
    defaults = {
        "ai_global_daily_limit": 400,
        "ai_global_minute_limit": 10,
        "ai_client_daily_limit": 20,
        "ai_client_minute_limit": 3,
    }
    return Settings(**{**defaults, **overrides})


async def call(redis, settings, client: str = "10.0.0.1") -> None:
    await enforce_rate_limit(redis, settings, client)


def test_the_peer_address_identifies_the_client() -> None:
    """A client is identified by its peer address."""

    assert client_identifier(FakeRequest("203.0.113.7")) == "203.0.113.7"


def test_a_missing_peer_falls_back_to_unknown() -> None:
    """A request with no peer address falls back to a single shared identity."""

    assert client_identifier(FakeRequest(None)) == "unknown"


def test_a_forwarded_header_is_not_trusted() -> None:
    """X-Forwarded-For is ignored, so a visitor cannot mint a fresh identity per request."""

    request = FakeRequest("10.0.0.1")
    request.headers = {"X-Forwarded-For": "1.2.3.4"}
    assert client_identifier(request) == "10.0.0.1"


def test_every_window_is_keyed_under_the_ai_ratelimit_namespace() -> None:
    """Every counter lives under the AI rate-limit key namespace."""

    windows = build_windows(settings_with(), "10.0.0.1", NOON)
    assert [window.key for window in windows] == [
        "ratelimit:ai:ip:10.0.0.1:min:29754000",
        "ratelimit:ai:ip:10.0.0.1:day:2026-07-28",
        "ratelimit:ai:global:min:29754000",
        "ratelimit:ai:global:day:2026-07-28",
    ]


def test_daily_windows_expire_at_the_next_utc_midnight() -> None:
    """Daily counters expire at the next UTC midnight, so they reset without a cleanup job."""

    daily = [window for window in build_windows(settings_with(), "ip", NOON) if "day" in window.key]
    assert all(window.ttl_seconds == 12 * 3600 - 30 for window in daily)


def test_minute_windows_expire_at_the_next_minute() -> None:
    """Minute counters expire at the next minute boundary."""

    minutes = [window for window in build_windows(settings_with(), "ip", NOON) if "min" in window.key]
    assert all(window.ttl_seconds == 30 for window in minutes)


async def test_a_ttl_is_set_on_every_counter(clock) -> None:
    """Every counter is created with a TTL, so none can outlive its window."""

    redis = FakeRedis()
    await call(redis, settings_with())
    assert set(redis.expiries) == set(redis.values)


async def test_the_client_minute_cap_rejects(clock) -> None:
    """A client exceeding its per-minute cap is rejected."""

    redis, settings = FakeRedis(), settings_with(ai_client_minute_limit=2)
    await call(redis, settings)
    await call(redis, settings)
    with pytest.raises(RateLimitExceeded) as raised:
        await call(redis, settings)
    assert raised.value.window_name == "per-client per-minute"


async def test_the_client_daily_cap_rejects(clock) -> None:
    """A client exceeding its daily cap is rejected."""

    redis = FakeRedis()
    settings = settings_with(ai_client_minute_limit=1000, ai_client_daily_limit=2)
    await call(redis, settings)
    await call(redis, settings)
    with pytest.raises(RateLimitExceeded) as raised:
        await call(redis, settings)
    assert raised.value.window_name == "per-client per-day"


async def test_the_global_minute_cap_rejects_across_clients(clock) -> None:
    """The global per-minute cap applies across separate clients."""

    redis = FakeRedis()
    settings = settings_with(ai_client_minute_limit=1000, ai_global_minute_limit=2)
    await call(redis, settings, "10.0.0.1")
    await call(redis, settings, "10.0.0.2")
    with pytest.raises(RateLimitExceeded) as raised:
        await call(redis, settings, "10.0.0.3")
    assert raised.value.window_name == "global per-minute"


async def test_the_global_daily_cap_rejects_across_clients(clock) -> None:
    """The global daily cap applies across separate clients."""

    redis = FakeRedis()
    settings = settings_with(
        ai_client_minute_limit=1000, ai_global_minute_limit=1000, ai_global_daily_limit=2
    )
    await call(redis, settings, "10.0.0.1")
    await call(redis, settings, "10.0.0.2")
    with pytest.raises(RateLimitExceeded) as raised:
        await call(redis, settings, "10.0.0.3")
    assert raised.value.window_name == "global per-day"


async def test_the_minute_window_resets_on_the_next_minute(clock) -> None:
    """Crossing into the next minute restores the per-minute budget."""

    redis, settings = FakeRedis(), settings_with(ai_client_minute_limit=1)
    await call(redis, settings)
    with pytest.raises(RateLimitExceeded):
        await call(redis, settings)
    
    clock["now"] = NOON + timedelta(minutes=1)
    await call(redis, settings)


async def test_the_daily_window_resets_on_the_next_utc_day(clock) -> None:
    """Crossing the UTC day boundary restores the daily budget."""

    redis = FakeRedis()
    settings = settings_with(ai_client_minute_limit=1000, ai_client_daily_limit=1)
    await call(redis, settings)
    with pytest.raises(RateLimitExceeded):
        await call(redis, settings)
    
    clock["now"] = NOON + timedelta(days=1)
    await call(redis, settings)


async def test_one_client_hitting_its_cap_does_not_block_another(clock) -> None:
    """One client exhausting its cap leaves other clients free to proceed."""

    redis, settings = FakeRedis(), settings_with(ai_client_minute_limit=1)
    await call(redis, settings, "10.0.0.1")
    with pytest.raises(RateLimitExceeded):
        await call(redis, settings, "10.0.0.1")
    await call(redis, settings, "10.0.0.2")


async def test_a_rejected_client_never_touches_the_global_counters(clock) -> None:
    """A client rejected by its own cap never consumes shared global quota."""

    redis, settings = FakeRedis(), settings_with(ai_client_minute_limit=1)
    await call(redis, settings)
    with pytest.raises(RateLimitExceeded):
        await call(redis, settings)
    assert redis.values["ratelimit:ai:global:min:29754000"] == 1


async def test_a_minute_rejection_reports_seconds(clock) -> None:
    """A short wait is reported to the visitor in seconds."""

    redis, settings = FakeRedis(), settings_with(ai_client_minute_limit=1)
    await call(redis, settings)
    with pytest.raises(RateLimitExceeded) as raised:
        await call(redis, settings)
    assert raised.value.message == "AI analysis is rate limited. Try again in 30 seconds."


async def test_a_daily_rejection_reports_hours(clock) -> None:
    """A long wait is reported to the visitor in hours."""

    redis = FakeRedis()
    settings = settings_with(ai_client_minute_limit=1000, ai_client_daily_limit=1)
    await call(redis, settings)
    with pytest.raises(RateLimitExceeded) as raised:
        await call(redis, settings)
    assert "hours" in raised.value.message
