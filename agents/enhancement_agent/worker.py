"""Enhancement agent Temporal worker entrypoint."""
from __future__ import annotations

import asyncio
import logging
import os

from temporalio.client import Client
from temporalio.worker import Worker

from agents.common import llm_config
from agents.common.memory_activities import extract_observations, recall_agent_memories, save_memory_entry
from agents.common.settings import EnhancementAgentSettings
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
from agents.enhancement_agent.workflows import (
    EnhancementWorkflow,
    WaitForEnhancementApprovalWorkflow,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = EnhancementAgentSettings()
    if config_path := os.environ.get("LLM_CONFIG_PATH"):
        llm_config.load(config_path)
        logger.info("Loaded LLM config from %s", config_path)
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
            commit_revised_enhancement_doc,
            fetch_enhancement_pr_comments,
            generate_enhancement_doc,
            poll_enhancement_pr_state,
            post_enhancement_pr_comment,
            process_enhancement_comments,
            store_enhancement_doc,
            submit_enhancement_pr,
            save_memory_entry, recall_agent_memories, extract_observations,
        ],
    ):
        logger.info("Enhancement agent worker running")
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    asyncio.run(main())
