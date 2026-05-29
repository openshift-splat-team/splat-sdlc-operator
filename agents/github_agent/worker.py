"""GitHub agent Temporal worker entrypoint."""
from __future__ import annotations

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from agents.common.settings import GitHubAgentSettings
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
from agents.github_agent.workflows import (
    CreatePRWorkflow,
    MonitorPRWorkflow,
    ReviewWorkflow,
    SetupStagingReposWorkflow,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = GitHubAgentSettings()
    logger.info(
        "Connecting to Temporal at %s, task queue=%s",
        settings.temporal_host,
        settings.temporal_task_queue,
    )

    client = await Client.connect(
        settings.temporal_host,
        namespace=settings.temporal_namespace,
    )

    async with Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[ReviewWorkflow, CreatePRWorkflow, SetupStagingReposWorkflow, MonitorPRWorkflow],
        activities=[
            fetch_pr, run_review, post_comments, store_review, create_pr, store_created_pr,
            fork_repository, create_feature_branch, create_staging_pr,
            poll_pr_for_label_drop, process_pr_comments, reset_agent_hold_label,
        ],
    ):
        logger.info("GitHub agent worker running")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
