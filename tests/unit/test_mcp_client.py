"""Tests for the openshift-dep-tree MCP client wrapper."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agents.openshift_agent.mcp_client import DepTreeClient, _normalize_repo, _parse_result


def _make_result(data: dict, *, is_error: bool = False):
    """Build a fake CallToolResult-like object."""
    block = SimpleNamespace(text=json.dumps(data))
    return SimpleNamespace(content=[block], isError=is_error)


class TestNormalizeRepo:
    def test_strips_openshift_prefix(self):
        assert _normalize_repo("openshift/cluster-etcd-operator") == "cluster-etcd-operator"

    def test_strips_operator_framework_prefix(self):
        assert _normalize_repo("operator-framework/operator-sdk") == "operator-sdk"

    def test_no_prefix_unchanged(self):
        assert _normalize_repo("cluster-etcd-operator") == "cluster-etcd-operator"


class TestParseResult:
    def test_parses_json(self):
        result = _make_result({"count": 5, "items": [1, 2, 3]})
        parsed = _parse_result(result)
        assert parsed == {"count": 5, "items": [1, 2, 3]}

    def test_error_raises(self):
        result = _make_result({"error": "not found"}, is_error=True)
        with pytest.raises(RuntimeError, match="MCP tool error"):
            _parse_result(result)

    def test_no_text_raises(self):
        result = SimpleNamespace(content=[], isError=False)
        with pytest.raises(RuntimeError, match="no text content"):
            _parse_result(result)


class TestDepTreeClient:
    @pytest.fixture
    def session(self):
        return AsyncMock()

    @pytest.fixture
    def client(self, session):
        return DepTreeClient(session)

    async def test_feature_impact(self, client, session):
        session.call_tool.return_value = _make_result({
            "query": {"feature": "etcd encryption"},
            "result_count": 2,
            "results": [
                {"repo": "cluster-etcd-operator", "score": 80.0},
                {"repo": "api", "score": 45.0},
            ],
        })

        result = await client.feature_impact("etcd encryption")

        session.call_tool.assert_called_once_with(
            "feature_impact_tool",
            {"feature": "etcd encryption", "platform": "", "classification": "", "top": 30, "min_score": 10.0},
        )
        assert result["result_count"] == 2
        assert result["results"][0]["repo"] == "cluster-etcd-operator"

    async def test_get_repo_info_strips_prefix(self, client, session):
        session.call_tool.return_value = _make_result({"repo": "installer", "metadata": {}})

        await client.get_repo_info("openshift/installer")

        session.call_tool.assert_called_once_with(
            "get_repo_info",
            {"repo": "installer"},
        )

    async def test_get_repo_dependencies(self, client, session):
        session.call_tool.return_value = _make_result({
            "repo": "cluster-etcd-operator",
            "depends_on": ["openshift/api", "openshift/library-go"],
            "depended_on_by": [],
        })

        result = await client.get_repo_dependencies("cluster-etcd-operator")

        assert result["depends_on"] == ["openshift/api", "openshift/library-go"]

    async def test_search_repos(self, client, session):
        session.call_tool.return_value = _make_result({
            "query": "etcd",
            "count": 1,
            "matches": [{"repo": "cluster-etcd-operator", "matched_in": ["name"]}],
        })

        result = await client.search_repos("etcd")

        assert result["count"] == 1

    async def test_get_repo_api_usage(self, client, session):
        session.call_tool.return_value = _make_result({
            "repo": "cluster-etcd-operator",
            "packages": ["operator/v1"],
            "kinds": ["Etcd"],
        })

        result = await client.get_repo_api_usage("openshift/cluster-etcd-operator")

        session.call_tool.assert_called_once_with(
            "get_repo_api_usage",
            {"repo": "cluster-etcd-operator"},
        )
        assert result["kinds"] == ["Etcd"]


class TestPromptRendering:
    """Verify the updated prompts render with the new template variables."""

    def test_identify_repos_renders_scored_repos(self):
        from agents.common.prompts import render

        scored_repos = [
            {
                "repo": "cluster-etcd-operator",
                "score": 80.0,
                "description": "Manages etcd",
                "summary": "Etcd operator",
                "platforms": ["aws", "gcp"],
                "classifications": ["etcd"],
                "depends_on": ["openshift/api"],
                "depended_on_by": [],
                "api_packages": ["operator/v1"],
                "api_kinds": ["Etcd"],
            },
        ]

        messages = render(
            "openshift_agent/identify_repos.md",
            scored_repos=scored_repos,
            change_description="Add etcd encryption at rest",
        )

        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert "cluster-etcd-operator" in messages[0]["content"]
        assert "score: 80.0" in messages[0]["content"]
        assert "etcd encryption" in messages[1]["content"]

    def test_analyze_feature_renders_deps(self):
        from agents.common.prompts import render

        affected_repos = [
            {"name": "openshift/api", "tier": "Tier 0", "change_type": "new_types", "reason": "New CRD", "required": True},
        ]
        repo_dependencies = {
            "openshift/api": {
                "depends_on": [],
                "depended_on_by": ["openshift/library-go", "openshift/installer"],
                "module": "github.com/openshift/api",
            },
        }

        messages = render(
            "openshift_agent/analyze_feature.md",
            affected_repos=affected_repos,
            repo_dependencies=repo_dependencies,
            feature_description="Add new CRD for widget management",
            target_ocp_version="4.17",
            jira_context=None,
        )

        assert len(messages) == 2
        assert "openshift/api" in messages[0]["content"]
        assert "openshift/library-go" in messages[0]["content"]
        assert "widget management" in messages[1]["content"]

    def test_ci_requirements_renders_metadata(self):
        from agents.common.prompts import render
        from agents.common.models import AffectedRepo

        affected_repos = [
            AffectedRepo(name="openshift/api", tier="Tier 0", reason="New types", change_type="new_types"),
        ]
        repo_metadata = {
            "openshift/api": {
                "repo": "api",
                "metadata": {
                    "platforms": ["aws", "gcp", "azure"],
                    "classifications": ["api"],
                },
                "api_usage": None,
                "dependencies": {"depends_on": []},
            },
        }

        messages = render(
            "openshift_agent/ci_requirements.md",
            affected_repos=affected_repos,
            repo_metadata=repo_metadata,
            feature_description="Add new API types",
        )

        assert len(messages) == 2
        assert "openshift/api" in messages[0]["content"]
        assert "New types" in messages[1]["content"]
