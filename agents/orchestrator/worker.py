"""Orchestrator Temporal worker entrypoint."""
from __future__ import annotations

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from agents.common.settings import OrchestratorSettings
from agents.orchestrator.activities import load_feature_plan
from agents.orchestrator.workflows import FullSDLCWorkflow, SDLCOrchestratorWorkflow

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = OrchestratorSettings()
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
        workflows=[SDLCOrchestratorWorkflow, FullSDLCWorkflow],
        activities=[load_feature_plan],
    ):
        logger.info("Orchestrator worker running")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
