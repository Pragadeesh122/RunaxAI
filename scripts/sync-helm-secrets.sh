#!/usr/bin/env bash
# Sync helm/values-secrets.yaml -> Kubernetes secret consumed by the CI deploy.
#
# The GitHub Actions deploy workflow reads helm values from a cluster secret
# named `helm-values-secrets` in the `arc-runners` namespace. That secret is
# NOT auto-synced from this repo. Run this script after editing the local
# values-secrets.yaml so the next deploy picks up your changes.
#
# Usage:
#   ./scripts/sync-helm-secrets.sh           # sync with diff preview + confirm
#   ./scripts/sync-helm-secrets.sh --yes     # skip confirmation
#   ./scripts/sync-helm-secrets.sh --check   # show diff, no changes

set -euo pipefail

SECRET_NAME="helm-values-secrets"
SECRET_NAMESPACE="arc-runners"
SECRET_KEY="values-secrets.yaml"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL_FILE="${REPO_ROOT}/helm/values-secrets.yaml"

assume_yes=false
check_only=false
for arg in "$@"; do
  case "$arg" in
    -y|--yes) assume_yes=true ;;
    --check)  check_only=true ;;
    -h|--help)
      sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

if ! command -v kubectl >/dev/null; then
  echo "error: kubectl not found in PATH" >&2
  exit 1
fi

if [[ ! -f "$LOCAL_FILE" ]]; then
  echo "error: local secrets file not found at $LOCAL_FILE" >&2
  exit 1
fi

current_ctx="$(kubectl config current-context 2>/dev/null || true)"
if [[ -z "$current_ctx" ]]; then
  echo "error: no current kubectl context — point kubectl at the prod cluster first" >&2
  exit 1
fi

if ! kubectl get namespace "$SECRET_NAMESPACE" >/dev/null 2>&1; then
  echo "error: namespace '$SECRET_NAMESPACE' not found in context '$current_ctx'" >&2
  exit 1
fi

echo "context:   $current_ctx"
echo "namespace: $SECRET_NAMESPACE"
echo "secret:    $SECRET_NAME"
echo "source:    $LOCAL_FILE"
echo

tmp_remote="$(mktemp)"
trap 'rm -f "$tmp_remote"' EXIT

if kubectl -n "$SECRET_NAMESPACE" get secret "$SECRET_NAME" >/dev/null 2>&1; then
  kubectl -n "$SECRET_NAMESPACE" get secret "$SECRET_NAME" \
    -o "jsonpath={.data.${SECRET_KEY//./\\.}}" | base64 -d > "$tmp_remote"
  if diff -q "$tmp_remote" "$LOCAL_FILE" >/dev/null 2>&1; then
    echo "no changes — cluster secret already matches local file."
    exit 0
  fi
  echo "diff (cluster -> local):"
  diff -u "$tmp_remote" "$LOCAL_FILE" || true
  echo
else
  echo "note: cluster secret does not exist yet — this will create it."
  echo
fi

if [[ "$check_only" == true ]]; then
  echo "--check passed; not applying."
  exit 0
fi

if [[ "$assume_yes" != true ]]; then
  read -r -p "apply this change to the cluster? [y/N] " reply
  case "$reply" in
    y|Y|yes|YES) ;;
    *) echo "aborted."; exit 1 ;;
  esac
fi

kubectl create secret generic "$SECRET_NAME" \
  --namespace "$SECRET_NAMESPACE" \
  --from-file="${SECRET_KEY}=${LOCAL_FILE}" \
  --dry-run=client -o yaml \
  | kubectl apply -f -

echo
echo "synced. trigger a redeploy to pick up the new values."
