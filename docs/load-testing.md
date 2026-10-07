# Request benchmark

Measure successful requests per second within fixed latency targets, plus PostgreSQL demand, AI response-cache behavior and CPU/memory usage. Run manually against an explicitly selected private environment; this workload is outside GitHub Actions.

## Workload and measurements

Each iteration makes one HTTP request. A fixed arrival rate distributes traffic equally across `GET /capacity`, `GET /nodes?limit=50&offset=0`, `GET /jobs?limit=10&offset=0`, `GET /nodes/{id}` and cached `POST /ai/analyze`. IDs are selected before the run; response bodies and cache hits are checked. k6 may schedule one request more or fewer at the time boundary; all actual requests must still complete successfully, with no dropped arrivals. There are no WebSocket connections, ingestion requests or model calls.

k6 records offered and successful RPS, errors, dropped iterations, and per-route p50/p95/p99 with sample counts. The recorder samples backend metrics and container resources every five seconds. It saves raw observations, revisions/source hashes, image/resource settings, pool occupancy, query/acquisition timing, cache hits/misses, CPU, memory and throttling. PostgreSQL and Redis measurements describe their work for this API workload, not their standalone maximum throughput.

Database query timing covers cursor execution and fetching through the driver; it excludes acquiring a connection. Acquisition timing includes pool waits, connection creation/health checks and lookup of an already held connection, so it is not pure pool-wait time. Service percentiles are estimates from Prometheus histogram buckets; request percentiles come directly from k6. Pool occupancy and resources are sampled, so brief peaks may be missed. Database totals include the fixture’s normal cache-refresh queries.

AI cache hits still query PostgreSQL for the fingerprint, then read Redis. On a miss, rate limiting precedes additional retrieval and generation. This benchmark requires `from_cache: true` and uses the private fixture below to block external calls; do not direct it at a provider-enabled public deployment. Cache counters describe response-cache lookups, not every Redis operation.

## Private reproducible environment

Run these commands from the repository in WSL/Linux after the normal Python development setup. Docker and the pinned k6 image are the only additional tools. The fixture uses real routes and stores with four nodes, 32 GPUs, 1,000 jobs (24 running, eight pending, 968 completed), one GPU failure and one preloaded analysis. It runs the normal five-second cache refresh; Kafka, retention, Prometheus/Loki retrieval, WebSocket delivery and model generation are excluded. PostgreSQL data uses tmpfs and Redis persistence is disabled, so these runs do not measure disk-bound production storage. It exposes only loopback ports and refuses default production store addresses. Requests use direct HTTP, excluding Traefik, TLS, Funnel and browser rendering.

Use the backend runtime image recorded in the baseline results, or build the repository Dockerfile and record the resulting image. Source is mounted read-only; the report records its digest separately from the runtime image. These are disposable resources with test-only credentials.

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

If native k6 is unavailable, copy the binary from the pinned Docker image; no host package installation is needed:

```bash
mkdir -p tasks/load-tests
docker create --name videre-k6-tool grafana/k6@sha256:98305727d160c065e1da695619c40ea4becbc3e116a3842da2d6027970e428c2
docker cp videre-k6-tool:/usr/bin/k6 tasks/load-tests/k6
docker rm videre-k6-tool
tasks/load-tests/k6 version
```

## Run and interpret

Once the private backend is healthy, this one command runs the correctness smoke and collects supporting evidence:

```bash
mkdir -p tasks/load-tests/smoke
.venv/bin/python scripts/record-load.py --api-base-url http://127.0.0.1:18089 --environment private-fixture --containers videre-rps-backend,videre-rps-postgres,videre-rps-redis --node-id node-0 --ai-entity-type node --ai-entity-id node-0 --rps 5 --duration-seconds 10 --output tasks/load-tests/smoke
```

Use a fresh output folder for each run. Record two minutes with `--idle --duration-seconds 120`, then warm the workload separately for 20 seconds before each measured stage. Prime the fixture analysis before warm-up with `docker exec videre-rps-backend python /bench/load_environment.py --prime-cache`; the existing 420-second TTL covers warm-up plus a five-minute run. Keep dataset, cache conditions, resource limits, source and runtime versions fixed.

For the separate warm-up, select the same IDs and save its summary outside the measured run folder:

```bash
mkdir -p tasks/load-tests/warmup
API_BASE_URL=http://127.0.0.1:18089 ENVIRONMENT=private-fixture NODE_ID=node-0 AI_ENTITY_TYPE=node AI_ENTITY_ID=node-0 RPS=5 DURATION_SECONDS=20 SUMMARY_PATH="$PWD/tasks/load-tests/warmup/k6-summary.json" tasks/load-tests/k6 run --quiet scripts/k6-requests.js
```

Run 5 RPS for 300 seconds twice. Freeze common p95/p99 limits, enforced for every route with zero errors, after reviewing that baseline, before increasing the rate; pass them with `--p95-ms` and `--p99-ms`. Increase the offered rate, review each run, narrow between the last pass and first failure, then repeat the passing boundary. The highest confirmed rate applies only to this workload, duration and environment. Longer endurance, other mixes, dataset sizes and external network paths require their own measurements.

`report.json` distinguishes passed, failed, inconclusive and collection failures. Invalid responses, cache misses, errors, dropped arrivals or breached supplied latency thresholds fail the workload. Missing/reset metrics, generator/host saturation and unsafe memory pressure invalidate capacity conclusions; a 90% container memory safeguard stops the run. Capped service CPU throttling is recorded as potential bottleneck evidence rather than discarded. Never classify dropped arrivals alone as a proven backend limit.

Reports include `k6-summary.json`, k6 logs, raw backend metrics, timestamped resource samples and environment metadata. The generator and services share the host; record that contention alongside results. Keep raw reports locally under ignored `tasks/load-tests`; the checked-in result summary and this guide preserve the public benchmark claim.

Cache correctness is verified separately by the existing AI fingerprint/cache tests: ordinary telemetry preserves hits while relevant health/failure changes invalidate them. That supports only the tested cases, not an absolute claim of zero false invalidations. The old 6.5-second real-generation latency is unverified by these cached-only runs and must not be used to claim a new speedup.

## Cleanup and verification

After preserving reports, remove only the disposable benchmark resources:

```bash
docker rm -fv videre-rps-backend videre-rps-postgres videre-rps-redis
docker network rm videre-rps
```

Do not apply migrations, policies or configuration to the production cluster for this benchmark. The added service metrics ship with the next normal backend deployment. Harness tests can run locally with `VIDERE_RUN_K6_TESTS=1 VIDERE_K6_BINARY="$PWD/tasks/load-tests/k6" .venv/bin/pytest tests/test_k6_requests.py`; database integration tests use an explicitly selected disposable database and the application role.

## Recorded baseline — 2026-10-06

Each measured stage lasted five minutes, after a separate 20-second warm-up. Both 5 RPS baselines passed; cached AI median latency was 9.35–9.37 ms, p95 14.45–16.62 ms and p99 18.95–30.64 ms across 600 validated cache hits. Targets were frozen before the ramp: **p95 <100 ms and p99 <250 ms for every route, with zero errors or dropped arrivals**. These are local benchmark targets, not a production SLA.

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

**80 RPS passed twice**, with 48,002 successful requests, zero errors/drops and worst-route p99 of 246.18 and 242.79 ms. **85 RPS failed**, with cached AI p99 of 390.61 ms. The observed boundary is 80–85 RPS at five-RPS resolution, with little p99 headroom; this is not a guaranteed operating limit.

All actual responses were valid; the 160 RPS stage dropped 7,613 arrivals and is inconclusive for capacity. Failed stages achieved their offered rate but breached latency targets. The [result summary](load-testing-results.json) retains every stage, per-route sample counts and percentiles, PostgreSQL/cache measurements, resource observations, revisions, image identities and raw-artifact checksums. Raw reports remain under ignored `tasks/load-tests/rps-verified-*`.

Across the two 80 RPS runs, PostgreSQL recorded about 289 SELECT executions/second including background refresh, mean query duration 0.68–0.69 ms and mean connection acquisition 0.50–0.56 ms. Redis GET mean was 0.61–0.62 ms with 9,600 validated cached AI responses. Backend CPU averaged 0.33 cores; sampled memory maxima across runs were 146 MiB backend, 150 MiB PostgreSQL and 10.5 MiB Redis. Pool occupancy sample maxima differed (one and seven), illustrating why sampled peaks are not exact.

At 120 RPS, backend CPU averaged about 0.48 of its 0.5-core allowance and throttling affected 92.5% of CPU periods; PostgreSQL averaged 0.13 of one core and Redis 0.005 of 0.5 cores. Higher tails coincided with backend throttling and longer connection acquisition. Client-side query and Redis timings include backend scheduling, so these observations do not establish a database-server or pool-configuration defect.

The result applies to the fixed, preloaded, direct-loopback fixture on a shared four-core/8-GiB host. Enforced cache hits do not represent a natural cache hit rate. It excludes live ingestion, AI generation, browser rendering and the public network path; no optimization or cold-to-cached speedup is claimed.
