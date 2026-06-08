# Full SDLC Workflow

End-to-end OpenShift feature lifecycle managed by `FullSDLCWorkflow` in `agents/orchestrator/workflows.py`.

For project setup see [../../README.md](../../README.md).

## Input

`SDLCFeatureInput` model fields:

| Field | Type | Description |
|---|---|---|
| `jira_epic_id` | `str \| None` | Existing epic key; a new epic is created when absent |
| `feature_description` | `str` | Natural-language feature description |
| `target_ocp_version` | `str \| None` | Target OpenShift version (e.g. `"4.18"`) |
| `staging_github_org` | `str` | GitHub org where forks are created |
| `enhancement_repo` | `str` | Enhancements repo slug (default `openshift-splat-team/enhancements`) |

## Output

Returns a `StagingPlan` containing `feature_id` and a list of `StagingRepo` entries (one per affected repository).

## Phase Breakdown

### Phase A -- Ensure Jira Epic

- **Child workflow:** `EnsureEpicWorkflow` (jira-agent)
- **Task queue:** `jira-agent`
- **Timeout:** 10 min
- **Produces:** `JiraEpic` with key, summary, stories

### Phase B -- Feature Analysis

- **Child workflow:** `OpenShiftFeatureWorkflow`
- **Task queue:** `openshift-agent`
- **Timeout:** 15 min
- **Inputs:** `OpenShiftFeatureInput` populated with epic context (key, title, stories)
- **Produces:** artifact `runs/{run_id}/openshift-feature-plan.json`
- The feature plan is loaded via `load_feature_plan` activity for subsequent phases.

### Phase C -- Enhancement PR

- **Child workflow:** `EnhancementWorkflow`
- **Task queue:** `enhancement-agent`
- **Timeout:** 15 min
- **Inputs:** `JiraEpic`, `OpenShiftFeaturePlan`, `EnhancementPRInput`, feature branch name, target OCP version
- **Produces:** `CreatedPR` (enhancement PR URL), artifact `runs/{run_id}/enhancement-doc.json`
- Also creates a design-doc review story in Jira via `CreateDesignDocStoryWorkflow` (jira-agent).

### Phase D -- Human Approval Gate (Enhancement PR)

- **Child workflow:** `WaitForEnhancementApprovalWorkflow`
- **Task queue:** `enhancement-agent`
- **Timeout:** 30 days
- **Behaviour:** Polls the enhancement PR every 5 minutes. Processes reviewer comments via LLM, commits revised doc, posts a response. Exits when the PR is merged, approved (>= 1 approving review), or closed.
- **If closed:** transitions to `CloseStoryWontDoWorkflow`, returns an empty `StagingPlan`, and exits.

### Phase D.5 -- Fork Repos

- **Child workflow:** `ForkReposWorkflow`
- **Task queue:** `github-agent`
- **Timeout:** 10 min
- Forks every unique repo from `feature_plan.pr_sequence` into `staging_github_org`.

### Phase D.6 -- Reconcile Enhancement Doc Forks

- Loads the approved enhancement doc from `runs/{run_id}/enhancement-doc.json`.
- If `enhancement_doc.repos_to_fork` contains additional repos, forks them via a second `ForkReposWorkflow`.

### Phase E -- Story Refinement (Human Gate)

- **Activity:** `propose_stories` (requirements-agent, LLM)
- **Child workflow:** `StoryRefinementWorkflow`
- **Task queue:** `jira-agent`
- **Timeout:** 14 days
- Posts sized/prioritised story proposals as a Jira comment. Polls epic comments every 5 minutes. New human comments trigger `refine_stories` (LLM) and re-post. Exits when any comment contains `"stories approved"`.

### Phase F -- Create Stories

- **Child workflow:** `CreateStoriesWorkflow`
- **Task queue:** `jira-agent`
- **Timeout:** 5 min
- Creates, sizes, prioritises, and links stories from the approved plan.

### Phase G -- Setup Staging Repos

- **Child workflow:** `SetupStagingReposWorkflow`
- **Task queue:** `github-agent`
- **Timeout:** 10 min
- Forks repos, creates feature branches, opens draft PRs with `agent-hold` label.
- **Produces:** `StagingPlan`

### Phase H -- Code Generation

- **Child workflow:** `ImplementFeatureWorkflow`
- **Task queue:** `github-agent`
- **Timeout:** 4 hours
- Generates and commits code changes across all repos (one PR per repo). See [implement-feature.md](implement-feature.md).

### Phase I -- PR Monitors (fire-and-forget)

- **Child workflow:** `MonitorPRWorkflow` (one per staging repo)
- **Task queue:** `github-agent`
- **Timeout:** 90 days
- Long-lived: polls for `agent-hold` label removal every 5 minutes, processes new comments via LLM, applies file changes, posts response, re-applies label. Exits when PR is closed.

## Artifact Keys

| Phase | Key |
|---|---|
| B | `runs/{run_id}/openshift-feature-plan.json` |
| C | `runs/{run_id}/enhancement-doc.json` |
| E | `runs/{run_id}/story-plan.json` |
| H | `runs/{run_id}/impl-result.json` |
