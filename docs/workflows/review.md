# PR Review Workflow

LLM-reviews a pull request and posts inline comments back to GitHub/Gitea. Implemented by `ReviewWorkflow` in `agents/github_agent/workflows.py`.

For project setup see [../../README.md](../../README.md).

## Trigger

- **Task type:** `review`
- **Required field:** `github_pr_url` (full URL of the PR to review)

Dispatched by the orchestrator to the `github-agent` task queue with a 10-minute execution timeout.

## Activity Chain

### 1. `fetch_pr`

- **Timeout:** 30 s
- **Retry:** standard (3 attempts, 2 s initial, 2x backoff)
- Fetches PR metadata and diff from GitHub/Gitea via the `github_client`.
- **Output:** `PRData` (url, title, body, branches, files, diff)

### 2. `run_review`

- **Timeout:** 10 min
- **Retry:** LLM (5 attempts, 5 s initial, 2x backoff)
- Renders the `github_agent/run_review.md` prompt with PR title, body, branches, and diff.
- LLM returns a structured `ReviewResult` with summary, approval decision, and inline comments.
- Each `InlineComment` has `path`, `line`, `body`, and `severity` (info/warning/error).
- **Output:** `ReviewResult`

### 3. `post_comments`

- **Timeout:** 30 s
- **Retry:** standard
- Posts the review to the PR via the GitHub/Gitea API using `github_client.post_review`.
- Submits a review with the summary as the body, inline comments attached, and an approve/comment action.

### 4. `store_review`

- **Timeout:** 30 s
- **Retry:** standard
- Serialises the `ReviewResult` to JSON and uploads to S3.
- **Artifact key:** `runs/{run_id}/review-result.json`

## Models

### `PRData`

| Field | Type |
|---|---|
| `url` | `str` |
| `title` | `str` |
| `body` | `str \| None` |
| `base_branch` | `str` |
| `head_branch` | `str` |
| `files` | `list[PRFile]` |
| `diff` | `str` |

### `ReviewResult`

| Field | Type |
|---|---|
| `pr_url` | `str` |
| `summary` | `str` |
| `inline_comments` | `list[InlineComment]` |
| `approved` | `bool` |
| `artifact_ref` | `str` |
