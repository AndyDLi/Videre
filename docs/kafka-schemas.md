# Kafka Message Schemas

The four Kafka topics carry JSON messages, keeping messages easy to inspect and debug.

The Pydantic models in `src/videre/events.py` define the shared wire contract. Both the producer and consumer import these models, preventing schema drift.

## Message Envelope

| Field | Type | Purpose |
|---|---|---|
| `event_id` | UUID string | Unique per message; the consumer's idempotency key. |
| `event_type` | string | Specific event identifier in `"<domain>.<event>"` form, such as `gpu.thermal_throttling`. |
| `schema_version` | int | Version of the message contract, incremented on breaking schema changes. |
| `timestamp` | ISO-8601 UTC | Time the producer created the message. |
| `correlation_id` | UUID string | Identifies a related sequence of events, linking a trigger to the events it causes. |
| `payload` | object | Typed snapshot of the entity associated with the topic. |
| `simulation_run` | object | Immutable `run_id` (UUID), `cluster_id` and `started_at` (UTC) shared by every event from one simulator instance. |

## Topics and Routing

Kafka preserves message order only within a partition. Each topic therefore uses a stable partition key so all events for the same relevant entity are routed to the same partition and retain their relative order.

| Topic | Payload | Partition key | Message type |
|---|---|---|---|
| `node-events` | `Node` | Node ID | `NodeEventMessage` |
| `gpu-metrics` | `GPU` | Node ID | `GpuMetricMessage` |
| `job-events` | `Job` | Job ID | `JobEventMessage` |
| `scheduler-events` | `SchedulerEvent` | Job ID → node ID → event ID | `SchedulerEventMessage` |

## Persistence and Replay

The backend processes records sequentially with automatic offset commits disabled. After an applied event's Postgres transaction succeeds, it updates Prometheus metrics and commits only that record's topic/partition at its next offset (`offset + 1`). A malformed record is rejected with its topic, partition, offset, and validation reason logged before the same explicit skip commit. Valid committed bookmarks take precedence; a missing or invalid bookmark resets to the earliest retained record so uncommitted events can be replayed, which relies on a stable envelope `event_id` value.

With a valid bookmark, failure recovery resumes at the committed offset. Without one, `earliest` can replay already-persisted events from retained history (configured for three days): extra processing and possible repeated metric increments are the cost of preserving uncommitted events. Records deleted by retention cannot be recovered.


## Simulation Run Boundary

A fresh simulator creates one run ID and start time when rebuilding memory. The first consumed event from a newer run, on any topic, atomically advances the cluster's durable boundary, resets node/GPU health, marks old active jobs FAILED with "simulation reset", and resolves superseded incidents. Stored history and assignments remain under existing retention. Repeating the boundary does nothing; restarting only the backend preserves the current run. Older-run events are logged and skipped before state or metric updates, with only their own partition/next offset committed. Previously unseen stale events are not backfilled.
