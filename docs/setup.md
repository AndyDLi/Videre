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
