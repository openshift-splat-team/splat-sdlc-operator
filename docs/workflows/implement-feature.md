# Implement Feature Workflow

Generates and commits code changes across all repos for a feature, one PR per repo. Implemented by `ImplementFeatureWorkflow` and `CodeGenerationWorkflow` in `agents/github_agent/workflows.py`.

For project setup see [../../README.md](../../README.md).

## Trigger

### Standalone task type

- **Task type:** `implement_feature`
- **Required field:** `implement_feature` (`ImplementFeatureInput` on the `WorkflowTrigger`)

The orchestrator loads the `StagingPlan` and `OpenShiftFeaturePlan` from S3 using the artifact refs, then dispatches `ImplementFeatureWorkflow` to the `github-agent` task queue with a 4-hour timeout.

### As Phase H of `full_sdlc`

Called directly by `FullSDLCWorkflow` with the `StagingPlan` and `OpenShiftFeaturePlan` already in memory.

## Input Model -- `ImplementFeatureInput`

| Field | Type | Description |
|---|---|---|
| `feature_id` | `str` | Unique feature identifier |
| `staging_plan_ref` | `str` | S3 artifact key for the `StagingPlan` |
| `feature_plan_ref` | `str` | S3 artifact key for the `OpenShiftFeaturePlan` |
| `feature_description` | `str` | Natural-language feature description |

## Step Grouping -- `_group_steps_by_repo`

Before execution, all `PRStep` entries from the feature plan are grouped by repository into `RepoPRBundle` objects:

- **Steps** are sorted by `step` number within each bundle.
- **Risk** is the maximum risk across all steps in the bundle (`low` < `medium` < `high`).
- **CI requirements** are deduplicated across steps.
- **Cross-repo blockers** are derived: if a step's `blocked_by_step` belongs to a different repo, that repo is added to `blocked_by_repos`.

### `RepoPRBundle` Fields

| Field | Type |
|---|---|
| `repo` | `str` |
| `tier` | `str` |
| `steps` | `list[PRStep]` |
| `risk` | `"low" \| "medium" \| "high"` |
| `ci_requirements` | `list[str]` |
| `blocked_by_repos` | `list[str]` |

## Dependency-Ordered Execution

`ImplementFeatureWorkflow` processes bundles in waves:

1. Builds a lookup `staging_by_repo` mapping `"org/repo"` to `StagingRepo`.
2. Each iteration selects **ready** bundles: not yet completed, present in the staging plan, and all `blocked_by_repos` already completed.
3. Ready bundles run as **concurrent child workflows** (`CodeGenerationWorkflow`) via `asyncio.gather`.
4. After a wave completes, its repos are added to `completed_repos` and the next wave begins.
5. Bundles with no matching staging repo are silently skipped.
6. If no bundle is ready and unblocked repos remain, raises `NondeterminismError` (deadlock).

## CodeGenerationWorkflow (per repo)

Each `CodeGenerationWorkflow` child runs on the `github-agent` task queue with a 1-hour timeout:

### 1. `fetch_repo_context`

- **Timeout:** 60 s
- Fetches the source repo's structure from GitHub (org, repo, main branch).

### 2. `generate_code_for_bundle`

- **Timeout:** 10 min
- **Retry:** LLM (5 attempts, 5 s initial, 2x backoff)
- Passes the `RepoPRBundle`, feature description, and repo context to the LLM.
- Returns a list of `FileChange` objects (path, content, commit_message).

### 3. `apply_file_changes`

- **Timeout:** 5 min
- **Retry:** standard (3 attempts)
- Commits each file change to the staging repo's feature branch.
- Skipped if no file changes were generated.

### 4. `update_pr_description`

- **Timeout:** 30 s
- Updates the staging PR body with the code generation result.

### 5. `remove_agent_hold`

- **Timeout:** 30 s
- Removes the `agent-hold` label from the staging PR, signalling that the PR is ready for review.

## Output

### `CodeGenerationResult`

| Field | Type |
|---|---|
| `repo` | `str` |
| `files_changed` | `list[str]` |
| `commit_messages` | `list[str]` |

### `FeatureImplementationResult`

| Field | Type |
|---|---|
| `feature_id` | `str` |
| `results` | `list[CodeGenerationResult]` |
| `artifact_ref` | `str` |

**Artifact key:** `runs/{run_id}/impl-result.json`
