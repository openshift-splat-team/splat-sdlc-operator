"""GitHub operations for OpenShift enhancement doc PRs."""
from __future__ import annotations

import base64

from github import Github, GithubException
from github.PullRequest import PullRequest as GHPullRequest

from agents.common.models import CreatedPR, EnhancementDoc
from agents.common.settings import EnhancementAgentSettings


def _connect(settings: EnhancementAgentSettings) -> Github:
    return Github(settings.github_token)


def _enhancement_path(feature_slug: str) -> str:
    return f"enhancements/{feature_slug}/README.md"


def _render_doc_markdown(doc: EnhancementDoc) -> str:
    sections = [
        f"# {doc.title}",
        "",
        f"## Summary\n\n{doc.summary}",
        f"## Motivation\n\n{doc.motivation}",
        "## Goals\n\n" + "\n".join(f"- {g}" for g in doc.goals),
        "## Non-Goals\n\n" + "\n".join(f"- {ng}" for ng in doc.non_goals),
        f"## Proposal\n\n{doc.proposal}",
        f"## Implementation Details\n\n{doc.implementation_details}",
        f"## Graduation Criteria\n\n{doc.graduation_criteria}",
        "## Risks and Mitigations\n\n" + "\n".join(f"- {r}" for r in doc.risks),
        "## Drawbacks\n\n" + "\n".join(f"- {d}" for d in doc.drawbacks),
        "## Alternatives\n\n" + "\n".join(f"- {a}" for a in doc.alternatives),
    ]
    return "\n\n".join(sections)


def _sync_default_branch(fork_slug: str, source_slug: str, settings: EnhancementAgentSettings) -> None:
    """Fast-forward the fork's default branch to match upstream."""
    gh = _connect(settings)
    source = gh.get_repo(source_slug)
    fork = gh.get_repo(fork_slug)
    default_branch = source.default_branch
    upstream_sha = source.get_branch(default_branch).commit.sha
    fork_ref = fork.get_git_ref(f"heads/{default_branch}")
    if fork_ref.object.sha != upstream_sha:
        fork_ref.edit(sha=upstream_sha, force=True)


def fork_enhancement_repo(
    enhancement_repo: str,
    staging_org: str,
    settings: EnhancementAgentSettings,
) -> str:
    """Fork enhancement_repo into staging_org, syncing default branch if fork exists.

    Returns fork slug 'org/repo'.
    """
    gh = _connect(settings)
    repo_name = enhancement_repo.split("/")[-1]
    fork_slug = f"{staging_org}/{repo_name}"

    try:
        gh.get_repo(fork_slug)
        _sync_default_branch(fork_slug, enhancement_repo, settings)
        return fork_slug
    except GithubException:
        pass

    repo = gh.get_repo(enhancement_repo)
    org = gh.get_organization(staging_org)
    repo.create_fork(organization=org)
    return fork_slug


def create_enhancement_branch(
    fork_slug: str,
    branch_name: str,
    settings: EnhancementAgentSettings,
) -> str:
    """Create a feature branch in the fork; returns branch_name."""
    gh = _connect(settings)
    repo = gh.get_repo(fork_slug)

    # Check if branch already exists
    try:
        repo.get_branch(branch_name)
        return branch_name
    except GithubException:
        pass

    default_branch = repo.default_branch
    ref = repo.get_git_ref(f"heads/{default_branch}")
    repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=ref.object.sha)
    return branch_name


def commit_enhancement_doc(
    fork_slug: str,
    branch: str,
    doc: EnhancementDoc,
    feature_slug: str,
    settings: EnhancementAgentSettings,
) -> str:
    """Commit the enhancement doc markdown to the branch; returns the commit sha."""
    gh = _connect(settings)
    repo = gh.get_repo(fork_slug)
    path = _enhancement_path(feature_slug)
    content = _render_doc_markdown(doc)
    message = f"enhancements: add {feature_slug} enhancement proposal"

    try:
        existing = repo.get_contents(path, ref=branch)
        result = repo.update_file(path, message, content, existing.sha, branch=branch)
    except GithubException:
        result = repo.create_file(path, message, content, branch=branch)

    return result["commit"].sha


def create_enhancement_pr(
    fork_slug: str,
    branch: str,
    base_repo: str,
    base_branch: str,
    doc: EnhancementDoc,
    jira_story_key: str | None,
    settings: EnhancementAgentSettings,
) -> CreatedPR:
    """Open a PR from fork:branch against base_repo:base_branch."""
    gh = _connect(settings)
    base = gh.get_repo(base_repo)
    fork_owner = fork_slug.split("/")[0]

    title = doc.title
    body = f"{doc.summary}\n\n## Motivation\n\n{doc.motivation}"
    if jira_story_key:
        title = f"[{jira_story_key}] {title}"
        body += f"\n\n---\nJira: {jira_story_key}"

    pr: GHPullRequest = base.create_pull(
        title=title,
        body=body,
        head=f"{fork_owner}:{branch}",
        base=base_branch,
        draft=False,
    )
    return CreatedPR(
        url=pr.html_url,
        number=pr.number,
        title=pr.title,
        head_branch=branch,
        base_branch=base_branch,
        draft=False,
    )


def get_pr_state(
    repo_slug: str,
    pr_number: int,
    settings: EnhancementAgentSettings,
) -> dict:
    gh = _connect(settings)
    repo = gh.get_repo(repo_slug)
    pr: GHPullRequest = repo.get_pull(pr_number)

    reviews = list(pr.get_reviews())
    approved_count = sum(1 for r in reviews if r.state == "APPROVED")

    return {
        "state": pr.state,
        "merged": pr.merged,
        "approved_review_count": approved_count,
        "labels": [label.name for label in pr.labels],
    }
