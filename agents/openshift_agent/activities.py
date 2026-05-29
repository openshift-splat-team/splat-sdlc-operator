from __future__ import annotations

from pathlib import Path

from temporalio import activity

from agents.common import llm, prompts, storage
from agents.common.models import (
    AffectedRepo,
    CIRequirements,
    OpenShiftFeatureInput,
    OpenShiftFeaturePlan,
    RepoIdentificationResult,
)
from agents.common.settings import OpenShiftAgentSettings
from agents.openshift_agent import repo_client

# Load the dependency map once at import time — it's a static knowledge file.
_DEPENDENCY_MAP = (
    Path(__file__).parents[2] / "prompts" / "openshift_agent" / "knowledge" / "dependency_map.md"
).read_text()


@activity.defn
async def identify_affected_repos(input: OpenShiftFeatureInput) -> RepoIdentificationResult:
    settings = OpenShiftAgentSettings()
    activity.logger.info("Identifying affected repos for: %s", input.feature_description[:80])

    messages = prompts.render(
        "openshift_agent/identify_repos.md",
        dependency_map=_DEPENDENCY_MAP,
        change_description=input.feature_description,
    )
    return await llm.complete_structured(messages, settings, RepoIdentificationResult)


@activity.defn
async def analyze_feature(
    input: OpenShiftFeatureInput,
    repo_result: RepoIdentificationResult,
    jira_context: dict | None,
) -> OpenShiftFeaturePlan:
    settings = OpenShiftAgentSettings()
    activity.logger.info("Analyzing feature plan for: %s", input.feature_description[:80])

    messages = prompts.render(
        "openshift_agent/analyze_feature.md",
        dependency_map=_DEPENDENCY_MAP,
        feature_description=input.feature_description,
        target_ocp_version=input.target_ocp_version,
        jira_context=jira_context,
    )
    return await llm.complete_structured(messages, settings, OpenShiftFeaturePlan)


@activity.defn
async def determine_ci_requirements(
    input: OpenShiftFeatureInput,
    affected_repos: list[AffectedRepo],
) -> CIRequirements:
    settings = OpenShiftAgentSettings()
    activity.logger.info("Determining CI requirements for %d repos", len(affected_repos))

    messages = prompts.render(
        "openshift_agent/ci_requirements.md",
        dependency_map=_DEPENDENCY_MAP,
        affected_repos=affected_repos,
        feature_description=input.feature_description,
    )
    return await llm.complete_structured(messages, settings, CIRequirements)


@activity.defn
async def fetch_repo_context(repo_name: str) -> dict:
    """Fetch live repo metadata from GitHub to supplement static knowledge."""
    settings = OpenShiftAgentSettings()
    activity.logger.info("Fetching live context for openshift/%s", repo_name)

    go_mod = repo_client.get_go_mod(repo_name, settings)
    open_prs = repo_client.get_open_prs(repo_name, settings, limit=10)

    return {
        "repo": repo_name,
        "has_go_mod": go_mod is not None,
        "open_pr_count": len(open_prs),
        "recent_prs": open_prs[:5],
    }


@activity.defn
async def store_feature_plan(plan: OpenShiftFeaturePlan, run_id: str) -> str:
    settings = OpenShiftAgentSettings()
    key = f"runs/{run_id}/openshift-feature-plan.json"
    activity.logger.info("Storing feature plan to MinIO key %s", key)
    return storage.put_artifact(key, plan, settings)
