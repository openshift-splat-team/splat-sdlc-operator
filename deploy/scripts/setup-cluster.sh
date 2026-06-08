#!/usr/bin/env bash
# Idempotent Kind cluster bootstrap for local SDLC agent development.
# Run this once after cloning, or re-run safely after cluster-down.
set -euo pipefail

CLUSTER_NAME="sdlc"
NAMESPACE="sdlc"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ── Colour helpers ────────────────────────────────────────────────────────────
info()  { echo "  [INFO]  $*"; }
ok()    { echo "  [OK]    $*"; }
warn()  { echo "  [WARN]  $*"; }
die()   { echo "  [ERROR] $*" >&2; exit 1; }

# ── Prerequisite check ────────────────────────────────────────────────────────
info "Checking prerequisites..."
for cmd in kind kubectl helm docker; do
  command -v "$cmd" &>/dev/null || die "'$cmd' not found on PATH. Install it and retry."
done
ok "All prerequisites found."

# ── Kind cluster ──────────────────────────────────────────────────────────────
if kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
  ok "Kind cluster '${CLUSTER_NAME}' already exists — skipping creation."
else
  info "Creating Kind cluster '${CLUSTER_NAME}'..."
  kind create cluster \
    --name "${CLUSTER_NAME}" \
    --config "${DEPLOY_DIR}/kind-config.yaml" \
    --wait 60s
  ok "Kind cluster created."
fi

# Point kubectl at the Kind cluster
kubectl config use-context "kind-${CLUSTER_NAME}" &>/dev/null

# ── Namespace ─────────────────────────────────────────────────────────────────
info "Creating namespace '${NAMESPACE}'..."
kubectl apply -f "${DEPLOY_DIR}/manifests/namespace.yaml"

# ── Temporal (via official Helm chart) ───────────────────────────────────────
info "Adding temporalio Helm repo..."
helm repo add temporalio https://go.temporal.io/helm-charts 2>/dev/null || true
helm repo update temporalio

info "Installing Temporal (this takes ~60s on first run)..."
helm upgrade --install temporal temporalio/temporal \
  --namespace "${NAMESPACE}" \
  --set server.replicaCount=1 \
  --set cassandra.config.cluster_size=1 \
  --set elasticsearch.enabled=false \
  --set prometheus.enabled=false \
  --set grafana.enabled=false \
  --timeout 300s \
  --wait
ok "Temporal deployed."

# ── RustFS (S3-compatible object store) ───────────────────────────────────────
info "Deploying RustFS..."
kubectl apply -f "${DEPLOY_DIR}/manifests/rustfs/" --namespace "${NAMESPACE}"
kubectl rollout status deployment/rustfs -n "${NAMESPACE}" --timeout=90s
ok "RustFS deployed."

# ── Ollama ────────────────────────────────────────────────────────────────────
info "Deploying Ollama (init container will pull the model on first start)..."
kubectl apply -f "${DEPLOY_DIR}/manifests/ollama/" --namespace "${NAMESPACE}"
# Don't wait here — model pull can take several minutes on first boot.
# Check progress with: kubectl logs -n sdlc deployment/ollama -c pull-model -f
ok "Ollama manifest applied. Model pull runs in the background — see 'make ollama-logs'."

# ── Agent deployments ─────────────────────────────────────────────────────────
# Load locally-built images into Kind (no-op if images don't exist yet)
for image in sdlc/orchestrator sdlc/requirements-agent sdlc/review-agent; do
  if docker image inspect "${image}:latest" &>/dev/null; then
    info "Loading image ${image}:latest into Kind..."
    kind load docker-image "${image}:latest" --name "${CLUSTER_NAME}"
  else
    warn "Image ${image}:latest not found locally — run 'make build' then 'make load'."
  fi
done

info "Applying agent manifests..."
for agent in orchestrator requirements-agent review-agent; do
  if ls "${DEPLOY_DIR}/manifests/${agent}/"*.yaml &>/dev/null; then
    kubectl apply -f "${DEPLOY_DIR}/manifests/${agent}/" --namespace "${NAMESPACE}"
  fi
done
ok "Agent manifests applied."

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "======================================================================"
echo "  Cluster '${CLUSTER_NAME}' is ready."
echo ""
echo "  Temporal UI:   http://localhost:8233"
echo "  RustFS console: http://localhost:9001  (user: rustfsadmin / rustfsadmin)"
echo "  Temporal gRPC: localhost:7233"
echo "  Ollama API:    http://localhost:11434  (model pull may still be in progress)"
echo ""
echo "  Next steps:"
echo "    1. Create credentials secrets:  make secrets-template"
echo "    2. Run a worker locally:        make dev-requirements"
echo "    3. Trigger a workflow:          make trigger"
echo "======================================================================"
