# Requirements Workflow

Fetches a Jira epic and produces a structured requirement specification. Implemented by `RequirementsWorkflow` in `agents/requirements_agent/workflows.py`.

For project setup see [../../README.md](../../README.md).

## Trigger

- **Task type:** `requirements`
- **Required field:** `jira_epic_id` (Jira epic key or URL; the trigger script parses URLs via `parse_issue_key`)

Dispatched by the orchestrator to the `requirements-agent` task queue with a 10-minute execution timeout.

## Activity Chain

### 1. `fetch_jira_epic`

- **Timeout:** 30 s
- **Retry:** standard (3 attempts, 2 s initial, 2x backoff)
- Calls the Jira client to retrieve the epic, its parent context, and child stories.
- **Output:** `JiraEpic`

### 2. `produce_spec`

- **Timeout:** 10 min
- **Retry:** LLM (5 attempts, 5 s initial, 2x backoff)
- Renders the `requirements_agent/produce_spec.md` prompt template with epic data.
- LLM decomposes the epic into stories with acceptance criteria.
- **Output:** `RequirementSpec`

### 3. `store_spec`

- **Timeout:** 30 s
- **Retry:** standard
- Serialises the `RequirementSpec` to JSON and uploads to S3.
- **Artifact key:** `runs/{run_id}/requirement-spec.json`

## Models

### `JiraEpic` (input to `produce_spec`)

| Field | Type |
|---|---|
| `key` | `str` |
| `summary` | `str` |
| `description` | `str \| None` |
| `stories` | `list[JiraStory]` |
| `parent_key` | `str \| None` |
| `parent_summary` | `str \| None` |
| `parent_description` | `str \| None` |
| `target_ocp_version` | `str \| None` |

### `RequirementSpec` (output)

| Field | Type |
|---|---|
| `epic_id` | `str` |
| `title` | `str` |
| `stories` | `list[Story]` |
| `acceptance_criteria` | `list[str]` |
| `artifact_ref` | `str` |
