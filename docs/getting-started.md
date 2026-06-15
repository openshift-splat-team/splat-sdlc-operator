# Getting Started

Get a workflow running in 5 minutes. For prerequisites (podman, podman-compose,
uv) and full setup details, see the [project README](../README.md).

## Quick Start

### 1. Clone and configure

```bash
git clone <repo-url>
cd agent-sdlc-workflow
cp .env.example .env
```

Edit `.env` if you want to use a cloud LLM provider. The defaults use Ollama
(bundled in the compose stack).

### 2. Start the stack

```bash
make dev
```

First run takes a few minutes while Ollama downloads the configured model. All
services start automatically: Temporal, RustFS, Ollama, Gitea, Jira simulator,
dep-tree MCP server, and all six agent workers.

### 3. Set up simulators

Run all setup steps in one shot:

```bash
make setup              # gitea-setup → gitea-seed-repos → gitea-reviewer → jira-seed → gitea-token
```

Or run them individually:

```bash
make gitea-setup        # create admin user, API token, staging org
make gitea-seed-repos   # create staging repositories
make jira-seed          # import test data into Jira simulator
```

Copy the printed Gitea token into your `.env` as `GITHUB_TOKEN`.

### 4. Trigger a workflow

```bash
make dev-trigger
```

Follow the interactive prompts. Select `full_sdlc` for the complete end-to-end
flow, or a narrower task type for specific phases.

## Service URLs

Once the stack is running:

| Service | URL | Credentials |
|---|---|---|
| Temporal UI | http://localhost:8233 | -- |
| RustFS Console | http://localhost:9001 | rustfsadmin / rustfsadmin |
| Ollama API | http://localhost:11434 | -- |
| Gitea | http://localhost:3000 | gitea / gitea123 |
| Jira Simulator | http://localhost:8080 | -- |

## Seed Test Data (Optional)

```bash
make jira-seed          # import test_data/*.xlsx into the Jira simulator
```

## Next Steps

- [Architecture](architecture.md) -- understand the system design
- [LLM Providers](configuration/llm-providers.md) -- switch models or use cloud providers
- [Gitea Simulator](simulators/gitea.md) -- detailed Gitea setup and usage
- [Jira Simulator](simulators/jira.md) -- detailed Jira simulator guide
- [Monitoring](operations/monitoring.md) -- observe running workflows
