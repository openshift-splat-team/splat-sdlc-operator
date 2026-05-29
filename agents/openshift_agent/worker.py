"""OpenShift agent Temporal worker entrypoint."""
from __future__ import annotations

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

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
        ],
    ):
        logger.info("OpenShift agent worker running")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
