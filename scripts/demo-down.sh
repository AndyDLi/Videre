#!/usr/bin/env bash
# Stop the Videre demo. Run inside the WSL2 Ubuntu distro.
# Flushes and stops the simulator, then stops k3s. The containers keep running until
# `wsl --shutdown` is run from Windows to take the demo offline and return VM's memory.

set -euo pipefail
export KUBECONFIG="$HOME/.kube/config"

if kubectl get nodes >/dev/null 2>&1; then
  echo "==> Stopping the simulator (SIGTERM flushes in-flight Kafka events)..."
  kubectl -n videre scale deploy/simulator --replicas=0
  kubectl -n videre wait --for=delete pod -l app=simulator --timeout=60s || true
fi

echo "==> Stopping k3s..."
sudo systemctl stop k3s

echo "==> k3s stopped. Run 'wsl --shutdown' from Windows PowerShell to take Videre offline and free the VM's RAM."
