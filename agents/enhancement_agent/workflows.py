from __future__ import annotations

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from agents.common.models import (
        CreatedPR,
        EnhancementApprovalInput,
        EnhancementDoc,
        EnhancementPRInput,
        JiraEpic,
        OpenShiftFeaturePlan,
    )
    from agents.common.memory import format_memories_for_prompt
    from agents.common.memory_activities import extract_observations, recall_agent_memories
    from agents.enhancement_agent.activities import (
        commit_revised_enhancement_doc,
        fetch_enhancement_pr_comments,
        generate_enhancement_doc,
        poll_enhancement_pr_state,
        post_enhancement_pr_comment,
        process_enhancement_comments,
        store_enhancement_doc,
        submit_enhancement_pr,
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

_POLL_INTERVAL = timedelta(minutes=5)


@workflow.defn
class EnhancementWorkflow:
    """Generates an OpenShift enhancement doc and opens a PR in the enhancements repo."""

    @workflow.run
    async def run(
        self,
        epic: JiraEpic,
        feature_plan: OpenShiftFeaturePlan,
        pr_input: EnhancementPRInput,
        feature_branch: str,
        target_ocp_version: str | None,
        run_id: str,
    ) -> CreatedPR:
        workflow.logger.info("EnhancementWorkflow starting for epic %s", epic.key)

        past_memories = await workflow.execute_activity(
            recall_agent_memories,
            args=["enhancement-agent"],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_STANDARD_RETRY,
        )
        memories_context = format_memories_for_prompt(past_memories)

        doc: EnhancementDoc = await workflow.execute_activity(
            generate_enhancement_doc,
            args=[epic, feature_plan, target_ocp_version, memories_context],
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=_LLM_RETRY,
        )

        await workflow.execute_activity(
            store_enhancement_doc,
            args=[doc, run_id],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_STANDARD_RETRY,
        )

        created_pr: CreatedPR = await workflow.execute_activity(
            submit_enhancement_pr,
            args=[doc, pr_input, feature_branch],
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=_STANDARD_RETRY,
        )

        workflow.logger.info("Enhancement PR created: %s", created_pr.url)

        try:
            await workflow.execute_activity(
                extract_observations,
                args=[
                    "enhancement-agent",
                    run_id,
                    f"Generated enhancement doc '{doc.title}' for epic {epic.key} and opened PR {created_pr.url}.",
                ],
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        except Exception:
            workflow.logger.warning("Memory reflection failed; continuing")

        return created_pr


@workflow.defn
class WaitForEnhancementApprovalWorkflow:
    """Polls a PR until it is approved or closed, revising the enhancement doc
    in response to reviewer comments while waiting.

    Returns 'approved' or 'closed'.
    """

    @workflow.run
    async def run(self, input: EnhancementApprovalInput) -> str:
        repo_slug = input.repo_slug
        pr_number = input.pr_number
        workflow.logger.info(
            "WaitForEnhancementApprovalWorkflow: watching %s#%d", repo_slug, pr_number
        )

        current_doc = input.enhancement_doc
        last_seen_comment_count = 0

        while True:
            state = await workflow.execute_activity(
                poll_enhancement_pr_state,
                args=[repo_slug, pr_number],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_STANDARD_RETRY,
            )

            if state.get("merged"):
                workflow.logger.info("Enhancement PR %s#%d merged", repo_slug, pr_number)
                return "approved"

            if state.get("approved_review_count", 0) >= 1:
                workflow.logger.info("Enhancement PR %s#%d approved", repo_slug, pr_number)
                return "approved"

            if state.get("state") == "closed":
                workflow.logger.info("Enhancement PR %s#%d closed without merge", repo_slug, pr_number)
                return "closed"

            new_comments: list[dict] = await workflow.execute_activity(
                fetch_enhancement_pr_comments,
                args=[repo_slug, pr_number, last_seen_comment_count],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_STANDARD_RETRY,
            )

            if new_comments:
                workflow.logger.info(
                    "Detected %d new comments on %s#%d; revising doc",
                    len(new_comments), repo_slug, pr_number,
                )

                result = await workflow.execute_activity(
                    process_enhancement_comments,
                    args=[current_doc, new_comments, input.epic, input.feature_plan],
                    start_to_close_timeout=timedelta(minutes=10),
                    retry_policy=_LLM_RETRY,
                )

                await workflow.execute_activity(
                    commit_revised_enhancement_doc,
                    args=[input.fork_slug, input.feature_branch, result.revised_doc, input.feature_slug],
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=_STANDARD_RETRY,
                )

                await workflow.execute_activity(
                    post_enhancement_pr_comment,
                    args=[repo_slug, pr_number, result.response_body],
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=_STANDARD_RETRY,
                )

                current_doc = result.revised_doc
                last_seen_comment_count += len(new_comments)

                workflow.logger.info(
                    "Enhancement doc revised and committed; comment count now %d",
                    last_seen_comment_count,
                )

            await asyncio.sleep(_POLL_INTERVAL.total_seconds())
