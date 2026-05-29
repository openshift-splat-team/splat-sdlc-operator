from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from agents.common.models import OpenShiftFeatureInput, OpenShiftFeaturePlan
    from agents.openshift_agent.activities import (
        analyze_feature,
        determine_ci_requirements,
        fetch_repo_context,
        identify_affected_repos,
        store_feature_plan,
    )

_STANDARD_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_attempts=3,
    non_retryable_error_types=["ValueError"],
)

_LLM_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=2.0,
    maximum_attempts=5,
    non_retryable_error_types=["ValueError"],
)


@workflow.defn
class OpenShiftFeatureWorkflow:
    @workflow.run
    async def run(self, input: OpenShiftFeatureInput, run_id: str) -> str:
        workflow.logger.info(
            "OpenShiftFeatureWorkflow starting: %s", input.feature_description[:80]
        )

        # Step 1 — identify which repos are affected
        repo_result = await workflow.execute_activity(
            identify_affected_repos,
            input,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=_LLM_RETRY,
        )
        workflow.logger.info(
            "Identified %d affected repos; primary=%s",
            len(repo_result.repos),
            repo_result.primary_repo,
        )

        # Step 2 — fetch live GitHub context for the primary repo and key affected repos
        # (run concurrently for the top 3 repos to stay within rate limits)
        top_repos = [repo_result.primary_repo] + [
            r.name.removeprefix("openshift/")
            for r in repo_result.repos
            if r.required and r.name != repo_result.primary_repo
        ][:2]

        repo_contexts = []
        for repo_name in top_repos:
            ctx = await workflow.execute_activity(
                fetch_repo_context,
                repo_name,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_STANDARD_RETRY,
            )
            repo_contexts.append(ctx)

        # Step 3 — fetch Jira context if an epic ID was provided
        jira_context = None
        if input.jira_epic_id:
            # Jira fetch is handled by the requirements agent; here we pass through
            # whatever context is already on the input as a plain dict
            jira_context = {"epic_id": input.jira_epic_id}

        # Step 4 — full feature analysis: ordered PR sequence + timeline + risks
        plan = await workflow.execute_activity(
            analyze_feature,
            args=[input, repo_result, jira_context],
            start_to_close_timeout=timedelta(seconds=180),
            retry_policy=_LLM_RETRY,
        )

        # Step 5 — determine CI requirements
        ci = await workflow.execute_activity(
            determine_ci_requirements,
            args=[input, repo_result.repos],
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=_LLM_RETRY,
        )
        plan.ci_requirements = ci

        # Step 6 — store
        artifact_ref = await workflow.execute_activity(
            store_feature_plan,
            args=[plan, run_id],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_STANDARD_RETRY,
        )

        workflow.logger.info("OpenShiftFeatureWorkflow complete; artifact_ref=%s", artifact_ref)
        return artifact_ref
