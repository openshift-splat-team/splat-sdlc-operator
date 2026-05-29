from __future__ import annotations

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from agents.common.models import (
        JiraEpic,
        JiraStoryCreated,
        SDLCFeatureInput,
        StoryPlan,
    )
    from agents.jira_agent.activities import (
        close_story_wont_do,
        create_approved_stories,
        create_design_doc_story,
        ensure_jira_epic,
        poll_epic_comments,
        post_story_proposals,
        set_story_dependencies,
        size_and_prioritize_stories,
        store_story_plan,
    )

_STANDARD_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_attempts=3,
    non_retryable_error_types=["ValueError"],
)

_POLL_INTERVAL = timedelta(minutes=5)
_STORIES_APPROVED_MARKER = "stories approved"


@workflow.defn
class EnsureEpicWorkflow:
    @workflow.run
    async def run(self, feature_input: SDLCFeatureInput) -> JiraEpic:
        workflow.logger.info("EnsureEpicWorkflow: ensuring epic exists")
        return await workflow.execute_activity(
            ensure_jira_epic,
            feature_input,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=_STANDARD_RETRY,
        )


@workflow.defn
class CreateDesignDocStoryWorkflow:
    @workflow.run
    async def run(self, epic_key: str, pr_url: str) -> JiraStoryCreated:
        workflow.logger.info("Creating design doc story for epic %s", epic_key)
        return await workflow.execute_activity(
            create_design_doc_story,
            args=[epic_key, pr_url],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_STANDARD_RETRY,
        )


@workflow.defn
class StoryRefinementWorkflow:
    """Posts story proposals to the Jira epic and waits for 'stories approved' comment.

    On each poll cycle, if new comments arrive without approval, calls the
    requirements_agent refine_stories activity to update the plan.
    Returns the final approved StoryPlan.
    """

    @workflow.run
    async def run(self, epic_key: str, initial_plan: StoryPlan, run_id: str) -> StoryPlan:
        workflow.logger.info("StoryRefinementWorkflow started for epic %s", epic_key)

        await workflow.execute_activity(
            post_story_proposals,
            args=[epic_key, initial_plan],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_STANDARD_RETRY,
        )

        seen_comment_ids: set[str] = set()
        current_plan = initial_plan

        while True:
            comments = await workflow.execute_activity(
                poll_epic_comments,
                epic_key,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_STANDARD_RETRY,
            )

            new_comments = [c for c in comments if c.comment_id not in seen_comment_ids]
            for c in new_comments:
                seen_comment_ids.add(c.comment_id)

            # Check for approval marker
            approved = any(
                _STORIES_APPROVED_MARKER in c.body.lower()
                for c in comments
            )
            if approved:
                workflow.logger.info("Stories approved for epic %s", epic_key)
                break

            # Refine based on new human feedback (delegated to requirements_agent)
            if new_comments:
                feedback_texts = [c.body for c in new_comments]
                workflow.logger.info(
                    "%d new comments on epic %s — refining story plan", len(new_comments), epic_key
                )
                # Import refine_stories from requirements_agent at runtime
                from agents.requirements_agent.activities import refine_stories  # noqa: PLC0415

                current_plan = await workflow.execute_activity(
                    refine_stories,
                    args=[current_plan, feedback_texts],
                    start_to_close_timeout=timedelta(minutes=10),
                    retry_policy=RetryPolicy(
                        initial_interval=timedelta(seconds=5),
                        backoff_coefficient=2.0,
                        maximum_attempts=5,
                        non_retryable_error_types=["ValueError"],
                    ),
                    task_queue="requirements-agent",
                )
                # Re-post updated proposals
                await workflow.execute_activity(
                    post_story_proposals,
                    args=[epic_key, current_plan],
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=_STANDARD_RETRY,
                )

            await asyncio.sleep(_POLL_INTERVAL.total_seconds())

        artifact_ref = await workflow.execute_activity(
            store_story_plan,
            args=[current_plan, run_id],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_STANDARD_RETRY,
        )
        current_plan.artifact_ref = artifact_ref
        return current_plan


@workflow.defn
class CreateStoriesWorkflow:
    @workflow.run
    async def run(self, epic_key: str, story_plan: StoryPlan) -> list[JiraStoryCreated]:
        workflow.logger.info("Creating %d stories for epic %s", len(story_plan.stories), epic_key)

        created = await workflow.execute_activity(
            create_approved_stories,
            args=[epic_key, story_plan],
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=_STANDARD_RETRY,
        )

        await workflow.execute_activity(
            size_and_prioritize_stories,
            args=[created, story_plan],
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=_STANDARD_RETRY,
        )

        await workflow.execute_activity(
            set_story_dependencies,
            args=[created, story_plan],
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=_STANDARD_RETRY,
        )

        return created


@workflow.defn
class CloseStoryWontDoWorkflow:
    @workflow.run
    async def run(self, story_key: str) -> None:
        await workflow.execute_activity(
            close_story_wont_do,
            story_key,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_STANDARD_RETRY,
        )
