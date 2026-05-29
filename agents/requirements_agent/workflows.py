from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from agents.common.models import RequirementSpec
    from agents.requirements_agent.activities import (
        fetch_jira_epic,
        produce_spec,
        store_spec,
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
class RequirementsWorkflow:
    @workflow.run
    async def run(self, epic_key: str, run_id: str) -> str:
        workflow.logger.info("RequirementsWorkflow starting for epic %s", epic_key)

        epic = await workflow.execute_activity(
            fetch_jira_epic,
            epic_key,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_STANDARD_RETRY,
        )

        spec = await workflow.execute_activity(
            produce_spec,
            epic,
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=_LLM_RETRY,
        )

        artifact_ref = await workflow.execute_activity(
            store_spec,
            args=[spec, run_id],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_STANDARD_RETRY,
        )

        workflow.logger.info("RequirementsWorkflow complete; artifact_ref=%s", artifact_ref)
        return artifact_ref
