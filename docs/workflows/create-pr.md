# Create PR Workflow

Opens a pull request on GitHub/Gitea and stores the result. Implemented by `CreatePRWorkflow` in `agents/github_agent/workflows.py`.

For project setup see [../../README.md](../../README.md).

## Trigger

- **Task type:** `create_pr`
- **Required field:** `github_create_pr` (`CreatePRInput` object on the `WorkflowTrigger`)

Dispatched by the orchestrator to the `github-agent` task queue with a 5-minute execution timeout.

## Input Model -- `CreatePRInput`

| Field | Type | Default | Description |
|---|---|---|---|
| `repo` | `str` | required | `owner/repo` slug (e.g. `acme/my-service`) |
| `head_branch` | `str` | required | Branch containing the changes |
| `base_branch` | `str` | `"main"` | Target branch for the PR |
| `title` | `str` | required | PR title |
| `body` | `str` | `""` | PR body |
| `draft` | `bool` | `False` | Open as draft PR |
| `jira_issue_key` | `str \| None` | `None` | If set, prepended to title and linked in body |

## Activity Chain

### 1. `create_pr`

- **Timeout:** 30 s
- **Retry:** standard (3 attempts, 2 s initial, 2x backoff)
- Calls `github_client.create_pr` with the input.
- **Output:** `CreatedPR`

### 2. `store_created_pr`

- **Timeout:** 30 s
- **Retry:** standard
- Serialises the `CreatedPR` to JSON and uploads to S3.
- **Artifact key:** `runs/{run_id}/created-pr.json`

## Output Model -- `CreatedPR`

| Field | Type |
|---|---|
| `url` | `str` |
| `number` | `int` |
| `title` | `str` |
| `head_branch` | `str` |
| `base_branch` | `str` |
| `draft` | `bool` |
| `artifact_ref` | `str` |
