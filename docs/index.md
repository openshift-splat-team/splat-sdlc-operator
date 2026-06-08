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

### Configuration

- [LLM Providers](configuration/llm-providers.md) -- model routing, per-agent overrides, structured output
- [Artifact Storage](configuration/artifact-storage.md) -- S3 storage, key patterns, agent memory

### Operations

- [Monitoring](operations/monitoring.md) -- Temporal UI, worker logs, workflow states
- [Troubleshooting](operations/troubleshooting.md) -- common errors, restarts, resets

### Simulators

- [Gitea](simulators/gitea.md) -- local GitHub-compatible Git server
- [Jira Simulator](simulators/jira.md) -- minimal Jira REST API with SQLite backend
