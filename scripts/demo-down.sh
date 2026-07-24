#!/usr/bin/env bash
# Stop the Videre demo. Run inside the WSL2 Ubuntu distro.
# Flushes and stops the simulator, then stops k3s. Afterward run
# `wsl --shutdown` from Windows to return the VM's memory to Windows.

set -euo pipefail
export KUBECONFIG="$HOME/.kube/config"

if kubectl get nodes >/dev/null 2>&1; then
  echo "==> Stopping the simulator (SIGTERM flushes in-flight Kafka events)..."
  kubectl -n videre scale deploy/simulator --replicas=0
  kubectl -n videre wait --for=delete pod -l app=simulator --timeout=60s || true
fi

echo "==> Stopping k3s..."
sudo systemctl stop k3s

echo "==> Videre is down. Run 'wsl --shutdown' from Windows PowerShell to free the VM's RAM."
