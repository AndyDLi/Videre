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


async def test_a_parsed_response_is_returned() -> None:
    """A structured response is returned as the parsed analysis model."""

    analyst, _ = make_analyst([FakeResponse(parsed=ANALYSIS)])
    assert await analyst.analyze(make_context()) == ANALYSIS


async def test_raw_json_text_is_parsed_when_parsed_is_absent() -> None:
    """When the SDK supplies only raw text, the JSON body is parsed into the analysis model."""

    analyst, _ = make_analyst([FakeResponse(text=ANALYSIS.model_dump_json())])
    assert (await analyst.analyze(make_context())).summary == ANALYSIS.summary


async def test_the_pinned_model_is_used() -> None:
    """The configured model identifier is sent verbatim rather than a floating alias."""

    analyst, client = make_analyst([FakeResponse(parsed=ANALYSIS)])
    await analyst.analyze(make_context())
    assert client.aio.models.calls[0]["model"] == "gemini-test"


async def test_the_prompt_carries_the_entity() -> None:
    """The entity under analysis reaches the model inside the prompt."""

    analyst, client = make_analyst([FakeResponse(parsed=ANALYSIS)])
    await analyst.analyze(make_context())
    assert "gpu-1-2" in client.aio.models.calls[0]["contents"]


async def test_a_429_raises_immediately_without_retrying() -> None:
    """A provider rate-limit rejection raises at once, since retrying would only deepen the breach."""

    analyst, client = make_analyst([client_error(429), FakeResponse(parsed=ANALYSIS)])
    with pytest.raises(GeminiRateLimitError):
        await analyst.analyze(make_context())
    assert len(client.aio.models.calls) == 1


async def test_a_400_raises_a_request_error() -> None:
    """A malformed request fails immediately, because retrying cannot change the outcome."""

    analyst, client = make_analyst([client_error(400)])
    with pytest.raises(GeminiRequestError):
        await analyst.analyze(make_context())
    assert len(client.aio.models.calls) == 1


async def test_an_invalid_key_raises_a_request_error() -> None:
    """A rejected credential surfaces as a request error rather than a transient failure."""

    analyst, _ = make_analyst([client_error(403)])
    with pytest.raises(GeminiRequestError):
        await analyst.analyze(make_context())


async def test_a_server_error_is_retried_then_succeeds() -> None:
    """A transient server error is retried, and the following success is returned."""

    analyst, client = make_analyst([server_error(), FakeResponse(parsed=ANALYSIS)])
    assert await analyst.analyze(make_context()) == ANALYSIS
    assert len(client.aio.models.calls) == 2


async def test_persistent_server_errors_raise_unavailable() -> None:
    """Exhausting every attempt on server errors reports the provider as unavailable."""

    analyst, client = make_analyst([server_error(), server_error(), server_error()])
    with pytest.raises(GeminiUnavailableError):
        await analyst.analyze(make_context())
    assert len(client.aio.models.calls) == 3


async def test_a_timeout_is_retried() -> None:
    """A timed-out call is retried like any other transient failure."""

    analyst, client = make_analyst([TimeoutError(), FakeResponse(parsed=ANALYSIS)])
    assert await analyst.analyze(make_context()) == ANALYSIS
    assert len(client.aio.models.calls) == 2


async def test_unparseable_output_raises_a_response_error() -> None:
    """Output that is not valid JSON is rejected rather than passed on as an analysis."""

    analyst, _ = make_analyst([FakeResponse(text="not json at all")])
    with pytest.raises(GeminiResponseError):
        await analyst.analyze(make_context())


async def test_empty_output_raises_a_response_error() -> None:
    """A response carrying no content at all is rejected."""

    analyst, _ = make_analyst([FakeResponse()])
    with pytest.raises(GeminiResponseError):
        await analyst.analyze(make_context())
