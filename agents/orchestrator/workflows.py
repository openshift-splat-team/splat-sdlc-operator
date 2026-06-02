from __future__ import annotations

import re
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from agents.common.models import (
        EnhancementPRInput,
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

        # Phase B — Analyze feature and identify affected repos
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
        )
        feature_plan_ref: str = await workflow.execute_child_workflow(
            OpenShiftFeatureWorkflow.run,
            args=[openshift_input, run_id],
            id=f"{run_id}-openshift-feature",
            task_queue="openshift-agent",
            execution_timeout=timedelta(minutes=15),
        )
        # Load feature plan artifact — passed by ref; decode inline via activity is simplest
        # For now pass openshift_input details forward; full plan loaded in Phase C
        workflow.logger.info("Feature plan artifact: %s", feature_plan_ref)

        # Phase C — Generate and submit enhancement PR
        # We need the full OpenShiftFeaturePlan; fetch from storage via a lightweight activity
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

        pr_input = EnhancementPRInput(
            repo=feature_input.enhancement_repo,
            base_branch="main",
            jira_epic_key=epic.key,
        )

        enhancement_pr = await workflow.execute_child_workflow(
            EnhancementWorkflow.run,
            args=[epic, feature_plan, pr_input, feature_branch, feature_input.target_ocp_version, run_id],
            id=f"{run_id}-enhancement",
            task_queue="enhancement-agent",
            execution_timeout=timedelta(minutes=15),
        )
        workflow.logger.info("Enhancement PR: %s", enhancement_pr.url)

        # Create design doc review story
        design_story = await workflow.execute_child_workflow(
            CreateDesignDocStoryWorkflow.run,
            args=[epic.key, enhancement_pr.url],
            id=f"{run_id}-design-story",
            task_queue="jira-agent",
            execution_timeout=timedelta(seconds=60),
        )

        # Phase D — Wait for enhancement PR approval (or closure)
        # Extract repo slug and PR number from URL
        url_parts = enhancement_pr.url.rstrip("/").split("/")
        enhancement_repo_slug = f"{url_parts[-4]}/{url_parts[-3]}"
        enhancement_pr_number = int(url_parts[-1])

        approval_result: str = await workflow.execute_child_workflow(
            WaitForEnhancementApprovalWorkflow.run,
            args=[enhancement_repo_slug, enhancement_pr_number],
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

        workflow.logger.info("Enhancement PR approved; proceeding to story planning")

        # Phase E — Story proposal and human refinement loop
        from agents.requirements_agent.activities import propose_stories  # noqa: PLC0415

        # Load requirement spec artifact via a helper (spec was stored in Phase B of requirements flow)
        # For now, build a minimal spec from the epic for story proposal
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

        # Phase F — Create, size, prioritize, link stories
        await workflow.execute_child_workflow(
            CreateStoriesWorkflow.run,
            args=[epic.key, final_story_plan],
            id=f"{run_id}-create-stories",
            task_queue="jira-agent",
            execution_timeout=timedelta(minutes=5),
        )

        # Phase G — Fork repos and create staging PRs
        staging_plan: StagingPlan = await workflow.execute_child_workflow(
            SetupStagingReposWorkflow.run,
            args=[feature_plan, feature_input.staging_github_org, run_id, feature_branch],
            id=f"{run_id}-setup-staging",
            task_queue="github-agent",
            execution_timeout=timedelta(minutes=10),
        )

        # Phase H — Start long-lived PR monitors (fire-and-forget)
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
