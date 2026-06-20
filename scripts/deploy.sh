#!/usr/bin/env bash
# One-shot production deploy from the machine that holds helm/values-secrets.yaml.
#
# The CI deploy reads provider/app secrets from the in-cluster `helm-values-secrets`
# secret, NOT from your local file — so a local edit is inert until synced. This
# wrapper always syncs first, then triggers the deploy, so the pod secret can
# never silently lag behind your local helm/values-secrets.yaml.
#
# Steps:
#   1. ./scripts/sync-helm-secrets.sh  -> push local values-secrets.yaml into the cluster
#   2. gh workflow run deploy.yml      -> trigger Build & Deploy (renders the fresh secret)
#
# Usage:
#   ./scripts/deploy.sh           # sync with diff preview + confirm, then deploy
#   ./scripts/deploy.sh --yes     # skip the sync confirmation prompt
#
# Requires: kubectl (pointed at the prod cluster) and gh (authenticated).
# Note: gh workflow run needs the workflow_dispatch trigger to already exist on
# the default branch — merge this change once before the wrapper can trigger deploys.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if ! command -v gh >/dev/null; then
  echo "error: gh (GitHub CLI) not found in PATH" >&2
  exit 1
fi

echo "==> syncing local helm/values-secrets.yaml into the cluster secret"
./scripts/sync-helm-secrets.sh "$@"

echo
echo "==> triggering the deploy workflow on main"
gh workflow run deploy.yml --ref main

echo
echo "deploy triggered. follow it with:"
echo "  gh run watch \"\$(gh run list --workflow=deploy.yml -L1 --json databaseId -q '.[0].databaseId')\""
