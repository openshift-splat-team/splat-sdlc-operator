"""OpenShift agent Temporal worker entrypoint."""
from __future__ import annotations

import asyncio
import logging
import os

from temporalio.client import Client
from temporalio.worker import Worker

from agents.common import llm_config
from agents.common.memory_activities import extract_observations, recall_agent_memories, save_memory_entry
from agents.common.settings import OpenShiftAgentSettings
from agents.openshift_agent.activities import (
    analyze_feature,
    determine_ci_requirements,
    fetch_repo_context,
    identify_affected_repos,
    store_feature_plan,
)
from agents.openshift_agent.workflows import OpenShiftFeatureWorkflow

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = OpenShiftAgentSettings()
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
        workflows=[OpenShiftFeatureWorkflow],
        activities=[
            identify_affected_repos,
            analyze_feature,
            determine_ci_requirements,
            fetch_repo_context,
            store_feature_plan,
            save_memory_entry, recall_agent_memories, extract_observations,
        ],
    ):
        logger.info("OpenShift agent worker running")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
