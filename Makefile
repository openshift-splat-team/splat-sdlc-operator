.PHONY: dev dev-down dev-build dev-logs dev-trigger \
        cluster cluster-down cluster-status build load deploy rollout \
        ollama-logs ollama-model \
        port-forward dev-orchestrator dev-requirements dev-github trigger \
        test test-integration lint fmt secrets-template clean

CLUSTER_NAME  := sdlc
NAMESPACE     := sdlc
IMAGES        := sdlc/base sdlc/orchestrator sdlc/requirements-agent sdlc/github-agent sdlc/openshift-agent
COMPOSE       := podman-compose

# ── Local dev (compose) ───────────────────────────────────────────────────────

dev: dev-build
	$(COMPOSE) up

dev-down:
	$(COMPOSE) down

dev-build:
	$(COMPOSE) build

dev-logs:
	$(COMPOSE) logs -f

# Run trigger script inside the compose network
dev-trigger:
	$(COMPOSE) run --rm orchestrator python scripts/trigger.py

# ── Cluster lifecycle (Kind — integration / pre-deploy testing) ───────────────

cluster:
	bash deploy/scripts/setup-cluster.sh

cluster-down:
	kind delete cluster --name $(CLUSTER_NAME)

cluster-status:
	kubectl get pods -n $(NAMESPACE)

# ── Image management ──────────────────────────────────────────────────────────

build:
	docker build -f docker/base.Dockerfile              -t sdlc/base:latest              .
	docker build -f docker/orchestrator.Dockerfile      -t sdlc/orchestrator:latest      .
	docker build -f docker/requirements-agent.Dockerfile -t sdlc/requirements-agent:latest .
	docker build -f docker/github-agent.Dockerfile      -t sdlc/github-agent:latest      .
	docker build -f docker/openshift-agent.Dockerfile   -t sdlc/openshift-agent:latest   .

load:
	@for img in $(IMAGES); do \
	  echo "Loading $$img:latest into Kind..."; \
	  kind load docker-image $$img:latest --name $(CLUSTER_NAME); \
	done

push:
	@echo "Set REGISTRY and tag images before pushing to a remote registry."

# ── In-cluster deployment ─────────────────────────────────────────────────────

deploy:
	kubectl apply -f deploy/manifests/namespace.yaml
	kubectl apply -f deploy/manifests/minio/ -n $(NAMESPACE)
	kubectl apply -f deploy/manifests/orchestrator/ -n $(NAMESPACE)
	kubectl apply -f deploy/manifests/requirements-agent/ -n $(NAMESPACE)
	kubectl apply -f deploy/manifests/github-agent/ -n $(NAMESPACE)

rollout:
	kubectl rollout restart deployment -n $(NAMESPACE)

# Watch the Ollama model pull progress (init container)
ollama-logs:
	kubectl logs -n $(NAMESPACE) deployment/ollama -c pull-model -f

# Change the model without editing the manifest (triggers pod restart + re-pull)
ollama-model:
	@read -p "Model name (e.g. qwen2.5:3b): " model; \
	kubectl patch configmap ollama-config -n $(NAMESPACE) --type merge \
	  -p "{\"data\":{\"model\":\"$$model\"}}"; \
	kubectl rollout restart deployment/ollama -n $(NAMESPACE)

# ── Local dev (workers run on host, connect to Kind Temporal) ─────────────────

port-forward:
	@echo "Starting port-forwards (Ctrl-C to stop)..."
	kubectl port-forward -n $(NAMESPACE) svc/temporal-frontend 7233:7233 &
	kubectl port-forward -n $(NAMESPACE) svc/temporal-web 8233:8233 &
	kubectl port-forward -n $(NAMESPACE) svc/minio 9000:9000 9001:9001 &
	@wait

dev-orchestrator:
	uv run python -m agents.orchestrator.worker

dev-requirements:
	uv run python -m agents.requirements_agent.worker

dev-github:
	uv run python -m agents.github_agent.worker

dev-openshift:
	uv run python -m agents.openshift_agent.worker

trigger:
	uv run python scripts/trigger.py

# ── Testing ───────────────────────────────────────────────────────────────────

test:
	uv run pytest tests/unit -v

test-integration:
	uv run pytest tests/integration -v

# ── Code quality ──────────────────────────────────────────────────────────────

lint:
	uv run ruff check agents tests
	uv run mypy agents

fmt:
	uv run ruff format agents tests

# ── Housekeeping ──────────────────────────────────────────────────────────────

secrets-template:
	@echo ""
	@echo "Run the following to create Kubernetes secrets (substitute real values):"
	@echo ""
	@echo "kubectl create secret generic llm-credentials \\"
	@echo "  --namespace $(NAMESPACE) \\"
	@echo "  --from-literal=LLM_API_KEY=sk-... \\"
	@echo "  --from-literal=LITELLM_MODEL=openai/gpt-4o"
	@echo ""
	@echo "kubectl create secret generic github-credentials \\"
	@echo "  --namespace $(NAMESPACE) \\"
	@echo "  --from-literal=GITHUB_TOKEN=ghp_..."
	@echo ""
	@echo "kubectl create secret generic jira-credentials \\"
	@echo "  --namespace $(NAMESPACE) \\"
	@echo "  --from-literal=JIRA_URL=https://yourorg.atlassian.net \\"
	@echo "  --from-literal=JIRA_USER=user@example.com \\"
	@echo "  --from-literal=JIRA_TOKEN=..."
	@echo ""
	@echo "kubectl create secret generic minio-credentials \\"
	@echo "  --namespace $(NAMESPACE) \\"
	@echo "  --from-literal=MINIO_ACCESS_KEY=minioadmin \\"
	@echo "  --from-literal=MINIO_SECRET_KEY=minioadmin \\"
	@echo "  --from-literal=MINIO_BUCKET=sdlc-artifacts"
	@echo ""

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
