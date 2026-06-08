.PHONY: dev dev-down dev-build dev-logs dev-reload dev-rebuild dev-restart dev-trigger \
        gitea-token gitea-setup gitea-seed-repos gitea-mirror-repo gitea-reviewer \
        jira-seed jira-seed-force \
        cluster cluster-down cluster-status build load deploy rollout \
        ollama-logs ollama-model \
        port-forward dev-orchestrator dev-requirements dev-github trigger \
        trigger-enhancement-review \
        test test-integration lint fmt secrets-template clean

CLUSTER_NAME  := sdlc
NAMESPACE     := sdlc
IMAGES        := sdlc/base sdlc/orchestrator sdlc/requirements-agent sdlc/github-agent sdlc/openshift-agent
COMPOSE       := podman-compose

# ── Local dev (compose) ───────────────────────────────────────────────────────

WORKERS := orchestrator requirements-agent github-agent openshift-agent jira-agent enhancement-agent

dev: dev-build
	$(COMPOSE) up

dev-down:
	$(COMPOSE) down

dev-build:
	$(COMPOSE) build

dev-logs:
	$(COMPOSE) logs -f

# Restart only the worker containers (picks up code changes via bind mounts).
# Infrastructure (Temporal, RustFS, Gitea, Ollama) stays running.
dev-reload:
	$(COMPOSE) restart $(WORKERS)

# Rebuild and restart workers only (needed after pyproject.toml / uv.lock changes).
dev-rebuild:
	$(COMPOSE) build $(WORKERS)
	$(COMPOSE) up -d $(WORKERS)

# Restart a single worker: make dev-restart W=orchestrator
dev-restart:
ifndef W
	@echo "Usage: make dev-restart W=<worker>"; echo "Workers: $(WORKERS)"; exit 1
else
	$(COMPOSE) restart $(W)
endif

# Run trigger script inside the compose network
dev-trigger:
	$(COMPOSE) run --rm orchestrator python scripts/trigger.py

# ── Gitea (local GitHub simulator) ───────────────────────────────────────────
# Run once after 'make dev':
#   1. make gitea-setup      — create admin user, API token, orgs
#   2. make gitea-seed-repos — create source repos the workflows fork/PR against
# Uses exec inside the running container to avoid SQLite lock issues.

gitea-setup:  ## Initialise Gitea: create admin user, API token, and staging org
	@$(COMPOSE) exec --user 1000 gitea sh -c '\
	  GITEA_WORK_DIR=/data gitea admin user create \
	    --username gitea --password gitea123 \
	    --email admin@gitea.local --admin 2>&1 | grep -v "already exists" || true; \
	  TOKEN=$$(cat /data/gitea/gitea-token.txt 2>/dev/null | tr -d "[:space:]"); \
	  if [ -z "$$TOKEN" ]; then \
	    EXISTING_ID=$$(curl -s -u gitea:gitea123 http://localhost:3000/api/v1/users/gitea/tokens \
	      | sed "s/.*\"id\":\([0-9]*\),\"name\":\"sdlc-agent\".*/\1/" | grep -E "^[0-9]+$$" | head -1); \
	    if [ -n "$$EXISTING_ID" ]; then \
	      curl -s -X DELETE -u gitea:gitea123 "http://localhost:3000/api/v1/users/gitea/tokens/$$EXISTING_ID"; \
	    fi; \
	    RESP=$$(curl -s -X POST http://localhost:3000/api/v1/users/gitea/tokens \
	      -u gitea:gitea123 -H "Content-Type: application/json" \
	      -d "{\"name\":\"sdlc-agent\",\"scopes\":[\"write:repository\",\"write:issue\",\"write:organization\",\"read:user\"]}"); \
	    TOKEN=$$(echo "$$RESP" | sed "s/.*\"sha1\":\"\([^\"]*\)\".*/\1/" | grep -v "^{"); \
	    printf "%s" "$$TOKEN" > /data/gitea/gitea-token.txt; \
	    echo "[gitea-setup] Token created"; \
	  else \
	    echo "[gitea-setup] Token already exists"; \
	  fi; \
	  curl -s -X POST http://localhost:3000/api/v1/orgs \
	    -u gitea:gitea123 -H "Content-Type: application/json" \
	    -d "{\"username\":\"staging\",\"visibility\":\"private\"}" > /dev/null 2>&1 || true; \
	  echo "[gitea-setup] Done. Run: make gitea-token"'

gitea-reviewer:  ## Create a 'reviewer' user for manual PR reviews (login: reviewer / reviewer123)
	@curl -sf -u gitea:gitea123 http://localhost:3000/api/v1/admin/users \
	  -H "Content-Type: application/json" \
	  -d '{"username":"reviewer","password":"reviewer123","email":"reviewer@gitea.local","must_change_password":false}' > /dev/null 2>&1 \
	  && echo "[gitea-reviewer] User 'reviewer' created" \
	  || echo "[gitea-reviewer] User 'reviewer' already exists"; \
	TEAM_ID=$$(curl -s -u gitea:gitea123 http://localhost:3000/api/v1/orgs/openshift-splat-team/teams \
	  | python3 -c "import sys,json; print(next(t['id'] for t in json.load(sys.stdin) if t['name']=='Owners'))"); \
	curl -sf -u gitea:gitea123 -X PUT "http://localhost:3000/api/v1/teams/$$TEAM_ID/members/reviewer" > /dev/null 2>&1; \
	echo "[gitea-reviewer] Added to openshift-splat-team/Owners"; \
	echo "[gitea-reviewer] Login: http://localhost:3000  reviewer / reviewer123"

gitea-seed-repos:  ## Create orgs and staging repos in Gitea (openshift/* repos are mirrored on demand by the workflow)
	@TOKEN=$$($(COMPOSE) exec gitea cat /data/gitea/gitea-token.txt 2>/dev/null | tr -d '[:space:]'); \
	if [ -z "$$TOKEN" ]; then echo "No token — run 'make gitea-setup' first."; exit 1; fi; \
	BASE=http://localhost:3000/api/v1; \
	for org in openshift openshift-splat-team; do \
	  curl -s -X POST "$$BASE/orgs" -H "Authorization: token $$TOKEN" \
	    -H "Content-Type: application/json" \
	    -d "{\"username\":\"$$org\",\"visibility\":\"public\"}" > /dev/null 2>&1 || true; \
	  echo "[gitea-seed-repos] org: $$org"; \
	done; \
	curl -s -X POST "$$BASE/orgs/openshift-splat-team/repos" -H "Authorization: token $$TOKEN" \
	  -H "Content-Type: application/json" \
	  -d "{\"name\":\"enhancements\",\"private\":false,\"default_branch\":\"main\",\"auto_init\":true}" > /dev/null 2>&1 || true; \
	echo "[gitea-seed-repos] local repo: openshift-splat-team/enhancements"; \
	echo "[gitea-seed-repos] Done. openshift/* repos are mirrored from GitHub on demand by ForkReposWorkflow."

# Print the Gitea API token (set as GITHUB_TOKEN in .env to use Gitea)
gitea-token:  ## Print Gitea API token (paste into .env as GITHUB_TOKEN)
	@$(COMPOSE) exec gitea cat /data/gitea/gitea-token.txt 2>/dev/null || \
	  echo "No token found — run 'make gitea-setup' first."

gitea-mirror-repo:  ## Mirror a GitHub repo into Gitea: make gitea-mirror-repo REPO=owner/name
ifndef REPO
	$(error REPO is required — e.g.: make gitea-mirror-repo REPO=openshift/enhancements)
endif
	@TOKEN=$$($(COMPOSE) exec gitea cat /data/gitea/gitea-token.txt 2>/dev/null | tr -d '[:space:]'); \
	if [ -z "$$TOKEN" ]; then echo "No token — run 'make gitea-setup' first."; exit 1; fi; \
	ORG=$$(echo "$(REPO)" | cut -d/ -f1); \
	REPO_NAME=$$(echo "$(REPO)" | cut -d/ -f2); \
	BASE=http://localhost:3000/api/v1; \
	echo "[gitea-mirror-repo] Ensuring org $$ORG exists..."; \
	curl -s -X POST "$$BASE/orgs" -H "Authorization: token $$TOKEN" \
	  -H "Content-Type: application/json" \
	  -d "{\"username\":\"$$ORG\",\"visibility\":\"public\"}" > /dev/null 2>&1 || true; \
	echo "[gitea-mirror-repo] Mirroring github.com/$(REPO)..."; \
	TMPFILE=$$(mktemp); \
	HTTP_CODE=$$(curl -s -o "$$TMPFILE" -w "%{http_code}" -X POST "$$BASE/repos/migrate" \
	  -H "Authorization: token $$TOKEN" \
	  -H "Content-Type: application/json" \
	  -d "{\"clone_addr\":\"https://github.com/$(REPO)\",\"repo_name\":\"$$REPO_NAME\",\"repo_owner\":\"$$ORG\",\"mirror\":true,\"mirror_interval\":\"8h\",\"private\":false}"); \
	if [ "$$HTTP_CODE" = "201" ]; then \
	  echo "[gitea-mirror-repo] Mirror created: http://localhost:3000/$(REPO)"; \
	elif [ "$$HTTP_CODE" = "409" ]; then \
	  echo "[gitea-mirror-repo] Already mirrored: http://localhost:3000/$(REPO)"; \
	else \
	  echo "[gitea-mirror-repo] Error (HTTP $$HTTP_CODE):"; \
	  cat "$$TMPFILE"; echo; rm -f "$$TMPFILE"; exit 1; \
	fi; \
	rm -f "$$TMPFILE"

# ── Jira simulator seed ───────────────────────────────────────────────────────

# Import xlsx exports from test_data/ into the running Jira simulator.
# Idempotent — already-existing issues are skipped.
# Requires: make dev  (jira-simulator must be running)
jira-seed:  ## Import test_data/*.xlsx into the local Jira simulator (skips existing)
	uv run python scripts/jira_seed.py

jira-seed-force:  ## Re-import test_data/*.xlsx, overwriting existing issues and labels
	uv run python scripts/jira_seed.py --force

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
	kubectl apply -f deploy/manifests/rustfs/ -n $(NAMESPACE)
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
	kubectl port-forward -n $(NAMESPACE) svc/rustfs 9000:9000 9001:9001 &
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
	uv run --extra dev python scripts/trigger.py full_sdlc

trigger-enhancement-review:
	uv run --extra dev python scripts/trigger.py enhancement_review

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
	@echo "kubectl create secret generic s3-credentials \\"
	@echo "  --namespace $(NAMESPACE) \\"
	@echo "  --from-literal=S3_ACCESS_KEY=rustfsadmin \\"
	@echo "  --from-literal=S3_SECRET_KEY=rustfsadmin \\"
	@echo "  --from-literal=S3_BUCKET=sdlc-artifacts"
	@echo ""

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
