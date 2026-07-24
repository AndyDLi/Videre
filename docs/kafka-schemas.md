# Kafka Message Schemas

The four Kafka topics carry JSON messages. Avro, Protobuf, and a schema registry are unnecessary for this single, small-scale producer; JSON keeps messages easy to inspect and debug.

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

## Topics and Routing

Kafka preserves message order only within a partition. Each topic therefore uses a stable partition key so all events for the same relevant entity are routed to the same partition and retain their relative order.

| Topic | Payload | Partition key | Message type |
|---|---|---|---|
| `node-events` | `Node` | Node ID | `NodeEventMessage` |
| `gpu-metrics` | `GPU` | Node ID | `GpuMetricMessage` |
| `job-events` | `Job` | Job ID | `JobEventMessage` |
| `scheduler-events` | `SchedulerEvent` | Job ID → node ID → event ID | `SchedulerEventMessage` |
