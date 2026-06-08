"""Thin wrapper around the Jira REST API."""
from __future__ import annotations

import re

from jira import JIRA

from agents.common.models import JiraEpic, JiraStory
from agents.common.settings import RequirementsAgentSettings


def _connect(settings: RequirementsAgentSettings) -> JIRA:
    return JIRA(
        server=settings.jira_url,
        basic_auth=(settings.jira_user, settings.jira_token),
    )


def parse_issue_key(url_or_key: str) -> str:
    """Accept a Jira issue key or a URL (real Jira or simulator) and return the bare key."""
    # Real Jira: https://issues.redhat.com/browse/OCPBUGS-1234
    # Simulator:  http://localhost:8080/ui/issue/SPLAT-2724
    match = re.search(r'/(?:browse|issue)/([A-Z][A-Z0-9_]+-\d+)', url_or_key)
    if match:
        return match.group(1)
    # Bare key like PROJ-123
    if re.fullmatch(r'[A-Z][A-Z0-9_]+-\d+', url_or_key.strip()):
        return url_or_key.strip()
    raise ValueError(f"Cannot parse Jira issue key from: {url_or_key!r}")


def fetch_epic(epic_key_or_url: str, settings: RequirementsAgentSettings) -> JiraEpic:
    epic_key = parse_issue_key(epic_key_or_url)
    jira = _connect(settings)
    epic_issue = jira.issue(epic_key)

    target_ocp_version: str | None = None
    for v in getattr(epic_issue.fields, "fixVersions", None) or []:
        m = re.search(r'4\.\d+', getattr(v, "name", ""))
        if m:
            target_ocp_version = m.group(0)
            break

    epic = JiraEpic(
        key=epic_issue.key,
        summary=epic_issue.fields.summary,
        description=getattr(epic_issue.fields, "description", None),
        target_ocp_version=target_ocp_version,
    )

    # Fetch parent context if present
    parent = getattr(epic_issue.fields, "parent", None)
    if parent:
        try:
            parent_issue = jira.issue(parent.key)
            epic.parent_key = parent_issue.key
            epic.parent_summary = parent_issue.fields.summary
            epic.parent_description = getattr(parent_issue.fields, "description", None)
        except Exception:
            pass

    # Fetch child stories via JQL
    jql = f'"Epic Link" = {epic_key} OR "parent" = {epic_key}'
    children = jira.search_issues(jql, maxResults=50)
    for issue in children:
        story_points = getattr(issue.fields, "story_points", None) or getattr(
            issue.fields, "customfield_10016", None
        )
        epic.stories.append(
            JiraStory(
                key=issue.key,
                summary=issue.fields.summary,
                description=getattr(issue.fields, "description", None),
                story_points=float(story_points) if story_points else None,
                status=issue.fields.status.name,
            )
        )

    return epic
