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

## Baseline Idle Usage

These measurements establish the host's pre-stack baseline. Compare future measurements against them to estimate the actual footprint of Videre after deployment, which is expected to use approximately 3 to 5 GB of additional memory and storage depending on workloads, images, and retained data.

| Measure | Value |
|---|---|
| Idle distribution memory usage | 1.4Gi of 7.8Gi |
| Distribution disk usage (`df -h /`) | 21G used, 936G free |
| Windows-side VHDX size | 29.5GB, sparse |

The current VHDX path is: `C:\Users\andyd\AppData\Local\wsl\{12b8dd3b-529a-41dc-80f5-ec8372af710d}\ext4.vhdx`.

The distribution GUID changes after a reinstall. Locate the active Ubuntu 24.04 VHDX with:

```powershell
Get-ChildItem HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss |
  Get-ItemProperty | Where-Object DistributionName -eq 'Ubuntu-24.04' |
  ForEach-Object { Get-Item "$($_.BasePath)\ext4.vhdx" }
```

## Deployed Footprint

Measured with the full stack running: nine infrastructure and application pods plus the simulator's materialized job pods.

| Measure | Baseline | Deployed | Limit |
|---|---|---|---|
| Distribution memory | 1.4Gi | 3.0Gi of 7.8Gi | 8 GB WSL2 cap |
| Distribution disk (`df -h /`) | 21G | 33G used, 923G free | ~20 GB project budget |
| Namespace CPU requests | — | 1195m | 3 |
| Namespace memory requests | — | 2384Mi | 5Gi |
| Namespace memory limits | — | 5152Mi | 6500Mi |
| Namespace storage requests | — | 14Gi | 16Gi |
| Live pod usage | — | 225m CPU, 1388Mi | — |

Everything sits inside its cap. Actual PVC consumption is far below the claims reserved for it:

| Store | On disk | Claim |
|---|---|---|
| Prometheus TSDB | 262M | 4Gi |
| Kafka logs | 146M | 4Gi |
| Postgres data | 121M | 2Gi |
| Grafana database | 49M | 1Gi |
| Loki chunks and index | 5M | 3Gi |

The largest consumer is not a claim at all. The k3s image store holds **5.5G**, roughly ten times every PVC combined, because each CI merge publishes three SHA-tagged images and nothing removes the ones no longer referenced. No retention policy covers it. Reclaim the space with `sudo k3s crictl rmi --prune` when the distribution disk grows.

The WSL2 virtual disk grows on demand and never shrinks on its own. `sparseVhd=true` limits how far it overshoots, but returning space to Windows needs a manual compact after a large deletion.
