from typing import Any

from httpx2 import AsyncClient, MockTransport, Request, Response

from test_ai_fingerprint import seed
from test_event_mapping import sample_job
from videre.backend.ai.loki_source import (
    build_entity_query,
    build_pod_query,
    parse_streams,
    query_logs,
    resolve_queries,
)
from videre.backend.ai.prometheus_source import build_queries, query_metrics, summarize
from videre.backend.persistence.event_mapping import apply_event
from videre.database.tables import FailureEntityTable
from videre.event_types import LifecycleEventType
from videre.events import JobEventMessage, Topic
from videre.models import JobState


class RecordingHandler:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.queries: list[str] = []
    
    def __call__(self, request: Request) -> Response:
        self.queries.append(request.url.params["query"])
        return Response(200, json=self.payload)


def client_for(handler: RecordingHandler) -> AsyncClient:
    return AsyncClient(transport=MockTransport(handler))


def matrix(metric_name: str, labels: dict[str, str], values: list[float]) -> dict[str, Any]:
    return {
        "status": "success",
        "data": {
            "resultType": "matrix",
            "result": [
                {
                    "metric": {"__name__": metric_name, **labels},
                    "values": [[1_700_000_000 + index * 60, str(value)] for index, value in enumerate(values)],
                }
            ],
        },
    }


def streams(lines: list[tuple[int, str]]) -> dict[str, Any]:
    return {
        "status": "success",
        "data": {
            "resultType": "streams",
            "result": [
                {
                    "stream": {"app": "simulator", "pod": "simulator-abc"},
                    "values": [[str(timestamp), line] for timestamp, line in lines],
                }
            ],
        },
    }


# --- PromQL construction ---


def test_gpu_queries_filter_by_gpu_id() -> None:
    queries = build_queries(FailureEntityTable.GPU, "gpu-1-2", 15)
    assert all('gpu_id="gpu-1-2"' in query for query in queries)
    assert any(query.startswith("videre_gpu_temperature_celsius") for query in queries)


def test_node_queries_filter_by_node_id() -> None:
    queries = build_queries(FailureEntityTable.NODE, "node-1", 15)
    assert all('node_id="node-1"' in query for query in queries)


def test_job_queries_use_deployment_wide_series() -> None:
    queries = build_queries(FailureEntityTable.JOB, "job-9", 15)
    assert "videre_jobs_by_state" in queries
    assert all("job-9" not in query for query in queries)


def test_label_values_are_escaped() -> None:
    queries = build_queries(FailureEntityTable.GPU, 'gpu-"evil"', 15)
    assert all('gpu_id="gpu-\\"evil\\""' in query for query in queries)


# --- Prometheus parsing ---


def test_series_are_summarized() -> None:
    summaries = summarize("fallback", matrix("videre_gpu_temperature_celsius", {"gpu_id": "gpu-1-2"}, [40.0, 90.0]))
    assert len(summaries) == 1
    summary = summaries[0]
    assert (summary.metric, summary.labels) == ("videre_gpu_temperature_celsius", {"gpu_id": "gpu-1-2"})
    assert (summary.latest, summary.minimum, summary.maximum, summary.average) == (90.0, 40.0, 90.0, 65.0)
    assert summary.sample_count == 2


def test_a_failed_prometheus_response_yields_no_series() -> None:
    assert summarize("fallback", {"status": "error", "error": "bad query"}) == []


def test_an_empty_series_is_skipped() -> None:
    assert summarize("fallback", matrix("videre_gpu_utilization_percent", {}, [])) == []


async def test_query_metrics_issues_every_query() -> None:
    handler = RecordingHandler(matrix("videre_gpu_utilization_percent", {"gpu_id": "gpu-1-2"}, [10.0, 20.0]))
    async with client_for(handler) as client:
        context = await query_metrics(
            client, "http://prometheus", FailureEntityTable.GPU, "gpu-1-2", window_minutes=15
        )
    assert len(handler.queries) == 4
    assert context.window_minutes == 15
    assert len(context.series) == 4


# --- LogQL construction ---


def test_entity_query_filters_the_application_streams() -> None:
    assert build_entity_query("node-1") == '{namespace="videre", app=~"simulator|backend"} |= "node-1"'


def test_pod_query_selects_one_pod_stream() -> None:
    assert build_pod_query("sim-job-1-x9") == '{namespace="videre", pod="sim-job-1-x9"}'


async def test_node_maps_to_its_own_id(session) -> None:
    await seed(session)
    assert await resolve_queries(session, FailureEntityTable.NODE, "node-0") == [build_entity_query("node-0")]


async def test_gpu_maps_to_its_parent_node_id(session) -> None:
    await seed(session)
    assert await resolve_queries(session, FailureEntityTable.GPU, "gpu-0-0") == [build_entity_query("node-0")]


async def test_job_maps_to_its_id_and_its_pod(session) -> None:
    await seed(session)
    
    job = sample_job(JobState.RUNNING)
    job.pod_name = "sim-job-1-x9"
    await apply_event(session, Topic.JOB_EVENTS, JobEventMessage(
        event_type=LifecycleEventType.JOB_RUNNING.value, payload=job
    ))
    await session.flush()
    
    assert await resolve_queries(session, FailureEntityTable.JOB, "job-1") == [
        build_entity_query("job-1"),
        build_pod_query("sim-job-1-x9"),
    ]


async def test_job_without_a_pod_maps_to_its_id_only(session) -> None:
    await seed(session)
    assert await resolve_queries(session, FailureEntityTable.JOB, "job-1") == [build_entity_query("job-1")]


# --- Loki parsing ---


def test_lines_are_parsed_with_labels() -> None:
    lines = parse_streams(streams([(1_700_000_000_000_000_000, "published")]))
    assert len(lines) == 1
    assert lines[0].line == "published"
    assert lines[0].labels["app"] == "simulator"


def test_a_failed_loki_response_yields_no_lines() -> None:
    assert parse_streams({"status": "error"}) == []


def test_long_lines_are_truncated() -> None:
    lines = parse_streams(streams([(1_700_000_000_000_000_000, "x" * 900)]))
    assert len(lines[0].line) == 500


async def test_query_logs_merges_queries_newest_first_within_the_limit() -> None:
    handler = RecordingHandler(streams([
        (1_700_000_000_000_000_000, "older"),
        (1_700_000_060_000_000_000, "newer"),
    ]))
    async with client_for(handler) as client:
        context = await query_logs(
            client,
            "http://loki",
            [build_entity_query("job-1"), build_pod_query("sim-job-1-x9")],
            window_minutes=15,
            line_limit=3,
        )
    assert len(handler.queries) == 2
    assert [line.line for line in context.lines] == ["newer", "newer", "older"]
