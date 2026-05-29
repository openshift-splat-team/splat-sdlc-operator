# Agent SDLC Workflow

Hierarchical LLM agents for automating the full OpenShift feature SDLC, powered by [Temporal](https://temporal.io/) and [LiteLLM](https://github.com/BerriAI/litellm).

## Architecture

```
Trigger (CLI / future: webhook)
  └── SDLCOrchestratorWorkflow  [task_queue: orchestrator]
        │
        ├── FullSDLCWorkflow                          full end-to-end OpenShift feature flow
        │     ├── EnsureEpicWorkflow                  [jira-agent]       fetch or create Jira epic
        │     ├── OpenShiftFeatureWorkflow             [openshift-agent]  identify affected repos, produce plan
        │     ├── EnhancementWorkflow                  [enhancement-agent] generate & PR enhancement doc
        │     ├── WaitForEnhancementApprovalWorkflow   [enhancement-agent] poll PR until approved or closed
        │     ├── StoryRefinementWorkflow              [jira-agent]       propose stories, iterate with humans
        │     ├── CreateStoriesWorkflow                [jira-agent]       create, size, prioritize, link stories
        │     ├── SetupStagingReposWorkflow            [github-agent]     fork repos, create branches & PRs
        │     └── MonitorPRWorkflow (×N)               [github-agent]     watch agent-hold label, process comments
        │
        ├── RequirementsWorkflow  [requirements-agent]
        │     fetch_jira_epic → produce_spec (LLM) → store to MinIO
        ├── ReviewWorkflow        [github-agent]
        │     fetch_pr → run_review (LLM) → post_comments → store to MinIO
        ├── CreatePRWorkflow      [github-agent]
        │     create_pr → store to MinIO
        └── OpenShiftFeatureWorkflow  [openshift-agent]
              identify_repos → fetch_context → analyze (LLM) → ci_requirements → store to MinIO
```

LiteLLM abstracts all LLM calls — swap providers (OpenAI, Anthropic, Ollama, etc.) via the `LITELLM_MODEL` env var with no code changes.

## Full SDLC Flow

The `full_sdlc` task type runs the complete OpenShift feature development workflow. Phases execute sequentially; human approval gates pause the workflow until a human acts.

```
  Jira epic URL or key
           │
           ▼
┌─────────────────────────────────────────────────────┐
│  Phase A · EnsureEpicWorkflow          [jira-agent] │
│  Fetch existing epic or create a new one            │
└─────────────────────┬───────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────┐
│  Phase B · OpenShiftFeatureWorkflow [openshift-agent]│
│  Identify affected repos, produce implementation    │
│  plan, determine CI requirements                    │
└─────────────────────┬───────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────┐
│  Phase C · EnhancementWorkflow   [enhancement-agent]│
│  Generate OpenShift enhancement doc (LLM)           │
│  Fork enhancements repo → commit doc → open PR      │
│  Create design-doc-review story in Jira             │
└─────────────────────┬───────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────┐
│ ⏸ Phase D · WaitForEnhancementApproval  [HUMAN GATE]│
│  Poll PR every 5 min until:                         │
│    approved → continue to Phase E                   │
│    closed   → mark story "Won't Do" and exit        │
└─────────────────────┬───────────────────────────────┘
                      │ approved
                      ▼
┌─────────────────────────────────────────────────────┐
│  Phase E · StoryRefinementWorkflow     [jira-agent] │
│  LLM proposes sized & prioritized stories           │
│  Post proposals as Jira comment                     │
│                                                     │
│ ⏸ [HUMAN GATE] Poll epic comments every 5 min       │
│    new comments → LLM refines plan → re-post        │
│    "stories approved" comment → continue            │
└─────────────────────┬───────────────────────────────┘
                      │ stories approved
                      ▼
┌─────────────────────────────────────────────────────┐
│  Phase F · CreateStoriesWorkflow       [jira-agent] │
│  Create stories in Jira                             │
│  Set story points, priority, dependency links       │
└─────────────────────┬───────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────┐
│  Phase G · SetupStagingReposWorkflow  [github-agent]│
│  For each affected repo (concurrently):             │
│    Fork to staging org (sync main if fork exists)   │
│    Create feature branch                            │
│    Open draft PR  →  add "agent-hold" label         │
└─────────────────────┬───────────────────────────────┘
                      │
                      ▼ (one child workflow per repo, fire-and-forget)
┌─────────────────────────────────────────────────────┐
│  Phase H · MonitorPRWorkflow ×N       [github-agent]│
│  Poll PR every 5 min (runs up to 90 days)           │
│                                                     │
│ ⏸ [HUMAN GATE] agent-hold label dropped?            │
│    yes → LLM processes review comments              │
│          post response → re-add agent-hold          │
│    PR closed/merged → monitor exits                 │
└─────────────────────────────────────────────────────┘
```

Human approval gates (`⏸`) are implemented as Temporal `wait_condition` polling loops — workers are never blocked; the workflow sleeps between polls and resumes durably across restarts.

## Two environments

| | Local dev | Integration / pre-deploy |
|---|---|---|
| **Command** | `make dev` | `make cluster` |
| **Tool** | podman-compose | Kind + kubectl + helm |
| **Startup** | ~1 min + model pull | ~5 min (first run) |
| **Workers** | Containers in compose | Pods in Kubernetes |
| **Use for** | Day-to-day development | Testing k8s manifests and NetworkPolicies |

---

## Prerequisites

```bash
# podman + podman-compose (local dev)
# On Fedora/RHEL:
sudo dnf install podman podman-compose

# uv (Python package manager)
curl -Ls https://astral.sh/uv/install.sh | sh

# Kind + kubectl + helm (integration testing only)
# kind:    https://kind.sigs.k8s.io/docs/user/quick-start/#installation
# kubectl: https://kubernetes.io/docs/tasks/tools/
# helm:    https://helm.sh/docs/intro/install/
```

---

## Local dev setup (podman-compose)

### 1. Clone and configure

```bash
git clone <repo>
cd agent-sdlc-workflow
cp .env.example .env
```

Edit `.env` — at minimum fill in your credentials. The default is Ollama with Qwen2.5 7B (no API key needed):

```bash
LITELLM_MODEL=ollama/qwen2.5:7b-instruct-q4_K_M   # pulled automatically on first start
# LLM_API_KEY=                                      # not needed for Ollama

GITHUB_TOKEN=ghp_...
STAGING_GITHUB_ORG=your-staging-org                 # GitHub org where forks are created
JIRA_URL=https://yourorg.atlassian.net
JIRA_USER=user@example.com
JIRA_TOKEN=...
```

See `.env.example` for alternative LLM providers (OpenAI, Anthropic, Azure) and recommended CPU-only Ollama models.

### 2. Start everything

```bash
make dev
```

This starts PostgreSQL (Temporal backend), Temporal, MinIO, Ollama, pulls the configured model, then starts all workers. First run takes a few minutes while Ollama downloads the model.

```
  Temporal UI:   http://localhost:8233
  MinIO console: http://localhost:9001  (minioadmin / minioadmin)
  Ollama API:    http://localhost:11434
```

> **Podman DNS note:** If containers can't resolve each other by hostname, aardvark-dns may be stuck. Fix with:
> ```bash
> make dev-down
> podman network rm agent-sdlc-workflow_sdlc 2>/dev/null
> pkill -9 aardvark-dns 2>/dev/null
> rm -rf /run/user/$(id -u)/containers/networks/aardvark-dns
> make dev
> ```

### 3. Trigger a workflow

In a second terminal:

```bash
make dev-trigger
```

Follow the prompts, then watch the workflow in the Temporal UI at **http://localhost:8233**.

For a full end-to-end SDLC run, select `full_sdlc` and provide:
- `feature_description` — plain-text description of the OpenShift feature
- `staging_github_org` — your staging GitHub org (forks land here)
- `jira_epic_id` — optional; creates a new epic if omitted

### 4. Stop

```bash
make dev-down
```

The `ollama-data` volume persists the downloaded model so subsequent `make dev` starts are fast.

---

## Integration testing (Kind)

Use this when testing Kubernetes manifests, NetworkPolicies, or production-like deployment config.

```bash
make cluster          # one-time setup (~5 min first run)
make secrets-template # print kubectl commands to create secrets, then run them
make build            # build production Docker images
make load             # load images into Kind
make deploy           # apply all k8s manifests
```

Watch Ollama model pull (happens in an init container on first pod start):

```bash
make ollama-logs
```

Change the Ollama model without editing manifests:

```bash
make ollama-model     # prompts for model name, patches ConfigMap, restarts pod
```

Tear down:

```bash
make cluster-down
```

---

## Development workflow

```bash
make test       # unit tests (no cluster needed)
make lint       # ruff + mypy
make fmt        # auto-format
make dev-logs   # tail all compose service logs
```

Code changes to `agents/` and `prompts/` are picked up immediately by running workers (volume-mounted in compose). Dependency changes (`pyproject.toml`) require `make dev-build` to rebuild the image.

---

## Adding a new agent

1. Create `agents/<name>/` with `worker.py`, `workflows.py`, `activities.py`
2. Add a settings class in `agents/common/settings.py`
3. Add a service block to `compose.yaml` using the `x-worker` anchor
4. Add `deploy/manifests/<name>/deployment.yaml` and `networkpolicy.yaml`
5. Add `docker/<name>.Dockerfile` for production builds
6. Wire child workflow dispatch in `agents/orchestrator/workflows.py`

---

## Configuration

All config is via environment variables (`.env` for local dev, k8s Secrets for in-cluster).

| Variable | Description |
|---|---|
| `LITELLM_MODEL` | LiteLLM model string — e.g. `ollama/qwen2.5:7b-instruct-q4_K_M`, `openai/gpt-4o`, `anthropic/claude-sonnet-4-6` |
| `LLM_API_KEY` | API key for the LLM provider (not required for Ollama) |
| `LLM_API_BASE` | Override LLM API base URL (set automatically in compose and k8s manifests) |
| `GITHUB_TOKEN` | GitHub PAT with `repo` scope (github-agent, enhancement-agent) |
| `STAGING_GITHUB_ORG` | GitHub org where repository forks are created |
| `JIRA_URL` / `JIRA_USER` / `JIRA_TOKEN` | Jira credentials (requirements-agent, jira-agent) |
| `ENHANCEMENT_REPO` | Enhancement proposals repo, default `openshift-splat-team/enhancements` |
| `MINIO_ENDPOINT` | MinIO API address |
