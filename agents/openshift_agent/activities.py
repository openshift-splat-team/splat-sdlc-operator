from __future__ import annotations

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
from agents.openshift_agent import mcp_client, repo_client


@activity.defn
async def identify_affected_repos(input: OpenShiftFeatureInput) -> RepoIdentificationResult:
    settings = OpenShiftAgentSettings()
    activity.logger.info("Identifying affected repos for: %s", input.feature_description[:80])

    async with mcp_client.connect(settings) as client:
        impact = await client.feature_impact(input.feature_description)

    scored_repos = impact.get("results", [])
    activity.logger.info("MCP returned %d scored candidates", len(scored_repos))

    if not scored_repos:
        activity.logger.warning("feature_impact_tool returned 0 candidates")
        return RepoIdentificationResult(
            repos=[], primary_repo="", api_change_required=False, mco_involved=False,
        )

    mcp_repo_names = {r["repo"] for r in scored_repos}

    messages = prompts.render(
        "openshift_agent/identify_repos.md",
        scored_repos=scored_repos,
        change_description=input.feature_description,
    )
    result = await llm.complete_structured(messages, settings, RepoIdentificationResult)

    unknown = [r.name for r in result.repos if mcp_client._normalize_repo(r.name) not in mcp_repo_names]
    if unknown:
        activity.logger.warning("Dropping repos not in MCP dataset: %s", unknown)
    result.repos = [r for r in result.repos if mcp_client._normalize_repo(r.name) in mcp_repo_names]
    return result


@activity.defn
async def analyze_feature(
    input: OpenShiftFeatureInput,
    repo_result: RepoIdentificationResult,
    jira_context: dict | None,
) -> OpenShiftFeaturePlan:
    settings = OpenShiftAgentSettings()
    activity.logger.info("Analyzing feature plan for: %s", input.feature_description[:80])

    repo_dependencies: dict[str, dict] = {}
    async with mcp_client.connect(settings) as client:
        for repo in repo_result.repos:
            try:
                deps = await client.get_repo_dependencies(repo.name)
                repo_dependencies[repo.name] = deps
            except Exception:
                activity.logger.warning("Failed to fetch deps for %s", repo.name)
                repo_dependencies[repo.name] = {}

    affected_repos = [r.model_dump() for r in repo_result.repos]

    messages = prompts.render(
        "openshift_agent/analyze_feature.md",
        affected_repos=affected_repos,
        repo_dependencies=repo_dependencies,
        feature_description=input.feature_description,
        target_ocp_version=input.target_ocp_version,
        jira_context=jira_context,
    )
    plan = await llm.complete_structured(messages, settings, OpenShiftFeaturePlan)

    known_repos = {r.name for r in repo_result.repos}
    unknown = [step.repo for step in plan.pr_sequence if step.repo not in known_repos]
    if unknown:
        activity.logger.warning("Dropping pr_sequence steps with unknown repos: %s", unknown)
    plan.pr_sequence = [step for step in plan.pr_sequence if step.repo in known_repos]
    return plan


@activity.defn
async def determine_ci_requirements(
    input: OpenShiftFeatureInput,
    affected_repos: list[AffectedRepo],
) -> CIRequirements:
    settings = OpenShiftAgentSettings()
    activity.logger.info("Determining CI requirements for %d repos", len(affected_repos))

    repo_metadata: dict[str, dict] = {}
    async with mcp_client.connect(settings) as client:
        for repo in affected_repos:
            try:
                info = await client.get_repo_info(repo.name)
                repo_metadata[repo.name] = info
            except Exception:
                activity.logger.warning("Failed to fetch metadata for %s", repo.name)
                repo_metadata[repo.name] = {}

    messages = prompts.render(
        "openshift_agent/ci_requirements.md",
        affected_repos=affected_repos,
        repo_metadata=repo_metadata,
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
    activity.logger.info("Storing feature plan to S3 key %s", key)
    return storage.put_artifact(key, plan, settings)
