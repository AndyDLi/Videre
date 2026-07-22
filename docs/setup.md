# Host Setup

Videre is self-hosted on a personal Windows 11 machine with an Intel Core Ultra 7 258V, 8 CPU cores, and 32 GB of RAM. The full application stack runs in an Ubuntu 24.04 WSL2 distribution limited to 8 GB of memory and 4 CPU cores. Tailscale Funnel provides the single public HTTPS endpoint.

This document captures the host configuration required to recreate the environment after reinstalling Windows.

## Availability Model

Videre is intentionally available on-demand rather than continuously. The host follows normal sleep and shutdown behavior, and the public URL is reachable only while the machine is running. No permanent power-policy changes or always-on commitment are required.

The recorded README walkthrough is the primary demonstration artifact. For planned extended availability, such as soak testing or recording a demo, temporarily suppress sleep: `presentationsettings /start`. Restore normal sleep behavior afterwards: `presentationsettings /stop`.

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

## Distro Configuration

`/etc/wsl.conf` enables `systemd`, which is required because both k3s and Tailscale install and run as systemd-managed services:

```ini
[boot]
systemd=true

[user]
default=andyd
```

- Apply operating-system updates manually with: `sudo apt update && sudo apt full-upgrade -y`.
- Automatic security updates are also enabled through `unattended-upgrades`. In `/etc/apt/apt.conf.d/20auto-upgrades`, both `Update-Package-Lists` and `Unattended-Upgrade` are set to `"1"`.

## Automatic WSL Startup

The `Videre-WSL-Keepalive` Scheduled Task starts the Ubuntu distribution headlessly when the user logs in and keep the WSL VM active.

WSL can stop its VM after the last interactive Linux process exits, even when the systemd services remain configured. The task prevents this by maintaining a long-running `sleep infinity` process inside the distribution.

Recreate the task with:

```powershell
$action   = New-ScheduledTaskAction -Execute "conhost.exe" `
            -Argument "--headless wsl.exe -d Ubuntu-24.04 --exec sleep infinity"
$trigger  = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "Videre-WSL-Keepalive" -Action $action -Trigger $trigger -Settings $settings
```

The task runs only after the Windows user logs in because WSL operates as a per-user environment. Following an unattended Windows restart, Videre remains unavailable until the next user logon. This behavior is acceptable under the on-demand availability model

## Tailscale and Funnel

Videre's public endpoint is: `https://ragingasian.tail462d2b.ts.net`.

Tailscale Funnel exposes the selected local service through Tailscale's HTTPS edge. Funnel supports public exposure on ports 443/8443/10000; TLS terminates at Tailscale's edge, and Funnel bandwidth limits are managed by Tailscale rather than configured locally.

- Install Tailscale inside Ubuntu: `curl -fsSL https://tailscale.com/install.sh | sh`.
- Then `sudo tailscale up` and complete the browser-based authentication flow.
- Allow the `andyd` Linux user to run Tailscale commands without `sudo`: `sudo tailscale set --operator=andyd`.
- In the Tailscale admin console, enable MagicDNS and HTTPS Certificates because both are required for Funnel and use the tailnet suffix `tail462d2b.ts.net`.
- Grant the Funnel Node attribute through the Tailscale access-control policy:

```jsonc
"nodeAttrs": [
  { "target": ["autogroup:member"], "attr": ["funnel"] },
]
```

Manage Funnel with the following commands: `sudo tailscale funnel --bg <port>` exposes a local port publicly and persists the configuration across restarts; `tailscale funnel status` shows the active Funnel configuration; `sudo tailscale funnel reset` removes the current Funnel configuration.

## Baseline Idle Usage

These measurements establish the host's pre-stack baseline. Compare future measurements against them to estimate the actual foorprint of Videre after deployment, which is expected to use approximately 3 to 5 GB of additional memory and sroage depending on workloads, images, and retained data.

| Measure | Value |
|---|---|
| Idle distribution memory usgae | 1.4Gi of 7.8Gi |
| Distribution disk usage (`df -h /`) | 21G used, 936G free |
| Windows-side VHDX size | 29.5GB, sparse |

The current VHDX path is: `C:\Users\andyd\AppData\Local\wsl\{12b8dd3b-529a-41dc-80f5-ec8372af710d}\ext4.vhdx`.

The distribution GUID changes after a reinstall. Locate the activate Ubuntu 24.04 VHDX with:

```powershell
Get-ChildItem HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss |
  Get-ItemProperty | Where-Object DistributionName -eq 'Ubuntu-24.04' |
  ForEach-Object { Get-Item "$($_.BasePath)\ext4.vhdx" }
```
