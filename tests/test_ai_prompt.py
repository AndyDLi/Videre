from datetime import UTC, datetime

from videre.backend.ai.context import (
    FailureContext,
    LogLineContext,
    LokiContext,
    MetricSeriesContext,
    PostgresContext,
    PrometheusContext,
)
from videre.backend.ai.prompt import TRUNCATION_MARKER, build_prompt
from videre.database.tables import FailureEntityTable

GENERATED_AT = datetime(2026, 7, 28, 21, 0, tzinfo=UTC)


def make_context(*, logs: int = 3, series: int = 2, degraded: bool = False) -> FailureContext:
    return FailureContext(
        entity_type=FailureEntityTable.GPU,
        entity_id="gpu-1-2",
        generated_at=GENERATED_AT,
        postgres=PostgresContext(),
        prometheus=None if degraded else PrometheusContext(
            window_minutes=15,
            series=[
                MetricSeriesContext(
                    metric="videre_gpu_temperature_celsius",
                    labels={"gpu_id": "gpu-1-2"},
                    latest=90.0,
                    minimum=40.0,
                    maximum=90.0,
                    average=65.0,
                    sample_count=15,
                )
            ] * series,
        ),
        logs=LokiContext(
            queries=["{namespace=\"videre\"}"],
            window_minutes=15,
            lines=[
                LogLineContext(timestamp=GENERATED_AT, labels={"pod": "simulator-abc"}, line=f"line {index}")
                for index in range(logs)
            ],
        ),
    )


def test_the_entity_is_named_first() -> None:
    assert build_prompt(make_context(), maximum_characters=10_000).startswith("ENTITY: gpu gpu-1-2")


def test_every_available_section_is_present() -> None:
    prompt = build_prompt(make_context(), maximum_characters=10_000)
    assert "CLUSTER RECORDS:" in prompt
    assert "METRIC TRENDS" in prompt
    assert "RECENT LOG LINES" in prompt


def test_unavailable_sources_are_named() -> None:
    prompt = build_prompt(make_context(degraded=True), maximum_characters=10_000)
    assert "UNAVAILABLE DATA SOURCES" in prompt
    assert "prometheus" in prompt
    assert "METRIC TRENDS" not in prompt


def test_an_empty_context_still_renders() -> None:
    context = FailureContext(
        entity_type=FailureEntityTable.NODE, entity_id="node-0", generated_at=GENERATED_AT
    )
    prompt = build_prompt(context, maximum_characters=10_000)
    assert "ENTITY: node node-0" in prompt
    assert "UNAVAILABLE DATA SOURCES" in prompt


def test_logs_are_dropped_before_metrics_when_oversized() -> None:
    prompt = build_prompt(make_context(logs=400), maximum_characters=1_200)
    assert len(prompt) <= 1_200
    assert "METRIC TRENDS" in prompt


def test_an_unshrinkable_prompt_is_hard_truncated() -> None:
    context = make_context()
    context.postgres = PostgresContext.model_validate({})
    prompt = build_prompt(context, maximum_characters=60)
    assert len(prompt) <= 60
    assert prompt.endswith(TRUNCATION_MARKER)


def test_the_prompt_contains_only_context_data() -> None:
    prompt = build_prompt(make_context(), maximum_characters=10_000)
    for forbidden in ("password", "postgresql", "svc.cluster.local", "api_key", "AIza"):
        assert forbidden not in prompt
