# Enhancement Review Workflow

Re-enters the enhancement review cycle for a previous `full_sdlc` run, loading the feature plan artifact from that run. Managed by the orchestrator's `enhancement_review` branch and the `WaitForEnhancementApprovalWorkflow` in `agents/enhancement_agent/workflows.py`.

For project setup see [../../README.md](../../README.md).

## Trigger

- **Task type:** `enhancement_review`
- **Required field:** `enhancement_review` (`EnhancementReviewInput` on the `WorkflowTrigger`)

### `EnhancementReviewInput` Fields

| Field | Type | Description |
|---|---|---|
| `source_run_id` | `str` | Run ID of a previous `full_sdlc` run whose feature plan to reuse |
| `jira_epic_id` | `str` | Existing Jira epic key |
| `feature_description` | `str` | Natural-language feature description |
| `target_ocp_version` | `str \| None` | Target OpenShift version |
| `staging_github_org` | `str` | GitHub org where forks are created |
| `enhancement_repo` | `str` | Enhancements repo slug (default `openshift-splat-team/enhancements`) |

## Loading Previous Artifacts

The orchestrator loads the feature plan from the source run:

```
runs/{source_run_id}/openshift-feature-plan.json
```

This is fetched via `load_feature_plan` activity (30 s timeout, 3 retries).

## Orchestration Sequence

1. **EnsureEpicWorkflow** (jira-agent, 10 min) -- validates the Jira epic exists.
2. **EnhancementWorkflow** (enhancement-agent, 15 min) -- generates the enhancement doc via LLM using the loaded feature plan, stores it as `runs/{run_id}/enhancement-doc.json`, and opens a PR.
3. **WaitForEnhancementApprovalWorkflow** (enhancement-agent, 30 day timeout) -- polling loop until the PR is approved or closed.

## Enhancement Approval Polling Loop

`WaitForEnhancementApprovalWorkflow` receives an `EnhancementApprovalInput` containing `repo_slug`, `pr_number`, `fork_slug`, `feature_branch`, `feature_slug`, the `enhancement_doc`, `epic`, and `feature_plan`.

### Poll Cycle (every 5 minutes)

1. **`poll_enhancement_pr_state`** (30 s) -- returns a dict with `merged`, `approved_review_count`, and `state` fields.
2. **Exit conditions:**
   - `merged == True` or `approved_review_count >= 1` --> returns `"approved"`
   - `state == "closed"` --> returns `"closed"`
3. **`fetch_enhancement_pr_comments`** (30 s) -- fetches comments newer than `last_seen_comment_count`.

### Legacy Normalisation

The raw comments list may contain plain `str` entries from older history instead of `dict` objects. The workflow normalises these by wrapping them as `{"author": "unknown", "body": <str>}`.

### Comment Processing

When new comments are detected:

1. **`process_enhancement_comments`** (10 min, LLM retry) -- passes the current `EnhancementDoc`, new comments, epic, and feature plan to the LLM. Returns an `EnhancementCommentResult` with `revised_doc` and `response_body`.
2. **`commit_revised_enhancement_doc`** (5 min) -- commits the revised doc to the fork (`fork_slug`) on the feature branch.
3. **`post_enhancement_pr_comment`** (30 s) -- posts the response body as a PR comment.
4. Updates `current_doc` and increments `last_seen_comment_count`.

## Output

Returns a `WorkflowResult` with `artifact_ref = runs/{run_id}/enhancement-doc.json`.
