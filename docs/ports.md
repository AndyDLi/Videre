# Ports

## Cluster

ClusterIP Services in the `videre` namespace, reachable by other pods as `http://<name>:<port>`.

| Port | Component | Function |
|---|---|---|
| 80 | `frontend` | Maps onto the Nginx container's 8080 |
| 3000 | `grafana` | Dashboards, and the `d-solo` panels embedded by the drill-down pages |
| 3100 | `loki` | Log ingest and query API |
| 5432 | `postgres` | Entity state, job history, failure records |
| 6379 | `redis` | Cluster-health cache, rate-limit counters, AI response cache |
| 8000 | `backend` | REST API, `/ws/cluster-health`, `/metrics` |
| 9090 | `prometheus` | Metrics store and query API |
| 9092 | `kafka` | Broker listener; headless Service |

## Container

Listening inside their own pod, with no Service in front.

| Port | Component | Function |
|---|---|---|
| 8080 | `frontend` | Nginx's listener; 8080 because it runs unprivileged and cannot bind 80 |
| 9093 | `kafka` | KRaft controller listener |
| 9096 | `loki` | gRPC listener; unused in single-binary mode |
| 12345 | `alloy` | HTTP and health endpoint; the DaemonSet has no Service, so it is reached by pod IP |

## Local

On the developer's machine. The port-forwards are created on demand and stop when the command does.

| Port | Component | Function |
|---|---|---|
| 80 | Traefik | HTTP ingress; no route configured until Phase 8 |
| 443 | Traefik | HTTPS ingress; no route configured until Phase 8 |
| 3000 | Grafana port-forward | `kubectl -n videre port-forward svc/grafana 3000:3000` |
| 5173 | Vite dev server | `npm run dev`; the working local dashboard |
| 6443 | k3s API server | Kubernetes control plane |
| 8000 | Backend port-forward | `kubectl -n videre port-forward svc/backend 8000:8000` |
| 8082 | Frontend port-forward | `kubectl -n videre port-forward svc/frontend 8082:80` |

## Public

| Port | Component | Function |
|---|---|---|
| 443 | Tailscale Funnel | The only public entry point; TLS terminates at Tailscale's edge |
