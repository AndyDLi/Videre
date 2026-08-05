<div align="center">

# 🔭 Videre

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.140-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Kafka](https://img.shields.io/badge/Kafka-4.3-231F20?style=for-the-badge&logo=apachekafka&logoColor=white)](https://kafka.apache.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-17-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Redis](https://img.shields.io/badge/Redis-8-FF4438?style=for-the-badge&logo=redis&logoColor=white)](https://redis.io/)
[![Kubernetes](https://img.shields.io/badge/Kubernetes-k3s-326CE5?style=for-the-badge&logo=kubernetes&logoColor=white)](https://k3s.io/)
[![Prometheus](https://img.shields.io/badge/Prometheus-3-E6522C?style=for-the-badge&logo=prometheus&logoColor=white)](https://prometheus.io/)
[![Grafana](https://img.shields.io/badge/Grafana-12-F46800?style=for-the-badge&logo=grafana&logoColor=white)](https://grafana.com/)
[![Loki](https://img.shields.io/badge/Loki-3-F46800?style=for-the-badge&logo=grafana&logoColor=white)](https://grafana.com/oss/loki/)
[![TypeScript](https://img.shields.io/badge/TypeScript-6-3178C6?style=for-the-badge&logo=typescript&logoColor=white)](https://www.typescriptlang.org/)

[![CI](https://img.shields.io/github/actions/workflow/status/AndyDLi/Videre/ci.yml?branch=main&style=for-the-badge&logo=githubactions&logoColor=white&label=CI)](https://github.com/AndyDLi/Videre/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT-blue?style=for-the-badge)](LICENSE)

**A real-time, full-stack observability platform and operations console for GPU training clusters, serving live telemetry on a real Kubernetes cluster with AI-assisted root-cause analysis.**

[Architecture](#️-architecture) · [Report Bug](https://github.com/AndyDLi/Videre/issues) · [Request Feature](https://github.com/AndyDLi/Videre/issues)

</div>

---



---

## 📋 Table of Contents

- [✨ What It Does](#-what-it-does)
- [🏗️ Architecture](#️-architecture)
- [🚀 Running It Yourself](#-running-it-yourself)
- [📁 Repository Layout](#-repository-layout)
- [📚 Additional Documentation](#-additional-documentation)
- [📜 License](#-license)
- [👤 Author](#-author)

## ✨ What It Does

### 📡 Live Cluster Telemetry

- **Real-Time Health Stream** - Node, GPU, and job states stream over a WebSocket, refreshing from a Redis snapshot every five seconds.
- **Continuous Metrics** - Every GPU reports utilization, temperature, memory, and error counters on a ten-second cadence.
- **Weighted Failure Injection** - Nineteen distinct failure modes span GPU, node, job, and capacity faults with weighted probabilities based on the event rarity.
- **Automatic Recovery** - Unhealthy nodes and GPUs autonomously return to service, allowing the cluster to settle into a degraded steady state rather than cascading to a total outage.

### 🔗 Correlated Failures

- **Cause and Effect** - Seventeen rules link triggers to plausible downstream failures (i.e., a thermal event on a GPU causes an NCCL timeout for that node's job).
- **Global Incident Tracing** - Every event in a failure cascade shares a single correlation ID, allowing reconstruction from any point in the chain.
- **Bounded Cascades** - Strict depth and fan-out limits prevent a single trigger from spiraling into an unrealistic event storm.

### ☸️ Real Kubernetes Execution

- **Materialized Workloads** - Simulated running jbos map directly to real Kubernetes Jobs, labeled to reflect the simulated nodes they represent.
- **Authentic Failure States** - An OOM kill occurs by breaching a container's memory limit, ensuring the kernel records the fault.
- **Least-Privilege Identity** - The simulator's ServiceAccount is strictly scoped, holding only the namespaced Job, Pod, and exec permissions it needs to operate.

### 🔎 Failure and Capacity Analysis

- **Root-Cause Records** - Every recorded failure includes its category, a root-cause tag, and a correlation ID tying it back to the original trigger.
- **Capacity Bottlenecks** - Six distinct metrics expose where usable capacity is lost: unavailable GPUs, reserved-but-idle GPUs, fragmentation delays, queued jobs, and drained or cordoned nodes.
- **Entity Drill-Down** - Any node, GPU, or job can be expanded to reveal its current state, historical failures, and metric trends.

### 📊 Observability Pipeline

- **Metrics Without a Collector** - Thirteen domain metrics are exposed on the backend's own endpoint and scraped directly by Prometheus.
- **Log Aggregation** - Grafana Alloy ships container logs to Loki, queryable by namespace, pod, container, and application.
- **Flat Disk Usage** - A three-day retention window governs Prometheus, Loki, Kafka, and Postgres, so storage plateaus instead of growing.

### 🤖 AI Root-Cause Assistant

- **Three-Source Context** - Database records, metric trends, and recent logs are gathered concurrently. If a data source is slow or missing, it is gracefully dropped and explicitly noted in the prompt.
- **Fingerprint Caching** - AI responses are keyed strictly on stable state attributes, such as entity ID, health state, and unresolved failures, rather than the assembled context that would fold in noisy metric ticks.
- **Layered Quota Guards** - Per-minute and per-day limits, per client and globally, keep a publicly reachable endpoint inside the provider's tier.

## 🏗️ Architecture

### Components

```mermaid
---
config:
  themeVariables:
    fontSize: 20px
  flowchart:
    padding: 22
    nodeSpacing: 50
    rankSpacing: 50
    subGraphTitleMargin:
      top: 20
      bottom: 8
---
flowchart LR
    visitor(["Public Visitor"])

    subgraph windows["Windows 11 Host"]
        subgraph wsl["WSL2 (8 GB / 4 cores)"]
            funnel["Tailscale Funnel<br/>TLS terminates here"]

            subgraph k3s["k3s (videre namespace)"]
                traefik["Traefik"]
                dash["Dashboard"]
                api["Backend API"]
                sim["Simulator"]
                grafana["Grafana"]
                alloy["Alloy"]
                kafka[("Kafka")]
                postgres[("PostgreSQL")]
                redis[("Redis")]
                prometheus[("Prometheus")]
                loki[("Loki")]
            end
        end
    end

    gemini["Google Gemini"]

    visitor -->|HTTPS| funnel
    funnel -->|"HTTP on 80"| traefik
    traefik -->|/| dash
    traefik -->|/api| api
    traefik -->|/grafana| grafana
    sim -->|publishes| kafka
    api -->|consumes| kafka
    api --> postgres
    api --> redis
    api -->|analysis| gemini
    prometheus -->|scrapes| api
    alloy -->|pushes logs| loki
    grafana -->|queries| prometheus
    grafana -->|queries| loki
```

- Everything runs on one machine. A Windows 11 laptop hosts a WSL2 distribution capped at 8 GB and 4 cores, and inside it a single-node k3s cluster runs every component as a Kubernetes workload.
- Public traffic routes exclusively through Tailscale Funnel, which terminates TLS at the host and forwards plain HTTP to Traefik on port 80, so no inbound port is ever opened on the router or on Windows. 
- A single FastAPI application handles REST and WebSocket traffic while concurrently running a Kafka consumer, cache refresh, and retention pruner as background tasks.

### Data Flow

```mermaid
---
config:
  themeVariables:
    fontSize: 20px
  flowchart:
    padding: 22
    nodeSpacing: 50
    rankSpacing: 50
    subGraphTitleMargin:
      top: 20
      bottom: 8
---
flowchart LR
    sim["Simulator<br/>1s tick"]
    k8s["Kubernetes API<br/>real Jobs and Pods"]
    kafka[("Kafka<br/>4 topics, 3-day retention")]
    consumer["Kafka Consumer"]
    postgres[("PostgreSQL")]
    metrics["/metrics"]
    prometheus[("Prometheus")]
    refresh["Cache Refresh<br/>every 5s"]
    redis[("Redis")]
    api["REST + WebSocket"]
    alloy["Alloy"]
    loki[("Loki")]
    ai["AI Assistant"]
    gemini["Gemini"]

    sim -->|"keyed per entity"| kafka
    sim -->|"create Job, exec outcome"| k8s
    kafka --> consumer
    consumer -->|"state and failure records"| postgres
    consumer -->|"gauges and counters"| metrics
    metrics -->|"scrape 15s"| prometheus
    alloy -->|"container logs"| loki

    postgres --> refresh
    refresh -->|"snapshot"| redis
    redis --> api
    postgres --> api

    postgres --> ai
    prometheus --> ai
    loki --> ai
    ai -->|"prompt"| gemini
```

- The simulator publishes to four JSON Kafka topics and maps every simulated job to a real Kubernetes Pod. The backend consumes all four topics, persists current state and failure records to Postgres, and updates Prometheus gauges strictly after the database transaction commits. Concurrently, Alloy streams raw container logs directly to Loki. A background loop aggregates cluster health into a Redis snapshot every seconds seconds and streams it to WebSocket clients.
- Topics are partitioned by a stable routing key, so all events for a specific node or job land in the same partition, guaranteeing they process in a strict sequence. Deduplication is enforced in Postgres, where a single constraint on the envelope's `event_id` ensures that replaying a topic inserts nothing twice, and Kafka offsets commit only after the database transaction succeeds.
- The AI assistant queries all three data stores concurrently. Postgres serves the structured state, Prometheus serves the metrics, and Loki serves the logs, allowing the model to align failure records, metric movement, and container log lines from the same window, tracing cascading symptoms back to their root causes.

## 🚀 Running It Yourself

Videre is available on-demand and started manually. While the machine is on for normal daily use, the stack stays stopped and consumes no resources: k3s does not auto-start, and the WSL VM is not held up. The stack, and its public URL, are up only while a demo is explicitly running (see `docs/setup.md` for more information).

### Prerequisites

- **Linux** with `systemd`, tested on WSL2 Ubuntu 24.04, capped at 8 GB and 4 cores.
- **[k3s](https://k3s.io/)** & `kubectl` for local cluster orchestration.
- **[uv](https://docs.astral.sh/uv/)** for Python dependency management.
- **Node.js 24** to build the dashboard image.
- **Gemini API Key (Optional)** for AI assistant.

### Local Development

```bash
uv sync                  # install dependencies
uv run ruff check .      # lint
uv run mypy              # strict type-checking
uv run pytest            # unit tests
```

*Note*: Database-backed tests skip unless pointed at a live Postgres instance:

```bash
VIDERE_TEST_DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/videre uv run pytest
```

The dev server automatically proxies `/api` and `/grafana` to the live cluster via Traefik.

```bash
cd frontend && npm ci && npm run dev
```

### Deploying the Full Stack

#### 1. Provision Secrets

These four secrets are excluded from Git. Create them manually in your cluster, or the database, backend, and Grafana pods stall in `CreateContainerConfigError`:

| Secret | Keys |
|---|---|
| `postgres-secret` | `POSTGRES_PASSWORD` |
| `postgres-app-secret` | `POSTGRES_APP_USER`, `POSTGRES_APP_PASSWORD` |
| `gemini-secret` | `GEMINI_API_KEY` |
| `grafana-secret` | `admin-password` |

#### 2. Apply Manifests

Deply the core kustomization alongside two one-time bootstrap manifests (for Kafka topic and Traefik configuration):

```bash
kubectl apply -k k8s/
kubectl apply -f k8s/kafka/30-topics-job.yaml
kubectl apply -f k8s/traefik/01-helmchartconfig.yaml
```

#### 3. Apply Schema Migration

```bash
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/videre uv run alembic upgrade head
```

#### 4. Control the Demo

```bash
./scripts/demo-up.sh     # starts k3s, awaits infrastructure, scales simulator, and verifies URL
./scripts/demo-down.sh   # flushes in-flight events, then safely stops k3s
```

## 📁 Repository Layout

```
├── src/videre/         # Shared models and Kafka wire contract
│   ├── simulator/      # Failure engine, telemetry, K8s materialization
│   ├── backend/        # FastAPI app, Kafka consumer, cache, metrics, AI
│   └── database/       # SQLAlchemy models for Postgres
├── alembic/            # Database migrations
├── frontend/           # Dashboard source and container build
├── k8s/                # Kubernetes manifests (applied via kubectl apply -k)
├── tests/              # Pytest suite for simulator and backend
├── scripts/            # Demo start/stop and CI deploy scripts
└── docs/               # Additional operational and design reference
```

## 📚 Additional Documentation

| Document | Covers |
|---|---|
| [docs/setup.md](docs/setup.md) | WSL2 limits, Tailscale routing, and demo lifecycle. |
| [docs/materialization.md](docs/materialization.md) | How simulated jobs translate to real Pods with real kernel-level faults. |
| [docs/kafka-schemas.md](docs/kafka-schemas.md) | Message envelopes, topics, and strict partition keys. |
| [docs/metrics.md](docs/metrics.md) | A complete reference of every metric and its labels. |
| [docs/redis-keys.md](docs/redis-keys.md) | Key namespaces, TTLs, and collision prevention rules. |
| [docs/ports.md](docs/ports.md) | Every internal cluster and external host port mapping. |
| [.github/workflows/self-hosted.md](.github/workflows/self-hosted.md) | Runner rationale and least-privilege permission bounding. |

## 📜 License

Released under the [MIT License](LICENSE).

## 👤 Author

**Andy Li**

- 🎓 Computer Science Student @ Georgia Institute of Technology
- 💼 LinkedIn: [@andyli8](https://www.linkedin.com/in/andyli8/)
- 🐙 GitHub: [@AndyDLi](https://github.com/AndyDLi)
- 📧 Email: andy.dang.li@gmail.com
- 🌐 Portfolio: [andyli-portfolio.vercel.app](https://andyli-portfolio.vercel.app/)

---
