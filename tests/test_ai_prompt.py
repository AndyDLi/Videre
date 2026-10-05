from datetime import UTC, datetime

from videre.backend.ai.context import (
    FailureContext,
    FailureRecordContext,
    GpuStateContext,
    JobStateContext,
    LogLineContext,
    LokiContext,
    MetricSeriesContext,
    NodeStateContext,
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
    """The prompt opens by naming the entity under analysis."""

    assert build_prompt(make_context(), maximum_characters=10_000).startswith("ENTITY: gpu gpu-1-2")


def test_every_available_section_is_present() -> None:
    """A full context renders all three source sections into the prompt."""

    prompt = build_prompt(make_context(), maximum_characters=10_000)
    assert "CLUSTER RECORDS:" in prompt
    assert "METRIC TRENDS" in prompt
    assert "RECENT LOG LINES" in prompt


def test_unavailable_sources_are_named() -> None:
    """A missing source is declared to the model rather than silently omitted."""

    prompt = build_prompt(make_context(degraded=True), maximum_characters=10_000)
    assert "UNAVAILABLE DATA SOURCES" in prompt
    assert "prometheus" in prompt
    assert "METRIC TRENDS" not in prompt


def test_an_empty_context_still_renders() -> None:
    """A context with no sources at all still produces a usable prompt naming the entity."""

    context = FailureContext(
        entity_type=FailureEntityTable.NODE, entity_id="node-0", generated_at=GENERATED_AT
    )
    prompt = build_prompt(context, maximum_characters=10_000)
    assert "ENTITY: node node-0" in prompt
    assert "UNAVAILABLE DATA SOURCES" in prompt


def test_logs_are_dropped_before_metrics_when_oversized() -> None:
    """The reduction ladder sheds log lines first, keeping metric trends within the budget."""

    prompt = build_prompt(make_context(logs=400), maximum_characters=1_200)
    assert len(prompt) <= 1_200
    assert "METRIC TRENDS" in prompt


def test_an_unshrinkable_prompt_is_hard_truncated() -> None:
    """A context that cannot shrink far enough is cut to the budget and marked as truncated."""

    context = make_context()
    context.postgres = PostgresContext.model_validate({})
    prompt = build_prompt(context, maximum_characters=60)
    assert len(prompt) <= 60
    assert prompt.endswith(TRUNCATION_MARKER)


def test_the_prompt_contains_only_context_data() -> None:
    """No credential, connection string, or internal address leaks into the prompt."""

    prompt = build_prompt(make_context(), maximum_characters=10_000)
    for forbidden in ("password", "postgresql", "svc.cluster.local", "api_key", "AIza"):
        assert forbidden not in prompt


def dense_context() -> FailureContext:
    context = make_context(logs=50, series=24)
    context.entity_type, context.entity_id = FailureEntityTable.JOB, "job-1"
    assert context.postgres is not None
    context.postgres.job = JobStateContext(
        id="job-1", cluster_id="cluster-a", lifecycle_state="FAILED", requested_cpu_cores=8,
        requested_memory_gb=64, requested_gpu_count=1, priority=0, pod_name=None,
        failure_reason="timeout " * 2000, started_at=None, completed_at=None,
        assigned_node_ids=[f"node-{i}" for i in range(8)],
    )
    context.postgres.assigned_nodes = [NodeStateContext(
        id=f"node-{i}", cluster_id="cluster-a", health_state="READY", cpu_cores=64,
        memory_gb=512, gpu_count=8, updated_at=GENERATED_AT,
    ) for i in range(8)]
    context.postgres.gpus = [GpuStateContext(
        id=f"gpu-{i:02}", node_id=f"node-{i//8}", health_state="FAILED", utilization_percentage=0,
        temperature_celsius=90, memory_used_mb=0, memory_total_mb=81920,
        ecc_correctable_count=0, ecc_uncorrectable_count=1, xid_error_count=1,
        last_updated_at=GENERATED_AT,
    ) for i in range(64)]
    def failures(prefix, entity_type, entity_id):
        return [FailureRecordContext(
            id=f"{prefix}-{i:02}", entity_type=entity_type, entity_id=entity_id,
            category=entity_type, root_cause_tag="gpu_xid_error" if entity_type == "gpu" else "job_timeout",
            correlation_id="shared-incident", detected_at=GENERATED_AT, resolved_at=None,
        ) for i in range(20)]
    context.postgres.unresolved_failures = failures("direct-gpu", "gpu", "gpu-00")
    context.postgres.correlated_failures = failures("correlated-job", "job", "job-other")
    context.postgres.recently_resolved_failures = [row.model_copy(update={"resolved_at": GENERATED_AT})
        for row in failures("resolved", "gpu", "gpu-00")]
    context.postgres.truncated_sections = ["gpus"]
    assert context.prometheus is not None
    context.prometheus.scope = "deployment"
    return context


def test_dense_prompt_keeps_failure_evidence_and_scope_within_budget():
    prompt = build_prompt(dense_context(), maximum_characters=24_000)
    assert len(prompt) <= 24_000
    assert "direct-gpu-00" in prompt and "correlated-job-00" in prompt
    assert "gpu_xid_error" in prompt and "job_timeout" in prompt
    assert "not per-job measurements" in prompt
    assert "gpus" in prompt.split("CLUSTER RECORDS:")[0]
    assert "evidence reduced" in prompt
    assert not prompt.endswith(TRUNCATION_MARKER)


def test_relationship_instructions_do_not_assert_assignment_or_causality():
    from videre.backend.ai.prompt import SYSTEM_INSTRUCTION
    assert "exact GPU assignment is unknown" in SYSTEM_INSTRUCTION
    assert "not proof of causality" in SYSTEM_INSTRUCTION
    assert "observed facts from hypotheses" in SYSTEM_INSTRUCTION


def test_unicode_evidence_fits_budget_without_losing_target_or_failures():
    import json

    context = dense_context()
    assert context.postgres is not None and context.postgres.job is not None
    postgres = context.postgres
    symbol = chr(0x1F4A5)
    context.entity_id = "job-" + symbol * 124
    postgres.job.id = context.entity_id
    postgres.job.cluster_id = symbol * 64
    for index, node in enumerate(postgres.assigned_nodes):
        node.id, node.cluster_id = f"{index:02}" + symbol * 62, symbol * 64
    postgres.job.assigned_node_ids = [node.id for node in postgres.assigned_nodes]
    for index, gpu in enumerate(postgres.gpus):
        gpu.id, gpu.node_id = f"{index:02}" + symbol * 62, postgres.assigned_nodes[index // 8].id
    for section_index, rows in enumerate((
        postgres.unresolved_failures, postgres.correlated_failures, postgres.recently_resolved_failures,
    )):
        for index, row in enumerate(rows):
            row.id = f"{section_index}{index:02}" + symbol * 61
            row.entity_id = symbol * 128 if row.entity_type == "job" else postgres.gpus[0].id
            row.correlation_id = symbol * 64
            row.root_cause_tag = symbol * 64
    prompt = build_prompt(context, maximum_characters=24_000)
    assert len(prompt) <= 24_000
    assert not prompt.endswith(TRUNCATION_MARKER)
    records = json.loads(prompt.split("CLUSTER RECORDS:\n")[1].split("\n\n")[0])
    assert records["job"]["id"] == context.entity_id
    assert len(records["unresolved_failures"]) == 5
    assert len(records["correlated_failures"]) == 5
