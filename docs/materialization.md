# Turning Simulated Jobs into Real Pods

Videre simulates nodes, GPUs, and scheduling in memory. Each scheduled job gets a lightweight Kubernetes Job and Pod on the single real k3s node. These Pods produce real Kubernetes results without running GPU workloads.

## How It Works

1. The simulator assigns a job to a simulated node and creates its real Pod.
2. Labels link the Pod to that simulated job and node. The Job has a two-minute time limit by default.
3. The Pod waits for an outcome. The simulator runs a command inside the Pod (Kubernetes exec) to write the outcome to a file:

| Outcome | Real Result |
|---|---|
| `complete` | Exits successfully with code `0` |
| `fail` | Exits with code `1` |
| `oom` | Exceeds its memory limit and is killed for running out of memory (`OOMKilled`) |

These results appear in Kubernetes status, logs, and diagnostic commands. Kubernetes removes finished Jobs after two minutes by default.

## Permissions and Limits

The `videre-simulator` account can create Jobs, read/list Pods, and run exec in the `videre` namespace. It cannot read, watch, or delete Jobs.

Kubernetes checks each request against these rules:

- Simulator Jobs must use `sim-job-` names and the approved template: one `workload` container, limited resources, the default account without an API token, no volumes or credentials, and no host access or elevated privileges.
- Only the authenticated Job controller can create reserved Pods, and each must belong to a reserved Job. Pod updates, debug containers, and resource resizing are also checked.
- Simulator exec is restricted to `sim-job-` Pod names. Copying labels does not grant access or bypass the rules.

CI can replace application images, but cannot add or remove containers or change accounts, credentials, mounts, resource limits, or security settings. Replacement code still has the application's existing permissions. These rules do not block access to existing application services or prevent resource exhaustion.

Exact restrictions are defined in [the admission rules](../k8s/namespace/30-admission.yaml).
