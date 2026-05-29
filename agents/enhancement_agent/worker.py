"""Enhancement agent Temporal worker entrypoint."""
from __future__ import annotations

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from agents.common.settings import EnhancementAgentSettings
from agents.enhancement_agent.activities import (
    generate_enhancement_doc,
    poll_enhancement_pr_state,
    store_enhancement_doc,
    submit_enhancement_pr,
)
from agents.enhancement_agent.workflows import (
    EnhancementWorkflow,
    WaitForEnhancementApprovalWorkflow,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = EnhancementAgentSettings()
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
        workflows=[
            EnhancementWorkflow,
            WaitForEnhancementApprovalWorkflow,
        ],
        activities=[
            generate_enhancement_doc,
            poll_enhancement_pr_state,
            store_enhancement_doc,
            submit_enhancement_pr,
        ],
    ):
        logger.info("Enhancement agent worker running")
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    asyncio.run(main())
