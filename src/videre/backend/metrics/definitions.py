"""
Prometheus metric definition for simulated cluster telemetry data.
"""

from prometheus_client import Counter, Gauge

BYTES_PER_MEGABYTE = 1024 * 1024

CLUSTER_ID = "cluster_id"
NODE_ID = "node_id"
GPU_ID = "gpu_id"
STATE = "state"


# Per-GPU telemetry metrics

GPU_UTILIZATION = Gauge(
    "videre_gpu_utilization_percent",
    "Current GPU utilization, 0-100.",
    [NODE_ID, GPU_ID],
)

GPU_TEMPERATURE = Gauge(
    "videre_gpu_temperature_celsius",
    "Current GPU temperature in degrees Celsius.",
    [NODE_ID, GPU_ID],
)

GPU_MEMORY_USED = Gauge(
    "videre_gpu_memory_used_bytes",
    "GPU memory currently in use, in bytes.",
    [NODE_ID, GPU_ID],
)

GPU_MEMORY_TOTAL = Gauge(
    "videre_gpu_memory_total_bytes",
    "Total GPU memory, in bytes.",
    [NODE_ID, GPU_ID],
)


# Health states

GPU_HEALTH_STATE = Gauge(
    "videre_gpu_health_state",
    "1 for the GPU's current health state, 0 for every other state.",
    [NODE_ID, GPU_ID, STATE],
)

NODE_HEALTH_STATE = Gauge(
    "videre_node_health_state",
    "1 for the node's current health state, 0 for every other state.",
    [NODE_ID, STATE],
)


# Cumulative domain events

JOB_COMPLETIONS = Counter(
    "videre_job_completions_total",
    "Jobs that reached the COMPLETED state.",
)

JOB_FAILURES = Counter(
    "videre_job_failures_total",
    "Job-level failure-mode events, by failure mode.",
    ["failure_mode"],
)

GPU_ERROR_EVENTS = Counter(
    "videre_gpu_error_events_total",
    "GPU error events, by error type.",
    [NODE_ID, GPU_ID, "error_type"],
)

NODE_FAILURE_EVENTS = Counter(
    "videre_node_failure_events_total",
    "Node-level failure events, by failure mode.",
    [NODE_ID, "failure_mode"],
)

CAPACITY_EVENTS = Counter(
    "videre_capacity_events_total",
    "Capacity-loss events reported on the scheduler-events topic, by event type.",
    ["event_type"],
)


# Cluster-level cached rollups

JOBS_BY_STATE = Gauge(
    "videre_jobs_by_state",
    "Jobs currently in each lifecycle state.",
    [CLUSTER_ID, STATE],
)

UNRESOLVED_FAILURES = Gauge(
    "videre_unresolved_failures",
    "Failure records with no resolved_at timestamp, across the whole deployment.",
)
