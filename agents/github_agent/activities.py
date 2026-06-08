from __future__ import annotations

import asyncio
from pydantic import BaseModel
from temporalio import activity

from agents.common import llm, prompts, storage
from agents.common.models import (
    CodeGenerationResult,
    CommentProcessingResult,
    CreatePRInput,
    CreatedPR,
    FeatureImplementationResult,
    FileChange,
    InlineComment,
    PRData,
    PRMonitorEvent,
    RepoPRBundle,
    ReviewResult,
    StagingRepo,
)
from agents.common.settings import GitHubAgentSettings
from agents.github_agent import github_client


# ── Review activities ─────────────────────────────────────────────────────────

@activity.defn
async def fetch_pr(pr_url: str) -> PRData:
    settings = GitHubAgentSettings()
    activity.logger.info("Fetching PR %s", pr_url)
    return github_client.fetch_pr(pr_url, settings)


@activity.defn
async def run_review(pr_data: PRData) -> ReviewResult:
    settings = GitHubAgentSettings()
    activity.logger.info("Running LLM review of PR %s", pr_data.url)

    messages = prompts.render(
        "github_agent/run_review.md",
        pr_title=pr_data.title,
        pr_body=pr_data.body,
        head_branch=pr_data.head_branch,
        base_branch=pr_data.base_branch,
        diff=pr_data.diff,
    )

    class _ReviewPayload(BaseModel):
        summary: str
        approved: bool
        inline_comments: list[InlineComment] = []

    payload = await llm.complete_structured(messages, settings, _ReviewPayload)
    return ReviewResult(
        pr_url=pr_data.url,
        summary=payload.summary,
        approved=payload.approved,
        inline_comments=payload.inline_comments,
    )


@activity.defn
async def post_comments(review: ReviewResult) -> None:
    settings = GitHubAgentSettings()
    activity.logger.info(
        "Posting review to GitHub PR %s (%d comments)", review.pr_url, len(review.inline_comments)
    )
    github_client.post_review(
        review.pr_url, review.summary, review.inline_comments, review.approved, settings
    )


@activity.defn
async def store_review(review: ReviewResult, run_id: str) -> str:
    settings = GitHubAgentSettings()
    key = f"runs/{run_id}/review-result.json"
    activity.logger.info("Storing review to S3 key %s", key)
    return storage.put_artifact(key, review, settings)


# ── PR creation activities ────────────────────────────────────────────────────

@activity.defn
async def create_pr(input: CreatePRInput) -> CreatedPR:
    settings = GitHubAgentSettings()
    activity.logger.info(
        "Creating PR on %s: %s → %s", input.repo, input.head_branch, input.base_branch
    )
    return github_client.create_pr(input, settings)


@activity.defn
async def store_created_pr(pr: CreatedPR, run_id: str) -> str:
    settings = GitHubAgentSettings()
    key = f"runs/{run_id}/created-pr.json"
    activity.logger.info("Storing created PR record to S3 key %s", key)
    return storage.put_artifact(key, pr, settings)


# ── Staging / fork / monitoring activities ────────────────────────────────────

@activity.defn
async def fork_repository(source_slug: str, staging_org: str) -> StagingRepo:
    settings = GitHubAgentSettings()
    if "/" not in source_slug:
        source_slug = f"openshift/{source_slug}"
    activity.logger.info("Forking %s into %s", source_slug, staging_org)
    source_org, source_repo = source_slug.split("/", 1)
    fork_slug = github_client.fork_repo(source_slug, staging_org, settings)
    from urllib.parse import urlparse  # noqa: PLC0415
    parsed = urlparse(settings.github_base_url)
    web_base = f"{parsed.scheme}://{parsed.netloc}"
    return StagingRepo(
        source_org=source_org,
        source_repo=source_repo,
        staging_org=staging_org,
        staging_repo=fork_slug.split("/")[-1],
        fork_url=f"{web_base}/{fork_slug}",
    )


@activity.defn
async def create_feature_branch(staging_repo: StagingRepo, feature_branch: str) -> StagingRepo:
    settings = GitHubAgentSettings()
    fork_slug = f"{staging_repo.staging_org}/{staging_repo.staging_repo}"
    activity.logger.info("Creating branch %s on %s", feature_branch, fork_slug)
    github_client.create_branch(fork_slug, feature_branch, "main", settings)
    staging_repo.feature_branch = feature_branch
    return staging_repo


@activity.defn
async def create_staging_pr(
    staging_repo: StagingRepo,
    story_key: str,
    title: str,
    body: str,
) -> StagingRepo:
    settings = GitHubAgentSettings()
    source_slug = f"{staging_repo.source_org}/{staging_repo.source_repo}"
    fork_owner = staging_repo.staging_org
    activity.logger.info("Creating staging PR on %s from %s", source_slug, fork_owner)

    pr_input = CreatePRInput(
        repo=source_slug,
        head_branch=f"{fork_owner}:{staging_repo.feature_branch}",
        base_branch="main",
        title=f"[{story_key}] {title}",
        body=body,
        draft=True,
        jira_issue_key=story_key,
    )
    created = github_client.create_pr(pr_input, settings)
    github_client.add_label(source_slug, created.number, "agent-hold", settings)

    staging_repo.pr_url = created.url
    staging_repo.pr_number = created.number
    staging_repo.labels = ["agent-hold"]
    return staging_repo


@activity.defn
async def poll_pr_for_label_drop(staging_repo: StagingRepo) -> PRMonitorEvent:
    settings = GitHubAgentSettings()
    source_slug = f"{staging_repo.source_org}/{staging_repo.source_repo}"
    state = github_client.get_pr_state(source_slug, staging_repo.pr_number, settings)
    labels = state.get("labels", [])

    if state.get("state") == "closed":
        return PRMonitorEvent(
            repo_slug=source_slug,
            pr_number=staging_repo.pr_number,
            pr_url=staging_repo.pr_url,
            event_type="closed",
            labels=labels,
        )

    if "agent-hold" not in labels:
        comments = github_client.get_pr_comments_since(
            source_slug, staging_repo.pr_number, 0, settings
        )
        return PRMonitorEvent(
            repo_slug=source_slug,
            pr_number=staging_repo.pr_number,
            pr_url=staging_repo.pr_url,
            event_type="label_dropped",
            new_comments=[c["body"] for c in comments],
            labels=labels,
        )

    return PRMonitorEvent(
        repo_slug=source_slug,
        pr_number=staging_repo.pr_number,
        pr_url=staging_repo.pr_url,
        event_type="comment",
        labels=labels,
    )


@activity.defn
async def process_pr_comments(staging_repo: StagingRepo, comments: list[str]) -> CommentProcessingResult:
    settings = GitHubAgentSettings()
    source_slug = f"{staging_repo.source_org}/{staging_repo.source_repo}"
    fork_slug = f"{staging_repo.staging_org}/{staging_repo.staging_repo}"
    activity.logger.info("Processing %d comments on %s#%d", len(comments), source_slug, staging_repo.pr_number)

    pr_data = github_client.fetch_pr(staging_repo.pr_url, settings)

    files_with_content = []
    for pr_file in pr_data.files:
        try:
            content = github_client.get_file_content(fork_slug, pr_file.filename, staging_repo.feature_branch, settings)
            files_with_content.append({"path": pr_file.filename, "content": content})
        except Exception:
            activity.logger.warning("Could not fetch content for %s; skipping", pr_file.filename)

    messages = prompts.render(
        "github_agent/process_comments.md",
        pr_url=staging_repo.pr_url,
        repo=source_slug,
        feature_branch=staging_repo.feature_branch,
        files=files_with_content,
        comments=comments,
    )
    return await llm.complete_structured(messages, settings, CommentProcessingResult)


@activity.defn
async def apply_file_changes(staging_repo: StagingRepo, file_changes: list[FileChange]) -> None:
    settings = GitHubAgentSettings()
    fork_slug = f"{staging_repo.staging_org}/{staging_repo.staging_repo}"
    activity.logger.info(
        "Applying %d file changes to %s on branch %s",
        len(file_changes), fork_slug, staging_repo.feature_branch,
    )
    for change in file_changes:
        github_client.push_file_change(
            fork_slug,
            staging_repo.feature_branch,
            change.path,
            change.content,
            change.commit_message,
            settings,
        )
        activity.logger.info("Pushed change to %s", change.path)


@activity.defn
async def post_pr_comment(staging_repo: StagingRepo, body: str) -> None:
    settings = GitHubAgentSettings()
    source_slug = f"{staging_repo.source_org}/{staging_repo.source_repo}"
    activity.logger.info("Posting comment on %s#%d", source_slug, staging_repo.pr_number)
    github_client.post_issue_comment(source_slug, staging_repo.pr_number, body, settings)


@activity.defn
async def reset_agent_hold_label(staging_repo: StagingRepo) -> None:
    settings = GitHubAgentSettings()
    source_slug = f"{staging_repo.source_org}/{staging_repo.source_repo}"
    activity.logger.info("Resetting agent-hold label on %s#%d", source_slug, staging_repo.pr_number)
    github_client.add_label(source_slug, staging_repo.pr_number, "agent-hold", settings)


# ── Code generation activities ────────────────────────────────────────────────

@activity.defn
async def fetch_repo_context(source_org: str, source_repo: str, branch: str) -> dict:
    settings = GitHubAgentSettings()
    source_slug = f"{source_org}/{source_repo}"
    activity.logger.info("Fetching repo context for %s@%s", source_slug, branch)
    return github_client.get_repo_context(source_slug, branch, settings)


@activity.defn
async def generate_code_for_bundle(
    bundle: RepoPRBundle,
    feature_description: str,
    repo_context: dict,
) -> list[FileChange]:
    settings = GitHubAgentSettings()
    activity.logger.info(
        "Generating code for %s (%d steps)", bundle.repo, len(bundle.steps)
    )

    messages = prompts.render(
        "github_agent/generate_code.md",
        repo=bundle.repo,
        tier=bundle.tier,
        steps=bundle.steps,
        feature_description=feature_description,
        repo_context=repo_context,
    )

    class _CodeGenResponse(BaseModel):
        file_changes: list[FileChange]

    result = await llm.complete_structured(messages, settings, _CodeGenResponse)
    return result.file_changes


@activity.defn
async def update_pr_description(staging_repo: StagingRepo, result: CodeGenerationResult) -> None:
    settings = GitHubAgentSettings()
    source_slug = f"{staging_repo.source_org}/{staging_repo.source_repo}"
    activity.logger.info("Updating PR description on %s#%d", source_slug, staging_repo.pr_number)

    summary = "\n\n## Implementation Summary\n\n"
    summary += f"**Files changed ({len(result.files_changed)}):**\n"
    for path in result.files_changed:
        summary += f"- `{path}`\n"
    if result.commit_messages:
        summary += "\n**Commits:**\n"
        for msg in result.commit_messages:
            summary += f"- {msg}\n"

    current_body = github_client.get_pr_body(source_slug, staging_repo.pr_number, settings)
    github_client.update_pr_body(source_slug, staging_repo.pr_number, current_body + summary, settings)


@activity.defn
async def remove_agent_hold(staging_repo: StagingRepo) -> None:
    settings = GitHubAgentSettings()
    source_slug = f"{staging_repo.source_org}/{staging_repo.source_repo}"
    activity.logger.info("Removing agent-hold from %s#%d", source_slug, staging_repo.pr_number)
    github_client.remove_label(source_slug, staging_repo.pr_number, "agent-hold", settings)


@activity.defn
async def store_implementation_result(result: FeatureImplementationResult, run_id: str) -> str:
    settings = GitHubAgentSettings()
    key = f"runs/{run_id}/impl-result.json"
    activity.logger.info("Storing implementation result to S3 key %s", key)
    return storage.put_artifact(key, result, settings)
