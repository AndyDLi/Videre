from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY, CollectorRegistry

from test_backend_health import build_client
from test_event_mapping import sample_gpu, sample_job, sample_node
from videre.backend.cache.snapshot import ClusterHealthSnapshot
from videre.backend.metrics.instrumentation import instrument_application
from videre.backend.metrics.recorder import (
    CAPACITY_EVENT_TYPES,
    GPU_ERROR_EVENT_TYPES,
    JOB_FAILURE_EVENT_TYPES,
    NODE_FAILURE_EVENT_TYPES,
    record_cluster_snapshots,
    record_event,
)
from videre.event_types import EventType, LifecycleEventType
from videre.events import (
    GpuMetricMessage,
    JobEventMessage,
    NodeEventMessage,
    SchedulerEventMessage,
    Topic,
)
from videre.models import (
    GpuHealthState,
    JobState,
    NodeHealthState,
    SchedulerEvent,
    SchedulerEventType,
)

MEGABYTE = 1024 * 1024


def read(name: str, **labels: str) -> float:
    value = REGISTRY.get_sample_value(name, labels)
    return 0.0 if value is None else value


def build_isolated_client() -> tuple[TestClient, CollectorRegistry]:
    registry = CollectorRegistry()
    application = FastAPI()

    @application.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "healthy"}

    @application.get("/nodes/{node_id}")
    def node_detail(node_id: str) -> dict[str, str]:
        return {"id": node_id}

    instrument_application(application, registry)
    return TestClient(application), registry


# --- Completeness ---


def test_the_four_topic_groups_partition_every_failure_event_type() -> None:
    grouped = (
        NODE_FAILURE_EVENT_TYPES
        | GPU_ERROR_EVENT_TYPES
        | JOB_FAILURE_EVENT_TYPES
        | CAPACITY_EVENT_TYPES
    )
    assert grouped == {member.value for member in EventType}


def test_the_four_topic_groups_do_not_overlap() -> None:
    groups = (
        NODE_FAILURE_EVENT_TYPES,
        GPU_ERROR_EVENT_TYPES,
        JOB_FAILURE_EVENT_TYPES,
        CAPACITY_EVENT_TYPES,
    )
    assert sum(len(group) for group in groups) == len(set().union(*groups))


# --- GPU telemetry gauges ---


def test_gpu_metric_event_sets_every_gpu_gauge() -> None:
    gpu = sample_gpu()
    gpu.id = "metrics-gpu-gauges"
    gpu.utilization_percentage = 73.5
    gpu.temperature_celsius = 68.0
    gpu.memory_used_mb = 40960
    
    record_event(Topic.GPU_METRICS, GpuMetricMessage(
        event_type=LifecycleEventType.GPU_METRIC.value, payload=gpu
    ))
    
    labels = {"node_id": gpu.node_id, "gpu_id": gpu.id}
    assert read("videre_gpu_utilization_percent", **labels) == 73.5
    assert read("videre_gpu_temperature_celsius", **labels) == 68.0
    assert read("videre_gpu_memory_used_bytes", **labels) == 40960 * MEGABYTE
    assert read("videre_gpu_memory_total_bytes", **labels) == 81920 * MEGABYTE


def test_gpu_gauges_are_overwritten_by_the_next_event() -> None:
    gpu = sample_gpu()
    gpu.id = "metrics-gpu-overwrite"
    
    gpu.utilization_percentage = 10.0
    record_event(Topic.GPU_METRICS, GpuMetricMessage(
        event_type=LifecycleEventType.GPU_METRIC.value, payload=gpu
    ))
    gpu.utilization_percentage = 91.0
    record_event(Topic.GPU_METRICS, GpuMetricMessage(
        event_type=LifecycleEventType.GPU_METRIC.value, payload=gpu
    ))
    
    assert read("videre_gpu_utilization_percent", node_id=gpu.node_id, gpu_id=gpu.id) == 91.0


def test_gpu_health_state_marks_exactly_one_state_active() -> None:
    gpu = sample_gpu()
    gpu.id = "metrics-gpu-health"
    gpu.health_state = GpuHealthState.DEGRADED
    
    record_event(Topic.GPU_METRICS, GpuMetricMessage(
        event_type=EventType.GPU_XID_ERROR.value, payload=gpu
    ))
    
    for state in GpuHealthState:
        expected = 1.0 if state is GpuHealthState.DEGRADED else 0.0
        assert read(
            "videre_gpu_health_state", node_id=gpu.node_id, gpu_id=gpu.id, state=state.value
        ) == expected


def test_gpu_health_state_clears_the_previous_state_on_recovery() -> None:
    gpu = sample_gpu()
    gpu.id = "metrics-gpu-recovery"
    
    gpu.health_state = GpuHealthState.FAILED
    record_event(Topic.GPU_METRICS, GpuMetricMessage(
        event_type=EventType.GPU_DRIVER_CRASH.value, payload=gpu
    ))
    gpu.health_state = GpuHealthState.HEALTHY
    record_event(Topic.GPU_METRICS, GpuMetricMessage(
        event_type=LifecycleEventType.GPU_RECOVERED.value, payload=gpu
    ))
    
    labels = {"node_id": gpu.node_id, "gpu_id": gpu.id}
    assert read("videre_gpu_health_state", **labels, state=GpuHealthState.FAILED.value) == 0.0
    assert read("videre_gpu_health_state", **labels, state=GpuHealthState.HEALTHY.value) == 1.0


# --- Node telemetry gauges ---


def test_node_health_state_marks_exactly_one_state_active() -> None:
    node = sample_node(NodeHealthState.DRAINING)
    node.id = "metrics-node-health"
    
    record_event(Topic.NODE_EVENTS, NodeEventMessage(
        event_type=EventType.NODE_DRAINED.value, payload=node
    ))
    
    for state in NodeHealthState:
        expected = 1.0 if state is NodeHealthState.DRAINING else 0.0
        assert read("videre_node_health_state", node_id=node.id, state=state.value) == expected


def test_node_health_state_clears_the_previous_state_on_recovery() -> None:
    node = sample_node(NodeHealthState.NOT_READY)
    node.id = "metrics-node-recovery"
    
    record_event(Topic.NODE_EVENTS, NodeEventMessage(
        event_type=EventType.NODE_KUBELET_DOWN.value, payload=node
    ))
    node.health_state = NodeHealthState.READY
    record_event(Topic.NODE_EVENTS, NodeEventMessage(
        event_type=LifecycleEventType.NODE_RECOVERED.value, payload=node
    ))
    
    assert read("videre_node_health_state", node_id=node.id, state=NodeHealthState.NOT_READY.value) == 0.0
    assert read("videre_node_health_state", node_id=node.id, state=NodeHealthState.READY.value) == 1.0


# --- Counters ---


def test_gpu_error_event_increments_the_error_counter() -> None:
    gpu = sample_gpu()
    gpu.id = "metrics-gpu-errors"
    labels = {"node_id": gpu.node_id, "gpu_id": gpu.id, "error_type": EventType.GPU_XID_ERROR.value}
    before = read("videre_gpu_error_events_total", **labels)
    
    record_event(Topic.GPU_METRICS, GpuMetricMessage(
        event_type=EventType.GPU_XID_ERROR.value, payload=gpu
    ))
    
    assert read("videre_gpu_error_events_total", **labels) == before + 1.0


def test_routine_gpu_telemetry_does_not_increment_the_error_counter() -> None:
    gpu = sample_gpu()
    gpu.id = "metrics-gpu-no-error"
    labels = {"node_id": gpu.node_id, "gpu_id": gpu.id, "error_type": LifecycleEventType.GPU_METRIC.value}
    
    record_event(Topic.GPU_METRICS, GpuMetricMessage(
        event_type=LifecycleEventType.GPU_METRIC.value, payload=gpu
    ))
    
    assert REGISTRY.get_sample_value("videre_gpu_error_events_total", labels) is None


def test_node_failure_event_increments_the_node_failure_counter() -> None:
    node = sample_node(NodeHealthState.NOT_READY)
    node.id = "metrics-node-failures"
    labels = {"node_id": node.id, "failure_mode": EventType.NODE_DISK_PRESSURE.value}
    before = read("videre_node_failure_events_total", **labels)
    
    record_event(Topic.NODE_EVENTS, NodeEventMessage(
        event_type=EventType.NODE_DISK_PRESSURE.value, payload=node
    ))
    
    assert read("videre_node_failure_events_total", **labels) == before + 1.0


def test_job_completion_increments_only_the_completion_counter() -> None:
    completions_before = read("videre_job_completions_total")
    failures_before = read("videre_job_failures_total", failure_mode=EventType.JOB_OOM_KILL.value)
    
    record_event(Topic.JOB_EVENTS, JobEventMessage(
        event_type=LifecycleEventType.JOB_COMPLETED.value, payload=sample_job(JobState.COMPLETED)
    ))
    
    assert read("videre_job_completions_total") == completions_before + 1.0
    assert read("videre_job_failures_total", failure_mode=EventType.JOB_OOM_KILL.value) == failures_before


def test_job_failure_increments_its_own_failure_mode_only() -> None:
    before = read("videre_job_failures_total", failure_mode=EventType.JOB_NCCL_TIMEOUT.value)
    other_before = read("videre_job_failures_total", failure_mode=EventType.JOB_PREEMPTED.value)
    
    record_event(Topic.JOB_EVENTS, JobEventMessage(
        event_type=EventType.JOB_NCCL_TIMEOUT.value, payload=sample_job(JobState.FAILED)
    ))
    
    assert read("videre_job_failures_total", failure_mode=EventType.JOB_NCCL_TIMEOUT.value) == before + 1.0
    assert read("videre_job_failures_total", failure_mode=EventType.JOB_PREEMPTED.value) == other_before


def test_capacity_event_increments_the_capacity_counter() -> None:
    before = read("videre_capacity_events_total", event_type=EventType.CAPACITY_FRAGMENTATION.value)
    scheduler_event = SchedulerEvent(
        id="metrics-scheduler-1",
        type=SchedulerEventType.QUEUEING_DELAY,
        node_id="metrics-node-capacity",
        delay_seconds=45.0,
        reason="resource fragmentation delayed placement",
    )
    
    record_event(Topic.SCHEDULER_EVENTS, SchedulerEventMessage(
        event_type=EventType.CAPACITY_FRAGMENTATION.value, payload=scheduler_event
    ))
    
    assert read(
        "videre_capacity_events_total", event_type=EventType.CAPACITY_FRAGMENTATION.value
    ) == before + 1.0


def test_no_counter_is_labelled_by_an_unbounded_field() -> None:
    unbounded = {"job_id", "event_id", "correlation_id", "timestamp", "reason"}
    for name in (
        "videre_gpu_error_events_total",
        "videre_node_failure_events_total",
        "videre_job_failures_total",
        "videre_capacity_events_total",
    ):
        collector = REGISTRY._names_to_collectors[name]
        assert not unbounded & set(collector._labelnames)


# --- Cluster snapshot rollups ---


def test_snapshot_gauges_report_job_counts_and_zero_absent_states() -> None:
    snapshot = ClusterHealthSnapshot(
        cluster_id="metrics-cluster",
        cluster_name="metrics-cluster",
        jobs_by_lifecycle_state={JobState.RUNNING.value: 7, JobState.PENDING.value: 2},
        unresolved_failure_count=4,
    )
    
    record_cluster_snapshots([snapshot])
    
    assert read("videre_jobs_by_state", cluster_id="metrics-cluster", state=JobState.RUNNING.value) == 7.0
    assert read("videre_jobs_by_state", cluster_id="metrics-cluster", state=JobState.PENDING.value) == 2.0
    assert read("videre_jobs_by_state", cluster_id="metrics-cluster", state=JobState.FAILED.value) == 0.0
    assert read("videre_jobs_by_state", cluster_id="metrics-cluster", state=JobState.COMPLETED.value) == 0.0
    assert read("videre_unresolved_failures") == 4.0


def test_snapshot_gauges_drop_a_state_back_to_zero_when_it_empties() -> None:
    full = ClusterHealthSnapshot(
        cluster_id="metrics-cluster-drain",
        cluster_name="metrics-cluster-drain",
        jobs_by_lifecycle_state={JobState.RUNNING.value: 3},
    )
    empty = ClusterHealthSnapshot(
        cluster_id="metrics-cluster-drain",
        cluster_name="metrics-cluster-drain",
        jobs_by_lifecycle_state={},
    )
    
    record_cluster_snapshots([full])
    record_cluster_snapshots([empty])
    
    assert read("videre_jobs_by_state", cluster_id="metrics-cluster-drain", state=JobState.RUNNING.value) == 0.0


def test_recording_no_snapshots_leaves_the_unresolved_gauge_untouched() -> None:
    record_cluster_snapshots([
        ClusterHealthSnapshot(cluster_id="metrics-cluster-keep", cluster_name="k", unresolved_failure_count=9)
    ])
    record_cluster_snapshots([])
    
    assert read("videre_unresolved_failures") == 9.0


# --- The /metrics endpoint ---


def test_metrics_endpoint_returns_prometheus_exposition_format() -> None:
    with build_client() as client:
        response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "# TYPE videre_gpu_utilization_percent gauge" in response.text
    assert "# TYPE videre_job_completions_total counter" in response.text


def test_metrics_endpoint_declares_the_http_service_metrics() -> None:
    with build_client() as client:
        response = client.get("/metrics")

    assert "# TYPE http_requests_total counter" in response.text
    assert "# TYPE http_request_duration_seconds histogram" in response.text


def test_process_and_runtime_metrics_are_exposed() -> None:
    with build_client() as client:
        response = client.get("/metrics")

    assert "process_resident_memory_bytes" in response.text
    assert "python_gc_objects_collected_total" in response.text


# --- HTTP service metrics, against an isolated registry ---


def test_requests_are_counted_by_route_template_and_exact_status() -> None:
    client, registry = build_isolated_client()
    client.get("/nodes/node-0")
    client.get("/nodes/node-1")

    assert registry.get_sample_value(
        "http_requests_total", {"handler": "/nodes/{node_id}", "method": "GET", "status": "200"}
    ) == 2.0
    assert registry.get_sample_value(
        "http_requests_total", {"handler": "/nodes/{node_id}", "method": "GET", "status": "2xx"}
    ) is None


def test_latency_is_recorded_per_route() -> None:
    client, registry = build_isolated_client()
    client.get("/nodes/node-0")

    assert registry.get_sample_value(
        "http_request_duration_seconds_count", {"handler": "/nodes/{node_id}", "method": "GET"}
    ) == 1.0


def test_untemplated_paths_are_grouped_to_bound_cardinality() -> None:
    client, registry = build_isolated_client()
    client.get("/wp-login.php")
    client.get("/.env")

    assert registry.get_sample_value(
        "http_requests_total", {"handler": "none", "method": "GET", "status": "404"}
    ) == 2.0
    assert registry.get_sample_value(
        "http_requests_total", {"handler": "/wp-login.php", "method": "GET", "status": "404"}
    ) is None


def test_probe_and_scrape_traffic_is_excluded_from_http_metrics() -> None:
    client, registry = build_isolated_client()
    client.get("/healthz")
    client.get("/metrics")
    client.get("/metrics")

    assert registry.get_sample_value(
        "http_requests_total", {"handler": "/healthz", "method": "GET", "status": "200"}
    ) is None
    assert registry.get_sample_value(
        "http_requests_total", {"handler": "/metrics", "method": "GET", "status": "200"}
    ) is None
