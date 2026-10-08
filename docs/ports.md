# Ports

## Cluster

Inside the cluster, connect to `<name>.videre.svc.cluster.local:<port>` using the component's protocol. Kafka's headless Service points directly to its Pod; the others use internal Service IPs (ClusterIP). Public web access goes through Traefik.

| Port | Component | Function |
|---|---|---|
| 80 | `frontend` | HTTP Service forwarding to container port 8080. |
| 3000 | `grafana` | Dashboards and embedded `/d-solo/...` charts. |
| 3100 | `loki` | Accepts Alloy logs and serves Grafana log queries. |
| 5432 | `postgres` | Entity state, job history, failure records. |
| 6379 | `redis` | Cluster-health cache, rate-limit counters, AI response cache. |
| 8000 | `backend` | REST APIs, `/ws/cluster-health`, `/metrics` |
| 9090 | `prometheus` | Stores metrics and serves the query API for Grafana. |
| 9092 | `kafka` | Kafka client connections. |

## Container

These ports run inside Pods. Of these, only frontend port 8080 has a Service; reach the others through the Pod IP or `localhost` inside the Pod.

| Port | Component | Function |
|---|---|---|
| 8080 | `frontend` | Nginx web server running as a non-root user. |
| 9093 | `kafka` | KRaft controller listener. |
| 9096 | `loki` | Internal gRPC listener. |
| 12345 | `alloy` | Log collector's HTTP server. |

## Local

These ports are used on the host for web routing, development, and cluster access.

| Port | Component | Function |
|---|---|---|
| 80 | Traefik | Routes HTTP traffic from Funnel to Kubernetes Services. |
| 443 | Tailscale | Terminates HTTPS and forwards traffic to Traefik on port 80. Traefik's own HTTPS exposure is disabled to avoid a port conflict. |
| 6443 | k3s API server | Kubernetes management API. |
| 5173 | Vite dev server | The local dashboard from `npm run dev`. |
| 3000 | Grafana port-forward | `kubectl -n videre port-forward svc/grafana 3000:3000`. |
| 8000 | Backend port-forward | `kubectl -n videre port-forward svc/backend 8000:8000`. |
| 8082 | Frontend port-forward | `kubectl -n videre port-forward svc/frontend 8082:80`. |

## Public

| Port | Component | Function |
|---|---|---|
| 443 | Tailscale Funnel | Public HTTPS entry point; forwards to Traefik on local port 80. |
