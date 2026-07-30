from typing import Any

from fastapi.testclient import TestClient

from videre.backend.application import create_application
from videre.backend.dependencies import get_redis, get_session
from videre.backend.settings import Settings

DEVELOPMENT_ORIGIN = "http://localhost:5173"
PRODUCTION_ORIGIN = "https://ragingasian.tail462d2b.ts.net"
FOREIGN_ORIGIN = "https://not-videre.example.com"


class ReachableSession:
    async def execute(self, statement: Any) -> Any:
        return None


class ReachableRedis:
    async def ping(self) -> bool:
        return True


def build_client(cors_allowed_origins: str = DEVELOPMENT_ORIGIN) -> TestClient:
    application = create_application(Settings(cors_allowed_origins=cors_allowed_origins))
    application.dependency_overrides[get_session] = lambda: ReachableSession()
    application.dependency_overrides[get_redis] = lambda: ReachableRedis()
    return TestClient(application)


def test_settings_default_to_the_local_development_origin() -> None:
    assert Settings().cors_allowed_origin_list == [DEVELOPMENT_ORIGIN]


def test_settings_split_a_comma_separated_origin_list() -> None:
    settings = Settings(cors_allowed_origins=f"{DEVELOPMENT_ORIGIN}, {PRODUCTION_ORIGIN} ,")
    assert settings.cors_allowed_origin_list == [DEVELOPMENT_ORIGIN, PRODUCTION_ORIGIN]


def test_allowed_origin_receives_cors_headers_on_a_simple_request() -> None:
    with build_client() as client:
        response = client.get("/healthz", headers={"Origin": DEVELOPMENT_ORIGIN})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == DEVELOPMENT_ORIGIN
    assert "Retry-After" in response.headers["access-control-expose-headers"]


def test_allowed_origin_receives_a_successful_preflight_for_the_ai_endpoint() -> None:
    with build_client() as client:
        response = client.options(
            "/ai/analyze",
            headers={
                "Origin": DEVELOPMENT_ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == DEVELOPMENT_ORIGIN
    assert "POST" in response.headers["access-control-allow-methods"]


def test_foreign_origin_receives_no_allow_origin_header() -> None:
    with build_client() as client:
        response = client.get("/healthz", headers={"Origin": FOREIGN_ORIGIN})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_multiple_configured_origins_are_each_allowed() -> None:
    with build_client(f"{DEVELOPMENT_ORIGIN},{PRODUCTION_ORIGIN}") as client:
        for origin in (DEVELOPMENT_ORIGIN, PRODUCTION_ORIGIN):
            response = client.get("/healthz", headers={"Origin": origin})
            assert response.headers["access-control-allow-origin"] == origin
