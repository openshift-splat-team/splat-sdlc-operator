"""Thin wrapper around the GitHub REST API via PyGithub."""
from __future__ import annotations

import base64
import logging
import re

import requests

logger = logging.getLogger(__name__)
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
    owner, name = input.repo.split("/", 1)
    api_base = settings.github_base_url.rstrip("/")
    headers = {"Authorization": f"token {settings.github_token}", "Content-Type": "application/json"}

    title = input.title
    body = input.body

    if input.jira_issue_key:
        title = f"[{input.jira_issue_key}] {title}"
        body = body + f"\n\n---\nJira: [{input.jira_issue_key}]"

    resp = requests.post(
        f"{api_base}/repos/{owner}/{name}/pulls",
        headers=headers,
        json={
            "title": title,
            "body": body,
            "head": input.head_branch,
            "base": input.base_branch,
        },
        timeout=30,
    )

    if resp.status_code == 409 or (resp.status_code == 422 and "already exists" in resp.text.lower()):
        list_resp = requests.get(
            f"{api_base}/repos/{owner}/{name}/pulls",
            headers=headers,
            params={"state": "open", "head": input.head_branch, "base": input.base_branch},
            timeout=15,
        )
        if list_resp.status_code == 200 and list_resp.json():
            pr_data = list_resp.json()[0]
        else:
            raise RuntimeError(f"PR conflict but no existing PR found: {resp.status_code} {resp.text[:200]}")
    elif resp.status_code in (200, 201):
        pr_data = resp.json()
    else:
        raise RuntimeError(f"Failed to create PR on {input.repo}: {resp.status_code} {resp.text[:200]}")

    from urllib.parse import urlparse  # noqa: PLC0415
    parsed = urlparse(api_base)
    web_base = f"{parsed.scheme}://{parsed.netloc}"

    return CreatedPR(
        url=pr_data.get("html_url") or f"{web_base}/{input.repo}/pulls/{pr_data['number']}",
        number=pr_data["number"],
        title=pr_data.get("title", title),
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
    if repo_data.get("empty", True):
        if resp.status_code == 201:
            requests.delete(f"{base}/repos/{org}/{repo_name}", headers=headers, timeout=10)
        return False

    branches = requests.get(
        f"{base}/repos/{org}/{repo_name}/branches?limit=1",
        headers=headers,
        timeout=10,
    )
    if branches.status_code != 200 or not branches.json():
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


def delete_file(repo_slug: str, branch: str, path: str, settings: GitHubAgentSettings) -> None:
    """Delete a file from a branch."""
    gh = _connect(settings)
    repo = gh.get_repo(repo_slug)
    try:
        existing = repo.get_contents(path, ref=branch)
        repo.delete_file(path, f"ci: remove stale workflow {path}", existing.sha, branch=branch)
    except GithubException:
        pass


def list_directory(repo_slug: str, branch: str, path: str, settings: GitHubAgentSettings) -> list[str]:
    """List file names in a directory on a branch. Returns empty list if dir doesn't exist."""
    gh = _connect(settings)
    repo = gh.get_repo(repo_slug)
    try:
        contents = repo.get_contents(path, ref=branch)
        if isinstance(contents, list):
            return [c.name for c in contents]
        return [contents.name]
    except GithubException:
        return []


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


# ── Rich context (upstream GitHub) ──────────────────────────────────────────

_GITHUB_API = "https://api.github.com"
_GITHUB_RAW = "https://raw.githubusercontent.com"
_DEFAULT_CONTEXT_BUDGET = 29_000  # ~7,250 tokens (leaves headroom for truncation markers)

_AGENT_FILES = {"CLAUDE.md", "AGENTS.md"}
_KEY_SOURCE_NAMES = {"types.go", "doc.go", "register.go"}


def _gh_headers(settings: GitHubAgentSettings) -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json"}
    token = settings.github_source_token
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _fetch_raw(slug: str, branch: str, path: str, settings: GitHubAgentSettings) -> str | None:
    """Fetch a single file's content from raw.githubusercontent.com."""
    url = f"{_GITHUB_RAW}/{slug}/{branch}/{path}"
    headers = {}
    if settings.github_source_token:
        headers["Authorization"] = f"token {settings.github_source_token}"
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            return resp.text
    except requests.RequestException:
        pass
    return None


def _build_dir_tree(tree_entries: list[dict], max_depth: int = 3, max_bytes: int = 5000) -> str:
    """Build a directory tree string from GitHub tree API entries."""
    lines: list[str] = []
    size = 0
    for entry in sorted(tree_entries, key=lambda e: e["path"]):
        path = entry["path"]
        depth = path.count("/")
        if depth >= max_depth:
            continue
        name = path.rsplit("/", 1)[-1]
        indent = "  " * depth
        prefix = "/" if entry["type"] == "tree" else " "
        line = f"{indent}{prefix}{name}"
        size += len(line) + 1
        if size > max_bytes:
            lines.append("... [tree truncated]")
            break
        lines.append(line)
    return "\n".join(lines)


def fetch_rich_context(
    source_slug: str,
    settings: GitHubAgentSettings,
    context_budget: int | None = None,
) -> dict:
    """Fetch rich repo context from upstream GitHub for LLM code generation.

    Caches the result in S3 keyed by repo slug. Uses the upstream repo's
    ``pushed_at`` timestamp to detect staleness — if the repo hasn't been
    pushed to since the last cache, the cached context is returned immediately.

    Returns dict with: default_branch, agent_instructions, markdown_docs,
    dir_tree, go_mod, key_files.
    """
    if context_budget is None:
        context_budget = _DEFAULT_CONTEXT_BUDGET
    from agents.common import storage  # noqa: PLC0415

    headers = _gh_headers(settings)
    result: dict = {
        "default_branch": "master",
        "agent_instructions": "",
        "markdown_docs": [],
        "dir_tree": "",
        "go_mod": "",
        "readme": "",
        "key_files": [],
        "dir_listing": "",
    }

    # 1. Get repo metadata (default branch + pushed_at for cache validation)
    repo_resp = requests.get(
        f"{_GITHUB_API}/repos/{source_slug}",
        headers=headers,
        timeout=15,
    )
    if repo_resp.status_code != 200:
        return result
    repo_meta = repo_resp.json()
    default_branch = repo_meta.get("default_branch", "master")
    pushed_at = repo_meta.get("pushed_at", "")
    result["default_branch"] = default_branch

    # 2. Check S3 cache
    cache_key = f"repo-context/{source_slug}.json"
    try:
        cached = storage.get_json(cache_key, settings)
    except Exception:
        cached = None
    if cached and cached.get("_pushed_at") == pushed_at and pushed_at:
        logger.info("Cache hit for %s (pushed_at=%s)", source_slug, pushed_at)
        cached.pop("_pushed_at", None)
        return cached
    logger.info("Cache miss for %s (pushed_at=%s), fetching from GitHub", source_slug, pushed_at)

    # 2. Get full recursive tree (single API call)
    tree_resp = requests.get(
        f"{_GITHUB_API}/repos/{source_slug}/git/trees/{default_branch}?recursive=1",
        headers=headers,
        timeout=30,
    )
    if tree_resp.status_code != 200:
        return result
    tree_data = tree_resp.json()
    tree_entries = tree_data.get("tree", [])

    # 3. Build 3-level directory tree from the tree response
    result["dir_tree"] = _build_dir_tree(tree_entries, max_depth=3, max_bytes=5000)
    # Legacy field for backward compat
    result["dir_listing"] = _build_dir_tree(tree_entries, max_depth=1, max_bytes=2000)

    budget = context_budget - len(result["dir_tree"])

    # 4. Classify files of interest
    agent_paths: list[str] = []
    claude_cmd_paths: list[str] = []
    markdown_paths: list[str] = []
    key_source_paths: list[str] = []

    for entry in tree_entries:
        if entry["type"] != "blob":
            continue
        path = entry["path"]
        name = path.rsplit("/", 1)[-1]

        if name in _AGENT_FILES and "/" not in path:
            agent_paths.append(path)
        elif path.startswith(".claude/commands/") and name.endswith(".md"):
            claude_cmd_paths.append(path)
        elif name.endswith(".md") and name not in _AGENT_FILES:
            markdown_paths.append(path)
        elif name in _KEY_SOURCE_NAMES:
            key_source_paths.append(path)
        elif name == "go.mod" and "/" not in path:
            content = _fetch_raw(source_slug, default_branch, path, settings)
            if content:
                result["go_mod"] = content[:3000]
                budget -= len(result["go_mod"])

    # 5. Fetch agent instructions (highest priority)
    agent_parts: list[str] = []
    for path in agent_paths:
        content = _fetch_raw(source_slug, default_branch, path, settings)
        if content:
            agent_parts.append(content)
    for path in claude_cmd_paths:
        content = _fetch_raw(source_slug, default_branch, path, settings)
        if content:
            agent_parts.append(f"### {path}\n{content}")

    if agent_parts:
        agent_text = "\n\n---\n\n".join(agent_parts)
        if len(agent_text) > 10_000:
            agent_text = agent_text[:10_000] + "\n\n[truncated]"
        result["agent_instructions"] = agent_text
        budget -= len(agent_text)

    # 6. Fetch markdown docs (prioritize root, then docs/, then others)
    def _md_sort_key(p: str) -> tuple[int, str]:
        if "/" not in p:
            return (0, p)
        if p.startswith("docs/"):
            return (1, p)
        return (2, p)

    markdown_paths.sort(key=_md_sort_key)
    md_budget = min(max(budget, 0), 10_000)
    md_used = 0
    for path in markdown_paths[:15]:
        content = _fetch_raw(source_slug, default_branch, path, settings)
        if content:
            name = path.rsplit("/", 1)[-1]
            if name.lower() in ("readme.md", "readme") and "/" not in path:
                result["readme"] = content[:2000]
            max_file = min(3000, md_budget - md_used)
            if max_file <= 0:
                break
            truncated = content[:max_file]
            if len(content) > max_file:
                truncated += "\n\n[truncated]"
            result["markdown_docs"].append({"path": path, "content": truncated})
            md_used += len(truncated)
    budget -= md_used

    # 7. Fetch key source files (remaining budget)
    src_budget = max(budget, 0)
    src_used = 0
    for path in key_source_paths[:20]:
        if src_used >= src_budget:
            break
        content = _fetch_raw(source_slug, default_branch, path, settings)
        if content:
            truncated = content[:2000]
            if len(content) > 2000:
                truncated += "\n\n[truncated]"
            result["key_files"].append({"path": path, "content": truncated})
            src_used += len(truncated)

    # Store in S3 cache with pushed_at for future validation
    if pushed_at:
        try:
            storage.put_json(cache_key, {**result, "_pushed_at": pushed_at}, settings)
        except Exception:
            pass  # cache write failure is non-fatal

    return result


_TYPE_DECL_RE = re.compile(r"^\s*type\s+(\w+)\s+", re.MULTILINE)


def fetch_package_type_index(
    source_slug: str,
    directories: list[str],
    settings: GitHubAgentSettings,
) -> dict[str, list[dict]]:
    """Scan .go files in *directories* and return existing type declarations.

    Returns ``{directory: [{name, file, line}, ...]}``.  Used to prevent the
    code-generation LLM from redeclaring types that already exist.
    """
    headers = _gh_headers(settings)

    resp = requests.get(
        f"{_GITHUB_API}/repos/{source_slug}/git/trees/master?recursive=1",
        headers=headers,
        timeout=30,
    )
    if resp.status_code != 200:
        return {}

    entries = resp.json().get("tree", [])

    dir_set = {d.rstrip("/") for d in directories}
    go_files: dict[str, list[str]] = {}
    for entry in entries:
        if entry["type"] != "blob":
            continue
        path = entry["path"]
        name = path.rsplit("/", 1)[-1]
        if not name.endswith(".go"):
            continue
        if name.endswith("_test.go") or name.startswith("zz_generated"):
            continue
        parent = path.rsplit("/", 1)[0] if "/" in path else "."
        if parent in dir_set:
            go_files.setdefault(parent, []).append(path)

    index: dict[str, list[dict]] = {}
    for directory in sorted(go_files):
        decls: list[dict] = []
        for path in sorted(go_files[directory]):
            content = _fetch_raw(source_slug, "master", path, settings)
            if not content:
                continue
            filename = path.rsplit("/", 1)[-1]
            for i, line in enumerate(content.splitlines(), 1):
                m = _TYPE_DECL_RE.match(line)
                if m:
                    decls.append({"name": m.group(1), "file": filename, "line": i})
        if decls:
            index[directory] = decls
    return index


def get_pr_body(repo_slug: str, pr_number: int, settings: GitHubAgentSettings) -> str:
    owner, name = repo_slug.split("/", 1)
    base = settings.github_base_url.rstrip("/")
    headers = {"Authorization": f"token {settings.github_token}"}
    resp = requests.get(f"{base}/repos/{owner}/{name}/pulls/{pr_number}", headers=headers, timeout=15)
    if resp.status_code == 200:
        return resp.json().get("body") or ""
    return ""


def update_pr_body(repo_slug: str, pr_number: int, body: str, settings: GitHubAgentSettings) -> None:
    owner, name = repo_slug.split("/", 1)
    base = settings.github_base_url.rstrip("/")
    headers = {"Authorization": f"token {settings.github_token}", "Content-Type": "application/json"}
    resp = requests.patch(
        f"{base}/repos/{owner}/{name}/pulls/{pr_number}",
        headers=headers,
        json={"body": body},
        timeout=15,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Failed to update PR body on {repo_slug}#{pr_number}: {resp.status_code} {resp.text[:200]}")


def post_issue_comment(repo_slug: str, pr_number: int, body: str, settings: GitHubAgentSettings) -> None:
    owner, name = repo_slug.split("/", 1)
    base = settings.github_base_url.rstrip("/")
    headers = {"Authorization": f"token {settings.github_token}", "Content-Type": "application/json"}
    resp = requests.post(
        f"{base}/repos/{owner}/{name}/issues/{pr_number}/comments",
        headers=headers,
        json={"body": body},
        timeout=15,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Failed to post comment on {repo_slug}#{pr_number}: {resp.status_code} {resp.text[:200]}")


def get_branch_head_sha(repo_slug: str, branch: str, settings: GitHubAgentSettings) -> str:
    owner, name = repo_slug.split("/", 1)
    base = settings.github_base_url.rstrip("/")
    headers = {"Authorization": f"token {settings.github_token}"}
    resp = requests.get(f"{base}/repos/{owner}/{name}/branches/{branch}", headers=headers, timeout=15)
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to get branch {branch} on {repo_slug}: {resp.status_code}")
    return resp.json()["commit"]["id"]


def get_commit_statuses(repo_slug: str, sha: str, settings: GitHubAgentSettings) -> list[dict]:
    owner, name = repo_slug.split("/", 1)
    base = settings.github_base_url.rstrip("/")
    headers = {"Authorization": f"token {settings.github_token}"}
    resp = requests.get(f"{base}/repos/{owner}/{name}/statuses/{sha}", headers=headers, timeout=15)
    if resp.status_code != 200:
        return []
    return [
        {"context": s.get("context", ""), "state": s.get("status", s.get("state", "")), "description": s.get("description", "")}
        for s in resp.json()
    ]


def enable_repo_actions(repo_slug: str, settings: GitHubAgentSettings) -> None:
    _set_repo_actions(repo_slug, True, settings)


def disable_repo_actions(repo_slug: str, settings: GitHubAgentSettings) -> None:
    _set_repo_actions(repo_slug, False, settings)


def _set_repo_actions(repo_slug: str, enabled: bool, settings: GitHubAgentSettings) -> None:
    owner, name = repo_slug.split("/", 1)
    base = settings.github_base_url.rstrip("/")
    headers = {"Authorization": f"token {settings.github_token}", "Content-Type": "application/json"}
    resp = requests.patch(
        f"{base}/repos/{owner}/{name}",
        headers=headers,
        json={"has_actions": enabled},
        timeout=15,
    )
    if resp.status_code in (200, 201):
        logger.info("Actions %s on %s", "enabled" if enabled else "disabled", repo_slug)
    else:
        logger.warning("Failed to set actions=%s on %s: %d", enabled, repo_slug, resp.status_code)


def get_pr_state(repo_slug: str, pr_number: int, settings: GitHubAgentSettings) -> dict:
    owner, name = repo_slug.split("/", 1)
    base = settings.github_base_url.rstrip("/")
    headers = {"Authorization": f"token {settings.github_token}"}
    resp = requests.get(f"{base}/repos/{owner}/{name}/pulls/{pr_number}", headers=headers, timeout=15)
    if resp.status_code != 200:
        return {"state": "unknown", "merged": False, "labels": []}
    pr_data = resp.json()
    labels = [lbl["name"] for lbl in pr_data.get("labels", [])]
    return {
        "state": pr_data.get("state", "unknown"),
        "merged": pr_data.get("merged", False),
        "labels": labels,
    }
