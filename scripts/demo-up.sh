#!/usr/bin/env bash
# Start the Videre demo. Run inside the WSL2 Ubuntu distro.
# Brings k3s up, waits for the core infrastructure, then starts the simulator.

set -euo pipefail
export KUBECONFIG="$HOME/.kube/config"

while mountpoint -q /Docker/host; do sudo umount -l /Docker/host; done

echo "==> Starting k3s..."
sudo systemctl start k3s

echo "==> Waiting for the Kubernetes API to be ready..."
deadline=$(( $(date +%s) + 180 ))
ready=0
until [ "$ready" -ge 3 ]; do    # 3 consecutive successes to ensure stability
  if kubectl get --raw='/readyz' >/dev/null 2>&1; then ready=$((ready+1)); else ready=0; fi
  [ "$(date +%s)" -ge "$deadline" ] && { echo "k3s API not ready within 180s" >&2; exit 1; }
  sleep 2
done

echo "==> Waiting for core infrastructure to be ready..."
for deploy in postgres redis kafka prometheus grafana; do
  kubectl -n videre rollout status "deploy/$deploy" --timeout=180s
done

echo "==> Starting the simulator..."
kubectl -n videre scale deploy/simulator --replicas=1
kubectl -n videre rollout status deploy/simulator --timeout=120s

echo "==> Videre is up: https://ragingasian.tail462d2b.ts.net"
