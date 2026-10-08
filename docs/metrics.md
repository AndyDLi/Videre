# Prometheus Metrics

Prometheus reads the backend's `/metrics` endpoint on port 8000 through the internal `backend` Service. Detailed job, failure, and scheduling records stay in Postgres.

## Domain Metrics

Gauges show current values. Counters count processed events. Labels identify the entity, state, or event type.

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

Health and job states use `NodeHealthState`, `GpuHealthState`, and `JobState`. Event labels (`failure_mode`, `error_type`, `event_type`) use these groups:

| Group | Event types |
|---|---|
| node | `node.kubelet_down`, `node.untolerated_taint`, `node.image_pull_failure`, `node.cni_failure`, `node.disk_pressure`, `node.drained`, `node.health_check_removed` |
| gpu | `gpu.thermal_throttling`, `gpu.ecc_uncorrectable`, `gpu.xid_error`, `gpu.nvlink_degraded`, `gpu.driver_crash` |
| job | `job.oom_kill`, `job.nccl_timeout`, `job.straggler`, `job.checkpoint_corrupt`, `job.preempted` |
| capacity | `capacity.fragmentation`, `capacity.reserved_idle` |

## Capacity Counts

`GET /capacity` puts each GPU into one category, using its last-reported health and utilization:

| Category | Rule |
|---|---|
| Unavailable for new work | Node is NOT_READY, DRAINING, or CORDONED, or GPU is FAILED |
| Degraded | READY node; DEGRADED or THROTTLING GPU |
| Healthy idle | READY node; HEALTHY GPU below 5% utilization |
| Healthy active | READY node; HEALTHY GPU at least 5% utilized |

`unavailable_gpus + degraded_gpus + idle_gpus + active_gpus = total_gpus` per cluster.

| Field | Counts |
|---|---|
| `queued_job_count` | Current PENDING jobs |
| `drained_node_count` | Current DRAINING nodes |
| `unschedulable_node_count` | Current CORDONED nodes |
| `queueing_delay_event_count` | Node-linked QUEUEING_DELAY records in that cluster during the last three days, including the start and end times |
| `idle_reserved_gpus` | Older name for `idle_gpus`; does not measure reservations |
| `fragmentation_event_count` | Older name for `queueing_delay_event_count`; does not measure fragmentation |

CORDONED nodes may still run existing jobs. Counts may be stale and do not guarantee job placement. Job assignments identify nodes, not individual GPUs.

Future-dated delay records are excluded; repeated delays on one node count separately. `capacity.reserved_idle` reports a simulated PLACEMENT, without tracking reservations.

## Updates and Charts

- The backend saves accepted events to Postgres, updates metrics, then saves its Kafka reading position. Replays count again; a missing or invalid position may replay up to three days of events.
- Rejected events do not update metrics. After simulator resets, job-state and unresolved-failure gauges update at the next cache refresh; node/GPU values follow their next snapshots.
- Grafana's GPU count below 5% uses utilization alone, without checking health, availability for new work, or reservations.
- Historical event charts count processed events, not unique GPUs/jobs or lost capacity. History lasts three days; events per minute is calculated over a ten-minute window.

## HTTP Metrics

API metrics track request count, duration, and request/response size by route, method, and exact status code. `/healthz` and `/metrics` are excluded.
