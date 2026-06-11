# Agent SDLC Workflow -- Documentation

Agent SDLC Workflow is a Temporal-based multi-agent system that automates the
OpenShift software development lifecycle. Six specialized agents -- orchestrator,
requirements, GitHub, OpenShift, Jira, and enhancement -- collaborate through
Temporal workflows to take a feature from a Jira epic through design documents,
story creation, code implementation, and pull-request review.

See the [project README](../README.md) for a quick overview and full setup
instructions.

---

## Table of Contents

### Getting Started

- [Quickstart](getting-started.md) -- get a workflow running in 5 minutes

### Architecture

- [Architecture Deep Dive](architecture.md) -- system design, data flow, and infrastructure

### Agents

- [Agent Overview](agents/overview.md) -- responsibilities, task queues, and activities for each agent
- [Adding an Agent](agents/adding-an-agent.md) -- step-by-step guide to creating a new agent
- [Adding a Workflow Task Type](agents/adding-a-workflow.md) -- how to add a new orchestrator task type

### Workflows

- [Workflow Overview](workflows/overview.md) -- task types, triggering, and artifact storage
- [Full SDLC](workflows/full-sdlc.md) -- end-to-end OpenShift feature flow (Phases A--J)
- [Requirements](workflows/requirements.md) -- Jira epic to structured requirement spec
- [PR Review](workflows/review.md) -- LLM-powered code review
- [Create PR](workflows/create-pr.md) -- open a pull request with optional Jira linking
- [OpenShift Feature](workflows/openshift-feature.md) -- repo identification and implementation planning
- [Enhancement Review](workflows/enhancement-review.md) -- revise enhancement doc from PR comments
- [Implement Feature](workflows/implement-feature.md) -- LLM code generation per repo in dependency order

### Configuration

- [LLM Providers](configuration/llm-providers.md) -- model routing, per-agent overrides, structured output
- [Artifact Storage](configuration/artifact-storage.md) -- S3 storage, key patterns, agent memory

### Prompts

- [Prompt Template Guide](prompts/guide.md) -- template format, inventory, and how to add new prompts

### Operations

- [Monitoring](operations/monitoring.md) -- Temporal UI, worker logs, workflow states
- [Troubleshooting](operations/troubleshooting.md) -- common errors, restarts, resets

### Simulators

- [Gitea](simulators/gitea.md) -- local GitHub-compatible Git server
- [Jira Simulator](simulators/jira.md) -- minimal Jira REST API with SQLite backend
