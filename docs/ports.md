# Ports

## Cluster

These ClusterIP Services in the `videre` namespace are reachable anywhere inside the cluster via standard DNS (`http://<name>:<port>`), but are isolated from the outside world.

| Port | Component | Function |
|---|---|---|
| 80 | `frontend` | Standard HTTP bridge that forwards traffic to the container's unprivileged port 8080. |
| 3000 | `grafana` | Visualization dashboard serving full monitoring UI and `/d-solo/...` embedded charts pulled into drill-down iframes. |
| 3100 | `loki` | Two-way HTTP pipeline for Alloy to push logs and Grafana to query them. |
| 5432 | `postgres` | Entity state, job history, failure records. |
| 6379 | `redis` | Cluster-health cache, rate-limit counters, AI response cache. |
| 8000 | `backend` | REST APIs, `/ws/cluster-health`, `/metrics` |
| 9090 | `prometheus` | Stores metrics and serves the query API for Grafana. |
| 9092 | `kafka` | Network socket where the Kafka server sits and listens for connections. |

## Container

These listeners run locally inside individual pods as the actual destination that ClusterIP Services route traffic to. They have no DNS name and can only be reached via their pod IP or `localhost`.

| Port | Component | Function |
|---|---|---|
| 8080 | `frontend` | The Nginx web server, binded to 8080 to run securely as a non-root user. |
| 9093 | `kafka` | KRaft controller listener. |
| 9096 | `loki` | Internal gRPC listener. |
| 12345 | `alloy` | Log collector's HTTP server. |

## Local

These ports run on local hardware to build, test, and control the cluster.

| Port | Component | Function |
|---|---|---|
| 80 | Traefik | Receives the HTTP traffic that Tailscale Funnel forwards from the public URL, then routes it to the right Kubernetes Service. |
| 443 | Tailscale | Handles the secure incoming internet connection and passes it to Traefik on port 80, keeping Traefik's own secure port disabled so they do not fight for control. |
| 6443 | k3s API server | Kubernetes control plane. |
| 5173 | Vite dev server | The local dashboard from `npm run dev`. |
| 3000 | Grafana port-forward | `kubectl -n videre port-forward svc/grafana 3000:3000`. |
| 8000 | Backend port-forward | `kubectl -n videre port-forward svc/backend 8000:8000`. |
| 8082 | Frontend port-forward | `kubectl -n videre port-forward svc/frontend 8082:80`. |

## Public

| Port | Component | Function |
|---|---|---|
| 443 | Tailscale Funnel | The only public entry point. Receives HTTPS traffic from the internet and forwards it to Traefik on local port 80. |
