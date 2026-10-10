# Architecture and domain diagrams

Each diagram shows a different part of Videre's current implementation.

## C4 Diagram

The dashboard shows simulated nodes, GPUs, and jobs, while the application and small CPU-only job containers run on one real Kubernetes node in WSL2. Browser requests pass through Tailscale Funnel and Traefik to the frontend, backend, or Grafana. The backend reads simulator events from Kafka, saves records in PostgreSQL, and uses Redis for cached data and request limits. Prometheus collects metrics, Loki stores logs collected by Alloy, and Grafana displays both.

![C4 Diagram](C4%20Diagram.png)

## AI Diagnosis Sequence Diagram

For an AI diagnosis, the backend looks up the selected node, GPU, or job and checks for a cached answer matching its health, placement, and failure details. If no answer matches, it checks request limits and gathers database records, metrics, and logs. Gemini uses this evidence to suggest a likely cause and next steps, with missing information marked in its input. Successful answers are cached for seven minutes by default, and cached answers do not count toward AI request limits.

![AI Diagnosis Sequence Diagram](AI%20Diagnosis%20Sequence%20Diagram.png)

## Telemetry Activity Diagram

The backend checks Kafka messages one at a time and skips malformed messages or messages from outdated or conflicting simulation runs. For accepted messages, it saves database changes, updates metrics, and then saves its reading position in Kafka. After an error, it reconnects and resumes from the last saved position, or the oldest retained message if no saved position is valid. A message may be processed again: event IDs prevent duplicate history records, but metrics can be counted again.

![Telemetry Activity Diagram](Telemetry%20Activity%20Diagram.png)

## Job Lifecycle State Machine

Jobs move from `PENDING` to `RUNNING` when a simulated node is ready, then to `COMPLETED` or `FAILED`. Some simulated incidents end a job; slowness and damaged checkpoints leave it running. A new simulation run marks unfinished jobs from the previous run as failed in the database. These states follow the simulation even if creating a real job container fails.

![Job Lifecycle State Machine](Job%20Lifecycle%20State%20Machine.png)

## Entity-Relationship Diagram

This diagram shows how PostgreSQL stores cluster data and history. Clusters contain nodes and jobs, nodes contain GPUs, and the assignment table links jobs to nodes rather than individual GPUs. Scheduler events record scheduling activity, while failure records describe incidents and group related failures using a shared ID. A primary key identifies a record; a foreign key links it to another table, and the line symbols show how many records can be linked.

![Entity-Relationship Diagram](Videre%20ERD.png)

## Domain Class Diagram

This diagram shows the simulator's main objects and their responsibilities. `ClusterState` holds the simulated clusters, nodes, GPUs, and jobs, while `Simulator` coordinates each update. `JobLifecycle` creates and advances jobs, and `CorrelationEngine` schedules failures that can trigger other failures. The optional `Materializer` creates real CPU-only job containers and signals their outcomes; requested resources describe simulated jobs rather than reserved hardware.

![Domain Class Diagram](Videre%20Domain%20Class%20Diagram.png)
