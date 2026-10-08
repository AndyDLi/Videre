# Host Setup

Videre runs on Windows 11 in Ubuntu 24.04 WSL2, limited to 8 GB RAM and four CPU cores. The host has an Intel Core Ultra 7 258V, eight cores, and 32 GB RAM. Tailscale Funnel provides public HTTPS access.

## When the Demo Runs

The demo runs on demand. k3s starts manually. Shutting down WSL stops the workloads and takes the public URL offline; opening Ubuntu starts WSL and Tailscale, but not k3s.

## WSL2 Resource Limits

Save these settings in `C:\Users\andyd\.wslconfig`:

```ini
[wsl2]
memory=8GB
processors=4

[experimental]
autoMemoryReclaim=gradual
sparseVhd=true
```

These limits apply to all WSL2 distributions on this host. Memory is used as needed. `autoMemoryReclaim=gradual` returns cached memory to Windows; `sparseVhd=true` applies to new virtual disks. See [WSL settings](https://learn.microsoft.com/en-us/windows/wsl/wsl-config).

The existing Ubuntu disk was converted with:

```powershell
wsl --shutdown
wsl --manage Ubuntu-24.04 --set-sparse true
```

If WSL refuses sparse conversion, stop rather than adding an unsafe override. After changing `.wslconfig`, run `wsl --shutdown` and reopen Ubuntu. Check the limits with `nproc` and `free -h`; this host reported `4` CPUs, `7.8Gi` RAM, and `2.0Gi` swap.

Disable automatic k3s startup once in Ubuntu:

```bash
sudo systemctl disable k3s
```

## Starting and Stopping the Demo

| Action | Where | Command |
|---|---|---|
| Start | Ubuntu | `cd ~/Videre && ./scripts/demo-up.sh` |
| Stop simulator and k3s | Ubuntu | `cd ~/Videre && ./scripts/demo-down.sh` |
| Stop remaining containers and release memory | Windows PowerShell | `wsl --shutdown` |

Startup checks infrastructure and HTTPS access. Shutdown lets the simulator flush pending Kafka events. **Complete both stop steps:** stopping k3s alone leaves containers running.

## Tailscale and Funnel

Public URL: [ragingasian.tail462d2b.ts.net](https://ragingasian.tail462d2b.ts.net).

1. In Ubuntu, install Tailscale: `curl -fsSL https://tailscale.com/install.sh | sh`.
2. Run `sudo tailscale up` and sign in through the browser.
3. In the admin console, enable MagicDNS and HTTPS Certificates. This host uses `tail462d2b.ts.net`.
4. Allow Funnel in the tailnet access policy:

```jsonc
"nodeAttrs": [
  { "target": ["autogroup:member"], "attr": ["funnel"] },
]
```

5. Forward public HTTPS traffic to Traefik on `127.0.0.1:80`:

```bash
sudo tailscale funnel --bg 80
```

Tailscale handles HTTPS; Traefik routes requests inside Kubernetes. Keep Traefik's HTTPS exposure disabled in `k8s/traefik/01-helmchartconfig.yaml` to avoid claiming port 443.

`--bg` preserves Funnel configuration across restarts. Check it with `tailscale funnel status`; clear it with `sudo tailscale funnel reset`. See [Funnel commands](https://tailscale.com/docs/reference/tailscale-cli/funnel).

## Resource Use

Recorded usage, with configured limits and capacity:

### Memory

| Component | Recorded Value | Limit / Capacity |
|---|---|---|
| WSL2 VM (Stack Running) | 3.8 Gi | 7.8 Gi |
| WSL2 VM (k3s stopped, WSL running) | 1.4 Gi | 7.8 Gi |
| Namespace Requests | 2352 Mi | 5 Gi |
| Namespace Limits | 5088 Mi | 6500 Mi |
| Videre Pods | 1440 Mi | Not Enforced |
| Per-Container Max | — | 3 Gi |

### CPU

| Component | Recorded Value | Limit / Capacity |
|---|---|---|
| WSL2 VM | — | 4 Cores |
| Namespace Requests | 1185m | 3 Cores |
| Namespace CPU Limit | — | Not Configured |
| Videre Pods | 171m | Not Enforced |
| Per-Container Max | — | 4 Cores |

CPU `1000m` equals one core. Requests reserve capacity for scheduling; quotas cap declared allocations. Running usage is limited per container, with no combined CPU limit for the namespace.

### Storage

| Component | Recorded Value | Limit / Capacity |
|---|---|---|
| Total Videre Footprint | 7.2G | ~20 GB Project Budget |
| Namespace Claims | 14Gi | 16Gi |
| PVC Count | 5 Volumes | 10 Volumes |
| Prometheus TSDB | 262M | 4Gi |
| Kafka Logs | 146M | 4Gi |
| Postgres Data | 121M | 2Gi |
| Grafana Database | 49M | 1Gi |
| Loki Chunks & Index | 5M | 3Gi |
| containerd Image Store | 5.6G | Not Enforced |

PVC sizes are requested capacity. The ~20 GB project budget is not an enforced disk quota.

## Deployment Permissions

CI's `videre-deployer` account can update images for `backend`, `frontend`, and `simulator`, read Deployments, and list Pods. It cannot read Secrets, change other Deployments, install access rules, or run commands inside Pods. See [simulator permissions](materialization.md#permissions-and-limits).

Four admission policies in `k8s/namespace/30-admission.yaml` check identities and resource names, denying requests if validation fails. Labels do not grant access. Only `system:serviceaccount:kube-system:job-controller` may create Pods whose names start with `sim-job-`; changing that identity requires a reviewed policy update.

## Database and Release Operations

CI prepares a disposable PostgreSQL 17.10 database and tests as `videre_app`. Local tests need a separate prepared database; never use production. Required tests fail without a database URL.

**CI updates images only.** Apply database, Secret, and ConfigMap changes manually from the reviewed checkout. The app role cannot change the schema; backend images contain no Alembic files. `/healthz` checks connectivity only.

### Fresh Database Installation

Use the reviewed code checkout and an administrator kubeconfig (cluster access file). Verify the full commit SHA and cluster target:

```bash
read -r -p 'Reviewed checkout SHA: ' release_source
[[ "$release_source" =~ ^[0-9a-f]{40}$ ]] && [ "$(git rev-parse HEAD)" = "$release_source" ] || exit 1
export KUBECONFIG="$HOME/.kube/config"
kubectl config current-context
kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}{"\n"}'
```

**Stop if the checkout or cluster is wrong.** Create the four Secrets and apply the stack using [README deployment steps](../README.md#deploying-the-full-stack). Pause backend and simulator, then forward PostgreSQL:

```bash
kubectl -n videre scale deployment/backend deployment/simulator --replicas=0
kubectl -n videre rollout status deployment/postgres --timeout=180s
kubectl -n videre port-forward service/postgres 15432:5432
```

Leave that terminal open. In a second Ubuntu terminal, use the same reviewed checkout and administrator kubeconfig. Enter the admin SQLAlchemy URL for user `postgres`, host `127.0.0.1:15432`, database `videre`, and the administrator password:

```bash
read -rs -p 'Admin DATABASE_URL: ' DATABASE_URL; printf '\n'
export DATABASE_URL
uv sync --locked --all-extras
uv run alembic upgrade 8d7e3a9164b2
uv run alembic current --check-heads
unset DATABASE_URL
```

Target: `8d7e3a9164b2`. Do not use an unchecked `head` in production.

Create the app's database account **only on a fresh database without `videre_app`**:

```bash
kubectl -n videre exec -i deployment/postgres -- \
  psql -X -U postgres -d videre -v database_name=videre < scripts/bootstrap-postgres.sql
kubectl -n videre exec -it deployment/postgres -- \
  psql -X -U postgres -d videre -c '\password videre_app'
```

Match the password to `postgres-app-secret` for user `videre_app`. Keep passwords out of Git, SQL files, and command arguments. Future-table grants apply to tables created by `postgres`; recheck them if the migration owner changes.

Check schema and app access:

```bash
kubectl -n videre exec -i deployment/postgres -- psql -X -v ON_ERROR_STOP=1 -U postgres -d videre <<'SQL'
SELECT version_num FROM public.alembic_version;
SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls
FROM pg_roles WHERE rolname = 'videre_app';
SELECT has_schema_privilege('videre_app', 'videre', 'USAGE') AS usage,
       has_schema_privilege('videre_app', 'videre', 'CREATE') AS create;
SELECT c.relname, p.privilege,
       has_table_privilege('videre_app', c.oid, p.privilege) AS allowed
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
CROSS JOIN (VALUES ('SELECT'), ('INSERT'), ('UPDATE'), ('DELETE')) AS p(privilege)
WHERE n.nspname = 'videre' AND c.relkind = 'r' ORDER BY c.relname, p.privilege;
SET ROLE videre_app;
SELECT id, simulation_run_id, simulation_run_started_at FROM videre.clusters LIMIT 0;
RESET ROLE;
SQL
```

**Stop unless all checks pass:**

- Revision: `8d7e3a9164b2`.
- Login: true; all elevated role flags: false.
- Schema access (USAGE): true; table creation (CREATE): false.
- All 28 table grants: true.

Inspect the returned values; `ON_ERROR_STOP` catches SQL errors, not false results. Then resume:

```bash
kubectl -n videre scale deployment/backend --replicas=1
kubectl -n videre rollout status deployment/backend --timeout=180s
kubectl -n videre scale deployment/simulator --replicas=1
kubectl -n videre rollout status deployment/simulator --timeout=180s
```

Confirm backend readiness with the app Secret. Check application APIs and event-consumer progress.

### Database Updates

The simulation-run migration is `c41f8a7d2b95 -> 8d7e3a9164b2`, from source `b6e9d0d8f0a3352a2202e9bdc6e6dc70697896cf`. Confirm the migration files match:

```bash
git diff --exit-code b6e9d0d8f0a3352a2202e9bdc6e6dc70697896cf -- alembic alembic.ini
```

Ensure no other deployment or database change is running, and pause the simulator. Using the admin URL and port-forward above:

1. Run `uv run alembic current`.
2. Upgrade with `uv run alembic upgrade 8d7e3a9164b2` only from `c41f8a7d2b95`.
3. If already at the target, verify it. **Stop for any other revision.**
4. Check the run ID/start-time columns and their paired constraint:

```bash
kubectl -n videre exec -i deployment/postgres -- psql -X -v ON_ERROR_STOP=1 -U postgres -d videre <<'SQL'
SELECT version_num FROM public.alembic_version;
SELECT column_name, is_nullable FROM information_schema.columns
WHERE table_schema = 'videre' AND table_name = 'clusters'
  AND column_name IN ('simulation_run_id', 'simulation_run_started_at');
SELECT conname, convalidated, pg_get_constraintdef(oid) FROM pg_constraint
WHERE conrelid = 'videre.clusters'::regclass AND conname = 'ck_clusters_simulation_run_paired';
SQL
```

Both columns must allow null values, and the constraint requiring them to be set together must be validated. Repeat the app-role checks. Deploy a backend accepting v1/v2 events before starting a v2 simulator.

For future changes, record the source SHA, starting/target revisions, files, commands, affected workloads, compatibility checks, and recovery steps. Prepare compatible database/configuration changes before merging. Apply only the named files and restart affected workloads. Applying the full stack can restore stale image tags; breaking changes need a staged rollout.

### GPU Availability and Grafana

Keep schema `8d7e3a9164b2`; this update needs no migration or policy change. Update backend before frontend. The backend still supports older frontend versions.

After CI deployment, check `/api/capacity` returns `total_gpus`, `unavailable_gpus`, `degraded_gpus`, `idle_gpus`, `active_gpus`, and `queueing_delay_event_count` per cluster. For manual updates, check these after backend rollout, before updating frontend.

Apply the Grafana ConfigMap manually while no other release or configuration change is running. Verify the reviewed checkout and cluster:

```bash
read -r -p 'Reviewed source SHA: ' release_source
[[ "$release_source" =~ ^[0-9a-f]{40}$ ]] && [ "$(git rev-parse HEAD)" = "$release_source" ] || exit 1
export KUBECONFIG="$HOME/.kube/config"
kubectl config current-context
kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}{"\n"}'
# Stop unless the context and endpoint match the intended cluster.
kubectl -n videre apply -f k8s/grafana/02-configmap-dashboards.yaml
```

After Grafana reloads, check the title `GPUs Below 5% Utilization` and its explanation. Queries are unchanged. Do not apply the full stack.

### Release Recovery

Image tags record the desired release; the successful deploy summary records what was deployed. After a failed rollout, compare desired tags, current images, and the last successful release before choosing a recovery target.

Recorded recovery baseline:

| Checkpoint | Value |
|---|---|
| Source revision | `1e8b365702c591b470611260a87ee0421edbe117` |
| Desired-tag commit | `5566a31b0c3647f2ce21a510cafbb4dfaa97c157` |
| Successful deployment | [run 37217089029](https://github.com/AndyDLi/Videre/actions/runs/37217089029) |
| Backend/simulator | `0.9.0-1e8b365` |
| Frontend | `0.9.2-1e8b365` |
| Schema | `8d7e3a9164b2` |

Keep schema `8d7e3a9164b2`. Check the recovery images against the schema, configuration, and policies: v1-only backends cannot read retained v2 events, and simulators from before the security hardening fail admission. If incompatible, stop and use the failed release's recovery plan.

Stop other release workflows and ensure nobody else is changing the deployment. **Restore this baseline's frontend before its backend:** the new frontend needs fields the old backend lacks. Frontend-only recovery may keep the new backend.

```bash
kubectl -n videre set image deployment/frontend frontend=ghcr.io/andydli/videre-frontend:0.9.2-1e8b365
kubectl -n videre rollout status deployment/frontend --timeout=180s
```

Verify the old frontend loads and its overview/capacity pages work with the current backend. Then restore backend and simulator:

```bash
kubectl -n videre set image deployment/backend backend=ghcr.io/andydli/videre-backend:0.9.0-1e8b365
kubectl -n videre rollout status deployment/backend --timeout=180s
kubectl -n videre set image deployment/simulator simulator=ghcr.io/andydli/videre-simulator:0.9.0-1e8b365
kubectl -n videre rollout status deployment/simulator --timeout=180s
kubectl -n videre get deployments -o custom-columns=NAME:.metadata.name,IMAGE:.spec.template.spec.containers[*].image,READY:.status.readyReplicas
```

Verify images, APIs, event consumption, Job creation, schema, and grants. Update desired tags through reviewed Git changes before resuming releases. Avoid blind `rollout undo` or schema downgrades.
