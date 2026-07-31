#!/usr/bin/env bash
# Generate a least-privilege kubeconfig for the CI deploy job.

set -euo pipefail
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/config}"

NAMESPACE=videre
SECRET=videre-deployer-token
OUTPUT="$HOME/.kube/videre-deployer.config"

echo "==> Reading the ServiceAccount token..."
TOKEN=$(kubectl -n "$NAMESPACE" get secret "$SECRET" -o jsonpath='{.data.token}' | base64 -d)
AUTHORITY=$(kubectl -n "$NAMESPACE" get secret "$SECRET" -o jsonpath='{.data.ca\.crt}')
SERVER=$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')

echo "==> Writing $OUTPUT..."
cat > "$OUTPUT" <<EOF
apiVersion: v1
kind: Config
clusters:
  - name: videre
    cluster:
      server: ${SERVER}
      certificate-authority-data: ${AUTHORITY}
users:
  - name: videre-deployer
    user:
      token: ${TOKEN}
contexts:
  - name: videre
    context:
      cluster: videre
      user: videre-deployer
      namespace: ${NAMESPACE}
current-context: videre
EOF

chmod 600 "$OUTPUT"
echo "==> Done. Verify with: KUBECONFIG=$OUTPUT kubectl get deployments"
