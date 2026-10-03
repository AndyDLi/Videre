# Prometheus Metrics

The backend exposes `/metrics` on port 8000. Prometheus periodically uses the Kubernetes network (via the in-cluster `backend` Service) to scrape metrics from it. Continuous numeric telemetry lives here, while structured records (failure records, scheduler events, job rows) stay in Postgres.

Values come from two writers inside the backend process:

- The Kafka consumer, strictly after each event's Postgres transaction commits.
- The cache-refresh loop for cluster-wide aggregations.

Kafka offset commits follow metric updates. If persistence succeeds but the offset commit fails, reconnecting can replay that event and increment its counters again even when Postgres suppresses duplicate domain rows. Counters therefore reflect processing, including replays, rather than exactly-once event counts. Valid bookmarks limit replay to uncommitted records; a missing or invalid bookmark uses `earliest` and may repeat increments across the retained three-day history.

## Domain Metrics

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `videre_gpu_utilization_percent` | Gauge | `node_id`, `gpu_id` | Current GPU utilization, 0-100 |
| `videre_gpu_temperature_celsius` | Gauge | `node_id`, `gpu_id` | Current GPU temperature |
| `videre_gpu_memory_used_bytes` | Gauge | `node_id`, `gpu_id` | GPU memory in use |
| `videre_gpu_memory_total_bytes` | Gauge | `node_id`, `gpu_id` | Total GPU memory, constant per GPU |
| `videre_gpu_health_state` | Gauge | `node_id`, `gpu_id`, `state` | 1 on the active state, 0 elsewhere |
| `videre_node_health_state` | Gauge | `node_id`, `state` | 1 on the active state, 0 elsewhere |
| `videre_jobs_by_state` | Gauge | `cluster_id`, `state` | Jobs currently in each lifecycle state |
| `videre_unresolved_failures` | Gauge | — | Failure records with no `resolved_at` |
| `videre_job_completions_total` | Counter | — | Jobs that reached COMPLETED |
| `videre_job_failures_total` | Counter | `failure_mode` | Job-level failure events |
| `videre_gpu_error_events_total` | Counter | `node_id`, `gpu_id`, `error_type` | GPU error events |
| `videre_node_failure_events_total` | Counter | `node_id`, `failure_mode` | Node-level failure events |
| `videre_capacity_events_total` | Counter | `event_type` | Capacity-loss events |

- `state` values are the `NodeHealthState`, `GpuHealthState`, and `JobState` enums.
- `failure_mode`, `error_type`, and `event_type` values are `EventType` members and are grouped by the topic they arrive on:

| Group | Event types |
|---|---|
| node | `node.kubelet_down`, `node.untolerated_taint`, `node.image_pull_failure`, `node.cni_failure`, `node.disk_pressure`, `node.drained`, `node.health_check_removed` |
| gpu | `gpu.thermal_throttling`, `gpu.ecc_uncorrectable`, `gpu.xid_error`, `gpu.nvlink_degraded`, `gpu.driver_crash` |
| job | `job.oom_kill`, `job.nccl_timeout`, `job.straggler`, `job.checkpoint_corrupt`, `job.preempted` |
| capacity | `capacity.fragmentation`, `capacity.reserved_idle` |

## HTTP Service Metrics

The FastAPI instrumentator automatically tracks API request count, duration, and request/response size by route, HTTP method, and exact status code. `/healthz` and `/metrics` are excluded from API request metrics because health probes and Prometheus scrapes are internal traffic, not real API usage.
