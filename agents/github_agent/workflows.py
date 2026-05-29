from __future__ import annotations

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from agents.common.models import (
        CreatePRInput,
        CreatedPR,
        OpenShiftFeaturePlan,
        ReviewResult,
        StagingPlan,
        StagingRepo,
    )
    from agents.github_agent.activities import (
        create_feature_branch,
        create_pr,
        create_staging_pr,
        fetch_pr,
        fork_repository,
        poll_pr_for_label_drop,
        post_comments,
        process_pr_comments,
        reset_agent_hold_label,
        run_review,
        store_created_pr,
        store_review,
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
class ReviewWorkflow:
    @workflow.run
    async def run(self, pr_url: str, run_id: str) -> str:
        workflow.logger.info("ReviewWorkflow starting for PR %s", pr_url)

        pr_data = await workflow.execute_activity(
            fetch_pr, pr_url,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_STANDARD_RETRY,
        )
        review = await workflow.execute_activity(
            run_review, pr_data,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=_LLM_RETRY,
        )
        await workflow.execute_activity(
            post_comments, review,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_STANDARD_RETRY,
        )
        artifact_ref = await workflow.execute_activity(
            store_review, args=[review, run_id],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_STANDARD_RETRY,
        )

        workflow.logger.info("ReviewWorkflow complete; artifact_ref=%s", artifact_ref)
        return artifact_ref


@workflow.defn
class CreatePRWorkflow:
    @workflow.run
    async def run(self, input: CreatePRInput, run_id: str) -> str:
        workflow.logger.info(
            "CreatePRWorkflow starting: %s %s→%s",
            input.repo, input.head_branch, input.base_branch,
        )

        created = await workflow.execute_activity(
            create_pr, input,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_STANDARD_RETRY,
        )
        artifact_ref = await workflow.execute_activity(
            store_created_pr, args=[created, run_id],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_STANDARD_RETRY,
        )

        workflow.logger.info(
            "CreatePRWorkflow complete; PR #%d at %s", created.number, created.url
        )
        return artifact_ref


_POLL_INTERVAL = timedelta(minutes=5)


@workflow.defn
class SetupStagingReposWorkflow:
    """Forks all affected repos, creates feature branches, and opens draft PRs with agent-hold."""

    @workflow.run
    async def run(
        self,
        feature_plan: OpenShiftFeaturePlan,
        staging_org: str,
        feature_id: str,
        feature_branch: str,
    ) -> StagingPlan:
        workflow.logger.info(
            "SetupStagingReposWorkflow: setting up %d repos", len(feature_plan.pr_sequence)
        )

        # Deduplicate repos from the PR sequence
        seen: set[str] = set()
        unique_repos: list[str] = []
        for step in feature_plan.pr_sequence:
            if step.repo not in seen:
                seen.add(step.repo)
                unique_repos.append(step.repo)

        # Fork all repos concurrently
        fork_tasks = [
            workflow.execute_activity(
                fork_repository,
                args=[repo, staging_org],
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=_STANDARD_RETRY,
            )
            for repo in unique_repos
        ]
        staging_repos: list[StagingRepo] = list(await asyncio.gather(*fork_tasks))

        # Create feature branches concurrently
        branch_tasks = [
            workflow.execute_activity(
                create_feature_branch,
                args=[sr, feature_branch],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_STANDARD_RETRY,
            )
            for sr in staging_repos
        ]
        staging_repos = list(await asyncio.gather(*branch_tasks))

        # Create draft PRs with agent-hold (sequential to avoid rate limits)
        for i, sr in enumerate(staging_repos):
            repo_slug = f"{sr.source_org}/{sr.source_repo}"
            title = f"feat: {feature_id} changes for {sr.source_repo}"
            body = (
                f"This PR implements changes for feature {feature_id}.\n\n"
                f"**CI Requirements:**\n"
                + "\n".join(
                    f"- {job.job_name} ({job.job_type})"
                    for job in feature_plan.ci_requirements.required_jobs
                    if job.repo == repo_slug
                )
            )
            staging_repos[i] = await workflow.execute_activity(
                create_staging_pr,
                args=[sr, feature_id, title, body],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_STANDARD_RETRY,
            )

        return StagingPlan(feature_id=feature_id, repos=staging_repos)


@workflow.defn
class MonitorPRWorkflow:
    """Long-running per-repo workflow; processes PR comments when agent-hold is dropped."""

    @workflow.run
    async def run(self, staging_repo: StagingRepo) -> None:
        source_slug = f"{staging_repo.source_org}/{staging_repo.source_repo}"
        workflow.logger.info(
            "MonitorPRWorkflow: watching %s#%d", source_slug, staging_repo.pr_number
        )

        while True:
            event = await workflow.execute_activity(
                poll_pr_for_label_drop,
                staging_repo,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_STANDARD_RETRY,
            )

            if event.event_type == "closed":
                workflow.logger.info("PR %s#%d closed; monitor exiting", source_slug, staging_repo.pr_number)
                return

            if event.event_type == "label_dropped" and event.new_comments:
                workflow.logger.info(
                    "agent-hold dropped on %s#%d; processing %d comments",
                    source_slug, staging_repo.pr_number, len(event.new_comments),
                )
                response = await workflow.execute_activity(
                    process_pr_comments,
                    args=[staging_repo, event.new_comments],
                    start_to_close_timeout=timedelta(minutes=10),
                    retry_policy=RetryPolicy(
                        initial_interval=timedelta(seconds=5),
                        backoff_coefficient=2.0,
                        maximum_attempts=5,
                        non_retryable_error_types=["ValueError"],
                    ),
                )
                workflow.logger.info("Comment response generated (%d chars)", len(response))

                await workflow.execute_activity(
                    reset_agent_hold_label,
                    staging_repo,
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=_STANDARD_RETRY,
                )

            await asyncio.sleep(_POLL_INTERVAL.total_seconds())
