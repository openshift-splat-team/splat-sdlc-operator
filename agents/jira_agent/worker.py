"""Jira agent Temporal worker entrypoint."""
from __future__ import annotations

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from agents.common.settings import JiraAgentSettings
from agents.jira_agent.activities import (
    close_story_wont_do,
    create_approved_stories,
    create_design_doc_story,
    ensure_jira_epic,
    poll_epic_comments,
    post_story_proposals,
    set_story_dependencies,
    size_and_prioritize_stories,
    store_story_plan,
)
from agents.jira_agent.workflows import (
    CloseStoryWontDoWorkflow,
    CreateDesignDocStoryWorkflow,
    CreateStoriesWorkflow,
    EnsureEpicWorkflow,
    StoryRefinementWorkflow,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = JiraAgentSettings()
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
            EnsureEpicWorkflow,
            CreateDesignDocStoryWorkflow,
            StoryRefinementWorkflow,
            CreateStoriesWorkflow,
            CloseStoryWontDoWorkflow,
        ],
        activities=[
            ensure_jira_epic,
            create_design_doc_story,
            post_story_proposals,
            poll_epic_comments,
            create_approved_stories,
            size_and_prioritize_stories,
            set_story_dependencies,
            close_story_wont_do,
            store_story_plan,
        ],
    ):
        logger.info("Jira agent worker running")
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    asyncio.run(main())
