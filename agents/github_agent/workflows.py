from __future__ import annotations

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from agents.common.models import (
        CodeGenerationResult,
        CreatePRInput,
        CreatedPR,
        FeatureImplementationResult,
        OpenShiftFeaturePlan,
        PRStep,
        RepoPRBundle,
        ReviewResult,
        StagingPlan,
        StagingRepo,
    )
    from agents.github_agent.activities import (
        apply_file_changes,
        create_feature_branch,
        create_pr,
        create_staging_pr,
        fetch_pr,
        fetch_repo_context,
        fork_repository,
        generate_code_for_bundle,
        mirror_repository,
        poll_pr_for_label_drop,
        post_comments,
        post_pr_comment,
        process_pr_comments,
        remove_agent_hold,
        reset_agent_hold_label,
        run_review,
        store_created_pr,
        store_implementation_result,
        store_review,
        update_pr_description,
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
        repos_to_fork: list[str],
        staging_org: str,
        feature_id: str,
        feature_branch: str,
    ) -> StagingPlan:
        unique_repos = list(dict.fromkeys(repos_to_fork))
        workflow.logger.info(
            "SetupStagingReposWorkflow: setting up %d repos", len(unique_repos)
        )

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

        # Create feature branches concurrently — skip repos that fail (e.g. still syncing)
        ready_repos: list[StagingRepo] = []
        for sr in staging_repos:
            try:
                sr = await workflow.execute_activity(
                    create_feature_branch,
                    args=[sr, feature_branch],
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=_STANDARD_RETRY,
                )
                ready_repos.append(sr)
            except Exception:
                slug = f"{sr.source_org}/{sr.source_repo}"
                workflow.logger.warning("Skipping %s — branch creation failed (repo may still be syncing)", slug)

        workflow.logger.info(
            "SetupStagingReposWorkflow: %d/%d repos ready for PRs",
            len(ready_repos), len(staging_repos),
        )

        # Create draft PRs with agent-hold (sequential to avoid rate limits)
        for i, sr in enumerate(ready_repos):
            title = f"feat: {feature_id} changes for {sr.source_repo}"
            body = f"This PR implements changes for feature {feature_id}.\n"
            ready_repos[i] = await workflow.execute_activity(
                create_staging_pr,
                args=[sr, feature_id, title, body],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_STANDARD_RETRY,
            )

        return StagingPlan(feature_id=feature_id, repos=ready_repos)


@workflow.defn
class MirrorReposWorkflow:
    """Mirrors GitHub repos into Gitea. Returns only the repos that succeeded."""

    @workflow.run
    async def run(self, repo_slugs: list[str]) -> list[str]:
        workflow.logger.info("MirrorReposWorkflow: mirroring %d repos", len(repo_slugs))
        results: list[bool] = list(await asyncio.gather(*[
            workflow.execute_activity(
                mirror_repository,
                args=[slug],
                start_to_close_timeout=timedelta(seconds=120),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=5),
                    backoff_coefficient=2.0,
                    maximum_attempts=2,
                ),
            )
            for slug in repo_slugs
        ]))
        mirrored = [slug for slug, ok in zip(repo_slugs, results) if ok]
        dropped = [slug for slug, ok in zip(repo_slugs, results) if not ok]
        if dropped:
            workflow.logger.warning("MirrorReposWorkflow: dropped %d repos that failed to mirror: %s", len(dropped), dropped)
        workflow.logger.info("MirrorReposWorkflow: %d/%d repos mirrored", len(mirrored), len(repo_slugs))
        return mirrored


@workflow.defn
class ForkReposWorkflow:
    """Forks a list of repo slugs into a staging org concurrently."""

    @workflow.run
    async def run(self, repo_slugs: list[str], staging_org: str) -> list[StagingRepo]:
        workflow.logger.info(
            "ForkReposWorkflow: forking %d repos into %s",
            len(repo_slugs), staging_org,
        )
        staging_repos: list[StagingRepo] = list(
            await asyncio.gather(*[
                workflow.execute_activity(
                    fork_repository,
                    args=[slug, staging_org],
                    start_to_close_timeout=timedelta(seconds=60),
                    retry_policy=_STANDARD_RETRY,
                )
                for slug in repo_slugs
            ])
        )
        workflow.logger.info("ForkReposWorkflow: forked %d repos", len(staging_repos))
        return staging_repos


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
                result = await workflow.execute_activity(
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
                workflow.logger.info(
                    "Comment processing complete: %d file changes", len(result.file_changes)
                )

                if result.file_changes:
                    await workflow.execute_activity(
                        apply_file_changes,
                        args=[staging_repo, result.file_changes],
                        start_to_close_timeout=timedelta(minutes=5),
                        retry_policy=_STANDARD_RETRY,
                    )

                await workflow.execute_activity(
                    post_pr_comment,
                    args=[staging_repo, result.response_body],
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=_STANDARD_RETRY,
                )

                await workflow.execute_activity(
                    reset_agent_hold_label,
                    staging_repo,
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=_STANDARD_RETRY,
                )

            await asyncio.sleep(_POLL_INTERVAL.total_seconds())


# ── Code generation helpers ───────────────────────────────────────────────────

_RISK_ORDER = {"low": 0, "medium": 1, "high": 2}


def _group_steps_by_repo(plan: "OpenShiftFeaturePlan") -> "list[RepoPRBundle]":
    """Group all PRSteps by repo, deriving risk, CI requirements, and cross-repo blockers."""
    from collections import defaultdict  # noqa: PLC0415

    step_to_repo: dict[int, str] = {s.step: s.repo for s in plan.pr_sequence}

    groups: dict[str, list[PRStep]] = defaultdict(list)
    for step in plan.pr_sequence:
        groups[step.repo].append(step)

    bundles: list[RepoPRBundle] = []
    for repo, steps in groups.items():
        blocked_by_repos: list[str] = []
        for step in steps:
            if step.blocked_by_step is not None:
                blocking_repo = step_to_repo.get(step.blocked_by_step)
                if blocking_repo and blocking_repo != repo and blocking_repo not in blocked_by_repos:
                    blocked_by_repos.append(blocking_repo)

        max_risk = max(steps, key=lambda s: _RISK_ORDER[s.risk]).risk

        seen_reqs: set[str] = set()
        ci_requirements: list[str] = []
        for step in steps:
            for req in step.ci_requirements:
                if req not in seen_reqs:
                    ci_requirements.append(req)
                    seen_reqs.add(req)

        bundles.append(RepoPRBundle(
            repo=repo,
            tier=steps[0].tier,
            steps=sorted(steps, key=lambda s: s.step),
            risk=max_risk,
            ci_requirements=ci_requirements,
            blocked_by_repos=blocked_by_repos,
        ))

    return bundles


# ── CodeGenerationWorkflow ────────────────────────────────────────────────────

@workflow.defn
class CodeGenerationWorkflow:
    """Generates and commits all code changes for a single repo, then updates the PR."""

    @workflow.run
    async def run(
        self,
        staging_repo: "StagingRepo",
        bundle: "RepoPRBundle",
        feature_description: str,
    ) -> "CodeGenerationResult":
        source_slug = f"{staging_repo.source_org}/{staging_repo.source_repo}"
        workflow.logger.info("CodeGenerationWorkflow: generating code for %s", source_slug)

        repo_context = await workflow.execute_activity(
            fetch_repo_context,
            args=[staging_repo.source_org, staging_repo.source_repo, "main"],
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=_STANDARD_RETRY,
        )

        file_changes = await workflow.execute_activity(
            generate_code_for_bundle,
            args=[bundle, feature_description, repo_context],
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=_LLM_RETRY,
        )

        if file_changes:
            await workflow.execute_activity(
                apply_file_changes,
                args=[staging_repo, file_changes],
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=_STANDARD_RETRY,
            )

        result = CodeGenerationResult(
            repo=bundle.repo,
            files_changed=[fc.path for fc in file_changes],
            commit_messages=[fc.commit_message for fc in file_changes],
        )

        await workflow.execute_activity(
            update_pr_description,
            args=[staging_repo, result],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_STANDARD_RETRY,
        )

        await workflow.execute_activity(
            remove_agent_hold,
            staging_repo,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_STANDARD_RETRY,
        )

        workflow.logger.info(
            "CodeGenerationWorkflow: done for %s; %d files changed",
            source_slug, len(file_changes),
        )
        return result


# ── ImplementFeatureWorkflow ──────────────────────────────────────────────────

@workflow.defn
class ImplementFeatureWorkflow:
    """Orchestrates code generation across all repos for a feature, one PR per repo."""

    @workflow.run
    async def run(
        self,
        staging_plan: "StagingPlan",
        feature_plan: "OpenShiftFeaturePlan",
        feature_description: str,
        run_id: str,
    ) -> "FeatureImplementationResult":
        workflow.logger.info(
            "ImplementFeatureWorkflow: %s across %d repos",
            staging_plan.feature_id, len(staging_plan.repos),
        )

        bundles = _group_steps_by_repo(feature_plan)

        staging_by_repo: dict[str, StagingRepo] = {
            f"{sr.source_org}/{sr.source_repo}": sr
            for sr in staging_plan.repos
        }

        completed_repos: set[str] = set()
        all_results: list[CodeGenerationResult] = []

        while len(completed_repos) < len(bundles):
            ready = [
                b for b in bundles
                if b.repo not in completed_repos
                and b.repo in staging_by_repo
                and all(dep in completed_repos for dep in b.blocked_by_repos)
            ]

            if not ready:
                # Skip bundles with no staging repo (not in staging plan)
                unblocked_missing = [
                    b for b in bundles
                    if b.repo not in completed_repos and b.repo not in staging_by_repo
                ]
                completed_repos.update(b.repo for b in unblocked_missing)
                if len(completed_repos) >= len(bundles):
                    break
                raise workflow.NondeterminismError(
                    "Deadlock: no ready bundle and all remaining repos have blockers"
                )

            wave_tasks = [
                workflow.execute_child_workflow(
                    CodeGenerationWorkflow.run,
                    args=[staging_by_repo[b.repo], b, feature_description],
                    id=f"{workflow.info().workflow_id}-codegen-{b.repo.replace('/', '-')}",
                    task_queue="github-agent",
                    execution_timeout=timedelta(hours=1),
                )
                for b in ready
            ]
            wave_results: list[CodeGenerationResult] = list(await asyncio.gather(*wave_tasks))
            all_results.extend(wave_results)
            completed_repos.update(b.repo for b in ready)

        result = FeatureImplementationResult(
            feature_id=staging_plan.feature_id,
            results=all_results,
        )
        artifact_ref = await workflow.execute_activity(
            store_implementation_result,
            args=[result, run_id],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_STANDARD_RETRY,
        )
        result.artifact_ref = artifact_ref

        workflow.logger.info(
            "ImplementFeatureWorkflow complete: %d repos implemented", len(all_results)
        )
        return result
