from __future__ import annotations

import asyncio
from pydantic import BaseModel
from temporalio import activity

from agents.common import llm, prompts, storage
from agents.common.models import (
    CITest,
    CodeGenerationResult,
    CommentProcessingResult,
    CreatePRInput,
    CreatedPR,
    FeatureImplementationResult,
    FileChange,
    FileEdit,
    InlineComment,
    PRData,
    PRMonitorEvent,
    RepoPRBundle,
    ReviewResult,
    StagingPlan,
    StagingRepo,
    TestResult,
)
from agents.common.settings import GitHubAgentSettings
from agents.github_agent import ci_config, ci_workflow_generator, github_client, test_runner


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


@activity.defn
async def store_staging_plan(plan: StagingPlan, run_id: str) -> str:
    settings = GitHubAgentSettings()
    key = f"runs/{run_id}/staging-plan.json"
    activity.logger.info("Storing staging plan to S3 key %s", key)
    return storage.put_artifact(key, plan, settings)


# ── Staging / fork / monitoring activities ────────────────────────────────────

@activity.defn
async def mirror_repository(source_slug: str) -> bool:
    """Mirror a GitHub repo into Gitea. Returns True on success, False if mirror failed."""
    settings = GitHubAgentSettings()
    if not github_client.is_gitea(settings):
        return True
    if "/" not in source_slug:
        source_slug = f"openshift/{source_slug}"
    activity.logger.info("Mirroring %s from GitHub into Gitea", source_slug)
    ok = github_client.mirror_repo(source_slug, settings)
    if ok:
        github_client.disable_repo_actions(source_slug, settings)
        activity.logger.info("Mirror ready: %s (actions disabled)", source_slug)
    else:
        activity.logger.warning("Mirror failed for %s; will be dropped from fork list", source_slug)
    return ok


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
    gh = github_client._connect(settings)
    repo = gh.get_repo(fork_slug)
    default_branch = repo.default_branch or "main"
    activity.logger.info("Creating branch %s on %s from %s", feature_branch, fork_slug, default_branch)
    github_client.create_branch(fork_slug, feature_branch, default_branch, settings)
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
    fork_slug = f"{staging_repo.staging_org}/{staging_repo.staging_repo}"
    gh = github_client._connect(settings)
    repo = gh.get_repo(fork_slug)
    default_branch = repo.default_branch or "main"
    activity.logger.info("Creating staging PR on %s (base=%s, head=%s)", fork_slug, default_branch, staging_repo.feature_branch)

    pr_input = CreatePRInput(
        repo=fork_slug,
        head_branch=staging_repo.feature_branch,
        base_branch=default_branch,
        title=f"[{story_key}] {title}",
        body=body,
        draft=True,
        jira_issue_key=story_key,
    )
    created = github_client.create_pr(pr_input, settings)
    github_client.add_label(fork_slug, created.number, "agent-hold", settings)

    staging_repo.pr_url = created.url
    staging_repo.pr_number = created.number
    staging_repo.labels = ["agent-hold"]
    return staging_repo


@activity.defn
async def poll_pr_for_label_drop(staging_repo: StagingRepo) -> PRMonitorEvent:
    settings = GitHubAgentSettings()
    fork_slug = f"{staging_repo.staging_org}/{staging_repo.staging_repo}"
    state = github_client.get_pr_state(fork_slug, staging_repo.pr_number, settings)
    labels = state.get("labels", [])

    if state.get("state") == "closed":
        return PRMonitorEvent(
            repo_slug=fork_slug,
            pr_number=staging_repo.pr_number,
            pr_url=staging_repo.pr_url,
            event_type="closed",
            labels=labels,
        )

    if "agent-hold" not in labels:
        comments = github_client.get_pr_comments_since(
            fork_slug, staging_repo.pr_number, 0, settings
        )
        retest = False
        filtered: list[str] = []
        for c in comments:
            body = c["body"]
            lines = body.splitlines()
            clean_lines = [ln for ln in lines if ln.strip() != "/retest"]
            if len(clean_lines) < len(lines):
                retest = True
            cleaned = "\n".join(clean_lines).strip()
            if cleaned:
                filtered.append(cleaned)
        return PRMonitorEvent(
            repo_slug=fork_slug,
            pr_number=staging_repo.pr_number,
            pr_url=staging_repo.pr_url,
            event_type="label_dropped",
            new_comments=filtered,
            labels=labels,
            retest_requested=retest,
        )

    return PRMonitorEvent(
        repo_slug=fork_slug,
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
async def apply_file_changes(staging_repo: StagingRepo, file_changes: list[FileChange]) -> list[str]:
    """Apply file changes. Returns list of warnings for skipped edits (empty = all OK)."""
    settings = GitHubAgentSettings()
    fork_slug = f"{staging_repo.staging_org}/{staging_repo.staging_repo}"
    branch = staging_repo.feature_branch
    activity.logger.info(
        "Applying %d file changes to %s on branch %s",
        len(file_changes), fork_slug, branch,
    )
    warnings: list[str] = []
    for change in file_changes:
        if change.action == "modify" and change.edits:
            try:
                current = github_client.get_file_content(fork_slug, change.path, branch, settings)
            except Exception:
                msg = f"`{change.path}`: file not found on branch `{branch}` — all edits skipped"
                activity.logger.warning("File not found for modify: %s on %s", change.path, branch)
                warnings.append(msg)
                continue
            modified = current
            applied = 0
            for edit in change.edits:
                if edit.search not in modified:
                    msg = f"`{change.path}`: search text not found — edit skipped: `{edit.search[:80]}...`"
                    activity.logger.warning("Skipped edit in %s: search text not found: %s", change.path, edit.search[:100])
                    warnings.append(msg)
                    continue
                modified = modified.replace(edit.search, edit.replace, 1)
                applied += 1
            if applied > 0 and modified != current:
                github_client.push_file_change(
                    fork_slug, branch, change.path, modified, change.commit_message, settings,
                )
            activity.logger.info("Applied %d/%d edits to %s", applied, len(change.edits), change.path)
        else:
            github_client.push_file_change(
                fork_slug, branch, change.path, change.content, change.commit_message, settings,
            )
            activity.logger.info("Created %s", change.path)
    return warnings


@activity.defn
async def post_pr_comment(staging_repo: StagingRepo, body: str) -> None:
    settings = GitHubAgentSettings()
    fork_slug = f"{staging_repo.staging_org}/{staging_repo.staging_repo}"
    activity.logger.info("Posting comment on %s#%d", fork_slug, staging_repo.pr_number)
    github_client.post_issue_comment(fork_slug, staging_repo.pr_number, body, settings)


@activity.defn
async def reset_agent_hold_label(staging_repo: StagingRepo) -> None:
    settings = GitHubAgentSettings()
    fork_slug = f"{staging_repo.staging_org}/{staging_repo.staging_repo}"
    activity.logger.info("Resetting agent-hold label on %s#%d", fork_slug, staging_repo.pr_number)
    github_client.add_label(fork_slug, staging_repo.pr_number, "agent-hold", settings)


# ── Code generation activities ────────────────────────────────────────────────

@activity.defn
async def fetch_repo_context(source_org: str, source_repo: str, branch: str) -> dict:
    settings = GitHubAgentSettings()
    source_slug = f"{source_org}/{source_repo}"
    activity.logger.info("Fetching rich repo context for %s from upstream GitHub", source_slug)

    from agents.common.llm import get_context_budget
    ctx = github_client.fetch_rich_context(
        source_slug, settings, context_budget=get_context_budget(settings),
    )
    activity.logger.info(
        "Rich context for %s: default_branch=%s, agent_instructions=%d bytes, "
        "markdown_docs=%d files, dir_tree=%d bytes, key_files=%d files",
        source_slug, ctx["default_branch"], len(ctx.get("agent_instructions", "")),
        len(ctx.get("markdown_docs", [])), len(ctx.get("dir_tree", "")),
        len(ctx.get("key_files", [])),
    )
    return ctx


@activity.defn
async def fetch_files_for_editing(staging_repo: StagingRepo, file_paths: list[str]) -> dict[str, str]:
    """Fetch current content of files to be modified. Returns {path: content}."""
    settings = GitHubAgentSettings()
    fork_slug = f"{staging_repo.staging_org}/{staging_repo.staging_repo}"
    branch = staging_repo.feature_branch
    result: dict[str, str] = {}
    for path in file_paths:
        try:
            content = github_client.get_file_content(fork_slug, path, branch, settings)
            result[path] = content
            activity.logger.info("Fetched %s (%d bytes) for editing", path, len(content))
        except Exception:
            activity.logger.info("File %s not found on %s — will be created", path, branch)
    return result


@activity.defn
async def fetch_type_index(
    source_org: str,
    source_repo: str,
    directories: list[str],
) -> dict[str, list[dict]]:
    """Fetch existing Go type declarations in target directories."""
    settings = GitHubAgentSettings()
    source_slug = f"{source_org}/{source_repo}"
    activity.logger.info("Fetching type index for %s dirs=%s", source_slug, directories)
    index = github_client.fetch_package_type_index(source_slug, directories, settings)
    total = sum(len(v) for v in index.values())
    activity.logger.info("Type index: %d declarations across %d directories", total, len(index))
    return index


@activity.defn
async def generate_code_for_bundle(
    bundle: RepoPRBundle,
    feature_description: str,
    repo_context: dict,
    existing_files: dict[str, str] | None = None,
) -> list[FileChange]:
    settings = GitHubAgentSettings()
    activity.logger.info(
        "Generating code for %s (%d steps, %d existing files for editing)",
        bundle.repo, len(bundle.steps), len(existing_files or {}),
    )

    messages = prompts.render(
        "github_agent/generate_code.md",
        repo=bundle.repo,
        tier=bundle.tier,
        steps=bundle.steps,
        feature_description=feature_description,
        repo_context=repo_context,
        existing_files=existing_files or {},
    )

    class _CodeGenResponse(BaseModel):
        file_changes: list[FileChange]

    result = await llm.complete_structured(messages, settings, _CodeGenResponse)
    return result.file_changes


@activity.defn
async def update_pr_description(staging_repo: StagingRepo, result: CodeGenerationResult) -> None:
    settings = GitHubAgentSettings()
    fork_slug = f"{staging_repo.staging_org}/{staging_repo.staging_repo}"
    activity.logger.info("Updating PR description on %s#%d", fork_slug, staging_repo.pr_number)

    summary = "\n\n## Implementation Summary\n\n"
    summary += f"**Files changed ({len(result.files_changed)}):**\n"
    for path in result.files_changed:
        summary += f"- `{path}`\n"
    if result.commit_messages:
        summary += "\n**Commits:**\n"
        for msg in result.commit_messages:
            summary += f"- {msg}\n"

    current_body = github_client.get_pr_body(fork_slug, staging_repo.pr_number, settings)
    github_client.update_pr_body(fork_slug, staging_repo.pr_number, current_body + summary, settings)


@activity.defn
async def remove_agent_hold(staging_repo: StagingRepo) -> None:
    settings = GitHubAgentSettings()
    fork_slug = f"{staging_repo.staging_org}/{staging_repo.staging_repo}"
    activity.logger.info("Removing agent-hold from %s#%d", fork_slug, staging_repo.pr_number)
    github_client.remove_label(fork_slug, staging_repo.pr_number, "agent-hold", settings)


@activity.defn
async def store_implementation_result(result: FeatureImplementationResult, run_id: str) -> str:
    settings = GitHubAgentSettings()
    key = f"runs/{run_id}/impl-result.json"
    activity.logger.info("Storing implementation result to S3 key %s", key)
    return storage.put_artifact(key, result, settings)


# ── CI validation activities ────────────────────────────────────────────────

@activity.defn
async def fetch_repo_ci_config(source_org: str, source_repo: str, branch: str) -> list[CITest]:
    settings = GitHubAgentSettings()
    activity.logger.info("Fetching CI config for %s/%s@%s", source_org, source_repo, branch)
    return ci_config.fetch_ci_config(source_repo, branch, settings)


@activity.defn
async def run_repo_tests(staging_repo: StagingRepo, tests: list[CITest]) -> list[TestResult]:
    settings = GitHubAgentSettings()
    fork_slug = f"{staging_repo.staging_org}/{staging_repo.staging_repo}"

    from urllib.parse import urlparse  # noqa: PLC0415
    parsed = urlparse(settings.github_base_url)
    clone_url = f"{parsed.scheme}://{parsed.netloc}/{fork_slug}.git"

    activity.logger.info(
        "Running %d CI tests for %s on branch %s",
        len(tests), fork_slug, staging_repo.feature_branch,
    )
    return test_runner.run_tests(clone_url, staging_repo.feature_branch, tests, settings)


@activity.defn
async def generate_test_fixes(
    staging_repo: StagingRepo,
    failures: list[TestResult],
    bundle: RepoPRBundle,
    feature_description: str,
    repo_context: dict,
    attempt: int,
    max_attempts: int,
) -> list[FileChange]:
    settings = GitHubAgentSettings()
    activity.logger.info(
        "Generating fixes for %d test failures in %s (attempt %d/%d)",
        len(failures), bundle.repo, attempt, max_attempts,
    )
    messages = prompts.render(
        "github_agent/fix_test_failures.md",
        repo=bundle.repo,
        steps=bundle.steps,
        feature_description=feature_description,
        failures=[f.model_dump() for f in failures],
        repo_context=repo_context,
        attempt=attempt,
        max_attempts=max_attempts,
    )

    class _FixResponse(BaseModel):
        file_changes: list[FileChange]

    result = await llm.complete_structured(messages, settings, _FixResponse)
    return result.file_changes


# ── Gitea Actions CI activities ──────────────────────────────────────────────

@activity.defn
async def check_is_gitea() -> bool:
    settings = GitHubAgentSettings()
    return github_client.is_gitea(settings)


@activity.defn
async def push_ci_workflow(staging_repo: StagingRepo, tests: list[CITest]) -> None:
    """Generate a Gitea Actions workflow from CI tests and push it to the feature branch."""
    settings = GitHubAgentSettings()
    fork_slug = f"{staging_repo.staging_org}/{staging_repo.staging_repo}"
    branch = staging_repo.feature_branch

    stale_gitea = [n for n in github_client.list_directory(fork_slug, branch, ".gitea/workflows", settings) if n != "ci.yml"]
    upstream_gh = github_client.list_directory(fork_slug, branch, ".github/workflows", settings)

    if stale_gitea or upstream_gh:
        github_client.disable_repo_actions(fork_slug, settings)
        for name in stale_gitea:
            github_client.delete_file(fork_slug, branch, f".gitea/workflows/{name}", settings)
            activity.logger.info("Removed stale workflow: .gitea/workflows/%s", name)
        for name in upstream_gh:
            github_client.delete_file(fork_slug, branch, f".github/workflows/{name}", settings)
            activity.logger.info("Removed upstream workflow: .github/workflows/%s", name)

    repo_files = github_client.list_directory(fork_slug, branch, ".", settings)

    go_mod = None
    try:
        go_mod = github_client.get_file_content(fork_slug, "go.mod", branch, settings)
    except Exception:
        pass
    go_image = ci_workflow_generator.detect_go_image(go_mod, settings.go_builder_image)
    activity.logger.info("Using Go image %s for %s", go_image, fork_slug)

    lint_config = None
    for name in ci_workflow_generator._GOLANGCI_CONFIGS:
        if repo_files and name in repo_files:
            try:
                lint_config = github_client.get_file_content(fork_slug, name, branch, settings)
            except Exception:
                pass
            break

    workflow_yaml = ci_workflow_generator.generate_ci_workflow(tests, go_image, repo_files, lint_config)
    github_client.push_file_change(
        fork_slug, branch, ".gitea/workflows/ci.yml", workflow_yaml,
        "ci: add Gitea Actions CI workflow", settings,
    )

    github_client.enable_repo_actions(fork_slug, settings)
    activity.logger.info("Pushed CI workflow to %s on branch %s", fork_slug, branch)


@activity.defn
async def poll_ci_status(staging_repo: StagingRepo, expected_count: int) -> list[TestResult]:
    """Poll Gitea commit statuses until all checks complete or timeout."""
    settings = GitHubAgentSettings()
    fork_slug = f"{staging_repo.staging_org}/{staging_repo.staging_repo}"
    branch = staging_repo.feature_branch

    await asyncio.sleep(5)

    sha = github_client.get_branch_head_sha(fork_slug, branch, settings)
    activity.logger.info("Polling CI status for %s@%s (sha=%s, expecting %d checks)", fork_slug, branch, sha[:8], expected_count)

    ci_prefix = "CI / "
    max_polls = 40  # 40 * 15s = 10 minutes
    for i in range(max_polls):
        activity.heartbeat(f"poll {i+1}/{max_polls}")
        statuses = github_client.get_commit_statuses(fork_slug, sha, settings)

        latest: dict[str, dict] = {}
        for s in statuses:
            ctx = s["context"]
            if not ctx.startswith(ci_prefix):
                continue
            latest[ctx] = s

        if latest:
            pending = [s for s in latest.values() if s["state"] == "pending"]
            if not pending:
                activity.logger.info("All %d CI checks complete for %s", len(latest), sha[:8])
                return [
                    TestResult(
                        test_name=s["context"].removeprefix(ci_prefix),
                        passed=s["state"] == "success",
                        exit_code=0 if s["state"] == "success" else 1,
                        stdout=s.get("description", ""),
                    )
                    for s in latest.values()
                ]

        await asyncio.sleep(15)

    activity.logger.warning("Timeout waiting for CI statuses on %s", sha[:8])
    latest_statuses = github_client.get_commit_statuses(fork_slug, sha, settings)
    latest_final: dict[str, dict] = {}
    for s in latest_statuses:
        ctx = s["context"]
        if ctx.startswith(ci_prefix):
            latest_final[ctx] = s
    return [
        TestResult(
            test_name=s["context"].removeprefix(ci_prefix),
            passed=s["state"] == "success",
            exit_code=0 if s["state"] == "success" else 2,
            stdout=s.get("description", "") + (" [timed out]" if s["state"] == "pending" else ""),
        )
        for s in latest_final.values()
    ]
