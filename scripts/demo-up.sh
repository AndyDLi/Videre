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

PUBLIC_HOST="ragingasian.tail462d2b.ts.net"

echo "==> Verifying public reachability..."
edge_ip=$(curl -sS -m 10 "https://dns.google/resolve?name=${PUBLIC_HOST}&type=A" 2>/dev/null \
  | python3 -c "import sys,json; a=[x['data'] for x in json.load(sys.stdin).get('Answer',[]) if x.get('type')==1]; print(a[0] if a else '')" 2>/dev/null || true)

if [ -z "$edge_ip" ]; then
  echo "==> Videre is up: https://${PUBLIC_HOST}"
  echo "WARNING: could not resolve the Funnel edge, so public reachability is unverified." >&2
  exit 0
fi

for attempt in $(seq 1 12); do
  code=$(curl -sS -o /dev/null -w '%{http_code}' -m 10 \
    --resolve "${PUBLIC_HOST}:443:${edge_ip}" "https://${PUBLIC_HOST}/" 2>/dev/null || true)
  if [ "${code}" = "200" ]; then
    echo "==> Videre is up: https://${PUBLIC_HOST}"
    exit 0
  fi
  sleep 5
done

echo "WARNING: the stack is running, but https://${PUBLIC_HOST} returned ${code:-000} via ${edge_ip}." >&2
echo "         Recover the tunnel with: sudo tailscale funnel reset && sudo tailscale funnel --bg 80" >&2
exit 1
