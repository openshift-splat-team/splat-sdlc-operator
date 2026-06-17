"""GitHub operations for OpenShift enhancement doc PRs."""
from __future__ import annotations

import base64

import requests
from github import Github, GithubException
from github.PullRequest import PullRequest as GHPullRequest

from agents.common.models import CreatedPR, EnhancementDoc
from agents.common.settings import EnhancementAgentSettings


def _connect(settings: EnhancementAgentSettings) -> Github:
    return Github(settings.github_token, base_url=settings.github_base_url)


def _enhancement_path(feature_slug: str) -> str:
    return f"enhancements/{feature_slug}/README.md"


def _bullet_list(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "N/A"


def _render_doc_markdown(doc: EnhancementDoc) -> str:
    frontmatter = (
        "---\n"
        f"title: {doc.title}\n"
        "authors:\n  - TBD\n"
        "reviewers:\n  - TBD\n"
        "approvers:\n  - TBD\n"
        "api-approvers:\n  - TBD\n"
        "creation-date: TBD\n"
        "last-updated: TBD\n"
        "status: provisional\n"
        "---\n"
    )
    sections = [
        frontmatter,
        f"# {doc.title}",
        f"## Summary\n\n{doc.summary}",
        f"## Motivation\n\n{doc.motivation}",
        "### User Stories\n\n" + _bullet_list(doc.user_stories),
        "### Goals\n\n" + _bullet_list(doc.goals),
        "### Non-Goals\n\n" + _bullet_list(doc.non_goals),
        f"## Proposal\n\n{doc.proposal}",
        f"### Workflow Description\n\n{doc.workflow_description or 'N/A'}",
        f"### API Extensions\n\n{doc.api_extensions or 'N/A'}",
        f"### Topology Considerations\n\n{doc.topology_considerations or 'N/A'}",
        f"### Implementation Details/Notes/Constraints\n\n{doc.implementation_details or 'N/A'}",
        "### Risks and Mitigations\n\n" + _bullet_list(doc.risks),
        "### Drawbacks\n\n" + _bullet_list(doc.drawbacks),
        "## Alternatives (Not Implemented)\n\n" + _bullet_list(doc.alternatives),
        "## Open Questions [optional]\n\n" + _bullet_list(doc.open_questions),
        f"## Test Plan\n\n{doc.test_plan or 'N/A'}",
        f"## Graduation Criteria\n\n{doc.graduation_criteria or 'N/A'}",
        f"### Dev Preview -> Tech Preview\n\n{doc.graduation_dev_preview_to_tech_preview or 'N/A'}",
        f"### Tech Preview -> GA\n\n{doc.graduation_tech_preview_to_ga or 'N/A'}",
        f"## Upgrade / Downgrade Strategy\n\n{doc.upgrade_downgrade_strategy or 'N/A'}",
        f"## Version Skew Strategy\n\n{doc.version_skew_strategy or 'N/A'}",
        f"## Operational Aspects of API Extensions\n\n{doc.operational_aspects or 'N/A'}",
        f"## Support Procedures\n\n{doc.support_procedures or 'N/A'}",
        f"## Infrastructure Needed [optional]\n\n{doc.infrastructure_needed or 'N/A'}",
        "## Repositories to Fork\n\n" + (
            "\n".join(f"- `{r}`" for r in doc.repos_to_fork)
            if doc.repos_to_fork
            else "_No repositories identified._"
        ),
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
    try:
        repo.create_fork(organization=org)
    except GithubException as exc:
        if exc.status != 409:
            raise
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

    # PyGithub's create_git_ref (POST /git/refs) returns 405 on Gitea; use the branches API.
    owner, name = fork_slug.split("/", 1)
    base = settings.github_base_url.rstrip("/")
    default_branch = repo.default_branch
    resp = requests.post(
        f"{base}/repos/{owner}/{name}/branches",
        headers={"Authorization": f"token {settings.github_token}", "Content-Type": "application/json"},
        json={"new_branch_name": branch_name, "old_branch_name": default_branch},
        timeout=15,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Failed to create branch {branch_name} in {fork_slug}: {resp.status_code} {resp.text}")
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
    content_b64 = base64.b64encode(content.encode()).decode()

    try:
        existing = repo.get_contents(path, ref=branch)
        result = repo.update_file(path, message, content, existing.sha, branch=branch)
        return result["commit"].sha
    except GithubException:
        pass

    # Try PyGithub's create_file (PUT) — works on GitHub. Gitea rejects PUT without a SHA
    # (422 "[SHA]: Required"), so fall back to POST which is Gitea's create endpoint.
    try:
        result = repo.create_file(path, message, content, branch=branch)
        return result["commit"].sha
    except GithubException as exc:
        if exc.status != 422:
            raise

    owner, name = fork_slug.split("/", 1)
    base = settings.github_base_url.rstrip("/")
    resp = requests.post(
        f"{base}/repos/{owner}/{name}/contents/{path}",
        headers={"Authorization": f"token {settings.github_token}", "Content-Type": "application/json"},
        json={"message": message, "content": content_b64, "branch": branch},
        timeout=15,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Failed to create file {path} in {fork_slug}: {resp.status_code} {resp.text}")
    return resp.json()["commit"]["sha"]


def _ensure_label(repo_slug: str, label_name: str, issue_number: int, settings: EnhancementAgentSettings) -> None:
    """Create the label if needed and apply it to the issue/PR via REST API (Gitea-safe)."""
    owner, name = repo_slug.split("/", 1)
    base = settings.github_base_url.rstrip("/")
    headers = {"Authorization": f"token {settings.github_token}", "Content-Type": "application/json"}

    resp = requests.get(f"{base}/repos/{owner}/{name}/labels", headers=headers, timeout=10)
    label_id = None
    if resp.status_code == 200:
        for lbl in resp.json():
            if lbl["name"] == label_name:
                label_id = lbl["id"]
                break

    if label_id is None:
        resp = requests.post(
            f"{base}/repos/{owner}/{name}/labels",
            headers=headers,
            json={"name": label_name, "color": "#856404"},
            timeout=10,
        )
        if resp.status_code in (200, 201):
            label_id = resp.json()["id"]

    if label_id is not None:
        requests.post(
            f"{base}/repos/{owner}/{name}/issues/{issue_number}/labels",
            headers=headers,
            json={"labels": [label_id]},
            timeout=10,
        )


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

    try:
        pr: GHPullRequest = base.create_pull(
            title=title,
            body=body,
            head=f"{fork_owner}:{branch}",
            base=base_branch,
            draft=False,
        )
    except GithubException as exc:
        if exc.status != 409:
            raise
        existing = list(base.get_pulls(state="open", head=f"{fork_owner}:{branch}", base=base_branch))
        if not existing:
            raise
        pr = existing[0]
    _ensure_label(base_repo, "agent-hold", pr.number, settings)

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

    # PyGithub's pr.get_reviews() builds a URL path that Gitea returns without
    # the /api/v1 prefix, triggering an AssertionError in Requester.  Use the
    # Gitea REST API directly instead.
    owner, name = repo_slug.split("/", 1)
    base = settings.github_base_url.rstrip("/")
    resp = requests.get(
        f"{base}/repos/{owner}/{name}/pulls/{pr_number}/reviews",
        headers={"Authorization": f"token {settings.github_token}"},
        timeout=15,
    )
    approved_count = 0
    if resp.status_code == 200:
        approved_count = sum(1 for r in resp.json() if r.get("state") == "APPROVED")

    return {
        "state": pr.state,
        "merged": pr.merged,
        "approved_review_count": approved_count,
        "labels": [label.name for label in pr.labels],
    }


def get_pr_comments(
    repo_slug: str,
    pr_number: int,
    since_count: int,
    settings: EnhancementAgentSettings,
) -> list[dict]:
    """Fetch PR comments (issue + review) newer than `since_count` via Gitea REST API."""
    owner, name = repo_slug.split("/", 1)
    base = settings.github_base_url.rstrip("/")
    headers = {"Authorization": f"token {settings.github_token}"}

    all_comments: list[dict] = []

    # Issue-level comments (conversation tab)
    resp = requests.get(
        f"{base}/repos/{owner}/{name}/issues/{pr_number}/comments",
        headers=headers,
        timeout=15,
    )
    if resp.status_code == 200:
        for c in resp.json():
            all_comments.append({
                "id": c.get("id"),
                "body": c.get("body", ""),
                "author": c.get("user", {}).get("login", ""),
                "created_at": c.get("created_at", ""),
            })

    # Review comments (Files tab / inline code comments) — Gitea nests these
    # under each review, not at /pulls/{n}/comments (which returns 404).
    resp = requests.get(
        f"{base}/repos/{owner}/{name}/pulls/{pr_number}/reviews",
        headers=headers,
        timeout=15,
    )
    if resp.status_code == 200:
        for review in resp.json():
            review_id = review.get("id")
            rc_resp = requests.get(
                f"{base}/repos/{owner}/{name}/pulls/{pr_number}/reviews/{review_id}/comments",
                headers=headers,
                timeout=15,
            )
            if rc_resp.status_code == 200:
                for c in rc_resp.json():
                    all_comments.append({
                        "id": c.get("id"),
                        "body": c.get("body", ""),
                        "author": c.get("user", {}).get("login", ""),
                        "created_at": c.get("created_at", ""),
                    })

    bot_user = settings.github_bot_user
    all_comments = [c for c in all_comments if c["author"] != bot_user]
    all_comments.sort(key=lambda c: c.get("created_at", ""))
    return [
        {"id": c["id"], "body": c["body"], "author": c["author"]}
        for c in all_comments[since_count:]
    ]


def post_pr_comment(
    repo_slug: str,
    pr_number: int,
    body: str,
    settings: EnhancementAgentSettings,
) -> None:
    """Post a comment on the enhancement PR via Gitea REST API."""
    owner, name = repo_slug.split("/", 1)
    base = settings.github_base_url.rstrip("/")
    resp = requests.post(
        f"{base}/repos/{owner}/{name}/issues/{pr_number}/comments",
        headers={"Authorization": f"token {settings.github_token}", "Content-Type": "application/json"},
        json={"body": body},
        timeout=15,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(
            f"Failed to post comment on {repo_slug}#{pr_number}: {resp.status_code} {resp.text}"
        )
