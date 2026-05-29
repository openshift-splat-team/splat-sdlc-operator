import pytest
from agents.common.prompts import render
from agents.common.models import JiraStory


def test_produce_spec_renders_system_and_user():
    story = JiraStory(key="PROJ-2", summary="Login page", status="To Do")
    messages = render(
        "requirements_agent/produce_spec.md",
        epic_key="PROJ-1",
        epic_summary="User authentication",
        epic_description="Allow users to log in",
        stories=[story],
    )
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "PROJ-1" in messages[1]["content"]
    assert "PROJ-2" in messages[1]["content"]
    assert "Login page" in messages[1]["content"]


def test_produce_spec_omits_description_block_when_none():
    messages = render(
        "requirements_agent/produce_spec.md",
        epic_key="PROJ-1",
        epic_summary="No description epic",
        epic_description=None,
        stories=[],
    )
    assert "### Description" not in messages[1]["content"]


def test_run_review_renders_system_and_user():
    messages = render(
        "github_agent/run_review.md",
        pr_title="Add login endpoint",
        pr_body="Implements POST /auth/login",
        head_branch="feature/login",
        base_branch="main",
        diff="--- a/auth.py\n+++ b/auth.py\n@@ -1 +1 @@\n+def login(): pass",
    )
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "Add login endpoint" in messages[1]["content"]
    assert "feature/login" in messages[1]["content"]


def test_run_review_omits_description_when_none():
    messages = render(
        "github_agent/run_review.md",
        pr_title="Fix bug",
        pr_body=None,
        head_branch="fix/bug",
        base_branch="main",
        diff="-old\n+new",
    )
    assert "### Description" not in messages[1]["content"]


def test_missing_variable_raises():
    with pytest.raises(Exception):
        render("requirements_agent/produce_spec.md")  # missing all variables
