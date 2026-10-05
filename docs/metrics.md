# Prometheus Metrics

The backend exposes `/metrics` on port 8000. Prometheus periodically uses the Kubernetes network (via the in-cluster `backend` Service) to scrape metrics from it. Continuous numeric telemetry lives here, while structured records (failure records, scheduler events, job rows) stay in Postgres.

Values come from two writers inside the backend process:

- The Kafka consumer, strictly after each event's Postgres transaction commits.
- The cache-refresh loop for cluster-wide aggregations.

Kafka offset commits follow metric updates. If persistence succeeds but the offset commit fails, reconnecting can replay that event and increment its counters again even when Postgres suppresses duplicate domain rows. Counters therefore reflect processing, including replays, rather than exactly-once event counts. Valid bookmarks limit replay to uncommitted records; a missing or invalid bookmark uses `earliest` and may repeat increments across the retained three-day history.

Events rejected as stale, legacy-after-boundary, or conflicting runs update no metrics. Run resets appear in job/incident aggregates after the next cache refresh; node/GPU gauges and measured telemetry follow normal per-entity snapshots.

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
| `videre_capacity_events_total` | Counter | `event_type` | Processed capacity-scenario events |

- `state` values are the `NodeHealthState`, `GpuHealthState`, and `JobState` enums.
- `failure_mode`, `error_type`, and `event_type` values are `EventType` members and are grouped by the topic they arrive on:

| Group | Event types |
|---|---|
| node | `node.kubelet_down`, `node.untolerated_taint`, `node.image_pull_failure`, `node.cni_failure`, `node.disk_pressure`, `node.drained`, `node.health_check_removed` |
| gpu | `gpu.thermal_throttling`, `gpu.ecc_uncorrectable`, `gpu.xid_error`, `gpu.nvlink_degraded`, `gpu.driver_crash` |
| job | `job.oom_kill`, `job.nccl_timeout`, `job.straggler`, `job.checkpoint_corrupt`, `job.preempted` |
| capacity | `capacity.fragmentation`, `capacity.reserved_idle` |

## GPU Availability and Capacity Counts

`GET /capacity` classifies each tracked GPU once, using its last-reported node health, GPU health and utilization:

| Category | Rule, in precedence order |
|---|---|
| Unavailable for new work | Node is NOT_READY, DRAINING or CORDONED, or GPU is FAILED. |
| Degraded | READY node and DEGRADED or THROTTLING GPU, at any utilization. |
| Healthy idle | READY node and HEALTHY GPU below 5% utilization. |
| Healthy active | READY node and HEALTHY GPU at least 5% utilized. |

`unavailable_gpus + degraded_gpus + idle_gpus + active_gpus = total_gpus` per cluster. CORDONED nodes can still run existing work. These observations do not guarantee placement or fresh telemetry. Raw GPU-health snapshots remain a separate view. Node-level job assignments provide no per-GPU allocation or reservation evidence.

`queued_job_count`, `drained_node_count` and `unschedulable_node_count` count current PENDING jobs, DRAINING nodes and CORDONED nodes. `queueing_delay_event_count` counts stored QUEUEING_DELAY records linked to a node in that cluster, from the inclusive rolling three-day cutoff through the captured current time; future records are excluded. Repeated delays on one node count separately. This is neither a distinct entity count nor proof of fragmentation or capacity lost.

The deprecated wire aliases `idle_reserved_gpus` and `fragmentation_event_count` equal `idle_gpus` and `queueing_delay_event_count`, respectively, for older clients. Their names do not establish reservations or fragmentation. The legacy `capacity.reserved_idle` event identifier represents a simulated scenario; it still emits PLACEMENT with reason `simulated idle-capacity signal`, without tracked reservation state.

Grafana's GPU count below 5% uses measured utilization alone; it does not establish health, new-work availability or reservations. Historical failure/error/capacity charts use Prometheus processing-counter increases over the selected range, with three-day history retention and possible replay increments. They do not count unique GPUs/jobs or lost capacity. The events-per-minute chart uses a ten-minute rate window. Keep those historical counts separate from current-state counts and the API's node-linked stored delay records.

## HTTP Service Metrics

The FastAPI instrumentator automatically tracks API request count, duration, and request/response size by route, HTTP method, and exact status code. `/healthz` and `/metrics` are excluded from API request metrics because health probes and Prometheus scrapes are internal traffic, not real API usage.
