#!/usr/bin/env bash
# One-shot installer for metrics-server on the AgenticRAG K3s cluster.
# Idempotent: re-running upgrades to the chart's latest patch with the same flags.
#
# Run from any host with kubectl + helm pointed at the cluster:
#   ./scripts/install-metrics-server.sh
#
# Why this script exists: K3s does not ship metrics-server out of the box, and
# without it `kubectl top` returns "Metrics API not available" and HPA stays
# in "unknown" forever. The --kubelet-insecure-tls flag is required because
# K3s kubelets use self-signed certs by default.

set -euo pipefail

CHART_VERSION="${CHART_VERSION:-3.12.2}"   # metrics-server chart 3.12.2 ships app v0.7.2
RELEASE_NAME="metrics-server"
NAMESPACE="kube-system"

echo "==> Ensuring metrics-server helm repo is registered"
helm repo add metrics-server https://kubernetes-sigs.github.io/metrics-server/ >/dev/null 2>&1 || true
helm repo update metrics-server

echo "==> Installing/upgrading metrics-server (chart ${CHART_VERSION})"
helm upgrade --install "${RELEASE_NAME}" metrics-server/metrics-server \
  --namespace "${NAMESPACE}" \
  --version "${CHART_VERSION}" \
  --set 'args={--kubelet-insecure-tls,--kubelet-preferred-address-types=InternalIP\,Hostname\,InternalDNS\,ExternalDNS\,ExternalIP}' \
  --wait \
  --timeout 3m

echo "==> Waiting for the metrics API to become available (up to 2 min)"
for i in $(seq 1 24); do
  if kubectl top node >/dev/null 2>&1; then
    echo "metrics-server is serving"
    kubectl top node
    exit 0
  fi
  sleep 5
done

echo "ERROR: metrics-server installed but the Metrics API never came up."
echo "Inspect: kubectl -n ${NAMESPACE} logs deploy/${RELEASE_NAME}"
exit 1
