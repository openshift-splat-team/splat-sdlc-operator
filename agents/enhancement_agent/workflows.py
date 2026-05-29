from __future__ import annotations

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from agents.common.models import (
        CreatedPR,
        EnhancementDoc,
        EnhancementPRInput,
        JiraEpic,
        OpenShiftFeaturePlan,
    )
    from agents.enhancement_agent.activities import (
        generate_enhancement_doc,
        poll_enhancement_pr_state,
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

        doc: EnhancementDoc = await workflow.execute_activity(
            generate_enhancement_doc,
            args=[epic, feature_plan, target_ocp_version],
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
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=_STANDARD_RETRY,
        )

        workflow.logger.info("Enhancement PR created: %s", created_pr.url)
        return created_pr


@workflow.defn
class WaitForEnhancementApprovalWorkflow:
    """Polls a PR until it is approved (>=1 approving review) or closed.

    Returns 'approved' or 'closed'.
    """

    @workflow.run
    async def run(self, repo_slug: str, pr_number: int) -> str:
        workflow.logger.info(
            "WaitForEnhancementApprovalWorkflow: watching %s#%d", repo_slug, pr_number
        )

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

            await asyncio.sleep(_POLL_INTERVAL.total_seconds())
