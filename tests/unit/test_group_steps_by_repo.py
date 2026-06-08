"""Unit tests for _group_steps_by_repo helper in ImplementFeatureWorkflow."""
from __future__ import annotations

import pytest

from agents.common.models import CIRequirements, OpenShiftFeaturePlan, PRStep
from agents.github_agent.workflows import _group_steps_by_repo


def _make_plan(steps: list[dict]) -> OpenShiftFeaturePlan:
    return OpenShiftFeaturePlan(
        summary="test feature",
        affected_tiers=["tier-0", "tier-1"],
        pr_sequence=[PRStep(**s) for s in steps],
        estimated_timeline="2 weeks",
        ci_requirements=CIRequirements(),
    )


def test_groups_steps_by_repo_basic():
    plan = _make_plan([
        {"step": 1, "repo": "org/repo-a", "tier": "tier-0", "description": "Add type", "risk": "low"},
        {"step": 2, "repo": "org/repo-b", "tier": "tier-1", "description": "Implement", "risk": "medium"},
        {"step": 3, "repo": "org/repo-a", "tier": "tier-0", "description": "Add test", "risk": "low",
         "blocked_by_step": 2},
    ])
    bundles = _group_steps_by_repo(plan)

    assert len(bundles) == 2
    by_repo = {b.repo: b for b in bundles}

    assert "org/repo-a" in by_repo
    assert "org/repo-b" in by_repo

    bundle_a = by_repo["org/repo-a"]
    assert len(bundle_a.steps) == 2
    assert bundle_a.steps[0].step == 1
    assert bundle_a.steps[1].step == 3

    bundle_b = by_repo["org/repo-b"]
    assert len(bundle_b.steps) == 1


def test_blocked_by_repos_derived_correctly():
    """repo-a step 3 is blocked by step 2 which belongs to repo-b → repo-a.blocked_by_repos = ['org/repo-b']."""
    plan = _make_plan([
        {"step": 1, "repo": "org/repo-a", "tier": "tier-0", "description": "Add type", "risk": "low"},
        {"step": 2, "repo": "org/repo-b", "tier": "tier-1", "description": "Implement", "risk": "low"},
        {"step": 3, "repo": "org/repo-a", "tier": "tier-0", "description": "Add test", "risk": "low",
         "blocked_by_step": 2},
    ])
    bundles = _group_steps_by_repo(plan)
    by_repo = {b.repo: b for b in bundles}

    assert "org/repo-b" in by_repo["org/repo-a"].blocked_by_repos
    assert by_repo["org/repo-b"].blocked_by_repos == []


def test_self_blocking_not_counted():
    """A step blocked by another step in the same repo should not appear in blocked_by_repos."""
    plan = _make_plan([
        {"step": 1, "repo": "org/repo-a", "tier": "tier-0", "description": "Step 1", "risk": "low"},
        {"step": 2, "repo": "org/repo-a", "tier": "tier-0", "description": "Step 2", "risk": "low",
         "blocked_by_step": 1},
    ])
    bundles = _group_steps_by_repo(plan)
    assert len(bundles) == 1
    assert bundles[0].blocked_by_repos == []


def test_risk_is_highest_across_steps():
    plan = _make_plan([
        {"step": 1, "repo": "org/repo-a", "tier": "tier-0", "description": "A", "risk": "low"},
        {"step": 2, "repo": "org/repo-a", "tier": "tier-0", "description": "B", "risk": "high"},
        {"step": 3, "repo": "org/repo-a", "tier": "tier-0", "description": "C", "risk": "medium"},
    ])
    bundles = _group_steps_by_repo(plan)
    assert bundles[0].risk == "high"


def test_ci_requirements_are_union():
    plan = _make_plan([
        {"step": 1, "repo": "org/repo-a", "tier": "tier-0", "description": "A", "risk": "low",
         "ci_requirements": ["job-unit", "job-e2e"]},
        {"step": 2, "repo": "org/repo-a", "tier": "tier-0", "description": "B", "risk": "low",
         "ci_requirements": ["job-e2e", "job-upgrade"]},
    ])
    bundles = _group_steps_by_repo(plan)
    assert set(bundles[0].ci_requirements) == {"job-unit", "job-e2e", "job-upgrade"}


def test_steps_sorted_by_step_number():
    plan = _make_plan([
        {"step": 3, "repo": "org/repo-a", "tier": "tier-0", "description": "C", "risk": "low"},
        {"step": 1, "repo": "org/repo-a", "tier": "tier-0", "description": "A", "risk": "low"},
        {"step": 2, "repo": "org/repo-a", "tier": "tier-0", "description": "B", "risk": "low"},
    ])
    bundles = _group_steps_by_repo(plan)
    assert [s.step for s in bundles[0].steps] == [1, 2, 3]


def test_single_repo_no_blockers():
    plan = _make_plan([
        {"step": 1, "repo": "org/solo", "tier": "tier-1", "description": "Only change", "risk": "medium"},
    ])
    bundles = _group_steps_by_repo(plan)
    assert len(bundles) == 1
    assert bundles[0].repo == "org/solo"
    assert bundles[0].blocked_by_repos == []
    assert bundles[0].tier == "tier-1"
