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

**A full-stack observability platform for simulated GPU training clusters, running lightweight containers on a real Kubernetes node, delivering live telemetry, job outcome tracking, and AI-assisted root-cause analysis.**

[Architecture](#architecture) · [Report Bug](https://github.com/AndyDLi/Videre/issues) · [Request Feature](https://github.com/AndyDLi/Videre/issues)

</div>

---

**Recorded walkthrough**

https://github.com/user-attachments/assets/3e13f436-e406-4b0c-831b-7bae66769ba8

---

## 📋 Table of Contents

- [🧭 What It Does](#what-it-does)
- [🧩 Architecture](#architecture)
- [🛠️ Running It Yourself](#running-it-yourself)
- [🗂️ Repository Layout](#repository-layout)
- [📖 Additional Documentation](#additional-documentation)
- [⚖️ License](#license)
- [👤 Author](#author)

<a id="what-it-does"></a>

## 🧭 What It Does

### 📡 Live Health and Metrics

- **Health updates:** Node, GPU, and job status reaches the dashboard every five seconds by default. The last snapshot is marked **Stale** after 20 seconds without fresh data.
- **GPU measurements:** Utilization, temperature, memory, and error counts update every ten seconds by default.

### 🔗 Failure Simulation and Incidents

- **Failure scenarios:** Nineteen failure modes cover nodes, GPUs, jobs, and capacity, with some occurring more often than others.
- **Related failures:** Seventeen rules link triggers to downstream faults, such as an overheating GPU causing a job timeout. A shared incident ID connects the events.
- **Controlled recovery:** Limits keep one failure from triggering too many events. Unhealthy nodes and GPUs can return to service automatically.

### ⚙️ Real Kubernetes Execution

- **Real Pods:** Scheduled jobs create lightweight Kubernetes Jobs and Pods, labeled with the simulated job and node they represent.
- **Real outcomes:** Pods finish successfully, fail, or exceed their memory limit and are killed. GPU training remains simulated.
- **Restricted access:** The simulator's account can create Jobs, inspect Pods, and run commands inside approved Pods in the `videre` namespace.

### 🔎 Failure and Capacity Analysis

- **Failure records:** Each record includes a category, cause label, and shared incident ID.
- **GPU availability:** Health and utilization group GPUs as unavailable for new work, degraded, healthy idle, or healthy active. Waiting jobs, nodes draining or blocking new work, and recent queueing delays provide separate capacity indicators.
- **Detailed views:** Inspect a node, GPU, or job to see its state, failure history, and performance charts.

### 📊 Metrics and Logs

- **Metrics:** Prometheus reads thirteen domain metrics directly from the backend.
- **Logs:** Alloy collects container logs in Loki; Grafana lets you search by namespace, Pod, container, or application.
- **History:** Prometheus, Loki, Kafka, and PostgreSQL use three-day history retention. Current cluster state and unresolved node/GPU failures are retained.

### 🤖 AI Assistant

- **Suggested causes and next steps:** Gemini compares database state, recent metrics, logs, and related incidents. Missing context is flagged; related failures do not prove a cause or a job's exact GPU assignment.
- **Cached diagnoses:** Answers are reused for up to seven minutes by default. Relevant health, placement, or failure changes stop reuse; routine telemetry updates do not.
- **Request limits:** Per-minute and daily limits apply per client and globally.

<a id="architecture"></a>

## 🧩 Architecture [Diagrams](docs/diagrams/architecture.md)

### C4 Diagram

<a href="docs/diagrams/C4%20Diagram.png"><img src="docs/diagrams/C4%20Diagram.png" alt="C4 Diagram" width="900"></a>

### AI Diagnosis Sequence Diagram

<a href="docs/diagrams/AI%20Diagnosis%20Sequence%20Diagram.png"><img src="docs/diagrams/AI%20Diagnosis%20Sequence%20Diagram.png" alt="AI Diagnosis Sequence Diagram" width="900"></a>

### Telemetry Activity Diagram

<a href="docs/diagrams/Telemetry%20Activity%20Diagram.png"><img src="docs/diagrams/Telemetry%20Activity%20Diagram.png" alt="Telemetry Activity Diagram" width="900"></a>

### Job Lifecycle State Machine

<a href="docs/diagrams/Job%20Lifecycle%20State%20Machine.png"><img src="docs/diagrams/Job%20Lifecycle%20State%20Machine.png" alt="Job Lifecycle State Machine" width="900"></a>

### Entity-Relationship Diagram

<a href="docs/diagrams/Videre%20ERD.png"><img src="docs/diagrams/Videre%20ERD.png" alt="Entity-Relationship Diagram" width="900"></a>

### Domain Class Diagram

<a href="docs/diagrams/Videre%20Domain%20Class%20Diagram.png"><img src="docs/diagrams/Videre%20Domain%20Class%20Diagram.png" alt="Domain Class Diagram" width="900"></a>

<a id="running-it-yourself"></a>

## 🛠️ Running It Yourself

Videre runs on demand. Start it manually; shutting down WSL takes the demo offline. Run commands from the repository root in Ubuntu unless stated otherwise. See [host setup](docs/setup.md) for WSL limits and Tailscale Funnel configuration.

### Prerequisites

- Linux with `systemd`; tested on WSL2 Ubuntu 24.04.
- [k3s](https://k3s.io/), `kubectl`, and administrator cluster access.
- Python 3.12 or later and [uv](https://docs.astral.sh/uv/) for Python development and database setup.
- Node.js 24 for frontend development.
- Tailscale Funnel configured for the public demo and its start script.
- An optional Gemini API key with no billing account attached.

For another host, update the public hostname in `scripts/demo-up.sh`, `k8s/grafana/30-deployment.yaml`, and `k8s/backend/10-configmap.yaml`.

### Local Development

```bash
uv sync                  # install dependencies
uv run ruff check .      # lint
uv run mypy              # strict type-checking
uv run pytest            # unit tests
```

Without `VIDERE_TEST_DATABASE_URL`, database integration tests are skipped. CI prepares disposable PostgreSQL 17.10 and tests as `videre_app`. For local tests, adapt the [migration and account setup](docs/setup.md#database-and-release-operations) to a separate test database. **Never use production:** tests delete rows inside a transaction that is rolled back.

```bash
VIDERE_REQUIRE_DATABASE_TESTS=1 VIDERE_TEST_DATABASE_URL=postgresql+asyncpg://videre_app:test_password@localhost:5432/videre_test uv run pytest
```

For frontend development, keep the local cluster running at `127.0.0.1:80`. The development server forwards `/api` and `/grafana` to Traefik:

```bash
cd frontend && npm ci && npm run dev
```

### Deploying the Full Stack

These steps are for a fresh installation. Start k3s and complete the first checkout and cluster verification block in [database setup](docs/setup.md#fresh-database-installation) before applying anything. Stop if the reviewed source or cluster target is wrong.

#### 1. Create the Namespace and Secrets

```bash
kubectl apply -f k8s/namespace/00-namespace.yaml
```

Create these four Secrets in the `videre` namespace. Keep credentials out of Git. Missing Secrets or keys prevent the affected containers from starting:

| Secret | Keys |
|---|---|
| `postgres-secret` | `POSTGRES_PASSWORD` |
| `postgres-app-secret` | `POSTGRES_APP_USER`, `POSTGRES_APP_PASSWORD` |
| `gemini-secret` | `GEMINI_API_KEY` |
| `grafana-secret` | `admin-password` |

Set `POSTGRES_APP_USER=videre_app`; its password must match the account created in step 3. To disable AI, still create `gemini-secret` with an empty `GEMINI_API_KEY`.

#### 2. Apply Deployment Files

Apply the stack, create Kafka topics, configure Traefik, and pause backend and simulator until the database is ready:

```bash
kubectl apply -k k8s/
kubectl apply -f k8s/kafka/30-topics-job.yaml
kubectl apply -f k8s/traefik/01-helmchartconfig.yaml
kubectl -n videre scale deployment/backend deployment/simulator --replicas=0
```

#### 3. Prepare the Database

Follow [database setup](docs/setup.md#database-and-release-operations) to migrate as `postgres`, create `videre_app` with `scripts/bootstrap-postgres.sql`, and verify schema and permissions before restarting backend and simulator.

CI updates images only. Apply database and configuration changes manually from reviewed source. A successful deployment confirms a release; image tags alone do not. Use the linked guide for updates and recovery instead of reapplying the full stack.

#### 4. Start and Stop the Demo

Start in Ubuntu:

```bash
./scripts/demo-up.sh     # starts k3s, awaits infrastructure, scales simulator, and verifies URL
```

Stop in Ubuntu:

```bash
./scripts/demo-down.sh   # flushes in-flight events, then safely stops k3s
```

Then stop the remaining containers and release WSL memory in **Windows PowerShell**:

```powershell
wsl --shutdown
```

<a id="repository-layout"></a>

## 🗂️ Repository Layout

```
├── src/videre/         # Shared models and Kafka message definitions
│   ├── simulator/      # Failure simulation, measurements, real Kubernetes Jobs
│   ├── backend/        # FastAPI app, Kafka consumer, cache, metrics, AI
│   └── database/       # SQLAlchemy models for Postgres
├── alembic/            # Database migrations
├── frontend/           # Dashboard source and container build
├── k8s/                # Kubernetes manifests (applied via kubectl apply -k)
├── tests/              # Pytest suite for simulator and backend
├── scripts/            # Demo start/stop and CI deploy scripts
└── docs/               # Detailed reference guides
```

<a id="additional-documentation"></a>

## 📖 Additional Documentation

| Document | Covers |
|---|---|
| [Architecture Diagrams](docs/diagrams/architecture.md) | Six diagrams with explanations |
| [docs/setup.md](docs/setup.md) | Host limits, public routing, start/stop, database setup, and release recovery |
| [docs/materialization.md](docs/materialization.md) | Real Pod outcomes and Kubernetes permission limits |
| [docs/kafka-schemas.md](docs/kafka-schemas.md) | Message fields, topics, ordering, and recovery |
| [docs/metrics.md](docs/metrics.md) | Metric names, labels, and capacity counts |
| [docs/load-testing.md](docs/load-testing.md) | Results, conditions, commands, and measurement limits |
| [docs/redis-keys.md](docs/redis-keys.md) | Key formats, expiry, caching, and rate limits |
| [docs/ports.md](docs/ports.md) | Cluster, container, local, and public ports |
| [.github/workflows/self-hosted.md](.github/workflows/self-hosted.md) | Deployment pipeline, permissions, and retry rules |

<a id="license"></a>

## ⚖️ License

Released under the [MIT License](LICENSE).

<a id="author"></a>

## 👤 Author

**Andy Li**

- 🎓 Computer Science Student at Georgia Institute of Technology
- 🔗 LinkedIn: [@andyli8](https://www.linkedin.com/in/andyli8/)
- 💻 GitHub: [@AndyDLi](https://github.com/AndyDLi)
- ✉️ Email: [andy.dang.li@gmail.com](mailto:andy.dang.li@gmail.com)
- 🌐 Portfolio: [andyli-portfolio.vercel.app](https://andyli-portfolio.vercel.app/)

---
