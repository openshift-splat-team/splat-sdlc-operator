"""Jira write operations — create/update epics, stories, comments, and links."""
from __future__ import annotations

from jira import JIRA
from agents.requirements_agent.jira_client import parse_issue_key

from agents.common.models import (
    JiraCommentResult,
    JiraEpic,
    JiraEpicUpdate,
    JiraStoryCreated,
    JiraStoryDraft,
)
from agents.common.settings import JiraAgentSettings


def _connect(settings: JiraAgentSettings) -> JIRA:
    return JIRA(
        server=settings.jira_url,
        basic_auth=(settings.jira_user, settings.jira_token),
    )


def create_epic(summary: str, description: str, settings: JiraAgentSettings) -> JiraEpicUpdate:
    jira = _connect(settings)
    issue = jira.create_issue(
        fields={
            "summary": summary,
            "description": description,
            "issuetype": {"name": "Epic"},
        }
    )
    return JiraEpicUpdate(key=issue.key, summary=summary, description=description)


def get_epic(epic_key_or_url: str, settings: JiraAgentSettings) -> JiraEpic:
    """Fetch an epic by key or URL (read path for the jira_agent)."""
    epic_key = parse_issue_key(epic_key_or_url)
    jira = _connect(settings)
    issue = jira.issue(epic_key)
    epic = JiraEpic(
        key=issue.key,
        summary=issue.fields.summary,
        description=getattr(issue.fields, "description", None),
    )
    parent = getattr(issue.fields, "parent", None)
    if parent:
        try:
            parent_issue = jira.issue(parent.key)
            epic.parent_key = parent_issue.key
            epic.parent_summary = parent_issue.fields.summary
            epic.parent_description = getattr(parent_issue.fields, "description", None)
        except Exception:
            pass
    return epic


def create_story(draft: JiraStoryDraft, settings: JiraAgentSettings) -> JiraStoryCreated:
    jira = _connect(settings)

    # Check if a story with the same summary already exists under the epic to be idempotent
    safe_project = draft.epic_key.split("-")[0].replace("\\", "\\\\").replace('"', '\\"')
    safe_title = draft.title.replace("\\", "\\\\").replace('"', '\\"')
    jql = f'project = "{safe_project}" AND summary ~ "{safe_title}" AND issuetype = Story'
    existing = jira.search_issues(jql, maxResults=1)
    if existing:
        issue = existing[0]
        return JiraStoryCreated(
            key=issue.key,
            summary=issue.fields.summary,
            url=f"{settings.jira_url}/browse/{issue.key}",
            epic_key=draft.epic_key,
        )

    description = draft.description
    if draft.acceptance_criteria:
        criteria_text = "\n".join(f"* {c}" for c in draft.acceptance_criteria)
        description = f"{description}\n\nh3. Acceptance Criteria\n{criteria_text}"

    project_key = draft.epic_key.split("-")[0]
    fields: dict = {
        "project": {"key": project_key},
        "summary": draft.title,
        "description": description,
        "issuetype": {"name": "Story"},
    }
    if draft.story_points is not None:
        fields["customfield_10016"] = draft.story_points

    issue = jira.create_issue(fields=fields)

    # Link to epic
    try:
        jira.create_issue_link("Epic-Story", issue.key, draft.epic_key)
    except Exception:
        # Fallback: set Epic Link custom field
        try:
            jira.update_issue_field(issue.key, {"customfield_10014": draft.epic_key})
        except Exception:
            pass

    return JiraStoryCreated(
        key=issue.key,
        summary=draft.title,
        url=f"{settings.jira_url}/browse/{issue.key}",
        epic_key=draft.epic_key,
    )


def post_comment(issue_key: str, body: str, settings: JiraAgentSettings) -> JiraCommentResult:
    jira = _connect(settings)
    comment = jira.add_comment(issue_key, body)
    return JiraCommentResult(
        comment_id=str(comment.id),
        body=comment.body,
        author=comment.author.displayName,
    )


def get_comments(issue_key: str, settings: JiraAgentSettings) -> list[JiraCommentResult]:
    jira = _connect(settings)
    comments = jira.comments(issue_key)
    return [
        JiraCommentResult(
            comment_id=str(c.id),
            body=c.body,
            author=c.author.displayName,
        )
        for c in comments
    ]


def update_story_status(key: str, transition_name: str, settings: JiraAgentSettings) -> None:
    jira = _connect(settings)
    transitions = jira.transitions(key)
    target = next((t for t in transitions if t["name"].lower() == transition_name.lower()), None)
    if target:
        jira.transition_issue(key, target["id"])


def set_story_points(key: str, points: int, settings: JiraAgentSettings) -> None:
    jira = _connect(settings)
    jira.update_issue_field(key, {"customfield_10016": points})


def set_dependency_link(
    from_key: str,
    to_key: str,
    link_type: str,
    settings: JiraAgentSettings,
) -> None:
    jira = _connect(settings)
    # Check if the link already exists
    issue = jira.issue(from_key, fields="issuelinks")
    for link in issue.fields.issuelinks:
        outward = getattr(link, "outwardIssue", None)
        inward = getattr(link, "inwardIssue", None)
        if (outward and outward.key == to_key) or (inward and inward.key == to_key):
            return
    jira.create_issue_link(link_type, from_key, to_key)


def close_story(key: str, resolution: str, settings: JiraAgentSettings) -> None:
    jira = _connect(settings)
    transitions = jira.transitions(key)
    done = next((t for t in transitions if "done" in t["name"].lower() or "close" in t["name"].lower()), None)
    if done:
        jira.transition_issue(key, done["id"], fields={"resolution": {"name": resolution}})
