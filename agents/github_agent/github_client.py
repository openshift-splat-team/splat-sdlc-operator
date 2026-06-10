"""Thin wrapper around the GitHub REST API via PyGithub."""
from __future__ import annotations

import base64

import requests
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

    try:
        pr: GHPullRequest = repo.create_pull(
            title=title,
            body=body,
            head=input.head_branch,
            base=input.base_branch,
            draft=input.draft,
        )
    except GithubException as exc:
        if exc.status != 409:
            raise
        existing = list(repo.get_pulls(state="open", head=input.head_branch, base=input.base_branch))
        if not existing:
            raise
        pr = existing[0]

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
    try:
        source.create_fork(organization=org)
    except GithubException as exc:
        if exc.status != 409:
            raise
    return fork_slug


def is_gitea(settings: GitHubAgentSettings) -> bool:
    return "api.github.com" not in settings.github_base_url


def mirror_repo(source_slug: str, settings: GitHubAgentSettings) -> bool:
    """Mirror a GitHub repo into Gitea via the migrate API.

    Returns True if the mirror exists (created or already present), False on failure.
    No-op (returns True) when not using Gitea.
    """
    if not is_gitea(settings):
        return True

    base = settings.github_base_url.rstrip("/")
    headers = {"Authorization": f"token {settings.github_token}", "Content-Type": "application/json"}
    org = source_slug.split("/")[0]
    repo_name = source_slug.split("/")[-1]

    requests.post(
        f"{base}/orgs",
        headers=headers,
        json={"username": org, "visibility": "public"},
        timeout=10,
    )

    resp = requests.post(
        f"{base}/repos/migrate",
        headers=headers,
        json={
            "clone_addr": f"https://github.com/{source_slug}",
            "repo_name": repo_name,
            "repo_owner": org,
            "mirror": True,
            "mirror_interval": "8h",
            "private": False,
        },
        timeout=60,
    )
    if resp.status_code not in (201, 409):
        return False

    verify = requests.get(
        f"{base}/repos/{org}/{repo_name}",
        headers=headers,
        timeout=10,
    )
    if verify.status_code != 200:
        return False
    repo_data = verify.json()
    if repo_data.get("empty", True) and resp.status_code == 201:
        requests.delete(f"{base}/repos/{org}/{repo_name}", headers=headers, timeout=10)
        return False
    return True


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

    # PyGithub's create_git_ref (POST /git/refs) returns 405 on Gitea; use the branches API.
    owner, name = repo_slug.split("/", 1)
    base = settings.github_base_url.rstrip("/")
    resp = requests.post(
        f"{base}/repos/{owner}/{name}/branches",
        headers={"Authorization": f"token {settings.github_token}", "Content-Type": "application/json"},
        json={"new_branch_name": branch_name, "old_branch_name": from_ref},
        timeout=15,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Failed to create branch {branch_name} in {repo_slug}: {resp.status_code} {resp.text}")
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
        return result["commit"].sha
    except GithubException:
        pass

    # Try PyGithub's create_file (PUT) — works on GitHub. Gitea rejects PUT without a SHA
    # (422 "[SHA]: Required"), so fall back to POST which is Gitea's create endpoint.
    try:
        result = repo.create_file(path, commit_message, content, branch=branch)
        return result["commit"].sha
    except GithubException as exc:
        if exc.status != 422:
            raise

    owner, name = repo_slug.split("/", 1)
    base = settings.github_base_url.rstrip("/")
    content_b64 = base64.b64encode(content.encode()).decode()
    resp = requests.post(
        f"{base}/repos/{owner}/{name}/contents/{path}",
        headers={"Authorization": f"token {settings.github_token}", "Content-Type": "application/json"},
        json={"message": commit_message, "content": content_b64, "branch": branch},
        timeout=15,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Failed to create file {path} in {repo_slug}: {resp.status_code} {resp.text}")
    return resp.json()["commit"]["sha"]


def add_label(repo_slug: str, pr_number: int, label: str, settings: GitHubAgentSettings) -> None:
    owner, name = repo_slug.split("/", 1)
    base = settings.github_base_url.rstrip("/")
    headers = {"Authorization": f"token {settings.github_token}", "Content-Type": "application/json"}

    resp = requests.get(f"{base}/repos/{owner}/{name}/labels", headers=headers, timeout=10)
    label_id = None
    if resp.status_code == 200:
        for lbl in resp.json():
            if lbl["name"] == label:
                label_id = lbl["id"]
                break

    if label_id is None:
        resp = requests.post(
            f"{base}/repos/{owner}/{name}/labels",
            headers=headers,
            json={"name": label, "color": "#856404"},
            timeout=10,
        )
        if resp.status_code in (200, 201):
            label_id = resp.json()["id"]

    if label_id is not None:
        requests.post(
            f"{base}/repos/{owner}/{name}/issues/{pr_number}/labels",
            headers=headers,
            json={"labels": [label_id]},
            timeout=10,
        )


def remove_label(repo_slug: str, pr_number: int, label: str, settings: GitHubAgentSettings) -> None:
    owner, name = repo_slug.split("/", 1)
    base = settings.github_base_url.rstrip("/")
    headers = {"Authorization": f"token {settings.github_token}"}

    resp = requests.get(f"{base}/repos/{owner}/{name}/labels", headers=headers, timeout=10)
    if resp.status_code == 200:
        for lbl in resp.json():
            if lbl["name"] == label:
                requests.delete(
                    f"{base}/repos/{owner}/{name}/issues/{pr_number}/labels/{lbl['id']}",
                    headers=headers,
                    timeout=10,
                )
                break


def get_pr_labels(repo_slug: str, pr_number: int, settings: GitHubAgentSettings) -> list[str]:
    owner, name = repo_slug.split("/", 1)
    base = settings.github_base_url.rstrip("/")
    headers = {"Authorization": f"token {settings.github_token}"}
    resp = requests.get(f"{base}/repos/{owner}/{name}/issues/{pr_number}/labels", headers=headers, timeout=10)
    if resp.status_code == 200:
        return [lbl["name"] for lbl in resp.json()]
    return []


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


def get_file_content(repo_slug: str, path: str, ref: str, settings: GitHubAgentSettings) -> str:
    """Return decoded text content of a file at the given ref."""
    gh = _connect(settings)
    contents = gh.get_repo(repo_slug).get_contents(path, ref=ref)
    return contents.decoded_content.decode("utf-8")


def get_repo_context(source_slug: str, branch: str, settings: GitHubAgentSettings) -> dict:
    """Fetch go.mod, README (truncated), and root directory listing from a repo."""
    gh = _connect(settings)
    repo = gh.get_repo(source_slug)

    go_mod = ""
    try:
        go_mod = repo.get_contents("go.mod", ref=branch).decoded_content.decode("utf-8")
    except GithubException:
        pass

    readme = ""
    for name in ("README.md", "readme.md", "README"):
        try:
            readme = repo.get_contents(name, ref=branch).decoded_content.decode("utf-8")
            readme = readme[:2000]
            break
        except GithubException:
            pass

    dir_listing = ""
    try:
        contents = repo.get_contents("", ref=branch)
        dir_listing = "\n".join(
            f"{'/' if c.type == 'dir' else ' '}{c.name}"
            for c in sorted(contents, key=lambda c: (c.type != "dir", c.name))
        )
    except GithubException:
        pass

    return {"go_mod": go_mod, "readme": readme, "dir_listing": dir_listing}


def get_pr_body(repo_slug: str, pr_number: int, settings: GitHubAgentSettings) -> str:
    gh = _connect(settings)
    pr: GHPullRequest = gh.get_repo(repo_slug).get_pull(pr_number)
    return pr.body or ""


def update_pr_body(repo_slug: str, pr_number: int, body: str, settings: GitHubAgentSettings) -> None:
    gh = _connect(settings)
    pr: GHPullRequest = gh.get_repo(repo_slug).get_pull(pr_number)
    pr.edit(body=body)


def post_issue_comment(repo_slug: str, pr_number: int, body: str, settings: GitHubAgentSettings) -> None:
    gh = _connect(settings)
    gh.get_repo(repo_slug).get_issue(pr_number).create_comment(body)


def get_pr_state(repo_slug: str, pr_number: int, settings: GitHubAgentSettings) -> dict:
    gh = _connect(settings)
    pr: GHPullRequest = gh.get_repo(repo_slug).get_pull(pr_number)
    return {
        "state": pr.state,
        "merged": pr.merged,
        "labels": [label.name for label in pr.labels],
    }
