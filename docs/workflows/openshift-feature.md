# OpenShift Feature Analysis Workflow

Analyses an OpenShift feature description and produces an ordered implementation plan. Implemented by `OpenShiftFeatureWorkflow` in `agents/openshift_agent/workflows.py` with activities in `agents/openshift_agent/activities.py`.

For project setup see [../../README.md](../../README.md).

## Trigger

- **Task type:** `openshift_feature`
- **Required field:** `openshift_feature` (`OpenShiftFeatureInput` on the `WorkflowTrigger`)

Dispatched by the orchestrator to the `openshift-agent` task queue with a 15-minute execution timeout.

## Input Model -- `OpenShiftFeatureInput`

| Field | Type | Description |
|---|---|---|
| `feature_description` | `str` | Natural-language description of the feature |
| `target_ocp_version` | `str \| None` | Target OpenShift version |
| `jira_epic_id` | `str \| None` | Optional Jira epic key for context |
| `jira_context` | `dict \| None` | Structured epic/story context passed from orchestrator |

## Activity Chain

### 1. `identify_affected_repos`

- **Timeout:** 10 min
- **Retry:** LLM (5 attempts)
- **MCP integration:** Connects to the `dep-tree` MCP server via `mcp_client.connect()`. Calls `feature_impact_tool` with the feature description. The tool returns a scored list of candidate repositories.
- **LLM selection:** Renders `openshift_agent/identify_repos.md` with the scored candidates. The LLM selects the final set and flags API-change and MCO involvement.
- **Hallucination filter:** Any repo in the LLM output not present in the MCP dataset (`mcp_repo_names`) is dropped with a warning.
- **Output:** `RepoIdentificationResult` (repos, primary_repo, api_change_required, mco_involved)

### 2. `fetch_repo_context`

- **Timeout:** 30 s per repo
- **Retry:** standard (3 attempts)
- Fetches live GitHub context (go.mod existence, open PR count, recent PRs) for the primary repo and up to 2 additional required repos.
- Runs sequentially to stay within rate limits.

### 3. `analyze_feature`

- **Timeout:** 3 min
- **Retry:** LLM (5 attempts)
- **MCP integration:** For each affected repo, calls `get_repo_dependencies` from the dep-tree MCP server to enrich the analysis with dependency data.
- Renders `openshift_agent/analyze_feature.md` with affected repos, dependencies, feature description, target version, and Jira context.
- LLM produces an ordered PR sequence with timeline and risks.
- **Hallucination filter:** Any `pr_sequence` step referencing an unknown repo is dropped.
- **Output:** `OpenShiftFeaturePlan`

### 4. `determine_ci_requirements`

- **Timeout:** 10 min
- **Retry:** LLM (5 attempts)
- **MCP integration:** Calls `get_repo_info` per repo for CI metadata.
- Renders `openshift_agent/ci_requirements.md` and asks the LLM to identify required presubmit jobs and release config changes.
- **Output:** `CIRequirements` (merged into `plan.ci_requirements`)

### 5. `store_feature_plan`

- **Timeout:** 30 s
- **Retry:** standard
- **Artifact key:** `runs/{run_id}/openshift-feature-plan.json`

## Output Model -- `OpenShiftFeaturePlan`

| Field | Type |
|---|---|
| `summary` | `str` |
| `affected_tiers` | `list[str]` |
| `pr_sequence` | `list[PRStep]` |
| `estimated_timeline` | `str` |
| `risks` | `list[str]` |
| `notes` | `list[str]` |
| `ci_requirements` | `CIRequirements` |
| `artifact_ref` | `str` |

Each `PRStep` carries `step`, `repo`, `tier`, `description`, `blocked_by_step`, `branch`, `risk`, and `ci_requirements`.
