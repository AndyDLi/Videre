# Load Testing

| Offered RPS | Successful RPS | Worst route p95 / p99 (ms) | Result |
|---:|---:|---:|---|
| 5 | 5.00 | 18.4 / 30.6 | passed |
| 5 | 5.00 | 14.4 / 22.2 | passed |
| 10 | 10.00 | 17.7 / 29.0 | passed |
| 20 | 20.00 | 17.4 / 27.0 | passed |
| 40 | 40.00 | 19.3 / 34.9 | passed |
| 80 | 80.00 | 31.4 / 246.2 | passed |
| 160 | 134.62 | 1704.6 / 2393.4 | inconclusive — dropped arrivals |
| 120 | 120.00 | 577.6 / 753.1 | failed |
| 100 | 100.00 | 380.7 / 673.3 | failed |
| 90 | 90.00 | 125.8 / 372.6 | failed |
| 85 | 85.00 | 80.6 / 390.6 | failed |
| 80 (repeat) | 80.00 | 31.3 / 242.8 | passed |

RPS means requests per second. p95/p99 are the response times met by 95%/99% of requests.

**80 RPS is the passing standard for this local, cached-AI test:** five minutes per stage, after a 20-second warm-up. Pass criteria: **p95 <100 ms, p99 <250 ms on every route, zero errors or dropped arrivals**.

## Measurements

The two 80 RPS runs:

| Measurement | Result |
|---|---|
| Successful requests | 48,002; zero errors/drops |
| Worst-route p99 | 246.18 and 242.79 ms |
| PostgreSQL SELECT executions | About 289/second, including background refresh |
| Mean database query time | 0.68–0.69 ms |
| Mean connection acquisition time | 0.50–0.56 ms |
| Mean Redis GET time | 0.61–0.62 ms |
| Validated cached AI responses | 9,600 |
| Average backend CPU | 0.33 cores |
| Highest sampled memory | Backend: 146 MiB; PostgreSQL: 150 MiB; Redis: 10.5 MiB |
| Highest sampled pool occupancy | One and seven connections across the two runs |

Other measurements:

- **5 RPS:** Across 600 cached AI responses, median latency was 9.35–9.37 ms, p95 14.45–16.62 ms, and p99 18.95–30.64 ms.
- **85 RPS:** Cached AI p99 was 390.61 ms. The passing boundary was measured in five-RPS steps.
- **120 RPS:** The backend used 0.48 of its 0.5-core limit; PostgreSQL used 0.13 of 1 core; Redis used 0.005 of 0.5 cores, on average. Backend CPU throttling affected 92.5% of CPU periods.
- **160 RPS:** The test tool could not start 7,613 requests (dropped arrivals), making capacity inconclusive. All actual responses were valid; other failed stages exceeded latency targets.

Slower responses coincided with backend throttling and longer connection acquisition. This does not establish a database or pool defect.

Full measurements, per-route samples, source/image identities, and report checksums: [result summary](load-testing-results.json).

## Test Conditions

One request per iteration, split equally across:

- `GET /capacity`
- `GET /nodes?limit=50&offset=0`
- `GET /jobs?limit=10&offset=0`
- `GET /nodes/{id}`
- Cached `POST /ai/analyze`

| Condition | Setting |
|---|---|
| Dataset | Four nodes, 32 GPUs, one GPU failure, 1,000 jobs: 24 running, eight pending, 968 completed |
| AI cache | One preloaded analysis; every AI response requires `from_cache: true` |
| Host | Shared four-core/8-GiB host; direct local HTTP |
| Storage | PostgreSQL in memory (tmpfs); Redis persistence off |
| Refresh and sampling | Every five seconds |

The test excludes disk-bound storage, Kafka ingestion, retention, WebSockets, model generation, Prometheus/Loki retrieval, Traefik, TLS, Funnel, and browser rendering.

### Measurement Notes

- Request percentiles come from k6; service percentiles are histogram estimates. Sampling can miss brief peaks.
- Query time covers execution/fetching. Connection acquisition includes waits, creation/checks, and held-connection lookup. Both query and Redis timing include backend scheduling.
- Cached AI still queries PostgreSQL before Redis. Cache counters measure response-cache lookups only. These results do not measure natural cache hit rate or either store's maximum throughput.
- AI generation was not tested. The historical 6.5-second figure remains unverified.

## Run the Test

Run from the repository root in WSL/Linux with the Python development environment, Docker, and k6. Use only the private fixture: it exposes loopback ports and blocks external AI calls. Do not change production for this test.

Use the recorded backend runtime image, or record your replacement image and source version.

### Setup

```bash
docker network create videre-rps
docker run -d --name videre-rps-postgres --network videre-rps --cpus 1 --memory 512m --tmpfs /var/lib/postgresql/data:rw -e POSTGRES_USER=benchmark -e POSTGRES_PASSWORD=benchmark -e POSTGRES_DB=benchmark -p 127.0.0.1:55437:5432 postgres:17.10-bookworm
docker run -d --name videre-rps-redis --network videre-rps --cpus 0.5 --memory 256m -p 127.0.0.1:56379:6379 redis:8.8.0-alpine redis-server --save '' --appendonly no
# Wait for pg_isready to succeed before migrating.
docker exec videre-rps-postgres pg_isready -U benchmark -d benchmark
DATABASE_URL=postgresql+asyncpg://benchmark:benchmark@127.0.0.1:55437/benchmark .venv/bin/alembic upgrade head
docker exec -i videre-rps-postgres psql -U benchmark -d benchmark -v ON_ERROR_STOP=1 <<'SQL'
CREATE ROLE videre_app LOGIN PASSWORD 'benchmark' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
GRANT CONNECT ON DATABASE benchmark TO videre_app;
GRANT USAGE ON SCHEMA videre TO videre_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA videre TO videre_app;
ALTER DEFAULT PRIVILEGES FOR ROLE benchmark IN SCHEMA videre GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO videre_app;
SQL
docker run -d --name videre-rps-backend --network videre-rps --cpus 0.5 --memory 384m -p 127.0.0.1:18089:8000 --mount type=bind,src="$PWD/src",dst=/app/src,readonly --mount type=bind,src="$PWD/tests/load_environment.py",dst=/bench/load_environment.py,readonly -e PYTHONPATH=/app/src -e VIDERE_POSTGRES_HOST=videre-rps-postgres -e VIDERE_POSTGRES_DATABASE=benchmark -e VIDERE_POSTGRES_USER=videre_app -e VIDERE_POSTGRES_PASSWORD=benchmark -e VIDERE_REDIS_HOST=videre-rps-redis --entrypoint python ghcr.io/andydli/videre-backend:0.9.0 /bench/load_environment.py
```

If k6 is unavailable:

```bash
mkdir -p tasks/load-tests
docker create --name videre-k6-tool grafana/k6@sha256:98305727d160c065e1da695619c40ea4becbc3e116a3842da2d6027970e428c2
docker cp videre-k6-tool:/usr/bin/k6 tasks/load-tests/k6
docker rm videre-k6-tool
tasks/load-tests/k6 version
```

### Smoke Test

Wait for the backend to be healthy:

```bash
mkdir -p tasks/load-tests/smoke
.venv/bin/python scripts/record-load.py --api-base-url http://127.0.0.1:18089 --environment private-fixture --containers videre-rps-backend,videre-rps-postgres,videre-rps-redis --node-id node-0 --ai-entity-type node --ai-entity-id node-0 --rps 5 --duration-seconds 10 --output tasks/load-tests/smoke
```

### Measured Runs

1. Keep dataset, cache, resource limits, source, runtime, and selected IDs fixed. Use fresh output folders.
2. Record an idle reference: `--idle --duration-seconds 120`.
3. Before each stage, run `docker exec videre-rps-backend python /bench/load_environment.py --prime-cache`. Its 420-second cache lifetime covers warm-up and measurement.
4. Warm up for 20 seconds; save its report separately:

```bash
mkdir -p tasks/load-tests/warmup
API_BASE_URL=http://127.0.0.1:18089 ENVIRONMENT=private-fixture NODE_ID=node-0 AI_ENTITY_TYPE=node AI_ENTITY_ID=node-0 RPS=5 DURATION_SECONDS=20 SUMMARY_PATH="$PWD/tasks/load-tests/warmup/k6-summary.json" tasks/load-tests/k6 run --quiet scripts/k6-requests.js
```

5. Run 5 RPS for 300 seconds twice. Review the baselines; set `--p95-ms` and `--p99-ms` before increasing traffic.
6. Increase traffic, narrow between the last pass and first failure, then repeat the passing rate.

Missing/reset metrics, an overloaded test tool or host, or unsafe memory use make capacity inconclusive. Runs stop at 90% of container memory. Dropped arrivals alone do not prove a backend limit.

Keep `report.json`, `k6-summary.json`, logs, raw metrics, resource samples, and environment metadata under ignored `tasks/load-tests` (`rps-verified-*` for the recorded series). Include shared-host contention.

### Cleanup

Preserve reports, then remove only the test resources:

```bash
docker rm -fv videre-rps-backend videre-rps-postgres videre-rps-redis
docker network rm videre-rps
```

Harness check: `VIDERE_RUN_K6_TESTS=1 VIDERE_K6_BINARY="$PWD/tasks/load-tests/k6" .venv/bin/pytest tests/test_k6_requests.py`. Database tests require a disposable database and the application role.
