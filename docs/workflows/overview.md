# Workflow Overview

For project setup, architecture, and environment configuration see [../../README.md](../../README.md).

## Task Types

The orchestrator (`SDLCOrchestratorWorkflow`) dispatches work based on the `task_type` field of a `WorkflowTrigger`. Seven task types are supported:

| Task Type | Description | Agent / Task Queue | Input Model | Doc |
|---|---|---|---|---|
| `requirements` | Produce a structured requirement spec from a Jira epic | `requirements-agent` | `jira_epic_id` (string) | [requirements.md](requirements.md) |
| `review` | LLM-review a pull request and post inline comments | `github-agent` | `github_pr_url` (string) | [review.md](review.md) |
| `create_pr` | Open a pull request on GitHub/Gitea | `github-agent` | `CreatePRInput` | [create-pr.md](create-pr.md) |
| `openshift_feature` | Analyse an OpenShift feature and produce an implementation plan | `openshift-agent` | `OpenShiftFeatureInput` | [openshift-feature.md](openshift-feature.md) |
| `full_sdlc` | End-to-end feature lifecycle with human gates | `orchestrator` | `SDLCFeatureInput` | [full-sdlc.md](full-sdlc.md) |
| `implement_feature` | Generate code across repos from a staging plan | `github-agent` | `ImplementFeatureInput` | [implement-feature.md](implement-feature.md) |
| `enhancement_review` | Re-enter the enhancement review cycle for a previous run | `enhancement-agent` | `EnhancementReviewInput` | [enhancement-review.md](enhancement-review.md) |

All input models are defined in `agents/common/models.py`. The task type literal is enforced by the `WorkflowTrigger.task_type` field.

## How to Trigger

### Interactive (inside Compose)

```bash
make dev-trigger
```

This runs `scripts/trigger.py` inside the compose network. The script prompts for `task_type` and the fields relevant to that type, then starts `SDLCOrchestratorWorkflow` on the Temporal server.

### CLI shortcut

```bash
# Pass task type as first argument to skip the prompt
make dev-trigger ARGS="full_sdlc"
```

### Programmatic

```python
from agents.common.models import WorkflowTrigger
from agents.orchestrator.workflows import SDLCOrchestratorWorkflow

trigger = WorkflowTrigger(
    task_type="requirements",
    jira_epic_id="OCPBUGS-1234",
    run_id="my-run-001",
)
await client.start_workflow(SDLCOrchestratorWorkflow.run, trigger, id=trigger.run_id, task_queue="orchestrator")
```

## Artifact Storage

Every workflow stores its output as a JSON artifact in S3 (MinIO) under the key pattern `runs/{run_id}/<artifact>.json`. The artifact key is returned in `WorkflowResult.artifact_ref`.
