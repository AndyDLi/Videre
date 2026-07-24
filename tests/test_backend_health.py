from typing import Any

import pytest
from fastapi.testclient import TestClient

from videre.backend.application import create_application
from videre.backend.dependencies import get_redis, get_session
from videre.backend.settings import Settings


class FakeSession:
    def __init__(self, *, working: bool = True) -> None:
        self._working = working

    async def execute(self, statement: Any) -> Any:
        if not self._working:
            raise ConnectionError("postgres down")
        return None


class FakeRedis:
    def __init__(self, *, working: bool = True) -> None:
        self._working = working

    async def ping(self) -> bool:
        if not self._working:
            raise ConnectionError("redis down")
        return True


def build_client(*, postgres_working: bool = True, redis_working: bool = True) -> TestClient:
    application = create_application(Settings())
    application.dependency_overrides[get_session] = lambda: FakeSession(working=postgres_working)
    application.dependency_overrides[get_redis] = lambda: FakeRedis(working=redis_working)
    return TestClient(application)


def test_healthz_reports_healthy_when_both_datastores_respond() -> None:
    with build_client() as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "checks": {"postgres": True, "redis": True}}


@pytest.mark.parametrize(
    ("postgres_working", "redis_working"),
    [(False, True), (True, False), (False, False)],
)
def test_healthz_reports_503_when_a_datastore_is_unreachable(postgres_working, redis_working) -> None:
    with build_client(postgres_working=postgres_working, redis_working=redis_working) as client:
        response = client.get("/healthz")
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"


def test_settings_build_the_expected_dsn() -> None:
    settings = Settings(postgres_host="db", postgres_user="u", postgres_password="p")
    dsn = settings.postgres_dsn
    assert dsn.render_as_string(hide_password=False) == "postgresql+asyncpg://u:p@db:5432/videre"
    assert "***" in str(dsn)
    assert settings.redis_url.startswith("redis://")


def test_settings_escape_a_password_containing_url_characters() -> None:
    settings = Settings(postgres_host="db", postgres_user="u", postgres_password="p@ss/word")
    assert settings.postgres_dsn.password == "p@ss/word"     # survives a round trip unmangled
