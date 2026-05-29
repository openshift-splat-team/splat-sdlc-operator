from agents.common.models import (
    InlineComment,
    JiraEpic,
    JiraStory,
    PRData,
    PRFile,
    RequirementSpec,
    ReviewResult,
    Story,
    WorkflowTrigger,
)


def test_workflow_trigger_requirements():
    t = WorkflowTrigger(task_type="requirements", jira_epic_id="PROJ-1", run_id="run-abc")
    assert t.task_type == "requirements"
    assert t.github_pr_url is None


def test_workflow_trigger_review():
    t = WorkflowTrigger(task_type="review", github_pr_url="https://github.com/o/r/pull/1", run_id="run-xyz")
    assert t.jira_epic_id is None


def test_requirement_spec_roundtrip():
    spec = RequirementSpec(
        epic_id="PROJ-1",
        title="User Auth",
        stories=[Story(title="Login", description="...", acceptance_criteria=["AC1"])],
        acceptance_criteria=["System must authenticate users"],
        artifact_ref="runs/run-abc/spec.json",
    )
    restored = RequirementSpec.model_validate_json(spec.model_dump_json())
    assert restored.epic_id == spec.epic_id
    assert len(restored.stories) == 1


def test_review_result_defaults():
    r = ReviewResult(pr_url="https://github.com/o/r/pull/1", summary="LGTM")
    assert r.approved is False
    assert r.inline_comments == []


def test_inline_comment_severity_default():
    c = InlineComment(path="src/main.py", line=10, body="Fix this")
    assert c.severity == "info"


def test_jira_epic_with_stories():
    epic = JiraEpic(
        key="PROJ-1",
        summary="Epic title",
        stories=[JiraStory(key="PROJ-2", summary="Story", status="In Progress")],
    )
    assert epic.stories[0].key == "PROJ-2"
