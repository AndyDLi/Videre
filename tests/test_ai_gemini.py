import pytest
from google.genai import errors

from test_ai_prompt import make_context
from videre.backend.ai.analysis import RootCauseAnalysis
from videre.backend.ai.gemini import (
    GeminiAnalyst,
    GeminiRateLimitError,
    GeminiRequestError,
    GeminiResponseError,
    GeminiUnavailableError,
)
from videre.backend.settings import Settings

ANALYSIS = RootCauseAnalysis(summary="GPU is throttling.", next_steps=["Check cooling.", "Drain the node."])


class FakeResponse:
    def __init__(self, parsed=None, text=None) -> None:
        self.parsed = parsed
        self.text = text


class FakeModels:
    def __init__(self, outcomes) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict] = []
    
    async def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeClient:
    def __init__(self, outcomes) -> None:
        self.aio = type("Aio", (), {"models": FakeModels(outcomes)})()


def make_analyst(outcomes, **overrides) -> tuple[GeminiAnalyst, FakeClient]:
    settings = Settings(gemini_model="gemini-test", gemini_maximum_attempts=3, **overrides)
    client = FakeClient(outcomes)
    return GeminiAnalyst(settings, client=client), client


def client_error(code: int) -> errors.ClientError:
    return errors.ClientError(code, {"error": {"message": "boom", "code": code}})


def server_error(code: int = 503) -> errors.ServerError:
    return errors.ServerError(code, {"error": {"message": "unavailable", "code": code}})


# --- Success ---


async def test_a_parsed_response_is_returned() -> None:
    analyst, _ = make_analyst([FakeResponse(parsed=ANALYSIS)])
    assert await analyst.analyze(make_context()) == ANALYSIS


async def test_raw_json_text_is_parsed_when_parsed_is_absent() -> None:
    analyst, _ = make_analyst([FakeResponse(text=ANALYSIS.model_dump_json())])
    assert (await analyst.analyze(make_context())).summary == ANALYSIS.summary


async def test_the_pinned_model_is_used() -> None:
    analyst, client = make_analyst([FakeResponse(parsed=ANALYSIS)])
    await analyst.analyze(make_context())
    assert client.aio.models.calls[0]["model"] == "gemini-test"


async def test_the_prompt_carries_the_entity() -> None:
    analyst, client = make_analyst([FakeResponse(parsed=ANALYSIS)])
    await analyst.analyze(make_context())
    assert "gpu-1-2" in client.aio.models.calls[0]["contents"]


# --- Rate limiting is never retried ---


async def test_a_429_raises_immediately_without_retrying() -> None:
    analyst, client = make_analyst([client_error(429), FakeResponse(parsed=ANALYSIS)])
    with pytest.raises(GeminiRateLimitError):
        await analyst.analyze(make_context())
    assert len(client.aio.models.calls) == 1


# --- Other client errors are distinct and not retried ---


async def test_a_400_raises_a_request_error() -> None:
    analyst, client = make_analyst([client_error(400)])
    with pytest.raises(GeminiRequestError):
        await analyst.analyze(make_context())
    assert len(client.aio.models.calls) == 1


async def test_an_invalid_key_raises_a_request_error() -> None:
    analyst, _ = make_analyst([client_error(403)])
    with pytest.raises(GeminiRequestError):
        await analyst.analyze(make_context())


# --- Transient failures are retried ---


async def test_a_server_error_is_retried_then_succeeds() -> None:
    analyst, client = make_analyst([server_error(), FakeResponse(parsed=ANALYSIS)])
    assert await analyst.analyze(make_context()) == ANALYSIS
    assert len(client.aio.models.calls) == 2


async def test_persistent_server_errors_raise_unavailable() -> None:
    analyst, client = make_analyst([server_error(), server_error(), server_error()])
    with pytest.raises(GeminiUnavailableError):
        await analyst.analyze(make_context())
    assert len(client.aio.models.calls) == 3


async def test_a_timeout_is_retried() -> None:
    analyst, client = make_analyst([TimeoutError(), FakeResponse(parsed=ANALYSIS)])
    assert await analyst.analyze(make_context()) == ANALYSIS
    assert len(client.aio.models.calls) == 2


# --- Malformed output ---


async def test_unparseable_output_raises_a_response_error() -> None:
    analyst, _ = make_analyst([FakeResponse(text="not json at all")])
    with pytest.raises(GeminiResponseError):
        await analyst.analyze(make_context())


async def test_empty_output_raises_a_response_error() -> None:
    analyst, _ = make_analyst([FakeResponse()])
    with pytest.raises(GeminiResponseError):
        await analyst.analyze(make_context())
