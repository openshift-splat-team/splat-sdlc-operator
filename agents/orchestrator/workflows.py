from __future__ import annotations

import re
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from agents.common.models import (
        EnhancementApprovalInput,
        EnhancementPRInput,
        EnhancementReviewInput,
        FeatureImplementationResult,
        ImplementFeatureInput,
        JiraEpic,
        OpenShiftFeatureInput,
        SDLCFeatureInput,
        StagingPlan,
        WorkflowResult,
        WorkflowTrigger,
    )
    from agents.enhancement_agent.workflows import (
        EnhancementWorkflow,
        WaitForEnhancementApprovalWorkflow,
    )
    from agents.github_agent.workflows import (
        CreatePRWorkflow,
        ForkReposWorkflow,
        ImplementFeatureWorkflow,
        MonitorPRWorkflow,
        ReviewWorkflow,
        SetupStagingReposWorkflow,
    )
    from agents.jira_agent.workflows import (
        CloseStoryWontDoWorkflow,
        CreateDesignDocStoryWorkflow,
        CreateStoriesWorkflow,
        EnsureEpicWorkflow,
        StoryRefinementWorkflow,
    )
    from agents.openshift_agent.workflows import OpenShiftFeatureWorkflow
    from agents.requirements_agent.workflows import RequirementsWorkflow


@workflow.defn
class SDLCOrchestratorWorkflow:
    @workflow.run
    async def run(self, trigger: WorkflowTrigger) -> WorkflowResult:
        workflow.logger.info(
            "Orchestrator received task_type=%s run_id=%s", trigger.task_type, trigger.run_id
        )

        if trigger.task_type == "requirements":
            if not trigger.jira_epic_id:
                raise ValueError("jira_epic_id required for requirements task")

            artifact_ref = await workflow.execute_child_workflow(
                RequirementsWorkflow.run,
                args=[trigger.jira_epic_id, trigger.run_id],
                id=f"{trigger.run_id}-requirements",
                task_queue="requirements-agent",
                execution_timeout=timedelta(minutes=10),
            )
            return WorkflowResult(
                run_id=trigger.run_id,
                task_type="requirements",
                status="completed",
                artifact_ref=artifact_ref,
            )

        elif trigger.task_type == "review":
            if not trigger.github_pr_url:
                raise ValueError("github_pr_url required for review task")

            artifact_ref = await workflow.execute_child_workflow(
                ReviewWorkflow.run,
                args=[trigger.github_pr_url, trigger.run_id],
                id=f"{trigger.run_id}-review",
                task_queue="github-agent",
                execution_timeout=timedelta(minutes=10),
            )
            return WorkflowResult(
                run_id=trigger.run_id,
                task_type="review",
                status="completed",
                artifact_ref=artifact_ref,
            )

        elif trigger.task_type == "create_pr":
            if not trigger.github_create_pr:
                raise ValueError("github_create_pr required for create_pr task")

            artifact_ref = await workflow.execute_child_workflow(
                CreatePRWorkflow.run,
                args=[trigger.github_create_pr, trigger.run_id],
                id=f"{trigger.run_id}-create-pr",
                task_queue="github-agent",
                execution_timeout=timedelta(minutes=5),
            )
            return WorkflowResult(
                run_id=trigger.run_id,
                task_type="create_pr",
                status="completed",
                artifact_ref=artifact_ref,
            )

        elif trigger.task_type == "openshift_feature":
            if not trigger.openshift_feature:
                raise ValueError("openshift_feature required for openshift_feature task")

            artifact_ref = await workflow.execute_child_workflow(
                OpenShiftFeatureWorkflow.run,
                args=[trigger.openshift_feature, trigger.run_id],
                id=f"{trigger.run_id}-openshift-feature",
                task_queue="openshift-agent",
                execution_timeout=timedelta(minutes=15),
            )
            return WorkflowResult(
                run_id=trigger.run_id,
                task_type="openshift_feature",
                status="completed",
                artifact_ref=artifact_ref,
            )

        elif trigger.task_type == "full_sdlc":
            if not trigger.full_sdlc:
                raise ValueError("full_sdlc required for full_sdlc task")

            staging_plan = await workflow.execute_child_workflow(
                FullSDLCWorkflow.run,
                args=[trigger.full_sdlc, trigger.run_id],
                id=f"{trigger.run_id}-full-sdlc",
                task_queue="orchestrator",
                execution_timeout=timedelta(days=95),
            )
            return WorkflowResult(
                run_id=trigger.run_id,
                task_type="full_sdlc",
                status="completed",
                artifact_ref=staging_plan.artifact_ref,
            )

        elif trigger.task_type == "implement_feature":
            if not trigger.implement_feature:
                raise ValueError("implement_feature required for implement_feature task")

            from agents.orchestrator.activities import load_feature_plan, load_staging_plan  # noqa: PLC0415

            inp: ImplementFeatureInput = trigger.implement_feature
            staging_plan = await workflow.execute_activity(
                load_staging_plan,
                inp.staging_plan_ref,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(initial_interval=timedelta(seconds=2), backoff_coefficient=2.0, maximum_attempts=3),
            )
            feature_plan = await workflow.execute_activity(
                load_feature_plan,
                inp.feature_plan_ref,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(initial_interval=timedelta(seconds=2), backoff_coefficient=2.0, maximum_attempts=3),
            )
            impl_result: FeatureImplementationResult = await workflow.execute_child_workflow(
                ImplementFeatureWorkflow.run,
                args=[staging_plan, feature_plan, inp.feature_description, trigger.run_id],
                id=f"{trigger.run_id}-implement-feature",
                task_queue="github-agent",
                execution_timeout=timedelta(hours=4),
            )
            return WorkflowResult(
                run_id=trigger.run_id,
                task_type="implement_feature",
                status="completed",
                artifact_ref=impl_result.artifact_ref,
            )

        elif trigger.task_type == "enhancement_review":
            if not trigger.enhancement_review:
                raise ValueError("enhancement_review required for enhancement_review task")

            from agents.orchestrator.activities import load_enhancement_doc, load_feature_plan  # noqa: PLC0415

            inp_er: EnhancementReviewInput = trigger.enhancement_review
            feature_branch = _feature_branch_name(trigger.run_id)

            feature_plan = await workflow.execute_activity(
                load_feature_plan,
                f"runs/{inp_er.source_run_id}/openshift-feature-plan.json",
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(initial_interval=timedelta(seconds=2), backoff_coefficient=2.0, maximum_attempts=3),
            )

            epic: JiraEpic = await workflow.execute_child_workflow(
                EnsureEpicWorkflow.run,
                SDLCFeatureInput(
                    jira_epic_id=inp_er.jira_epic_id,
                    feature_description=inp_er.feature_description,
                    target_ocp_version=inp_er.target_ocp_version,
                    staging_github_org=inp_er.staging_github_org,
                    enhancement_repo=inp_er.enhancement_repo,
                ),
                id=f"{trigger.run_id}-ensure-epic",
                task_queue="jira-agent",
                execution_timeout=timedelta(minutes=10),
            )

            pr_input = EnhancementPRInput(
                repo=inp_er.enhancement_repo,
                base_branch="main",
                jira_epic_key=epic.key,
            )

            enhancement_pr = await workflow.execute_child_workflow(
                EnhancementWorkflow.run,
                args=[epic, feature_plan, pr_input, feature_branch, inp_er.target_ocp_version, trigger.run_id],
                id=f"{trigger.run_id}-enhancement",
                task_queue="enhancement-agent",
                execution_timeout=timedelta(minutes=15),
            )
            workflow.logger.info("Enhancement PR: %s", enhancement_pr.url)

            url_parts = enhancement_pr.url.rstrip("/").split("/")
            enhancement_repo_slug = f"{url_parts[-4]}/{url_parts[-3]}"
            enhancement_pr_number = int(url_parts[-1])

            enhancement_doc = await workflow.execute_activity(
                load_enhancement_doc,
                f"runs/{trigger.run_id}/enhancement-doc.json",
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(initial_interval=timedelta(seconds=2), backoff_coefficient=2.0, maximum_attempts=3),
            )
            enhancement_fork_slug = f"{inp_er.staging_github_org}/{inp_er.enhancement_repo.split('/')[-1]}"
            _enh_title = re.sub(r"^\[.*?\]\s*", "", enhancement_pr.title)
            enhancement_feature_slug = re.sub(r"[^a-z0-9]+", "-", _enh_title.lower()).strip("-")[:80]

            approval_input = EnhancementApprovalInput(
                repo_slug=enhancement_repo_slug,
                pr_number=enhancement_pr_number,
                fork_slug=enhancement_fork_slug,
                feature_branch=feature_branch,
                feature_slug=enhancement_feature_slug,
                run_id=trigger.run_id,
                enhancement_doc=enhancement_doc,
                epic=epic,
                feature_plan=feature_plan,
            )

            approval_result: str = await workflow.execute_child_workflow(
                WaitForEnhancementApprovalWorkflow.run,
                args=[approval_input],
                id=f"{trigger.run_id}-wait-enhancement",
                task_queue="enhancement-agent",
                execution_timeout=timedelta(days=30),
            )

            return WorkflowResult(
                run_id=trigger.run_id,
                task_type="enhancement_review",
                status="completed",
                artifact_ref=f"runs/{trigger.run_id}/enhancement-doc.json",
            )

        else:
            workflow.logger.warning("Unknown task_type=%s — skipping", trigger.task_type)
            return WorkflowResult(
                run_id=trigger.run_id,
                task_type=trigger.task_type,
                status="skipped",
            )


def _feature_branch_name(run_id: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", run_id.lower()).strip("-")[:40]
    return f"feat/{slug}"


@workflow.defn
class FullSDLCWorkflow:
    """End-to-end OpenShift feature SDLC workflow with human approval gates."""

    @workflow.run
    async def run(self, feature_input: SDLCFeatureInput, run_id: str) -> StagingPlan:
        workflow.logger.info("FullSDLCWorkflow starting run_id=%s", run_id)
        feature_branch = _feature_branch_name(run_id)

        # Phase A — Ensure Jira epic exists
        epic: JiraEpic = await workflow.execute_child_workflow(
            EnsureEpicWorkflow.run,
            feature_input,
            id=f"{run_id}-ensure-epic",
            task_queue="jira-agent",
            execution_timeout=timedelta(minutes=10),
        )
        workflow.logger.info("Epic: %s", epic.key)

        # Phase B — Generate enhancement doc and open PR (before feature plan)
        pr_input = EnhancementPRInput(
            repo=feature_input.enhancement_repo,
            base_branch="main",
            jira_epic_key=epic.key,
        )

        enhancement_pr = await workflow.execute_child_workflow(
            EnhancementWorkflow.run,
            args=[epic, pr_input, feature_branch, feature_input.target_ocp_version, run_id],
            id=f"{run_id}-enhancement",
            task_queue="enhancement-agent",
            execution_timeout=timedelta(minutes=15),
        )
        workflow.logger.info("Enhancement PR: %s", enhancement_pr.url)

        design_story = await workflow.execute_child_workflow(
            CreateDesignDocStoryWorkflow.run,
            args=[epic.key, enhancement_pr.url],
            id=f"{run_id}-design-story",
            task_queue="jira-agent",
            execution_timeout=timedelta(seconds=60),
        )

        # Phase C — Wait for enhancement PR approval (or closure)
        url_parts = enhancement_pr.url.rstrip("/").split("/")
        enhancement_repo_slug = f"{url_parts[-4]}/{url_parts[-3]}"
        enhancement_pr_number = int(url_parts[-1])

        from agents.orchestrator.activities import load_enhancement_doc  # noqa: PLC0415

        enhancement_doc_for_approval = await workflow.execute_activity(
            load_enhancement_doc,
            f"runs/{run_id}/enhancement-doc.json",
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=2),
                backoff_coefficient=2.0,
                maximum_attempts=3,
            ),
        )
        enhancement_fork_slug = f"{feature_input.staging_github_org}/{feature_input.enhancement_repo.split('/')[-1]}"
        _enh_title = re.sub(r"^\[.*?\]\s*", "", enhancement_pr.title)
        enhancement_feature_slug = re.sub(r"[^a-z0-9]+", "-", _enh_title.lower()).strip("-")[:80]

        approval_input = EnhancementApprovalInput(
            repo_slug=enhancement_repo_slug,
            pr_number=enhancement_pr_number,
            fork_slug=enhancement_fork_slug,
            feature_branch=feature_branch,
            feature_slug=enhancement_feature_slug,
            run_id=run_id,
            enhancement_doc=enhancement_doc_for_approval,
            epic=epic,
            feature_plan=OpenShiftFeaturePlan(summary="", affected_tiers=[], pr_sequence=[], estimated_timeline=""),
        )

        approval_result: str = await workflow.execute_child_workflow(
            WaitForEnhancementApprovalWorkflow.run,
            args=[approval_input],
            id=f"{run_id}-wait-enhancement",
            task_queue="enhancement-agent",
            execution_timeout=timedelta(days=30),
        )

        if approval_result == "closed":
            workflow.logger.info("Enhancement PR closed; closing design story and exiting")
            await workflow.execute_child_workflow(
                CloseStoryWontDoWorkflow.run,
                design_story.key,
                id=f"{run_id}-close-story",
                task_queue="jira-agent",
                execution_timeout=timedelta(seconds=30),
            )
            return StagingPlan(feature_id=run_id, repos=[])

        workflow.logger.info("Enhancement PR approved; loading approved repos")

        # Phase D — Load approved enhancement doc, fork its repos
        enhancement_doc = await workflow.execute_activity(
            load_enhancement_doc,
            f"runs/{run_id}/enhancement-doc.json",
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=2),
                backoff_coefficient=2.0,
                maximum_attempts=3,
            ),
        )
        repos_to_fork = enhancement_doc.repos_to_fork
        if repos_to_fork:
            await workflow.execute_child_workflow(
                ForkReposWorkflow.run,
                args=[repos_to_fork, feature_input.staging_github_org],
                id=f"{run_id}-fork-repos",
                task_queue="github-agent",
                execution_timeout=timedelta(minutes=10),
            )
        workflow.logger.info(
            "Phase D: forked %d repos from enhancement doc into %s",
            len(repos_to_fork), feature_input.staging_github_org,
        )

        # Phase E — Analyze feature scoped to the approved repos
        openshift_input = OpenShiftFeatureInput(
            feature_description=feature_input.feature_description,
            target_ocp_version=feature_input.target_ocp_version,
            jira_epic_id=epic.key,
            jira_context={
                "epic_id": epic.key,
                "title": epic.summary,
                "stories": [
                    {"title": s.summary, "description": s.description or ""}
                    for s in epic.stories
                ],
            },
            repos=repos_to_fork,
        )
        feature_plan_ref: str = await workflow.execute_child_workflow(
            OpenShiftFeatureWorkflow.run,
            args=[openshift_input, run_id],
            id=f"{run_id}-openshift-feature",
            task_queue="openshift-agent",
            execution_timeout=timedelta(minutes=15),
        )
        workflow.logger.info("Feature plan artifact: %s", feature_plan_ref)

        from agents.orchestrator.activities import load_feature_plan  # noqa: PLC0415

        feature_plan = await workflow.execute_activity(
            load_feature_plan,
            feature_plan_ref,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=2),
                backoff_coefficient=2.0,
                maximum_attempts=3,
            ),
        )

        # Phase F — Story proposal and human refinement loop
        from agents.requirements_agent.activities import propose_stories  # noqa: PLC0415
        from agents.common.models import RequirementSpec, Story  # noqa: PLC0415

        minimal_spec = RequirementSpec(
            epic_id=epic.key,
            title=epic.summary,
            stories=[Story(title=epic.summary, description=epic.description or "", acceptance_criteria=[])],
            acceptance_criteria=[],
        )

        story_plan = await workflow.execute_activity(
            propose_stories,
            args=[minimal_spec, feature_plan],
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=5),
                backoff_coefficient=2.0,
                maximum_attempts=5,
                non_retryable_error_types=["ValueError"],
            ),
            task_queue="requirements-agent",
        )

        final_story_plan = await workflow.execute_child_workflow(
            StoryRefinementWorkflow.run,
            args=[epic.key, story_plan, run_id],
            id=f"{run_id}-story-refinement",
            task_queue="jira-agent",
            execution_timeout=timedelta(days=14),
        )

        # Phase G — Create, size, prioritize, link stories
        await workflow.execute_child_workflow(
            CreateStoriesWorkflow.run,
            args=[epic.key, final_story_plan],
            id=f"{run_id}-create-stories",
            task_queue="jira-agent",
            execution_timeout=timedelta(minutes=5),
        )

        # Phase H — Create feature branches and staging PRs for forked repos
        staging_plan: StagingPlan = await workflow.execute_child_workflow(
            SetupStagingReposWorkflow.run,
            args=[repos_to_fork, feature_input.staging_github_org, run_id, feature_branch],
            id=f"{run_id}-setup-staging",
            task_queue="github-agent",
            execution_timeout=timedelta(minutes=10),
        )

        # Phase I — Generate and commit code changes (one PR per repo)
        await workflow.execute_child_workflow(
            ImplementFeatureWorkflow.run,
            args=[staging_plan, feature_plan, feature_input.feature_description, run_id],
            id=f"{run_id}-implement-feature",
            task_queue="github-agent",
            execution_timeout=timedelta(hours=4),
        )
        workflow.logger.info("Phase I: code generation complete for %d repos", len(staging_plan.repos))

        # Phase J — Start long-lived PR monitors (fire-and-forget, watches for human comments)
        for staging_repo in staging_plan.repos:
            repo_slug = f"{staging_repo.source_org}/{staging_repo.source_repo}"
            await workflow.start_child_workflow(
                MonitorPRWorkflow.run,
                staging_repo,
                id=f"{run_id}-monitor-{repo_slug.replace('/', '-')}",
                task_queue="github-agent",
                execution_timeout=timedelta(days=90),
            )

        workflow.logger.info(
            "FullSDLCWorkflow complete; %d staging repos, monitors started", len(staging_plan.repos)
        )
        return staging_plan
