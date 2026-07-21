# Host Setup

Videre self-hosts on a personal Windows 11 machine (Intel Core Ultra 7 258V, 8 cores, 32GB RAM). The entire stack runs inside a WSL2 Ubuntu 24.04 distro capped at 8GB RAM / 4 cores; Tailscale Funnel provides the single public HTTPS entry point. This file records the host configuration so it can be rebuilt from scratch after a Windows reinstall.

## Availability model

On-demand by design: the machine sleeps and shuts down normally, and the public URL works whenever it is on — no always-on obligation and no permanent power-settings changes. The README's recorded walkthrough is the primary artifact. For deliberate long windows (extended soak runs, demo recordings), temporarily prevent sleep with `presentationsettings /start` and revert with `presentationsettings /stop` when done.

## WSL2 resource caps

`C:\Users\andyd\.wslconfig`:

```ini
[wsl2]
memory=8GB
processors=4

[experimental]
autoMemoryReclaim=gradual
sparseVhd=true
```

- `memory` / `processors` — a ceiling; WSL2 allocates on demand and leaves Windows 24GB / 4 cores for daily use.
- `autoMemoryReclaim=gradual` — idle and cached memory drains back to Windows instead of the Vmmem process holding its peak allocation.
- `sparseVhd=true` — newly created virtual disks return freed space to Windows. The pre-existing distro disk needed a one-time conversion:

```powershell
wsl --shutdown
wsl --manage Ubuntu-24.04 --set-sparse true
```

Config changes take effect after `wsl --shutdown` (wait ~10s before reopening). Verify from inside the distro: `nproc` → 4, `free -h` → ~7.8Gi total with 2.0Gi swap.

## Distro configuration

`/etc/wsl.conf` — systemd is required because k3s and tailscaled install as systemd services:

```ini
[boot]
systemd=true

[user]
default=andyd
```

Security updates are applied with `sudo apt update && sudo apt full-upgrade -y`. Unattended-upgrades is installed and active; `/etc/apt/apt.conf.d/20auto-upgrades` sets both `Update-Package-Lists` and `Unattended-Upgrade` to `"1"`.

## Auto-start (on-demand model)

Scheduled task `Videre-WSL-Keepalive` starts the distro headlessly at logon and holds it open — WSL can idle the VM out once the last interactive session closes, even with systemd services running, so the task pins a `sleep infinity` inside the distro. Recreate with:

```powershell
$action   = New-ScheduledTaskAction -Execute "conhost.exe" `
            -Argument "--headless wsl.exe -d Ubuntu-24.04 --exec sleep infinity"
$trigger  = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "Videre-WSL-Keepalive" -Action $action -Trigger $trigger -Settings $settings
```

The task runs only when the user is logged on (WSL is a per-user VM), so after an unattended reboot the demo stays down until logon — acceptable under the on-demand model.

## Tailscale and Funnel

Public entry point: `https://ragingasian.tail462d2b.ts.net`. Funnel serves only ports 443/8443/10000; TLS terminates at Tailscale's edge; bandwidth limits are non-configurable.

- Install inside the distro: `curl -fsSL https://tailscale.com/install.sh | sh`, then `sudo tailscale up` (browser login). `sudo tailscale set --operator=andyd` allows sudo-less CLI use. `tailscaled` runs as an enabled systemd service.
- Admin console → DNS: MagicDNS and HTTPS Certificates are enabled — both are Funnel prerequisites (tailnet suffix `tail462d2b.ts.net`).
- Access Controls policy grants the funnel node attribute:

```jsonc
"nodeAttrs": [
  { "target": ["autogroup:member"], "attr": ["funnel"] },
]
```

Operate: `sudo tailscale funnel --bg <port>` exposes a local port publicly (config persists across restarts); `tailscale funnel status` shows the active config; `sudo tailscale funnel reset` removes it.

## Baseline idle usage (pre-stack)

Reference point for judging the stack's real footprint once deployed (estimate: 3–5GB).

| Measure | Value |
|---|---|
| Memory used, idle distro | 1.4Gi of 7.8Gi |
| Distro disk used (`df -h /`) | 21G used, 936G free |
| VHDX size (Windows side) | 29.5GB, sparse |

VHDX location: `C:\Users\andyd\AppData\Local\wsl\{12b8dd3b-529a-41dc-80f5-ec8372af710d}\ext4.vhdx` (the GUID changes on reinstall — find it via):

```powershell
Get-ChildItem HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss |
  Get-ItemProperty | Where-Object DistributionName -eq 'Ubuntu-24.04' |
  ForEach-Object { Get-Item "$($_.BasePath)\ext4.vhdx" }
```
