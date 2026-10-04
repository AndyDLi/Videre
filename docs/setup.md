# Host Setup

Videre is self-hosted on a personal Windows 11 machine with an Intel Core Ultra 7 258V, 8 CPU cores, and 32 GB of RAM. The full application stack runs in an Ubuntu 24.04 WSL2 distribution limited to 8 GB of memory and 4 CPU cores. Tailscale Funnel provides the single public HTTPS endpoint.

This document captures the host configuration required to recreate the environment after reinstalling Windows.

## Availability Model

Videre is available on-demand and started manually. While the machine is on for normal daily use, the stack stays stopped and consumes no resources: k3s does not auto-start, and the WSL VM is not held up. The stack, and its public URL, are up only while a demo is explicitly running (see "Starting and Stopping the Demo").

## WSL2 Resource Limits

`C:\Users\andyd\.wslconfig`:

```ini
[wsl2]
memory=8GB
processors=4

[experimental]
autoMemoryReclaim=gradual
sparseVhd=true
```

- `memory` / `processors` set maximum resource limits, not reserved allocations. WSL2 consumes resources as needed, leaving up to 24 GB of RAM and 4 CPU cores available to Windows for normal use.
- `autoMemoryReclaim=gradual` gradually returns idle and cached Linux memory to Windows, preventing the `Vmmem` process from retaining peak memory usage unnecessarily.
- `sparseVhd=true` allows newly created WSL virtual disks to reclaim unused storage on the Windows filesystem.

The existing Ubuntu virtual disk required a one-time sparse-disk conversion:

```powershell
wsl --shutdown
wsl --manage Ubuntu-24.04 --set-sparse true
```

- Changes to `.wslconfig` apply only after WSL has fully stopped: `wsl --shutdown`.
- Wait approximately 10 seconds before reopening the distribution. Verify the active limits from within Ubuntu: `nproc` → 4, `free -h` → ~7.8Gi total with 2.0Gi of swap.

## Manual Startup (WSL and k3s)

To ensure Videre only runs when explicitly started, disable k3s auto-start:

  ```bash
  sudo systemctl disable k3s
  ```

Opening the Ubuntu terminal will still boot the WSL VM on demand. While the lightweight `tailscaled` service auto-starts to maintain network connectivity, k3s and its workloads remain offline. This design ensures that following a Windows restart, the demo consumes no resources until manually launched.

## Starting and Stopping the Demo

Two helper scripts in the `scripts/` directory manage the application lifecycle from within the cluster.

- Startup (`demo-up.sh`): starts k3s, waits for core infrastructure to initialize, and scales the simulator to 1.
- Shutdown (`demo-down.sh`): scales the simulator to 0, which triggers a SIGTERM handler that gracefully flushes in-flight Kafka events, before stopping k3s.

**To Start the Demo:**

1. Open the Ubuntu terminal to boot the WSL VM.
2. Execute `cd ~/Videre && ./scripts/demo-up.sh`.

**To Stop the Demo:**

1. Execute `./scripts/demo-down.sh`.
2. From Windows PowerShell, take the demo offline and release the VM's memory: `wsl --shutdown`.

Both steps are needed. Stopping k3s leaves the containers themselves running, so the public URL keeps serving until WSL shuts down.

## Tailscale and Funnel

Videre's public endpoint is: `https://ragingasian.tail462d2b.ts.net`.

- Install Tailscale inside Ubuntu: `curl -fsSL https://tailscale.com/install.sh | sh`.
- Then `sudo tailscale up` and complete the browser-based authentication flow.
- In the Tailscale admin console, enable MagicDNS and HTTPS Certificates because both are required for Funnel and use the tailnet suffix `tail462d2b.ts.net`.
- Grant the Funnel Node attribute through the Tailscale access-control policy:

```jsonc
"nodeAttrs": [
  { "target": ["autogroup:member"], "attr": ["funnel"] },
]
```

Funnel forwards the public endpoint to Traefik, the ingress controller built into k3s, which then routes each request to the right service inside the cluster:

```bash
sudo tailscale funnel --bg 80
```

- `--bg` runs Funnel as a background service and stores the configuration inside `tailscaled`, so it survives service restarts and host reboots without being entered again.
- The forwarding target is `127.0.0.1:80`.
- The target is Traefik's plain HTTP port rather than its HTTPS port because `tailscaled` has already terminated TLS. Forwarding to HTTPS would only add a second, self-signed handshake across the loopback interface and protect nothing.
- Traefik's own HTTPS port stays disabled (`k8s/traefik/01-helmchartconfig.yaml`) so that k3s cannot claim port 443. If it does, it intercepts the Funnel's traffic and the public URL serves Traefik's self-signed certificate.

Inspect the active configuration with `tailscale funnel status`, and remove it with `sudo tailscale funnel reset`.

Once WSL has shut down, the public URL returns `502 Bad Gateway` because nothing is listening behind port 80. This is expected under the on-demand availability model, and the Funnel configuration itself stays in place.

## Footprint

### Memory

| Component | Current Usage | Limit / Capacity |
|---|---|---|
| WSL2 VM (Stack Running) | 3.8 Gi | 7.8 Gi |
| WSL2 VM (Stack Stopped) | 1.4 Gi | 7.8 Gi |
| Namespace Requests | 2352 Mi | 5 Gi |
| Namespace Limits | 5088 Mi | 6500 Mi |
| Videre Pods | 1440 Mi | Not Enforced |
| Per-Container Max | — | 3 Gi | 

*Note*: Memory for Videre Pods are not enforced as a group. Enforcement happens per-container.

### CPU

| Component | Current Usage | Limit / Capacity |
|---|---|---|
| WSL2 VM | — | 4 Cores |
| Namespace Requests | 1185m | 3 Cores |
| Namespace Limits | — | Not Enforced |
| Videre Pods | 171m | Not Enforced |
| Per-Container Max | — | 4 Cores |

*Note*: Namespace Limits are not enforced because Request and core count already bound it. In addition, like memory, CPU usage is measured dynamically across the Pods, not strictly capped as an aggregate group.

### Storage

| Component | Current Usage | Limit / Capacity |
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

## Kubernetes Deployment and Simulator Privileges

CI uses `videre-deployer`, with patch permission only on `backend`, `frontend`, and `simulator`. Deployment reads support discovery and rollout status; Pod list supports diagnostics. It cannot update unrelated Deployments, read Secrets, install policies/RBAC, or exec into Pods. The simulator's permissions and generated-Pod boundary are described in `docs/materialization.md`.

`k8s/namespace/30-admission.yaml` contains four native ValidatingAdmissionPolicies with fail-closed Deny bindings scoped to `videre`. Requests are matched by authenticated identity and resource names, never workload labels. The current k3s configuration uses `system:serviceaccount:kube-system:job-controller` to create Job Pods; another controller identity requires a deliberate policy update, not a broad exception.


## Database and Release Operations

CI migrates disposable PostgreSQL 17.10 before running tests as `videre_app`. Required database tests fail if their URL is missing. Use a separate prepared database for local tests; never use production.

CI updates images only. An operator applies schema, role, Secret and ConfigMap changes from the reviewed release checkout. The app role can read/write data but cannot migrate the schema. Backend images contain no Alembic files; `/healthz` checks connectivity, not schema or table grants.

### Fresh Database Installation

Use the reviewed release checkout and an administrator kubeconfig. Verify its full SHA and the cluster endpoint:

```bash
read -r -p 'Reviewed checkout SHA: ' release_source
[[ "$release_source" =~ ^[0-9a-f]{40}$ ]] && [ "$(git rev-parse HEAD)" = "$release_source" ] || exit 1
export KUBECONFIG="$HOME/.kube/config"
kubectl config current-context
kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}{"\n"}'
```

Stop if either target is wrong. Create the four Secrets and apply the stack as described in README, then pause backend and simulator until the database is ready:

```bash
kubectl -n videre scale deployment/backend deployment/simulator --replicas=0
kubectl -n videre rollout status deployment/postgres --timeout=180s
kubectl -n videre port-forward service/postgres 15432:5432
```

Leave port-forward running. In another WSL terminal, enter the administrative SQLAlchemy URL using `postgres`, `127.0.0.1:15432`, database `videre`, and the administrator password. The prompt hides the URL:

```bash
read -rs -p 'Admin DATABASE_URL: ' DATABASE_URL; printf '\n'
export DATABASE_URL
uv sync --locked --all-extras
uv run alembic upgrade 8d7e3a9164b2
uv run alembic current --check-heads
unset DATABASE_URL
```

This release targets `8d7e3a9164b2`. Future releases must specify their starting and target revisions; do not use an unchecked `head` in production. Run bootstrap only on a fresh database without `videre_app`:

```bash
kubectl -n videre exec -i deployment/postgres -- \
  psql -X -U postgres -d videre -v database_name=videre < scripts/bootstrap-postgres.sql
kubectl -n videre exec -it deployment/postgres -- \
  psql -X -U postgres -d videre -c '\password videre_app'
```

Set the password to match `postgres-app-secret`, with user `videre_app`. Keep real passwords out of SQL files, Git and command arguments. Bootstrap grants database CONNECT, schema USAGE and table SELECT/INSERT/UPDATE/DELETE without schema CREATE or table ownership. Future-table grants apply to tables created by `postgres`; update and verify default grants if the migration owner changes.

Verify the revision and application access before resuming:

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

Stop unless the revision is `8d7e3a9164b2`, login is true, elevated flags are false, USAGE is true, CREATE is false, and all 28 table grants are true. Inspect the results: `ON_ERROR_STOP` catches SQL errors, not false values. Then resume:

```bash
kubectl -n videre scale deployment/backend --replicas=1
kubectl -n videre rollout status deployment/backend --timeout=180s
kubectl -n videre scale deployment/simulator --replicas=1
kubectl -n videre rollout status deployment/simulator --timeout=180s
```

Check backend readiness with the actual app Secret, then verify application APIs and consumer progress.

### Revision-Specific Schema and Configuration Changes

The simulation-boundary migration is `c41f8a7d2b95 -> 8d7e3a9164b2`, from source `b6e9d0d8f0a3352a2202e9bdc6e6dc70697896cf`. Verify the checkout has those migration definitions:

```bash
git diff --exit-code b6e9d0d8f0a3352a2202e9bdc6e6dc70697896cf -- alembic alembic.ini
```

Coordinate exclusive access and pause the simulator. Using the admin URL and port-forward above, run `uv run alembic current`. Upgrade with `uv run alembic upgrade 8d7e3a9164b2` only from `c41f8a7d2b95`. If already at the target, verify it; stop for any other revision. Check the target, nullable columns and validated paired constraint:

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

Require both columns to be nullable and the paired constraint validated. Repeat the app-role checks. Deploy a backend that accepts v1/v2 events before starting a v2 simulator. This CI change needs no production migration or configuration update; the target was already verified live.

For future schema/configuration changes, record these in the PR/runbook:

- Full source SHA and starting/target schema revisions.
- Exact manifests, affected workloads and operator commands.
- Compatibility with application versions and retained events.
- Verification steps and a compatible recovery target.

Prepare compatible schema/configuration before merging. Apply only the named manifests; restart workloads whose environment changed. Applying the full stack can restore stale image tags. Breaking changes require a staged rollout plan.

### Verified Releases and Compatible Recovery

Manifest tags describe desired images. A successful deploy job and rollout summary confirm the deployed release, including source SHA, image-tag commit, images and run link. After failure, compare desired tags, running images and the last successful release. Keep its run link and schema/configuration compatibility notes.

A verified recovery baseline is:

| Checkpoint | Value |
|---|---|
| Source revision | `b6e9d0d8f0a3352a2202e9bdc6e6dc70697896cf` |
| Desired-tag commit | `6dca16bd50decfa00e8e252857b57596d7d8c386` |
| Successful deployment | [run 37182816390](https://github.com/AndyDLi/Videre/actions/runs/37182816390) |
| Backend/simulator | `0.9.0-b6e9d0d` |
| Frontend | `0.9.2-b6e9d0d` |
| Schema | `8d7e3a9164b2` |

The baseline configuration and workload template were verified with the current policies. Recheck compatibility before recovery. Keep schema `8d7e3a9164b2`; image rollback does not require removing its added columns. A v1-only backend cannot consume retained v2 events, and pre-hardening simulator images fail admission. Choose a verified compatible release, not simply an older tag.

Stop competing release workflows and coordinate exclusive access. Check current images, rollouts, schema, configuration and policies against the baseline. If incompatible, use the failed release's recovery plan. Otherwise restore these images in order:

```bash
kubectl -n videre set image deployment/backend backend=ghcr.io/andydli/videre-backend:0.9.0-b6e9d0d
kubectl -n videre rollout status deployment/backend --timeout=180s
kubectl -n videre set image deployment/simulator simulator=ghcr.io/andydli/videre-simulator:0.9.0-b6e9d0d
kubectl -n videre rollout status deployment/simulator --timeout=180s
kubectl -n videre set image deployment/frontend frontend=ghcr.io/andydli/videre-frontend:0.9.2-b6e9d0d
kubectl -n videre rollout status deployment/frontend --timeout=180s
kubectl -n videre get deployments -o custom-columns=NAME:.metadata.name,IMAGE:.spec.template.spec.containers[*].image,READY:.status.readyReplicas
```

Verify images, application APIs, consumer/materialization progress and schema/grants. Reconcile desired tags through reviewed Git changes before resuming releases. Avoid blind `rollout undo` or schema downgrades; resume only releases still desired and compatible.
