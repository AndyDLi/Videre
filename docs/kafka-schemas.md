# Kafka Message Schemas

Kafka carries JSON messages for nodes, GPUs, jobs, and scheduling. The sender and backend use the same [message definitions](../src/videre/events.py).

## Message Fields

| Field | Meaning |
|---|---|
| `event_id` | Unique message ID, used to prevent duplicate database records. |
| `event_type` | What happened, such as `gpu.thermal_throttling`. |
| `schema_version` | Message format version. |
| `timestamp` | When the message was created, in UTC. |
| `correlation_id` | Shared ID linking related events. |
| `payload` | Details of the node, GPU, job, or scheduling event. |
| `simulation_run` | Simulator run ID, cluster ID, and UTC start time. |

Version 1 has no `simulation_run`. Version 2 requires it. Other versions are rejected.

## Topics and Ordering

A topic is a message stream. Messages with the same partition key stay in order within that topic.

| Topic | Contains | Partition key |
|---|---|---|
| `node-events` | Node details | Node ID |
| `gpu-metrics` | GPU details | Node ID |
| `job-events` | Job details | Job ID |
| `scheduler-events` | Scheduling decisions | Job ID, otherwise node ID, otherwise event ID |

## Saving and Recovery

- The backend processes messages one at a time. For accepted events, it saves data to Postgres, updates metrics, then saves its reading position in Kafka.
- Invalid messages are logged and skipped.
- After a failure, reading resumes from the saved position. If that position is missing or invalid, reading starts from the oldest retained message.
- Replayed messages keep their original `event_id`, preventing duplicate database records. Metrics may be counted again.
- Kafka keeps three days of messages. Deleted messages cannot be recovered.

## Simulator Restarts

A fresh simulator starts a new run. Its first event resets node and GPU health, marks old active jobs as failed with "simulation reset", and closes old incidents. History follows the existing retention rules.

The reset happens once per run. After a version 2 run is recorded, version 1 events and older or conflicting runs are logged and skipped without changing state or metrics. Restarting only the backend keeps the current run.
