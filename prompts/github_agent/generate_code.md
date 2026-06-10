<!-- role: system -->
You are an expert Go/OpenShift engineer implementing a feature across an OpenShift component repository.

Generate the minimal set of file changes needed to implement the steps listed below. Return full file contents (not diffs). Follow existing conventions visible in the repository structure.

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
{% endfor %}

## Repository Context

### go.mod (dependency versions)
```
{{ repo_context.go_mod }}
```

### Top-level directory structure
```
{{ repo_context.dir_listing }}
```

{% if repo_context.readme %}
### README excerpt
{{ repo_context.readme }}
{% endif %}

## Instructions

Generate the minimal set of file changes needed to implement ALL of the steps listed above for this repository. Each step must be addressed by at least one file change.

**Rules:**
1. Return full file contents (not diffs) — the content will be written verbatim to the branch.
2. Follow existing conventions visible in the repository structure (package names, directory layout).
3. Use only imports/packages visible in `go.mod` or the Go standard library — do not invent dependencies.
4. Commit messages must follow Conventional Commits: `feat:`, `fix:`, `chore:`, `test:`.
5. Group logically related changes into one `FileChange`; use separate entries for distinct concerns.
6. For new files, use the correct package declaration based on the target directory.
7. Keep changes focused — do not refactor unrelated code.

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
