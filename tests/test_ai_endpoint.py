import pytest
import pytest_asyncio
from httpx2 import ASGITransport, AsyncClient

from test_ai_response_cache import FakeRedis
from test_cache import SingleSessionFactory
from test_event_mapping import sample_gpu, sample_job, sample_node
from videre.backend.ai import assistant
from videre.backend.ai.analysis import RootCauseAnalysis
from videre.backend.ai.gemini import (
    GeminiRequestError,
    GeminiUnavailableError,
)
from videre.backend.ai.rate_limit import RateLimitExceeded
from videre.backend.application import create_application
from videre.backend.dependencies import (
    get_gemini_analyst,
    get_http_client,
    get_redis,
    get_session,
    get_session_factory,
)
from videre.backend.persistence.event_mapping import apply_event
from videre.backend.settings import Settings
from videre.event_types import EventType, LifecycleEventType
from videre.events import GpuMetricMessage, JobEventMessage, NodeEventMessage, Topic
from videre.models import JobState, NodeHealthState

ANALYSIS = RootCauseAnalysis(summary="Node is not ready.", next_steps=["Check the kubelet."])


class SpyAnalyst:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls = 0
        self.error = error
    
    async def analyze(self, context) -> RootCauseAnalysis:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return ANALYSIS


@pytest.fixture(autouse=True)
def stub_context(monkeypatch):    
    from datetime import UTC, datetime
    
    from videre.backend.ai.context import FailureContext
    
    async def fake_assemble(session_factory, http_client, settings, entity_type, entity_id):
        return FailureContext(
            entity_type=entity_type, entity_id=entity_id, generated_at=datetime.now(UTC)
        )
    
    monkeypatch.setattr(assistant, "assemble_failure_context", fake_assemble)


async def seed(session) -> None:
    await apply_event(session, Topic.NODE_EVENTS, NodeEventMessage(
        event_type=LifecycleEventType.NODE_STATE.value, payload=sample_node()
    ))
    await apply_event(session, Topic.GPU_METRICS, GpuMetricMessage(
        event_type=LifecycleEventType.GPU_METRIC.value, payload=sample_gpu()
    ))
    await apply_event(session, Topic.JOB_EVENTS, JobEventMessage(
        event_type=LifecycleEventType.JOB_RUNNING.value, payload=sample_job(JobState.RUNNING)
    ))
    await session.flush()


def build_client(session, analyst, settings=None):
    application = create_application(settings or Settings())
    redis_client = FakeRedis()
    application.dependency_overrides[get_session] = lambda: session
    application.dependency_overrides[get_session_factory] = lambda: SingleSessionFactory(session)
    application.dependency_overrides[get_redis] = lambda: redis_client
    application.dependency_overrides[get_http_client] = lambda: None
    application.dependency_overrides[get_gemini_analyst] = lambda: analyst
    return application, redis_client


@pytest_asyncio.fixture
async def analyst():
    return SpyAnalyst()


@pytest_asyncio.fixture
async def client(session, analyst):
    application, _ = build_client(session, analyst)
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client


def request_body(entity_type: str = "node", entity_id: str = "node-0") -> dict:
    return {"entity_type": entity_type, "entity_id": entity_id}


# --- Fresh request ---


async def test_a_fresh_request_returns_an_analysis(session, client, analyst) -> None:
    await seed(session)
    response = await client.post("/ai/analyze", json=request_body())
    
    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == ANALYSIS.summary
    assert body["next_steps"] == ANALYSIS.next_steps
    assert body["from_cache"] is False
    assert body["cache_age_seconds"] is None
    assert (body["entity_type"], body["entity_id"]) == ("node", "node-0")
    assert analyst.calls == 1


async def test_every_entity_type_is_accepted(session, client) -> None:
    await seed(session)
    for entity_type, entity_id in (("node", "node-0"), ("gpu", "gpu-0-0"), ("job", "job-1")):
        response = await client.post("/ai/analyze", json=request_body(entity_type, entity_id))
        assert response.status_code == 200, entity_type


# --- Cache hit ---


async def test_a_repeated_request_is_served_from_cache(session, client, analyst) -> None:
    await seed(session)
    await client.post("/ai/analyze", json=request_body())
    response = await client.post("/ai/analyze", json=request_body())
    
    assert response.json()["from_cache"] is True
    assert response.json()["cache_age_seconds"] is not None
    assert analyst.calls == 1


# --- Changed situation within the TTL ---


async def test_a_changed_health_state_produces_a_fresh_analysis(session, client, analyst) -> None:
    await seed(session)
    await client.post("/ai/analyze", json=request_body())
    
    await apply_event(session, Topic.NODE_EVENTS, NodeEventMessage(
        event_type=EventType.NODE_KUBELET_DOWN.value,
        payload=sample_node(NodeHealthState.NOT_READY),
    ))
    await session.flush()
    
    response = await client.post("/ai/analyze", json=request_body())
    assert response.json()["from_cache"] is False
    assert analyst.calls == 2


# --- Validation ---


async def test_an_unknown_entity_returns_404_without_calling_gemini(session, client, analyst) -> None:
    await seed(session)
    response = await client.post("/ai/analyze", json=request_body(entity_id="node-absent"))
    
    assert response.status_code == 404
    assert analyst.calls == 0


async def test_an_invalid_entity_type_returns_422(client) -> None:
    assert (await client.post("/ai/analyze", json=request_body("cluster", "cluster-a"))).status_code == 422


async def test_an_empty_entity_id_returns_422(client) -> None:
    assert (await client.post("/ai/analyze", json=request_body("node", ""))).status_code == 422


# --- Rate limiting ---


async def test_a_rate_limited_request_returns_429_with_retry_after(
    session, client, analyst, monkeypatch
) -> None:
    await seed(session)
    
    async def reject(redis_client, settings, client_id):
        raise RateLimitExceeded("global per-day", 400, 3600)
    
    monkeypatch.setattr(assistant, "enforce_rate_limit", reject)
    response = await client.post("/ai/analyze", json=request_body())
    
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "3600"
    assert "try again" in response.json()["detail"].lower()
    assert analyst.calls == 0


# --- Provider failures ---


async def test_an_unavailable_provider_returns_503(session) -> None:
    analyst = SpyAnalyst(GeminiUnavailableError("gemini unreachable"))
    application, _ = build_client(session, analyst)
    await seed(session)
    
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        response = await async_client.post("/ai/analyze", json=request_body())
    
    assert response.status_code == 503


async def test_a_provider_error_never_leaks_upstream_detail(session) -> None:
    analyst = SpyAnalyst(GeminiRequestError("gemini rejected the request: 400 model gemini-secret-x"))
    application, _ = build_client(session, analyst)
    await seed(session)
    
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        response = await async_client.post("/ai/analyze", json=request_body())
    
    assert response.status_code == 502
    assert "gemini" not in response.text.lower()


async def test_an_unconfigured_assistant_returns_503(session) -> None:
    application, _ = build_client(session, None)
    await seed(session)
    
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        response = await async_client.post("/ai/analyze", json=request_body())
    
    assert response.status_code == 503
