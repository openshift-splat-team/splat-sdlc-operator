# Agent Overview

This project contains six Temporal-based agents that together implement an automated SDLC workflow for OpenShift features. Each agent runs as an independent Temporal worker process, communicating through child workflows and shared S3 artifacts.

## Agent Summary

| Agent | Task Queue | Settings Class | Key Activities |
|-------|-----------|----------------|----------------|
| orchestrator | `orchestrator` | `OrchestratorSettings` | `load_feature_plan`, `load_enhancement_doc`, `load_staging_plan` |
| requirements-agent | `requirements-agent` | `RequirementsAgentSettings` | `fetch_jira_epic`, `produce_spec`, `store_spec`, `propose_stories`, `refine_stories` |
| github-agent | `github-agent` | `GitHubAgentSettings` | `fetch_pr`, `run_review`, `post_comments`, `create_pr`, `fork_repository`, `create_feature_branch`, `generate_code_for_bundle`, `apply_file_changes`, `process_pr_comments` |
| openshift-agent | `openshift-agent` | `OpenShiftAgentSettings` | `identify_affected_repos`, `fetch_repo_context`, `analyze_feature`, `determine_ci_requirements`, `store_feature_plan` |
| jira-agent | `jira-agent` | `JiraAgentSettings` | `ensure_jira_epic`, `create_approved_stories`, `post_story_proposals`, `poll_epic_comments`, `create_design_doc_story`, `size_and_prioritize_stories`, `set_story_dependencies`, `close_story_wont_do`, `store_story_plan` |
| enhancement-agent | `enhancement-agent` | `EnhancementAgentSettings` | `generate_enhancement_doc`, `submit_enhancement_pr`, `store_enhancement_doc`, `poll_enhancement_pr_state`, `fetch_enhancement_pr_comments`, `process_enhancement_comments`, `commit_revised_enhancement_doc`, `post_enhancement_pr_comment` |

All settings classes inherit from `BaseAgentSettings` which provides Temporal connection, LLM provider, and S3 storage configuration. Every worker also registers the shared memory activities: `save_memory_entry`, `recall_agent_memories`, `extract_observations`.

---

## Orchestrator

**Task queue:** `orchestrator` | **Settings:** `OrchestratorSettings` | **Module:** `agents.orchestrator.worker`

Routes incoming `WorkflowTrigger` messages to the correct child workflow based on `task_type`. Makes no LLM calls of its own. Hosts two workflow classes:

- **`SDLCOrchestratorWorkflow`** -- dispatches to child workflows: `RequirementsWorkflow`, `ReviewWorkflow`, `CreatePRWorkflow`, `OpenShiftFeatureWorkflow`, `FullSDLCWorkflow`, `ImplementFeatureWorkflow`, and enhancement review flows.
- **`FullSDLCWorkflow`** -- end-to-end SDLC pipeline: epic creation, requirements, feature analysis, enhancement doc, story planning, repo staging, code generation, and PR monitoring.

Activities are limited to artifact loading: `load_feature_plan`, `load_enhancement_doc`, `load_staging_plan`.

## Requirements Agent

**Task queue:** `requirements-agent` | **Settings:** `RequirementsAgentSettings` (extends `JiraBaseSettings`) | **Module:** `agents.requirements_agent.worker`

Fetches Jira epics and produces structured requirement specifications via LLM. Also handles story proposal generation and refinement (called cross-queue by the jira-agent).

- `fetch_jira_epic` -- retrieves epic data including child stories from Jira
- `produce_spec` -- renders `requirements_agent/produce_spec.md` prompt, returns `RequirementSpec`
- `store_spec` -- persists the spec to S3
- `propose_stories` -- renders `requirements_agent/propose_stories.md` prompt, returns `StoryPlan`
- `refine_stories` -- renders `requirements_agent/refine_stories.md` prompt with human feedback, returns revised `StoryPlan`

## GitHub Agent

**Task queue:** `github-agent` | **Settings:** `GitHubAgentSettings` | **Module:** `agents.github_agent.worker`

Handles all GitHub/Gitea interactions: PR reviews, staging repo setup, code generation, and PR monitoring. Hosts multiple workflows: `ReviewWorkflow`, `CreatePRWorkflow`, `SetupStagingReposWorkflow`, `ForkReposWorkflow`, `ImplementFeatureWorkflow`, `CodeGenerationWorkflow`, `MonitorPRWorkflow`.

- `fetch_pr` -- retrieves PR metadata and diff from GitHub
- `run_review` -- renders `github_agent/run_review.md` prompt, returns `ReviewResult`
- `post_comments`, `post_pr_comment` -- posts inline review comments or general comments
- `create_pr` -- creates a pull request via the GitHub API
- `fork_repository` -- forks a repo into the staging org
- `create_feature_branch` -- creates a branch on a staging fork
- `create_staging_pr` -- opens a draft PR with `agent-hold` label
- `generate_code_for_bundle` -- renders `github_agent/generate_code.md` prompt, returns `FileChange` list
- `apply_file_changes` -- commits generated file changes to a branch
- `process_pr_comments` -- renders `github_agent/process_comments.md` prompt, returns response + file changes
- `fetch_repo_context` -- retrieves repo structure, go.mod, and README for code generation context
- `poll_pr_for_label_drop` -- polls a PR for `agent-hold` label removal or new comments
- `update_pr_description`, `remove_agent_hold`, `reset_agent_hold_label` -- PR management helpers
- `store_implementation_result` -- persists implementation results to S3

## OpenShift Agent

**Task queue:** `openshift-agent` | **Settings:** `OpenShiftAgentSettings` | **Module:** `agents.openshift_agent.worker`

Performs feature impact analysis across the OpenShift repository ecosystem using an MCP dependency-tree server and LLM reasoning. Settings include MCP connection fields (`mcp_server_url`, `mcp_server_command`, `mcp_server_script`, `mcp_data_dir`).

- `identify_affected_repos` -- queries the MCP dep-tree server for dependency scores, then renders `openshift_agent/identify_repos.md` prompt to select affected repos
- `fetch_repo_context` -- retrieves repo metadata and dependency information via the MCP server
- `analyze_feature` -- renders `openshift_agent/analyze_feature.md` prompt, returns `OpenShiftFeaturePlan` with ordered PR sequence
- `determine_ci_requirements` -- renders `openshift_agent/ci_requirements.md` prompt, returns CI job requirements
- `store_feature_plan` -- persists the feature plan to S3

## Jira Agent

**Task queue:** `jira-agent` | **Settings:** `JiraAgentSettings` (extends `JiraBaseSettings`) | **Module:** `agents.jira_agent.worker`

Manages story lifecycle in Jira: epic creation, story proposals with human approval gates, sizing, prioritization, and dependency linking. Hosts workflows: `EnsureEpicWorkflow`, `CreateDesignDocStoryWorkflow`, `StoryRefinementWorkflow`, `CreateStoriesWorkflow`, `CloseStoryWontDoWorkflow`.

- `ensure_jira_epic` -- creates or fetches a Jira epic for the feature
- `post_story_proposals` -- posts proposed stories as a comment on the epic
- `poll_epic_comments` -- polls for new comments; looks for "stories approved" marker
- `create_approved_stories` -- creates Jira stories from the approved plan
- `create_design_doc_story` -- creates a story linking to the enhancement PR
- `size_and_prioritize_stories` -- sets story points from the plan
- `set_story_dependencies` -- creates "is blocked by" links between stories
- `close_story_wont_do` -- closes a story with "Won't Do" resolution
- `store_story_plan` -- persists the story plan to S3

## Enhancement Agent

**Task queue:** `enhancement-agent` | **Settings:** `EnhancementAgentSettings` | **Module:** `agents.enhancement_agent.worker`

Generates OpenShift Enhancement Proposals, opens PRs in the enhancements repo, and processes reviewer feedback in a long-running approval loop. Settings include `github_bot_user` (excluded from reviewer comments) and `enhancement_repo`. Hosts workflows: `EnhancementWorkflow`, `WaitForEnhancementApprovalWorkflow`.

- `generate_enhancement_doc` -- renders `enhancement_agent/generate_doc.md` prompt with epic + feature plan + agent memories, returns `EnhancementDoc`
- `store_enhancement_doc` -- persists the doc to S3
- `submit_enhancement_pr` -- forks the enhancement repo, commits the doc, and opens a PR
- `poll_enhancement_pr_state` -- checks PR merge/approval/close status
- `fetch_enhancement_pr_comments` -- retrieves new comments, filtering out bot comments
- `process_enhancement_comments` -- renders `enhancement_agent/process_comments.md` prompt, returns `EnhancementCommentResult` with revised doc + response
- `commit_revised_enhancement_doc` -- pushes the revised doc to the fork branch
- `post_enhancement_pr_comment` -- posts the agent's response on the PR
