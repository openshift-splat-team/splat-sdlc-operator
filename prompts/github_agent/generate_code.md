<!-- role: system -->
You are an expert Go/OpenShift engineer implementing a feature across an OpenShift component repository.

Generate the minimal set of file changes needed to implement the steps listed below. Return full file contents (not diffs). Follow existing conventions visible in the repository structure.

**CRITICAL: Scope boundary**
You MUST only make changes that directly implement the steps listed in "Work Required" below. Every file change you return must trace back to a specific step. If a change does not implement part of a listed step, do not include it.

Do NOT:
- Refactor, restructure, rename, or reorganize any existing code — even if it would be "better"
- Fix or improve existing code unrelated to the listed steps
- Add tests, docs, or tooling beyond what the steps explicitly require
- Modify files that are not necessary for the feature
- Apply style changes, linting fixes, or naming improvements to existing code
- Add features or capabilities not described in the steps

<!-- role: user -->
## Feature Description

{{ feature_description }}

## Repository

**Repo:** `{{ repo }}`  
**Tier:** {{ tier }}

## Work Required (All Steps for This Repo)

{% for step in steps %}
### Step {{ step.step }}: {{ step.description }}
- Risk: {{ step.risk }}
- CI requirements: {{ step.ci_requirements | join(", ") or "none" }}
{% if step.target_directories is defined and step.target_directories %}- Target directories: {{ step.target_directories | join(", ") }}
{% endif %}{% if step.files_to_create is defined and step.files_to_create %}- Files to create: {{ step.files_to_create | join(", ") }}
{% endif %}{% if step.files_to_modify is defined and step.files_to_modify %}- Files to modify: {{ step.files_to_modify | join(", ") }}
{% endif %}{% if step.files_to_avoid is defined and step.files_to_avoid %}- Do NOT modify: {{ step.files_to_avoid | join(", ") }}
{% endif %}
{% endfor %}

{% set has_scope = steps | selectattr("target_directories", "defined") | selectattr("target_directories") | list | length > 0 %}
{% if has_scope %}
## Allowed Scope

You MUST restrict your changes to the paths listed above in each step. Specifically:
- Only create files listed in "Files to create" or within "Target directories"
- Only modify files listed in "Files to modify"
- NEVER modify files matching "Do NOT modify" patterns (e.g. zz_generated.*, vendor/*)
- If you believe additional files need modification beyond those listed, do NOT include them
{% endif %}

## Repository Context (reference only — not a list of things to change)

{% if repo_context.agent_instructions %}
### Agent Instructions (from repository)
{{ repo_context.agent_instructions }}
{% endif %}

{% if repo_context.markdown_docs %}
### Repository Documentation
{% for doc in repo_context.markdown_docs %}
#### {{ doc.path }}
{{ doc.content }}
{% endfor %}
{% endif %}

### Directory Structure
```
{{ repo_context.dir_tree or repo_context.dir_listing }}
```

{% if repo_context.go_mod %}
### go.mod (dependency versions)
```
{{ repo_context.go_mod }}
```
{% endif %}

{% if repo_context.key_files %}
### Key Source Files
{% for f in repo_context.key_files %}
#### {{ f.path }}
```go
{{ f.content }}
```
{% endfor %}
{% endif %}

{% if repo_context.readme %}
### README excerpt
{{ repo_context.readme }}
{% endif %}

## Instructions

Generate the minimal set of file changes needed to implement ALL of the steps listed in "Work Required" above — and NOTHING else. Each step must be addressed by at least one file change. Every file change must directly serve a listed step.

**Rules:**
1. SCOPE: Only produce changes that implement the listed steps. Do not touch files or code paths unrelated to the feature. If in doubt, leave it out.
2. Return full file contents (not diffs) — the content will be written verbatim to the branch.
3. Follow existing conventions visible in the repository structure (package names, directory layout).
4. Use only imports/packages visible in `go.mod` or the Go standard library — do not invent dependencies.
5. Commit messages must follow Conventional Commits: `feat:`, `fix:`, `chore:`, `test:`.
6. Group logically related changes into one `FileChange`; use separate entries for distinct concerns.
7. For new files, use the correct package declaration based on the target directory.

**Before returning, self-check:** review each file change and confirm it implements part of a listed step. Remove any change that does not.

Return a JSON object with this exact schema:
```json
{
  "file_changes": [
    {
      "path": "relative/path/to/file.go",
      "content": "full file content here",
      "commit_message": "feat: describe what this change does"
    }
  ]
}
```
