"""Requirements agent Temporal worker entrypoint."""
from __future__ import annotations

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from agents.common.settings import RequirementsAgentSettings
from agents.requirements_agent.activities import (
    fetch_jira_epic,
    produce_spec,
    propose_stories,
    refine_stories,
    store_spec,
)
from agents.requirements_agent.workflows import RequirementsWorkflow

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = RequirementsAgentSettings()
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
        workflows=[RequirementsWorkflow],
        activities=[fetch_jira_epic, produce_spec, store_spec, propose_stories, refine_stories],
    ):
        logger.info("Requirements agent worker running")
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    asyncio.run(main())
