"""Thin wrapper around the GitHub REST API via PyGithub."""
from __future__ import annotations

from github import Github, GithubException
from github.PullRequest import PullRequest as GHPullRequest

from agents.common.models import (
    CreatePRInput,
    CreatedPR,
    InlineComment,
    PRData,
    PRFile,
    StagingRepo,
)
from agents.common.settings import GitHubAgentSettings


def _connect(settings: GitHubAgentSettings) -> Github:
    return Github(settings.github_token, base_url=settings.github_base_url)


def _parse_pr_url(url: str) -> tuple[str, int]:
    """Extract 'owner/repo' and PR number from a GitHub PR URL."""
    parts = url.rstrip("/").split("/")
    pr_number = int(parts[-1])
    repo_slug = f"{parts[-4]}/{parts[-3]}"
    return repo_slug, pr_number


def fetch_pr(pr_url: str, settings: GitHubAgentSettings) -> PRData:
    gh = _connect(settings)
    repo_slug, pr_number = _parse_pr_url(pr_url)
    repo = gh.get_repo(repo_slug)
    pr: GHPullRequest = repo.get_pull(pr_number)

    files = [
        PRFile(filename=f.filename, patch=f.patch, status=f.status)
        for f in pr.get_files()
    ]

    diff_parts = []
    for f in files:
        if f.patch:
            diff_parts.append(f"--- {f.filename}\n{f.patch}")
    diff = "\n\n".join(diff_parts)
    if len(diff) > 60_000:
        diff = diff[:60_000] + "\n\n[diff truncated]"

    return PRData(
        url=pr_url,
        title=pr.title,
        body=pr.body,
        base_branch=pr.base.ref,
        head_branch=pr.head.ref,
        files=files,
        diff=diff,
    )


def post_review(
    pr_url: str,
    result_summary: str,
    comments: list[InlineComment],
    approved: bool,
    settings: GitHubAgentSettings,
) -> None:
    gh = _connect(settings)
    repo_slug, pr_number = _parse_pr_url(pr_url)
    repo = gh.get_repo(repo_slug)
    pr: GHPullRequest = repo.get_pull(pr_number)

    gh_comments = [
        {"path": c.path, "line": c.line, "body": f"[{c.severity.upper()}] {c.body}"}
        for c in comments
    ]
    event = "APPROVE" if approved else "COMMENT"
    pr.create_review(body=result_summary, event=event, comments=gh_comments)


def create_pr(input: CreatePRInput, settings: GitHubAgentSettings) -> CreatedPR:
    gh = _connect(settings)
    repo = gh.get_repo(input.repo)

    title = input.title
    body = input.body

    if input.jira_issue_key:
        title = f"[{input.jira_issue_key}] {title}"
        jira_link = f"\n\n---\nJira: [{input.jira_issue_key}]"
        body = body + jira_link

    pr: GHPullRequest = repo.create_pull(
        title=title,
        body=body,
        head=input.head_branch,
        base=input.base_branch,
        draft=input.draft,
    )

    return CreatedPR(
        url=pr.html_url,
        number=pr.number,
        title=pr.title,
        head_branch=input.head_branch,
        base_branch=input.base_branch,
        draft=input.draft,
    )


# ── Staging / fork / branch / label operations ────────────────────────────────

def _sync_default_branch(fork_slug: str, source_slug: str, settings: GitHubAgentSettings) -> None:
    """Merge upstream default branch into the fork's default branch."""
    gh = _connect(settings)
    fork = gh.get_repo(fork_slug)
    source = gh.get_repo(source_slug)
    default_branch = source.default_branch
    upstream_sha = source.get_branch(default_branch).commit.sha
    fork_ref = fork.get_git_ref(f"heads/{default_branch}")
    if fork_ref.object.sha != upstream_sha:
        fork_ref.edit(sha=upstream_sha, force=True)


def fork_repo(source_slug: str, target_org: str, settings: GitHubAgentSettings) -> str:
    """Fork source_slug into target_org, syncing default branch if fork exists.

    Returns fork slug 'org/repo'.
    """
    gh = _connect(settings)
    repo_name = source_slug.split("/")[-1]
    fork_slug = f"{target_org}/{repo_name}"

    try:
        gh.get_repo(fork_slug)
        _sync_default_branch(fork_slug, source_slug, settings)
        return fork_slug
    except GithubException:
        pass

    source = gh.get_repo(source_slug)
    org = gh.get_organization(target_org)
    source.create_fork(organization=org)
    return fork_slug


def create_branch(
    repo_slug: str,
    branch_name: str,
    from_ref: str,
    settings: GitHubAgentSettings,
) -> str:
    gh = _connect(settings)
    repo = gh.get_repo(repo_slug)

    try:
        repo.get_branch(branch_name)
        return branch_name
    except GithubException:
        pass

    ref = repo.get_git_ref(f"heads/{from_ref}")
    repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=ref.object.sha)
    return branch_name


def push_file_change(
    repo_slug: str,
    branch: str,
    path: str,
    content: str,
    commit_message: str,
    settings: GitHubAgentSettings,
) -> str:
    """Create or update a file on branch; returns commit sha."""
    gh = _connect(settings)
    repo = gh.get_repo(repo_slug)

    try:
        existing = repo.get_contents(path, ref=branch)
        result = repo.update_file(path, commit_message, content, existing.sha, branch=branch)
    except GithubException:
        result = repo.create_file(path, commit_message, content, branch=branch)

    return result["commit"].sha


def add_label(repo_slug: str, pr_number: int, label: str, settings: GitHubAgentSettings) -> None:
    gh = _connect(settings)
    pr: GHPullRequest = gh.get_repo(repo_slug).get_pull(pr_number)
    pr.add_to_labels(label)


def remove_label(repo_slug: str, pr_number: int, label: str, settings: GitHubAgentSettings) -> None:
    gh = _connect(settings)
    pr: GHPullRequest = gh.get_repo(repo_slug).get_pull(pr_number)
    try:
        pr.remove_from_labels(label)
    except GithubException:
        pass


def get_pr_labels(repo_slug: str, pr_number: int, settings: GitHubAgentSettings) -> list[str]:
    gh = _connect(settings)
    pr: GHPullRequest = gh.get_repo(repo_slug).get_pull(pr_number)
    return [label.name for label in pr.labels]


def get_pr_comments_since(
    repo_slug: str,
    pr_number: int,
    since_comment_id: int,
    settings: GitHubAgentSettings,
) -> list[dict]:
    gh = _connect(settings)
    issue = gh.get_repo(repo_slug).get_issue(pr_number)
    comments = []
    for c in issue.get_comments():
        if c.id > since_comment_id:
            comments.append({"id": c.id, "body": c.body, "author": c.user.login})
    return comments


def get_pr_state(repo_slug: str, pr_number: int, settings: GitHubAgentSettings) -> dict:
    gh = _connect(settings)
    pr: GHPullRequest = gh.get_repo(repo_slug).get_pull(pr_number)
    return {
        "state": pr.state,
        "merged": pr.merged,
        "labels": [label.name for label in pr.labels],
    }
