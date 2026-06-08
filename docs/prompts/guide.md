# Prompt Template Guide

## How Templates Work

Prompt templates are Jinja2 markdown files stored in the `prompts/` directory, organized by agent. They are rendered at runtime by `agents/common/prompts.py` and produce a list of message dicts (`[{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]`) ready for the LLM.

Each template is split into sections using HTML comment markers:

```markdown
<!-- role: system -->
You are a senior engineer. Analyze the following...

Respond ONLY with a valid JSON object.

Output schema:
{ "result": "string" }

<!-- role: user -->
## Input Data
{{ variable_name }}
```

The `render()` function in `agents/common/prompts.py` uses a regex (`<!-- role: system -->` or `<!-- role: user -->`) to split the rendered markdown into message sections. Content before the first marker is discarded.

## The render() Function

```python
from agents.common.prompts import render

messages = render("requirements_agent/produce_spec.md", epic_key="PROJ-1", ...)
# Returns: [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]
```

- `template_path` is relative to the `prompts/` directory
- Keyword arguments are passed as Jinja2 variables
- Uses `StrictUndefined` -- missing variables raise an error rather than rendering blank
- `trim_blocks` and `lstrip_blocks` are enabled for clean Jinja control flow

Templates are resolved from `prompts/` at the repository root (two levels up from `agents/common/prompts.py`). In Docker, the `prompts/` directory is volume-mounted read-only, so changes to templates on the host take effect immediately without rebuilding.

## Template Inventory

### requirements_agent/produce_spec.md

**Called by:** `produce_spec` activity | **Output model:** `RequirementSpec`

Converts a Jira epic and its child stories into a structured requirement specification.

**Variables:** `epic_key`, `epic_summary`, `epic_description`, `stories` (list of story dicts with `key`, `summary`, `status`, `story_points`, `description`), `parent_key` (optional), `parent_summary` (optional), `parent_description` (optional)

### requirements_agent/propose_stories.md

**Called by:** `propose_stories` activity | **Output model:** `StoryPlan`

Takes a requirement spec and a feature implementation plan, produces a sized and prioritized story plan with dependencies.

**Variables:** `epic_id`, `title`, `stories` (list from RequirementSpec), `acceptance_criteria`, `feature_plan` (OpenShiftFeaturePlan dict with `summary`, `pr_sequence`, `risks`, etc.)

### requirements_agent/refine_stories.md

**Called by:** `refine_stories` activity | **Output model:** `StoryPlan`

Revises a story plan based on human reviewer feedback from Jira epic comments.

**Variables:** `epic_id`, `stories` (current StoryPlan stories), `sizing_rationale`, `comments` (list of feedback comment dicts)

### enhancement_agent/generate_doc.md

**Called by:** `generate_enhancement_doc` activity | **Output model:** `EnhancementDoc`

Generates a full OpenShift Enhancement Proposal document from a Jira epic and feature implementation plan.

**Variables:** `epic_key`, `epic_summary`, `epic_description`, `parent_key` (optional), `parent_summary` (optional), `parent_description` (optional), `target_ocp_version` (optional), `feature_plan` (OpenShiftFeaturePlan dict), `memories` (optional -- formatted agent memory context from prior runs)

### enhancement_agent/process_comments.md

**Called by:** `process_enhancement_comments` activity | **Output model:** `EnhancementCommentResult`

Revises an enhancement document based on PR reviewer comments. Produces a response body quoting each reviewer concern and the revised document.

**Variables:** `current_doc` (EnhancementDoc dict), `comments` (list of `{"author", "body"}` dicts), `epic_key`, `epic_summary`, `feature_plan_summary`

### openshift_agent/identify_repos.md

**Called by:** `identify_affected_repos` activity | **Output model:** `AffectedReposResult`

Selects which OpenShift repositories are affected by a feature, from a list of candidates scored by the MCP dependency-tree server.

**Variables:** `feature_description`, `target_ocp_version` (optional), `jira_context` (optional), `repos` (list of candidate repo dicts with `repo`, `score`, and metadata)

### openshift_agent/analyze_feature.md

**Called by:** `analyze_feature` activity | **Output model:** `OpenShiftFeaturePlan`

Produces an ordered PR sequence and implementation plan given the affected repos and their dependency context.

**Variables:** `feature_description`, `target_ocp_version` (optional), `jira_context` (optional), `affected_repos` (list of repo dicts with `name`, `tier`, `change_type`, `reason`, `required`), `repo_dependencies` (dict mapping repo name to dependency info)

### openshift_agent/ci_requirements.md

**Called by:** `determine_ci_requirements` activity | **Output model:** `CIRequirements`

Determines which CI jobs need to be added or updated for the feature across all affected repos.

**Variables:** `feature_description`, `target_ocp_version` (optional), `affected_repos`, `plan_summary` (from the feature plan), `pr_sequence` (ordered list of PRStep dicts)

### github_agent/run_review.md

**Called by:** `run_review` activity | **Output model:** `ReviewResult`

Reviews a pull request diff and produces inline comments with severity levels.

**Variables:** `pr_title`, `pr_body`, `pr_diff`

### github_agent/generate_code.md

**Called by:** `generate_code_for_bundle` activity | **Output model:** `_CodeGenResponse` (wrapper for `list[FileChange]`)

Generates file changes for a single repository given the implementation steps from the feature plan.

**Variables:** `repo`, `tier`, `steps` (list of PRStep dicts with `step`, `description`), `feature_description`, `repo_context` (dict with `go_mod`, `tree`, `readme`)

### github_agent/process_comments.md

**Called by:** `process_pr_comments` activity | **Output model:** `CommentProcessingResult`

Processes human review comments on a staging PR. Produces a response body and optional file changes to address the feedback.

**Variables:** `pr_url`, `repo`, `feature_branch`, `files` (list of `{"path", "content"}` dicts for current file state), `comments` (list of comment dicts)

## Modifying a Prompt

1. Edit the `.md` file directly in `prompts/<agent>/`
2. Changes take effect immediately -- templates are loaded by Jinja2's `FileSystemLoader` at render time
3. In Docker Compose, `prompts/` is volume-mounted (`./prompts:/app/prompts:ro,z`), so no container rebuild is needed
4. Use `{{ variable }}` for Jinja2 substitution; `{% for %}` / `{% if %}` for control flow
5. Always include the output schema in the system section so the LLM produces parseable JSON
6. Test by running the relevant task type: `python -m scripts.trigger <task_type>`

## Adding a New Prompt

1. Create `prompts/<agent>/<name>.md` with `<!-- role: system -->` and `<!-- role: user -->` sections
2. Call it from the activity: `messages = prompts.render("<agent>/<name>.md", key=value, ...)`
3. Pass `messages` to `llm.complete_structured(messages, settings, OutputModel)` to get a parsed response
