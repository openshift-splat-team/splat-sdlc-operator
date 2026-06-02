"""Read-only GitHub client for inspecting openshift org repositories."""
from __future__ import annotations

from github import Github

from agents.common.settings import OpenShiftAgentSettings


def _connect(settings: OpenShiftAgentSettings) -> Github:
    return Github(settings.github_token, base_url=settings.github_base_url)


def get_go_mod(repo_name: str, settings: OpenShiftAgentSettings) -> str | None:
    """Return the contents of go.mod for an openshift org repo, or None if absent."""
    gh = _connect(settings)
    try:
        repo = gh.get_repo(f"openshift/{repo_name}")
        content = repo.get_contents("go.mod")
        return content.decoded_content.decode()
    except Exception:
        return None


def get_repo_topics(repo_name: str, settings: OpenShiftAgentSettings) -> list[str]:
    gh = _connect(settings)
    try:
        return gh.get_repo(f"openshift/{repo_name}").get_topics()
    except Exception:
        return []


def get_open_prs(repo_name: str, settings: OpenShiftAgentSettings, limit: int = 20) -> list[dict]:
    """Return recent open PRs for a repo as plain dicts."""
    gh = _connect(settings)
    try:
        repo = gh.get_repo(f"openshift/{repo_name}")
        prs = repo.get_pulls(state="open", sort="updated", direction="desc")
        return [
            {
                "number": pr.number,
                "title": pr.title,
                "url": pr.html_url,
                "author": pr.user.login,
                "labels": [lb.name for lb in pr.labels],
                "draft": pr.draft,
            }
            for pr in list(prs)[:limit]
        ]
    except Exception:
        return []
